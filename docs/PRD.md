# LunarSerpent — Product Requirements Document (PRD)

**Document ID:** LS-DOC-001 · **Version:** 1.0 · **Status:** Baseline
**Date:** 2026-08-04
**Covers:** Project brief **Part 9** (project documentation), and defines the requirements for Parts 1–7.

---

## 1. Document control

| Field | Value |
|---|---|
| Product | LunarSerpent — Lunar Scientific Analysis & Rover Traverse Planning System |
| Type | Scientific capstone project |
| Related documents | `SRD.md` (system requirements), `FORMULAS.md` (mathematics), `DATASETS.md` (data), `TECHNOLOGY.md` (stack), `ALGORITHMS.md` (planner selection), `SCIENCE_BACKGROUND.md` (domain) |
| Audience | Project owner, academic evaluators, future maintainers |

---

## 2. Executive summary

LunarSerpent is a **scientific decision-support system for lunar surface exploration**. It
presents a 3-D interactive Moon globe as its interface, but the globe is a *front end to an
analysis engine*, not a visualisation in itself.

The system ingests authoritative lunar datasets — LOLA topography, the Robbins crater
catalogue, LROC imagery, Chandrayaan-2 OHRC — and derives terrain products (slope, roughness,
curvature, hazard, risk, cost), detects and classifies surface features (craters, boulders),
and plans safe rover traverses between user-specified selenographic coordinates.

**The distinguishing requirement is scientific provability.** Every displayed number must
trace to a documented formula with a peer-reviewed source. Where a quantity cannot be
determined with justified confidence, the system states its uncertainty or declines to report
it — rather than producing a plausible-looking value.

---

## 3. Problem statement

Planning a lunar surface traverse requires simultaneously reasoning about topography,
morphology, obstacle distribution, vehicle capability and mission energy budget. These data
exist, but are scattered across archives in different projections, formats, resolutions and
reference frames. Existing tools address parts of this:

| Tool | Strength | Gap |
|---|---|---|
| NASA Moon Trek | Excellent imagery browsing | No traverse planning; no rover model |
| QGIS + planetary plugins | Full GIS analysis | Steep learning curve; not a mission tool; no 3-D globe |
| Published crater catalogues | Authoritative | Static tables; no terrain integration |
| Academic path planners | Rigorous algorithms | Not connected to real lunar data |

**No accessible tool takes a start and end coordinate on the Moon and returns a
scientifically-justified safe traverse with full provenance.** That is the gap LunarSerpent
fills.

---

## 4. Goals and non-goals

### 4.1 Goals

| # | Goal |
|---|---|
| G1 | Render the Moon in 3-D with Google-Maps-grade clarity, on real selenographic coordinates, uniformly visible from all directions including both poles |
| G2 | Detect and classify craters and boulders at the finest resolution the available data honestly supports |
| G3 | Compute per-feature and per-point terrain science: slope, elevation, depth, height, curvature, roughness — each with its measurement baseline and uncertainty |
| G4 | Plan safe rover traverses between user-chosen coordinates, comparing multiple algorithms and justifying the selection empirically |
| G5 | Make every result traceable to a formula and a citation |
| G6 | Deliver an interface that is attractive, interactive and genuinely usable for analysis |

### 4.2 Non-goals — stated explicitly

| # | Non-goal | Why |
|---|---|---|
| N1 | **Global metre-scale boulder mapping** | Physically impossible: ~10¹⁴ pixels, hundreds of TB. No mission has done it. Handled by global catalogue + on-demand AOI detail |
| N2 | Real-time rover telemetry / commanding | This is a planning tool, not flight software |
| N3 | Per-crater absolute age as a single number | Scientifically indefensible (`FORMULAS.md` §4.4) |
| N4 | Replacing published catalogues | Robbins is used as ground truth, not competed with |
| N5 | Sub-surface / geophysical modelling | Out of scope; surface only |

---

## 5. Users

| Persona | Needs | Primary parts |
|---|---|---|
| **Planetary science student** (primary) | Explore lunar terrain, inspect craters, understand methods | 1, 2, 3, 4 |
| **Mission planning analyst** | Evaluate candidate landing sites and traverses; compare routes | 4, 6 |
| **Academic evaluator** | Verify scientific correctness and traceability | 5, 8, 9 |
| **Robotics researcher** | Benchmark path planning on realistic terrain | 6 |

