"""
Heightmap tiles for the Cesium globe, from products this project can cite.

The Terrain globe drew the ion 3D Tileset, which sits +1,789 m above LOLA over
240 samples and reads +234 m at the Apollo 15 site where LOLA and the LROC NAC
stereo DTM agree on -1924 m to within a metre. This endpoint exists so the same
globe can be drawn from the DEMs every measurement here already comes from.

The property that makes it worth having is per-tile source selection: one
globe, three products, each region at the finest topography actually held for
it. These tests pin that behaviour, because a regression would be invisible —
the globe would still draw, just from coarser data, and nothing on screen would
say so.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

client = TestClient(app)
npass = nfail = 0


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


def tile(x, y, level, **kw):
    return client.get("/api/v1/terrain/tile",
                      params={"x": x, "y": y, "level": level, **kw})


def xy(lat, lon, level):
    cols, rows = 2 ** (level + 1), 2 ** level
    return int(((lon + 180.0) % 360.0) / 360.0 * cols), int((90.0 - lat) / 180.0 * rows)


print("\nThe whole sphere is covered, at every level\n")

r = tile(0, 0, 0)
check("the level-0 tile serves", r.status_code == 200,
      f"HTTP {r.status_code} · {r.headers.get('X-Source')}")
n = int(r.headers["X-Width"]) * int(r.headers["X-Height"])
check("the body is exactly the declared lattice, float32",
      len(r.content) == n * 4, f"{len(r.content)} bytes for {n} samples")
check("little-endian, as the browser reads it",
      abs(struct.unpack("<f", r.content[:4])[0]) < 20000,
      "a byte-order error would come back as 1e38 and spike the mesh")

vals = np.frombuffer(r.content, "<f4")
check("heights are lunar elevations about the 1737.4 km sphere",
      -10000 < vals.min() and vals.max() < 12000,
      f"{vals.min():.0f} .. {vals.max():.0f} m")
check("nothing is NaN — Cesium cannot render it",
      np.isfinite(vals).all(), "unmeasured ground reads as the sphere")

check("a tile outside the level's grid is refused, not wrapped",
      tile(99999, 0, 2).status_code == 422)


print("\nEach region gets the finest product actually held for it\n")

cases = [
    ("Apollo 15", 26.13222, 3.63386, 12, "NAC_DTM_APOLLO15_E261N0036", 2.0),
    ("south pole", -89.46, 222.0, 12, "LDEM_875S_10M", 10.0),
    ("Apollo 17", 20.19080, 30.77168, 12, "LDEM_64", 473.8),
]
for name, lat, lon, lvl, want, cell in cases:
    x, y = xy(lat, lon, lvl)
    rr = tile(x, y, lvl)
    got = rr.headers.get("X-Source", "")
    check(f"{name} is served by {want}",
          rr.status_code == 200 and got == want,
          f"{got} at {rr.headers.get('X-Cell-M')} m")

x, y = xy(26.13222, 3.63386, 12)
fine = np.frombuffer(tile(x, y, 12).content, "<f4")
check("the 2 m tile carries relief the coarse product cannot hold",
      fine.std() > 0.5,
      f"sigma {fine.std():.1f} m across the Apollo 15 tile")


print("\nIt agrees with the analysis pipeline, not merely with itself\n")

# The decisive check: the same ground, through a completely different code
# path. If these disagree, one of the two is lying about where the Moon is.
from backend.core.raster import get_dem  # noqa: E402

dem = get_dem("ldem_64")
x, y = xy(20.19080, 30.77168, 12)
r = tile(x, y, 12)
s_, n_, w_, e_ = (float(v) for v in r.headers["X-Bounds"].split(","))
g = np.frombuffer(r.content, "<f4").reshape(65, 65)
centre = float(g[32, 32])
ref = float(dem.elevation_at((s_ + n_) / 2, ((w_ + e_) / 2) % 360.0))
check("a tile's centre matches the DEM read directly",
      abs(centre - ref) < 60.0,
      f"tile {centre:.1f} m vs DEM {ref:.1f} m — within one 473.8 m cell")
check("and it is nowhere near the ion tileset's datum",
      abs(centre - ref) < 500,
      "the tileset was +1,789 m out; this is the same surface as the analysis")

print(f"\n{npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
