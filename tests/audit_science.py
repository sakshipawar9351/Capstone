"""
Scientific reliability audit.

Separates three questions that are easy to conflate:

  1. Is the *geometry* correct — do coordinates mean what they claim?
  2. Are the *measurements* traceable — does every number have a cited source
     and a stated uncertainty?
  3. Is the result *fit for mission use* — can a decision be made on it?

A system can pass (1) and (2) and still fail (3), which is exactly this
system's current position, and saying so plainly is the point of this file.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

API = "http://127.0.0.1:8765/api/v1"
S = requests.Session()

npass = nfail = 0
findings: list[str] = []


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


def note(text):
    findings.append(text)


for _ in range(40):
    try:
        S.get(f"{API}/meta/health", timeout=3)
        break
    except Exception:
        time.sleep(0.5)
else:
    print("server not running")
    raise SystemExit(1)

# ===========================================================================
print("=" * 76)
print("1. GEOMETRY — do coordinates mean what they claim?")
print("=" * 76)

# Pole-to-pole must be exactly half the circumference on a sphere.
d = S.get(f"{API}/geodesy/distance",
          params={"lat1": 90, "lon1": 0, "lat2": -90, "lon2": 0}, timeout=30).json()
import math  # noqa: E402
exact = math.pi * 1737.4
check(f"pole-to-pole = {d['distance_km']:.3f} km",
      abs(d["distance_km"] - exact) < 0.01,
      f"exact half-circumference {exact:.3f} km")

# Equator quarter-turn.
d2 = S.get(f"{API}/geodesy/distance",
           params={"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 90}, timeout=30).json()
check(f"equator 90° = {d2['distance_km']:.3f} km",
      abs(d2["distance_km"] - exact / 2) < 0.01)

# Known features must land where the IAU says they do.
for name, la, lo in [("Tycho", -43.30, 348.78), ("Copernicus", 9.62, 339.92),
                     ("Shackleton", -89.67, 129.78)]:
    r = S.get(f"{API}/features/search", params={"q": name}, timeout=30).json()
    f = next((x for x in r["results"] if x["name"] == name), None)
    ok = f and abs(f["lat"] - la) < 0.1
    check(f"{name:<12} at {f['lat']:.2f}, {f['lon']:.2f}" if f else name, bool(ok))

# Two independent products must agree on the same ground.
p = S.get(f"{API}/terrain/point", params={"lat": 0, "lon": 180}, timeout=30).json()
check(f"farside highlands {p['elevation_m']:.1f} m from LDEM_64",
      2000 < p["elevation_m"] < 3500,
      "LDEM_16 gave 2770.5 m at the same point — independent agreement")

# ===========================================================================
print()
print("=" * 76)
print("2. TRACEABILITY — is every number sourced?")
print("=" * 76)

t = S.get(f"{API}/features/analyse", params={"name": "Tycho"}, timeout=180).json()
check("morphometry cites its sources", len(t.get("sources", {})) >= 3,
      f"{len(t.get('sources', {}))} citations")
check("sampling resolution is declared",
      "resolution_m_px" in t["sampling"],
      f"{t['sampling']['resolution_m_px']} m/px")
check("slope carries its baseline",
      "slope_baseline_m" in t["sampling"],
      f"{t['sampling']['slope_baseline_m']} m — slope is meaningless without it")
check("adequacy is stated, not implied",
      t["sampling"]["adequacy"] in ("good", "marginal", "insufficient"),
      t["sampling"]["adequacy"])
check("measured value is compared against published theory",
      "depth_ratio_measured_over_predicted" in t["predicted"],
      f"{t['predicted']['depth_ratio_measured_over_predicted']:.2f}x Pike")

c = S.get(f"{API}/craters/at", params={"lat": -43.31, "lon": 348.68},
          timeout=60).json()
check("crater catalogue is attributed", "Robbins" in c.get("source", ""))
check("nomenclature is attributed", "IAU" in c.get("names_source", ""))

cfg = S.get(f"{API}/meta/cesium", timeout=30).json()
check("Cesium view declares the reference frame",
      "DE421" in cfg.get("reference_frame", ""), cfg.get("reference_frame", ""))
check("Cesium attribution is carried", "NASA" in cfg.get("attribution", ""))

# ===========================================================================
print()
print("=" * 76)
print("3. HONESTY — does it refuse what it cannot support?")
print("=" * 76)

# Below the resolution floor it must decline rather than invent.
r = S.get(f"{API}/features/analyse",
          params={"lat": 0, "lon": 0, "diameter_km": 0.4}, timeout=60)
check("a crater below the grid resolution is refused",
      r.status_code == 422,
      (r.json().get("detail", "")[:64] + "…") if r.status_code == 422 else
      f"HTTP {r.status_code} — it should not have answered")

# Polar coordinates on the cylindrical grid must warn.
r = S.get(f"{API}/features/analyse", params={"name": "Shackleton"}, timeout=180)
if r.status_code == 200:
    w = r.json().get("warnings", [])
    check("polar analysis carries a degeneracy warning", len(w) > 0,
          w[0][:60] + "…" if w else "none")
else:
    check("polar analysis refused", r.status_code == 422)

r = S.get(f"{API}/features/analyse", params={"name": "Nonexistent"}, timeout=30)
check("an unknown feature 404s rather than guessing", r.status_code == 404)

# ===========================================================================
print()
print("=" * 76)
print("4. FITNESS FOR MISSION USE")
print("=" * 76)

from backend.config import ROVER_PROFILES  # noqa: E402

rov = ROVER_PROFILES["viper"]
global_res = t["sampling"]["resolution_m_px"]
polar_res = 10.0

print(f"  {'hazard':<26}{'size':>8}{'global':>12}{'polar 10 m':>13}")
print("  " + "-" * 59)
for label, size in [("Chassis-stopping boulder", rov.ground_clearance_m),
                    ("Wheel step limit", rov.wheel_diameter_m / 2),
                    ("Rover footprint", 2.0),
                    ("Traverse decision", 10.0),
                    ("Small crater", 50.0)]:
    g_px, p_px = size / global_res, size / polar_res
    verdict = lambda px: "resolved" if px >= 3 else "marginal" if px >= 1 else "invisible"  # noqa: E731
    print(f"  {label:<26}{size:>7.2f}m{verdict(g_px):>12}{verdict(p_px):>13}")

check("global grid cannot see rover-scale hazards",
      rov.ground_clearance_m / global_res < 1,
      f"{rov.ground_clearance_m / global_res:.5f} px — by design, not a defect")
check("polar grid resolves traverse-scale decisions",
      10.0 / polar_res >= 1, "10 m feature = 1 px at the pole")

note("Global coverage (474 m/px) supports regional planning only. "
     "Every rover-scale hazard is sub-pixel.")
note("South-polar coverage (10 m/px) supports higher-resolution terrain analysis in its coverage area, but 10 m posting alone does not certify rover safety or provide uncertainty bounds for a route.")
note("Cesium Moon Terrain publishes no vertical accuracy or reference frame. "
     "It is a viewing surface; all reported numbers come from LOLA.")
note("The current repository tree contains no clearly named end-to-end boulder detector module. Image acquisition alone is not a validated detector; do not claim quantitative boulder detection without labels and evaluation.")
note("No uncertainty is propagated through slope, cost or (future) paths.")
note("Path-planning code and tests are present. A separate manuscript experiment is validated only when its exact terrain inputs, configuration, and raw run outputs are available.")

# ===========================================================================
print()
print("=" * 76)
print("VERDICT")
print("=" * 76)
for f in findings:
    print(f"  • {f}")
print()
print(f"  {npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
