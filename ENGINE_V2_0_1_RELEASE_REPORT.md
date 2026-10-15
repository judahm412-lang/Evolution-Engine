# Evolution Engine v2.0.1 release report

Validation completed 2026-10-15. This patch adds a local research laboratory to the v2.0 scientific engine. Evidence files in this checkout record the actual tests and measurements; browser experiments and scale fixtures lived only in disposable `runtime/v201-*` workspaces.

## 1. Executive summary

The release provides safer storage operations, recoverable research organization, bounded historical visualizations and offline reports. Existing evolution, RPS evaluation, selection, mutation and RNG pathways remain unchanged. An actual v2.0.0 wheel and the patch produced identical 1,000-generation trajectories, including a real v2.0.0 checkpoint resumed by v2.0.1 after metadata edits. This is compatibility evidence, not a new scientific finding.

## 2. Implemented feature inventory

| Area | Delivered behavior |
|---|---|
| Storage | Per-experiment logical estimates with physical totals; disk warnings/critical pause; capacity-checked exclusive SQLite reclaim |
| Recovery | Consistent online ZIP backup, strict manifest/integrity/dependency verification, new-directory restore, explicit interrupted jobs |
| Safety | Atomic bulk deletion, source-reference markers, backup age/checksum checks, cross-process scheduler/worker/maintenance gate |
| Organization | Separate notes, tags/counts, groups, bounded search/config comparison, exact-seed repeat, named persistent baskets, bulk tags/groups, three new-run retention presets |
| Genetics | Paged parent-edge graph with missing ancestors, expansion, keyboard/pan/zoom, and exact same-architecture weight/bias comparison |
| History | Recorded replay, bounded extrema-preserving charts, bookmarks, checkpoint/event timeline, descriptive milestones with human review |
| Output | Escaped standalone offline HTML report with provenance, charts and optional large details; downloadable job artifacts |
| Dashboard | Integrated local pages, responsive layout, long-job progress, resource readings and truthful unavailable-data states |

## 3. Git provenance

Development branch: `develop/v2.0.1`, based on stable v2.0.0 commit `143d300547b94dd21a01527ec81dfa004f836a1e`. Coherent implementation commits: `bf3d955`, `934d152`, `c0d2e16`, `dd781be`; final validation/documentation commit is this report's release commit. The v2.0.0 tag and the separate `develop/v2.1` branch were preserved. The final `v2.0.1` tag points to the validated release commit on `master` after the release gate.

## 4. Database migration

Opening schema 2 applies a transactional, forward-only schema 3 migration for notes, tags, groups, repetition provenance, bookmarks, baskets, milestones, storage readings, backups and jobs. Original scientific tables are not rewritten. A real original-version SQLite fixture, failure rollback, idempotent reopening, future-schema rejection, integrity and foreign-key checks pass. v2.0.0 must use a separate pre-upgrade backup after migration; it does not read schema 3. See `DATABASE_SCHEMA.md`.

## 5. Scientific preservation

The scientific modules have no diff against v2.0.0. All 110 files in the original historical manifest still match their SHA-256 values (`v2_0_1_preservation_audit.json`). The three 1,000-generation paths in `v2_0_1_scientific_validation.json` share genome digest `d0808973e5d40c3cf584a80ab913ebc2005e9f300c47733de867a208d8cdf8bf` and fitness digest `0a15acdad5ac5702c3b50f898fb576dddea1e4f1f070c2acdc5e953f4cf3821b`. Comparisons cover every genome identity, parameter byte, mutation record, fingerprint, per-network fitness/count row and final three PCG64 states. Timing, timestamps, IDs and application metadata are excluded. Original RPS source-compatibility tests remain part of the passing suite; a live TurboWarp VM was not run for this patch.

## 6. Checkpoint upgrade

An unmodified v2.0.0 wheel completed 364 generations and wrote its normal checksummed checkpoint. v2.0.1 migrated that workspace, edited notes and tags, then resumed to generation 1,000. It exactly matched both the stable uninterrupted run and patch uninterrupted run at the boundaries above. New checkpoints identify the compatible scientific engine explicitly; legacy v2.0.0 format-1 checkpoints are accepted only with the known v2.0.0 engine version and valid checksum. The original fixture also exercises the maximum supported signed 64-bit seed. `scripts/validate_patch_science.py` reproduces the long comparison in a fresh destination.

## 7. Automated tests and package

Final complete suite: **92 passed in 16.51 seconds**, with a TestClient deprecation warning and an intentionally duplicate ZIP-entry warning in a rejection test. Five preserved Experiment 8 tests also passed. Tests cover migration and rollback, real scheduler/worker/deletion races, live-WAL backup/restore, injected transaction failures, archive attacks, disk pause, job hard-exit recovery, bounded queries, API security and streamed request limits. The v2.0.1 wheel was installed under `/tmp` and imported outside the source checkout; a three-generation maximum-seed run, bundled assets, graph API, backup/verify/restore and RNG equality passed. The final wheel completed the 40-generation target example outside the checkout. A release-candidate wheel with the same Python code verified and restored its archive into a new directory and passed SQLite integrity/foreign-key checks; the final wheel differs only in chart-axis JavaScript and was separately inspected for that bundled asset. Wheel SHA-256: `c7bb5951347072015c02ce1875d49f3b7a389f352c9e0a41629d8e302f9edf91` (`v2_0_1_wheel_validation.json`).

## 8. Backup and restore validation

