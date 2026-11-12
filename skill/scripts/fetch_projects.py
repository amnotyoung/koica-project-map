"""oda-map-lab 에서 해당 국가의 KOICA 사업을 **전부** 끌어와 초안을 만든다.

    python fetch_projects.py --country 네팔 --out draft.json
    python fetch_projects.py --country 네팔 --year 2026 --all

사업명·기간·예산·분야 배지는 원문에서 자동으로 채운다. **지명(`place`)은 추정값이다** —
그룹 라벨을 그대로 옮긴 것이라 실제 대상지와 다를 수 있다(`룸비니` 그룹에 버르디야
사업이 들어 있는 식). 반드시 pick_projects.py 로 사람이 확인·수정해야 한다.

좌표는 `details.source` 를 함께 보고 선별한다. `국가(폴백)` 좌표는 버리고 지명에서
다시 풀지만, 도시·도시(음차)·IATI 원본(공식좌표)은 `source_coord` 로 보존한다.
여러 대상지를 한 점으로 묶은 그룹은 그 좌표만으로 모든 지점을 표현할 수 없으므로
resolve_places 가 각 지명을 다시 푼다.
"""
from __future__ import annotations

from decimal import Decimal

import argparse
import html
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

from country_names import canonical, identity
import annual_portfolio
import iati_aid
from portfolio_selection import TITLE_PERIOD, project_key, reconcile_notices, title_period, year_decision
from common import CACHE_DIR, REFERENCE_DIR, fetch, log, read_json, sector_map, write_json

SOURCE = "https://oda-map-lab.pages.dev/generated/map-base.json"
CACHE = CACHE_DIR / "map-base.json"
TTL_HOURS = 12          # 원천이 IATI 라 갱신이 잦지 않다. 그래도 하루 안에 한 번은 다시 받는다

# 국별협력사업(무상원조 프로젝트)의 성격 — 기본 선택 대상
MAIN_AID = "프로젝트 원조"
# 2027년판 국문 24·36쪽의 두 최저액 사업. 원화만 있을 때는 두 원천 예산 중 작은 값.
MAIN_BUDGET_USD = 2_000_000
MAIN_BUDGET_KRW = 2_260_000_000
# 사업명 끝의 기간/총액만 읽는다. 설명에 등장하는 집행액·분담금은 사용하지 않는다.
TITLE_BUDGET = re.compile(
    r"[(（]\s*['‘’`]?(?:20)?\d{2}\s*년?\s*[-~–—]\s*['‘’`]?(?:20)?\d{2}\s*년?\s*[/／,]\s*"
    r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(억|천만|백만|십만|만|천)?\s*(달러|불|원)\s*[)）]\s*$"
)
AMOUNT_SCALE = {"억":100_000_000, "천만":10_000_000, "백만":1_000_000,
                "십만":100_000, "만":10_000, "천":1_000, None:1}


PERIOD_IN_TEXT = re.compile(r"(?<!\d)['‘’`]?(?:20)?\d{2}\s*[-–~—]\s*['‘’`]?(?:20)?\d{2}(?!\d)")
MONEY_EN = re.compile(r"\$|USD|KRW|dollars?|\bwon\b", re.I)
MONEY_KO = re.compile(r"\d[\d,.]*\s*(?:억|천만|백만|십만|만|천)?\s*(?:달러|불|원)")


def budget_label(total, currency, lang):
    if lang == "ko":
        scale, unit = (10**8, "억 원") if currency == "KRW" else (10**4, "만 불")
    else:
        scale, unit = (10**9, "bn") if total >= 10**9 else (10**6, "m")
    number = format((total / scale).normalize(), "f")
    return f"{number}{unit}" if lang == "ko" else f"{currency} {number}{unit}"


