"""Freeze bilingual country inputs and check pagination and geography without rendering slides."""
import argparse
import csv
from collections import Counter
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

from lxml import html

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill/scripts"))
from country_names import atlas_countries
from fetch_projects import collect_for_review, prepare_locations
from common import REFERENCE_DIR, read_json
from official_notices import add_notices
from layout import compute_pages
from pick_projects import export_editor, persist
from project_scope import edition_fields, LOCATION_FIELDS, prepare_projects


def read_editor(folder, iso):
    tree = html.fromstring((folder / "editors" / (iso + ".html")).read_text(encoding="utf-8"))
    return json.loads(tree.get_element_by_id("payload").text)


def refresh_review(baseline, iso, year, review_geo, missing_ids=None):
    # Refresh locations and candidates without changing the reviewer’s selection.
    doc = read_editor(baseline, iso)
    if doc["year"] != year or doc["country_iso3"] != iso:
        raise ValueError("준비 목록과 검토 국가·연도가 일치하지 않습니다")
    facts = read_json(REFERENCE_DIR / "public_project_scopes.json").get(doc["country"], {})
    location_rows = []
    for row in doc["projects"]:
        row.pop("_review_location", None)
        if (not review_geo or not row["selected"] or row.get("_location_basis") == "manager-reviewed"
                or "reviewed_pins" in row or "reviewed_unresolved" in row):
            continue
        if missing_ids is not None and row["id"].partition("@")[0] not in missing_ids and row["id"] not in missing_ids:
            continue
        location_rows.append(row)
        fact = edition_fields(facts.get(row["id"]), year)
        if (fact.get("scope_sources") and "coverage" in fact
                and row.get("_location_basis") in {"group-representative","annual-plan"}):
            row["source_place"] = row["place"]
            row.pop("source_coord", None)
            sources = list(dict.fromkeys([*(row.get("scope_sources") or []), *fact["scope_sources"]]))
            row.update({k: fact[k] for k in LOCATION_FIELDS if k in fact})
            row["scope_sources"] = sources
            row["_location_basis"] = "public-project-evidence"
        if row.get("_title_region") and row.get("coverage") in {"adm1","adm2"}:
            old = row.pop("coverage")
            row["coverage"] = old.replace("adm","admin")
            row[row["coverage"]+"_names"] = row.pop(old+"_names")
    if location_rows:
        prepare_locations({**doc, "projects":location_rows})
    if doc["notice_search"]["limited"]:
        doc = add_notices(doc, all_notices=True)
    return doc


def write_notice_comparison(baseline, prepared, countries):
    def links(doc):
        return {url: row for row in doc["notice_candidates"] for url in row["scope_sources"]}

    with (prepared / "공고대조.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["국가", "변동", "공고 URL", "기존 후보 ID", "현재 후보 ID", "현재 후보 사업명",
                         "추출 사업기간", "비슷한 기존 사업 ID", "기존 후보 사업명"])
        for country in countries:
            iso = country["iso3"]
            old = read_editor(baseline, iso)
            if not old["notice_search"]["limited"]:
                continue
            before, after = links(old), links(read_editor(prepared, iso))
            for url in sorted(before.keys() | after.keys()):
                prev, curr = before.get(url, {}), after.get(url, {})
                change = "추가" if not prev else "제외" if not curr else "유지"
                writer.writerow([country["country"], change, url, prev.get("id"), curr.get("id"),
                                 curr.get("name_ko"), curr.get("_period"), curr.get("_similar_project_id"),
                                 prev.get("name_ko")])


