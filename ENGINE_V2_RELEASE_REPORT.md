# Evolution Engine v2.0 release report

Release audit completed 2026-10-12. Source and artifacts are in `engineV2/`; original Engine v1 and Experiment 8 remain separate.

## Executive summary

Engine v2.0 implements the requested local evolutionary research workflow: configure independent experiments, evolve source-compatible RPS populations, pause/resume and extend runs, recover interrupted workers, inspect lineage and behavior, compare histories, run saved-network championships, and export results. It installs as a Python package with a CLI and a bundled local dashboard. Required v2.0 features are implemented and exercised; the scientific and platform limits below define the release's verified scope.

The browser-created 100-network, 1,000-generation acceptance experiment completed after pause at generation 364, web-server restart and resume. Its complete genome and fitness digests match the separately executed uninterrupted run. A four-pause 1,000-generation run matches as well. All 110 original files in the pre-development manifest pass SHA-256 preservation checks.

## Implemented feature inventory

| Area | Delivered behavior |
|---|---|
| Neural engine | Immutable float64 genomes, arbitrary feedforward layer sizes, five activations and activation registry, initialization, batch observations, serialization and distance |
| Evolution | Population identities, separate fitness, stable top-N/tournament/rank selection, elitism, asexual inheritance, uniform/Gaussian weight/bias mutation, actual mutation records and ancestry |
| Environments | Source-audited RPS, original bots/phases, controlled schedules, match traces, and continuous target demonstration with more than three outputs |
| Persistence | Strict TOML/JSON, namespace-qualified SQLite genomes, referenced snapshots, normalized fitness/events, transactional migrations, checksummed checkpoints, safe pause/resume/stop/extension |
| Scheduling | Independent processes/RNG streams, priorities, bounded retries, worker-crash detection, global and batch limits, replicate seeds and bot-weight sweeps |
| Research | Saved-cohort round robins, original and seven unfamiliar opponents, historical champions, score matrices, descriptive clusters, genetic/behavioral diversity, founders and bounded ancestry traversal |
| Import/export | Raw TurboWarp TXT/JSON/ZIP, omitted-elite reconciliation, mutation/missing-data warnings, immutable Experiment 8 references, JSON/CSV/gzip results and tournament download endpoints |
| Dashboard | Overview, creation/templates/duplication, live monitor, filters/history, genetics, inspector, tournament lab, comparisons, measured benchmarks and connected settings |
| Distribution | Real src-layout package, module/console entry points, lock file, examples, wheel, tests and required documentation |

## Architecture overview

The runner coordinates validated configuration, environment evaluation, modular reproduction and atomic storage. Genome inheritance is isolated from runtime caches. A detached process scheduler controls independent workers through SQLite state and advisory locks. The web server is a client of the same services, and SSE throttles progress rendering. Both research and evolution use the shared v2 RPS core; the existing Experiment 8 implementation remains frozen. See `ARCHITECTURE.md`, `DATABASE_SCHEMA.md` and the programmatic examples in `EXPERIMENT_GUIDE.md`.

## Engine v1 compatibility results

The actual SB3 source establishes 9→12→3 architecture, all-weights-then-bias ordering, newest-first input encoding, lowest-index tie handling, 30 shuffled rounds of 23 self-play and 20 bot throws, per-round weighted score accumulation, final-shuffle tie ranking, four elite-parent passes and source-ordered mutation draws.

Differential tests compare the frozen Experiment 8 implementation over 12 genomes × 40 histories, and execute SB3 blocks through a limited test interpreter for three genomes × 40 histories, one controlled complete population round, top-20 selection, mutation and identity metadata. Checked-in source-hashed fixtures additionally compare hidden/output activations for two genomes × 40 histories. Tested actions, controlled fitness, ranking and mutations agree; neural float comparisons allow 1e-12. A live TurboWarp JavaScript VM was not executed. The same numeric seed is not claimed to produce identical cross-engine histories. See `COMPATIBILITY.md` for exact boundaries and the final saved-next-population convention.

## Automated test results

