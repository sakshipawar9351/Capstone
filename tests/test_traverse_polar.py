"""
End-to-end traverse planning on real south-polar terrain.

Everything upstream of this file has been verified against synthetic surfaces
with known answers. This runs the whole chain — polar stereographic DEM, slope,
detrended roughness, terramechanical slip, hazard classification, cost surface,
seven planners, route metrics — over ground that actually exists, and checks
that the results are physically sensible rather than merely self-consistent.

The site
--------
Connecting Ridge, near 89.45 S / 222 E: the high ground linking Shackleton's rim
to the de Gerlache direction. It is one of NASA's designated Artemis III
candidate landing regions, chosen for near-continuous illumination and adjacency
to permanently shadowed terrain. It is used here because it is a real traverse
problem rather than a convenient one — mostly drivable, with enough hazard that
a planner has to work.

What this file is for
---------------------
Three questions that only real terrain can answer:

1. Do the seven planners agree on cost where theory says they must, and differ
   where theory says they may?
2. Does the soil model change the route, or only the reported numbers?
3. Does the resolution of the DEM change the verdict?

Reference
---------
LOLA LDEM_875S_10M, 10 m/px polar stereographic, IAU Mean Earth / DE421.
"""
from __future__ import annotations

import dataclasses
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from backend.analysis.hazard import HAZARD_CLASSES, analyse_traversability  # noqa: E402
from backend.config import ROVER_PROFILES  # noqa: E402
from backend.core.polar import open_polar  # noqa: E402
from backend.planning.metrics import evaluate_path  # noqa: E402
from backend.planning.planners import (ALGORITHMS, Grid, plan,  # noqa: E402
                                        smooth_path)

ROOT = Path(__file__).resolve().parents[1]
DEM = ROOT / "data" / "raw" / "polar" / "dem"

#: Connecting Ridge, Artemis III candidate region.
SITE_LAT, SITE_LON = -89.45, 222.0
HALF_PX = 250                      # 500 x 500 cells = 5.0 km square

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


# ---------------------------------------------------------------------------
print("\nTerrain — Connecting Ridge, 89.45 S / 222 E\n")

dem = open_polar(img, lbl)
# One cell of margin, discarded by the engine after differentiating. Without it
# the 3x3 operators duplicate the border and report about half the true gradient
# around the whole rim — the same fix the AOI path uses, applied here so both
# produce the same numbers for the same ground.
HALO = 1
_haloed = dem.window_around(SITE_LAT, SITE_LON, half_px=HALF_PX + HALO)
# Everything except the analysis works on the region proper, so the window is
# trimmed here — including its row/column origin, or every latlon_of would be
# off by one cell and the reported route would sit beside the terrain it was
# planned on.
win = dataclasses.replace(
    _haloed,
    elevation=_haloed.elevation[HALO:-HALO, HALO:-HALO],
    row0=_haloed.row0 + HALO, col0=_haloed.col0 + HALO)
ws = win.stats()
span_km = ws["shape"][0] * win.baseline_m / 1000.0

print(f"  window       : {ws['shape'][0]} x {ws['shape'][1]} px = {span_km:.2f} km square")
print(f"  baseline     : {win.baseline_m:.3f} m")
print(f"  elevation    : {ws['min_m']:.0f} .. {ws['max_m']:.0f} m   "
      f"(relief {ws['relief_m']:.0f} m)")

check("the window is real data, not a gap",
      np.isfinite(win.elevation).mean() > 0.99,
      f"{np.isfinite(win.elevation).mean() * 100:.2f}% valid")
check("relief is hundreds of metres, as a ridge should be",
      300 < ws["relief_m"] < 3000, f"{ws['relief_m']:.0f} m")
check("the baseline is the polar grid's, not the global grid's",
      abs(win.baseline_m - 10.0) < 0.01, f"{win.baseline_m:.3f} m")


# ---------------------------------------------------------------------------
print("\nTraversability under two soil models\n")

