"""Shared country identities for the atlas, public catalogues and geographic sources."""
import json
import unicodedata
from functools import lru_cache

from common import REFERENCE_DIR


def key(value):
    return "".join(unicodedata.normalize("NFKC", value or "").casefold().split())


@lru_cache(maxsize=1)
def atlas_countries():
    return json.loads((REFERENCE_DIR / "atlas_countries.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _lookup():
    return {key(label):country for country in atlas_countries()
            for label in [country["ko"], country["en"], country["iso3"], country["iso2"], *country["aliases"]]}


def identity(value):
    return _lookup().get(key(value), {})


def canonical(value):
    return identity(value).get("ko", value)


def notice_query(country):
    # Use a common search stem where KOICA's bulletin uses competing Korean spellings.
    return {"COD":"콩고","KGZ":"키르기","SLB":"솔로몬"}.get(identity(country).get("iso3"), canonical(country))


def mentions_country(text, country):
    ref = identity(country)
    names = [country] if not ref else [ref["ko"], *ref["aliases"]]
    normalized = key(text)
    # Searching for Sudan or India also returns South Sudan or Indonesia in the bulletin.
    others = [entry["ko"] for entry in atlas_countries() if entry is not ref] + ["남수단"]
    for other in others:
        larger = key(other)
        if any(key(n) != larger and key(n) in larger for n in names):
            normalized = normalized.replace(larger, "")
    return any(key(name) in normalized for name in names)
