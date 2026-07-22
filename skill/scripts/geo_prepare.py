"""국가별 지도 배경 + 지명 사전을 준비한다.

    python geo_prepare.py --country 네팔
    python geo_prepare.py --country NPL --detail 10m --force

산출물 (skill/cache/geo/):
    <ISO3>_basemap.json  — 렌더링용 폴리곤 (국토·주변국·주 경계)
    <ISO3>_places.json   — 지명 해석용 (도시 + ADM1~3 이름·중심·면적)

출처: Natural Earth(퍼블릭 도메인) · geoBoundaries(CC BY) · GeoNames(CC BY)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import (GEO_CACHE, bbox_intersects, bbox_of, centroid_of, fetch,
                    geom_area_deg2, log, norm, outer_rings, read_json,
                    round_ring, simplify, unzip_member, write_json)

NE_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
          "master/geojson/ne_{detail}_admin_0_countries.geojson")
GB_API = "https://www.geoboundaries.org/api/current/gbOpen/{iso3}/{lvl}/"
GEONAMES_URL = "https://download.geonames.org/export/dump/cities500.zip"

# 지도 단순화 허용오차(도). 국가 크기에 따라 조정된다.
SIMPLIFY_BASE = 0.004


# ─────────────────────────────── Natural Earth ───────────────────────────────

def load_countries(detail: str, force: bool) -> list:
    dest = GEO_CACHE / f"ne_{detail}_admin_0_countries.geojson"
    fetch(NE_URL.format(detail=detail), dest, force)
    return read_json(dest)["features"]


def iso3_of(props: dict) -> str:
    for k in ("ISO_A3_EH", "ISO_A3", "ADM0_A3"):
        v = props.get(k)
        if v and v not in ("-99", "-1"):
            return v
    return ""


def find_country(features: list, query: str):
    """한글명 · 영문명 · ISO3 어느 쪽으로도 찾는다."""
    q = norm(query)
    qu = query.strip().upper()
    exact, partial = [], []
    for f in features:
        p = f["properties"]
        if iso3_of(p).upper() == qu:
            return f
        names = [p.get("NAME_KO"), p.get("NAME"), p.get("NAME_LONG"),
                 p.get("ADMIN"), p.get("NAME_EN")]
        for nm in names:
            if not nm:
                continue
            if norm(nm) == q:
                exact.append(f)
                break
            if q and q in norm(nm):
                partial.append(f)
                break
    if exact:
        return exact[0]
    if len(partial) == 1:
        return partial[0]
    if partial:
        opts = ", ".join(f'{f["properties"].get("NAME_KO")}({iso3_of(f["properties"])})'
                         for f in partial[:8])
        raise SystemExit(f"'{query}' 가 여러 국가와 일치합니다: {opts}")
    raise SystemExit(f"'{query}' 에 해당하는 국가를 찾지 못했습니다. 한글명·영문명·ISO3 로 지정하세요.")


# ─────────────────────────────── geoBoundaries ───────────────────────────────

def load_adm(iso3: str, lvl: str, force: bool):
    """ADM1~3 경계. 해당 레벨이 없는 국가도 많으므로 실패는 조용히 넘긴다."""
    meta_p = GEO_CACHE / f"{iso3}_{lvl}_meta.json"
    try:
        meta = json.loads(fetch(GB_API.format(iso3=iso3, lvl=lvl), meta_p, force)
                          .read_text(encoding="utf-8"))
    except Exception as e:
        log(f"  · {lvl}: 메타 조회 실패 ({e.__class__.__name__})")
        return []
    url = meta.get("simplifiedGeometryGeoJSON") or meta.get("gjDownloadURL")
    if not url:
        log(f"  · {lvl}: 경계 데이터 없음")
        return []
    try:
        gj = read_json(fetch(url, GEO_CACHE / f"{iso3}_{lvl}.geojson", force))
    except Exception as e:
        log(f"  · {lvl}: 다운로드 실패 ({e.__class__.__name__})")
        return []
    return gj.get("features", [])


# ─────────────────────────────── GeoNames ───────────────────────────────

def load_cities(iso2: str, force: bool) -> list:
    zp = fetch(GEONAMES_URL, GEO_CACHE / "cities500.zip", force)
    txt = unzip_member(zp, "cities500.txt", GEO_CACHE / "cities500.txt")
    out = []
    with open(txt, encoding="utf-8") as f:
        for line in f:
            r = line.split("\t")
            if len(r) < 15 or r[8] != iso2:
                continue
            out.append({
                "name": r[1],
                "alt": [a for a in r[3].split(",") if a][:6],
                "lon": round(float(r[5]), 5),
                "lat": round(float(r[4]), 5),
                "pop": int(r[14] or 0),
            })
    out.sort(key=lambda c: -c["pop"])
    return out


# ─────────────────────────────── 조립 ───────────────────────────────

def pack_geom(geom: dict, tol: float) -> list:
    return [round_ring(simplify(r, tol)) for r in outer_rings(geom)]


def build(country_q: str, detail: str, force: bool) -> tuple[Path, Path]:
    feats = load_countries(detail, force)
    cf = find_country(feats, country_q)
    p = cf["properties"]
    iso3 = iso3_of(p)
    iso2 = (p.get("ISO_A2_EH") or p.get("ISO_A2") or "").upper()
    name_ko = p.get("NAME_KO") or p.get("NAME")
    name_en = p.get("NAME_EN") or p.get("NAME") or p.get("ADMIN")
    bbox = bbox_of(cf["geometry"])
    span = max(bbox[2] - bbox[0], bbox[3] - bbox[1], 0.5)
    tol = SIMPLIFY_BASE * max(span / 5.0, 0.35)

    log(f"[{iso3}] {name_ko} / {name_en}  bbox={[round(v,2) for v in bbox]}")

    # 주변국 — 화면 밖으로 살짝 나가도록 여유 있게 잡는다
    pad = max(span * 0.45, 1.2)
    view = [bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad]
    neighbors = []
    for f in feats:
        if f is cf or iso3_of(f["properties"]) == iso3:
            continue
        if not bbox_intersects(bbox_of(f["geometry"]), view):
            continue
        rings = pack_geom(f["geometry"], tol * 1.6)
        if rings:
            np_ = f["properties"]
            # 지도 위 표기는 영문을 쓴다 — 한글 정식명은 너무 길다(중화인민공화국)
            neighbors.append({"name": (np_.get("NAME") or np_.get("NAME_EN") or "").upper(),
                              "name_ko": np_.get("NAME_KO"), "rings": rings})
    log(f"  · 주변국 {len(neighbors)}개")

    # 행정경계
    adm_render, places = [], []
    for lvl in ("ADM1", "ADM2", "ADM3"):
        fs = load_adm(iso3, lvl, force)
        if not fs:
            continue
        log(f"  · {lvl} {len(fs)}개")
        for f in fs:
            nm = (f["properties"].get("shapeName") or "").strip()
            g = f.get("geometry")
            if not nm or not g:
                continue
            places.append({
                "name": nm, "level": lvl,
                "centroid": [round(v, 5) for v in centroid_of(g)],
                "area": round(geom_area_deg2(g), 6),
                "bbox": [round(v, 4) for v in bbox_of(g)],
            })
        if lvl == "ADM1":
            for f in fs:
                if f.get("geometry"):
                    adm_render.extend(pack_geom(f["geometry"], tol))

    cities = load_cities(iso2, force) if iso2 else []
    log(f"  · 도시 {len(cities)}개 (GeoNames cities500)")

    basemap = {
        "iso3": iso3, "iso2": iso2, "name_ko": name_ko, "name_en": name_en,
        "bbox": [round(v, 5) for v in bbox],
        "land": pack_geom(cf["geometry"], tol),
        "neighbors": neighbors,
        "admin1": adm_render,
        "cities": [c for c in cities[:40]],   # 지도 라벨용 상위 도시
        "source": {"boundary": f"Natural Earth {detail}",
                   "admin": "geoBoundaries gbOpen", "places": "GeoNames cities500"},
    }
    places_doc = {"iso3": iso3, "name_ko": name_ko, "admin": places, "cities": cities}

    bp = write_json(GEO_CACHE / f"{iso3}_basemap.json", basemap)
    pp = write_json(GEO_CACHE / f"{iso3}_places.json", places_doc)
    log(f"  ✓ {bp.name} ({bp.stat().st_size//1024}KB) · {pp.name} ({pp.stat().st_size//1024}KB)")
    return bp, pp


def main() -> int:
    ap = argparse.ArgumentParser(description="국가별 지도 배경·지명 사전 준비")
    ap.add_argument("--country", required=True, help="한글명·영문명·ISO3 (예: 네팔, Nepal, NPL)")
    ap.add_argument("--detail", default="50m", choices=["10m", "50m", "110m"],
                    help="Natural Earth 해상도 (기본 50m)")
    ap.add_argument("--force", action="store_true", help="캐시 무시하고 다시 받기")
    a = ap.parse_args()
    build(a.country, a.detail, a.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
