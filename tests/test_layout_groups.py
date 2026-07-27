from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from common import design_tokens
import layout
import render_html


def project_card(place: str, name: str, point: dict | None = None) -> dict:
    tok = design_tokens()
    card = layout.build_card(
        {"place": place, "badges": ["H"], "name_ko": name}, tok, "ko", 1.0
    )
    card["points"] = [dict(point)] if point else []
    card["nationwide"] = point is None
    return card


class PlaceGroupTests(unittest.TestCase):
    def test_empty_resolution_is_not_nationwide(self):
        self.assertFalse(layout._is_nationwide([]))
        self.assertTrue(layout._is_nationwide([{"kind": "nationwide"}]))

    def test_long_place_heading_shrinks_to_card_width(self):
        tok = design_tokens()
        place = "키체/케찰테낭고/토토니카판/솔롤라/치말테낭고 주"
        card = project_card(place, "여러 지역 사업", {"x": 1, "y": 1, "lon": 1, "lat": 1})
        self.assertLess(card["place_font"], tok["card"]["place"]["size"])
        self.assertLessEqual(card["place_w"], tok["card"]["name"]["w"] + 0.0001)

    def test_same_place_is_one_heading_and_one_leader(self):
        tok = design_tokens()
        suva = {
            "x": 5.36, "y": 5.23, "lon": 178.42531, "lat": -18.13683,
            "marker_kind": "point",
        }
        ovalau = {
            "x": 6.01, "y": 4.38, "lon": 178.78762, "lat": -17.68148,
            "marker_kind": "point",
        }
        cards = [
            project_card("수바", "첫 번째 수바 사업", suva),
            project_card("오발라우", "오발라우 사업", ovalau),
            project_card("수바", "두 번째 수바 사업", suva),
            project_card("수바", "세 번째 수바 사업", suva),
        ]

        groups = layout._group_cards(cards, tok)
        self.assertEqual([g["place"] for g in groups], ["수바", "오발라우"])
        suva_group = groups[0]
        self.assertEqual([c["show_place"] for c in suva_group["items"]],
                         [True, False, False])
        self.assertEqual(len(suva_group["points"]), 1)

        suva_group.update({"x": 8.9, "y": 1.2, "side": "right",
                           "anchor": [8.9, 1.275]})
        leaders = layout._leaders_of_card(suva_group)
        self.assertEqual(len(leaders), 1)
        self.assertEqual(leaders[0]["place"], "수바")

        flat = layout._flatten_groups([suva_group], tok["card"]["gap"])
        self.assertEqual(sum(1 for c in flat if c["show_place"]), 1)
        self.assertTrue(flat[1]["y"] > flat[0]["y"])
        self.assertEqual(flat[1]["body_dy"], 0.0)

    def test_nationwide_projects_share_heading_without_leader(self):
        tok = design_tokens()
        groups = layout._group_cards([
            project_card("피지 전역", "전국사업 1"),
            project_card("피지 전역", "전국사업 2"),
        ], tok)
        self.assertEqual(len(groups), 1)
        group = groups[0]
        group["anchor"] = [8.9, 1.2]
        self.assertEqual(layout._leaders_of_card(group), [])

    def test_mode_selection_does_not_merge_same_label_at_different_coordinates(self):
        tok = design_tokens()
        projects = [
            {"place": "동명 지역", "badges": ["H"], "name_ko": "첫 사업"},
            {"place": "동명 지역", "badges": ["H"], "name_ko": "둘째 사업"},
        ]
        resolved = {
            "places": [
                {"parts": [{"ok": True, "kind": "city", "lon": 1.0, "lat": 2.0,
                            "matched": "Place A"}]},
                {"parts": [{"ok": True, "kind": "city", "lon": 3.0, "lat": 4.0,
                            "matched": "Place B"}]},
            ],
        }
        with patch.object(layout, "_group_cards", wraps=layout._group_cards) as grouped:
            layout.choose_mode({"projects": projects}, tok, "ko", resolved)
        cards = grouped.call_args.args[0]
        self.assertEqual(len(layout._group_cards(cards, tok)), 2)


class TitleLayoutTests(unittest.TestCase):
    def test_korean_title_uses_one_inline_rich_text_box(self):
        tok = design_tokens()
        title = layout._title_layout("피지", "Fiji", "ko", tok)
        self.assertEqual(title["mode"], "inline_runs")
        self.assertEqual([r["text"] for r in title["runs"]], ["피지 ", "Fiji"])
        self.assertAlmostEqual(title["x"], 2.96902, places=5)
        self.assertAlmostEqual(title["y"], 0.52466, places=5)
        self.assertAlmostEqual(title["w"], 0.68294, places=5)
        self.assertAlmostEqual(title["h"], 0.25910, places=5)
        self.assertEqual(title["runs"][0]["size"], 23.09)
        self.assertEqual(title["runs"][0]["baseline"], -5787)
        self.assertEqual(title["runs"][0]["spacing"], -96)

    def test_english_title_matches_source_textbox(self):
        tok = design_tokens()
        title = layout._title_layout("피지", "Fiji", "en", tok)
        self.assertEqual(title["mode"], "single_run")
        self.assertEqual([r["text"] for r in title["runs"]], ["Fiji"])
        self.assertAlmostEqual(title["x"], 3.14311, places=5)
        self.assertAlmostEqual(title["y"], 0.53375, places=5)
        self.assertAlmostEqual(title["w"], 0.31860, places=5)
        self.assertAlmostEqual(title["h"], 0.23744, places=5)
        self.assertEqual(title["runs"][0]["size"], 14.11)

    def test_html_title_flows_runs_inline_without_fixed_country_offset(self):
        tok = design_tokens()
        title = layout._title_layout("우즈베키스탄", "Uzbekistan", "ko", tok)
        self.assertNotIn("html_en_dx", title)
        svg = render_html.draw_title(
            {"index": 2, "title": title, "country": {
                "ko": "우즈베키스탄", "en": "Uzbekistan",
            }, "lang": "ko"},
            tok,
        )
        self.assertEqual(svg.count("<text "), 2)  # 국가명 + 핀의 II
        self.assertEqual(svg.count("<tspan "), 2)
        self.assertIn("우즈베키스탄 ", svg)
        self.assertIn(">Uzbekistan</tspan>", svg)
        self.assertNotIn("letter-spacing", svg)
        self.assertLess(svg.index("<text "), svg.index("<path "))
        self.assertIn("font-family: Georgia", svg)

    def test_html_english_title_does_not_apply_ppt_tracking_as_svg_spacing(self):
        tok = design_tokens()
        title = layout._title_layout("피지", "Fiji", "en", tok)
        svg = render_html.draw_title(
            {"index": 2, "title": title,
             "country": {"ko": "피지", "en": "Fiji"}, "lang": "en"},
            tok,
        )
        self.assertIn(">Fiji</text>", svg)
        self.assertNotIn("letter-spacing", svg)


if __name__ == "__main__":
    unittest.main()
