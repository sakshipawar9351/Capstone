# LunarSerpent research audit and submission gate

**Audit date:** 2026-10-13  
**Repository baseline:** `c5e69bd7a63c1a84dadd54569bd47714697ce3f8` (`main`)  
**Purpose:** Track and close issues that prevent a defensible, reproducible research paper. This audit does not certify scientific validity or replace independent review.

## Blocking findings

### R1 — Detector experiment provenance is unresolved (BLOCKER)
The published project notebook `notebooks/train_crater_unet_colab.ipynb` describes Kaguya optical imagery at 125 m/px, with 640 px tiles cropped to 256 px and U-Net/ResNet-34. The paper's detector claim is described as LOLA elevation-derived input. Those are different inputs and experiments. The notebook has no executed outputs in the repository tree, and no model checkpoint or evaluation manifest is tracked in the repository.

**Required closure:** identify the exact dataset and modality used for the paper results; recover the matching checkpoint, split manifest, prediction masks, evaluation script, and logs. If the reported LOLA result cannot be reconstructed, remove its numeric claims or explicitly replace the experiment with a newly run, fully documented LOLA experiment. Do not substitute optical metrics as DEM metrics.

### R2 — Spatial independence of held-out evaluation is unproven (BLOCKER)
The evaluation must show that train/validation/test pixels do not overlap geographically. Tile-level random splitting is not enough where tiles overlap spatially. Report the actual coordinate/block split, tile overlap audit, and whether the test region was used for model selection or threshold selection.

**Required closure:** build a machine-readable spatial split manifest; compute geographic overlap across all splits; freeze test data before tuning thresholds; report crater-level and pixel-level metrics with precise definitions.

### R3 — Crater-fusion experiment lacks traceable artifacts (BLOCKER)
Manuscript-reported fusion values require the exact control/treatment configuration, detector outputs, cost-map diffs, route outputs, and machine-readable results for all sites. The repository baseline `docs/results/baseline_terrain_only.json` is evidence for a terrain-only benchmark, not by itself evidence for a crater-fusion treatment.

**Required closure:** freeze the five site configurations; record data-product IDs, resolution, rover profile, soil, risk-aversion parameter, detector threshold, hazard inflation rule and start/goal; save control and treatment JSON; derive all manuscript tables from those files. Otherwise remove the treatment numbers and describe fusion as qualitative/prototype work only if supported.

### R4 — Descent behavior in the terramechanics implementation needs clarification (BLOCKER if the paper claims direction-aware descent)
`backend/analysis/terramechanics.py` has `slip_ratio(slope_deg)` and `effective_speed(slope_deg)` without route heading or signed route direction. `effective_speed` computes force using `max(sin(theta), 0.0)`; negative slope therefore receives no gravity-assist term and is not a descent/braking model. This does not support claims that ascent/descent-specific physical speed caps are modelled.

**Required closure:** either (a) narrow the paper's claim to a magnitude-based slope proxy and clearly state that direction-specific descent braking is not modelled, or (b) implement a signed grade/direction and a justified descent/braking model with unit tests and rerun every dependent experiment. Do not mix these alternatives.

### R5 — Reported route costs do not match the archived terrain-only baseline (BLOCKER for exact replication)
The archived `docs/results/baseline_terrain_only.json` contains a five-site run at approximately 29.6126 m/cell with costs including Apollo 17: 18885.964 s, Apollo 15: 16979.515 s, and Luna 21: 13395.615 s. A separate manuscript table reports different values for some of the same named sites. The difference may be legitimate if the corridor, endpoints or configuration changed, but the provenance must be explicit.

**Required closure:** give each run a unique configuration ID and state why site bounds, endpoints, DEM product, grid resolution, or cost parameters differ. Do not combine rows from different run configurations as if they were one baseline.

### R6 — The repository's status text is contradictory
`README.md` marks phases P1–P7 as pending, while it lists implemented analysis/planning modules and a benchmark. `tests/audit_science.py` contains stale verdict notes saying path planning and boulder detection are not built, despite planner modules/tests being present. These statements describe different snapshots or scopes and should not be silently treated as current truth.

**Required closure:** distinguish implemented, tested, data-dependent, experimental, and not implemented; generate status from evidence rather than optimistic phase names. Do not claim a feature is scientifically validated simply because code exists.

## Important reproducibility work

- Run the documented tests from a clean environment and archive stdout/stderr, environment details and dataset-availability decisions.
- Make test skips visible in CI. A test that exits successfully when required data is missing is not a completed validation experiment.
- Archive complete run-level planner data, not only aggregate tables; pin seeds and store every stochastic run.
- Track model card/configuration and SHA-256 of weights externally when the binary is too large for Git; document an immutable retrieval method.
- Verify that the benchmark script actually writes machine-readable raw results before citing it as a results generator.
- Run every scientific equation against the implementation, with explicit units and sign conventions.
- Audit all cited references against publisher pages/DOIs; a citation existing syntactically does not prove it supports the claim.

## Formatting and paper gate

- Add an explicit Conclusion section that summarizes only validated findings.
- Ensure every result in the abstract appears in a result table and traces to a raw result artifact.
- Put resolution, dataset, split, threshold, number of scenes/craters, uncertainty and metrics definitions next to the result they describe.
- Verify figure/table lettering, readable axis labels, equations, reference ordering and two-column layout in the final PDF.
- Clearly disclose that a software simulation/prototype does not certify a physical rover traverse.

## Automated artifact gate

Run `python scripts/audit_manuscript_artifacts.py` from the repository root. It searches the repository for checkpoints, evaluation/provenance files, and crater-fusion result artifacts, and checks whether the tracked U-Net notebook contains saved execution outputs and matches the LOLA-DEM modality described in the paper. It is expected to exit non-zero while blockers remain. If weights/results are stored outside the repository, pass their directory with `--artifact-root`; do not expose private credentials or upload restricted datasets.

The script checks artifact presence and provenance clues only; it does not validate model quality, rerun path planning, prove spatial independence, or certify a scientific claim.

## Submission gate

A manuscript is **not cleared for submission** until R1–R5 are closed or their unsupported claims are removed; the final paper is rebuilt; tests and experiments are run with logs; citations are checked; and all tables can be regenerated from archived outputs. A polished PDF alone is not sufficient.
