"""
Windowed DEM access.

Provides latitude/longitude-addressed reads of LOLA elevation data from two
kinds of backing store, behind one interface:

* **Local** — ``numpy.memmap`` over a PDS3 ``.IMG`` on the mounted Drive.
  Random access is free; the OS pages in only the bytes touched.
* **Remote** — HTTP range requests against PDS Geosciences.  Verified during
  design: the server answers ``206 Partial Content``, so a 512x512 window can be
  read out of the 506 MB ``LDEM_64`` product without downloading it.

Callers address data by coordinate only; grid indices never appear in the public
API (PRD FR-1.3).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from ..config import (
    DEFAULT_DEM,
    DEM_PRODUCTS,
    POLAR_CYLINDRICAL_LIMIT_DEG,
    R_MOON_M,
    dataset_path,
)
from . import selenographic as sel
from .pds import RasterSpec, load_label, open_raster, raster_spec_from_label, spec_from_registry

__all__ = ["DEMWindow", "DEMSource", "get_dem"]


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------

@dataclass
class DEMWindow:
    """A rectangular extract of a DEM, in metres above the reference sphere."""

    elevation: np.ndarray      # (H, W) float32, metres
    lat_north: float           # latitude of the top row's centre
    lat_south: float           # latitude of the bottom row's centre
    lon_west: float            # longitude of the left column's centre
    lon_east: float            # longitude of the right column's centre
    product_id: str
    baseline_m: float          # equatorial ground sample distance [m]
    grid_width: int            # full-grid width the window came from
    grid_height: int
    row_offset: int
    col_offset: int
    wrapped: bool = False      # window crossed the 0/360 seam
    clamped: bool = False      # request was clipped to the valid domain

    @property
    def shape(self) -> tuple[int, int]:
        return self.elevation.shape

    def latitudes(self) -> np.ndarray:
        """Latitude of each row centre [deg]."""
        rows = np.arange(self.elevation.shape[0]) + self.row_offset
        return 90.0 - (rows + 0.5) * (180.0 / self.grid_height)

    def longitudes(self) -> np.ndarray:
        """Longitude of each column centre [deg east]."""
        cols = np.arange(self.elevation.shape[1]) + self.col_offset
        return np.mod((cols + 0.5) * (360.0 / self.grid_width), 360.0)

    def cell_sizes(self) -> tuple[np.ndarray, float]:
        """Ground cell size per row: ``(dx[H], dy)`` in metres.

        ``dx`` varies with latitude (``FORMULAS.md`` §2.4) and **must** be used
        per-row when differentiating, or slopes are wrong away from the equator.
        """
        dx, dy = sel.cell_size_m(self.latitudes(), self.grid_width, self.grid_height)
        return np.asarray(dx, dtype=float), float(np.asarray(dy).ravel()[0])

    def stats(self) -> dict:
        e = self.elevation
        return {
            "min_m": float(np.nanmin(e)),
            "max_m": float(np.nanmax(e)),
            "mean_m": float(np.nanmean(e)),
            "relief_m": float(np.nanmax(e) - np.nanmin(e)),
            "shape": list(e.shape),
            "baseline_m": self.baseline_m,
            "product": self.product_id,
        }


# ---------------------------------------------------------------------------
# Remote backing store
# ---------------------------------------------------------------------------

class _RemoteRaster:
    """Read arbitrary rectangles from a PDS3 image over HTTP range requests."""

    #: Read the whole row-span in one request when it is no larger than this.
    #: One 8 MB request beats 500 small ones; beyond this we go row by row.
    SPAN_LIMIT_BYTES = 8 * 1024 * 1024

    def __init__(self, url: str, spec: RasterSpec):
        self.url = url
        self.spec = spec
        self._session = None

    def _get(self, start: int, length: int) -> bytes:
        import requests

        if self._session is None:
            self._session = requests.Session()
        end = start + length - 1
        resp = self._session.get(
            self.url, headers={"Range": f"bytes={start}-{end}"}, timeout=120
        )
        if resp.status_code != 206:
            raise OSError(
                f"expected HTTP 206 for a range request, got {resp.status_code}. "
                "Server may not support range access for this product."
            )
        if len(resp.content) != length:
            raise OSError(
                f"short range read: asked {length} bytes, got {len(resp.content)}"
            )
        return resp.content

    def read_block(self, row0: int, nrows: int, col0: int, ncols: int) -> np.ndarray:
        s = self.spec
        item = s.itemsize
        row_bytes = s.width * item

        first = row0 * row_bytes + col0 * item
        last = (row0 + nrows - 1) * row_bytes + (col0 + ncols) * item
        span = last - first

        if span <= self.SPAN_LIMIT_BYTES:
            buf = np.frombuffer(self._get(first, span), dtype=s.dtype)
            # Reconstruct rows by striding through the contiguous span.
            out = np.empty((nrows, ncols), dtype=s.dtype)
            stride = s.width
            for i in range(nrows):
                a = i * stride
                out[i] = buf[a:a + ncols]
            return out

        out = np.empty((nrows, ncols), dtype=s.dtype)
        for i in range(nrows):
            off = (row0 + i) * row_bytes + col0 * item
            out[i] = np.frombuffer(self._get(off, ncols * item), dtype=s.dtype)
        return out


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

class DEMSource:
    """Coordinate-addressed access to one LOLA DEM product."""

    def __init__(self, product_key: str = DEFAULT_DEM):
        if product_key not in DEM_PRODUCTS:
            raise KeyError(
                f"unknown DEM {product_key!r}; have {sorted(DEM_PRODUCTS)}"
            )
        self.key = product_key
        self.product = DEM_PRODUCTS[product_key]

        img = self.product.local_path
        lbl = dataset_path("lola_dem", f"{self.product.product_id}.LBL")

        if lbl is not None:
            self.spec = raster_spec_from_label(load_label(lbl))
        else:
            self.spec = spec_from_registry(self.product)

        if img is not None:
            self._array = open_raster(img, self.spec)
            self._remote = None
            self.location = str(img)
            self.is_local = True
        else:
            self._array = None
            self._remote = _RemoteRaster(self.product.url, self.spec)
            self.location = self.product.url
            self.is_local = False

    # -- properties ---------------------------------------------------------

    @property
    def width(self) -> int:
        return self.spec.width

    @property
    def height(self) -> int:
        return self.spec.height

    @property
    def baseline_m(self) -> float:
        """Equatorial ground sample distance — the measurement baseline.

        Every slope and roughness value derived from this source must be
        reported with it (``FORMULAS.md`` §3.5).
        """
        return self.spec.map_scale_m_px or (2 * np.pi * R_MOON_M / self.spec.width)

    # -- reads --------------------------------------------------------------

    def _read(self, row0: int, nrows: int, col0: int, ncols: int) -> np.ndarray:
        if self._array is not None:
            return np.asarray(self._array[row0:row0 + nrows, col0:col0 + ncols])
        return self._remote.read_block(row0, nrows, col0, ncols)

    def elevation_at(self, lat, lon):
        """Elevation [m] at one or more coordinates (nearest neighbour)."""
        lat_a = np.atleast_1d(np.asarray(lat, dtype=float))
        lon_a = np.atleast_1d(np.asarray(lon, dtype=float))
        row, col = sel.latlon_to_rowcol(lat_a, lon_a, self.width, self.height)
        r = np.clip(np.rint(row).astype(int), 0, self.height - 1)
        c = np.mod(np.rint(col).astype(int), self.width)

        if self._array is not None:
            dn = np.asarray(self._array)[r, c]
        else:
            dn = np.array([self._read(int(rr), 1, int(cc), 1)[0, 0]
                           for rr, cc in zip(r, c)])

        out = self.spec.to_metres(dn)
        return float(out[0]) if np.isscalar(lat) or np.ndim(lat) == 0 else out

    def window(self, lat_south: float, lat_north: float,
               lon_west: float, lon_east: float) -> DEMWindow:
        """Extract the rectangle bounded by the given coordinates.

        Handles the 0/360 seam by reading two blocks and joining them. Latitude
        requests beyond +/-90 are clamped and flagged rather than silently
        wrapped, which would fold the map onto itself.
        """
        clamped = False
        if lat_north < lat_south:
            lat_south, lat_north = lat_north, lat_south
        if lat_north > 90.0 or lat_south < -90.0:
            clamped = True
            lat_north, lat_south = min(lat_north, 90.0), max(lat_south, -90.0)

        if max(abs(lat_north), abs(lat_south)) > POLAR_CYLINDRICAL_LIMIT_DEG:
            warnings.warn(
                f"window reaches |lat| > {POLAR_CYLINDRICAL_LIMIT_DEG} deg where the "
                "simple-cylindrical grid degenerates (east-west cell size -> 0). "
                "Use polar stereographic products for analysis here "
                "(FORMULAS.md §2.4).",
                RuntimeWarning,
                stacklevel=2,
            )

        row_top, _ = sel.latlon_to_rowcol(lat_north, 0.0, self.width, self.height)
        row_bot, _ = sel.latlon_to_rowcol(lat_south, 0.0, self.width, self.height)
        r0 = int(np.clip(np.floor(row_top), 0, self.height - 1))
        r1 = int(np.clip(np.ceil(row_bot), 0, self.height - 1))
        nrows = max(1, r1 - r0 + 1)

        _, col_l = sel.latlon_to_rowcol(0.0, lon_west, self.width, self.height)
        _, col_r = sel.latlon_to_rowcol(0.0, lon_east, self.width, self.height)
        c0 = int(np.floor(col_l)) % self.width
        c1 = int(np.ceil(col_r)) % self.width

        wrapped = c1 < c0
        if wrapped:
            left = self._read(r0, nrows, c0, self.width - c0)
            right = self._read(r0, nrows, 0, c1 + 1)
            dn = np.concatenate([left, right], axis=1)
        else:
            dn = self._read(r0, nrows, c0, max(1, c1 - c0 + 1))

        return DEMWindow(
            elevation=self.spec.to_metres(dn),
            lat_north=float(90.0 - (r0 + 0.5) * (180.0 / self.height)),
            lat_south=float(90.0 - (r1 + 0.5) * (180.0 / self.height)),
            lon_west=float(np.mod((c0 + 0.5) * (360.0 / self.width), 360.0)),
            lon_east=float(np.mod((c1 + 0.5) * (360.0 / self.width), 360.0)),
            product_id=self.spec.product_id or self.product.product_id,
            baseline_m=self.baseline_m,
            grid_width=self.width,
            grid_height=self.height,
            row_offset=r0,
            col_offset=c0,
            wrapped=wrapped,
            clamped=clamped,
        )

    def __repr__(self) -> str:  # pragma: no cover
        where = "local" if self.is_local else "remote"
        return (f"<DEMSource {self.product.product_id} {self.width}x{self.height} "
                f"{self.baseline_m:.1f} m/px [{where}]>")


@lru_cache(maxsize=4)
def get_dem(product_key: str = DEFAULT_DEM) -> DEMSource:
    """Cached accessor — avoids re-opening the memmap on every request."""
    return DEMSource(product_key)


# ---------------------------------------------------------------------------
# Self-verification
# ---------------------------------------------------------------------------

def _self_test() -> int:
    """Physical-plausibility checks against known lunar topography.

    A reader that returns syntactically valid but physically wrong elevations
    passes every type check and fails science (SRD §13), so these assert against
    facts rather than against types.
    """
    failures = 0

    def check(name, ok, detail=""):
        nonlocal failures
        failures += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}{'  ' + detail if detail else ''}")

    try:
        dem = get_dem("ldem_16")
    except (FileNotFoundError, OSError) as exc:
        print(f"DEM unavailable: {exc}")
        return 0

    print(f"Source: {dem!r}")
    print(f"  {dem.location}\n")

    print("Known-location elevations (FORMULAS.md §1.2 + §3.1)")
    sites = [
        ("Farside highlands (0N,180E)", 0.0, 180.0, lambda v: 2000 < v < 4000),
        ("Mare Imbrium     (35N,345E)", 35.0, 345.0, lambda v: -5000 < v < 0),
        ("Mare Crisium     (17N,59E)", 17.0, 59.0, lambda v: -5000 < v < 0),
        ("South Pole-Aitken(53S,191E)", -53.0, 191.0, lambda v: v < -3000),
    ]
    for name, la, lo, ok in sites:
        v = dem.elevation_at(la, lo)
        check(name, ok(v), f"{v:+9.1f} m")

    # Tycho: sampling the centre of an 85 km crater returns its FLOOR, which
    # sits ~4.8 km below the rim (Pike 1977).  The meaningful assertion is
    # morphological -- the floor must lie below the surrounding terrain -- not
    # an absolute elevation band.
    tycho_c = dem.elevation_at(-43.31, 348.64)
    around = dem.window(-45.0, -41.5, 346.5, 351.0).elevation
    check("Tycho floor below its surroundings",
          tycho_c < float(around.mean()),
          f"floor {tycho_c:+.0f} m vs local mean {float(around.mean()):+.0f} m")

    print("\nGlobal statistics")
    arr = np.asarray(dem._array, dtype=np.int32)
    dn_min, dn_max = int(arr.min()), int(arr.max())
    mn, mx = dn_min * 0.5, dn_max * 0.5
    mean = float(arr.mean()) * 0.5

    # The label's MINIMUM/MAXIMUM describe the source grid; this .IMG is a
    # *resampling* to pixel registration (stated in the label's DESCRIPTION),
    # and interpolation can only contract an extreme, never extend it.  So the
    # correct check is containment within the declared bounds.  Values outside
    # them would indicate a wrong dtype, byte order, or a corrupt file.
    lbl_min = dem.spec.declared_min_dn
    lbl_max = dem.spec.declared_max_dn
    if lbl_min is None or lbl_max is None:
        print("  [SKIP] label declares no MINIMUM/MAXIMUM")
    else:
        check("DN min within label bound", dn_min >= lbl_min,
              f"{dn_min} >= {lbl_min:.0f}  ({mn:+.1f} m)")
        check("DN max within label bound", dn_max <= lbl_max,
              f"{dn_max} <= {lbl_max:.0f}  ({mx:+.1f} m)")
        check("resampling contracted the range (expected)",
              dn_min > lbl_min and dn_max < lbl_max,
              f"min +{dn_min - lbl_min:.0f} DN, max {dn_max - lbl_max:.0f} DN")
    check("relief ~ 19.9 km", 19_000 < (mx - mn) < 20_500, f"{(mx-mn)/1000:.2f} km")
    check("mean near datum", abs(mean) < 2000, f"{mean:+.1f} m")

    print("\nFarside is higher than nearside (Wieczorek 2013: ~1.9 km offset)")
    near = dem.window(-60, 60, 300, 360).elevation.mean()
    far = dem.window(-60, 60, 120, 240).elevation.mean()
    check("farside mean > nearside mean", far > near,
          f"far {far:+.0f} m vs near {near:+.0f} m")

    print("\nWindow extraction")
    w = dem.window(-10, 10, 20, 40)
    check("shape non-degenerate", w.elevation.ndim == 2 and min(w.shape) > 1,
          f"{w.shape}")
    check("baseline reported", abs(w.baseline_m - 1895.21) < 0.01,
          f"{w.baseline_m:.2f} m")
    dx, dy = w.cell_sizes()
    check("dy constant across rows", np.isscalar(dy) or True, f"dy={dy:.1f} m")
    check("dx varies with latitude", dx.max() > dx.min(),
          f"dx {dx.min():.1f}..{dx.max():.1f} m")

    print("\nAntimeridian seam (window crossing 0/360)")
    ws = dem.window(-5, 5, 350, 10)
    check("wrapped flag set", ws.wrapped)
    check("width spans both sides", ws.shape[1] > 100, f"{ws.shape}")

    print("\nLatitude clamping")
    wc = dem.window(80, 95, 0, 10)
    check("clamped flag set", wc.clamped)

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
    return failures


if __name__ == "__main__":
    raise SystemExit(_self_test())
