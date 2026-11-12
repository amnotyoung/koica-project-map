import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill/scripts"))
from annual_portfolio import reconcile


class AnnualPortfolioTests(unittest.TestCase):
    def test_source_first_recovery_and_review_without_project_exceptions(self):
        def entry(name, amount="1.0", status="계속"):
            return {"title":name, "account":"[405]중남미지역일반협력국가그룹(ODA)",
                    "period":"2026-2029", "annual_100m_krw":amount, "status":status, "page":2}
        titles = ["예시국 학교 건축", "예시국 조세 행정", "예시국 농산물 유통", "예시국 지적 재조사"]
        prior = {"basis":"confirmed","resolution":"A","projects":[entry(titles[0]), entry(titles[2])]}
        target = {"basis":"requested","resolution":"B","source":"https://example.org",
                  "projects":[entry(titles[0]),entry(titles[1],status="신규"),entry(titles[2],amount="-"),entry(titles[3])]}
        existing = [{"id":"legacy","name_ko":titles[3],"selected":True}]
        pending = []
        audit = reconcile(existing, pending, "예시국", 2027, ["예시국"], target, prior, {})
        self.assertEqual([p["result"] for p in audit], ["added","review","review","catalog_match"])
        self.assertEqual(len(existing), 2)
        self.assertTrue(all(not p["selected"] for p in pending))
        self.assertEqual(len(existing[1]["_annual_plan"]),2)

    def test_similar_titles_are_not_silently_merged_and_country_prefix_is_unambiguous(self):
        row = {"title":"인도네시아 토양 정보 현대화","account":"일반협력국가그룹","period":"2025-2028",
               "page":2,"annual_100m_krw":"1","status":"계속"}
        target = {"basis":"confirmed","resolution":"A","source":"source","projects":[row]}
        countries = ["인도","인도네시아"]
        self.assertFalse(reconcile([], [], "인도", 2027, countries, target, {}, {}))
        existing = [{"id":"old","name_ko":row["title"]+" 2차","selected":True,"_period":row["period"]}]
        pending = []
        reconcile(existing, pending, "인도네시아", 2027, countries, target, {}, {})
        self.assertEqual(pending[0]["_possible_catalog_ids"],["old"])
        self.assertEqual(len(existing),1)
