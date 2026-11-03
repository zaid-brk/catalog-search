"""Paired before/after retrieval timings on one fixed, already-built index."""
import argparse
from collections import defaultdict
import csv
import gzip
import io
import json
from pathlib import Path
import random
import statistics

import numpy as np

from catalog_search.evaluate import environment, file_hash, jsonl, recall, workloads
from catalog_search.worker import Worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--queries', type=int, default=200)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--probes', type=int, default=32)
    args = parser.parse_args()
    if args.queries < 1 or args.repeats < 1 or not 1 <= args.probes <= 4096:
        parser.error('invalid benchmark options')
    manifest = json.loads((args.dataset / 'manifest.json').read_text())
    if file_hash(args.dataset / 'catalog.jsonl') != manifest['catalog_sha256']:
        raise ValueError('catalog/manifest mismatch')
    products = jsonl(args.dataset / 'products.jsonl')
    queries = jsonl(args.dataset / 'queries-test.jsonl')[:args.queries]
    dev_ids = {q['query_id'] for q in jsonl(args.dataset / 'queries-dev.jsonl')}
    if not queries or any(q['query_id'] in dev_ids for q in queries):
        raise ValueError('empty test set or overlapping dev/test IDs')
    cases = workloads(products)
    configurations = [('exact', 1), ('ivf', args.probes), ('auto', args.probes)]
    rng = random.Random(42)
    rows = []
    verification = {'query_filter_cases': 0, 'cross_version_hit_set_changes': 0,
                    'cross_version_order_changes': 0, 'maximum_shared_hit_score_delta': 0.0,
                    'full_probe_cases_per_version': 0}
    with Worker(args.baseline, args.index) as baseline, Worker(args.candidate, args.index) as candidate:
        workers = {'baseline': baseline, 'candidate': candidate}
        info = candidate.request({'info': True})
        if baseline.request({'info': True}) != info:
            raise ValueError('engines loaded different index metadata')
        if info['products'] != len(products) or info['model_id'] != manifest['model_id']:
            raise ValueError('index/dataset mismatch')
        for query in queries:
            for label, filters in cases:
                request = {**query, **filters, 'k': 10}
                exact = {version: worker.request({**request, 'strategy': 'exact'})
                         for version, worker in workers.items()}
                verification['query_filter_cases'] += 1
                for version, worker in workers.items():
                    full = worker.request({**request, 'strategy': 'ivf', 'probes': info['clusters']})
                    if full['hits'] != exact[version]['hits']:
                        raise ValueError('full-probe IVF differs from exact search')
                verification['full_probe_cases_per_version'] += 1
                # Warm and compare each path before timings. Float scores may
                # change at rounding precision; report both sets and ordering.
                for method, probes in configurations:
                    results = {version: worker.request({**request, 'strategy': method, 'probes': probes})
                               for version, worker in workers.items()}
                    ids = {version: [h['row'] for h in result['hits']] for version, result in results.items()}
                    verification['cross_version_hit_set_changes'] += set(ids['baseline']) != set(ids['candidate'])
                    verification['cross_version_order_changes'] += ids['baseline'] != ids['candidate']
                    before_scores = {h['row']: h['score'] for h in results['baseline']['hits']}
                    for hit in results['candidate']['hits']:
                        if hit['row'] in before_scores:
                            verification['maximum_shared_hit_score_delta'] = max(
                                verification['maximum_shared_hit_score_delta'],
                                abs(hit['score'] - before_scores[hit['row']]))
                for repeat in range(args.repeats):
                    order = configurations.copy()
                    rng.shuffle(order)
                    for method, probes in order:
                        versions = list(workers)
                        rng.shuffle(versions)
                        for version in versions:
                            result = workers[version].request({**request, 'strategy': method, 'probes': probes})
                            rows.append({'query_id': query['query_id'], 'workload': label,
                                         'method': method, 'probes': probes, 'version': version,
                                         'repeat': repeat, 'chosen_strategy': result['strategy'],
                                         'eligible': result['eligible'], 'comparisons': result['comparisons'],
                                         'recall_at_10': recall(result, exact['baseline']),
                                         'retrieval_ms': result['retrieval_ms']})
    groups = defaultdict(list)
    for row in rows:
        groups[(row['workload'], row['method'], row['version'])].append(row)
    summary = []
    for (label, method, version), group in sorted(groups.items()):
        times = [row['retrieval_ms'] for row in group]
        summary.append({'workload': label, 'method': method, 'version': version,
                        'observations': len(group), 'query_count': len({r['query_id'] for r in group}),
                        'p50_ms': float(np.percentile(times, 50)), 'p95_ms': float(np.percentile(times, 95)),
                        'mean_recall_at_10': statistics.mean(row['recall_at_10'] for row in group)})
    env = environment(args.candidate, args.index, args.dataset)
    env['baseline_binary_sha256'] = file_hash(args.baseline)
    env['comparison_script_sha256'] = file_hash(Path(__file__))
    env['candidate_index_source_sha256'] = file_hash(Path('engine/src/index.cpp'))
    env['query_files_sha256'] = {split: file_hash(args.dataset / f'queries-{split}.jsonl') for split in ('dev', 'test')}
    report = {'environment': env, 'index_info': {k: v for k, v in info.items() if k not in ('brands', 'colors')},
              'settings': {'queries': len(queries), 'repeats': args.repeats, 'probes': args.probes, 'k': 10,
                           'seed': 42, 'schedule': 'shuffled methods, randomly ordered baseline/candidate pairs'},
              'workloads': [{'label': label, 'filters': filters,
                             'eligible': sum(all(p[k] == v for k, v in filters.items()) for p in products)}
                            for label, filters in cases],
              'verification': verification, 'summary': summary}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    raw = io.StringIO(newline='')
    writer = csv.DictWriter(raw, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    with gzip.GzipFile(filename=str(args.output / 'raw.csv.gz'), mode='wb', mtime=0) as file:
        file.write(raw.getvalue().encode())
    lines = ['# Paired vector-scoring experiment', '',
             f"{len(products):,} real products; {len(queries)} test queries; three filter workloads; {args.repeats} repeats.", '',
             'One fixed index is shared by both engines. Timings include C++ retrieval only, excluding model inference and transport. Recall is against baseline exact vector neighbors, not shopper relevance.', '',
             '| Workload | Method | Before p50 / p95 ms | After p50 / p95 ms | Median speedup | Before / after recall@10 |',
             '| --- | --- | ---: | ---: | ---: | ---: |']
    for label, _ in cases:
        for method, _ in configurations:
            before = next(r for r in summary if (r['workload'], r['method'], r['version']) == (label, method, 'baseline'))
            after = next(r for r in summary if (r['workload'], r['method'], r['version']) == (label, method, 'candidate'))
            lines.append(f"| {label} | {method} | {before['p50_ms']:.4f} / {before['p95_ms']:.4f} | {after['p50_ms']:.4f} / {after['p95_ms']:.4f} | {before['p50_ms']/after['p50_ms']:.2f}x | {before['mean_recall_at_10']:.4f} / {after['mean_recall_at_10']:.4f} |")
    lines += ['', 'Raw timing rows: `raw.csv.gz`. Configuration, hashes, actual filter counts, numerical checks, and full-precision summaries: `report.json`.', '',
              'These are same-machine observations, not service throughput or a cross-machine performance guarantee. Repeats are not additional independent queries.']
    (args.output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    print(json.dumps(verification, indent=2))


if __name__ == '__main__':
    main()
