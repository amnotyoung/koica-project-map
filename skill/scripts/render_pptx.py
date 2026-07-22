"""layout.json → 편집 가능한 .pptx.

    python render_pptx.py --layout layout.json --out map.pptx
    python render_pptx.py --layout a.json b.json --out deck.pptx     # 여러 장

지도는 이미지로 넣고, **카드·배지·지시선·마커·범례는 도형**으로 만든다.
파워포인트에서 문구를 고치고 핀을 옮길 수 있어야 하기 때문이다.

좌표는 layout.json 을 그대로 쓴다. 여기서 배치를 다시 계산하면 HTML 출력과 갈라진다.
python-pptx 가 필요하다 — `skill/.venv/bin/python` 으로 실행할 것.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

from common import design_tokens, log, read_json

EMU_IN = 914400


def I(v: float) -> Emu:
    return Emu(int(round(v * EMU_IN)))


def rgb(hex_: str) -> RGBColor:
    return RGBColor.from_string(hex_.lstrip("#").upper())


# ─────────────────────────────── 지도 이미지 ───────────────────────────────

def map_image(layout_path: Path, tmp: Path, scale: int = 3) -> tuple[Path, dict]:
    """지도만 렌더해 PNG 로 굽고, 실제 그림 영역만 잘라낸다."""
    import export
    import render_html

    L = read_json(layout_path)
    tmp.mkdir(parents=True, exist_ok=True)
    html = tmp / "map_only.html"
    html.write_text(render_html.render(L, layers="map"), encoding="utf-8")
    png = export.to_png(html, tmp / "map_only.png", scale=scale)

    from PIL import Image
    c = L["map"].get("content") or L["map"]["frame"]
    px = 96 * scale
    im = Image.open(png)
    box = (max(int(c["x"] * px), 0), max(int(c["y"] * px), 0),
           min(int((c["x"] + c["w"]) * px), im.width),
           min(int((c["y"] + c["h"]) * px), im.height))
    out = tmp / "map_crop.png"
    im.crop(box).save(out)
    return out, c


# ─────────────────────────────── 도형 ───────────────────────────────

def textbox(slide, x, y, w, h, text, size, color, *, bold=False, align=PP_ALIGN.LEFT,
            font="맑은 고딕", anchor=MSO_ANCHOR.TOP, spacing=1.0):
    tb = slide.shapes.add_textbox(I(x), I(y), I(w), I(h))
    tf = tb.text_frame
    tf.word_wrap = False
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    lines = text if isinstance(text, list) else [text]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if spacing != 1.0:
            p.line_spacing = spacing
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.name = font
        r.font.color.rgb = rgb(color)
    return tb


def flatten(shape):
    """도형에 붙는 테마 스타일(<p:style>)을 떼어 그림자·광택을 없앤다.

    `shadow.inherit = False` 는 빈 <a:effectLst/> 만 넣는데, 뷰어에 따라
    테마의 effectRef 를 그대로 살려 그림자가 남는다. 원본 샘플은 평면이다.
    """
    el = shape._element.find(
        "{http://schemas.openxmlformats.org/presentationml/2006/main}style")
    if el is not None:
        shape._element.remove(el)
    return shape


def rect(slide, x, y, w, h, fill=None, line=None, line_w=0.75, shape=MSO_SHAPE.RECTANGLE):
    s = flatten(slide.shapes.add_shape(shape, I(x), I(y), I(w), I(h)))
    if fill:
        s.fill.solid()
        s.fill.fore_color.rgb = rgb(fill)
    else:
        s.fill.background()
    if line:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(line_w)
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    return s


def draw_slide(prs, L: dict, tok: dict, tmp: Path, layout_path: Path) -> None:
    col, cd = tok["color"], tok["card"]
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    # 1) 지도 — 이미지
    img, c = map_image(layout_path, tmp)
    slide.shapes.add_picture(str(img), I(c["x"]), I(c["y"]), I(c["w"]), I(c["h"]))

    # 2) 지시선 — 꺾은선은 직선 커넥터 여러 개로 나눠 그린다.
    #    python-pptx 의 ELBOW 커넥터는 꺾이는 지점을 지정할 수 없어 쓸 수 없다.
    for ld in L["leaders"]:
        pts = ld.get("points") or [ld["from"], ld["to"]]
        for p, q in zip(pts, pts[1:]):
            cn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                            I(p[0]), I(p[1]), I(q[0]), I(q[1]))
            cn.line.color.rgb = rgb(col["leader"])
            cn.line.width = Pt(tok["leader"]["w_pt"])

    # 3) 마커
    mk = tok["marker"]
    for m in L["markers"]:
        if m["kind"] == "area":
            d = mk["area"]["d"]
            rect(slide, m["x"] - d / 2, m["y"] - d / 2, d, d, None,
                 col["area_ring"], mk["area"]["line_w"], MSO_SHAPE.OVAL)
        d = mk["point"]["d"]
        rect(slide, m["x"] - d / 2, m["y"] - d / 2, d, d, col["pin"], None,
             shape=MSO_SHAPE.OVAL)

    # 4) 카드
    bd = cd["badge"]
    for card in L["cards"]:
        x, y = card["x"], card["y"]
        textbox(slide, x, y, cd["name"]["w"], cd["place"]["h"] * 1.4,
                card["place"], cd["place"]["size"], col["heading"], bold=True)
        bx = x + bd["dx"]
        for k in card["badges"]:
            by = y + bd["dy"]
            rect(slide, bx, by, bd["w"], bd["h"], col["badge_bg"])
            textbox(slide, bx, by, bd["w"], bd["h"], _sym(k), bd["size"],
                    col["badge_fg"], bold=True, align=PP_ALIGN.CENTER,
                    anchor=MSO_ANCHOR.MIDDLE)
            bx += bd["w"] + bd["gap"]
        # 줄바꿈은 layout.py 가 이미 정했다. 여기서 다시 흘리면 HTML 과 달라진다.
        textbox(slide, x + cd["name"]["dx"], y + cd["name"]["dy"] - 0.015,
                cd["name"]["w"], card["h"], card["lines"], card["font"],
                col["body"], spacing=0.92)
        # 대상지가 여럿인 면 단위 사업의 설명 — 그 카드 안에 붙는다 (원본과 동일)
        if card.get("note"):
            textbox(slide, x + cd["name"]["dx"],
                    y + cd["name"]["dy"] - 0.015 + len(card["lines"]) * card["line_h"],
                    cd["name"]["w"], card["line_h"] * 1.3, card["note"], card["font"],
                    col["area_ring"], bold=True)

    draw_title(slide, L, tok)
    draw_region_tab(slide, L, tok)
    draw_legend(slide, L, tok)
    


_SYMS = {"E": "E", "H": "H", "G": "G", "A": "A", "T": "…"}


def _sym(k: str) -> str:
    return _SYMS.get(k, k)


def map_pin(slide, p: dict, fill: str):
    """지도 핀 — 자유형으로 그린다.

    MSO_SHAPE.TEAR 를 회전시키면 기울어진 달걀이 나와 원본과 전혀 다르다.
    render_html.pin_path 와 같은 기하를 다각형으로 근사한다(작은 크기라 충분히 매끈).
    """
    import math

    import render_html as rh
    cx, cy, r, tip = rh.pin_geometry(p)
    d = max(tip - cy, r * 1.05)
    a = math.pi / 2 - math.asin(min(r / d, 0.999))     # 접점까지의 각
    pts = [(cx, tip)]
    steps = 48
    a0 = math.atan2(r * math.cos(a), r * math.sin(a))  # 우측 접점의 각
    for i in range(steps + 1):                          # 접점 → 위쪽 → 반대 접점
        th = a0 - (2 * math.pi - 2 * a0) * i / steps
        pts.append((cx + r * math.sin(th), cy + r * math.cos(th)))
    ff = slide.shapes.build_freeform(I(pts[0][0]), I(pts[0][1]))
    ff.add_line_segments([(I(x), I(y)) for x, y in pts[1:]], close=True)
    s = flatten(ff.convert_to_shape())
    s.fill.solid()
    s.fill.fore_color.rgb = rgb(fill)
    s.line.fill.background()
    s.shadow.inherit = False
    return cx, cy


def draw_title(slide, L: dict, tok: dict) -> None:
    t, col = tok["title"], tok["color"]
    p, b = t["pin"], t["box"]
    rect(slide, b["x"], b["y"], b["w"], b["h"], None, col["region_tab"], 1.2)
    # 핀 = 보라 물방울 + 흰 원 + 로마숫자 (원본은 도형 3개다)
    cx, cy = map_pin(slide, p, col["region_tab"])
    ri = p.get("inner_d", p["w"] * 0.82) / 2
    rect(slide, cx - ri, cy - ri, ri * 2, ri * 2, "FFFFFF", None, shape=MSO_SHAPE.OVAL)
    textbox(slide, cx - ri, cy - ri, ri * 2, ri * 2, _roman(L.get("index", 1)),
            p.get("label_size", 8.98), col["region_tab"],
            align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

    tb = slide.shapes.add_textbox(I(b["x"] + t["text"]["dx"]), I(b["y"]),
                                  I(b["w"]), I(b["h"]))
    tf = tb.text_frame
    tf.word_wrap = False
    tf.margin_left = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    para = tf.paragraphs[0]
    if L["lang"] == "ko":
        pairs = [(L["country"]["ko"], t["text"]["size_ko"]),
                 ("  " + L["country"]["en"], t["text"]["size_en"])]
    else:
        pairs = [(L["country"]["en"], t["text"]["size_ko"])]
    for text, size in pairs:
        r = para.add_run()
        r.text = text
        r.font.size = Pt(size)
        r.font.name = "맑은 고딕"
        r.font.color.rgb = rgb(col["heading"])


def _roman(n: int) -> str:
    out = ""
    for v, s in [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]:
        while n >= v:
            out += s
            n -= v
    return out or "I"


def draw_region_tab(slide, L: dict, tok: dict) -> None:
    if not L.get("region"):
        return
    r, col = tok["region_tab"], tok["color"]
    rect(slide, r["x"], r["y"], r["w"], r["h"], col["region_tab_bg"])
    tb = textbox(slide, r["x"] - (r["h"] - r["w"]) / 2, r["y"] + (r["h"] - r["w"]) / 2,
                 r["h"], r["w"], L["region"], r["size"], col["region_tab"],
                 align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    tb.rotation = 90


def draw_legend(slide, L: dict, tok: dict) -> None:
    lg, col = L["legend"], tok["color"]
    fs = lg["size"]
    y = lg["y0"]
    for it in lg["items"]:
        rect(slide, lg["x"], y, lg["swatch"], lg["swatch"], col["badge_bg"])
        textbox(slide, lg["x"], y, lg["swatch"], lg["swatch"], it["symbol"], fs,
                col["badge_fg"], bold=True, align=PP_ALIGN.CENTER,
                anchor=MSO_ANCHOR.MIDDLE)
        # 한글은 글자를 세로로 쌓고, 영문은 통째로 90° 회전 (낱자로 흩어지면 못 읽는다)
        if L["lang"] == "en":
            h = len(it["label"]) * fs / 72 * 0.55
            tb = textbox(slide, lg["x"] + lg["swatch"] / 2 - h / 2,
                         y + lg["swatch"] + 0.02 + h / 2 - 0.06, h, 0.12,
                         it["label"], fs, col["body"], align=PP_ALIGN.CENTER,
                         anchor=MSO_ANCHOR.MIDDLE)
            tb.rotation = 90
        else:
            h = len(it["label"]) * fs / 72 * 1.05
            textbox(slide, lg["x"] - 0.03, y + lg["swatch"] + 0.02, lg["swatch"] + 0.06,
                    h, list(it["label"]), fs, col["body"], align=PP_ALIGN.CENTER,
                    spacing=0.9)
        y += lg["swatch"] + h + 0.09
    pn = lg["page_num"]
    textbox(slide, pn["x"], pn["y"] - 0.14, 0.3, 0.2, str(L.get("index", 1)),
            pn["size"], col["body"])


def draw_notes(slide, L: dict, tok: dict) -> None:
    if not L.get("notes"):
        return
    lay = tok["layout"][L["mode"]]
    if L["mode"] == "A":
        x, y = lay["bottom_row"]["x0"], lay["bottom_row"]["y"] - 0.24
    else:
        x, y = lay["right_col"]["x"], lay["right_col"]["y1"] + 0.05
    textbox(slide, x, y, 2.0, 0.18, " ".join(L["notes"]), 7.0,
            tok["color"]["area_ring"], bold=True)


# ─────────────────────────────── CLI ───────────────────────────────

def build(layout_paths: list, out: Path) -> Path:
    tok = design_tokens()
    prs = Presentation()
    prs.slide_width = I(tok["canvas"]["w_in"])
    prs.slide_height = I(tok["canvas"]["h_in"])
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for i, lp in enumerate(layout_paths, 1):
            L = read_json(lp)
            log(f'  [{i}/{len(layout_paths)}] {L["country"]["ko"]} ({L["lang"]})')
            draw_slide(prs, L, tok, tmp / f"s{i}", Path(lp))
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    log(f"  → {out} ({out.stat().st_size//1024}KB, 슬라이드 {len(layout_paths)}장)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="layout.json → 편집 가능한 PPTX")
    ap.add_argument("--layout", required=True, nargs="+", help="layout.json (여러 개 가능)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    build([Path(p) for p in a.layout], Path(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
