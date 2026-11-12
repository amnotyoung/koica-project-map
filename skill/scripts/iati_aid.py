"""Recover missing aid types from KOICA's published activity XML by exact identifier."""
import json
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from common import CACHE_DIR, fetch, log

URL = "https://www.odakorea.go.kr/opm/iati_act_KR-GOV-051.xml"
INDEX = CACHE_DIR / "koica-iati-aid.json"


def read_codes(path):
    codes = {}
    for _, node in ET.iterparse(path, events=("end",)):
        if node.tag != "iati-activity":
            continue
        key = (node.findtext("iati-identifier") or "").removeprefix("KR-GOV-010-")
        default = node.find("default-aid-type")
        if key.startswith("KR-GOV-051-") and default is not None and default.get("vocabulary", "1") == "1":
            codes["iati:" + key] = default.get("code", "")
        node.clear()
    if not codes:
        raise ValueError("KOICA XML 원조유형 없음")
    return codes


def load_codes(force=False):
    previous = {}
    if INDEX.exists():
        try:
            previous = json.loads(INDEX.read_text())
            if previous and not force and time.time() - INDEX.stat().st_mtime < 12 * 3600:
                return previous
        except (OSError, ValueError):
            pass
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=INDEX.parent) as tmp:
            codes = read_codes(fetch(URL, Path(tmp) / "activities.xml"))
            pending = Path(tmp) / "aid.json"
            pending.write_text(json.dumps(codes))
            pending.replace(INDEX)
            return codes
    except (OSError, ValueError, ET.ParseError) as exc:
        log(f"  ! KOICA IATI 원조유형 갱신 실패 ({exc}). 캐시 {len(previous)}건 사용")
        return previous
