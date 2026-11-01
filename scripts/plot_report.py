#!/usr/bin/env python3
"""Export recall/latency tradeoffs from a completed experiment."""
import argparse
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("report",type=Path); args=parser.parse_args()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    report=json.loads(args.report.read_text()); rows=report["summary"]
    workloads=sorted({r["workload"] for r in rows})
    figure,axes=plt.subplots(1,len(workloads),figsize=(5*len(workloads),4),squeeze=False)
    for axis,workload in zip(axes[0],workloads):
        for method in sorted({r["method"] for r in rows}):
            points=sorted((r for r in rows if r["workload"]==workload and r["method"]==method),key=lambda r:r["probes"])
            axis.plot([r["mean_recall_at_k"] for r in points],[r["p50_ms"] for r in points],"o-",label=method)
        axis.set(title=workload,xlabel="Recall@k against exact vector search",ylabel="Median retrieval latency (ms)",yscale="log")
        axis.grid(alpha=.2); axis.legend(fontsize=8)
    figure.suptitle(report["environment"]["dataset_manifest"]["provenance"],fontsize=10)
    figure.tight_layout(); figure.savefig(args.report.parent / "recall-latency.png",dpi=180)
    figure.savefig(args.report.parent / "recall-latency.svg")


if __name__=="__main__": main()
