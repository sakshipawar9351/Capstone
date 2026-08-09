"""
Curated entry points into the gazetteer — the "Discover" catalogue.

Why curation is needed
----------------------
The system knows 1.3 million craters and 9 086 named features.  That is a
research asset and a terrible starting point: a newcomer opening the globe has
no way to know that Tycho matters and ``Tycho ZE`` does not.  This module
supplies the missing editorial layer — a small set of places worth visiting,
grouped the way a person would ask for them.

Everything here resolves against the live IAU index rather than hard-coding
coordinates.  A curated list therefore contains *names and reasons only*; the
positions, diameters and etymologies still come from the gazetteer, so the
curation can never drift out of agreement with the data.

Earth visibility
----------------
Each place is tagged nearside / limb / farside.  The Moon is in synchronous
rotation, so the sub-Earth point sits near 0 deg longitude and a feature is
visible from Earth when its longitude lies within roughly +/-90 deg of that.
Optical libration — the Moon's slight apparent rocking, caused by its orbital
eccentricity and axial tilt — swings the visible edge by about +/-8 deg, which
is why a band either side of the 90 deg limit is genuinely marginal rather than
simply visible or not.

Reference: Meeus, J. (1998), *Astronomical Algorithms*, 2nd ed., ch. 53
(libration of the Moon).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Half-width of the optical libration zone [deg].
LIBRATION_DEG = 8.0


def earth_visibility(lon_east: float) -> tuple[str, str]:
    """Classify a longitude by whether Earth ever sees it."""
    # Signed longitude about the sub-Earth meridian.
    d = abs((lon_east + 180.0) % 360.0 - 180.0)
    if d <= 90.0 - LIBRATION_DEG:
        return "nearside", "Always visible from Earth"
    if d <= 90.0 + LIBRATION_DEG:
        return "limb", "On the limb — visible only at favourable libration"
    return "farside", "Never visible from Earth"


@dataclass(frozen=True)
class Pick:
    """One curated place: a gazetteer name plus why it is worth seeing."""

    name: str
    why: str


# ---------------------------------------------------------------------------
# Curated selections
# ---------------------------------------------------------------------------

FEATURED: tuple[Pick, ...] = (
    Pick("Tycho", "Youngest large crater; its ray system spans the nearside"),
    Pick("Copernicus", "The textbook complex crater — terraces and central peaks"),
    Pick("Aristarchus", "Brightest feature on the Moon, on a volcanic plateau"),
    Pick("Clavius", "Ancient giant, heavily overprinted by later impacts"),
    Pick("Plato", "Impact basin flooded flat by mare basalt"),
    Pick("Shackleton", "Polar crater with permanently shadowed floor; Artemis target"),
    Pick("Grimaldi", "One of the darkest surfaces on the Moon"),
    Pick("Theophilus", "Young complex crater cutting into its older neighbour"),
    Pick("Petavius", "Floor split by a prominent rille"),
    Pick("Gassendi", "Fractured floor, long studied for volcanic history"),
)

BASINS: tuple[Pick, ...] = (
    Pick("Hertzsprung", "Farside multi-ring basin"),
    Pick("Apollo", "Large farside basin inside South Pole-Aitken"),
    Pick("Korolev", "Well-preserved farside basin"),
    Pick("Schrodinger", "Among the best-preserved large basins anywhere"),
    Pick("Mendeleev", "Farside basin with a flat, filled floor"),
    Pick("Poincare", "Deep basin in the southern farside highlands"),
    Pick("Birkhoff", "Northern farside basin"),
    Pick("Lorentz", "Large basin on the western limb"),
)

MARIA: tuple[Pick, ...] = (
    Pick("Oceanus Procellarum", "The largest mare — 2 592 km across"),
    Pick("Mare Imbrium", "Vast basin filled by basalt; defines the nearside"),
    Pick("Mare Tranquillitatis", "Apollo 11 landed here in 1969"),
    Pick("Mare Serenitatis", "Apollo 17 explored its south-eastern edge"),
    Pick("Mare Crisium", "Isolated circular mare near the eastern limb"),
    Pick("Mare Orientale", "Youngest large basin; textbook multi-ring structure"),
    Pick("Mare Nectaris", "Defines the Nectarian stratigraphic period"),
    Pick("Mare Humorum", "Circular mare with strong gravity anomaly"),
    Pick("Mare Frigoris", "Long arc of mare across the northern nearside"),
    Pick("Mare Moscoviense", "One of very few maria on the farside"),
)

MOUNTAINS: tuple[Pick, ...] = (
    Pick("Montes Apenninus", "Highest range on the Moon; Apollo 15 landing site"),
    Pick("Montes Caucasus", "Rugged range on the Imbrium rim"),
    Pick("Montes Alpes", "Cut through by the Alpine Valley"),
    Pick("Montes Carpatus", "Southern rim of Mare Imbrium"),
    Pick("Montes Jura", "Curved range enclosing Sinus Iridum"),
    Pick("Montes Cordillera", "Outermost ring of the Orientale basin"),
    Pick("Montes Rook", "Inner ring of Orientale"),
    Pick("Mons Huygens", "Tallest single peak on the Moon"),
)

VALLEYS: tuple[Pick, ...] = (
    Pick("Vallis Alpes", "166 km graben slicing through the Alps"),
    Pick("Vallis Schroteri", "Largest sinuous rille — a collapsed lava channel"),
    Pick("Vallis Rheita", "Long chain of merged craters"),
    Pick("Rima Hadley", "Apollo 15 drove along its rim"),
    Pick("Rima Ariadaeus", "Straight graben over 300 km long"),
    Pick("Rupes Recta", "The Straight Wall — a 110 km fault scarp"),
    Pick("Vallis Snellius", "Radial valley from the Nectaris impact"),
)

#: Human landing and impact sites, by their gazetteer names.
MISSIONS: tuple[Pick, ...] = (
    Pick("Statio Tranquillitatis", "Apollo 11 — first crewed landing, 1969"),
    Pick("Mare Cognitum", "Ranger 7 returned the first close-up images, 1964"),
    Pick("Taurus Littrow Valley", "Apollo 17 — last crewed landing, 1972"),
    Pick("Mount Marilyn", "Apollo 11 navigation landmark"),
)


CATEGORIES: tuple[dict, ...] = (
    {
        "key": "featured",
        "label": "Featured",
        "blurb": "Ten places that repay a first visit.",
        "picks": FEATURED,
    },
    {
        # Restricted to the Earth-facing hemisphere on purpose. Ranked purely
        # by size this list would be identical to "Basins" and "Farside", since
        # the largest named craters on the Moon are farside basins — three
        # categories showing Hertzsprung, Apollo and Korolev is not a catalogue,
        # it is the same list printed three times.
        "key": "craters",
        "label": "Great craters",
        "blurb": "Large nearside craters — the ones you can see from Earth.",
        "kinds": ("crater",),
        "min_diameter_km": 100.0,
        "nearside_only": True,
        "limit": 24,
    },
    {
        "key": "basins",
        "label": "Basins",
        "blurb": "Impacts big enough to form rings.",
        "picks": BASINS,
    },
    {
        "key": "maria",
        "label": "Maria & seas",
        "blurb": "Basalt plains that make the face of the Moon.",
        "picks": MARIA,
    },
    {
        "key": "mountains",
        "label": "Mountains",
        "blurb": "Ranges and peaks, mostly basin rims.",
        "picks": MOUNTAINS,
    },
    {
        "key": "valleys",
        "label": "Valleys & rilles",
        "blurb": "Graben, lava channels and fault scarps.",
        "picks": VALLEYS,
    },
    {
        "key": "missions",
        "label": "Missions",
        "blurb": "Where spacecraft and people reached the surface.",
        "picks": MISSIONS,
        "kinds": ("landing_site",),
        "limit": 20,
    },
    {
        "key": "polar",
        "label": "Polar",
        "blurb": "Above 70° latitude — the regions Artemis is aiming for.",
        "lat_min": 70.0,
        "limit": 24,
    },
    {
        "key": "farside",
        "label": "Farside",
        "blurb": "Never visible from Earth; first seen by Luna 3 in 1959.",
        "farside_only": True,
        "kinds": ("crater",),
        "min_diameter_km": 150.0,
        "limit": 24,
    },
)


def build(index) -> list[dict]:
    """Resolve every category against the gazetteer.

    Curated names that do not resolve are dropped silently rather than shown as
    broken entries — the gazetteer is the authority, and a name that is not in
    it is a curation error, not something the user should have to see.
    """
    out = []

    for cat in CATEGORIES:
        items: list[dict] = []
        seen: set[str] = set()

        # 1. Curated picks first, in editorial order.
        for pick in cat.get("picks", ()):
            f = index.by_name(pick.name)
            if f is None or f.name in seen:
                continue
            seen.add(f.name)
            d = f.to_dict()
            d["why"] = pick.why
            d["curated"] = True
            items.append(d)

        # 2. Top up from the gazetteer where the category defines a rule.
        limit = cat.get("limit")
        if limit and len(items) < limit:
            kinds = set(cat["kinds"]) if cat.get("kinds") else None
            lat_min = cat.get("lat_min")
            for f in index.query(
                kinds=kinds,
                min_diameter_km=cat.get("min_diameter_km", 0.0),
                limit=4000,
            ):
                if len(items) >= limit:
                    break
                if f.name in seen:
                    continue
                if lat_min is not None and abs(f.lat) < lat_min:
                    continue
                if cat.get("farside_only"):
                    if earth_visibility(f.lon)[0] != "farside":
                        continue
                if cat.get("nearside_only"):
                    if earth_visibility(f.lon)[0] == "farside":
                        continue
                seen.add(f.name)
                d = f.to_dict()
                d["curated"] = False
                items.append(d)

        # 3. Tag every item with Earth visibility.
        for d in items:
            vis, note = earth_visibility(d["lon"])
            d["visibility"] = vis
            d["visibility_note"] = note

        out.append({
            "key": cat["key"],
            "label": cat["label"],
            "blurb": cat["blurb"],
            "count": len(items),
            "items": items,
        })

    return out


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _self_test() -> int:
    from .nomenclature import load_index

    npass = nfail = 0

    def check(name, ok, detail=""):
        nonlocal npass, nfail
        if ok:
            npass += 1
            print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
        else:
            nfail += 1
            print(f"  FAIL  {name}   {detail}")

    print("\nEarth visibility classification\n")
    for lon, want in [(0, "nearside"), (45, "nearside"), (75, "nearside"),
                      (85, "limb"), (95, "limb"), (180, "farside"),
                      (270, "limb"), (300, "nearside"), (359, "nearside")]:
        got = earth_visibility(lon)[0]
        check(f"lon {lon:>3}° -> {got}", got == want, f"expected {want}")

    print("\nCatalogue resolution\n")
    idx = load_index()
    cats = build(idx)
    check("all categories built", len(cats) == len(CATEGORIES),
          f"{len(cats)} categories")

    total = 0
    for c in cats:
        total += c["count"]
        print(f"    {c['label']:<18} {c['count']:>3} items"
              f"   e.g. {', '.join(i['name'] for i in c['items'][:3])}")
        check(f"{c['label']} is non-empty", c["count"] > 0)

    check("catalogue has useful breadth", total > 90, f"{total} entries")

    print("\nCuration integrity\n")
    # Every curated name must resolve, or the list has drifted from the data.
    missing = []
    for cat in CATEGORIES:
        for pick in cat.get("picks", ()):
            if idx.by_name(pick.name) is None:
                missing.append(f"{cat['key']}:{pick.name}")
    check("every curated name exists in the gazetteer",
          not missing, ", ".join(missing) if missing else "all resolve")

    farside = next(c for c in cats if c["key"] == "farside")
    check("farside category really is all farside",
          all(i["visibility"] == "farside" for i in farside["items"]),
          f"{farside['count']} checked")

    polar = next(c for c in cats if c["key"] == "polar")
    check("polar category really is polar",
          all(abs(i["lat"]) >= 70 for i in polar["items"]),
          f"{polar['count']} checked")

    craters = next(c for c in cats if c["key"] == "craters")
    check("great craters are all Earth-facing",
          all(i["visibility"] != "farside" for i in craters["items"]),
          f"{craters['count']} checked")

    # Categories must not be three printings of the same list.
    cr = {i["name"] for i in craters["items"]}
    fs = {i["name"] for i in farside["items"]}
    check("great craters and farside do not overlap",
          not (cr & fs), f"overlap: {sorted(cr & fs)[:4]}")

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
