# Retrieval experiment

Dataset: synthetic clustered vectors; no real products or semantic claims

One query at a time. Timings exclude embeddings and transport. Recall is agreement with exact vector neighbors, not human relevance.

| Workload | Method | Probes | Recall@k | p50 ms | p95 ms |
|---|---|---:|---:|---:|---:|
| all | auto | 1 | 0.767 | 0.1060 | 0.1749 |
| all | auto | 4 | 1.000 | 0.2423 | 0.3944 |
| all | auto | 8 | 1.000 | 0.4710 | 0.6576 |
| all | auto | 16 | 1.000 | 0.9026 | 1.3903 |
| all | auto | 64 | 1.000 | 3.9542 | 5.5582 |
| all | exact | 1 | 1.000 | 2.0201 | 2.1375 |
| all | ivf | 1 | 0.767 | 0.1074 | 0.1664 |
| all | ivf | 4 | 1.000 | 0.2418 | 0.3995 |
| all | ivf | 8 | 1.000 | 0.4512 | 0.7211 |
| all | ivf | 16 | 1.000 | 0.9328 | 1.4041 |
| all | ivf | 64 | 1.000 | 3.9652 | 5.5785 |
| brand-narrow | auto | 1 | 0.718 | 0.0059 | 0.0083 |
| brand-narrow | auto | 4 | 0.998 | 0.0103 | 0.0137 |
| brand-narrow | auto | 8 | 1.000 | 0.0163 | 0.0216 |
| brand-narrow | auto | 16 | 1.000 | 0.0254 | 0.0293 |
| brand-narrow | auto | 64 | 1.000 | 0.0254 | 0.0298 |
| brand-narrow | exact | 1 | 1.000 | 0.0255 | 0.0338 |
| brand-narrow | ivf | 1 | 0.718 | 0.0060 | 0.0083 |
| brand-narrow | ivf | 4 | 0.998 | 0.0103 | 0.0135 |
| brand-narrow | ivf | 8 | 1.000 | 0.0161 | 0.0204 |
| brand-narrow | ivf | 16 | 1.000 | 0.0273 | 0.0335 |
| brand-narrow | ivf | 64 | 1.000 | 0.0925 | 0.1052 |
| color-medium | auto | 1 | 0.727 | 0.0136 | 0.0196 |
| color-medium | auto | 4 | 1.000 | 0.0282 | 0.0396 |
| color-medium | auto | 8 | 1.000 | 0.0480 | 0.0639 |
| color-medium | auto | 16 | 1.000 | 0.0860 | 0.1107 |
| color-medium | auto | 64 | 1.000 | 0.3237 | 0.3562 |
| color-medium | exact | 1 | 1.000 | 0.2443 | 0.2736 |
| color-medium | ivf | 1 | 0.727 | 0.0132 | 0.0200 |
| color-medium | ivf | 4 | 1.000 | 0.0281 | 0.0392 |
| color-medium | ivf | 8 | 1.000 | 0.0477 | 0.0628 |
| color-medium | ivf | 16 | 1.000 | 0.0862 | 0.1087 |
| color-medium | ivf | 64 | 1.000 | 0.3249 | 0.3691 |

Full environment, hashes, configuration, and individual observations are in report.json and raw.csv.
Vector byte counts exclude metadata, cluster storage, allocator overhead, and process runtime. These results do not establish deployed service throughput.
