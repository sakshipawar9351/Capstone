# LunarSerpent — System Requirements Document (SRD)

**Document ID:** LS-DOC-002 · **Version:** 1.0 · **Status:** Baseline
**Date:** 2026-08-04
**Covers:** Project brief **Part 9**. Defines *how* the system satisfies the requirements in `PRD.md`.

---

## 1. Document control

| Field | Value |
|---|---|
| System | LunarSerpent |
| Parent document | `PRD.md` (LS-DOC-001) |
| Related | `FORMULAS.md`, `DATASETS.md`, `TECHNOLOGY.md`, `ALGORITHMS.md` |
| Scope | Architecture, components, interfaces, data models, verification |

---

## 2. System architecture

### 2.1 Architectural style

**Layered, with strict downward dependency.** A layer may call the layer below it and never
the layer above. This guarantees that the scientific core is independent of presentation and
can therefore be tested in isolation — a prerequisite for NFR-1 (scientific integrity) and
NFR-9 (maintainability).

```
┌───────────────────────────────────────────────────────────────┐
│  L5  PRESENTATION      Three.js globe · layers panel · charts │
├───────────────────────────────────────────────────────────────┤
│  L4  SERVICE           FastAPI routes · schemas · caching     │
├───────────────────────────────────────────────────────────────┤
│  L3  PLANNING          algorithms · rover model · benchmark   │
├───────────────────────────────────────────────────────────────┤
│  L2  ANALYSIS          terrain · detection · classify · hazard│
├───────────────────────────────────────────────────────────────┤
│  L1  CORE              selenographic · PDS reader · raster    │
├───────────────────────────────────────────────────────────────┤
│  L0  DATA              Drive mount · PDS HTTP range · WMTS    │
└───────────────────────────────────────────────────────────────┘
```

### 2.2 Key architectural decisions

| # | Decision | Rationale |
|---|---|---|
| AD-1 | Layered monolith, not microservices | Single-user analysis tool; network hops would add latency for no benefit |
| AD-2 | Data read in place, never copied | NFR-5; source provably unmodified |
| AD-3 | Coordinates are `(lat, lon)` at every layer boundary | Enforces PRD FR-1.3 (no pixel-based positioning) structurally, not by convention |
| AD-4 | Analysis layer has **zero** web dependencies | Testable and reusable without a server |
| AD-5 | Frontend consumes only the public API | No hidden coupling; API is the contract |
| AD-6 | All derived rasters share one projection | Layers register pixel-exactly with no reprojection |
| AD-7 | Formulas isolated in pure functions | Each is unit-testable against published values (FR-5.5) |

---

## 3. Directory structure

