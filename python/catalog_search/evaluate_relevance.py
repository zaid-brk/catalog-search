"""Compare the live search modes on held-out Amazon ESCI judgments."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import random
import statistics

import httpx
import numpy as np

from .evaluate import file_hash, jsonl
from .ranking import HYBRID_DEPTH, MODES

GAINS = {"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0}
TOP_K = 10


def load_judgments(examples, query_ids, product_ids):
    from pyarrow.parquet import ParquetFile

    columns = ["query_id", "product_id", "product_locale", "split", "esci_label"]
    judgments = defaultdict(dict)
    for batch in ParquetFile(examples).iter_batches(columns=columns):
        for row in batch.to_pylist():
            query_id = str(row["query_id"])
            product_id = row["product_id"]
            if (row["split"] == "test" and row["product_locale"] == "us"
                    and query_id in query_ids and product_id in product_ids):
                gain = GAINS[row["esci_label"]]
                previous = judgments[query_id].setdefault(product_id, gain)
                if previous != gain:
                    raise ValueError(f"Conflicting ESCI labels for query {query_id}, product {product_id}")
    return judgments


def dcg(gains):
    return sum(gain / math.log2(rank + 2) for rank, gain in enumerate(gains))


def evaluate(dataset, examples, url, repeats):
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    products = {p["id"] for p in jsonl(dataset / "products.jsonl")}
    test_path = dataset / "queries-test.jsonl"
    test = jsonl(test_path)
    ids = {q["query_id"] for q in test}
    dev_ids = {q["query_id"] for q in jsonl(dataset / "queries-dev.jsonl")}
    if len(ids) != len(test) or ids & dev_ids:
        raise ValueError("Test query IDs must be unique and disjoint from development IDs")
    judgments = load_judgments(examples, ids, products)
    queries = [q for q in test if any(judgments[q["query_id"]].values())]
    if not queries:
        raise ValueError("No held-out queries have a positive ESCI judgment in this catalog")

    quality = defaultdict(list)
    times = defaultdict(list)
    rng = random.Random(42)

    with httpx.Client(base_url=url, timeout=30, trust_env=False) as client:
        response = client.get("/api/info")
        response.raise_for_status()
        info = response.json()
        if (any(info[key] != manifest[key] for key in ("products", "model_id", "provenance"))
                or not info["semantic"] or not info["keyword_available"]):
            raise ValueError("Start the semantic demo with the same ESCI dataset")
        probes = min(info["clusters"], 8)

        def search(query, mode):
            response = client.post("/api/search", json={
                "query": query["text"], "mode": mode, "k": TOP_K, "strategy": "auto", "probes": probes,
            })
            response.raise_for_status()
            return response.json()

        for query in queries[:5]:
            for mode in MODES:
                search(query, mode)

        for query in queries:
            labels = judgments[query["query_id"]]
            ideal = dcg(sorted(labels.values(), reverse=True)[:TOP_K])
            for repeat in range(repeats):
                for mode in rng.sample(MODES, len(MODES)):
                    result = search(query, mode)
                    times[mode].append(result["total_ms"])
                    if repeat == 0:
                        hits = [hit["id"] for hit in result["hits"]]
                        if len(hits) != len(set(hits)) or not set(hits) <= products:
                            raise ValueError("Search returned duplicate or unknown product IDs")
                        score = dcg(labels.get(hit, 0) for hit in hits) / ideal
                        quality[mode].append((score, sum(hit in labels for hit in hits), len(hits)))

    summary = {}
    for mode in MODES:
        scores, judged, returned = zip(*quality[mode])
        summary[mode] = {
            "mean_ndcg_at_10": statistics.mean(scores),
            "judged_hits": sum(judged),
            "returned_hits": sum(returned),
            "judged_hit_fraction": sum(judged) / max(1, sum(returned)),
            "p95_server_ms": float(np.percentile(times[mode], 95)),
        }
    return {
        "catalog_products": len(products), "catalog_sha256": manifest["catalog_sha256"],
        "examples_sha256": file_hash(examples), "test_queries_sha256": file_hash(test_path),
        "test_queries": len(test), "evaluated_queries": len(queries), "repeats": repeats,
        "settings": {"k": TOP_K, "strategy": "auto", "probes": probes, "hybrid_depth": HYBRID_DEPTH},
        "exact_cost_factor": info["exact_cost_factor"], "gains": GAINS, "results": summary,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--examples", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    print(json.dumps(evaluate(args.dataset, args.examples, args.url, args.repeats), indent=2))


if __name__ == "__main__":
    main()
