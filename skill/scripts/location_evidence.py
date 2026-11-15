"""Recover country-scoped places from explicit project titles and reported IATI localities."""
import re
from collections import defaultdict

from common import GEO_CACHE, fetch, norm, read_json, unzip_member
from geo_prepare import GEONAMES_URL
from iati_aid import URL
from facility_locations import FACILITY, facility_index, named_facility
from project_geography import evidence_scope, identifies_local_participants


def cities_for(iso2):
    names = defaultdict(dict)
    path = GEO_CACHE / "cities500.txt"
    if not path.exists():
        archive = fetch(GEONAMES_URL, GEO_CACHE / "cities500.zip")
        unzip_member(archive, "cities500.txt", path)
    with path.open(encoding="utf-8") as source:
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


def named_city(title, cities):
    # Only explicit city/town labels qualify without an independent activity location.
    matches = {}
    for m in re.finditer(r"\b(?:city|town)\b", title):
        before = title[:m.start()].strip().split()
        after = title[m.end():].strip().split()
        candidates = [" ".join(before[-n:]).strip(" ,") for n in range(min(5,len(before)), 0, -1)]
        if after[:1] == ["of"]:
            candidates = [" ".join(after[1:n+1]).strip(" ,") for n in range(min(5,len(after)-1),0,-1)] + candidates
        for term in candidates:
            found = cities.get(term, {})
            if len(term) >= 3 and len(found) == 1:
                city = next(iter(found.values()))
                matches[city["id"]] = city
                break
    if len(matches) == 1:
        return next(iter(matches.values()))
    return None


def delivery_city(row, places, texts, cities, regions):
    if len(places) != 1 or identifies_local_participants(texts):
        return {}
    key = norm(places[0])
    matches = cities.get(key, {})
    if len(key) < 3 or len(matches) != 1:
        return {}
    title = row.get("name_en") or ""
    if re.search(r"\b(?:province|region|district|island|county|cities|municipalities)s?\b",title,re.I):
        return {}
    # A capital is often in the location field for policy work anywhere in the country.
    # Require a physical intervention explicitly located in the reported city.
    activity = r"(?:hospital|school|university|training cent(?:er|re)|laboratory|treatment plant|vocational cent(?:er|re)|facility)"
    marker = r"(?:the city of |city of )?" + re.escape(key)
    pattern = rf"\b{activity}\s+(?:located |based )?in\s+{marker}(?: city)?(?=\s*(?:$|[,.;(]))"
    city = next(iter(matches.values()))
    # Some titles identify the facility, its purpose, then the city and country.
    # Require the same city in Korean and retain the locality's precision.
    ko = city.get("ko")
    ko_title = row.get("name_ko", "")
    title_match = (ko and re.search(r"(?<![가-힣])"+re.escape(ko)+r"(?:시)?(?=\s)",ko_title)
                   and re.search(r"\b(?:establishment|construction|renovation|modernization) of (?:an? |the )?"
                                 r"[^,;]{0,60}\b(?:cent(?:er|re)|hospital|school|laboratory)\b"
                                 r"[^,;]{0,120}\bin "+re.escape(key)+r"\s*,", norm(title)))
    for sentence in (title, *(s for t in texts for s in re.split(r"[;\n]|(?<=[.!?])\s+", t))):
        if re.search(r"\b(?:meeting|visit|example|survey|workshop|other|and elsewhere)\b", sentence, re.I):
            continue
        normalized = norm(sentence)
        if not (sentence == title and title_match or re.search(pattern, normalized)) or not re.search(
                r"\b(?:construct\w*|establish\w*|build\w*|moderniz\w*|renovat\w*|equip\w*|upgrad\w*)\b", normalized):
            continue
        if regions.get(boundary_key(key)) and not re.search(r"\b(?:city of "+re.escape(key)+"|"+re.escape(key)+r" city)\b", normalized):
            continue
        return {"coverage":"site", "place":city["ko"] or city["name"], "place_en":city["name"],
                "geonames_locality":{k:city[k] for k in ("id","name","lat","lon")},
                "_location_evidence":"시설 설치·개선 대상 도시와 IATI 보고 지명 일치 · "+city["name"]}
    return {}


def conflicting_city_unit(row, cities):
    title = norm(row.get("name_en") or "")
    for match in re.finditer(r"([가-힣]{2,12})\s*시(?:\s|의|에서|내)", row.get("name_ko") or ""):
        for city in cities.get(norm(match[1]), {}).values():
            name = re.escape(norm(city["name"]))
            unit = r"(?:province|region|county|governorate|district|department)"
            if re.search(rf"\b(?:{unit} of {name}|{name} {unit})\b", title):
                return city["name"]
    return None


def enrich_locations(doc, reported_places, cities, regions, *, descriptions=None, iso2=None):
    for row in doc["projects"]:
        if not row.get("selected"):
            continue
        fid = row["id"]
        places = reported_places.get(fid.partition("@")[0], [])
        if places:
            row["_iati_reported_places"] = places
        if ("reviewed_pins" in row or "reviewed_unresolved" in row
                or row.get("_location_basis") not in {"group-representative","annual-plan"}
                or row.get("coverage") not in {None, "unknown"} or "@" in fid):
            continue
        activity_texts = (descriptions or {}).get(fid, [])
        conflict = conflicting_city_unit(row, cities)
        if conflict:
            row.setdefault("source_place", row["place"])
            row.update(coverage="unknown", _location_evidence="국·영문 사업명의 시·권역 불일치 · "+conflict)
            row.pop("source_coord", None)
            continue
        evidence = evidence_scope(row, doc.get("country",""), activity_texts,
                                  places, cities, regions, boundary_key)
        if not evidence and iso2 and FACILITY.search(" ".join([row.get("name_en") or "", *activity_texts])):
            evidence = named_facility(row.get("name_en") or "", activity_texts, facility_index(iso2))
        if not evidence:
            evidence = delivery_city(row, places, activity_texts, cities, regions)
        if evidence:
            links = evidence.pop("scope_sources", [])
            row.pop("source_coord", None)
            row.update(source_place=row["place"], _location_basis="public-project-evidence", **evidence)
            row["scope_sources"] = list(dict.fromkeys([*(row.get("scope_sources") or []),
                URL if fid.startswith("iati:") else doc["source"], *links,
                *([] if evidence.get("source_coord") else
                  [GEONAMES_URL if row["coverage"]=="site" else "https://www.geoboundaries.org/"])]))
            continue
        if identifies_local_participants(activity_texts):
            row.setdefault("source_place", row["place"])
            row["coverage"] = "unknown"
            row.pop("source_coord", None)
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
                level = {"adm1":"admin1", "adm2":"admin2"}[level]
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
        basis = "사업명과 IATI 보고 지명이 일치한 도시"
        if not city and not re.search(r"\b(?:provinces?|regions?|districts?|states?|municipalities|cities|towns|counties)\b", title):
            city = named_city(title, cities)
            basis = "사업명에 명시된 도시"
        if city:
            row.pop("source_coord", None)
            row.update(coverage="site", source_place=row["place"], place=city["ko"] or city["name"],
                       place_en=city["name"], geonames_locality={k:city[k] for k in ("id","name","lat","lon")},
                       _location_basis="public-project-evidence", scope_sources=list(dict.fromkeys([*(row.get("scope_sources") or []), doc.get("source") or URL, GEONAMES_URL])),
                       _location_evidence=f"{basis} · {city['name']}")


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
