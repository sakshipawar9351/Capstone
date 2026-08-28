"""
Derived rasters as images — FR-1.13 and FR-1.14.

Checking that a PNG comes back would be nearly worthless: the endpoint would
pass that test while returning a uniform grey square. What matters is whether
the picture is *of* something, and whether a reader can recover the number
behind a colour.

So these tests decode the images and interrogate the pixels. The properties
asserted are the ones a wrong implementation would violate:

* the image has the shape the AOI declared — not the source's native grid, and
  not a thumbnail;
* it carries real structure rather than one flat colour;
* the hazard map uses exactly the palette in ``config``, so the map, the legend
  and the planner cannot disagree about what "marginal" means;
* the ramps are keyed to the rover's limits, so the same ground rendered for a
  more capable vehicle looks *safer* rather than merely different;
* every response states the range it was scaled over, in a named unit.

The last one is the difference between a measurement and a decoration. A slope
map with no numbers beside it cannot be read at all.
"""
from __future__ import annotations

import io
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from backend.analysis.hazard import HAZARD_CLASSES  # noqa: E402
from backend.api.routes_layers import LAYERS  # noqa: E402
from backend.config import dataset_path  # noqa: E402
from backend.main import app  # noqa: E402

npass = nfail = 0


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


if dataset_path("polar", "dem", "ldem_875s_10m_float.img") is None:
    print("polar DEM not present — skipping")
    raise SystemExit(0)

client = TestClient(app)
#: Small enough to render eight times quickly, large enough to contain real
#: crater structure — this is the same south-polar box the planning tests use.
SITE = dict(south=-89.50, north=-89.46, west=220.0, east=224.0)


def fetch(layer, **extra):
    r = client.get("/api/v1/aoi/layer", params={**SITE, "layer": layer, **extra})
    if r.status_code != 200:
        return r, None
    return r, np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"))


# ---------------------------------------------------------------------------
print("\nEvery derived quantity is renderable\n")

shapes = set()
for layer in LAYERS:
    r, img = fetch(layer)
    if img is None:
        check(f"{layer} renders", False, f"HTTP {r.status_code} {r.text[:70]}")
        continue
    shapes.add(img.shape[:2])
    colours = len(np.unique(img.reshape(-1, 3), axis=0))
    # Hazard is categorical — five classes is its whole vocabulary, so it can
    # never show as many colours as a continuous ramp and must not be judged
    # against one. What it shares with the others is that a uniform square
    # would mean the layer is not showing the terrain.
    floor = 2 if layer == "hazard" else 8
    check(f"{layer:<10} renders with real structure", colours > floor,
          f"{img.shape[1]}x{img.shape[0]}, {colours} distinct colours, "
          f"{r.headers['X-Range-Low']}..{r.headers['X-Range-High']} "
          f"{r.headers['X-Unit']}")

check("every layer covers the same ground at the same posting",
      len(shapes) == 1, f"shapes seen: {sorted(shapes)}")

prev = client.get("/api/v1/aoi/preview", params=SITE).json()
declared = tuple(prev["aoi"]["shape"])
check("the image is the analysed grid, not a resized picture of it",
      shapes and next(iter(shapes)) == declared,
      f"AOI declared {declared}, image is {next(iter(shapes)) if shapes else '—'}")


# ---------------------------------------------------------------------------
print("\nA colour can be turned back into a number\n")

r, _ = fetch("slope")
h = r.headers
check("the response states the range it was scaled over",
      "X-Range-Low" in h and "X-Range-High" in h and float(h["X-Range-High"]) > 0,
      f"{h['X-Range-Low']} .. {h['X-Range-High']}")
check("and the unit that range is in", h.get("X-Unit") == "deg", h.get("X-Unit"))
check("the posting is reported with the picture", float(h["X-Cell-M"]) == 10.0,
      f"{h['X-Cell-M']} m")
check("so is the product the bytes came from",
      h.get("X-Source") == "LDEM_875S_10M", h.get("X-Source"))
check("and the bounds it actually covered", h.get("X-Bounds", "").count(",") == 3,
      h.get("X-Bounds"))

units = {}
for layer in LAYERS:
    rr, _ = fetch(layer)
    units[layer] = rr.headers.get("X-Unit")
check("every layer names its unit rather than leaving it implied",
      all(units.values()), str(units))


# ---------------------------------------------------------------------------
print("\nThe published key matches the picture it captions\n")

# This is the check that catches a legend drifting from its map. The page prints
# the ramp each layer publishes underneath that layer's image; if the ramp is
# not the one the renderer used, the caption is a confident lie. It happened:
# elevation and hillshade were captioned with the green-amber-red risk ramp,
# which appears nowhere in either of them.
cat = {x["key"]: x for x in client.get("/api/v1/aoi/layers").json()["layers"]}
check("every layer is either given a ramp or declared categorical",
      all(("ramp" in v) and (v["categorical"] == (v["ramp"] is None))
          for v in cat.values()),
      f"categorical: {[k for k, v in cat.items() if v['categorical']]}")


