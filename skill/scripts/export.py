"""HTML → PDF / PNG (headless Chrome).

    python export.py --html map.html --pdf map.pdf --png map.png

Chrome 은 macOS 기본 설치 경로에서 찾는다. 없으면 CHROME 환경변수로 지정.
PNG 은 --scale 로 배율을 올려 인쇄용 해상도를 얻는다 (기본 2배 = 192dpi).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from common import log

CANDIDATES = [
    os.environ.get("CHROME", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
]


def find_chrome() -> str:
    for c in CANDIDATES:
        if c and Path(c).exists():
            return c
    raise SystemExit(
        "Chrome 을 찾지 못했습니다. CHROME 환경변수에 실행 파일 경로를 지정하세요.")


def run(chrome: str, args: list, expect: Path, timeout: int = 90,
        vtb: int = 8000, gl: bool = False) -> None:
    """Chrome 을 띄우고 **산출 파일이 안정되면** 종료시킨다.

    headless Chrome 이 파일을 다 쓰고도 프로세스가 살아 있는 환경이 있다
    (이 맥이 그렇다). 정상 종료를 기다리면 무한정 걸리므로 결과물을 보고 판단한다.
    """
    if expect.exists():
        expect.unlink()
    tmp = tempfile.mkdtemp()
    base = [chrome, "--headless=new", "--no-sandbox", "--no-first-run",
            "--no-default-browser-check", "--hide-scrollbars",
            f"--virtual-time-budget={vtb}", f"--user-data-dir={tmp}"]
    # MapLibre 는 WebGL 이 필요하다. headless 에선 SwiftShader 로 돈다(확인 완료).
    base += (["--use-gl=swiftshader", "--enable-unsafe-swiftshader"]
             if gl else ["--disable-gpu"])
    p = subprocess.Popen(base + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.time() + timeout
        stable, last = 0, -1
        while time.time() < deadline:
            if p.poll() is not None:
                break
            if expect.exists():
                size = expect.stat().st_size
                stable = stable + 1 if size == last and size > 0 else 0
                last = size
                if stable >= 3:            # 3회 연속 같은 크기 = 쓰기 완료
                    break
            time.sleep(0.35)
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not expect.exists() or expect.stat().st_size == 0:
        err = (p.stderr.read().decode("utf-8", "replace") if p.stderr else "")
        raise SystemExit("Chrome 이 결과를 만들지 못했습니다.\n  "
                         + "\n  ".join(err.strip().splitlines()[-4:]))


def to_pdf(html: Path, out: Path, chrome: str | None = None) -> Path:
    chrome = chrome or find_chrome()
    out.parent.mkdir(parents=True, exist_ok=True)
    run(chrome, [f"--print-to-pdf={out}", "--no-pdf-header-footer",
                 html.resolve().as_uri()], out)
    log(f"  → {out} ({out.stat().st_size//1024}KB)")
    return out


def to_png(html: Path, out: Path, scale: int = 2, chrome: str | None = None,
           window: tuple | None = None, ready_title: str | None = None) -> Path:
    """window 는 CSS 픽셀 크기. 생략하면 슬라이드 한 장(13.333×7.5in @96dpi)."""
    chrome = chrome or find_chrome()
    out.parent.mkdir(parents=True, exist_ok=True)
    # --window-size 는 **CSS 픽셀**이다. 여기에 배율을 곱해 넘기면 창만 커지고
    # 시트는 가운데 작게 남는다. 배율은 --force-device-scale-factor 가 담당한다.
    w, h = window or (round(13.333 * 96), round(7.5 * 96))
    gl = ready_title is not None            # 타일 지도는 WebGL 이 필요하다
    run(chrome, [f"--screenshot={out}", f"--window-size={w},{h}",
                 f"--force-device-scale-factor={scale}",
                 "--default-background-color=FFFFFFFF", html.resolve().as_uri()],
        out, vtb=30000 if gl else 8000, gl=gl)
    log(f"  → {out} ({out.stat().st_size//1024}KB, {w*scale}×{h*scale})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="HTML → PDF/PNG")
    ap.add_argument("--html", required=True)
    ap.add_argument("--pdf")
    ap.add_argument("--png")
    ap.add_argument("--scale", type=int, default=2)
    a = ap.parse_args()
    src = Path(a.html)
    if not src.exists():
        raise SystemExit(f"{src} 가 없습니다.")
    chrome = find_chrome()
    if a.pdf:
        to_pdf(src, Path(a.pdf), chrome)
    if a.png:
        to_png(src, Path(a.png), a.scale, chrome)
    if not (a.pdf or a.png):
        ap.error("--pdf 또는 --png 중 하나가 필요합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
