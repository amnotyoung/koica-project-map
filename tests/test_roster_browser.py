"""Opt-in browser regressions: KOICA_BROWSER_TESTS=1 python -m unittest discover -s tests."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill/scripts"))
from cdp import WS, _free_port, _wait_debugger
from export import find_chrome
from pick_projects import export_editor


@unittest.skipUnless(os.environ.get("KOICA_BROWSER_TESTS") == "1", "headless Chrome opt-in")
class RosterBrowserTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        port = _free_port()
        chrome = subprocess.Popen([find_chrome(), "--headless=new", "--no-sandbox",
                                   f"--user-data-dir={self.folder}/profile",
                                   f"--remote-debugging-port={port}", "about:blank"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(chrome.wait, 10)
        self.addCleanup(chrome.terminate)
        self.ws = WS(_wait_debugger(port))
        self.addCleanup(self.ws.close)
        self.ws.call("Page.enable")
        base = {"id":"original", "name_ko":"낙농사업('23-'28/1,000만불)", "_period":"2024-2028",
                "place":"아디스아바바", "selected":True, "_location_basis":"group-representative",
                "display_place_en":"Field office", "source_coord":{"lat":9, "lon":38.75, "source":"도시"}}
        candidate = {"id":"koica-board:1", "name_ko":"낙농 강화 공고", "_notice_candidate":True,
                     "_similar_project_id":"original", "scope_sources":["https://example.org/notice"]}
        geography = {"land":"", "cities":[], "years":{}, "regions":{"admin1":[],"admin2":[]},
                     "transform":[20, -500, 320, 40]}
        with patch("preview_geo.preview_geo", return_value=geography):
            page = export_editor(self.folder/"test.html", {"country":"에티오피아", "projects":[base],
                                                          "notice_candidates":[candidate]})
        self.ws.call("Page.navigate", {"url":page.as_uri()})
        for _ in range(80):
            if self.js("document.querySelector('article')!==null"):
                break
            time.sleep(.05)
        self.js("""document.querySelector('[data-filter=all]').click();
            var original=document.querySelector('article');
            var place=original.querySelector('[data-field=place]');
            var change=(el,value,event='input')=>{el.value=value;el.dispatchEvent(new Event(event,{bubbles:true}))};
            var mode=value=>change(document.getElementById('geo-mode'),value,'change');""")

    def js(self, code):
        result = self.ws.call("Runtime.evaluate", {"expression":code,"returnByValue":True,
                                                    "userGesture":True,"awaitPromise":True})
        self.assertNotIn("exceptionDetails", result)
        return result["result"].get("value")

    def download(self):
        target = Path(tempfile.mkdtemp(dir=self.folder))
        self.ws.call("Browser.setDownloadBehavior", {"behavior":"allow","downloadPath":str(target)})
        self.js("document.getElementById('save').click()")
        for _ in range(80):
            files = list(target.glob("*.json"))
            if files:
                return json.loads(files[0].read_text())
            time.sleep(.05)
        self.fail(self.js("document.getElementById('feedback').textContent"))

    def test_noop_mode_restore_and_explicit_keyboard_confirmation(self):
        self.js("""place.focus();change(place,'아디스아바바  ');mode('nationwide');mode('site')""")
        self.assertEqual(self.js("place.value"),"아디스아바바")
        self.assertTrue(self.js("$('geo-confirm').disabled"))
        row = self.download()["projects"][0]
        self.assertEqual(row["_period"],"2024-2028")
        self.assertEqual(row["source_coord"]["lon"],38.75)
        self.assertEqual(row["_location_basis"],"group-representative")
        self.assertEqual(row["display_place_en"],"Field office")
        self.js("change($('latitude'),'9.25');change($('longitude'),'38.9');$('coord-apply').click();$('save').click()")
        self.assertIn("확정", self.js("$('feedback').textContent"))
        self.js("mode('nationwide');mode('site');$('geo-confirm').click()")
        row = self.download()["projects"][0]
        self.assertEqual(row["reviewed_pins"][0]["lat"],9.25)
        self.assertEqual(row["display_place_en"],"Field office")
        self.js("$('geo-undo').click();change(place,'test');$('geo-cancel').click()")
        self.assertEqual(self.download()["projects"][0]["source_coord"]["lat"],9)

    def test_period_choice_and_duplicate_resolution(self):
        self.js("change(original.querySelector('[data-period]'),'title')")
        self.assertEqual(self.download()["projects"][0]["_period"],"2023-2028")
        self.js("document.querySelector('[data-duplicate=linked]').click()")
        doc = self.download()
        self.assertEqual(len(doc["projects"]),1)
        self.assertEqual(doc["projects"][0]["_linked_notices"][0]["id"],"koica-board:1")
        self.js("document.querySelector('[data-duplicate=separate]').click();document.querySelectorAll('[data-field=selected]')[1].click()")
        doc = self.download()
        self.assertEqual(len(doc["projects"]),2)
        self.assertNotIn("_linked_notices", doc["projects"][0])
