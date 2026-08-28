"""
The region's elevation as a 3D surface — geometry, not appearance.

A mesh endpoint is easy to test badly: assert 200, assert some bytes came back,
move on. That would pass while returning a surface with inverted triangles,
heights in the wrong units, or — worst and most plausible — a *different*
resampling of the DEM from the one the analysis ran on. That last failure is
invisible: the picture looks like terrain, it is just not the terrain anyone
computed a slope or a route across.

So the central test here reads the AOI window in-process, the same call the
hazard engine makes, and checks the mesh's heights against it cell by cell.
Everything else follows from that: if the vertices are the analysed elevations,
placed at the analysed cell size, then a distance measured on this surface is
the distance the planner costed.
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

from backend.config import dataset_path  # noqa: E402
from backend.core.aoi import plan_aoi  # noqa: E402
from backend.core.aoi_window import read_aoi  # noqa: E402
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
SITE = dict(south=-89.50, north=-89.46, west=220.0, east=224.0)


def mesh(**params):
    r = client.get("/api/v1/aoi/mesh", params={**SITE, **params})
    if r.status_code != 200:
        return r, None
    h = r.headers
    n = int(h["X-Vertices"])
    t = int(h["X-Triangles"])
    buf = r.content
    return r, {
        "positions": np.frombuffer(buf, np.float32, n * 3, 0).reshape(n, 3),
        "normals": np.frombuffer(buf, np.float32, n * 3, n * 12).reshape(n, 3),
        "indices": np.frombuffer(buf, np.uint32, t * 3, n * 24).reshape(t, 3),
        "rows": int(h["X-Rows"]), "cols": int(h["X-Cols"]),
        "cell": float(h["X-Cell-M"]), "stride": int(h["X-Stride"]),
        "mean": float(h["X-Mean-M"]), "h": h,
    }


# ---------------------------------------------------------------------------
print("\nThe body is exactly what the headers describe\n")

r, m = mesh()
check("the mesh is served", m is not None,
      f"HTTP {r.status_code}" if m is None else
      f"{m['rows']}x{m['cols']}, {len(m['indices']):,} triangles")
if m is None:
    print(f"\n{npass} passed, {nfail} failed")
    raise SystemExit(1)

n = m["rows"] * m["cols"]
t = (m["rows"] - 1) * (m["cols"] - 1) * 2
check("the byte count is positions + normals + indices, nothing else",
      len(r.content) == n * 12 + n * 12 + t * 12,
      f"{len(r.content):,} bytes for {n:,} vertices and {t:,} triangles")
check("the vertex count matches the declared grid",
      len(m["positions"]) == n and int(r.headers["X-Vertices"]) == n)
check("the triangle count is two per quad",
      len(m["indices"]) == t and int(r.headers["X-Triangles"]) == t)
check("little-endian float32, as the client assumes",
      struct.unpack("<f", r.content[:4])[0] == m["positions"][0, 0],
      "a byte-order mismatch would render as noise")


# ---------------------------------------------------------------------------
print("\nThe surface is the one the analysis ran on\n")

# The independent check: read the window the way the hazard engine does, and
# compare. Nothing in this block calls the endpoint's own code path.
aoi = plan_aoi(**SITE)
win = read_aoi(aoi)
z = win.elevation

check("the mesh is drawn at the AOI's own posting",
      abs(m["cell"] - win.cell_m) < 1e-6 and m["stride"] == 1,
      f"{m['cell']} m, stride {m['stride']}")
check("the mesh grid is the analysed grid",
      (m["rows"], m["cols"]) == z.shape, f"{z.shape} vs {(m['rows'], m['cols'])}")

valid = np.isfinite(z)
mean = float(z[valid].mean())
want = np.where(valid, z, mean) - mean
got = m["positions"][:, 2].reshape(m["rows"], m["cols"]).astype(np.float64)
err = float(np.abs(got - want).max())
check("every vertex height is the analysed elevation, less the region mean",
      err < 0.02,
      f"worst disagreement {err*1000:.2f} mm over {n:,} vertices")
check("the mean that was removed is reported so heights can be restored",
      abs(m["mean"] - mean) < 0.01, f"{m['mean']} m")

# x east, y north, in true local metres — this is what makes a distance
# measured on the mesh the distance the planner costed.
px = m["positions"][:, 0].reshape(m["rows"], m["cols"])
py = m["positions"][:, 1].reshape(m["rows"], m["cols"])
check("x spacing is exactly one cell, eastward",
      abs(float(px[0, 1] - px[0, 0]) - m["cell"]) < 1e-3,
      f"{float(px[0, 1] - px[0, 0]):.4f} m")
check("y spacing is exactly one cell, and rows run south",
      abs(float(py[0, 0] - py[1, 0]) - m["cell"]) < 1e-3,
      f"row 0 is {float(py[0, 0] - py[1, 0]):.4f} m north of row 1")
check("the grid is centred on the region",
      abs(float(px.mean())) < 1e-3 and abs(float(py.mean())) < 1e-3,
      "so the camera orbits the region, not its corner")


# ---------------------------------------------------------------------------
print("\nThe triangles are wound and shaded correctly\n")

idx = m["indices"]
check("no index points past the end of the vertex array",
      int(idx.max()) < n, f"max index {int(idx.max()):,} of {n:,}")
check("every triangle has three distinct vertices",
      bool((idx[:, 0] != idx[:, 1]).all() and (idx[:, 1] != idx[:, 2]).all()
           and (idx[:, 0] != idx[:, 2]).all()))

# Winding: with x east, y north and z up, a triangle seen from above must have
# a cross product pointing up. Backwards winding renders the terrain inside-out
# and every face vanishes under back-face culling.
p = m["positions"].astype(np.float64)
a, b, c = p[idx[:, 0]], p[idx[:, 1]], p[idx[:, 2]]
cz = np.cross(b - a, c - a)[:, 2]
check("every triangle is wound counter-clockwise seen from above",
      bool((cz > 0).all()), f"{int((cz <= 0).sum())} of {len(idx):,} inverted")

nn = np.linalg.norm(m["normals"].astype(np.float64), axis=1)
check("normals are unit length", float(np.abs(nn - 1).max()) < 1e-3,
      f"worst {float(np.abs(nn-1).max()):.2e} off unit")
check("normals point upward, not into the ground",
      bool((m["normals"][:, 2] > 0).all()),
      "a downward normal would shade that face black")

# The normals must agree with the slope map, or the render and the analysis
# disagree about how steep the same ground is.
slope_from_normal = np.degrees(np.arccos(np.clip(
    m["normals"][:, 2].astype(np.float64), -1, 1)))
from backend.analysis.terrain import slope_aspect  # noqa: E402
sl, _ = slope_aspect(z, win.cell_m, win.cell_m)
d = np.abs(slope_from_normal.reshape(m["rows"], m["cols"]) - sl)
interior = d[2:-2, 2:-2]
check("mesh shading agrees with the slope map it sits beside",
      float(np.nanmedian(interior)) < 1.0,
      f"median disagreement {float(np.nanmedian(interior)):.3f} deg "
      f"over the interior")


# ---------------------------------------------------------------------------
print("\nA large region is decimated, and says so\n")

r2, big = mesh(max_verts=4096)
check("the vertex budget is honoured", big and len(big["positions"]) <= 4096,
      f"{len(big['positions']):,} vertices at stride {big['stride']}")
check("the decimation is reported, not hidden",
      big["stride"] > 1 and float(r2.headers["X-Cell-M"]) > win.cell_m,
      f"drawn at {r2.headers['X-Cell-M']} m from "
      f"{r2.headers['X-Native-Cell-M']} m data")
check("the native posting is still reported so the page can say both",
      abs(float(r2.headers["X-Native-Cell-M"]) - win.cell_m) < 1e-6)

# Striding, not averaging: an averaged mesh smooths away the scarps this view
# exists to show, so the decimated surface must keep the extremes.
zb = big["positions"][:, 2]
check("decimation samples rather than averages, so relief survives",
      float(zb.max() - zb.min()) > 0.75 * float(want.max() - want.min()),
      f"{float(zb.max()-zb.min()):.0f} m of {float(want.max()-want.min()):.0f} m kept")


# ---------------------------------------------------------------------------
print("\nRefusals are specific\n")

r3 = client.get("/api/v1/aoi/mesh",
                params={"south": 10, "north": 10.00001, "west": 20,
                        "east": 20.00001})
check("a region too small to make a surface from is refused, not empty",
      r3.status_code == 422, f"HTTP {r3.status_code} {str(r3.json())[:60]}")

check("the source that supplied the bytes travels with the mesh",
      r.headers.get("X-Source") == "LDEM_875S_10M", r.headers.get("X-Source"))
check("so does the fraction of cells that were actually measured",
      0 < float(r.headers["X-Valid-Fraction"]) <= 1.0,
      f"{float(r.headers['X-Valid-Fraction'])*100:.2f}% measured")


print(f"\n{npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