---

## 6. Functional requirements

Requirements are numbered `FR-<part>.<n>` and map to the project brief. Priority: **M** =
must-have, **S** = should-have, **C** = could-have.

### FR-1 — 3D Moon globe (brief Part 1)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-1.1 | Render an interactive 3-D Moon globe | M | Globe renders at ≥30 fps at 1080p |
| FR-1.2 | Display surface features (craters, maria, rilles) with clarity comparable to Google Earth | M | LROC WAC 100 m/px basemap resolves named craters ≥5 km at default zoom |
| FR-1.3 | Position everything by **real selenographic latitude/longitude**; no pixel-based positioning | M | Every feature's coordinates round-trip through `FORMULAS.md` §1.2 within 1 pixel |
| FR-1.4 | Both poles clearly and correctly visible | M | Camera can reach ±90°; polar features render without projection artefacts |
| FR-1.5 | Full 360° viewing from all sides | M | No orientation shows a blank, black or degraded hemisphere |
| FR-1.6 | **No sunlight / illumination effects** | M | Rendered brightness is independent of camera and light direction — unlit material, no scene lights (`FORMULAS.md` §8.1) |
| FR-1.7 | Zoom in/out retaining high resolution and clarity | M | Progressive WMTS LOD; no visible pixelation within the layer's native resolution |
| FR-1.8 | Auto-rotate **and** manual rotate | M | Both available; auto-rotate pauses on user interaction |
| FR-1.9 | Coordinate input — type or pick lat/lon | M | Typed coordinates fly the camera to target; click returns coordinates to ≤0.01° |
| FR-1.10 | Named features labelled at their exact coordinates | M | IAU Gazetteer names anchored to catalogue centres |
| FR-1.11 | Features remain legible when zoomed out | M | Label decluttering by feature importance; markers scale with zoom |
| FR-1.12 | Layers panel (Google-Maps style) | M | Toggle + opacity per layer |
| FR-1.13 | Layers: hazard, risk, crater detection, boulder detection, slope, cost map | M | All six present and independently toggleable |
| FR-1.14 | Additional layers: elevation, roughness, curvature, aspect, classification, illumination, geology | S | Each with legend and units |
| FR-1.15 | Graticule (lat/lon grid) overlay | S | Toggleable; labelled |
| FR-1.16 | Offline fallback basemap | S | Globe renders with no network |

### FR-2 — Crater and boulder detection (brief Part 2)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-2.1 | Provide a global crater layer complete to D ≥ 1 km | M | Robbins catalogue loaded; 1 296 879 craters queryable |
| FR-2.2 | Detect craters below catalogue completeness from the DEM | M | Detector runs; precision/recall reported against Robbins on the ≥1 km overlap |
| FR-2.3 | Detect boulders at metre scale within a user-selected AOI | M | Shadow-based detection on OHRC/NAC; minimum detectable height reported per scene |
| FR-2.4 | Report full scientific information per feature | M | Name, coordinates, diameter, area, depth, height, slope, elevation, classification, degradation index, epoch — with units and uncertainties |
| FR-2.5 | State the detection limit alongside every survey | M | "No boulders detected" is never reported without the accompanying $h_{\min}$ |
| FR-2.6 | Extrapolate sub-resolution boulder population | S | Size–frequency power law fitted and reported (`FORMULAS.md` §5.3) |
| FR-2.7 | Validate detector against independent ground truth | M | Scored on `artificial_lunar` masks **and** real images, both reported |

### FR-3 — Classification (brief Part 3)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-3.1 | Classify craters by size into named classes | M | 7 classes per `FORMULAS.md` §4.3 |
| FR-3.2 | Base class boundaries on published reference data | M | Every boundary cites a physical/observational transition |
| FR-3.3 | Provide proof/formula for each classification rule | M | Documented in `FORMULAS.md` §4 |
| FR-3.4 | Visually separate classes by distinct colour | M | Colour-blind-safe categorical palette; legend always visible |
| FR-3.5 | Classify boulders by size and hazard category | M | Bins tied to rover clearance and wheel diameter |
| FR-3.6 | Report morphological type (simple / complex / peak-ring / basin) | S | Derived from diameter and measured $d/D$ |

