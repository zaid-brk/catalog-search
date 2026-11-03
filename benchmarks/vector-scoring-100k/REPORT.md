# Paired vector-scoring experiment

100,000 real products; 200 test queries; three filter workloads; 3 repeats.

One fixed index is shared by both engines. Timings include C++ retrieval only, excluding model inference and transport. Recall is against baseline exact vector neighbors, not shopper relevance.

| Workload | Method | Before p50 / p95 ms | After p50 / p95 ms | Median speedup | Before / after recall@10 |
| --- | --- | ---: | ---: | ---: | ---: |
| all | exact | 21.9350 / 22.9688 | 7.5563 / 8.0494 | 2.90x | 1.0000 / 1.0000 |
| all | ivf | 17.3724 / 19.3970 | 11.4263 / 12.6189 | 1.52x | 0.9915 / 0.9915 |
| all | auto | 17.3685 / 19.3922 | 11.3305 / 12.7164 | 1.53x | 0.9915 / 0.9915 |
| brand-narrow | exact | 0.1222 / 0.1410 | 0.0455 / 0.0551 | 2.69x | 1.0000 / 1.0000 |
| brand-narrow | ivf | 0.1342 / 0.1739 | 0.0645 / 0.0799 | 2.08x | 0.8005 / 0.8005 |
| brand-narrow | auto | 0.1224 / 0.1409 | 0.0455 / 0.0546 | 2.69x | 1.0000 / 1.0000 |
| color-medium | exact | 3.1745 / 3.6926 | 1.7293 / 2.2399 | 1.84x | 1.0000 / 1.0000 |
| color-medium | ivf | 1.6808 / 2.2244 | 0.7775 / 1.2677 | 2.16x | 0.9810 / 0.9810 |
| color-medium | auto | 1.6545 / 2.1643 | 0.7588 / 1.2520 | 2.18x | 0.9810 / 0.9810 |

Raw timing rows: `raw.csv.gz`. Configuration, hashes, actual filter counts, numerical checks, and full-precision summaries: `report.json`.

These are same-machine observations, not service throughput or a cross-machine performance guarantee. Repeats are not additional independent queries.
