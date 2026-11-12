import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill" / "scripts"))
from project_scope import prepare_projects


class CoverageTests(unittest.TestCase):
    def test_national_and_unconfirmed_scope_remove_city_coordinate(self):
        record = {"place":"수도", "source_coord":{"lon":10,"lat":10},
                  "_location_basis":"group-representative","_coord_source":"도시"}
        rows = prepare_projects({"country":"예시국","projects":[
            {**record,"name_ko":"예시국 전국 청소년 지원"}, {**record,"name_ko":"농업 지원"}]})["projects"]
        self.assertEqual([r["coverage"] for r in rows], ["nationwide","unknown"])
        self.assertTrue(all("source_coord" not in r for r in rows))

    def test_one_activity_retains_separate_site_coordinates(self):
        rows=[{"id":"iati:activity@"+p,"place":p,"source_coord":{"lon":x,"lat":1},"name_ko":"사업"}
              for p,x in [("A",2),("B",3)]]
        projects=prepare_projects({"country":"예시국","projects":rows})["projects"]
        self.assertEqual(len(projects),1)
        self.assertEqual([p["source_coord"]["lon"] for p in projects[0]["sites"]],[2,3])
        self.assertEqual(projects[0]["source_ids"],["iati:activity@A","iati:activity@B"])

    def test_verified_extent_without_names_does_not_plot_source_groups(self):
        rows = [{"id":"iati:x@"+p, "place":p, "name_ko":"Youth", "coverage":"unknown",
                 "scope_label":"6개 주 56개 군", "source_coord":{"lon":1,"lat":2}}
                for p in ["A", "B"]]
        projects = prepare_projects({"country":"X","projects":rows})["projects"]
        self.assertEqual(len(projects),1)
        self.assertEqual(projects[0]["place"],"6개 주 56개 군")
        self.assertNotIn("sites",projects[0])
        self.assertNotIn("source_coord",projects[0])
