# Delivery roadmap

| Phase | Status | Evidence |
|---|---|---|
| 0 — Extract and validate existing components | Complete | Source audit, frozen Experiment 8 tests, controlled inference/match differentials, original-file SHA-256 manifest |
| 1 — Complete evolution | Complete | Immutable networks, source-compatible RPS, general strategies, continuous target, 40-generation test |
| 2 — Persistence and reproducibility | Complete | Atomic generations/checkpoints, migrations, imports/exports, exact resumed histories, injected transaction failures |
| 3 — Performance and parallel experiments | Complete | Reference/compiled equality, 1/2/4-worker measurements, bounded scheduler retries, worker interruption, batch limits, 200/1,000-generation endurance |
| 4 — Local dashboard integration | Complete | Browser-created 1,000-generation run, restart/resume, inspection/genetics, saved tournament/export, responsive review and API integration tests |
| Release gate | Complete within documented scope | Tested wheel installation, 49-test suite, five original tests, matching long-run hashes, preservation audit, release report and required documentation |

Authoritative evidence and scientific/platform limitations are in `ENGINE_V2_RELEASE_REPORT.md`. The source-based compatibility claim does not include a live TurboWarp JavaScript execution or a controlled cross-runtime speedup measurement.

Future v2.1 priorities: two-parent reproduction/crossover interfaces and controlled research with asexual baselines. Later versions may address speciation, topology and lifetime learning. None is part of the delivered v2.0 scope.