```
d:\Lunar_Serpent\
├── backend/
│   ├── config.py                  # paths, constants, product registry, rover profiles
│   ├── core/
│   │   ├── selenographic.py       # FORMULAS §1, §2  — coordinates & geodesy
│   │   ├── pds.py                 # PDS3 label parser + .IMG reader
│   │   ├── raster.py              # windowed DEM access (memmap + HTTP range)
│   │   └── remote.py              # HTTP range client, WMTS tile client
│   ├── data/
│   │   ├── sources.py             # dataset discovery & availability checks
│   │   ├── catalog_robbins.py     # 227 MB CSV -> compact NumPy index
│   │   └── catalog_iau.py         # IAU Gazetteer nomenclature
│   ├── analysis/
│   │   ├── terrain.py             # FORMULAS §3 — slope, aspect, curvature, roughness
│   │   ├── craters.py             # FORMULAS §5.1 — DEM crater detection
│   │   ├── boulders.py            # FORMULAS §5.2/5.3 — shadow-based detection
│   │   ├── classify.py            # FORMULAS §4 — taxonomy & morphometry
│   │   └── hazard.py              # FORMULAS §6 — hazard, risk, cost surfaces
│   ├── planning/
│   │   ├── costmap.py             # cost surface construction
│   │   ├── algorithms.py          # A*, Dijkstra, Theta*, D* Lite, RRT*, PRM, BFS, APF
│   │   ├── rover.py               # FORMULAS §7 — mobility model
│   │   ├── smoothing.py           # cost-validated shortcut smoothing
│   │   └── benchmark.py           # comparison harness
│   ├── api/
│   │   ├── schemas.py             # Pydantic models
│   │   └── routes/                # terrain, features, layers, paths, meta
│   └── main.py                    # FastAPI application
├── frontend/
│   ├── index.html
│   ├── css/
│   └── js/
│       ├── main.js                # bootstrap
│       ├── globe.js               # Three.js scene, sphere, camera
│       ├── tiles.js               # WMTS quadtree LOD
│       ├── layers.js              # layer registry & compositing
│       ├── features.js            # markers, labels, decluttering
│       ├── coords.js              # FORMULAS §1.3 (mirrors backend)
│       ├── panels/                # inspector, planner, legend
│       └── api.js                 # typed API client
├── docs/                          # PRD, SRD, FORMULAS, DATASETS, TECHNOLOGY, ALGORITHMS
├── tests/                         # formula & component tests
├── data/derived/                  # generated products (git-ignorable)
└── run.py                         # launcher
```

---

## 4. Layer L0 — Data access

### 4.1 Sources

| ID | Source | Access | Requirement |
|---|---|---|---|
| DS-1 | LOLA `LDEM_16` | `G:` Drive mount, `numpy.memmap` | Primary elevation |
| DS-2 | LOLA `LDEM_64/128` | PDS **HTTP range** | On-demand detail |
| DS-3 | Robbins catalogue | `G:` mount, streaming CSV parse | Crater layer |
| DS-4 | Moon Trek WMTS | HTTPS tiles, LRU cache | Basemap |
| DS-5 | IAU Gazetteer | HTTPS, cached | Feature names |
| DS-6 | OHRC / NAC | `G:` mount / ODE | AOI boulder detection |
| DS-7 | `artificial_lunar` | `G:` mount | Detector validation |

### 4.2 Requirements

| ID | Requirement |
|---|---|
| SR-D1 | Source availability shall be probed at startup; each source reports `available` / `degraded` / `unavailable` with a human-readable reason |
| SR-D2 | Absence of any single source shall not prevent startup |
| SR-D3 | No source file shall be opened for writing |
| SR-D4 | Remote reads shall use HTTP range requests where the server supports them (verified: PDS returns 206) |
| SR-D5 | Tile cache shall be bounded (default 512 MB) with LRU eviction |
| SR-D6 | The 227 MB Robbins CSV shall be converted **once** to a memory-mapped NumPy index; subsequent loads shall be O(1) |

### 4.3 Robbins index format

Streaming single-pass conversion (never fully in memory), producing a fixed-width binary:

| Field | dtype | Notes |
|---|---|---|
| `lat` | `float32` | planetocentric degrees |
| `lon` | `float32` | east, 0–360 |
| `diam_km` | `float32` | circle-fit diameter |
| `ellipticity` | `float32` | |
| `arc_frac` | `float32` | rim fraction traced (confidence proxy) |
| `class_id` | `uint8` | assigned per `FORMULAS.md` §4.3 |

≈ 1.3 M rows × 21 B ≈ **28 MB**, memory-mapped. A coarse lat/lon bucket index enables
sub-millisecond spatial queries without a database.

---

## 5. Layer L1 — Core

### 5.1 `core/selenographic.py`

Implements `FORMULAS.md` §1–2. Pure functions, no I/O.

