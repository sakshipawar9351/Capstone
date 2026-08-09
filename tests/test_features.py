"""End-to-end test of named features and crater morphometry over the API."""
import time

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


print("=" * 76)
print("1. HEALTH")
print("=" * 76)
h = s.get(B + "/meta/health", timeout=60).json()
for k, v in h["components"].items():
    print(f"  {k:<14}: {v}")
check("nomenclature online", h["components"]["nomenclature"]["ok"],
      f"{h['components']['nomenclature'].get('count'):,} features, "
      f"{h['components']['nomenclature'].get('named_craters'):,} named craters")

print()
print("=" * 76)
print("2. NAMED FEATURES")
print("=" * 76)
k = s.get(B + "/features/kinds", timeout=30).json()
check("kinds listed", len(k["kinds"]) > 10, f"{len(k['kinds'])} kinds")

r = s.get(B + "/features/named",
          params={"min_diameter_km": 100, "limit": 25}, timeout=60).json()
check("large named features", r["count"] > 0,
      f"{r['count']} in {r['query_ms']} ms")
for f in r["features"][:6]:
    print(f"      {f['name']:<24} {f['kind_label']:<16} "
          f"D={f['diameter_km']:>8.1f} km  {f['lat']:>7.2f},{f['lon']:>7.2f}")

r = s.get(B + "/features/search", params={"q": "tych"}, timeout=30).json()
check("search 'tych'", any(x["name"] == "Tycho" for x in r["results"]),
      ", ".join(x["name"] for x in r["results"][:4]))

r = s.get(B + "/features/named",
          params={"kinds": "landing_site", "limit": 100}, timeout=30).json()
check("landing sites", r["count"] > 20, f"{r['count']} sites")

print()
print("=" * 76)
print("3. MORPHOMETRY VIA API  (published depths in brackets)")
print("=" * 76)
cases = [("Tycho", 4700), ("Copernicus", 3800), ("Clavius", 3500),
         ("Plato", 1000), ("Aristarchus", 3000)]
for nm, pub in cases:
    t0 = time.time()
    resp = s.get(B + "/features/analyse", params={"name": nm}, timeout=180)
    dt = (time.time() - t0) * 1000
    if resp.status_code != 200:
        check(f"{nm} analysed", False, f"HTTP {resp.status_code}")
        continue
    a = resp.json()
    m, p, sm = a["measured"], a["predicted"], a["sampling"]
    ok = m["depth_m"] is not None and m["depth_m"] > 0
    check(f"{nm:<12} depth {m['depth_m']:>6.0f} m [{pub}]  "
          f"rim {m['rim_height_m']:>5.0f} m  wall {m['wall_slope_deg']:>5.1f}°  "
          f"vol {m['volume_km3']:>8,.0f} km³",
          ok, f"{sm['adequacy']}, {dt:.0f} ms")
    print(f"        ratio vs Pike {p['depth_ratio_measured_over_predicted']:.2f}× "
          f"— {p['interpretation'][:72]}")

print()
print("=" * 76)
print("4. SCIENTIFIC HONESTY")
print("=" * 76)
r = s.get(B + "/features/analyse", params={"name": "Shackleton"}, timeout=180)
if r.status_code == 200:
    a = r.json()
    check("polar crater carries a warning", len(a["warnings"]) > 0,
          a["warnings"][0][:70] + "…" if a["warnings"] else "none")
else:
    check("polar crater handled", r.status_code == 422,
          f"HTTP {r.status_code} (refused, acceptable)")

r = s.get(B + "/features/analyse", params={"name": "Nonexistentcrater"}, timeout=60)
check("unknown name -> 404", r.status_code == 404,
      r.json().get("detail", "")[:60])

r = s.get(B + "/features/analyse", params={"name": "Copernicus"}, timeout=180).json()
check("sources cited", len(r["sources"]) >= 3, f"{len(r['sources'])} citations")
check("profile returned", len(r["profile"]) > 8, f"{len(r['profile'])} rings")

print()
print("=" * 76)
print(f"RESULT: {npass} passed, {nfail} failed")
print("=" * 76)
raise SystemExit(1 if nfail else 0)
