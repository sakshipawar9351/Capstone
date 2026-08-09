"""
Traversability: turning topography into hazard, risk and cost.

What this module produces
-------------------------
From an elevation window it derives four rasters:

``slope``        gradient magnitude in degrees, at the grid's own baseline
``hazard``       a categorical verdict per cell, from a rover's mobility limits
``risk``         a continuous 0-1 score combining slope, roughness and margin
``cost``         seconds to cross a cell, which is what a planner minimises

The separation matters. Hazard is a hard constraint — a 30° slope is impassable
to a VIPER-class rover whatever else is true. Risk is a soft preference, letting
a planner choose between two legal routes. Cost is the objective function.
Collapsing them into one number would make the planner unable to distinguish
"illegal" from "merely unpleasant".

Scale
-----
Every output is tagged with the baseline it was computed over, because slope is
meaningless without it. At the 10 m posting of the LOLA polar DEM these results
describe terrain a rover could realistically respond to; at the 474 m posting of
the global grid they describe the shape of a region, not the safety of a route.
The same code produces both, and only the baseline tells them apart.

References
----------
Horn, B. K. P. (1981), "Hill shading and the reflectance map", Proc. IEEE 69(1),
    14-47. doi:10.1109/PROC.1981.11918 — the slope operator.
Riley, S. J. et al. (1999), "A terrain ruggedness index...", Intermountain
    Journal of Sciences 5, 23-27 — the roughness measure.
Wilcox, B. H. et al. (2007), "ATHLETE: A cargo handling and manipulation robot",
    J. Field Robotics 24, 421-434 — slope limits for wheeled planetary vehicles.
Rover mobility limits are taken per-vehicle from ``config.ROVER_PROFILES``;
their provenance is documented there.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import G_MOON, ROVER_PROFILES, RoverProfile
from .terrain import roughness as _roughness
from .terrain import slope_aspect, terrain_ruggedness_index

__all__ = [
    "HazardClass", "HAZARD_CLASSES", "TraversabilityMap",
    "analyse_traversability",
]


# ---------------------------------------------------------------------------
# Hazard classification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HazardClass:
    key: str
    label: str
    code: int
    colour: str
    meaning: str


#: Ordered from safest to impassable. The thresholds are expressed as fractions
#: of a specific rover's limits rather than absolute angles, so the same scheme
#: applies to a 26 kg Pragyan and a 700 kg crewed LRV without rewriting it.
HAZARD_CLASSES: tuple[HazardClass, ...] = (
    HazardClass("clear", "Clear", 0, "#35c48a",
                "Below half the sustained slope limit; nominal driving"),
    HazardClass("caution", "Caution", 1, "#9ccc4f",
                "Within the sustained limit but not comfortably so"),
    HazardClass("marginal", "Marginal", 2, "#e9c46a",
                "At the sustained gradeability limit; slow, power-hungry"),
    HazardClass("hazard", "Hazard", 3, "#e07a5a",
                "Beyond sustained capability, below tip-over; escape only"),
    HazardClass("impassable", "Impassable", 4, "#c1352b",
                "Exceeds static stability, or data is missing"),
)

_BY_CODE = {h.code: h for h in HAZARD_CLASSES}


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class TraversabilityMap:
    """Derived rasters plus the assumptions that produced them."""

    slope_deg: np.ndarray
    aspect_deg: np.ndarray
    roughness_m: np.ndarray
    tri_m: np.ndarray
    hazard: np.ndarray            # int8, HazardClass.code
    risk: np.ndarray              # float, 0-1
    cost_s: np.ndarray            # seconds to traverse one cell
    speed_ms: np.ndarray          # achievable speed per cell

    baseline_m: float
    rover: RoverProfile
    risk_aversion: float
    valid: np.ndarray             # cells with usable elevation

    warnings: list[str] = field(default_factory=list)

    # -- summaries -------------------------------------------------------

    def class_fractions(self) -> dict[str, float]:
        tot = int(self.valid.sum())
        if tot == 0:
            return {h.key: 0.0 for h in HAZARD_CLASSES}
        out = {}
        for h in HAZARD_CLASSES:
            n = int(((self.hazard == h.code) & self.valid).sum())
            out[h.key] = round(n / tot, 5)
        return out

    def stats(self) -> dict:
        s = self.slope_deg[self.valid]
        r = self.risk[self.valid]
        passable = self.hazard < HAZARD_CLASSES[-1].code
        return {
            "baseline_m": round(self.baseline_m, 3),
            "rover": self.rover.key,
            "risk_aversion": self.risk_aversion,
            "cells": int(self.valid.size),
            "valid_cells": int(self.valid.sum()),
            "slope_deg": {
                "mean": round(float(s.mean()), 3),
                "median": round(float(np.median(s)), 3),
                "p90": round(float(np.percentile(s, 90)), 3),
                "p99": round(float(np.percentile(s, 99)), 3),
                "max": round(float(s.max()), 3),
            },
            "risk": {
                "mean": round(float(r.mean()), 4),
                "p90": round(float(np.percentile(r, 90)), 4),
            },
            "passable_fraction": round(
                float((passable & self.valid).sum() / max(self.valid.sum(), 1)), 5),
            "classes": self.class_fractions(),
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Mobility model
# ---------------------------------------------------------------------------

def achievable_speed(slope_deg, rover: RoverProfile) -> np.ndarray:
    r"""Speed a rover can sustain on a given grade.

    Two limits act together, and the lower one wins:

    **Commanded speed.** Planetary rovers are driven far below their mechanical
    maximum for hazard-avoidance reasons, so ``nominal_speed_ms`` is the ceiling
    on level ground regardless of available power.

    **Power.** Climbing costs traction force against gravity plus rolling
    resistance:

    .. math::
        F = m g (\sin\theta + \mu_r \cos\theta)
        \qquad
        v_{\max} = P / F

    Descending is not treated as free: below about −5° the limit becomes
    braking control rather than propulsion, so speed is capped rather than
    allowed to grow without bound. A model that let a rover accelerate downhill
    would produce paths that prefer plunging into craters.

    Lunar gravity (1.625 m/s²) makes the gravitational term about six times
    smaller than on Earth, which is why slopes that would stop a terrestrial
    vehicle remain drivable — and why rolling resistance in loose regolith,
    not gravity, is usually the binding constraint.
    """
    th = np.radians(np.asarray(slope_deg, dtype=np.float64))
    climb = np.maximum(np.sin(th), 0.0)          # descent gives no free power
    force = rover.mass_kg * G_MOON * (climb + rover.mu_rolling * np.cos(th))
    force = np.maximum(force, 1e-6)

    v_power = rover.propulsion_power_w / force
    v = np.minimum(v_power, rover.nominal_speed_ms)

    # On steep descents control, not propulsion, sets the pace.
    steep_down = np.radians(-5.0)
    v = np.where(th < steep_down, np.minimum(v, rover.nominal_speed_ms * 0.6), v)
    return np.maximum(v, 1e-4)


def classify_hazard(slope_deg, valid, rover: RoverProfile) -> np.ndarray:
    """Assign each cell a hazard class from the rover's own limits."""
    s = np.asarray(slope_deg, dtype=np.float64)
    lim = rover.max_slope_deg
    tip = rover.tip_over_slope_deg

    out = np.full(s.shape, HAZARD_CLASSES[0].code, dtype=np.int8)
    out[s >= 0.5 * lim] = 1        # caution
    out[s >= 0.85 * lim] = 2       # marginal
    out[s >= lim] = 3              # hazard: past sustained capability
    out[s >= tip] = 4              # impassable: past static stability
    out[~valid] = 4                # unknown terrain is not assumed safe
    return out