| Function | Implements |
|---|---|
| `latlon_to_rowcol(lat, lon, W, H)` | §1.2 |
| `rowcol_to_latlon(row, col, W, H)` | §1.2 inverse |
| `latlon_to_xyz(lat, lon, z)` | §1.4 |
| `haversine(lat1, lon1, lat2, lon2)` | §2.1 |
| `surface_distance_3d(s_gc, dz)` | §2.2 |
| `initial_bearing(...)` | §2.3 |
| `cell_size_m(lat, W, H)` | §2.4 — **returns (dx, dy)**, dx latitude-corrected |

| ID | Requirement |
|---|---|
| SR-C1 | `latlon_to_rowcol` and its inverse shall round-trip within 1e-9 degrees |
| SR-C2 | `cell_size_m` shall reproduce the PDS `MAP_SCALE` at the equator to within 0.01 m |
| SR-C3 | Functions shall accept scalars **and** NumPy arrays (vectorised) |
| SR-C4 | Longitude shall be normalised to [0, 360) on input; −180…180 accepted |

### 5.2 `core/pds.py`

| ID | Requirement |
|---|---|
| SR-C5 | Shall parse PDS3 `.LBL` key/value and `OBJECT` blocks |
| SR-C6 | Shall extract `LINES`, `LINE_SAMPLES`, `SAMPLE_TYPE`, `SAMPLE_BITS`, `SCALING_FACTOR`, `OFFSET`, `MAP_RESOLUTION`, `MAP_SCALE` |
| SR-C7 | Shall map `SAMPLE_TYPE`/`SAMPLE_BITS` to a NumPy dtype (`LSB_INTEGER`/16 → `<i2`) |
| SR-C8 | Shall **never** hard-code raster parameters — always read from the label, falling back to the registry only if the label is absent, and warn when it does |

### 5.3 `core/raster.py`

| ID | Requirement |
|---|---|
| SR-C9 | `window(lat_min, lat_max, lon_min, lon_max, product)` shall return elevations in **metres** plus the geotransform |
| SR-C10 | Shall handle antimeridian-crossing windows |
| SR-C11 | Shall clamp latitude requests to ±90° and report clamping |
| SR-C12 | Shall select the product resolution appropriate to the requested extent, and report which was used |
| SR-C13 | Local memmap shall be preferred; remote range requests used only when the product is not local |

---

## 6. Layer L2 — Analysis

### 6.1 `analysis/terrain.py`

| ID | Requirement |
|---|---|
| SR-A1 | Slope shall use Horn's operator (`FORMULAS.md` §3.2) |
| SR-A2 | Slope shall use **latitude-corrected** `dx` per row (§2.4). *This is a correctness requirement, not an optimisation* |
| SR-A3 | Every terrain product shall be returned with its `baseline_m` |
| SR-A4 | Slopes below the noise floor (§3.5) shall be flagged, not silently rounded |
| SR-A5 | Curvature shall use Zevenbergen & Thorne (§3.4) |
| SR-A6 | Roughness shall provide TRI, RMS slope and relief, each with window size |
| SR-A7 | Above 85° latitude the module shall refuse cylindrical analysis and report that polar stereographic data is required |

### 6.2 `analysis/craters.py`

| ID | Requirement |
|---|---|
| SR-A8 | Detection shall require **all three** of: curvature signature, Hough circularity, depth-diameter consistency (§5.1) |
| SR-A9 | Each detection shall carry a confidence score calibrated against Robbins on D ≥ 1 km |
| SR-A10 | Detections shall be deduplicated against the catalogue; catalogue entries always take precedence |
| SR-A11 | Detector shall report precision, recall and F1 against Robbins on the overlap range |

### 6.3 `analysis/boulders.py`

| ID | Requirement |
|---|---|
| SR-A12 | Height shall be derived from shadow length and solar incidence (§5.2) |
| SR-A13 | Solar incidence shall be read from image metadata; **detection shall fail loudly if unavailable** rather than assume a value |
| SR-A14 | Minimum detectable height $h_{\min}$ shall be computed and returned with every survey |
| SR-A15 | Local slope correction shall be applied to shadow-derived heights |
| SR-A16 | Size–frequency distribution shall be fitted and sub-resolution population extrapolated (§5.3) |

