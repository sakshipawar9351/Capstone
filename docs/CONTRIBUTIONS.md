# LunarSerpent — Provenance and Contributions

**Document ID:** LS-DOC-009 · **Version:** 1.0 · **Status:** Baseline
**Date:** 2026-08-09

---

## 1. Why this document exists

A scientific system is built almost entirely from other people's work. That is
correct practice, not a weakness: a terramechanics model that invented its own
pressure–sinkage law would be wrong, not original. But it makes one question
unavoidable — **what, precisely, is new here?**

This document answers it explicitly, method by method, so the boundary between
inherited and original is drawn deliberately rather than reconstructed
afterwards. It exists to be checked.

Every method in the system falls into one of three categories:

| Mark | Meaning |
|:--:|---|
| **I** | **Inherited** — used as published, cited at the point of use. No claim of novelty. |
| **A** | **Adapted** — published method, modified for lunar or polar conditions, or for a constraint of this system. The modification is stated. |
| **O** | **Original** — developed here. The reasoning is given so it can be disputed. |

The codebase currently carries **53 distinct citations, 23 DOIs and 20 typeset
formulas across 7 modules.** The overwhelming majority is inherited. That
proportion is expected and healthy.

Section 3 states **ten original findings**, each with the command that
reproduces it. Where a finding was reached by first getting something wrong,
that is recorded too — a result whose failure mode is documented is easier to
trust than one that arrived clean.

---

## 2. Method inventory

### 2.1 Coordinates and geodesy — `core/selenographic.py`, `core/polar.py`

| Method | | Source / note |
|---|:--:|---|
| Reference frame: IAU Mean Earth / Polar Axis, DE421, R = 1737.4 km | **I** | Archinal et al. (2018), doi:10.1007/s10569-017-9805-5 |
| Simple-cylindrical pixel ↔ lat/lon | **I** | PDS3 map-projection standard; parameters read from each product's own label |
| Haversine great-circle distance | **I** | Standard formulation |
| *Observation:* on an equal-axis sphere the great circle **is** the exact geodesic, so no ellipsoidal iteration is needed | **O** | Follows from `A = B = C = 1737.4 km` in the LOLA label. Trivial once noticed, and it removes a whole class of approximation error other systems carry. |
| Polar stereographic forward/inverse | **I** | Snyder (1987), USGS Prof. Paper 1395 §21 |
| Stereographic point-scale factor sec²(c/2) | **I** | Snyder (1987) |
| Verifying projection parameters by inverting the grid edge and comparing to the label's declared `MAXIMUM_LATITUDE` | **O** | A self-check that the implemented projection is the one that produced the grid. Recovered −87.4994° against a declared −87.5°. |

### 2.2 Terrain derivatives — `analysis/terrain.py`

| Method | | Source / note |
|---|:--:|---|
| Slope and aspect, 3×3 third-order finite difference | **I** | Horn (1981), doi:10.1109/PROC.1981.11918 |
| Profile and plan curvature | **I** | Zevenbergen & Thorne (1987), doi:10.1002/esp.3290120107 |
| Terrain Ruggedness Index | **I** | Riley, DeGloria & Elliot (1999) |
| Per-row `dx = 2πR cos(φ)/W` applied inside the slope operator | **A** | Horn assumes a uniform grid. On a simple-cylindrical planetary grid the east–west cell shrinks as cos(φ), and applying a constant `dx` inflates east–west gradients by 2× at 60° latitude. |
| **Detrended roughness**: RMS residual about the best-fit plane, in closed form | **A** | Plane-fit residual is the standard geomorphological definition; the contribution is the closed-form σ²ᵣ = var − (a²+b²)⟨x²⟩ evaluated by separable filters (O(n) in window size), **and the demonstration that the naive form is wrong here** — see §3.1. |

### 2.3 Crater morphometry — `analysis/morphometry.py`

