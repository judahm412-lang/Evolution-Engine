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

## Research tools and browser acceptance in progress (2026-10-14 resume)
- Implemented background jobs, research API, search/config diff, exact-seed browser creation/repeats, persistent baskets, graph/weight comparison, extrema-preserving charts, replay, milestones, timeline and offline HTML reports.
- Complete suite last passed: 87 tests in 13.90 s. New browser code was formatted with Prettier 3.6.2 (development tool only).
- Actual stable-wheel scientific regression completed: all three 1,000-generation runs match exactly in genome identities/bytes/metadata/fingerprints, all fitness/count rows, and final RNG states. One run used the real v2.0.0 wheel through generation 364, then migrated and resumed with edited notes/tags. Evidence: v2_0_1_scientific_validation.json; reproducible script scripts/validate_patch_science.py. Timing: old uninterrupted 23.614 s; patch uninterrupted 22.509 s, single sequential observations, not a claim of speedup.
- Browser test workspace ONLY: runtime/v201-browser, server port 8766. Existing runtime/release and historical files remain untouched.
- Browser verified: created exact seed 9223372036854775807 with Balanced preset, ran 12 generations (ID 2ac875ea4fc2); journal edit persisted and escaped script-like text; experiment bookmark; completed report job b03b7d397209456485d940b2defb0118; bulk tags and storage measurements completed; delete preview correctly listed identity, size, dependencies and extra no-backup acknowledgment. No deletion performed through browser.
- Existing disposable browser experiments: b9fb73092d66 dense 100 generations; 32a1a064b8f6 sparse 100; 916632a1641d created worker-preview placeholder. New exact-seed run is 2ac875ea4fc2.
- Browser runtime: use keyboard Enter/Space for reliable semantic actions; native click coordinates intermittently target the preceding item. A graph-script brace bug was caught on reload and fixed. Validate all JS with `node --input-type=module --check` using stdin; plain `node --check file.js` did not catch the module-context error reliably.
- Next: continue browser acceptance (backup/download, family/weights/replay/charts/timeline/milestones, repeat, basket persistence/server restart, desktop/mobile screenshots, console), stronger process-race/job-recovery tests, 100k-history performance, docs, package version/wheel, final audit and release. No release tag or master merge yet.

## Process safety and research interface checkpoint (2026-10-14)
- Full suite: 90 passed in 15.11 s. Added actual-process scheduler launch/queued-child deletion, active-worker WAL backup/restore, and executor hard-exit recovery tests.
- Browser archive e6a134dbff3c4b13a51be533056db743 verified and downloaded; downloaded SHA-256 matches the workspace archive (4bf57a9f36ead65fb3657ae9473ac83dd0adc0da78fd01bb35c338355d3cc1db). Contains three disposable experiments and 20 validated checkpoints.
- On resumption, persisted deletion job f3b19c9d256f468d9d703e4f89ed32f1 was completed with explicit ID confirmation and no-backup acknowledgment for disposable run 2ac875ea4fc2. Previous log described only the preview observed by the agent; the final deletion action occurred between recorded sessions. Existing real research was not involved.
- Added tag suggestions/counts, partial-graph frontier disclosure, populated default experiment selection, and backup-list refresh without full-page reload.
- Remaining release gates: finish browser workflows/responsive evidence, scale benchmarks, documentation, version/wheel, final review and release publication.

## Final validation checkpoint (2026-10-15)
- Full suite: 92 passed in 17.02 s before a presentation-only chart-axis spacing fix; suite rerun after that fix is part of the final gate. Five preserved Experiment 8 tests passed. JavaScript module syntax and `git diff --check` pass.
- Browser: notes/tag/repeat/basket/backup/replay/chart/lineage/weight/bookmark/milestone/timeline/report workflows exercised. Completion milestone review persisted after reload. Report downloaded (9,108 bytes) and escaped script-like note. Checkpoint 100 now links to recorded generation 99. No final-console errors.
- Scale: 100k synthetic aggregate rows query median 187.58 ms and preserve injected peak. Browser loaded 983 plotted points in 207.70 ms, with 10.20 ms measured for DOM/layout on the corrected chart. These are local warm observations, not controlled hardware claims. Other measurements in `v2_0_1_lab_benchmarks.json`.
- Original scientific files and 110 historical inputs remain byte-for-byte unchanged. Three actual 1,000-generation paths (stable wheel, stable checkpoint upgraded/resumed after metadata edits, patch) match all genome/fitness and final RNG boundaries in `v2_0_1_scientific_validation.json`.
- Final outside-checkout wheel check completes a 40-generation target run, archive verification, fresh-directory restore, and integrity/foreign-key checks. Wheel rebuilt after last chart-axis change; final hash recorded in release evidence/report.
