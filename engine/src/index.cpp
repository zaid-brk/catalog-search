#include "catalog/index.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cmath>
#include <cctype>
#include <fstream>
#include <iterator>
#include <limits>
#include <numeric>
#include <queue>
#include <random>
#include <stdexcept>
#include <unordered_set>

namespace catalog {
static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559,
              "Index format requires IEEE-754 32-bit floats");
namespace {
using Clock = std::chrono::steady_clock;
constexpr std::size_t kMaxFile = 2ULL * 1024 * 1024 * 1024;
constexpr std::size_t kMaxString = 1024 * 1024;
constexpr std::size_t kMaxDimensions = 4096;
constexpr std::size_t kMaxClusters = 4096;
using Bytes = std::vector<std::uint8_t>;

bool better(const Hit& a, const Hit& b) {
  return a.score > b.score || (a.score == b.score && a.row < b.row);
}
struct Better {
  bool operator()(const Hit& a, const Hit& b) const { return better(a, b); }
};

void u32(Bytes& out, std::uint32_t v) {
  for (unsigned i = 0; i < 4; ++i) out.push_back(static_cast<std::uint8_t>(v >> (8 * i)));
}
void u64(Bytes& out, std::uint64_t v) {
  for (unsigned i = 0; i < 8; ++i) out.push_back(static_cast<std::uint8_t>(v >> (8 * i)));
}
void string(Bytes& out, const std::string& s) {
  if (s.size() > kMaxString) throw std::invalid_argument("metadata string too long");
  u32(out, static_cast<std::uint32_t>(s.size()));
  out.insert(out.end(), s.begin(), s.end());
}
std::uint64_t checksum(std::span<const std::uint8_t> bytes) {
  std::uint64_t h = 14695981039346656037ULL;
  for (auto b : bytes) { h ^= b; h *= 1099511628211ULL; }
  return h;
}
struct Reader {
  std::span<const std::uint8_t> bytes;
  std::size_t pos = 0;
  void need(std::size_t n) const {
    if (n > bytes.size() - pos) throw std::runtime_error("truncated index");
  }
  std::uint32_t read32() {
    need(4); std::uint32_t v = 0;
    for (unsigned i = 0; i < 4; ++i) v |= std::uint32_t(bytes[pos++]) << (8 * i);
    return v;
  }
  std::uint64_t read64() {
    need(8); std::uint64_t v = 0;
    for (unsigned i = 0; i < 8; ++i) v |= std::uint64_t(bytes[pos++]) << (8 * i);
    return v;
  }
  float readfloat() {
    float v = std::bit_cast<float>(read32());
    if (!std::isfinite(v)) throw std::runtime_error("non-finite index vector");
    return v;
  }
  std::string readstring() {
    auto n = read32();
    if (n > kMaxString) throw std::runtime_error("metadata string too long");
    need(n);
    std::string s(reinterpret_cast<const char*>(bytes.data() + pos), n);
    pos += n; return s;
  }
};

template <class Map> std::vector<std::string> keys(const Map& map) {
  std::vector<std::string> out;
  for (const auto& [key, _] : map) if (!key.empty()) out.push_back(key);
  std::sort(out.begin(), out.end()); return out;
}
}  // namespace

float dot(std::span<const float> a, std::span<const float> b) {
  if (a.size() != b.size()) throw std::invalid_argument("dimension mismatch");
  float total = 0;
  for (std::size_t i = 0; i < a.size(); ++i) total += a[i] * b[i];
  return total;
}

std::vector<float> normalized(std::span<const float> values) {
  double squared = 0;
  for (float v : values) {
    if (!std::isfinite(v)) throw std::invalid_argument("vector contains non-finite values");
    squared += static_cast<double>(v) * v;
  }
  if (values.empty() || squared <= 0) throw std::invalid_argument("vector must be nonzero");
  double norm = std::sqrt(squared);
  std::vector<float> out; out.reserve(values.size());
  for (float v : values) out.push_back(static_cast<float>(v / norm));
  return out;
}

std::string normalize_label(std::string value) {
  // ASCII-only normalization is shared with Python; non-ASCII bytes are retained.
  for (char& c : value) if (c >= 'A' && c <= 'Z') c = static_cast<char>(c + ('a' - 'A'));
  auto space = [](unsigned char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; };
  auto first = std::find_if_not(value.begin(), value.end(), space);
  auto last = std::find_if_not(value.rbegin(), value.rend(), space).base();
  return first < last ? std::string(first, last) : "";
}