### FR-4 — Per-feature calculation (brief Part 4)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-4.1 | Clicking a crater returns its full scientific profile | M | Response < 500 ms |
| FR-4.2 | Clicking any point returns local terrain science | M | Slope, aspect, elevation, curvature, roughness, hazard |
| FR-4.3 | Any point along a planned path is inspectable | M | Same data as FR-4.2, plus along-path cumulative metrics |
| FR-4.4 | Every value carries units and measurement baseline | M | Schema-enforced; baseline is a required field |
| FR-4.5 | Elevation profile along a path or transect | M | SVG chart with distance and elevation axes |
| FR-4.6 | Slope profile along a path | M | With the rover's slope limit marked |

### FR-5 — Formula documentation (brief Part 5)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-5.1 | Separate document listing every formula used | M | `FORMULAS.md` exists and is complete |
| FR-5.2 | Proof or justification for each formula | M | Every entry has a Derivation/Proof section |
| FR-5.3 | Source/reference for each formula | M | DOI-resolvable citation per entry |
| FR-5.4 | Explanation of *why* each formula is used | M | Every entry has a "Why this one" section naming rejected alternatives |
| FR-5.5 | Formulas verified by executable tests | S | Unit test per formula against hand-computed or published values |

### FR-6 — Path planning (brief Part 6)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-6.1 | User selects start and end by latitude/longitude | M | Typed entry or map click |
| FR-6.2 | Compute the safest path avoiding craters, boulders and hazardous slopes | M | Returned path has no cell exceeding rover limits |
| FR-6.3 | Compare multiple planning algorithms | M | ≥6 algorithms executed on identical inputs |
| FR-6.4 | State which algorithm was selected and why | M | `ALGORITHMS.md` §4, with empirical support |
| FR-6.5 | Show outputs and paths from the other algorithms | M | All rendered simultaneously, visually distinguished |
| FR-6.6 | Highlight the recommended path | M | Visually dominant; others subdued |
| FR-6.7 | Explain why the highlighted path is recommended | M | Human-readable rationale citing its metrics |
| FR-6.8 | Report per-path: distance, time, speed, cost, elevation (avg/max), slope (avg/max), terrain risk, safety score, craters detected and avoided, recommended speed | M | All fields present for every path |
| FR-6.9 | Start and end pin markers | M | Distinct symbols |
| FR-6.10 | Rover profile selectable | S | ≥3 profiles; changing profile re-plans |
| FR-6.11 | Risk-aversion parameter exposed | S | Slider from fastest to safest; path family shown |
| FR-6.12 | Replanning when a new hazard is introduced | C | D\* Lite repair demonstrated |

### FR-7 — Interface (brief Part 7)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| FR-7.1 | Attractive, professional scientific visual design | M | Consistent design system; dark theme suited to imagery |
| FR-7.2 | Interactive and responsive | M | All controls < 100 ms feedback |
| FR-7.3 | Layer legends with units | M | Every active layer shows a legend |
| FR-7.4 | Feature search by name | S | Type-ahead over IAU names |
| FR-7.5 | Export results (JSON / CSV / GeoJSON) | S | Paths and feature tables exportable |
| FR-7.6 | Provenance visible in-app | M | Active layers show data producer and citation |

---

## 7. Non-functional requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-1 | **Scientific integrity** | No displayed value may lack a documented derivation. Uncertainty is reported wherever it is material |
| NFR-2 | **Reproducibility** | Identical inputs produce identical outputs. Stochastic methods are never used for primary results |
| NFR-3 | **Provenance** | Every layer names its source dataset and producer |
| NFR-4 | Performance | Globe ≥30 fps; point query <500 ms; path planning <10 s on a 1000×1000 AOI |
| NFR-5 | Storage | No bulk duplication of source data; local footprint <100 MB excluding caches |
| NFR-6 | Portability | Runs on the target machine with no build step and no admin rights |
| NFR-7 | Resilience | Network loss degrades gracefully to cached/offline data with a clear indicator |
| NFR-8 | Accessibility | Colour palettes distinguishable under common colour-vision deficiencies; no information conveyed by colour alone |
| NFR-9 | Maintainability | Analysis code separated from presentation; formulas isolated in testable functions |
| NFR-10 | Documentation | PRD, SRD, FORMULAS, DATASETS, TECHNOLOGY, ALGORITHMS all maintained and cross-referenced |

