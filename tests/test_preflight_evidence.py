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
