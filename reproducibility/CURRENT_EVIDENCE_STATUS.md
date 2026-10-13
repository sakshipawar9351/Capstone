# Current evidence status — LunarSerpent

**Audit date:** 2026-10-13  
**Audited main commit:** `c5e69bd7a63c1a84dadd54569bd47714697ce3f8`

This is a source-availability audit, not a successful rerun of the project.

| Claim/workstream | Current evidence | Status |
|---|---|---|
| Historical LOLA U-Net + ResNet-34 metrics (P=0.829, R=0.710, F1=0.765) | No matching checkpoint, frozen tile manifest, raw prediction export, or metrics manifest found in the audited public tree | **Not reproducible from current snapshot** |
| 1,048 training tiles / 24 held-out tiles / 1,979 craters | No matching frozen list of tile IDs and labels | **Counts not independently verified** |
| Five-site crater-fusion claim | No matching control/treatment output JSON, detected-object outputs, route files, or frozen configuration hashes | **Not established from current artifacts** |
| Five-site terrain-only baseline | `docs/results/baseline_terrain_only.json` archives A*/Dijkstra comparisons | **Static transcription check only; not rerun here** |
| Planner comparison table | Benchmark protocol/script exists but the run-level table output is not archived in structured form | **Needs clean rerun and logs** |
| Mobility-model descent claim | `effective_speed()` has no route-heading argument and no explicit descent speed cap | **Manuscript/code statement needs correction or model extension** |
| IEEE manuscript formatting | Manuscript source DOCX/PDF is not in the audited repository tree | **Requires a separate manuscript-source editing pass** |

The paper's Table IX control route costs differ from the corresponding archived A* costs. That discrepancy must be reconciled by a frozen configuration/data manifest rather than explained by assumption.

The tracked U-Net notebook is an optical-image experiment based on Kaguya tiles at 125 m/px and has no saved outputs in the repository. It is not the paper's LOLA DEM-derived experiment. Do not mix their data modalities or metrics.

## What was not done

- No training or inference was run.
- No full planner benchmark was rerun.
- No claim-level audit of every reference was completed.
- No synthetic smoke-test result was treated as scientific evidence.
