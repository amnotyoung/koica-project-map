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
