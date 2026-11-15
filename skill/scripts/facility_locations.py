"""Identify an existing delivery facility by its proper name in the country gazetteer."""
from functools import lru_cache
from pathlib import Path
import io
import re
import tempfile
from urllib.error import URLError
import zipfile

from common import GEO_CACHE, fetch, log, norm

FACILITY = re.compile(r"\b(?:university|hospital|college|polytechnic|institute|school|airport)\b", re.I)
FEATURES = {"UNIV", "SCH", "SCHC", "SCHT", "HSP", "HSPC", "HSPD", "ITTR", "AIRP"}
GENERIC = set("the of for at and national central teaching regional general public technical vocational "
              "education medical training university hospital college polytechnic institute school technology airport international".split())


@lru_cache(maxsize=12)
def facility_index(iso):
    if not re.fullmatch("[A-Z]{2}", iso):
        raise ValueError("Invalid country code")
    folder = GEO_CACHE / "facilities"
    folder.mkdir(exist_ok=True, parents=True)
    target = folder / (iso + ".zip")
    url = "https://download.geonames.org/export/dump/" + iso + ".zip"
    try:
        if not target.exists():
            with tempfile.TemporaryDirectory(dir=folder) as tmp:
                archive = fetch(url, Path(tmp) / target.name)
                with zipfile.ZipFile(archive) as zipped:
                    zipped.getinfo(iso + ".txt")
                archive.replace(target)
        index = {}
        with zipfile.ZipFile(target) as zipped, zipped.open(iso + ".txt") as raw:
            for line in io.TextIOWrapper(raw, encoding="utf-8"):
                fields = line.split("\t")
                if fields[6] != "S" or fields[7] not in FEATURES or fields[8] != iso:
                    continue
                ident, name, ascii_name, aliases, lat, lon = fields[:6]
                for alias in (name, ascii_name, *aliases.split(",")):
                    label = norm(alias)
                    labels = [label]
                    # Preserve the full proper name when the local form puts the institution type first.
                    prefix = re.fullmatch(r"(?:universite|universidad|universidade) (?:de |du |d')?(.+)", label)
                    if fields[7] == "UNIV" and prefix:
                        labels.append(prefix[1] + " university")
                    for key in labels:
                        if FACILITY.search(key) and set(key.split()) - GENERIC and len(key) >= 10:
                            index.setdefault(key, {})[ident] = (name, float(lat), float(lon))
        return index
    except (URLError, OSError, zipfile.BadZipFile, KeyError) as exc:
        log(f"  ! {iso} 시설 지명 조회 실패 ({exc})")
        return {}


def named_facility(title, descriptions, index):
    # Only locative/delivery roles name the recipient. A coordinating university,
    # a future facility of the same name, or a branch campus needs separate evidence.
    if re.search(r"\b(?:campus|campuses|branch|nationwide)\b", title, re.I):
        return {}
    texts = [norm(s) for text in (title, *descriptions) for s in re.split(r"[;\n]|(?<=[.!?])\s+", text)
             if not re.search(r"\b(?:visit|meeting|workshop|conference|survey|partnered|coordinated|trained abroad)\b",s,re.I)]
    found = {}
    for alias, entries in index.items():
        if not any(alias in t for t in texts):
            continue
        pattern = (r"\b(?:at|within|education environment (?:in|for)|renovation of|modernization of|modernisation of|upgrading of|"
                   r"equipment for|capacity (?:building )?of|strengthening) (?:the )?"
                   + re.escape(alias) + r"(?=$|[.,;:(]|\s+(?:operations|in|through|under|by|for|to)\b|\s*\()")
        if not any(re.search(pattern, t) for t in texts):
            continue
        if len(entries) != 1:
            return {}
        found.update(entries)
    if len(found) != 1:
        return {}
    ident, (name, lat, lon) = next(iter(found.items()))
    return {"coverage":"site", "place":name, "place_en":name,
            "source_coord":{"place":name,"lat":lat,"lon":lon,"source":"GeoNames "+ident,"publisher":"GeoNames"},
            "_location_evidence":"사업의 시설명·수혜 역할과 일치한 GeoNames 시설 · "+name,
            "scope_sources":["https://www.geonames.org/"+ident]}
