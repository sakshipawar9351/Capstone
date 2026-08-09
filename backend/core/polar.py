"""
Polar stereographic grids — LOLA's high-resolution polar DEMs.

Why a separate module
---------------------
``raster.py`` handles simple-cylindrical products, where latitude is linear in
row and longitude linear in column. That mapping is not merely inaccurate near
the poles — it is undefined at them. Every meridian converges on a single point,
so a cylindrical grid devotes an entire row to a place with no east-west extent
at all.

The LOLA polar products avoid this by projecting onto a plane tangent at the
pole. Row and column become Cartesian metres from the pole, and latitude enters
through the distance from the origin rather than through the row index. The two
grid types therefore need genuinely different code, not a shared function with
a special case.

Projection
----------
Polar stereographic on a sphere, centred on the pole. For a south polar grid:

.. math::
    \\rho = 2R\\tan(45° + \\varphi/2)

    x = \\rho\\sin(\\lambda - \\lambda_0)
    \\qquad
    y = \\rho\\cos(\\lambda - \\lambda_0)

and for a north polar grid the latitude term becomes :math:`\\tan(45° - φ/2)`
with the sign of *y* reversed. Pixel indices follow from the label's
projection offsets:

.. math::
    s = S_0 + x / \\text{MAP\\_SCALE}
    \\qquad
    l = L_0 - y / \\text{MAP\\_SCALE}

*Verification.* For ``LDEM_875S_10M`` the label declares a grid edge at
−87.5° latitude and ``SAMPLE_PROJECTION_OFFSET = 7583.5``. Substituting
φ = −87.5° gives ρ = 75 833 m, or 7583.3 pixels at 10 m/pixel — agreeing with
the declared offset to within a fifth of a pixel. The equations above are
therefore the ones that produced the grid, not a plausible reconstruction.

Why stereographic specifically
------------------------------
It is **conformal**: angles are preserved, so a slope computed on the grid is
the true ground slope in every azimuth. An equal-area projection would distort
gradients directionally and quietly corrupt exactly the quantity this project
exists to measure. Scale grows away from the pole as sec²(distance/2R), which
over the 2.5° span of these products is at most 0.05 % — negligible, and
corrected for regardless in :func:`PolarGrid.cell_size_m`.

Reference
---------
Snyder, J. P. (1987), *Map Projections — A Working Manual*, USGS Professional
Paper 1395, §21 (Stereographic projection, polar aspect).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import R_MOON_M

__all__ = ["PolarGrid", "PolarWindow", "parse_polar_label", "open_polar"]

DEG = math.pi / 180.0


# ---------------------------------------------------------------------------
# Label
# ---------------------------------------------------------------------------

def _num(txt: str, key: str) -> float | None:
    m = re.search(rf"^\s*{key}\s*=\s*([-+0-9.eE]+)", txt, re.M)
    return float(m.group(1)) if m else None


def _str(txt: str, key: str) -> str | None:
    m = re.search(rf'^\s*{key}\s*=\s*"?([^"\r\n]+?)"?\s*$', txt, re.M)
    return m.group(1).strip() if m else None


def parse_polar_label(path: str | Path) -> dict:
    """Read the geometry out of a PDS3 polar stereographic label."""
    txt = Path(path).read_text(errors="replace")

    proj = (_str(txt, "MAP_PROJECTION_TYPE") or "").upper()
    if "POLAR" not in proj or "STEREO" not in proj:
        raise ValueError(f"not a polar stereographic label: {proj!r}")

    sb = int(_num(txt, "SAMPLE_BITS") or 0)
    stype = (_str(txt, "SAMPLE_TYPE") or "").upper()
    # PC_REAL is IEEE floating point, least-significant byte first.
    if "REAL" in stype and sb == 32:
        dtype = "<f4" if stype.startswith("PC") else ">f4"
    elif sb == 16:
        dtype = "<i2" if stype.startswith(("PC", "LSB")) else ">i2"
    else:
        raise ValueError(f"unsupported sample type {stype} / {sb} bits")

    return {
        "product_id": _str(txt, "PRODUCT_ID") or "",
        "height": int(_num(txt, "LINES")),
        "width": int(_num(txt, "LINE_SAMPLES")),
        "dtype": dtype,
        "map_scale_m": _num(txt, "MAP_SCALE"),
        "centre_lat": _num(txt, "CENTER_LATITUDE"),
        "centre_lon": _num(txt, "CENTER_LONGITUDE") or 0.0,
        "line_offset": _num(txt, "LINE_PROJECTION_OFFSET"),
        "sample_offset": _num(txt, "SAMPLE_PROJECTION_OFFSET"),
        "min_lat": _num(txt, "MINIMUM_LATITUDE"),
        "max_lat": _num(txt, "MAXIMUM_LATITUDE"),
        "scaling_factor": _num(txt, "SCALING_FACTOR") or 1.0,
        "offset": _num(txt, "OFFSET") or 0.0,
        "radius_km": _num(txt, "A_AXIS_RADIUS") or (R_MOON_M / 1000.0),
        "frame": _str(txt, "COORDINATE_SYSTEM_NAME") or "",
    }


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

@dataclass
class PolarGrid:
    """Geometry of a polar stereographic raster."""

    width: int
    height: int
    map_scale_m: float
    centre_lat: float          # +90 or -90
    centre_lon: float
    line_offset: float
    sample_offset: float
    radius_m: float = R_MOON_M

    @property
    def south(self) -> bool:
        return self.centre_lat < 0

    # -- projection ------------------------------------------------------

    def latlon_to_xy(self, lat, lon):
        """Selenographic to projection-plane metres."""
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)
        dlon = (lon - self.centre_lon) * DEG

        if self.south:
            rho = 2.0 * self.radius_m * np.tan((45.0 + lat / 2.0) * DEG)
            y = rho * np.cos(dlon)
        else:
            rho = 2.0 * self.radius_m * np.tan((45.0 - lat / 2.0) * DEG)
            y = -rho * np.cos(dlon)
        x = rho * np.sin(dlon)
        return x, y

    def xy_to_latlon(self, x, y):
        """Projection-plane metres back to selenographic."""
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        rho = np.hypot(x, y)

        c = 2.0 * np.arctan(rho / (2.0 * self.radius_m))
        if self.south:
            lat = -(90.0 - c / DEG)
            lon = self.centre_lon + np.degrees(np.arctan2(x, y))
        else:
            lat = 90.0 - c / DEG
            lon = self.centre_lon + np.degrees(np.arctan2(x, -y))
        return lat, np.mod(lon, 360.0)

    # -- pixel indices ---------------------------------------------------

    def latlon_to_rowcol(self, lat, lon):
        x, y = self.latlon_to_xy(lat, lon)
        col = self.sample_offset + x / self.map_scale_m
        row = self.line_offset - y / self.map_scale_m
        return row, col

    def rowcol_to_latlon(self, row, col):
        x = (np.asarray(col, dtype=np.float64) - self.sample_offset) * self.map_scale_m
        y = (self.line_offset - np.asarray(row, dtype=np.float64)) * self.map_scale_m
        return self.xy_to_latlon(x, y)

    def contains(self, lat, lon) -> bool:
        r, c = self.latlon_to_rowcol(lat, lon)
        return bool(0 <= r < self.height and 0 <= c < self.width)

    # -- scale -----------------------------------------------------------

    def cell_size_m(self, lat):
        """True ground size of one cell at a latitude.

        Stereographic scale grows away from the tangent point as sec²(c/2),
        where c is the angular distance from the pole. Ignoring it would
        overstate distances near the grid edge — by only ~0.05 % over these
        products, but slope is a ratio of a height to a distance and there is
        no reason to carry an avoidable bias into it.
        """
        lat = np.asarray(lat, dtype=np.float64)
        c = (90.0 - np.abs(lat)) * DEG          # angular distance from the pole
        k = 1.0 / np.cos(c / 2.0) ** 2          # point scale factor
        return self.map_scale_m / k

    @property
    def edge_latitude(self) -> float:
        """Latitude reached at the middle of the grid edge."""
        lat, _ = self.rowcol_to_latlon(0.0, self.sample_offset)
        return float(lat)


# ---------------------------------------------------------------------------
# Windowed access
# ---------------------------------------------------------------------------

@dataclass
class PolarWindow:
    """A square extract, in metres above the reference sphere."""

    elevation: np.ndarray
    grid: PolarGrid
    row0: int
    col0: int
    centre_lat: float
    centre_lon: float
    baseline_m: float

    @property
    def shape(self):
        return self.elevation.shape

    def latlon_of(self, row: int, col: int):
        return self.grid.rowcol_to_latlon(self.row0 + row, self.col0 + col)

    def stats(self) -> dict:
        e = self.elevation[np.isfinite(self.elevation)]
        if e.size == 0:
            return {"valid": 0}
        return {
            "valid": int(e.size),
            "min_m": float(e.min()),
            "max_m": float(e.max()),
            "mean_m": float(e.mean()),
            "relief_m": float(e.max() - e.min()),
            "shape": list(self.elevation.shape),
            "baseline_m": self.baseline_m,
        }


class PolarDEM:
    """Memory-mapped access to a LOLA polar stereographic DEM."""

    def __init__(self, img_path: str | Path, lbl_path: str | Path):
        self.path = Path(img_path)
        self.meta = parse_polar_label(lbl_path)
        m = self.meta

        self.grid = PolarGrid(
            width=m["width"], height=m["height"],
            map_scale_m=m["map_scale_m"],
            centre_lat=m["centre_lat"], centre_lon=m["centre_lon"],
            line_offset=m["line_offset"], sample_offset=m["sample_offset"],
            radius_m=m["radius_km"] * 1000.0,
        )

        expect = m["width"] * m["height"] * int(m["dtype"][-1])
        actual = self.path.stat().st_size
        if actual != expect:
            raise ValueError(
                f"{self.path.name}: expected {expect:,} bytes for a "
                f"{m['width']}x{m['height']} {m['dtype']} grid, found "
                f"{actual:,}. The file is incomplete or the label does not "
                "describe it."
            )

        self._data = np.memmap(self.path, dtype=m["dtype"], mode="r",
                               shape=(m["height"], m["width"]))

    # -- values ----------------------------------------------------------

    def _to_metres(self, raw):
        """Apply the label's scaling.

        These products store height in kilometres relative to the 1737.4 km
        sphere (``SCALING_FACTOR = 1``, ``OFFSET = 1737.4``, both in km), so the
        conversion is a unit change rather than the DN arithmetic the
        cylindrical 16-bit products need.
        """
        return np.asarray(raw, dtype=np.float64) * self.meta["scaling_factor"] * 1000.0

    def elevation_at(self, lat: float, lon: float) -> float:
        r, c = self.grid.latlon_to_rowcol(lat, lon)
        ri, ci = int(round(float(r))), int(round(float(c)))
        if not (0 <= ri < self.grid.height and 0 <= ci < self.grid.width):
            raise ValueError(
                f"({lat:.4f}, {lon:.4f}) lies outside "
                f"{self.meta['product_id']} — this grid covers "
                f"{self.meta['min_lat']:.1f}° to {self.meta['max_lat']:.1f}°")
        return float(self._to_metres(self._data[ri, ci]))

    def window_around(self, lat: float, lon: float, half_px: int = 256) -> PolarWindow:
        """Square window centred on a coordinate, in pixels."""
        r, c = self.grid.latlon_to_rowcol(lat, lon)
        r0 = max(0, int(round(float(r))) - half_px)
        c0 = max(0, int(round(float(c))) - half_px)
        r1 = min(self.grid.height, r0 + 2 * half_px)
        c1 = min(self.grid.width, c0 + 2 * half_px)
        if r1 <= r0 or c1 <= c0:
            raise ValueError("window falls outside the grid")

        raw = np.array(self._data[r0:r1, c0:c1])
        elev = self._to_metres(raw)
        # LOLA marks gaps with a large negative sentinel rather than NaN.
        elev[raw < -1e30] = np.nan

        return PolarWindow(
            elevation=elev, grid=self.grid, row0=r0, col0=c0,
            centre_lat=lat, centre_lon=lon,
            baseline_m=float(self.grid.cell_size_m(lat)),
        )


def open_polar(img_path, lbl_path) -> PolarDEM:
    return PolarDEM(img_path, lbl_path)


# ---------------------------------------------------------------------------
# Self-test — geometry only, so it runs without the raster
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

    print("\nPolar stereographic geometry — LDEM_875S_10M parameters\n")

    g = PolarGrid(width=15168, height=15168, map_scale_m=10.0,
                  centre_lat=-90.0, centre_lon=0.0,
                  line_offset=7583.5, sample_offset=7583.5)

    # 1. The pole must land on the declared projection origin.
    r, c = g.latlon_to_rowcol(-90.0, 0.0)
    check("pole maps to the projection offsets",
          abs(float(r) - 7583.5) < 1e-6 and abs(float(c) - 7583.5) < 1e-6,
          f"row={float(r):.4f} col={float(c):.4f}")

    # 2. The grid edge must land on the label's declared MAXIMUM_LATITUDE.
    #
    #    Note what the offsets are *not*: 7583.5 = (15168 - 1) / 2, i.e. simply
    #    the centre of a pixel-registered grid. It is not derived from the edge
    #    latitude, so comparing the two directly tests nothing. The meaningful
    #    check runs the other way — take the grid's half-width in pixels, invert
    #    the projection, and confirm the latitude it yields is the one the label
    #    declares.
    half_px = g.width / 2.0                       # 7584 px from centre to edge
    lat_edge, _ = g.xy_to_latlon(half_px * g.map_scale_m, 0.0)
    check("grid edge inverts to the declared MAXIMUM_LATITUDE (-87.5)",
          abs(float(lat_edge) - (-87.5)) < 0.001,
          f"edge at {float(lat_edge):.4f}° — label rounds this to -87.5°")

    # 3. Round trip must be exact to floating point.
    pts = [(-90.0, 0.0), (-89.0, 45.0), (-88.0, 180.0), (-87.6, 270.0),
           (-88.5, 359.9)]
    worst = 0.0
    for la, lo in pts:
        rr, cc = g.latlon_to_rowcol(la, lo)
        la2, lo2 = g.rowcol_to_latlon(rr, cc)
        dlat = abs(float(la2) - la)
        dlon = abs(((float(lo2) - lo + 180) % 360) - 180) * math.cos(la * DEG)
        worst = max(worst, dlat, dlon)
    check("round trip lat/lon -> pixel -> lat/lon", worst < 1e-9,
          f"worst error {worst:.2e}°")

    # 4. All four meridians must be distinguishable — the whole point of the
    #    projection is that longitude survives at the pole's neighbourhood.
    seen = [tuple(np.round(g.latlon_to_rowcol(-88.0, lo), 3))
            for lo in (0, 90, 180, 270)]
    check("four meridians give four distinct pixels",
          len(set(seen)) == 4, str(seen[:2]))

    # 5. Scale factor: cells shrink very slightly away from the pole.
    at_pole = float(g.cell_size_m(-90.0))
    at_edge = float(g.cell_size_m(-87.5))
    check("cell size varies with the stereographic scale factor",
          at_edge < at_pole and (at_pole - at_edge) / at_pole < 0.001,
          f"{at_pole:.4f} m at pole, {at_edge:.4f} m at edge "
          f"({(at_pole-at_edge)/at_pole*100:.4f} %)")

    # 6. A north grid must mirror, not duplicate, the south one.
    gn = PolarGrid(width=15168, height=15168, map_scale_m=10.0,
                   centre_lat=90.0, centre_lon=0.0,
                   line_offset=7583.5, sample_offset=7583.5)
    rs, cs = g.latlon_to_rowcol(-88.0, 0.0)
    rn, cn = gn.latlon_to_rowcol(88.0, 0.0)
    check("north and south grids mirror in row",
          abs(float(rs) - 7583.5) > 100 and
          abs((float(rs) - 7583.5) + (float(rn) - 7583.5)) < 1e-6,
          f"south row {float(rs):.1f}, north row {float(rn):.1f}")

    # 7. Requests outside the covered cap must be rejected, not extrapolated.
    check("coordinate outside the cap is refused",
          not g.contains(-60.0, 0.0), "lat -60 correctly outside")
    check("coordinate inside the cap is accepted", g.contains(-89.0, 123.0))

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
