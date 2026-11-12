"""Regenerate a map using a locally supplied, calibrated PowerPoint reference.

The reference owns geography, markers, leader routes, grouping and typography.
The input owns project text. This is deliberately separate from geographic
auto-layout: changing a location or the project set requires a new calibration.
No private reference artwork is bundled with this repository.
"""
from __future__ import annotations

from copy import deepcopy
from difflib import SequenceMatcher
import hashlib
import json
import posixpath
from pathlib import Path
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

from lxml import etree as ET

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
}
LOCATION_FIELDS = ("place", "place_en", "kind", "aliases", "source_coord")
CONTEXT_FIELDS = ("country", "country_en", "region", "region_en", "map_bbox")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse(data: bytes):
    return ET.fromstring(data, ET.XMLParser(resolve_entities=False, no_network=True))


def xml(root) -> bytes:
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)


def project_contract(project: dict) -> dict:
    return {"id": project["id"], "badges": project.get("badges", []),
            **{key: project[key] for key in LOCATION_FIELDS if key in project}}


def context_contract(doc: dict) -> dict:
    return {key: doc[key] for key in CONTEXT_FIELDS if key in doc}


def projects_by_id(doc: dict) -> dict:
    records = doc.get("projects", [])
    ids = [record.get("id") for record in records]
    if not ids or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("참조 생성에는 비어 있지 않은 고유 project id가 필요합니다")
    return dict(zip(ids, records))


def paragraph(root, binding: dict):
    matches = root.xpath(".//p:sp[p:nvSpPr/p:cNvPr/@id=$id]", namespaces=NS,
                         id=str(binding["shape_id"]))
    if len(matches) != 1:
        raise ValueError(f"참조 텍스트 도형을 특정할 수 없습니다: {binding['shape_id']}")
    ps = matches[0].findall("p:txBody/a:p", NS)
    index = binding.get("paragraph", 0)
    if not isinstance(index, int) or not 0 <= index < len(ps):
        raise ValueError("참조 문단 번호가 유효하지 않습니다")
    return ps[index]


def paragraph_text(p) -> str:
    return "".join(p.xpath("./a:r/a:t/text()", namespaces=NS))


def replace_text(p, text: str) -> None:
    """Edit text without flattening fonts, tracking, superscripts or paragraphs.

    Equal substrings retain their original run properties. Inserted text inherits
    the local run. A note in a separate paragraph is never consumed by an edit.
    """
    if p.find("a:fld", NS) is not None:
        raise ValueError("필드가 있는 문단은 별도 참조 슬롯이 필요합니다")
    runs = p.findall("a:r", NS)
    old = paragraph_text(p)
    if not runs or not old:
        raise ValueError("빈 참조 문단에는 텍스트를 주입할 수 없습니다")
    if old == text:
        return
    breaks, run_index = [], 0
    for child in p:
        if child.tag == f"{{{NS['a']}}}r":
            run_index += 1
        elif child.tag == f"{{{NS['a']}}}br":
            breaks.append((run_index, deepcopy(child)))
    owners = [i for i, run in enumerate(runs)
              for _ in (run.findtext("a:t", default="", namespaces=NS))]
    output = []
    for tag, i0, i1, j0, j1 in SequenceMatcher(None, old, text, autojunk=False).get_opcodes():
        if tag == "equal":
            output.extend(zip(text[j0:j1], owners[i0:i1]))
        elif tag in ("replace", "insert"):
            owner = owners[min(max(0, i0 - (tag == "insert")), len(owners) - 1)]
            output.extend((ch, owner) for ch in text[j0:j1])
    for run in runs:
        p.remove(run)
    for br in p.findall("a:br", NS):
        p.remove(br)
    insert_at = 1 if p.find("a:pPr", NS) is not None else 0
    chunks = []
    for ch, owner in output:
        if chunks and chunks[-1][0] == owner:
            chunks[-1][1] += ch
        else:
            chunks.append([owner, ch])
    for owner, value in chunks:
        while breaks and breaks[0][0] <= owner:
            p.insert(insert_at, breaks.pop(0)[1])
            insert_at += 1
        run = deepcopy(runs[owner])
        run.find("a:t", NS).text = value
        p.insert(insert_at, run)
        insert_at += 1
    for _, br in breaks:
        p.insert(insert_at, br)
        insert_at += 1


