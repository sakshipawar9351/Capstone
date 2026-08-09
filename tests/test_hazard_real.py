"""
Traversability on real south-polar terrain.

Runs the hazard engine over the LOLA 10 m polar DEM at sites whose character is
independently known, and checks that the verdicts match what the literature
says about them. A hazard map that called Shackleton's walls easy driving would
be worse than no hazard map at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from backend.analysis.hazard import HAZARD_CLASSES, analyse_traversability  # noqa: E402
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


img, lbl = DEM / "ldem_875s_10m_float.img", DEM / "ldem_875s_10m_float.lbl"
if not img.exists():
    print("polar DEM absent — run scripts/fetch_polar.py --download")
    raise SystemExit(0)

dem = open_polar(img, lbl)
print(f"\nLDEM_875S_10M — {dem.meta['map_scale_m']:.0f} m/px, "
      f"{dem.meta['min_lat']}° to {dem.meta['max_lat']}°\n")

# ---------------------------------------------------------------------------
# Sites of differing character. Shackleton is a 21 km crater with walls near
# the angle of repose; the surrounding plateau is comparatively benign.
SITES = [
    ("Shackleton interior", -89.68, 129.78, 300),
    ("Shackleton rim/wall", -89.85, 100.00, 300),
    ("Polar plateau", -88.60, 210.00, 300),
    ("Near de Gerlache", -88.50, 273.00, 300),
]

results = {}
print(f"{'SITE':<24}{'mean°':>7}{'p90°':>7}{'max°':>7}{'passable':>10}{'risk':>7}")
print("-" * 62)

for name, la, lo, half in SITES:
    win = dem.window_around(la, lo, half_px=half)
    tm = analyse_traversability(win.elevation, win.baseline_m, rover="viper")
    st = tm.stats()
    results[name] = (tm, st)
    print(f"{name:<24}{st['slope_deg']['mean']:>7.2f}"
          f"{st['slope_deg']['p90']:>7.2f}{st['slope_deg']['max']:>7.2f}"
          f"{st['passable_fraction'] * 100:>9.1f}%{st['risk']['mean']:>7.3f}")

print()
# ---------------------------------------------------------------------------
print("Physical plausibility\n")

for name, (tm, st) in results.items():
    check(f"{name:<24} slopes are physical",
          0 <= st["slope_deg"]["mean"] < 45 and st["slope_deg"]["max"] <= 90,
          f"max {st['slope_deg']['max']:.1f}°")

wall = results["Shackleton rim/wall"][1]
plateau = results["Polar plateau"][1]
check("crater wall is steeper than the plateau",
      wall["slope_deg"]["p90"] > plateau["slope_deg"]["p90"],
      f"{wall['slope_deg']['p90']:.1f}° vs {plateau['slope_deg']['p90']:.1f}°")
check("crater wall is less passable than the plateau",
      wall["passable_fraction"] <= plateau["passable_fraction"],
      f"{wall['passable_fraction']*100:.1f}% vs "
      f"{plateau['passable_fraction']*100:.1f}%")
check("crater wall carries higher risk",
      wall["risk"]["mean"] > plateau["risk"]["mean"],
      f"{wall['risk']['mean']:.3f} vs {plateau['risk']['mean']:.3f}")

# ---------------------------------------------------------------------------
print("\nRover sensitivity — the same ground, three vehicles\n")
win = dem.window_around(-89.85, 100.0, half_px=300)
print(f"  {'rover':<24}{'limit':>7}{'passable':>11}{'mean speed':>12}")
print("  " + "-" * 54)
frac = {}
for rv in ("pragyan", "viper", "lrv"):
    tm = analyse_traversability(win.elevation, win.baseline_m, rover=rv)
    st = tm.stats()
    frac[rv] = st["passable_fraction"]
    v = tm.speed_ms[tm.hazard < 4]
    print(f"  {tm.rover.name[:23]:<24}{tm.rover.max_slope_deg:>6.0f}°"
          f"{st['passable_fraction']*100:>10.1f}%"
          f"{float(v.mean()) if v.size else 0:>11.3f} m/s")

check("a higher tip-over limit yields more passable ground",
      frac["lrv"] >= frac["viper"],
      f"LRV {frac['lrv']*100:.1f}% vs VIPER {frac['viper']*100:.1f}%")

# ---------------------------------------------------------------------------
print("\nRisk aversion changes the cost surface, not the legality\n")
base = analyse_traversability(win.elevation, win.baseline_m,
                              rover="viper", risk_aversion=0.0)
timid = analyse_traversability(win.elevation, win.baseline_m,
                               rover="viper", risk_aversion=8.0)
ok = np.isfinite(base.cost_s) & np.isfinite(timid.cost_s)
ratio = float(timid.cost_s[ok].mean() / base.cost_s[ok].mean())
print(f"  gamma 0 mean cost {base.cost_s[ok].mean():>8.2f} s")
print(f"  gamma 8 mean cost {timid.cost_s[ok].mean():>8.2f} s   ({ratio:.2f}x)")
check("risk aversion raises cost", ratio > 1.2, f"{ratio:.2f}x")
check("risk aversion does not change what is passable",
      int((base.hazard == 4).sum()) == int((timid.hazard == 4).sum()),
      "impassable set identical")

# ---------------------------------------------------------------------------
print("\nWhy a polar product is required, not merely preferable\n")
from backend.core.raster import get_dem  # noqa: E402

# The cylindrical grid is not simply coarser at the pole — it is degenerate.
# East-west cell size scales with cos(lat), so it collapses toward zero as the
# meridians converge. Slope is rise over run, and a vanishing run inflates the
# gradient without bound. What it returns here is an artefact of the projection,
# not a measurement of the ground — which is the entire reason the LOLA team
# publishes separate polar stereographic products.
g = get_dem()
gwin = g.window(-89.9, -89.4, 100.0, 160.0)
dx = np.asarray(gwin.cell_sizes()[0], dtype=float)
gtm = analyse_traversability(np.asarray(gwin.elevation, dtype=np.float64),
                             float(dx.mean()), rover="viper")
gst = gtm.stats()
ptm, pst = results["Shackleton rim/wall"]

print(f"  {'grid':<24}{'E-W cell':>11}{'max slope':>11}   verdict")
print("  " + "-" * 60)
print(f"  {'LDEM_64 cylindrical':<24}{dx.mean():>10.1f}m"
      f"{gst['slope_deg']['max']:>10.1f}°   degenerate")
print(f"  {'LDEM_875S_10M polar':<24}{pst['baseline_m']:>10.1f}m"
      f"{pst['slope_deg']['max']:>10.1f}°   valid")

check("cylindrical cell size collapses near the pole",
      dx.mean() < 20.0,
      f"{dx.mean():.1f} m east-west here, against 474 m at the equator")
check("that collapse manufactures near-vertical slopes",
      gst["slope_deg"]["max"] > 85.0,
      f"{gst['slope_deg']['max']:.1f}° — an artefact, not terrain")
check("the polar grid returns physically plausible maxima",
      pst["slope_deg"]["max"] < 80.0,
      f"{pst['slope_deg']['max']:.1f}° on a crater wall")
check("the polar grid needs no scale warning", not ptm.warnings)

print(f"\n{npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
