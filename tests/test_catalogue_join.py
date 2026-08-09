"""Verify the Robbins <-> IAU catalogue join resolves real crater names."""
import sys

sys.path.insert(0, r"d:\Lunar_Serpent")

from backend.data.catalog_robbins import load_index  # noqa: E402
from backend.data.nomenclature import load_index as load_names  # noqa: E402

craters = load_index()
names = load_names()

npass = nfail = 0


def check(name, ok, detail=""):
    global npass, nfail
    if ok:
        npass += 1
        print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
    else:
        nfail += 1
        print(f"  FAIL  {name}   {detail}")


print("\nCatalogue join: Robbins measurement -> IAU name\n")

# Each of these is a famous crater; the Robbins entry nearest its IAU centre
# must resolve back to the same name.
CASES = [
    ("Tycho", -43.30, 348.78, 85.3),
    ("Copernicus", 9.62, 339.92, 96.1),
    ("Clavius", -58.62, 345.27, 230.8),
    ("Aristarchus", 23.72, 312.51, 40.0),
    ("Plato", 51.62, 350.62, 100.7),
    ("Kepler", 8.12, 322.03, 29.5),
    ("Grimaldi", -5.38, 291.58, 172.7),
    ("Theophilus", -11.42, 26.37, 98.6),
    ("Petavius", -25.34, 60.51, 184.4),
    ("Gassendi", -17.55, 320.00, 109.6),
]

for want, la, lo, dm in CASES:
    near = craters.nearest(la, lo)
    if near is None:
        check(f"{want} — Robbins entry found", False)
        continue
    got = names.match_crater(near.lat, near.lon, near.diameter_km)
    ok = got is not None and got.name == want
    check(f"{want:<13} Robbins {near.id:<14} D={near.diameter_km:>7.2f} km",
          ok, f"-> {got.name if got else 'NO MATCH'}")

print("\nGuard against wrong matches\n")

# A tiny crater sitting inside Clavius must NOT inherit the name "Clavius":
# position alone would match, so the diameter test is what prevents it.
tiny = names.match_crater(-58.62, 345.27, 2.0)
check("2 km crater at Clavius centre does not become 'Clavius'",
      tiny is None or tiny.name != "Clavius",
      f"got {tiny.name if tiny else 'None'}")

# A point in featureless mare should resolve to nothing.
blank = names.match_crater(20.0, 300.0, 3.0)
check("small unnamed mare crater stays unnamed",
      blank is None, f"got {blank.name if blank else 'None'}")

print("\nCoverage over the nested-crater stack\n")

# The user's click point from the screenshot.
enc = craters.containing(1.8753, 57.9122)
print(f"  {len(enc)} craters contain (1.8753 N, 57.9122 E):")
named_n = 0
for c in enc[:8]:
    hit = names.match_crater(c.lat, c.lon, c.diameter_km)
    if hit:
        named_n += 1
    print(f"    {c.id:<14} D={c.diameter_km:>8.2f} km  {c.class_label:<8} "
          f"-> {hit.name if hit else '(unnamed)'}")
check("at least one nested crater resolves to a name", named_n > 0,
      f"{named_n}/{len(enc)} named")

print("\nHow much of the catalogue is named at all\n")
big = craters.largest(200)
hits = sum(1 for c in big if names.match_crater(c.lat, c.lon, c.diameter_km))
print(f"  200 largest Robbins craters -> {hits} carry IAU names "
      f"({hits/2:.0f}%)")
check("large craters are mostly named", hits > 60, f"{hits}/200")

print(f"\n{npass} passed, {nfail} failed")
raise SystemExit(1 if nfail else 0)
