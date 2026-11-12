"""Country-independent map framing and label placement from geographic data."""
from common import ring_area, norm
from text_metrics import measure


def extent(base, resolved, override=None):
    if override:
        return list(override), False
    full = base["bbox"]
    rings = sorted(base["land"], key=lambda r: abs(ring_area(r)), reverse=True)
    total = sum(abs(ring_area(r)) for r in rings)
    selected, area = [], 0
    for ring in rings:
        selected.extend(ring)
        area += abs(ring_area(ring))
        if area >= total * .94:
            break
    # Every mapped project remains in the main map, including offshore sites.
    selected.extend([p["lon"], p["lat"]] for record in resolved["places"]
                    for p in record["parts"] if p.get("ok") and p.get("lon") is not None)
    if not selected:
        return full, False
    focus = [min(p[0] for p in selected), min(p[1] for p in selected),
             max(p[0] for p in selected), max(p[1] for p in selected)]
    full_area = max((full[2]-full[0]) * (full[3]-full[1]), 1e-9)
    focus_area = (focus[2]-focus[0]) * (focus[3]-focus[1])
    use_focus = 0 < focus_area < full_area * .65
    return (focus if use_focus else full), use_focus


def overlap(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def place_labels(map_data, markers, leaders, tok):
    """Freeze label positions once so both renderers use identical decisions.

    Project places precede population-ranked cities. Administrative labels have
    a lower priority, and all text boxes must fit fully inside the map frame.
    """
    f = map_data["frame"]
    bounds = [f["x"]+.04, f["y"]+.04, f["x"]+f["w"]-.04, f["y"]+f["h"]-.04]
    blocked = [[m["x"]-.055,m["y"]-.055,m["x"]+.055,m["y"]+.055] for m in markers]
    if map_data.get("locator"):
        q=map_data["locator"]["frame"]
        blocked.append([q["x"]-.04,q["y"]-.04,q["x"]+q["w"]+.04,q["y"]+q["h"]+.04])
    labels, seen = [], []
    candidates = [{**m, "project": True, "name": m.get("name", "")} for m in markers]
    candidates += sorted(map_data.get("cities",[]),key=lambda c:-c.get("pop",0))
    for c in candidates:
        key = norm(c["name"])
        if not c["name"] or any(key == name and (c["x"]-x)**2+(c["y"]-y)**2 < .16**2
                                for name,x,y in seen):
            continue
        seen.append((key,c["x"],c["y"]))
        if len(labels) >= tok["map_style"].get("city_max",46) and not c.get("project"):
            continue
        size=6.0 if c.get("project") else 5.2
        w=measure(c["name"],size, bool(c.get("project")),0)
        h=size/72*1.15
        choices=[]
        for rank,(dx,dy) in enumerate(((.075,-h/2),(-w-.075,-h/2),(-w/2,-h-.09),(-w/2,.09))):
            x,y=c["x"]+dx,c["y"]+dy
            box=[x-.015,y-.01,x+w+.015,y+h+.01]
            if not (box[0]>=bounds[0] and box[1]>=bounds[1] and box[2]<=bounds[2] and box[3]<=bounds[3]):
                continue
            if any(overlap(box,b) for b in blocked):
                continue
            from layout import _seg_hits_box, _segments
            hits=sum(any(_seg_hits_box(p,q,box) for p,q in _segments(l)) for l in leaders)
            choices.append((hits,rank,x,y,box))
        if not choices:
            continue
        _,_,x,y,box=min(choices)
        labels.append({"name":c["name"],"x":x,"y":y+h*.78,"size":size,
                       "bold":bool(c.get("project")),"dot":[c["x"],c["y"]],
                       "box":box,"kind":"city"})
        blocked.append(box)
    for a in map_data.get("admin1_labels",[]):
        if a.get("area",0) < .12:
            continue
        size=6.0; w=measure(a["name"],size,False,.25);h=size/72
        for dx,dy in ((0,0),(0,-.15),(0,.15),(-.2,0),(.2,0)):
            x,y=a["x"]+dx,a["y"]+dy
            box=[x-w/2,y-h,x+w/2,y+.025]
            if not (box[0]>=bounds[0] and box[1]>=bounds[1] and box[2]<=bounds[2] and box[3]<=bounds[3]):
                continue
            if any(overlap(box,b) for b in blocked):
                continue
            labels.append({"name":a["name"],"x":x,"y":y,"size":size,
                           "box":box,"kind":"admin"})
            blocked.append(box)
            break
    return labels