def complete_card_metadata(row):
    """Carry reported dates and total budget into both display titles before review."""
    ko = row["name_ko"].rstrip().rstrip(")") + ")"
    title_years = title_period(ko)
    period = "-".join(map(str, title_years)) if title_years else row.get("_period", "")
    amount = TITLE_BUDGET.search(ko)
    if amount:
        value, unit, currency = amount.groups()
        total = Decimal(value.replace(",", "")) * AMOUNT_SCALE[unit]
        currency = "KRW" if currency == "원" else "USD"
    elif row.get("_budget_period_only"):
        total, currency = Decimal(0), ""
    else:
        reported = row.get("_reported_budget")
        if reported is None:
            total, currency = Decimal(str(row.get("_budget_krw") or 0)), "KRW"
        else:
            currency = reported.get("currency")
            total = Decimal(str(reported.get("value") or 0)) if currency in {"USD","KRW"} else Decimal(0)
    for lang, money in (("ko", MONEY_KO), ("en", MONEY_EN)):
        key = "name_" + lang
        name = row.get(key)
        if not name:
            continue
        fields = []
        dated_task = re.search(r"scheduled in 20\d{2}|20\d{2}년 과업", name, re.I)
        if period and not PERIOD_IN_TEXT.search(name) and not dated_task:
            fields.append(period.replace("-", "–"))
        if total > 0 and not money.search(name):
            fields.append(budget_label(total, currency, lang))
        if fields:
            row.setdefault("_source_" + key, name)
            row[key] = name + " (" + " / ".join(fields) + ")"


def meets_budget_floor(title, details):
    match = TITLE_BUDGET.search(title)
    if match:
        amount, unit, currency = match.groups()
        value = float(amount.replace(",", "")) * AMOUNT_SCALE[unit]
        return value >= (MAIN_BUDGET_KRW if currency == "원" else MAIN_BUDGET_USD)
    reported = (details.get("amounts") or {}).get("budget") or {}
    currency = reported.get("currency") or "KRW"
    floor = {"USD":MAIN_BUDGET_USD, "KRW":MAIN_BUDGET_KRW}.get(currency)
    value = reported.get("value") if reported else details.get("budget")
    return floor is not None and isinstance(value, (int, float)) and value >= floor


# 원천 데이터의 지역 구분 → 슬라이드 지역 탭 표기 (샘플은 '아시아태평양')
REGION_TAB = {"아시아": "아시아태평양", "오세아니아": "아시아태평양",
              "중남미": "중남미", "아프리카": "아프리카",
              "중동": "중동·CIS", "동구 및 CIS": "동구·CIS"}
COUNTRY_FALLBACK = "국가(폴백)"


def load_source(force: bool = False) -> dict:
    stale = (not CACHE.exists()
             or time.time() - CACHE.stat().st_mtime > TTL_HOURS * 3600)
    if stale or force:
        log(f"  · 최신 데이터 확인 ({SOURCE})")
        fetch(SOURCE, CACHE, force=True)
    return read_json(CACHE)


def _badge(sector: str, sm: dict) -> str:
    """세부 분야명 → 배지 5종. sector_map.yaml 을 먼저 보고, 없으면 폴백 규칙."""
    if not sector:
        return ""
    for key, names in sm["sectors"].items():
        if sector in names:
            return key
    parts = [p.strip() for p in sector.split(",") if p.strip()]
    if len(parts) > 1:                       # 쉼표로 묶인 복합 분야는 조각별 다수결
        votes = [b for b in (_badge(p, sm) for p in parts) if b]
        if votes:
            return max(set(votes), key=votes.count)
    for rule in sm["fallback_rules"]:
        if re.search(rule["pattern"], sector):
            return rule["bucket"]
    return ""


def _place_guess(group_label: str) -> str:
    """그룹 라벨 → `place` 후보. `키체, 케찰테낭고` 처럼 쉼표로 묶인 건 `/` 로 잇는다."""
    s = re.sub(r"\s*\((진행|종료|국가)\)\s*$", "", group_label).strip()
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return "/".join(dict.fromkeys(parts))


def _period(de: dict) -> str:
    a, b = (de.get("start") or "")[:4], (de.get("end") or "")[:4]
    return f"{a}-{b}" if a and b else (a or b or "")


