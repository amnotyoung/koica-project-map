import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill/scripts"))
import atlas_background as atlas


class AtlasBackgroundTests(unittest.TestCase):
    def test_local_plate_requires_matching_image_and_edition(self):
        data = b"verified image"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ref = root / "reference"
            registry = ref / "atlas_backgrounds"
            registry.mkdir(parents=True)
            deck = root / "book.pptx"
            with ZipFile(deck, "w") as z:
                z.writestr("ppt/media/map.jpg", data)
            plate = {"media":"ppt/media/map.jpg", "sha256":hashlib.sha256(data).hexdigest()}
            profile = {"deck":deck.name, "countries":{"AZE":plate}}
            file = registry / "2027.json"
            file.write_text(json.dumps(profile))
            with patch.object(atlas,"REFERENCE_DIR",ref), patch.object(atlas,"SKILL_DIR",root/"skill"):
                doc = {"country":"AZE","year":2027}
                self.assertEqual(Path(atlas.extract(doc, root)["path"]).read_bytes(), data)
                self.assertIsNone(atlas.extract({**doc,"map_bbox":[1,2,3,4]},root))
                self.assertIsNone(atlas.extract({**doc,"year":2028},root))
                plate["sha256"] = "changed"
                file.write_text(json.dumps(profile))
                self.assertIsNone(atlas.extract(doc,root))

    def test_registered_controls_align_and_off_plate_sites_fall_back(self):
        edition = atlas.read_json(atlas.REFERENCE_DIR/"atlas_backgrounds"/"2027.json")
        for plate in edition["countries"].values():
            frame = dict(x=.5,y=1,w=4,h=3)
            projection = atlas.PlateProjection(plate,frame)
            f = projection.frame
            self.assertAlmostEqual(f["w"]/f["h"], plate["width"]/plate["height"])
            for _,lon,lat,u,v in plate["controls"]:
                x,y = projection(lon,lat)
                self.assertAlmostEqual(x,f["x"]+u*f["w"],places=4)
                self.assertAlmostEqual(y,f["y"]+v*f["h"],places=4)
            self.assertFalse(atlas.covers_projects(plate,{"places":[{"parts":[{"ok":True,"lon":0,"lat":0}]}]}))

class DiscoveredPlateTests(unittest.TestCase):
    @staticmethod
    def write_atlas(path):
        from atlas_discovery import A, P, R
        ns = f'xmlns:p="{P[1:-1]}" xmlns:a="{A[1:-1]}" xmlns:r="{R[1:-1]}"'
        with ZipFile(path, "w") as z:
            z.writestr("ppt/presentation.xml", f'<p:presentation {ns}><p:sldIdLst><p:sldId r:id="r9"/><p:sldId r:id="r3"/></p:sldIdLst></p:presentation>')
            z.writestr("ppt/_rels/presentation.xml.rels", '<Relationships><Relationship Id="r9" Target="slides/slide9.xml"/><Relationship Id="r3" Target="slides/slide3.xml"/></Relationships>')
            for number,title in [(9,"네팔 Nepal"), (3,"Nepal")]:
                picture = '<p:pic><p:blipFill><a:blip r:embed="{}"/></p:blipFill><p:spPr><a:xfrm><a:ext cx="{}" cy="{}"/></a:xfrm></p:spPr></p:pic>'
                z.writestr(f"ppt/slides/slide{number}.xml", f'<p:sld {ns}><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{title}</a:t></a:r></a:p></p:txBody></p:sp>'
                           + picture.format("icon",200000,200000) + picture.format("bg",6000000,5000000) + '</p:spTree></p:cSld></p:sld>')
                z.writestr(f"ppt/slides/_rels/slide{number}.xml.rels", '<Relationships><Relationship Id="bg" Type="test/image" Target="../media/plate.png"/><Relationship Id="icon" Type="test/image" Target="../media/pin.png"/></Relationships>')
            z.writestr("ppt/media/plate.png", b"source image")
            z.writestr("ppt/media/pin.png", b"point icon")

    def test_future_book_discovers_map_by_title_and_uses_slide_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            deck=root/"2029 프로젝트 맵.pptx"
            self.write_atlas(deck)
            doc={"country":"NPL","year":2029}
            with patch.object(atlas,"SKILL_DIR",root/"skill"), patch.object(atlas,"REFERENCE_DIR",root), \
                 patch("atlas_registration.register",return_value={"width":500,"height":400}) as register:
                plate=atlas.extract(doc,root)
                self.assertEqual(plate["slides"],[1,2])
                self.assertEqual(plate["media"],"ppt/media/plate.png")
                self.assertEqual(Path(plate["path"]).suffix,".png")
                self.assertEqual(Path(plate["path"]).read_bytes(),b"source image")
                self.assertEqual(register.call_args.args[:2],(b"source image","NP"))
                self.assertIsNone(atlas.extract({**doc,"country":"Ghana"},root))
                register.return_value=None
                self.assertIsNone(atlas.extract(doc,root))

    def test_affine_dateline_and_limited_view(self):
        plate={"width":600,"height":300,"origin":[180,0],"coefficients":[[.5,.1,0],[.5,0,-.1]],"usable_box":[.2,.2,.8,.8]}
        def includes(lon):
            return atlas.covers_projects(plate,{"places":[{"parts":[{"ok":True,"lon":lon,"lat":0}]}]})
        self.assertTrue(includes(-179))
        self.assertFalse(includes(-176))

    def test_automatic_fit_accepts_distributed_towns_and_rejects_a_line(self):
        try:
            import numpy
        except ImportError:
            self.skipTest("numpy is optional for registering a new plate")
        from atlas_registration import fit
        pts=[[str(i),x,y,.1+x*.2,.8-y*.2] for i,(x,y) in enumerate((x,y) for x in range(4) for y in range(4))]
        result=fit(pts+[["outlier",8,7,.1,.8]],(800,600))
        self.assertEqual(result["control_count"],16)
        self.assertAlmostEqual(result["validation_max_px"],0)
        self.assertIsNone(fit([[str(x),x,x,x/12,x/12] for x in range(12)],(800,600)))
