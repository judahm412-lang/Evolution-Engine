# Database schema and recovery format

Each `--data` directory owns `engine.sqlite`, its SQLite WAL sidecars, manager/worker lock files, and log files. Engine v2 never silently migrates historical Experiment 8 databases.

## Schema version 2

| Table | Identity / purpose |
|---|---|
| experiments | `id` text primary key; resolved config JSON, state, completed generation count, timestamps, PID, error, retries, priority, engine version and import/batch provenance |
| genomes | `(experiment_id,id)` primary key; architecture, activations, immutable float64 gene BLOB, metadata JSON, fingerprint, optional external reference |
| parents | `(experiment_id,child_id,parent_id)` primary key; index on parent ID for descendants; prepared for multiple parents in a future version |
| populations | `(experiment_id,generation,slot)` primary key and unique genome per snapshot; ordered identity references, not repeated gene arrays |
| fitness | `(experiment_id,generation,network_id)` primary key; total, self-play, raw bot, match and outcome counts, environment components JSON |
| generations | `(experiment_id,generation)` primary key; aggregate statistics JSON, including real measured compute timings |
| checkpoints | `(experiment_id,generation)` primary key; state JSON, SHA-256, timestamp, archive flag |
| events | Integer ID, experiment ID, timestamp, kind and message/traceback |
| settings | JSON values keyed by setting name |
| benchmarks | Integer ID, timestamp and measured result JSON |
| analyses | Integer ID, timestamp, kind and saved tournament JSON |

Foreign keys protect experiment/genome references. Parent IDs intentionally need not resolve for incomplete raw historical archives; missing ancestors are surfaced rather than fabricated. Indexes support ancestry and per-network fitness lookups. A genome fingerprint covers architecture, activations and parameter bytes. Stored gene BLOBs use little-endian float64 on the supported target platform. Mutation metadata stores zero-based parameter indices, before/after values, attempted mutation count, parent, birth label, and first evaluated generation.

## Transactions and checkpoints

WAL permits readers during short write transactions. Connections use foreign keys and a 30-second busy timeout; writes use `BEGIN IMMEDIATE`. One transaction inserts new genomes, the evaluated snapshot/fitness (subject to history stride), all generation statistics, the next population and all RNG states, then advances experiment progress. Any exception before commit rolls everything back. A per-experiment advisory lock prevents duplicate workers. The next generation must match the stored progress counter.

Checkpoint format 1 stores engine/environment versions, experiment ID, next generation, ordered population IDs, next identity, resolved config, independent initialization/evaluation/reproduction PCG64 states, environment-state field, and pending operation. Current environments finish episodes inside each generation and have no outstanding episode state. Genome data is referenced, not duplicated.

Every generation has an atomic latest checkpoint. `checkpoint_frequency` controls **additional retained history**, not crash-safety frequency. `checkpoint_retention` caps archived checkpoints; the current checkpoint is retained even between archive boundaries. `history_stride` controls population and per-network fitness snapshots; final snapshot and all aggregate statistics are retained. All immutable genomes/ancestry are retained. There is no automatic research-data deletion.

Restoration verifies checksum, format, versions, namespace, population uniqueness/dimensions, next ID and configuration. Only the requested generation limit may change on extension. Corruption is an error, not a silent fallback. A crash before commit restarts that generation using its saved RNG state; after commit it resumes at the next generation.

## Migrations and backups

`PRAGMA user_version` is migrated transactionally: version 0 creates schema 1; schema 2 adds `analyses`. Databases newer than this engine are refused. Back up before installing a future release. Use SQLite's online backup API or stop all writers and copy a checkpointed database; copying only the main file while WAL writes are active is not a consistent backup. Deletion and automatic rollback to archived checkpoints are not exposed as dashboard actions.

Imports from Experiment 8 require a closed, immutable source database and use read-only immutable connections, preventing source-side WAL/cache files. Source path/world and fingerprints are retained; moving that source requires an explicit re-import. JSON/CSV exports are portable research artifacts, not complete recovery backups. JSON population exports include lineage metadata, parameters, and available fitness; gzip is optional. Statistics CSV includes aggregate fields; structured fields are represented within cells.