def calibrate(source: Path, doc: dict, slides: list, destination: Path) -> dict:
    """Record explicit project-to-shape bindings after inspecting a reference.

    slides = [{lang, part, bindings: [{project_id, shape_id, paragraph?}]}]
    Paths and the source hash remain local. Calibration does not infer locations.
    """
    projects = projects_by_id(doc)
    result = {"version": 1, "source": str(source.resolve()),
              "source_sha256": digest(source.read_bytes()),
              "context": context_contract(doc),
              "projects": [project_contract(p) for p in projects.values()],
              "slides": deepcopy(slides)}
    with ZipFile(source) as package:
        for slide in result["slides"]:
            root = parse(package.read(slide["part"]))
            for binding in slide["bindings"]:
                if binding["project_id"] not in projects:
                    raise ValueError("참조 슬롯의 project id가 입력에 없습니다")
                p = paragraph(root, binding)
                binding["source_text_sha256"] = digest(paragraph_text(p).encode())
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    return result


def rels_name(part: str) -> str:
    folder, name = posixpath.split(part)
    return posixpath.join(folder, "_rels", name + ".rels") if part else "_rels/.rels"


def target_part(part: str, target: str) -> str:
    value = posixpath.normpath(target.lstrip("/") if target.startswith("/") else
                              posixpath.join(posixpath.dirname(part), target))
    if value.startswith("../") or value.startswith("/"):
        raise ValueError("패키지 밖을 가리키는 관계입니다")
    return value


def subset_package(parts: dict, selected: list[str]) -> dict:
    """Keep only selected slides and parts reachable through OPC relationships.

    Omitted slides must not remain hidden inside the deliverable. Remove notes,
    comments, custom shows and the stale preview thumbnail as well.
    """
    main = "ppt/presentation.xml"
    pres = parse(parts[main])
    rel_name = rels_name(main)
    rels = parse(parts[rel_name])
    slide_ids = pres.find("p:sldIdLst", NS)
    by_target = {target_part(main, rel.get("Target")): rel.get("Id")
                 for rel in rels if rel.get("Type", "").endswith("/slide")}
    by_id = {s.get(f"{{{NS['r']}}}id"): s for s in slide_ids}
    if len(selected) != len(set(selected)) or any(p not in by_target for p in selected):
        raise ValueError("선택 슬라이드가 없거나 중복됩니다")
    slide_ids[:] = [by_id[by_target[p]] for p in selected]
    for rel in list(rels):
        if rel.get("Type", "").endswith("/slide") and target_part(main, rel.get("Target")) not in selected:
            rels.remove(rel)
    for tag in ("custShowLst", "extLst"):
        element = pres.find(f"p:{tag}", NS)
        if element is not None:
            pres.remove(element)
    parts[main], parts[rel_name] = xml(pres), xml(rels)

    kept, visiting = {}, [""]
    visited = set()
    while visiting:
        part = visiting.pop()
        if part in visited:
            continue
        visited.add(part)
        if part:
            if part not in parts:
                raise ValueError(f"누락된 PPTX 부품: {part}")
            kept[part] = parts[part]
        rp = rels_name(part)
        if rp not in parts:
            continue
        relationships = parse(parts[rp])
        for rel in list(relationships):
            kind = rel.get("Type", "").rsplit("/", 1)[-1]
            if kind in {"notesSlide", "notesMaster", "comments", "commentAuthors", "thumbnail"}:
                relationships.remove(rel)
                continue
            if rel.get("TargetMode") != "External":
                target = target_part(part, rel.get("Target"))
                if target.startswith("ppt/slides/slide") and target.endswith(".xml") and target not in selected:
                    raise ValueError("선택하지 않은 슬라이드를 참조하는 연결이 있습니다")
                visiting.append(target)
        kept[rp] = xml(relationships)
    types = parse(parts["[Content_Types].xml"])
    for item in list(types):
        if item.tag.endswith("Override") and item.get("PartName", "").lstrip("/") not in kept:
            types.remove(item)
    kept["[Content_Types].xml"] = xml(types)
    if "docProps/app.xml" in kept:
        props = parse(kept["docProps/app.xml"])
        for item in list(props):
            name = ET.QName(item).localname
            if name == "Slides":
                item.text = str(len(selected))
            elif name == "Notes":
                item.text = "0"
            elif name in {"TitlesOfParts", "HeadingPairs"}:
                props.remove(item)
        kept["docProps/app.xml"] = xml(props)
    return kept


