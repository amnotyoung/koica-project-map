import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "skill/scripts"))
from country_names import atlas_countries, canonical, identity


class CountryNamesTests(unittest.TestCase):
    def test_roster_identities_and_separate_neighbours(self):
        countries = atlas_countries()
        self.assertEqual(len({c["iso3"] for c in countries}),len(countries))
        for c in countries:
            for name in [c["ko"],c["iso3"],c["iso2"],c["en"],*c["aliases"]]:
                self.assertEqual(identity(name),c)
        self.assertEqual(canonical("키르기즈공화국"),canonical("KGZ"))
        self.assertEqual(canonical("콩고민주공화국(DR콩고)"),canonical("COD"))
        self.assertNotEqual(canonical("도미니카"),canonical("DOM"))
        self.assertNotEqual(canonical("남수단"),canonical("SDN"))
