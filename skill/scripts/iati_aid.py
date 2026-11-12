"""Recover missing aid types from KOICA's published activity XML by exact identifier."""
import json
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from common import CACHE_DIR, fetch, log

URL = "https://www.odakorea.go.kr/opm/iati_act_KR-GOV-051.xml"
INDEX = CACHE_DIR / "koica-iati-activities-v3.json"


def read_index(path):
    codes = {}
    triangular = []
    reported_places = {}
    for _, node in ET.iterparse(path, events=("end",)):
        if node.tag != "iati-activity":
            continue
        key = (node.findtext("iati-identifier") or "").removeprefix("KR-GOV-010-")
        default = node.find("default-aid-type")
        if key.startswith("KR-GOV-051-") and default is not None and default.get("vocabulary", "1") == "1":
            fid = "iati:" + key
            codes[fid] = default.get("code", "")
            if codes[fid] in {"C01", "B03"}:
                locations = []
                for place in node.findall("location"):
                    name = (place.findtext("name/narrative") or "").strip()
                    if name:
                        locations.append(name)
                if locations:
                    reported_places[fid] = list(dict.fromkeys(locations))
            title = (node.findtext("title/narrative") or "").strip()
            if codes[fid] == "C01" and re.search(r"\btriangular\b|삼각협력", title, re.I):
                descriptions = " ".join(n.text or "" for n in node.findall("description/narrative"))
                dates = {d.get("type"): d.get("iso-date", "")[:4] for d in node.findall("activity-date")}
                triangular.append({"id":fid, "title":title, "description":descriptions,
                                   "start":dates.get("2") or dates.get("1"), "end":dates.get("4") or dates.get("3")})
        node.clear()
    if not codes:
        raise ValueError("KOICA XML 원조유형 없음")
    return {"codes":codes, "triangular":triangular, "places":reported_places}


def load_index(force=False):
    previous = {}
    if INDEX.exists():
        try:
            previous = json.loads(INDEX.read_text())
            if previous.get("codes") and not force and time.time() - INDEX.stat().st_mtime < 12 * 3600:
                return previous
        except (OSError, ValueError):
            pass
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=INDEX.parent) as tmp:
            index = read_index(fetch(URL, Path(tmp) / "activities.xml"))
            pending = Path(tmp) / "aid.json"
            pending.write_text(json.dumps(index))
            pending.replace(INDEX)
            return index
    except (OSError, ValueError, ET.ParseError) as exc:
        log(f"  ! KOICA IATI 원조유형 갱신 실패 ({exc}). 캐시 {len(previous.get('codes', {}))}건 사용")
        return previous


def load_codes(force=False):
    return load_index(force).get("codes", {})


def partner_candidates(activities, country, country_en, year, domestic_ids, confirmed_ids):
    """Suggest cross-border components only for review, without importing foreign pins or budgets."""
    terms = [re.escape(t) for t in (country, country_en) if t]
    mention = re.compile(r"(?<!\w)(?:" + "|".join(terms) + r")(?![A-Za-z])", re.I)
    groups = {}
    for activity in activities:
        title = re.sub(r"^\([^()]+\)\s*", "", activity["title"])
        start, end = activity["start"], activity["end"]
        if not (start and end and start.isdecimal() and end.isdecimal()) or year and not int(start) <= year <= int(end):
            continue
        key = (title.casefold(), start, end, activity["description"])
        groups.setdefault(key, []).append(activity)
    candidates = []
    for (_, start, end, description), group in groups.items():
        ids = sorted(a["id"] for a in group)
        if domestic_ids.intersection(ids) or confirmed_ids.intersection(ids):
            continue
        title = re.sub(r"^\([^()]+\)\s*", "", group[0]["title"])
        if mention.search(title + " " + description):
            candidates.append({"id":f"partner:{country}:{ids[0]}", "selected":False,
                               "name_ko":title, "name_en":title, "_period":f"{start}-{end}",
                               "coverage":"unknown", "place":"", "badges":[], "partner_activity_ids":ids,
                               "scope_sources":[URL], "_stage":"삼각협력 참여 확인"})
    return candidates
