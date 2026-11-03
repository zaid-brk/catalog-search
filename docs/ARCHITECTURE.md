# How the engine works

The catalog is stored as a flat array of normalized float vectors, with product metadata alongside it. Similarity is a dot product accumulated through four independent partial sums, with a scalar tail for other dimensions. This permits compiler SIMD optimization; score rounding can differ from a serial sum. Each product has an external ID and an internal row number used by the indexes.

## Search

Exact search checks every product that meets the filters. A small heap keeps the best k results without sorting the whole catalog. Ties use the smaller row number so results are repeatable.

IVF uses spherical k-means to group vectors. At query time it ranks the group centroids, visits the requested number of groups, and checks eligible products in those groups. Searching more groups usually improves recall but costs more work. Searching every group should match exact search.

Brand and color each have sorted posting lists. Single-field filters borrow a read-only `std::span` of an existing list; combined filters intersect the lists into a request-local vector. Unfiltered exact search walks row numbers directly. Filtered IVF uses a per-query mask to check whether a candidate is eligible before calculating its score; unfiltered IVF skips that mask.

The planner compares an estimate of exact-search work with the cost of scanning centroids and selected groups. Its coefficient can be calibrated on development queries. It's a heuristic: uneven groups and memory access can make it choose the slower path. Calibration and test evaluation use different queries.

## Files and concurrency

The binary index contains the products, vectors, centroids, posting lists, model fingerprint, and planner coefficient. It has a version and a checksum. The loader checks sizes, normalized finite vectors, IDs, membership, and corruption before accepting it. The checksum detects accidental corruption; it isn't cryptographic authentication.

Saving writes a temporary file and renames it. There is no transactional or fsync-based durability guarantee. The format is limited to 2 GiB.

The index stays unchanged while serving requests. Each search has its own heap and temporary buffers, so readers can share one index. Updating the catalog requires rebuilding it.

## App

The Python gateway turns text into an embedding and sends the vector and filters to the C++ HTTP API. Both sides check the model fingerprint to avoid mixing incompatible embeddings. Boost.Beast handles HTTP and Boost.JSON handles JSON. The server has a fixed worker pool, bounded queued work, and request deadlines.

The frontend shows results and separates encoding time from C++ retrieval time. A persistent CLI worker runs the same search handler for benchmarks without HTTP or model inference.

This is a single-machine CPU engine. It doesn't include concurrent writes, replication, natural-language filter parsing, or a trained custom embedding model.
