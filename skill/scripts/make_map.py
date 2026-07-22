"""프로젝트맵 생성 — 전 과정을 한 번에.

    python make_map.py --input nepal.json --outdir out
    python make_map.py --input nepal.json timor.json --outdir out --lang ko en
    python make_map.py --input nepal.json --outdir out --formats pdf pptx

단계: 지명해석 → 배치(layout.json) → SVG(html) → PDF/PNG → PPTX
PPTX 를 만들려면 `skill/.venv/bin/python` 으로 실행해야 한다 (python-pptx 필요).
국문·영문을 함께 지정하면 **같은 배치**로 언어만 바꾼 슬라이드가 나란히 생성된다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import log, read_json, write_json
import layout as layout_mod
import render_html

ALL_FORMATS = ["html", "png", "pdf", "pptx"]


def run(inputs: list, outdir: Path, langs: list, formats: list,
        detail: str = "50m", scale: int = 2) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    made = {f: [] for f in formats}
    layouts = []

    for idx, src in enumerate(inputs, 1):
        doc = read_json(src)
        # 국문·영문을 함께 뽑을 때는 두 슬라이드가 짝으로 보이도록 폰트 배율을 맞춘다.
        # 영문이 길어 축소되면 국문도 같이 줄인다 (design.md 판단 규칙 5).
        pair_scale, probed = None, {}
        if len(langs) > 1:
            probed = {lg: layout_mod.compute(doc, lg, idx, detail) for lg in langs}
            scales = [L["font_scale"] for L in probed.values()]
            pair_scale = min(scales)
            if len(set(scales)) > 1:
                log(f"  · 언어별 배율이 달라 {pair_scale:.2f}배로 통일합니다")

        for lang in langs:
            stem = f'{Path(src).stem}_{lang}'
            log(f"── {doc['country']} / {lang} ──")
            # 배율 탐색 때 이미 만든 배치가 조건에 맞으면 다시 계산하지 않는다
            L = probed.get(lang)
            if L is None or L["font_scale"] != pair_scale:
                L = layout_mod.compute(doc, lang, idx, detail, pair_scale)
            lp = write_json(outdir / f"{stem}.layout.json", L, indent=1)
            layouts.append(lp)
            log(f'  카드 {len(L["cards"])} · 마커 {len(L["markers"])} · 지시선 '
                f'{len(L["leaders"])} · 교차 {L["crossings"]} · 글자가림 {L.get("text_hits", 0)} '
                f'· 폰트 {L["font_scale"]}배')
            for w in L["warnings"]:
                log(f"  ! {w}")

            html = outdir / f"{stem}.html"
            html.write_text(render_html.render(L), encoding="utf-8")
            if "html" in formats:
                made["html"].append(html)
                log(f"  → {html.name}")

            if {"png", "pdf"} & set(formats):
                import export
                if "png" in formats:
                    made["png"].append(export.to_png(html, outdir / f"{stem}.png", scale))
                if "pdf" in formats:
                    made["pdf"].append(export.to_pdf(html, outdir / f"{stem}.pdf"))

    _suggest_contribution(layouts)

    if "pptx" in formats:
        try:
            import render_pptx
        except ImportError:
            log("  ! python-pptx 가 없어 PPTX 를 건너뜁니다. "
                "skill/.venv/bin/python 으로 실행하세요.")
        else:
            name = "project_map.pptx" if len(layouts) > 1 else f"{Path(inputs[0]).stem}.pptx"
            made["pptx"].append(render_pptx.build(layouts, outdir / name))
    return made


def _suggest_contribution(layouts: list) -> None:
    """지도를 다 만들었으면 위치를 사람이 확인했다는 뜻이다.

    원천 데이터가 국가 중심점으로만 알고 있던 지점을 우리가 정밀화했다면
    돌려줄 값어치가 있다. **여기서 보내지는 않는다** — 안내만 하고 제출은 사람이 한다.
    """
    try:
        import contribute
    except ImportError:
        return
    seen = set()
    for lp in layouts:
        L = read_json(lp)
        country = L["country"]["ko"]
        if country in seen:
            continue
        seen.add(country)
        doc = contribute.build(L, author="", only_improved=True)
        n = len(doc["points"])
        if n:
            contribute.suggest(lp, country, n + doc["_skipped_already_precise"], n)


def main() -> int:
    ap = argparse.ArgumentParser(description="KOICA 프로젝트맵 생성 (전 과정)")
    ap.add_argument("--input", required=True, nargs="+", help="사업 목록 JSON (국가별)")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--lang", nargs="+", default=["ko"], choices=["ko", "en"])
    ap.add_argument("--formats", nargs="+", default=["html", "pdf", "pptx"],
                    choices=ALL_FORMATS)
    ap.add_argument("--detail", default="50m", choices=["10m", "50m", "110m"])
    ap.add_argument("--scale", type=int, default=2, help="PNG 배율 (2 = 192dpi)")
    a = ap.parse_args()

    made = run([Path(p) for p in a.input], Path(a.outdir), a.lang, a.formats,
               a.detail, a.scale)
    log("\n생성 완료:")
    for f, paths in made.items():
        for p in paths:
            log(f"  {f:5s} {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
