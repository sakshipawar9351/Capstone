"""Smoke-test every LunarSerpent endpoint against known lunar ground truth."""
import json
import time

import requests

B = "http://127.0.0.1:8765/api/v1"
s = requests.Session()

# Wait for the server to bind.
for _ in range(40):
    try:
        s.get(B + "/meta/health", timeout=3)
        break
    except Exception:
        time.sleep(0.5)
else:
    raise SystemExit("server did not start")

npass = nfail = 0


def check(name, cond, detail=""):
    global npass, nfail
    if cond:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


print("=" * 74)
print("1. HEALTH")
print("=" * 74)
t0 = time.time()
h = s.get(B + "/meta/health", timeout=30).json()
print(f"  frame   : {h['reference_frame']}")
print(f"  radius  : {h['moon_radius_m']} m")
for k, v in h["components"].items():
    print(f"  {k:<10}: {v}")
check("elevation online", h["components"]["elevation"]["ok"])
check("craters online", h["components"]["craters"]["ok"],
      f"{h['components']['craters'].get('count'):,} craters")

print()
print("=" * 74)
print("2. LAYERS")
print("=" * 74)
L = s.get(B + "/meta/layers", timeout=30).json()
check("basemaps listed", len(L["basemaps"]) >= 3, f"{len(L['basemaps'])} layers")
check("crater classes", len(L["crater_classes"]) == 7,
      f"{len(L['crater_classes'])} classes")
check("rovers listed", len(L["rovers"]) >= 4, f"{len(L['rovers'])} profiles")

print()
print("=" * 74)
print("3. TERRAIN  (validated against known lunar topography)")
print("=" * 74)
sites = [
    ("Farside highlands", 0.0, 180.0, lambda e: 1000 < e < 5000),
    ("Mare Imbrium", 35.0, 345.0, lambda e: -5000 < e < 0),
    ("South Pole-Aitken", -53.0, 191.0, lambda e: e < -2000),
    ("Mare Crisium", 17.0, 59.0, lambda e: -5000 < e < 0),
]
for name, la, lo, ok in sites:
    r = s.get(B + "/terrain/point", params={"lat": la, "lon": lo}, timeout=30).json()
    e = r["elevation_m"]
    check(f"{name:<20} {e:>9.1f} m", ok(e), f"cell {r['cell_size_m']['east_west']:.0f} m E-W")

r = s.get(B + "/terrain/point", params={"lat": 89.0, "lon": 0.0}, timeout=30).json()
check("polar warning issued", "warning" in r)

print()
print("=" * 74)
print("4. CRATERS")
print("=" * 74)
t0 = time.time()
r = s.get(B + "/craters/bbox",
          params={"south": -90, "north": 90, "min_diameter_km": 100, "limit": 500},
          timeout=60).json()
dt = (time.time() - t0) * 1000
check("global D>=100km query", r["total_matching"] > 50,
      f"{r['total_matching']} craters, {r['query_ms']} ms server / {dt:.0f} ms round-trip")
if r["craters"]:
    big = r["craters"][0]
    print(f"  largest: {big['id']}  D={big['diameter_km']:.1f} km  "
          f"class={big['class_label']}  at {big['lat']:.2f}, {big['lon']:.2f}")
    check("largest is a basin", big["diameter_km"] > 500)

r = s.get(B + "/craters/largest", params={"n": 5}, timeout=30).json()
check("largest endpoint", len(r["craters"]) == 5)

# Tycho: 43.31 S, 348.79 E, D = 85 km
r = s.get(B + "/craters/at", params={"lat": -43.31, "lon": 348.79}, timeout=60).json()
check("Tycho region has enclosing craters", len(r["enclosing"]) > 0,
      f"{len(r['enclosing'])} enclosing")
if r["nearest"]:
    print(f"  nearest to Tycho centre: D={r['nearest']['diameter_km']:.2f} km")

print()
print("=" * 74)
print("5. GEODESY")
print("=" * 74)
# Quarter circumference: pi/2 * R = 2729.3 km
r = s.get(B + "/geodesy/distance",
          params={"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 90}, timeout=30).json()
expect = 3.141592653589793 / 2 * 1737400 / 1000
check("quarter circumference", abs(r["distance_km"] - expect) < 0.01,
      f"{r['distance_km']:.3f} km vs {expect:.3f} km")

r = s.get(B + "/geodesy/distance",
          params={"lat1": -90, "lon1": 0, "lat2": 90, "lon2": 0}, timeout=30).json()
expect = 3.141592653589793 * 1737400 / 1000
check("pole to pole", abs(r["distance_km"] - expect) < 0.01,
      f"{r['distance_km']:.3f} km")

print()
print("=" * 74)
print("6. BASEMAP TEXTURE  (stitches WMTS tiles; first call is slow)")
print("=" * 74)
t0 = time.time()
r = s.get(B + "/texture/wac", params={"z": 3}, timeout=600)
dt = time.time() - t0
check("texture z=3 served", r.status_code == 200 and len(r.content) > 50_000,
      f"{len(r.content)/1024:.0f} KB in {dt:.1f} s")
if r.status_code == 200:
    import io

    from PIL import Image
    im = Image.open(io.BytesIO(r.content))
    check("aspect ratio 2:1", abs(im.width / im.height - 2.0) < 0.01,
          f"{im.width}x{im.height}")

print()
print("=" * 74)
print(f"RESULT: {npass} passed, {nfail} failed")
print("=" * 74)
raise SystemExit(1 if nfail else 0)
