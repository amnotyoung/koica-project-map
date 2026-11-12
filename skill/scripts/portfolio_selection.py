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
    verified = bool(reviewed and year in reviewed.get("verified_years", [])
                    and reviewed.get("scope_sources"))
    if structured:
        s, e = int(structured.split("-")[0]), int(structured.split("-")[-1])
        in_field = s <= year <= e
        if named and (named[0] <= year <= named[1]) != in_field:
            # Preserve both values. Never turn a title-only extension into proven execution.
            report["decision"] = ("verified_for_year" if verified else
                                  "included_by_field_review" if in_field else "needs_evidence")
            return in_field or verified, report
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
                                         "admin1_names","admin2_names","sites","recipient_country","scope_sources") if k in notice}}
