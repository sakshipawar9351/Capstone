"""
Evaluating a planned route.

A planner returns a sequence of cells and a scalar cost. That is not enough to
decide whether a rover should drive it. This module turns a path into the
report the brief asks for: how far, how long, how steep, how much energy, how
risky, what it passes through, and how much margin remains before the vehicle's
limits.

Two principles shape the numbers below.

**Distance is three-dimensional.** A traverse that climbs 400 m over 2 km is
longer than 2 km, and reporting the map distance would understate both time and
energy. Every segment is measured with its elevation change included.

**Safety is governed by the worst point, not the average.** A route that is
gentle for 5 km and crosses one 30 deg scarp is not a safe route, and averaging
would hide exactly the cell that matters. The safety score is therefore
dominated by the minimum margin along the path, with the mean contributing only
a secondary term.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..config import G_MOON, RoverProfile

__all__ = ["PathMetrics", "evaluate_path"]


@dataclass
class PathMetrics:
    """Everything measurable about one route."""

    # Geometry
    distance_m: float                 # 3-D, following the terrain
    ground_distance_m: float          # map distance, for comparison
    straight_line_m: float            # start to goal, the lower bound
    detour_ratio: float               # distance / straight line
    waypoints: int

    # Time and effort
    time_s: float
    mean_speed_ms: float
    min_speed_ms: float
    recommended_speed_ms: float
    energy_j: float
    climb_m: float                    # total ascent
    descent_m: float

    # Terrain crossed
    elev_min_m: float
    elev_max_m: float
    elev_mean_m: float
    slope_mean_deg: float
    slope_max_deg: float
    slope_p90_deg: float

    # Risk
    risk_mean: float
    risk_max: float
    hazard_fractions: dict[str, float]
    safety_score: float               # 0-100
    slope_margin: float               # 0-1, headroom to tip-over
    limiting_factor: str

    # Context
    craters_crossed: list[dict] = field(default_factory=list)
    craters_avoided: list[dict] = field(default_factory=list)
    baseline_m: float = 0.0
    rover: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        r1 = lambda v: round(float(v), 1)      # noqa: E731
        r3 = lambda v: round(float(v), 3)      # noqa: E731
        return {
            "geometry": {
                "distance_km": round(self.distance_m / 1000, 3),
                "ground_distance_km": round(self.ground_distance_m / 1000, 3),
                "straight_line_km": round(self.straight_line_m / 1000, 3),
                "detour_ratio": r3(self.detour_ratio),
                "waypoints": self.waypoints,
                "climb_m": r1(self.climb_m),
                "descent_m": r1(self.descent_m),
            },
            "traverse": {
                "time_s": r1(self.time_s),
                "time_hours": round(self.time_s / 3600, 2),
                "mean_speed_ms": r3(self.mean_speed_ms),
                "min_speed_ms": r3(self.min_speed_ms),
                "recommended_speed_ms": r3(self.recommended_speed_ms),
                "energy_kj": round(self.energy_j / 1000, 1),
            },
            "elevation": {
                "min_m": r1(self.elev_min_m),
                "max_m": r1(self.elev_max_m),
                "mean_m": r1(self.elev_mean_m),
            },
            "slope": {
                "mean_deg": r3(self.slope_mean_deg),
                "p90_deg": r3(self.slope_p90_deg),
                "max_deg": r3(self.slope_max_deg),
                "baseline_m": r1(self.baseline_m),
            },
            "risk": {
                "mean": r3(self.risk_mean),
                "max": r3(self.risk_max),
                "hazard_fractions": {k: round(v, 4)
                                     for k, v in self.hazard_fractions.items()},
                "safety_score": r1(self.safety_score),
                "slope_margin": r3(self.slope_margin),
                "limiting_factor": self.limiting_factor,
            },
            "craters": {
                "crossed": self.craters_crossed,
                "avoided_nearby": self.craters_avoided,
                "n_crossed": len(self.craters_crossed),
                "n_avoided": len(self.craters_avoided),
            },
            "rover": self.rover,
            "warnings": self.warnings,
        }


def _safety_score(slope_max, risk_max, hazard_frac,
                  rover: RoverProfile) -> tuple[float, float, str]:
    r"""Composite 0-100 safety, and the factor that limits it.

    .. math:: S = 100\,(1 - r_\max)\,(1 - f_\text{hazard})

    where :math:`r_\max` is the peak cell risk along the route.

    **Why slope does not appear separately.** Risk is already
    :math:`1-(1-r_\theta)(1-r_\text{rough})`, the probability of at least one
    independent failure mode, and :math:`r_\theta` is a function of slope. An
    earlier version multiplied by a slope-margin term as well, which counted
    the same gradient twice and depressed every score on sloping ground — a
    9.5° ramp scored 68 rather than 93. One physical quantity, one appearance.

    **Why the peak and not the mean.** A route that is gentle for 5 km and
    crosses one scarp is not safe, and averaging conceals precisely the cell
    that stops the vehicle. The mean is reported alongside, but does not enter
    the score.

    **Why multiplication.** The terms are not interchangeable: terrain that is
    partly impassable cannot be redeemed by being smooth elsewhere. Each factor
    can veto the score alone, which is how a physical limit behaves and a
    weighted sum does not.
    """
    score = 100.0 * (1.0 - risk_max) * (1.0 - hazard_frac)

    # Margin to static stability, reported for interpretation rather than
    # folded into the score.
    m_slope = max(0.0, 1.0 - slope_max / max(rover.tip_over_slope_deg, 1e-6))

    # Name whichever term is doing the damage — a bare number tells an operator
    # nothing about what to change.
    terms = {
        "peak risk": risk_max,
        "hazardous fraction of route": hazard_frac,
        "slope margin": 1.0 - m_slope,
    }
    limiting = max(terms, key=terms.get)
    if max(terms.values()) < 0.10:
        limiting = "none — comfortable margin on all counts"
    return float(np.clip(score, 0.0, 100.0)), m_slope, limiting


def evaluate_path(path, *, elevation, slope_deg, risk, hazard, speed_ms,
                  cell_m, rover: RoverProfile, latlon_of=None,
                  crater_index=None, hazard_classes=None) -> PathMetrics:
    """Measure a planned route.

    ``path`` is a list of ``(row, col)`` cells. The remaining arrays are the
    traversability rasters the path was planned over, so every statistic refers
    to the same terrain the planner saw.

    ``latlon_of`` maps a cell to selenographic coordinates, enabling true
    geodesic distance and crater lookup. Without it, distances fall back to
    planar cell geometry and are reported as such.
    """
    if len(path) < 2:
        raise ValueError("a path needs at least two waypoints")

    warnings: list[str] = []
    rows = np.array([p[0] for p in path])
    cols = np.array([p[1] for p in path])

    z = np.asarray(elevation, dtype=np.float64)[rows, cols]
    s = np.asarray(slope_deg, dtype=np.float64)[rows, cols]
    rk = np.asarray(risk, dtype=np.float64)[rows, cols]
    hz = np.asarray(hazard)[rows, cols]
    v = np.asarray(speed_ms, dtype=np.float64)[rows, cols]

    # ── Geometry ────────────────────────────────────────────────────────
    dr = np.diff(rows).astype(float)
    dc = np.diff(cols).astype(float)
    ground_seg = np.hypot(dr, dc) * cell_m
    dz = np.diff(z)
    # Three-dimensional: a climb lengthens the traverse.
    seg = np.hypot(ground_seg, dz)

    ground_distance = float(ground_seg.sum())
    distance = float(seg.sum())
    climb = float(dz[dz > 0].sum())
    descent = float(-dz[dz < 0].sum())

    if latlon_of is not None:
        from ..core import selenographic as sg
        la0, lo0 = latlon_of(*path[0])
        la1, lo1 = latlon_of(*path[-1])
        straight = float(sg.haversine_distance(la0, lo0, la1, lo1))
    else:
        straight = float(math.hypot(rows[-1] - rows[0], cols[-1] - cols[0]) * cell_m)
        warnings.append("No coordinate mapping supplied; straight-line distance "
                        "is planar rather than geodesic.")

    # ── Time and energy ─────────────────────────────────────────────────
    # Segment speed is the mean of its endpoints, matching how edge cost was
    # computed during planning so time and cost stay consistent.
    v_seg = 0.5 * (v[:-1] + v[1:])
    v_seg = np.maximum(v_seg, 1e-6)
    time_s = float((seg / v_seg).sum())
    mean_speed = distance / time_s if time_s > 0 else 0.0

    # Work = lift against gravity + rolling resistance over ground distance.
    # Descent is not credited: a rover cannot regenerate, and braking costs
    # energy rather than returning it.
    energy = (rover.mass_kg * G_MOON * climb
              + rover.mu_rolling * rover.mass_kg * G_MOON * ground_distance)

    # ── Risk and safety ─────────────────────────────────────────────────
    n = len(path)
    fractions = {}
    if hazard_classes:
        for hc in hazard_classes:
            fractions[hc.key] = float((hz == hc.code).sum()) / n
    hazard_frac = fractions.get("hazard", 0.0) + fractions.get("impassable", 0.0)

    score, margin, limiting = _safety_score(
        float(s.max()), float(rk.max()), hazard_frac, rover)

    if float(s.max()) > rover.max_slope_deg:
        warnings.append(
            f"Path reaches {s.max():.1f} deg, beyond the sustained gradeability "
            f"of {rover.max_slope_deg:.0f} deg. Traversable but not nominal.")
    if hazard_frac > 0:
        warnings.append(
            f"{hazard_frac * 100:.1f}% of the route lies in hazard-class terrain.")

    # Recommended speed: the slowest the vehicle must go anywhere on the route.
    # Commanding the mean would exceed the limit at the hardest point.
    recommended = float(np.min(v))

    # ── Craters ─────────────────────────────────────────────────────────
    crossed, avoided = [], []
    if crater_index is not None and latlon_of is not None:
        seen = set()
        # Sample along the path rather than every cell — adjacent cells return
        # the same craters and the query is the expensive part.
        step = max(1, len(path) // 60)
        for idx in range(0, len(path), step):
            la, lo = latlon_of(*path[idx])
            for c in crater_index.containing(la, lo)[:4]:
                if c.id in seen:
                    continue
                seen.add(c.id)
                crossed.append({"id": c.id, "diameter_km": round(c.diameter_km, 3),
                                "lat": round(c.lat, 4), "lon": round(c.lon, 4),
                                "class": c.class_label})
        # Craters near the corridor that the route does not enter.
        mid = len(path) // 2
        la, lo = latlon_of(*path[mid])
        for c in crater_index.query(south=la - 0.15, north=la + 0.15,
                                    west=lo - 0.6, east=lo + 0.6,
                                    min_diameter_km=0.5, limit=40):
            if c.id not in seen:
                avoided.append({"id": c.id,
                                "diameter_km": round(c.diameter_km, 3),
                                "lat": round(c.lat, 4), "lon": round(c.lon, 4),
                                "class": c.class_label})
        avoided = avoided[:20]

    return PathMetrics(
        distance_m=distance, ground_distance_m=ground_distance,
        straight_line_m=straight,
        detour_ratio=(distance / straight) if straight > 0 else 1.0,
        waypoints=len(path),
        time_s=time_s, mean_speed_ms=mean_speed, min_speed_ms=float(v.min()),
        recommended_speed_ms=recommended, energy_j=float(energy),
        climb_m=climb, descent_m=descent,
        elev_min_m=float(z.min()), elev_max_m=float(z.max()),
        elev_mean_m=float(z.mean()),
        slope_mean_deg=float(s.mean()), slope_max_deg=float(s.max()),
        slope_p90_deg=float(np.percentile(s, 90)),
        risk_mean=float(rk.mean()), risk_max=float(rk.max()),
        hazard_fractions=fractions, safety_score=score, slope_margin=margin,
        limiting_factor=limiting,
        craters_crossed=crossed, craters_avoided=avoided,
        baseline_m=float(cell_m), rover=rover.key, warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _self_test() -> int:
    from ..analysis.hazard import HAZARD_CLASSES, analyse_traversability
    from ..config import ROVER_PROFILES

    npass = nfail = 0

    def check(name, ok, detail=""):
        nonlocal npass, nfail
        if ok:
            npass += 1
            print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
        else:
            nfail += 1
            print(f"  FAIL  {name}   {detail}")

    print("\nPath metrics on synthetic terrain\n")
    rover = ROVER_PROFILES["viper"]
    n = 60
    yy, xx = np.mgrid[0:n, 0:n].astype(float)

    # A gentle ramp: 100 m of climb across 60 cells of 10 m.
    z = xx * (100.0 / n)
    tm = analyse_traversability(z, 10.0, rover="viper")

    path = [(30, c) for c in range(5, 55)]
    m = evaluate_path(path, elevation=z, slope_deg=tm.slope_deg, risk=tm.risk,
                      hazard=tm.hazard, speed_ms=tm.speed_ms, cell_m=10.0,
                      rover=rover, hazard_classes=HAZARD_CLASSES)

    ground = 49 * 10.0
    check(f"ground distance {m.ground_distance_m:.1f} m",
          abs(m.ground_distance_m - ground) < 1e-6, f"expected {ground}")
    check(f"3-D distance {m.distance_m:.2f} m exceeds ground distance",
          m.distance_m > m.ground_distance_m,
          "a climb lengthens the traverse")

    expect_climb = 49 * (100.0 / n)
    check(f"climb {m.climb_m:.2f} m", abs(m.climb_m - expect_climb) < 1e-6)
    check("no descent on a monotonic ramp", m.descent_m == 0.0)

    check(f"time {m.time_s:.0f} s at ~{m.mean_speed_ms:.3f} m/s",
          m.time_s > 0
          and 0 < m.mean_speed_ms <= rover.nominal_speed_ms * (1 + 1e-9),
          "tolerance because mean speed equals the commanded speed exactly "
          "on terrain that never limits it")
    check("energy is positive and finite",
          0 < m.energy_j < 1e9, f"{m.energy_j / 1000:.1f} kJ")

    # Energy check against the closed form.
    e_expect = (rover.mass_kg * G_MOON * m.climb_m
                + rover.mu_rolling * rover.mass_kg * G_MOON * m.ground_distance_m)
    check("energy matches mgh + mu.mgd", abs(m.energy_j - e_expect) < 1e-6)

    print("\nSafety scoring\n")
    check(f"gentle ramp scores high ({m.safety_score:.1f}/100)",
          m.safety_score > 70, f"limited by: {m.limiting_factor}")

    # A route over a scarp must score far worse even though most of it is fine.
    z2 = xx * (100.0 / n)
    z2[:, 30:33] += np.linspace(0, 45, 3)[None, :]
    tm2 = analyse_traversability(z2, 10.0, rover="viper")
    m2 = evaluate_path(path, elevation=z2, slope_deg=tm2.slope_deg, risk=tm2.risk,
                       hazard=tm2.hazard, speed_ms=tm2.speed_ms, cell_m=10.0,
                       rover=rover, hazard_classes=HAZARD_CLASSES)
    check(f"one scarp collapses the score ({m2.safety_score:.1f}/100)",
          m2.safety_score < m.safety_score * 0.5,
          f"max slope {m2.slope_max_deg:.1f} deg, limited by: {m2.limiting_factor}")
    check("the worst point dominates, not the average",
          m2.slope_mean_deg < rover.max_slope_deg < m2.slope_max_deg,
          f"mean {m2.slope_mean_deg:.1f} deg vs max {m2.slope_max_deg:.1f} deg")
    check("a beyond-limit slope raises a warning",
          any("sustained gradeability" in w for w in m2.warnings))

    print("\nRecommended speed\n")
    check(f"recommended {m2.recommended_speed_ms:.4f} m/s is the slowest on route",
          abs(m2.recommended_speed_ms - m2.min_speed_ms) < 1e-9,
          "commanding the mean would exceed the limit at the hardest point")

    print("\nDetour reporting\n")
    check(f"detour ratio {m.detour_ratio:.3f} >= 1",
          m.detour_ratio >= 1.0 - 1e-9)
    check("planar straight-line fallback is flagged",
          any("planar" in w for w in m.warnings))

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
