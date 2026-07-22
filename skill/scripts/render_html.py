"""layout.json → 인라인 SVG HTML.

    python render_html.py --layout layout.json --out map.html

배치 규칙은 전부 layout.py 가 정한다. 여기서는 좌표를 그대로 그릴 뿐이니
위치를 재계산하지 말 것 — PPTX 출력과 갈라진다.
좌표계는 1 단위 = 1 인치, 글자 크기는 pt/72 인치.
"""
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

from common import SKILL_DIR, design_tokens, log, read_json

PT = 1.0 / 72.0


def _data_uri(png_path: str) -> str:
    """타일 배경을 data URI 로 박아 HTML 한 장으로 완결시킨다 (PDF·PPTX 변환에 필요)."""
    import base64
    return "data:image/png;base64," + base64.b64encode(
        Path(png_path).read_bytes()).decode()


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def path_of(rings: list) -> str:
    out = []
    for r in rings:
        if len(r) < 2:
            continue
        out.append("M" + " L".join(f"{p[0]:.4f},{p[1]:.4f}" for p in r) + "Z")
    return " ".join(out)


# ─────────────────────────────── 조각별 ───────────────────────────────

def draw_map(L: dict, tok: dict) -> str:
    m, ms = L["map"], tok["map_style"]
    # 배경·클립은 프레임이 아니라 **실제 그림 영역**에 맞춘다 (빈 회색 띠 제거)
    f = m.get("content") or m["frame"]
    tiles = m.get("tiles")
    s = [f'<clipPath id="mapclip"><rect x="{f["x"]:.4f}" y="{f["y"]:.4f}" '
         f'width="{f["w"]:.4f}" height="{f["h"]:.4f}"/></clipPath>',
         f'<g clip-path="url(#mapclip)">']

    if tiles:
        # OSM 벡터 타일 배경(도로·하천). 국토 밖은 마스크로 눌러 대상국만 밝게 남긴다 —
        # 원본 샘플의 "흰 국토 + 회색 주변국" 표현이 이것이다.
        s.append(f'<image x="{f["x"]:.4f}" y="{f["y"]:.4f}" width="{f["w"]:.4f}" '
                 f'height="{f["h"]:.4f}" preserveAspectRatio="none" '
                 f'href="{_data_uri(tiles["png"])}"/>')
        outer = (f'M{f["x"]:.4f},{f["y"]:.4f} H{f["x"]+f["w"]:.4f} '
                 f'V{f["y"]+f["h"]:.4f} H{f["x"]:.4f} Z')
        s.append(f'<path d="{outer} {path_of(m["land"])}" fill-rule="evenodd" '
                 f'fill="{ms["neighbor"]}" fill-opacity="{ms.get("mask_opacity", 0.8)}"/>')
    else:
        s.append(f'<rect x="{f["x"]:.4f}" y="{f["y"]:.4f}" width="{f["w"]:.4f}" '
                 f'height="{f["h"]:.4f}" fill="{ms["neighbor"]}"/>')
        for n in m["neighbors"]:
            s.append(f'<path d="{path_of(n["rings"])}" fill="{ms["neighbor"]}" '
                     f'stroke="#D9D4D0" stroke-width="0.004"/>')
        s.append(f'<path d="{path_of(m["land"])}" fill="{ms["land"]}"/>')
        if m.get("rivers"):
            d = " ".join("M" + " L".join(f"{p[0]:.4f},{p[1]:.4f}" for p in r)
                         for r in m["rivers"] if len(r) > 1)
            s.append(f'<path d="{d}" fill="none" stroke="{ms["river"]}" '
                     f'stroke-width="{ms["river_w"]*PT:.5f}" stroke-linecap="round"/>')
        if m.get("lakes"):
            s.append(f'<path d="{path_of(m["lakes"])}" fill="{ms["lake"]}" '
                     f'stroke="{ms["river"]}" stroke-width="{0.3*PT:.5f}"/>')
        if m.get("admin2"):
            s.append(f'<path d="{path_of(m["admin2"])}" fill="none" '
                     f'stroke="{ms["admin2"]}" stroke-width="{ms["admin2_w"]*PT:.5f}" '
                     f'stroke-dasharray="{ms["admin2_dash"].replace(",", " ")}" '
                     f'opacity="0.85"/>')

    for n in m["neighbors"]:                       # 주변국 이름 (샘플의 CHINA/INDIA)
        lab = _neighbor_label(n, f)
        if lab:
            s.append(lab)
    # 국경 — 타일 배경이든 벡터든 대상국 윤곽은 또렷해야 한다
    s.append(f'<path d="{path_of(m["land"])}" fill="none" stroke="{ms["border"]}" '
             f'stroke-width="{ms["border_w"]*PT:.5f}" stroke-linejoin="round"/>')
    # dasharray 는 user unit(=인치) 이다. "3,2" 로 쓰면 3인치 대시가 되어 선이 사라진다.
    if m.get("admin1"):
        s.append(f'<path d="{path_of(m["admin1"])}" fill="none" '
                 f'stroke="{ms["admin1"]}" stroke-width="{ms["admin1_w"]*PT:.5f}" '
                 f'stroke-dasharray="{ms["admin1_dash"].replace(",", " ")}" '
                 f'opacity="0.7"/>')

    # 주 이름은 사업 마커를 피한다 — 핀을 덮으면 지도의 본래 목적이 가려진다.
    # 반대로 **도시 이름은 마커를 피하지 않는다.** 사업이 있는 도시(카트만두·포카라)의
    # 이름이야말로 꼭 보여야 하고, 라벨은 점 오른쪽으로 비껴 찍혀 겹치지도 않는다.
    marker_boxes = [(mk["x"] - 0.13, mk["y"] - 0.13, mk["x"] + 0.13, mk["y"] + 0.13)
                    for mk in L.get("markers", [])]
    placed = []
    al = ms["admin1_label"]
    for a in m.get("admin1_labels", []):
        if a.get("area", 1) < al["min_area"]:
            continue
        w = len(a["name"]) * (al["size"] * PT * 0.62 + al["tracking"])
        # 중심이 막히면 위아래로 조금씩 비켜본다. 그래도 안 되면 생략한다.
        spot = None
        for dx, dy in ((0, 0), (0, -0.17), (0, 0.17), (-0.22, 0), (0.22, 0),
                       (0, -0.32), (0, 0.32)):
            x, y = a["x"] + dx, a["y"] + dy
            if not (f["x"] + 0.15 < x < f["x"] + f["w"] - 0.15
                    and f["y"] + 0.1 < y < f["y"] + f["h"] - 0.1):
                continue
            box = (x - w / 2, y - 0.06, x + w / 2, y + 0.06)
            if not any(_overlap(box, b) for b in placed + marker_boxes):
                spot = (x, y, box)
                break
        if not spot:
            continue
        x, y, box = spot
        placed.append(box)
        s.append(f'<text x="{x:.4f}" y="{y:.4f}" font-size="{al["size"]*PT:.5f}" '
                 f'fill="{al["color"]}" text-anchor="middle" font-weight="700" '
                 f'letter-spacing="{al["tracking"]:.4f}" paint-order="stroke" '
                 f'stroke="#FFFFFF" stroke-width="0.014">{esc(a["name"])}</text>')

    cl = ms["city_label"]
    shown = 0
    for c in m.get("cities", []):
        if shown >= ms.get("city_max", 46):
            break
        if not (f["x"] + 0.05 < c["x"] < f["x"] + f["w"] - 0.4
                and f["y"] + 0.05 < c["y"] < f["y"] + f["h"] - 0.05):
            continue
        w = len(c["name"]) * cl["size"] * PT * 0.55
        box = (c["x"] - 0.02, c["y"] - 0.045, c["x"] + 0.05 + w, c["y"] + 0.045)
        if any(_overlap(box, b) for b in placed):
            continue
        placed.append(box)
        shown += 1
        s.append(f'<circle cx="{c["x"]:.4f}" cy="{c["y"]:.4f}" r="{ms["city_dot_r"]:.4f}" '
                 f'fill="#FFFFFF" stroke="{ms["city_dot"]}" stroke-width="0.006"/>')
        s.append(f'<text x="{c["x"]+0.045:.4f}" y="{c["y"]+0.028:.4f}" '
                 f'font-size="{cl["size"]*PT:.5f}" fill="{cl["color"]}" '
                 f'paint-order="stroke" stroke="#FFFFFF" stroke-width="0.016">'
                 f'{esc(c["name"])}</text>')
    s.append("</g>")
    return "\n".join(s)


