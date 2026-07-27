"""oda-map-lab 에서 해당 국가의 KOICA 사업을 **전부** 끌어와 초안을 만든다.

    python fetch_projects.py --country 네팔 --out draft.json
    python fetch_projects.py --country 네팔 --year 2026 --all

사업명·기간·예산·분야 배지는 원문에서 자동으로 채운다. **지명(`place`)은 추정값이다** —
그룹 라벨을 그대로 옮긴 것이라 실제 대상지와 다를 수 있다(`룸비니` 그룹에 버르디야
사업이 들어 있는 식). 반드시 pick_projects.py 로 사람이 확인·수정해야 한다.

좌표는 `details.source` 를 함께 보고 선별한다. `국가(폴백)` 좌표는 버리고 지명에서
다시 풀지만, 도시·도시(음차)·IATI 원본(공식좌표)은 `source_coord` 로 보존한다.
여러 대상지를 한 점으로 묶은 그룹은 그 좌표만으로 모든 지점을 표현할 수 없으므로
resolve_places 가 각 지명을 다시 푼다.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

from common import CACHE_DIR, fetch, log, read_json, sector_map, write_json

SOURCE = "https://oda-map-lab.pages.dev/generated/map-base.json"
CACHE = CACHE_DIR / "map-base.json"
TTL_HOURS = 12          # 원천이 IATI 라 갱신이 잦지 않다. 그래도 하루 안에 한 번은 다시 받는다

# 국별협력사업(무상원조 프로젝트)의 성격 — 기본 선택 대상
MAIN_AID = "프로젝트 원조"
MAIN_BUDGET_KRW = 3_000_000_000     # 30억원. 봉사단·연수·소규모 민관협력과 가르는 선

# 원천 데이터의 지역 구분 → 슬라이드 지역 탭 표기 (샘플은 '아시아태평양')
REGION_TAB = {"아시아": "아시아태평양", "오세아니아": "아시아태평양",
              "중남미": "중남미", "아프리카": "아프리카",
              "중동": "중동·CIS", "동구 및 CIS": "동구·CIS"}
COUNTRY_FALLBACK = "국가(폴백)"


def load_source(force: bool = False) -> dict:
    stale = (not CACHE.exists()
             or time.time() - CACHE.stat().st_mtime > TTL_HOURS * 3600)
    if stale or force:
        log(f"  · 최신 데이터 확인 ({SOURCE})")
        fetch(SOURCE, CACHE, force=True)
    return read_json(CACHE)


def _badge(sector: str, sm: dict) -> str:
    """세부 분야명 → 배지 5종. sector_map.yaml 을 먼저 보고, 없으면 폴백 규칙."""
    if not sector:
        return ""
    for key, names in sm["sectors"].items():
        if sector in names:
            return key
    parts = [p.strip() for p in sector.split(",") if p.strip()]
    if len(parts) > 1:                       # 쉼표로 묶인 복합 분야는 조각별 다수결
        votes = [b for b in (_badge(p, sm) for p in parts) if b]
        if votes:
            return max(set(votes), key=votes.count)
    for rule in sm["fallback_rules"]:
        if re.search(rule["pattern"], sector):
            return rule["bucket"]
    return ""


def _place_guess(group_label: str) -> str:
    """그룹 라벨 → `place` 후보. `키체, 케찰테낭고` 처럼 쉼표로 묶인 건 `/` 로 잇는다."""
    s = re.sub(r"\s*\((진행|종료|국가)\)\s*$", "", group_label).strip()
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return "/".join(parts)


def _period(de: dict) -> str:
    a, b = (de.get("start") or "")[:4], (de.get("end") or "")[:4]
    return f"{a}-{b}" if a and b else (a or b or "")


def _trusted_source_coord(feature: dict, place: str) -> dict | None:
    """국가 중심점 폴백이 아닌 유효한 WGS84 좌표만 보존한다."""
    source = str(feature.get("details", {}).get("source") or "").strip()
    if not source or source == COUNTRY_FALLBACK:
        return None
    try:
        lat, lon = float(feature["lat"]), float(feature["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"place": place, "lat": round(lat, 6), "lon": round(lon, 6),
            "source": source}


def collect(country: str, year: int | None, include_all: bool,
            force: bool = False) -> dict:
    data = load_source(force)
    sm = sector_map()
    rows, seen = [], set()
    region = ""
    for f in data["features"]:
        if f.get("country") == country and f.get("details", {}).get("region"):
            region = REGION_TAB.get(f["details"]["region"], f["details"]["region"])
            break

    for f in data["features"]:
        if f.get("country") != country or not f.get("layer", "").startswith("project"):
            continue
        done = f["layer"].endswith("_done")
        other = "other" in f["layer"]
        m = re.search(r"·\s*(.+?)\s*$", f["name"]["ko"])
        place = _place_guess(m.group(1) if m else "")
        coord_source = str(f.get("details", {}).get("source") or "").strip()
        source_coord = _trusted_source_coord(f, place)
        for mem in f.get("members", []):
            de = mem.get("details", {})
            agency = str(de.get("agency") or "")
            if not include_all and "KOICA" not in agency:
                continue
            fid = mem.get("feature_id")
            if fid in seen:
                continue
            seen.add(fid)
            name_ko = html.unescape(mem["name"].get("ko") or "").strip()
            name_en = html.unescape(mem["name"].get("en") or "").strip()
            budget = de.get("budget") or 0
            per = _period(de)
            if year and per:
                s, e = per.split("-")[0], per.split("-")[-1]
                if s and e and not (int(s) <= year <= int(e)):
                    continue
            main = (de.get("aid") == MAIN_AID and "KOICA" in agency
                    and budget >= MAIN_BUDGET_KRW and not done and not other)
            row = {
                "selected": main,
                "place": place,
                "badges": [b for b in [_badge(de.get("sector", ""), sm)] if b],
                "name_ko": name_ko,
                "name_en": name_en,
                "_period": per,
                "_budget_krw": budget,
                "_aid": de.get("aid") or "",
                "_agency": agency,
                "_sector": de.get("sector") or "",
                "_stage": de.get("stage") or "",
                "_done": done,
                "_other": other,
                "_id": fid,
            }
            if coord_source:
                row["_coord_source"] = coord_source
            if source_coord:
                row["source_coord"] = dict(source_coord)
            rows.append(row)

    rows.sort(key=lambda r: (not r["selected"], -r["_budget_krw"]))
    log(f'[{country}] KOICA 사업 {len(rows)}건 수집 '
        f'· 국별협력사업 후보 {sum(1 for r in rows if r["selected"])}건 기본 선택')
    return {"country": country, "region": region, "year": year,
            "fetched_at": date.today().isoformat(),
            "source": SOURCE, "projects": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description="국가별 KOICA 사업 수집 (초안)")
    ap.add_argument("--country", required=True)
    ap.add_argument("--year", type=int, help="해당 연도에 진행 중인 사업만")
    ap.add_argument("--all", action="store_true", help="타기관 사업까지 포함")
    ap.add_argument("--force", action="store_true", help="캐시 무시하고 다시 받기")
    ap.add_argument("--out", default="draft.json")
    a = ap.parse_args()
    d = collect(a.country, a.year, a.all, a.force)
    write_json(Path(a.out), d, indent=1)
    log(f"  → {a.out}")
    log("  ! 지명(place)은 그룹 라벨에서 뽑은 **추정값**이다 — 사람이 확인해야 한다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
