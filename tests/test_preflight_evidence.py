import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "skill/scripts"))
from location_evidence import enrich_locations, title_region
from fetch_projects import apply_translation


class PreflightEvidenceTests(unittest.TestCase):
    def test_translation_needs_the_same_original_title(self):
        row = {"id":"x", "name_ko":"보건사업", "name_en":""}
        translations = {"x":{"source":"교육사업","en":"Education"}}
        apply_translation(row, translations)
        self.assertEqual(row["name_en"],"")
        translations["x"] = {"source":"보건사업","en":"Health"}
        apply_translation(row,translations)
        self.assertEqual(row["name_en"],"Health")

    def test_district_cannot_stand_in_for_a_province_with_the_same_name(self):
        regions={"lak":[("admin2","Lak","districts")]}
        self.assertIsNone(title_region("in Dak Lak Province",regions))
        self.assertIsNone(title_region("Buon Ho Town, Dak Lak Province",regions))
        self.assertEqual(title_region("in Lak District",regions),("admin2","Lak"))

    def test_reported_capital_does_not_pin_a_rural_project(self):
        city={"x":{"1":{"id":1,"ko":"엑스","name":"X","lat":1,"lon":2}}}
        row={"id":"a","selected":True,"place":"수도","_location_basis":"group-representative",
             "name_en":"Rural nutrition programme","name_ko":"농촌 영양사업"}
        enrich_locations({"projects":[row]},{"a":["Capital"]},city,{})
        self.assertNotIn("geonames_locality",row)
        self.assertEqual(row["_iati_reported_places"],["Capital"])


class ActivityScopeTests(unittest.TestCase):
    def test_multi_region_goal_requires_every_beneficiary_to_resolve(self):
        from project_geography import beneficiary_regions
        from location_evidence import boundary_key
        regs = {"alpha":[("adm1","Alpha","province")],"beta":[("adm1","Beta","province")]}
        src = ["Direct beneficiaries: Alpha - 3,000 people and Beta - 200 people"]
        self.assertEqual(beneficiary_regions(src,regs,boundary_key),[("adm1","Alpha"),("adm1","Beta")])
        self.assertFalse(beneficiary_regions(src,{"alpha":regs["alpha"]},boundary_key))
        self.assertFalse(beneficiary_regions([src[0]+", plus an unspecified district"],regs,boundary_key))

    def test_exact_region_from_both_sources_reaches_polygon_renderer(self):
        from location_evidence import enrich_locations
        row={"id":"p","selected":True,"name_en":"Crop development in Central Valley",
             "name_ko":"중부 계곡지역 농업개발","place":"Capital","_location_basis":"group-representative"}
        enrich_locations({"country":"example","source":"catalogue","projects":[row]}, {}, {},
                         {"central valley":[("adm1","Central Valley","regions")]},
                         descriptions={"p":["Irrigated farming in Central Valley"]})
        self.assertEqual(row["coverage"],"admin1")
        self.assertEqual(row["admin1_names"],["Central Valley"])

    def test_selected_municipalities_do_not_paint_the_whole_region(self):
        row = {"id":"p","selected":True,"name_en":"Maternal health in Delta Region",
               "name_ko":"델타 지역 모자보건","place":"Delta","_location_basis":"group-representative"}
        enrich_locations({"projects":[row]}, {}, {}, {"delta":[("adm1","Delta","region")]},
                         descriptions={"p":["Support for selected municipalities in Delta"]})
        self.assertEqual(row["coverage"],"unknown")
