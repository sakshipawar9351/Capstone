r"""
The planner benchmark the protocol promised.

``ALGORITHMS.md`` 6.2 lists what was outstanding before the selection could be
called final: four of the five scenarios, the epsilon sweep, RRT* variance over
thirty runs, and wall-clock as a median rather than a single sample. This runs
all of it and writes the numbers back.

Why each piece is here
----------------------
**Scenarios.** A benchmark on one site measures that site. Open mare, a crater
field, sustained highland slopes and a rim crossing exercise different regimes:
the first has almost no cost variation for a heuristic to exploit, the last is a
place where the only route is over something expensive.

**Epsilon sweep.** Weighted A* trades optimality for speed by a factor the
caller chooses. Reporting one value of that factor describes a point, not the
trade — and the two measurements taken so far disagree about its size (4.5 % on
a 250 k-cell grid, 20.3 % on 2.24 M), which is exactly why the curve matters.

**Thirty RRT\* runs.** A stochastic planner sampled once tells you nothing about
spread, and spread is the whole argument for rejecting it. One run quoted as
evidence would be the error this file exists to correct.

**Median of five.** A single wall-clock reading measures the machine's mood.

Run: ``python tests/benchmark_planners.py [--quick]``
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.metadata
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from backend.analysis.hazard import analyse_traversability  # noqa: E402
from backend.config import dataset_path  # noqa: E402
from backend.core.aoi import plan_aoi  # noqa: E402
from backend.core.aoi_window import read_aoi  # noqa: E402
from backend.planning.planners import Grid, plan, smooth_path  # noqa: E402

QUICK = "--quick" in sys.argv
REPEATS = 3 if QUICK else 5
RRT_RUNS = 8 if QUICK else 30
HALO = 1
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def output_path() -> Path:
    """Use a new timestamped artifact by default; never silently overwrite results."""
    if "--output" in sys.argv:
        i = sys.argv.index("--output")
        if i + 1 >= len(sys.argv):
            raise SystemExit("ERROR: --output requires a path")
        path = Path(sys.argv[i + 1])
    else:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = PROJECT_ROOT / "docs" / "results" / f"planner_benchmark_{stamp}.json"
    if path.exists() and "--force" not in sys.argv:
        raise SystemExit(f"ERROR: refusing to overwrite {path}; choose another --output or pass --force")
    return path


def source_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None

#: Scenarios 1-5 of the protocol. Bounds chosen so each lands in the regime it
#: is named for, and small enough that all seven planners finish.
SCENARIOS = [
    ("1 open mare",      "Mare Serenitatis, gentle",   25.0,  25.6,  17.0,  17.6),
    ("2 crater field",   "Highlands south of Tycho",  -46.0, -45.4, -12.0, -11.4),
    ("3 highland",       "Sustained slopes",          -10.0,  -9.4,  20.0,  20.6),
    ("4 rim crossing",   "Across a crater rim",       -43.6, -43.0, -11.6, -11.0),
    ("5 polar site",     "Connecting Ridge, 10 m",    -89.50, -89.42, 218.0, 226.0),
]

ALL = ("bfs", "dijkstra", "astar", "weighted_astar", "theta_star",
       "dstar_lite", "rrt_star")


def build(name, s, n, w, e):
    """Cost surface plus a start and goal near opposite corners."""
    aoi = plan_aoi(s, n, w, e)
    win = read_aoi(aoi, halo=HALO)
    tm = analyse_traversability(win.elevation, win.cell_m, rover="viper",
                                soil="nominal", halo=HALO)
    grid = Grid(tm.cost_s, win.cell_m)
    idx = np.argwhere(np.isfinite(tm.cost_s))
    if idx.size == 0:
        return None
    h, wd = tm.cost_s.shape

    def snap(r, c):
        d = (idx[:, 0] - r) ** 2 + (idx[:, 1] - c) ** 2
        return tuple(int(x) for x in idx[d.argmin()])

    start, goal = snap(h // 8, wd // 8), snap(h - h // 8 - 1, wd - wd // 8 - 1)
    if start == goal:
        return None
    return aoi, win, tm, grid, start, goal


def timed(grid, start, goal, algorithm, repeats=REPEATS, **kw):
    """Return the final deterministic result, median time and every timing sample."""
    times, res = [], None
    for _ in range(repeats):
        t0 = time.perf_counter()
        res = plan(grid, start, goal, algorithm=algorithm, **kw)
        times.append((time.perf_counter() - t0) * 1e3)
    return res, statistics.median(times), times


def path_length_m(path, cell_m: float) -> float | None:
    """Polyline length on the planner's row/column grid, including any-angle segments."""
    if not path or len(path) < 2:
        return 0.0 if path else None
    return float(sum(math.hypot(float(b[0]) - float(a[0]),
                                float(b[1]) - float(a[1])) * cell_m
                     for a, b in zip(path, path[1:])))


