"""
Wheel–soil interaction: the physics that decides whether a rover moves.

Why this module exists
----------------------
The mobility model in ``hazard.py`` used a fixed rolling-resistance
coefficient. That is a reasonable placeholder and a poor description of a
planetary rover, because it cannot represent the failure mode that has actually
stranded them. Spirit ended its mission immobilised in soft soil at Troy;
Opportunity spent five weeks trapped in the Purgatory ripple. Neither was
stopped by a slope beyond its gradeability — both were stopped by **slip**,
where the wheels turn and the vehicle does not advance.

Slip is not a small correction. On loose regolith it rises non-linearly with
slope, and the operational limit is reached well before the geometric one: a
vehicle rated to 25° may be immobile at 15° if the soil is weak. Planning a
traverse on slope alone therefore certifies routes that cannot be driven.

The model
---------
Three classical relationships, in the form used for planetary rover analysis.

**1. Bekker pressure–sinkage.** Contact pressure required to sink a plate of
width *b* to depth *z*:

.. math:: p = \\left(\\frac{k_c}{b} + k_\\varphi\\right) z^{\\,n}

**2. Mohr–Coulomb shear strength.** The maximum shear a soil can carry under
normal stress :math:`\\sigma`:

.. math:: \\tau_{\\max} = c + \\sigma\\tan\\varphi

**3. Janosi–Hanamoto shear displacement.** Shear stress does not reach its
maximum instantly; it develops with slip displacement *j*:

.. math:: \\tau(j) = \\tau_{\\max}\\left(1 - e^{-j/K}\\right)

Integrating (3) along a wheel's contact patch gives the tractive force as a
function of slip ratio, which is what closes the loop: a demanded drawbar pull
implies a slip, and a slip implies a real speed.

Lunar regolith parameters
-------------------------
Values are Apollo-derived, from the Lunar Sourcebook, with the Chang'e-4 range
quoted for comparison because it is the best modern in-situ constraint. Where
sources disagree the conservative end is used — an optimistic soil model
produces optimistic routes, and the consequence of that error is a stranded
vehicle rather than a slower one.

References
----------
Bekker, M. G. (1969), *Introduction to Terrain–Vehicle Systems*, Univ. of
    Michigan Press.
Janosi, Z. & Hanamoto, B. (1961), "The analytical determination of drawbar pull
    as a function of slip for tracked vehicles", Proc. 1st Int. Conf. ISTVS.
Wong, J. Y. & Reece, A. R. (1967), "Prediction of rigid wheel performance based
    on the analysis of soil–wheel stresses", J. Terramechanics 4(1), 81–98.
Carrier, W. D., Olhoeft, G. R. & Mendell, W. (1991), "Physical properties of
    the lunar surface", in *Lunar Sourcebook*, ch. 9, Cambridge Univ. Press.
Ding, L. et al. (2011), "Experimental study and analysis on driving wheels'
    performance for planetary exploration rovers moving in deformable soil",
    J. Terramechanics 48(1), 27–45.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..config import G_MOON, RoverProfile

__all__ = [
    "SoilModel", "LUNAR_REGOLITH", "LUNAR_REGOLITH_WEAK", "SOIL_MODELS",
    "slip_ratio", "tractive_coefficient", "max_slope_by_slip",
    "operational_slope_limit", "sinkage", "effective_speed", "SlipResult",
    "SlipTable", "slip_table",
]


# ---------------------------------------------------------------------------
# Soil
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SoilModel:
    """Mechanical properties of a regolith."""

    name: str
    cohesion_pa: float          # c
    friction_deg: float         # phi
    density_kgm3: float
    k_c: float                  # Bekker cohesive modulus  [N/m^(n+1)]
    k_phi: float                # Bekker frictional modulus [N/m^(n+2)]
    n: float                    # Bekker sinkage exponent
    shear_modulus_m: float      # K, Janosi-Hanamoto shear deformation modulus
    source: str


#: Nominal Apollo-derived lunar regolith, 0–15 cm depth.
#: Carrier et al. (1991), Lunar Sourcebook ch. 9.
LUNAR_REGOLITH = SoilModel(
    name="Lunar regolith (Apollo nominal)",
    cohesion_pa=520.0,
    friction_deg=42.0,
    density_kgm3=1600.0,
    k_c=1400.0,
    k_phi=820_000.0,
    n=1.0,
    shear_modulus_m=0.018,
    source="Carrier, Olhoeft & Mendell (1991), Lunar Sourcebook ch. 9",
)

#: Weak-soil case. Chang'e-4 in-situ estimates span phi = 21.5–42.0 deg with
#: cohesion 520–3154 Pa; the low-friction end is used here because that is the
#: condition under which a rover becomes immobilised, and a traverse that is
#: safe only for strong soil is not a safe traverse.
LUNAR_REGOLITH_WEAK = SoilModel(
    name="Lunar regolith (weak / low-friction case)",
    cohesion_pa=250.0,
    friction_deg=25.0,
    density_kgm3=1400.0,
    k_c=900.0,
    k_phi=400_000.0,
    n=1.1,
    shear_modulus_m=0.025,
    source="Low-friction bound after Chang'e-4 in-situ estimates",
)

#: Selectable by key from an API or the UI.
SOIL_MODELS: dict[str, SoilModel] = {
    "nominal": LUNAR_REGOLITH,
    "weak": LUNAR_REGOLITH_WEAK,
}


# ---------------------------------------------------------------------------
# Wheel geometry helpers
# ---------------------------------------------------------------------------

def _contact_length(rover: RoverProfile, z: float) -> float:
    """Chord length of the wheel–soil contact patch at sinkage *z*.

    Geometry only: for a rigid wheel of radius *r* sunk to depth *z*, the
    contact arc subtends :math:`\\arccos(1 - z/r)` and its chord is
    :math:`2\\sqrt{2rz - z^2}`. A longer patch spreads the load and, in the
    Janosi–Hanamoto integral, allows more shear displacement to develop — which
    is why a sinking wheel can generate more thrust right up until sinkage
    itself becomes the problem.
    """
    r = rover.wheel_diameter_m / 2.0
    z = max(min(z, r * 0.9), 1e-6)
    return 2.0 * math.sqrt(max(2.0 * r * z - z * z, 1e-12))


def sinkage(rover: RoverProfile, soil: SoilModel = LUNAR_REGOLITH,
            n_wheels: int = 4, width_m: float | None = None) -> float:
    r"""Static wheel sinkage from Bekker's pressure–sinkage relation.

    Inverting :math:`p = (k_c/b + k_\varphi) z^n` for *z* at the pressure the
    vehicle actually applies:

    .. math:: z = \left(\frac{p}{k_c/b + k_\varphi}\right)^{1/n}

    Lunar gravity enters through the load: the same vehicle presses six times
    less hard than on Earth, which is why lunar rovers sink centimetres where a
    terrestrial vehicle of equal mass would sink decimetres.
    """
    b = width_m if width_m is not None else rover.wheel_diameter_m * 0.4
    load_n = rover.mass_kg * G_MOON / max(n_wheels, 1)

    # Contact area is solved iteratively: pressure sets sinkage, sinkage sets
    # contact length, contact length sets pressure. Three passes converge well
    # inside the uncertainty of the soil parameters themselves.
    z = 0.01
    for _ in range(3):
        area = max(_contact_length(rover, z) * b, 1e-9)
        p = load_n / area
        z = (p / (soil.k_c / b + soil.k_phi)) ** (1.0 / soil.n)
        z = min(z, rover.wheel_diameter_m * 0.45)
    return float(z)


# ---------------------------------------------------------------------------
# Traction
# ---------------------------------------------------------------------------

def tractive_coefficient(slip: float, rover: RoverProfile,
                         soil: SoilModel = LUNAR_REGOLITH,
                         n_wheels: int = 4,
                         width_m: float | None = None) -> float:
    r"""Drawbar-pull coefficient :math:`H/W` available at a given slip ratio.

    Integrating the Janosi–Hanamoto shear law along the contact patch:

    .. math::
        \frac{H}{W} = \left(\frac{cA}{W} + \tan\varphi\right)
                      \left[1 - \frac{K}{i\,L}
                      \left(1 - e^{-i L / K}\right)\right]

    The bracket is the fraction of the soil's Mohr–Coulomb strength actually
    mobilised. At :math:`i \to 0` it vanishes — a wheel that does not slip at
    all generates no thrust — and it approaches unity only as slip becomes
    large. That is the essential trade: traction is *bought* with slip, and
    beyond a point the price is the whole vehicle's progress.
    """
    slip = float(np.clip(slip, 1e-6, 0.999))
    b = width_m if width_m is not None else rover.wheel_diameter_m * 0.4
    z = sinkage(rover, soil, n_wheels, b)
    L = _contact_length(rover, z)
    A = L * b
    W = rover.mass_kg * G_MOON / max(n_wheels, 1)

    tan_phi = math.tan(math.radians(soil.friction_deg))
    max_coeff = (soil.cohesion_pa * A) / W + tan_phi

    K = soil.shear_modulus_m
    x = slip * L / K
    mobilised = 1.0 - (1.0 / x) * (1.0 - math.exp(-x)) if x > 1e-9 else 0.0
    return float(max_coeff * mobilised)


def motion_resistance_coefficient(rover: RoverProfile,
                                  soil: SoilModel = LUNAR_REGOLITH,
                                  n_wheels: int = 4,
                                  width_m: float | None = None) -> float:
    r"""Compaction resistance :math:`R/W`, from the work of making a rut.

    .. math:: R = \frac{b\,(k_c/b + k_\varphi)\,z^{\,n+1}}{n+1}

    This is the energy spent compressing soil the wheel then rolls out of —
    the dominant resistance on loose regolith, and the physical quantity that a
    fixed rolling-resistance coefficient stands in for.
    """
    b = width_m if width_m is not None else rover.wheel_diameter_m * 0.4
    z = sinkage(rover, soil, n_wheels, b)
    W = rover.mass_kg * G_MOON / max(n_wheels, 1)
    R = b * (soil.k_c / b + soil.k_phi) * z ** (soil.n + 1.0) / (soil.n + 1.0)
    return float(R / W)


@dataclass
class SlipResult:
    slip: float                 # 0-1
    demanded: float             # DP/W required
    available: float            # H/W at that slip
    resistance: float           # R/W
    sinkage_m: float
    immobilised: bool
    regime: str                 # nominal | elevated | severe | immobilised


#: Slip regimes. MER and MSL operations treat sustained slip above roughly
#: 60 % as grounds to abort a drive; below about 20 % is routine. The
#: boundaries here follow that operational practice rather than a physical
#: threshold, because it is a decision rule, not a property of the soil.
SLIP_NOMINAL = 0.20
SLIP_ELEVATED = 0.40
SLIP_SEVERE = 0.60


def slip_ratio(slope_deg, rover: RoverProfile,
               soil: SoilModel = LUNAR_REGOLITH,
               n_wheels: int = 4) -> SlipResult:
    r"""Slip required to climb a slope, or immobilisation if none suffices.

    Force balance along the slope, per unit weight:

    .. math:: \frac{DP}{W} = \sin\theta + \frac{R}{W}\cos\theta

    The vehicle must generate that much drawbar pull. Since available thrust
    rises monotonically with slip, the equilibrium slip is found by bisection.
    If even :math:`i \to 1` cannot meet the demand the wheels spin without
    advancing, which is immobilisation — and it is reported as such rather than
    as a very slow traverse.
    """
    th = math.radians(float(slope_deg))
    R_W = motion_resistance_coefficient(rover, soil, n_wheels)
    demanded = math.sin(th) + R_W * math.cos(th)
    z = sinkage(rover, soil, n_wheels)

    # Simplified downhill case: when gravity assistance exceeds resistance,
    # no positive tractive demand is required. This model does NOT calculate
    # braking force, wheel lock, or a safe descent-speed limit.
    if demanded <= 0:
        return SlipResult(0.0, demanded,
                          tractive_coefficient(0.05, rover, soil, n_wheels),
                          R_W, z, False, "nominal")

    hi = tractive_coefficient(0.99, rover, soil, n_wheels)
    if hi < demanded:
        return SlipResult(1.0, demanded, hi, R_W, z, True, "immobilised")

    lo_i, hi_i = 1e-4, 0.99
    for _ in range(60):
        mid = 0.5 * (lo_i + hi_i)
        if tractive_coefficient(mid, rover, soil, n_wheels) < demanded:
            lo_i = mid
        else:
            hi_i = mid
    i = 0.5 * (lo_i + hi_i)

    regime = ("nominal" if i <= SLIP_NOMINAL else
              "elevated" if i <= SLIP_ELEVATED else
              "severe" if i <= SLIP_SEVERE else "immobilised")
    return SlipResult(float(i), demanded,
                      tractive_coefficient(i, rover, soil, n_wheels),
                      R_W, z, i > SLIP_SEVERE, regime)


#: Upper bound of the gradeability search. Chosen well above any wheeled
#: vehicle's static stability limit so that the bound is never the answer: a
#: search capped at 45° silently returns 45° for every rover whose traction
#: limit exceeds it, which looks like a result and is not one.
_GRADE_SEARCH_MAX_DEG = 70.0


def max_slope_by_slip(rover: RoverProfile, soil: SoilModel = LUNAR_REGOLITH,
                      slip_limit: float = SLIP_SEVERE,
                      n_wheels: int = 4) -> float:
    """Steepest slope climbable without exceeding a slip limit.

    This is the *traction* gradeability. On weak soil it falls below the
    vehicle's geometric limit, and then it — not the tip-over angle — is what
    bounds a planned route. On strong soil it can exceed the tip-over angle, in
    which case geometry binds instead; :func:`operational_slope_limit` returns
    whichever applies.
    """
    lo, hi = 0.0, _GRADE_SEARCH_MAX_DEG
    if slip_ratio(hi, rover, soil, n_wheels).slip <= slip_limit:
        return float(hi)          # traction never binds below the search bound
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if slip_ratio(mid, rover, soil, n_wheels).slip <= slip_limit:
            lo = mid
        else:
            hi = mid
    return float(0.5 * (lo + hi))


def operational_slope_limit(rover: RoverProfile, soil: SoilModel = LUNAR_REGOLITH,
                            slip_limit: float = SLIP_SEVERE,
                            n_wheels: int = 4) -> tuple[float, str]:
    """The slope that actually bounds a traverse, and which effect sets it.

    Returns ``(degrees, "traction" | "stability")``. Reporting the binding
    mechanism alongside the number matters operationally: a traction limit can
    be relaxed by choosing a firmer route, a stability limit cannot.
    """
    traction = max_slope_by_slip(rover, soil, slip_limit, n_wheels)
    if traction <= rover.tip_over_slope_deg:
        return traction, "traction"
    return float(rover.tip_over_slope_deg), "stability"


def effective_speed(slope_deg, rover: RoverProfile,
                    soil: SoilModel = LUNAR_REGOLITH,
                    n_wheels: int = 4) -> tuple[float, SlipResult]:
    r"""Ground speed after slip losses.

    Slip is defined as :math:`i = 1 - v_\text{actual}/(\omega r)`, so the
    vehicle advances at :math:`(1-i)` times its commanded speed. A rover
    driving at 0.2 m/s with 40 % slip is covering ground at 0.12 m/s while its
    odometry, if uncorrected, still reports 0.2 — which is how a traverse can
    silently fall behind schedule and how dead-reckoned position drifts.

    Power is applied on top of that: the implemented power term uses
    max(sin(theta), 0), so downhill gravity assistance is not credited when
    computing the power-limited speed. Negative slopes can trigger the simple
    zero-traction-demand branch in :func:`slip_ratio`, but this function is
    NOT a direction-aware downhill braking or stability model. It does not
    establish a safe descent speed. Papers must describe this as a simplified
    slope-based speed proxy unless a separate validated descent model is used.
    """
    s = slip_ratio(slope_deg, rover, soil, n_wheels)
    if s.immobilised:
        return 0.0, s

    th = math.radians(float(slope_deg))
    force = rover.mass_kg * G_MOON * (max(math.sin(th), 0.0)
                                      + s.resistance * math.cos(th))
    v_power = rover.propulsion_power_w / max(force, 1e-6)
    v_cmd = min(rover.nominal_speed_ms, v_power)
    return float(max(v_cmd * (1.0 - s.slip), 0.0)), s


# ---------------------------------------------------------------------------
# Vectorised slip over a raster
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SlipTable:
    """Slip as a function of slope, tabulated once and interpolated.

    :func:`slip_ratio` bisects sixty times per call, which is fine for a single
    slope and unusable for the hundreds of thousands of cells in a DEM window.
    Slip depends only on slope once the rover, soil and wheel count are fixed,
    so a one-dimensional table is not an approximation of the physics — only of
    the sampling, and at 0.1° spacing that error is far below the spread of the
    soil parameters themselves.
    """

    slope_deg: np.ndarray        # monotone grid, ascending
    slip: np.ndarray             # slip at each grid slope, 0-1
    immobilised_deg: float       # first slope at which no slip suffices
    sinkage_m: float
    resistance: float            # R/W, constant for flat-ish sinkage
    rover_key: str
    soil_name: str

    def __call__(self, slope_deg) -> np.ndarray:
        """Slip for an array of slopes. Above the table it stays immobilised."""
        s = np.asarray(slope_deg, dtype=np.float64)
        return np.interp(s, self.slope_deg, self.slip,
                         left=float(self.slip[0]), right=float(self.slip[-1]))

    def is_immobilised(self, slope_deg) -> np.ndarray:
        return np.asarray(slope_deg, dtype=np.float64) >= self.immobilised_deg

    def max_slope(self, slip_limit: float = SLIP_SEVERE) -> float:
        """Steepest tabulated slope whose slip stays within a limit."""
        ok = self.slip <= slip_limit
        if not ok.any():
            return 0.0
        return float(self.slope_deg[np.flatnonzero(ok)[-1]])


_SLIP_TABLES: dict[tuple, SlipTable] = {}


def slip_table(rover: RoverProfile, soil: SoilModel = LUNAR_REGOLITH,
               n_wheels: int = 4, *, lo_deg: float = -30.0,
               hi_deg: float = 50.0, step_deg: float = 0.1) -> SlipTable:
    """Build (and cache) the slip curve for one rover on one soil.

    Cached because a traversability run calls it once per window and the curve
    depends on nothing that varies within a run.
    """
    key = (rover.key, soil.name, n_wheels, lo_deg, hi_deg, step_deg)
    hit = _SLIP_TABLES.get(key)
    if hit is not None:
        return hit

    grid = np.arange(lo_deg, hi_deg + 0.5 * step_deg, step_deg)
    slips = np.empty(grid.size, dtype=np.float64)
    immob = float("inf")
    z = res = 0.0

    for i, deg in enumerate(grid):
        r = slip_ratio(float(deg), rover, soil, n_wheels)
        slips[i] = r.slip
        if i == 0:
            z, res = r.sinkage_m, r.resistance
        if r.immobilised and immob == float("inf"):
            immob = float(deg)

    # Slip must not decrease with slope; bisection noise near the immobilisation
    # knee can produce a 1e-9 dip that would otherwise survive into the raster.
    slips = np.maximum.accumulate(slips)

    tab = SlipTable(grid, slips, immob, z, res, rover.key, soil.name)
    _SLIP_TABLES[key] = tab
    return tab


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _self_test() -> int:
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

    v = ROVER_PROFILES["viper"]

    print("\nSinkage — Bekker pressure-sinkage\n")
    z_nom = sinkage(v, LUNAR_REGOLITH)
    z_weak = sinkage(v, LUNAR_REGOLITH_WEAK)
    print(f"    nominal regolith : {z_nom * 100:.2f} cm")
    print(f"    weak regolith    : {z_weak * 100:.2f} cm")
    check("sinkage is centimetre-scale on nominal regolith",
          0.001 < z_nom < 0.10, f"{z_nom*100:.2f} cm")
    check("weak soil gives deeper sinkage", z_weak > z_nom,
          f"{z_weak*100:.2f} vs {z_nom*100:.2f} cm")

    print("\nTraction develops with slip (Janosi-Hanamoto)\n")
    prev = -1.0
    for i in (0.02, 0.05, 0.1, 0.2, 0.4, 0.6, 0.9):
        h = tractive_coefficient(i, v, LUNAR_REGOLITH)
        print(f"    slip {i:>4.0%}  ->  H/W = {h:.3f}")
        if h <= prev:
            check("traction rises monotonically with slip", False)
            break
        prev = h
    else:
        check("traction rises monotonically with slip", True)
    check("no thrust without slip",
          tractive_coefficient(1e-6, v, LUNAR_REGOLITH) < 0.01,
          "a wheel that does not slip generates no drawbar pull")

    print("\nSlip against slope — the operational limit\n")
    print(f"    {'slope':>6}{'slip':>9}{'regime':>14}{'speed':>10}")
    print("    " + "-" * 40)
    for deg in (0, 5, 10, 15, 20, 25, 30):
        sp, s = effective_speed(deg, v, LUNAR_REGOLITH)
        print(f"    {deg:>5}°{s.slip:>8.1%}{s.regime:>14}{sp:>9.3f} m/s")

    s5 = slip_ratio(5, v, LUNAR_REGOLITH)
    s25 = slip_ratio(25, v, LUNAR_REGOLITH)
    check("slip increases with slope", s25.slip > s5.slip,
          f"{s5.slip:.1%} at 5° -> {s25.slip:.1%} at 25°")
    check("gentle slopes stay in the nominal regime", s5.regime == "nominal")

    print("\nWhich constraint binds — traction or geometry?\n")
    print(f"    {'rover':<10}{'tip-over':>10}{'traction':>10}{'traction':>10}"
          f"{'binds on':>12}{'binds on':>12}")
    print(f"    {'':<10}{'(geom)':>10}{'(nominal)':>10}{'(weak)':>10}"
          f"{'nominal':>12}{'weak':>12}")
    print("    " + "-" * 64)
    for key in ("pragyan", "yutu2", "viper", "lrv"):
        r = ROVER_PROFILES[key]
        tn = max_slope_by_slip(r, LUNAR_REGOLITH)
        tw = max_slope_by_slip(r, LUNAR_REGOLITH_WEAK)
        _, bn = operational_slope_limit(r, LUNAR_REGOLITH)
        _, bw = operational_slope_limit(r, LUNAR_REGOLITH_WEAK)
        print(f"    {key:<10}{r.tip_over_slope_deg:>9.1f}°{tn:>9.1f}°"
              f"{tw:>9.1f}°{bn:>12}{bw:>12}")

    nom = max_slope_by_slip(v, LUNAR_REGOLITH)
    weak = max_slope_by_slip(v, LUNAR_REGOLITH_WEAK)
    check("weak soil lowers the climbable slope", weak < nom,
          f"{weak:.1f}° vs {nom:.1f}° — soil strength, not geometry, can bind")
    check("on weak soil traction binds below the tip-over limit",
          weak < v.tip_over_slope_deg,
          f"{weak:.1f}° vs a {v.tip_over_slope_deg:.0f}° tip-over limit")
    check("on nominal soil geometry binds instead",
          operational_slope_limit(v, LUNAR_REGOLITH)[1] == "stability",
          f"traction allows {nom:.1f}°, past the {v.tip_over_slope_deg:.0f}° tip-over limit")

    # A search bounded at 45 deg returned 45.0 for every rover whose traction
    # limit lay above it, which read as a result. Guard against reintroducing it.
    check("the gradeability search bound is not mistaken for an answer",
          len({round(max_slope_by_slip(ROVER_PROFILES[k], LUNAR_REGOLITH), 1)
               for k in ("pragyan", "yutu2", "viper", "lrv")}) == 4,
          "four rovers, four distinct traction limits")

    over = [(k, ROVER_PROFILES[k].tip_over_slope_deg /
             max_slope_by_slip(ROVER_PROFILES[k], LUNAR_REGOLITH_WEAK))
            for k in ("pragyan", "yutu2", "viper", "lrv")]
    check("the geometric limit over-certifies on weak soil",
          all(f > 1.5 for _, f in over),
          "by " + ", ".join(f"{f:.2f}x ({k})" for k, f in over))

    print("\nSlip losses in speed\n")
    v0, _ = effective_speed(0, v, LUNAR_REGOLITH)
    v20, s20 = effective_speed(20, v, LUNAR_REGOLITH)
    check(f"speed falls with slope ({v0:.3f} -> {v20:.3f} m/s)", v20 < v0)
    check("advance equals commanded speed times (1 - slip)",
          abs(v20 - min(v.nominal_speed_ms,
                        v.propulsion_power_w /
                        (v.mass_kg * G_MOON *
                         (math.sin(math.radians(20)) +
                          s20.resistance * math.cos(math.radians(20)))))
              * (1 - s20.slip)) < 1e-9)

    print("\nVehicle comparison on identical soil\n")
    print(f"    {'rover':<28}{'sinkage':>9}{'max slope':>11}")
    print("    " + "-" * 48)
    for key in ("pragyan", "viper", "lrv"):
        r = ROVER_PROFILES[key]
        print(f"    {r.name[:27]:<28}{sinkage(r)*100:>8.2f}cm"
              f"{max_slope_by_slip(r):>10.1f}°")

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