### 6.4 `analysis/classify.py`

| ID | Requirement |
|---|---|
| SR-A17 | Classification shall follow `FORMULAS.md` §4.3 exactly |
| SR-A18 | Degradation index Δ shall be computed where depth is measurable (§4.4a) |
| SR-A19 | Age shall be exposed only as: degradation index, stratigraphic epoch, or model age **with uncertainty** — never a bare number |
| SR-A20 | Colour assignment shall be colour-vision-deficiency safe |

### 6.5 `analysis/hazard.py`

| ID | Requirement |
|---|---|
| SR-A21 | Hazards shall combine with `max()`, not a weighted sum (§6.4) |
| SR-A22 | Impassable cells shall be represented as `inf`, never a large finite number |
| SR-A23 | Hazard shall be parameterised by the selected rover profile |
| SR-A24 | Cost, hazard and risk surfaces shall be independently renderable as layers |

---

## 7. Layer L3 — Planning

| ID | Requirement |
|---|---|
| SR-P1 | Algorithms shall share one `PlannerResult` interface so metrics are comparable |
| SR-P2 | Every algorithm shall report: path, cost, length, time, energy, nodes expanded, peak open-set size, wall-clock, success |
| SR-P3 | A\* heuristic shall be the admissible/consistent form proved in `FORMULAS.md` §9.1 |
| SR-P4 | A\* and Dijkstra shall return **identical cost** on identical input — an automated test, since divergence proves a heuristic bug |
| SR-P5 | Stochastic algorithms shall accept a seed and report it, so runs are reproducible |
| SR-P6 | Smoothing shall accept a shortcut only if integrated cost strictly decreases |
| SR-P7 | The benchmark harness shall run all algorithms on identical inputs and emit a comparison table |
| SR-P8 | Planner shall operate on an AOI sub-grid, not the global grid, and report the AOI used |

---

## 8. Layer L4 — Service API

Base path `/api/v1`. All responses JSON unless noted.

### 8.1 Metadata

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/meta/health` | Service status |
| `GET` | `/meta/sources` | Dataset availability (SR-D1) |
| `GET` | `/meta/layers` | Layer registry with legends, units, credits |
| `GET` | `/meta/rovers` | Rover profiles |

### 8.2 Terrain

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/terrain/point?lat=&lon=` | Full terrain science at a point (FR-4.2) |
| `POST` | `/terrain/profile` | Elevation/slope profile along a polyline (FR-4.5, 4.6) |
| `GET` | `/terrain/window?...` | Gridded terrain products for an extent |

### 8.3 Features

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/features/craters?bbox=&min_diam=` | Catalogue query |
| `GET` | `/features/crater/{id}` | Full crater profile (FR-4.1) |
| `GET` | `/features/named?q=` | IAU name search (FR-7.4) |
| `POST` | `/features/detect/craters` | Run detection on an AOI |
| `POST` | `/features/detect/boulders` | Run boulder detection on an AOI |

### 8.4 Layers

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/layers/{layer}/{z}/{x}/{y}.png` | Rendered analysis tile |
| `GET` | `/layers/basemap/{layer}/{z}/{x}/{y}.jpg` | Proxied + cached WMTS tile |