| Method | | Source / note |
|---|:--:|---|
| Depth–diameter scaling, simple and complex regimes | **I** | Pike (1974) doi:10.1029/GL001i007p00291; Pike (1977) |
| Rim-height scaling | **I** | Pike (1977) |
| Simple→complex transition at D ≈ 15 km | **I** | Pike (1977); Melosh (1989) |
| Radial elevation profiling rather than window min/max | **A** | The approach used for LOLA-derived catalogues (Head et al. 2010; Wang et al. 2021). Specific choices here — rim as the highest ring-mean within 0.70–1.25 R, floor as the 10th percentile inside 0.35 R, datum as the median of the 1.2–1.5 R annulus — are ours, chosen so the datum sits outside the continuous ejecta blanket. |
| **Resolution-adequacy verdict** (`good` ≥ 30 cells, `marginal` ≥ 10, else refuse) | **O** | §3.8 |
| **Depth-ratio interpretation bands** (fresh / degraded / infilled) | **O** | Thresholds on measured ÷ Pike-predicted depth, with the ±30 % scatter of Pike's own fit as the "fresh" band. |

### 2.4 Terramechanics — `analysis/terramechanics.py`

| Method | | Source / note |
|---|:--:|---|
| Pressure–sinkage `p = (k_c/b + k_φ)zⁿ` | **I** | Bekker (1969) |
| Mohr–Coulomb shear strength | **I** | Classical soil mechanics |
| Shear-displacement law `τ(j) = τ_max(1 − e^(−j/K))` | **I** | Janosi & Hanamoto (1961) |
| Drawbar-pull integral over the contact patch | **I** | Wong & Reece (1967), J. Terramechanics 4(1), 81–98 |
| Compaction (motion) resistance | **I** | Bekker (1969) |
| Regolith parameters c = 520 Pa, φ = 42°, K = 1.8 cm | **I** | Carrier, Olhoeft & Mendell (1991), *Lunar Sourcebook* ch. 9 |
| Slip regime bands (20 % / 40 % / 60 %) | **I** | MER and MSL flight-operations practice, not a soil property — labelled as such in code |
| Iterative sinkage solution (pressure → sinkage → contact area → pressure) | **A** | Bekker's relation is implicit once contact geometry depends on sinkage. Three fixed-point passes converge well inside the spread of the soil parameters themselves. |
| **Conservative soil selection** — weak case uses φ = 25° from the Chang'e-4 range 21.5–42° | **O** | §3.2 |
| **`max_slope_by_slip`: traction gradeability distinct from geometric, and which one binds** | **O** | §3.2 |
| **Slip tabulated over slope and interpolated** (`SlipTable`) | **A** | The force balance is Bekker/Janosi–Hanamoto; the contribution is noting that slip depends only on slope once rover, soil and wheel count are fixed, so a 0.1° table is exact to the sampling and turns a per-cell bisection into an O(1) lookup — 640 000 cells in 24 ms. |

### 2.5 Traversability — `analysis/hazard.py`

| Method | | Source / note |
|---|:--:|---|
| Power-limited speed `v = P / [mg(sinθ + μcosθ)]` | **I** | Elementary mechanics |
| Slope limits for wheeled planetary vehicles | **I** | Wilcox et al. (2007), J. Field Robotics 24, 421–434 |
| **Hazard / risk / cost as three separate quantities** | **O** | §3.3 |
| **Risk as `1 − (1 − r_grade)(1 − r_rough)`** | **A** | Standard probability of at least one of two independent events; the contribution is treating grade and roughness as *independent failure modes* rather than averaging them, and squaring the stability term because consequence grows faster than angle. |
| **`r_grade = max(r_stability, r_traction)`** — two reductions, deliberately different | **O** | Slip is a function of slope, so combining a slip term with a slope term probabilistically would count the same gradient twice — the error corrected in §3.1 and §3.3. Correlated terms are reduced by `max` (the binding constraint governs); only genuinely independent terms are multiplied. |
| **Traction risk measured from the 20 % routine-slip threshold, not from zero** | **O** | About 1 % slip occurs on flat ground from motion resistance alone; measuring from zero would score level terrain as hazardous. |
| **Hazard = worse of geometric and traction verdicts, with the binding one reported** | **O** | §3.2. A traction limit can be relaxed by choosing firmer ground; a stability limit cannot. An operator needs to know which they face. |
| Hazard classes as fractions of a specific vehicle's limits | **O** | Lets one scheme serve a 26 kg Pragyan and a 700 kg LRV without rewriting thresholds. |
| **Cost `C = (d/v)(1 + γR)` with exposed risk-aversion γ** | **O** | γ is a mission decision, not a physical constant, so it is a parameter rather than a tuned value. |

### 2.6 Path planning — `planning/planners.py`

