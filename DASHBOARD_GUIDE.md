# Dashboard guide

Start with `python -m evolution_engine --data /absolute/path/my-lab serve`. Open <http://127.0.0.1:8765>. The API's machine-readable request/response schemas are at `/openapi.json`; mutations require `X-Evolution-Client: dashboard` and a matching origin. This is a single-user loopback service with no accounts, telemetry, external CDN, or arbitrary file/shell access. Remote sharing/authentication is outside v2.0.

## Workflow

1. **New experiment:** select Original Engine v1 or workspace defaults, name the run, choose generations, bot weight, seed and checkpoint settings. Compatibility locks source-defining controls. General mode exposes architecture, population, selection, mutation and environment. Advanced JSON overrides support every validated setting. Four Worlds creates a bot-weight sweep; replicas and sweeps are queued automatically. Single experiments are created before Start.
2. **Live monitor:** Start, Pause, Resume, Stop, and Extend run are backend operations. Pauses/stops occur at committed generation boundaries. Watch completed generations, active elapsed time, throughput/ETA, current worker, checkpoint, fitness components, diversity, distributions, mutation counts and descriptive clusters. SSE updates are throttled; stored statistics remain authoritative.
3. **Population history:** select a zero-based generation to see ranked networks and fitness components. Open a network or add the top ten to the tournament basket. For histories sampled with a stride, choose a retained generation.
4. **Network inspector:** inspect architecture, source birth label, first population, parent, descendants, actual mutations, layer weights/biases and historical fitness. RPS shows all 40 reachable decisions. Calculate outputs for a comma-separated input vector. Add individual networks to the tournament basket.
5. **Genetics:** choose a population to see colored clusters and founder ancestry. Trace a network's parent chain with a bounded depth, or compare two IDs by RMS distance and changed parameter count. Change generation to inspect historical lineage changes. Continue deep trees from displayed ancestors.
6. **Tournament lab:** add saved populations or historical champions, choose rounds, repeats, starting histories, independent opponents and seed, then run. Inspect ranking, matrix and opponent trials. Export JSON or reload a saved tournament. Basket selection is temporary browser state; completed results persist in SQLite.
7. **Configuration & exports:** inspect the resolved config, checkpoints and event log. Download config, statistics, summary, population, champion or analysis. CLI/API also offer gzip. These exports do not replace a database backup.
8. **Experiments:** filter by name/config text, status, environment, creation date, minimum generations or observed fitness, and page through history. **Compare runs** displays stored fitness curves for selected histories.
9. **Settings:** set global worker count, scheduler poll interval, refresh interval, log verbosity and default experiment JSON (including retention/performance settings). Choose a storage location with launch `--data`; changing it through an arbitrary browser path is intentionally unavailable.
10. **Benchmarks:** displays persisted measurements from the CLI benchmark command, including per-component and worker scaling data. The release workspace includes the actual measured release artifact.

Closing the tab does not stop experiments. Stopping/restarting the web server does not reset history or checkpoint state. If the whole machine/app terminates the scheduler, launch `serve` with the same data root to recover interrupted workers. Failure messages are retained and retries are bounded. Stop or Pause a run explicitly when execution should cease.

## Data and accessibility boundaries

Controls use labels and native keyboard navigation. Charts are SVG with accessible metric names; underlying numbers are available in history tables and exports. Tables scroll horizontally at narrow widths; the navigation becomes a top section. Monitor charts show at most the latest 1,000 points. Experiment/population API pages cap at 200 items and ancestry at 200 nodes; source databases are never sent wholesale to the browser. Some research queries (e.g. full ancestry aggregation and large all-pairs analyses) can still be expensive for unusually large populations.

The browser stores a root seed as a JavaScript number; the form supports exactly representable integers through 2^53-1. Use TOML/CLI for larger 64-bit seeds and preserve the original config export. Existing larger seeds are displayed as text for reference; avoid editing them through browser numeric controls.
