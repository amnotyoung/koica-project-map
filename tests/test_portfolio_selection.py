import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill/scripts"))
import fetch_projects
from portfolio_selection import project_key, public_additions, year_decision


class AnnualMapTests(unittest.TestCase):
    def test_unverified_title_extension_is_flagged_not_auto_promoted(self):
        title = "보건사업(’22-’26/220만불)"
        accepted, audit = year_decision(2026, "2022-2025", title, None)
        self.assertFalse(accepted)
        self.assertEqual(audit["decision"], "needs_evidence")
        verified = {"verified_years":[2026], "scope_sources":["https://example.org/project"]}
        self.assertTrue(year_decision(2026, "2022-2025", title, verified)[0])
        self.assertFalse(year_decision(2027, "2022-2025", title, verified)[0])

    def test_later_contract_can_confirm_work_after_both_catalog_dates(self):
        title = "통계사업('23-'26/965만불)"
        verified = {"verified_years":[2027], "scope_sources":["https://example.org/tender"]}
        accepted, audit = year_decision(2027, "2023-2026", title, verified)
        self.assertTrue(accepted)
        self.assertEqual(audit["source_period"], "2023-2026")
        self.assertFalse(year_decision(2028, "2023-2026", title, verified)[0])

    def test_small_explicit_bilateral_project_selected_but_not_training(self):
        def member(i, aid):
            return {"feature_id":str(i), "name":{"ko":"시험사업"}, "details":{
                "agency":"KOICA", "aid":aid, "biz_type":"국별협력사업", "budget":100,
                "start":"2025-01", "end":"2026-12"}}
        sample = {"features":[{"country":"시험국","name":{"ko":"시험국 · 도시"},"layer":"project",
                               "members":[member(1,"프로젝트 원조"),member(2,"연수")]}]}
        with patch.object(fetch_projects, "load_source", return_value=sample):
            rows = fetch_projects.collect("시험국",2026,False)["projects"]
        self.assertEqual([r["id"] for r in rows if r["selected"]], ["1"])

    def test_reference_budget_floor_handles_both_currencies_and_partial_spending(self):
        check = fetch_projects.meets_budget_floor
        self.assertTrue(check("사업(’21-’25/200만불)", {"budget":1}))
        self.assertFalse(check("사업(2022-2029/199만 달러)", {"budget":3_000_000_000}))
        self.assertTrue(check("사업(2022-2026/2,260백만원)", {}))
        self.assertTrue(check("필리핀 도시 기후회복력 역량강화 사업", {"budget":2_260_000_000}))
        self.assertFalse(check("사업 (집행액 300만불)", {"budget":2_259_999_999}))
        self.assertFalse(check("사업", {}))
        self.assertTrue(check("사업", {"amounts":{"budget":{"currency":"USD", "value":2_000_000}}}))

    def test_published_programme_is_not_counted_again_after_inventory_catches_up(self):
        notice = {"edition_year":2026, "title":"예시국 보건 사업", "scope_sources":["https://example.org/programme"],
                  "id":"notice:1","period":"2026-2029","stage":"기획","published":"2025-08-01","publisher":"KOICA"}
        self.assertEqual(len(list(public_additions([notice], 2026, set(), set()))),1)
        self.assertFalse(list(public_additions([notice], 2026, {project_key("예시국 보건사업('26-'29/100만불)")},set())))
        self.assertFalse(list(public_additions([notice], 2027,set(),set())))