| Method | | Source / note |
|---|:--:|---|
| Breadth-first search | **I** | Standard |
| Dijkstra | **I** | Dijkstra (1959) |
| A\* | **I** | Hart, Nilsson & Raphael (1968) |
| Weighted A\* | **I** | Pohl (1970) |
| Theta\* | **I** | Daniel et al. (2010), JAIR 39, 533–579 |
| D\* Lite | **I** | Koenig & Likhachev (2005) |
| RRT\* | **I** | Karaman & Frazzoli (2011) |
| Corner-cutting prohibition on diagonals | **I** | Standard grid-planning practice |
| Symmetric edge cost — mean of the two cell costs × step length | **A** | Makes `c(a,b) = c(b,a)`, which Dijkstra and A\* both assume and which keeps a route's cost independent of travel direction. Destination-cost-only, the common shortcut, breaks both. |
| Admissible heuristic `h = ‖n − goal‖ · min(C)` | **A** | Standard construction; the contribution is the explicit statement that this bound is *loose by design* and the measurement of what that costs — §3.4. |
| Lazy-deletion priority queue in D\* Lite | **A** | `UpdateVertex` must remove an arbitrary node, which a binary heap cannot do; scanning for it costs O(n) per call, eight times per expansion. Recording each node's current key and discarding non-matching entries on pop is the standard remedy — it cut a 500×500 plan from 368 s to 42 s with an identical result. |
| **Finding: A\*'s advantage is terrain-dependent, not a constant** | **O** | §3.4 |
| **Finding: any-angle planning pays on coherent terrain, costs on noise** | **O** | §3.5, five sites |
| **Finding: Weighted A* saturates — past e ~ 2.5 the dial does nothing** | **O** | §3.6 |
| **Finding: RRT*'s spread is widest on the easiest terrain** | **O** | §3.7, 150 seeded runs |
| **Any-angle path costs integrated along the chord, not across its endpoints** | **O** | §3.5, accounting note. Endpoint averaging under-prices exactly the shortcuts an any-angle planner exists to take. |
| Shortcut smoothing as a post-process | **A** | Shortcutting a grid path is standard practice. The contribution is the acceptance test: a chord is taken only where its *integrated* cost is lower, not merely where it is passable. Every accepted step strictly lowers the total, so the search's optimality bound survives — which the usual length-only test does not preserve on a weighted surface. Measured: 471 → 25 waypoints for −0.55 % cost in 222 ms. |

### 2.7 Path evaluation — `planning/metrics.py`

| Method | | Source / note |
|---|:--:|---|
| Three-dimensional path length | **I** | Trivial geometry, stated because map distance understates both time and energy |
| Energy `E = mgh + μmgd` | **I** | Elementary mechanics; descent uncredited since a rover cannot regenerate |
| **Safety score `S = 100(1 − r_max)(1 − f_hazard)`** | **O** | §3.3 |
| **Worst-cell dominance** — peak risk governs, mean reported but excluded | **O** | §3.3 |
| **Named limiting factor** | **O** | A score without a cause tells an operator nothing about what to change. |
| Recommended speed = route minimum, not mean | **O** | Commanding the mean exceeds the limit at the hardest point. |

---

## 3. Original contributions, in full

These are the claims this work would defend. Each is reproducible from the
repository.

### 3.1 Undetrended roughness restates slope

Local elevation standard deviation is widely used as a roughness proxy. On
sloping ground it is not one: a perfectly smooth plane has large elevation
variance purely because it is tilted.

**Measured on a constant 9.5° ramp: undetrended 1.361 m, detrended 0.000 m.**

The consequence is not cosmetic. Any hazard model combining "roughness" with
slope then counts the same gradient twice. In this system that error scored a
gentle, entirely safe ramp at 21.6/100 against the 92.7/100 it now receives —
a factor of four, on terrain a rover can drive without difficulty.

*Reproduce:* `python -m backend.analysis.terrain` for the 1.361 m / 0.000 m
pair. The 21.6 figure is a development measurement: the defective code has been
removed, so only the corrected score re-runs (`python tests/test_planners.py`).

### 3.2 Which constraint binds — traction or geometry — depends on the soil

Rover slope limits are conventionally quoted as geometric: a tip-over angle or
a sustained-gradeability figure. Solving the Bekker–Janosi–Hanamoto system for
the slip at which a vehicle can no longer generate the required drawbar pull
gives a second, independent limit. Which of the two binds is not fixed — it
depends on the regolith.

