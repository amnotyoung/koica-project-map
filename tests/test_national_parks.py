import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill" / "scripts"))
from national_parks import add_to_layout, label_anchor, project_features


class NationalParkTests(unittest.TestCase):
    def test_multipolygon_holes_and_designation_filter(self):
        outer = [[0,0],[4,0],[4,4],[0,4],[0,0]]
        hole = [[1,1],[3,1],[3,3],[1,3],[1,1]]
        island = [[5,0],[6,0],[6,1],[5,1],[5,0]]
        def feature(designation, status):
            return {"properties":{"desig_eng":designation,"status":status,"site_pid":"id","name":"Park"},
                    "geometry":{"type":"MultiPolygon","coordinates":[[outer,hole],[island]]}}
        projection = Mock(view={"center":[0,0]})
        projection.rings.side_effect = lambda rings: rings
        parks = project_features([feature("National Park","Designated"),feature("Forest Reserve","Designated"),
                                  feature("National Park","Proposed")], projection)
        self.assertEqual([p["polygons"] for p in parks], [[[outer,hole],[island]]])
        span,x,y = label_anchor(parks[0]["polygons"][0])
        self.assertGreater(span,0)
        self.assertFalse(1 < x < 3 and 1 < y < 3)

    def test_failure_is_distinct_from_verified_empty(self):
        result = {"map":{"frame":{"x":0,"y":0,"w":3,"h":3},"labels":[]},
                  "country":{"iso3":"KEN"},"source":{},"warnings":[],"markers":[]}
        with patch("national_parks.load",side_effect=OSError("offline")):
            add_to_layout(result,None)
        self.assertTrue(result["warnings"])
        self.assertNotIn("national_parks",result["map"])
        with patch("national_parks.load",return_value={"features":[],"source":"test","retrieved":"2026-11-12"}):
            add_to_layout(result,None)
        self.assertEqual(result["map"]["national_parks"],[])
