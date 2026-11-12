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
from datetime import datetime
from pathlib import Path

from common import log, read_json, write_json
import layout as layout_mod
import render_html

ALL_FORMATS = ["html", "png", "pdf", "pptx"]


def stamped_dir(base: Path) -> Path:
    """`base/<YYYY-MM-DD_HHMM>/` 를 만들고 `base/latest` 가 그것을 가리키게 한다.

    실행마다 폴더가 갈라져 이전 산출물을 덮어쓰지 않는다. 이력이 쌓이고,
    최신은 언제나 `base/latest` 로 찾는다.
    """
    run = base / datetime.now().strftime("%Y-%m-%d_%H%M")
    if run.exists():                                   # 같은 분에 두 번 돌리면 초까지
        run = base / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    link = base / "latest"
    try:
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(run.name)                      # base 기준 상대 링크
    except OSError:
        pass                                           # 심볼릭 링크 불가 환경은 그냥 건너뛴다
    return run


def run(inputs: list, outdir: Path, langs: list, formats: list,
        detail: str = "50m", scale: int = 2) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    made = {f: [] for f in formats}
    layouts = []

    for idx, src in enumerate(inputs, 1):
        doc = read_json(src)
        for L in layout_mod.compute_pages(doc, langs, idx, detail):
            lang = L["lang"]
            suffix = f'_p{L["page"]:02d}' if L["pages"] > 1 else ""
            stem = f'{Path(src).stem}_{lang}{suffix}'
            log(f"── {doc['country']} / {lang} / {L['page']} of {L['pages']} ──")
            lp = write_json(outdir / f"{stem}.layout.json", L, indent=1)
            layouts.append(lp)
            log(f'  카드 {len(L["cards"])} · 마커 {len(L["markers"])} · 지시선 '
                f'{len(L["leaders"])} · 교차 {L["crossings"]} · 글자가림 {L.get("text_hits", 0)} '
                f'· 지도밀도 {L["map"].get("density", "standard")} '
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

    # Producing a map does not verify its inferred sites. Contributions require
    # a separate, explicit location review.

    if "pptx" in formats:
        try:
            import render_pptx
        except ImportError:
            log("  ! python-pptx 가 없어 PPTX 를 건너뜁니다. "
                "skill/.venv/bin/python 으로 실행하세요.")
        else:
            name = "project_map.pptx" if len(inputs) > 1 else f"{Path(inputs[0]).stem}.pptx"
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
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", nargs="+", help="사업 목록 JSON (국가별)")
    source.add_argument("--country", nargs="+", help="공개 사업자료에서 국가별 KOICA 사업을 수집하여 생성")
    ap.add_argument("--year", type=int, help="사업 기간에 포함되는 기준연도")
    ap.add_argument("--include-unselected", action="store_true", help="30억원 이상 진행 프로젝트 외 KOICA 사업도 포함")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--lang", nargs="+", default=None, choices=["ko", "en"])
    ap.add_argument("--formats", nargs="+", default=None,
                    choices=ALL_FORMATS)
    ap.add_argument("--reference-template", type=Path,
                    help="검수한 로컬 참조 매니페스트. 원본 지도·도형을 유지하며 사업명을 재생성")
    ap.add_argument("--detail", default="10m", choices=["10m", "50m", "110m"])
    ap.add_argument("--scale", type=int, default=2, help="PNG 배율 (2 = 192dpi)")
    ap.add_argument("--flat", action="store_true",
                    help="날짜 하위폴더 없이 outdir 에 바로 쓴다 (덮어쓰기)")
    a = ap.parse_args()

    if a.reference_template:
        if not a.input or len(a.input) != 1:
            ap.error("참조 생성은 국가별 입력 1개와 그 국가의 매니페스트를 사용합니다")
        if a.formats and a.formats != ["pptx"]:
            ap.error("참조 생성은 PPTX를 보존합니다. PDF는 PowerPoint에서 내보내세요")
        import reference_pptx
        outdir = Path(a.outdir) if a.flat else stamped_dir(Path(a.outdir))
        out = outdir / f"{Path(a.input[0]).stem}.pptx"
        try:
            report = reference_pptx.build(read_json(Path(a.input[0])),
                                          a.reference_template, out, a.lang)
        except (ValueError, OSError) as e:
            ap.error(str(e))
        write_json(out.with_suffix(".reference-report.json"), report, indent=2)
        log(f"참조 생성 완료 → {out} ({report['slides']}장, 사업 {report['projects']}건)")
        log("  원본 지도·편집 가능한 도형을 보존했습니다. PowerPoint에서 비교 검수하세요.")
        return 0

    # 실행마다 out/<날짜_시각>/ 로 나눠 이전 산출물을 지키고, out/latest 로 최신을 가리킨다
    outdir = Path(a.outdir) if a.flat else stamped_dir(Path(a.outdir))
    if a.country:
        import fetch_projects
        inputs = []
        for country in a.country:
            doc = fetch_projects.collect(country, a.year, False)
            if not a.include_unselected:
                doc["projects"] = [p for p in doc["projects"] if p["selected"]]
            if not doc["projects"]:
                ap.error(f"{country}: 조건에 맞는 사업이 없습니다. 연도·선택 조건을 확인하세요")
            inputs.append(write_json(outdir / "inputs" / f"{country}.json", doc, indent=2))
    else:
        inputs = [Path(p) for p in a.input]
    made = run(inputs, outdir, a.lang or ["ko"],
               a.formats or ["html", "pdf", "pptx"],
               a.detail, a.scale)
    log(f"\n생성 완료 → {outdir}")
    if not a.flat:
        log(f"  (최신본은 {Path(a.outdir) / 'latest'} 로도 열 수 있습니다)")
    for f, paths in made.items():
        for p in paths:
            log(f"  {f:5s} {p.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