def main() -> int:
    if dataset_path("lola_dem", "LDEM_64.IMG") is None:
        print("ERROR: required global DEM not present; no benchmark was run.")
        return 2
    artifact_path = output_path()
    artifact = {
        "schema_version": 1,
        "run_started_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "run_type": "quick_smoke_benchmark_not_for_paper" if QUICK else "full_benchmark",
        "quick_mode": QUICK,
        "timing_repeats": REPEATS,
        "rrt_star_seeds": list(range(RRT_RUNS)),
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": package_version("numpy"),
        "source_commit": source_commit(),
        "scenarios": [],
        "skipped_scenarios": [],
        "weighted_astar_sweep": [],
        "notes": [
            "Run-level output records the actual per-scenario measurements generated by this invocation.",
            "Quick mode is a smoke benchmark and must not be presented as final paper evidence.",
            "Runtime values are environment-dependent; retain the environment and source commit."
        ]
    }
    print(f"\nPlanner benchmark — median of {REPEATS} runs, "
          f"RRT* over {RRT_RUNS}{'  [quick]' if QUICK else ''}\n")

    summary = []
    epsilon_context = None
    for label, note, s, n, w, e in SCENARIOS:
        built = build(label, s, n, w, e)
        if built is None:
            print(f"{label}: no usable terrain, skipped\n")
            artifact["skipped_scenarios"].append({"label": label, "reason": "no usable finite terrain"})
            continue
        aoi, win, tm, grid, start, goal = built
        st = tm.stats()
        grid_bytes = np.ascontiguousarray(tm.cost_s, dtype=np.float64).tobytes()
        case_record = {
            "label": label, "description": note,
            "bounds_deg": {"south": s, "north": n, "west": w, "east": e},
            "grid_shape": list(tm.cost_s.shape), "cell_m": float(win.cell_m),
            "start_rc": list(start), "goal_rc": list(goal),
            "cost_grid_sha256": hashlib.sha256(grid_bytes).hexdigest(),
            "terrain_summary": {
                "slope_mean_deg": float(st["slope_deg"]["mean"]),
                "slope_max_deg": float(st["slope_deg"]["max"]),
                "passable_fraction": float(st["passable_fraction"]),
                "cost_spread": float(np.max(tm.cost_s[np.isfinite(tm.cost_s)]) /
                                      np.min(tm.cost_s[np.isfinite(tm.cost_s)]))
            },
            "deterministic_planners": [], "rrt_star": {}, "smoothing": None
        }
        fin = tm.cost_s[np.isfinite(tm.cost_s)]
        spread = float(fin.max() / fin.min())

        print(f"{label} — {note}")
        print(f"  {aoi.rows}x{aoi.cols} @ {aoi.cell_m:.0f} m, "
              f"slope mean {st['slope_deg']['mean']:.1f} max {st['slope_deg']['max']:.1f} deg, "
              f"passable {st['passable_fraction']*100:.2f}%, cost spread {spread:.1f}x")
        print(f"  {'algorithm':<22}{'cost':>12}{'ratio':>8}{'ms':>10}{'expanded':>11}")
        print("  " + "-" * 63)

        rows, ref = {}, None
        for alg in ALL:
            if alg == "rrt_star":
                continue
            res, ms, time_samples = timed(grid, start, goal, alg)
            rows[alg] = (res, ms, time_samples)
            if res.found and res.optimal and ref is None:
                ref = res.cost
        for alg, (res, ms, time_samples) in rows.items():
            ratio = (res.cost / ref) if (res.found and ref) else float("nan")
            print(f"  {res.algorithm:<22}{res.cost:>12.1f}{ratio:>8.3f}"
                  f"{ms:>10.1f}{res.nodes_expanded:>11,}")
            case_record["deterministic_planners"].append({
                "algorithm": res.algorithm,
                "found": bool(res.found), "optimal": bool(res.optimal),
                "cost_s": float(res.cost) if res.found else None,
                "ratio_to_reference": float(ratio) if np.isfinite(ratio) else None,
                "runtime_ms_median": float(ms), "runtime_samples_ms": [float(x) for x in time_samples],
                "timing_repeats": REPEATS, "nodes_expanded": int(res.nodes_expanded),
                "path_length_m": path_length_m(res.path, win.cell_m),
                "waypoint_count": len(res.path) if res.path is not None else 0
            })

        # RRT* separately: stochastic, so spread is the measurement.
        costs, times, rrt_runs = [], [], []
        for seed in range(RRT_RUNS):
            t0 = time.perf_counter()
            r = plan(grid, start, goal, algorithm="rrt_star", seed=seed)
            elapsed_ms = (time.perf_counter() - t0) * 1e3
            times.append(elapsed_ms)
            run_cost = float(r.cost) if r.found else None
            rrt_runs.append({"seed": seed, "found": bool(r.found), "cost_s": run_cost,
                             "runtime_ms": float(elapsed_ms),
                             "nodes_expanded": int(r.nodes_expanded)})
            if r.found:
                costs.append(r.cost)
        case_record["rrt_star"] = {
            "requested_runs": RRT_RUNS, "successful_runs": len(costs), "runs": rrt_runs,
            "cost_mean_s": float(statistics.mean(costs)) if costs else None,
            "cost_median_s": float(statistics.median(costs)) if costs else None,
            "cost_population_sd_s": float(statistics.pstdev(costs)) if len(costs) > 1 else (0.0 if costs else None),
            "runtime_median_ms": float(statistics.median(times)) if times else None,
            "cost_ratio_min": float(min(c / ref for c in costs)) if costs and ref else None,
            "cost_ratio_max": float(max(c / ref for c in costs)) if costs and ref else None
        }
        if costs:
            rel = [c / ref for c in costs] if ref else costs
            print(f"  {'RRT* (n=' + str(RRT_RUNS) + ')':<22}"
                  f"{statistics.mean(costs):>12.1f}"
                  f"{statistics.mean(rel):>8.3f}{statistics.median(times):>10.1f}"
                  f"{'  found ' + str(len(costs)) + '/' + str(RRT_RUNS):>11}")
            print(f"    spread: {min(rel):.3f}x to {max(rel):.3f}x optimal, "
                  f"sd {statistics.pstdev(rel):.3f}")

        # Smoothing on the optimal route.
        a = rows["astar"][0]
        if a.found and len(a.path) > 2:
            sm, sc, before = smooth_path(grid, a.path, max_span=200)
            print(f"    smoothing: {len(a.path)} -> {len(sm)} waypoints, "
                  f"{before:.0f} -> {sc:.0f} s ({sc/before:.4f}x)")
            case_record["smoothing"] = {
                "original_waypoints": len(a.path), "smoothed_waypoints": len(sm),
                "original_cost_s": float(before), "smoothed_cost_s": float(sc),
                "cost_ratio": float(sc / before) if before else None
            }

        artifact["scenarios"].append(case_record)
        summary.append((label, spread,
                        rows["dijkstra"][0].nodes_expanded,
                        rows["astar"][0].nodes_expanded,
                        rows["theta_star"][0].cost / ref if ref else float("nan")))
        print()

        if label.startswith("5"):
            epsilon_context = (grid, start, goal, ref, label)

    # -- epsilon sweep -----------------------------------------------------
    if epsilon_context is not None:
        eps_grid, eps_start, eps_goal, eps_ref, eps_label = epsilon_context
        print("Weighted A* — the speed/optimality curve\\n")
        print(f"  {'epsilon':>8}{'cost ratio':>12}{'ms':>10}{'expanded':>11}"
              f"{'vs A* speed':>13}")
        print("  " + "-" * 54)
        base, base_ms, base_samples = timed(eps_grid, eps_start, eps_goal, "astar")
        for eps in (1.0, 1.25, 1.5, 2.0, 2.5, 4.0, 8.0):
            res, ms, time_samples = timed(eps_grid, eps_start, eps_goal, "weighted_astar", weight=eps)
            ratio = res.cost / eps_ref if res.found and eps_ref else float("nan")
            speedup = base_ms / max(ms, 1e-9)
            print(f"  {eps:>8.2f}{ratio:>12.4f}{ms:>10.1f}"
                  f"{res.nodes_expanded:>11,}{speedup:>12.1f}x")
            artifact["weighted_astar_sweep"].append({
                "scenario": eps_label, "epsilon": float(eps), "found": bool(res.found),
                "cost_s": float(res.cost) if res.found else None,
                "ratio_to_reference": float(ratio) if np.isfinite(ratio) else None,
                "runtime_ms_median": float(ms), "runtime_samples_ms": [float(x) for x in time_samples],
                "timing_repeats": REPEATS, "weight": float(eps),
                "nodes_expanded": int(res.nodes_expanded),
                "path_length_m": path_length_m(res.path, eps_grid.cell_m),
                "speedup_vs_astar": float(speedup)
            })
        print(f"\\n  A* reference: {base.cost:.1f} s in {base_ms:.1f} ms, "
              f"{base.nodes_expanded:,} expansions")
    else:
        print("Weighted A* sweep skipped: the fifth scenario had no usable terrain.")
        artifact["weighted_astar_sweep_skipped_reason"] = "fifth scenario unavailable"

    # -- how the heuristic's value varies with terrain ---------------------
    print("\\nDoes the A* advantage hold across regimes?\\n")
    print(f"  {'scenario':<18}{'cost spread':>13}{'Dijkstra':>11}{'A*':>10}"
          f"{'saving':>9}{'Theta*':>9}")
    print("  " + "-" * 70)
    for label, spread, dij, ast, th in summary:
        print(f"  {label:<18}{spread:>12.1f}x{dij:>11,}{ast:>10,}"
              f"{(1-ast/max(dij,1))*100:>8.0f}%{th:>9.3f}")

    artifact["run_finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    artifact["scenario_count_completed"] = len(artifact["scenarios"])
    artifact["scenario_count_skipped"] = len(artifact["skipped_scenarios"])
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(f"\\nStructured benchmark artifact saved to: {artifact_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
