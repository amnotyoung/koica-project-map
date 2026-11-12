"""Recover country-scoped places from explicit project titles and reported IATI localities."""
import re
from collections import defaultdict

from common import GEO_CACHE, norm, read_json
from geo_prepare import GEONAMES_URL
from iati_aid import URL


def cities_for(iso2):
    names = defaultdict(dict)
    with (GEO_CACHE / "cities500.txt").open(encoding="utf-8") as source:
        for line in source:
            fields = line.rstrip("\n").split("\t")
            if fields[8] != iso2:
                continue
            ident, name, ascii_name, alternatives, lat, lon = fields[:6]
            ko = next((v for v in alternatives.split(",") if re.fullmatch(r"[가-힣 ]+", v)), "")
            city = {"id":int(ident),"name":name,"lat":float(lat),"lon":float(lon),"ko":ko}
            for label in (name, ascii_name, ko):
                if label:
                    names[norm(label)][ident] = city
    return names


def match_city(title, reported, cities):
    # One recorded locality is not proof that an entire project takes place there.
    if len(reported) != 1:
        return None
    name = norm(reported[0])
    matches = cities.get(name, {})
    if len(matches) != 1 or len(name) < 3:
        return None
    # Preserve larger regions and multi-place scopes for separate review.
    if re.search(r"\b(?:province|district|region|department|governorate|county|municipalities)s?\b", title):
        return None
    place = re.escape(name)
    if not re.search(r"\b(?:in|at|city of|municipality of) " + place + r"(?=,|$|\s*\(| city\b)", title):
        return None
    return next(iter(matches.values()))


def enrich_locations(doc, reported_places, cities, regions):
    for row in doc["projects"]:
        if not row.get("selected"):
            continue
        fid = row["id"]
        places = reported_places.get(fid.partition("@")[0], [])
        if places:
            row["_iati_reported_places"] = places
        if (row.get("reviewed_pins") or row.get("_location_basis") not in {"group-representative","annual-plan"}
                or row.get("coverage") not in {None, "unknown"} or "@" in fid):
            continue
        title = norm(row.get("name_en") or "")
        if re.search(r"\bnationwide\b", title):
            row.update(coverage="nationwide", _location_basis="project-title")
            row.pop("source_coord", None)
            continue
        region = title_region(title, regions)
        if region:
            level, name = region
            row["_title_region"] = name
            # Facility projects need a site within the region, not the whole boundary.
            if not re.search(r"\b(hospital|school|cent(?:er|re)|station|plant|campus|university|airport|construction)\b", title):
                row.update(coverage=level, source_place=row["place"], place=name, place_en=name,
                           _location_basis="public-project-evidence",
                           _location_evidence="사업명에 명시된 행정구역 · " + name)
                row[level + "_names"] = [name]
                row.pop("source_coord", None)
                continue
        city = match_city(title, places, cities)
        if city:
            # A city and an island/province can share a name (e.g. Zanzibar).
            original = row.get("name_ko", "")
            ko_name = city.get("ko")
            city_type = (re.search(r"\b(?:city|municipality)\b", title) or
                         ko_name and re.search(re.escape(ko_name) + r"\s*시(?:의|에|와|\s|$)", original))
            if not city_type:
                city = None
        if city:
            row.pop("source_coord", None)
            row.update(coverage="site", source_place=row["place"], place=city["ko"] or city["name"],
                       place_en=city["name"], geonames_locality={k:city[k] for k in ("id","name","lat","lon")},
                       _location_basis="public-project-evidence", scope_sources=[URL, GEONAMES_URL],
                       _location_evidence=f"사업명과 IATI 위치가 일치한 도시 · {places[0]}")


def boundary_key(text):
    return norm(text).replace("đ", "d").replace("ł", "l")


def regional_names(iso3, entries):
    regions = defaultdict(list)
    types = {}
    for level in ("ADM1", "ADM2"):
        path = GEO_CACHE / f"{iso3}_{level}_meta.json"
        types[level] = boundary_key(read_json(path).get("boundaryCanonical") or "") if path.exists() else ""
    for entry in entries:
        level = entry["level"]
        if level in types:
            regions[boundary_key(entry["name"])].append((level.lower(), entry["name"], types[level]))
    return regions


def title_region(title, regions):
    title = boundary_key(title)
    units = r"province|governorate|region|state|department|county|district"
    # A single-level polygon cannot express a mixed or incompletely named footprint.
    if len(re.findall(r"\b(?:" + units + r"|sub county|town|city|village|municipality)\b", title)) != 1:
        return None
    if re.search(r"\b(provinces|districts|regions|governorates|counties|states|departments|sub county)\b", title):
        return None
    m = re.search(r"\b(" + units + r")\b", title)
    if not m:
        return None
    words = title[:m.start()].rstrip().split()
    unit = m[1]
    plural = "counties" if unit == "county" else unit+"s"
    for length in range(min(6,len(words)),0,-1):
        name = " ".join(words[-length:])
        found = [r for r in regions.get(name, []) if len(name)>=3 and
                 re.search(r"\b(?:"+unit+"|"+plural+r")\b",r[2])]
        if len(found) == 1:
            return found[0][:2]
    return None