def ramp_points(hexes, n=256):
    """The published ramp as a dense polyline in RGB."""
    stops = np.array([[int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
                      for h in hexes], dtype=np.float64)
    pos = np.linspace(0, len(stops) - 1, n)
    lo = np.floor(pos).astype(int)
    hi = np.minimum(lo + 1, len(stops) - 1)
    f = (pos - lo)[:, None]
    return stops[lo] * (1 - f) + stops[hi] * f


IMPASSABLE = tuple(int(HAZARD_CLASSES[-1].colour.lstrip("#")[i:i + 2], 16)
                   for i in (0, 2, 4))
#: The two colours that are deliberately off-ramp: unmeasured ground, and
#: impassable cells drawn in the hazard palette rather than at a ramp's end.
_OFF_RAMP = {(20, 22, 26), IMPASSABLE}

for layer, spec in cat.items():
    if spec["categorical"]:
        continue
    _, img = fetch(layer)
    line = ramp_points(spec["ramp"])
    px = np.unique(img.reshape(-1, 3), axis=0).astype(np.float64)
    keep = np.array([tuple(int(v) for v in p) not in _OFF_RAMP for p in px])
    d = np.abs(px[keep][:, None, :] - line[None, :, :]).sum(axis=2).min(axis=1)
    check(f"{layer:<10} contains only colours from the ramp it publishes",
          float(d.max()) <= 6,
          f"worst colour is {d.max():.0f}/765 off the published ramp")

check("elevation is not captioned with the risk ramp",
      cat["elevation"]["ramp"][0] != cat["risk"]["ramp"][0],
      f"relief starts {cat['elevation']['ramp'][0]}, "
      f"risk starts {cat['risk']['ramp'][0]}")


# ---------------------------------------------------------------------------
print("\nHazard uses the one palette the whole system agrees on\n")

_, haz = fetch("hazard")
palette = {tuple(int(c.colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)): c.key
           for c in HAZARD_CLASSES}
seen = {tuple(px) for px in np.unique(haz.reshape(-1, 3), axis=0)}
stray = seen - set(palette)
check("no colour appears that is not a declared hazard class",
      not stray, f"stray: {sorted(stray)}" if stray else
      ", ".join(sorted(palette[s] for s in seen)))

counts = Counter(map(tuple, haz.reshape(-1, 3)))
named = {palette[c]: n for c, n in counts.items()}
print("   ", ", ".join(f"{k} {v / haz[:, :, 0].size * 100:.1f}%"
                       for k, v in sorted(named.items(), key=lambda kv: -kv[1])))
check("more than one class is present on real polar terrain", len(named) > 1,
      "a single-class map would mean the thresholds are not biting")


# ---------------------------------------------------------------------------
print("\nRamps are keyed to the rover, not to the data\n")

# The whole point of scaling to the vehicle's own limits: the same ground shown
# for a more capable rover must read as safer. Scaled to the data range instead,
# both images would be identical and the colour would mean nothing.
_, viper = fetch("slope", rover="viper")
r_lrv, lrv = fetch("slope", rover="lrv")

green = np.array([53, 196, 138], dtype=np.int16)


def greenness(img):
    """How far the image sits toward the safe end of the ramp."""
    return float(-np.abs(img.astype(np.int16) - green).sum(axis=2).mean())


check("a rover with a higher slope limit sees the same ground as safer",
      greenness(lrv) > greenness(viper),
      f"LRV {greenness(lrv):.0f} vs VIPER {greenness(viper):.0f} "
      f"(scaled to {r_lrv.headers['X-Range-High']} deg vs "
      f"{r.headers['X-Range-High']} deg)")

# Regolith strength changes slip, and slip changes hazard. If the two soils
# produced identical pictures, the terramechanics would not be reaching the map.
_, nom = fetch("slip", soil="nominal")
_, weak = fetch("slip", soil="weak")
check("weak regolith produces a different slip map from nominal",
      not np.array_equal(nom, weak),
      f"{int((nom != weak).any(axis=2).sum()):,} cells differ")


# ---------------------------------------------------------------------------
print("\nUnknown ground is not drawn as data\n")

# Impassable is a different kind of answer from "very expensive", so it must not
# be the top of a continuous ramp — it gets the hazard palette's own colour.
_, cost = fetch("cost")
n_imp = int((cost == np.array(IMPASSABLE)).all(axis=2).sum())
check("impassable cells are shown in the hazard palette, not as expensive ones",
      n_imp > 0, f"{n_imp:,} cells")

check("the catalogue describes every layer the endpoint serves",
      {x["key"] for x in client.get("/api/v1/aoi/layers").json()["layers"]}
      == set(LAYERS))
check("an unknown layer is refused with the list of real ones",
      client.get("/api/v1/aoi/layer",
                 params={**SITE, "layer": "vibes"}).status_code == 422)
check("an unknown rover is refused",
      client.get("/api/v1/aoi/layer",
                 params={**SITE, "rover": "batmobile"}).status_code == 422)


print(f"\n{npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