---

## 8. Explicit scientific limitations

These are **product decisions**, disclosed rather than hidden. Each appears in the UI where
relevant.

| # | Limitation | Consequence | How disclosed |
|---|---|---|---|
| L1 | Global DEM baseline is 1895 m | Global slope is *corridor-scale*, not rover-scale | Baseline shown with every slope value |
| L2 | Boulder detection requires AOI-scale imagery | Not globally available | AOI selection is explicit; coverage shown |
| L3 | Crater age is inferred, never measured | Only degradation index, epoch, and model age with uncertainty | Three separate labelled fields |
| L4 | Synthetic training data has a domain gap | Detector scores differ on synthetic vs real | **Both** scores published |
| L5 | Simple-cylindrical grids degenerate at poles | Cylindrical analysis invalid above ~85° | System switches to polar stereographic and says so |
| L6 | LOLA interpolation creates artificial roughness | Apparent texture in sparse-track regions is not real | Interpolated regions flagged |
| L7 | Vertical quantisation is 0.5 m | Slopes below ~0.05° unresolvable | Reported as "below noise floor" |

---

## 9. Success metrics

| # | Metric | Target |
|---|---|---|
| SM-1 | Formulas with proof **and** citation | 100 % |
| SM-2 | Displayed values traceable to a formula | 100 % |
| SM-3 | Crater detector precision vs Robbins (D ≥ 1 km) | ≥ 0.80 |
| SM-4 | Crater detector recall vs Robbins (D ≥ 1 km) | ≥ 0.70 |
| SM-5 | A\* path cost vs Dijkstra optimum | = 1.00 (identical) |
| SM-6 | A\* nodes expanded vs Dijkstra | ≤ 0.50 |
| SM-7 | Algorithms compared | ≥ 6 |
| SM-8 | Coordinate round-trip error | ≤ 1 pixel |
| SM-9 | Globe frame rate at 1080p | ≥ 30 fps |
| SM-10 | Local storage excluding caches | ≤ 100 MB |

> SM-3 and SM-4 are **targets, not guarantees.** If the classical detector does not reach
> them, the measured values are reported as they are. Reporting a real 0.62 recall is
> scientifically correct; claiming 0.85 without evidence is not.

---

## 10. Release phases

| Phase | Deliverable | Status |
|---|---|---|
| **P0** | Documentation baseline — PRD, SRD, FORMULAS, DATASETS, TECHNOLOGY, ALGORITHMS | **In progress** |
| P1 | Data layer — selenographic core, PDS reader, catalogue index | Pending |
| P2 | Terrain analysis — slope, aspect, curvature, roughness, hazard, risk, cost | Pending |
| P3 | Detection & classification — craters, boulders, taxonomy | Pending |
| P4 | Path planning — all algorithms + benchmark harness | Pending |
| P5 | API — FastAPI service exposing all analyses | Pending |
| P6 | Globe UI — Three.js, layers panel, interaction | Pending |
| P7 | Validation & reporting — measured metrics appended to docs | Pending |

---

## 11. Traceability — brief → requirements

| Brief part | Requirements | Supporting documents |
|---|---|---|
| 1. 3D globe | FR-1.1 … FR-1.16 | `FORMULAS.md` §1, §8; `TECHNOLOGY.md` §3 |
| 2. Detection | FR-2.1 … FR-2.7 | `FORMULAS.md` §5; `DATASETS.md` §4 |
| 3. Classification | FR-3.1 … FR-3.6 | `FORMULAS.md` §4 |
| 4. Per-feature calculation | FR-4.1 … FR-4.6 | `FORMULAS.md` §3 |
| 5. Formula documentation | FR-5.1 … FR-5.5 | `FORMULAS.md` (whole) |
| 6. Path planning | FR-6.1 … FR-6.12 | `ALGORITHMS.md`; `FORMULAS.md` §6, §7, §9 |
| 7. Interface | FR-7.1 … FR-7.6 | `TECHNOLOGY.md` §3 |
| 8. Datasets & technology | — | `DATASETS.md`; `TECHNOLOGY.md` |
| 9. Documentation | — | This document; `SRD.md` |

---

## 12. Revision history

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-08-04 | Baseline. Requirements derived from project brief; scientific limitations stated explicitly; success metrics defined as measurable targets. |
