# LunarSerpent research-paper reproducibility audit

**Audit date:** 2026-10-13  
**Repository snapshot reviewed:** `c5e69bd7a63c1a84dadd54569bd47714697ce3f8` (`main`)  
**Purpose:** distinguish code presence, archived evidence, and claims that still require a clean experimental rerun.

## Verdict

**The paper is not yet reproducible from this repository snapshot.** The repository contains meaningful analysis and path-planning code, tests, a training notebook, and a terrain-only baseline archive. It does not contain the historical LOLA detector checkpoint, the frozen train/test tile manifests, the raw held-out predictions, or the five-site crater-fusion control/treatment outputs needed to independently reproduce the paper's detector and fusion claims.

This is an evidence-availability verdict, not a claim that the research was never performed. Do not replace missing artifacts with estimates or results from a different experiment.

## Critical method/data mismatch

The paper describes a U-Net with a ResNet-34 encoder trained on LOLA DEM-derived channels. The tracked notebook `notebooks/train_crater_unet_colab.ipynb` documents a different experiment: 256×256 crops from 640×640 Kaguya optical tiles at 125 m/px, with a per-pixel **crater-rim** target. Its cells have no saved execution outputs in the repository snapshot. This notebook is not evidence for the paper's LOLA-DEM model or its reported held-out metrics.

**Required resolution:** recover the actual LOLA notebook/training script and artifacts, or run a newly specified experiment on the claimed LOLA-derived inputs and replace the manuscript results with those newly measured results. Do not describe the Kaguya optical experiment as a reproduction of the LOLA experiment.

## Evidence inventory

| Paper claim/workstream | What the repository provides | Current evidence status |
|---|---|---|
| Detector P=0.829, R=0.710, F1=0.765 on held-out data | No matching checkpoint, 24-tile manifest, raw held-out predictions, or metric JSON found in this snapshot | **Not independently reproducible** |
| 1,048 train tiles and 24 held-out tiles / 1,979 craters | No frozen list of the exact tiles/labels that generated these counts | **Counts alone are not a reproducible split** |
| Five-site crater-fusion result / “no route changed” | No matching detector outputs, control/treatment route files, frozen cost-grid hashes, or run config bundle | **Claim cannot be established from current artifacts** |
| Terrain-only planner baseline | `docs/results/baseline_terrain_only.json` contains five frozen control cases and results | **Archived transcription check only; not a fresh rerun** |
| Multi-site planner comparison | `tests/benchmark_planners.py` documents a benchmark protocol, but its visible implementation prints console output rather than archiving a structured run-level artifact | **Needs run-level artifact export and rerun** |
| Ascent/descent mobility description | `backend/analysis/terramechanics.py::effective_speed` receives slope but no heading/travel direction and has no explicit descent speed cap | **Any manuscript claim of a descent-specific cap is unsupported by this implementation** |
| Bibliography | Manuscript is not tracked in this repository snapshot; source modules and docs provide references for some formulas | **Claim-level reference verification remains a separate task** |
| IEEE PDF layout, figures and tables | Manuscript DOCX/PDF is not in the tracked repository tree | **Cannot be repaired by a repository-only change; inspect and edit the source DOCX separately** |

## Archived baseline versus manuscript Table IX

The reviewed manuscript reports Table IX control route costs of 18,676; 16,779; 12,984; 14,142; and 14,925 s. The archived A* costs in `docs/results/baseline_terrain_only.json` for the corresponding five cases are 18,885.964; 16,979.515; 13,395.615; 14,466.226; and 15,117.616 s. Differences may be explained by a different grid, data product, start/goal, or configuration, but the matching provenance was not present in the reviewed snapshot.

Do not label these as the same run until the input data, product, configuration, and source revision are reconciled. Keep the archive immutable; write any new output to a new file.

## Equation-to-code check: slope direction

The current `effective_speed()` computes the grade-force term using `max(sin(theta), 0.0)` and rolling resistance. Its signature does not accept route heading or a direction flag, and the function contains no explicit descent cap. Therefore the paper must not claim that this code applies a direction-specific downhill speed limit.

Two defensible options exist:
1. **Conservative paper correction:** describe the implemented model exactly and state that direction-dependent downhill dynamics are outside its scope; or
2. **Model extension:** explicitly implement signed grade relative to the direction of travel, document assumptions and bounds, add unit tests, and rerun every affected result before changing the manuscript's claims.

Do not change the physical model merely to make the text agree with an unverified equation.

## What must be frozen for a reproducible submission

### Detector
- checkpoint and SHA-256; architecture, channel construction, normalization, threshold, and dependency versions
- exact training/validation/test tile IDs and the catalogue version used to label them
- source DEM product, resolution, spatial bounds, preprocessing script and hashes
- raw object predictions and the exact one-to-one matching rule, including centre/radius tolerances
- metrics calculated only after the split and evaluation rule are frozen

### Crater fusion
- five site manifests, start/goal, DEM/cost-grid identifiers and SHA-256 hashes
- control and treatment detection outputs and fused-cell masks
- risk/dilation thresholds, planner, planner parameters, and source commit
- ordered route coordinates and route cost for both control and treatment
- separately label any extra small-area or alternate-resolution experiment

### Planner benchmark
- one row per site/planner/seed/run, including success, cost, expanded nodes, path length, runtime, DEM/grid hash, start/goal, and configuration hash
- machine-readable JSON/CSV, raw console output, Python/package versions and commit SHA
- same cost grid and start/goal for every compared planner
- summarize repeated timings with the predeclared statistic; retain raw runs

### Manuscript publication checks
- trace each quantitative claim in abstract, tables, results and conclusion to a specific artifact/row
- audit each citation against its publisher/DOI metadata and the actual claim it supports
- make every figure, axis, unit, acronym and table readable in the target IEEE template
- ensure limitations say “regional planning / decision support” unless rover-scale safety is validated at an appropriate spatial scale
- add a concise conclusion that reports only supported findings
- render the final DOCX to PDF and inspect every page; venue-specific page limits/template still apply

## Commands for the evidence workflow

See [the reproducibility kit README](../reproducibility/README.md). The validators are intended to fail closed on inconsistent exports. They validate file structure and metric arithmetic; they do **not** prove that data, labels, matching rules, or scientific assumptions are valid.

A synthetic smoke-test pass is only evidence that the scripts behave on synthetic fixtures. It must never be reported as an experimental result.

## Submission decision

Until the detector/fusion evidence is recovered or rerun, the manuscript should either:
- remain a conservative integration/path-planning study that omits unsupported detector/fusion outcomes, or
- wait for the missing experiments to be rerun and archived.

Professional layout cannot compensate for missing experimental provenance. Conversely, missing old artifacts do not prevent a new, clearly identified experiment; they prevent calling it a reproduction of the historical result.
