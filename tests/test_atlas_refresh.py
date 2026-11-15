import unittest
from pathlib import Path
from unittest.mock import patch

from tools.prepare_atlas import refresh_review
from location_evidence import enrich_locations


class AtlasRefreshTests(unittest.TestCase):
    def test_refresh_preserves_selection_period_and_reviewers_location(self):
        rows = [{"id":"x","selected":True,"_period":"2024-2028","place":"검토 위치",
                 "reviewed_pins":[],"_location_basis":"group-representative"},
                {"id":"y","selected":False,"place":"미선택 위치","_location_basis":"annual-plan"}]
        draft = {"year":2027,"country_iso3":"VNM","country":"베트남","projects":rows,
                 "notice_search":{"limited":False}}
        facts = {"베트남":{r["id"]:{"year":2027,"coverage":"site","place":"새 제안",
                                        "scope_sources":["example"]} for r in rows}}
        with patch("tools.prepare_atlas.read_editor", return_value=draft), \
             patch("tools.prepare_atlas.read_json", return_value=facts), \
             patch("tools.prepare_atlas.prepare_locations", side_effect=lambda doc:
                   enrich_locations(doc,{}, {}, {},descriptions={})):
            result = refresh_review(Path("."), "VNM", 2027, True)
        self.assertEqual(result["projects"][0]["place"], "검토 위치")
        self.assertEqual(result["projects"][0]["_period"], "2024-2028")
        self.assertEqual(result["projects"][0]["reviewed_pins"], [])
        self.assertFalse(result["projects"][1]["selected"])
        self.assertEqual(result["projects"][1]["place"], "미선택 위치")
