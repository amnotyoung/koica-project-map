"""Prepare one project per activity and keep the evidence for its geographic scope."""
import re
from collections import defaultdict


LOCATION_FIELDS = ("place", "place_en", "scope_label", "scope_label_en", "sites", "geonames_locality",
                   "coverage", "admin1_names", "admin2_names", "scope_sources", "_location_evidence",
                   "implementation_place", "implementation_place_en", "map_scope", "reviewed_pins",
                   "reviewed_unresolved", "admin1_ids", "admin2_ids")


def describe_map_scope(record, resolved):
    """Describe only the geography supported by the record and resolved for this map."""
    spec = record.get("map_scope")
    if not spec:
        return
    if not record.get("scope_sources"):
        raise ValueError("map_scope에는 위치 근거(scope_sources)가 필요합니다")
    coverage = record.get("coverage")
    areas = {r["region_id"] for r in resolved.get("regions", [])}
    pins = record.get("reviewed_pins") or []
    points = {(p["lon"], p["lat"]) for p in resolved["parts"] if p.get("ok") and p.get("lon") is not None}
    ko, en = [], []
    if "total" in spec:
        total = spec["total"]
        if coverage not in {"admin1","admin2"} and not (coverage == "site" and "reviewed_pins" in record):
            raise ValueError("전체 대상 수와 비교할 확인 지점 또는 행정구역이 필요합니다")
        count = len(areas) if coverage != "site" else len(points)
        if type(total) is not int or total < max(1, count):
            raise ValueError("전체 대상 수가 지도에 표시한 대상 수보다 작거나 유효하지 않습니다")
        resolved["partial_coverage"] = count < total
        ko.append(f"전체 {total}곳 중 {count}곳 표시")
        en.append(f"{count} of {total} locations mapped")
    facilities = spec.get("facilities")
    if facilities:
        if coverage not in {"admin1","admin2"} or not all(facilities.get(k) for k in ("ko","en")):
            raise ValueError("시설 소재 권역에는 행정구역과 국·영문 시설명이 필요합니다")
        resolved["facility_context"] = True
        ko.append(f"{facilities['ko']} 소재 행정구역")
        en.append(f"Administrative areas containing {facilities['en']}")
    if spec.get("corridor"):
        if coverage != "site" or "reviewed_pins" not in record or len(pins) > 2:
            raise ValueError("개략 구간에는 확인된 양 끝 지점만 reviewed_pins로 지정하세요")
        resolved["corridor"] = (len(pins) == len(points) == 2 and resolved["resolved"]
                                and not resolved.get("source_conflicts") and len({p["name"] for p in pins}) == 2)
        if resolved["corridor"]:
            ko.append("점선은 양 끝을 연결한 개략 구간")
            en.append("Dashed line connects endpoints schematically")
        else:
            ko.append("양 끝 지점 확인 전 · 선 생략")
            en.append("Endpoints incomplete · alignment unplotted")
    record["_map_caption"] = {"ko":" · ".join(ko), "en":" · ".join(en)}


def delivery_caption(record, lang):
    """Name the delivery site or reported locality separately from geographic coverage."""
    if record.get("coverage") not in {"nationwide", "admin1", "admin2"}:
        return ""
    site = record.get("implementation_place_en" if lang == "en" else "implementation_place")
    if site:
        return ("Implementation site · " if lang == "en" else "수행지 · ") + site
    areas = {name.casefold() for field in ("admin1_names", "admin2_names")
             for name in record.get(field, [])}
    reported = [s for s in dict.fromkeys(record.get("_iati_reported_places") or [])
                if s and s.casefold() not in areas]
    if reported:
        return ("IATI locality · " if lang == "en" else "IATI 보고 지명 · ") + ", ".join(reported)
    return ""


def edition_fields(fact, year):
    if not fact:
        return {}
    if fact["year"] == year:
        return {k:v for k,v in fact.items() if k not in {"year", "scope_years"}}
    if year in fact.get("scope_years", []) and fact.get("scope_sources"):
        return {k:fact[k] for k in LOCATION_FIELDS if k in fact}
    return {}