Index Index::build(std::vector<Product> products, std::vector<float> vectors,
                   std::size_t dimensions, std::string model_id,
                   std::string provenance, const BuildOptions& options) {
  if (dimensions == 0 || dimensions > kMaxDimensions || products.size() > 10000000 ||
      vectors.size() != products.size() * dimensions)
    throw std::invalid_argument("invalid vector shape (dimensions 1..4096, rows <= 10M)");
  if (!options.clusters || options.clusters > kMaxClusters || !options.iterations ||
      !options.training_samples || !std::isfinite(options.exact_cost_factor) ||
      options.exact_cost_factor <= 0)
    throw std::invalid_argument("invalid build options");
  if (model_id.empty()) throw std::invalid_argument("model_id is required");
  Index index;
  index.dimensions_ = dimensions;
  index.model_id_ = std::move(model_id);
  index.provenance_ = std::move(provenance);
  index.exact_cost_factor_ = options.exact_cost_factor;
  index.products_ = std::move(products);
  index.vectors_ = std::move(vectors);
  std::unordered_set<std::string> ids;
  for (std::size_t i = 0; i < index.size(); ++i) {
    auto& p = index.products_[i];
    if (p.id.empty() || !ids.insert(p.id).second) throw std::invalid_argument("product IDs must be unique and nonempty");
    p.brand = normalize_label(p.brand); p.color = normalize_label(p.color);
    for (const auto* s : {&p.id, &p.title, &p.description, &p.brand, &p.color})
      if (s->size() > kMaxString) throw std::invalid_argument("metadata string too long");
    auto v = normalized(std::span(index.vectors_).subspan(i * dimensions, dimensions));
    std::copy(v.begin(), v.end(), index.vectors_.begin() + static_cast<std::ptrdiff_t>(i * dimensions));
  }
  index.build_metadata();
  if (index.size() == 0) return index;
  std::size_t samples = std::min(options.training_samples, index.size());
  std::size_t count = std::min(options.clusters, samples);
  std::mt19937 rng(options.seed);
  std::vector<std::uint32_t> order(index.size());
  std::iota(order.begin(), order.end(), 0);
  std::shuffle(order.begin(), order.end(), rng);
  order.resize(samples);
  auto row = [&](std::uint32_t i) { return std::span(index.vectors_).subspan(std::size_t(i) * dimensions, dimensions); };
  index.centroids_.reserve(count * dimensions);
  for (std::size_t c = 0; c < count; ++c) {
    auto v = row(order[c]); index.centroids_.insert(index.centroids_.end(), v.begin(), v.end());
  }
  auto nearest = [&](std::span<const float> v) {
    std::size_t best = 0; float score = -std::numeric_limits<float>::infinity();
    for (std::size_t c = 0; c < count; ++c) {
      float s = dot(v, std::span(index.centroids_).subspan(c * dimensions, dimensions));
      if (s > score) { score = s; best = c; }
    }
    return best;
  };
  // Spherical k-means: cosine similarity throughout training and retrieval.
  for (std::size_t it = 0; it < options.iterations; ++it) {
    std::vector<double> sums(count * dimensions, 0);
    std::vector<std::size_t> counts(count, 0);
    for (auto i : order) {
      auto v = row(i); auto c = nearest(v); ++counts[c];
      for (std::size_t d = 0; d < dimensions; ++d) sums[c * dimensions + d] += v[d];
    }
    for (std::size_t c = 0; c < count; ++c) {
      double squared = 0;
      for (std::size_t d = 0; d < dimensions; ++d) squared += sums[c * dimensions + d] * sums[c * dimensions + d];
      if (!counts[c] || squared < 1e-20) {
        auto v = row(order[rng() % samples]);
        std::copy(v.begin(), v.end(), index.centroids_.begin() + static_cast<std::ptrdiff_t>(c * dimensions));
      } else {
        double norm = std::sqrt(squared);
        for (std::size_t d = 0; d < dimensions; ++d)
          index.centroids_[c * dimensions + d] = static_cast<float>(sums[c * dimensions + d] / norm);
      }
    }
  }
  index.lists_.resize(count);
  for (std::size_t i = 0; i < index.size(); ++i)
    index.lists_[nearest(row(static_cast<std::uint32_t>(i)))].push_back(static_cast<std::uint32_t>(i));
  return index;
}

void Index::build_metadata() {
  brands_.clear(); colors_.clear();
  for (std::size_t i = 0; i < size(); ++i) {
    brands_[products_[i].brand].push_back(static_cast<std::uint32_t>(i));
    colors_[products_[i].color].push_back(static_cast<std::uint32_t>(i));
  }
}

