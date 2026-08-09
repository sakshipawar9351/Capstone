"""
Lunar surface missions — every spacecraft that has reached the Moon's surface.

Scope
-----
Missions that made contact with the surface: deliberate impacts, failed landings
that struck the Moon, soft landings, rovers, sample returns and crewed missions.
Orbiters that never descended are out of scope; orbiters that ended in a
*controlled impact* are included, because they produced a surface event with a
known location.

Coordinate provenance — why this matters
----------------------------------------
Landing coordinates published at the time of each mission were derived from
tracking and dead reckoning, and several were wrong by kilometres.  The Lunar
Reconnaissance Orbiter Camera has since imaged the hardware itself, so most
historic sites now have positions good to a few metres.

Every entry therefore carries a ``coord_precision`` field:

``measured``
    The spacecraft or its shadow is visible in LROC imagery and the position
    was measured from it.  Accurate to roughly 10 m or better.
``reported``
    The operating agency's stated touchdown or impact point, not yet
    independently confirmed by imaging.  Typically good to hundreds of metres.
``approximate``
    Only a target region is known — usually a failed landing whose debris has
    not been located.  May be wrong by tens of kilometres.

Conflating these would be the same error as quoting a model prediction as a
measurement, so the interface displays the distinction.

Primary reference for measured coordinates
------------------------------------------
Wagner, R. V., Nelson, D. M., Plescia, J. B., Robinson, M. S., Speyerer, E. J.
& Mazarico, E. (2017), "Coordinates of anthropogenic features on the Moon",
*Icarus* 283, 92–103.  doi:10.1016/j.icarus.2016.05.011

Supporting sources
------------------
NASA NSSDCA Master Catalog — https://nssdc.gsfc.nasa.gov/nmc/
LROC featured landing-site imagery — https://lroc.asu.edu/
Per-mission agency releases are cited in individual entries where they are the
authority (recent commercial and non-US missions).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Mission", "MISSIONS", "by_key", "countries", "statistics"]


@dataclass(frozen=True)
class Mission:
    """One spacecraft that reached the lunar surface."""

    key: str
    name: str
    agency: str
    country: str
    flag: str
    year: int
    arrival: str                 # ISO date of surface contact
    kind: str                    # impact | landing | rover | sample_return | crewed
    outcome: str                 # success | partial | failure
    lat: float | None
    lon: float | None            # east-positive, 0-360
    site: str
    coord_precision: str         # measured | reported | approximate
    summary: str
    achievements: tuple[str, ...] = ()
    crew: tuple[str, ...] = ()
    sample_mass_g: float | None = None
    surface_duration: str | None = None
    traverse_km: float | None = None
    refs: tuple[str, ...] = ()

    @property
    def is_first(self) -> bool:
        return any(a.lower().startswith("first") for a in self.achievements)

    def to_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name, "agency": self.agency,
            "country": self.country, "flag": self.flag, "year": self.year,
            "arrival": self.arrival, "kind": self.kind, "outcome": self.outcome,
            "lat": self.lat, "lon": self.lon, "site": self.site,
            "coord_precision": self.coord_precision,
            "summary": self.summary,
            "achievements": list(self.achievements),
            "crew": list(self.crew),
            "sample_mass_g": self.sample_mass_g,
            "surface_duration": self.surface_duration,
            "traverse_km": self.traverse_km,
            "refs": list(self.refs),
            "is_first": self.is_first,
        }


W2017 = "Wagner et al. (2017) Icarus 283, 92–103, doi:10.1016/j.icarus.2016.05.011"
NSSDC = "NASA NSSDCA Master Catalog"


# ---------------------------------------------------------------------------
# The catalogue, in chronological order of surface contact
# ---------------------------------------------------------------------------

#: Grouped by country below purely so the source reads well.  The exported
#: ``MISSIONS`` is sorted chronologically, which is the order the history
#: actually happened in and the order every consumer wants.
_CATALOGUE: tuple[Mission, ...] = (

    # ── Soviet Union ────────────────────────────────────────────────────
    Mission(
        key="luna2", name="Luna 2", agency="OKB-1", country="Soviet Union",
        flag="🇷🇺", year=1959, arrival="1959-09-14", kind="impact",
        outcome="success", lat=29.1, lon=0.0, site="Palus Putredinis",
        coord_precision="approximate",
        summary="The first human-made object to reach another celestial body, "
                "impacting east of Mare Imbrium.",
        achievements=(
            "First spacecraft to reach the surface of another world",
            "Confirmed the Moon has no appreciable magnetic field",
            "Confirmed the Moon has no radiation belt",
        ),
        refs=(NSSDC,),
    ),
    Mission(
        key="luna9", name="Luna 9", agency="Lavochkin", country="Soviet Union",
        flag="🇷🇺", year=1966, arrival="1966-02-03", kind="landing",
        outcome="success", lat=7.08, lon=295.63, site="Oceanus Procellarum",
        coord_precision="measured",
        summary="The first spacecraft to survive a landing on another world and "
                "transmit from its surface.",
        achievements=(
            "First survivable soft landing on another celestial body",
            "First photographs taken from the surface of another world",
            "Showed the regolith bears a lander's weight — settling the fear "
            "that a spacecraft would sink into deep dust",
        ),
        surface_duration="3 days",
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="luna13", name="Luna 13", agency="Lavochkin", country="Soviet Union",
        flag="🇷🇺", year=1966, arrival="1966-12-24", kind="landing",
        outcome="success", lat=18.87, lon=297.95, site="Oceanus Procellarum",
        coord_precision="measured",
        summary="Second Soviet soft landing, carrying instruments to measure the "
                "mechanical properties of the regolith directly.",
        achievements=(
            "First mechanical soil-density measurement on another world",
            "Penetrometer and radiation densitometer characterised regolith "
            "bearing strength",
        ),
        surface_duration="6 days",
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="luna16", name="Luna 16", agency="Lavochkin", country="Soviet Union",
        flag="🇷🇺", year=1970, arrival="1970-09-20", kind="sample_return",
        outcome="success", lat=-0.51, lon=56.36, site="Mare Fecunditatis",
        coord_precision="measured",
        summary="The first robotic mission to collect material from another "
                "world and return it to Earth.",
        achievements=(
            "First robotic sample return from another celestial body",
            "Demonstrated automated drilling, ascent and Earth return",
            "Returned mare basalt distinct from all Apollo samples",
        ),
        sample_mass_g=101.0,
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="luna17", name="Luna 17 / Lunokhod 1", agency="Lavochkin",
        country="Soviet Union", flag="🇷🇺", year=1970, arrival="1970-11-17",
        kind="rover", outcome="success", lat=38.2378, lon=324.9982,
        site="Mare Imbrium", coord_precision="measured",
        summary="Delivered Lunokhod 1, the first wheeled vehicle to operate on "
                "another world, driven remotely from Earth.",
        achievements=(
            "First remote-controlled rover on another celestial body",
            "Operated 10 months — far beyond its 3-month design life",
            "Its retroreflector is still ranged by lasers from Earth today",
        ),
        traverse_km=10.5,
        surface_duration="322 days",
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="luna20", name="Luna 20", agency="Lavochkin", country="Soviet Union",
        flag="🇷🇺", year=1972, arrival="1972-02-21", kind="sample_return",
        outcome="success", lat=3.79, lon=56.63, site="Apollonius highlands",
        coord_precision="measured",
        summary="Returned the first robotic sample of the lunar highlands, a "
                "terrain type Luna 16 had not sampled.",
        achievements=(
            "First robotic sample of lunar highland crust",
            "Returned anorthositic material supporting the magma-ocean model",
        ),
        sample_mass_g=55.0,
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="luna21", name="Luna 21 / Lunokhod 2", agency="Lavochkin",
        country="Soviet Union", flag="🇷🇺", year=1973, arrival="1973-01-15",
        kind="rover", outcome="success", lat=25.99, lon=30.41,
        site="Le Monnier crater, Mare Serenitatis", coord_precision="measured",
        summary="The second Soviet rover, which drove further than any vehicle "
                "on another world for the next four decades.",
        achievements=(
            "Longest off-world traverse until Opportunity surpassed it in 2014",
            "Returned over 80 000 television images",
            "Magnetometer surveyed local crustal magnetism along the route",
        ),
        traverse_km=39.0,
        surface_duration="4 months",
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="luna24", name="Luna 24", agency="Lavochkin", country="Soviet Union",
        flag="🇷🇺", year=1976, arrival="1976-08-18", kind="sample_return",
        outcome="success", lat=12.71, lon=62.21, site="Mare Crisium",
        coord_precision="measured",
        summary="The last Soviet lunar mission and the final sample return of "
                "the 20th century.",
        achievements=(
            "Deepest robotic core of the era — drilled to ~2 m",
            "Its samples were later found to contain indigenous water, "
            "overturning the belief that the Moon was entirely dry",
            "Last spacecraft to land on the Moon until Chang'e 3, 37 years on",
        ),
        sample_mass_g=170.0,
        refs=(W2017, NSSDC),
    ),

    # ── United States ───────────────────────────────────────────────────
    Mission(
        key="ranger7", name="Ranger 7", agency="NASA", country="United States",
        flag="🇺🇸", year=1964, arrival="1964-07-31", kind="impact",
        outcome="success", lat=-10.63, lon=339.34, site="Mare Cognitum",
        coord_precision="measured",
        summary="Returned the first American close-up images of the Moon, "
                "transmitting until the moment of impact.",
        achievements=(
            "First US mission to return close-up lunar images — 4 308 frames",
            "Resolved features 1 000× smaller than the best telescopes could",
            "Its target region was named Mare Cognitum, 'the sea that has "
            "become known', for this result",
        ),
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="ranger8", name="Ranger 8", agency="NASA", country="United States",
        flag="🇺🇸", year=1965, arrival="1965-02-20", kind="impact",
        outcome="success", lat=2.71, lon=24.81, site="Mare Tranquillitatis",
        coord_precision="measured",
        summary="Imaged the region that would later receive Apollo 11.",
        achievements=("Returned 7 137 images of the future Apollo landing zone",),
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="ranger9", name="Ranger 9", agency="NASA", country="United States",
        flag="🇺🇸", year=1965, arrival="1965-03-24", kind="impact",
        outcome="success", lat=-12.83, lon=357.63, site="Alphonsus crater",
        coord_precision="measured",
        summary="Targeted a crater floor of suspected volcanic activity; its "
                "descent was broadcast live on American television.",
        achievements=(
            "First lunar images broadcast live to the public",
            "Imaged dark-halo craters interpreted as volcanic vents",
        ),
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="surveyor1", name="Surveyor 1", agency="NASA", country="United States",
        flag="🇺🇸", year=1966, arrival="1966-06-02", kind="landing",
        outcome="success", lat=-2.47, lon=316.53, site="Oceanus Procellarum",
        coord_precision="measured",
        summary="The first American soft landing, achieved on the first attempt.",
        achievements=(
            "First US soft landing on another world",
            "Returned 11 240 images including the first lunar sunset sequence",
            "Confirmed the surface could support a crewed lander",
        ),
        surface_duration="6 weeks",
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="surveyor3", name="Surveyor 3", agency="NASA", country="United States",
        flag="🇺🇸", year=1967, arrival="1967-04-20", kind="landing",
        outcome="success", lat=-2.99, lon=336.57, site="Oceanus Procellarum",
        coord_precision="measured",
        summary="Carried a soil-scoop arm, and later became the only spacecraft "
                "ever visited by human beings on another world.",
        achievements=(
            "First mechanical arm to excavate soil on another world",
            "Visited by Apollo 12 in 1969; parts returned to Earth after "
            "31 months of lunar exposure",
            "Its returned camera provided the first data on long-duration "
            "material degradation in the lunar environment",
        ),
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="surveyor5", name="Surveyor 5", agency="NASA", country="United States",
        flag="🇺🇸", year=1967, arrival="1967-09-11", kind="landing",
        outcome="success", lat=1.42, lon=23.20, site="Mare Tranquillitatis",
        coord_precision="measured",
        summary="Performed the first chemical analysis of the surface of another "
                "world using an alpha-scattering instrument.",
        achievements=(
            "First in-situ chemical analysis of another planetary surface",
            "Showed mare soil is basaltic — settling a long-running debate",
        ),
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="surveyor6", name="Surveyor 6", agency="NASA", country="United States",
        flag="🇺🇸", year=1967, arrival="1967-11-10", kind="landing",
        outcome="success", lat=0.49, lon=358.60, site="Sinus Medii",
        coord_precision="measured",
        summary="Landed near the centre of the visible disc, then fired its "
                "engines again and hopped to a new position.",
        achievements=(
            "First liftoff from the surface of another world",
            "The 2.4 m hop gave stereo views and tested ascent feasibility",
        ),
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="surveyor7", name="Surveyor 7", agency="NASA", country="United States",
        flag="🇺🇸", year=1968, arrival="1968-01-10", kind="landing",
        outcome="success", lat=-41.01, lon=348.59, site="Tycho north rim",
        coord_precision="measured",
        summary="The only Surveyor sent for science rather than Apollo "
                "reconnaissance, targeting the rugged ejecta of Tycho.",
        achievements=(
            "First landing in the lunar highlands",
            "Showed highland soil differs chemically from mare soil — lower "
            "iron, higher aluminium",
        ),
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="apollo11", name="Apollo 11", agency="NASA", country="United States",
        flag="🇺🇸", year=1969, arrival="1969-07-20", kind="crewed",
        outcome="success", lat=0.67409, lon=23.47298,
        site="Mare Tranquillitatis — Statio Tranquillitatis",
        coord_precision="measured",
        summary="The first crewed landing on another world.",
        achievements=(
            "First humans to land on and walk upon another celestial body",
            "Deployed the first retroreflector, still ranged from Earth to "
            "measure the Earth–Moon distance to millimetres",
            "Returned samples showing mare basalts are ~3.7 billion years old",
        ),
        crew=("Neil Armstrong", "Buzz Aldrin"),
        sample_mass_g=21550.0,
        surface_duration="21 h 36 min",
        traverse_km=0.25,
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="apollo12", name="Apollo 12", agency="NASA", country="United States",
        flag="🇺🇸", year=1969, arrival="1969-11-19", kind="crewed",
        outcome="success", lat=-3.01381, lon=336.57774,
        site="Oceanus Procellarum", coord_precision="measured",
        summary="Demonstrated precision landing by touching down within walking "
                "distance of Surveyor 3, which had arrived two years earlier.",
        achievements=(
            "First pinpoint landing on another world — 163 m from its target",
            "First deployment of a long-duration surface science station (ALSEP)",
            "Retrieved hardware from an earlier spacecraft for study on Earth",
        ),
        crew=("Pete Conrad", "Alan Bean"),
        sample_mass_g=34350.0,
        surface_duration="31 h 31 min",
        traverse_km=1.35,
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="apollo14", name="Apollo 14", agency="NASA", country="United States",
        flag="🇺🇸", year=1971, arrival="1971-02-05", kind="crewed",
        outcome="success", lat=-3.64530, lon=342.52157,
        site="Fra Mauro formation", coord_precision="measured",
        summary="Reached the Fra Mauro highlands, ejecta from the Imbrium "
                "impact — the target Apollo 13 had been forced to abandon.",
        achievements=(
            "First sampling of Imbrium basin ejecta, dating that impact",
            "Returned 'Big Bertha', later found to contain what may be the "
            "oldest known Earth rock, launched to the Moon by an impact",
            "First use of a wheeled equipment transporter on another world",
        ),
        crew=("Alan Shepard", "Edgar Mitchell"),
        sample_mass_g=42280.0,
        surface_duration="33 h 31 min",
        traverse_km=3.45,
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="apollo15", name="Apollo 15", agency="NASA", country="United States",
        flag="🇺🇸", year=1971, arrival="1971-07-30", kind="crewed",
        outcome="success", lat=26.13222, lon=3.63386,
        site="Hadley–Apennine", coord_precision="measured",
        summary="The first mission carrying a rover, landing between a mountain "
                "front and a sinuous rille.",
        achievements=(
            "First use of a crewed vehicle on another world (Lunar Roving Vehicle)",
            "Collected the 'Genesis Rock', a fragment of primordial lunar crust",
            "Performed the hammer-and-feather drop, demonstrating Galileo's "
            "equivalence principle in a vacuum",
        ),
        crew=("David Scott", "James Irwin"),
        sample_mass_g=77310.0,
        surface_duration="66 h 55 min",
        traverse_km=27.9,
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="apollo16", name="Apollo 16", agency="NASA", country="United States",
        flag="🇺🇸", year=1972, arrival="1972-04-21", kind="crewed",
        outcome="success", lat=-8.97341, lon=15.49859,
        site="Descartes highlands", coord_precision="measured",
        summary="The only crewed landing in the central highlands, sent to test "
                "the hypothesis that the region was volcanic.",
        achievements=(
            "Disproved the volcanic-highlands hypothesis — the rocks are "
            "impact breccias, a result obtained by going and looking",
            "Deployed the first astronomical telescope operated from another "
            "world (far-ultraviolet camera)",
            "Highest-latitude Apollo sampling of ancient crust",
        ),
        crew=("John Young", "Charles Duke"),
        sample_mass_g=95710.0,
        surface_duration="71 h 02 min",
        traverse_km=26.7,
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="apollo17", name="Apollo 17", agency="NASA", country="United States",
        flag="🇺🇸", year=1972, arrival="1972-12-11", kind="crewed",
        outcome="success", lat=20.19080, lon=30.77168,
        site="Taurus–Littrow valley", coord_precision="measured",
        summary="The final crewed landing, and the only one to carry a "
                "professional geologist.",
        achievements=(
            "Only crewed mission to include a trained geologist (Schmitt)",
            "Discovered orange volcanic glass — evidence of explosive "
            "fire-fountain eruptions 3.6 billion years ago",
            "Largest sample return of any mission: 110.5 kg",
            "Last time humans stood on another world",
        ),
        crew=("Eugene Cernan", "Harrison Schmitt"),
        sample_mass_g=110520.0,
        surface_duration="74 h 59 min",
        traverse_km=35.7,
        refs=(W2017, NSSDC),
    ),
    Mission(
        key="lcross", name="LCROSS", agency="NASA", country="United States",
        flag="🇺🇸", year=2009, arrival="2009-10-09", kind="impact",
        outcome="success", lat=-84.675, lon=311.275, site="Cabeus crater",
        coord_precision="reported",
        summary="Deliberately crashed a spent rocket stage into a permanently "
                "shadowed polar crater and flew through the debris plume.",
        achievements=(
            "First direct detection of water ice in a lunar cold trap",
            "Measured ~5.6 % water by mass in the ejected material",
            "Established the resource case for polar exploration",
        ),
        refs=("Colaprete et al. (2010) Science 330, 463–468, "
              "doi:10.1126/science.1186986", NSSDC),
    ),
    Mission(
        key="grail", name="GRAIL (Ebb & Flow)", agency="NASA",
        country="United States", flag="🇺🇸", year=2012, arrival="2012-12-17",
        kind="impact", outcome="success", lat=75.62, lon=333.41,
        site="Northern rim, Goldschmidt crater", coord_precision="reported",
        summary="Twin gravity-mapping orbiters ended their mission with a "
                "controlled impact once their fuel was exhausted.",
        achievements=(
            "Produced the highest-resolution gravity field of any body, "
            "including Earth",
            "Revealed the crust is far thinner than believed — 34–43 km",
            "Its gravity model underpins the geolocation of LOLA topography, "
            "and therefore this system's own coordinates",
        ),
        refs=("Zuber et al. (2013) Science 339, 668–671, "
              "doi:10.1126/science.1231507", NSSDC),
    ),
    Mission(
        key="ladee", name="LADEE", agency="NASA", country="United States",
        flag="🇺🇸", year=2014, arrival="2014-04-18", kind="impact",
        outcome="success", lat=-11.85, lon=93.25, site="Farside, near Sundman V",
        coord_precision="reported",
        summary="Studied the tenuous lunar exosphere and dust environment before "
                "a planned impact.",
        achievements=(
            "Characterised the Moon's extremely thin exosphere",
            "Found no evidence for the high-altitude dust cloud reported by "
            "Apollo astronauts",
        ),
        refs=(NSSDC,),
    ),
    Mission(
        key="im1", name="IM-1 Odysseus", agency="Intuitive Machines",
        country="United States", flag="🇺🇸", year=2024, arrival="2024-02-22",
        kind="landing", outcome="partial", lat=-80.13, lon=1.44,
        site="Malapert A, near south pole", coord_precision="reported",
        summary="The first commercial spacecraft to soft-land on the Moon, and "
                "the first US landing in over half a century — though it broke "
                "a leg and came to rest tilted.",
        achievements=(
            "First commercially operated soft landing on another world",
            "First US soft landing since Apollo 17 in 1972",
            "Southernmost landing achieved at the time",
        ),
        surface_duration="~7 days",
        refs=("Intuitive Machines mission reports", "NASA CLPS"),
    ),
    Mission(
        key="blueghost1", name="Blue Ghost Mission 1",
        agency="Firefly Aerospace", country="United States", flag="🇺🇸",
        year=2025, arrival="2025-03-02", kind="landing", outcome="success",
        lat=18.56, lon=61.81, site="Mare Crisium", coord_precision="reported",
        summary="The first fully successful commercial lunar landing, operating "
                "a full lunar day with all payloads functional.",
        achievements=(
            "First commercial soft landing to complete its mission fully upright "
            "and operational",
            "Operated ten NASA payloads through a complete lunar day",
            "Imaged a total solar eclipse from the lunar surface",
        ),
        surface_duration="14 days (a full lunar day)",
        refs=("Firefly Aerospace mission reports", "NASA CLPS"),
    ),
    Mission(
        key="im2", name="IM-2 Athena", agency="Intuitive Machines",
        country="United States", flag="🇺🇸", year=2025, arrival="2025-03-06",
        kind="landing", outcome="partial", lat=-84.79, lon=29.35,
        site="Mons Mouton, south polar region", coord_precision="reported",
        summary="Touched down softly closer to the south pole than any prior "
                "mission, but toppled and could not generate enough power.",
        achievements=(
            "Closest approach to the lunar south pole by a landed spacecraft",
            "Demonstrated precision descent to high-latitude rough terrain",
        ),
        surface_duration="~1 day (power-limited)",
        refs=("Intuitive Machines mission reports", "NASA CLPS"),
    ),

    # ── China ───────────────────────────────────────────────────────────
    Mission(
        key="change3", name="Chang'e 3 / Yutu", agency="CNSA", country="China",
        flag="🇨🇳", year=2013, arrival="2013-12-14", kind="rover",
        outcome="success", lat=44.1214, lon=340.4884,
        site="Mare Imbrium", coord_precision="measured",
        summary="Ended a 37-year gap in soft landings and delivered China's "
                "first rover, Yutu.",
        achievements=(
            "First soft landing on the Moon since Luna 24 in 1976",
            "Ground-penetrating radar produced the first direct subsurface "
            "profile of lunar regolith and buried lava flows",
            "Identified a previously unknown basalt type",
        ),
        traverse_km=0.114,
        refs=("Xiao et al. (2015) Science 347, 1226–1229, "
              "doi:10.1126/science.1259866", NSSDC),
    ),
    Mission(
        key="change4", name="Chang'e 4 / Yutu-2", agency="CNSA", country="China",
        flag="🇨🇳", year=2019, arrival="2019-01-03", kind="rover",
        outcome="success", lat=-45.4446, lon=177.5991,
        site="Von Kármán crater, South Pole–Aitken basin",
        coord_precision="measured",
        summary="The first landing on the far side of the Moon, made possible by "
                "a dedicated relay satellite at the Earth–Moon L2 point.",
        achievements=(
            "First soft landing on the lunar far side",
            "First communications relay enabling far-side surface operations",
            "Radar sounding revealed the layered structure beneath SPA basin",
            "Yutu-2 became the longest-operating lunar rover in history",
        ),
        traverse_km=1.6,
        refs=("Li et al. (2019) Nature 569, 378–382, "
              "doi:10.1038/s41586-019-1189-0", NSSDC),
    ),
    Mission(
        key="change5", name="Chang'e 5", agency="CNSA", country="China",
        flag="🇨🇳", year=2020, arrival="2020-12-01", kind="sample_return",
        outcome="success", lat=43.0576, lon=308.0839,
        site="Mons Rümker, Oceanus Procellarum", coord_precision="measured",
        summary="Returned the first lunar samples in 44 years, targeting terrain "
                "far younger than anything Apollo or Luna reached.",
        achievements=(
            "First lunar sample return since 1976",
            "Returned basalts just 2.0 billion years old — 1 billion years "
            "younger than any previous sample, proving volcanism persisted "
            "far longer than models predicted",
            "Recalibrated the crater-counting chronology used to date surfaces "
            "across the entire Solar System",
        ),
        sample_mass_g=1731.0,
        refs=("Li et al. (2021) Nature 600, 54–58, "
              "doi:10.1038/s41586-021-04100-2", NSSDC),
    ),
    Mission(
        key="change6", name="Chang'e 6", agency="CNSA", country="China",
        flag="🇨🇳", year=2024, arrival="2024-06-02", kind="sample_return",
        outcome="success", lat=-41.6385, lon=206.0033,
        site="Apollo basin, South Pole–Aitken", coord_precision="measured",
        summary="The first mission to collect material from the far side of the "
                "Moon and return it to Earth.",
        achievements=(
            "First sample return from the lunar far side",
            "Sampled the South Pole–Aitken basin, the oldest and largest "
            "impact structure on the Moon",
            "Provides the first direct test of why the two hemispheres differ "
            "so profoundly",
        ),
        sample_mass_g=1935.3,
        refs=("CNSA mission reports", NSSDC),
    ),

    # ── India ───────────────────────────────────────────────────────────
    Mission(
        key="mip", name="Chandrayaan-1 Moon Impact Probe", agency="ISRO",
        country="India", flag="🇮🇳", year=2008, arrival="2008-11-14",
        kind="impact", outcome="success", lat=-89.0, lon=0.0,
        site="Near Shackleton crater, south pole", coord_precision="approximate",
        summary="India's first object on the Moon, released from the "
                "Chandrayaan-1 orbiter to strike the south polar region.",
        achievements=(
            "First Indian spacecraft to reach the lunar surface",
            "Its mass spectrometer detected water in the tenuous exosphere "
            "during descent, part of the evidence overturning the view of a "
            "completely dry Moon",
        ),
        refs=("Sridharan et al. (2010) Planet. Space Sci. 58, 947–950", NSSDC),
    ),
    Mission(
        key="chandrayaan3", name="Chandrayaan-3 (Vikram & Pragyan)",
        agency="ISRO", country="India", flag="🇮🇳", year=2023,
        arrival="2023-08-23", kind="rover", outcome="success",
        lat=-69.373, lon=32.319, site="Statio Shiv Shakti, south polar highlands",
        coord_precision="reported",
        summary="Made India the fourth nation to land softly on the Moon, and "
                "the first to do so in the high southern latitudes.",
        achievements=(
            "First soft landing in the lunar south polar region",
            "Fourth nation to achieve a soft lunar landing",
            "Measured the thermal profile of the polar regolith directly, "
            "finding a steep gradient in the top few centimetres",
            "Confirmed sulphur in the polar soil by in-situ spectroscopy",
        ),
        traverse_km=0.1,
        surface_duration="14 days (one lunar day)",
        refs=("ISRO mission reports", NSSDC),
    ),

    # ── Japan ───────────────────────────────────────────────────────────
    Mission(
        key="hiten", name="Hiten", agency="ISAS/JAXA", country="Japan",
        flag="🇯🇵", year=1993, arrival="1993-04-10", kind="impact",
        outcome="success", lat=-34.3, lon=55.6, site="Near Furnerius crater",
        coord_precision="approximate",
        summary="Japan's first lunar mission, an engineering testbed that ended "
                "with a controlled impact.",
        achievements=(
            "Third nation to place a spacecraft at the Moon",
            "Pioneered low-energy ballistic capture trajectories now used "
            "widely to reach the Moon on minimal fuel",
        ),
        refs=(NSSDC,),
    ),
    Mission(
        key="kaguya", name="Kaguya (SELENE)", agency="JAXA", country="Japan",
        flag="🇯🇵", year=2009, arrival="2009-06-10", kind="impact",
        outcome="success", lat=-65.5, lon=80.4, site="Near Gill crater",
        coord_precision="reported",
        summary="A major orbital survey mission concluded by a controlled impact.",
        achievements=(
            "Its Terrain Camera stereo data underpins the SLDEM2015 topographic "
            "model still in scientific use",
            "Obtained the first high-definition video of the Moon from orbit",
            "Discovered vertical holes interpreted as skylights into lava tubes",
        ),
        refs=("Haruyama et al. (2009) Science 323, 905–908", NSSDC),
    ),
    Mission(
        key="slim", name="SLIM", agency="JAXA", country="Japan", flag="🇯🇵",
        year=2024, arrival="2024-01-19", kind="landing", outcome="partial",
        lat=-13.3160, lon=25.2510, site="Shioli crater, Mare Nectaris",
        coord_precision="measured",
        summary="A demonstrator for precision landing that hit its target within "
                "metres, then came to rest nose-down with its solar cells "
                "facing the wrong way.",
        achievements=(
            "Most accurate lunar landing ever achieved — within ~55 m of target, "
            "against the kilometres typical of earlier missions",
            "Fifth nation to land softly on the Moon",
            "Survived multiple lunar nights it was never designed to endure",
        ),
        surface_duration="Intermittent over several months",
        refs=("JAXA mission reports", NSSDC),
    ),

    # ── Failed landings, included because they reached the surface ──────
    Mission(
        key="beresheet", name="Beresheet", agency="SpaceIL / IAI",
        country="Israel", flag="🇮🇱", year=2019, arrival="2019-04-11",
        kind="landing", outcome="failure", lat=32.5956, lon=19.3496,
        site="Mare Serenitatis", coord_precision="measured",
        summary="The first privately funded lunar landing attempt, lost when its "
                "main engine shut down during descent.",
        achievements=(
            "First privately funded spacecraft to reach the Moon",
            "Seventh spacecraft ever to enter lunar orbit",
            "Its impact site was later imaged by LRO, and the crash itself "
            "became a calibration target for impact studies",
        ),
        refs=(W2017, "LROC impact-site imagery"),
    ),
    Mission(
        key="vikram2", name="Chandrayaan-2 Vikram", agency="ISRO",
        country="India", flag="🇮🇳", year=2019, arrival="2019-09-06",
        kind="landing", outcome="failure", lat=-70.881, lon=22.784,
        site="South polar highlands", coord_precision="measured",
        summary="Lost control during its final braking phase and struck the "
                "surface; debris was later located in LRO imagery.",
        achievements=(
            "Its orbiter remains operational and continues returning data, "
            "including the 0.25 m/px OHRC imagery used by this project",
        ),
        refs=("LROC impact-site imagery", NSSDC),
    ),
    Mission(
        key="hakutor1", name="Hakuto-R Mission 1", agency="ispace",
        country="Japan", flag="🇯🇵", year=2023, arrival="2023-04-25",
        kind="landing", outcome="failure", lat=47.581, lon=44.094,
        site="Atlas crater, Mare Frigoris", coord_precision="measured",
        summary="Ran out of propellant while hovering, after its altimeter was "
                "confused by the rim of the crater it was crossing.",
        achievements=(
            "First commercial lunar landing attempt by a Japanese company",
            "Its failure traced to software rejecting a genuine altitude jump "
            "as sensor error — a case study now cited in landing-system design",
        ),
        refs=("ispace technical analysis", "LROC impact-site imagery"),
    ),
    Mission(
        key="luna25", name="Luna 25", agency="Roscosmos", country="Russia",
        flag="🇷🇺", year=2023, arrival="2023-08-19", kind="landing",
        outcome="failure", lat=-57.865, lon=61.360, site="Near Pontécoulant G",
        coord_precision="measured",
        summary="Russia's first lunar mission in 47 years, lost when an engine "
                "burn ran long and dropped it into an impact trajectory.",
        achievements=(
            "First Russian lunar mission since Luna 24 in 1976",
            "Its impact crater was located by LRO, giving a precise position",
        ),
        refs=("LROC impact-site imagery", NSSDC),
    ),
    Mission(
        key="hakutor2", name="Hakuto-R Mission 2 (Resilience)", agency="ispace",
        country="Japan", flag="🇯🇵", year=2025, arrival="2025-06-05",
        kind="landing", outcome="failure", lat=60.5, lon=355.0,
        site="Mare Frigoris", coord_precision="reported",
        summary="A second commercial attempt lost to a hard landing when its "
                "laser rangefinder failed to return valid altitude data.",
        achievements=(
            "Completed 8 of 9 mission milestones before descent",
            "Cause isolated to the laser range finder — not guidance software, "
            "propulsion or power — and published openly",
        ),
        refs=("ispace technical cause analysis (2025)",
              "NASA LRO impact-site imagery"),
    ),

    # ── Europe ──────────────────────────────────────────────────────────
    Mission(
        key="smart1", name="SMART-1", agency="ESA", country="Europe",
        flag="🇪🇺", year=2006, arrival="2006-09-03", kind="impact",
        outcome="success", lat=-34.262, lon=313.55, site="Lacus Excellentiae",
        coord_precision="measured",
        summary="Europe's first lunar mission, which reached the Moon using "
                "solar-electric propulsion and ended in a controlled impact.",
        achievements=(
            "First European spacecraft at the Moon",
            "First use of ion propulsion as primary propulsion to another world",
            "Demonstrated the technique now standard for deep-space missions",
        ),
        refs=("Foing et al. (2006) Adv. Space Res.", NSSDC),
    ),
)


#: Chronological by surface contact — the order the history happened in.
MISSIONS: tuple[Mission, ...] = tuple(
    sorted(_CATALOGUE, key=lambda m: (m.arrival, m.key))
)


# ---------------------------------------------------------------------------
# Access helpers
# ---------------------------------------------------------------------------

_BY_KEY = {m.key: m for m in MISSIONS}


def by_key(key: str) -> Mission | None:
    return _BY_KEY.get(key)


def countries() -> list[dict]:
    """Missions grouped by country, ordered by count."""
    agg: dict[str, dict] = {}
    for m in MISSIONS:
        c = agg.setdefault(m.country, {
            "country": m.country, "flag": m.flag, "count": 0,
            "success": 0, "keys": [],
        })
        c["count"] += 1
        c["success"] += 1 if m.outcome == "success" else 0
        c["keys"].append(m.key)
    return sorted(agg.values(), key=lambda c: -c["count"])


def statistics() -> dict:
    total_samples = sum(m.sample_mass_g or 0 for m in MISSIONS)
    total_traverse = sum(m.traverse_km or 0 for m in MISSIONS)
    return {
        "total_missions": len(MISSIONS),
        "by_outcome": {
            o: sum(1 for m in MISSIONS if m.outcome == o)
            for o in ("success", "partial", "failure")
        },
        "by_kind": {
            k: sum(1 for m in MISSIONS if m.kind == k)
            for k in ("impact", "landing", "rover", "sample_return", "crewed")
        },
        "countries": len({m.country for m in MISSIONS}),
        "total_sample_mass_kg": round(total_samples / 1000.0, 2),
        "total_traverse_km": round(total_traverse, 2),
        "crewed_landings": sum(1 for m in MISSIONS if m.kind == "crewed"),
        "people_landed": sum(len(m.crew) for m in MISSIONS),
        "year_range": [min(m.year for m in MISSIONS),
                       max(m.year for m in MISSIONS)],
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

    print("\nMission catalogue integrity\n")

    check("unique keys", len(_BY_KEY) == len(MISSIONS),
          f"{len(MISSIONS)} missions, {len(_BY_KEY)} keys")

    bad_lat = [m.key for m in MISSIONS
               if m.lat is not None and not -90 <= m.lat <= 90]
    check("all latitudes in range", not bad_lat, str(bad_lat))

    bad_lon = [m.key for m in MISSIONS
               if m.lon is not None and not 0 <= m.lon <= 360]
    check("all longitudes east-positive 0–360", not bad_lon, str(bad_lon))

    no_coord = [m.key for m in MISSIONS if m.lat is None]
    check("every mission has a position", not no_coord, str(no_coord))

    valid_prec = {"measured", "reported", "approximate"}
    bad_p = [m.key for m in MISSIONS if m.coord_precision not in valid_prec]
    check("coordinate precision declared for all", not bad_p, str(bad_p))

    no_ach = [m.key for m in MISSIONS if not m.achievements]
    check("every mission lists achievements", not no_ach, str(no_ach))

    no_ref = [m.key for m in MISSIONS if not m.refs]
    check("every mission carries a reference", not no_ref, str(no_ref))

    chrono = [m.arrival for m in MISSIONS]
    check("catalogue is in chronological order",
          chrono == sorted(chrono),
          "out of order" if chrono != sorted(chrono) else "")

    print("\nCross-checks against known facts\n")

    a11 = by_key("apollo11")
    check("Apollo 11 at Statio Tranquillitatis",
          abs(a11.lat - 0.674) < 0.01 and abs(a11.lon - 23.473) < 0.01,
          f"{a11.lat}, {a11.lon}")

    c4 = by_key("change4")
    check("Chang'e 4 is on the farside (lon 90–270)",
          90 < c4.lon < 270, f"lon {c4.lon}")

    c3 = by_key("chandrayaan3")
    check("Chandrayaan-3 is the southernmost successful landing",
          c3.lat == min(m.lat for m in MISSIONS
                        if m.kind in ("landing", "rover", "crewed")
                        and m.outcome == "success"),
          f"{c3.lat}°")

    st = statistics()
    print()
    for k, v in st.items():
        print(f"    {k:<22} {v}")

    check("Apollo returned 380–383 kg in total",
          380 < sum(m.sample_mass_g for m in MISSIONS
                    if m.kind == "crewed") / 1000 < 383,
          f"{sum(m.sample_mass_g for m in MISSIONS if m.kind=='crewed')/1000:.1f} kg")
    check("12 people have walked on the Moon", st["people_landed"] == 12,
          str(st["people_landed"]))
    check("6 crewed landings", st["crewed_landings"] == 6)

    print("\nBy country\n")
    for c in countries():
        print(f"    {c['flag']}  {c['country']:<16} {c['count']:>2} missions, "
              f"{c['success']:>2} fully successful")

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