def _trusted_source_coord(feature: dict, place: str) -> dict | None:
    """국가 중심점 폴백이 아닌 유효한 WGS84 좌표만 보존한다."""
    source = str(feature.get("details", {}).get("source") or "").strip()
    if not source or source == COUNTRY_FALLBACK:
        return None
    try:
        lat, lon = float(feature["lat"]), float(feature["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"place": place, "lat": round(lat, 6), "lon": round(lon, 6),
            "source": source}


def collect(country: str, year: int | None, include_all: bool,
            force: bool = False, *, review_partners: bool = False) -> dict:
    country = canonical(country)
    data = load_source(force)
    scopes = read_json(REFERENCE_DIR / "public_project_scopes.json").get(country, {})
    sm = sector_map()
    rows, seen, catalog_titles, review = [], set(), set(), []
    period_candidates = []
    aid_codes = None
    notices = read_json(REFERENCE_DIR / "public_programmes.json").get(country, [])
    country_en = ""
    region = ""
    for f in data["features"]:
        if canonical(f.get("country")) == country and f.get("details", {}).get("region"):
            region = REGION_TAB.get(f["details"]["region"], f["details"]["region"])
            break

    for f in data["features"]:
        if canonical(f.get("country")) != country or not f.get("layer", "").startswith("project"):
            continue
        if not country_en and "·" in (f.get("name", {}).get("en") or ""):
            country_en = f["name"]["en"].partition("·")[0].strip()
        done = f["layer"].endswith("_done")
        other = "other" in f["layer"]
        m = re.search(r"·\s*(.+?)\s*$", f["name"]["ko"])
        place = _place_guess(m.group(1) if m else "")
        coord_source = str(f.get("details", {}).get("source") or "").strip()
        source_coord = _trusted_source_coord(f, place)
        for mem in f.get("members", []):
            de = mem.get("details", {})
            agency = str(de.get("agency") or "")
            if not include_all and "KOICA" not in agency:
                continue
            fid = mem.get("feature_id")
            if fid in seen:
                continue
            seen.add(fid)
            name_ko = html.unescape(mem["name"].get("ko") or "").strip()
            name_en = html.unescape(mem["name"].get("en") or "").strip()
            budget = de.get("budget") or 0
            per = _period(de)
            aid = de.get("aid") or ""
            xml_source = (de.get("source_info") or {}).get("url") == iati_aid.URL
            aid_code = ""
            if xml_source and "KOICA" in agency and (not aid or de.get("biz_type") == "국별협력사업"):
                if aid_codes is None:
                    aid_codes = iati_aid.load_codes(force)
                aid_code = aid_codes.get((fid or "").partition("@")[0], "")
                if not aid and aid_code == "C01":
                    aid = MAIN_AID
                elif not aid and aid_code == "B03":
                    aid = "목적지정 프로그램·기금 기여"
            if "KOICA" in agency:
                catalog_titles.add(project_key(name_ko))
            fact = scopes.get(fid) or scopes.get((fid or "").partition("@")[0])
            applicable, decision = year_decision(year, per, name_ko, fact)
            if decision:
                review.append({"id":fid, "name":name_ko, **decision})
            earmarked = (aid_code == "B03" and de.get("biz_type") == "국별협력사업"
                         and de.get("biz_grade") == "부서")
            project_aid = aid == MAIN_AID or earmarked
            needs_review = (not applicable and decision and decision["decision"] == "needs_evidence"
                            and project_aid and "KOICA" in agency)
            if not applicable and not needs_review:
                continue
            explicit_bilateral = de.get("biz_type") == "국별협력사업"
            main = (project_aid and "KOICA" in agency
                    and (explicit_bilateral or (not xml_source or TITLE_BUDGET.search(name_ko)) and meets_budget_floor(name_ko, de)) and not done and not other)
            row = {
                "selected": main,
                "place": place,
                "badges": [b for b in [_badge(de.get("sector", ""), sm)] if b],
                "name_ko": name_ko,
                "name_en": name_en,
                "_period": per,
                "_budget_krw": budget,
                "_biz_type": de.get("biz_type"),
                "_aid": aid,
                "_agency": agency,
                "_sector": de.get("sector") or "",
                "_stage": de.get("stage") or "",
                "_done": done,
                "_other": other,
                "_id": fid,
                "id": fid,
                "_source_info": de.get("source_info", {}),
                "_location_basis": "group-representative",
            }
            reported = (de.get("amounts") or {}).get("budget")
            if isinstance(reported, dict):
                row["_reported_budget"] = reported
            if aid_code:
                row["_iati_aid_code"] = aid_code
            if xml_source:
                # The XML budget element covers a reporting period, often a single year.
                row["_budget_period_only"] = True
                if aid and not de.get("aid"):
                    row["_aid_source"] = iati_aid.URL
            if decision:
                row["_period_review"] = decision
                if decision["decision"] == "verified_for_year":
                    # The target year is verified; retain the raw structured period in the audit.
                    row["_period"] = "-".join(map(str, decision["title_period"]))
            if coord_source:
                row["_coord_source"] = coord_source
            if source_coord:
                row["source_coord"] = dict(source_coord)
            if fact and year == fact["year"]:
                if any(k in fact for k in ("coverage", "place", "sites", "geonames_locality")):
                    row["source_place"] = place
                    row.pop("source_coord", None)
                    row["_location_basis"] = "public-project-evidence"
                for lang in ("ko", "en"):
                    field = "name_" + lang
                    if field in fact and fact[field] != row[field]:
                        row["_source_" + field] = row[field]
                row.update({k:v for k,v in fact.items() if k != "year"})
                if decision and decision["decision"] == "verified_period":
                    row["_period"] = decision["verified_period"]
                    for field in ("name_ko", "name_en"):
                        match = TITLE_PERIOD.search(row[field])
                        if match and title_period(row[field]) != tuple(map(int, row["_period"].split("-"))):
                            row.setdefault("_source_" + field, row[field])
                            row[field] = (row[field][:match.start(1)] + row["_period"].replace("-", "–")
                                          + row[field][match.end(2):])

            if needs_review:
                row.update(selected=False, _period_candidate=True)
                period_candidates.append(row)
            else:
                rows.append(row)

    reconcile_notices(rows, notices, year, catalog_titles, seen)
    countries = {f["country"] for f in data["features"] if f.get("country")}
    plan_audit, plan_candidates = annual_portfolio.add_plan(rows, period_candidates, country, year, countries, scopes)
    decisions = {r["id"]:r["_period_review"]["decision"] for r in rows if r.get("_period_review")}
    for item in review:
        if item["id"] in decisions:
            item["decision"] = decisions[item["id"]]
    for row in rows + period_candidates + plan_candidates:
        complete_card_metadata(row)
    for item in review:
        log(f'  · 기간 대조 {item["decision"]}: {item["name"]}')
    if region == "동구·CIS":
        region = "중동중앙아시아"
    rows.sort(key=lambda r: (not r["selected"], -(r["_budget_krw"] or 0)))
    log(f'[{country}] KOICA 사업 {len(rows)}건 수집 '
        f'· 국별협력사업 후보 {sum(1 for r in rows if r["selected"])}건 기본 선택')
    extra = {"annual_plan_audit":plan_audit, "annual_plan_candidates":plan_candidates}
    if review_partners:
        domestic = {fid.partition("@")[0] for fid in seen if fid}
        confirmed = {fid for row in rows for fid in row.get("partner_activity_ids", [])}
        activities = iati_aid.load_index(force and aid_codes is None).get("triangular", [])
        extra["partner_candidates"] = iati_aid.partner_candidates(activities, country, country_en, year, domestic, confirmed)
    if identity(country):
        extra.update(country_ko=country, country_iso3=identity(country)["iso3"])
    return {**extra, "country": country, "region": region, "year": year,
            "fetched_at": date.today().isoformat(),
            "source": SOURCE, "source_build_id": data.get("build_id"),
            "period_review": review, "period_candidates": period_candidates, "use_gazetteer": False,
            "location_status": "source-group-unverified", "projects": rows}


def collect_for_review(country, year, include_all=False, force=False, all_notices=False):
    from official_notices import add_notices
    return add_notices(collect(country, year, include_all, force, review_partners=True), force=force, all_notices=all_notices)


def main() -> int:
    ap = argparse.ArgumentParser(description="국가별 KOICA 사업 수집 (초안)")
    ap.add_argument("--country", required=True)
    ap.add_argument("--year", type=int, help="해당 연도에 진행 중인 사업만")
    ap.add_argument("--all", action="store_true", help="타기관 사업까지 포함")
    ap.add_argument("--force", action="store_true", help="캐시 무시하고 다시 받기")
    ap.add_argument("--all-notices", action="store_true", help="국가 검색 결과의 모든 페이지에서 공고 후보 확인")
    ap.add_argument("--out", default="draft.json")
    a = ap.parse_args()
    d = collect_for_review(a.country, a.year, a.all, a.force, a.all_notices)
    write_json(Path(a.out), d, indent=1)
    log(f"  → {a.out}")
    log("  ! 지명(place)은 그룹 라벨에서 뽑은 **추정값**이다 — 사람이 확인해야 한다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
