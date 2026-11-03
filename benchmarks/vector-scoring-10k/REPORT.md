# Paired vector-scoring experiment

10,000 real products; 200 test queries; three filter workloads; 3 repeats.

One fixed index is shared by both engines. Timings include C++ retrieval only, excluding model inference and transport. Recall is against baseline exact vector neighbors, not shopper relevance.

| Workload | Method | Before p50 / p95 ms | After p50 / p95 ms | Median speedup | Before / after recall@10 |
| --- | --- | ---: | ---: | ---: | ---: |
| all | exact | 2.2184 / 2.3768 | 0.7631 / 0.8895 | 2.91x | 1.0000 / 1.0000 |
| all | ivf | 1.3409 / 1.7046 | 0.5654 / 0.9848 | 2.37x | 0.9875 / 0.9875 |
| all | auto | 1.3426 / 1.7655 | 0.5630 / 0.9581 | 2.38x | 0.9875 / 0.9875 |
| brand-narrow | exact | 0.0160 / 0.0210 | 0.0071 / 0.0093 | 2.26x | 1.0000 / 1.0000 |
| brand-narrow | ivf | 0.0323 / 0.0395 | 0.0154 / 0.0194 | 2.09x | 0.8025 / 0.8025 |
| brand-narrow | auto | 0.0160 / 0.0188 | 0.0071 / 0.0090 | 2.26x | 1.0000 / 1.0000 |
| color-medium | exact | 0.2611 / 0.3116 | 0.0939 / 0.1425 | 2.78x | 1.0000 / 1.0000 |
| color-medium | ivf | 0.1575 / 0.2066 | 0.0606 / 0.0800 | 2.60x | 0.9560 / 0.9560 |
| color-medium | auto | 0.1581 / 0.2032 | 0.0609 / 0.0802 | 2.60x | 0.9560 / 0.9560 |

Raw timing rows: `raw.csv.gz`. Configuration, hashes, actual filter counts, numerical checks, and full-precision summaries: `report.json`.

These are same-machine observations, not service throughput or a cross-machine performance guarantee. Repeats are not additional independent queries.
