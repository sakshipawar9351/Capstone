"""
End-to-end verification of the whole system.

Checks the parts a unit test cannot: that the server answers, that every
endpoint returns sane data, that both frontends and all their assets are
served, and that the external services the app depends on are reachable.

    python tests/verify_all.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"
API = f"{BASE}/api/v1"

npass = nfail = nwarn = 0
S = requests.Session()


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")
    return ok


def warn(name, detail=""):
    global nwarn
    nwarn += 1
    print(f"  WARN  {name}   {detail}")


def head(title):
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


# ---------------------------------------------------------------------------
head("1. SERVER")
# ---------------------------------------------------------------------------
up = False
for _ in range(40):
    try:
        S.get(f"{API}/meta/health", timeout=3)
        up = True
        break
    except Exception:
        time.sleep(0.5)

if not check("server responding on 127.0.0.1:8765", up):
    print("\nStart it with:  python -m uvicorn backend.main:app --port 8765")
    raise SystemExit(1)

h = S.get(f"{API}/meta/health", timeout=30).json()
for comp, want in [("elevation", "LDEM_64"), ("craters", None), ("nomenclature", None)]:
    c = h["components"].get(comp, {})
    ok = c.get("ok") is True
    extra = c.get("product") or f"{c.get('count', 0):,}"
    check(f"{comp:<14} online", ok, str(extra))
    if comp == "elevation" and c.get("product") != want:
        warn("elevation product", f"expected {want}, got {c.get('product')}")

# ---------------------------------------------------------------------------
head("2. API ENDPOINTS")
# ---------------------------------------------------------------------------
ENDPOINTS = [
    # /meta/layers returns basemaps + crater_classes + rovers + dem_products;
    # there is no separate /craters/classes route.
    ("meta/layers", {},
     lambda d: len(d["basemaps"]) >= 3 and len(d["crater_classes"]) >= 6),
    ("meta/cesium", {}, lambda d: d["asset"] == 2684829 and len(d["token"]) > 100),
    ("craters/bbox", {"south": -50, "north": -35, "west": 340, "east": 356,
                      "min_diameter_km": 20, "limit": 50},
     lambda d: d["count"] > 0),
    ("craters/at", {"lat": -43.31, "lon": 348.68}, lambda d: len(d["enclosing"]) > 0),
    ("craters/landmarks", {"n": 10}, lambda d: d["count"] == 10),
    ("features/named", {"min_diameter_km": 100, "limit": 20}, lambda d: d["count"] == 20),
    ("features/search", {"q": "tycho"},
     lambda d: any(r["name"] == "Tycho" for r in d["results"])),
    ("features/kinds", {}, lambda d: len(d["kinds"]) > 10),
    ("features/analyse", {"name": "Tycho"},
     lambda d: 3500 < d["measured"]["depth_m"] < 5500),
    ("terrain/point", {"lat": 0, "lon": 180}, lambda d: 2000 < d["elevation_m"] < 3500),
    ("terrain/grid", {"south": -45, "north": -41, "west": 347, "east": 351,
                      "width": 65, "height": 65}, None),
    ("discover", {}, lambda d: d["total"] > 100),
    ("discoveries", {}, lambda d: d["count"] >= 20),
    ("missions", {}, lambda d: d["count"] >= 40),
    ("missions/apollo11", {}, lambda d: d["crew"] and len(d["crew"]) == 2),
    ("geodesy/distance", {"lat1": 90, "lon1": 0, "lat2": -90, "lon2": 0},
     lambda d: abs(d["distance_km"] - 5458.2) < 1),
]

for path, params, validate in ENDPOINTS:
    t0 = time.time()
    try:
        r = S.get(f"{API}/{path}", params=params, timeout=180)
        dt = (time.time() - t0) * 1000
        if r.status_code != 200:
            check(f"GET /{path:<22}", False, f"HTTP {r.status_code}")
            continue
        if validate is None:
            check(f"GET /{path:<22}", len(r.content) > 100,
                  f"{len(r.content):,} bytes, {dt:.0f} ms")
        else:
            check(f"GET /{path:<22}", validate(r.json()), f"{dt:.0f} ms")
    except Exception as exc:
        check(f"GET /{path:<22}", False, str(exc)[:60])

# ---------------------------------------------------------------------------
head("3. FRONTEND ASSETS")
# ---------------------------------------------------------------------------
# One integrated application: both renderers live in index.html and are chosen
# at runtime, so there is no second page to serve.
ASSETS = [
    "/", "/index.html",
    "/css/style.css",
    "/js/main.js", "/js/globe.js", "/js/api.js", "/js/cesium-renderer.js",
]
for path in ASSETS:
    try:
        r = S.get(BASE + path, timeout=30)
        check(f"{path:<26}", r.status_code == 200,
              f"{len(r.content) / 1024:.1f} KB")
    except Exception as exc:
        check(f"{path:<26}", False, str(exc)[:50])

# The single page must carry everything both renderers need.
body = S.get(BASE + "/index.html", timeout=30).text
needles = [
    "js/main.js", "css/style.css",   # core
    "cesiumContainer", "rnd-cesium", "rnd-three",  # renderer switch
    'id="gl"',                        # Three.js canvas
]
missing = [n for n in needles if n not in body]
check("index.html wires both renderers", not missing,
      f"missing {missing}" if missing else "single integrated page")

# The standalone Cesium page should be gone, not merely unlinked.
r = S.get(BASE + "/cesium.html", timeout=30)
check("standalone cesium.html removed", r.status_code == 404,
      f"HTTP {r.status_code}")

# ---------------------------------------------------------------------------
head("4. EXTERNAL SERVICES")
# ---------------------------------------------------------------------------
cfg = S.get(f"{API}/meta/cesium", timeout=30).json()

try:
    r = S.get("https://api.cesium.com/v1/assets/2684829/endpoint",
              params={"access_token": cfg["token"]}, timeout=60)
    ok = r.status_code == 200
    check("Cesium ion token valid", ok, f"HTTP {r.status_code}")
    if ok:
        ep = r.json()
        s2 = requests.Session()
        s2.headers["Authorization"] = f"Bearer {ep['accessToken']}"
        ts = s2.get(ep["url"], timeout=90)
        check("Moon tileset reachable", ts.status_code == 200,
              f"{len(ts.content):,} bytes")
except Exception as exc:
    check("Cesium ion reachable", False, str(exc)[:60])

try:
    r = S.get(f"https://cesium.com/downloads/cesiumjs/releases/"
              f"{cfg['version']}/Build/Cesium/Cesium.js", stream=True, timeout=60)
    check(f"CesiumJS {cfg['version']} on CDN", r.status_code == 200)
    r.close()
except Exception as exc:
    check("CesiumJS CDN", False, str(exc)[:60])

try:
    # Route is /tiles/{layer}/{z}/{y}/{x} â€” row before column, no extension.
    r = S.get(f"{API}/tiles/wac/3/2/4", timeout=60)
    check("Moon Trek tile proxy", r.status_code == 200 and len(r.content) > 1000,
          f"{len(r.content) / 1024:.0f} KB")
except Exception as exc:
    check("Moon Trek tile proxy", False, str(exc)[:60])

# ---------------------------------------------------------------------------
head("5. UNIT SUITES")
# ---------------------------------------------------------------------------
p = subprocess.run([sys.executable, "tests/run_all.py"],
                   cwd=ROOT, capture_output=True, text=True)
tail = [ln for ln in p.stdout.splitlines() if "passed" in ln]
check("all unit suites", p.returncode == 0, tail[-1] if tail else "")

# ---------------------------------------------------------------------------
head("SUMMARY")
# ---------------------------------------------------------------------------
print(f"  {npass} passed, {nfail} failed, {nwarn} warnings")
raise SystemExit(1 if nfail else 0)