def _overlap(a, b) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _neighbor_label(n: dict, f: dict):
    """주변국 이름(샘플의 CHINA/INDIA).

    전체 중심은 대부분 화면 밖이라 쓸 수 없다. **프레임 안에 들어온 점들만** 모아
    그 중심에 찍는다."""
    x0, y0 = f["x"] + 0.35, f["y"] + 0.28
    x1, y1 = f["x"] + f["w"] - 0.35, f["y"] + f["h"] - 0.28
    inside = [p for r in n["rings"] for p in r if x0 < p[0] < x1 and y0 < p[1] < y1]
    if len(inside) < 3 or not n.get("name"):
        return None
    x = sum(p[0] for p in inside) / len(inside)
    y = sum(p[1] for p in inside) / len(inside)
    return (f'<text x="{x:.4f}" y="{y:.4f}" font-size="{9.0*PT:.5f}" fill="#C4BEB9" '
            f'text-anchor="middle" letter-spacing="0.025">{esc(n["name"])}</text>')


def draw_leaders(L: dict, tok: dict) -> str:
    """꺾은선 지시선. 좌측열은 카드 열을 수평으로 빠져나온 뒤 꺾인다(layout._leader)."""
    c = tok["color"]["leader"]
    w = tok["leader"]["w_pt"] * PT
    out = []
    for ld in L["leaders"]:
        pts = ld.get("points") or [ld["from"], ld["to"]]
        d = " ".join(f"{p[0]:.4f},{p[1]:.4f}" for p in pts)
        out.append(f'<polyline points="{d}" fill="none" stroke="{c}" '
                   f'stroke-width="{w:.5f}" stroke-linejoin="round"/>')
    return "\n".join(out)


