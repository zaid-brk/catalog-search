# Hybrid search benchmark

The demo offers three ranking modes. Keyword uses BM25 over product titles (k1 = 1.2, b = 0.75). Semantic uses the existing MiniLM and C++ vector pipeline. Hybrid combines at least the top 50 candidates per path with [reciprocal rank fusion](https://cormack.uwaterloo.ca/cormack/cormacksigir09-rrf.pdf) (rank constant 60). The gateway applies brand and color filters before ranking on both paths. Semantic is the default.

## Results

The local run used 10,000 Amazon ESCI US products on an Apple M2 Pro. Both vector paths used Automatic with eight probes and the shipped index defaults. Of the 200 prepared test queries, 179 had at least one positively judged product in the sampled catalog. Each mode was timed three times per query after warm-up, with the order shuffled.

| Search mode | Mean nDCG@10 | Judged hits / returned hits | p95 server latency |
| --- | ---: | ---: | ---: |
| Keyword | 0.579 | 137 / 1,622 (8.4%) | 1.32 ms |
| Semantic | 0.479 | 122 / 1,790 (6.8%) | 11.39 ms |
| Hybrid | 0.588 | 140 / 1,790 (7.8%) | 12.35 ms |

The metric uses gains of 1.0 for Exact, 0.1 for Substitute, 0.01 for Complement, and 0 for Irrelevant. It treats unjudged hits as zero gain and normalizes each query against its ideal ordering of judged products in the sampled catalog. The judged-hit fraction includes all four labels. Most hits were unjudged, so the small difference between Hybrid and Keyword is specific to this sample and scoring rule. Keyword sometimes returned fewer than 10 results.

Latency is the gateway's server total, including query encoding, the C++ request, keyword retrieval, and rank fusion as applicable. It excludes browser-to-gateway transport and rendering.

## Reproduce

Start the 10,000-product semantic demo using the [README setup](../README.md#running-it). In a second terminal, run:

```sh
.venv-semantic/bin/python -m catalog_search.evaluate_relevance \
  --dataset data/esci-10000 \
  --examples data/raw/shopping_queries_dataset_examples.parquet
```

The JSON report includes the dataset and query hashes, rank settings, coverage, and measurements. Use the prepared catalog and its matching index and product metadata from the same dataset directory.
