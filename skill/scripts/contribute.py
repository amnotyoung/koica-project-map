"""정밀화한 사업 위치를 oda-map-lab 기여 파일로 내보낸다.

    python contribute.py --layout out/nepal_ko.layout.json --author "홍길동"

지도를 다 만들었다는 건 그 국가 사업들의 위치를 사람이 확인했다는 뜻이다.
그 좌표는 원천 데이터에서 `국가(폴백)`으로 남은 사업 지점을 정밀화한다.

**전송하지 않는다.** koica-contrib 규격 JSON 을 파일로 만들 뿐이고, 제출은
사용자가 직접 한다. 남의 서비스로 데이터를 보내는 일은 사람이 결정할 몫이다.

규격: https://oda-map-lab.pages.dev/generated/contributor-schema.json (schema_version 2)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

from common import CACHE_DIR, log, read_json, write_json

SCHEMA_URL = "https://oda-map-lab.pages.dev/generated/contributor-schema.json"
CONTRIBUTOR_PAGE = "https://oda-map-lab.pages.dev"
MAP_BASE = CACHE_DIR / "map-base.json"

# 같은 지점으로 볼 거리(도). 약 3km — 이보다 가까우면 이미 정확하다고 본다.
SAME_SPOT_DEG = 0.03


def _country_fallbacks(country: str) -> list:
    """원천 데이터에서 그 국가의 **국가 중심점 폴백** 지점들. 보정 대상이다."""
    if not MAP_BASE.exists():
        return []
    data = read_json(MAP_BASE)
    out = []
    for f in data["features"]:
        if f.get("country") != country or not f.get("layer", "").startswith("project"):
            continue
        if f.get("details", {}).get("source") != "국가(폴백)":
            continue
        m = re.search(r"·\s*(.+?)\s*\((진행|종료)\)\s*$", f["name"]["ko"])
        out.append({"label": (m.group(1) if m else f["name"]["ko"]).strip(),
                    "name": f["name"]["ko"], "lat": f.get("lat"), "lon": f.get("lon")})
    return out


def build(layout: dict, author: str, office: str = "",
          only_improved: bool = True) -> dict:
    country = layout["country"]["ko"]
    office = office or country
    fallbacks = _country_fallbacks(country)
    fb_labels = {f["label"]: f for f in fallbacks}

    points, skipped = [], 0
    seen = set()
    for card in layout["cards"]:
        for p in card.get("points", []):
            if p.get("lon") is None or p.get("lat") is None:
                continue
            key = (round(p["lat"], 5), round(p["lon"], 5), p["name"])
            if key in seen:
                continue
            seen.add(key)
            # 원천이 국가폴백으로 두고 있던 지점인가 — 그렇다면 보정 기여가 된다
            hit = None
            for lbl, fb in fb_labels.items():
                if lbl and (lbl in card["place"] or p["name"] in lbl):
                    hit = fb
                    break
            if only_improved and not hit:
                skipped += 1
                continue
            pt = {
                "id": f'skill-{int(time.time()*1000)}-{len(points)}',
                "createdAt": int(time.time() * 1000),
                "cat": "project_site",
                "name": p["name"],
                "lat": round(p["lat"], 6),
                "lon": round(p["lon"], 6),
                "office": office,
                "author": author,
                "proj_status": "ongoing",
                "donor": "koica",
                "project": card["text"],
                "note": (f'프로젝트맵 스킬 — 지명 「{p["name"]}」 을 '
                         f'{p.get("level", "")} 수준으로 해석'.strip()),
            }
            if hit:
                pt["corrects"] = {"name": hit["name"], "country": country}
            points.append(pt)

    return {"version": 1, "schema": "koica-contrib", "lang": "ko",
            "exportedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "submitter": {"office": office, "author": author},
            "points": points,
            "_skipped_already_precise": skipped}


def suggest(layout_path: Path, country: str, n_points: int, n_fallback: int) -> None:
    """지도 생성 뒤 보여줄 안내. 실제 제출은 사용자가 한다."""
    if not n_fallback:
        return
    log(f"\n  ── 위치 정보 기여 제안 ──")
    log(f"  {country} 사업 위치 {n_points}곳을 확인하셨습니다. 그중 {n_fallback}곳은")
    log(f"  oda-map-lab 에서 아직 **국가 중심점**으로만 표시되는 지점입니다.")
    log(f"  기여 파일을 만들려면:")
    log(f"    python scripts/contribute.py --layout {layout_path} --author \"이름\"")
    log(f"  (파일만 만듭니다. 제출은 {CONTRIBUTOR_PAGE} 에서 직접 하세요)")


def main() -> int:
    ap = argparse.ArgumentParser(description="정밀 좌표 → oda-map-lab 기여 파일")
    ap.add_argument("--layout", required=True, help="생성된 layout.json")
    ap.add_argument("--author", required=True, help="작성자 이름 (필수 항목)")
    ap.add_argument("--office", help="작성 사무소. 기본은 대상 국가")
    ap.add_argument("--all", action="store_true",
                    help="이미 정확한 지점까지 전부 포함")
    ap.add_argument("--out", help="출력 경로. 기본은 KOICA_<사무소>_<작성자>_<날짜>.json")
    a = ap.parse_args()

    layout = read_json(Path(a.layout))
    doc = build(layout, a.author, a.office or "", only_improved=not a.all)
    if not doc["points"]:
        log("  기여할 지점이 없습니다 (모두 이미 정확하거나 대상이 아님)")
        return 0

    s = doc["submitter"]
    safe = re.sub(r"[^\w가-힣]+", "", f'{s["office"]}_{s["author"]}') or "submit"
    out = Path(a.out) if a.out else Path(f"KOICA_{safe}_{date.today().isoformat()}.json")
    write_json(out, doc, indent=1)

    skipped = doc["_skipped_already_precise"]
    corrects = sum(1 for p in doc["points"] if "corrects" in p)
    tail = f" (이미 정확한 {skipped}곳 제외)" if skipped else ""
    log(f'  ✓ 기여 파일 {out} — 지점 {len(doc["points"])}곳{tail}')
    log(f"  보정 대상(국가폴백) {corrects}곳 포함")
    log(f"\n  제출은 직접 하세요 — {CONTRIBUTOR_PAGE} 의 수집폼에서 이 파일을 올리거나")
    log(f"  담당자에게 전달하면 관리자 승인 후 반영됩니다.")
    log(f"  ! 보내기 전에 파일을 열어 좌표와 작성자 정보를 확인하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
