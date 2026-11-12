"""Use named first-level administrative boundaries for regional project coverage."""
import re

from common import GEO_CACHE, read_json, norm
from national_parks import label_anchor

ADMIN_TYPE = r"(?:county|province|state|governorate|oblast|region)"
SITE_WORDS = re.compile(r"\b(?:hospital|campus|sub[- ]county|construction of .*? for )", re.I)


def assign_regions(records, resolved, features, center_lon=0):
    boundaries = {}
    for feature in features:
        props = feature["properties"]
        if (feature.get("geometry") or {}).get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        name = props.get("shapeName", "")
        simple = re.sub(r"\s+" + ADMIN_TYPE + r"$", "", name, flags=re.I)
        if simple:
            boundaries.setdefault(norm(simple), []).append(feature)
    for record, row in zip(records, resolved["places"]):
        scope = record.get("coverage")
        if scope in {"site", "nationwide"} or (scope == "unknown" and not record.get("_inferred_scope")):
            continue
        title = record.get("name_en") or ""
        explicit = record.get("admin1_name") if scope == "admin1" else None
        if explicit:
            names = [norm(explicit)]
        elif record.get("_location_basis") == "group-representative" and not SITE_WORDS.search(title):
            names = [name for name in boundaries if re.search(
                r"(?<!\w)" + re.escape(name) + r"\s+" + ADMIN_TYPE + r"\b", norm(title))]
        else:
            names = []
        if len(names) != 1 or len(boundaries.get(names[0], [])) != 1:
            if scope == "admin1":
                row.update(parts=[], resolved=False)
            continue
        feature = boundaries[names[0]][0]
        props = feature["properties"]
        geom = feature["geometry"]
        polygons = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        polygons = [[[[x + 360 * round((center_lon-x)/360), y] for x,y,*_ in ring]
                     for ring in polygon] for polygon in polygons if polygon and polygon[0]]
        if not polygons:
            row.update(parts=[], resolved=False)
            continue
        span, lon, lat = max(label_anchor(rings) for rings in polygons)
        if not span:
            row.update(parts=[], resolved=False)
            continue
        region = props["shapeName"]
        row.update(resolved=True, source_conflicts=[], region=region, geometry=polygons,
                   region_id=props.get("shapeID") or region, evidence=explicit or title,
                   parts=[{"ok":True,"kind":"admin1","level":"ADM1","matched":region,
                           "lon":lon,"lat":lat,"source":"geoBoundaries ADM1"}])
        if record.get("_inferred_scope"):
            record["place"] = record.get("source_place") or region
        record["coverage"] = "admin1"
        record["admin1_name"] = region


def resolve_regions(doc, resolved, bbox):
    path = GEO_CACHE / f"{resolved['iso3']}_ADM1.geojson"
    features = read_json(path)["features"] if path.exists() else []
    assign_regions(doc["projects"], resolved, features, (bbox[0]+bbox[2])/2)
