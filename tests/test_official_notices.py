import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill/scripts"))
from official_notices import BOARD, candidate, discover, parse_board
from pick_projects import editor_html


class OfficialNotices(unittest.TestCase):
    def test_country_and_project_year_not_application_dates(self):
        t = "예시국 교사 양성사업 예비조사 전문가 공모"
        content = t+"\n접수기간 2025-2026\n사업기간 및 예산 2027-2031 / 300만불"
        row = candidate("예시국", 2027, "123", t, content)
        self.assertFalse(row["selected"])
        self.assertEqual(row["_period"], "2027-2031")
        self.assertIn("300만불",row["name_ko"])
        self.assertIsNone(candidate("예시국", 2026, "123", t, content))
        self.assertIsNone(candidate("다른국", 2027, "123", t, content))
        self.assertEqual(candidate("예시국", 2027, "123", t, t+"\n접수기간 2025-2026")["_period"], "")

    def test_table_header_does_not_become_the_project_name(self):
        title = "쿠바 에너지 접근성 개선사업 예비조사 전문가 모집"
        body = title + "\n사업명 사업기간/규모 사업내용\n쿠바 에너지 접근성 개선사업 2026-2029/\n850 만불•전력공급"
        row = candidate("쿠바", 2027, "42", title, body)
        self.assertEqual(row["name_ko"], "쿠바 에너지 접근성 개선사업 (2026-2029/850 만불)")
        self.assertFalse(row["selected"])

    def test_board_filters_domains_and_distinguishes_failure_from_empty(self):
        link = BOARD + "123/artclView.do"
        parsed, _ = parse_board(f'<a href="{link}"><strong>예시국 공고</strong></a>'
                                f'<a href="{link.replace("www.koica.go.kr","example.org")}">기타</a>')
        self.assertEqual(parsed, {"123":"예시국 공고"})
        self.assertEqual(parse_board("총 0 개의 글이 등록되었습니다.")[0], {})
        with self.assertRaises(ValueError):
            parse_board("<p>공사 중</p>")

    def test_reannouncements_preserve_links_and_never_enter_existing_roster(self):
        t = "예시국 교사양성 사업(2027-2030/500만불) 예비조사 전문가 모집"
        def get(_,url,parse):
            return (({"32":t,"31":t},2),False) if "artclList" in url else (t,False)
        roster=[{"name_ko":"예시국 교사양성 사업(2027-2030/500만불)"}]
        with patch("official_notices.Bulletin.get",get):
            hits, info = discover("예시국",2027,roster)
        self.assertEqual(info["status"],"ok")
        self.assertEqual(len(hits),1)
        self.assertEqual(len(hits[0]["scope_sources"]),2)
        self.assertEqual(hits[0]["_similar_project"],roster[0]["name_ko"])
        self.assertFalse(hits[0]["selected"])
        self.assertEqual(len(roster),1)

    def test_external_title_remains_inert_json_on_export(self):
        rendered = editor_html({"projects":[{"name_ko":"</script><h1>내용</h1>"}]})
        self.assertNotIn("</script><h1>내용", rendered)
        self.assertIn(r"\u003c/script>", rendered)
