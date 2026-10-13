# v2.0.1 implementation log

## Scope and baseline
- User directive: research laboratory quality-of-life release, all 20 numbered features.
- Stable tag verified: v2.0.0 = 143d300547b94dd21a01527ec81dfa004f836a1e.
- Working branch: develop/v2.0.1, created from clean master. develop/v2.1 untouched.
- Original scientific modules and original historical input files are preservation boundaries.
- All destructive tests use disposable workspaces; existing runtime workspaces are not deletion targets.

## Work in progress
- Phase 0 audited storage, API, scheduler, runner, CLI, research services, dashboard and tests.
- Baseline tests running; baseline performance recorded separately before source changes.
- Phase 1: explicit checkpoint compatibility, transactional schema migration, separate research metadata.
- Phase 2 design: a workspace advisory read/write gate shared by all writes and held for a worker's entire lifetime; exclusive nonblocking maintenance rejects all active workers. A queued child rechecks existence/status after acquiring its gate. Per-experiment legacy locks remain authoritative too. Scheduler launch and maintenance share the gate. Deletion is atomic and marks serialized source references. VACUUM is offline with respect to workers/writers. Backups use SQLite online snapshots.

## Release gate
No v2.0.1 tag or master merge until tests, original-checkpoint migration, deterministic 1,000-generation regression, backup/restore, browser acceptance, performance checks and wheel installation pass. This file is a progress record, not a completion claim.

## Persistence and storage foundation checkpoint
- Baseline: 49 tests passed in 12.19 s. New foundations plus unchanged regression suite: 72 passed in 12.82 s (two known warnings: TestClient deprecation and intentionally duplicated ZIP entry).
- Original-code fixture: tests/fixtures/v2_0_0/engine.sqlite.gz, schema 2, paused after 3 generations, seed 9223372036854775807; original commit and SHA-256 in provenance.json. Upgrade/resume equals an uninterrupted run in all genome, fitness and RNG comparisons.
- Added metadata schema 3, explicit format/science checkpoint compatibility, shared worker/write gate and exclusive maintenance, atomic bulk deletion with serialized analytical reference markers, consistent online backups and bounded new-directory restore, disk-space pause and resource sampling.
- Destructive tests inject rollback failures and exercise lock protection, a deleted queued child, WAL inclusion, corrupt/malicious ZIPs, missing external sources, insufficient space and exact resume after disk pause.
- Backup excludes logs, caches, lock files and earlier archives; external historical sources are explicitly referenced and verified rather than copied.
- Maintenance currently requires ALL workers paused, including when deleting an unrelated inactive experiment. This conservative rule is deliberate and must be visible in UI/docs.
- Original baseline generation measurement: 40 generations, seed 91, 0.645 s locally (single observation; cold/warm and runtime differences must be reported in final benchmarks).
- Remaining: background jobs/API, all dashboard features, historical queries/reports, expanded race/performance/browser acceptance, documentation, wheel and release gates. Package remains 2.0.0 pending validation.
