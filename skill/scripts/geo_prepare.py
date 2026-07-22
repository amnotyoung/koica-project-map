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

NE_BASE = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
           "master/geojson/ne_{detail}_{layer}.geojson")
NE_URL = NE_BASE.replace("{layer}", "admin_0_countries")
# 하천·호수는 국경 해상도와 무관하게 10m 를 쓴다.
# 50m 하천은 전 세계 462줄뿐이라 한 나라를 잘라내면 큰 강 몇 개밖에 안 남는다
# (네팔 기준 50m 9줄 vs 10m 22줄). 7MB 한 번 받아 캐시한다. 도로는 50MB 라 제외.
PHYSICAL_DETAIL = {"10m": "10m", "50m": "10m", "110m": "10m"}
GB_API = "https://www.geoboundaries.org/api/current/gbOpen/{iso3}/{lvl}/"
GEONAMES_URL = "https://download.geonames.org/export/dump/cities500.zip"

# 지도 단순화 허용오차(도). 국가 크기에 따라 조정된다.
SIMPLIFY_BASE = 0.004

# basemap.json 형식 버전. 레이어를 추가하면 올린다 — 오래된 캐시를 쓰면
# 하천·주 이름이 없는 밋밋한 지도가 조용히 나온다.
BASEMAP_VERSION = 2


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


# ─────────────────────────────── 자연 지물 ───────────────────────────────

def _lines_of(geom: dict) -> list:
    t, c = geom.get("type"), geom.get("coordinates") or []
    if t == "LineString":
        return [c]
    if t == "MultiLineString":
        return list(c)
    return []


def load_physical(layer: str, detail: str, view: list, tol: float, force: bool) -> list:
    """하천/호수를 화면 범위로 잘라온다. 원본 샘플의 물줄기 표현을 대신한다."""
    det = PHYSICAL_DETAIL.get(detail, "50m")
    url = NE_BASE.format(detail=det, layer=layer)
    try:
        gj = read_json(fetch(url, GEO_CACHE / f"ne_{det}_{layer}.geojson", force))
    except Exception as e:
        log(f"  · {layer}: 내려받기 실패 ({e.__class__.__name__})")
        return []
    out = []
    for f in gj.get("features", []):
        g = f.get("geometry")
        if not g or not bbox_intersects(bbox_of(g), view):
            continue
        if g["type"] in ("LineString", "MultiLineString"):
            for ln in _lines_of(g):
                if len(ln) >= 2:
                    out.append(round_ring(simplify(ln, tol)))
        else:
            out.extend(pack_geom(g, tol))
    return out


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

# 행정단위 일반명. 지도 라벨에는 고유명만 쓴다 (`NAVOIY REGION` → `NAVOIY`).
_ADMIN_TAIL = ("REGION", "PROVINCE", "DISTRICT", "ZONE", "OBLAST", "STATE",
               "GOVERNORATE", "PREFECTURE", "DEPARTMENT", "COUNTY", "MUNICIPALITY")
_ADMIN_HEAD = ("REPUBLIC OF ", "STATE OF ", "PROVINCE OF ", "AUTONOMOUS REPUBLIC OF ")


def short_admin_name(name: str) -> str:
    s = " ".join(name.upper().split())
    for h in _ADMIN_HEAD:
        if s.startswith(h):
            s = s[len(h):]
    parts = s.split()
    # 끝 단어가 일반명이고 앞에 고유명이 남을 때만 뗀다 (`PROVINCE 1` 은 그대로).
    if len(parts) > 1 and parts[-1] in _ADMIN_TAIL:
        parts = parts[:-1]
    return " ".join(parts) or s

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
    adm_render, adm2_render, adm1_labels, places = [], [], [], []
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
            cen = [round(v, 5) for v in centroid_of(g)]
            places.append({
                "name": nm, "level": lvl, "centroid": cen,
                "area": round(geom_area_deg2(g), 6),
                "bbox": [round(v, 4) for v in bbox_of(g)],
            })
            if lvl == "ADM1":
                # 원본 샘플의 주황색 주(州) 이름 — 지도 인상을 좌우하는 요소다
                adm1_labels.append({"name": short_admin_name(nm), "lon": cen[0],
                                    "lat": cen[1], "area": round(geom_area_deg2(g), 6)})
        if lvl in ("ADM1", "ADM2"):
            target = adm_render if lvl == "ADM1" else adm2_render
            for f in fs:
                if f.get("geometry"):
                    target.extend(pack_geom(f["geometry"], tol if lvl == "ADM1" else tol * 1.5))

    rivers = load_physical("rivers_lake_centerlines", detail, view, tol * 1.2, force)
    lakes = load_physical("lakes", detail, view, tol * 1.2, force)
    log(f"  · 하천 {len(rivers)}줄 · 호수 {len(lakes)}개")

    cities = load_cities(iso2, force) if iso2 else []
    log(f"  · 도시 {len(cities)}개 (GeoNames cities500)")

    basemap = {
        "v": BASEMAP_VERSION,
        "iso3": iso3, "iso2": iso2, "name_ko": name_ko, "name_en": name_en,
        "bbox": [round(v, 5) for v in bbox],
        "land": pack_geom(cf["geometry"], tol),
        "neighbors": neighbors,
        "admin1": adm_render,
        "admin2": adm2_render,
        "admin1_labels": sorted(adm1_labels, key=lambda a: -a["area"]),
        "rivers": rivers,
        "lakes": lakes,
        "cities": cities[:120],               # 지도 라벨용 — 렌더러가 충돌 회피로 추린다
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
