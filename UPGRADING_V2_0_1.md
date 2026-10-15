# Upgrade from Evolution Engine v2.0.0

The upgrade preserves existing scientific config, immutable genomes, IDs, ancestry, fitness and compatible checkpoints. Opening a workspace applies a transactional schema 2 → 3 metadata migration. Original v2.0.0 checkpoints retain their checksum and resume under the explicit compatible scientific engine. The old application rejects schema 3: rollback means running the old application against a **separate pre-upgrade backup**, not downgrading a migrated database.

## 1. Quiesce the old installation

Pause every running experiment and wait until all show `paused`, `completed` or another inactive state. Pause queued runs too. Stop the old web server and its detached manager after workers have reached safe boundaries. Closing the browser or terminating only the web server does **not** stop the manager. Inspect local process arguments and target only processes whose `--data` path is this workspace; do not issue blanket process-kill commands. Never run v2.0.0 and v2.0.1 workers against the same workspace.

## 2. Preserve a pre-upgrade SQLite snapshot

v2.0.0 has no complete backup CLI. Before installing/opening v2.0.1, save this small script as `preupgrade_backup.py` outside the workspace:

```python
from pathlib import Path
import sqlite3
import sys
source, destination = map(Path, sys.argv[1:])
if destination.exists():
    raise SystemExit('Choose a new destination directory')
destination.mkdir(parents=True)
with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as src:
    with sqlite3.connect(destination / 'engine.sqlite') as dst:
        src.backup(dst)
        assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not dst.execute('PRAGMA foreign_key_check').fetchall()
print(destination.resolve())
```

Run with absolute paths (these commands work in fish):

```sh
python3 preupgrade_backup.py /absolute/path/my-lab/engine.sqlite /absolute/path/pre-v201-backup
```

This uses SQLite's online backup API, including committed WAL data. Keep external immutable Experiment 8 source databases at their original paths and independently preserve them; neither this script nor the v2.0.1 archive duplicates those files. Keep the old installation/wheel available if you need to inspect the old snapshot.

## 3. Install and open the upgraded application

From the v2.0.1 checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m pip install --no-deps .
.venv/bin/python -m evolution_engine --data /absolute/path/my-lab check
.venv/bin/python -m evolution_engine --data /absolute/path/my-lab serve
```

For a wheel, replace the install command with `.venv/bin/python -m pip install --no-deps dist/evolution_engine-2.0.1-py3-none-any.whl`. The first `check` opens/migrates the workspace. A failed migration rolls back; do not manually edit `PRAGMA user_version`. Unknown newer schemas and incompatible scientific engines are rejected.

Open `http://127.0.0.1:8765`, inspect the saved experiments, and resume explicitly. Notes/tags/bookmarks are separate metadata and do not change evolutionary RNG draws. Research reports/CSV exports are useful artifacts but do not replace recovery backups.

## 4. Create and validate regular backups

```sh
.venv/bin/python -m evolution_engine --data /absolute/path/my-lab backup
.venv/bin/python -m evolution_engine verify-backup /absolute/path/my-lab/backups/ARCHIVE.zip
.venv/bin/python -m evolution_engine restore /absolute/path/my-lab/backups/ARCHIVE.zip --destination /absolute/path/restored-lab
.venv/bin/python -m evolution_engine --data /absolute/path/restored-lab check
```

The archive contains `engine.sqlite` and a manifest with SHA-256/size/schema/application version and external dependencies. Every archive has a new name. Verification checks archive structure/limits, checksum, integrity, foreign keys, checkpoint namespace/config/population/RNG and latest committed progress. Restore validates before publishing into a new directory; it refuses to overwrite anything. Active/queued states become paused and interrupted jobs remain explicitly interrupted. Source archive bytes are not changed.

If a historical source is missing or changed, verification reports the problem. Restore can preserve the referencing research metadata, but gene-dependent operations remain unavailable until the original immutable dependency is restored at its recorded path. Do not replace it with unrelated data.

## Maintenance and recovery

- Backup, annotations and read-only analysis are allowed during runs. Online backup uses a consistent database snapshot.
- Deletion and Reclaim Storage require all workers paused, including unrelated workers. The scheduler, worker startup and all engine writes share a coordinated maintenance lock.
- Delete previews counts, identities, dependencies and estimated logical bytes. A verified archive within 24 hours is highlighted and its checksum is rechecked. Otherwise an extra no-backup acknowledgment is mandatory.
- Deletion does not remove historical source files or necessarily shrink the database. Reclaim Storage separately checkpoints WAL, checks capacity, runs VACUUM and validates integrity. Close long-lived external database readers if they prevent WAL checkpointing.
- Low disk capacity blocks new scheduling and then pauses active workers at safe generation boundaries. Free capacity before resuming.
- A hard-interrupted background job is marked `interrupted`, never assumed complete or automatically retried. Inspect any partial files, then retry explicitly. Failed deletion rolls back its transaction; failed VACUUM leaves SQLite recovery to its transaction machinery.
