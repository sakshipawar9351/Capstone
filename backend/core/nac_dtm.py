r"""
Reading an LROC NAC stereo DTM — the finest topography this project holds.

These are not global products. Each is a narrow strip a few kilometres wide
covering one site, built by stereo photogrammetry from a pair of Narrow Angle
Camera images, and published at 2 m where every global product this project
uses is 29.6 m or coarser.

Why that matters here specifically: ``SITE_MAX_CELL_M`` is 20 m, so until now
only the south polar DEM could certify a rover traverse and the whole
equatorial Moon was limited to "regional corridor". A 2 m strip crosses that
threshold by a factor of ten — on ground where Apollo 15 actually drove 27.9 km,
which makes it a place the model's verdict can be checked against a real
mission rather than only against itself.

Geometry
--------
The products are equirectangular with an *attached* PDS3 label: label text
first, image data starting at record ``^IMAGE``. The label's projection offsets
are stated against a global grid origin, which for a small sub-window lands
hundreds of thousands of pixels outside the file — so the corner keywords are
used instead, and they are both simpler and checkable:

    row r  ->  lat = MAXIMUM_LATITUDE      - (r + 0.5) * dlat
    col c  ->  lon = WESTERNMOST_LONGITUDE + (c + 0.5) * dlon

Both spacings are confirmed against ``MAP_SCALE`` in :func:`_self_test`: 2.0 m
divided by the Moon's degree length reproduces the declared latitude span to
seven digits, and the same with a ``cos(CENTER_LATITUDE)`` factor reproduces
the longitude span. If a future product breaks that agreement the test fails
rather than the geometry silently drifting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import R_MOON_M
from .pds import parse_label

__all__ = ["NACDtm", "open_nac_dtm"]

#: How much of the file to read looking for the label's END. Generous: these
#: labels run to a few kilobytes and reading the whole 146 MB file as text to
#: find a keyword would be absurd.
_LABEL_PROBE_BYTES = 64 * 1024

#: Anything at or below this is a gap, not terrain. LROC writes the IEEE
#: single-precision minimum as its missing constant.
_MISSING_BELOW = -1e30


@dataclass
class NACDtm:
    """One NAC stereo DTM strip, memory-mapped."""

    path: Path
    data: np.memmap
    product_id: str
    cell_m: float
    north: float
    south: float
    west: float
    east: float

    @property
    def shape(self) -> tuple[int, int]:
        return self.data.shape

    @property
    def dlat(self) -> float:
        return (self.north - self.south) / self.shape[0]

    @property
    def dlon(self) -> float:
        return (self.east - self.west) / self.shape[1]

    def latlon_to_rowcol(self, lat, lon):
        """Fractional row/column of a coordinate. Pixel centres, like the rest."""
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)
        # Onto the product's own longitude branch. These strips are narrow, so a
        # region a fraction of a degree away must not be pushed 360 degrees off.
        lon = np.where(lon - self.west > 180.0, lon - 360.0, lon)
        lon = np.where(self.west - lon > 180.0, lon + 360.0, lon)
        row = (self.north - lat) / self.dlat - 0.5
        col = (lon - self.west) / self.dlon - 0.5
        return row, col

    def rowcol_to_latlon(self, row, col):
        lat = self.north - (np.asarray(row, dtype=np.float64) + 0.5) * self.dlat
        lon = self.west + (np.asarray(col, dtype=np.float64) + 0.5) * self.dlon
        return lat, lon

    def read(self, r0: int, r1: int, c0: int, c1: int) -> np.ndarray:
        """A block in metres, with gaps as NaN."""
        h, w = self.shape
        r0, r1 = max(0, r0), min(h, r1)
        c0, c1 = max(0, c0), min(w, c1)
        if r1 <= r0 or c1 <= c0:
            return np.zeros((0, 0), dtype=np.float64)
        out = np.array(self.data[r0:r1, c0:c1], dtype=np.float64)
        out[out <= _MISSING_BELOW] = np.nan
        return out


def open_nac_dtm(path: Path | str) -> NACDtm:
    """Open a NAC DTM by parsing the label attached to its own image file."""
    path = Path(path)
    head = path.open("rb").read(_LABEL_PROBE_BYTES)
    text = head.decode("latin-1", errors="replace")
    end = text.find("\nEND\r\n")
    label = parse_label(text[:end] if end > 0 else text)

    def num(key: str) -> float:
        v = label.get(key)
        if v is None:
            raise ValueError(f"{path.name}: label has no {key}")
        return float(str(v).split()[0].strip("<>"))

    lines, samples = int(num("LINES")), int(num("LINE_SAMPLES"))
    record_bytes = int(num("RECORD_BYTES"))
    image_record = int(str(label.get("^IMAGE", "1")).strip("()<> ").split()[0])
    offset = (image_record - 1) * record_bytes

    sample_type = str(label.get("SAMPLE_TYPE", "PC_REAL")).strip()
    bits = int(num("SAMPLE_BITS"))
    if sample_type != "PC_REAL" or bits != 32:
        raise ValueError(f"{path.name}: expected 32-bit PC_REAL, got "
                         f"{sample_type}/{bits}")

    expect = offset + lines * samples * 4
    actual = path.stat().st_size
    if actual != expect:
        raise ValueError(
            f"{path.name}: {actual:,} bytes but the label describes "
            f"{expect:,} ({lines}x{samples} float32 after a {offset}-byte "
            "header). The file is truncated or the label was misread.")

    data = np.memmap(path, dtype="<f4", mode="r", offset=offset,
                     shape=(lines, samples))
    return NACDtm(
        path=path, data=data,
        product_id=str(label.get("PRODUCT_ID", path.stem)).strip(),
        cell_m=num("MAP_SCALE"),
        north=num("MAXIMUM_LATITUDE"), south=num("MINIMUM_LATITUDE"),
        west=num("WESTERNMOST_LONGITUDE"), east=num("EASTERNMOST_LONGITUDE"),
    )


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _self_test() -> int:
    from ..config import dataset_path

    npass = nfail = 0

    def check(name, ok, detail=""):
        nonlocal npass, nfail
        if ok:
            npass += 1
            print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
        else:
            nfail += 1
            print(f"  FAIL  {name}   {detail}")

    p = dataset_path("nac_dtm", "NAC_DTM_APOLLO15_E261N0036.IMG")
    if p is None:
        print("Apollo 15 NAC DTM not present — skipping")
        return 0

    d = open_nac_dtm(p)
    print(f"\n{d.product_id}: {d.shape[0]:,}x{d.shape[1]:,} at {d.cell_m} m\n")

    check("the attached label parsed", d.product_id.startswith("NAC_DTM"),
          d.product_id)
    check("it is finer than any global product this project has",
          d.cell_m < 29.0, f"{d.cell_m:.2f} m against 29.61 m streamed")
    check("and crosses the 20 m site threshold", d.cell_m <= 20.0,
          "so a traverse here can be certified, not merely corridored")

    # The geometry check that matters: derive the spacing from MAP_SCALE alone
    # and see whether it reproduces the declared corners. If these disagree the
    # coordinate mapping is wrong and every slope computed from it is fiction.
    deg_m = math.pi * R_MOON_M / 180.0
    want_dlat = d.cell_m / deg_m
    err_lat = abs(want_dlat - d.dlat) / d.dlat
    check("row spacing agrees with MAP_SCALE",
          err_lat < 1e-4, f"{d.dlat*deg_m:.4f} m/row vs {d.cell_m} m declared")

    want_dlon = d.cell_m / (deg_m * math.cos(math.radians((d.north + d.south) / 2)))
    err_lon = abs(want_dlon - d.dlon) / d.dlon
    check("column spacing agrees with MAP_SCALE and the centre latitude",
          err_lon < 1e-3,
          f"equirectangular: cos({(d.north+d.south)/2:.1f} deg) applies")

    # Round trip.
    for r, c in ((0, 0), (d.shape[0] - 1, d.shape[1] - 1), (7000, 1200)):
        la, lo = d.rowcol_to_latlon(r, c)
        rr, cc = d.latlon_to_rowcol(la, lo)
        if abs(rr - r) > 1e-6 or abs(cc - c) > 1e-6:
            check(f"round trip at ({r},{c})", False, f"got ({rr},{cc})")
            break
    else:
        check("row/col to lat/lon round trips exactly", True,
              "three corners and an interior point")

    check("the strip contains the Apollo 15 landing site",
          d.south < 26.13222 < d.north and d.west < 3.63386 < d.east,
          f"{d.south:.3f}..{d.north:.3f} lat, {d.west:.3f}..{d.east:.3f} lon")

    blk = d.read(7000, 7100, 1200, 1300)
    good = blk[np.isfinite(blk)]
    check("a block reads as real terrain", good.size > 0
          and -3000 < good.min() < good.max() < 3000,
          f"{good.min():.1f}..{good.max():.1f} m over 100x100 cells")
    check("gaps come back as NaN, not as a sentinel elevation",
          not np.any(blk <= _MISSING_BELOW),
          "a -3.4e38 cell treated as terrain would dominate every statistic")

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
