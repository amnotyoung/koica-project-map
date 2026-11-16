"""Read a locally available atlas plate and register geographic overlays to its pixels."""
import hashlib
import math
import re
import subprocess
import unicodedata
from functools import lru_cache
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree.ElementTree import ParseError

from common import GEO_CACHE, REFERENCE_DIR, SKILL_DIR, log, read_json
from atlas_discovery import country_plate
from country_names import identity


def _source_deck(year, named):
    roots = list(dict.fromkeys([Path.cwd(), SKILL_DIR.parent]))
    if named:
        for root in roots:
            if (root / named).is_file():
                return root / named
    for root in roots:
        candidates = [p for p in root.glob("*.pptx") if not p.name.startswith("~$")
                      and re.search(r"(?<![0-9])"+year+r"(?![0-9])", p.name)
                      and re.search(r"프로젝트\s*맵|project[ _-]*map", unicodedata.normalize("NFC",p.stem), re.I)]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            log(f"  ! {year}년 원본 책자가 여러 개입니다. --atlas-deck으로 지정할 수 있습니다.")
            return None
    return None


@lru_cache(maxsize=8)
def _catalog(path, stamp):
    return read_json(path)


def extract(doc, outdir, deck=None):
    year = str(doc.get("year", ""))
    if not year.isdecimal() or doc.get("map_bbox") or doc.get("map_density") == "city":
        return None
    directory = REFERENCE_DIR / "atlas_backgrounds"
    registry = directory / (year + ".json")
    edition = read_json(registry) if registry.is_file() else {}
    deck = Path(deck) if deck is not None else _source_deck(year, edition.get("deck"))
    if deck is None:
        return None
    country = identity(doc["country"])
    aliases = ()
    if not country:
        from geo_prepare import find_country, iso3_of, load_countries
        props = find_country(load_countries("10m", False), doc["country"])["properties"]
        country = {"iso3":iso3_of(props), "iso2":props.get("ISO_A2_EH") or props.get("ISO_A2")}
        aliases = (doc["country"], props.get("NAME_KO"), props.get("NAME_EN"), props.get("ADMIN"))
    iso = country["iso3"]
    explicit = edition.get("countries", {}).get(iso)
    try:
        with ZipFile(deck) as z:
            if explicit and deck.name == edition.get("deck") and explicit["media"] in z.namelist():
                data = z.read(explicit["media"])
                if hashlib.sha256(data).hexdigest() == explicit["sha256"]:
                    return _save(explicit, data, outdir, iso, year, deck)
            found = country_plate(deck, iso, aliases)
            if not found:
                return None
            media, slides = found
            data = z.read(media)
    except (BadZipFile, KeyError, ParseError, OSError) as exc:
        log(f"  ! 원본 책자 읽기 실패 ({deck.name}): {exc}")
        return None

    digest = hashlib.sha256(data).hexdigest()
    catalog = directory / "plates.json"
    record = _catalog(catalog,catalog.stat().st_mtime_ns).get(digest) if catalog.is_file() else None
    activity_ids = {str(p.get("id") or p.get("_id") or "").split("@")[0]
                    for p in doc.get("projects", [])}
    if record and (record["country"] != iso or (record.get("activity_ids") and
                  not activity_ids.issubset(record["activity_ids"]))):
        log(f"  · {iso}: 원본 그림은 범용 배경지도로 등록되지 않았습니다. 공개 지도를 사용합니다.")
        return None
    if record and record.get("registration_year"):
        prior = directory / (str(record["registration_year"]) + ".json")
        spline = read_json(prior)["countries"][iso]
        if spline["sha256"] != digest:
            return None
        record = spline
    if record is None:
        from atlas_registration import register
        try:
            record = register(data, country["iso2"], GEO_CACHE / "cities500.txt")
        except (ImportError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
            log(f"  · {iso}: 원본 지도 기준점 확인 실패 ({exc})")
        if not record:
            log(f"  · {iso}: 원본 그림의 위치 정합을 확인할 수 없어 공개 지도를 사용합니다.")
            return None
    return _save(dict(record,media=media,slides=slides,sha256=digest), data, outdir, iso, year, deck)


def _save(plate, data, outdir, iso, year, deck):
    suffix = Path(plate["media"]).suffix.lower()
    dest = outdir / f"{iso}-{year}-{plate['sha256'][:12]}{suffix}"
    dest.write_bytes(data)
    return dict(plate, path=str(dest.resolve()), deck=deck.name)


class PlateProjection:
    """Map geodetic coordinates to the page with the plate's fitted thin-plate spline."""
    def __init__(self, plate, frame):
        self.plate = plate
        aspect = plate["width"] / plate["height"]
        w = min(frame["w"], frame["h"] * aspect)
        h = w / aspect
        self.frame = dict(x=frame["x"]+(frame["w"]-w)/2, y=frame["y"]+(frame["h"]-h)/2, w=w, h=h)

    def __call__(self, lon, lat):
        origin = self.plate["origin"]
        basis = []
        lon += 360 * round((origin[0]-lon)/360)
        for _,cx,cy,_,_ in self.plate.get("controls", []):
            r2 = (lon-cx)**2 + (lat-cy)**2
            basis.append(r2*math.log(max(r2,1e-12)))
        basis.extend((1,lon-origin[0],lat-origin[1]))
        u,v = [sum(a*b for a,b in zip(basis,coef)) for coef in self.plate["coefficients"]]
        f = self.frame
        return [round(f["x"]+u*f["w"],5),round(f["y"]+v*f["h"],5)]

    def rings(self, rings):
        return [[self(x,y) for x,y in ring] for ring in rings]


def covers_projects(plate, resolved):
    """Use the public map if a new site or any part of a project area falls outside the plate."""
    unit = PlateProjection(plate, dict(x=0, y=0, w=1, h=plate["height"]/plate["width"]))
    west,north,east,south = plate.get("usable_box", [0,0,1,1])
    for row in resolved["places"]:
        coords = [(p["lon"],p["lat"]) for p in row["parts"] if p.get("ok") and p.get("lon") is not None]
        for region in row.get("regions", []):
            for polygon in region["geometry"]:
                coords.extend(polygon[0])
        for x,y in coords:
            u,v = unit(x,y)
            if not (west <= u <= east and north <= v/unit.frame["h"] <= south):
                return False
    return True
