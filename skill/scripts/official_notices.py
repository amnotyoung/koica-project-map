"""Search KOICA's country-filtered expert bulletin for project formation notices."""
import hashlib
from itertools import count
import html
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

from lxml import etree, html as dom

from common import CACHE_DIR, log
from portfolio_selection import project_key, title_period

BOARD = "https://www.koica.go.kr/bbs/koica_kr/292/"
ARTICLE = re.compile(r"/bbs/koica_kr/292/(\d+)/artclView\.do$")
STAGE = re.compile(r"예비\s*조사|심층\s*기획\s*조사|기획\s*조사|형성\s*조사|신규\s*사업")
EXCLUDE = re.compile(r"종료\s*평가|사후\s*점검|영향\s*평가|인턴|코디네이터")
RANGE = re.compile(r"(?<!\d)['‘’`]?((?:20)?\d{2})\s*년?\s*[-–—~∼]\s*['‘’`]?((?:20)?\d{2})\s*년?(?!\d)")
COST = re.compile(r"[\d,]+(?:\.\d+)?\s*(?:억|백만|만)\s*(?:달러|불|원)")
TTL = 12 * 3600


def clean(s):
    return " ".join(html.unescape(s).replace("**", "").split())


def article_id(href):
    u = urlsplit(urljoin(BOARD, href))
    match = ARTICLE.fullmatch(u.path)
    return match[1] if u.scheme == "https" and u.netloc == "www.koica.go.kr" and match else None


def parse_board(raw):
    hits = {}
    if "Markdown Content:" in raw:
        for m in re.finditer(r"\*\*([^*\n]+?)\*\*\]\((https://[^\s)]+)\)", raw):
            number = article_id(m[2])
            if number:
                hits[number] = clean(m[1]).removesuffix("[New]").strip()
    else:
        tree = dom.fromstring(raw)
        for node in tree.xpath('//a[@href]'):
            number = article_id(node.get("href"))
            if number:
                pieces = node.xpath('.//strong') or [node]
                hits[number] = clean(pieces[0].text_content())
    total = re.search(r"총\s*([\d,]+)\s*개의?\s*글", clean(re.sub(r"<[^>]+>|_", " ", raw)))
    if not hits and (not total or total[1] != "0"):
        raise ValueError("공식 게시판 목록 형식을 확인할 수 없습니다")
    return hits, int(total[1].replace(",", "")) if total else None


def detail_text(raw):
    if "Markdown Content:" in raw:
        return raw.split("Markdown Content:", 1)[1].strip()
    tree = dom.fromstring(raw)
    nodes = tree.xpath('//*[contains(concat(" ",normalize-space(@class)," "), " artclView ")]')
    if not nodes:
        nodes = tree.xpath('//*[contains(@class,"artclViewBody") or contains(@class,"artclViewTitle")]')
    if not nodes:
        raise ValueError("공고 본문 형식을 확인할 수 없습니다")
    return "\n".join(clean(t) for node in nodes for t in node.itertext() if t.strip())


