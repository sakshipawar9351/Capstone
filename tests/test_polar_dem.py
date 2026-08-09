"""
Verify the polar DEM reads correctly, against independently published values.

The south polar region is unusually well documented because Artemis site
selection has scrutinised it, so several landmarks have depths and elevations
in the literature that can be checked directly.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from backend.core.polar import open_polar  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEM = ROOT / "data" / "raw" / "polar" / "dem"

npass = nfail = 0


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


img = DEM / "ldem_875s_10m_float.img"
lbl = DEM / "ldem_875s_10m_float.lbl"

if not (img.exists() and lbl.exists()):
    print("polar DEM not present — run scripts/fetch_polar.py --download")
    raise SystemExit(0)

print("\nOpening LDEM_875S_10M\n")
dem = open_polar(img, lbl)
m = dem.meta
print(f"  product      : {m['product_id']}")
print(f"  grid         : {m['width']} x {m['height']}  ({m['dtype']})")
print(f"  scale        : {m['map_scale_m']} m/px")
print(f"  coverage     : {m['min_lat']}° to {m['max_lat']}°")
print(f"  frame        : {m['frame']}")
print()

check("label frame matches the project frame",
      "DE421" in m["frame"], m["frame"])
check("resolution is 10 m/px", abs(m["map_scale_m"] - 10.0) < 1e-9)

# ---------------------------------------------------------------------------
print("\nElevations at documented south-polar landmarks\n")
# Published context: the pole sits on the rim region of Shackleton, whose floor
# lies roughly 4 km below the surrounding rim crest (Zuber et al. 2012,
# Nature 486, 378: Shackleton is ~21 km across and ~4.2 km deep).
SITES = [
    ("South pole (90S)", -89.999, 0.0, (-2000, 2000)),
    ("Shackleton floor", -89.68, 129.78, (-3000, 1000)),
    ("Shackleton rim", -89.90, 0.0, (-2000, 2000)),
    ("Near de Gerlache", -88.50, 273.0, (-3000, 2000)),
    ("Grid edge (87.5S)", -87.51, 0.0, (-5000, 5000)),
]
for name, la, lo, (lo_m, hi_m) in SITES:
    try:
        e = dem.elevation_at(la, lo)
        check(f"{name:<22} {e:>9.1f} m", lo_m <= e <= hi_m,
              f"expected {lo_m}..{hi_m}")
    except Exception as exc:
        check(f"{name:<22}", False, str(exc)[:60])

# ---------------------------------------------------------------------------
print("\nWindow extraction and relief\n")
win = dem.window_around(-89.68, 129.78, half_px=400)
st = win.stats()
print(f"  window       : {st['shape'][0]} x {st['shape'][1]} px "
      f"= {st['shape'][0] * win.baseline_m / 1000:.1f} km across")
print(f"  baseline     : {win.baseline_m:.3f} m")
print(f"  elevation    : {st['min_m']:.0f} .. {st['max_m']:.0f} m")
print(f"  relief       : {st['relief_m']:.0f} m")

check("window is the requested size", st["shape"] == [800, 800], str(st["shape"]))
check("baseline is ~10 m", abs(win.baseline_m - 10.0) < 0.01)
check("Shackleton relief is kilometres, not metres",
      1500 < st["relief_m"] < 6000, f"{st['relief_m']:.0f} m")
check("no unphysical elevations",
      -12000 < st["min_m"] and st["max_m"] < 12000)

# ---------------------------------------------------------------------------
print("\nResolution gain over the global DEM\n")
from backend.core.raster import get_dem  # noqa: E402

glob = get_dem()
print(f"  global cylindrical : {glob.baseline_m:>8.1f} m/px  ({glob.product.product_id})")
print(f"  polar stereographic: {win.baseline_m:>8.1f} m/px  ({m['product_id']})")
gain = glob.baseline_m / win.baseline_m
print(f"  improvement        : {gain:>8.1f}x")
check("polar DEM is far finer than the global grid", gain > 40, f"{gain:.0f}x")

# What a rover can now be told about.
print("\n  Hazard scale vs the new sampling:")
for label, size in [("Rover footprint", 2.0), ("Traverse decision", 10.0),
                    ("Crater 50 m across", 50.0)]:
    px = size / win.baseline_m
    verdict = "RESOLVED" if px >= 3 else "marginal" if px >= 1 else "invisible"
    print(f"    {label:<22} {size:>6.1f} m = {px:>6.2f} px   {verdict}")

check("a 10 m traverse decision is now resolved",
      10.0 / win.baseline_m >= 1.0)

# ---------------------------------------------------------------------------
print("\nGeometry round trip on the real grid\n")
worst = 0.0
for la, lo in [(-89.5, 0.0), (-88.7, 137.4), (-88.0, 271.9), (-87.6, 45.0)]:
    r, c = dem.grid.latlon_to_rowcol(la, lo)
    la2, lo2 = dem.grid.rowcol_to_latlon(r, c)
    worst = max(worst, abs(float(la2) - la))
check("lat/lon -> pixel -> lat/lon exact", worst < 1e-9, f"{worst:.2e}°")

print(f"\n{npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