| Rover | Tip-over (geometric) | Traction, nominal soil | Traction, weak soil | Binds on nominal | Binds on weak |
|---|---|---|---|---|---|
| Pragyan-class | 30.0° | 30.9° | 16.1° | stability | **traction** |
| Yutu-2-class | 33.0° | 39.7° | 18.4° | stability | **traction** |
| VIPER-class | 35.0° | 46.5° | 21.1° | stability | **traction** |
| Apollo LRV-class | 45.0° | 50.8° | 23.5° | stability | **traction** |

On Apollo-nominal regolith (c = 520 Pa, φ = 42°) traction gradeability exceeds
every vehicle's tip-over angle, so the conventional geometric limit is the
correct one and nothing is gained by modelling slip.

On the low-friction Chang'e-4 bound (c = 250 Pa, φ = 25°) that reverses for
every vehicle tested. **The geometric limit then over-certifies by 1.66× to
1.91×** — it approves slopes at which the wheels turn without advancing. This
is the failure mode that immobilised *Spirit*: not a grade beyond capability,
but soil that could not supply the thrust.

The contribution is not "slip matters" but the sign and size of the effect, and
that the answer is soil-dependent rather than a property of the vehicle. A
system quoting one gradeability number for a rover is quoting an answer to an
under-specified question.

**On real terrain.** At Connecting Ridge (89.45° S, 222° E — an Artemis III
candidate region), over a 5 km square of 10 m LOLA polar data:

| | Nominal soil | Weak soil |
|---|---|---|
| Passable area | 99.9 % | 90.9 % |
| Cells where traction binds | 0.0 % | **9.1 %** |
| Optimal route length | 6.18 km | 7.60 km |
| Traverse time | 10.3 h | 13.6 h |
| Peak slope on route | 27.0° | 20.6° |
| Cell overlap between the two routes | — | **2.3 %** |

The soil model does not merely re-price the same route: at 2.3 % shared cells
the two traverses are essentially different paths. A planner given only slope
would have returned the 6.18 km route in both cases and certified 9 % of the
map that the weak-soil vehicle cannot cross.

*Reproduce:* `python -m backend.analysis.terramechanics`,
`python tests/test_traverse_polar.py`

**Re-measured 2026-08-11.** These figures moved slightly — traction-bound
cells 9.0 → 9.1 %, the weak-soil route 7.68 → 7.60 km — after a boundary
defect was fixed in the slope operator (§3.11a). The conclusion is unchanged and
the shift is smaller than the spread of the soil parameters themselves, but a
published number that has changed is worth saying so about.

**A note on how this was found.** The first implementation bisected for the
traction limit over `[0°, 45°]` and returned 45.0° for VIPER, LRV and every
other rover whose limit lay above the bound — a search ceiling presented as a
measurement. It survived because 45° is a plausible-looking number. The tell
was two different vehicles reporting it identically. The suite now asserts that
four rovers produce four distinct limits, which fails immediately if the bound
is ever reintroduced.

### 3.3 Hazard, risk and cost must be three quantities

Collapsing traversability into one number leaves a planner unable to
distinguish *illegal* from *merely unpleasant*. This system keeps:

- **hazard** — a hard constraint; impassable cells carry infinite cost and are
  excluded structurally, so no planner can be tuned into crossing one;
- **risk** — a soft preference between legal routes, combined as independent
  failure modes rather than averaged;
- **cost** — the objective actually minimised.

Safety scoring follows the same discipline: **the peak cell governs, the mean
is reported but excluded.** A route that is gentle for 5 km and crosses one
scarp is not safe, and averaging conceals precisely the cell that stops the
vehicle. Terms multiply rather than sum, so each can veto the score alone —
which is how a physical limit behaves.

A first implementation multiplied by a slope-margin term *and* by risk, which
already contains a slope component. Removing that double-count moved the same
gentle ramp from 67.6 to its present 92.7 (development measurement; the
current score is verified by `tests/test_planners.py`).

The same ramp therefore read 21.6, then 67.6, then 92.7 as two independent
double-counts were removed — from the roughness definition (§3.1) and from the
score itself. Neither bug was visible as an error; each simply produced a
pessimistic number that looked reasonable. That is the argument for stating
what each term means before combining terms.

### 3.4 A\*'s efficiency advantage does not survive strongly-weighted terrain

