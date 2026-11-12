from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill" / "scripts"))
import reference_pptx as ref
import layout
from common import design_tokens


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.source = self.folder / "human.pptx"
        self.manifest = self.folder / "slots.json"
        self.out = self.folder / "generated.pptx"
        p, a, r, rel, ct = (ref.NS[x] for x in ("p", "a", "r", "rel", "ct"))
        slide = f'''<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:spTree>
          <p:grpSp><p:sp><p:nvSpPr><p:cNvPr id="7" name="project"/></p:nvSpPr>
          <p:spPr><a:xfrm><a:off x="100" y="200"/><a:ext cx="300" cy="400"/></a:xfrm></p:spPr>
          <p:txBody><a:bodyPr/><a:p><a:pPr/>
          <a:r><a:rPr sz="770" spc="-64"/><a:t>Build 2</a:t></a:r>
          <a:r><a:rPr baseline="30000"/><a:t>nd</a:t></a:r>
          <a:r><a:rPr/><a:t> school</a:t></a:r></a:p>
          <a:p><a:r><a:rPr b="1"/><a:t>* original note</a:t></a:r></a:p>
          </p:txBody></p:sp></p:grpSp></p:spTree></p:cSld></p:sld>'''
        parts = {
            "[Content_Types].xml": f'<Types xmlns="{ct}"><Override PartName="/ppt/slides/slide1.xml" ContentType="slide"/><Override PartName="/ppt/slides/slide2.xml" ContentType="slide"/></Types>',
            "_rels/.rels": f'<Relationships xmlns="{rel}"><Relationship Id="root" Type="{r}/officeDocument" Target="ppt/presentation.xml"/><Relationship Id="thumb" Type="{r}/thumbnail" Target="docProps/thumbnail.jpeg"/></Relationships>',
            "ppt/presentation.xml": f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst><p:sldId id="256" r:id="s1"/><p:sldId id="257" r:id="s2"/></p:sldIdLst></p:presentation>',
            "ppt/_rels/presentation.xml.rels": f'<Relationships xmlns="{rel}"><Relationship Id="s1" Type="{r}/slide" Target="slides/slide1.xml"/><Relationship Id="s2" Type="{r}/slide" Target="slides/slide2.xml"/></Relationships>',
            "ppt/slides/slide1.xml": slide,
            "ppt/slides/slide2.xml": slide.replace("original note", "other slide"),
            "ppt/slides/_rels/slide1.xml.rels": f'<Relationships xmlns="{rel}"><Relationship Id="map" Type="{r}/image" Target="../media/map.png"/><Relationship Id="note" Type="{r}/notesSlide" Target="../notesSlides/notesSlide1.xml"/></Relationships>',
            "ppt/media/map.png": b"original cartographic artwork",
            "docProps/thumbnail.jpeg": b"stale preview",
            "ppt/notesSlides/notesSlide1.xml": "<note>private speaker notes</note>",
        }
        with ZipFile(self.source, "w") as package:
            for name, value in parts.items():
                package.writestr(name, value)
        self.doc = {"country": "Example", "projects": [
            {"id": "school", "place": "City", "badges": ["E"], "name_en": "Build 2nd school"}]}
        self.slides = [{"lang": "en", "part": "ppt/slides/slide1.xml", "bindings": [
            {"project_id": "school", "shape_id": 7, "paragraph": 0}]}]
        ref.calibrate(self.source, self.doc, self.slides, self.manifest)

    def test_changed_text_preserves_artwork_geometry_note_and_superscript(self):
        before = self.source.read_bytes()
        self.doc["projects"][0]["name_en"] = "Build 2nd schools"
        report = ref.build(self.doc, self.manifest, self.out)
        with ZipFile(self.out) as z:
            root = ref.parse(z.read("ppt/slides/slide1.xml"))
            p = ref.paragraph(root, self.slides[0]["bindings"][0])
            self.assertEqual(ref.paragraph_text(p), "Build 2nd schools")
            self.assertEqual(p.xpath('./a:r[a:rPr/@baseline="30000"]/a:t/text()', namespaces=ref.NS), ["nd"])
            self.assertEqual(root.xpath('.//a:p[2]/a:r/a:t/text()', namespaces=ref.NS), ["* original note"])
            self.assertEqual(root.find('.//a:off', ref.NS).get("x"), "100")
            self.assertEqual(z.read("ppt/media/map.png"), b"original cartographic artwork")
        self.assertTrue(report["bindings"][0]["changed"])
        self.assertEqual(self.source.read_bytes(), before)

    def test_unselected_slides_notes_and_stale_thumbnail_are_not_embedded(self):
        ref.build(self.doc, self.manifest, self.out)
        with ZipFile(self.out) as z:
            self.assertNotIn("ppt/slides/slide2.xml", z.namelist())
            self.assertNotIn("ppt/notesSlides/notesSlide1.xml", z.namelist())
            self.assertNotIn("docProps/thumbnail.jpeg", z.namelist())
            pres = ref.parse(z.read("ppt/presentation.xml"))
            self.assertEqual(len(pres.find("p:sldIdLst", ref.NS)), 1)
            self.assertNotIn(b"slide2.xml", z.read("[Content_Types].xml"))

    def test_changed_location_or_project_set_fails_before_overwriting_output(self):
        self.out.write_bytes(b"previous output")
        for change in ("place", "badges", "id"):
            doc = deepcopy(self.doc)
            doc["projects"][0][change] = ["H"] if change == "badges" else "different"
            with self.assertRaises(ValueError):
                ref.build(doc, self.manifest, self.out)
            self.assertEqual(self.out.read_bytes(), b"previous output")

    def test_wrong_source_language_and_long_text_fail(self):
        with self.assertRaisesRegex(ValueError, "언어"):
            ref.build(self.doc, self.manifest, self.out, ["ko"])
        self.doc["projects"][0]["name_en"] *= 10
        with self.assertRaisesRegex(ValueError, "긴 문구"):
            ref.build(self.doc, self.manifest, self.out)
        self.source.write_bytes(self.source.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "원본이 바뀌"):
            ref.build(self.doc, self.manifest, self.out)

    def test_duplicate_ids_and_slots_fail(self):
        doc = deepcopy(self.doc)
        doc["projects"].append(deepcopy(doc["projects"][0]))
        with self.assertRaisesRegex(ValueError, "고유"):
            ref.build(doc, self.manifest, self.out)
        manifest = json.loads(self.manifest.read_text())
        manifest["slides"][0]["bindings"] *= 2
        self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "정확히 한 번"):
            ref.build(self.doc, self.manifest, self.out)

    def test_manual_line_break_survives_text_correction(self):
        a = ref.NS["a"]
        p = ref.parse(f'<a:p xmlns:a="{a}"><a:r><a:rPr sz="770"/><a:t>Fiji (GCF</a:t></a:r><a:br/><a:r><a:rPr/><a:t>(2021-2027)</a:t></a:r></a:p>'.encode())
        ref.replace_text(p, "Fiji (GCF) (2021-2027)")
        self.assertEqual(ref.paragraph_text(p), "Fiji (GCF) (2021-2027)")
        self.assertEqual(len(p.findall("a:br", ref.NS)), 1)
        before_break = []
        for child in p:
            if child.tag.endswith("}br"):
                break
            before_break += child.xpath('./a:t/text()', namespaces=ref.NS)
        self.assertEqual("".join(before_break), "Fiji (GCF) ")


class LayoutRegressionTests(unittest.TestCase):
    def test_bottom_swap_refreshes_every_anchor_and_keeps_same_row(self):
        cards = [{"x": 4.43, "y": 6.46, "place_w": .5, "side": "bottom"},
                 {"x": 6.97, "y": 6.46, "place_w": .8, "side": "bottom"}]
        for c in cards:
            c["anchor"] = layout.anchor_of(c, c, c["side"])
        layout._swap_slots(*cards)
        layout._restack(cards, "bottom")
        for c in cards:
            self.assertEqual(c["anchor"], layout.anchor_of(c, c, "bottom"))
            self.assertEqual(c["y"], 6.46)

    def test_multiple_badges_leave_a_gap_before_first_line(self):
        tok = design_tokens()
        for count in (1, 2, 3):
            card = layout.build_card({"place": "City", "name_ko": "사업명", "badges": ["E"] * count}, tok, "ko", 1)
            b = tok["card"]["badge"]
            right = b["dx"] + count * b["w"] + (count - 1) * b["gap"]
            self.assertGreaterEqual(card["first_line_dx"] + 1e-9, right + b["gap"])


if __name__ == "__main__":
    unittest.main()
