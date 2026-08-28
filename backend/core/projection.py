"""
A local map projection centred on whatever region is being analysed.

Why an AOI needs its own projection
-----------------------------------
Every grid this system reads is stored in a projection chosen for global
convenience, not for the region in hand:

* **Simple cylindrical** has cells whose east-west size scales with cos(phi).
  At 60 deg a cell is half as wide as it is tall; toward a pole it collapses
  entirely (``CONTRIBUTIONS.md`` 3.7). Slope, cost and any planner that assumes
  a square cell are all wrong on it away from the equator.
* **Polar stereographic** is square near its own pole and useless elsewhere.

Analysis wants neither. It wants square cells of a known size, so that a
diagonal step really is sqrt(2) cells, a slope really is rise over run, and one
cost surface means the same thing everywhere in it. So each AOI is resampled
onto a grid in an **azimuthal equidistant projection centred on the AOI
itself**, and every downstream stage — slope, roughness, hazard, cost, the
planners — sees the same clean geometry regardless of where on the Moon the
region sits or which product supplied the bytes.

Distortion, quantified
----------------------
Azimuthal equidistant keeps radial distance from the centre exact; the
perpendicular scale is ``c / sin(c)`` for angular distance ``c``. On a 1737.4 km
sphere:

===============  ==============  ==================
region radius    c               scale error
===============  ==============  ==================
10 km            0.0058 rad      0.0006 %
100 km           0.0576 rad      0.055 %
350 km           0.201 rad       0.68 %
700 km           0.403 rad       2.7 %
===============  ==============  ==================

Negligible for a site AOI, small for a regional survey, and reported rather
than assumed — :func:`max_scale_error` returns it so an AOI can state its own
geometric fidelity instead of implying perfection.
"""

from __future__ import annotations

import math

import numpy as np

from ..config import R_MOON_M

__all__ = ["LocalProjection", "max_scale_error"]

_TINY = 1e-12


def max_scale_error(radius_m: float, radius: float = R_MOON_M) -> float:
    """Fractional tangential scale error at a distance from the centre.

    Zero at the centre and growing without bound toward the antipode, where the
    single point opposite the origin is stretched into a whole circle.

    The ``c >= pi`` guard is not defensive tidiness. ``c / sin(c)`` turns
    **negative** past the antipode, so a naive evaluation reports a 10,900 km
    region as *less* distorted than a 700 km one — and any caller using this as
    a limit then waves through precisely the regions it exists to reject. Beyond
    the antipode the projection has no meaning at all, so the honest answer is
    infinite.
    """
    c = abs(float(radius_m)) / float(radius)
    if c < _TINY:
        return 0.0
    if c >= math.pi:
        return math.inf
    return c / math.sin(c) - 1.0