An admissible heuristic must assume the cheapest cost found anywhere on the
map. Where cell costs span a wide range — as they do on any real hazard
surface, because risk *multiplies* cost — that bound becomes loose and guides
the search poorly.

| Terrain | Cost spread | Dijkstra | A\* | Saving |
|---|---|---|---|---|
| Uniform cost | 1× | 880 | 26 | **97 %** |
| Random weighted | 12× | 1 508 | 1 496 | **1 %** |
| Crater field (Tycho highlands) | 2.1× | 987 | 381 | **61 %** |
| Open mare (Serenitatis) | 2.9× | 1 272 | 769 | **40 %** |
| Highland, sustained slope | 2.7× | 1 375 | 772 | **44 %** |
| Connecting Ridge, 10 m LOLA | 7.8× | 58 132 | 43 150 | **26 %** |
| Crater-rim crossing | 5.8× | 959 | 838 | **13 %** |

Five real sites now, not one. The saving ranges from **61 % to 13 %** and never
approaches the 97 % of a uniform grid.

The saving is not a simple function of spread — the random grid has the *wider*
spread and the *smaller* saving, and among the real sites the rim crossing
(5.8×) saves less than the polar ridge (7.8×). Two things matter, and only one
is usually discussed:

- **spread**, which sets how loose the admissible bound is; and
- **spatial coherence**, which sets whether cheap cells form usable corridors.
  Real terrain has coherent low-cost ground following ridges and crater floors,
  so the heuristic still points somewhere useful. Uncorrelated noise has cheap
  cells scattered everywhere and nowhere, and the heuristic degenerates.

The familiar claim that A\* greatly outperforms Dijkstra derives from uniform
or lightly-weighted grids. On real planetary hazard terrain the advantage is
real but roughly a third of the textbook figure, and on synthetic random
weights it nearly vanishes. Benchmarks on random grids are therefore not a
guide to planetary performance in either direction.

*Reproduce:* `python tests/test_planners.py`,
`python tests/test_traverse_polar.py`

### 3.5 Any-angle planning pays on real terrain and costs on synthetic terrain

Theta\* is not confined to 45° headings, so it searches a strictly larger set of
routes than a grid planner and its cost is not bounded below by the grid
optimum. Whether it actually wins turns out to depend on how the terrain is
structured, and the two cases point opposite ways:

| Terrain | Theta\* vs grid optimum | Cost spread |
|---|---|---|
| Random weighted grid | **+8.6 %** (worse) | 12× |
| Crater field (Tycho highlands) | **−3.7 %** | 2.1× |
| Open mare (Serenitatis) | **−2.0 %** | 2.9× |
| Crater-rim crossing | **−1.8 %** | 5.8× |
| Connecting Ridge, 10 m LOLA | **−2.3 %** | 7.8× |
| Highland, sustained slope | **0.0 %** (tie) | 2.7× |

Across five real sites Theta\* is at or below the grid optimum every time,
between 0 and 3.7 % cheaper. Only the synthetic random grid puts it *above*.
That is one measurement repeated, not a coincidence.

A straight chord across coherent terrain — a ridge crest, a crater floor —
tends to stay on ground of the same character, so the shortcut is real. A chord
across uncorrelated noise samples the cost distribution afresh and reverts to
the mean, losing the grid path's ability to thread between expensive cells.

The practical consequence is the 471 → 52 waypoint reduction at no cost
penalty. A route a rover must actually execute as a sequence of commanded
headings is nine times cheaper to represent, and each waypoint is a place the
vehicle stops turning and starts driving.

*Reproduce:* `python tests/test_traverse_polar.py`

**Accounting note.** This comparison is only meaningful if both routes are
priced on the same terrain. Summing edge costs between consecutive waypoints —
correct for a grid path, where they are adjacent — silently under-prices an
any-angle path, because a chord spanning 200 cells averaged from its two
endpoints ignores 198 of them. Segment costs are therefore integrated cell by
cell along the chord. Without that correction Theta\* appeared to beat the grid
optimum partly by not being charged for the ground it crossed.

### 3.6 Bounded-suboptimal search buys three orders of magnitude for a few per cent

Weighted A\* multiplies its heuristic by ε, trading a guaranteed optimality
bound of ε for speed. The bound is usually quoted; the *curve* rarely is. On the
Connecting Ridge cost surface:

