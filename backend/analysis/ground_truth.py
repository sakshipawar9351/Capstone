r"""
Validating the hazard model against places humans and rovers actually went.

Everything else in this project is internally consistent: the slope operator
agrees with the mesh, the planners agree with each other, the layers agree with
the statistics. None of that is evidence the model describes the Moon. A model
can be perfectly self-consistent and still wrong about the ground.

There is one class of lunar terrain whose traversability is not in doubt.
Eleven missions have driven on the surface — three Apollo rovers, two
Lunokhods, Yutu, Yutu-2, Pragyan, and the crewed walking traverses of Apollo
11, 12 and 14 — and their coordinates are measured, not inferred. Whatever the
model says about that ground, reality has already answered.

Two things are measured here.

Falsifiability
--------------
A hazard model that calls driven ground impassable is wrong, and this says so
in those terms. It is the only test in the project that can be refuted by the
Moon rather than by another part of the codebase. It is deliberately blunt: no
tolerance, no "mostly". Apollo 17 drove 35.7 km across Taurus-Littrow; if the
model refuses the landing point, the model is broken.

What resolution costs
---------------------
The same sites are analysed at two postings and the slope statistics compared.
This is where the project's central claim comes from: at the ~500 m gridding
common in regional studies, terrain that contains slopes past a rover's
tip-over limit reports as uniformly gentle. Measured at Apollo 17, maximum
slope in a 5 km box is 3.01 deg at 473.8 m and 27.14 deg at 29.6 m — the coarse
grid does not soften that hazard, it removes it.

The p99 rather than the maximum is the number to quote. A single extreme cell
can be a gap-fill artifact or a bad return; the 99th percentile cannot.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.aoi import AOIUnavailable, plan_aoi
from ..data.missions import by_key as get_mission
from .hazard import HAZARD_CLASSES

__all__ = ["DRIVEN", "LANDED", "SiteResult", "analyse_site",
           "compare_resolutions", "understatement"]

#: Missions that moved across the surface under their own power, with the
#: distance each is documented to have covered. Their ground is drivable by
#: demonstration, which is what makes them a test rather than a comparison.
DRIVEN: tuple[str, ...] = (
    "apollo11", "apollo12", "apollo14",       # crewed, on foot
    "apollo15", "apollo16", "apollo17",       # crewed, Lunar Roving Vehicle
    "luna17", "luna21",                       # Lunokhod 1 and 2
    "change3", "change4", "chandrayaan3",     # Yutu, Yutu-2, Pragyan
)

#: Soft-landed successfully but did not travel. Weaker evidence — the ground
#: took a lander, which does not prove a rover could cross it — so these are
#: reported but never asserted on.
LANDED: tuple[str, ...] = (
    "luna9", "luna13", "surveyor1", "surveyor3", "surveyor5", "surveyor6",
    "surveyor7", "luna16", "luna20", "luna24", "change5", "change6",
    "slim", "blueghost1",
)

#: Half-width of the box analysed around each site, in degrees. 0.08 deg is
#: about 5 km at the equator — far enough at Apollo 17 to include the massifs
#: that flank the valley, which is the point.
DEFAULT_HALF_DEG = 0.08


@dataclass
class SiteResult:
    key: str
    name: str
    lat: float
    lon: float
    traverse_km: float | None
    cell_m: float
    product_id: str
    relief_m: float
    slope_mean: float
    slope_p99: float
    slope_max: float
    passable_fraction: float
    #: Hazard class at the landing coordinate itself.
    site_class: str
    site_passable: bool

    def to_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name,
            "coordinate": {"lat": self.lat, "lon": self.lon},
            "traverse_km": self.traverse_km,
            "cell_m": round(self.cell_m, 2), "product_id": self.product_id,
            "relief_m": round(self.relief_m, 1),
            "slope_deg": {"mean": round(self.slope_mean, 3),
                          "p99": round(self.slope_p99, 3),
                          "max": round(self.slope_max, 3)},
            "passable_fraction": round(self.passable_fraction, 5),
            "site_class": self.site_class,
            "site_passable": self.site_passable,
        }


def analyse_site(key: str, *, source: str | None = None,
                 half_deg: float = DEFAULT_HALF_DEG,
                 rover: str = "viper", soil: str = "nominal") -> SiteResult:
    """Run the hazard model over a box centred on a mission's coordinate.

    ``rover`` is held constant across sites on purpose. The Lunar Roving
    Vehicle, Lunokhod and Yutu have different limits, and using each vehicle's
    own would make the sites incomparable — the question here is what the
    *terrain* is, measured once and the same way everywhere.
    """
    from ..planning.service import analyse_aoi        # local: heavy import

    m = get_mission(key)
    if m is None or m.lat is None:
        raise ValueError(f"no coordinate for mission {key!r}")

    aoi = plan_aoi(m.lat - half_deg, m.lat + half_deg,
                   m.lon - half_deg, m.lon + half_deg, source=source)
    ana = analyse_aoi(aoi, rover=rover, soil=soil)
    t, w = ana.tmap, ana.window
    s = t.stats()

    rc = w.rowcol_of(m.lat, m.lon)
    if rc is None:
        raise ValueError(f"{key}: coordinate fell outside its own window")
    code = int(t.hazard[rc])
    cls = HAZARD_CLASSES[code]

    ws = w.stats()
    return SiteResult(
        key=key, name=m.name, lat=m.lat, lon=m.lon,
        traverse_km=m.traverse_km, cell_m=aoi.cell_m,
        product_id=aoi.source.product_id,
        relief_m=float(ws.get("relief_m", float("nan"))),
        slope_mean=s["slope_deg"]["mean"], slope_p99=s["slope_deg"]["p99"],
        slope_max=s["slope_deg"]["max"],
        passable_fraction=s["passable_fraction"],
        site_class=cls.label, site_passable=code < HAZARD_CLASSES[-1].code,
    )


def compare_resolutions(key: str, coarse: str | None = None,
                        fine: str = "ldem_1024", **kw
                        ) -> tuple[SiteResult, SiteResult]:
    """The same site at two postings. ``coarse=None`` takes the local default."""
    return analyse_site(key, source=coarse, **kw), analyse_site(key, source=fine, **kw)


def understatement(coarse: SiteResult, fine: SiteResult) -> dict:
    """By how much the coarse posting understates the terrain.

    Reported as ratios rather than differences so sites of different character
    can be compared: a factor of five is a factor of five whether the ground is
    gentle or savage.
    """
    def ratio(a, b):
        return float(b / a) if a > 1e-9 else float("inf")
    return {
        "cell_ratio": round(coarse.cell_m / fine.cell_m, 2),
        "slope_p99_ratio": round(ratio(coarse.slope_p99, fine.slope_p99), 2),
        "slope_max_ratio": round(ratio(coarse.slope_max, fine.slope_max), 2),
        "relief_ratio": round(ratio(coarse.relief_m, fine.relief_m), 2),
        "passability_lost": round(
            coarse.passable_fraction - fine.passable_fraction, 5),
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _main() -> int:
    npass = nfail = 0

    def check(name, ok, detail=""):
        nonlocal npass, nfail
        if ok:
            npass += 1
            print(f"  PASS  {name}" + (f"   {detail}" if detail else ""))
        else:
            nfail += 1
            print(f"  FAIL  {name}   {detail}")

    print("\nThe model must not refuse ground that was actually driven\n")

    results: list[SiteResult] = []
    for key in DRIVEN:
        try:
            r = analyse_site(key)
        except (AOIUnavailable, ValueError) as e:
            print(f"  SKIP  {key}: {e}")
            continue
        results.append(r)
        drove = f"drove {r.traverse_km:.2f} km" if r.traverse_km else "walked"
        check(f"{r.name} ({drove}) is passable at its own coordinate",
              r.site_passable,
              f"{r.site_class}, {r.passable_fraction*100:.1f}% of the box passable")

    check("every driven site was reachable by the model",
          all(r.site_passable for r in results),
          f"{len(results)} sites, {sum(r.site_passable for r in results)} passable")

    # The weaker statement for landers: reported, never asserted. Landing on
    # ground proves a lander could sit there, not that a rover could cross it.
    print("\nSites that soft-landed but did not travel (reported, not asserted)\n")
    landed_ok = 0
    landed_n = 0
    for key in LANDED:
        try:
            r = analyse_site(key)
        except (AOIUnavailable, ValueError):
            continue
        landed_n += 1
        landed_ok += r.site_passable
    print(f"  {landed_ok} of {landed_n} landing sites also come out passable")
    check("the landers are consistent with the driven sites",
          landed_n == 0 or landed_ok / landed_n > 0.8,
          "a lander site the model refuses is worth looking at, not a failure")

    print("\nWhat the coarse posting costs, where ground truth exists\n")
    print(f"  {'site':<22} {'coarse':>9} {'fine':>9} {'p99 x':>7} {'max x':>7}")
    print("  " + "-" * 60)
    ratios = []
    for key in ("apollo15", "apollo17"):
        try:
            c, f = compare_resolutions(key)
        except (AOIUnavailable, OSError) as e:
            print(f"  {key}: fine posting unavailable ({type(e).__name__})")
            continue
        u = understatement(c, f)
        ratios.append(u)
        print(f"  {c.name:<22} {c.slope_p99:>8.2f}° {f.slope_p99:>8.2f}° "
              f"{u['slope_p99_ratio']:>6.1f}x {u['slope_max_ratio']:>6.1f}x")

    if ratios:
        check("the coarse posting materially understates slope",
              all(u["slope_p99_ratio"] > 2.0 for u in ratios),
              "if this ever fails, the project's central claim has changed")

    print(f"\n{npass} passed, {nfail} failed")
    return 1 if nfail else 0


if __name__ == "__main__":
    raise SystemExit(_main())
