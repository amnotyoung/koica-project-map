"""Prepare one project per activity and keep the evidence for its geographic scope."""
import re
from collections import defaultdict


def prepare_projects(doc):
    country = doc["country"]
    projects = []
    grouped = defaultdict(list)
    for original in doc["projects"]:
        record = dict(original)
        scope = record.get("coverage")
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
        project["source_ids"] = [s.get("id") or s["_id"] for s in sites]
        if project.get("coverage") not in {"nationwide", "unknown", "admin1", "admin2", "external"}:
            project["sites"] = [{k:s[k] for k in ("place","place_en","kind","aliases","source_coord","_location_basis","name_en") if k in s} for s in sites]
            project["place"] = "/".join(dict.fromkeys(s["place"] for s in sites))
            project.pop("place_en", None)
        project["id"] = activity
        project.pop("source_coord", None)
    return {**doc, "projects": projects}
