# Real product retrieval experiments

These runs use Amazon ESCI US products and 384-dimensional MiniLM embeddings, rather than the generated vectors in the original experiment. They measure C++ retrieval on one Apple M2 Pro, not a deployed service.

## Protocol

- Sample products deterministically with seed 42. Use `sentence-transformers/all-MiniLM-L6-v2` revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, normalized embeddings, and the recorded title/description recipe.
- Use the existing 200 development queries from ESCI's train split for calibration, and 200 separate test queries from its test split for reporting. Preparation selects queries by sorted query ID; these are not a random sample of all customer queries. Test query IDs are checked against all development IDs.
- Build 64 clusters with 12 training iterations, at most 10,000 training vectors, and seed 42. Use a Release build (`-O3 -DNDEBUG`, Apple Clang 21.0.0).
- Fix the calibration operating point at 32 probes and k=10. Choose the fastest candidate planner factor whose development mean recall is at least 0.95 in every workload. Freeze it before reading test results; calibrate each catalog size separately.
- Evaluate exact search, IVF, and the frozen planner at 1, 4, 8, 16, 32, and 64 probes. The sweep illustrates the tradeoff; the development recall target applies only at 32 probes. The planner does not enforce a recall floor at other probe counts.
- Use 200 test queries, three metadata workloads, and three timing repeats. Warm every configuration and shuffle the C++ timing order. Each summary cell has 600 observations from 200 distinct query IDs; repeats are not additional queries.
- Compare each result against exact vector neighbors within that filter's eligible set. This recall measures vector-search approximation, not human shopping relevance or ESCI relevance labels. The same queries are used in all filter workloads, even when a brand is unrelated to the original query.

The brand/color labels describe intended workload selectivity. The reports record the actual eligible counts, which can differ substantially from 1% and 10% because real metadata is uneven and often missing. All rows, including rows with missing metadata, remain eligible in unfiltered search.

## 10,000 products

The development-selected factor was **8**. The held-out planner results at the fixed **32-probe** operating point were:

| Workload | Eligible products | Exact p50 / p95 ms | Planner p50 / p95 ms | Planner mean recall@10 | Planner choice |
| --- | ---: | ---: | ---: | ---: | --- |
| All products | 10,000 | 2.2008 / 2.3383 | 1.2105 / 1.3830 | 0.9875 | IVF |
| Brand: nike | 52 (0.52%) | 0.0148 / 0.0173 | 0.0149 / 0.0178 | 1.0000 | Exact |
| Color: black | 1,055 (10.55%) | 0.2443 / 0.2717 | 0.1513 / 0.1882 | 0.9560 | IVF |

At this operating point the unfiltered planner median was about **1.82x faster than this engine's exact path**, trading away about 1.25% of exact neighbors on average. For the narrow brand filter, scanning 52 eligible products was both faster and more accurate than using IVF: forced IVF at 32 probes reached only 0.8025 mean recall and a 0.0313 ms median.

Low probes are unsafe to treat as an equivalent-quality speedup: at one probe, unfiltered mean recall was 0.520 and the brand planner mean recall was only 0.017. At 64 probes, forced IVF matched exact neighbors but was slower than exact search on this run. The calibrated factor remains specific to the dataset, machine, and probe setting; the application default has not been changed.

[Full 10k report](../benchmarks/example-esci-10k/REPORT.md), [environment and configuration](../benchmarks/example-esci-10k/report.json), [development calibration](../benchmarks/example-esci-10k/calibration.json), and [compressed observations](../benchmarks/example-esci-10k/raw.csv.gz).

## 100,000 products

Development calibration independently selected **factor 8** at the same fixed **32-probe** operating point. The held-out results were:

| Workload | Eligible products | Exact p50 / p95 ms | Planner p50 / p95 ms | Planner mean recall@10 | Planner choice |
| --- | ---: | ---: | ---: | ---: | --- |
| All products | 100,000 | 22.1125 / 23.3583 | 16.7339 / 19.0790 | 0.9915 | IVF |
| Brand: nike | 508 (0.508%) | 0.1237 / 0.1411 | 0.1238 / 0.1376 | 1.0000 | Exact |
| Color: black | 10,998 (10.998%) | 2.8328 / 3.5847 | 1.6043 / 2.1038 | 0.9810 | IVF |

The unfiltered planner median was about **1.32x faster than this engine's exact path** at 0.9915 mean recall. For the brand filter it chose exact search, retained full recall, and was faster than forced 32-probe IVF (0.1372 ms median, 0.8005 mean recall). The color workload reached 0.981 mean recall with a 1.6043 ms planner median versus 2.8328 ms exact.

The 32-probe planner exceeded the preselected 0.95 mean recall target in every held-out workload at both catalog sizes. That is a result of these samples, not a guarantee on future queries. At one probe the 100k brand planner recall fell to 0.0575; there is no implicit quality guarantee when changing probes.

The planner was not faster in every setting. Probing all clusters restored exact neighbors, while unfiltered IVF incurred more work than the exact path. The application's default index/planner configuration remains unchanged; these results use the separately built tuned indexes.

