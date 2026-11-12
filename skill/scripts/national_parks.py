"""Country-wide national park polygons from the public Protected Planet WDPCA layer."""
import json
import re
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from common import GEO_CACHE, UA
from cartography import overlap
from text_metrics import measure

LAYER = "https://data-gis.unep-wcmc.org/server/rest/services/ProtectedPlanet/WDPCA/FeatureServer/1"


def _download(iso3):
    if not re.fullmatch("[A-Z]{3}", iso3):
        raise ValueError("Invalid ISO3")
    query = {
        "where": f"iso3 LIKE '%{iso3}%' AND desig_eng = 'National Park' AND status <> 'Proposed'",
        "outFields": "objectid,site_pid,name_eng,name,desig_eng,status,iso3",
        "orderByFields": "objectid", "outSR": 4326, "geometryPrecision": 5,
        "maxAllowableOffset": .0005, "resultRecordCount": 500, "f": "geojson",
    }
    features = []
    while True:
        query["resultOffset"] = len(features)
        request = Request(LAYER + "/query?" + urlencode(query), headers={"User-Agent": UA})
        with urlopen(request, timeout=45) as response:
            page = json.load(response)
        if page.get("type") != "FeatureCollection" or not isinstance(page.get("features"), list):
            raise ValueError(f"WDPCA query failed: {page.get('error', 'invalid response')}")
        batch = page["features"]
        if not batch:
            break
        if features and batch[0]["properties"]["objectid"] <= features[-1]["properties"]["objectid"]:
            raise ValueError("WDPCA pagination did not advance")
        features.extend(batch)
        more = page.get("exceededTransferLimit") or (page.get("properties") or {}).get("exceededTransferLimit")
        if not more and len(batch) < 500:
            break
    return {"features": features, "retrieved": date.today().isoformat(), "source": LAYER}


def load(iso3):
    stamp = date.today().strftime("%Y-%m")
    cache = GEO_CACHE / "parks" / f"{iso3}-{stamp}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    data = _download(iso3)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=cache.parent, delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=False)
    Path(tmp.name).replace(cache)
    return data


def label_anchor(rings):
    """Find a wide interior interval, excluding holes by the even-odd rule."""
    ys = [p[1] for p in rings[0]]
    best = (0, 0, 0)
    for step in range(1, 8):
        y = min(ys) + (max(ys)-min(ys))*step/8
        crossings = []
        for ring in rings:
            for a,b in zip(ring, ring[1:]):
                if (a[1] > y) != (b[1] > y):
                    crossings.append(a[0]+(b[0]-a[0])*(y-a[1])/(b[1]-a[1]))
        crossings.sort()
        for left,right in zip(crossings[::2], crossings[1::2]):
            best = max(best, (right-left, (left+right)/2, y))
    return best


def project_features(features, projection):
    parks = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        kind = geometry.get("type")
        if kind not in {"Polygon", "MultiPolygon"}:
            continue
        polygons = geometry["coordinates"] if kind == "MultiPolygon" else [geometry["coordinates"]]
        props = feature["properties"]
        if props.get("desig_eng") != "National Park" or props.get("status") == "Proposed":
            continue
        projected = []
        for polygon in polygons:
            if not polygon or any(len(r) < 4 or r[0] != r[-1] for r in polygon):
                continue
            center = projection.view["center"][0]
            rings = [[[lon + 360 * round((center-lon)/360), lat] for lon,lat,*_ in ring] for ring in polygon]
            projected.append(projection.rings(rings))
        if projected:
            parks.append({"id":props["site_pid"], "name":props.get("name_eng") or props.get("name"),
                          "polygons":projected})
    return parks


def add_to_layout(result, projection):
    m = result["map"]
    try:
        data = load(result["country"]["iso3"])
        parks = project_features(data["features"], projection)
    except (OSError, ValueError, KeyError) as error:
        result["warnings"].append(f"국립공원 경계 조회 실패: {error}")
        return
    result["source"]["national_parks"] = {"url":data["source"], "retrieved":data["retrieved"]}
    m["national_parks"] = parks
    blocked = [label["box"] for label in m["labels"]]
    blocked.extend([p["x"]-.10,p["y"]-.10,p["x"]+.10,p["y"]+.10] for p in result["markers"])
    f = m["frame"]
    named = set()
    for park in parks:
        if not park["name"] or park["name"] in named:
            continue
        span,x,y = max(label_anchor(polygon) for polygon in park["polygons"])
        if span < .12:
            continue
        name = park["name"]
        width = measure(name, 5.4, False, 0) + .05
        box = [x-width/2,y-.075,x+width/2,y+.02]
        if (box[0]>=f["x"] and box[2]<=f["x"]+f["w"] and box[1]>=f["y"] and box[3]<=f["y"]+f["h"]
                and not any(overlap(box, other) for other in blocked)):
            m["labels"].append({"name":name,"kind":"park","x":x,"y":y,"size":5.4,"box":box})
            blocked.append(box)
            named.add(name)
