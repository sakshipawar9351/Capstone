"""
Crater morphometry measured from topography.

What this module does
---------------------
Given a crater's centre and diameter, it extracts the surrounding DEM, builds a
radial elevation profile, and from that profile measures the quantities a
planetary scientist actually reports: rim crest elevation, floor elevation,
depth, rim height above the surrounding terrain, wall slope, and excavated
volume.  It then compares each measurement against the published depth-diameter
scaling laws, so the reader can see whether this particular crater is fresh,
degraded, or anomalous.

Why a radial profile rather than a simple min/max
-------------------------------------------------
Taking ``max(window) - min(window)`` would be wrong in a way that looks right.
The maximum inside a crater's bounding box is frequently a neighbouring peak or
the rim of an adjacent crater, and the minimum is frequently a small superposed
crater on the floor.  Averaging elevation around concentric rings suppresses
both: azimuthal structure cancels while the radial signature — floor, wall,
rim, ejecta — survives.  This is the standard approach used for LOLA-derived
crater catalogues (Head et al. 2010; Wang et al. 2021).

Resolution honesty
------------------
A crater cannot be measured from a grid that does not resolve it.  Every result
carries ``pixels_across`` and an explicit ``adequacy`` verdict, and measurements
from an under-resolved grid are labelled as such rather than quietly reported.
At LDEM_16's 1895 m/px, a 20 km crater spans only ~10 cells: enough to detect,
not enough to characterise.

References
----------
Pike, R. J. (1974), "Depth/diameter relations of fresh lunar craters:
    Revision from spacecraft data", Geophysical Research Letters 1(7), 291-294.
    doi:10.1029/GL001i007p00291
Pike, R. J. (1977), "Size-dependence in the shape of fresh impact craters on
    the Moon", in Impact and Explosion Cratering, Pergamon, 489-509.
Melosh, H. J. (1989), Impact Cratering: A Geologic Process, Oxford Univ. Press.
Head, J. W. et al. (2010), Science 329, 1504-1507. doi:10.1126/science.1195050
Wang, Y. et al. (2021), JGR Planets 126, e2020JE006728. doi:10.1029/2020JE006728
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..config import (
    PIKE_COMPLEX,
    PIKE_RELATIVE_UNCERTAINTY,
    PIKE_RIM_HEIGHT,
    PIKE_SIMPLE,
    POLAR_CYLINDRICAL_LIMIT_DEG,
    R_MOON_M,
    SIMPLE_COMPLEX_TRANSITION_KM,
)
from ..core import selenographic as sg

__all__ = [
    "CraterMorphometry",
    "analyse_crater",
    "pike_depth_km",
    "pike_rim_height_km",
    "morphological_class",
]


# ---------------------------------------------------------------------------
# Published scaling laws
# ---------------------------------------------------------------------------

def pike_depth_km(diameter_km: float) -> tuple[float, str]:
    r"""Predicted rim-to-floor depth from Pike's depth-diameter fits.

    .. math::
        d = 0.196\,D^{1.010} \quad (\text{simple},\; D < 15\ \mathrm{km})

        d = 1.044\,D^{0.301} \quad (\text{complex},\; D > 15\ \mathrm{km})

    The exponent change at the transition is not a fitting convenience: simple
    craters retain their excavated cavity, so depth grows almost linearly with
    diameter, whereas complex craters collapse under their own weight, and the
    much smaller exponent is the signature of that collapse (Melosh 1989).
    """
    if diameter_km <= 0:
        return float("nan"), "undefined"
    if diameter_km < SIMPLE_COMPLEX_TRANSITION_KM:
        a, b = PIKE_SIMPLE
        return a * diameter_km ** b, "simple"
    a, b = PIKE_COMPLEX
    return a * diameter_km ** b, "complex"


def pike_rim_height_km(diameter_km: float) -> float:
    r"""Predicted rim height above the pre-impact surface.

    .. math:: h_r = 0.036\,D^{1.014}
    """
    a, b = PIKE_RIM_HEIGHT
    return a * diameter_km ** b if diameter_km > 0 else float("nan")


def morphological_class(diameter_km: float) -> tuple[str, str]:
    """Morphological type and the diagnostic feature that defines it."""
    d = diameter_km
    if d < 15:
        return "Simple", "Bowl-shaped cavity; smooth walls, no central peak"
    if d < 50:
        return "Complex", "Terraced walls and a central peak"
    if d < 140:
        return "Complex (peak)", "Well-developed central peak, wide terraces"
    if d < 300:
        return "Peak-ring basin", "Central peak replaced by an interior ring"
    return "Multi-ring basin", "Multiple concentric rings"


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class CraterMorphometry:
    """Everything measurable about one crater, with provenance attached."""

    lat: float
    lon: float
    diameter_km: float

    # Measured from the DEM
    rim_elev_m: float
    floor_elev_m: float
    reference_elev_m: float          # surrounding terrain datum
    depth_m: float                   # rim crest -> floor
    rim_height_m: float              # rim crest -> surrounding terrain
    floor_depth_m: float             # surrounding terrain -> floor
    wall_slope_deg: float
    max_slope_deg: float
    mean_slope_deg: float
    volume_km3: float
    relief_m: float

    # Sampling context
    resolution_m_px: float
    pixels_across: float
    adequacy: str
    slope_baseline_m: float

    # Published comparison
    predicted_depth_m: float
    predicted_regime: str
    depth_ratio: float               # measured / predicted
    predicted_rim_height_m: float
    morph_class: str
    morph_basis: str
    depth_diameter_ratio: float

    profile: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sources: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        r2 = lambda v: None if v is None or not np.isfinite(v) else round(float(v), 2)
        r4 = lambda v: None if v is None or not np.isfinite(v) else round(float(v), 4)
        return {
            "location": {"lat": r4(self.lat), "lon": r4(self.lon)},
            "diameter_km": r4(self.diameter_km),
            "measured": {
                "rim_elevation_m": r2(self.rim_elev_m),
                "floor_elevation_m": r2(self.floor_elev_m),
                "reference_elevation_m": r2(self.reference_elev_m),
                "depth_m": r2(self.depth_m),
                "rim_height_m": r2(self.rim_height_m),
                "floor_depth_m": r2(self.floor_depth_m),
                "relief_m": r2(self.relief_m),
                "wall_slope_deg": r2(self.wall_slope_deg),
                "mean_slope_deg": r2(self.mean_slope_deg),
                "max_slope_deg": r2(self.max_slope_deg),
                "volume_km3": r4(self.volume_km3),
                "depth_diameter_ratio": r4(self.depth_diameter_ratio),
            },
            "predicted": {
                "depth_m": r2(self.predicted_depth_m),
                "regime": self.predicted_regime,
                "rim_height_m": r2(self.predicted_rim_height_m),
                "depth_ratio_measured_over_predicted": r4(self.depth_ratio),
                "uncertainty_band": PIKE_RELATIVE_UNCERTAINTY,
                "interpretation": self._interpret(),
            },
            "morphology": {"class": self.morph_class, "basis": self.morph_basis},
            "sampling": {
                "resolution_m_px": r2(self.resolution_m_px),
                "pixels_across_diameter": r2(self.pixels_across),
                "adequacy": self.adequacy,
                "slope_baseline_m": r2(self.slope_baseline_m),
            },
            "profile": self.profile,
            "warnings": self.warnings,
            "sources": self.sources,
        }

    def _interpret(self) -> str:
        """State what the depth ratio means, without overclaiming."""
        if not np.isfinite(self.depth_ratio):
            return "Not comparable."
        lo, hi = 1 - PIKE_RELATIVE_UNCERTAINTY, 1 + PIKE_RELATIVE_UNCERTAINTY
        if self.adequacy == "insufficient":
            return ("The grid does not resolve this crater; the comparison is "
                    "indicative only.")
        if self.depth_ratio < 0.5:
            return ("Much shallower than a fresh crater of this size — "
                    "consistent with substantial infilling or degradation.")
        if self.depth_ratio < lo:
            return ("Shallower than the fresh-crater fit — some infilling or "
                    "wall collapse.")
        if self.depth_ratio <= hi:
            return ("Within the scatter of Pike's fresh-crater relation — "
                    "morphologically fresh.")
        return ("Deeper than the fresh-crater fit; check for a superposed "
                "crater on the floor or a mis-centred rim.")


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def _radial_profile(z, dist_m, r_max_m, nbins):
    """Mean, min and max elevation in concentric annuli."""
    edges = np.linspace(0.0, r_max_m, nbins + 1)
    idx = np.digitize(dist_m.ravel(), edges) - 1
    zf = z.ravel()

    means = np.full(nbins, np.nan)
    mins = np.full(nbins, np.nan)
    maxs = np.full(nbins, np.nan)
    counts = np.zeros(nbins, dtype=int)

    for b in range(nbins):
        sel = zf[idx == b]
        if sel.size:
            means[b] = sel.mean()
            mins[b] = sel.min()
            maxs[b] = sel.max()
            counts[b] = sel.size
    centres = 0.5 * (edges[:-1] + edges[1:])
    return centres, means, mins, maxs, counts


def analyse_crater(dem_source, lat: float, lon: float, diameter_km: float, *,
                   nbins: int = 48, extent_factor: float = 1.6) -> CraterMorphometry:
    """Measure one crater from topography.

    ``extent_factor`` sets how far beyond the rim the window reaches.  1.6 R is
    chosen so the annulus between 1.2 R and 1.5 R — used as the surrounding
    terrain datum — sits outside the continuous ejecta blanket but inside the
    window, which is what makes rim height a meaningful number.
    """
    warnings: list[str] = []
    R_m = diameter_km * 500.0                     # crater radius in metres
    reach_m = R_m * extent_factor

    # Angular half-size of the window.
    half_deg = math.degrees(reach_m / R_MOON_M)
    south, north = lat - half_deg, lat + half_deg
    lon_half = half_deg / max(math.cos(math.radians(lat)), 0.02)
    west, east = lon - lon_half, lon + lon_half

    if abs(lat) > POLAR_CYLINDRICAL_LIMIT_DEG:
        warnings.append(
            f"Centre is above {POLAR_CYLINDRICAL_LIMIT_DEG}° latitude, where the "
            "simple-cylindrical grid degenerates. Horizontal distances and "
            "slopes here are unreliable; a polar stereographic product is "
            "required for a defensible measurement."
        )

    south = max(south, -89.999)
    north = min(north, 89.999)

    win = dem_source.window(south, north, west, east)
    z = np.asarray(win.elevation, dtype=np.float64)
    if z.size < 25 or min(z.shape) < 5:
        raise ValueError(
            f"A {diameter_km:g} km crater spans only "
            f"{(diameter_km * 1000.0) / dem_source.baseline_m:.1f} cells at "
            f"{dem_source.baseline_m:.0f} m/px, which cannot support a radial "
            "profile. Use a finer DEM product (LDEM_64 or LDEM_128) for craters "
            "this small."
        )

    lats = win.latitudes()
    lons = win.longitudes()
    LON, LAT = np.meshgrid(lons, lats)

    # Exact great-circle distance from the crater centre to every cell.
    dist = np.asarray(sg.haversine_distance(lat, lon, LAT, LON), dtype=np.float64)

    res = float(dem_source.baseline_m)
    px_across = (diameter_km * 1000.0) / res
    if px_across >= 30:
        adequacy = "good"
    elif px_across >= 10:
        adequacy = "marginal"
    else:
        adequacy = "insufficient"
        warnings.append(
            f"Crater spans only {px_across:.1f} DEM cells at {res:.0f} m/px. "
            "Depth and slope are not reliably resolved at this scale; a finer "
            "product (LDEM_64 or better) is needed for a quantitative result."
        )
    if adequacy == "marginal":
        warnings.append(
            f"Crater spans {px_across:.1f} cells — sufficient to detect and "
            "approximate, but rim and floor are under-sampled."
        )

    # Adapt the annulus count to what the grid can actually support: asking for
    # 48 rings across a window only a few cells wide would leave most of them
    # empty and make the profile noise rather than signal.
    nbins = int(np.clip(reach_m / max(res, 1.0), 6, nbins))

    centres, means, mins, maxs, counts = _radial_profile(z, dist, reach_m, nbins)
    valid = counts > 0
    if valid.sum() < 4:
        raise ValueError(
            "Radial profile could not be formed: too few DEM cells fall inside "
            "the crater's footprint at this resolution."
        )

    # ── Rim: the highest ring-mean in a band around the nominal radius ──
    # Searching a band rather than a single ring tolerates the ~10-20 % spread
    # between catalogue diameter and true rim position.
    rim_band = valid & (centres > 0.70 * R_m) & (centres < 1.25 * R_m)
    if not rim_band.any():
        rim_band = valid
    rim_i = int(np.nanargmax(np.where(rim_band, means, -np.inf)))
    rim_elev = float(means[rim_i])
    rim_r = float(centres[rim_i])

    # ── Floor: low percentile inside the inner third ──
    inner = dist <= max(0.35 * R_m, res * 1.5)
    floor_elev = (float(np.percentile(z[inner], 10)) if inner.sum() >= 4
                  else float(np.nanmin(means[valid])))

    # ── Reference datum: surrounding terrain, outside continuous ejecta ──
    outer = (dist > 1.2 * R_m) & (dist <= 1.5 * R_m)
    if outer.sum() >= 8:
        reference = float(np.median(z[outer]))
    else:
        reference = float(np.nanmedian(means[valid][-max(3, nbins // 8):]))
        warnings.append(
            "Surrounding-terrain annulus was truncated; rim height is less "
            "certain than depth."
        )

    depth = rim_elev - floor_elev
    rim_height = rim_elev - reference
    floor_depth = reference - floor_elev

    # ── Wall slope from the profile between floor edge and rim ──
    inner_i = int(np.nanargmin(np.where(valid & (centres < rim_r), means, np.inf)))
    run = max(rim_r - float(centres[inner_i]), res)
    rise = rim_elev - float(means[inner_i])
    wall_slope = math.degrees(math.atan2(rise, run))

    # ── Gridded slope field, for mean/max over the crater interior ──
    from .terrain import slope_aspect
    dx, dy = win.cell_sizes()
    slope_deg, _ = slope_aspect(z, dx, dy)
    interior = dist <= R_m
    si = slope_deg[interior]
    si = si[np.isfinite(si)]
    mean_slope = float(si.mean()) if si.size else float("nan")
    max_slope = float(si.max()) if si.size else float("nan")

    # ── Excavated volume below the surrounding datum, inside the rim ──
    dxa = np.asarray(dx, dtype=np.float64).reshape(-1, 1)
    cell_area = dxa * float(dy)                       # m^2, varies by row
    below = interior & (z < reference)
    volume_m3 = float(np.sum((reference - z)[below] *
                             np.broadcast_to(cell_area, z.shape)[below]))
    volume_km3 = volume_m3 / 1e9

    pred_depth_km, regime = pike_depth_km(diameter_km)
    pred_depth_m = pred_depth_km * 1000.0
    pred_rim_m = pike_rim_height_km(diameter_km) * 1000.0
    mclass, mbasis = morphological_class(diameter_km)

    prof = [
        {"r_km": round(float(centres[i]) / 1000.0, 4),
         "r_over_R": round(float(centres[i]) / R_m, 4),
         "mean_m": round(float(means[i]), 1),
         "min_m": round(float(mins[i]), 1),
         "max_m": round(float(maxs[i]), 1)}
        for i in range(nbins) if valid[i]
    ]

    return CraterMorphometry(
        lat=lat, lon=lon, diameter_km=diameter_km,
        rim_elev_m=rim_elev, floor_elev_m=floor_elev, reference_elev_m=reference,
        depth_m=depth, rim_height_m=rim_height, floor_depth_m=floor_depth,
        wall_slope_deg=wall_slope, max_slope_deg=max_slope,
        mean_slope_deg=mean_slope,
        volume_km3=volume_km3, relief_m=float(np.nanmax(z) - np.nanmin(z)),
        resolution_m_px=res, pixels_across=px_across, adequacy=adequacy,
        slope_baseline_m=res,
        predicted_depth_m=pred_depth_m, predicted_regime=regime,
        depth_ratio=depth / pred_depth_m if pred_depth_m > 0 else float("nan"),
        predicted_rim_height_m=pred_rim_m,
        morph_class=mclass, morph_basis=mbasis,
        depth_diameter_ratio=depth / (diameter_km * 1000.0),
        profile=prof, warnings=warnings,
        sources={
            "topography": "LOLA LDEM (Smith et al. 2010, doi:10.1007/s11214-009-9512-y)",
            "depth_diameter": "Pike (1974) doi:10.1029/GL001i007p00291; Pike (1977)",
            "slope_operator": "Horn (1981) doi:10.1109/PROC.1981.11918",
            "collapse_mechanics": "Melosh (1989), Impact Cratering: A Geologic Process",
        },
    )


# ---------------------------------------------------------------------------
# Self-test against craters with published depths
# ---------------------------------------------------------------------------

def _self_test() -> int:
    from ..core.raster import get_dem

    npass = nfail = 0

    def check(name, ok, detail=""):
        nonlocal npass, nfail
        if ok:
            npass += 1
            print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
        else:
            nfail += 1
            print(f"  FAIL  {name}   {detail}")

    print("\nCrater morphometry — scaling laws\n")

    # Pike's relations at known diameters.
    d1, r1 = pike_depth_km(1.0)
    check("Pike simple, D=1 km -> 0.196 km", abs(d1 - 0.196) < 1e-3 and r1 == "simple",
          f"{d1*1000:.0f} m")
    d100, r100 = pike_depth_km(100.0)
    check("Pike complex, D=100 km -> ~4.2 km",
          3.5 < d100 < 5.0 and r100 == "complex", f"{d100:.2f} km")
    check("complex craters are shallower than linear extrapolation",
          d100 < 0.196 * 100, f"{d100:.2f} vs {0.196*100:.1f} km")

    print("\nMeasured from LOLA topography\n")
    dem = get_dem()

    # Published values (Pike 1976; LOLA-derived catalogues).
    cases = [
        ("Tycho",       -43.31, 348.68,  85.3, 4700, 0.30),
        ("Copernicus",    9.62, 339.92,  96.1, 3800, 0.35),
        ("Clavius",     -58.62, 345.27, 230.8, 3500, 0.55),
        ("Plato",        51.62, 350.62, 100.7, 1000, 1.20),
    ]
    for nm, la, lo, dm, want_m, tol in cases:
        try:
            m = analyse_crater(dem, la, lo, dm)
        except Exception as exc:  # noqa: BLE001
            check(f"{nm} analysed", False, str(exc)[:60])
            continue
        rel = abs(m.depth_m - want_m) / want_m
        check(f"{nm:<11} depth {m.depth_m:>6.0f} m  (published ~{want_m} m)",
              rel < tol,
              f"d/D={m.depth_diameter_ratio:.4f}  {m.pixels_across:.0f} px  "
              f"{m.adequacy}")

    # Plato is a lava-flooded crater: it must read far shallower than fresh.
    plato = analyse_crater(dem, 51.62, 350.62, 100.7)
    check("Plato reads as infilled (depth well below Pike)",
          plato.depth_ratio < 0.6, f"ratio {plato.depth_ratio:.2f}")

    tycho = analyse_crater(dem, -43.31, 348.68, 85.3)
    check("Tycho reads as fresh (near Pike)",
          0.6 < tycho.depth_ratio < 1.6, f"ratio {tycho.depth_ratio:.2f}")
    check("Tycho rim stands above surroundings", tycho.rim_height_m > 0,
          f"{tycho.rim_height_m:.0f} m")
    check("Tycho volume positive", tycho.volume_km3 > 0,
          f"{tycho.volume_km3:,.0f} km3")

    # Adequacy is a property of crater size *relative to the grid*, not of any
    # particular diameter, so these thresholds are derived from the DEM in use.
    # Hard-coding "20 km is marginal" was true of LDEM_16 and false of LDEM_64,
    # which is exactly the assumption a resolution upgrade should break.
    res = dem.baseline_m

    d_marginal = res * 15.0 / 1000.0          # ~15 cells across -> marginal
    marginal = analyse_crater(dem, -43.31, 348.68, d_marginal)
    check(f"{d_marginal:.1f} km crater flagged marginal at {res:.0f} m/px",
          marginal.adequacy in ("marginal", "insufficient") and marginal.warnings,
          f"{marginal.pixels_across:.1f} px -> {marginal.adequacy}")

    d_good = res * 40.0 / 1000.0              # ~40 cells across -> good
    good = analyse_crater(dem, -43.31, 348.68, d_good)
    check(f"{d_good:.1f} km crater reads as well-resolved",
          good.adequacy == "good",
          f"{good.pixels_across:.1f} px -> {good.adequacy}")

    # Below the resolution floor the module must refuse rather than invent.
    d_tiny = res * 2.0 / 1000.0               # ~2 cells across -> unusable
    try:
        analyse_crater(dem, 0.0, 0.0, d_tiny)
        check(f"{d_tiny:.1f} km crater refused at {res:.0f} m/px",
              False, "returned a result instead of refusing")
    except ValueError as exc:
        check(f"{d_tiny:.1f} km crater refused with an actionable message",
              "finer DEM" in str(exc) or "cells" in str(exc),
              str(exc)[:60] + "…")

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