| ε | Cost vs optimal | Expansions | Fewer expansions |
|---|---|---|---|
| 1.00 | 1.0000× | 43 150 | 1× |
| 1.25 | 1.0067× | 31 685 | 1.4× |
| 1.50 | 1.0190× | 9 374 | **4.6×** |
| 2.00 | 1.0391× | 464 | **93×** |
| 2.50 | 1.0589× | 186 | **232×** |
| 4.00 | 1.0593× | 186 | 232× |
| 8.00 | 1.0593× | 186 | 232× |

Three things fall out that a single ε could not show.

**The trade is wildly asymmetric.** At ε = 2.0 the route costs **3.9 % more for
93× fewer expansions**. For a planner a human is waiting on, that is not a close
call.

**It saturates.** Past ε ≈ 2.5 the search stops changing: identical cost and
identical 186 expansions at ε = 2.5, 4 and 8. The heuristic is already dominant
enough to drive straight at the goal, and raising ε further buys nothing. Any
implementation offering ε as a free dial is offering a range that mostly does
not exist.

**Report expansions, not wall-clock.** Two runs of this sweep on the same
machine gave *identical* cost ratios and *identical* expansion counts, while
the wall-clock speed-up at ε = 2.5 came out 456× once and 232× the other — a
factor of two, from nothing but machine load. The earlier version of this table
quoted the timing figures. Expansions are a property of the search; seconds are
a property of the afternoon.

The realised suboptimality is also far inside the guarantee — 5.9 % actual
against a permitted 150 % at ε = 2.5. The bound is worst-case and, on this
terrain, enormously pessimistic.

### 3.7 A stochastic planner's spread is the argument against it

RRT\* was rejected in `ALGORITHMS.md` §4.2 on determinism grounds — a mission
tool must give the same answer twice. That was an argument, not a measurement.
Thirty seeded runs on each of five sites make it one:

| Site | Mean cost | Best | Worst | σ | Found |
|---|---|---|---|---|---|
| Open mare | 1.081× | 0.965× | **1.320×** | 0.108 | 30/30 |
| Crater field | 1.008× | 0.962× | 1.177× | 0.049 | 30/30 |
| Highland | 1.036× | 0.998× | 1.213× | 0.052 | 30/30 |
| Rim crossing | 1.023× | 0.968× | 1.232× | 0.065 | 30/30 |
| Polar site, 10 m | 1.049× | 1.001× | 1.123× | 0.034 | 30/30 |

**Completeness is not the problem** — it found a route 150 times out of 150.
The problem is that *which* route depends on the seed. On the open mare the
same request returns anything from 3.5 % better than the grid optimum to **32 %
worse**, and nothing in the output distinguishes the good run from the bad one.

The variance is also largest where the terrain is *easiest* (open mare, σ =
0.108) and smallest on the hardest site (polar, σ = 0.034). Gentle ground gives
the sampler many nearly-equivalent routes and no gradient to prefer between
them; constrained ground funnels every sample toward the same corridor. So the
one regime where a planner could most afford to be sloppy is the one where a
sampling method is least repeatable.

Quoting a single run — as this project did before these thirty — would have
reported any number between 0.965 and 1.320 as *the* result.

### 3.8 Resolution–hazard mismatch, quantified

Rover-scale hazards are sub-pixel in every globally available product.

| Hazard | Size | At 474 m/px | At 10 m/px |
|---|---|---|---|
| Chassis-stopping boulder | 0.25 m | 0.00053 px | 0.025 px |
| Wheel step limit | 0.25 m | 0.00053 px | 0.025 px |
| Rover footprint | 2 m | 0.0042 px | 0.2 px |
| Traverse decision | 10 m | 0.021 px | 1.0 px |

The system therefore refuses analysis below its resolution floor rather than
returning a plausible number — a 0.4 km crater is declined with *"spans only
0.8 cells at 474 m/px"*.

### 3.9 Simple-cylindrical grids are degenerate at the poles

East–west cell width scales with cos(φ) and collapses as meridians converge.
Slope is rise ÷ run, so a vanishing run inflates gradient without bound.

**At 89.65° S the LDEM_64 east–west cell is 2.8 m against 474 m at the
equator, and the slope operator returns 89.6° on ground the 10 m polar
stereographic product measures at 73.3°.**

Polar slope computed on an equirectangular grid is an artefact of the
projection. This is why the LOLA team publishes separate polar products, and
why this system uses a distinct reader for them rather than a special case.

*Reproduce:* `python tests/test_hazard_real.py`