std::vector<std::uint32_t> Index::eligible_rows(const Filter& filter) const {
  auto brand = normalize_label(filter.brand), color = normalize_label(filter.color);
  if (brand.empty() && color.empty()) {
    std::vector<std::uint32_t> rows(size()); std::iota(rows.begin(), rows.end(), 0); return rows;
  }
  const std::vector<std::uint32_t>* b = nullptr;
  const std::vector<std::uint32_t>* c = nullptr;
  if (!brand.empty()) { auto it = brands_.find(brand); if (it == brands_.end()) return {}; b = &it->second; }
  if (!color.empty()) { auto it = colors_.find(color); if (it == colors_.end()) return {}; c = &it->second; }
  if (!b) return *c;
  if (!c) return *b;
  std::vector<std::uint32_t> result;
  result.reserve(std::min(b->size(), c->size()));
  std::set_intersection(b->begin(), b->end(), c->begin(), c->end(), std::back_inserter(result));
  return result;
}

SearchResult Index::search(std::span<const float> query, const SearchOptions& options) const {
  auto start = Clock::now();
  if (query.size() != dimensions_) throw std::invalid_argument("query dimension mismatch");
  if (options.k == 0 || options.k > 1000 || options.probes == 0)
    throw std::invalid_argument("k must be 1..1000 and probes must be positive");
  auto q = normalized(query);
  SearchResult out;
  auto eligible = eligible_rows(options.filter); out.eligible = eligible.size();
  std::size_t probes = std::min(options.probes, clusters());
  // Estimate dot products, including centroid comparisons. Metadata/list overhead
  // is intentionally approximate; benchmarks calibrate the factor on dev queries.
  double ivf_work = static_cast<double>(clusters()) +
      static_cast<double>(size()) * static_cast<double>(probes) / std::max<std::size_t>(1, clusters());
  bool exact = options.strategy == Strategy::Exact || clusters() == 0 ||
      (options.strategy == Strategy::Auto && static_cast<double>(eligible.size()) * exact_cost_factor_ <= ivf_work);
  out.strategy = exact ? "exact" : "ivf";
  std::size_t k = std::min(options.k, eligible.size());
  std::priority_queue<Hit, std::vector<Hit>, Better> heap;
  auto consider = [&](std::uint32_t i) {
    float s = dot(q, std::span(vectors_).subspan(std::size_t(i) * dimensions_, dimensions_));
    ++out.comparisons;
    Hit h{i, s};
    if (heap.size() < k) heap.push(h);
    else if (better(h, heap.top())) { heap.pop(); heap.push(h); }
  };
  if (k) {
    if (exact) for (auto i : eligible) consider(i);
    else {
      std::vector<Hit> ranked; ranked.reserve(clusters());
      for (std::size_t c = 0; c < clusters(); ++c)
        ranked.push_back({static_cast<std::uint32_t>(c), dot(q, std::span(centroids_).subspan(c * dimensions_, dimensions_))});
      std::partial_sort(ranked.begin(), ranked.begin() + static_cast<std::ptrdiff_t>(probes), ranked.end(), better);
      // A byte mask allows O(1) eligibility checks; this allocation is included in timing.
      std::vector<std::uint8_t> mask(size(), 0);
      for (auto i : eligible) mask[i] = 1;
      for (std::size_t c = 0; c < probes; ++c) {
        ++out.clusters_searched;
        for (auto i : lists_[ranked[c].row]) if (mask[i]) consider(i);
      }
    }
  }
  while (!heap.empty()) { out.hits.push_back(heap.top()); heap.pop(); }
  std::sort(out.hits.begin(), out.hits.end(), better);
  out.retrieval_ms = std::chrono::duration<double, std::milli>(Clock::now() - start).count();
  return out;
}

const Product& Index::product(std::size_t row) const { return products_.at(row); }
std::vector<std::string> Index::brands() const { return keys(brands_); }
std::vector<std::string> Index::colors() const { return keys(colors_); }

