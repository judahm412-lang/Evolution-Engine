# Experiment guide

## Configuration

TOML and JSON load into the same strict Pydantic configuration. Unknown keys, invalid dimensions, non-finite values, and incompatible compatibility-mode settings are errors. `examples/compatibility.toml` and `examples/target.toml` are runnable examples; omitted settings receive explicit defaults stored with the experiment.

| Section | Settings and meaning |
|---|---|
| Root | `name`, `description`, optional unique `experiment_id`, `mode`, `generations`, `replicates`, `seed` |
| population | `size` (2..1000); `network.layers`, one activation per non-input layer; `initialization` uniform, normal or zeros |
| evolution | `selection` top/tournament/rank; `elite_count`, `tournament_size`; asexual reproduction; uniform/Gaussian `mutation`, `probability`, `magnitude`, `mutate_weights`, `mutate_biases` |
| environment | `type` rps/target; RPS `matches`, `rounds`, `bot_rounds`, `bot_weight`, `self_weight`, `opponents`; continuous-demo `target` |
| execution | `workers` per replicate/sweep batch, `priority`, `retries`, `checkpoint_frequency`, `checkpoint_retention`, `history_stride`, `acceleration` auto/numpy/numba |
| storage | `export_compression`; `archive_policy="retain"` |

Activations are sigmoid, relu, tanh, linear and softmax. Add custom activations through `neural.register_activation` before loading configurations. General networks support multiple hidden layers and any supported output size; RPS specifically requires nine inputs, three outputs and an even population. The continuous target example has four outputs and proves evolution is environment-independent.

Top selection cycles through elites for parent choices. Tournament selection samples candidates and keeps the best; rank selection samples with linearly decreasing rank weights. Every method preserves configured elites. Mutation probability applies independently to selected weight/bias locations. Gaussian magnitude is standard deviation; uniform magnitude is the symmetric bound. A probability draw that yields no numerical change is an attempt, not an actual mutation.

## Controlled runs and parallelism

Use a fresh experiment ID for every independent history. Record the resolved config, engine version and dependency lock. Compare multiple seeds and independent opponent evaluations; evolutionary fitness is a within-population measure, not a general intelligence score.

A `replicates` count above one derives distinct seeds using NumPy SeedSequence. Batch provenance records root seed and replicate index. Sweeps keep the same replicate-seed sequence across bot weights, enabling paired comparisons. `--sweep 0 0.1 0.25 1` creates the Four Worlds style configuration series. Do not treat paired seeds as independent replications across conditions.

Concurrency operates across independent experiments, one process per experiment. The global settings limit and a batch's `execution.workers` cap both apply. The default global limit is two; CPU-library thread counts are limited to one in workers to avoid oversubscription. Priority ranges -100..100; larger values start first. Queued jobs can be paused/cancelled before startup. Scheduler locks prevent competing managers; experiment locks prevent competing writers. A crashed worker is retried up to the configured limit and failures remain in events/logs. Resume explicitly to retry a failed experiment after fixing its cause.

Direct CLI execution does not require the web server. A foreground manager is also available:

```sh
.venv/bin/python -m evolution_engine --data runtime/my-lab manager --until-idle --workers 2
```

Run this only if that workspace does not already have a scheduler. Ordinary `serve`, enqueued `run`, `start` and `resume` ensure a detached manager exists.

## History and research

Snapshot indices start at zero; completed generation count is one greater than the last evaluated snapshot. Inspect population 999 after 1,000 generations. Statistics always exist, but reduced `history_stride` deliberately omits intermediate detailed snapshots. Population history, inspector fitness, exports and analyses report only retained data. The monitor displays up to the latest 1,000 generations; the API supports paging and exports contain full statistics.

Tournaments accept saved networks from multiple experiments through the API/dashboard. CLI tournaments select one saved population. The score matrix is row-network net score against column-network. Competitive counts are ordered pairs and exclude the diagonal. Full starts means blank plus all 27 complete histories. Repeats duplicate deterministic network-versus-network results; they are not independent samples. Original bot comparisons use the original 20-throw rule at all three phases. Unfamiliar opponents use the requested throw length, blank history and explicit seed sequence; repetitions of stochastic bots are seeded trials. Opponent results are independent from the round-robin ranking and never change evolutionary fitness.

Genetic distance is RMS parameter difference. Behavioral diversity is mean pairwise policy Hamming distance for RPS. Descriptive clusters use deterministic farthest-first initialization and at most four centers. They are useful partitions, not a claim of evolved species. Founder ancestry follows parents to known roots; missing ancestors remain unknown. Ancestry requests cap at 200 nodes; continue from an ancestor ID to traverse older history.

## Historical import formats

`import-e8` accepts the preserved Experiment 8 SQLite schema (`networks`, `appearances`), a world and optional generation list. It loads metadata/ancestry, references gene arrays read-only, and reports mutation discrepancies. Close/checkpoint an actively written source before importing it. It must remain unchanged and reachable.

`import-archive` accepts TurboWarp JSON arrays in `.txt`/`.json`, ZIP members, gzip JSON, and v2 exported population JSON. Four-field elite records preserve known birth/parent metadata from earlier appearances; seven-field records carry identity, JSON weights, JSON biases, fitness, source birth label, mutation attempts and parent. ZIP members are processed in numeric chunk order. Choose `--prefix` when a ZIP contains multiple worlds; never merge their identity namespaces. `--population-size` defaults to 100 and `--start-generation` to zero. Conflicting identities/dimensions fail and roll back imported rows. Missing generations/ancestors and uncertain mutation metadata create visible warning events. Exported fitness is preserved when present. Missing component scores are null, never invented.

## Programmatic API

```python
from evolution_engine.config import Config
from evolution_engine.storage import Store
from evolution_engine.runner import run_experiment
from evolution_engine.research import tournament, inspect, population_analysis

store = Store('/absolute/path/my-lab')
experiment_id = store.create(Config(generations=40, seed=42))
run_experiment(store.root, experiment_id)
population = store.population(experiment_id, 39)
result = tournament(population[:10], full_starts=True,
                    opponents=('cycle', 'uniform', 'reactive'), seed=8)
network = inspect(store, experiment_id, population[0].id)
analysis = population_analysis(store, experiment_id, 39)
```

`run_experiment(..., stop_after=N)` pauses after N additional committed generations for scripted recovery tests. `Genome.forward(observations, compatibility=False)` accepts one observation or a batch. `Genome.record()` serializes inherited data; `Genome(**record)` validates/restores it. Environment plugins return `Evaluation` arrays and expose reset/observe/step; register new factories in `environments.ENVIRONMENTS` and add their validated configuration type in `config.Environment`. See the implementations for exact type contracts.
