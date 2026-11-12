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

    def test_structured_only_extension_needs_confirmation_too(self):
        title = "교육사업('21-'25/283만불)"
        accepted, audit = year_decision(2027, "2021-2027", title, None)
        self.assertFalse(accepted)
        self.assertEqual(audit["decision"], "needs_evidence")
        fact = {"verified_years":[2027], "scope_sources":["https://example.org/project"]}
        self.assertEqual(year_decision(2027, "2021-2027", title, fact)[1]["decision"], "verified_activity_in_year")

    def test_reviewed_period_reaches_selection_before_stale_title_and_dates(self):
        fact = {"year":2027, "verified_period":"2025-2028", "scope_sources":["https://example.org/signed"]}
        member = {"feature_id":"p", "name":{"ko":"사업(2025-2026/560만불)", "en":"Programme"},
                  "details":{"agency":"KOICA", "aid":"프로젝트 원조", "biz_type":"국별협력사업",
                             "start":"2025", "end":"2026"}}
        sample = {"features":[{"country":"시험국","name":{"ko":"시험국"},"layer":"project","members":[member]}]}
        def reference(path):
            return {"시험국":{"p":fact}} if path.name == "public_project_scopes.json" else {}
        with patch.object(fetch_projects, "load_source", return_value=sample), patch.object(fetch_projects, "read_json", side_effect=reference):
            row = fetch_projects.collect("시험국",2027,False)["projects"][0]
        self.assertTrue(row["selected"])
        self.assertEqual(row["_period"], "2025-2028")
        self.assertIn("2025–2028", row["name_ko"])
        self.assertIn("2025–2028", row["name_en"])
        self.assertEqual(row["_period_review"]["source_period"], "2025-2026")
        self.assertEqual(row["_source_name_ko"], member["name"]["ko"])
        self.assertFalse(year_decision(2027, "2025-2026", "", {**fact, "scope_sources":[]})[0])
        accepted, audit = year_decision(2027,"2025-2026","",{**fact,"period_needs_review":"출처 간 불일치"})
        self.assertFalse(accepted)
        self.assertEqual(audit["decision"], "needs_evidence")

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

    def test_missing_xml_aid_uses_official_code_and_hides_annual_budget(self):
        import iati_aid
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            xml = Path(tmp) / "source.xml"
            xml.write_text('<iati-activities><iati-activity><iati-identifier>KR-GOV-010-KR-GOV-051-1</iati-identifier><default-aid-type code="C01"/></iati-activity></iati-activities>')
            index = iati_aid.read_codes(xml)
        member = {"feature_id":"iati:KR-GOV-051-1", "name":{"ko":"시설사업", "en":"Facilities"},
                  "details":{"agency":"KOICA","biz_type":"국별협력사업","budget":100000000,
                  "source_info":{"url":iati_aid.URL}, "start":"2026","end":"2030"}}
        sample = {"features":[{"country":"시험국","name":{"ko":"수도"},"layer":"project","members":[member]}]}
        with patch.object(fetch_projects,"load_source",return_value=sample), patch.object(iati_aid,"load_codes",return_value=index):
            row = fetch_projects.collect("시험국",2027,False)["projects"][0]
        self.assertTrue(row["selected"])
        self.assertEqual(row["name_en"], "Facilities (2026–2030)")
        self.assertEqual(row["_aid_source"], iati_aid.URL)

    def test_reference_budget_floor_handles_both_currencies_and_partial_spending(self):
        check = fetch_projects.meets_budget_floor
        self.assertTrue(check("사업(’21-’25/200만불)", {"budget":1}))
        self.assertFalse(check("사업(2022-2029/199만 달러)", {"budget":3_000_000_000}))
        self.assertTrue(check("사업(2022-2026/2,260백만원)", {}))
        self.assertTrue(check("필리핀 도시 기후회복력 역량강화 사업", {"budget":2_260_000_000}))
        self.assertFalse(check("사업 (집행액 300만불)", {"budget":2_259_999_999}))
        self.assertFalse(check("사업", {}))
        self.assertTrue(check("사업", {"amounts":{"budget":{"currency":"USD", "value":2_000_000}}}))

    def test_bilingual_metadata_preserves_amounts_and_reviewed_differences(self):
        row = {"name_ko":"시험('25-'29/850만불)", "name_en":"Training",
               "_period":"2025-2028", "_budget_krw":90}
        fetch_projects.complete_card_metadata(row)
        self.assertEqual(row['name_en'], "Training (2025–2029 / USD 8.5m)")
        self.assertEqual(row['_period'], "2025-2028")
        self.assertEqual(row['_source_name_en'], "Training")
        row.update(name_ko="통계사업 (965만 불·2027년 과업 예정)", name_en="Statistics (USD 9.65m; work scheduled in 2027)")
        expected = row.copy()
        fetch_projects.complete_card_metadata(row)
        self.assertEqual(expected,row)
        row.update(name_ko="시설",name_en="Facility",_reported_budget={"value":4000,"currency":"USD"})
        fetch_projects.complete_card_metadata(row)
        self.assertIn("USD",row["name_en"])
        self.assertNotIn("KRW",row["name_en"])

    def test_confirmed_catalog_and_notice_ids_render_once_with_reviewed_scope(self):
        from portfolio_selection import reconcile_notices
        notice = {"id":"official:1","title":"농업","period":"2026-2034","edition_year":2027,
                  "source_ids":["iati:a","iati:b"],"scope_sources":["https://example.org"],
                  "coverage":"admin2","admin2_names":["A","B"],"place":"A·B"}
        rows = [{"id":i,"name_ko":"농업사업","_period":"2026-2034","selected":True,
                 "source_coord":{"lon":1,"lat":1}} for i in ["iati:a","iati:b"]]
        reconcile_notices(rows,[notice],2027,set(),set())
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["admin2_names"],["A","B"])
        self.assertNotIn("source_coord",rows[0])
        self.assertEqual(set(rows[0]["_reconciled_ids"]),{"iati:a","iati:b","official:1"})

    def test_date_conflict_survives_as_unselected_review_candidate(self):
        member = {"feature_id":"item","name":{"ko":"교육 사업('25-'29/500만불)", "en":"Education"},
                  "details":{"agency":"KOICA", "aid":"프로젝트 원조", "biz_type":"국별협력사업",
                             "start":"2025-01", "end":"2025-12", "budget":1_000_000_000}}
        data = {"features":[{"country":"시험국","name":{"ko":"시험국 · 수도"},
                              "layer":"project_done","members":[member]}]}
        with patch.object(fetch_projects, "load_source", return_value=data):
            doc = fetch_projects.collect("시험국", 2027, False)
        self.assertEqual(doc["projects"], [])
        self.assertEqual(doc["period_candidates"][0]["id"], "item")
        self.assertFalse(doc["period_candidates"][0]["selected"])
        self.assertEqual(doc["period_candidates"][0]["_period"], "2025-2025")

    def test_published_programme_is_not_counted_again_after_inventory_catches_up(self):
        notice = {"edition_year":2026, "title":"예시국 보건 사업", "scope_sources":["https://example.org/programme"],
                  "id":"notice:1","period":"2026-2029","stage":"기획","published":"2025-08-01","publisher":"KOICA"}
        self.assertEqual(len(list(public_additions([notice], 2026, set(), set()))),1)
        self.assertFalse(list(public_additions([notice], 2026, {project_key("예시국 보건사업('26-'29/100만불)")},set())))
        self.assertFalse(list(public_additions([notice], 2027,set(),set())))
