"""
Composing an AOI into a planned traverse.

This is the layer that turns "a region and two coordinates" into "seven routes,
a recommendation, and the reasoning behind it". Everything below it already
existed and was tested in isolation; nothing here re-implements analysis or
search. What it adds is the composition, the honesty about endpoints, and the
justification a mission tool has to carry.

Cost of the work, measured
--------------------------
On the largest site AOI the budget allows (2.24 M cells, 19.0 x 11.8 km of
10 m polar data):

====================  =========  ==========  =============
planner               wall       cost ratio  expansions
====================  =========  ==========  =============
Weighted A* (e=2.5)     1.3 s       1.203      71,008
BFS                    20.5 s       1.288   1,957,940
A*                     43.9 s       1.000   1,551,320
Dijkstra               49.3 s       1.000   2,027,844
Theta*                110.4 s       0.978   1,537,467
====================  =========  ==========  =============

Two things follow. First, this cannot run inside a request — hence
``core.jobs``. Second, the algorithm set is a real choice rather than a
formality: running all seven costs minutes, so callers say what they want and
the default is the set the selection in ``ALGORITHMS.md`` actually rests on.

Note also that Weighted A*'s penalty grew from 4.5 % on a 250 k-cell grid to
20.3 % here. That is one sample, not a law, but it is the opposite direction
from the usual assumption that a bounded-suboptimal search stays near its
bound, and it is why the recommendation is measured per run rather than fixed.

Endpoints are never moved silently
----------------------------------
A start or goal that lands on impassable ground is snapped to the nearest cell
a rover could occupy, and the distance moved is *reported*. Quietly relocating
a mission's landing site by 200 m and then planning from the new one would be
the single most dangerous thing this module could do.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np

from ..analysis.hazard import HAZARD_CLASSES, analyse_traversability
from ..config import DEFAULT_RISK_AVERSION, ROVER_PROFILES
from ..core.aoi import AOI, Tier
from ..core.aoi_window import AOIWindow, read_aoi, trim_halo
from .metrics import evaluate_path
from .planners import ALGORITHMS, Grid, plan, smooth_path

__all__ = [
    "SnapResult", "AnalysisResult", "snap_to_passable",
    "analyse_aoi", "plan_traverse", "DEFAULT_ALGORITHMS", "FAST_ALGORITHMS",
]

#: The set the selection rationale rests on: an optimality reference, the
#: selected planner, the bounded-suboptimal alternative, and the any-angle one.
#: Roughly 205 s on a full-budget site AOI.
DEFAULT_ALGORITHMS = ("dijkstra", "astar", "weighted_astar", "theta_star")

#: For interactive use — a route in a couple of seconds, with its bound stated.
FAST_ALGORITHMS = ("weighted_astar",)

#: How far a start or goal may be moved onto passable ground before the request
#: is refused instead. 50 cells is 500 m at site posting: far enough to clear a
#: rim the user clicked on, near enough that the route still answers the
#: question that was asked.
MAX_SNAP_CELLS = 50

#: Cells of margin read beyond the AOI and discarded after differentiating.
#: One is enough for the 3x3 operators used here (Horn slope, Riley TRI,
#: Zevenbergen-Thorne curvature).
_HALO = 1

Progress = Callable[[float, str], None]


def _noop(_f: float, _m: str = "") -> None:
    pass


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@dataclass
class SnapResult:
    """Where an endpoint ended up, and how far it had to move to get there."""

    requested_lat: float
    requested_lon: float
    row: int
    col: int
    lat: float
    lon: float
    moved_cells: float
    moved_m: float
    snapped: bool
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "requested": {"lat": self.requested_lat, "lon": self.requested_lon},
            "used": {"lat": self.lat, "lon": self.lon},
            "cell": [self.row, self.col],
            "snapped": self.snapped,
            "moved_m": round(self.moved_m, 1),
            "reason": self.reason,
        }


def snap_to_passable(cost: np.ndarray, row: int, col: int, cell_m: float, *,
                     max_cells: int = MAX_SNAP_CELLS) -> tuple[int, int, float]:
    """Nearest cell a rover could occupy, searched outward in rings.

    Returns ``(row, col, moved_cells)``. Raises if nothing within
    ``max_cells`` is passable — better to refuse than to plan from somewhere
    the user did not choose.

    Rings rather than a scan of the whole array: at 2.24 M cells a global
    ``argwhere`` costs tens of milliseconds and allocates a second array, while
    the answer is almost always within a handful of cells.
    """
    h, w = cost.shape
    if not (0 <= row < h and 0 <= col < w):
        raise ValueError("coordinate lies outside the analysed region")
    if math.isfinite(cost[row, col]):
        return row, col, 0.0

    for radius in range(1, max_cells + 1):
        best = None
        best_d2 = None
        r0, r1 = max(0, row - radius), min(h, row + radius + 1)
        c0, c1 = max(0, col - radius), min(w, col + radius + 1)
        for r in range(r0, r1):
            # Only the ring's edge is new; interior rows were covered already.
            on_edge = (r == row - radius or r == row + radius)
            cols = range(c0, c1) if on_edge else (
                c for c in (col - radius, col + radius) if c0 <= c < c1)
            for c in cols:
                if not math.isfinite(cost[r, c]):
                    continue
                d2 = (r - row) ** 2 + (c - col) ** 2
                if best_d2 is None or d2 < best_d2:
                    best, best_d2 = (r, c), d2
        if best is not None:
            return best[0], best[1], math.sqrt(best_d2)

    raise ValueError(
        f"No passable cell within {max_cells} cells "
        f"({max_cells * cell_m / 1000:.1f} km) of the requested point. The "
        "region around it is impassable to this rover; choose another point "
        "or a rover with a higher slope limit.")


def _resolve_endpoint(win: AOIWindow, cost: np.ndarray, lat: float, lon: float,
                      label: str) -> SnapResult:
    rc = win.rowcol_of(lat, lon)
    if rc is None:
        raise ValueError(
            f"The {label} ({lat:.4f}, {lon:.4f}) lies outside this AOI.")
    row, col, moved = snap_to_passable(cost, rc[0], rc[1], win.cell_m)
    la, lo = win.latlon_of(row, col)
    return SnapResult(
        requested_lat=lat, requested_lon=lon, row=row, col=col, lat=la, lon=lo,
        moved_cells=moved, moved_m=moved * win.cell_m, snapped=moved > 0,
        reason=("" if moved == 0 else
                f"the requested {label} was impassable; moved "
                f"{moved * win.cell_m:.0f} m to the nearest cell this rover "
                "can occupy"),
    )


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    aoi: AOI
    window: AOIWindow
    tmap: object                # TraversabilityMap
    seconds: float

    def to_dict(self) -> dict:
        return {
            "aoi": self.aoi.to_dict(),
            "window": self.window.stats(),
            "traversability": self.tmap.stats(),
            "seconds": round(self.seconds, 2),
        }


def analyse_aoi(aoi: AOI, *, rover: str = "viper", soil: str = "nominal",
                risk_aversion: float = DEFAULT_RISK_AVERSION,
                progress: Progress = _noop) -> AnalysisResult:
    """Read a region and derive its traversability."""
    t0 = time.perf_counter()
    progress(0.05, "reading elevation")
    # One cell of margin, discarded after differentiating. Without it the 3x3
    # slope operator has no neighbour outside the window, duplicates the border
    # instead, and reports roughly half the true gradient all the way round the
    # region — measured at 0.90x the interior mean on real polar terrain.
    win = read_aoi(aoi, halo=_HALO)

    # No projection special-case is needed here any more: read_aoi resamples
    # every AOI onto a square local grid, so a single cell size is exact
    # wherever the region sits and whichever product supplied the bytes.
    progress(0.25, "slope, roughness, slip, hazard")
    # The engine trims its own margin, so every caller gets true slope to the
    # region's edge without each having to remember to do it.
    tmap = analyse_traversability(win.elevation, win.cell_m, rover=rover,
                                  soil=soil, risk_aversion=risk_aversion,
                                  halo=_HALO)
    if _HALO:
        win = replace(win, elevation=trim_halo(win.elevation, _HALO))

    progress(0.45, "traversability complete")
    return AnalysisResult(aoi=aoi, window=win, tmap=tmap,
                          seconds=time.perf_counter() - t0)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def _recommend(rows: list[dict]) -> dict:
    """Pick a route to recommend, and say why in terms of what was measured."""
    found = [r for r in rows if r["found"]]
    if not found:
        return {"algorithm": None, "why": "no algorithm found a route"}

    optimal = [r for r in found if r.get("optimal_by_construction")]
    pool = optimal or found
    best = min(pool, key=lambda r: (r["cost_s"], r["runtime_ms"]))

    if optimal:
        why = (f"{best['algorithm']} carries an optimality guarantee by "
               f"construction and matched the lowest cost found "
               f"({best['cost_s']:.0f} s). ")
    else:
        why = (f"No algorithm run guaranteed optimality; {best['algorithm']} "
               f"returned the cheapest route found ({best['cost_s']:.0f} s). ")

    cheaper = [r for r in found if r["cost_s"] < best["cost_s"] - 1e-6]
    if cheaper:
        c = min(cheaper, key=lambda r: r["cost_s"])
        why += (f"{c['algorithm']} came in {(1 - c['cost_s']/best['cost_s'])*100:.1f} % "
                "cheaper but is any-angle, so it searches a larger set of routes "
                "than the grid optimum bounds and offers no guarantee. ")

    fastest = min(found, key=lambda r: r["runtime_ms"])
    if fastest["algorithm"] != best["algorithm"]:
        why += (f"{fastest['algorithm']} was {best['runtime_ms']/max(fastest['runtime_ms'],1e-9):.0f}x "
                f"faster for {(fastest['cost_s']/best['cost_s'] - 1)*100:+.1f} % cost, "
                "which is the trade to make if a route is needed interactively.")
    return {"algorithm": best["algorithm"], "key": best["key"], "why": why.strip()}


def plan_traverse(aoi: AOI, start: tuple[float, float], goal: tuple[float, float],
                  *, rover: str = "viper", soil: str = "nominal",
                  risk_aversion: float = DEFAULT_RISK_AVERSION,
                  algorithms: tuple[str, ...] | None = None,
                  smooth: bool = True,
                  analysis: AnalysisResult | None = None,
                  progress: Progress = _noop) -> dict:
    """Plan a traverse across an AOI with every requested algorithm.

    ``start`` and ``goal`` are ``(lat, lon)``. Both are snapped onto passable
    ground if necessary, and any movement is reported rather than absorbed.
    """
    algorithms = tuple(algorithms or DEFAULT_ALGORITHMS)
    unknown = [a for a in algorithms if a not in ALGORITHMS]
    if unknown:
        raise ValueError(f"unknown algorithm(s) {unknown}; "
                         f"have {sorted(ALGORITHMS)}")

    # A survey-tier route is geometrically sound — every AOI is resampled onto
    # a square grid, so rise-over-run and sqrt(2) diagonals hold at 237 m just
    # as at 10 m. What it is *not* is a rover-scale certification: a 237 m cell
    # averages away the 20 m scarp that would stop the vehicle. So it is planned
    # and labelled, rather than refused outright — choosing a corridor across a
    # region is a real task, and refusing it would leave most of the Moon
    # unusable. What must never happen is the two being confused.
    site = aoi.tier is Tier.SITE
    certification = "traverse" if site else "regional-corridor"
    cert_note = ("Rover-scale traverse: the posting resolves obstacles a "
                 "vehicle must respond to."
                 if site else
                 f"Regional corridor only. At {aoi.cell_m:.0f} m a cell averages "
                 f"over {aoi.cell_m / 10:.0f}x the ground a rover negotiates, so "
                 "this route selects a direction, not a drivable path. Peak "
                 "slope is understated — measured 33.9 deg on ground a 10 m grid "
                 "found at 69.0 deg. Re-plan at site tier before committing.")

    ana = analysis or analyse_aoi(aoi, rover=rover, soil=soil,
                                  risk_aversion=risk_aversion, progress=progress)
    win, tmap = ana.window, ana.tmap
    prof = ROVER_PROFILES[rover] if isinstance(rover, str) else rover

    progress(0.5, "resolving endpoints")
    s = _resolve_endpoint(win, tmap.cost_s, start[0], start[1], "start")
    g = _resolve_endpoint(win, tmap.cost_s, goal[0], goal[1], "goal")
    if (s.row, s.col) == (g.row, g.col):
        raise ValueError("start and goal resolve to the same cell")

    grid = Grid(tmap.cost_s, win.cell_m)
    rows: list[dict] = []
    paths: dict[str, list] = {}

    for i, key in enumerate(algorithms):
        progress(0.5 + 0.45 * i / max(len(algorithms), 1), f"planning: {key}")
        res = plan(grid, (s.row, s.col), (g.row, g.col), algorithm=key)
        row = res.to_dict()
        row["key"] = key
        if res.found:
            paths[key] = res.path
            row["metrics"] = _metrics(res.path, win, tmap, prof).to_dict()
        rows.append(row)

    # Ratio against the best guaranteed-optimal cost, which is the only
    # meaningful denominator: comparing to an any-angle route would make grid
    # planners look worse than they are for a reason unrelated to search.
    opt = [r["cost_s"] for r in rows
           if r["found"] and r.get("optimal_by_construction")]
    ref = min(opt) if opt else min((r["cost_s"] for r in rows if r["found"]),
                                   default=None)
    for r in rows:
        r["cost_ratio"] = (round(r["cost_s"] / ref, 4)
                           if (r["found"] and ref) else None)

    rec = _recommend(rows)
    progress(0.96, "smoothing and profiling")

    route = None
    if rec["algorithm"] is not None:
        chosen = paths[rec["key"]]
        if smooth and len(chosen) > 2:
            sm, sm_cost, before = smooth_path(grid, chosen, max_span=200)
            if sm_cost <= before + 1e-9:
                rec["smoothed"] = {
                    "waypoints_before": len(chosen), "waypoints_after": len(sm),
                    "cost_before_s": round(before, 3),
                    "cost_after_s": round(sm_cost, 3),
                    "note": ("shortcuts accepted only where the integrated cost "
                             "along the chord is lower, so the optimality bound "
                             "survives the post-process"),
                }
                chosen = sm
        route = _route_geometry(chosen, win, tmap)

    progress(1.0, "done")
    return {
        "aoi": aoi.to_dict(),
        "window": win.stats(),
        "traversability": tmap.stats(),
        "rover": prof.key,
        "soil": tmap.soil.name,
        "risk_aversion": risk_aversion,
        # What this route is, stated rather than left to be inferred from the
        # tier. The two must never be confused for one another.
        "certification": certification,
        "certification_note": cert_note,
        "endpoints": {"start": s.to_dict(), "goal": g.to_dict()},
        "algorithms": rows,
        "recommended": rec,
        "route": route,
        "analysis_seconds": round(ana.seconds, 2),
    }


def _metrics(path, win: AOIWindow, tmap, prof):
    return evaluate_path(
        path, elevation=win.elevation, slope_deg=tmap.slope_deg, risk=tmap.risk,
        hazard=tmap.hazard, speed_ms=tmap.speed_ms, cell_m=win.cell_m,
        rover=prof, latlon_of=win.latlon_of, hazard_classes=HAZARD_CLASSES)


def _densify(path) -> list[tuple[int, int]]:
    """Every cell the route actually crosses, not only its waypoints.

    An any-angle or smoothed route has waypoints hundreds of metres apart. A
    profile sampled at those waypoints alone would step over the ground between
    them — on a 3.3 km route that smoothing reduced to 15 waypoints, it would
    report terrain every 220 m on a 10 m grid, hiding precisely the slopes the
    route was shaped to avoid.

    So the chords are walked cell by cell, by the same Bresenham traversal the
    planner uses to price them. The waypoint count is still reported separately,
    because that is what a rover executes as commanded headings.
    """
    if len(path) < 2:
        return list(path)
    out: list[tuple[int, int]] = [tuple(path[0])]
    for (r0, c0), (r1, c1) in zip(path, path[1:]):
        dr, dc = abs(r1 - r0), abs(c1 - c0)
        sr = 1 if r1 > r0 else -1
        sc = 1 if c1 > c0 else -1
        err = dr - dc
        r, c = r0, c0
        while (r, c) != (r1, c1):
            e2 = 2 * err
            if e2 > -dc:
                err -= dc
                r += sr
            if e2 < dr:
                err += dr
                c += sc
            out.append((r, c))
    return out


def _route_geometry(path, win: AOIWindow, tmap) -> dict:
    """The route as coordinates, with the profiles FR-4.5/4.6 ask for."""
    waypoints = list(path)
    path = _densify(path)
    lat, lon, elev, slope, risk, slip = [], [], [], [], [], []
    for r, c in path:
        la, lo = win.latlon_of(r, c)
        lat.append(round(float(la), 6))
        lon.append(round(float(lo), 6))
        elev.append(round(float(win.elevation[r, c]), 2))
        slope.append(round(float(tmap.slope_deg[r, c]), 3))
        risk.append(round(float(tmap.risk[r, c]), 4))
        slip.append(round(float(tmap.slip[r, c]), 4))

    # Cumulative ground distance, so a profile can be plotted against distance
    # rather than against waypoint index — which would compress any-angle runs.
    dist = [0.0]
    for i in range(1, len(path)):
        dr = path[i][0] - path[i-1][0]
        dc = path[i][1] - path[i-1][1]
        dist.append(round(dist[-1] + math.hypot(dr, dc) * win.cell_m, 2))

    return {
        # What a rover executes: the commanded headings.
        "waypoints": len(waypoints),
        "waypoint_latlon": [[round(float(a), 6), round(float(b), 6)]
                            for a, b in (win.latlon_of(r, c) for r, c in waypoints)],
        # What it drives over: every cell crossed, for drawing and for profiles.
        "samples": len(path),
        "lat": lat, "lon": lon,
        "profile": {"distance_m": dist, "elevation_m": elev,
                    "slope_deg": slope, "risk": risk, "slip": slip},
    }
