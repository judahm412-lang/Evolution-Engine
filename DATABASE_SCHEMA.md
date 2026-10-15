# Database schema and recovery format

Each `--data` directory owns `engine.sqlite`, its SQLite WAL sidecars, manager/worker lock files, and log files. Engine v2 never silently migrates historical Experiment 8 databases.

## Scientific tables inherited from schema 2

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

`PRAGMA user_version` is migrated transactionally: version 0 creates schema 1; schema 2 adds `analyses`; schema 3 adds separate research metadata. Databases newer than this engine are refused. Back up before installing a future release. Use SQLite's online backup API or stop all writers and copy a checkpointed database; copying only the main file while WAL writes are active is not a consistent backup. v2.0.1 adds coordinated deletion; rollback to an archived checkpoint remains unavailable through the dashboard.

Imports from Experiment 8 require a closed, immutable source database and use read-only immutable connections, preventing source-side WAL/cache files. Source path/world and fingerprints are retained; moving that source requires an explicit re-import. JSON/CSV exports are portable research artifacts, not complete recovery backups. JSON population exports include lineage metadata, parameters, and available fitness; gzip is optional. Statistics CSV includes aggregate fields; structured fields are represented within cells.

## Schema version 3: research metadata

| Table | Purpose |
|---|---|
| notes | One journal JSON document per experiment; separate timestamps |
| tags / experiment_tags | Tag vocabulary and experiment memberships |
| research_groups | Optional project name per experiment |
| repetitions | Source experiment ID and same/fresh seed provenance |
| bookmarks | Named, typed references with notes and tags |
| baskets | Ordered namespace-qualified entrants, including a persistent draft |
| milestones | Generation, detector kind/value/provenance, review state and notes |
| storage_estimates | Cached logical payload estimates with generation and timestamp |
| storage_measurements | Last 1,000 workspace/disk measurements |
| backups | Unique archive name, manifest, archive checksum and verification date |
| jobs | Durable queue, progress, request/result, error and timestamps |

The migration is forward-only, idempotent and transactional. Unknown future versions fail. Metadata edits never rewrite scientific config, genes, fingerprints or RNG state. Supporting indexes cover search/status/date, tags, bookmarks, milestones, events and pending jobs. Repetition source IDs deliberately survive deletion of their source as provenance text. Analysis JSON references are marked `source_deleted`; baskets report unavailable entrants. Explicit dependent-analysis deletion also removes their tournament bookmarks.

Checkpoint format remains 1. New checkpoints identify `scientific_engine=fixed-feedforward-2.0`; application release is informational. Legacy format-1 checkpoints without that identifier are accepted only with application version `2.0.0`. Checksums, namespace, population, configuration and RNG validation remain mandatory. Unknown science engines and formats fail.

Logical storage uses SQL `LENGTH(genes)` and stored JSON lengths plus documented row-overhead estimates. It excludes indexes, annotation payloads and fragmentation; physical-minus-logical is only an accounting remainder. Measurements may become stale while runs advance. Deletion frees reusable pages; coordinated WAL checkpoint/VACUUM physically compacts the file and checks integrity and foreign keys afterward.
