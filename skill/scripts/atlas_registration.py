"""Register printed city labels against GeoNames on previously unseen atlas images."""
import csv
import io
import shutil
import subprocess
import unicodedata
from collections import defaultdict


def _key(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if c.isascii() and c.isalnum())


def city_index(path, iso2):
    locations = defaultdict(set)
    with path.open(encoding="utf-8") as f:
        for line in f:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 9 or fields[8] != iso2:
                continue
            lon,lat = float(fields[5]),float(fields[4])
            for label in (fields[1],fields[2],*fields[3].split(",")):
                key = _key(label)
                if len(key) >= 3:
                    locations[key].add((lon,lat))
    return {k:next(iter(v)) for k,v in locations.items() if len(v)==1}


def label_matches(tsv, size, names):
    matches = {}
    w,h = size
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        name = row.get("text") or ""
        point = names.get(_key(name))
        confidence = float(row["conf"])
        if point is None or confidence < 15:
            continue
        x,y,width,height = (int(row[k]) for k in ("left","top","width","height"))
        if point not in matches or confidence > matches[point][0]:
            matches[point] = (confidence,[name,*point,(x+width/2)/w,(y+height/2)/h])
    return [value[1] for value in matches.values()]


def fit(controls, size, *, printed_labels=True):
    """Fit an oriented affine transform and measure leave-one-city-out errors."""
    import numpy as np
    if len(controls) < (7 if printed_labels else 5):
        return None
    width,height=size
    coords=np.array([r[1:3] for r in controls],dtype=float)
    # Put longitudes on the same branch for countries crossing the dateline.
    radians=np.radians(coords[:,0])
    meridian=np.degrees(np.arctan2(np.sin(radians).mean(),np.cos(radians).mean()))
    coords[:,0] += 360*np.round((meridian-coords[:,0])/360)
    origin=coords.mean(axis=0)
    a=np.column_stack([np.ones(len(coords)),coords-origin])
    uv=np.array([r[3:5] for r in controls])
    scale=np.array([width,height])/max(size)
    keep=np.ones(len(uv),dtype=bool)
    if printed_labels:
        samples=np.random.default_rng(66).integers(len(a),size=(2200,3))
        samples=samples[np.abs(np.linalg.det(a[samples]))>1e-6]
        if not len(samples):
            return None
        models=np.linalg.solve(a[samples],uv[samples])
        models=models[(models[:,1,0]>0)&(models[:,2,1]<0)&
                      (abs(models[:,1,1])<models[:,1,0]*1.3)&(abs(models[:,2,0])<-models[:,2,1]*1.3)]
        if not len(models):
            return None
        errors=np.linalg.norm((a@models-uv)*scale,axis=2)
        counts=(errors<.021).sum(axis=1)
        best=np.lexsort((np.minimum(errors,.021).sum(axis=1),-counts))[0]
        keep=errors[best]<.021
        for _ in range(4):
            if keep.sum()<7:
                return None
            coef=np.linalg.lstsq(a[keep],uv[keep],rcond=None)[0]
            keep=np.linalg.norm((a@coef-uv)*scale,axis=1)<.021
    a,uv=a[keep],uv[keep]
    if len(a)<(7 if printed_labels else 5) or np.min(np.ptp(uv,axis=0))<.18:
        return None
    coef,_,rank,_=np.linalg.lstsq(a,uv,rcond=None)
    if rank!=3 or coef[1,0]<=0 or coef[2,1]>=0:
        return None
    errors=[]
    for i in range(len(a)):
        rest=np.arange(len(a))!=i
        local,_,rank,_=np.linalg.lstsq(a[rest],uv[rest],rcond=None)
        if rank!=3:
            return None
        errors.append(np.linalg.norm((a[i]@local-uv[i])*scale))
    if max(errors)>.035 or np.median(errors)>.016:
        return None
    return {"model":"affine","origin":origin.round(7).tolist(),"coefficients":coef.T.round(10).tolist(),
            "control_count":len(a),"validation_width":920,
            "validation_max_px":round(max(errors)*920*max(size)/width,1),
            "basis":"printed-labels" if printed_labels else "map-landmarks"}


def register(data, iso2, gazetteer):
    from PIL import Image
    if not shutil.which("tesseract"):
        return None
    if not gazetteer.is_file():
        from geo_prepare import load_cities
        load_cities(iso2, False)
    with Image.open(io.BytesIO(data)) as image:
        size=image.size
        scale=min(2,2400/max(size))
        resized=image.convert("RGBA")
        background=Image.new("RGB",size,"white")
        background.paste(resized,mask=resized.getchannel("A"))
        ocr=background.resize(tuple(round(v*scale) for v in size))
        stream=io.BytesIO()
        ocr.save(stream,format="PNG")
    proc=subprocess.run(["tesseract","stdin","stdout","--psm","11","-l","eng","tsv"],
                        input=stream.getvalue(),capture_output=True,timeout=60)
    if proc.returncode:
        return None
    controls=label_matches(proc.stdout.decode("utf-8"),ocr.size,city_index(gazetteer,iso2))
    result = fit(controls,size)
    return dict(result,width=size[0],height=size[1]) if result else None
