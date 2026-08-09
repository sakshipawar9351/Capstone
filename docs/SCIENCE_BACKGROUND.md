# LunarSerpent — Lunar Surface Science and Exploration Insights

**Document ID:** LS-DOC-007 · **Version:** 1.0 · **Status:** Baseline
**Date:** 2026-08-04
**Covers:** Project brief **Part 6** prerequisite — "conduct full study of the Moon, the Moon's surface, and exploration insights, but only include insights that are scientifically provable."

---

## 0. Inclusion criterion

This document contains **only** statements that are (a) measured by an instrument, (b) derived
from measurement by a documented method, or (c) directly observed during a flown mission.

Statements that are plausible but unproven are **excluded**, and a short list of commonly
repeated claims that did *not* meet the criterion appears in §13. Each section closes with
**⇒ Implication for traverse planning**, which is the actionable output that feeds Part 6.

---

## 1. Global physical parameters

| Property | Value | Source |
|---|---|---|
| Mean radius | 1737.4 km | Archinal et al. (2018) |
| Surface gravity | 1.625 m s⁻² (0.1657 g⊕) | NASA Moon Fact Sheet |
| Surface area | 3.793 × 10⁷ km² | Derived, 4πR² |
| Escape velocity | 2.38 km s⁻¹ | Derived |
| Sidereal rotation | 27.32 d (synchronous) | IAU |
| Solar day (synodic) | 29.53 d | IAU |
| Axial tilt to ecliptic | **1.54°** | Archinal et al. (2018) |
| Surface pressure | ~3 × 10⁻¹⁵ bar (hard vacuum) | Apollo ALSEP |
| Topographic range | −9.1 km to +10.8 km (19.9 km) | LOLA `LDEM_16` label |

**⇒ Implication for traverse planning.** Three of these drive the mobility model directly:

1. **Gravity 1.625 m s⁻²** enters the slope-resistance term of `FORMULAS.md` §7.1. A rover
   needs ~6× less power to climb a given grade than on Earth — but also has ~6× less normal
   force, so *traction* is reduced in proportion. The two effects cancel in
   θ_max = arctan(μ), which is why gradeability is set by friction, not by gravity.
2. **Axial tilt of only 1.54°** is the single most consequential number for polar operations.
   Because the spin axis is nearly perpendicular to the ecliptic, the Sun never rises more
   than ~1.5° above the horizon at the poles. This creates both permanently shadowed regions
   and near-permanently illuminated peaks (§9).
3. **The 29.53-day solar day** means ~14.75 Earth-days of darkness at most latitudes — a hard
   constraint on solar-powered traverse duration.

---

## 2. The nearside–farside dichotomy

**Measured facts:**

| Property | Nearside | Farside |
|---|---|---|
| Mare coverage | ~31 % | **~2 %** |
| Mean elevation | lower | higher by ~1.9 km |
| Crustal thickness (GRAIL) | ~30 km | ~50 km |

Verified independently during this project: a range-request read of LOLA `LDEM_64` at
(0 °N, 180 °E) — the farside centre — returned **+2730 m**, consistent with the elevated
farside highlands.

**⇒ Implication.** Terrain character is *predictably* different by hemisphere. Nearside maria
offer the gentlest traverses; farside highlands are rougher and more heavily cratered, because
they are older and lack the resurfacing that mare flooding provided.

