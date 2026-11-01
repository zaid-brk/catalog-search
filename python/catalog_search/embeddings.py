"""Keep product/query embeddings compatible and record exactly what made them."""
import hashlib
import json
import re
from pathlib import Path

import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
STOPWORDS = {"a", "an", "the", "for", "of", "and", "to", "with", "me", "something", "i", "want", "in", "my"}


def normalize_label(value: str) -> str:
    return value.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")).strip(" \t\r\n")


def model_identity(config: dict) -> str:
    fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
    return f"{config['encoder']}:{fingerprint}"


def product_text(product: dict) -> str:
    return f"{product['title']}\n{product.get('description', '')}"[:4096]


class Encoder:
    def __init__(self, config: dict, *, model_path: str | None = None):
        self.config = config
        self.model_id = model_identity(config)
        self.model = None
        if config["encoder"] == "minilm":
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(model_path or config["name"], revision=None if model_path else config["revision"], trust_remote_code=False)
            self.model.max_seq_length = config["max_seq_length"]
        elif config["encoder"] != "hash-fixture":
            raise ValueError("This dataset cannot encode text queries")

    def encode(self, texts: list[str]) -> np.ndarray:
        if self.model is not None:
            return self.model.encode(texts, batch_size=64, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=len(texts) > 100).astype(np.float32)
        # Offline test fixture ONLY. This is lexical hashing, not semantic AI.
        vectors = np.zeros((len(texts), self.config["dimensions"]), dtype=np.float32)
        for row, text in enumerate(texts):
            tokens = [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]
            if not tokens:
                raise ValueError("Enter a query containing searchable words")
            for token in tokens:
                digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
                bucket = int.from_bytes(digest[:4], "little") % vectors.shape[1]
                vectors[row, bucket] += 1 if digest[4] & 1 else -1
            norm = np.linalg.norm(vectors[row])
            if not norm:
                raise ValueError("Query produced an empty vector")
            vectors[row] /= norm
        return vectors


def fixture_config() -> dict:
    return {"encoder": "hash-fixture", "dimensions": 384, "version": 1, "text_recipe": "title-description-4096-v1", "normalization": "l2"}


def semantic_config(revision: str | None = None) -> dict:
    # Resolve main ONCE and persist an immutable revision for queries/rebuilds.
    from huggingface_hub import model_info
    revision = model_info(MODEL_NAME, revision=revision or "main").sha
    if not revision:
        raise RuntimeError("Could not resolve model revision")
    return {"encoder": "minilm", "name": MODEL_NAME, "revision": revision, "dimensions": 384, "max_seq_length": 256, "text_recipe": "title-description-4096-v1", "normalization": "l2"}
