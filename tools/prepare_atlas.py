"""Freeze bilingual country inputs and check pagination and geography without rendering slides."""
import argparse
import csv
from collections import Counter
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill/scripts"))
from country_names import atlas_countries
from fetch_projects import collect_for_review
from layout import compute_pages
from pick_projects import export_editor, persist
from project_scope import prepare_projects


def check_country(job):
    ref, year, out = job
    iso, country = ref["iso3"], ref["ko"]
    doc = collect_for_review(country, year)
    doc["map_languages"] = ["ko","en"]
    selected = [r for r in doc["projects"] if r["selected"]]
    input_doc = {**doc, "projects":selected}
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
    parser.add_argument("--workers",type=int,default=2)
    args = parser.parse_args()
    out = args.outdir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    records, issues = [], []
    jobs=[(c,args.year,out) for c in atlas_countries()]
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
    persist(out / "manifest.json", {"year":args.year, "checked_at":date.today().isoformat(), "countries":records})


if __name__ == "__main__":
    main()