- Full v2 suite: **49 passed**, 12.19 seconds on the final integrated implementation before the last export-only addition.
- Final export/historical/research regression: **5 passed**, 0.38 seconds after that addition.
- Preserved Experiment 8 suite: **5 passed**, 0.024 seconds; source/results were not rewritten.
- JavaScript syntax validation passed (`node --check`).
- The only Python test warning is Starlette's deprecation notice for its httpx TestClient adapter; no test failure was suppressed.

Coverage includes source differentials, parameter/activation validation, immutability, cache identity after shuffles, reference/compiled equality, selection/mutation, non-RPS evolution, exact recovery, corruption rejection, injected pre-checkpoint/pre-commit failures, migrations, raw/gzip imports, rollback, API validation/security, exports, actual subprocess workers, SIGKILL recovery, pause/cancel, distinct replicate seeds and enforced per-batch concurrency. Integration tests need permitted loopback networking and process execution.

The wheel was installed into a fresh temporary venv and imported from site-packages while running outside the checkout. Without Numba installed, the CLI completed the 40-generation target example and the engine completed a three-generation compatibility run using its NumPy fallback. Bundled HTML/CSS/JS and OpenAPI routes were verified; SQLite integrity passed. Evidence: `wheel_validation.json`.

## Performance benchmarks

On Ryzen 7 9700X/Python 3.13.5/NumPy 2.5.4, a full 40-generation compatibility run took **0.835 s**, or **47.91 generations/s**, including history/checkpoints. Process peak RSS was **146.64 MiB**; CPU time was **0.635 s**, equivalent to 76.06% of one core over that interval. Generation transaction time totaled **0.3014 s**; checkpoint preparation **0.00175 s** overlaps storage timing and includes initialization.

The warmed NumPy match kernel took **24.623 ms/generation** and optional Numba kernel **0.325 ms**, with identical controlled results. The full evaluation path averaged **1.775 ms/generation** in the measured short run. Four independent 40-generation jobs achieved aggregate **19.41 / 37.80 / 72.18 generations/s** with **1 / 2 / 4 workers**, including startup, queue and storage overhead.

The supplied TurboWarp tournament baseline is **0.416 s/generation**. It was not rerun, and timing boundaries differ; no measured end-to-end TurboWarp speedup is claimed. `BENCHMARKS.md` documents hardware, seed overrides, warm-up, exclusions, bottlenecks and all measured values from `benchmark_results.json`.

## Persistence, endurance and recovery

| Validation | Result |
|---|---|
| 40-generation compatibility | Passed; 4,000 fitness rows and 3,300 immutable identities |
| 200-generation stability | Completed in 4.172 s |
| Uninterrupted 1,000 generations | Completed in 20.665 s |
| Four-pause 1,000 generations | Completed in 20.754 s; pauses after cumulative 37, 100, 201, 400 generations |
| Browser 1,000 generations | Completed; pause/restart/resume preserved exact trajectory |
| Four concurrent fixed-seed runs | Genome and complete fitness history identical to direct reference |
| Worker interruption | SIGKILL detected, bounded retry resumed latest committed state |
| Commit failures | Injected errors before checkpoint/commit rolled back and resumed without duplicate identities/snapshots |
| Integrity | SQLite integrity `ok`, no foreign-key violations, schema 2 |
| Historical integration | Experiment 8 world A generation 999 referenced read-only and used for 2,520 ordered competitive matches |

Both long scripted runs and browser experiment `ed17e6addec9` share:

- Genome/metadata SHA-256: `4e4aff73ca4bb4835c553b0b1360ceab05c17f1ac76792fcfbf61c6abc6cac49`
- Fitness-history SHA-256: `eb303000e473f04376d03b8ceb463cc2ce6fb161b84476a9f21885c22783dfac`

Timings are excluded from those digests. The uninterrupted long run's peak RSS changed from 147.86 to 149.28 MiB and first/last 50-generation average compute time from 12.476 to 12.402 ms. This is bounded endurance evidence, not a claim about indefinite operation. See `acceptance_results.json`, `release_audit.json` and `scripts/validate_release.py`.

## Dashboard acceptance evidence

The browser created **Acceptance 1000**, compatibility mode, seed 20261011, 100 networks, 1,000 generations, bot weight 0.25. Start/live statistics, pause at 364, server restart/history recovery, resume and completion were observed. The worker scheduler survived the web-server restart.

