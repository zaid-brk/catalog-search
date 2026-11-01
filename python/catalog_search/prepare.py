"""Prepare real ESCI data, an honest offline UI fixture, or synthetic experiments."""
import argparse
import hashlib
import heapq
import html
import json
from pathlib import Path
import platform
import re
import urllib.request

import numpy as np

from .embeddings import Encoder, fixture_config, model_identity, normalize_label, product_text, semantic_config

ESCI_BASE = "https://media.githubusercontent.com/media/amazon-science/esci-data/main/shopping_queries_dataset/"


def download(name: str, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    if path.exists():
        return path
    temporary = path.with_suffix(".part")
    try:
        with urllib.request.urlopen(ESCI_BASE + name, timeout=60) as source, temporary.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
        with temporary.open("rb") as downloaded:
            magic = downloaded.read(4)
        if magic != b"PAR1":
            raise ValueError("Download is not Parquet (possibly a Git LFS pointer)")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def fixture_products() -> list[dict]:
    items = [
        ("Waterproof hiking jacket", "Lightweight rain shell with hood for wet trails and outdoor walks."),
        ("Insulated winter coat", "Warm padded coat for freezing weather and snowy commutes."),
        ("Trail running shoes", "Breathable running footwear with grippy soles for muddy trails."),
        ("Waterproof hiking boots", "Ankle support and water protection for mountain hiking."),
        ("Travel backpack", "Lightweight cabin backpack with laptop pocket for flights and commuting."),
        ("Camping sleeping bag", "Warm insulated sleeping bag for overnight camping outdoors."),
        ("Camping tent", "Portable waterproof shelter for two people with rain cover."),
        ("Insulated water bottle", "Reusable steel bottle keeps drinking water cool during hikes."),
        ("Wireless headphones", "Over ear headphones with noise cancellation for music and travel."),
        ("Mechanical keyboard", "Quiet tactile keyboard for typing and desktop computer work."),
        ("Laptop stand", "Adjustable desk stand raises a laptop screen for comfortable work."),
        ("USB charging cable", "Durable braided USB cable for charging phones and accessories."),
        ("Portable phone charger", "Compact battery power bank for charging a phone while traveling."),
        ("Yoga exercise mat", "Non slip padded mat for stretching yoga and home workouts."),
        ("Running shorts", "Quick dry breathable shorts for summer running and training."),
        ("Cotton everyday shirt", "Soft breathable cotton shirt for casual daily wear."),
        ("Ceramic coffee mug", "Reusable ceramic cup for hot tea and coffee at home."),
        ("Coffee travel tumbler", "Insulated leak resistant travel cup keeps coffee warm."),
        ("Reading desk lamp", "Adjustable LED lamp for reading studying and desk work."),
        ("Garden work gloves", "Protective gloves for gardening planting and yard work."),
        ("Rain umbrella", "Compact folding umbrella for rain protection while walking."),
        ("Cycling helmet", "Lightweight vented protective helmet for bicycle riding."),
        ("Beach towel", "Absorbent cotton towel for swimming beach trips and pool days."),
        ("Kitchen storage containers", "Stackable food containers with lids for meal preparation."),
    ]
    products = []
    for i, (title, description) in enumerate(items):
        for color in ("blue", "black", "red"):
            for brand in ("trailworks", "everyday", "summit"):
                products.append({"id": f"fixture-{i}-{color}-{brand}", "title": f"{title} — {color}", "description": description, "brand": brand, "color": color})
    return products


def sample_esci_products(path: Path, limit: int, seed: int):
    """Scan Parquet in bounded batches instead of expanding a 1GB file in RAM."""
    import pyarrow.parquet as pq
    file=pq.ParquetFile(path)
    columns=["product_id","product_locale","product_title","product_description","product_bullet_point","product_brand","product_color"]
    if missing := set(columns)-set(file.schema.names): raise ValueError(f"Missing ESCI columns: {sorted(missing)}")
    seen=set(); selected=[]
    def clean(value): return html.unescape(re.sub(r"<[^>]*>"," ",str(value or ""))).strip()
    for batch in file.iter_batches(batch_size=8192,columns=columns):
        for row in batch.to_pylist():
            if row["product_locale"]!="us": continue
            product_id=str(row["product_id"] or "").strip(); title=clean(row["product_title"])
            if not product_id or not title or product_id in seen: continue
            seen.add(product_id)
            # Lowest deterministic hashes form a stable sample, independent of row order.
            priority=int.from_bytes(hashlib.blake2b(f"{seed}:{product_id}".encode(),digest_size=8).digest(),"big")
            if len(selected)>=limit and priority>=-selected[0][0]: continue
            product={"id":product_id,"title":title,"description":clean(str(row["product_bullet_point"] or "")+" "+str(row["product_description"] or ""))[:8000],"brand":normalize_label(str(row["product_brand"] or "")),"color":normalize_label(str(row["product_color"] or ""))}
            entry=(-priority,product_id,product)
            if len(selected)<limit: heapq.heappush(selected,entry)
            else: heapq.heapreplace(selected,entry)
    products=sorted((row[2] for row in selected),key=lambda p:p["id"])
    if not products: raise ValueError("No usable US products")
    return products,{"source_rows":file.metadata.num_rows,"eligible_unique_products":len(seen),"selected_products":len(products),"missing_brand":sum(not p["brand"] for p in products),"missing_color":sum(not p["color"] for p in products),"sampling":"lowest blake2b(seed:product_id) hashes"}


def sample_esci_queries(path: Path, product_ids: set[str]):
    import pyarrow.parquet as pq
    file=pq.ParquetFile(path); selected={"train":{},"test":{}}
    for batch in file.iter_batches(batch_size=16384,columns=["product_id","product_locale","query_id","query","split"]):
        for row in batch.to_pylist():
            if row["product_locale"]=="us" and row["product_id"] in product_ids and row["split"] in selected and row["query"]:
                selected[row["split"]][str(row["query_id"])]=str(row["query"])
    # A query seen in test is never used for dev calibration.
    for query_id in selected["test"]: selected["train"].pop(query_id,None)
    return {split:sorted(values.items())[:200] for split,values in selected.items()}


def write_dataset(output: Path, products: list[dict], vectors: np.ndarray, config: dict, provenance: str, queries: dict[str, list[dict]], report: dict):
    output.mkdir(parents=True, exist_ok=True)
    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.shape != (len(products), config["dimensions"]) or not np.isfinite(vectors).all():
        raise ValueError("Invalid embedding matrix")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(norms <= 0):
        raise ValueError("Zero vectors are not supported")
    vectors = vectors / norms
    identity = model_identity(config)
    with (output / "catalog.jsonl").open("w") as file:
        file.write(json.dumps({"dimensions": vectors.shape[1], "model_id": identity, "provenance": provenance}) + "\n")
        for product, vector in zip(products, vectors):
            file.write(json.dumps({**product, "vector": vector.tolist()}, ensure_ascii=False, allow_nan=False) + "\n")
    with (output / "products.jsonl").open("w") as file:
        for p in products:
            file.write(json.dumps(p, ensure_ascii=False) + "\n")
    np.save(output / "vectors.npy", vectors)
    for split, rows in queries.items():
        with (output / f"queries-{split}.jsonl").open("w") as file:
            for q in rows:
                file.write(json.dumps({**q, "model_id": identity}, allow_nan=False) + "\n")
    digest = hashlib.sha256()
    with (output / "catalog.jsonl").open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    manifest = {"format_version": 1, "encoder": config, "model_id": identity, "provenance": provenance, "products": len(products), "dimensions": vectors.shape[1], "catalog_sha256": digest.hexdigest(), "python": platform.python_version(), "numpy": np.__version__, "report": report}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


def synthetic(n: int, seed: int, dimensions=64):
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(32, dimensions))
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)
    vectors = centers[rng.integers(0, len(centers), n)] + rng.normal(0, .10, (n, dimensions))
    # Nested groups create 1%, 10%, and 100% eligibility workloads.
    products = [{"id": f"s-{i}", "title": f"Synthetic vector {i}", "description": "Generated benchmark fixture; not a real product.", "brand": "rare" if i % 100 == 0 else "common", "color": "blue" if i % 10 == 0 else "black"} for i in range(n)]
    queries = {}
    for split in ("dev", "test"):
        queries[split] = []
        for i in range(60):
            vector = centers[rng.integers(len(centers))] + rng.normal(0, .1, dimensions)
            queries[split].append({"query_id": f"{split}-{i}", "vector": vector.tolist()})
    config = {"encoder": "synthetic", "dimensions": dimensions, "seed": seed, "generator_version": 1}
    return products, vectors, config, queries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["fixture", "synthetic", "esci"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--products", type=Path)
    parser.add_argument("--examples", type=Path)
    parser.add_argument("--revision")
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000000:
        parser.error("limit must be 1..1000000")
    if args.source == "synthetic":
        products, vectors, config, queries = synthetic(args.limit, args.seed)
        write_dataset(args.output, products, vectors, config, "synthetic clustered vectors; no real products or semantic claims", queries, {"seed": args.seed})
        return
    if args.source == "fixture":
        products = fixture_products()[:args.limit]; config = fixture_config(); report = {"handwritten_products": len(products)}
        provenance = "handwritten offline fixture; lexical hashing, not semantic embeddings"
        texts = ["waterproof hiking jacket", "warm coat for winter", "wireless headphones for travel", "coffee cup", "running shoes", "camping tent"]
        encoder = Encoder(config)
        queries = {"dev": [{"query_id": f"fixture-dev-{i}", "text": text, "vector": v.tolist()} for i, (text, v) in enumerate(zip(texts[:3], encoder.encode(texts[:3])))], "test": [{"query_id": f"fixture-test-{i}", "text": text, "vector": v.tolist()} for i, (text, v) in enumerate(zip(texts[3:], encoder.encode(texts[3:])))]}
    else:
        raw = args.output.parent / "raw"
        product_file = args.products or download("shopping_queries_dataset_products.parquet", raw)
        example_file = args.examples or download("shopping_queries_dataset_examples.parquet", raw)
        products, report = sample_esci_products(product_file, args.limit, args.seed)
        config = semantic_config(args.revision); encoder = Encoder(config)
        provenance = "Amazon ESCI US products; MiniLM embeddings; see manifest and dataset source"
        ids = {p["id"] for p in products}
        examples = sample_esci_queries(example_file, ids)
        queries = {}
        for output_split, source_split in (("dev", "train"), ("test", "test")):
            pairs=examples[source_split]
            if not pairs: raise ValueError(f"No {output_split} queries for selected products; increase --limit")
            texts = [text for _,text in pairs]
            query_vectors = encoder.encode(texts)
            queries[output_split] = [{"query_id": i, "text": text, "vector": v.tolist()} for (i,text),v in zip(pairs, query_vectors)]
        report.update({"seed": args.seed, "query_dev_count": len(queries["dev"]), "query_test_count": len(queries["test"])})
    vectors = encoder.encode([product_text(p) for p in products])
    write_dataset(args.output, products, vectors, config, provenance, queries, report)


if __name__ == "__main__":
    main()
