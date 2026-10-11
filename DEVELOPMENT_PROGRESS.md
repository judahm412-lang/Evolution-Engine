# Engine v2 development progress

2026-10-11: Phase 0 in progress. Authoritative engineV1.sb3 and all Experiment 8 modules located. Historical research is read-only. Root .git is a managed empty read-only directory; Engine v2 will maintain its own Git repository.

Source audit identifies Experiment 8's scalar inference, 40-state policy encoding, simultaneous matches, original bots, and vectorized tournaments as reusable. Source-level checks of selection, mutation, scheduling, and archival metadata are underway. System Python lacks dependencies; creating an isolated venv.

Remaining: all implementation phases, compatibility fixtures, persistence/recovery, scheduler, dashboard, endurance and acceptance tests, benchmarks, final audit. No release claim yet.

Phase 0 and Phase 1 implementation checkpoint: all original Experiment 8 unit tests passed (5); new core and persistence suite passed (32 total, 1.10 s). A separately persisted 100-network/40-generation compatibility experiment completed in 0.882 s on this host (runtime/phase1, id 237bf4468614). This is a local elapsed observation, not yet a controlled benchmark. Implemented immutable networks, configurable activations/layers, source-ordered RPS policy cache, optional compiled matches, exact selection/reproduction/mutation order, independent target environment, strict TOML/JSON config, normalized SQLite history and atomic checkpoints, imports/exports, and initial process manager. Fixed-seed pause/resume equivalence and injected transaction failure recovery pass. Full source-VM differential verification and measured performance report are pending.

Phase 2: recovery/import tests pass, including read-only Experiment 8 references and schema migration. Scheduler needs process integration tests. Phase 3/4 next: scheduler failure tests, benchmarks, dashboard and browser acceptance, 200/1000-generation endurance, complete documentation and final audit. Historical source manifest is saved; no historical file has been intentionally changed.
