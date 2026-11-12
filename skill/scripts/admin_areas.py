"""Use named administrative boundaries for regional project coverage."""
import re

from common import GEO_CACHE, read_json, norm
from national_parks import label_anchor

ADMIN_TYPE = r"(?:county|province|state|governorate|oblast|region)"
SITE_WORDS = re.compile(r"\b(?:hospital|campus|sub[- ]county|construction of .*? for )", re.I)


def assign_regions(records, resolved, features, center_lon=0, level="ADM1"):
    boundaries, by_id = {}, {}
    for feature in features:
        props = feature["properties"]
        if (feature.get("geometry") or {}).get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        name = props.get("shapeName", "")
        simple = re.sub(r"\s+" + ADMIN_TYPE + r"$", "", name, flags=re.I)
        by_id[props.get("shapeID") or name] = feature
        if simple:
            boundaries.setdefault(norm(simple), []).append(feature)
    key = {"ADM1": "admin1", "ADM2": "admin2"}[level]
    for record, row in zip(records, resolved["places"]):
        scope = record.get("coverage")
        if (level == "ADM2" or scope == "admin2") and scope != key:
            continue
        if scope in {"site", "nationwide", "external"} or (scope == "unknown" and not record.get("_inferred_scope")):
            continue
        title = record.get("name_en") or ""
        explicit = record.get(f"{key}_name") if scope == key else None
        listed = record.get(f"{key}_names") if scope == key else None
        ids = record.get(f"{key}_ids") if scope == key else None
        if ids:
            names = list(dict.fromkeys(ids))
        elif listed or explicit:
            names = list(dict.fromkeys(norm(n) for n in (listed or [explicit])))
        elif record.get("_location_basis") == "group-representative" and not SITE_WORDS.search(title):
            names = [name for name in boundaries if re.search(
                r"(?<!\w)" + re.escape(name) + r"\s+" + ADMIN_TYPE + r"\b", norm(title))]
            if len(names) != 1:
                continue
        else:
            continue
        regions, parts = [], []
        for name in names:
            if ids:
                matches = [by_id[name]] if name in by_id else []
            else:
                matches = boundaries.get(name, [])
            if len(matches) != 1:
                break
            feature = matches[0]
            props, geom = feature["properties"], feature["geometry"]
            ringsets = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
            polygons = [[[[x + 360 * round((center_lon-x)/360), y] for x,y,*_ in ring]
                         for ring in polygon] for polygon in ringsets if polygon and polygon[0]]
            span, lon, lat = max((label_anchor(rings) for rings in polygons), default=(0,0,0))
            if not span:
                break
            region = props["shapeName"]
            regions.append({"region": region, "geometry": polygons,
                            "region_id": props.get("shapeID") or region})
            parts.append({"ok": True, "kind": key, "level": level, "matched": region,
                          "lon": lon, "lat": lat, "source": f"geoBoundaries {level}"})
        if not regions or len(regions) != len(names):
            row.update(parts=[], resolved=False)
            continue
        row.update(resolved=True, source_conflicts=[], regions=regions, parts=parts,
                   region="/".join(r["region"] for r in regions),
                   evidence=record.get("scope_sources") or explicit or title)
        if len(regions) == 1:
            row.update(regions[0])
            record[f"{key}_name"] = row["region"]
        if record.get("_inferred_scope"):
            record["place"] = record.get("source_place") or row["region"]
        record["coverage"] = key


def resolve_regions(doc, resolved, bbox):
    levels = ["ADM1"]
    if any(p.get("coverage") == "admin2" for p in doc["projects"]):
        levels.append("ADM2")
    for level in levels:
        path = GEO_CACHE / f"{resolved['iso3']}_{level}.geojson"
        features = read_json(path)["features"] if path.exists() else []
        assign_regions(doc["projects"], resolved, features, (bbox[0]+bbox[2])/2, level)
