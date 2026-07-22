"""사업 목록을 브라우저에서 체크·수정해 `projects.json` 을 만든다.

    python pick_projects.py --country 네팔 --year 2026 --out projects.json
    python pick_projects.py --draft draft.json --out projects.json

로컬에만 열리는 임시 HTTP 서버를 띄우고 브라우저를 연다. 저장을 누르면 결과를
받아 파일로 쓰고 서버는 스스로 닫힌다. 외부로 나가는 통신은 없다.

수집기(fetch_projects)가 채워주는 **지명은 추정값**이라 이 확인 단계가 필수다 —
그룹 라벨을 옮긴 것이라 실제 대상지와 다를 수 있다.
"""
from __future__ import annotations

import argparse
import http.server
import json
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from common import SKILL_DIR, log, read_json, write_json

import fetch_projects

PAGE = SKILL_DIR / "assets" / "picker.html"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def serve(draft: dict, timeout: float = 1800) -> dict | None:
    """브라우저에서 선택·수정을 받아 돌려준다. 닫히거나 시간이 지나면 None."""
    html = PAGE.read_text(encoding="utf-8").replace(
        "window.__DRAFT__", json.dumps(draft, ensure_ascii=False))
    body = html.encode("utf-8")
    result: dict = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, payload=b"", ctype="text/plain; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            self._send(200, body, "text/html; charset=utf-8")

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            try:
                result.update(json.loads(self.rfile.read(n)))
            except Exception as e:
                self._send(400, str(e).encode())
                return
            self._send(200, b"ok")
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    port = _free_port()
    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{port}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"\n  브라우저에서 사업을 선택·수정한 뒤 [저장하고 지도 만들기] 를 누르세요")
    log(f"  → {url}\n  (창이 안 열리면 위 주소를 직접 여세요. Ctrl-C 로 취소)")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    end = time.time() + timeout
    try:
        while time.time() < end and not result:
            time.sleep(0.3)
    except KeyboardInterrupt:
        log("  · 취소했습니다")
    finally:
        srv.shutdown()
        srv.server_close()
    return result or None


def main() -> int:
    ap = argparse.ArgumentParser(description="사업 선택·수정 UI")
    ap.add_argument("--country", help="국가명 (초안을 새로 수집)")
    ap.add_argument("--draft", help="이미 만든 초안 JSON")
    ap.add_argument("--year", type=int, help="해당 연도 진행 사업만")
    ap.add_argument("--all", action="store_true", help="타기관 사업까지 포함")
    ap.add_argument("--force", action="store_true", help="원천 데이터 다시 받기")
    ap.add_argument("--out", default="projects.json")
    a = ap.parse_args()
    if not (a.country or a.draft):
        ap.error("--country 또는 --draft 중 하나가 필요합니다.")

    draft = (read_json(Path(a.draft)) if a.draft
             else fetch_projects.collect(a.country, a.year, a.all, a.force))
    picked = serve(draft)
    if not picked:
        log("  ! 선택 결과를 받지 못했습니다 — 파일을 만들지 않았습니다")
        return 1
    write_json(Path(a.out), picked, indent=1)
    log(f'  ✓ {len(picked["projects"])}건 선택 → {a.out}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
