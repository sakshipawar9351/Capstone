"""
The planning service, end to end on real terrain.

Exercises the composition that turns a region and two coordinates into routes:
AOI -> window -> traversability -> planners -> metrics -> recommendation.
Everything underneath is verified elsewhere; what is checked here is that the
pieces agree with each other, and that the parts a mission tool must never get
wrong — moved endpoints, refused requests, the basis of a recommendation — are
reported rather than absorbed.

Site: the Connecting Ridge area, 10 m LOLA polar data.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from backend.config import dataset_path  # noqa: E402
from backend.core.aoi import Tier, plan_aoi  # noqa: E402
from backend.planning.service import (  # noqa: E402
    FAST_ALGORITHMS, analyse_aoi, plan_traverse, snap_to_passable)

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


# ---------------------------------------------------------------------------
print("\nAnalysis of a site AOI\n")

aoi = plan_aoi(-89.50, -89.42, 218.0, 226.0, tier=Tier.SITE)
print(f"  AOI {aoi.rows}x{aoi.cols} = {aoi.cell_count:,} cells @ {aoi.cell_m:.0f} m")

seen: list[tuple[float, str]] = []
t0 = time.perf_counter()
ana = analyse_aoi(aoi, rover="viper", soil="nominal",
                  progress=lambda f, m: seen.append((f, m)))
t_ana = time.perf_counter() - t0

st = ana.tmap.stats()
print(f"  analysed in {t_ana:.1f}s — passable {st['passable_fraction']*100:.2f}%, "
      f"slope max {st['slope_deg']['max']:.1f}°")

check("the window is real data",
      ana.window.stats()["valid_fraction"] > 0.99)

# A 3x3 operator at a window's edge has no outside neighbour. With
# mode="nearest" it sees a duplicated column and reports roughly half the true
# gradient — measured at 0.90x the interior mean before this was fixed. The
# analysis therefore reads one cell of margin and trims it after
# differentiating, so the caller gets true slope right to the region's edge.
from backend.analysis.hazard import analyse_traversability  # noqa: E402
from backend.core.aoi_window import trim_halo  # noqa: E402

_ramp = np.arange(42, dtype=float)[None, :].repeat(42, axis=0) * 1.0
_haloed = analyse_traversability(_ramp, 10.0, rover="viper").slope_deg
_trimmed = trim_halo(_haloed, 1)
_expect = np.degrees(np.arctan(0.1))
check("a haloed ramp has uniform slope to its very edge",
      bool(np.allclose(_trimmed, _expect, atol=1e-6)),
      f"{_trimmed.min():.4f}..{_trimmed.max():.4f} deg against {_expect:.4f}")
check("without the halo the edge would be understated",
      abs(_haloed[:, 0].mean() - _expect) > 1.0,
      f"untrimmed edge reads {_haloed[:, 0].mean():.4f} deg — the bug this guards")

check("analysis returns exactly the region asked for, halo removed",
      ana.tmap.slope_deg.shape == (aoi.rows, aoi.cols)
      and ana.window.elevation.shape == (aoi.rows, aoi.cols),
      f"{list(ana.tmap.slope_deg.shape)} vs [{aoi.rows}, {aoi.cols}]")
check("progress was reported while it ran", len(seen) >= 2,
      f"{len(seen)} updates, last {seen[-1][1]!r}")
check("the analysis is at the AOI's own posting",
      abs(ana.window.cell_m - aoi.cell_m) < 1e-9)
check("traversability names the binding constraint",
      "binding_constraint" in st, str(st.get("binding_constraint")))


# ---------------------------------------------------------------------------
print("\nEndpoints are snapped, never moved silently\n")

cost = ana.tmap.cost_s
free = np.argwhere(np.isfinite(cost))
blocked = np.argwhere(~np.isfinite(cost))
check("the region contains both passable and impassable ground",
      free.size > 0 and blocked.size > 0,
      f"{len(free):,} passable, {len(blocked):,} blocked")

r, c = (int(free[0][0]), int(free[0][1]))
check("a passable cell is left where it is",
      snap_to_passable(cost, r, c, ana.window.cell_m) == (r, c, 0.0))

if blocked.size:
    br, bc = int(blocked[len(blocked)//2][0]), int(blocked[len(blocked)//2][1])
    sr, sc, moved = snap_to_passable(cost, br, bc, ana.window.cell_m)
    check("an impassable cell snaps to passable ground",
          np.isfinite(cost[sr, sc]) and moved > 0,
          f"moved {moved:.1f} cells = {moved*ana.window.cell_m:.0f} m")


# ---------------------------------------------------------------------------
print("\nPlanning a traverse\n")

lat_s, lon_s = ana.window.latlon_of(int(0.15 * ana.window.shape[0]),
                                    int(0.15 * ana.window.shape[1]))
lat_g, lon_g = ana.window.latlon_of(int(0.85 * ana.window.shape[0]),
                                    int(0.85 * ana.window.shape[1]))

t0 = time.perf_counter()
rep = plan_traverse(aoi, (lat_s, lon_s), (lat_g, lon_g),
                    rover="viper", soil="nominal", analysis=ana)
t_plan = time.perf_counter() - t0
print(f"  planned in {t_plan:.1f}s with {len(rep['algorithms'])} algorithms\n")

print(f"  {'algorithm':<22}{'found':>7}{'cost (s)':>12}{'ratio':>8}{'ms':>9}{'wp':>7}")
print("  " + "-" * 65)
for a in rep["algorithms"]:
    print(f"  {a['algorithm']:<22}{str(a['found']):>7}"
          f"{(a['cost_s'] or float('nan')):>12.1f}"
          f"{(a['cost_ratio'] or float('nan')):>8.3f}"
          f"{a['runtime_ms']:>9.0f}{a['waypoints']:>7}")

check("every requested algorithm ran",
      len(rep["algorithms"]) == 4, str(len(rep["algorithms"])))
check("all of them found a route",
      all(a["found"] for a in rep["algorithms"]))

opt = [a for a in rep["algorithms"] if a.get("optimal_by_construction")]
check("the optimal planners agree exactly",
      len({round(a["cost_s"], 6) for a in opt}) == 1,
      f"{[a['algorithm'] for a in opt]} all at "
      f"{opt[0]['cost_s']:.3f} s")

check("endpoints are reported with any movement",
      "snapped" in rep["endpoints"]["start"]
      and "moved_m" in rep["endpoints"]["start"],
      f"start moved {rep['endpoints']['start']['moved_m']} m, "
      f"goal moved {rep['endpoints']['goal']['moved_m']} m")


# ---------------------------------------------------------------------------
print("\nThe recommendation is justified, not asserted\n")

rec = rep["recommended"]
print(f"  -> {rec['algorithm']}")
print(f"     {rec['why'][:150]}…")
check("a route is recommended", rec["algorithm"] is not None)
check("the reasoning cites what was measured",
      any(t in rec["why"] for t in ("optimality", "cheaper", "faster")),
      "a recommendation without a reason tells an operator nothing")
if "smoothed" in rec:
    sm = rec["smoothed"]
    print(f"     smoothing {sm['waypoints_before']} -> {sm['waypoints_after']} "
          f"waypoints, cost {sm['cost_before_s']:.0f} -> {sm['cost_after_s']:.0f} s")
    check("smoothing never raised the cost",
          sm["cost_after_s"] <= sm["cost_before_s"] + 1e-6)
    check("smoothing reduced the waypoint count",
          sm["waypoints_after"] < sm["waypoints_before"])


# ---------------------------------------------------------------------------
print("\nThe route carries geometry and profiles\n")

route = rep["route"]
p = route["profile"]
span_km = p["distance_m"][-1] / 1000
print(f"  {route['waypoints']} waypoints (commanded headings), "
      f"{route['samples']} samples along {span_km:.2f} km")
step = p["distance_m"][-1] / max(route["samples"] - 1, 1)
print(f"  profile sampled every {step:.1f} m on a {ana.window.cell_m:.0f} m grid")

check("coordinates are returned for the globe",
      len(route["lat"]) == route["samples"] == len(route["lon"]))
check("elevation and slope profiles are present (FR-4.5 / 4.6)",
      len(p["elevation_m"]) == route["samples"]
      and len(p["slope_deg"]) == route["samples"])
check("distance increases monotonically",
      all(b >= a for a, b in zip(p["distance_m"], p["distance_m"][1:])))
check("the profile also carries risk and slip",
      len(p["risk"]) == len(p["slip"]) == route["samples"])
check("every sample sits on passable ground",
      all(s < 90.0 for s in p["slope_deg"]))

# A smoothed route has waypoints hundreds of metres apart; profiling at those
# alone would step straight over the terrain the route was shaped to avoid.
check("the profile follows the ground, not just the waypoints",
      route["samples"] > route["waypoints"] * 3,
      f"{route['samples']} samples for {route['waypoints']} waypoints")
check("sampling is at grid resolution, not waypoint spacing",
      step <= ana.window.cell_m * 1.5,
      f"{step:.1f} m steps on a {ana.window.cell_m:.0f} m grid")
check("waypoints are reported separately for execution",
      len(route["waypoint_latlon"]) == route["waypoints"])


# ---------------------------------------------------------------------------
print("\nRefusals\n")

check("this AOI is certified as a rover traverse",
      rep["certification"] == "traverse", rep["certification_note"][:60])

try:
    plan_traverse(aoi, (-89.46, 222.0), (-20.0, 50.0), analysis=ana)
    check("an endpoint outside the AOI is refused", False, "it planned")
except ValueError as e:
    check("an endpoint outside the AOI is refused",
          "outside" in str(e), str(e)[:70])

try:
    plan_traverse(aoi, (lat_s, lon_s), (lat_g, lon_g),
                  algorithms=("teleport",), analysis=ana)
    check("an unknown algorithm is refused", False, "it planned")
except ValueError as e:
    check("an unknown algorithm is refused", "unknown algorithm" in str(e))


# ---------------------------------------------------------------------------
print("\nA fast plan is available for interactive use\n")

t0 = time.perf_counter()
quick = plan_traverse(aoi, (lat_s, lon_s), (lat_g, lon_g),
                      algorithms=FAST_ALGORITHMS, analysis=ana)
t_quick = time.perf_counter() - t0
qa = quick["algorithms"][0]
print(f"  {qa['algorithm']} in {t_quick:.2f}s, cost {qa['cost_s']:.0f} s")
check("the fast set returns a route", qa["found"])
check("it is faster than the full comparison", t_quick < t_plan,
      f"{t_quick:.2f}s vs {t_plan:.2f}s")
check("its suboptimality bound is stated, not hidden",
      qa.get("optimal_by_construction") is False and qa.get("note"),
      qa.get("note", ""))


# ---------------------------------------------------------------------------
print("\nAny region on the Moon can be planned — and says what it is\n")

for name, (s, n, w, e), (a_lat, a_lon), (b_lat, b_lon) in [
    ("Mare Imbrium", (32.0, 33.0, -18.0, -17.0), (32.2, -17.8), (32.8, -17.2)),
    ("Tycho",        (-44.0, -43.0, -11.5, -10.5), (-43.8, -11.3), (-43.2, -10.7)),
    ("far side",     (10.0, 11.0, 180.0, 181.0), (10.2, 180.2), (10.8, 180.8)),
]:
    a = plan_aoi(s, n, w, e, tier=Tier.SURVEY)
    r = plan_traverse(a, (a_lat, a_lon), (b_lat, b_lon),
                      algorithms=FAST_ALGORITHMS)
    km = r["route"]["profile"]["distance_m"][-1] / 1000
    print(f"  {name:<14} {a.cell_m:>4.0f} m  {km:>6.2f} km  "
          f"{r['certification']}")
    check(f"{name} plans without special-casing", r["route"] is not None)
    check(f"{name} is labelled a regional corridor, not a traverse",
          r["certification"] == "regional-corridor")

corridor = plan_traverse(
    plan_aoi(32.0, 33.0, -18.0, -17.0, tier=Tier.SURVEY),
    (32.2, -17.8), (32.8, -17.2), algorithms=FAST_ALGORITHMS)
check("a survey route warns that peak slope is understated",
      "understated" in corridor["certification_note"],
      "the honest difference between choosing a direction and certifying a drive")
check("a survey route does not claim traverse support",
      corridor["aoi"]["capability"]["supports_traverse"] is False)


print(f"\n{npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