def prepare_projects(doc):
    country = doc["country"]
    projects = []
    grouped = defaultdict(list)
    for original in doc["projects"]:
        record = dict(original)
        scope = record.get("coverage")
        if scope in {"adm1", "adm2"}:
            canonical = {"adm1":"admin1", "adm2":"admin2"}[scope]
            for suffix in ("_name", "_names", "_ids"):
                if scope+suffix in record:
                    record.setdefault(canonical+suffix, record[scope+suffix])
            record["coverage"] = scope = canonical
        title = record.get("name_ko", "")
        if scope == "nationwide" or (
            scope is None and record.get("_location_basis") == "group-representative"
            and re.search(r"(?:^|\s)전국\s+|"+re.escape(country)+r"\s*전역", title)
        ):
            record.update(coverage="nationwide", place=f"{country} 전역")
            record.pop("source_coord", None)
            record.pop("place_en", None)
        fid = record.get("id") or record.get("_id") or ""
        place = record.get("place", "").strip()
        if (not record.get("coverage") and record.get("_location_basis") == "group-representative"
                and record.get("_coord_source") in {"도시", "도시(음차)"} and "@" not in fid
                and place and place.casefold() not in (title + " " + (record.get("name_en") or "")).casefold()):
            record["coverage"] = "unknown"
            record["_inferred_scope"] = True
        if record.get("coverage") == "unknown":
            record.setdefault("source_place", place)
            record["place"] = record.get("scope_label") or "사업 범위 확인 필요"
            record.pop("source_coord", None)
            record.pop("place_en", None)
        if record.get("scope_label_en"):
            record["place_en"] = record["scope_label_en"]
        if fid.startswith("iati:") and "@" in fid:
            key = (fid.split("@", 1)[0], title, record.get("name_en"), tuple(record.get("badges", [])), record.get("coverage"))
            if not grouped[key]:
                projects.append(record)
            grouped[key].append(record)
        else:
            projects.append(record)
    for (activity, *_), sites in grouped.items():
        if len(sites) < 2:
            continue
        project = sites[0]
        if any(s.get("map_scope") != project.get("map_scope") for s in sites):
            raise ValueError(f"같은 활동의 위치 근거 유형이 서로 다릅니다: {activity}")
        reported = list(dict.fromkeys(p for s in sites for p in s.get("_iati_reported_places", [])))
        if reported:
            project["_iati_reported_places"] = reported
        project["source_ids"] = [s.get("id") or s["_id"] for s in sites]
        scope = project.get("coverage")
        if scope in {"admin1","admin2"} and all(s.get(scope+"_ids") for s in sites):
            for field in (scope+"_ids",scope+"_names"):
                project[field] = list(dict.fromkeys(value for s in sites for value in s.get(field, [])))
            project["place"] = "/".join(dict.fromkeys(s["place"] for s in sites))
        if scope not in {"nationwide", "unknown", "admin1", "admin2", "external"}:
            if project.get("map_scope") and all("reviewed_pins" in s for s in sites):
                pins = {(p["name"],p["lon"],p["lat"]):p for s in sites for p in s["reviewed_pins"]}
                project["reviewed_pins"] = list(pins.values())
                project["reviewed_unresolved"] = list(dict.fromkeys(n for s in sites for n in s.get("reviewed_unresolved", [])))
            else:
                project["sites"] = [{k:s[k] for k in ("place","place_en","kind","aliases","source_coord","reviewed_pins","reviewed_unresolved","coverage","_location_basis","name_en") if k in s} for s in sites]
                project.pop("reviewed_pins", None)
            project["place"] = "/".join(dict.fromkeys(s["place"] for s in sites))
            project.pop("place_en", None)
        project["id"] = activity
        project.pop("source_coord", None)
    return {**doc, "projects": projects}
