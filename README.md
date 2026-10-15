# Evolution Engine v2.0.1

A local Python laboratory for reproducible neural-network evolution, saved-genome research, and concurrent experiments. Engine v1 and Experiment 8 remain separate, preserved research inputs.

## Install on Debian Linux

Python 3.11+ is required; the release was tested on Debian 13 with Python 3.13.5. From this directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m pip install --no-deps -e .
```

The lock file records the tested environment, including optional Numba acceleration and test tools. For a minimal installation use `.venv/bin/python -m pip install .`; to select extras use `'.[accelerate,test]'`. NumPy is the fallback when Numba is unavailable. Install Debian's `python3-venv` package if your Python installation lacks venv support.

Commands use explicit interpreter paths and work in Bash and fish without activation. Optional activation: `source .venv/bin/activate` in Bash or `source .venv/bin/activate.fish` in fish.

## Launch the dashboard

```sh
.venv/bin/python -m evolution_engine --data runtime/release serve
```

Open <http://127.0.0.1:8765>. This directory already contains the completed browser acceptance experiment. To use a fresh workspace, replace `runtime/release` with `runtime/my-lab`. `--data` is a global option: place it **before** the command. Without it the default is `~/.local/share/evolution-engine`, or `EVOLUTION_DATA` if set. Relative data paths resolve from your current directory; absolute paths work from anywhere.

The server launches a separate scheduler. Closing a browser or stopping the web server leaves workers running. Relaunch with the same data directory to recover the UI. Use experiment Pause/Stop controls or CLI commands to stop execution deliberately. Serve only binds loopback addresses.

## Command-line quick start

```sh
.venv/bin/python -m evolution_engine --data runtime/my-lab run examples/compatibility.toml
.venv/bin/python -m evolution_engine --data runtime/my-lab list
.venv/bin/python -m evolution_engine --data runtime/my-lab run examples/target.toml --enqueue
.venv/bin/python -m evolution_engine --data runtime/my-lab run examples/compatibility.toml --sweep 0 0.1 0.25 1
.venv/bin/python -m evolution_engine --data runtime/my-lab pause EXPERIMENT_ID
.venv/bin/python -m evolution_engine --data runtime/my-lab resume EXPERIMENT_ID
.venv/bin/python -m evolution_engine --data runtime/my-lab resume EXPERIMENT_ID --generations 2000
.venv/bin/python -m evolution_engine --data runtime/my-lab inspect EXPERIMENT_ID 1
.venv/bin/python -m evolution_engine --data runtime/my-lab tournament EXPERIMENT_ID --generation 39 --full-starts
.venv/bin/python -m evolution_engine --data runtime/my-lab export EXPERIMENT_ID --kind statistics --output statistics.csv
.venv/bin/python -m evolution_engine --data runtime/my-lab export EXPERIMENT_ID --kind population --output population.json.gz --compress
.venv/bin/python -m evolution_engine --data runtime/my-lab check
```

Replace `EXPERIMENT_ID` with an ID returned by `run` or `list`. Direct `run` blocks until completion. `--enqueue`, replicates, and sweeps launch scheduler jobs. Commands also have the installed `evolution-engine` console entry point. `stop`/`cancel` preserve history and stop at a generation boundary; they do not delete data.

## Import historical data

```sh
.venv/bin/python -m evolution_engine --data runtime/my-lab import-e8 ../experiment_08/results/networks.sqlite --world A --generations 0 999
.venv/bin/python -m evolution_engine --data runtime/my-lab import-archive /absolute/path/archive.zip --name 'Historical world' --prefix WORLD_FILE_PREFIX
```

Experiment 8 imports reference a closed, immutable SQLite file. Keep that source at its recorded location; genes are verified on access. Raw JSON/TXT, gzip exports, and ZIP chunks are supported. Imports are read-only research cohorts and cannot be resumed as simulated histories. See [EXPERIMENT_GUIDE.md](EXPERIMENT_GUIDE.md) for formats and warnings.

## Verification and benchmarks

```sh
env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s ../experiment_08/tests -q
.venv/bin/python -m evolution_engine --data runtime/benchmarks-new benchmark --generations 40 --workers 1 2 4 --output benchmark-new.json
.venv/bin/python scripts/validate_release.py --data runtime/endurance-new --output acceptance-new.json
.venv/bin/python -m pip wheel --no-deps . --wheel-dir dist
```

The original SB3 and Experiment 8 are needed only for differential tests/imports, not to run the installed engine. Integration tests use local processes and loopback networking. A restrictive sandbox may block those tests.

Read [ENGINE_V2_0_1_RELEASE_REPORT.md](ENGINE_V2_0_1_RELEASE_REPORT.md) for the patch release, and [ENGINE_V2_RELEASE_REPORT.md](ENGINE_V2_RELEASE_REPORT.md) for evidence and limitations, [COMPATIBILITY.md](COMPATIBILITY.md) for the precise equivalence claim, [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md) for the UI, and [ARCHITECTURE.md](ARCHITECTURE.md), [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md), [BENCHMARKS.md](BENCHMARKS.md) for technical details.

## Research laboratory tools in v2.0.1

Storage Manager distinguishes physical SQLite/WAL files from cached per-experiment logical estimates. Backups create verified online snapshots; restore always uses a new directory. Deletion previews identities, dependencies and backup status, and requires exclusive maintenance. Family Trees, genetic comparisons, journals, tags, exact-seed repeats, persistent tournament baskets, configuration comparisons, replay, bookmarks, milestones, timelines and offline reports work entirely locally.

See [UPGRADING_V2_0_1.md](UPGRADING_V2_0_1.md) **before opening an existing workspace**. Schema 2 upgrades transactionally to schema 3; original configurations, genomes and scientific checkpoints are preserved. The older application cannot open schema 3, so preserve a pre-upgrade backup. Never run old and new workers on the same workspace.

```sh
.venv/bin/python -m evolution_engine --data runtime/my-lab backup
.venv/bin/python -m evolution_engine verify-backup /absolute/path/BACKUP.zip
.venv/bin/python -m evolution_engine restore /absolute/path/BACKUP.zip --destination /absolute/path/new-lab
```

All workers must be paused before deletion or Reclaim Storage. Ordinary backup, notes, tags, browsing and resource monitoring may run while experiments are active. Background operation failures are visible and never reported as successful completion.
