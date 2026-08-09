"""
Major scientific discoveries about the Moon.

Scope and standard of evidence
------------------------------
Each entry records a finding that changed what the Moon was understood to be,
attributed to the mission and instrument that established it, with the primary
publication cited.  Several are tied to a specific place and can be shown on the
globe; others — the crustal dichotomy, the magma ocean — are global properties
with no single coordinate, and are marked as such rather than pinned to an
arbitrary point.

Every entry carries a ``status``:

``established``
    Independently confirmed by more than one instrument or dataset, and not
    seriously disputed.
``evolving``
    The observation is solid but its interpretation, extent or magnitude is
    still being revised.
``contested``
    Reported and published, but a competing explanation remains viable.

That distinction matters more here than anywhere else in this system.  "There is
water on the Moon" is four different discoveries — ice in polar cold traps,
hydroxyl bound in sunlit regolith, molecular water on sunlit surfaces, and water
trapped in volcanic glass — made by different missions, at different times, with
different confidence.  Collapsing them into one claim is how popular accounts go
wrong, so they are kept separate.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Discovery", "DISCOVERIES", "CATEGORIES", "by_key", "statistics"]


@dataclass(frozen=True)
class Discovery:
    key: str
    title: str
    category: str
    year: int
    mission: str
    instrument: str
    country: str
    flag: str
    status: str                       # established | evolving | contested
    headline: str                     # one sentence: what was found
    detail: str                       # why it mattered
    lat: float | None = None
    lon: float | None = None
    place: str | None = None          # None => global property, not a point
    value: str | None = None          # the key number, where there is one
    refs: tuple[str, ...] = ()

    @property
    def mappable(self) -> bool:
        return self.lat is not None

    def to_dict(self) -> dict:
        return {
            "key": self.key, "title": self.title, "category": self.category,
            "year": self.year, "mission": self.mission,
            "instrument": self.instrument, "country": self.country,
            "flag": self.flag, "status": self.status,
            "headline": self.headline, "detail": self.detail,
            "lat": self.lat, "lon": self.lon, "place": self.place,
            "value": self.value, "refs": list(self.refs),
            "mappable": self.mappable,
        }


CATEGORIES: tuple[dict, ...] = (
    {"key": "water", "label": "Water & volatiles",
     "blurb": "Four separate discoveries, often wrongly reported as one."},
    {"key": "interior", "label": "Interior & structure",
     "blurb": "What lies beneath the surface."},
    {"key": "volcanism", "label": "Volcanism",
     "blurb": "How long the Moon stayed geologically alive."},
    {"key": "impacts", "label": "Impact history",
     "blurb": "The record of bombardment, and what it dates."},
    {"key": "environment", "label": "Surface environment",
     "blurb": "Temperature, radiation, dust and magnetism."},
)


DISCOVERIES: tuple[Discovery, ...] = (

    # ── Water and volatiles ─────────────────────────────────────────────
    Discovery(
        key="apollo_dry", title="The Moon appears bone dry",
        category="water", year=1969, mission="Apollo 11",
        instrument="Returned samples", country="United States", flag="🇺🇸",
        status="evolving",
        headline="The first returned samples contained no detectable water, and "
                 "the Moon was declared the driest body known.",
        detail="No hydrous minerals were found — no clays, no micas, nothing "
               "that forms in the presence of water. This became textbook fact "
               "for nearly forty years, and it shaped every model of how the "
               "Moon formed. It was wrong, but not carelessly so: the water is "
               "there in parts per million, below what 1970s instruments could "
               "see. It is included here because a discovery that was later "
               "overturned is part of the scientific record, not an erasure "
               "from it.",
        value="Below detection limits of the era",
        refs=("Apollo Preliminary Science Reports (1969–1972)",),
    ),
    Discovery(
        key="volcanic_glass_water",
        title="Water trapped inside volcanic glass",
        category="water", year=2008, mission="Apollo 15 & 17 (re-analysis)",
        instrument="Secondary ion mass spectrometry",
        country="United States", flag="🇺🇸", status="established",
        headline="Modern instruments found water inside the Apollo samples "
                 "themselves — indigenous, not contamination.",
        detail="Ion microprobes reached detection limits three orders of "
               "magnitude below the Apollo-era instruments and found water "
               "dissolved in volcanic glass beads. Because the glass quenched "
               "during eruption, that water came from the lunar interior. The "
               "Moon was not dry; the instruments had been blind.",
        lat=20.19, lon=30.77, place="Taurus–Littrow (Apollo 17 orange glass)",
        value="Up to 46 ppm H₂O in glass; pre-eruption magma ~750 ppm",
        refs=("Saal, A. E. et al. (2008) Nature 454, 192–195, "
              "doi:10.1038/nature07047",),
    ),
    Discovery(
        key="m3_hydration",
        title="Hydroxyl and water across the sunlit surface",
        category="water", year=2009, mission="Chandrayaan-1",
        instrument="Moon Mineralogy Mapper (M³)", country="India / United States",
        flag="🇮🇳", status="established",
        headline="An infrared absorption at 3 μm revealed OH and H₂O bound in "
                 "the regolith over wide areas — strongest toward the poles.",
        detail="The signal strengthens with latitude and varies through the "
               "lunar day, implying an active cycle in which solar-wind protons "
               "combine with oxygen in the soil, and the product migrates. "
               "Water is not merely buried at the poles; it is being made and "
               "moved across the surface continuously. Confirmed independently "
               "by Cassini and Deep Impact flyby data.",
        value="3 μm absorption; strengthens poleward",
        refs=("Pieters, C. M. et al. (2009) Science 326, 568–572, "
              "doi:10.1126/science.1178658",),
    ),
    Discovery(
        key="lcross_ice", title="Water ice in a permanently shadowed crater",
        category="water", year=2009, mission="LCROSS", instrument="Impact plume "
        "spectroscopy", country="United States", flag="🇺🇸",
        status="established",
        headline="A rocket stage was driven into Cabeus crater and the debris "
                 "plume was flown through and analysed — it contained water ice.",
        detail="This is the direct detection: not an inference from reflectance "
               "or neutron counts, but material excavated from a crater floor "
               "that has not seen sunlight for billions of years, measured in "
               "flight. The plume also carried hydrogen sulphide, ammonia, "
               "carbon monoxide and mercury — a cold trap preserving a volatile "
               "inventory, not just ice. It is the foundation of the resource "
               "case for polar exploration.",
        lat=-84.675, lon=311.275, place="Cabeus crater, south polar region",
        value="5.6 ± 2.9 % water by mass in the ejecta",
        refs=("Colaprete, A. et al. (2010) Science 330, 463–468, "
              "doi:10.1126/science.1186986",),
    ),
    Discovery(
        key="sofia_water", title="Molecular water on a sunlit surface",
        category="water", year=2020, mission="SOFIA (airborne observatory)",
        instrument="FORCAST 6 μm spectrometer", country="United States / Germany",
        flag="🇺🇸", status="established",
        headline="A 6 μm emission line — diagnostic of H₂O specifically, not "
                 "hydroxyl — was detected on a sunlit part of the Moon.",
        detail="The earlier 3 μm detections could not separate water from "
               "hydroxyl; the 6 μm band can. Finding molecular water where "
               "temperatures reach 120 °C means it must be shielded, most "
               "plausibly trapped inside impact glass or between grains. It "
               "shows water is not confined to permanent shadow.",
        lat=-58.62, lon=345.27, place="Clavius crater, southern highlands",
        value="100–412 ppm H₂O",
        refs=("Honniball, C. I. et al. (2021) Nature Astronomy 5, 121–127, "
              "doi:10.1038/s41550-020-01222-x",),
    ),
    Discovery(
        key="chandrayaan3_sulphur", title="Sulphur in the polar regolith",
        category="water", year=2023, mission="Chandrayaan-3",
        instrument="APXS and LIBS on Pragyan", country="India", flag="🇮🇳",
        status="established",
        headline="The first in-situ chemical measurements at high southern "
                 "latitude confirmed sulphur, alongside aluminium, calcium, "
                 "iron, chromium and titanium.",
        detail="Sulphur had been inferred from orbit but never measured on the "
               "ground this far south. It matters for resource planning — "
               "sulphur is a candidate feedstock for construction materials — "
               "and for understanding how volatiles are distributed outside the "
               "permanently shadowed floors.",
        lat=-69.373, lon=32.319, place="Statio Shiv Shakti",
        value="Sulphur confirmed by two independent instruments",
        refs=("ISRO Chandrayaan-3 science results (2023)",),
    ),

    # ── Interior and structure ──────────────────────────────────────────
    Discovery(
        key="mascons", title="Mass concentrations beneath the maria",
        category="interior", year=1968, mission="Lunar Orbiter",
        instrument="Doppler tracking", country="United States", flag="🇺🇸",
        status="established",
        headline="Spacecraft tracking revealed dense mass concentrations under "
                 "the circular maria that visibly perturb lunar orbits.",
        detail="Found while analysing why orbiters kept drifting off predicted "
               "paths. Mascons are dense mantle material uplifted beneath large "
               "impact basins. They are the reason low lunar orbits are unstable "
               "and must be actively maintained — a practical constraint on "
               "every mission flown since.",
        lat=34.72, lon=345.09, place="Mare Imbrium (among the strongest)",
        refs=("Muller, P. M. & Sjogren, W. L. (1968) Science 161, 680–684, "
              "doi:10.1126/science.161.3842.680",),
    ),
    Discovery(
        key="magma_ocean", title="The Moon was once entirely molten",
        category="interior", year=1970, mission="Apollo 11 & 12",
        instrument="Returned highland samples", country="United States",
        flag="🇺🇸", status="established",
        headline="Highland rocks are dominated by anorthosite — a rock that "
                 "forms when light plagioclase crystals float to the top of a "
                 "molten body.",
        detail="A crust made this way requires a global magma ocean hundreds of "
               "kilometres deep. The idea now underpins how every rocky planet "
               "is thought to differentiate. It came from noticing that white "
               "highland rocks were the same mineral nearly everywhere.",
        value="Crust ~80 % plagioclase feldspar",
        refs=("Wood, J. A. et al. (1970) Proc. Apollo 11 Lunar Sci. Conf.",),
    ),
    Discovery(
        key="moonquakes", title="The Moon is seismically active",
        category="interior", year=1972, mission="Apollo 11–17 (ALSEP)",
        instrument="Passive Seismic Experiment", country="United States",
        flag="🇺🇸", status="established",
        headline="Seismometers left by Apollo crews recorded thousands of "
                 "moonquakes over eight years of continuous operation.",
        detail="Four types were identified: deep tidal quakes, shallow quakes, "
               "thermal quakes at dawn, and meteoroid impacts. Shallow "
               "moonquakes reach magnitude 5.5 and ring for tens of minutes, "
               "because a dry, fractured crust damps vibration far less than "
               "Earth's does. This is a direct engineering constraint on any "
               "permanent structure.",
        lat=0.674, lon=23.473, place="Apollo 11 through 17 station network",
        value="~12 000 events recorded 1969–1977",
        refs=("Nakamura, Y. et al. (1982) J. Geophys. Res. 87, A117",),
    ),
    Discovery(
        key="lunar_core", title="A small molten iron core",
        category="interior", year=2011, mission="Apollo (re-analysis)",
        instrument="Array-processed ALSEP seismic data",
        country="United States", flag="🇺🇸", status="evolving",
        headline="Reprocessing 1970s seismic recordings with modern array "
                 "methods resolved a solid inner core, a fluid outer core and a "
                 "partly molten boundary layer.",
        detail="The data had sat in archives for thirty years; the analysis "
               "techniques did not exist when it was collected. The core is "
               "roughly 330 km in radius — proportionally far smaller than "
               "Earth's — which constrains models of how the Moon formed and "
               "why it has no global magnetic field today.",
        value="Inner core ~240 km; outer core ~330 km radius",
        refs=("Weber, R. C. et al. (2011) Science 331, 309–312, "
              "doi:10.1126/science.1199375",),
    ),
    Discovery(
        key="grail_crust", title="The crust is far thinner than believed",
        category="interior", year=2013, mission="GRAIL",
        instrument="Twin-spacecraft ranging", country="United States", flag="🇺🇸",
        status="established",
        headline="Precision gravity mapping revised average crustal thickness "
                 "down from ~50 km to 34–43 km.",
        detail="GRAIL produced the highest-resolution gravity field of any body "
               "in the Solar System, Earth included. The thinner crust implies a "
               "bulk composition closer to Earth's, strengthening the giant-"
               "impact origin hypothesis. It also revealed a deep network of "
               "ancient dykes, and the resulting gravity model is what "
               "geolocates LOLA topography — including the coordinates this "
               "system uses.",
        value="Crustal thickness 34–43 km",
        refs=("Zuber, M. T. et al. (2013) Science 339, 668–671, "
              "doi:10.1126/science.1231507",),
    ),

    # ── Volcanism ───────────────────────────────────────────────────────
    Discovery(
        key="fire_fountains", title="Explosive fire-fountain eruptions",
        category="volcanism", year=1973, mission="Apollo 17",
        instrument="Returned samples", country="United States", flag="🇺🇸",
        status="established",
        headline="Orange and black glass beads found at Shorty crater formed as "
                 "spray from volcanic fountains, quenched in flight.",
        detail="The beads are coated in volatile elements, which means the "
               "eruptions were gas-driven — requiring volatiles in a Moon then "
               "thought dry. Harrison Schmitt spotted the orange soil in the "
               "field precisely because he was a geologist; it is the clearest "
               "case for sending trained observers rather than only instruments.",
        lat=20.19, lon=30.77, place="Shorty crater, Taurus–Littrow",
        value="Eruptions ~3.64 billion years ago",
        refs=("Heiken, G. H. et al. (1974) Geochim. Cosmochim. Acta 38, 1703",),
    ),
    Discovery(
        key="lava_tubes", title="Skylights into lava tubes",
        category="volcanism", year=2009, mission="Kaguya (SELENE)",
        instrument="Terrain Camera", country="Japan", flag="🇯🇵",
        status="established",
        headline="Vertical holes tens of metres across were found opening into "
                 "voids beneath the surface.",
        detail="Later LRO imaging showed the largest are entrances to intact "
               "lava tubes, some possibly kilometres long. Because lunar gravity "
               "is weak, such tubes can be far larger than any on Earth. They "
               "offer natural shielding from radiation, micrometeorites and the "
               "±150 °C surface temperature swing — which makes them the leading "
               "candidates for long-term habitation.",
        lat=14.09, lon=303.23, place="Marius Hills skylight",
        value="Opening ~50 m across, ~50 m deep",
        refs=("Haruyama, J. et al. (2009) Geophys. Res. Lett. 36, L21206, "
              "doi:10.1029/2009GL040635",),
    ),
    Discovery(
        key="young_basalt", title="Volcanism lasted a billion years longer",
        category="volcanism", year=2021, mission="Chang'e 5",
        instrument="Returned samples, radiometric dating", country="China",
        flag="🇨🇳", status="established",
        headline="Basalts returned from Oceanus Procellarum date to 2.0 billion "
                 "years — a billion years younger than any previous sample.",
        detail="Before this, the youngest dated lunar rock was about 3 billion "
               "years old and models had the Moon cooling to volcanic silence "
               "soon after. Direct dating of young terrain also recalibrated the "
               "crater-counting chronology used to date surfaces on Mars, "
               "Mercury and the asteroids — one sample return corrected ages "
               "across the Solar System.",
        lat=43.06, lon=308.08, place="Mons Rümker, Oceanus Procellarum",
        value="2.030 ± 0.004 billion years",
        refs=("Li, Q.-L. et al. (2021) Nature 600, 54–58, "
              "doi:10.1038/s41586-021-04100-2",),
    ),
    Discovery(
        key="imps", title="Possible volcanism within the last 100 million years",
        category="volcanism", year=2014, mission="LRO",
        instrument="LROC Narrow Angle Camera", country="United States",
        flag="🇺🇸", status="contested",
        headline="Small rough-textured patches carry so few superposed craters "
                 "that they may be extraordinarily young.",
        detail="Irregular Mare Patches would imply volcanic activity long after "
               "the Moon was thought geologically dead. The competing "
               "explanation is that unusual regolith properties suppress crater "
               "retention, making old terrain look young. This is listed as "
               "contested because it genuinely is — resolving it likely requires "
               "a sample, and it is exactly the sort of claim that should not be "
               "reported as settled.",
        lat=18.65, lon=33.75, place="Ina crater, Lacus Felicitatis",
        value="Model ages < 100 Myr, disputed",
        refs=("Braden, S. E. et al. (2014) Nature Geoscience 7, 787–791, "
              "doi:10.1038/ngeo2252",),
    ),

    # ── Impact history ──────────────────────────────────────────────────
    Discovery(
        key="spa_basin", title="The largest impact basin in the Solar System",
        category="impacts", year=1994, mission="Clementine",
        instrument="Laser altimeter", country="United States", flag="🇺🇸",
        status="established",
        headline="Altimetry revealed South Pole–Aitken to be 2 500 km across and "
                 "8 km deep — the largest confirmed impact structure anywhere.",
        detail="Suspected from Luna 3 imagery but only mapped when altimetry "
               "showed its true depth. The impact was violent enough to excavate "
               "lower crust and possibly mantle, making its floor the single "
               "most valuable sampling target on the Moon for understanding "
               "planetary interiors. Chang'e 6 sampled it in 2024.",
        lat=-53.0, lon=191.0, place="South Pole–Aitken basin, farside",
        value="~2 500 km across, up to 8.2 km deep",
        refs=("Zuber, M. T. et al. (1994) Science 266, 1839–1843",),
    ),
    Discovery(
        key="dichotomy", title="The two hemispheres are fundamentally different",
        category="impacts", year=1959, mission="Luna 3",
        instrument="Photographic imaging", country="Soviet Union", flag="🇷🇺",
        status="evolving",
        headline="The first images of the far side showed almost no maria — a "
                 "profound asymmetry still not fully explained.",
        detail="The nearside is about 31 % mare; the farside about 2 %. The "
               "farside crust is also thicker. Explanations include asymmetric "
               "heating from a young, close Earth, and a second body accreting "
               "onto the farside. GRAIL and Chang'e 6 have constrained the "
               "problem but not closed it — this remains one of the largest open "
               "questions in lunar science.",
        value="Nearside 31 % mare vs farside 2 %",
        refs=("Luna 3 imaging (1959)",
              "Wieczorek, M. A. et al. (2013) Science 339, 671–675"),
    ),
    Discovery(
        key="new_craters", title="The surface changes faster than expected",
        category="impacts", year=2016, mission="LRO",
        instrument="LROC temporal image pairs", country="United States",
        flag="🇺🇸", status="established",
        headline="Repeat imaging of the same ground found more than 200 new "
                 "impact craters formed during the mission itself.",
        detail="Comparing images years apart also revealed tens of thousands of "
               "surface changes from secondary impacts and debris. The top two "
               "centimetres of regolith is churned roughly a hundred times faster "
               "than models assumed — about once every 81 000 years. That "
               "directly affects how long hardware, footprints and surface "
               "installations survive.",
        value="222 new craters ≥ 10 m in ~7 years",
        refs=("Speyerer, E. J. et al. (2016) Nature 538, 215–218, "
              "doi:10.1038/nature19829",),
    ),

    # ── Surface environment ─────────────────────────────────────────────
    Discovery(
        key="cold_traps", title="The coldest places measured in the Solar System",
        category="environment", year=2010, mission="LRO",
        instrument="Diviner Lunar Radiometer", country="United States",
        flag="🇺🇸", status="established",
        headline="Permanently shadowed crater floors near the poles reach about "
                 "25 K — colder than the surface of Pluto.",
        detail="At that temperature water ice does not sublimate over the age of "
               "the Solar System, so these floors are traps that have been "
               "accumulating volatiles for billions of years. They are also "
               "brutally hostile to machinery: batteries, lubricants and "
               "electronics all fail long before 25 K without dedicated heating.",
        lat=-88.0, lon=90.0, place="South polar permanently shadowed regions",
        value="Minimum ~25 K (−248 °C)",
        refs=("Paige, D. A. et al. (2010) Science 330, 479–482, "
              "doi:10.1126/science.1187726",),
    ),
    Discovery(
        key="swirls", title="Magnetic anomalies that shield the surface",
        category="environment", year=1998, mission="Lunar Prospector",
        instrument="Magnetometer and electron reflectometer",
        country="United States", flag="🇺🇸", status="evolving",
        headline="Bright sinuous markings coincide with localised crustal "
                 "magnetic fields that deflect the solar wind.",
        detail="The Moon has no global magnetic field, but patches of magnetised "
               "crust survive. Where they occur, the solar wind is held off and "
               "the surface weathers more slowly — leaving it visibly brighter. "
               "They are natural experiments in radiation shielding, and Reiner "
               "Gamma is the best-studied example.",
        lat=7.5, lon=301.0, place="Reiner Gamma, Oceanus Procellarum",
        value="Fields up to ~100 nT at the surface",
        refs=("Hood, L. L. et al. (2001) J. Geophys. Res. 106, 27825",),
    ),
    Discovery(
        key="exosphere", title="The Moon has an atmosphere, barely",
        category="environment", year=2014, mission="LADEE",
        instrument="Neutral Mass Spectrometer and UVS",
        country="United States", flag="🇺🇸", status="established",
        headline="A collisionless exosphere of helium, argon, neon and sodium "
                 "was characterised in detail.",
        detail="So thin that atoms almost never collide — each follows a "
               "ballistic arc from the surface. LADEE also found no evidence for "
               "the high-altitude dust cloud several Apollo crews reported "
               "seeing at sunrise, which remains unexplained. Understanding the "
               "exosphere matters because human activity will perturb it, and "
               "the pristine state can only be measured once.",
        value="~10⁵ molecules cm⁻³ — 10¹⁴× thinner than Earth's",
        refs=("Benna, M. et al. (2015) Geophys. Res. Lett. 42, 3723",),
    ),
    Discovery(
        key="helium3", title="Helium-3 implanted by the solar wind",
        category="environment", year=1970, mission="Apollo 11",
        instrument="Returned sample analysis", country="United States",
        flag="🇺🇸", status="established",
        headline="Lunar soil retains helium-3 from billions of years of solar "
                 "wind exposure — an isotope vanishingly rare on Earth.",
        detail="Often cited as a fusion fuel, and that prospect is genuinely "
               "speculative: no practical helium-3 reactor exists. What is not "
               "speculative is the concentration, or its scientific value — the "
               "soil is an archive of solar activity over billions of years, "
               "readable nowhere else. Titanium-rich mare soils retain it best.",
        lat=0.674, lon=23.473, place="Mare Tranquillitatis (highest retention)",
        value="~10 ppb in mature high-Ti mare soil",
        refs=("Wittenberg, L. J. et al. (1986) Fusion Technology 10, 167",),
    ),
    Discovery(
        key="dust_hazard", title="Lunar dust is abrasive and clinging",
        category="environment", year=1972, mission="Apollo 12–17",
        instrument="Crew observation and post-mission analysis",
        country="United States", flag="🇺🇸", status="established",
        headline="Regolith dust adhered electrostatically to everything, "
                 "abraded seals and fabric, and irritated crew airways.",
        detail="Micrometeorite bombardment leaves grains sharp-edged, with no "
               "weathering to round them, and solar UV charges them so they "
               "cling. Apollo 17's crew reported hay-fever-like symptoms after "
               "dust entered the cabin. Seals degraded within a single mission. "
               "This is the most consistently underestimated engineering "
               "obstacle to sustained surface operations.",
        lat=20.19, lon=30.77, place="Taurus–Littrow (worst reported case)",
        refs=("Apollo 17 Technical Crew Debriefing (1972)",
              "Gaier, J. R. (2005) NASA/TM-2005-213610"),
    ),
)


# ---------------------------------------------------------------------------
# Access helpers
# ---------------------------------------------------------------------------

_BY_KEY = {d.key: d for d in DISCOVERIES}


def by_key(key: str) -> Discovery | None:
    return _BY_KEY.get(key)


def statistics() -> dict:
    return {
        "total": len(DISCOVERIES),
        "mappable": sum(1 for d in DISCOVERIES if d.mappable),
        "by_category": {
            c["key"]: sum(1 for d in DISCOVERIES if d.category == c["key"])
            for c in CATEGORIES
        },
        "by_status": {
            s: sum(1 for d in DISCOVERIES if d.status == s)
            for s in ("established", "evolving", "contested")
        },
        "year_range": [min(d.year for d in DISCOVERIES),
                       max(d.year for d in DISCOVERIES)],
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _self_test() -> int:
    npass = nfail = 0

    def check(name, ok, detail=""):
        nonlocal npass, nfail
        if ok:
            npass += 1
            print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
        else:
            nfail += 1
            print(f"  FAIL  {name}   {detail}")

    print("\nDiscovery catalogue integrity\n")

    check("unique keys", len(_BY_KEY) == len(DISCOVERIES),
          f"{len(DISCOVERIES)} entries")

    cat_keys = {c["key"] for c in CATEGORIES}
    bad_cat = [d.key for d in DISCOVERIES if d.category not in cat_keys]
    check("every entry has a known category", not bad_cat, str(bad_cat))

    valid_status = {"established", "evolving", "contested"}
    bad_st = [d.key for d in DISCOVERIES if d.status not in valid_status]
    check("every entry declares a confidence status", not bad_st, str(bad_st))

    no_ref = [d.key for d in DISCOVERIES if not d.refs]
    check("every entry carries a citation", not no_ref, str(no_ref))

    bad_lat = [d.key for d in DISCOVERIES
               if d.lat is not None and not -90 <= d.lat <= 90]
    check("mappable latitudes in range", not bad_lat, str(bad_lat))
    bad_lon = [d.key for d in DISCOVERIES
               if d.lon is not None and not 0 <= d.lon <= 360]
    check("mappable longitudes east-positive", not bad_lon, str(bad_lon))

    half = [d.key for d in DISCOVERIES
            if (d.lat is None) != (d.place is None)]
    check("coordinates and place names agree", not half, str(half))

    print("\nWater is treated as four separate findings, not one\n")
    water = [d for d in DISCOVERIES if d.category == "water"]
    check("water category has multiple distinct discoveries", len(water) >= 5,
          f"{len(water)} entries")
    for d in water:
        print(f"    {d.year}  {d.title:<46} {d.status}")

    print("\nContested claims are labelled as such\n")
    contested = [d for d in DISCOVERIES if d.status == "contested"]
    check("at least one contested claim is flagged", len(contested) >= 1,
          ", ".join(d.title for d in contested))

    st = statistics()
    print()
    for k, v in st.items():
        print(f"    {k:<16} {v}")

    check("catalogue spans the whole exploration era",
          st["year_range"][0] < 1970 and st["year_range"][1] > 2020,
          f"{st['year_range']}")
    check("most entries are mappable to a place",
          st["mappable"] >= len(DISCOVERIES) * 0.6,
          f"{st['mappable']}/{len(DISCOVERIES)}")

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