rover = ROVER_PROFILES["viper"]
surfaces = {}
for soil in ("nominal", "weak"):
    surfaces[soil] = analyse_traversability(
        _haloed.elevation, _haloed.baseline_m, rover=rover, soil=soil,
        risk_aversion=2.0, halo=HALO)

print(f"  {'soil':<10}{'passable':>10}{'clear':>8}{'slip p90':>10}{'slip max':>10}"
      f"{'traction-bound':>16}")
for soil, tm in surfaces.items():
    s = tm.stats()
    print(f"  {soil:<10}{s['passable_fraction'] * 100:>9.1f}%"
          f"{s['classes']['clear'] * 100:>7.1f}%{s['slip']['p90']:>10.3f}"
          f"{s['slip']['max']:>10.3f}"
          f"{s['binding_constraint']['traction'] * 100:>15.1f}%")

nom, weak = surfaces["nominal"], surfaces["weak"]
check("nominal soil leaves the ridge almost entirely drivable",
      nom.stats()["passable_fraction"] > 0.98,
      f"{nom.stats()['passable_fraction'] * 100:.1f}%")
check("weak soil closes ground that nominal soil allows",
      weak.stats()["passable_fraction"] < nom.stats()["passable_fraction"],
      f"{weak.stats()['passable_fraction'] * 100:.1f}% vs "
      f"{nom.stats()['passable_fraction'] * 100:.1f}%")
check("traction binds on real terrain, not just synthetic",
      weak.binding_constraint()["traction"] > 0.02,
      f"{weak.binding_constraint()['traction'] * 100:.1f}% of cells — "
      "slope alone would certify them")
check("traction never binds on nominal soil here",
      nom.binding_constraint()["traction"] == 0.0,
      "geometry governs, as the gradeability table predicts")


# ---------------------------------------------------------------------------
print("\nEndpoints\n")


def clearest_near(tm, r_target, c_target, radius=60):
    """Lowest-cost cell within a radius of a target — a deterministic pick.

    Endpoints are chosen from the terrain rather than hard-coded so the test
    describes the site rather than a lucky pair of coordinates.
    """
    h, w = tm.cost_s.shape
    r0, r1 = max(0, r_target - radius), min(h, r_target + radius)
    c0, c1 = max(0, c_target - radius), min(w, c_target + radius)
    sub = tm.cost_s[r0:r1, c0:c1]
    if not np.isfinite(sub).any():
        raise RuntimeError("no passable cell near the requested endpoint")
    idx = np.unravel_index(np.nanargmin(np.where(np.isfinite(sub), sub, np.inf)),
                           sub.shape)
    return int(r0 + idx[0]), int(c0 + idx[1])


n = win.shape[0]
start = clearest_near(nom, int(0.12 * n), int(0.12 * n))
goal = clearest_near(nom, int(0.88 * n), int(0.88 * n))

slat, slon = win.latlon_of(*start)
glat, glon = win.latlon_of(*goal)
print(f"  start  cell {start}   {float(slat):.4f} S-lat, {float(slon):.4f} E   "
      f"z = {win.elevation[start]:.0f} m")
print(f"  goal   cell {goal}   {float(glat):.4f} S-lat, {float(glon):.4f} E   "
      f"z = {win.elevation[goal]:.0f} m")

check("both endpoints are passable on nominal soil",
      np.isfinite(nom.cost_s[start]) and np.isfinite(nom.cost_s[goal]))
check("the endpoints are far enough apart to be a traverse",
      np.hypot(goal[0] - start[0], goal[1] - start[1]) * win.baseline_m > 3000,
      f"{np.hypot(goal[0] - start[0], goal[1] - start[1]) * win.baseline_m / 1000:.2f} km apart")


# ---------------------------------------------------------------------------
print("\nSeven planners on the same real cost surface\n")

grid = Grid(nom.cost_s, win.baseline_m)
results = {}
t_all = time.perf_counter()
for key, (label, _fn) in ALGORITHMS.items():
    results[key] = plan(grid, start, goal, algorithm=key)
print(f"  (all seven completed in {(time.perf_counter() - t_all):.1f} s)\n")