def build(doc: dict, manifest_path: Path, out: Path,
          langs: list[str] | None = None) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise ValueError("지원하지 않는 참조 양식 버전입니다")
    source = Path(manifest["source"])
    if not source.is_absolute():
        source = manifest_path.parent / source
    if source.resolve() == out.resolve():
        raise ValueError("인간 작성 원본을 덮어쓸 수 없습니다")
    if digest(source.read_bytes()) != manifest["source_sha256"]:
        raise ValueError("인간 작성 원본이 바뀌었습니다. 참조 슬롯을 다시 확인하세요")
    projects = projects_by_id(doc)
    expected = {p["id"]: p for p in manifest["projects"]}
    if context_contract(doc) != manifest["context"]:
        raise ValueError("국가·지도 범위가 참조본과 다릅니다. 자동배치 또는 재보정이 필요합니다")
    if set(projects) != set(expected):
        raise ValueError("사업 목록이 참조본과 다릅니다. 누락·추가 사업을 먼저 배치하세요")
    for key, project in projects.items():
        if project_contract(project) != expected[key]:
            raise ValueError(f"{key}: 위치·분야가 바뀌었습니다. 기존 마커를 재사용할 수 없습니다")
    slides = manifest["slides"]
    if langs is not None:
        if len(langs) != len(set(langs)) or set(langs) - {s["lang"] for s in slides}:
            raise ValueError("요청 언어의 인간 작성 참조 슬라이드가 없습니다")
        slides = [s for lang in langs for s in slides if s["lang"] == lang]
    if not slides:
        raise ValueError("생성할 참조 슬라이드가 없습니다")
    with ZipFile(source) as package:
        parts = {name: package.read(name) for name in package.namelist()}
    changes = []
    for slide in slides:
        root = parse(parts[slide["part"]])
        bound_ids = [b["project_id"] for b in slide["bindings"]]
        if len(bound_ids) != len(set(bound_ids)) or set(bound_ids) != set(projects):
            raise ValueError("각 슬라이드에 모든 사업이 정확히 한 번씩 연결되어야 합니다")
        slots = [(str(b["shape_id"]), b.get("paragraph", 0)) for b in slide["bindings"]]
        if len(slots) != len(set(slots)):
            raise ValueError("참조 텍스트 슬롯이 중복됩니다")
        for binding in slide["bindings"]:
            p = paragraph(root, binding)
            old = paragraph_text(p)
            if digest(old.encode()) != binding["source_text_sha256"]:
                raise ValueError("참조 슬롯의 원문이 일치하지 않습니다")
            field = f"name_{slide['lang']}"
            new = projects[binding["project_id"]].get(field)
            if not isinstance(new, str) or not new.strip() or "\n" in new or "\r" in new:
                raise ValueError(f"{binding['project_id']}: {field}는 한 문단의 사업명이어야 합니다")
            # A calibrated slot has finite capacity. This guard is conservative;
            # PowerPoint visual inspection is still required after any text edit.
            from layout import text_width
            if text_width(new, 10) > text_width(old, 10) * 1.10:
                raise ValueError(f"{binding['project_id']}: 참조 슬롯보다 긴 문구입니다. 배치를 다시 확인하세요")
            replace_text(p, new)
            if paragraph_text(p) != new:
                raise ValueError("사업명 주입 검증 실패")
            changes.append({"project_id": binding["project_id"], "lang": slide["lang"],
                            "shape_id": binding["shape_id"], "changed": old != new})
        parts[slide["part"]] = xml(root)
    parts = subset_package(parts, [s["part"] for s in slides])
    out.parent.mkdir(parents=True, exist_ok=True)
    # Write atomically so a failed validation cannot leave a partial deliverable.
    with tempfile.NamedTemporaryFile(dir=out.parent, suffix=".pptx", delete=False) as temp:
        temporary = Path(temp.name)
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as package:
            for name, content in parts.items():
                package.writestr(name, content)
        temporary.replace(out)
    finally:
        temporary.unlink(missing_ok=True)
    return {"renderer": "reference-pptx", "source_sha256": manifest["source_sha256"],
            "slides": len(slides), "projects": len(projects), "bindings": changes,
            "visual_review_required": True,
            "artwork": "Original local reference artwork and editable shapes retained"}