def draw_markers(L: dict, tok: dict) -> str:
    mk, col = tok["marker"], tok["color"]
    out = []
    for m in L["markers"]:
        if m["kind"] == "area":
            out.append(f'<circle cx="{m["x"]:.4f}" cy="{m["y"]:.4f}" '
                       f'r="{mk["area"]["d"]/2:.4f}" fill="none" '
                       f'stroke="{col["area_ring"]}" '
                       f'stroke-width="{mk["area"]["line_w"]*PT:.5f}"/>')
        out.append(f'<circle cx="{m["x"]:.4f}" cy="{m["y"]:.4f}" '
                   f'r="{mk["point"]["d"]/2:.4f}" fill="{col["pin"]}"/>')
    return "\n".join(out)


def draw_cards(L: dict, tok: dict) -> str:
    cd, col = tok["card"], tok["color"]
    bd = cd["badge"]
    out = []
    for c in L["cards"]:
        x, y = c["x"], c["y"]
        out.append(f'<text x="{x:.4f}" y="{y + cd["place"]["h"]*0.72:.4f}" '
                   f'font-size="{cd["place"]["size"]*PT:.5f}" font-weight="700" '
                   f'fill="{col["heading"]}" paint-order="stroke" stroke="#FFFFFF" '
                   f'stroke-width="{0.026:.4f}" stroke-linejoin="round">{esc(c["place"])}</text>')
        # 분야 배지
        bx = x + bd["dx"]
        for k in c["badges"]:
            by = y + bd["dy"]
            out.append(f'<rect x="{bx:.4f}" y="{by:.4f}" width="{bd["w"]:.4f}" '
                       f'height="{bd["h"]:.4f}" fill="{col["badge_bg"]}"/>')
            out.append(f'<text x="{bx + bd["w"]/2:.4f}" y="{by + bd["h"]*0.76:.4f}" '
                       f'font-size="{bd["size"]*PT:.5f}" fill="{col["badge_fg"]}" '
                       f'text-anchor="middle" font-weight="700">{esc(_sym(k))}</text>')
            bx += bd["w"] + bd["gap"]
        # 사업명 — 지시선이 글자를 관통하므로 흰 테두리를 깔아 가독성을 지킨다
        tx = x + cd["name"]["dx"]
        ty = y + cd["name"]["dy"] + c["line_h"] * 0.75
        for i, line in enumerate(c["lines"]):
            lx = tx if i == 0 else x + cd["name"]["dx"]
            out.append(f'<text x="{lx:.4f}" y="{ty:.4f}" font-size="{c["font"]*PT:.5f}" '
                       f'fill="{col["body"]}" paint-order="stroke" stroke="#FFFFFF" '
                       f'stroke-width="{0.022:.4f}" stroke-linejoin="round">{esc(line)}</text>')
            ty += c["line_h"]
    return "\n".join(out)


_SYMS = {"E": "E", "H": "H", "G": "G", "A": "A", "T": "…"}


def _sym(k: str) -> str:
    return _SYMS.get(k, k)