### 3.10 Shadow-based boulder metrology fails at the poles in principle

Boulder height from shadow length, `h = L·tan(90° − i)`, is standard. At polar
incidence angles it becomes unusable — not through poor data, but because the
sun never rises far enough.

The two NAC scenes held here are both near-grazing — M101980409LC at
i = 89.79° (sun 0.21° up) and M1410768185LC at i = 89.67° (sun 0.33° up), at
0.51 m/px:

- a 1 m boulder casts a **273 m** shadow in the first scene and **174 m** in
  the second, overlapping every other shadow in the frame, so a dark patch
  cannot be attributed to a single rock;
- ±2 px of shadow-length error → **0.4 cm** of height error — negligible, which
  is the surprise: the measurement one would expect to dominate does not;
- **±0.1° of incidence error → 0.48 m of height error, 48 % of a 1 m boulder.**

The entire error budget sits in the illumination geometry, not in the image.
Sharper pixels cannot fix this; only a higher sun can.

Boulder *width*, measured from the sunlit face, carries no such sensitivity.
Height by shadow requires 50–80° incidence, which does not occur at the poles.

---

### 3.11 Defects found by testing claims rather than code

Every finding above was reached by measurement, which means a defect in the
measuring apparatus is a defect in the finding. Two were found this way and are
recorded because the numbers in §3 moved when they were fixed.

**3.11a — slope was halved around every window edge.**

A 3×3 finite-difference operator at the boundary of an array has no neighbour
outside it. With `mode="nearest"` the edge row is duplicated, the difference
across it is taken over half the true distance, and the reported gradient is
**half the real one**.

Measured on a constant 5.7106° ramp: interior **5.7106°**, first and last
column **2.8624°**. On real polar terrain the border read **0.90× the interior
mean**, across 1.62 % of cells.

The fix is to read one cell of margin, differentiate, then trim — so every cell
in the region of interest is computed with neighbours on all four sides. The
margin now lives inside `analyse_traversability` rather than in its callers,
because two of the three callers had forgotten it, and those two were the ones
producing published numbers.

*Reproduce:* `python tests/test_plan_service.py` — asserts a haloed ramp is
uniform to its edge, **and** that the untrimmed version would be wrong.

**3.11b — the projection-distortion guard inverted past the antipode.**

Azimuthal equidistant stretches tangentially as `c / sin(c)`. Past the antipode
(`c > π`) that expression turns **negative**, so a guard using it to reject
over-large regions reported a 10,818 km region as *less* distorted than a
700 km one and admitted it — while correctly refusing a smaller 7,221 km one.

The failure is silent and inverted: the check passes exactly the cases it
exists to stop. It now returns infinity beyond the antipode, and regions are
capped at **2,603 km across**, where distortion reaches 10 %.

*Reproduce:* `python -m backend.core.projection`.

---

## 4. Datasets

All source data is public-domain NASA, USGS, PDS or ISRO material. No dataset
in this repository is original; the catalogues, DEMs and imagery are cited in
`DATASETS.md` with producer, instrument, resolution and reference frame.

The **derived indexes** (Robbins → memory-mapped array; IAU gazetteer → JSON;
Robbins ↔ IAU spatial join) are transformations of published data, reproducible
from the scripts in `scripts/`.

---

## 5. How this work should be cited

If any of §3 is used, cite the finding rather than the software, and state the
version. The claims are reproducible from a tagged commit; the code is a means
of reproducing them, not the contribution itself.

Inherited methods must retain their original citations — Bekker, Janosi &
Hanamoto, Wong & Reece, Horn, Pike, Snyder, Dijkstra, Hart et al., Carrier et
al. A reader should be able to reach the primary source for every equation
without passing through this project.

---

## 6. Revision history

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-08-09 | Baseline. 53 citations and 20 formulas inventoried and classified; seven original findings stated with reproduction commands. |
| 1.1 | 2026-08-10 | Slip folded into the hazard cost surface; all findings re-measured on real Connecting Ridge terrain. §3.2 corrected — the earlier 45.0° gradeability was a search bound, not a result, and the finding is now that *which* constraint binds is soil-dependent. §3.5 added (any-angle planning). §3.4 extended with the real-terrain case, which contradicts the spread-only explanation. Two implementation defects found and fixed: any-angle path costs were averaged across chord endpoints rather than integrated, and D\* Lite's queue removal was O(n). |
