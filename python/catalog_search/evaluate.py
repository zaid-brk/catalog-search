"""Reproducible dev calibration and held-out C++ retrieval experiments."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time

import numpy as np

from .worker import Worker


def jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def workloads(products):
    # Use real metadata distributions; record actual selectivity, never assume 1/10%.
    brands = Counter(p["brand"] for p in products if p["brand"])
    colors = Counter(p["color"] for p in products if p["color"])
    result = [("all", {})]
    for label, field, frequencies, target in (("brand-narrow", "brand", brands, .01), ("color-medium", "color", colors, .1)):
        if frequencies:
            value = min(frequencies, key=lambda key: (abs(frequencies[key] / len(products) - target), key))
            result.append((label, {field: value}))
    return result


def recall(actual, exact):
    expected = {h["row"] for h in exact["hits"]}
    return len({h["row"] for h in actual["hits"]} & expected) / len(expected) if expected else 1.0


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as file:
        while block := file.read(1024 * 1024): h.update(block)
    return h.hexdigest()


def environment(binary, index, dataset):
    try: revision = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except subprocess.CalledProcessError: revision = "uncommitted"
    try: cpu = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError): cpu = platform.processor()
    return {"platform": platform.platform(), "machine": platform.machine(), "cpu": cpu, "logical_cpus": os.cpu_count(), "python": platform.python_version(), "numpy": np.__version__, "git_revision": revision, "binary_sha256": file_hash(binary), "index_sha256": file_hash(index), "index_bytes": index.stat().st_size, "dataset_manifest": json.loads((dataset / "manifest.json").read_text()), "timing_scope": "C++ retrieval_ms; worker transport/encoding excluded; one query at a time, one engine thread", "memory_note": "vector_bytes is vector storage only; not process RSS", "relevance_note": "Recall compares vector neighbors, not shopper relevance. Synthetic data cannot establish real catalog performance."}


def calibrate(worker, info, queries, cases, probes, k, output, min_recall):
    records = []
    for q in queries:
        for label, filters in cases:
            request = {**q, **filters, "k": k, "probes": probes}
            exact = worker.request({**request, "strategy": "exact"})
            ivf = worker.request({**request, "strategy": "ivf"})
            # Warm both paths, then interleave measurements.
            times = {"exact": [], "ivf": []}
            for _ in range(3):
                for method in ("ivf", "exact"):
                    times[method].append(worker.request({**request, "strategy": method})["retrieval_ms"])
            records.append({"query_id": q["query_id"], "workload": label, "eligible": exact["eligible"], "exact_ms": statistics.median(times["exact"]), "ivf_ms": statistics.median(times["ivf"]), "ivf_recall": recall(ivf, exact)})
    work = info["clusters"] + info["products"] * min(probes, info["clusters"]) / max(1, info["clusters"])
    scores = []
    for factor in (.000001, .125, .25, .5, 1, 2, 4, 8, 16):
        total = sum(row["exact_ms"] if row["eligible"] * factor <= work else row["ivf_ms"] for row in records)
        by_workload=defaultdict(list)
        for row in records:
            by_workload[row["workload"]].append(1.0 if row["eligible"] * factor <= work else row["ivf_recall"])
        mean_recalls={key:statistics.mean(values) for key,values in by_workload.items()}
        scores.append({"factor": factor, "total_predicted_ms": total, "mean_recall_by_workload": mean_recalls, "feasible": all(value>=min_recall for value in mean_recalls.values())})
    chosen = min((row for row in scores if row["feasible"]), key=lambda row: row["total_predicted_ms"])["factor"]
    report = {"split": "dev", "recommended_exact_cost_factor": chosen, "probes": probes, "k": k, "minimum_dev_mean_recall_per_workload": min_recall, "objective": "minimize dev retrieval time subject to mean vector recall target in each dev workload", "warning": "A dev recall target is not a guarantee on unseen queries. Factor is workload/hardware/probe specific.", "dev_query_ids": [q["query_id"] for q in queries], "candidate_scores": scores, "records": records}
    output.mkdir(parents=True, exist_ok=True)
    (output / "calibration.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Dev calibration recommends --exact-cost-factor {chosen}. Rebuild the index with that factor before test evaluation.")


def evaluate(args):
    manifest = json.loads((args.dataset / "manifest.json").read_text())
    if file_hash(args.dataset / "catalog.jsonl") != manifest["catalog_sha256"]:
        raise ValueError("Catalog does not match its manifest")
    products = jsonl(args.dataset / "products.jsonl")
    queries = jsonl(args.dataset / f"queries-{'dev' if args.calibrate else 'test'}.jsonl")[:args.queries]
    if not products or not queries: raise ValueError("Benchmark requires nonempty products and queries")
    dev_ids = {q["query_id"] for q in jsonl(args.dataset / "queries-dev.jsonl")}
    if not args.calibrate and any(q["query_id"] in dev_ids for q in queries):
        raise ValueError("Dev/test query IDs overlap")
    args.output.mkdir(parents=True, exist_ok=True)
    cases = workloads(products)
    rng = np.random.default_rng(args.seed)
    rows = []
    ground_truth = {}
    with Worker(args.binary, args.index) as worker:
        info = worker.request({"info": True})
        if info["model_id"] != manifest["model_id"] or info["products"] != len(products): raise ValueError("Index/dataset mismatch")
        if args.calibrate:
            calibrate(worker, info, queries, cases, args.probes[0], args.k, args.output, args.min_recall)
            return
        for query in queries:
            for label, filters in cases:
                base = {**query, **filters, "k": args.k}
                exact = worker.request({**base, "strategy": "exact"})
                ground_truth[(query["query_id"],label)]={hit["row"] for hit in exact["hits"]}
                configs = [("exact", 1)] + [(method, probes) for method in ("ivf", "auto") for probes in args.probes]
                for method, probes in configs: worker.request({**base, "strategy": method, "probes": probes})
                for repeat in range(args.repeats):
                    for position in rng.permutation(len(configs)):
                        method, probes = configs[position]
                        started = time.perf_counter()
                        result = worker.request({**base, "strategy": method, "probes": probes})
                        wall = (time.perf_counter() - started) * 1000
                        rows.append({"query_id": query["query_id"], "workload": label, "method": method, "probes": probes, "repeat": repeat, "chosen_strategy": result["strategy"], "eligible": result["eligible"], "selectivity": result["eligible"] / max(1,len(products)), "recall_at_k": recall(result,exact), "retrieval_ms": result["retrieval_ms"], "worker_roundtrip_ms": wall, "comparisons": result["comparisons"], "clusters_searched": result["clusters_searched"]})
        if args.faiss:
            rows.extend(faiss_rows(args, products, queries, cases, ground_truth))
    with (args.output / "raw.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    groups = defaultdict(list)
    for row in rows: groups[(row["workload"], row["method"], row["probes"])].append(row)
    summary = []
    for (label, method, probes), group in sorted(groups.items()):
        timings = [r["retrieval_ms"] for r in group]
        summary.append({"workload": label, "method": method, "probes": probes, "observations": len(group), "query_count": len({r["query_id"] for r in group}), "mean_recall_at_k": statistics.mean(r["recall_at_k"] for r in group), "p50_ms": float(np.percentile(timings,50)), "p95_ms": float(np.percentile(timings,95)), "selectivity": group[0]["selectivity"], "mean_comparisons": statistics.mean(r["comparisons"] for r in group)})
    env=environment(args.binary,args.index,args.dataset)
    if args.faiss:
        import faiss
        env["faiss_version"]=faiss.__version__
        env["faiss_scope"]="Search-kernel reference: separately trained per-filter indexes; timings exclude filter selection/copying, unlike C++ timings. Not an end-to-end performance comparison. No claim of beating FAISS."
    report = {"environment": env, "index_info": info, "settings": {"k":args.k,"probes":args.probes,"repeats":args.repeats,"queries":len(queries),"seed":args.seed,"faiss":args.faiss}, "summary":summary}
    (args.output / "report.json").write_text(json.dumps(report,indent=2)+"\n")
    lines = ["# Retrieval experiment", "", f"Dataset: {manifest['provenance']}", "", "One query at a time. Timings exclude embeddings and transport. Recall is agreement with exact vector neighbors, not human relevance.", "", "| Workload | Method | Probes | Recall@k | p50 ms | p95 ms |", "|---|---|---:|---:|---:|---:|"]
    for r in summary: lines.append(f"| {r['workload']} | {r['method']} | {r['probes']} | {r['mean_recall_at_k']:.3f} | {r['p50_ms']:.4f} | {r['p95_ms']:.4f} |")
    lines += ["", "Full environment, hashes, configuration, and individual observations are in report.json and raw.csv.", "Vector byte counts exclude metadata, cluster storage, allocator overhead, and process runtime. These results do not establish deployed service throughput."]
    if args.faiss: lines += ["",env["faiss_scope"]]
    (args.output / "REPORT.md").write_text("\n".join(lines)+"\n")
    print("\n".join(lines))


def faiss_rows(args, products, queries, cases, ground_truth):
    import faiss
    faiss.omp_set_num_threads(1)
    vectors = np.load(args.dataset / "vectors.npy").astype(np.float32)
    records=[]
    for label, filters in cases:
        ids=np.array([i for i,p in enumerate(products) if all(p[key]==value for key,value in filters.items())],dtype=np.int64)
        if not len(ids): continue
        subset=np.ascontiguousarray(vectors[ids]); dimensions=subset.shape[1]
        flat=faiss.IndexFlatIP(dimensions); flat.add(subset)
        count=min(64,max(1,len(ids)//40))
        ivf=faiss.IndexIVFFlat(faiss.IndexFlatIP(dimensions),dimensions,count,faiss.METRIC_INNER_PRODUCT)
        ivf.train(subset); ivf.add(subset)
        for query in queries:
            q=np.array([query["vector"]],dtype=np.float32); q/=np.linalg.norm(q,axis=1,keepdims=True)
            k=min(args.k,len(ids)); expected_set=ground_truth[(query["query_id"],label)]
            for name,index in (("faiss-flat",flat),("faiss-ivf-prefilter",ivf)):
                for probes in ([1] if name=="faiss-flat" else args.probes):
                    if name!="faiss-flat": index.nprobe=min(probes,count)
                    index.search(q,k)
                    for repeat in range(args.repeats):
                        start=time.perf_counter(); _,found=index.search(q,k); elapsed=(time.perf_counter()-start)*1000
                        actual=set(ids[found[0][found[0]>=0]])
                        records.append({"query_id":query["query_id"],"workload":label,"method":name,"probes":probes,"repeat":repeat,"chosen_strategy":name,"eligible":len(ids),"selectivity":len(ids)/len(products),"recall_at_k":len(actual & expected_set)/len(expected_set),"retrieval_ms":elapsed,"worker_roundtrip_ms":elapsed,"comparisons":-1,"clusters_searched":-1})
    # FAISS uses separately built per-filter indexes. Its timings exclude filter
    # selection/copying and are a search-kernel reference, NOT an end-to-end win.
    return records


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--dataset",type=Path,required=True); parser.add_argument("--index",type=Path,required=True)
    parser.add_argument("--binary",type=Path,default=Path("build/catalog")); parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--queries",type=int,default=60); parser.add_argument("--repeats",type=int,default=3)
    parser.add_argument("--probes",type=int,nargs="+",default=[1,4,8,16,64]); parser.add_argument("--k",type=int,default=10)
    parser.add_argument("--seed",type=int,default=42); parser.add_argument("--calibrate",action="store_true"); parser.add_argument("--faiss",action="store_true")
    parser.add_argument("--min-recall",type=float,default=.95)
    args=parser.parse_args()
    if args.queries<1 or args.repeats<1 or not 1<=args.k<=1000 or not 0<=args.min_recall<=1 or any(p<1 or p>4096 for p in args.probes): parser.error("invalid benchmark size/options")
    evaluate(args)


if __name__=="__main__": main()
