# LunarSerpent

**A scientific decision-support system for lunar surface analysis and rover traverse planning.**

LunarSerpent presents a 3-D interactive Moon globe as its interface — but the globe is the
front door to an analysis engine, not a visualisation in itself. The system ingests
authoritative lunar datasets, derives terrain products, detects and classifies surface
features, and plans safe rover traverses between user-specified selenographic coordinates.

**The governing principle is scientific provability.** Every displayed number traces to a
documented formula with a peer-reviewed source. Where a quantity cannot be determined with
justified confidence, the system states its uncertainty or declines to report it — rather than
producing a plausible-looking value.

---

## Documentation

| Document | Contents |
|---|---|
| [PRD](docs/PRD.md) | Product requirements — goals, features, acceptance criteria, explicit limitations |
| [SRD](docs/SRD.md) | System requirements — architecture, components, API, data models, verification |
| [FORMULAS](docs/FORMULAS.md) | **Every equation** with derivation, rejected alternatives, and DOI citation |
| [DATASETS](docs/DATASETS.md) | Data sources, access methods, provenance, licensing |
| [TECHNOLOGY](docs/TECHNOLOGY.md) | Stack selection per project part, with justification |
| [ALGORITHMS](docs/ALGORITHMS.md) | Path planner survey, comparison matrix, selection rationale |
| [SCIENCE_BACKGROUND](docs/SCIENCE_BACKGROUND.md) | Lunar surface science and flown-mission exploration insights |

**Readable HTML version:**

```powershell
python scripts/build_docs.py
```

Then open `docs/html/index.html`. Mathematics is typeset with KaTeX; light and dark themes
follow the OS preference.

---

## Scientific approach in brief

| Concern | Approach |
|---|---|
| **Coordinates** | IAU Mean-Earth/Polar-Axis (DE421) frame, spherical datum R = 1737.4 km. All positioning by selenographic latitude/longitude; pixel indices exist only as the output of a verified transform |
| **Topography** | LOLA `LDEM_16` (1895 m/px), read directly from PDS3 via `numpy.memmap`. Higher resolutions streamed by HTTP range request at zero storage cost |
| **Slope** | Horn (1981) 3×3 operator with **latitude-corrected cell size** — without which polar slopes are underestimated by up to 5.8× |
| **Craters** | Robbins (2019) catalogue (1 296 879 craters, complete ≥ 1 km) as ground truth; DEM-based curvature + Hough detection *below* that limit |
| **Boulders** | Shadow-length photoclinometry, *h* = *L*·tan(*e*), on metre-scale imagery within a selected area of interest |
| **Classification** | Pike (1974, 1977) morphometric scaling; class boundaries follow physical transitions, not round numbers |
| **Path planning** | A\* with a **proved** admissible and consistent heuristic, plus cost-validated smoothing; benchmarked against 7 other algorithms |

---

## Deliberate scientific limitations

These are disclosed rather than hidden, and surface in the UI where relevant:

- **Global metre-scale boulder mapping is not attempted.** It would require ~10¹⁴ pixels
  (hundreds of TB) and has never been done by any mission. Handled instead by a global
  catalogue plus on-demand high-resolution detail for a selected region.
- **Slope is scale-dependent.** Every slope and roughness value carries its measurement
  baseline. A 1.9 km-baseline slope is *not* what a rover wheel experiences.
- **Crater age is inferred, never measured.** Reported as three separate quantities:
  measured degradation index, stratigraphic epoch, and model age with explicit uncertainty.
- **Cylindrical projections fail at the poles.** Above 85° latitude the system refuses
  cylindrical analysis and requires polar stereographic products.
- **Synthetic training data has a domain gap.** Detector accuracy is reported on *both*
  synthetic and real imagery.

---

## Technology stack

Chosen under three hard environment constraints — no Node.js/npm, Windows Application Control
blocking newly-downloaded compiled DLLs (so no GDAL, rasterio, pandas or PyTorch), and
read-only data on a mounted Drive.

```
Presentation   Three.js (ESM via CDN import-map) · vanilla ES modules · CSS · inline SVG
Service        FastAPI · Uvicorn · Pydantic v2
Analysis       NumPy · SciPy · scikit-image · OpenCV · scikit-learn · networkx
Data           numpy.memmap -> PDS3 .IMG · HTTP range -> PDS · WMTS -> NASA Moon Trek
```

No build step. No admin rights. 9 runtime dependencies, all verified importable on the target
machine. See [TECHNOLOGY.md](docs/TECHNOLOGY.md) for why each was chosen and what was rejected.

---

## Data

Source datasets are read **in place** and never copied, so the project's own storage footprint
is negligible.

| Dataset | Role | Access |
|---|---|---|
| LOLA `LDEM_16` | Primary elevation, 1895 m/px | Drive mount, memmap |
| LOLA `LDEM_64` / `128` | On-demand detail | PDS HTTP range (verified 206) |
| Robbins (2019) | 1.3 M crater catalogue | Drive mount → NumPy index |
| Chandrayaan-2 OHRC | 0.25 m/px imagery for boulder detection | Drive mount |
| Artificial Lunar Landscape | 16 500 labelled images for detector validation | Drive mount |
| NASA Moon Trek WMTS | Basemap imagery | Streamed, LRU-cached |
| IAU Gazetteer | Official feature names | HTTPS, cached |

Full provenance, resolutions, formats and citation obligations in
[DATASETS.md](docs/DATASETS.md).

---

## Project status

| Phase | Deliverable | Status |
|---|---|---|
| **P0** | Documentation baseline | ✅ **Complete** |
| P1 | Data layer — selenographic core, PDS reader, catalogue index | ⬜ Pending |
| P2 | Terrain analysis — slope, aspect, curvature, roughness, hazard, cost | ⬜ Pending |
| P3 | Detection & classification | ⬜ Pending |
| P4 | Path planning + benchmark harness | ⬜ Pending |
| P5 | FastAPI service | ⬜ Pending |
| P6 | Three.js globe UI | ⬜ Pending |
| P7 | Validation — measured metrics appended to docs | ⬜ Pending |

---

## Layout

```
Lunar_Serpent/
├── README.md
├── backend/          core · data · analysis · planning · api
├── frontend/         index.html · js/ · css/
├── docs/             PRD · SRD · FORMULAS · DATASETS · TECHNOLOGY · ALGORITHMS · SCIENCE_BACKGROUND
│   └── html/         generated readable documentation site
├── scripts/          build_docs.py
├── tests/            formula and component verification
└── data/derived/     generated products
```

---

## Attribution

All source data is public-domain NASA, USGS, PDS and ISRO material. Scientific practice
nonetheless requires attribution, and the application displays the producer credit for every
active layer. Academic output derived from this project must cite Robbins (2019) for the
crater catalogue and the Space Robotics Group, Keio University for the Artificial Lunar
Landscape dataset. Full obligations in [DATASETS.md](docs/DATASETS.md) §9.

---

## Document control

| Field | Value |
|---|---|
| Document ID | LS-DOC-000 |
| Version | 1.0 |
| Status | Baseline |
| Date | 2026-08-04 |

### Revision history

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-08-04 | Baseline. Phase 0 documentation set complete: PRD, SRD, FORMULAS, DATASETS, TECHNOLOGY, ALGORITHMS, SCIENCE_BACKGROUND. Environment constraints measured, data sources verified reachable, LOLA georeferencing validated against live PDS labels. |
