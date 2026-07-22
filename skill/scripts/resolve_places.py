"""지명 → 좌표 해석.

    python resolve_places.py --country 네팔 --places 카트만두 바디바스 "바라/팔사/반케"
    python resolve_places.py --country 네팔 --input projects.json --out resolved.json

해석 순서
    1) gazetteer.json 사용자 확정값        (최우선 — 한 번 고치면 계속 재사용)
    2) GeoNames 도시  → 점(point)
    3) ADM3 시/면     → 점(point)
    4) ADM2 군 · ADM1 주 → 면(area, 초록 원)

한글 음차 지명은 hangul.loose_key 로 라틴 지명과 대조한다. 자세한 원리는 hangul.py 참고.
`kind` 를 입력에서 명시하면 그 값이 우선한다 (사업이 지역 전체를 다루면 area).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from common import CACHE_DIR, GEO_CACHE, log, norm, read_json, write_json
from hangul import full_ratio, loose_key, similarity

import geo_prepare

ACCEPT = 0.75      # 이 미만이면 미해석 처리
MARGIN = 0.06      # 1위가 2위(다른 지명)를 이만큼 못 이기면 모호 처리
GAZETTEER = CACHE_DIR / "gazetteer.json"

# 면 단위 사업을 가리키는 한글 행정 접미어. `딜리/리키사/에르메라/바우카우 주` 처럼
# 마지막에 한 번만 붙고 나열 전체에 걸린다. design.md 의 '원형 표시 지역' 규칙과 연결된다.
AREA_SUFFIX = re.compile(r"\s*(주|도|군|구|현|지역|일원|전역|전지역)\s*$")

LEVEL_KIND = {"city": "point", "ADM3": "point", "ADM2": "area", "ADM1": "area"}
LEVEL_ORDER = ["city", "ADM3", "ADM2", "ADM1"]


# ─────────────────────────────── 사전 로딩 ───────────────────────────────

def ensure_country(country: str, detail: str = "50m"):
    """basemap/places 캐시가 없으면 geo_prepare 로 만든다."""
    hits = sorted(GEO_CACHE.glob("*_places.json"))
    for p in hits:
        doc = read_json(p)
        if country.strip().upper() == doc["iso3"] or norm(country) == norm(doc["name_ko"]):
            return doc
    log(f"[{country}] 지리 캐시 없음 — geo_prepare 실행")
    _, pp = geo_prepare.build(country, detail, False)
    return read_json(pp)


def build_index(places_doc: dict) -> list:
    """(표기, 대표이름, 레벨, 경도, 위도) 후보 목록."""
    idx = []
    for c in places_doc.get("cities", []):
        idx.append((c["name"], c["name"], "city", c["lon"], c["lat"], c.get("pop", 0)))
        for a in c.get("alt", []):
            idx.append((a, c["name"], "city", c["lon"], c["lat"], c.get("pop", 0)))
    for a in places_doc.get("admin", []):
        lon, lat = a["centroid"]
        idx.append((a["name"], a["name"], a["level"], lon, lat, 0))
    return idx


def load_gazetteer() -> dict:
    return read_json(GAZETTEER) if GAZETTEER.exists() else {}


def save_gazetteer(g: dict) -> None:
    write_json(GAZETTEER, g, indent=2)


# ─────────────────────────────── 매칭 ───────────────────────────────

def match_one(query: str, aliases: list, index: list) -> dict:
    """한 지명에 대해 최적 후보를 고른다."""
    terms = [query] + list(aliases or [])
    scored = []
    for label, canon, level, lon, lat, pop in index:
        s = max(similarity(t, label) for t in terms)
        if s > 0:
            f = max(full_ratio(t, label) for t in terms)
            fc = max(full_ratio(t, canon) for t in terms)   # 별칭이 아닌 **본명** 유사도
            scored.append((s, LEVEL_ORDER.index(level), -pop, canon, level, lon, lat, f, fc))
    if not scored:
        return {"ok": False, "reason": "후보 없음"}
    # 점수 → 본명 유사도 → 도시 > ADM3 > ADM2 > ADM1 → 인구 순
    scored.sort(key=lambda t: (-t[0], -t[8], t[1], t[2]))
    best = scored[0]
    # 2위가 '다른 지명'일 때만 마진을 따진다.
    # 같은 곳이 발음기호·행정레벨만 달리해 중복되는 경우가 많아(Butwāl 도시 ↔ Butwal ADM3)
    # 표기가 아니라 느슨한 키로 동일성을 판단한다.
    bk = loose_key(best[3])
    runner = next((s for s in scored if loose_key(s[3]) != bk), None)
    # 우열은 **전체키**로 가린다. 골격(자음만)은 후보를 넓게 걷어오는 장치라
    # 서로 다른 지명이 같은 값을 갖기 쉽다 — Chiquimula/Chiquimulilla 둘 다 `chkmr`.
    # 전체키까지 같으면 **본명**으로 가른다 — `Santiago Chimaltenango` 는 별칭이
    # `Chimaltenango` 와 같지만 본명은 딴판이라 진짜 후보가 아니다.
    ambiguous = (runner is not None
                 and best[7] - runner[7] < MARGIN
                 and best[8] - runner[8] < MARGIN)
    if best[0] < ACCEPT:
        return {"ok": False, "reason": f"최고 유사도 {best[0]:.2f} < {ACCEPT}",
                "near": [{"name": s[3], "level": s[4], "score": round(s[0], 3)}
                         for s in scored[:5]]}
    if ambiguous:
        return {"ok": False, "reason": "후보가 모호함",
                "near": [{"name": s[3], "level": s[4], "score": round(s[0], 3)}
                         for s in scored[:5]]}
    # 같은 곳이 여러 행정레벨에 걸쳐 있는 경우를 레벨별로 하나씩 남긴다.
    # 레벨 조화(harmonize_levels)는 여기서만 고르므로 '다른 지명'이 섞이면 안 된다.
    same_levels = {}
    for s in scored:
        if loose_key(s[3]) != bk or s[4] in same_levels:
            continue
        same_levels[s[4]] = {"name": s[3], "level": s[4], "lon": s[5], "lat": s[6],
                             "score": round(s[0], 3)}
    return {"ok": True, "matched": best[3], "level": best[4],
            "kind": LEVEL_KIND[best[4]], "lon": best[5], "lat": best[6],
            "score": round(best[0], 3), "levels": same_levels,
            "alternatives": [{"name": s[3], "level": s[4], "lon": s[5], "lat": s[6],
                              "score": round(s[0], 3)}
                             for s in scored[1:6] if loose_key(s[3]) != bk][:3]}


def harmonize_levels(parts: list) -> None:
    """`바라/팔사/반케/버르디야` 처럼 여러 지역을 묶은 항목은 같은 행정레벨로 맞춘다.

    같은 이름이 군(ADM2)과 시(ADM3) 양쪽에 있으면 단독 해석은 시를 고르지만,
    나열된 형제들이 군이면 군으로 읽는 게 맞다. 좌표와 마커 종류가 함께 바뀐다."""
    ok = [p for p in parts if p.get("ok")]
    if len(ok) < 2:
        return
    levels = [p["level"] for p in ok]
    if len(set(levels)) == 1:
        return
    major = max(set(levels), key=lambda lv: (levels.count(lv), -LEVEL_ORDER.index(lv)))
    if levels.count(major) < 2:
        return
    for p in ok:
        if p["level"] == major:
            continue
        # `levels` 는 같은 지명의 다른 행정레벨만 담는다. 다른 지명으로 건너뛰지 않는다.
        alt = (p.get("levels") or {}).get(major)
        if alt:
            p.update({"matched": alt["name"], "level": major, "kind": LEVEL_KIND[major],
                      "lon": alt["lon"], "lat": alt["lat"], "harmonized": True})


def resolve(country: str, entries: list, detail: str = "50m") -> dict:
    doc = ensure_country(country, detail)
    index = build_index(doc)
    gaz = load_gazetteer()
    iso3 = doc["iso3"]
    out, unresolved = [], []

    for e in entries:
        if isinstance(e, str):
            e = {"place": e}
        raw = (e.get("place") or "").strip()
        forced = e.get("kind")
        # `~ 주`, `~ 지역`, `~ 전역` 은 면 단위 사업 신호 — 접미어를 떼고 조회한다
        body, n_sub = AREA_SUFFIX.subn("", raw)
        if n_sub and not forced:
            forced = "area"
        # `동티모르 전역` — 전국 사업. 지도에 마커도 지시선도 없이 카드만 놓는다(샘플 slide3).
        if n_sub and (not body.strip() or similarity(body, doc["name_ko"]) >= 0.9
                      or norm(body) == norm(doc["name_ko"])):
            out.append({"query": raw, "label": raw, "resolved": True,
                        "parts": [{"ok": True, "name": raw, "matched": doc["name_ko"],
                                   "level": "country", "kind": "nationwide",
                                   "lon": None, "lat": None, "score": 1.0,
                                   "source": "country"}]})
            continue

        parts = []
        for name in [p.strip() for p in body.split("/") if p.strip()]:
            key = f"{iso3}:{norm(name)}"
            if key in gaz:                       # 사용자 확정값 최우선
                g = dict(gaz[key])
                g.update({"name": name, "source": "gazetteer", "ok": True})
                parts.append(g)
                continue
            r = match_one(name, e.get("aliases"), index)
            r["name"] = name
            r["source"] = "auto"
            parts.append(r)
            if not r["ok"]:
                unresolved.append({"country": country, "place": name,
                                   "in": raw, **{k: r[k] for k in ("reason", "near") if k in r}})
        harmonize_levels(parts)
        if forced:
            for p in parts:
                if p.get("ok"):
                    p["kind"] = forced
        out.append({"query": raw, "label": raw, "parts": parts,
                    "resolved": all(p.get("ok") for p in parts) and bool(parts)})

    return {"country": country, "iso3": iso3, "places": out,
            "unresolved": unresolved,
            "stats": {"total": len(out),
                      "resolved": sum(1 for o in out if o["resolved"]),
                      "parts": sum(len(o["parts"]) for o in out)}}


# ─────────────────────────────── CLI ───────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="지명 → 좌표 해석")
    ap.add_argument("--country", required=True)
    ap.add_argument("--places", nargs="*", default=[], help="지명 목록 ('/' 로 복수 지역)")
    ap.add_argument("--input", help="지명/사업 JSON 파일 (list 또는 {projects:[...]})")
    ap.add_argument("--out", help="결과 JSON 경로")
    ap.add_argument("--detail", default="50m")
    ap.add_argument("--set", nargs=3, metavar=("PLACE", "LON", "LAT"),
                    help="지명 좌표를 gazetteer 에 확정 저장 (수정 반영용)")
    ap.add_argument("--set-kind", default=None, choices=["point", "area"],
                    help="--set 과 함께 마커 종류 지정")
    a = ap.parse_args()

    if a.set:
        doc = ensure_country(a.country, a.detail)
        place, lon, lat = a.set[0], float(a.set[1]), float(a.set[2])
        gaz = load_gazetteer()
        key = f'{doc["iso3"]}:{norm(place)}'
        gaz[key] = {"matched": place, "level": "manual",
                    "kind": a.set_kind or "point", "lon": lon, "lat": lat, "score": 1.0}
        save_gazetteer(gaz)
        print(f"저장: {key} → ({lon}, {lat}) {gaz[key]['kind']}")
        return 0

    entries = list(a.places)
    if a.input:
        data = read_json(Path(a.input))
        items = data.get("projects", data) if isinstance(data, dict) else data
        for it in items:
            if isinstance(it, str):
                entries.append(it)
            else:
                entries.append({"place": it.get("place") or it.get("지명") or "",
                                "aliases": it.get("aliases"), "kind": it.get("kind")})
    if not entries:
        ap.error("--places 또는 --input 중 하나가 필요합니다.")

    res = resolve(a.country, entries, a.detail)
    s = res["stats"]
    log(f'[{res["iso3"]}] 지명 {s["total"]}건 중 {s["resolved"]}건 해석 '
        f'({s["resolved"]/max(s["total"],1)*100:.0f}%)')
    for u in res["unresolved"]:
        near = ", ".join(f'{n["name"]}({n["score"]})' for n in u.get("near", [])[:3])
        log(f'  ✗ {u["place"]} — {u["reason"]}' + (f' | 근접: {near}' if near else ""))

    if a.out:
        write_json(Path(a.out), res, indent=2)
        log(f"  → {a.out}")
    else:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