[Full 100k report](../benchmarks/example-esci-100k/REPORT.md), [environment and configuration](../benchmarks/example-esci-100k/report.json), [development calibration](../benchmarks/example-esci-100k/calibration.json), and [compressed observations](../benchmarks/example-esci-100k/raw.csv.gz).

## FAISS reference

FAISS 1.15.1 runs with one OpenMP thread. Its flat and IVF indexes use the same vectors and exact neighbor ground truth. Filtered FAISS indexes are built and trained separately for each eligible subset before measurement; their timed work excludes filtering and copying. The C++ engine times filtering, planning, centroid scoring, comparisons, and top-k selection inside retrieval. FAISS's Python search call has its own call overhead. The implementations use different clustering and different cluster counts for small filtered subsets, so equal probe counts do not imply equal work or recall.

FAISS measurements run after the C++ measurements, rather than in the same shuffled schedule. Treat them as search-kernel references with potentially different cache/thermal conditions. They are not an end-to-end speed comparison.

FAISS was substantially faster in the 10k reference: unfiltered exact search had a 0.2744 ms median, and its 32-probe IVF had a 0.1483 ms median at 0.988 mean recall. At 100k, unfiltered FAISS flat search had a 2.9204 ms median, and its 32-probe IVF had a 1.5849 ms median at 0.988 mean recall. FAISS's 100k IVF recall differs from the custom engine's 0.9915, so those two IVF latencies are not at identical quality. These results support studying the custom C++ engine's behavior; they do not support claiming it beats FAISS.

## Verification

All 15 C++ tests and all nine Python tests passed locally, including the Unicode JSONL regression. At each catalog size, exact top-10 IDs matched an independent NumPy dot-product/sort calculation for 20 test queries across all three filter workloads (120 query/filter checks total). Forced IVF at all 64 clusters matched exact neighbors in all 1,800 timed observations per catalog size. Every saved recall/p50/p95 summary was recomputed from its raw rows and matched: 60 cells and 36,000 observations per catalog size. Both plots were visually checked.

## What the artifacts contain

Each saved experiment includes a generated full table, `report.json`, `calibration.json`, compressed raw timing rows, and PNG/SVG recall-versus-latency plots. Reports retain dataset/model provenance, hashes, hardware, settings, actual filter values/counts, and the measured planner configuration. Downloaded products, embeddings, indexes, model files, and machine-specific execution logs stay local. Raw rows contain query IDs and measurements, not query or product text.

Retrieval timings exclude model inference, JSON/worker transport, HTTP, and index loading. They do not establish end-to-end latency, service throughput, shopper relevance, or performance on another machine. This is one timed experiment per catalog size, not a multi-machine study. Each catalog size has its own selected queries and trained clusters, so the size comparison is not a controlled scaling experiment with identical queries.

The benchmark reader also needed a correctness fix: Python `str.splitlines()` splits valid JSON strings containing Unicode line/paragraph separators. Reading physical JSONL lines preserves those characters. A regression test covers U+2028, U+2029, and U+0085.

## Reproduce

From the repository root, install the dependencies and prepare each catalog with the pinned model:

```sh
python3 scripts/setup_semantic.py --limit 10000
.venv-semantic/bin/python -m catalog_search.prepare --source esci --limit 10000 --revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 --output data/esci-10000
.venv-semantic/bin/python -m catalog_search.prepare --source esci --limit 100000 --revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 --output data/esci-100000
```

For each catalog, build the initial index, calibrate on development queries, read `recommended_exact_cost_factor` in `calibration.json`, and build a separate tuned index with that value before running the test set. Do not select the factor from test results. Preparation can take several minutes and first-time downloads are large.

```sh
build/catalog build --input data/esci-10000/catalog.jsonl --output data/esci-10000/catalog.csidx --clusters 64 --iterations 12 --training-samples 10000 --seed 42
.venv-semantic/bin/python -m catalog_search.evaluate --dataset data/esci-10000 --index data/esci-10000/catalog.csidx --output benchmarks/runs/esci-10000-dev --queries 200 --probes 32 --calibrate --min-recall 0.95
# This run selected factor 8; a fresh calibration may select a different factor.
build/catalog build --input data/esci-10000/catalog.jsonl --output data/esci-10000/catalog-tuned.csidx --clusters 64 --iterations 12 --training-samples 10000 --seed 42 --exact-cost-factor 8
.venv-semantic/bin/python -m catalog_search.evaluate --dataset data/esci-10000 --index data/esci-10000/catalog-tuned.csidx --output benchmarks/runs/esci-10000-test --queries 200 --repeats 3 --probes 1 4 8 16 32 64 --faiss
.venv-semantic/bin/python scripts/plot_report.py benchmarks/runs/esci-10000-test/report.json
```

Repeat these build/calibration/evaluation commands with `esci-100000` paths and the factor selected by that catalog's own development calibration. `--faiss` requires the optional `bench` dependencies installed by the setup script. Generated timing values vary between runs.
