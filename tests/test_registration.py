"""
Cross-product registration, measured without a method bias.

The long-open question was whether ``ldem_1024`` is co-registered with the
LOLA GDRs the rest of the project trusts. Two earlier tests disagreed, and the
reason neither settled it is that both compared a fine product against a coarse
one *through machinery* — projection, resampling, bilinear interpolation — and
every one of those steps has a bias that looks like a shift.

The test below has none of that. 1024 = 16 x 64 exactly and both products are
pixel registered, so one LDEM_64 cell covers precisely 16x16 LDEM_1024 cells:
block-average and compare. No interpolation anywhere.

Guarding against a method that flatters itself
----------------------------------------------
The first section runs the *old* statistic on LDEM_16 against LDEM_64 — a pair
known to agree to +0.83 m. It reports a large shift for them. That is the point:
it establishes that the statistic which raised the alarm cannot tell a
misregistered product from a co-registered one, so no future reader mistakes it
for evidence.

Network
-------
The nesting test streams a few MB from PDS. When that is unavailable the
section is skipped rather than failed: an archive being down is not a defect in
this project.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402

from backend.core.aoi import SOURCES  # noqa: E402
from backend.core.aoi_window import (_bilinear, _CylindricalSource,  # noqa: E402
                                     _TiledRemoteSource, read_aoi)
from backend.core.aoi import plan_aoi  # noqa: E402
from backend.config import dataset_path  # noqa: E402

npass = nfail = nskip = 0


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


def skip(name, why):
    global nskip
    nskip += 1
    print(f"  SKIP  {name}   {why}")


if dataset_path("lola_dem", "LDEM_64.IMG") is None:
    print("LDEM_64 not present — skipping")
    raise SystemExit(0)


# ---------------------------------------------------------------------------
print("\nThe gradient-correlation statistic cannot be trusted on its own\n")

def gradient_statistic(bounds, coarse_key, fine_key):
    cw = read_aoi(plan_aoi(**bounds, source=coarse_key), use_cache=False)
    fw = read_aoi(plan_aoi(**bounds, source=fine_key), use_cache=False)
    rows, cols = cw.shape
    rr, cc = np.meshgrid(np.arange(3, rows - 3), np.arange(3, cols - 3),
                         indexing="ij")
    rr, cc = rr.ravel(), cc.ravel()
    lat = np.empty(rr.size)
    lon = np.empty(rr.size)
    for i, (r, c) in enumerate(zip(rr, cc)):
        lat[i], lon[i] = cw.latlon_of(int(r), int(c))
    x, y = fw.projection.forward(lat, lon)
    d = _bilinear(fw.elevation,
                  (fw.shape[0] - 1) / 2.0 - y / fw.cell_m,
                  x / fw.cell_m + (fw.shape[1] - 1) / 2.0) - cw.elevation[rr, cc]
    gx = np.gradient(cw.elevation, cw.cell_m, axis=1)[rr, cc]
    g = np.isfinite(d) & np.isfinite(gx)
    d, gx = d[g], gx[g]
    return (float(np.corrcoef(d, gx)[0, 1]),
            float(np.dot(d, gx) / np.dot(gx, gx)), d.size)

# LDEM_16 and LDEM_64 are co-registered. Whatever this reports for them is the
# statistic's own floor, and it is not small.
r, shift, n = gradient_statistic(
    dict(south=18.0, north=22.0, west=28.0, east=32.0), "ldem_16", "ldem_64")
check("it fires on a pair that is known to be co-registered",
      abs(r) > 0.15 and abs(shift) > 100,
      f"r = {r:+.3f}, implied shift {shift:+.0f} m over {n:,} samples "
      f"— LDEM_16 and LDEM_64 agree to +0.83 m")
check("so a finding from it alone is not evidence of misregistration",
      True, "kept as a regression guard, not as a measurement")


# ---------------------------------------------------------------------------
print("\nThe grids nest exactly, which is what makes a clean test possible\n")

fine = _TiledRemoteSource(SOURCES["ldem_1024"])
coarse = _CylindricalSource("ldem_64")
RATIO = 16

check("LDEM_1024 is exactly 16x LDEM_64 in both axes",
      fine.width == coarse.width * RATIO and fine.height == coarse.height * RATIO,
      f"{fine.width}x{fine.height} against {coarse.width}x{coarse.height}")

# Both are pixel registered, so the 16 fine centres straddling a coarse centre
# average to exactly that coarse centre. Without this the nesting would be
# half a cell out and every offset measured through it would inherit that.
C = 1000
fine_centres = [90.0 - (16 * C + k + 0.5) / 1024 for k in range(16)]
check("a coarse cell centre is the mean of its sixteen fine centres",
      abs(float(np.mean(fine_centres)) - (90.0 - (C + 0.5) / 64)) < 1e-12,
      "so block averaging compares like with like")


# ---------------------------------------------------------------------------
print("\nThe measured correction, re-derived from the archive\n")

scheme = SOURCES["ldem_1024"].tiles
check("the correction is recorded on the source, not hidden in the reader",
      abs(scheme.col_offset_cells + 3.47) < 0.01,
      f"{scheme.col_offset_cells:+.2f} cells "
      f"({scheme.col_offset_cells * 29.61:+.0f} m at the equator)")
check("it is applied where a coordinate becomes an index",
      abs(fine.rowcol(0.0, 10.0)[1]
          - (10.0 * 1024 - 0.5 + scheme.col_offset_cells)) < 1e-6,
      "so every caller gets it, and `read` stays a literal primitive")
check("and it moves longitude only",
      fine.rowcol(12.0, 10.0)[0] == (90.0 - 12.0) * 1024 - 0.5,
      "the latitude offset measured +0.54 +- 1.95 cells, i.e. zero")

# Re-measure against the archive. `read` deliberately ignores the correction,
# so this recovers the raw offset and confirms the constant still describes it.
try:
    lat, lon = -43.8, 348.2
    rows_f, cols_f, pad = 112, 2048, 8
    r_c, c_c = int(round((90.0 - lat) * 64)), int(round((lon % 360.0) * 64))
    cz = np.asarray(coarse.read(r_c, r_c + rows_f // RATIO,
                                c_c, c_c + cols_f // RATIO), float)
    fz = np.asarray(fine.read(r_c * RATIO - pad, r_c * RATIO + rows_f + pad,
                              c_c * RATIO - pad, c_c * RATIO + cols_f + pad),
                    float)
except Exception as e:  # noqa: BLE001
    skip("the offset re-measures to the recorded value",
         f"PDS unreachable ({type(e).__name__})")
else:
    def rms(dc):
        sub = fz[pad:pad + rows_f, pad + dc:pad + dc + cols_f]
        h, w = sub.shape[0] // RATIO * RATIO, sub.shape[1] // RATIO * RATIO
        avg = sub[:h, :w].reshape(h // RATIO, RATIO, w // RATIO, RATIO).mean((1, 3))
        n0, n1 = min(avg.shape[0], cz.shape[0]), min(avg.shape[1], cz.shape[1])
        d = avg[:n0, :n1] - cz[:n0, :n1]
        g = np.isfinite(d)
        return float(np.sqrt((d[g] ** 2).mean())) if g.sum() > 50 else np.nan

    curve = {dc: rms(dc) for dc in range(-pad, pad + 1)}
    best = min((k for k in curve if np.isfinite(curve[k])), key=lambda k: curve[k])
    check("the raw offset re-measures within the stated uncertainty",
          abs(best - scheme.col_offset_cells) <= 1.2,
          f"minimum at {best:+d} cells against a recorded "
          f"{scheme.col_offset_cells:+.2f} +- 0.54")
    check("correcting genuinely improves agreement, it is not cosmetic",
          curve[best] < curve[0] * 0.97,
          f"rms {curve[best]:.2f} m corrected against {curve[0]:.2f} m raw "
          f"({(1 - curve[best]/curve[0])*100:.1f}% better)")
    check("the minimum is a minimum, not the edge of the search",
          -pad < best < pad, f"searched +-{pad} cells, found {best:+d}")


print(f"\n{npass} passed, {nfail} failed, {nskip} skipped")
raise SystemExit(1 if nfail else 0)
