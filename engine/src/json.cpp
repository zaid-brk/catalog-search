#include "catalog/json.hpp"
#include <boost/json/src.hpp>
#include <fstream>
#include <limits>
#include <stdexcept>

namespace catalog {
namespace {
std::string text(const json::object& o, const char* key, bool required = false) {
  auto p = o.if_contains(key);
  if (!p) {
    if (required) throw std::invalid_argument(std::string("missing field: ") + key);
    return "";
  }
  if (!p->is_string()) throw std::invalid_argument(std::string(key) + " must be a string");
  return std::string(p->as_string());
}
std::size_t integer(const json::object& o, const char* key, std::size_t fallback, std::size_t max) {
  auto p = o.if_contains(key); if (!p) return fallback;
  if (!(p->is_int64() || p->is_uint64())) throw std::invalid_argument(std::string(key) + " must be an integer");
  auto n = p->is_int64() ? (p->as_int64() < 0 ? 0 : static_cast<std::uint64_t>(p->as_int64())) : p->as_uint64();
  if (n < 1 || n > max) throw std::invalid_argument(std::string(key) + " outside allowed range");
  return static_cast<std::size_t>(n);
}
std::vector<float> vector(const json::object& o) {
  auto p = o.if_contains("vector");
  if (!p || !p->is_array() || p->as_array().size() > 4096) throw std::invalid_argument("vector must be an array with <=4096 numbers");
  std::vector<float> out; out.reserve(p->as_array().size());
  for (const auto& value : p->as_array()) {
    if (!value.is_number()) throw std::invalid_argument("vector must contain numbers");
    out.push_back(static_cast<float>(value.to_number<double>()));
  }
  return out;
}
json::array strings(const std::vector<std::string>& values) {
  json::array out; for (const auto& s : values) out.emplace_back(s); return out;
}
}  // namespace

SearchOptions parse_options(const json::object& request) {
  SearchOptions options;
  options.k = integer(request, "k", 10, 1000);
  options.probes = integer(request, "probes", 8, 4096);
  options.filter.brand = text(request, "brand"); options.filter.color = text(request, "color");
  auto strategy = text(request, "strategy");
  if (strategy.empty() || strategy == "auto") options.strategy = Strategy::Auto;
  else if (strategy == "exact") options.strategy = Strategy::Exact;
  else if (strategy == "ivf") options.strategy = Strategy::Ivf;
  else throw std::invalid_argument("strategy must be auto, exact, or ivf");
  return options;
}

json::object info_json(const Index& index) {
  return {{"products", index.size()}, {"dimensions", index.dimensions()},
    {"clusters", index.clusters()}, {"model_id", index.model_id()},
    {"provenance", index.provenance()}, {"vector_bytes", index.vector_bytes()},
    {"exact_cost_factor", index.exact_cost_factor()},
    {"brands", strings(index.brands())}, {"colors", strings(index.colors())}};
}

json::object search_json(const Index& index, const json::object& request) {
  // Refuse a query made by a different model/preprocessing configuration.
  if (text(request, "model_id", true) != index.model_id())
    throw std::invalid_argument("query model_id does not match index");
  auto query = vector(request);
  auto result = index.search(query, parse_options(request));
  json::array hits;
  for (const auto& hit : result.hits) {
    const auto& p = index.product(hit.row);
    hits.emplace_back(json::object{{"row", hit.row}, {"id", p.id}, {"title", p.title},
      {"description", p.description}, {"brand", p.brand}, {"color", p.color}, {"score", hit.score}});
  }
  return {{"hits", std::move(hits)}, {"strategy", result.strategy},
    {"eligible", result.eligible}, {"comparisons", result.comparisons},
    {"clusters_searched", result.clusters_searched}, {"retrieval_ms", result.retrieval_ms}};
}

Index import_jsonl(const std::filesystem::path& path, const BuildOptions& options) {
  std::ifstream file(path); if (!file) throw std::runtime_error("cannot open input catalog");
  std::string line;
  if (!std::getline(file, line)) throw std::invalid_argument("missing catalog header");
  auto header = json::parse(line).as_object();
  auto dims = integer(header, "dimensions", 0, 4096);
  if (!dims) throw std::invalid_argument("missing dimensions");
  auto model = text(header, "model_id", true), provenance = text(header, "provenance", true);
  std::vector<Product> products; std::vector<float> vectors;
  std::size_t number = 1;
  while (std::getline(file, line)) {
    ++number;
    if (line.size() > 4 * 1024 * 1024) throw std::invalid_argument("input line too long");
    if (line.empty()) continue;
    try {
      auto row = json::parse(line).as_object(); auto v = vector(row);
      if (v.size() != dims) throw std::invalid_argument("vector dimension mismatch");
      products.push_back({text(row, "id", true), text(row, "title", true), text(row, "description"), text(row, "brand"), text(row, "color")});
      vectors.insert(vectors.end(), v.begin(), v.end());
      if (products.size() > 10000000) throw std::invalid_argument("too many products");
    } catch (const std::exception& e) { throw std::invalid_argument("input line " + std::to_string(number) + ": " + e.what()); }
  }
  return Index::build(std::move(products), std::move(vectors), dims, model, provenance, options);
}
}  // namespace catalog
