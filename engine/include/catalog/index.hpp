#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <span>
#include <string>
#include <unordered_map>
#include <vector>

namespace catalog {

struct Product {
  std::string id, title, description, brand, color;
};

struct Filter {
  // Empty strings mean no restriction. Values are normalized during ingestion.
  std::string brand, color;
};

enum class Strategy { Auto, Exact, Ivf };

struct SearchOptions {
  std::size_t k = 10;
  std::size_t probes = 8;
  Filter filter;
  Strategy strategy = Strategy::Auto;
};

struct Hit {
  std::uint32_t row;
  float score;
  bool operator==(const Hit&) const = default;
};

struct SearchResult {
  std::vector<Hit> hits;
  std::string strategy;
  std::size_t eligible = 0;
  std::size_t comparisons = 0;
  std::size_t clusters_searched = 0;
  double retrieval_ms = 0;
};

struct BuildOptions {
  std::size_t clusters = 64;
  std::size_t iterations = 12;
  std::size_t training_samples = 10000;
  std::uint32_t seed = 42;
  // A tunable cost coefficient, NOT a promise of an optimal plan.
  double exact_cost_factor = 1.0;
};

class Index {
 public:
  static Index build(std::vector<Product> products, std::vector<float> vectors,
                     std::size_t dimensions, std::string model_id,
                     std::string provenance, const BuildOptions& options = {});
  static Index load(const std::filesystem::path& path);
  void save(const std::filesystem::path& path) const;

  // All state is immutable after build/load; search keeps scratch memory local.
  SearchResult search(std::span<const float> query,
                      const SearchOptions& options = {}) const;
  const Product& product(std::size_t row) const;
  std::size_t size() const { return products_.size(); }
  std::size_t dimensions() const { return dimensions_; }
  std::size_t clusters() const { return lists_.size(); }
  std::size_t vector_bytes() const { return vectors_.size() * sizeof(float); }
  const std::string& model_id() const { return model_id_; }
  const std::string& provenance() const { return provenance_; }
  double exact_cost_factor() const { return exact_cost_factor_; }
  std::vector<std::string> brands() const;
  std::vector<std::string> colors() const;

 private:
  void build_metadata();
  std::vector<std::uint32_t> eligible_rows(const Filter&) const;
  std::vector<Product> products_;
  std::vector<float> vectors_, centroids_;
  std::vector<std::vector<std::uint32_t>> lists_;
  std::unordered_map<std::string, std::vector<std::uint32_t>> brands_, colors_;
  std::size_t dimensions_ = 0;
  std::string model_id_, provenance_;
  double exact_cost_factor_ = 1;
};

std::vector<float> normalized(std::span<const float> values);
float dot(std::span<const float> a, std::span<const float> b);
std::string normalize_label(std::string value);

}  // namespace catalog