The online snapshot includes committed WAL data while a real worker is active. Restore validates ZIP structure, entry limits, SHA-256, SQLite integrity/foreign keys, checkpoints and external dependencies before publishing into a nonexistent directory. It pauses previously active/queued experiments and reports interrupted jobs. A browser-created 18.57 MiB archive was verified and downloaded; downloaded SHA-256 matched the workspace archive: `4bf57a9f36ead65fb3657ae9473ac83dd0adc0da78fd01bb35c338355d3cc1db`. Historical external files are referenced and hash checked, not copied.

## 9. Destructive-operation safety

Deletion and VACUUM require an exclusive workspace gate; all workers must be inactive, including unrelated workers. Scheduler launch holds a shared gate through spawn and each child rechecks existence/status after acquiring its lifetime gate. Actual-process tests prove rejection while a worker is active, safe deletion between launch and child acquisition, and preservation of unrelated experiments. Failed deletion rolls back atomically. Browser deletion previews identity, size and dependencies, disables a protected run, and requires explicit ID plus an additional acknowledgment without a recent verified backup. Reclaim separately checks free capacity and database integrity. Only disposable test workspaces were used; user research data were not deletion targets.

## 10. Browser acceptance

The local dashboard was exercised in the in-app browser: storage measurements and archive workflow; protected delete dialog; exact maximum seed and fresh-seed repeat; notes, tag counts and bulk tags; graph navigation/zoom/selection; exact genetic differences; replay; chart zoom/pan/export; persistent named basket across server restart; bookmark and milestone review; timeline navigation; resource view; and HTML report download. The reviewed completion milestone persisted after reload. Checkpoint 100 links to recorded generation 99, since checkpoint generation is the next evaluation. The downloaded report was 9,108 bytes and escaped a literal script-like note. Final browser console checks found no errors. Desktop and 390×844 resource/delete layouts were inspected; the narrow body fit 390 pixels. Screenshots are in `docs/screenshots/v2.0.1/`.

## 11. Performance measurements

`v2_0_1_lab_benchmarks.json` records local warm sequential observations, not controlled cross-hardware comparisons. The test database contained 80,100 real genomes from a 1,000-generation run, 100,000 **synthetic aggregate history rows** and 300 synthetic metadata experiments. Median storage summary was 7.36 ms; full physical/logical refresh 3.964 s (one sample); depth-30 lineage 1.44 ms; search over 302 experiments 9.55 ms; 100k-row chart query 187.58 ms with an injected peak retained; bulk tagging 200 runs 13.01 ms; uncached resource sampling 1.14 ms; 341 MiB online backup 11.03 s, 99.72 MiB archive, process peak RSS 55.20 MiB. In a browser, the 100k-row chart bounded to 983 plotted observations loaded in 280.30 ms and took 10.20 ms for script/DOM/layout on one observation; GPU paint is outside that measure. The stable-wheel 1,000-generation run took 23.614 s and patch run 22.509 s in separate sequential observations. No speedup is claimed.

## 12. Known limits

This is a single-user loopback-only Debian/Linux application. Advisory coordination assumes cooperating engine processes; stop older v2.0.0 processes before upgrade. Every worker pauses for exclusive maintenance. External immutable historical dependencies must remain reachable and unchanged. Logical deletion does not immediately return physical SQLite space; VACUUM is explicit and requires capacity. Jobs interrupted by hard exit are surfaced for manual review/retry; partial output files may need inspection. Graphs cap loaded nodes at 500, depth at 30 and page at 200; charts cap plotted points and preserve extrema. Replay only shows stored aggregates and any retained population, never missing detail. Genetic comparison requires matching architecture and activation sequence. Milestones describe stored measurements, not causes. Cluster membership unavailable in v2.0 records is shown as unavailable. Browser large-chart timing is one local observation.

## 13. Screenshots

- [Family tree](docs/screenshots/v2.0.1/family-tree.jpg)
- [Replay](docs/screenshots/v2.0.1/replay.jpg)
- [Saved basket](docs/screenshots/v2.0.1/basket.jpg)
- [Bookmarks](docs/screenshots/v2.0.1/bookmarks.jpg)
- [Backups](docs/screenshots/v2.0.1/backups.jpg)
- [Protected deletion at 375px](docs/screenshots/v2.0.1/mobile-delete-protection.jpg)
- [Resource monitor at 375px](docs/screenshots/v2.0.1/mobile-resources.jpg)
- [100k-row bounded chart](docs/screenshots/v2.0.1/large-chart.jpg)

## 14. Upgrade and Debian commands

Follow `UPGRADING_V2_0_1.md` to stop old workers/manager, preserve a pre-upgrade SQLite snapshot, migrate and resume. The following commands use fish-compatible syntax and assume the repository checkout is current:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m pip install --no-deps .
.venv/bin/python -m pytest -q
.venv/bin/python -m evolution_engine --data /absolute/path/my-lab check
.venv/bin/python -m evolution_engine --data /absolute/path/my-lab serve
.venv/bin/python -m evolution_engine --data /absolute/path/my-lab backup
.venv/bin/python -m evolution_engine verify-backup /absolute/path/my-lab/backups/ARCHIVE.zip
.venv/bin/python -m evolution_engine restore /absolute/path/my-lab/backups/ARCHIVE.zip --destination /absolute/path/restored-lab
```

Open `http://127.0.0.1:8765` after `serve`. `README.md`, `DASHBOARD_GUIDE.md` and `EXPERIMENT_GUIDE.md` cover operation. Archive/report downloads do not substitute for preserving external historical dependencies.

## 15. v2.1 priorities

Add two-parent reproduction with explicit inheritance and provenance; compare it against asexual and compute-matched baselines across independent seeds; use held-out tasks and correction for multiple comparisons before research claims. Extend live TurboWarp differential verification and scale measurements if needed. No v2.1 mechanism or empirical superiority claim is part of v2.0.1.
