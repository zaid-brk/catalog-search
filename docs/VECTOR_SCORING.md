# Profile-guided vector scoring

The real-data baseline showed that the custom engine had substantial room to improve. This change speeds up its dot-product reduction using four independent partial sums. The optimization improves measured retrieval without changing the API, index format, planner settings, or requiring a platform-specific instruction set.

## What the profile showed

A macOS `sample` run observed one exact-search worker on the 100,000-product MiniLM index for eight seconds at a one-millisecond sampling interval. It used the first 20 development queries cyclically; no test-query measurements selected the implementation.

Of 6,884 worker samples, 6,870 had the candidate-scoring lambda at the top of the stack (about 99.8%). That function contains the inlined dot product and heap update; this is not a claim that precisely 99.8% of CPU cycles were in the dot product. Sampled machine-code offsets were in its vector multiplication/scalar reduction region. The main thread was waiting for the worker and is excluded from this fraction.

The baseline compiler already used packed multiplication, but accumulated the products through a serial chain of scalar additions. The change breaks that chain into four partial sums and combines them at the end. A scalar tail handles dimensions that are not multiples of four.

Clang's loop hint disables outer-loop vectorization/interleaving for this small loop, leaving its SLP vectorizer to pack the four independent accumulations. On the measured Apple Clang build, disassembly showed packed `fmla.2s` accumulation. Other compilers use the same standard C++ implementation without the Clang-only hint. No global fast-math flag or architecture-specific intrinsic was introduced. Generated instructions and performance remain compiler/CPU dependent.

[Compact profiling evidence](../benchmarks/vector-scoring-100k/profile-summary.json). The raw sampling log stays local because it includes machine-specific process and filesystem details.

## Paired results

Both engines loaded the same existing index for each catalog size. The baseline is commit `eb08210a0acad7544206461af94d1a0fefa1d017`; both binaries used the same Release build settings (`-O3 -DNDEBUG`, Apple Clang 21.0.0) on an Apple M2 Pro. Candidate engine-source hashes, binary hashes, index hashes, query-file hashes, and comparison-script hashes are recorded in the reports. The reports' `git_revision` records the checkout base at measurement time; the candidate source hash identifies the measured working-tree implementation.

Each catalog uses 200 test queries, three filter workloads, three methods (exact, IVF, auto), and three repeats. Methods are shuffled and the two versions run in randomized pairs. Both versions are warmed before measurement. Each summary cell contains 600 timings from 200 distinct query IDs; repeats are not additional independent queries. This is one timed experiment per catalog size, not a cross-machine performance guarantee.

The fixed operating point is k=10 and 32 probes. Both versions retain the existing factor-8 index so the comparison isolates scoring changes. The brand workload selects `nike` (52/10,000 or 508/100,000 eligible products); the color workload selects `black` (1,055/10,000 or 10,998/100,000).

Unfiltered retrieval medians:

| Products | Method | Before | After | Median speedup | Recall@10 before / after |
| --- | --- | ---: | ---: | ---: | ---: |
| 10,000 | Exact | 2.2184 ms | 0.7631 ms | 2.91x | 1.0000 / 1.0000 |
| 10,000 | IVF | 1.3409 ms | 0.5654 ms | 2.37x | 0.9875 / 0.9875 |
| 10,000 | Auto | 1.3426 ms | 0.5630 ms | 2.38x | 0.9875 / 0.9875 |
| 100,000 | Exact | 21.9350 ms | 7.5563 ms | 2.90x | 1.0000 / 1.0000 |
| 100,000 | IVF | 17.3724 ms | 11.4263 ms | 1.52x | 0.9915 / 0.9915 |
| 100,000 | Auto | 17.3685 ms | 11.3305 ms | 1.53x | 0.9915 / 0.9915 |

Every measured method/filter combination improved in median latency at both catalog sizes. The full tables include p95 and selective-filter results: [10k](../benchmarks/vector-scoring-10k/REPORT.md), [100k](../benchmarks/vector-scoring-100k/REPORT.md). JSON configuration and compressed raw rows accompany each table; all 36 summary cells were independently recomputed from the 21,600 saved rows and matched.

Recall is agreement with the baseline's exact vector neighbors, not shopper relevance. Timings measure C++ retrieval and exclude embeddings, serialization/worker transport, HTTP, and loading. FAISS was not rerun for this isolated before/after experiment; the earlier [real-data comparison](REAL_DATA_RESULTS.md) remains a historical reference, not an updated performance comparison against the optimized engine.

## Correctness and precision

Summation order changes floating-point rounding. It does not promise bit-for-bit score compatibility or identical ranking for every possible near-tie.

Across 1,800 compared query/filter/method cases per catalog size, returned top-10 IDs and order all matched the baseline. Maximum shared-hit score changes were about `4.77e-7` at 10k and `8.34e-7` at 100k. Recall remained unchanged in every summary cell. For each version, probing all clusters also matched exact hits and scores across all 600 query/filter cases per catalog size.

The 17 C++ tests passed in Release, AddressSanitizer/UndefinedBehaviorSanitizer, and ThreadSanitizer builds. New tests compare dot products with a double-precision oracle across 26 dimensions from zero to 4,096, including scalar tails and spans offset from their allocation base. A 385-dimensional identical-vector test checks deterministic ties and equality between exact and full-probe IVF. All nine Python tests passed, including the independent NumPy search oracle and gateway integration.

## Planner limitation exposed by the improvement

At 100k and 32 probes, the faster exact path now beats IVF for the unfiltered workload, while the existing planner still picks IVF. The fixed factor was calibrated before this scoring optimization; the planner was not retuned in this experiment. At 10k, IVF remains faster than exact at the same operating point. These observations do not establish a general rule to prefer exact or IVF at other sizes/probe counts.

The simple planner assumes a rough relationship between eligible counts and clustered work. Its estimate can miss execution-cost differences; this is a separate planner limitation, not a correctness regression. To reproduce the fastest measured 100k unfiltered path at this operating point, select exact search explicitly. The automatic path still improved relative to its own baseline. No new default threshold was inferred from held-out test queries.

## Reproduce

Keep the dataset and index fixed between versions. From a clean checkout with the existing semantic environment, preserve the baseline binary before building the candidate. For example, with this change checked out:

```sh
git worktree add --detach ../catalog-search-scoring-baseline eb08210a0acad7544206461af94d1a0fefa1d017
.venv-semantic/bin/cmake -S ../catalog-search-scoring-baseline -B build-scoring-baseline -G Ninja -DCMAKE_BUILD_TYPE=Release -DBOOST_ROOT=/opt/anaconda3 -DCMAKE_PREFIX_PATH=/opt/anaconda3
.venv-semantic/bin/cmake --build build-scoring-baseline --target catalog
.venv-semantic/bin/cmake --build build --target catalog
.venv-semantic/bin/python benchmarks/compare_retrieval.py --baseline build-scoring-baseline/catalog --candidate build/catalog --dataset data/esci-100000 --index data/esci-100000/catalog-tuned.csidx --output benchmarks/runs/vector-scoring-100k
```

The Boost paths above match the measured macOS environment; adjust them for your installation. Use the [real-data preparation instructions](REAL_DATA_RESULTS.md) to prepare the pinned datasets and factor-8 indexes first. Repeat the comparison with `esci-10000` paths for the smaller catalog. New timings vary with system load and compiler configuration; the saved observations are the evidence for the reported ratios.
