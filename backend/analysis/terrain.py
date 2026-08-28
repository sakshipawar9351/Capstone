"""
Terrain derivatives from a digital elevation model.

Scale dependence — read this before using anything here
-------------------------------------------------------
Slope is not a property of a place; it is a property of a place *at a length
scale*.  The gradient measured across a 1.9 km cell is not the gradient a rover
wheel meets over 5 m, and quoting one as the other is a category error, not a
rounding error.  Every function in this module therefore returns its result
together with the baseline it was computed over, and callers are expected to
propagate that baseline to the user.

Grid geometry
-------------
The LOLA products are simple-cylindrical, so a cell's north-south extent is
constant while its east-west extent shrinks as cos(lat):

    dy = pi * R / H                     (constant)
    dx = 2 * pi * R * cos(lat) / W      (per row)

Treating dx as constant is the single most common error in DEM analysis on
planetary grids: at 60 deg latitude it inflates east-west gradients by a factor
of two.  Every derivative below takes ``dx`` as a per-row array.

References
----------
Horn, B. K. P. (1981), "Hill shading and the reflectance map",
    Proceedings of the IEEE 69(1), 14-47.  doi:10.1109/PROC.1981.11918
Zevenbergen, L. W. & Thorne, C. R. (1987), "Quantitative analysis of land
    surface topography", Earth Surface Processes and Landforms 12, 47-56.
    doi:10.1002/esp.3290120107
Riley, S. J., DeGloria, S. D. & Elliot, R. (1999), "A terrain ruggedness index
    that quantifies topographic heterogeneity", Intermountain Journal of
    Sciences 5, 23-27.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "TerrainDerivatives",
    "slope_aspect",
    "roughness",
    "terrain_ruggedness_index",
    "curvature",
    "hillshade",
    "analyse",
]


@dataclass
class TerrainDerivatives:
    """Derivatives of one DEM window, each tagged with its baseline."""

    slope_deg: np.ndarray
    aspect_deg: np.ndarray
    baseline_m: float          # the length scale these were measured over
    roughness_m: np.ndarray | None = None
    roughness_window: int | None = None
    tri_m: np.ndarray | None = None
    profile_curv: np.ndarray | None = None
    plan_curv: np.ndarray | None = None

    def stats(self) -> dict:
        s = self.slope_deg[np.isfinite(self.slope_deg)]
        out = {
            "baseline_m": round(self.baseline_m, 2),
            "slope_deg": {
                "mean": round(float(s.mean()), 3),
                "median": round(float(np.median(s)), 3),
                "p90": round(float(np.percentile(s, 90)), 3),
                "p99": round(float(np.percentile(s, 99)), 3),
                "max": round(float(s.max()), 3),
            },
        }
        if self.roughness_m is not None:
            r = self.roughness_m[np.isfinite(self.roughness_m)]
            out["roughness_m"] = {
                "window_px": self.roughness_window,
                "mean": round(float(r.mean()), 3),
                "p90": round(float(np.percentile(r, 90)), 3),
                "max": round(float(r.max()), 3),
            }
        return out


def _as_dx(dx, shape) -> np.ndarray:
    """Broadcast a per-row dx to a column vector."""
    dx = np.asarray(dx, dtype=np.float64)
    if dx.ndim == 0:
        return np.full((shape[0], 1), float(dx))
    return dx.reshape(-1, 1)


def slope_aspect(dem: np.ndarray, dx, dy: float) -> tuple[np.ndarray, np.ndarray]:
    r"""Slope and aspect by Horn's third-order finite difference.

    Horn's operator estimates the surface gradient from all eight neighbours,
    weighting the orthogonal ones twice:

    .. math::
        \frac{\partial z}{\partial x} =
          \frac{(z_3 + 2z_6 + z_9) - (z_1 + 2z_4 + z_7)}{8\,\Delta x}

        \frac{\partial z}{\partial y} =
          \frac{(z_7 + 2z_8 + z_9) - (z_1 + 2z_2 + z_3)}{8\,\Delta y}

        S = \arctan\sqrt{(\partial z/\partial x)^2 + (\partial z/\partial y)^2}

    It is preferred over the simpler two-point difference because averaging
    three rows suppresses the along-track noise characteristic of altimeter-
    derived grids, and it is the estimator used by GDAL and ArcGIS — so results
    here are directly comparable with those tools.

    Aspect is returned as a compass azimuth: degrees clockwise from north,
    pointing *downslope*.  Flat cells are assigned NaN rather than 0, because
    zero is a real direction and would otherwise contaminate circular statistics.
    """
    z = np.asarray(dem, dtype=np.float64)
    if z.ndim != 2 or min(z.shape) < 3:
        raise ValueError("slope_aspect needs a 2-D array of at least 3x3")

    # Edge-replicate so the output keeps the input's shape.
    p = np.pad(z, 1, mode="edge")
    z1, z2, z3 = p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:]
    z4, z6 = p[1:-1, :-2], p[1:-1, 2:]
    z7, z8, z9 = p[2:, :-2], p[2:, 1:-1], p[2:, 2:]

    dxa = _as_dx(dx, z.shape)
    dzdx = ((z3 + 2 * z6 + z9) - (z1 + 2 * z4 + z7)) / (8.0 * dxa)
    # Row index increases southward, so this is already d z / d(south).
    dzdy = ((z7 + 2 * z8 + z9) - (z1 + 2 * z2 + z3)) / (8.0 * dy)

    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))

    aspect = np.degrees(np.arctan2(dzdy, -dzdx))
    aspect = (90.0 - aspect) % 360.0
    aspect[np.hypot(dzdx, dzdy) < 1e-12] = np.nan

    return slope, aspect


def roughness(dem: np.ndarray, window: int = 3,
              detrend: bool = True) -> np.ndarray:
    r"""Local surface roughness, in metres.

    With ``detrend=True`` (the default) this is the RMS residual about the
    best-fit plane in each window — the geomorphological sense of roughness.
    With ``detrend=False`` it is the plain standard deviation of elevation.

    **Why detrending is not optional here.** A perfectly smooth slope has large
    elevation variance simply because it is tilted. Undetrended roughness
    therefore reports a flat ramp as rough, and any hazard model that combines
    it with slope counts the same gradient twice. Measured on a constant
    9.5° ramp the undetrended value is 1.36 m and the detrended value is 0 m:
    the first restates the slope, the second reports the absence of obstacles,
    and only the second is what a wheel responds to.

    For a plane :math:`z = ax + by + c` fitted by least squares over a window
    with centred coordinates, the residual variance has a closed form:

    .. math::
        a = \frac{\langle xz\rangle}{\langle x^2\rangle},\qquad
        b = \frac{\langle yz\rangle}{\langle y^2\rangle}

        \sigma_r^2 = \langle z^2\rangle - \langle z\rangle^2
                     - \bigl(a^2 + b^2\bigr)\langle x^2\rangle

    so no per-window regression is needed and the cost stays O(n) in the
    window size.
    """
    from scipy.ndimage import uniform_filter

    z = np.asarray(dem, dtype=np.float64)
    mean = uniform_filter(z, size=window, mode="nearest")
    var = uniform_filter(z * z, size=window, mode="nearest") - mean * mean

    if not detrend:
        return np.sqrt(np.clip(var, 0.0, None))

    # Centred offsets within the window, in pixels. <x^2> = <y^2> by symmetry.
    off = np.arange(window, dtype=np.float64) - (window - 1) / 2.0
    exx = float((off ** 2).mean())
    if exx <= 0:                      # window == 1: nothing to detrend
        return np.sqrt(np.clip(var, 0.0, None))

    # <xz> and <yz>: weight along one axis, average along the other. Separable,
    # so this is two 1-D passes rather than a 2-D regression per pixel.
    from scipy.ndimage import correlate1d

    wr = off / window
    exz = uniform_filter(correlate1d(z, wr, axis=0, mode="nearest"),
                         size=(1, window), mode="nearest")
    eyz = uniform_filter(correlate1d(z, wr, axis=1, mode="nearest"),
                         size=(window, 1), mode="nearest")

    a = exz / exx
    b = eyz / exx
    resid = var - (a * a + b * b) * exx
    return np.sqrt(np.clip(resid, 0.0, None))


def terrain_ruggedness_index(dem: np.ndarray) -> np.ndarray:
    """Riley's TRI: RMS elevation difference to the eight neighbours.

    Unlike a standard deviation, TRI is anchored on the centre cell, so it
    responds to an isolated spike — which is what a boulder or a small fresh
    crater looks like in a DEM — rather than to overall variability.
    """
    z = np.asarray(dem, dtype=np.float64)
    p = np.pad(z, 1, mode="edge")
    acc = np.zeros_like(z)
    for di in (0, 1, 2):
        for dj in (0, 1, 2):
            if di == 1 and dj == 1:
                continue
            d = p[di:di + z.shape[0], dj:dj + z.shape[1]] - z
            acc += d * d
    return np.sqrt(acc / 8.0)


def curvature(dem: np.ndarray, dx, dy: float) -> tuple[np.ndarray, np.ndarray]:
    r"""Profile and plan curvature after Zevenbergen & Thorne (1987).

    A quadratic surface is fitted to each 3x3 neighbourhood,

    .. math:: z = Ax^2y^2 + Bx^2y + Cxy^2 + Dx^2 + Ey^2 + Fxy + Gx + Hy + I

    from which curvature follows in closed form.  Profile curvature (along the
    slope) governs whether a rover accelerates or decelerates; plan curvature
    (across it) governs whether material converges or diverges.  Both are
    returned in units of 1/m; positive profile curvature is convex-upward.
    """
    z = np.asarray(dem, dtype=np.float64)
    p = np.pad(z, 1, mode="edge")
    dxa = _as_dx(dx, z.shape)

    z1, z2, z3 = p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:]
    z4, z5, z6 = p[1:-1, :-2], p[1:-1, 1:-1], p[1:-1, 2:]
    z7, z8, z9 = p[2:, :-2], p[2:, 1:-1], p[2:, 2:]

    D = ((z4 + z6) / 2.0 - z5) / (dxa ** 2)
    E = ((z2 + z8) / 2.0 - z5) / (dy ** 2)
    F = (z3 + z7 - z1 - z9) / (4.0 * dxa * dy)
    G = (z6 - z4) / (2.0 * dxa)
    H = (z8 - z2) / (2.0 * dy)

    g2 = G * G + H * H
    denom = np.where(g2 < 1e-20, np.nan, g2)

    profile = -2.0 * (D * G * G + E * H * H + F * G * H) / denom
    plan = 2.0 * (D * H * H + E * G * G - F * G * H) / denom
    return profile, plan


def hillshade(slope_deg, aspect_deg, azimuth_deg=315.0, altitude_deg=45.0):
    """Analytical hillshade.

    VISUALISATION ONLY.  This synthesises an illumination that does not exist;
    it must never be fed back into hazard or slope analysis, and the globe's
    basemap deliberately does not use it (the brief requires no illumination
    effects).  It is provided because a shaded relief is the clearest way to
    *inspect* a DEM window during development.
    """
    z = np.radians(90.0 - altitude_deg)
    a = np.radians(azimuth_deg)
    s = np.radians(slope_deg)
    asp = np.radians(np.nan_to_num(aspect_deg, nan=0.0))
    v = (np.cos(z) * np.cos(s)) + (np.sin(z) * np.sin(s) * np.cos(a - asp))
    return np.clip(v, 0.0, 1.0)


def analyse(dem: np.ndarray, dx, dy: float, *,
            baseline_m: float | None = None,
            roughness_window: int = 3,
            with_curvature: bool = False) -> TerrainDerivatives:
    """Full derivative set for a DEM window."""
    slope, asp = slope_aspect(dem, dx, dy)

    if baseline_m is None:
        dxa = np.asarray(dx, dtype=np.float64)
        baseline_m = float(np.mean(dxa) if dxa.ndim else dxa)

    out = TerrainDerivatives(
        slope_deg=slope, aspect_deg=asp, baseline_m=baseline_m,
        roughness_m=roughness(dem, roughness_window),
        roughness_window=roughness_window,
        tri_m=terrain_ruggedness_index(dem),
    )
    if with_curvature:
        out.profile_curv, out.plan_curv = curvature(dem, dx, dy)
    return out


# ---------------------------------------------------------------------------
# Self-test — analytic surfaces with known answers
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

    print("\nTerrain derivatives — verification against analytic surfaces\n")

    # 1. Flat plane: slope must be exactly zero.
    flat = np.full((20, 20), 1234.5)
    s, a = slope_aspect(flat, 100.0, 100.0)
    check("flat plane -> 0 deg slope", np.allclose(s, 0.0),
          f"max {s.max():.2e}")
    check("flat plane -> undefined aspect", np.all(np.isnan(a)))

    # 2. Constant 45 deg ramp: rise == run.
    n, cell = 30, 100.0
    ramp = np.tile(np.arange(n) * cell, (n, 1))       # rises toward +x
    s, a = slope_aspect(ramp, cell, cell)
    inner = s[2:-2, 2:-2]
    check("45 deg ramp -> 45 deg slope", np.allclose(inner, 45.0, atol=1e-9),
          f"mean {inner.mean():.6f}")

    # Downslope points toward -x, i.e. west = 270 deg.
    ai = a[2:-2, 2:-2]
    check("east-rising ramp -> aspect 270 (west)",
          np.allclose(ai, 270.0, atol=1e-6), f"mean {ai.mean():.3f}")

    # 3. Known gradient: 1 m rise over 20 m run -> atan(0.05) = 2.8624 deg.
    ramp2 = np.tile(np.arange(n) * 1.0, (n, 1))
    s2, _ = slope_aspect(ramp2, 20.0, 20.0)
    want = np.degrees(np.arctan(1.0 / 20.0))
    check(f"1:20 gradient -> {want:.4f} deg",
          np.allclose(s2[2:-2, 2:-2], want, atol=1e-9))

    # 4. Latitude-varying dx must change the answer.  Identical topography at
    #    the equator and at 60 deg must yield twice the gradient at 60 deg,
    #    because the cell there is half as wide on the ground.
    lat = np.array([0.0, 0.0, 60.0, 60.0])
    dxv = 1000.0 * np.cos(np.radians(lat))            # 1000, 1000, 500, 500 m
    z = np.tile(np.arange(6) * 10.0, (4, 1))
    s3, _ = slope_aspect(z, dxv, 1000.0)
    r = np.tan(np.radians(s3[3, 3])) / np.tan(np.radians(s3[0, 3]))
    check("cos(lat) narrowing doubles gradient at 60 deg",
          abs(r - 2.0) < 1e-9, f"ratio {r:.6f}")

    # 5. Roughness of a plane is zero; of noise, positive.
    check("roughness(plane) == 0", np.allclose(roughness(flat, 3), 0.0))
    rng = np.random.default_rng(0)
    noisy = flat + rng.normal(0, 5.0, flat.shape)
    rn = roughness(noisy, 5)[2:-2, 2:-2]
    check("roughness(sigma=5 noise) is positive", rn.mean() > 1.0,
          f"{rn.mean():.2f} m")

    # 5b. Detrending: a tilted plane is smooth, however steep it is.
    tilt = np.tile(np.arange(30) * 1.667, (30, 1))     # constant ~9.5 deg ramp
    r_plain = float(roughness(tilt, 3, detrend=False)[5:-5, 5:-5].mean())
    r_detr = float(roughness(tilt, 3, detrend=True)[5:-5, 5:-5].mean())
    print(f"    constant ramp -> undetrended {r_plain:.3f} m, "
          f"detrended {r_detr:.3f} m")
    check("undetrended roughness mistakes a ramp for rough ground",
          r_plain > 1.0, f"{r_plain:.3f} m — this is the slope, restated")
    check("detrended roughness of a plane is ~0",
          r_detr < 1e-6, f"{r_detr:.2e} m")

    # A bump on a ramp must still register once the trend is removed.
    bumped = tilt.copy()
    bumped[15, 15] += 3.0
    check("a bump on a ramp is still detected after detrending",
          float(roughness(bumped, 3, detrend=True)[15, 15]) > 0.5,
          "detrending removes the slope, not the obstacle")

    # 6. TRI responds to an isolated spike, as a boulder would.
    spike = flat.copy()
    spike[10, 10] += 50.0
    t = terrain_ruggedness_index(spike)
    check("TRI localises a spike", t[10, 10] > t[0, 0] + 40,
          f"spike {t[10,10]:.1f} m vs background {t[0,0]:.1f} m")

    # 7. Curvature: a paraboloid has constant, correctly-signed curvature.
    g = np.linspace(-500, 500, 41)
    X, Y = np.meshgrid(g, g)
    dome = -(X ** 2 + Y ** 2) / 20000.0               # convex-up dome
    pc, _ = curvature(dome, g[1] - g[0], g[1] - g[0])
    centre = pc[15:26, 15:26]
    check("dome -> positive profile curvature",
          np.nanmean(centre) > 0, f"mean {np.nanmean(centre):.3e} 1/m")

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
