"""Identify the large map image on titled country pages of a local OOXML atlas."""
import posixpath
import re
import unicodedata
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from country_names import atlas_countries

P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _key(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if c.isalnum())


def _title_country(text, names):
    # Korean title boxes frequently use a different English exonym or split
    # the Korean word across runs. The English suffix must contain no Hangul.
    direct = names.get(_key(text))
    if direct:
        return direct
    bilingual = re.fullmatch(r"([가-힣·\s]+)\s*([A-Za-zÀ-ž][A-Za-zÀ-ž'’.\-\s]+)", text)
    if bilingual:
        iso = names.get(_key(bilingual[1]))
        if iso:
            names.setdefault(_key(bilingual[2]), iso)
            return iso
    return None


@lru_cache(maxsize=8)
def _pages(path, stamp, size, extra_names=()):
    names = {_key(n): c["iso3"] for c in atlas_countries()
             for n in (c["ko"], c["en"], *c["aliases"])}
    names.update(extra_names)
    result = defaultdict(dict)
    with ZipFile(path) as z:
        pres = ET.fromstring(z.read("ppt/presentation.xml"))
        links = {e.get("Id"):e.get("Target") for e in ET.fromstring(z.read("ppt/_rels/presentation.xml.rels"))}
        for page, slide_id in enumerate(pres.findall(f"{P}sldIdLst/{P}sldId"), 1):
            part = _target("ppt/presentation.xml", links[slide_id.get(R+"id")])
            slide = ET.fromstring(z.read(part))
            titles = {_title_country("".join(s.itertext()).strip(), names)
                      for shape in slide.iter(P+"sp") for s in shape.findall(P+"txBody")}
            titles.discard(None)
            if len(titles) != 1:
                continue
            country = titles.pop()
            folder, filename = posixpath.split(part)
            relpath = posixpath.join(folder, "_rels", filename+".rels")
            if relpath not in z.NameToInfo:
                continue
            images = {e.get("Id"):_target(part, e.get("Target")) for e in ET.fromstring(z.read(relpath))
                      if e.get("Type","").endswith("/image") and e.get("TargetMode") != "External"}
            candidates = []
            for shape in slide.iter():
                if shape.tag not in {P+"pic",P+"sp"}:
                    continue
                ext = shape.find(f"{P}spPr/{A}xfrm/{A}ext")
                fill = shape.find(P+"blipFill") if shape.tag == P+"pic" else shape.find(f"{P}spPr/{A}blipFill")
                if ext is None or fill is None:
                    continue
                blip = fill.find(A+"blip")
                target = images.get(blip.get(R+"embed")) if blip is not None else None
                if not target or target not in z.NameToInfo or Path(target).suffix.lower() not in {".gif",".png",".jpg",".jpeg"}:
                    continue
                # Ignore badges and point symbols. OOXML group coordinates may
                # be local; the dominant picture is selected by area on the page.
                w,h = int(ext.get("cx")),int(ext.get("cy"))
                if min(w,h) >= 914400 and w*h >= 4*914400**2:
                    candidates.append((w*h,target))
            if candidates:
                # In some books a transparent cutout sits over the full map.
                # Equal extents retain the first (underlying) image.
                target = max(candidates,key=lambda item:item[0])[1]
                result[country].setdefault(target,[]).append(page)
    return dict(result)


def _target(part, target):
    return target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(part),target))


def country_plate(deck, iso, aliases=()):
    stat = deck.stat()
    extra = tuple((_key(label),iso) for label in aliases if label)
    candidates = _pages(deck, stat.st_mtime_ns, stat.st_size, extra).get(iso,{})
    # Two genuinely different plates require an explicit choice of edition.
    return next(iter(candidates.items())) if len(candidates) == 1 else None