class LocalProjection:
    """Azimuthal equidistant projection about one point on the sphere.

    Coordinates are metres east (``x``) and north (``y``) of the centre.
    """

    __slots__ = ("lat0", "lon0", "radius", "_sin0", "_cos0")

    def __init__(self, lat0: float, lon0: float, radius: float = R_MOON_M):
        self.lat0 = float(lat0)
        self.lon0 = float(lon0)
        self.radius = float(radius)
        self._sin0 = math.sin(math.radians(self.lat0))
        self._cos0 = math.cos(math.radians(self.lat0))

    # -- forward ---------------------------------------------------------

    def forward(self, lat, lon):
        """(lat, lon) in degrees -> (x, y) in metres from the centre."""
        la = np.radians(np.asarray(lat, dtype=np.float64))
        dlo = np.radians(np.asarray(lon, dtype=np.float64) - self.lon0)

        sin_la, cos_la = np.sin(la), np.cos(la)
        cos_c = self._sin0 * sin_la + self._cos0 * cos_la * np.cos(dlo)
        cos_c = np.clip(cos_c, -1.0, 1.0)
        c = np.arccos(cos_c)
        sin_c = np.sin(c)

        # k = c / sin(c) is 1 at the centre; the limit has to be supplied
        # explicitly or the antipode-free centre divides by zero.
        k = np.where(sin_c < _TINY, 1.0, c / np.where(sin_c < _TINY, 1.0, sin_c))

        x = self.radius * k * cos_la * np.sin(dlo)
        y = self.radius * k * (self._cos0 * sin_la
                               - self._sin0 * cos_la * np.cos(dlo))
        return x, y

    # -- inverse ---------------------------------------------------------

    def inverse(self, x, y):
        """(x, y) in metres from the centre -> (lat, lon) in degrees."""
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        rho = np.hypot(x, y)
        c = rho / self.radius
        sin_c, cos_c = np.sin(c), np.cos(c)

        safe_rho = np.where(rho < _TINY, 1.0, rho)
        sin_lat = cos_c * self._sin0 + (y * sin_c * self._cos0) / safe_rho
        lat = np.degrees(np.arcsin(np.clip(sin_lat, -1.0, 1.0)))

        lon = self.lon0 + np.degrees(np.arctan2(
            x * sin_c,
            rho * self._cos0 * cos_c - y * self._sin0 * sin_c))

        # At the centre the azimuth is undefined; the answer is the centre.
        lat = np.where(rho < _TINY, self.lat0, lat)
        lon = np.where(rho < _TINY, self.lon0, lon)
        lon = ((lon + 180.0) % 360.0 + 360.0) % 360.0 - 180.0
        return lat, lon

    def __repr__(self) -> str:                       # pragma: no cover
        return f"LocalProjection(lat0={self.lat0:.4f}, lon0={self.lon0:.4f})"


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

    print("\nThe centre is the origin, everywhere on the Moon\n")
    for lat0, lon0 in [(0, 0), (45, 90), (-89.5, 222), (89.9, -30), (-90, 0)]:
        p = LocalProjection(lat0, lon0)
        x, y = p.forward(lat0, lon0)
        check(f"({lat0}, {lon0}) projects to the origin",
              abs(float(x)) < 1e-6 and abs(float(y)) < 1e-6,
              f"({float(x):.2e}, {float(y):.2e})")

    print("\nRound trip, including at the poles where other grids fail\n")
    rng = np.random.default_rng(3)
    worst = 0.0
    for lat0, lon0 in [(0, 0), (30, 45), (-89.6, 222), (89.8, 100), (-45, 179)]:
        p = LocalProjection(lat0, lon0)
        # Points scattered within ~100 km of the centre.
        xs = rng.uniform(-1e5, 1e5, 400)
        ys = rng.uniform(-1e5, 1e5, 400)
        la, lo = p.inverse(xs, ys)
        bx, by = p.forward(la, lo)
        err = float(np.max(np.hypot(bx - xs, by - ys)))
        worst = max(worst, err)
    check("x,y -> lat,lon -> x,y returns the same point", worst < 1e-6,
          f"worst error {worst:.2e} m over 2,000 points at five centres")

    print("\nDistances from the centre are exact — that is the point\n")
    p = LocalProjection(-89.5, 222.0)
    for d_km in (1, 10, 50, 100):
        la, lo = p.inverse(d_km * 1000.0, 0.0)
        # Great-circle distance back to the centre.
        a, b = math.radians(p.lat0), math.radians(float(la))
        dlon = math.radians(float(lo) - p.lon0)
        ang = math.acos(min(1.0, math.sin(a)*math.sin(b)
                            + math.cos(a)*math.cos(b)*math.cos(dlon)))
        got = ang * R_MOON_M / 1000.0
        check(f"{d_km} km east of centre is {d_km} km away",
              abs(got - d_km) < 1e-6, f"measured {got:.9f} km")

    print("\nCells are square, which cylindrical grids are not\n")
    # One degree of longitude shrinks with latitude; one grid step must not.
    for lat0 in (0.0, 60.0, -89.5):
        p = LocalProjection(lat0, 0.0)
        la_e, lo_e = p.inverse(1000.0, 0.0)      # 1 km east
        la_n, lo_n = p.inverse(0.0, 1000.0)      # 1 km north
        def gc(latA, lonA, latB, lonB):
            a, b = math.radians(latA), math.radians(latB)
            d = math.radians(lonB - lonA)
            return math.acos(min(1.0, math.sin(a)*math.sin(b)
                                 + math.cos(a)*math.cos(b)*math.cos(d))) * R_MOON_M
        de = gc(lat0, 0.0, float(la_e), float(lo_e))
        dn = gc(lat0, 0.0, float(la_n), float(lo_n))
        check(f"at {lat0:>6.1f} deg a 1 km step is 1 km both ways",
              abs(de - 1000) < 1e-3 and abs(dn - 1000) < 1e-3,
              f"east {de:.4f} m, north {dn:.4f} m")

    print("\nDistortion is bounded and reported\n")
    for r_km, limit in [(10, 1e-5), (100, 1e-3), (350, 0.01), (700, 0.03)]:
        e = max_scale_error(r_km * 1000.0)
        print(f"    {r_km:>4} km radius -> {e*100:.4f} % tangential stretch")
        check(f"scale error at {r_km} km is under {limit*100:g} %", e < limit)
    check("the centre has no distortion", max_scale_error(0.0) == 0.0)

    # c/sin(c) turns negative past the antipode, which made a whole-Moon region
    # report *less* distortion than a 700 km one — so a guard built on this
    # waved through exactly what it existed to stop.
    antipode_km = math.pi * R_MOON_M / 1000
    print(f"    antipode at {antipode_km:,.0f} km")
    for km in (5000, 5457, 5460, 7000, 10900):
        e = max_scale_error(km * 1000.0)
        print(f"    {km:>6} km -> {'inf' if math.isinf(e) else f'{e*100:,.0f} %'}")
    check("distortion grows monotonically all the way to the antipode",
          max_scale_error(2e6) < max_scale_error(4e6) < max_scale_error(5.4e6))
    check("beyond the antipode the answer is infinite, never negative",
          math.isinf(max_scale_error(7e6)) and math.isinf(max_scale_error(1.09e7)),
          "a negative here silently passes the worst regions")
    check("no distance ever reports negative distortion",
          all(max_scale_error(d) >= 0.0 for d in range(0, 12_000_000, 250_000)))

    print("\nThe south pole is an ordinary point here\n")
    p = LocalProjection(-90.0, 0.0)
    la, lo = p.inverse(np.array([0.0, 1e4, -1e4]), np.array([1e4, 0.0, 0.0]))
    check("projecting about the pole yields finite coordinates",
          bool(np.all(np.isfinite(la)) and np.all(np.isfinite(lo))),
          f"lat {np.round(la, 4).tolist()}")
    check("all three points are 10 km from the pole",
          bool(np.allclose((90.0 + la) * math.pi / 180.0 * R_MOON_M, 1e4,
                           atol=1e-3)),
          "no convergence-of-meridians artefact")

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