def _download(url, timeout):
    req = Request(url, headers={"User-Agent":"Mozilla/5.0 KOICA-project-map"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read(3_000_000).decode("utf-8-sig")


class Bulletin:
    def __init__(self, force=False):
        self.force = force
        self.reader = False

    def get(self, url, parse):
        folder = CACHE_DIR / "koica-notices"
        folder.mkdir(parents=True, exist_ok=True)
        cache = folder / (hashlib.sha256(url.encode()).hexdigest() + ".txt")
        cached = cache.read_text() if cache.exists() else None
        if cached and not self.force and time.time() - cache.stat().st_mtime < TTL:
            return parse(cached), False
        routes = [("https://r.jina.ai/" + url, 18)] if self.reader else [
            (url, 4), ("https://r.jina.ai/" + url, 18)]
        for route, timeout in routes:
            try:
                raw = _download(route, timeout)
                result = parse(raw)
            except (OSError, ValueError, etree.ParserError) as exc:
                error = exc
                continue
            if route != url:
                self.reader = True
            with tempfile.NamedTemporaryFile(dir=folder, delete=False, mode="w", encoding="utf-8") as out:
                out.write(raw)
            Path(out.name).replace(cache)
            return result, False
        if cached:
            return parse(cached), True
        raise ValueError(f"공식 공고 조회 실패 ({error})")


def candidate(country, year, number, listing, body):
    lines = [clean(x).strip(" #") for x in body.splitlines() if clean(x)]
    intro = " ".join(lines[:6])[:1100]
    if country not in listing or EXCLUDE.search(listing):
        return None
    headline = next((s for s in lines[:6] if country in s and ("사업" in s or "프로그램" in s)
                     and len(s) <= 190 and not s.startswith(("한국국제협력단", "KOICA는"))), listing)
    if EXCLUDE.search(headline):
        return None
    stage = STAGE.search(headline + " " + listing + " " + intro)
    if not stage:
        return None
    name = ""
    for i, line in enumerate(lines[:24]):
        label = re.match(r"^[ㅇ○·\s]*사\s*업\s*명\s*[:：\s]+(.*)", line)
        if not label:
            continue
        name = label[1].strip()
        if re.match(r"사업\s*(기간|규모|내용)", name):
            # Flattened table: the next row has the project, dates and sometimes the cost.
            data_line = lines[i+1] if i+1 < len(lines) else ""
            name = RANGE.split(data_line, maxsplit=1)[0].rstrip(" (/") if country in data_line else ""
        break
    name = (name or headline).strip(" <>")
    name = re.sub(r"^(?:\[[^]]+\]|마감)\s*", "", name)
    project_name = re.split(r"\s*(?:심층\s*)?(?:기획|예비|형성)\s*조사\s*전문가|\s+전문가\s*(?:재?공모|모집)", name)[0].strip()
    # A form like "사업 모니터링 및 형성 조사" describes an assignment, not a named new project.
    if project_name.endswith((" 및", " 추가", " 내")):
        project_name = headline
    name = project_name
    period_line = next((" ".join(lines[i:i+3])[:200] for i,l in enumerate(lines)
                        if re.search(r"사업\s*기간|사업\s*규모\s*및\s*기간", l)), "")
    period = title_period(name) or title_period(headline) or title_period(listing)
    if not period and (m := RANGE.search(period_line)):
        period = tuple(int(v) if len(v)==4 else int(v)+2000 for v in m.groups())
    if period and not (2000 <= period[0] <= period[1] <= 2100):
        period = None
    start = re.search(r"(?<!\d)((?:20)?\d{2})\s*년(?:도)?\s*신규", listing + " " + intro)
    start_year = (int(start[1]) % 100 + 2000) if start else None
    if year and (period and not period[0] <= year <= period[1] or not period and start_year and start_year > year):
        return None
    url = BOARD + number + "/artclView.do"
    money = COST.search(period_line) or COST.search(headline) or COST.search(name)
    period_str = "-".join(map(str, period)) if period else ""
    if period and not title_period(name):
        name += f" ({period_str}" + (f"/{money[0]}" if money else "") + ")"
    evidence = period_line or next((s for s in lines[:8] if stage[0] in s), headline)
    return {"id":"koica-board:"+number, "selected":False, "name_ko":name, "name_en":"",
            "place":"", "coverage":"unknown", "badges":[], "_period":period_str,
            "_stage":stage[0].replace(" ",""), "_notice_title":headline, "_notice_evidence":evidence[:320],
            "_source_info":{"name":"KOICA 개발협력 좋은 일자리", "url":url},
            "scope_sources":[url], "_notice_candidate":True}


def discover(country, year, projects, *, force=False, max_pages=4, max_details=16):
    board = Bulletin(force)
    report = {"board":BOARD+"artclList.do", "checked_at":datetime.now(timezone.utc).isoformat(),
              "pages":0, "details":0, "errors":[], "limited":False, "stale":False}
    report["search_url"] = report["board"]+"?"+urlencode({"page":1, "srchColumn":"sj", "srchWrd":country})
    entries = {}
    pages = range(1, max_pages+1) if max_pages is not None else count(1)
    for page in pages:
        url = report["board"]+"?"+urlencode({"page":page, "srchColumn":"sj", "srchWrd":country})
        try:
            (hits, total), stale = board.get(url, parse_board)
        except (ValueError,OSError) as exc:
            report["errors"].append(str(exc))
            break
        report["pages"] += 1
        report["stale"] |= stale
        if hits and hits.keys() <= entries.keys():
            report["errors"].append("게시판이 같은 페이지를 반복 반환했습니다")
            break
        entries.update(hits)
        if not hits or (total is not None and len(entries) >= total) or len(hits)<10:
            break
    else:
        report["limited"] = True
    eligible = [(n,t) for n,t in entries.items() if country in t and not EXCLUDE.search(t)
                and (STAGE.search(t) or "사업" in t or "프로그램" in t or len(t)>=34)]
    # Prefer newly published items and explicit matches for the requested edition.
    eligible.sort(key=lambda item:(not (year and str(year) in item[1]), -int(item[0])))
    report["limited"] |= max_details is not None and len(eligible)>max_details

    def inspect(item):
        number, title = item
        url = BOARD+number+"/artclView.do"
        try:
            body, stale = board.get(url, detail_text)
            return candidate(country, year, number, title, body), stale, None
        except (ValueError,OSError) as exc:
            row = candidate(country, year, number, title, "")
            if row:
                row["_detail_unavailable"] = True
            return row, False, f"공고 {number}: {exc}"

    found = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for row, stale, error in pool.map(inspect, eligible[:max_details]):
            report["stale"] |= stale
            if error:
                report["errors"].append(error)
            else:
                report["details"] += 1
            if row:
                key = (project_key(row["name_ko"]), row["_period"], tuple(COST.findall(row["name_ko"])))
                if key in found:
                    found[key]["scope_sources"].extend(row["scope_sources"])
                else:
                    found[key] = row
    for (key, _, _), row in found.items():
        matches = [(SequenceMatcher(None, key, project_key(p["name_ko"])).ratio(), p)
                   for p in projects if p.get("name_ko")]
        if matches:
            score, other = max(matches, key=lambda x:x[0])
            if score >= .58:
                row["_similar_project"] = other["name_ko"]
                row["_similar_project_id"] = other.get("id")
    report["status"] = ("partial" if report["pages"] else "failed") if report["errors"] or report["stale"] else "ok"
    log(f'[KOICA 공고] {country} · 목록 {report["pages"]}쪽 · 본문 {report["details"]}건 · 검토 후보 {len(found)}건 ({report["status"]})')
    return list(found.values()), report


def add_notices(draft, force=False, all_notices=False):
    limits = {"max_pages":None, "max_details":None} if all_notices else {}
    candidates, info = discover(draft["country"], draft.get("year"), draft["projects"], force=force, **limits)
    return {**draft, "notice_candidates":candidates, "notice_search":info}
