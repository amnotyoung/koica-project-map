"""OSM 벡터 타일 → 배경 지도 이미지.

    python basemap_tiles.py --country 네팔 --out basemap.png

Natural Earth 는 세계지도용이라 한 나라를 확대하면 하천 몇 줄, 도로는 아예 없다.
oda-map-lab 이 쓰는 versatiles 타일(Shortbread 스키마)을 MapLibre 로 렌더해
도로·하천·지명 밀도를 원본 샘플 수준으로 끌어올린다.

**스타일은 여기서 직접 정의한다** — OSM 기본색(초록·베이지)이 아니라 design.md 의
KOICA 톤(흰 국토·연회색 배경·분홍 도로·파란 하천)으로 맞춘다.

투영은 Web Mercator 다. layout.Projection 과 같은 수식을 써야 핀이 어긋나지 않는다.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from common import GEO_CACHE, design_tokens, log, read_json

TILES = "https://tiles.versatiles.org/tiles/osm/{z}/{x}/{y}"
MAPLIBRE_JS = "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"
MAPLIBRE_CSS = "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css"
GLYPHS = "https://tiles.versatiles.org/assets/glyphs/{fontstack}/{range}.pbf"
TILE_SIZE = 512


# ─────────────────────────────── Web Mercator ───────────────────────────────

def merc_x(lon: float) -> float:
    return (lon + 180.0) / 360.0


def merc_y(lat: float) -> float:
    lat = max(min(lat, 85.05112878), -85.05112878)
    s = math.sin(math.radians(lat))
    return 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)


def merc_lat(y: float) -> float:
    return math.degrees(2 * math.atan(math.exp((0.5 - y) * 2 * math.pi)) - math.pi / 2)


def fit_view(bbox: list, w_px: float, h_px: float, pad: float = 0.04) -> dict:
    """bbox 를 w×h 픽셀에 채우는 center/zoom. MapLibre 와 같은 규약을 쓴다."""
    lon0, lat0, lon1, lat1 = bbox
    dlon, dlat = (lon1 - lon0) * pad, (lat1 - lat0) * pad
    lon0, lon1 = lon0 - dlon, lon1 + dlon
    lat0, lat1 = lat0 - dlat, lat1 + dlat
    x0, x1 = merc_x(lon0), merc_x(lon1)
    y0, y1 = merc_y(lat1), merc_y(lat0)          # y 는 위에서 아래로
    zx = math.log2(w_px / max(x1 - x0, 1e-12) / TILE_SIZE)
    zy = math.log2(h_px / max(y1 - y0, 1e-12) / TILE_SIZE)
    zoom = min(zx, zy)
    return {"zoom": zoom,
            "center": [(lon0 + lon1) / 2, merc_lat((y0 + y1) / 2)],
            "world_px": TILE_SIZE * (2 ** zoom)}


# ─────────────────────────────── 스타일 ───────────────────────────────

def style_json(ms: dict) -> dict:
    """Shortbread 스키마용 최소 스타일.

    **지명 라벨은 그리지 않는다.** 타일의 `name` 은 현지 문자(中文·देवनागरी)라
    KOICA 자료에 맞지 않고, 어떤 라벨을 남길지도 제어할 수 없다. 라벨은
    render_html 이 GeoNames·geoBoundaries 로 라틴 표기·충돌 회피까지 해서 얹는다.
    여기서는 **도로·하천·수면 같은 기하**만 가져온다 — 그게 Natural Earth 에 없던 것이다.
    """
    road = ms.get("road", "#EFC7C0")
    river = ms["river"]
    return {
        "version": 8,
        # symbol 레이어를 쓰지 않으므로 glyphs 는 필요 없지만, 스타일을 손볼 때
        # 텍스트를 켜면 없이는 통째로 백지가 되므로 남겨둔다.
        "glyphs": GLYPHS,
        "sources": {"v": {"type": "vector", "tiles": [TILES],
                          "minzoom": 0, "maxzoom": 14, "attribution": "© OpenStreetMap"}},
        "layers": [
            {"id": "bg", "type": "background",
             "paint": {"background-color": ms["neighbor"]}},
            {"id": "land", "type": "fill", "source": "v", "source-layer": "land",
             "paint": {"fill-color": ms.get("tile_land", "#FFFFFF")}},
            {"id": "ocean", "type": "fill", "source": "v", "source-layer": "ocean",
             "paint": {"fill-color": ms["lake"]}},
            {"id": "water", "type": "fill", "source": "v", "source-layer": "water_polygons",
             "paint": {"fill-color": ms["lake"]}},
            # 하천 — 원본 샘플의 파란 물줄기
            {"id": "river", "type": "line", "source": "v", "source-layer": "water_lines",
             "filter": ["in", ["get", "kind"], ["literal", ["river", "canal", "stream"]]],
             "paint": {"line-color": river,
                       "line-width": ["interpolate", ["linear"], ["zoom"],
                                      4, 0.5, 7, 1.1, 10, 2.2],
                       "line-opacity": 0.9}},
            # 도로 — 원본의 분홍 도로망
            {"id": "road-minor", "type": "line", "source": "v", "source-layer": "streets",
             "filter": ["in", ["get", "kind"], ["literal", ["secondary", "tertiary"]]],
             "paint": {"line-color": road,
                       "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.4, 9, 1.4],
                       "line-opacity": 0.8}},
            {"id": "road-major", "type": "line", "source": "v", "source-layer": "streets",
             "filter": ["in", ["get", "kind"],
                        ["literal", ["motorway", "trunk", "primary"]]],
             "paint": {"line-color": road,
                       "line-width": ["interpolate", ["linear"], ["zoom"], 4, 0.9, 9, 2.8]}},
            # 군 단위 경계 — 주 경계(admin_level 4)는 render_html 이 geoBoundaries 로 그린다
            {"id": "adm6", "type": "line", "source": "v", "source-layer": "boundaries",
             "filter": ["==", ["get", "admin_level"], 6],
             "paint": {"line-color": ms["admin2"], "line-width": 0.4,
                       "line-dasharray": [3, 3], "line-opacity": 0.55}},
        ],
    }


HTML = """<!doctype html><meta charset="utf-8">
<link href="{css}" rel="stylesheet">
<style>html,body{{margin:0;background:#fff}}#m{{width:{w}px;height:{h}px}}
 .maplibregl-control-container{{display:none}}</style>
<div id="m"></div>
<script src="{js}"></script>
<script>
const map = new maplibregl.Map({{
  container:'m', style:{style}, center:{center}, zoom:{zoom},
  attributionControl:false, interactive:false, fadeDuration:0,
  preserveDrawingBuffer:true
}});
// 타일이 다 그려지면 제목을 바꿔 렌더 완료를 알린다
map.on('idle', () => {{ document.title = 'MAP_READY'; }});
</script>
"""


def build_html(bbox: list, w_px: int, h_px: int, tok: dict) -> tuple[str, dict]:
    view = fit_view(bbox, w_px, h_px)
    html = HTML.format(css=MAPLIBRE_CSS, js=MAPLIBRE_JS, w=w_px, h=h_px,
                       style=json.dumps(style_json(tok["map_style"])),
                       center=json.dumps(view["center"]), zoom=view["zoom"])
    return html, view


def render(country: str, out: Path, w_px: int = 1600, h_px: int = 1100,
           scale: int = 2, detail: str = "50m") -> dict:
    import cdp
    import geo_prepare

    bp = GEO_CACHE / f"{country}_basemap.json" if len(country) == 3 else None
    if not (bp and bp.exists()):
        bp, _ = geo_prepare.build(country, detail, False)
    base = read_json(bp)
    tok = design_tokens()

    html_p = out.with_suffix(".html")
    html, view = build_html(base["bbox"], w_px, h_px, tok)
    html_p.parent.mkdir(parents=True, exist_ok=True)
    html_p.write_text(html, encoding="utf-8")

    # `--screenshot` 은 load 직후에 찍어 타일이 오기 전 백지가 된다 (cdp.py 참고)
    cdp.shot(html_p.resolve().as_uri(), out, w_px, h_px, scale,
             ready_js="document.title==='MAP_READY'")
    log(f'  · 타일 배경 {out.name} '
        f'({out.stat().st_size//1024}KB, zoom {view["zoom"]:.2f})')
    return {"view": view, "png": str(out), "w_px": w_px, "h_px": h_px,
            "bbox": base["bbox"], "iso3": base["iso3"]}


def main() -> int:
    ap = argparse.ArgumentParser(description="OSM 벡터 타일 → 배경 지도 PNG")
    ap.add_argument("--country", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1100)
    ap.add_argument("--scale", type=int, default=2)
    a = ap.parse_args()
    render(a.country, Path(a.out), a.width, a.height, a.scale)
    return 0


if __name__ == "__main__":
    sys.exit(main())