Inspection of final-generation champion **#79950** displayed parent **#79787**, source birth 998, first population 999, 18 actual mutations, all 40 decisions, weights/biases, descendants and historical fitness. The zero input produced `[-0.01352023107411035, 0.06105022467556531, 1.068481441043417]`. Ancestry traversal worked; parent/child distance was **0.04001083 RMS**, with **18 differing parameters**.

The tournament lab selected four saved networks, blank plus 27 full histories, two repeats, and cycle/uniform/reactive independent opponents. It completed **672 ordered competitive matches**. The stored result survived another server restart, and its **4,594-byte JSON export** was downloaded through the browser and parsed successfully (8 independent opponent trial records). API tests additionally exercise every experiment export format and gzip contents. The release workspace stores the measured benchmark report for its benchmark view.

Desktop and 390×844 viewport layouts were inspected; the narrow layout fits the page width and provides scrolling navigation/tables. No browser console errors were observed during the final check. `docs/dashboard-release.png` shows the completed run. The detailed usage guide is `DASHBOARD_GUIDE.md`.

## Final preservation and packaging audit

`historical_manifest.json` covers 110 original Engine v1/Experiment 8 files. Their bytes match the pre-development hashes. Early Python/SQLite read checks created a new Python cache and empty SQLite sidecars; those generated extras were removed, and immutable read-only access plus no-bytecode test execution prevents their recurrence. Existing original caches were retained. No original file was relocated, overwritten or migrated.

Runtime SQLite databases and experimental outputs are excluded from Git. The standalone `engineV2` Git history preserves implementation checkpoints. The distributable wheel is in `dist/`; runtime dependencies and dashboard assets are bundled/declared, and no checkout-relative imports are required in production.

## Known limitations

- Live TurboWarp runtime execution and a controlled end-to-end TurboWarp rerun were not performed. Compatibility evidence is source-level and differential, with explicitly documented numerical/RNG limits.
- Debian/Linux is the verified target. Windows/macOS scheduling and arbitrary future dependency combinations are unverified.
- Recovery is at generation boundaries. There is no mid-match restore or automatic repair/fallback of a corrupt checkpoint.
- History consumes disk space; full genome retention is intentional. Reduced history stride omits detailed intermediate snapshots. Monitor charts show the latest 1,000 points; full statistics are available by API/export. Ancestry, descendant lists and inspector history are bounded per request.
- Experiment 8 references depend on an unchanged, reachable source file. Actively written SQLite sources with nonempty WAL are rejected; freeze/checkpoint them first.
- The dashboard is single-user and loopback-only, with no remote authentication or hosted deployment. Storage roots are selected at launch. Browser-entered seeds are restricted to exactly representable integers; CLI/TOML supports the full configured 64-bit range.
- Tournament selection state is temporary in the browser; completed analyses persist. Network repeats are deterministic repetitions, not independent experimental evidence. Original bots keep their 20-throw protocol; unfamiliar bots use blank history and the requested length.
- Genetic clusters are descriptive partitions, not confirmed species. No claims of adaptation/generalization superiority are inferred from these implementation acceptance runs.
- Sexual reproduction, speciation, adaptive topology, recurrent models, lifetime learning and ecosystems are intentionally reserved for future releases.

## Installation and usage

Follow `README.md` for venv/lock-file installation and fish-compatible commands. To reopen the delivered acceptance workspace from `engineV2`:

```sh
.venv/bin/python -m evolution_engine --data runtime/release serve
```

Open <http://127.0.0.1:8765>. Use a different `--data` directory for fresh experiments. The default module/console commands support run/list/start/pause/resume/stop/cancel, manager, inspect, tournament, import, export, benchmark and integrity checks. README and `EXPERIMENT_GUIDE.md` contain copyable examples.

## Recommended v2.1 priorities

1. Extend the reproduction interface to two-parent inheritance and controlled crossover with explicit ancestry semantics.
2. Add compute-matched asexual controls and multiple independent seeds before drawing conclusions about sexual reproduction.
3. Add a live TurboWarp VM differential harness and controlled benchmark if cross-runtime verification becomes necessary.
4. Improve very-large-history querying and storage compaction/archival only with explicit preservation policies and measured workloads.

No v2.1 feature is implemented or represented as a v2.0 experimental finding.