def check_country(job):
    ref, year, out, baseline, review_geo, missing_ids = job
    iso, country = ref["iso3"], ref["ko"]
    doc = refresh_review(baseline, iso, year, review_geo, missing_ids) if baseline else collect_for_review(country, year)
    doc["map_languages"] = ["ko","en"]
    selected = [r for r in doc["projects"] if r["selected"]]
    input_doc = {**doc, "projects":selected}
    input_doc.pop("notice_candidates", None)
    pages = compute_pages(input_doc, ["ko","en"], detail="10m", render_background=False) if selected else []
    issues = []
    def issue(card, reason):
        evidence = card.get("provenance", {})
        return {"country":country,"id":card["project_id"],"reason":reason,"title":card["text"],
                "reported_places":" / ".join(evidence.get("_iati_reported_places", [])),
                "source":" ".join(evidence.get("scope_sources") or [(evidence.get("_source_info") or {}).get("url") or doc["source"]])}

    langs = {}
    for lang in ("ko","en"):
        langs[lang] = [p for p in pages if p["lang"] == lang]
    expected = Counter(r["id"] for r in prepare_projects(input_doc)["projects"])
    if len(langs["ko"]) != len(langs["en"]):
        raise ValueError(f"{country} 국·영문 페이지 수 불일치")
    for lang, language_pages in langs.items():
        rendered = Counter(c["project_id"] for p in language_pages for c in p["cards"])
        if rendered != expected or any(count != 1 for count in rendered.values()):
            raise ValueError(f"{country} {lang} 배치에서 사업 식별자 누락 또는 중복")
    for ko, en in zip(langs["ko"], langs["en"]):
        if {r["project_id"] for r in ko["cards"]} != {r["project_id"] for r in en["cards"]}:
            raise ValueError(f"{country} 국·영문 페이지별 사업 불일치")
        for page in (ko,en):
            if not page["fits"] or page["text_hits"]:
                raise ValueError(f"{country} {page['lang']} 설명 배치 초과")
        for card in ko["cards"]:
            if not card["points"] and not card["nationwide"] and not card.get("external"):
                issues.append(issue(card, "사업지 확인"))
            elif card.get("location_note"):
                issues.append(issue(card, "위치 근거 확인"))
            if not re.search("[가-힣]",card["text"]):
                raise ValueError(f"{country} 국문 사업명 누락: {card['project_id']}")
        for card in en["cards"]:
            if re.search("[가-힣]",card["text"]) or not re.search("[A-Za-z]",card["text"]):
                raise ValueError(f"{country} 영문 사업명 누락: {card['project_id']}")
    parent_ids = {i["id"] for i in issues}
    for r in doc["projects"]:
        if r["id"] in parent_ids or r["id"].partition("@")[0] in parent_ids:
            r["_review_location"] = True
    input_path = out / "inputs" / (iso + ".json")
    if selected:
        persist(input_path, input_doc)
    export_editor(out / "editors" / (iso + ".html"), doc)
    report = {"country":country,"iso3":iso,"projects":sum(len(l["cards"]) for l in langs["ko"]),
              "pages_per_language":len(langs["ko"]), "location_reviews":len(issues),
              "crossings":sum(p["crossings"] for p in pages),
              "notice_status":doc["notice_search"]["status"],"notice_candidates":len(doc["notice_candidates"]),
              "period_candidates":len(doc["period_candidates"]), "plan_candidates":len(doc["annual_plan_candidates"]),
              "status":"ready" if selected else "no_confirmed_projects"}
    if selected:
        report["input"] = str(input_path.relative_to(out))
    return report, issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year",type=int,required=True)
    parser.add_argument("--outdir",type=Path,required=True)
    parser.add_argument("--baseline",type=Path,help="기존 선정 목록을 유지하고 위치 근거와 제한된 공고 검색을 갱신")
    parser.add_argument("--location-countries", nargs="+", metavar="ISO3", help="위치 근거를 다시 판정할 국가 (기본 전체)")
    parser.add_argument("--missing-sites-only", action="store_true", help="기존 사업지 미확정 항목만 재판정")
    parser.add_argument("--workers",type=int,default=2)
    args = parser.parse_args()
    out = args.outdir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    records, issues = [], []
    if args.baseline and args.baseline.resolve() == out:
        parser.error("기존 준비 자료와 다른 출력 폴더를 지정하세요.")
    targets = set(args.location_countries or [c["iso3"] for c in atlas_countries()])
    if targets - {c["iso3"] for c in atlas_countries()}:
        parser.error("모르는 ISO3 국가 코드")
    missing = None
    if args.missing_sites_only:
        if not args.baseline:
            parser.error("--missing-sites-only에는 --baseline이 필요합니다")
        with (args.baseline / "위치검토.csv").open(encoding="utf-8-sig") as stream:
            missing = {(row["country"],row["id"]) for row in csv.DictReader(stream) if row["reason"]=="사업지 확인"}
    jobs=[(c,args.year,out,args.baseline,c["iso3"] in targets,
           {i for country,i in missing if country==c["ko"]} if missing is not None else None)
          for c in atlas_countries()]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for summary, problems in pool.map(check_country, jobs):
            records.append(summary)
            issues.extend(problems)
            print(summary["iso3"],summary["status"],summary["projects"],flush=True)
    with (out / "위치검토.csv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["country","id","reason","title","reported_places","source"])
        w.writeheader()
        w.writerows(issues)
    ready = sum(r["status"] == "ready" for r in records)
    cards = sum(r["projects"] for r in records)
    pages = sum(r["pages_per_language"] * 2 for r in records)
    table = [f"# {args.year}년 국별 프로젝트맵 생성 준비", "",
             f"{len(records)}개국 점검 · 생성 입력 {ready}개국 · 선정 {cards}건 · 국·영문 예상 {pages}쪽", "",
             "각 국가의 편집 화면에서 사업 선택과 위치를 검토할 수 있다. 위치 확인 건에는 미확정 사업지와 대표좌표 검토가 포함된다. 공고 후보는 포함 여부를 개별 검토한다.", "",
             "[위치 검토 목록](위치검토.csv) · [생성 입력 목록](manifest.json)", "",
             "| 국가 | 선정 사업 | 언어별 예정 쪽 | 위치 확인 | 기간 확인 | 공고 후보 | 준비 결과 |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for r in records:
        status = f"[입력 JSON]({r['input']})" if r.get("input") else f"{args.year}년 수행 확인 필요"
        table.append(f"| [{r['country']}](editors/{r['iso3']}.html) | {r['projects']} | {r['pages_per_language']} | "
                     f"{r['location_reviews']} | {r['period_candidates']} | {r['notice_candidates']} | {status} |")
    (out / "국가별 준비현황.md").write_text("\n".join(table)+"\n", encoding="utf-8")
    if args.baseline:
        write_notice_comparison(args.baseline, out, records)
    persist(out / "manifest.json", {"year":args.year, "checked_at":date.today().isoformat(), "countries":records})


if __name__ == "__main__":
    main()
