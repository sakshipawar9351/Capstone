"""Verify /terrain/grid: layout, orientation, and agreement with point sampling."""
import struct
import time

import numpy as np
import requests

B = "http://127.0.0.1:8765/api/v1"
s = requests.Session()
for _ in range(60):
    try:
        s.get(B + "/meta/health", timeout=3)
        break
    except Exception:
        time.sleep(0.5)
else:
    raise SystemExit("server did not start")

npass = nfail = 0


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


def grid(south, north, west, east, w=129, h=129):
    r = s.get(B + "/terrain/grid", params=dict(
        south=south, north=north, west=west, east=east, width=w, height=h),
        timeout=180)
    r.raise_for_status()
    a = np.frombuffer(r.content, dtype="<f4").reshape(
        int(r.headers["X-Height"]), int(r.headers["X-Width"]))
    return a, r.headers


print("\n/terrain/grid — layout and orientation\n")

# Window over Tycho: 43.31 S, 348.68 E, D = 85 km ~ 2.8 deg
a, h = grid(-45.0, -41.5, 347.0, 350.4)
check("byte count matches declared shape",
      a.shape == (129, 129), f"{a.shape}, {len(a.tobytes())} bytes")
check("float32 little-endian decodes to sane elevations",
      -10000 < a.min() < a.max() < 12000,
      f"{a.min():.0f} … {a.max():.0f} m")
check("headers report the same range",
      abs(float(h["X-Min-M"]) - a.min()) < 1 and
      abs(float(h["X-Max-M"]) - a.max()) < 1,
      f"hdr {h['X-Min-M']} / {h['X-Max-M']}")

# Orientation must be tested over a whole edge, not a single sample.
# The grid is bilinear over 1.9 km cells; a point query is nearest-neighbour.
# On a crater wall those two legitimately differ by hundreds of metres, so a
# single-point comparison tests interpolation, not orientation. Correlating a
# full transect isolates the thing actually under test: which way the axes run.
def point(lat, lon):
    return s.get(B + "/terrain/point",
                 params={"lat": lat, "lon": lon}, timeout=60).json()["elevation_m"]


def transect(name, grid_line, lats, lons):
    ref = np.array([point(la, lo) for la, lo in zip(lats, lons)])
    g = np.asarray(grid_line, dtype=float)
    r = float(np.corrcoef(g, ref)[0, 1])
    bias = float(np.mean(g - ref))
    check(f"{name}  r={r:.3f}  bias={bias:+.0f} m",
          r > 0.95 and abs(bias) < 200,
          f"range {ref.min():.0f}…{ref.max():.0f} m")


# Orientation is checked over Mare Serenitatis, deliberately: it is smooth, so
# bilinear and nearest-neighbour sampling agree and any residual disagreement
# can only come from the axis mapping itself. Testing orientation on Tycho's
# rim would measure interpolation error, not orientation.
S, Nn, W, E = 22.0, 30.0, 15.0, 23.0
b, _ = grid(S, Nn, W, E)
N = 13
idx = np.linspace(0, 128, N).astype(int)
lo_line = np.linspace(W, E, N)
la_line = np.linspace(Nn, S, N)

transect("row 0 runs W->E along the NORTH edge",
         b[0, idx], np.full(N, Nn), lo_line)
transect("last row runs W->E along the SOUTH edge",
         b[-1, idx], np.full(N, S), lo_line)
transect("col 0 runs N->S along the WEST edge",
         b[idx, 0], la_line, np.full(N, W))
transect("last col runs N->S along the EAST edge",
         b[idx, -1], la_line, np.full(N, E))

# A grid whose axes were transposed or flipped would still correlate along
# individual edges by chance on smooth ground, so assert the corners directly.
check("NW corner is north-west",
      abs(float(b[0, 0]) - point(Nn, W)) < 120,
      f"{float(b[0,0]):.0f} vs {point(Nn, W):.0f} m")
check("SE corner is south-east",
      abs(float(b[-1, -1]) - point(S, E)) < 120,
      f"{float(b[-1,-1]):.0f} vs {point(S, E):.0f} m")

print("\nDoes the grid actually contain Tycho?\n")
# Tycho's floor should be several km below its rim within this window.
relief = a.max() - a.min()
check("window relief consistent with a 4.5 km crater",
      2500 < relief < 9000, f"{relief:.0f} m")
centre = a[56:73, 56:73].mean()
rim_ring = np.concatenate([a[20:30, :].ravel(), a[-30:-20, :].ravel()])
check("crater centre sits below the surrounding terrain",
      centre < rim_ring.mean(), f"centre {centre:.0f} m vs around {rim_ring.mean():.0f} m")

print("\nDisplacement magnitude at the exaggerations offered\n")
R = 1737400.0
# Patch width for this window, for judging whether relief reads as terrain
# rather than as spikes.
patch_km = 3.4 * np.pi * 1737.4 / 180
print(f"  patch is ~{patch_km:.0f} km across, true relief {relief/1000:.1f} km "
      f"(aspect 1:{patch_km*1000/relief:.0f})")
for ex in (0, 1, 3, 6, 12):
    print(f"  {ex:>2}×  ->  {relief*ex/1000:>6.1f} km apparent "
          f"({(relief*ex)/R*100:>5.2f} % of radius, "
          f"aspect 1:{patch_km*1000/max(relief*ex, 1):.0f})")
check("default 3x keeps displacement under 1% of radius",
      (relief * 3) / R < 0.01, f"{(relief*3)/R*100:.2f} %")
check("max 12x stays under 4% of radius",
      (relief * 12) / R < 0.04, f"{(relief*12)/R*100:.2f} %")

print("\nSeam handling (window crossing 0/360)\n")
a2, _ = grid(-2.0, 2.0, 358.0, 362.0, 65, 65)
check("window across the prime meridian returns finite data",
      np.isfinite(a2).all() and a2.std() > 1,
      f"std {a2.std():.1f} m, range {a2.min():.0f}…{a2.max():.0f}")

print("\nPerformance\n")
t0 = time.time()
for _ in range(5):
    grid(-45, -41.5, 347, 350.4)
dt = (time.time() - t0) / 5 * 1000
check("grid served fast enough for interactive use", dt < 400, f"{dt:.0f} ms avg")

print(f"\n{npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
