# Catalog Search

A product search engine built in C++. I'm using it to explore how vector search works, especially when queries also have filters.

The engine supports exact search and an IVF index that groups similar products together. You can search for a brand to filter by, change how many groups get searched, and compare the results and timings. There's also a simple planner that chooses between checking every eligible product and using the index.

C++ handles indexing, filtering, retrieval, and saving/loading the index. Python handles data preparation and text embeddings using MiniLM. The demo is TypeScript with Vite, with a FastAPI service connecting it to the C++ API.

## Running it

You'll need a C++20 compiler, Boost 1.75+, Python 3.11, and Node 22.12+.

```sh
git clone https://github.com/zaid-brk/catalog-search.git
cd catalog-search
python3 scripts/setup_semantic.py
```

The setup script installs the Python/build dependencies, runs the C++ tests, builds the frontend, and prepares 10,000 products from the [Amazon ESCI dataset](https://github.com/amazon-science/esci-data). It downloads the full source files before sampling, so the first setup involves a large download.

Wait for `Real semantic catalog ready`, then start the app:

```sh
.venv-semantic/bin/python scripts/dev.py --dataset data/esci-10000
```

Open http://127.0.0.1:8000. Ctrl+C stops both services.

The app searches the loaded catalog, not the live internet. The optional brand filter suggests matching brands as you type; leave it blank to search all brands. It doesn't extract constraints like price from your search text.

For a small offline demo after building:

```sh
.venv-semantic/bin/python -m catalog_search.prepare --source fixture --output data/fixture
build/catalog build --input data/fixture/catalog.jsonl --output data/fixture/catalog.csidx --clusters 16
.venv-semantic/bin/python scripts/dev.py
```

That fixture has 216 handwritten products and uses word hashing instead of a language model. The interface labels which mode is running.

## Tests

```sh
.venv-semantic/bin/ctest --test-dir build --output-on-failure
.venv-semantic/bin/python -m unittest discover -s python/tests -v
.venv-semantic/bin/python scripts/smoke_http.py
```

The tests cover ranking, filters, invalid inputs, concurrent reads, index files, and comparison against a NumPy baseline. The HTTP test needs the offline fixture prepared first.

## Benchmarks

The benchmark scripts compare exact search, IVF, and the planner using separate development and test queries. They record recall, latency, comparisons, and the machine/configuration used.

```sh
.venv-semantic/bin/python -m catalog_search.prepare --source synthetic --limit 100000 --output data/synthetic-100k
build/catalog build --input data/synthetic-100k/catalog.jsonl --output data/synthetic-100k/catalog.csidx --clusters 64
.venv-semantic/bin/python -m catalog_search.evaluate --dataset data/synthetic-100k --index data/synthetic-100k/catalog.csidx --output benchmarks/runs/test
```

Saved runs include the original [synthetic experiment](benchmarks/example-synthetic-100k/REPORT.md) and real Amazon ESCI catalogs with [10,000](benchmarks/example-esci-10k/REPORT.md) and [100,000](benchmarks/example-esci-100k/REPORT.md) products. The [real-data results](docs/REAL_DATA_RESULTS.md) explain development-only planner calibration, held-out recall/latency, FAISS references, and reproduction commands. Retrieval timings exclude text encoding and HTTP; recall measures agreement with exact vector neighbors, not shopper relevance.

There's also a small C++ allocation benchmark:

```sh
cmake --build build --target catalog-allocation-bench
build/catalog-allocation-bench data/synthetic-100k/catalog.csidx 200
```

Search now uses `std::span` to read a single filter's existing posting list without copying it. Unfiltered searches skip the eligibility list entirely, and unfiltered IVF also skips the eligibility mask. Combined filters still build a request-local intersection so concurrent searches don't share mutable buffers.

On the 100,000-vector, 64-dimension synthetic index above, using the same benchmark against `fae97e9` and the updated engine:

| Unfiltered search | Requested bytes/query before | After | Allocations before → after |
| --- | ---: | ---: | ---: |
| Exact | 400,752 | 752 | 12 → 11 |
| IVF | 501,264 | 1,264 | 14 → 12 |

These are C++ `new` allocation requests during search, averaged over 200 repetitions of one fixed query in a Release build on macOS with Apple Clang. They exclude index loading and allocator overhead; they aren't peak memory usage or a general latency result. The executable also measures single-brand and single-color filters.

More on the [implementation](docs/ARCHITECTURE.md) and [benchmark measurements](docs/BENCHMARKS.md).
