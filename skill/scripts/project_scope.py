"""Prepare one project per activity and keep the evidence for its geographic scope."""
import re
from collections import defaultdict


LOCATION_FIELDS = ("place", "place_en", "scope_label", "scope_label_en", "sites", "geonames_locality",
                   "coverage", "admin1_names", "admin2_names", "scope_sources", "_location_evidence",
                   "implementation_place", "implementation_place_en")


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
            project["sites"] = [{k:s[k] for k in ("place","place_en","kind","aliases","source_coord","reviewed_pins","reviewed_unresolved","coverage","_location_basis","name_en") if k in s} for s in sites]
            project.pop("reviewed_pins", None)
            project["place"] = "/".join(dict.fromkeys(s["place"] for s in sites))
            project.pop("place_en", None)
        project["id"] = activity
        project.pop("source_coord", None)
    return {**doc, "projects": projects}
