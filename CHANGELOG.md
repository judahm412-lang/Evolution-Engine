# Changelog

## 2.0.1 — 2026-10-15

- Added the local research laboratory: measured storage, safe deletion and reclaim, verified backups and new-directory restore, disk policy, and resource monitoring.
- Added separate notes/tags/groups, bounded search, exact-seed repetition, persistent tournament baskets, bulk actions and new-run retention presets.
- Added paged ancestry graphs, parameter-by-parameter genetic comparison, historical replay, bounded extrema-preserving charts, bookmarks, descriptive milestones, timelines and offline research reports.
- Added durable maintenance jobs and a shared workspace gate across the scheduler, workers and maintenance; deleted queued work cannot start after maintenance.
- Migrated schema 2 to 3 transactionally while keeping scientific tables and compatible v2.0.0 checkpoint/RNG behavior intact. Corrected timeline checkpoint links to the last evaluated observation.
- Validated with 92 Python tests, five preserved Experiment 8 tests, actual stable-wheel 1,000-generation trajectory comparisons, browser acceptance, scale measurements and a separately installed wheel. Details and limits: `ENGINE_V2_0_1_RELEASE_REPORT.md`.

## 2.0.0 — 2026-10-12

- Added installable Python package, CLI, immutable configurable neural genomes and a generic environment/evaluation interface.
- Implemented source-audited RPS compatibility, exact controlled selection/mutation ordering, general selection and mutation options, and a continuous non-RPS example.
- Added transactional SQLite history, versioned/checksummed checkpoints, deterministic pause/resume and extension, independent RNG streams, read-only historical imports, CSV/JSON/gzip exports, and schema migrations.
- Added bounded-retry process scheduling, priority queues, independent replicate seeds, bot-weight sweeps, global/per-batch concurrency limits and generation-safe controls.
- Adapted Experiment 8's policy/match engine and seven causal unfamiliar opponents; added saved-cohort tournaments, lineage, clusters and genetic/behavioral analysis.
- Added optional Numba match acceleration, content-keyed policy caching, component benchmarks and measured 1/2/4-worker throughput.
- Integrated a local FastAPI/SSE dashboard for configuration, execution, monitoring, history, genetics, inspection, tournaments, comparisons and settings.
- Added source-block differential fixtures, persistence/failure tests, real-worker integration tests, 200/1,000-generation endurance evidence and browser acceptance evidence.
- Fixed queued-pause/start races, raw elite metadata reconciliation, generation validation, mutation discrepancy warnings, archive rollback, and immutable historical-database access.

Future reproduction, speciation, topology and lifetime-learning features remain outside this release.
