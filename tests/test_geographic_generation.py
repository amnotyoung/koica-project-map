from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill" / "scripts"))
import cartography
import layout
import resolve_places
import basemap_tiles
import render_html
from common import design_tokens


def square(x, y, side):
    return [[x,y],[x+side,y],[x+side,y+side],[x,y+side],[x,y]]


class GeographicGenerationTests(unittest.TestCase):
    def test_island_framing_keeps_all_project_locations_and_adds_overview(self):
        base={"bbox":[0,0,21,21],"land":[square(0,0,10),square(20,20,.1)]}
        resolved={"places":[{"parts":[{"ok":True,"lon":4,"lat":5}]}]}
        bbox, overview=cartography.extent(base,resolved)
        self.assertTrue(overview)
        self.assertEqual(bbox,[0,0,10,10])
        resolved["places"][0]["parts"].append({"ok":True,"lon":20.05,"lat":20.05})
        bbox,_=cartography.extent(base,resolved)
        self.assertGreaterEqual(bbox[2],20.05)
        self.assertGreaterEqual(bbox[3],20.05)

    def test_overview_requires_legible_land_missing_from_the_main_map(self):
        main = [square(1,1,2), square(20,20,.2)]
        frame = {"x":0,"y":0,"w":4,"h":4}
        self.assertFalse(cartography.locator_adds_detail(main, frame, [square(0,0,1),square(2,2,.01)]))
        self.assertTrue(cartography.locator_adds_detail(main, frame, [square(0,0,1),square(2,2,.08)]))

    def test_labels_prioritize_project_sites_without_overlap_or_clipping(self):
        m={"frame":{"x":0,"y":0,"w":4,"h":3},"cities":[
            {"name":"Large City","x":2,"y":1.5,"pop":1000000},
            {"name":"Edge City With Long Name","x":3.95,"y":2.95,"pop":1000}],
           "admin1_labels":[]}
        markers=[{"name":"Project site","x":2,"y":1.5}]
        labels=cartography.place_labels(m,markers,[],design_tokens())
        self.assertEqual(labels[0]["name"],"Project site")
        for label in labels:
            b=label["box"]
            self.assertGreaterEqual(b[0],0)
            self.assertLessEqual(b[2],4)
            self.assertGreaterEqual(b[1],0)
            self.assertLessEqual(b[3],3)
        for i,a in enumerate(labels):
            for b in labels[i+1:]:
                self.assertFalse(cartography.overlap(a["box"],b["box"]))

    def test_atlas_has_white_land_and_keeps_rivers_visible(self):
        style=basemap_tiles.style_json(design_tokens()["map_style"])
        layers={l["id"]:l for l in style["layers"]}
        self.assertEqual(layers["bg"]["paint"]["background-color"],"#FFFFFF")
        self.assertNotIn("land-forest",layers)
        self.assertEqual(layers["river"]["paint"]["line-opacity"],1)

    def test_source_title_conflict_is_flagged_without_inventing_coordinates(self):
        entry={"name_en":"Recycling in Pokhara Metropolitan City", "_location_basis":"group-representative"}
        parts=[{"ok":True,"lon":85.43,"lat":27.67}]
        index=[("Pokhara","Pokhara","city",83.98,28.21,500000)]
        before=deepcopy(parts)
        self.assertEqual(resolve_places.title_location_conflicts(entry,parts,index),["Pokhara"])
        self.assertEqual(parts,before)
        entry["_location_basis"]="verified"
        self.assertEqual(resolve_places.title_location_conflicts(entry,parts,index),[])

    def test_low_zoom_tile_maps_keep_public_vector_rivers(self):
        m={"frame":{"x":0,"y":0,"w":4,"h":3},"tiles":{"png":"unused.png"},
           "projection":{"zoom":8},"land":[square(0,0,3)],"neighbors":[],
           "admin1":[],"admin2":[],"labels":[],"rivers":[[[.1,.1],[2,2]]]}
        with patch.object(render_html,"_data_uri",return_value="data:image/png;base64,eA=="):
            svg=render_html.draw_map({"map":m,"lang":"ko","markers":[]},design_tokens())
        self.assertIn('clip-path="url(#countryclip)"',svg)
        self.assertIn('M0.1000,0.1000 L2.0000,2.0000',svg)

    def test_accents_do_not_duplicate_project_city_labels(self):
        m={"frame":{"x":0,"y":0,"w":4,"h":3},"cities":[
            {"name":"Díli","x":2.02,"y":1.51,"pop":100000}],"admin1_labels":[]}
        labels=cartography.place_labels(m,[{"name":"Dili","x":2,"y":1.5}],[],design_tokens())
        self.assertEqual([l["name"] for l in labels],["Dili"])

    def test_aspect_and_measured_captions_control_the_map_and_column(self):
        tok = design_tokens()
        bbox = [0, 0, 12, 4]
        rec = {"place":"Area","name_ko":"짧은 사업","name_en":"Project"}
        area = {"region":"Area", "parts":[{"ok":True,"kind":"admin1","matched":"Area","lon":10,"lat":2}]}
        resolved = {"places":[area]}
        doc = {"map_bbox":bbox,"projects":[rec]}
        self.assertEqual(layout.choose_mode(doc,tok,"en",resolved), "L")
        wide = layout.single_column_spec("L",bbox,tok)["map"]
        tall = layout.single_column_spec("L",[0,0,4,12],tok)["map"]
        self.assertGreater(wide["w"], 2 * wide["h"])
        self.assertGreater(tall["h"], 1.5 * tall["w"])
        self.assertLess(wide["x"] + wide["w"], tok["region_tab"]["rail_x"])
        dense = {**doc,"projects":[{**rec,"name_ko":"사업 설명 " * 40}] * 8}
        self.assertEqual(layout.choose_mode(dense,tok,"ko",{"places":[area]*8}), "C")
        point = {"parts":[{**area["parts"][0], "kind":"point"}]}
        self.assertEqual(layout.choose_mode(doc,tok,"en",{"places":[point]}), "R")

    def test_pagination_retains_every_project_at_readable_size_without_templates(self):
        doc={"country":"Example","projects":[
            {"id":str(i),"place":"City","badges":["E"],
             "name_ko":f"교육시설 확충 및 직업훈련 역량강화 사업 {i} (2026-2031/1,000만불)"}
            for i in range(25)]}
        resolved={"iso3":"TST","places":[{"resolved":True,"query":"City","parts":[
            {"ok":True,"kind":"point","lon":5,"lat":5,"matched":"City"}]} for _ in doc["projects"]]}
        base={"iso3":"TST","name_ko":"Example","name_en":"Example","bbox":[0,0,10,10],
              "land":[square(0,0,10)],"neighbors":[],"admin1":[],"cities":[],"source":{}}
        framed={**doc,"map_bbox":base["bbox"]}
        with patch.object(layout,"prepare",return_value=(framed,resolved,base)), \
             patch.object(layout,"finish_background"):
            pages=layout.compute_pages(doc,["ko"])
        self.assertGreater(len(pages),1)
        self.assertEqual(sorted(int(c["project_id"]) for p in pages for c in p["cards"]),list(range(25)))
        for page in pages:
            self.assertEqual(page["renderer"],"geographic-data")
            self.assertTrue(page["fits"])
            self.assertEqual(page["text_hits"],0)
            self.assertEqual(page["font_scale"],1.0)


if __name__ == "__main__":
    unittest.main()