print(f"  {'algorithm':<16}{'found':>7}{'cost (s)':>12}{'ratio':>8}"
      f"{'expanded':>11}{'ms':>9}{'waypts':>8}")
print("  " + "-" * 71)
opt = results["dijkstra"].cost
for key, r in results.items():
    ratio = (r.cost / opt) if (r.found and np.isfinite(opt) and opt > 0) else float("nan")
    print(f"  {r.algorithm:<16}{str(r.found):>7}"
          f"{(r.cost if r.found else float('nan')):>12.1f}{ratio:>8.3f}"
          f"{r.nodes_expanded:>11,}{r.runtime_ms:>9.1f}{len(r.path):>8}")

check("every planner finds a route across real terrain",
      all(r.found for r in results.values()),
      ", ".join(k for k, r in results.items() if not r.found) or "all seven")

# Dijkstra bounds the *grid-constrained* planners only. Theta* is any-angle: it
# is not confined to 45 degree headings, so it searches a strictly larger set of
# routes and may legitimately come in below the grid optimum. Including it here
# would assert that a less constrained search cannot do better, which is false.
GRID_BOUND = ("bfs", "dijkstra", "astar", "weighted_astar", "dstar_lite", "rrt_star")
check("Dijkstra bounds every grid-constrained planner",
      all(results[k].cost >= opt - 1e-6 for k in GRID_BOUND if results[k].found),
      "a grid planner below the grid optimum would mean a bug")
check("D* Lite reaches the same optimum as Dijkstra",
      abs(results["dstar_lite"].cost - opt) < 1e-6,
      f"{results['dstar_lite'].cost:.3f} vs {opt:.3f}")
check("A* reproduces the optimum exactly on real terrain",
      abs(results["astar"].cost - opt) < 1e-6,
      f"{results['astar'].cost:.3f} vs {opt:.3f}")
check("Weighted A* stays inside its suboptimality bound",
      results["weighted_astar"].cost <= opt * 2.5 + 1e-6,
      f"{results['weighted_astar'].cost / opt:.3f}x, bound 2.5x")
check("Theta* returns fewer waypoints than the grid path",
      len(results["theta_star"].path) < len(results["astar"].path),
      f"{len(results['theta_star'].path)} vs {len(results['astar'].path)}")
check("BFS is more expensive, having ignored the cost surface",
      results["bfs"].cost > opt,
      f"{results['bfs'].cost / opt:.2f}x optimal — the control")

# The any-angle result, stated rather than assumed in either direction. On
# random weighted terrain Theta* came in 8.6% *above* the grid optimum
# (test_planners.py); here it comes in below. Real terrain has spatially
# coherent hazard — ridges and crater walls — so a straight chord tends to stay
# on the same kind of ground, while on uncorrelated noise it does not.
theta_ratio = results["theta_star"].cost / opt
print(f"\n  Theta* against the grid optimum: {theta_ratio:.3f}x "
      f"({(1 - theta_ratio) * 100:+.1f}% cost, "
      f"{len(results['theta_star'].path)} waypoints vs {len(results['astar'].path)})")
check("the any-angle result is reported, not assumed",
      0.85 < theta_ratio < 1.15,
      "within a plausible band either side of the grid optimum")


# ---------------------------------------------------------------------------
print("\nCost-validated smoothing — recovering the any-angle gap after A*\n")

t0 = time.perf_counter()
sm_path, sm_cost, sm_before = smooth_path(grid, results["astar"].path, max_span=200)
sm_ms = (time.perf_counter() - t0) * 1e3

print(f"  {'route':<26}{'cost (s)':>11}{'vs A*':>9}{'waypoints':>11}{'ms':>10}")
print("  " + "-" * 67)
print(f"  {'A* (grid optimum)':<26}{sm_before:>11.1f}{1.0:>9.4f}"
      f"{len(results['astar'].path):>11}{results['astar'].runtime_ms:>10.1f}")
print(f"  {'A* + smoothing':<26}{sm_cost:>11.1f}{sm_cost / sm_before:>9.4f}"
      f"{len(sm_path):>11}{sm_ms:>10.1f}")
