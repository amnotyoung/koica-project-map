import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"skill"/"scripts"))
from admin_areas import assign_regions
from layout import _bilateral
from common import design_tokens


class RegionTests(unittest.TestCase):
    def test_county_scope_differs_from_site_within_county(self):
        outer = [[0,0],[3,0],[3,3],[0,3],[0,0]]
        hole = [[1,1],[2,1],[2,2],[1,2],[1,1]]
        feature = {"properties":{"shapeName":"Alpha","shapeID":"adm-one"},
                   "geometry":{"type":"Polygon","coordinates":[outer,hole]}}
        records = [{"name_en":title,"_location_basis":"group-representative"} for title in
                   ("Strengthening healthcare in Alpha County", "Building a hospital in Alpha County")]
        rows = {"places":[{"parts":[]},{"parts":[]}]}
        assign_regions(records, rows, [feature])
        region, facility = rows["places"]
        self.assertEqual(region["region_id"], "adm-one")
        self.assertEqual(region["geometry"], [[outer,hole]])
        self.assertNotIn("region_id", facility)
        self.assertNotEqual(records[1].get("coverage"), "admin1")

    def test_reviewed_regions_are_all_or_nothing(self):
        features = [{"properties":{"shapeName":name + " Region", "shapeID":name},
                     "geometry":{"type":"Polygon", "coordinates":[
                         [[x,0],[x+1,0],[x+1,1],[x,1],[x,0]]]}}
                    for x,name in enumerate(("First", "Second"))]
        names = [["First","Second"], ["First","Missing"]]
        records = [{"coverage":"admin1", "admin1_names":n} for n in names]
        rows = {"places":[{"parts":[]}, {"parts":[{"kind":"point"}]}]}
        assign_regions(records, rows, features)
        ok, missing = rows["places"]
        self.assertEqual([r["region_id"] for r in ok["regions"]], names[0])
        self.assertEqual(len(ok["parts"]), 2)
        self.assertFalse(missing["resolved"])
        self.assertFalse(missing["parts"])

    def test_editor_picks_one_of_two_districts_with_same_name_by_id(self):
        shape = {"type":"Polygon","coordinates":[[[0,0],[2,0],[2,2],[0,2],[0,0]]]}
        features = [{"properties":{"shapeName":"Central","shapeID":sid},"geometry":shape}
                    for sid in ("district-one","district-two")]
        record = {"coverage":"admin2","admin2_names":["Central"],"admin2_ids":["district-two"]}
        rows = {"places":[{"parts":[]}]}
        assign_regions([record], rows, features, level="ADM2")
        self.assertEqual(rows["places"][0]["region_id"],"district-two")
        record["admin2_ids"] = ["retired-id"]
        rows = {"places":[{"parts":[{"kind":"point"}]}]}
        assign_regions([record], rows, features, level="ADM2")
        self.assertFalse(rows["places"][0]["resolved"])
        self.assertEqual(rows["places"][0]["parts"],[])

    def test_bilateral_groups_get_opposite_edges(self):
        spec = design_tokens()["layout"]["C"]
        groups = [{"h":.6,"place_w":.3,"nationwide":False,"points":[{"x":x,"y":3}]}
                  for x in (5,8)]
        placed = _bilateral(groups,spec,spec["map"],.1)
        self.assertEqual([g["side"] for g in placed],["left","right"])
        self.assertLess(placed[0]["x"]+2.23,spec["map"]["x"])
        self.assertGreater(placed[1]["x"],spec["map"]["x"]+spec["map"]["w"])
