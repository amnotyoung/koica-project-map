from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fetch_projects
import resolve_places


def member(fid: str) -> dict:
    return {
        "feature_id": fid,
        "name": {"ko": f"사업 {fid}", "en": f"Project {fid}"},
        "details": {
            "stage": "사업착수",
            "start": "2025-01-01",
            "end": "2027-12-31",
            "aid": "프로젝트 원조",
            "agency": "한국국제협력단(KOICA)",
            "budget": 4_000_000_000,
            "sector": "의료서비스",
        },
    }


class FetchSourceCoordTests(unittest.TestCase):
    def test_place_guess_removes_duplicate_group_labels(self):
        self.assertEqual(
            fetch_projects._place_guess("도도마, 도도마 (진행)"),
            "도도마",
        )

    def test_collect_keeps_nonfallback_and_drops_country_fallback(self):
        data = {
            "features": [
                {
                    "country": "시험국",
                    "layer": "project",
                    "name": {"ko": "시험국 · 알파 (진행)"},
                    "lat": 10.25,
                    "lon": 20.5,
                    "details": {"region": "아시아", "source": "도시"},
                    "members": [member("city")],
                },
                {
                    "country": "시험국",
                    "layer": "project",
                    "name": {"ko": "시험국 · 베타 (진행)"},
                    "lat": 11.0,
                    "lon": 21.0,
                    "details": {"region": "아시아", "source": "국가(폴백)"},
                    "members": [member("fallback")],
                },
            ]
        }
        sector_map = {"sectors": {"H": ["의료서비스"]}, "fallback_rules": []}
        with patch.object(fetch_projects, "load_source", return_value=data), \
             patch.object(fetch_projects, "sector_map", return_value=sector_map):
            out = fetch_projects.collect("시험국", 2026, False)

        rows = {row["_id"]: row for row in out["projects"]}
        self.assertEqual(rows["city"]["source_coord"], {
            "place": "알파", "lat": 10.25, "lon": 20.5, "source": "도시"
        })
        self.assertNotIn("source_coord", rows["fallback"])
        self.assertEqual(rows["fallback"]["_coord_source"], "국가(폴백)")


class ResolveSourceCoordTests(unittest.TestCase):
    def setUp(self):
        self.places = {
            "iso3": "TST",
            "name_ko": "시험국",
            "cities": [
                {"name": "Alpha", "lon": 20.0, "lat": 10.0, "pop": 1000},
                {"name": "Beta", "lon": 30.0, "lat": 15.0, "pop": 900},
            ],
            "admin": [],
        }

    def resolve(self, entries):
        with patch.object(resolve_places, "ensure_country", return_value=self.places), \
             patch.object(resolve_places, "load_gazetteer", return_value={}):
            return resolve_places.resolve("시험국", entries)

    def test_nonfallback_coordinate_overrides_geocoder_coordinate(self):
        result = self.resolve([{
            "place": "Alpha",
            "source_coord": {
                "place": "Alpha", "lat": 10.25, "lon": 20.5, "source": "도시"
            },
        }])
        part = result["places"][0]["parts"][0]
        self.assertTrue(result["places"][0]["resolved"])
        self.assertEqual((part["lat"], part["lon"]), (10.25, 20.5))
        self.assertEqual(part["source"], "oda-map-lab")
        self.assertEqual(part["coord_source"], "도시")

    def test_country_fallback_coordinate_is_ignored(self):
        result = self.resolve([{
            "place": "Alpha",
            "source_coord": {
                "place": "Alpha", "lat": 10.25, "lon": 20.5,
                "source": "국가(폴백)",
            },
        }])
        part = result["places"][0]["parts"][0]
        self.assertEqual((part["lat"], part["lon"]), (10.0, 20.0))
        self.assertEqual(part["source"], "auto")

    def test_changed_place_invalidates_source_coordinate(self):
        result = self.resolve([{
            "place": "Beta",
            "source_coord": {
                "place": "Alpha", "lat": 10.25, "lon": 20.5, "source": "도시"
            },
        }])
        part = result["places"][0]["parts"][0]
        self.assertEqual((part["lat"], part["lon"]), (15.0, 30.0))
        self.assertEqual(part["source"], "auto")

    def test_multi_site_does_not_clone_single_source_coordinate(self):
        result = self.resolve([{
            "place": "Alpha/Beta",
            "source_coord": {
                "place": "Alpha/Beta", "lat": 10.25, "lon": 20.5, "source": "도시"
            },
        }])
        parts = result["places"][0]["parts"]
        self.assertEqual([(p["lat"], p["lon"]) for p in parts],
                         [(10.0, 20.0), (15.0, 30.0)])
        self.assertTrue(all(p["source"] == "auto" for p in parts))

    def test_manual_gazetteer_stays_above_source_coordinate(self):
        manual = {
            "TST:alpha": {
                "matched": "Alpha manual",
                "level": "manual",
                "kind": "point",
                "lat": 9.5,
                "lon": 19.5,
                "score": 1.0,
            }
        }
        entry = {
            "place": "Alpha",
            "source_coord": {
                "place": "Alpha", "lat": 10.25, "lon": 20.5, "source": "도시"
            },
        }
        with patch.object(resolve_places, "ensure_country", return_value=self.places), \
             patch.object(resolve_places, "load_gazetteer", return_value=manual):
            result = resolve_places.resolve("시험국", [entry])

        part = result["places"][0]["parts"][0]
        self.assertEqual((part["lat"], part["lon"]), (9.5, 19.5))
        self.assertEqual(part["source"], "gazetteer")


if __name__ == "__main__":
    unittest.main()
