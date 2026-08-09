"""
Selenographic coordinates and spherical geodesy.

Implements ``docs/FORMULAS.md`` sections 1 and 2.  This module is the foundation
of the whole system: it is the *only* place where a geographic coordinate is
converted to a grid index, which is what lets the rest of the codebase obey the
requirement that all positioning be by real latitude/longitude (PRD FR-1.3).

Reference frame
---------------
IAU Mean Earth / Polar Axis (ME), DE421 realisation, on a **sphere** of radius
1 737 400 m.  This is not a modelling choice but an inherited constraint: the
LOLA PDS3 label declares ``A_AXIS_RADIUS = B_AXIS_RADIUS = C_AXIS_RADIUS``, so
flattening is exactly zero and the great-circle distance is the *exact*
geodesic rather than an approximation.

Every public function accepts scalars or NumPy arrays and returns the same
shape (SRD SR-C3).

Angles are in **degrees** at every public boundary; radians appear only inside
function bodies.  Distances are in **metres**.
"""

from __future__ import annotations

import numpy as np

from ..config import R_MOON_M

__all__ = [
    "normalise_lon",
    "to_signed_lon",
    "latlon_to_rowcol",
    "rowcol_to_latlon",
    "latlon_to_xyz",
    "xyz_to_latlon",
    "haversine_distance",
    "surface_distance_3d",
    "initial_bearing",
    "destination_point",
    "cell_size_m",
    "metres_per_degree",
]


# ---------------------------------------------------------------------------
# Longitude conventions
# ---------------------------------------------------------------------------

def normalise_lon(lon):
    """Normalise longitude to east-positive ``[0, 360)``.

    Accepts either convention: ``-180..180`` (common in literature) or
    ``0..360`` (the LOLA product convention).  SRD SR-C4.

    >>> float(normalise_lon(-11.36))
    348.64
    >>> float(normalise_lon(360.0))
    0.0
    """
    return np.mod(np.asarray(lon, dtype=float), 360.0)


def to_signed_lon(lon):
    """Convert east longitude to the signed ``(-180, 180]`` convention.

    >>> float(to_signed_lon(348.64))
    -11.36
    """
    lon = normalise_lon(lon)
    return np.where(lon > 180.0, lon - 360.0, lon)


# ---------------------------------------------------------------------------
# Grid <-> coordinate mapping  (FORMULAS.md §1.2)
# ---------------------------------------------------------------------------

def latlon_to_rowcol(lat, lon, width: int, height: int):
    """Map latitude/longitude to fractional grid indices.

    Pixel-registered simple cylindrical::

        row = (90 - lat) * H/180 - 0.5
        col =        lon * W/360 - 0.5

    The ``-0.5`` encodes pixel registration: a pixel's coordinate refers to its
    *centre*.  Verified against the PDS labels — for ``LDEM_16`` this returns
    (1439.5, 2879.5) at (0 degN, 180 degE), reproducing that product's
    ``LINE_PROJECTION_OFFSET`` and ``SAMPLE_PROJECTION_OFFSET`` exactly.

    Returns fractional indices; the caller decides whether to round (nearest
    neighbour) or interpolate.

    Parameters
    ----------
    lat, lon : float or array
        Planetocentric latitude in ``[-90, 90]``; longitude in any convention.
    width, height : int
        Grid dimensions (``LINE_SAMPLES``, ``LINES``).

    Returns
    -------
    (row, col) : tuple of float or array
    """
    lat = np.asarray(lat, dtype=float)
    lon = normalise_lon(lon)
    row = (90.0 - lat) * (height / 180.0) - 0.5
    col = lon * (width / 360.0) - 0.5
    return row, col


def rowcol_to_latlon(row, col, width: int, height: int):
    """Inverse of :func:`latlon_to_rowcol`.

    ``lat = 90 - (row + 0.5) * 180/H``, ``lon = (col + 0.5) * 360/W``.

    Round-trips to within floating-point precision (SRD SR-C1).
    """
    row = np.asarray(row, dtype=float)
    col = np.asarray(col, dtype=float)
    lat = 90.0 - (row + 0.5) * (180.0 / height)
    lon = normalise_lon((col + 0.5) * (360.0 / width))
    return lat, lon


