# Measured performance

Measurements were taken on 2026-10-11 on the supplied AMD Ryzen 7 9700X (8 cores, 16 logical CPUs), 31,951,908 kB system RAM, Debian/Linux 6.12, Python 3.13.5, NumPy 2.5.4, with optional Numba installed. No GPU was used. Exact configuration, raw timing samples summarized as medians/minima, and worker-job latencies are in `benchmark_results.json`. The desktop was not isolated as a dedicated benchmark host; these are local observations, not universal guarantees.

The compatibility workload contains 100 networks, 30 pairing rounds, 23 self-play throws and 20 bot throws per round, top 20 selection, 80 children and 159 parameters per genome. Bot weight is 0.25. The baseline configuration records default seed 42; the measured components and direct run explicitly use seed 91, and parallel runs use seeds 700..703. These overrides are recorded in `measurement_seeds`. Full-run measurements retain every population/fitness snapshot and write a recovery checkpoint every generation, with archived checkpoints every ten generations.

## Component timings

| Component | Median | Repeats |
|---|---:|---:|
| Ordered inference, 100 networks × all 40 histories | 0.851 ms | 10 |
| One genome / one observation | 22.09 µs | 100 |
| NumPy match kernel, one generation's schedule | 24.623 ms | 5 |
| Numba match kernel, identical schedule | 0.325 ms | 20 |
| Elite ranking | 10.90 µs | 100 |
| Reproduction and mutation, 80 children | 9.825 ms | 10 |

Compiled first invocation took 53.149 ms. A compiled disk cache may already have existed, so this is **not a clean-cache JIT compilation measurement**. Kernel times exclude inference, schedule construction, statistics and persistence. NumPy and compiled paths pass equality tests on the same schedules; Numba uses no fast-math optimizations.

## Full execution and overhead

A 40-generation in-process run took **0.834836 s**, averaging **20.871 ms/generation** or **47.914 generations/s**.

| Measured total during that run | Time |
|---|---:|
| Evaluation, including policy preparation and schedules | 0.071000 s |
| SQLite generation transactions | 0.301427 s |
| Checkpoint serialization/checksum/INSERT (overlaps transactions) | 0.001749 s |
| Process CPU time | 0.635014 s |

CPU/wall time was 76.06% of one logical core; this is not total-system CPU utilization. Process peak resident memory was 146.64 MiB. Transaction timing includes SQLite commit/storage overhead; checkpoint time includes initialization and overlaps generation transactions, so it must not be added again. The remainder includes initialization, analysis, reproduction, state preparation and orchestration. After match acceleration, reproduction and database work dominate.

## Worker scaling

Four independent 40-generation experiments were executed per setting. These elapsed times include worker startup, queue wait, SQLite writes and scheduler polling, unlike the direct in-process measurement above.

| Workers | Batch elapsed | Aggregate throughput |
|---:|---:|---:|
| 1 | 8.244 s | 19.408 gen/s |
| 2 | 4.233 s | 37.801 gen/s |
| 4 | 2.217 s | 72.181 gen/s |

Short jobs magnify process/startup/polling costs. This does not establish scaling beyond four workers or elimination of SQLite's single-writer bottleneck. Two workers remain the conservative desktop default; per-batch and global limits are enforced.

## Endurance

`acceptance_results.json` records a 200-generation run in 4.172 s, an uninterrupted 1,000-generation run in 20.665 s and a four-pause 1,000-generation run in 20.754 s. The two long runs have exactly matching genome/fitness digests. During the uninterrupted run process peak RSS increased from 147.86 to 149.28 MiB; average generation compute time was 12.476 ms for the first 50 and 12.402 ms for the last 50. These observations show no progressive slowdown in this test; they do not prove unbounded-run memory stability. SQLite history grows with retained genomes and snapshots (the browser's 1,000-generation database is approximately 327 MiB).

## TurboWarp comparison

The supplied development directive reports **0.416 s/generation of tournament computation** for an optimized 200-generation TurboWarp run on the same CPU model. That baseline was **not rerun** here. Python's measured full evaluation averaged 0.071000/40 = **1.775 ms/generation** in the short compiled run; the warmed match kernel alone was 0.325 ms, and the NumPy kernel 24.623 ms.

These are substantially lower observed Python timings, but the timing boundaries, warm-up, software versions and host load are not controlled across the two systems. **No measured end-to-end TurboWarp speedup is claimed.** A live cross-runtime benchmark remains an optional follow-up, separate from the source-based compatibility tests.

Reproduce fresh measurements with the benchmark command in README.md; use a new data directory/output path to preserve these release observations. `src/evolution_engine/benchmark.py` documents the timing boundaries.