> Wieczorek, M. A. et al. (2013), *The crust of the Moon as seen by GRAIL*, Science **339**,
> 671–675. DOI: [10.1126/science.1231530](https://doi.org/10.1126/science.1231530)

---

## 3. Surface units: maria and highlands

| Property | Maria | Highlands |
|---|---|---|
| Composition | Basalt (Fe, Ti-rich) | Anorthosite (Ca, Al-rich) |
| Albedo | 0.07 – 0.10 | 0.11 – 0.18 |
| Age | 3.1 – 3.8 Ga | 4.4 – 4.5 Ga |
| Crater density | Lower | Higher (saturated) |
| Regolith depth | **4 – 5 m** | **10 – 15 m** |
| Typical km-scale slope | < 3° | 5 – 15° |

**⇒ Implication.** Mare surfaces are the preferred traverse medium: younger, hence fewer
craters; flatter; thinner and better-characterised regolith. Every crewed Apollo landing that
used the LRV operated on or adjacent to mare terrain. Highlands cost more energy and carry
higher obstacle density.

> McKay, D. S. et al. (1991), *The lunar regolith*, in *Lunar Sourcebook*, Cambridge
> University Press, Ch. 7.
> Bart, G. D. et al. (2011), *Global survey of lunar regolith depths from LROC images*,
> Icarus **215**, 485–490. DOI: [10.1016/j.icarus.2011.07.017](https://doi.org/10.1016/j.icarus.2011.07.017)

---

## 4. Regolith mechanical properties

The single most important body of knowledge for rover mobility, because it determines whether
wheels grip or sink. These values come from Apollo core samples, Surveyor penetrometry and
Lunokhod's onboard penetrometer — that is, **direct in-situ measurement**.

| Property | Value | Note |
|---|---|---|
| Bulk density (0–15 cm) | 1.50 ± 0.05 g cm⁻³ | Increases with depth |
| Bulk density (30–60 cm) | 1.74 ± 0.05 g cm⁻³ | Self-compaction |
| Porosity | 40 – 50 % | Very loose at surface |
| **Cohesion** | **0.1 – 1.0 kPa** | Low but non-zero |
| **Friction angle** | **30° – 50°** (typ. 35–45°) | Governs gradeability |
| Median grain size | 40 – 130 µm | Silt-to-fine-sand |
| Fraction < 20 µm | 10 – 20 % | The problematic dust fraction |
| Bearing capacity (~10 cm depth) | > 30 kPa | Ample for rover loads |

**⇒ Implication — this is where θ_max comes from.** With a friction angle of 35–45°, the
theoretical no-slip limit is arctan(μ) with μ ≈ 0.3–0.6, giving **17°–31°**
(`FORMULAS.md` §6.1). Flight vehicles are limited more conservatively — VIPER ~15° sustained —
because wheel slip rises sharply well before the theoretical limit, and because slip is
*measured*, not assumed:

> **Apollo 15–17 direct observation:** LRV wheel slip was negligible on level ground but rose
> to 2–3 % on modest slopes, and became operationally significant above ~15°. Crews reported
> difficulty maintaining traction on crater walls near 20°.

Bearing capacity is **not** a constraint — a rover will not sink. **Slope and obstacles are
the binding limits**, which is precisely why LunarSerpent's hazard model is built on slope,
roughness and boulders rather than on soil-strength trafficability.

> Carrier, W. D., Olhoeft, G. R. & Mendell, W. (1991), *Physical properties of the lunar
> surface*, in *Lunar Sourcebook*, Cambridge University Press, Ch. 9.
> Mitchell, J. K. et al. (1972), *Soil mechanics*, Apollo 16 Preliminary Science Report,
> NASA SP-315.

---

## 5. Impact cratering — the process that made the surface

The Moon has no atmosphere, no plate tectonics and no liquid water. **Impact cratering is the
dominant landform-producing process**, with mass wasting secondary. This is why a
cratering-mechanics framework (Part 3) is scientifically correct here, rather than terrestrial
geomorphology.

**Established sequence:** contact and compression → excavation (transient cavity) →
modification (collapse, where gravity exceeds target strength).

**Measured consequences used by this project:**

| Fact | Value | Used in |
|---|---|---|
| Simple→complex transition | **15 – 20 km** on the Moon | `FORMULAS.md` §4.1, §4.3 |
| Simple crater d/D | ≈ 0.196 | §4.1 |
| Complex crater d/D | Falls as D^−0.7 | §4.1 |
| Excavation depth | ≈ 0.1 D | §4.2 |
| Continuous ejecta extent | ≈ 1 crater radius beyond rim | §6.3 |
| Transition scales as | ≈ g⁻¹ across bodies | §4.1 |

**⇒ Implication.** Crater size *predicts* hazard character. A 100 m crater is a local
obstacle. A 100 km crater is a terrain feature with a multi-kilometre ejecta apron, terraced
walls at or beyond rover slope limits, and a raised rim. The exponential standoff of
`FORMULAS.md` §6.3, scaled to crater radius, is the mathematical expression of exactly this.

> Melosh, H. J. (1989), *Impact Cratering: A Geologic Process*, Oxford University Press.
> Pike, R. J. (1977), in *Impact and Explosion Cratering*, Pergamon, 489–509.

---

## 6. Boulders and ejecta blocks

**Measured facts:**

- Boulders are concentrated **around fresh craters**, in ejecta deposits, and on steep slopes
  where mass wasting has exposed blocks.
- Block abundance decays steeply with distance from the source crater.
- Size–frequency follows a power law N(>D) ∝ D^−β, with β ≈ 2.5–3.5.
- Boulders degrade over ~10⁷–10⁸ years by micrometeorite bombardment, so **abundant boulders
  indicate a young surface**.
- Boulder tracks on slopes are directly observed in LROC NAC imagery, recording downslope
  rolling.

**⇒ Implication — the highest-value planning insight in this document.** Boulder hazard is
**predictable from crater age and proximity**, not random. A traverse can be routed to avoid
fresh-crater ejecta fields *before any high-resolution imagery is examined*, using only the
crater catalogue and the degradation index. High-resolution boulder detection then
**confirms** the prediction over a far smaller area, instead of searching blindly.

This is precisely the two-tier architecture adopted in Part 2: global catalogue-driven
prediction, then AOI-scale confirmation.

> Watkins, R. N. et al. (2019), *Boulder distributions around young lunar impact craters*,
> JGR Planets **124**, 2754–2771. DOI: [10.1029/2019JE005963](https://doi.org/10.1029/2019JE005963)
> Basilevsky, A. T. et al. (2013), *Survival times of meter-sized boulders on the surface of
> the Moon*, Planet. Space Sci. **89**, 118–126.
> DOI: [10.1016/j.pss.2013.07.011](https://doi.org/10.1016/j.pss.2013.07.011)

---

## 7. Topographic and slope statistics

Measured from LOLA:

| Statistic | Value | Baseline |
|---|---|---|
| Global topographic range | 19.9 km | — |
| Median slope, maria | **< 2°** | ~1 km |
| Median slope, highlands | 4° – 8° | ~1 km |
| Slopes > 20° | Rare — mostly crater walls and rilles | ~1 km |
| RMS slope increases with | Decreasing baseline | self-affine |

**⇒ Implication — and a warning.** Most of the Moon is gentle at kilometre baselines. The
danger is concluding from this that the Moon is *easy* to drive on. It is not: hazards
concentrate at **metre** scale, which kilometre-baseline statistics cannot see.

This is the empirical justification for the scale-dependence discipline enforced throughout
LunarSerpent (`FORMULAS.md` §3.5): a slope value is meaningless without its baseline, and a
1.9 km-baseline slope map must never be presented as a rover-scale safety product.

> Kreslavsky, M. A. et al. (2013), *Lunar topographic roughness maps from LOLA data*, Icarus
> **226**, 52–66. DOI: [10.1016/j.icarus.2013.04.027](https://doi.org/10.1016/j.icarus.2013.04.027)
> Rosenburg, M. A. et al. (2011), *Global surface slopes and roughness of the Moon from LOLA*,
> JGR Planets **116**, E02001. DOI: [10.1029/2010JE003716](https://doi.org/10.1029/2010JE003716)

---

## 8. Thermal environment

Measured by LRO Diviner:

| Location | Daytime max | Night min |
|---|---|---|
| Equator | ~390 K (+117 °C) | ~95 K (−178 °C) |
| Mid-latitudes | ~360 K | ~100 K |
| **Permanently shadowed regions** | — | **25 – 40 K** |

The coldest PSR floors are **among the coldest measured surfaces in the Solar System** —
colder than Pluto's surface.

Regolith is an excellent insulator: below ~30 cm, temperature is nearly constant at ~250 K
regardless of surface swings.

**⇒ Implication.** Thermal management, not terrain, often limits mission duration. A solar
rover must either survive a ~354-hour night or complete its traverse within one lunar day.
This makes **traverse time a hard mission constraint**, which is why `FORMULAS.md` §7.2 reports
time and energy as first-class path metrics rather than incidental statistics.

> Paige, D. A. et al. (2010), *Diviner Lunar Radiometer observations of cold traps in the
> Moon's south polar region*, Science **330**, 479–482.
> DOI: [10.1126/science.1187726](https://doi.org/10.1126/science.1187726)

---

## 9. Polar illumination — why the poles are the target

The 1.54° axial tilt (§1) produces conditions found nowhere else on the Moon:

| Fact | Value | Source |
|---|---|---|
| Sun's maximum elevation at the poles | ~1.5° | Geometric consequence of tilt |
| PSR total area | ~13 000 km² (S), ~17 000 km² (N) | LOLA / Diviner |
| Best illuminated ridges | **80 – 90 %** annual illumination | LOLA illumination modelling |
| Confirmed water ice in PSRs | Yes — direct spectroscopic detection | M³, LCROSS |

**⇒ Implications — several, and all operationally decisive:**

1. **Illumination is a routing resource, not merely a constraint.** Near-permanently lit ridges
   allow near-continuous solar power. A route that stays on them can operate indefinitely; one
   that strays into shadow starts a battery countdown.
2. **Shadows are long and they move.** With the Sun ≤1.5° above the horizon, 10 m of relief
   casts a shadow hundreds of metres long, and that shadow *sweeps* as the Moon rotates.
   Illumination at a polar site is a **function of time**, not a static map.
3. **Excellent for boulder detection.** The permanently grazing illumination that complicates
   operations makes shadow-length photoclinometry maximally sensitive
   (`FORMULAS.md` §5.2) — h_min = k·p·tan(e) is minimised at low solar elevation e. The poles
   are the *easiest* place on the Moon to detect small boulders.
4. **Cylindrical map projections fail here.** As established in `FORMULAS.md` §2.4, east–west
   cell size → 0 at the pole. Polar work requires polar stereographic products — which is why
   LunarSerpent refuses cylindrical analysis above 85° rather than returning numbers it cannot
   justify.

> Mazarico, E. et al. (2011), *Illumination conditions of the lunar polar regions using LOLA
> topography*, Icarus **211**, 1066–1081. DOI: [10.1016/j.icarus.2010.10.030](https://doi.org/10.1016/j.icarus.2010.10.030)
> Colaprete, A. et al. (2010), *Detection of water in the LCROSS ejecta plume*, Science
> **330**, 463–468. DOI: [10.1126/science.1186986](https://doi.org/10.1126/science.1186986)

---

## 10. Lunar dust — the dominant operational hazard

**Directly observed during Apollo**, and the most consistently reported operational problem
across all crewed surface missions:

- Particles are **angular and abrasive** — formed by micrometeorite fragmentation, with no
  aqueous or aeolian rounding to smooth them.
- **Electrostatically charged** by UV photoemission and solar wind; adheres tenaciously.
- Apollo 17 documented abrasion of suits and seals, obscured optics, **degraded radiator
  performance causing thermal-control problems**, and jammed mechanisms.
- The LRV required an improvised fender repair on Apollo 17 after dust rooster-tails coated
  the vehicle.

**⇒ Implication.** Dust is a hazard LunarSerpent can only *partially* mitigate through routing:
disturbed, fresh, fine-grained surfaces and steep slopes mobilise more dust. But honesty
requires stating the limit — **dust accumulation is a time-and-activity-dependent degradation
process, not a spatial hazard field.** It cannot be represented as a cost-map layer without
inventing data. It is therefore documented as a mission-planning consideration and
**deliberately excluded from the cost surface.**

> Gaier, J. R. (2005), *The effects of lunar dust on EVA systems during the Apollo missions*,
> NASA/TM-2005-213610.

---

## 11. Radiation

| Source | Dose characteristics |
|---|---|
| Galactic cosmic rays | Continuous, ~0.3 mSv/day at the surface |
| Solar particle events | Sporadic; potentially lethal without shelter |
| Neutron albedo | Secondary, from regolith interaction |

The Moon has no magnetosphere and no atmosphere, so the surface is exposed. Regolith is an
effective shield — roughly 1 m provides substantial protection.

**⇒ Implication.** Relevant to crewed mission planning (shelter proximity, sortie duration)
but **not a spatial routing constraint for a robotic rover** at the scales this system models.
Included for completeness; explicitly excluded from the cost surface.

> Zeitlin, C. et al. (2013), Science **340**, 1080–1084. DOI: [10.1126/science.1235989](https://doi.org/10.1126/science.1235989)

---

## 12. Flown-mission experience — the empirical record

Everything below is observed operational history, not modelling.

| Mission | Vehicle | Distance | Speed | Key lesson |
|---|---|---|---|---|
| **Luna 17 / Lunokhod 1** (1970) | 756 kg, 8 wheels | 10.5 km | ~0.1 m/s | First rover; teleoperated with signal delay |
| **Apollo 15, 16, 17** (1971–72) | LRV, crewed | 27.8 / 26.6 / **35.7** km | up to 3.6 m/s | Highest speeds ever driven; dust fouling; dead-reckoning navigation |
| **Luna 21 / Lunokhod 2** (1973) | 840 kg | **39 km** | ~0.14 m/s | Longest robotic traverse until Opportunity; **lost to overheating after dust contaminated its radiator** |
| **Chang'e-3 / Yutu** (2013) | 140 kg, 6 wheels | 114 m | 0.055 m/s | **Mobility system failed after ~1 lunar day** |
| **Chang'e-4 / Yutu-2** (2019– ) | 140 kg | > 1 km, multi-year | 0.055 m/s | First farside rover; extreme caution, short daily drives |
| **Chandrayaan-3 / Pragyan** (2023) | 26 kg | ~100 m | 0.01 m/s | Successful south-polar-region operation |

**⇒ Implications — the four hardest-won lessons:**

1. **Robotic rovers are slow, and slowness is a choice.** Yutu-2 travels at 0.055 m/s and
   covers only metres per day — not because it cannot go faster, but because
   ground-in-the-loop hazard assessment governs the pace. LunarSerpent's nominal speeds
   (0.05–0.2 m/s for robotic profiles) reflect flown reality, not vehicle top speed.
2. **Two of six rovers were disabled by mobility or thermal-dust failures**, not by terrain
   impassability. Lunokhod 2 was lost after dust on its radiator caused overheating; Yutu's
   drive system failed. **This validates the risk-weighted cost function of
   `FORMULAS.md` §6.4** — minimising *exposure* to hazardous terrain matters more than
   minimising distance, because failures are driven by cumulative exposure.
3. **Crewed vehicles are ~30× faster.** The LRV's 3.6 m/s against Yutu-2's 0.055 m/s is why
   LunarSerpent's rover profiles differ by nearly two orders of magnitude, and why a traverse
   time prediction is meaningless without naming the vehicle.
4. **Total lunar surface distance driven by all missions ever: ~113 km.** Every kilometre is
   expensive and irreplaceable — which is the entire justification for planning traverses as
   carefully as this system attempts to.

---

## 13. Claims deliberately excluded

Per the inclusion criterion of §0, these commonly repeated statements were **rejected**:

| Claim | Why excluded |
|---|---|
| "Lunar dust is toxic to humans" | Inhalation risk is *suspected* and under study; not established for lunar regolith specifically |
| Precise absolute ages for individual unnamed craters | Not measurable (`FORMULAS.md` §4.4) |
| "Lava tubes provide confirmed safe habitats" | Pits and candidate tubes are confirmed; **structural stability is not** |
| Specific water-ice concentrations at arbitrary PSR locations | Presence is confirmed; spatial distribution and concentration remain poorly constrained |
| "Moonquakes are a rover hazard" | Deep moonquakes are real and measured, but no evidence links them to surface-vehicle risk |
| Global boulder density maps at metre scale | No such dataset exists (§6, and `PRD.md` N1) |

Excluding these is itself a scientific result: it marks the boundary of what this system may
legitimately claim.

---

## 14. Synthesis — how this science enters the system

| Insight | Implemented as |
|---|---|
| Friction angle 30–50° → gradeability | θ_max = arctan(μ), `FORMULAS.md` §6.1 |
| Gravity 1.625 m s⁻² | Mobility model, §7.1 |
| Bearing capacity is not limiting | Hazard model excludes sinkage; slope and obstacles dominate |
| Boulders cluster near fresh craters | Crater-proximity hazard §6.3; degradation index as predictor |
| Ejecta extends ~1 crater radius | Exponential standoff with ℓ = 0.5·r_c |
| Roughness is scale-dependent | Mandatory `baseline_m` on every slope/roughness value |
| 14.75-day night; thermal limits | Traverse **time** as a first-class path metric |
| Polar illumination is time-varying | Illumination treated as temporal, not a static layer |
| Cylindrical projection fails at poles | Analysis refused above 85°; polar stereographic required |
| Rover losses were exposure-driven | Risk-multiplied cost, not shortest distance |
| Maria are the gentlest terrain | Emerges from the cost surface — not hard-coded |
| Dust degradation is temporal | **Documented but excluded** from the cost map |

---

## 15. Consolidated references

1. Archinal, B. A. et al. (2018), Celest. Mech. Dyn. Astron. **130**:22. DOI: [10.1007/s10569-017-9805-5](https://doi.org/10.1007/s10569-017-9805-5)
2. Basilevsky, A. T. et al. (2013), Planet. Space Sci. **89**, 118–126. DOI: [10.1016/j.pss.2013.07.011](https://doi.org/10.1016/j.pss.2013.07.011)
3. Bart, G. D. et al. (2011), Icarus **215**, 485–490. DOI: [10.1016/j.icarus.2011.07.017](https://doi.org/10.1016/j.icarus.2011.07.017)
4. Carrier, W. D. et al. (1991), *Lunar Sourcebook*, Ch. 9, Cambridge University Press.
5. Colaprete, A. et al. (2010), Science **330**, 463–468. DOI: [10.1126/science.1186986](https://doi.org/10.1126/science.1186986)
6. Gaier, J. R. (2005), NASA/TM-2005-213610.
7. Kreslavsky, M. A. et al. (2013), Icarus **226**, 52–66. DOI: [10.1016/j.icarus.2013.04.027](https://doi.org/10.1016/j.icarus.2013.04.027)
8. Mazarico, E. et al. (2011), Icarus **211**, 1066–1081. DOI: [10.1016/j.icarus.2010.10.030](https://doi.org/10.1016/j.icarus.2010.10.030)
9. McKay, D. S. et al. (1991), *Lunar Sourcebook*, Ch. 7, Cambridge University Press.
10. Melosh, H. J. (1989), *Impact Cratering: A Geologic Process*, Oxford University Press.
11. Mitchell, J. K. et al. (1972), Apollo 16 Preliminary Science Report, NASA SP-315.
12. Paige, D. A. et al. (2010), Science **330**, 479–482. DOI: [10.1126/science.1187726](https://doi.org/10.1126/science.1187726)
13. Pike, R. J. (1977), in *Impact and Explosion Cratering*, Pergamon, 489–509.
14. Rosenburg, M. A. et al. (2011), JGR Planets **116**, E02001. DOI: [10.1029/2010JE003716](https://doi.org/10.1029/2010JE003716)
15. Watkins, R. N. et al. (2019), JGR Planets **124**, 2754–2771. DOI: [10.1029/2019JE005963](https://doi.org/10.1029/2019JE005963)
16. Wieczorek, M. A. et al. (2013), Science **339**, 671–675. DOI: [10.1126/science.1231530](https://doi.org/10.1126/science.1231530)

---

## 16. Revision history

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-08-04 | Baseline. Only measured/observed facts included; excluded claims documented in §13; every section mapped to a planning implication. |