# ---------------------------------------------------------------------------
# Cartesian conversion  (FORMULAS.md §1.4)
# ---------------------------------------------------------------------------

def latlon_to_xyz(lat, lon, elevation_m=0.0, radius_m: float = R_MOON_M):
    """Body-fixed Cartesian position [m].

    Elevation enters as a radial offset because the vertical datum *is* the
    reference sphere.
    """
    phi = np.radians(np.asarray(lat, dtype=float))
    lam = np.radians(normalise_lon(lon))
    r = radius_m + np.asarray(elevation_m, dtype=float)
    cos_phi = np.cos(phi)
    return r * cos_phi * np.cos(lam), r * cos_phi * np.sin(lam), r * np.sin(phi)


def xyz_to_latlon(x, y, z, radius_m: float = R_MOON_M):
    """Inverse of :func:`latlon_to_xyz`. Returns ``(lat, lon, elevation_m)``."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    z = np.asarray(z, dtype=float)
    r = np.sqrt(x * x + y * y + z * z)
    # `out` must be supplied alongside `where`, otherwise the masked-out
    # elements are uninitialised memory rather than the zeros we rely on.
    ratio = np.zeros(np.broadcast(z, r).shape, dtype=float)
    np.divide(z, r, out=ratio, where=r > 0)
    lat = np.degrees(np.arcsin(np.clip(ratio, -1.0, 1.0)))
    lon = normalise_lon(np.degrees(np.arctan2(y, x)))
    return lat, lon, r - radius_m


# ---------------------------------------------------------------------------
# Geodesy  (FORMULAS.md §2)
# ---------------------------------------------------------------------------

def haversine_distance(lat1, lon1, lat2, lon2, radius_m: float = R_MOON_M):
    """Great-circle distance [m].

    On a sphere this is the **exact** geodesic, not an approximation: the
    shortest path between two surface points is the minor arc of the great
    circle through them.

    The haversine form is used rather than the spherical law of cosines because
    it stays numerically stable for small separations, where
    ``cos(delta_sigma) -> 1`` and the law of cosines loses precision to
    floating-point cancellation.  ``atan2`` is used rather than ``arcsin``
    because the latter is ill-conditioned near antipodal points.
    """
    p1 = np.radians(np.asarray(lat1, dtype=float))
    p2 = np.radians(np.asarray(lat2, dtype=float))
    dphi = p2 - p1
    dlam = np.radians(normalise_lon(lon2) - normalise_lon(lon1))

    a = np.sin(dphi / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlam / 2.0) ** 2
    a = np.clip(a, 0.0, 1.0)
    return radius_m * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))


def surface_distance_3d(horizontal_m, delta_elevation_m):
    """Distance actually driven over terrain [m].

    ``sqrt(s_gc^2 + dz^2)`` — a rover travels *over* the surface, not through
    the chord.  Ignoring this under-estimates traverse distance, time and
    energy by ``1/cos(theta) - 1``: 3.5 % at 15 deg, 10 % at 25 deg.
    """
    s = np.asarray(horizontal_m, dtype=float)
    dz = np.asarray(delta_elevation_m, dtype=float)
    return np.hypot(s, dz)


def initial_bearing(lat1, lon1, lat2, lon2):
    """Initial great-circle bearing [deg clockwise from north, ``[0, 360)``].

    On a sphere the bearing along a great circle changes continuously, so this
    is the bearing *at the origin* and must be recomputed per segment.
    """
    p1 = np.radians(np.asarray(lat1, dtype=float))
    p2 = np.radians(np.asarray(lat2, dtype=float))
    dlam = np.radians(normalise_lon(lon2) - normalise_lon(lon1))

    y = np.sin(dlam) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dlam)
    return normalise_lon(np.degrees(np.arctan2(y, x)))


def destination_point(lat, lon, bearing_deg, distance_m,
                      radius_m: float = R_MOON_M):
    """Point reached by travelling ``distance_m`` along ``bearing_deg``.

    Direct spherical geodesic problem — used to generate traverse waypoints and
    to lay out search corridors.
    """
    p1 = np.radians(np.asarray(lat, dtype=float))
    l1 = np.radians(normalise_lon(lon))
    brg = np.radians(np.asarray(bearing_deg, dtype=float))
    delta = np.asarray(distance_m, dtype=float) / radius_m

    sin_p2 = np.sin(p1) * np.cos(delta) + np.cos(p1) * np.sin(delta) * np.cos(brg)
    p2 = np.arcsin(np.clip(sin_p2, -1.0, 1.0))
    l2 = l1 + np.arctan2(
        np.sin(brg) * np.sin(delta) * np.cos(p1),
        np.cos(delta) - np.sin(p1) * sin_p2,
    )
    return np.degrees(p2), normalise_lon(np.degrees(l2))


# ---------------------------------------------------------------------------
# Metric scale of a grid cell  (FORMULAS.md §2.4)
# ---------------------------------------------------------------------------

def cell_size_m(lat, width: int, height: int, radius_m: float = R_MOON_M):
    """Ground size of one grid cell at latitude ``lat``: ``(dx, dy)`` in metres.

    .. warning::
       ``dx`` is **latitude-dependent**::

           dy = pi * R / H                (constant)
           dx = 2 * pi * R * cos(lat) / W (shrinks toward the poles)

       The radius of the parallel of latitude is ``R*cos(lat)``, not ``R``, so
       east-west ground spacing contracts as ``cos(lat)``.

       Treating ``dx`` as constant is the single most common defect in naive
       planetary terrain analysis.  At 60 deg latitude it over-estimates
       east-west distance by 2x and therefore **under-estimates east-west slope
       by the same factor**; at 80 deg the error is 5.8x.  That produces hazard
       maps which are dangerously optimistic exactly where Artemis intends to
       land.

    At the equator, LOLA grids have ``W = 2H`` so ``dx == dy`` and cells are
    square — a useful self-check, and one that reproduces the label's
    ``MAP_SCALE`` (SRD SR-C2).

    As ``lat -> +/-90``, ``dx -> 0``.  This is a genuine degeneracy of the
    projection, not of the terrain; callers must switch to polar stereographic
    products above ``POLAR_CYLINDRICAL_LIMIT_DEG``.
    """
    lat = np.asarray(lat, dtype=float)
    dy = np.pi * radius_m / height
    dx = (2.0 * np.pi * radius_m / width) * np.cos(np.radians(lat))
    return dx, np.full_like(dx, dy) if np.ndim(dx) else dy


def metres_per_degree(lat, radius_m: float = R_MOON_M):
    """Ground metres per degree of latitude and of longitude at ``lat``.

    Returns ``(m_per_deg_lat, m_per_deg_lon)``.  Latitude spacing is constant
    on a sphere; longitude spacing carries the same ``cos(lat)`` factor as
    :func:`cell_size_m`.
    """
    lat = np.asarray(lat, dtype=float)
    per_lat = np.pi * radius_m / 180.0
    per_lon = (np.pi * radius_m / 180.0) * np.cos(np.radians(lat))
    return np.full_like(per_lon, per_lat) if np.ndim(per_lon) else per_lat, per_lon


# ---------------------------------------------------------------------------
# Self-verification
# ---------------------------------------------------------------------------

def _self_test() -> int:
    """Verify against the PDS labels and against analytic ground truth."""
    from ..config import DEM_PRODUCTS

    failures = 0

    def check(name, got, want, tol):
        nonlocal failures
        ok = abs(float(got) - float(want)) <= tol
        failures += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got {got:.6f}, "
              f"want {want:.6f} (tol {tol:g})")

    print("PDS label reproduction (FORMULAS.md §1.2)")
    for key, off_row, off_col in (("ldem_4", 359.5, 719.5),
                                  ("ldem_16", 1439.5, 2879.5),
                                  ("ldem_64", 5759.5, 11519.5)):
        p = DEM_PRODUCTS[key]
        r, c = latlon_to_rowcol(0.0, 180.0, p.width, p.height)
        check(f"{p.product_id} LINE_PROJECTION_OFFSET", r, off_row, 1e-9)
        check(f"{p.product_id} SAMPLE_PROJECTION_OFFSET", c, off_col, 1e-9)

    print("\nMAP_SCALE reproduction (FORMULAS.md §2.4, SRD SR-C2)")
    for key in ("ldem_4", "ldem_16", "ldem_64", "ldem_128"):
        p = DEM_PRODUCTS[key]
        dx, dy = cell_size_m(0.0, p.width, p.height)
        check(f"{p.product_id} dx at equator", dx, p.scale_m_px, 0.01)
        check(f"{p.product_id} dy == dx (square cells)", dy, dx, 1e-6)

    print("\nRound-trip (SRD SR-C1)")
    p = DEM_PRODUCTS["ldem_16"]
    for lat, lon in [(0, 0), (-43.31, 348.64), (85.0, 271.3), (-89.9, 45.0)]:
        r, c = latlon_to_rowcol(lat, lon, p.width, p.height)
        la, lo = rowcol_to_latlon(r, c, p.width, p.height)
        check(f"lat round-trip @({lat},{lon})", la, lat, 1e-9)
        check(f"lon round-trip @({lat},{lon})", lo, normalise_lon(lon), 1e-9)

    print("\nGeodesy (FORMULAS.md §2.1)")
    # Quarter circumference between pole and equator.
    check("pole->equator", haversine_distance(90, 0, 0, 0),
          np.pi * R_MOON_M / 2.0, 1.0)
    # Antipodal points: half circumference.
    check("antipodal", haversine_distance(0, 0, 0, 180),
          np.pi * R_MOON_M, 1.0)
    check("identical points", haversine_distance(10, 20, 10, 20), 0.0, 1e-6)
    # One degree along the equator.
    check("1 deg at equator", haversine_distance(0, 0, 0, 1),
          np.pi * R_MOON_M / 180.0, 1e-3)

    print("\nBearing (FORMULAS.md §2.3)")
    check("due north", initial_bearing(0, 0, 10, 0), 0.0, 1e-6)
    check("due east", initial_bearing(0, 0, 0, 10), 90.0, 1e-6)
    check("due south", initial_bearing(0, 0, -10, 0), 180.0, 1e-6)

    print("\nDestination point inverts distance+bearing")
    la, lo = destination_point(0.0, 0.0, 90.0, 100_000.0)
    check("round-trip distance", haversine_distance(0, 0, la, lo),
          100_000.0, 1e-3)

    print("\nLatitude-dependent cell size (FORMULAS.md §2.4)")
    dx0, _ = cell_size_m(0.0, p.width, p.height)
    dx60, _ = cell_size_m(60.0, p.width, p.height)
    dx80, _ = cell_size_m(80.0, p.width, p.height)
    check("dx(60) / dx(0) == cos(60) = 0.5", dx60 / dx0, 0.5, 1e-9)
    check("dx(80) / dx(0) == cos(80)", dx80 / dx0, np.cos(np.radians(80)), 1e-9)

    print("\nCartesian round-trip (FORMULAS.md §1.4)")
    x, y, z = latlon_to_xyz(-43.31, 348.64, 1234.5)
    la, lo, el = xyz_to_latlon(x, y, z)
    check("lat", la, -43.31, 1e-9)
    check("lon", lo, 348.64, 1e-9)
    check("elevation", el, 1234.5, 1e-6)

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
    return failures


if __name__ == "__main__":
    raise SystemExit(_self_test())