void Index::save(const std::filesystem::path& path) const {
  Bytes bytes{'C','S','I','D','X','0','0','1'};
  u32(bytes, 1); u32(bytes, static_cast<std::uint32_t>(dimensions_));
  u32(bytes, static_cast<std::uint32_t>(size())); u32(bytes, static_cast<std::uint32_t>(clusters()));
  u64(bytes, std::bit_cast<std::uint64_t>(exact_cost_factor_));
  string(bytes, model_id_); string(bytes, provenance_);
  for (const auto& p : products_) {
    string(bytes, p.id); string(bytes, p.title); string(bytes, p.description);
    string(bytes, p.brand); string(bytes, p.color);
  }
  for (float v : vectors_) u32(bytes, std::bit_cast<std::uint32_t>(v));
  for (float v : centroids_) u32(bytes, std::bit_cast<std::uint32_t>(v));
  for (const auto& list : lists_) {
    u32(bytes, static_cast<std::uint32_t>(list.size())); for (auto row : list) u32(bytes, row);
  }
  if (bytes.size() + 8 > kMaxFile) throw std::runtime_error("index exceeds 2 GiB format limit");
  u64(bytes, checksum(bytes));
  // Publish by rename so a failed write cannot replace a working index.
  auto temp = path; temp += ".tmp";
  {
    std::ofstream stream(temp, std::ios::binary | std::ios::trunc);
    stream.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    stream.close();
    if (!stream) throw std::runtime_error("cannot write index: " + temp.string());
  }
  std::filesystem::rename(temp, path);
}

Index Index::load(const std::filesystem::path& path) {
  auto length = std::filesystem::file_size(path);
  if (length < 48 || length > kMaxFile) throw std::runtime_error("invalid index file size");
  Bytes bytes(static_cast<std::size_t>(length));
  std::ifstream file(path, std::ios::binary);
  file.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(length));
  if (!file) throw std::runtime_error("cannot read index");
  Reader footer{std::span(bytes).last(8)};
  auto payload = std::span(bytes).first(bytes.size() - 8);
  if (footer.read64() != checksum(payload)) throw std::runtime_error("index checksum mismatch");
  Reader r{payload};
  if (!std::equal(bytes.begin(), bytes.begin() + 8, std::array<std::uint8_t,8>{'C','S','I','D','X','0','0','1'}.begin()))
    throw std::runtime_error("invalid index magic");
  r.pos = 8;
  if (r.read32() != 1) throw std::runtime_error("unsupported index version");
  Index index;
  index.dimensions_ = r.read32(); auto n = r.read32(); auto c = r.read32();
  index.exact_cost_factor_ = std::bit_cast<double>(r.read64());
  if (!index.dimensions_ || index.dimensions_ > kMaxDimensions || n > 10000000 || c > kMaxClusters ||
      c > n || (n && !c) || !std::isfinite(index.exact_cost_factor_) || index.exact_cost_factor_ <= 0)
    throw std::runtime_error("invalid index shape/configuration");
  index.model_id_ = r.readstring(); index.provenance_ = r.readstring();
  if (index.model_id_.empty()) throw std::runtime_error("missing model identity");
  // Bound allocation by the actual remaining file, before trusting header counts.
  std::uint64_t minimum = std::uint64_t(n) * 20 +
      (std::uint64_t(n) + c) * index.dimensions_ * 4 + std::uint64_t(c) * 4 + std::uint64_t(n) * 4;
  r.need(static_cast<std::size_t>(minimum));
  std::unordered_set<std::string> ids;
  index.products_.reserve(n);
  for (std::uint32_t i = 0; i < n; ++i) {
    Product p{r.readstring(), r.readstring(), r.readstring(), r.readstring(), r.readstring()};
    if (p.id.empty() || !ids.insert(p.id).second || p.brand != normalize_label(p.brand) || p.color != normalize_label(p.color))
      throw std::runtime_error("invalid product metadata");
    index.products_.push_back(std::move(p));
  }
  index.vectors_.resize(std::size_t(n) * index.dimensions_);
  index.centroids_.resize(std::size_t(c) * index.dimensions_);
  for (float& v : index.vectors_) v = r.readfloat();
  for (float& v : index.centroids_) v = r.readfloat();
  for (const auto* matrix : {&index.vectors_, &index.centroids_}) {
    for (std::size_t i = 0; i < matrix->size(); i += index.dimensions_) {
      auto v = std::span(*matrix).subspan(i, index.dimensions_);
      if (std::abs(dot(v, v) - 1) > 0.01F) throw std::runtime_error("index vector is not normalized");
    }
  }
  index.lists_.resize(c); std::vector<bool> seen(n, false); std::size_t total = 0;
  for (auto& list : index.lists_) {
    auto count = r.read32();
    if (count > n - total) throw std::runtime_error("invalid posting list count");
    r.need(std::size_t(count) * 4); list.reserve(count);
    for (std::uint32_t j = 0; j < count; ++j) {
      auto row = r.read32();
      if (row >= n || seen[row]) throw std::runtime_error("invalid/duplicate posting row");
      seen[row] = true; list.push_back(row);
    }
    total += count;
  }
  if (total != n || r.pos != payload.size()) throw std::runtime_error("invalid index membership/trailing bytes");
  index.build_metadata(); return index;
}
}  // namespace catalog