def compute_risk(slope_deg, roughness_m, valid, rover: RoverProfile) -> np.ndarray:
    r"""Continuous 0-1 hazard likelihood.

    .. math::
        R = 1 - (1 - r_\text{slope})(1 - r_\text{rough})

    Combining the terms this way — rather than averaging — treats them as
    independent ways to get stuck: a cell that is safe on slope but rough is
    still risky, and averaging would dilute that. The form is the standard
    probability of at least one of two independent events.

    The slope term is squared because consequence grows faster than angle:
    twice the grade is much more than twice the hazard once wheels begin to
    slip. The roughness term is scaled by ground clearance, since a boulder
    field matters relative to what the chassis can straddle.
    """
    s = np.asarray(slope_deg, dtype=np.float64)
    g = np.asarray(roughness_m, dtype=np.float64)

    r_slope = np.clip(s / max(rover.tip_over_slope_deg, 1e-6), 0.0, 1.0) ** 2
    r_rough = np.clip(g / max(rover.ground_clearance_m * 8.0, 1e-6), 0.0, 1.0)

    risk = 1.0 - (1.0 - r_slope) * (1.0 - r_rough)
    risk[~valid] = 1.0
    return np.clip(risk, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def analyse_traversability(elevation: np.ndarray, cell_m: float, *,
                           rover: str | RoverProfile = "viper",
                           risk_aversion: float = 2.0,
                           roughness_window: int = 3) -> TraversabilityMap:
    """Full traversability analysis of an elevation window.

    ``cell_m`` is the ground spacing. For the polar stereographic grids this is
    effectively constant, unlike the cylindrical grids where it varies with
    latitude — which is why this function takes a scalar and the cylindrical
    path passes a per-row array to :func:`slope_aspect` instead.

    ``risk_aversion`` (gamma) scales how much risk inflates cost:

    .. math:: C = \\frac{d}{v(\\theta)} \\, (1 + \\gamma R)

    At gamma = 0 the planner minimises time and will drive anywhere legal. As
    gamma grows it trades time for margin. It is exposed rather than fixed
    because the right value is a mission decision, not a physical constant.
    """
    prof = ROVER_PROFILES[rover] if isinstance(rover, str) else rover
    z = np.asarray(elevation, dtype=np.float64)
    warnings: list[str] = []

    valid = np.isfinite(z)
    if not valid.any():
        raise ValueError("elevation window contains no valid data")
    if valid.mean() < 0.98:
        warnings.append(
            f"{(1 - valid.mean()) * 100:.1f}% of cells have no elevation data; "
            "they are treated as impassable rather than interpolated.")

    # Fill gaps for differentiation only — the mask still marks them invalid,
    # so no filled value ever reaches the output.
    zf = z.copy()
    if not valid.all():
        zf[~valid] = np.nanmedian(z[valid])

    slope, aspect = slope_aspect(zf, cell_m, cell_m)
    rough = _roughness(zf, roughness_window)
    tri = terrain_ruggedness_index(zf)

    hazard = classify_hazard(slope, valid, prof)
    risk = compute_risk(slope, rough, valid, prof)
    speed = achievable_speed(slope, prof)

    # Cost is time, inflated by risk. Impassable cells get infinity so a
    # planner excludes them structurally rather than merely disliking them.
    cost = (cell_m / speed) * (1.0 + risk_aversion * risk)
    cost[hazard >= HAZARD_CLASSES[-1].code] = np.inf

    if cell_m > 100:
        warnings.append(
            f"Baseline is {cell_m:.0f} m. Slope averaged over this distance "
            "cannot represent what a rover wheel meets; these results describe "
            "regional shape, not traverse safety.")

    return TraversabilityMap(
        slope_deg=slope, aspect_deg=aspect, roughness_m=rough, tri_m=tri,
        hazard=hazard, risk=risk, cost_s=cost, speed_ms=speed,
        baseline_m=float(cell_m), rover=prof, risk_aversion=float(risk_aversion),
        valid=valid, warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _self_test() -> int:
    npass = nfail = 0

    def check(name, ok, detail=""):
        nonlocal npass, nfail
        if ok:
            npass += 1
            print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
        else:
            nfail += 1
            print(f"  FAIL  {name}   {detail}")

    print("\nMobility model\n")
    v = ROVER_PROFILES["viper"]

    flat = float(achievable_speed(0.0, v))
    check(f"flat ground -> commanded speed {flat:.3f} m/s",
          abs(flat - v.nominal_speed_ms) < 1e-6)

    for g in (5, 10, 15, 20, 25):
        sp = float(achievable_speed(float(g), v))
        print(f"    {g:>2}° grade -> {sp:.4f} m/s")
    check("speed falls monotonically with grade",
          all(achievable_speed(float(a), v) >= achievable_speed(float(b), v)
              for a, b in zip([0, 5, 10, 15], [5, 10, 15, 20])))
    check("a steep climb is slower than level ground",
          float(achievable_speed(25.0, v)) < flat)

    print("\nHazard classification\n")
    # Thresholds for a VIPER-class rover (sustained 15°, tip-over 35°):
    #   clear < 7.5 <= caution < 12.75 <= marginal < 15 <= hazard < 35 <= impassable
    for deg, want in [(0, "clear"), (9, "caution"), (13, "marginal"),
                      (18, "hazard"), (40, "impassable")]:
        code = int(classify_hazard(np.array([[float(deg)]]),
                                   np.array([[True]]), v)[0, 0])
        got = _BY_CODE[code].key
        check(f"{deg:>2}° -> {got}", got == want, f"expected {want}")

    code = int(classify_hazard(np.array([[0.0]]), np.array([[False]]), v)[0, 0])
    check("missing data is impassable, not assumed clear",
          _BY_CODE[code].key == "impassable")

    print("\nRisk combination\n")
    ok = np.array([[True]])
    R = lambda s, g: float(  # noqa: E731 — local shorthand for readability
        compute_risk(np.array([[s]]), np.array([[g]]), ok, v)[0, 0])
    # 0.5 m of local relief, not 2.0 m: the roughness term saturates at
    # 8x ground clearance (2.0 m for this rover), and a saturated input cannot
    # demonstrate that combination raises risk above either component.
    r_flat, r_slope, r_rough, r_both = R(0.0, 0.0), R(20.0, 0.0), R(0.0, 0.5), R(20.0, 0.5)
    print(f"    flat/smooth {r_flat:.3f}   steep {r_slope:.3f}   "
          f"rough {r_rough:.3f}   both {r_both:.3f}")
    check("flat smooth terrain is zero risk", r_flat < 1e-9)
    check("combined risk exceeds either alone",
          r_both > r_slope and r_both > r_rough,
          f"{r_both:.3f} vs slope {r_slope:.3f}, rough {r_rough:.3f}")
    check("combining is not averaging", r_both > (r_slope + r_rough) / 2)
    check("roughness beyond 8x clearance saturates to certain risk",
          abs(R(0.0, 2.0) - 1.0) < 1e-9,
          "2.0 m local relief vs 0.25 m clearance")

    print("\nSynthetic terrain end-to-end\n")
    n = 120
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    # A ramp crossed by a steep scarp: the planner must be able to tell them
    # apart, which is exactly what a single averaged number cannot do.
    z = xx * 0.3
    z[:, 60:64] += np.linspace(0, 60, 4)[None, :]
    tm = analyse_traversability(z, 10.0, rover="viper")

    st = tm.stats()
    print(f"    baseline {st['baseline_m']} m, "
          f"slope mean {st['slope_deg']['mean']}°, max {st['slope_deg']['max']}°")
    print(f"    passable {st['passable_fraction'] * 100:.1f}%   "
          f"classes {st['classes']}")

    check("ramp is mostly clear", st["classes"]["clear"] > 0.8)
    check("the scarp registers as impassable", st["classes"]["impassable"] > 0.0)
    check("impassable cells have infinite cost",
          np.isinf(tm.cost_s[tm.hazard == 4]).all())
    check("passable cells have finite positive cost",
          np.all(np.isfinite(tm.cost_s[tm.hazard < 4])) and
          np.all(tm.cost_s[tm.hazard < 4] > 0))

    print("\nBaseline honesty\n")
    coarse = analyse_traversability(z, 474.0, rover="viper")
    check("a coarse baseline triggers a warning",
          any("cannot represent" in w for w in coarse.warnings),
          coarse.warnings[0][:60] + "…" if coarse.warnings else "none")
    check("a 10 m baseline does not", not tm.warnings)

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