def draw_title(L: dict, tok: dict) -> str:
    t, col = tok["title"], tok["color"]
    p, b = t["pin"], t["box"]
    ko, en = L["country"]["ko"], L["country"]["en"]
    roman = _roman(L.get("index", 1))
    size = t["text"]["size_ko"] * PT
    out = [
        f'<rect x="{b["x"]:.4f}" y="{b["y"]:.4f}" width="{b["w"]:.4f}" height="{b["h"]:.4f}" '
        f'fill="none" stroke="{col["region_tab"]}" stroke-width="{1.2*PT:.5f}"/>',
        # 로마숫자 핀 — 위는 원, 아래는 꼭짓점
        f'<path d="M{p["x"]+p["w"]/2:.4f},{p["y"]+p["h"]:.4f} '
        f'L{p["x"]:.4f},{p["y"]+p["h"]*0.52:.4f} '
        f'A{p["w"]/2:.4f},{p["w"]/2:.4f} 0 1 1 {p["x"]+p["w"]:.4f},{p["y"]+p["h"]*0.52:.4f} Z" '
        f'fill="{col["region_tab"]}"/>',
        f'<text x="{p["x"]+p["w"]/2:.4f}" y="{p["y"]+p["h"]*0.48:.4f}" '
        f'font-size="{8.98*PT:.5f}" fill="#FFFFFF" text-anchor="middle">{roman}</text>',
    ]
    if L["lang"] == "ko":
        out.append(f'<text x="{b["x"]+t["text"]["dx"]:.4f}" y="{b["y"]+b["h"]*0.72:.4f}" '
                   f'font-size="{size:.5f}" fill="{col["heading"]}">{esc(ko)}'
                   f'<tspan font-size="{t["text"]["size_en"]*PT:.5f}" dx="0.06">{esc(en)}</tspan></text>')
    else:
        out.append(f'<text x="{b["x"]+t["text"]["dx"]:.4f}" y="{b["y"]+b["h"]*0.72:.4f}" '
                   f'font-size="{size:.5f}" fill="{col["heading"]}">{esc(en)}</text>')
    return "\n".join(out)


def _roman(n: int) -> str:
    vals = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out or "I"


def draw_region_tab(L: dict, tok: dict) -> str:
    if not L.get("region"):
        return ""
    r, col = tok["region_tab"], tok["color"]
    cx, cy = r["x"] + r["w"] / 2, r["y"] + r["h"] / 2
    return (f'<rect x="{r["x"]:.4f}" y="{r["y"]:.4f}" width="{r["w"]:.4f}" '
            f'height="{r["h"]:.4f}" fill="{col["region_tab_bg"]}"/>'
            f'<text x="{cx:.4f}" y="{cy:.4f}" font-size="{r["size"]*PT:.5f}" '
            f'fill="{col["region_tab"]}" text-anchor="middle" '
            f'transform="rotate(90 {cx:.4f} {cy:.4f})">{esc(L["region"])}</text>')


def draw_legend(L: dict, tok: dict) -> str:
    """세로 5칸. 항목마다 글자 수가 달라(교육 2자 ↔ 기술환경에너지 7자) 고정 간격을
    쓰면 겹친다. 실측 세로 블록 2.33in 안에 들어가도록 글자 크기를 맞춘다."""
    lg, col = L["legend"], tok["color"]
    en = L["lang"] == "en"
    fs = lg["size"] * PT
    gap = 0.09
    # 한글은 글자를 세로로 쌓고(한 글자 = 1행), 영문은 통째로 90° 회전시킨다.
    # 영문을 글자 단위로 쌓으면 'Education' 이 세로 낱자로 흩어져 읽히지 않는다.
    def label_h(s):
        return len(s) * fs * (0.52 if en else 1.0)

    total = sum(lg["swatch"] + label_h(i["label"]) + gap for i in lg["items"])
    avail = tok["canvas"]["h_in"] - lg["y0"] - 0.42
    if total > avail:
        fixed = len(lg["items"]) * (lg["swatch"] + gap)
        fs *= max(0.5, (avail - fixed) / max(total - fixed, 1e-6))

    out, y = [], lg["y0"]
    for it in lg["items"]:
        cx = lg["x"] + lg["swatch"] / 2
        out.append(f'<rect x="{lg["x"]:.4f}" y="{y:.4f}" width="{lg["swatch"]:.4f}" '
                   f'height="{lg["swatch"]:.4f}" fill="{col["badge_bg"]}"/>')
        out.append(f'<text x="{cx:.4f}" y="{y+lg["swatch"]*0.78:.4f}" '
                   f'font-size="{lg["size"]*PT:.5f}" fill="{col["badge_fg"]}" '
                   f'text-anchor="middle" font-weight="700">{esc(it["symbol"])}</text>')
        ly = y + lg["swatch"] + fs * 0.6
        if en:
            out.append(f'<text x="{cx:.4f}" y="{ly:.4f}" font-size="{fs:.5f}" '
                       f'fill="{col["body"]}" transform="rotate(90 {cx:.4f} {ly:.4f})">'
                       f'{esc(it["label"])}</text>')
            ly += label_h(it["label"])
        else:
            ly += fs * 0.4
            for ch in it["label"]:
                if ch == " ":
                    ly += fs * 0.5
                    continue
                out.append(f'<text x="{cx:.4f}" y="{ly:.4f}" font-size="{fs:.5f}" '
                           f'fill="{col["body"]}" text-anchor="middle">{esc(ch)}</text>')
                ly += fs
        y = ly + gap
    pn = lg["page_num"]
    out.append(f'<text x="{pn["x"]:.4f}" y="{pn["y"]:.4f}" font-size="{pn["size"]*PT:.5f}" '
               f'fill="{col["body"]}">{L.get("index", 1)}</text>')
    return "\n".join(out)