print(f"  {'Theta* (any-angle)':<26}{results['theta_star'].cost:>11.1f}"
      f"{results['theta_star'].cost / sm_before:>9.4f}"
      f"{len(results['theta_star'].path):>11}"
      f"{results['theta_star'].runtime_ms:>10.1f}")

gap = 1.0 - results["theta_star"].cost / sm_before
recovered = 1.0 - sm_cost / sm_before
print(f"\n  any-angle gap {gap * 100:.2f}% — smoothing recovers "
      f"{recovered * 100:.2f}% of it ({recovered / gap * 100:.0f}% of the gap)")

check("smoothing never costs more than the optimal path it was given",
      sm_cost <= sm_before + 1e-6,
      "the optimality guarantee survives the post-process")
check("smoothing collapses the waypoint count on real terrain",
      len(sm_path) < len(results["astar"].path) / 5,
      f"{len(sm_path)} vs {len(results['astar'].path)}")
check("every smoothed segment is passable",
      all(grid.line_of_sight(a, b)[0] for a, b in zip(sm_path, sm_path[1:])))
check("smoothing is cheaper than running an any-angle search",
      sm_ms < results["theta_star"].runtime_ms,
      f"{sm_ms:.0f} ms of post-process vs {results['theta_star'].runtime_ms:.0f} ms")


# ---------------------------------------------------------------------------
print("\nDoes the heuristic still help here?\n")

d_exp = results["dijkstra"].nodes_expanded
a_exp = results["astar"].nodes_expanded
saving = 1.0 - a_exp / max(d_exp, 1)
finite = nom.cost_s[np.isfinite(nom.cost_s)]
spread = float(finite.max() / finite.min())

print(f"  cost spread on this surface : {spread:.1f}x  "
      f"({finite.min():.2f} to {finite.max():.2f} s/cell)")
print(f"  Dijkstra expansions         : {d_exp:,}")
print(f"  A* expansions               : {a_exp:,}")
print(f"  saving                      : {saving * 100:.1f}%")

check("real hazard terrain has a wide cost spread",
      spread > 5.0, f"{spread:.1f}x — the admissible heuristic is bounded by the cheapest cell")
check("the A* saving is far below the uniform-grid figure",
      saving < 0.60,
      f"{saving * 100:.1f}% here against 97% on a uniform grid (CONTRIBUTIONS.md 3.4)")


# ---------------------------------------------------------------------------
print("\nRoute metrics — the optimal path\n")

best = results["dijkstra"]
pm = evaluate_path(
    best.path, elevation=win.elevation, slope_deg=nom.slope_deg, risk=nom.risk,
    hazard=nom.hazard, speed_ms=nom.speed_ms, cell_m=win.baseline_m,
    rover=rover, latlon_of=win.latlon_of, hazard_classes=HAZARD_CLASSES)
d = pm.to_dict() if hasattr(pm, "to_dict") else pm.__dict__

for k in ("distance_m", "ground_distance_m", "straight_line_m", "detour_ratio",
          "time_s", "mean_speed_ms", "recommended_speed_ms", "safety_score"):
    v = getattr(pm, k, None)
    if v is not None:
        print(f"  {k:<24}{v:>12.3f}")
lim = getattr(pm, "limiting_factor", None)
if lim:
    print(f"  {'limiting_factor':<24}{lim:>12}")

check("the 3-D path is at least as long as its map projection",
      pm.distance_m >= pm.ground_distance_m - 1e-6,
      f"{pm.distance_m:.0f} m vs {pm.ground_distance_m:.0f} m")
check("the route detours around hazard rather than flying straight",
      pm.detour_ratio > 1.0, f"{pm.detour_ratio:.3f}x the straight line")
check("the recommended speed is the route's minimum, not its mean",
      pm.recommended_speed_ms <= pm.mean_speed_ms + 1e-9,
      f"{pm.recommended_speed_ms:.4f} vs mean {pm.mean_speed_ms:.4f} m/s")
