from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill/scripts"))
from admin_areas import assign_regions
from cartography import clustered_extent
from project_scope import describe_map_scope, prepare_projects
from render_html import draw_project_areas


def point(x):
    return {"name":f"Place {x}","lon":x,"lat":3,"ok":True}


class EvidenceDisplayTests(unittest.TestCase):
    def test_partial_area_counts_drawn_boundaries_not_unresolved_names(self):
        shape = [[1,1],[3,1],[3,3],[1,3],[1,1]]
        features = [{"properties":{"shapeName":"Alpha District","shapeID":"alpha"},
                     "geometry":{"type":"Polygon","coordinates":[shape]}}]
        r = {"coverage":"admin2","admin2_names":["Missing","Alpha District","Alpha"],"map_scope":{"total":5},
             "scope_sources":["survey"]}
        row = {"parts":[]}; places={"places":[row]}
        assign_regions([r],places,features,level="ADM2")
        describe_map_scope(r,row)
        self.assertEqual(r["_map_caption"]["en"],"1 of 5 locations mapped")
        self.assertTrue(row["partial_coverage"])
        self.assertIsNone(clustered_extent([0,0,9,9],places))
        # A complete regional list must still match every supplied name.
        row = {"parts":[]}
        assign_regions([{**r,"map_scope":{}}],{"places":[row]},features,level="ADM2")
        self.assertFalse(row["resolved"])

    def test_two_endpoints_required_even_if_title_says_corridor(self):
        for pts,missing,conflict,expected in [
            ([], [], [], False), ([point(1)], [], [], False),
            ([point(1),point(1)], [], [], False), ([point(1),point(4)], ["unknown"], [], False),
            ([point(1),point(4)], [], ["uncertain location"], False),
            ([point(1),point(4)], [], [], True)
        ]:
            r = {"name_en":"Transport corridor","map_scope":{"corridor":True},"coverage":"site",
                 "reviewed_pins":pts,"scope_sources":["project plan"]}
            row = {"parts":pts,"resolved":not missing,"source_conflicts":conflict}
            describe_map_scope(r,row)
            self.assertEqual(row["corridor"],expected)
        row = {"parts":[point(1),point(4)],"resolved":True}
        describe_map_scope({"name_en":"Dry Corridor","coverage":"site"},row)
        self.assertNotIn("corridor",row)

    def test_context_outline_is_not_full_regional_coverage(self):
        a={"polygons":[[[[0,0],[2,0],[1,3],[0,0]]]],"name":"Test Province"}
        self.assertIn('fill="none"',draw_project_areas([{**a,"context_only":True}])[0])
        self.assertIn('fill="#C8343A"',draw_project_areas([a])[0])
        r={"coverage":"admin1","map_scope":{"facilities":{"ko":"참여 진료소","en":"participating clinics"}},
           "scope_sources":["study"]}
        row={"parts":[],"regions":[{"region_id":"alpha"}]}
        describe_map_scope(r,row)
        self.assertTrue(row["facility_context"])
        self.assertIn("clinics",r["_map_caption"]["en"])
        with self.assertRaises(ValueError):
            describe_map_scope({**r,"scope_sources":[]},row)

    def test_grouped_verified_sites_keep_distinct_locations(self):
        rows=[{"coverage":"site","map_scope":{"total":5},"name_ko":"사업","place":str(i),"scope_sources":["record"],
               "reviewed_pins":[point(i)],"id":"iati:test@"+str(i)} for i in [1,2]]
        r,=prepare_projects({"country":"시험국","projects":rows})["projects"]
        describe_map_scope(r,{"parts":r["reviewed_pins"],"resolved":True})
        self.assertEqual(r["_map_caption"]["ko"],"전체 5곳 중 2곳 표시")
