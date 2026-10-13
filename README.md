# LunarSerpent

**A scientific decision-support system for lunar surface analysis and rover traverse planning.**

LunarSerpent provides a 3-D interactive Moon-globe interface for exploring lunar datasets and terrain-analysis outputs. The public repository contains terrain-derivative, terramechanics and planner components, plus research notebooks; however, the complete detector-to-cost-map-to-route experiment is not independently reproducible from the currently tracked artifacts. Route outputs are model-based decision-support, not a certification of physical rover safety.

**The design goal is scientific traceability.** Equations, assumptions, data sources and limitations should be documented, and unsupported quantities should be reported as unavailable rather than inferred. Some research components remain experimental or depend on external data and model artifacts; code presence alone is not evidence of scientific validation.

---

## Run it

```powershell
python run.py
```

That is the whole thing. It checks the environment, reports which datasets
resolved and from where, starts the API, and opens the interface at
**http://127.0.0.1:8765/**. On Windows `run` works too.

First time only:

```powershell
python -m pip install -r requirements.txt
```

| Command | What it does |
|---|---|
| `python run.py` | Preflight, then serve and open a browser |
| `python run.py --check` | Preflight only — verify the environment and datasets, start nothing |
| `python run.py --test` | Run the full test suite first; refuse to serve if it fails |
| `python run.py --docs` | Rebuild `docs/html/` before serving |
| `python run.py --port 9000` | Serve on another port |
| `python run.py --no-browser` | Do not open a browser |
| `python scripts/audit_manuscript_artifacts.py` | Check whether checkpoints, detector provenance and crater-fusion result files needed by the paper are present; expected to report blockers until missing artifacts are supplied |

The preflight is worth reading rather than skipping: it prints which of the
candidate data roots each dataset resolved from, so a missing DEM is reported
as a missing DEM instead of surfacing later as an error inside a memmap.

Ctrl+C stops it.

---

## Documentation

| Document | Contents |
|---|---|
| [PRD](docs/PRD.md) | Product requirements — goals, features, acceptance criteria, explicit limitations |
| [SRD](docs/SRD.md) | System requirements — architecture, components, API, data models, verification |
| [FORMULAS](docs/FORMULAS.md) | **Every equation** with derivation, rejected alternatives, and DOI citation |
| [CONTRIBUTIONS](docs/CONTRIBUTIONS.md) | What is inherited, what is adapted, what is original — every method classified |
| [DATASETS](docs/DATASETS.md) | Data sources, access methods, provenance, licensing |
| [TECHNOLOGY](docs/TECHNOLOGY.md) | Stack selection per project part, with justification |
| [ALGORITHMS](docs/ALGORITHMS.md) | Path planner survey, comparison matrix, selection rationale, measured benchmark |
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
| **Craters** | Robbins catalogue support and terrain-analysis utilities are present. A reproducible end-to-end detector is not established by the current public artifacts; the checked-in U-Net notebook describes a separate Kaguya optical experiment |
| **Boulders** | Shadow-length photoclinometry is a proposed approach; quantitative boulder detection and validation are not established in this repository snapshot |
| **Classification** | Pike (1974, 1977) morphometric scaling; class boundaries follow physical transitions, not round numbers |
| **Path planning** | Seven planner implementations including A*, with algorithmic tests and an archived five-site terrain-only baseline; broader benchmark claims require matching run-level outputs |

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
- **Detector metrics require provenance.** No detector-accuracy claim is treated as validated unless the exact weights, data/split manifest, predictions and metric outputs are archived.

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

No build step. No admin rights. The local runtime uses the pinned dependencies documented in `requirements.txt`; detector training and model evaluation are separate workflows and are not established by the local runtime alone. See [TECHNOLOGY.md](docs/TECHNOLOGY.md) for the environment constraints.

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
| Artificial Lunar Landscape | Candidate labelled source identified for detector work; a validated result must cite the exact sample, split and evaluation outputs | Drive mount |
| NASA Moon Trek WMTS | Basemap imagery | Streamed, LRU-cached |
| IAU Gazetteer | Official feature names | HTTPS, cached |

Full provenance, resolutions, formats and citation obligations in
[DATASETS.md](docs/DATASETS.md).

---

## Project status

| Phase | Deliverable | Evidence-based status |
|---|---|---|
| **P0** | Documentation baseline | ✅ Documentation present |
| P1 | Data layer — selenographic core, PDS reader, catalogue index | ✅ Core modules present; execution depends on local data products |
| P2 | Terrain analysis — slope, aspect, curvature, roughness, hazard, cost | ✅ Analysis modules and tests present; validation remains data-/scale-dependent |
| P3 | Detection & classification | ⚠️ No single validated end-to-end detector is established by this repository snapshot; notebooks must be matched to the paper's dataset/modality |
| P4 | Path planning + benchmark harness | ✅ Planner implementation, tests, and benchmark script present; paper-specific results still require run-level provenance |
| P5 | FastAPI service | ✅ API modules and API tests present |
| P6 | Three.js globe UI | ✅ Frontend modules and frontend audit present |
| P7 | Validation — measured metrics appended to docs | ⚠️ Component checks exist; this does not establish reproducibility of every manuscript experiment |

**Status interpretation:** module presence means implementation exists, not that the feature is scientifically validated or independently reproducible. Results that require external DEMs, trained weights, or site-specific configurations are validated only when the corresponding inputs and run logs are available.

---

## Research-paper reproducibility note

The repository contains multiple distinct strands of work. In particular,
`notebooks/train_crater_unet_colab.ipynb` describes a U-Net/ResNet-34 experiment
on Kaguya optical imagery at 125 m/px, with 640 px tiles and 256 px centre crops.
It must **not** be treated as evidence for any paper result described as a
LOLA-DEM/elevation-input experiment. Those are different modalities and
experimental configurations.

The archived `docs/results/baseline_terrain_only.json` records terrain-only
planner runs. It is not, by itself, evidence for a crater-fusion treatment.
A paper should quote detector or fusion metrics only when the matching data
manifest, model/checkpoint identity, evaluation code, frozen site configuration,
and raw outputs can be produced. If an artifact is unavailable, state that
explicitly and remove or rerun the unsupported claim rather than infer a value.

For the current audit checklist and exact closure criteria, see
[`docs/RESEARCH_AUDIT_AND_SUBMISSION_GATE.md`](docs/RESEARCH_AUDIT_AND_SUBMISSION_GATE.md).

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