check("travel time is hours, not minutes, at rover speeds",
      pm.time_s > 3600, f"{pm.time_s / 3600:.1f} hours for "
      f"{pm.distance_m / 1000:.2f} km")


# ---------------------------------------------------------------------------
print("\nDoes the soil model change the route, or only the report?\n")

grid_w = Grid(weak.cost_s, win.baseline_m)
if not (grid_w.passable(*start) and grid_w.passable(*goal)):
    print("  (endpoints impassable on weak soil — the strongest possible result)")
    check("weak soil changes the answer", True, "endpoints themselves close")
else:
    weak_plan = plan(grid_w, start, goal, algorithm="dijkstra")
    check("a route still exists on weak soil", weak_plan.found)
    if weak_plan.found:
        same = set(map(tuple, best.path)) & set(map(tuple, weak_plan.path))
        overlap = len(same) / max(len(best.path), 1)
        pm_w = evaluate_path(
            weak_plan.path, elevation=win.elevation, slope_deg=weak.slope_deg,
            risk=weak.risk, hazard=weak.hazard, speed_ms=weak.speed_ms,
            cell_m=win.baseline_m, rover=rover, latlon_of=win.latlon_of,
            hazard_classes=HAZARD_CLASSES)

        print(f"  {'':<14}{'distance':>12}{'time':>12}{'max slope':>11}{'safety':>9}")
        for nm, m in (("nominal", pm), ("weak", pm_w)):
            print(f"  {nm:<14}{m.distance_m:>11.0f}m{m.time_s / 3600:>11.2f}h"
                  f"{m.slope_max_deg:>10.1f}°{m.safety_score:>9.1f}")
        print(f"  cell overlap between the two routes: {overlap * 100:.1f}%")

        check("the weak-soil route is not the nominal route relabelled",
              overlap < 0.98,
              f"{overlap * 100:.1f}% shared cells — soil changes the geometry, "
              "not merely the numbers")
        check("the weak-soil route avoids steeper ground",
              pm_w.slope_max_deg <= pm.slope_max_deg + 1e-6,
              f"max slope {pm_w.slope_max_deg:.1f}° vs {pm.slope_max_deg:.1f}°")
        check("the weak-soil route takes longer",
              pm_w.time_s > pm.time_s,
              f"{pm_w.time_s / 3600:.2f} h vs {pm.time_s / 3600:.2f} h — "
              "the cost of respecting traction")


# ---------------------------------------------------------------------------
print("\nWould the coarse global DEM have given the same answer?\n")

# Same ground, sampled at 474 m instead of 10 m. Not a fair traverse — the
# point is that the verdict itself changes with resolution.
step = 47
coarse_z = win.elevation[::step, ::step]
coarse = analyse_traversability(coarse_z, win.baseline_m * step,
                                rover=rover, soil="nominal")
cs, ns = coarse.stats(), nom.stats()
print(f"  {'baseline':<12}{'cells':>8}{'mean slope':>12}{'max slope':>11}{'passable':>11}")
for nm, s, tm2 in (("10 m", ns, nom), ("470 m", cs, coarse)):
    print(f"  {nm:<12}{s['valid_cells']:>8,}{s['slope_deg']['mean']:>11.2f}°"
          f"{s['slope_deg']['max']:>10.1f}°{s['passable_fraction'] * 100:>10.1f}%")

check("the coarse grid understates the steepest ground",
      cs["slope_deg"]["max"] < ns["slope_deg"]["max"],
      f"{cs['slope_deg']['max']:.1f}° vs {ns['slope_deg']['max']:.1f}° — "
      "averaging over 470 m removes the hazard, it does not clear it")
check("the coarse grid declares the site safer than it is",
      cs["passable_fraction"] >= ns["passable_fraction"],
      f"{cs['passable_fraction'] * 100:.1f}% vs {ns['passable_fraction'] * 100:.1f}%")
check("the coarse analysis warns that it cannot support a traverse",
      any("cannot represent" in w for w in coarse.warnings),
      coarse.warnings[0][:60] + "…" if coarse.warnings else "no warning — wrong")


print(f"\n{npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
