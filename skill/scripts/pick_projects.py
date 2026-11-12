"""Review a country roster interactively or export a self-contained review page."""
import argparse
import http.server
import json
import secrets
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

from common import SKILL_DIR, log, read_json
from fetch_projects import collect_for_review

PAGE = SKILL_DIR / "assets" / "picker.html"


def editor_html(draft, hosted=False, make_map=False):
    # Serialize last so project text never becomes markup or a template instruction.
    payload = json.dumps(draft, ensure_ascii=False).replace("<", r"\u003c")
    from preview_geo import preview_geo
    geo = {}
    if draft.get("country"):
        try:
            geo = preview_geo(draft["country"])
        except (OSError, ValueError, SystemExit) as exc:
            log(f"지도 미리보기 자료 준비 실패: {exc}")
    geo_payload = json.dumps(geo, ensure_ascii=False, separators=(",", ":")).replace("<", r"\u003c")
    return (PAGE.read_text(encoding="utf-8")
            .replace("__HOSTED__", "true" if hosted else "false")
            .replace("__SAVE_LABEL__", "저장하고 지도 만들기" if make_map else "선택 목록 저장")
            .replace("__LOCATION_JS__", (PAGE.parent / "location_editor.js").read_text(encoding="utf-8"))
            .replace("__GEO_JSON__", geo_payload)
            .replace("__DRAFT_JSON__", payload))


def export_editor(path, draft):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(editor_html(draft), encoding="utf-8")
    return path


def persist(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
    Path(tmp.name).replace(path)


def serve(draft, out, *, make_map=False, timeout=1800):
    token = secrets.token_urlsafe(24)
    saved = threading.Event()
    result = {}
    page = editor_html(draft, hosted=True, make_map=make_map).encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_bytes(self, code, body, mime="text/plain; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/?" + token:
                self.send_bytes(200, page, "text/html; charset=utf-8")
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/save?" + token:
                return self.send_error(404)
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 20_000_000:
                    raise ValueError("목록 크기를 확인하세요.")
                doc = json.loads(self.rfile.read(length))
                if (not isinstance(doc, dict) or doc.get("country") != draft["country"]
                        or doc.get("year") != draft.get("year") or not doc.get("projects")
                        or not isinstance(doc["projects"], list)
                        or any(not isinstance(p, dict) or not str(p.get("name_ko") or "").strip()
                               or p.get("selected") is False for p in doc["projects"])):
                    raise ValueError("선택한 국가·연도와 사업명을 확인하세요.")
                persist(out, doc)
            except (ValueError, OSError) as exc:
                return self.send_bytes(400, str(exc).encode())
            result.update(doc)
            saved.set()
            self.send_bytes(200, b"ok")

    with http.server.HTTPServer(("127.0.0.1", 0), Handler) as server:
        url = f"http://127.0.0.1:{server.server_port}/?{token}"
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        log(f"사업 목록 검토 → {url}")
        try:
            webbrowser.open(url)
            saved.wait(timeout)
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
    return result or None


def main():
    ap = argparse.ArgumentParser(description="KOICA 사업·공고 후보 검토")
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--country", help="공식 게시판에서 함께 조회할 국가")
    source.add_argument("--draft", help="초안 또는 기존 검토 JSON")
    ap.add_argument("--year", type=int)
    ap.add_argument("--all", action="store_true", help="타기관 사업도 조회")
    ap.add_argument("--force", action="store_true", help="캐시 새로 고침")
    ap.add_argument("--out", default="projects.json")
    ap.add_argument("--all-notices", action="store_true", help="국가 검색 결과의 모든 페이지에서 공고 후보 확인")
    ap.add_argument("--export-html", type=Path, help="담당자에게 전달할 편집 화면을 파일로 저장")
    args = ap.parse_args()
    draft = (read_json(Path(args.draft)) if args.draft else
             collect_for_review(args.country, args.year, args.all, args.force, args.all_notices))
    if args.export_html:
        log(f"검토 화면 → {export_editor(args.export_html, draft)}")
    elif not serve(draft, args.out):
        log("저장된 검토 결과가 없습니다.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
