"""BM25 title search and reciprocal rank fusion for the text gateway."""
from collections import Counter, defaultdict
import heapq
import math
import re

from .embeddings import normalize_label

MODES = ("keyword", "semantic", "hybrid")
HYBRID_DEPTH = 50
TOKEN = re.compile(r"[^\W_]+")


class TitleIndex:
    def __init__(self, products):
        self.products = []
        self.postings = defaultdict(list)
        self.filter_counts = Counter()
        lengths = []
        ids = set()
        for row, product in enumerate(products):
            product_id = product["id"]
            if not product_id or product_id in ids:
                raise ValueError("Product IDs must be unique and nonempty")
            ids.add(product_id)
            brand = normalize_label(product["brand"])
            color = normalize_label(product["color"])
            self.products.append({**product, "brand": brand, "color": color, "row": row})
            self.filter_counts.update({("", ""), (brand, ""), ("", color), (brand, color)})
            counts = Counter(TOKEN.findall(product["title"].casefold()))
            lengths.append(sum(counts.values()))
            for term, frequency in counts.items():
                self.postings[term].append((row, frequency))

        # BM25 with k1=1.2 and b=0.75. IDF stays fixed across metadata filters.
        average = sum(lengths) / max(1, len(lengths)) or 1
        self.norms = [1.2 * (0.25 + 0.75 * length / average) for length in lengths]
        self.idf = {
            term: math.log1p((len(lengths) - len(rows) + 0.5) / (len(rows) + 0.5))
            for term, rows in self.postings.items()
        }

    def search(self, query, k, brand="", color=""):
        brand, color = normalize_label(brand), normalize_label(color)
        scores = defaultdict(float)
        for term in dict.fromkeys(TOKEN.findall(query.casefold())):
            for row, frequency in self.postings.get(term, ()):
                product = self.products[row]
                if (brand and product["brand"] != brand) or (color and product["color"] != color):
                    continue
                scores[row] += self.idf[term] * frequency * 2.2 / (frequency + self.norms[row])
        ranked = heapq.nsmallest(k, scores, key=lambda row: (-scores[row], row))
        return [{**self.products[row], "score": scores[row]} for row in ranked], self.filter_counts[brand, color]


def fuse_rankings(keyword_hits, vector_hits, k):
    scores = defaultdict(float)
    products = {}
    for hits in (keyword_hits, vector_hits):
        for rank, hit in enumerate(hits, 1):
            product_id = hit["id"]
            products[product_id] = hit
            scores[product_id] += 1 / (60 + rank)
    ranked = heapq.nsmallest(k, scores, key=lambda product_id: (-scores[product_id], product_id))
    return [{**products[product_id], "score": scores[product_id]} for product_id in ranked]
