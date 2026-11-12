"""Regression tests for decisions that change which title and sources reach the map."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"skill/scripts"))
from common import design_tokens
from layout import build_card
from source_notes import source_notes


class ReviewSaveTests(unittest.TestCase):
    def test_only_an_explicit_period_choice_changes_the_printed_date(self):
        title = "낙농사업(‘23-’28/1,000만불)"
        row = {"name_ko":title, "_period":"2024-2028"}
        self.assertEqual(build_card(row,design_tokens(),"ko",1)["text"],title)
        row["_editor_period"] = {"source":"2024-2028","title":"2023-2028","choice":"source"}
        self.assertEqual(build_card(row,design_tokens(),"ko",1)["text"],"낙농사업(2024-2028/1,000만불)")
        self.assertEqual(row["name_ko"],title)

    def test_linked_notice_and_location_evidence_are_kept_separate(self):
        row = {"name_ko":"사업", "place":"구역", "_location_evidence":"현장 점검",
               "_linked_notices":[{"title":"기획 공고","urls":["https://example.org/notice"]}]}
        card = build_card(row,design_tokens(),"ko",1)
        result = source_notes({"map":{}, "cards":[card]})
        self.assertIn("사업지 확인 근거 · 현장 점검",result)
        self.assertIn("연결한 공고 기획 공고 · https://example.org/notice",result)