### 8.5 Planning

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/plan/path` | Plan with the selected algorithm |
| `POST` | `/plan/compare` | Run all algorithms, return comparison (FR-6.3, 6.5) |

### 8.6 API requirements

| ID | Requirement |
|---|---|
| SR-S1 | Every numeric field shall carry units in its schema |
| SR-S2 | Every slope/roughness field shall carry `baseline_m` as a **required** field (FR-4.4) |
| SR-S3 | Every response shall include a `provenance` block naming source datasets |
| SR-S4 | Errors shall be structured `{code, message, detail}` with actionable messages |
| SR-S5 | Requests exceeding resource limits shall return 413 with the limit stated, not time out |
| SR-S6 | OpenAPI documentation shall be auto-served at `/docs` |

---

## 9. Layer L5 — Presentation

| ID | Requirement |
|---|---|
| SR-F1 | Sphere shall be generated procedurally with UV per `FORMULAS.md` §1.3 |
| SR-F2 | Surface material shall be **unlit**; the scene shall contain **no light sources** (FR-1.6) |
| SR-F3 | Basemap shall use quadtree LOD; tiles loaded only for the visible frustum |
| SR-F4 | Tile cache shall be bounded with LRU eviction (NFR-4) |
| SR-F5 | Click shall ray-cast to the sphere and invert UV to (lat, lon) exactly |
| SR-F6 | Labels shall declutter by feature importance and zoom (FR-1.11) |
| SR-F7 | Layer panel shall support toggle + opacity per layer, with legend |
| SR-F8 | Auto-rotate shall pause on interaction and resume after an idle interval |
| SR-F9 | Camera shall reach ±90° latitude without gimbal artefacts (FR-1.4) |
| SR-F10 | UI shall show a clear indicator when running on cached or offline data |

---

## 10. Data models

### 10.1 `TerrainPoint`

```jsonc
{
  "lat": -43.31, "lon": 348.64,
  "elevation_m": 1234.5,
  "elevation_uncertainty_m": 0.5,      // quantisation, FORMULAS §3.1
  "slope_deg": 12.4,
  "slope_baseline_m": 1895.21,         // REQUIRED — FORMULAS §3.5
  "slope_below_noise_floor": false,
  "aspect_deg": 217.8,
  "aspect_defined": true,
  "curvature_profile": -0.0021,
  "curvature_plan": 0.0009,
  "roughness_tri_m": 45.2,
  "roughness_window_px": 3,
  "hazard": { "slope": 0.31, "roughness": 0.12, "crater": 0.0, "combined": 0.31 },
  "provenance": { "dem": "LOLA LDEM_16", "producer": "NASA/GSFC/MIT" }
}
```

### 10.2 `Crater`

```jsonc
{
  "id": "ROBBINS-00123456",
  "name": "Tycho",                     // null if unnamed
  "lat": -43.31, "lon": 348.64,
  "diameter_km": 85.3,
  "area_km2": 5715.0,
  "depth_m": 4700, "depth_source": "measured",   // measured | predicted
  "depth_uncertainty_m": 1410,                   // ±30 % if predicted
  "rim_height_m": 1200,
  "class": "large", "morphology": "complex",
  "degradation_index": 0.94,
  "epoch": "Copernican",
  "model_age_ga": null,                          // only with adequate counts
  "source": "Robbins 2019"
}
```

### 10.3 `PlannedPath`

```jsonc
{
  "algorithm": "astar",
  "success": true,
  "waypoints": [{"lat": .., "lon": .., "elevation_m": ..}],
  "distance_m": 42350.0,
  "distance_3d_m": 42910.0,
  "time_s": 214550.0,
  "energy_j": 1.83e7,
  "cost": 231400.0,
  "cost_ratio_to_optimal": 1.00,
  "elevation": {"mean_m": 1210, "max_m": 2340, "min_m": 890},
  "slope": {"mean_deg": 4.2, "max_deg": 13.8},
  "terrain_risk": 0.13,
  "safety_score": 87.0,
  "craters_intersected": 0,
  "craters_avoided": 47,
  "recommended_speed_ms": 0.18,
  "metrics": {"nodes_expanded": 18432, "peak_open_set": 921, "wall_clock_ms": 342},
  "rationale": "Lowest cost of all candidates; matches the Dijkstra optimum ..."
}
```

---

## 11. Performance and resources

| ID | Requirement |
|---|---|
| SR-N1 | Point query < 500 ms (NFR-4) |
| SR-N2 | Path planning < 10 s on a 1000×1000 AOI |
| SR-N3 | Backend RSS < 1 GB under normal operation |
| SR-N4 | Global DEM shall never be loaded fully into RAM; memmap windows only |
| SR-N5 | Analysis tiles shall be cached; identical requests recomputed at most once |
| SR-N6 | Globe ≥ 30 fps at 1080p on integrated graphics |

---

## 12. Error handling

| Condition | Behaviour |
|---|---|
| Drive mount unavailable | Startup succeeds; sources report `unavailable`; UI banner; PDS fallback where possible |
| Network unavailable | Basemap falls back to `moon_texture.jpg`; UI indicates offline |
| Requested latitude > 85° with cylindrical product | 422 with explanation and pointer to polar products |
| AOI too large | 413 stating the limit and the requested size |
| Solar incidence missing for boulder detection | 422 — **never** substitute a default (SR-A13) |
| Corrupt/short DEM read | Fail with byte offsets; never return zeros as elevation |

---

## 13. Verification strategy

| Level | Method | Target |
|---|---|---|
| **Formula** | Unit test per formula against hand-computed or published values | 100 % of `FORMULAS.md` |
| **Georeferencing** | Round-trip lat/lon ↔ row/col; PDS label reproduction | SR-C1, SR-C2 |
| **Physical plausibility** | Known-location elevation checks (SPA basin deepest; farside highlands positive) | Data layer |
| **Detector** | Precision/recall vs Robbins; synthetic **and** real scores | SR-A11, FR-2.7 |
| **Planner** | A\* cost ≡ Dijkstra cost; networkx cross-check | SR-P4 |
| **API** | Schema validation; required-field enforcement | SR-S1, SR-S2 |
| **Integration** | End-to-end: coordinates → analysis → path → render | PRD §9 |

**Physical-plausibility tests are first-class.** A DEM reader that returns syntactically valid
but physically wrong elevations passes every type check and fails science. Tests therefore
assert against *known lunar facts* — the South Pole–Aitken basin must be the deepest region;
the farside must average higher than the nearside; the global range must bracket the label's
stated min/max.

---

## 14. Deployment

| Aspect | Specification |
|---|---|
| Runtime | Python 3.13, Windows 11 |
| Launch | `python run.py` → Uvicorn on `127.0.0.1:8765` |
| Frontend | Served statically by FastAPI; no build step |
| Dependencies | 9 runtime packages, all verified importable |
| Privileges | None required |
| Data | Read-only from `G:` mount + network |

---

## 15. Traceability — PRD → SRD

| PRD requirement | Satisfied by |
|---|---|
| FR-1.3 (real coordinates) | AD-3, SR-C1, SR-C4, SR-F5 |
| FR-1.4 (poles visible) | SR-F9, SR-A7 |
| FR-1.6 (no illumination) | SR-F2 |
| FR-1.7 (zoom clarity) | SR-F3, SR-F4 |
| FR-1.13 (six layers) | SR-A24, SR-F7 |
| FR-2.3 (boulder detection) | SR-A12 … SR-A16 |
| FR-2.5 (state detection limit) | SR-A14 |
| FR-3.1–3.3 (classification) | SR-A17 |
| FR-4.4 (units + baseline) | SR-S1, SR-S2, SR-A3 |
| FR-5.5 (executable formulas) | §13 Formula level |
| FR-6.3–6.5 (compare algorithms) | SR-P1, SR-P2, SR-P7 |
| FR-6.8 (path metrics) | §10.3 `PlannedPath` |
| NFR-1 (integrity) | AD-4, AD-7, §13 |
| NFR-2 (reproducibility) | SR-P5 |
| NFR-5 (storage) | AD-2, SR-D5, SR-N4 |

---

## 16. Revision history

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-08-04 | Baseline. Architecture, component requirements, API surface, data models and verification strategy defined against PRD v1.0. |
