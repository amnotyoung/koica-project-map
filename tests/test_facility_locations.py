import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill/scripts"))
from facility_locations import named_facility
from location_evidence import enrich_locations


class FacilityLocations(unittest.TestCase):
    def test_only_a_named_delivery_facility_can_supply_coordinates(self):
        index = {"example university": {"12": ("Example University", 11.5, 32.1)}}
        title = "ICT education environment in Example University, Testland"
        hit = named_facility(title, [], index)
        self.assertEqual(hit["source_coord"]["lat"], 11.5)
        self.assertEqual(hit["scope_sources"], ["https://www.geonames.org/12"])
        self.assertFalse(named_facility("Rural nutrition", ["Meeting at Example University"], index))
        self.assertFalse(named_facility(title + " (west branch)", [], index))
        index["example university"]["13"] = ("Example University", 12.0, 32.1)
        self.assertFalse(named_facility(title, [], index))

    def test_a_reported_city_cannot_override_a_province_in_the_official_title(self):
        from common import norm
        city = {"id":1,"name":"Delta","ko":"델타","lat":2,"lon":3}
        row = {"id":"p","place":"델타","_location_basis":"group-representative","selected":True,
               "name_ko":"델타시 폐기물 관리","name_en":"Waste management in the Province of Delta"}
        enrich_locations({"projects":[row]}, {"p":["Delta"]}, {norm("델타"):{"1":city},"delta":{"1":city}}, {})
        self.assertNotIn("geonames_locality", row)
