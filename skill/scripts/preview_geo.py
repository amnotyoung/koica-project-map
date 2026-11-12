"""Compact, offline geography for the project roster's location editor."""
import math
import re

from common import GEO_CACHE, read_json, simplify
from resolve_places import ensure_country


def mercator(lat):
    return math.degrees(math.asinh(math.tan(math.radians(max(-85, min(85, lat))))))


def preview_geo(country):
    places = ensure_country(country, "10m")
    iso = places["iso3"]
    base = read_json(GEO_CACHE / f"{iso}_basemap.json")
    west, south, east, north = base["bbox"]
    mid = (east+west)/2
    low, high = mercator(south), mercator(north)
    scale = min(600/max(.001,east-west), 294/max(.001,high-low))
    tx, ty = 320-scale*mid, 160+scale*(low+high)/2

    def path(rings):
        parts = []
        for ring in rings:
            coords = [(x+360*round((mid-x)/360), y) for x,y,*_ in ring]
            if len(coords) < 3:
                continue
            pts = simplify(coords, .24/scale)
            parts.append("M"+" ".join(f"{x*scale+tx:.2f},{ty-mercator(y)*scale:.2f}" for x,y in pts)+"Z")
        return "".join(parts)

    regions = {}
    years = {}
    for level in ("admin1","admin2"):
        prefix = f"{iso}_{level.replace('admin','ADM')}"
        file = GEO_CACHE / (prefix+".geojson")
        meta = GEO_CACHE / (prefix+"_meta.json")
        years[level] = read_json(meta).get("boundaryYearRepresented") if meta.exists() else None
        regions[level] = []
        for f in read_json(file)["features"] if file.exists() else []:
            props, geom = f["properties"], f.get("geometry") or {}
            if not props.get("shapeName") or geom.get("type") not in ("Polygon","MultiPolygon"):
                continue
            polygons = [geom["coordinates"]] if geom["type"]=="Polygon" else geom["coordinates"]
            regions[level].append({"id":props.get("shapeID") or props["shapeName"],
                                   "name":props["shapeName"], "path":path(r for poly in polygons for r in poly)})
    cities = places["cities"]
    # The map's compact city cache keeps only a few aliases; include Korean names
    # from the original GeoNames table for offline Korean search as well.
    by_coord = {(round(c["lon"],5),round(c["lat"],5),c["name"]): c for c in cities}
    raw = GEO_CACHE / "cities500.txt"
    if raw.exists():
        with raw.open(encoding="utf-8") as rows:
            for line in rows:
                r = line.split("\t", 9)
                if len(r)<9 or not re.search("[가-힣]", r[3]):
                    continue
                c = by_coord.get((round(float(r[5])+360*round((mid-float(r[5]))/360),5),round(float(r[4]),5),r[1]))
                if c:
                    c["alt"] = list(dict.fromkeys([*c.get("alt",[]),*(a for a in r[3].split(",") if re.search("[가-힣]",a))]))
    return {"iso":iso, "transform":[scale,tx,ty,mid], "land":path(base["land"]),
            "cities":cities,"regions":regions,"years":years}
