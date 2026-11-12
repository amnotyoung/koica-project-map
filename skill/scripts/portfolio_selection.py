"""Reconcile a dated map inventory with explicit periods and reviewed public notices."""
import re
import unicodedata

# Parse a project period in the title's metadata, never two numbers in prose or a budget.
TITLE_PERIOD = re.compile(r"[(（]\s*['‘’`]?(20\d{2}|\d{2})\s*[-~–—]\s*['‘’`]?(20\d{2}|\d{2})\s*(?=[/／)）])")


def title_period(title):
    match = TITLE_PERIOD.search(title)
    if not match:
        return None
    start, end = (int(s) if len(s) == 4 else 2000 + int(s) for s in match.groups())
    return (start, end) if start <= end else None


def project_key(title):
    """Exact title modulo spacing and trailing period/budget, not fuzzy similarity."""
    title = unicodedata.normalize("NFKC", title)
    match = TITLE_PERIOD.search(title)
    if match:
        title = title[:match.start()]
    return re.sub(r"\s+", "", title).casefold()


def year_decision(year, structured, title, reviewed):
    named = title_period(title)
    report = {"source_period":structured, "title_period":list(named) if named else None}
    if year is None:
        return True, None
    if reviewed and reviewed.get("year") == year and reviewed.get("scope_sources"):
        if reviewed.get("period_needs_review"):
            return False, {**report, "decision":"needs_evidence", "reason":reviewed["period_needs_review"]}
        confirmed = reviewed.get("verified_period")
        if confirmed:
            start, end = map(int, confirmed.split("-"))
            return start <= year <= end, {**report, "decision":"verified_period", "verified_period":confirmed}
    verified = bool(reviewed and year in reviewed.get("verified_years", [])
                    and reviewed.get("scope_sources"))
    if structured:
        s, e = int(structured.split("-")[0]), int(structured.split("-")[-1])
        in_field = s <= year <= e
        if named and (named[0] <= year <= named[1]) != in_field:
            report["decision"] = "needs_evidence"
            if verified:
                report["decision"] = "verified_activity_in_year" if in_field else "verified_for_year"
            return verified, report
        if verified and not in_field:
            report["decision"] = "verified_activity_in_year"
            return True, report
        return in_field, None
    return not named or named[0] <= year <= named[1], None


def public_additions(notices, year, catalog_titles, catalog_ids):
    for notice in notices:
        if year != notice["edition_year"] or not notice.get("scope_sources"):
            continue
        keys = {project_key(n) for n in [notice["title"], *notice.get("aliases", [])]}
        if keys & catalog_titles or set(notice.get("source_ids", [])) & catalog_ids:
            continue
        yield {"id":notice["id"], "_id":notice["id"], "selected":True,
               "_period":notice["period"], "_stage":notice["stage"], "_budget_krw":None,
               "_agency":"한국국제협력단(KOICA)", "_location_basis":"public-project-evidence",
               "_source_info":{"name":notice["publisher"], "url":notice["scope_sources"][0],
                               "reference_date":notice["published"]},
               **{k:notice[k] for k in ("place","name_ko","name_en","badges","coverage",
                                         "admin1_names","admin2_names","sites","place_en","scope_label","scope_label_en","recipient_country","scope_sources") if k in notice}}


def reconcile_notices(rows, notices, year, catalog_titles, catalog_ids):
    """Prefer a catalog identity and the reviewed scope when a verified crosswalk exists."""
    for notice in notices:
        if year != notice["edition_year"] or not notice.get("scope_sources"):
            continue
        ids = set(notice.get("source_ids", [])) | {notice["id"]}
        matches = [row for row in rows if row["id"] in ids]
        if not matches:
            keys = {project_key(n) for n in (notice["title"], *notice.get("aliases", []))}
            same = [r for r in rows if project_key(r["name_ko"]) in keys and r["_period"] == notice["period"]]
            if len(same) == 1 and "@" not in same[0]["id"]:
                matches = same
        if not matches:
            rows.extend(public_additions([notice], year, catalog_titles, catalog_ids))
            continue
        kept = next((r for r in matches if r["id"] == notice["id"]), matches[0])
        kept["_reconciled_ids"] = list(dict.fromkeys([r["id"] for r in matches] + [notice["id"]]))
        kept["_reconciled_sources"] = [r.get("_source_info", {}) for r in matches]
        # Remove representative coordinates before attaching the verified project scope.
        for field in ("source_coord", "_coord_source", "sites", "admin1_names", "admin2_names"):
            kept.pop(field, None)
        for field in ("name_ko", "name_en", "place", "place_en", "coverage", "badges", "sites",
                      "admin1_names", "admin2_names", "scope_label", "scope_label_en",
                      "scope_sources", "recipient_country"):
            if field in notice:
                kept[field] = notice[field]
        kept["_location_basis"] = "public-project-evidence"
        kept["_period"] = notice["period"]
        kept["selected"] = any(r["selected"] for r in matches)
        for duplicate in matches:
            if duplicate is not kept:
                rows.remove(duplicate)
