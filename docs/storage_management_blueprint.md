# Storage Management Blueprint

## Purpose

This document turns the current measured storage pressure into an executable storage-governance blueprint. It is not a long-term rulebook. It is a current-state planning document derived from live file sizes and current lifecycle rules in `docs/rulebooks/engineering_constraints.md`.

## Verified Inventory

Verified on 2026-04-09 from current workspace files:

| Class | Verified paths | Size | Lifecycle classification | Current decision | Rationale |
| --- | --- | ---: | --- | --- | --- |
| Active DB state | `RearMirror/data/quant.db`, `RearMirror/data/quant.db-wal`, `RearMirror/data/quant.db-shm` | ~29.52 GB | Formal asset + active DB state | Keep | `quant.db` and `quant.db-wal` were updated today; this is active formal state, not stale residue |
| Formal feature warehouse | `RearMirror/data/features/zz500_alpha158_neutralized.parquet`, `RearMirror/data/features/feature_store.parquet`, `RearMirror/data/features/zz500_alpha158_raw.parquet`, `RearMirror/data/features/label_store.parquet` | ~11.12 GB | Formal asset | Keep | This is the primary feature warehouse and published feature matrix set |
| Feature checkpoints co-located under formal features | `RearMirror/data/features/.alpha158_ckpt/*.parquet` | ~3.06 GB | Rebuildable cache-like intermediate, but currently path-misplaced inside formal asset tree | Keep for now; migrate later | The files are rebuildable, but they currently live under `data/features/`, so they must not be auto-deleted before path migration |
| Experiment task snapshots | `RearMirror/experiments/tasks/task_*/features/*.parquet` and `RearMirror/experiments/tasks/task_*/features/.alpha158_ckpt/*` | ~24.64 GB | Experiment artifact | Delete-eligible under retention policy | The dominant space use is repeated copies of `alpha158_raw.parquet` and checkpoint files across task directories |
| Draft analysis / intermediate outputs | `e:/quant/draft/zz500_alpha158_full_industrial.parquet`, `e:/quant/draft/zz500_alpha158_exact_neutralized.parquet` | ~2.04 GB verified, ~2.45 GB user-reported total | Draft / intermediate output | Delete-eligible, but not in current repo-scoped execution slice | These are not formal assets and not required as active DB state, but they live outside `RearMirror/` and need a separate workspace-level retention slice |
| QA smoke outputs | `RearMirror/data/results/qa/neutralize_smoke/**` | ~0.11 GB | QA temporary artifact | Delete-eligible | Small, safe, already fits current cleanup policy |

## Keep / Delete Matrix

### Keep Now

1. `RearMirror/data/quant.db`
2. `RearMirror/data/quant.db-wal`
3. `RearMirror/data/quant.db-shm`
4. `RearMirror/data/features/zz500_alpha158_neutralized.parquet`
5. `RearMirror/data/features/feature_store.parquet`
6. `RearMirror/data/features/zz500_alpha158_raw.parquet`
7. `RearMirror/data/features/label_store.parquet`

Reason:
- These files are either active formal state or the current primary feature warehouse.
- Deleting them would violate the current lifecycle rules for formal assets.

### Keep For Now, But Reclassify Later

1. `RearMirror/data/features/.alpha158_ckpt/*.parquet`

Reason:
- They behave like rebuildable checkpoints, not permanent formal outputs.
- But they are currently stored under the formal feature path, so the storage mechanism must not delete them until they are moved into a dedicated cache layer such as `data/cache/alpha158_ckpt/`.

### Delete-Eligible Under Controlled Mechanism

1. `RearMirror/experiments/tasks/task_*`
2. `RearMirror/data/results/qa/**`
3. `RearMirror/logs/**` older than retention
4. `RearMirror/data/cache/**` once such cache is actually populated

Reason:
- These are experiment, QA, or rebuildable outputs, not primary formal assets.
- They become safe deletion candidates only under explicit retention and evidence rules.

### Delete-Eligible, But Outside Current Repo Slice

1. `e:/quant/draft/*.parquet`

Reason:
- These are draft/intermediate outputs, not formal assets.
- They live outside the current `RearMirror/` repo boundary, so they should be handled by a later workspace-level draft retention slice rather than the current repo-scoped task cleanup mechanism.

## Mechanism Blueprint

### Lane 1: Experiment Task Retention Cleanup

This is the first implementation lane and the only one approved for the current `approved_cleanup_execution` slice.

Target objects:
- `RearMirror/experiments/tasks/task_*`

Required controls:
1. Default `dry-run`
2. Explicit `--apply` gate for real deletion
3. `retention_days`
4. `keep_last_n`
5. `pinned` / allowlist protection
6. `max_delete_gb` fuse per run
7. Manifest output recording path, size, mtime, reason, and whether deletion actually happened

Initial policy baseline:
1. Keep the newest 2 task directories unconditionally
2. Keep any pinned task directory unconditionally
3. Only consider task directories older than retention for deletion
4. Delete at most one ~6.16 GB task directory per apply run unless `max_delete_gb` is explicitly raised

### Lane 2: Draft Artifact Retention

This is a later slice, not the current one.

Target objects:
- `e:/quant/draft/*.parquet`

Required controls:
1. Workspace-level path boundary, not repo-only boundary
2. `dry-run` and `--apply`
3. Optional pinning / allowlist
4. Manifest output

### Lane 3: Formal Asset Optimization Without Deletion

This is not a deletion lane.

Target objects:
- `RearMirror/data/quant.db-wal`
- `RearMirror/data/features/.alpha158_ckpt/*`

Required actions:
1. DB maintenance planning for WAL checkpoint / truncate / compaction when DB is quiescent
2. Migration plan to move rebuildable checkpoint artifacts from `data/features/.alpha158_ckpt/` into a cache layer

This lane exists because the storage pressure is not only a deletion problem; part of it is a storage-tiering problem.

## What B Should Build First

Current B scope is only:
- implement retention-based cleanup for `RearMirror/experiments/tasks/task_*`

B must not in this round:
1. delete `data/quant.db`, `data/quant.db-wal`, or any other active DB state file
2. delete `data/features/zz500_alpha158_*` or `feature_store.parquet`
3. delete `data/features/.alpha158_ckpt/*` before a path migration plan exists
4. delete workspace-root `draft/*.parquet`

## Release Goals For The Next Validation Round

Session D should be able to verify:
1. `dry-run` lists real `task_*` candidates with expected estimated reclaimed space
2. `keep_last_n`, `retention_days`, and `pinned` actually protect expected directories
3. an `--apply` run can delete at least one approved stale task directory and produce a manifest
4. no formal asset path under `RearMirror/data/` is touched
