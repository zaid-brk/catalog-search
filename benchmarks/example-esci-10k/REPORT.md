# Retrieval experiment

Dataset: Amazon ESCI US products; MiniLM embeddings; see manifest and dataset source

One query at a time. Timings exclude embeddings and transport. Recall is agreement with exact vector neighbors, not human relevance.

| Workload | Method | Probes | Recall@k | p50 ms | p95 ms |
|---|---|---:|---:|---:|---:|
| all | auto | 1 | 0.520 | 0.0581 | 0.0773 |
| all | auto | 4 | 0.811 | 0.1644 | 0.2080 |
| all | auto | 8 | 0.913 | 0.3169 | 0.3846 |
| all | auto | 16 | 0.958 | 0.6197 | 0.7067 |
| all | auto | 32 | 0.988 | 1.2105 | 1.3830 |
| all | auto | 64 | 1.000 | 2.3656 | 2.7313 |
| all | exact | 1 | 1.000 | 2.2008 | 2.3383 |
| all | faiss-flat | 1 | 1.000 | 0.2744 | 0.3004 |
| all | faiss-ivf-prefilter | 1 | 0.511 | 0.0096 | 0.0122 |
| all | faiss-ivf-prefilter | 4 | 0.818 | 0.0227 | 0.0285 |
| all | faiss-ivf-prefilter | 8 | 0.913 | 0.0399 | 0.0493 |
| all | faiss-ivf-prefilter | 16 | 0.957 | 0.0751 | 0.0884 |
| all | faiss-ivf-prefilter | 32 | 0.988 | 0.1483 | 0.1682 |
| all | faiss-ivf-prefilter | 64 | 1.000 | 0.3001 | 0.3259 |
| all | ivf | 1 | 0.520 | 0.0582 | 0.0775 |
| all | ivf | 4 | 0.811 | 0.1644 | 0.2061 |
| all | ivf | 8 | 0.913 | 0.3177 | 0.3815 |
| all | ivf | 16 | 0.958 | 0.6174 | 0.7294 |
| all | ivf | 32 | 0.988 | 1.2083 | 1.3977 |
| all | ivf | 64 | 1.000 | 2.3714 | 2.8123 |
| brand-narrow | auto | 1 | 0.017 | 0.0153 | 0.0174 |
| brand-narrow | auto | 4 | 1.000 | 0.0149 | 0.0177 |
| brand-narrow | auto | 8 | 1.000 | 0.0148 | 0.0180 |
| brand-narrow | auto | 16 | 1.000 | 0.0148 | 0.0177 |
| brand-narrow | auto | 32 | 1.000 | 0.0149 | 0.0178 |
| brand-narrow | auto | 64 | 1.000 | 0.0149 | 0.0174 |
| brand-narrow | exact | 1 | 1.000 | 0.0148 | 0.0173 |
| brand-narrow | faiss-flat | 1 | 1.000 | 0.0037 | 0.0041 |
| brand-narrow | faiss-ivf-prefilter | 1 | 1.000 | 0.0042 | 0.0045 |
| brand-narrow | faiss-ivf-prefilter | 4 | 1.000 | 0.0039 | 0.0042 |
| brand-narrow | faiss-ivf-prefilter | 8 | 1.000 | 0.0039 | 0.0043 |
| brand-narrow | faiss-ivf-prefilter | 16 | 1.000 | 0.0039 | 0.0042 |
| brand-narrow | faiss-ivf-prefilter | 32 | 1.000 | 0.0039 | 0.0042 |
| brand-narrow | faiss-ivf-prefilter | 64 | 1.000 | 0.0039 | 0.0043 |
| brand-narrow | ivf | 1 | 0.017 | 0.0153 | 0.0180 |
| brand-narrow | ivf | 4 | 0.101 | 0.0158 | 0.0250 |
| brand-narrow | ivf | 8 | 0.254 | 0.0165 | 0.0291 |
| brand-narrow | ivf | 16 | 0.493 | 0.0227 | 0.0320 |
| brand-narrow | ivf | 32 | 0.802 | 0.0313 | 0.0365 |
| brand-narrow | ivf | 64 | 1.000 | 0.0368 | 0.0425 |
| color-medium | auto | 1 | 0.260 | 0.0184 | 0.0281 |
| color-medium | auto | 4 | 0.523 | 0.0302 | 0.0509 |
| color-medium | auto | 8 | 0.700 | 0.0475 | 0.0779 |
| color-medium | auto | 16 | 0.858 | 0.0839 | 0.1212 |
| color-medium | auto | 32 | 0.956 | 0.1513 | 0.1882 |
| color-medium | auto | 64 | 1.000 | 0.2445 | 0.2678 |
| color-medium | exact | 1 | 1.000 | 0.2443 | 0.2717 |
| color-medium | faiss-flat | 1 | 1.000 | 0.0313 | 0.0360 |
| color-medium | faiss-ivf-prefilter | 1 | 0.371 | 0.0047 | 0.0060 |
| color-medium | faiss-ivf-prefilter | 4 | 0.713 | 0.0089 | 0.0110 |
| color-medium | faiss-ivf-prefilter | 8 | 0.869 | 0.0140 | 0.0178 |
| color-medium | faiss-ivf-prefilter | 16 | 0.970 | 0.0230 | 0.0274 |
| color-medium | faiss-ivf-prefilter | 32 | 1.000 | 0.0336 | 0.0385 |
| color-medium | faiss-ivf-prefilter | 64 | 1.000 | 0.0334 | 0.0382 |
| color-medium | ivf | 1 | 0.260 | 0.0184 | 0.0276 |
| color-medium | ivf | 4 | 0.523 | 0.0302 | 0.0506 |
| color-medium | ivf | 8 | 0.700 | 0.0475 | 0.0784 |
| color-medium | ivf | 16 | 0.858 | 0.0835 | 0.1206 |
| color-medium | ivf | 32 | 0.956 | 0.1509 | 0.1908 |
| color-medium | ivf | 64 | 1.000 | 0.2700 | 0.2964 |

Full environment, hashes, configuration, and individual observations are in report.json and raw.csv.gz.
Vector byte counts exclude metadata, cluster storage, allocator overhead, and process runtime. These results do not establish deployed service throughput.

Search-kernel reference: separately trained per-filter indexes; timings exclude filter selection/copying, unlike C++ timings. Not an end-to-end performance comparison. No claim of beating FAISS.

Protocol, interpretation, exact eligible counts, calibration, and reproduction commands: [real-data experiments](../../docs/REAL_DATA_RESULTS.md). The fixed calibration operating point is 32 probes; lower-probe rows do not inherit its recall target.

![Recall and latency by workload](recall-latency.png)
