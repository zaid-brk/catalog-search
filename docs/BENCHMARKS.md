# Benchmark notes

`python/catalog_search/evaluate.py` runs exact search, IVF, and the planner against precomputed query vectors. Each configuration gets a warm-up, then the order is shuffled for repeated measurements. The output includes raw observations, hashes, machine details, recall@k, and median/p95 latency.

The workloads are unfiltered, a brand close to 1% of the catalog, and a color close to 10%. Those are targets; the actual eligible counts are recorded. Ground truth is exact search within the eligible subset, not the unfiltered catalog.

Calibration uses development queries to select a planner coefficient subject to a minimum mean recall per workload. Test queries have separate IDs. A coefficient calibrated at one probe count isn't guaranteed to work well at other settings or on another machine.

## What the numbers include

- `retrieval_ms` includes query normalization, filtering, planning, allocations, centroid ranking, comparisons, and top-k selection. It excludes JSON, HTTP, model inference, and index loading.
- `worker_roundtrip_ms` also includes Python/CLI serialization and parsing.
- The app reports encoding and total request time separately. Encoding queue time is included in the total.
- `catalog-loadtest` measures concurrent C++ retrieval using cyclic precomputed queries. Its QPS isn't HTTP or end-to-end throughput. Peak RSS includes index loading; vector bytes alone aren't total memory use.

Recall measures agreement with exact vector neighbors. It doesn't tell us whether a person would find the products relevant. Compare latency at the same measured recall, rather than assuming equal probe counts mean equal quality.

## FAISS

The optional `--faiss` reference uses one OpenMP thread. It builds a separate index over each filtered subset before timing. That excludes filtering/copying work that the C++ engine does during search, so these are search-kernel references rather than an end-to-end speed comparison.

All methods use the same exact neighbor IDs as ground truth. Equal-score ties can be resolved differently by FAISS, so small recall differences need inspection. The FAISS comparison hasn't been run yet.

## Saved run

`benchmarks/example-synthetic-100k/` contains the first 100,000-vector experiment: report, gzipped raw observations, calibration, load test, and plots. It uses generated clustered 64-dimensional vectors and 60 held-out queries. Repeated timings aren't additional independent queries. These results don't establish performance on real 384-dimensional MiniLM product embeddings.
