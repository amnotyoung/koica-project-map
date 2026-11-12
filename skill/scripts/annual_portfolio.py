"""Reconcile a country's catalogue with the government-wide annual budget tables."""
import hashlib
import re
from difflib import SequenceMatcher

from country_names import atlas_countries, canonical
from common import REFERENCE_DIR, read_json
from portfolio_selection import project_key, title_period


def match_key(title):
    return re.sub(r"[^가-힣a-z0-9]", "", project_key(title))


def funded(record):
    value = record["annual_100m_krw"].replace(",", "")
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", value)) and float(value) > 0


def country_rows(index, country, countries, year):
    # Longest prefix distinguishes India from Indonesia and Niger from Nigeria.
    labels = {label for c in atlas_countries() for label in [c["ko"], *c["aliases"]]}
    names = sorted(set(countries) | labels | {country}, key=len, reverse=True)
    for row in index.get("projects", []):
        account = re.sub(r"^\[\d+\]|\(ODA\)$", "", row["account"])
        title = re.sub(r"\s+", "", row["title"])
        owner = account if account in names else next((n for n in names if n and title.startswith(n)), None)
        start, end = map(int, row["period"].split("-"))
        if canonical(owner) == canonical(country) and start <= year <= end:
            yield row


def reconcile(rows, pending, country, year, countries, target, previous, display, period_candidates=None):
    prior = {}
    for record in country_rows(previous, country, countries, year):
        if funded(record):
            prior.setdefault(match_key(record["title"]), []).append(record)
    audit = []
    for record in country_rows(target, country, countries, year):
        title = record["title"]
        key = match_key(title)
        if not key:
            continue
        proofs = [{"resolution":target["resolution"], "basis":target["basis"], **record}]
        history = prior.get(key, [])
        if len(history) == 1:
            proofs.append({"resolution":previous["resolution"], "basis":previous["basis"], **history[0]})
        corroborated = funded(record) and (target["basis"] == "confirmed" or
                                           (record["status"] == "계속" and len(history) == 1))
        candidates = rows + pending + (period_candidates or [])
        exact = [r for r in candidates if any(match_key(r.get(k) or "") == key
                                              for k in ("name_ko", "_source_name_ko"))]
        if exact:
            for r in exact:
                r.setdefault("_annual_plan", []).extend(proofs)
                if (corroborated and r.get("_period_candidate") and not r.get("period_needs_review")
                        and not r.get("_done") and not r.get("_other") and period_candidates is not None
                        and title_period(r["name_ko"]) == tuple(map(int, record["period"].split("-")))):
                    period_candidates.remove(r)
                    r.pop("_period_candidate")
                    r.update(selected=True, _period=record["period"])
                    r["_period_review"] = {**r["_period_review"], "decision":"verified_by_annual_plan"}
                    rows.append(r)
            audit.append({"title":title, "result":"catalog_match" if any(r.get("selected") for r in exact) else "review", "ids":[r["id"] for r in exact]})
            continue
        identity = hashlib.sha256(key.encode()).hexdigest()[:16]
        fid = f"plan:{country}:{identity}"
        possible = [r["id"] for r in candidates if any(
            SequenceMatcher(None, key, match_key(name), autojunk=False).ratio() >= .64
            or (not re.search("[가-힣]", name) and (r.get("_period") or "").split("-")[0] == record["period"].split("-")[0])
            for name in (r.get("name_ko"), r.get("_source_name_ko")) if name)]
        selected = corroborated and not possible
        row = {"id":fid, "_id":fid, "selected":selected, "_period":record["period"],
               "name_ko":title, "name_en":"", "place":"", "coverage":"unknown", "badges":[],
               "_agency":"한국국제협력단(KOICA)", "_budget_krw":None, "_stage":"계속" if selected else "시행계획 검토",
               "_location_basis":"annual-plan", "_annual_plan":proofs, "scope_sources":[target["source"]]}
        if selected:
            # Presentation metadata is applied after admission and cannot change the roster.
            labels = display.get(fid, {})
            if labels.get("year") == year and labels.get("scope_sources"):
                for k in ("name_ko","name_en","_period","badges","place","place_en","coverage","scope_label","scope_label_en",
                          "admin1_names","admin2_names","sites","geonames_locality","partner_activity_ids"):
                    if k in labels:
                        row[k] = labels[k]
                row["scope_sources"] += labels["scope_sources"]
            rows.append(row)
        else:
            if possible:
                row["_possible_catalog_ids"] = possible
            pending.append(row)
        audit.append({"title":title, "result":"added" if selected else "review", "ids":[fid]})
    return audit


def add_plan(rows, period_candidates, country, year, countries, display):
    if year is None:
        return [], []
    folder = REFERENCE_DIR / "annual_portfolio"
    target_file = folder / f"{year}-confirmed.json"
    if not target_file.exists():
        target_file = folder / f"{year}-requested.json"
    if not target_file.exists():
        return [], []
    previous_file = folder / f"{year-1}-confirmed.json"
    previous = read_json(previous_file) if previous_file.exists() else {}
    pending = []
    audit = reconcile(rows, pending, country, year, countries, read_json(target_file), previous, display, period_candidates)
    return audit, pending
