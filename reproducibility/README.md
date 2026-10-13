# LunarSerpent research reproducibility kit

This folder keeps the artifact audit and validation scripts alongside the source. **The tools do not create missing scientific evidence.** They hash available files, validate exported records, and calculate metrics only when the relevant frozen inputs are supplied.

See [the repository-grounded evidence audit](../docs/RESEARCH_PAPER_REPRODUCIBILITY.md) before interpreting any output.

## 1. Inventory the current checkout

```bash
python reproducibility/scripts/inventory_artifacts.py --root . --out reproducibility/runs/artifact_inventory.json
```

The report includes SHA-256 hashes, Python/platform information, source commit and candidate artifacts. Presence is not proof of provenance or correctness.

## 2. Recalculate object-level crater metrics

Export predictions to `reproducibility/schemas/detector_matches.csv` using one row per predicted object and the unique one-to-one catalogue match under a frozen matching rule. Then run:

```bash
python reproducibility/scripts/evaluate_crater_predictions.py --predictions reproducibility/runs/detector_matches.csv --catalog-count 1979 --out reproducibility/runs/detector_metrics.json
```

Use `--catalog-count 1979` only if the frozen test subset actually contains exactly 1,979 reference craters. The evaluator rejects duplicate predictions/matches, non-test rows, mixed checkpoints, and impossible counts. It does not validate the correctness of the matching algorithm.

## 3. Compare crater-fusion routes

Provide one JSON object following `reproducibility/schemas/fusion_site.json` for every frozen site, including control/treatment input hashes, config hashes, route coordinates and route cost. Then run:

```bash
python reproducibility/scripts/compare_fusion_routes.py --input reproducibility/runs/fusion_sites.json --out reproducibility/runs/fusion_comparison.json
```

Equal route cost does not imply equal route geometry. Route matching is performed on ordered coordinates rounded to nine decimal places. Declare any tolerance before analysis.

## 4. Validate the planner run log

Use the header in `reproducibility/schemas/planner_runs.csv`. There must be one row per site/planner/seed/run:

```bash
python reproducibility/scripts/validate_planner_logs.py --csv reproducibility/runs/planner_runs.csv --out reproducibility/runs/planner_log_audit.json
```

The validator checks schema, duplicate run keys and basic numeric consistency. It does not prove algorithm correctness or a fair comparison.

## 5. Source-project test and benchmark commands

Run from the repository root on the machine that has the required lunar data:

```bash
python run.py --check
python run.py --test
python tests/benchmark_planners.py
```

Capture the full console output, commit SHA, package versions, data product IDs and hashes. Do not overwrite `docs/results/baseline_terrain_only.json`; preserve new runs as separate timestamped files.

## Required historical inputs

To reproduce the paper's historical numbers, recover the exact LOLA checkpoint/configuration, train/validation/test manifests, raw predictions and matching script; the five-site fusion outputs and their inputs/configurations; and the complete planner logs. The currently tracked Kaguya optical notebook is a separate experiment and cannot substitute for the paper's LOLA DEM experiment.

Synthetic tests under this kit validate only software behavior on fabricated fixtures. They are not LunarSerpent experimental results.
