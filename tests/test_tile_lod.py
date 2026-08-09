"""Verify the mosaic endpoint delivers real resolution gains at each zoom."""
import io
import math
import time

import requests
from PIL import Image

B = "http://127.0.0.1:8765/api/v1"
s = requests.Session()

for _ in range(40):
    try:
        s.get(B + "/meta/health", timeout=3)
        break
    except Exception:
        time.sleep(0.5)
else:
    raise SystemExit("server did not start")

# A 4 deg window over the Copernicus region.
LAT, LON, HALF = 9.6, 339.9, 2.0
win = dict(south=LAT - HALF, north=LAT + HALF,
           west=LON - HALF, east=LON + HALF)

print("Window: %.1f-%.1f N, %.1f-%.1f E  (%.0f km across)"
      % (win["south"], win["north"], win["west"], win["east"],
         2 * HALF * math.pi * 1737.4 / 180))
print()
print(f"{'z':>2} {'tiles':>6} {'image px':<14} {'m/px':>7} {'KB':>7} {'s':>6}  "
      f"{'px across window':>16}")
print("-" * 76)

prev_mpp = None
ok = True
for z in range(3, 9):
    t0 = time.time()
    r = s.get(B + "/mosaic/wac", params={**win, "z": z}, timeout=300)
    dt = time.time() - t0
    if r.status_code != 200:
        print(f"{z:>2}  HTTP {r.status_code}")
        ok = False
        continue
    im = Image.open(io.BytesIO(r.content))
    mpp = float(r.headers["X-Metres-Per-Pixel"])
    zz = int(r.headers["X-Zoom"])
    tiles = int(r.headers["X-Tiles"])
    print(f"{zz:>2} {tiles:>6} {f'{im.width}x{im.height}':<14} {mpp:>7.0f} "
          f"{len(r.content)/1024:>7.0f} {dt:>6.1f}  {im.width:>16,}")

    if prev_mpp is not None and zz > 3:
        # Each level must halve the ground sample distance.
        if not (abs(prev_mpp / mpp - 2.0) < 0.01):
            print(f"      ^ EXPECTED 2x improvement, got {prev_mpp/mpp:.3f}x")
            ok = False
    prev_mpp = mpp

print()
print("Bounds snapping check (server must report what it actually covered):")
r = s.get(B + "/mosaic/wac", params={**win, "z": 7}, timeout=300)
h = r.headers
print(f"  requested : S{win['south']:.3f} N{win['north']:.3f} "
      f"W{win['west']:.3f} E{win['east']:.3f}")
print(f"  covered   : S{float(h['X-Bounds-South']):.3f} "
      f"N{float(h['X-Bounds-North']):.3f} "
      f"W{float(h['X-Bounds-West']):.3f} E{float(h['X-Bounds-East']):.3f}")
enclosed = (float(h["X-Bounds-South"]) <= win["south"]
            and float(h["X-Bounds-North"]) >= win["north"])
print(f"  {'PASS' if enclosed else 'FAIL'}  covered region encloses request")
ok = ok and enclosed

print()
print("Improvement over the base global texture (1333 m/px):")
r = s.get(B + "/mosaic/wac", params={**win, "z": 8}, timeout=300)
best = float(r.headers["X-Metres-Per-Pixel"])
print(f"  base   1333 m/px")
print(f"  patch  {best:.0f} m/px   ->  {1333/best:.1f}x sharper")

print()
print("RESULT:", "PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
