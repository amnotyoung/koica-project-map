"""Read geographic scope from activity evidence, keeping implementation sites separate from administrative areas."""
import re
from common import REFERENCE_DIR, read_json
from functools import lru_cache


@lru_cache(maxsize=1)
def institution_directory():
    return read_json(REFERENCE_DIR / "institution_localities.json")


def contains_name(text, name):
    return re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text) is not None


def identifies_local_participants(descriptions):
    return any(re.search(r"\b(?:participating|selected|pilot)\s+(?:municipalities|districts|communities|villages)\b"
                         r"|(?:참여|선정|시범)\s*(?:지자체|지방정부|마을|시군)|(?:실시된|도입한)\s*지역정부", text, re.I)
               for text in descriptions)


def beneficiary_regions(descriptions, regions, normalize):
    # All named rows in a counted direct-beneficiary list must resolve at the same level.
    for text in descriptions:
        match = re.search(r"direct beneficiaries\s*:\s*([^\n]+)", text, re.I)
        if not match:
            continue
        fields = re.split(r"\s*(?:&(?:amp;)*| and |;)\s*", match[1], flags=re.I)
        names = []
        for field in fields:
            item = re.fullmatch(r"([\wÀ-ỹ -]{2,60}?)\s*[-–:]\s*[\d,]+\s+(?:people|persons|households)"
                                r"(?:\s+in (?:the )?project area)?\s*[.]?", field.strip(), re.I)
            found = regions.get(normalize(item[1]), []) if item else []
            if len(found) != 1:
                break
            names.append(found[0][:2])
        else:
            if len(names) >= 2 and len({level for level, _ in names}) == 1:
                return names
    return []


def evidence_scope(row, country, texts, reported, cities, regions, normalize):
    """Return a map-ready scope only for supported, uniquely identified targets."""
    title = normalize(row.get("name_en") or "")
    description = normalize(" ".join(texts))
    bilingual = row.get("name_ko") or ""
    def area(items, basis):
        level = items[0][0].replace("adm1","admin1").replace("adm2","admin2")
        names = list(dict.fromkeys(name for _,name in items))
        return {"coverage":level,level+"_names":names,"place":" / ".join(names),
                "place_en":" / ".join(names),"_location_evidence":basis}
    direct = beneficiary_regions(texts, regions, normalize)
    if direct:
        return area(direct,"IATI 사업 설명의 직접 수혜지역 · " + " / ".join(n for _,n in direct))
    # A named administrative area in BOTH title and implementation description. Avoid
    # depicting an entire province for the construction of a facility at one site.
    if not identifies_local_participants(texts) and not re.search(
            r"\b(?:school|hospital|centre|center|university|construction|campus|district|city|town|station)\b",title):
        candidates = [(level,label) for name,values in regions.items() if len(name)>3 and len(values)==1
                      and contains_name(title,name) and contains_name(description,name)
                      for level,label,_ in values if level=="adm1"]
        if len(candidates)==1 and (re.search(r"(?:지역|주|성)(?:\s|의|내|에서)",bilingual) or
                                  normalize(row.get("place","")) == normalize(candidates[0][1])):
            return area(candidates,"국·영문 사업명과 사업 본문의 대상 권역 · " + candidates[0][1])
    # A report of a capital by itself, a survey itinerary or an institution's HQ
    # does not establish a project site. Match a named delivery facility.
    matched = []
    for facility in institution_directory().get(country, []):
        labels = [normalize(n) for n in facility["aliases"]]
        if not (any(contains_name(title,n) for n in labels) or
                any(re.search(r"\b(?:at|within|based at|renovation of|capacity of|equipment for) (?:the )?" + re.escape(n) + r"(?!\w)",description) for n in labels)):
            continue
        matched.append(facility)
    if len(matched) == 1:
        facility = matched[0]
        return {"coverage":"site","place":facility["ko"],"place_en":facility["en"],
                "geonames_locality":facility["locality"],"scope_sources":facility["sources"],
                "_location_evidence":"수혜기관 소재 도시 · "+facility["en"]+" (도시 대표위치)"}
    # One city named explicitly in a Korean title, corroborated by the official
    # English title or activity locality. Require an unambiguous Korean gazetteer name.
    for m in re.finditer(r"([가-힣]{2,12})\s*시(?:\s|의|에서|내)",bilingual):
        ko=m[1]
        matches=cities.get(normalize(ko),{})
        if len(matches)!=1:
            continue
        city=next(iter(matches.values()))
        en=normalize(city["name"])
        if contains_name(title,en) or any(normalize(x)==en for x in reported):
            return {"coverage":"site","place":ko,"place_en":city["name"],
                    "geonames_locality":{k:city[k] for k in ("id","name","lat","lon")},
                    "_location_evidence":"국문 사업명의 대상 도시와 원천 지명 일치 · "+city["name"]}
    return {}