def draw_notes(L: dict, tok: dict) -> str:
    if not L.get("notes"):
        return ""
    col = tok["color"]
    mode, lay = L["mode"], tok["layout"][L["mode"]]
    if mode == "A":
        x, y = lay["bottom_row"]["x0"], lay["bottom_row"]["y"] - 0.16
    else:
        x, y = lay["right_col"]["x"], lay["right_col"]["y1"] + 0.16
    return (f'<text x="{x:.4f}" y="{y:.4f}" font-size="{7.0*PT:.5f}" '
            f'fill="{col["area_ring"]}" font-weight="700">'
            f'{esc(" ".join(L["notes"]))}</text>')


def draw_credit(L: dict, tok: dict) -> str:
    src = ("Natural Earth · geoBoundaries (CC BY) · GeoNames (CC BY)"
           + (" · 지도 타일 © OpenStreetMap contributors" if L["map"].get("tiles") else ""))
    return (f'<text x="0.22" y="{tok["canvas"]["h_in"]-0.16:.4f}" '
            f'font-size="{4.6*PT:.5f}" fill="#B4B4B4">{esc(src)}</text>')


# ─────────────────────────────── 조립 ───────────────────────────────

def render(L: dict, layers: str = "all") -> str:
    """layers='map' 이면 지도만 그린다 — PPTX 에 배경 이미지로 넣을 때 쓴다
    (카드·지시선·범례는 PPTX 도형으로 따로 만들어야 편집이 된다)."""
    tok = design_tokens()
    w, h = L["canvas"]["w"], L["canvas"]["h"]
    parts = [draw_map(L, tok)] if layers == "map" else [
        draw_map(L, tok),
        draw_leaders(L, tok),
        draw_markers(L, tok),
        draw_cards(L, tok),
        draw_title(L, tok),
        draw_region_tab(L, tok),
        draw_legend(L, tok),
        draw_notes(L, tok),
        draw_credit(L, tok),
    ]
    body = "\n".join(parts)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
           f'width="{w}in" height="{h}in" shape-rendering="geometricPrecision">\n'
           f'{body}\n</svg>')
    tpl = (SKILL_DIR / "assets" / "template.html").read_text(encoding="utf-8")
    title = f'{L["country"]["ko"]} 프로젝트맵' if L["lang"] == "ko" \
        else f'{L["country"]["en"]} Project Map'
    return tpl.replace("{{TITLE}}", esc(title)).replace("{{SVG}}", svg)


def main() -> int:
    ap = argparse.ArgumentParser(description="layout.json → SVG HTML")
    ap.add_argument("--layout", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--layers", default="all", choices=["all", "map"],
                    help="map = 지도만 (PPTX 배경용)")
    a = ap.parse_args()
    L = read_json(Path(a.layout))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(render(L, a.layers), encoding="utf-8")
    log(f'  → {a.out}  (카드 {len(L["cards"])} · 마커 {len(L["markers"])} '
        f'· 교차 {L.get("crossings", "?")})')
    return 0


if __name__ == "__main__":
    sys.exit(main())
