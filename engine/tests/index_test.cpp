#include "catalog/index.hpp"
#include "catalog/json.hpp"
#include <gtest/gtest.h>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <limits>
#include <random>
#include <thread>

using namespace catalog;
namespace {
Index tiny() {
  return Index::build({{"a", "Rain shell", "", " Trail ", "BLUE"}, {"b", "Rain coat", "", "trail", "red"}, {"c", "Boots", "", "summit", "blue"}, {"d", "Same shell", "", "trail", "blue"}},
      {1,0,0, 0.8F,0.2F,0, 0,0,1, 1,0,0}, 3, "test", "unit fixture", {.clusters=2, .iterations=8});
}
Index random_index(std::size_t n = 400) {
  std::mt19937 rng(17); std::normal_distribution<float> dist;
  std::vector<Product> products; std::vector<float> vectors;
  for (std::size_t i = 0; i < n; ++i) {
    products.push_back({std::to_string(i), "Product", "", i % 10 ? "common" : "rare", i % 2 ? "blue" : "red"});
    for (int d = 0; d < 12; ++d) vectors.push_back(dist(rng));
  }
  return Index::build(std::move(products), std::move(vectors), 12, "test", "random fixture", {.clusters=12, .iterations=5});
}
std::filesystem::path temp_file(const std::string& suffix) {
  return std::filesystem::temp_directory_path() / ("catalog-test-" + std::to_string(std::hash<std::thread::id>{}(std::this_thread::get_id())) + suffix);
}
}

TEST(Math, NormalizesAndRejectsInvalid) {
  auto v = normalized(std::vector<float>{3,4}); EXPECT_NEAR(v[0], .6, 1e-6); EXPECT_NEAR(v[1], .8, 1e-6);
  EXPECT_THROW(normalized(std::vector<float>{0,0}), std::invalid_argument);
  EXPECT_THROW(normalized(std::vector<float>{NAN,1}), std::invalid_argument);
  EXPECT_THROW(normalized(std::vector<float>{INFINITY,1}), std::invalid_argument);
  EXPECT_THROW(dot(std::vector<float>{1}, std::vector<float>{1,2}), std::invalid_argument);
}
TEST(Math, DotMatchesDoubleOracleAcrossTailsAndUnalignedSpans) {
  std::mt19937 rng(2026);
  std::uniform_real_distribution<float> random(-1, 1);
  for (const std::size_t dimensions : {0, 1, 2, 3, 4, 5, 7, 8, 9, 15, 16, 17,
                                      63, 64, 65, 127, 128, 129, 383, 384, 385,
                                      767, 768, 769, 4095, 4096}) {
    std::vector<float> a(dimensions + 1), b(dimensions + 2);
    const float scale = 1 / std::sqrt(static_cast<float>(std::max<std::size_t>(1, dimensions)));
    for (auto& value : a) value = random(rng) * scale;
    for (auto& value : b) value = random(rng) * scale;
    const auto left = std::span<const float>(a).subspan(1, dimensions);
    const auto right = std::span<const float>(b).subspan(2, dimensions);
    double expected = 0;
    for (std::size_t i = 0; i < dimensions; ++i)
      expected += static_cast<double>(left[i]) * right[i];
    EXPECT_NEAR(dot(left, right), expected, 2e-6);
  }
}
TEST(Search, HighDimensionalTiesRemainDeterministic) {
  std::vector<Product> products;
  std::vector<float> vectors;
  const std::vector<float> query(385, 0.25F);
  for (int i = 0; i < 20; ++i) {
    products.push_back({std::to_string(i), "Identical product", "", "brand", "blue"});
    vectors.insert(vectors.end(), query.begin(), query.end());
  }
  auto index = Index::build(std::move(products), std::move(vectors), query.size(),
                            "test", "ties", {.clusters=4, .iterations=2});
  const auto exact = index.search(query, {.k=10, .strategy=Strategy::Exact});
  ASSERT_EQ(exact.hits.size(), 10);
  for (std::size_t i = 0; i < exact.hits.size(); ++i) EXPECT_EQ(exact.hits[i].row, i);
  EXPECT_EQ(index.search(query, {.k=10, .probes=4, .strategy=Strategy::Ivf}).hits, exact.hits);
}
TEST(Build, ValidatesShapeAndIdentity) {
  EXPECT_THROW(Index::build({{"a","","","",""}}, {1,2}, 3, "test", ""), std::invalid_argument);
  EXPECT_THROW(Index::build({}, {}, 0, "test", ""), std::invalid_argument);
  EXPECT_THROW(Index::build({{"a","","","",""},{"a","","","",""}}, {1,1}, 1, "test", ""), std::invalid_argument);
  EXPECT_THROW(Index::build({}, {}, 3, "", ""), std::invalid_argument);
  EXPECT_THROW(Index::build({}, {}, 3, "test", "", {.clusters=0}), std::invalid_argument);
}
TEST(Search, ExactOrderingAndTies) {
  auto index = tiny(); SearchOptions options; options.strategy = Strategy::Exact;
  auto result = index.search(std::vector<float>{1,0,0}, options);
  ASSERT_EQ(result.hits.size(), 4); EXPECT_EQ(result.hits[0].row, 0); EXPECT_EQ(result.hits[1].row, 3);
  EXPECT_EQ(result.hits[2].row, 1); EXPECT_EQ(result.hits[3].row, 2); EXPECT_EQ(result.comparisons, 4);
}
TEST(Search, FilterIntersectionAndUnknownValues) {
  auto index = tiny(); SearchOptions o; o.filter = {"TRAIL", " blue "}; o.strategy = Strategy::Exact;
  auto result = index.search(std::vector<float>{1,0,0}, o);
  ASSERT_EQ(result.hits.size(), 2); EXPECT_EQ(result.eligible, 2);
  for (auto hit : result.hits) { EXPECT_EQ(index.product(hit.row).brand, "trail"); EXPECT_EQ(index.product(hit.row).color, "blue"); }
  o.filter.brand = "missing"; EXPECT_TRUE(index.search(std::vector<float>{1,0,0}, o).hits.empty());
  o.filter = {"", "red"}; EXPECT_EQ(index.search(std::vector<float>{1,0,0}, o).eligible, 1);
}
TEST(Search, EmptyIndexAndInvalidRequest) {
  auto index = Index::build({}, {}, 3, "test", "");
  EXPECT_TRUE(index.search(std::vector<float>{1,0,0}).hits.empty());
  EXPECT_THROW(index.search(std::vector<float>{1,0}), std::invalid_argument);
  EXPECT_THROW(index.search(std::vector<float>{1,0,0}, {.k=0}), std::invalid_argument);
  EXPECT_THROW(index.search(std::vector<float>{1,0,0}, {.k=1001}), std::invalid_argument);
  EXPECT_THROW(index.search(std::vector<float>{1,0,0}, {.k=10, .probes=0}), std::invalid_argument);
}
TEST(Search, WhitespaceFiltersMatchUnfilteredSearch) {
  auto index = tiny();
  const std::vector<float> query{1,0,0};
  for (const auto strategy : {Strategy::Exact, Strategy::Ivf, Strategy::Auto}) {
    SearchOptions options; options.strategy = strategy; options.probes = 1;
    auto unfiltered = index.search(query, options);
    options.filter = {" \t\r\n", "  "};
    auto blank = index.search(query, options);
    EXPECT_EQ(blank.hits, unfiltered.hits);
    EXPECT_EQ(blank.eligible, index.size());
    EXPECT_EQ(blank.comparisons, unfiltered.comparisons);
    EXPECT_EQ(blank.strategy, unfiltered.strategy);
  }
}
TEST(Search, ProbingEveryClusterMatchesExactWithFilters) {
  auto index = random_index(); std::mt19937 rng(91); std::normal_distribution<float> normal;
  for (int i = 0; i < 35; ++i) {
    std::vector<float> query(12); for (auto& v : query) v = normal(rng);
    SearchOptions o; o.strategy = Strategy::Exact; o.filter = {i % 2 ? "rare" : "", i % 3 ? "blue" : ""};
    auto exact = index.search(query, o); o.strategy = Strategy::Ivf; o.probes = index.clusters();
    auto ivf = index.search(query, o); EXPECT_EQ(exact.hits, ivf.hits);
  }
}
TEST(Search, PlannerChoosesNarrowExactAndBroadIvf) {
  auto index = random_index(1000); std::vector<float> q(12, 1);
  SearchOptions o; o.probes = 1; o.filter.brand = "rare";
  EXPECT_EQ(index.search(q,o).strategy, "ivf"); // 100 eligible > ~95 estimated IVF work.
  o.filter.color = "blue"; // no eligible rare/blue rows in fixture
  EXPECT_EQ(index.search(q,o).strategy, "exact");
  o.filter = {}; EXPECT_EQ(index.search(q,o).strategy, "ivf");
}
TEST(Search, ParallelSearchMatchesSerial) {
  auto index = random_index(); std::vector<float> q(12, 1); auto expected = index.search(q).hits;
  std::atomic<bool> valid{true}; std::vector<std::thread> threads;
  for (int t = 0; t < 8; ++t) threads.emplace_back([&] {
    for (int i = 0; i < 50; ++i) if (index.search(q).hits != expected) valid = false;
  });
  for (auto& t : threads) t.join(); EXPECT_TRUE(valid);
}
TEST(Search, BorrowedPostingsAndOwnedIntersectionsRemainIndependent) {
  auto index = random_index(1000);
  const std::vector<float> query(12, 1);
  std::vector<SearchOptions> requests;
  for (const auto strategy : {Strategy::Exact, Strategy::Ivf, Strategy::Auto}) {
    for (const auto& filter : std::vector<Filter>{{}, {"common", ""}, {"", "blue"},
                                               {"common", "blue"}, {"rare", "blue"},
                                               {"missing", ""}}) {
      SearchOptions options; options.strategy = strategy; options.probes = 3; options.filter = filter;
      requests.push_back(options);
    }
  }
  std::vector<SearchResult> expected;
  for (const auto& request : requests) expected.push_back(index.search(query, request));
  std::atomic<bool> valid{true};
  std::vector<std::thread> threads;
  for (std::size_t t = 0; t < 8; ++t) threads.emplace_back([&,t] {
    for (std::size_t i = 0; i < 100; ++i) {
      auto position = (i+t) % requests.size();
      auto actual = index.search(query, requests[position]);
      const auto& reference = expected[position];
      if (actual.hits != reference.hits || actual.eligible != reference.eligible ||
          actual.comparisons != reference.comparisons || actual.strategy != reference.strategy)
        valid = false;
    }
  });
  for (auto& thread : threads) thread.join();
  EXPECT_TRUE(valid);
}
TEST(Persistence, RoundTripAndDeterminism) {
  auto index = random_index(); auto path = temp_file(".idx"); index.save(path);
  auto loaded = Index::load(path); std::vector<float> q(12,1);
  EXPECT_EQ(index.search(q).hits, loaded.search(q).hits); EXPECT_EQ(loaded.model_id(), "test");
  EXPECT_EQ(loaded.brands(), index.brands());
  auto other = temp_file("-second.idx"); random_index().save(other);
  std::ifstream a(path, std::ios::binary), b(other, std::ios::binary);
  EXPECT_EQ(std::string((std::istreambuf_iterator<char>(a)), {}), std::string((std::istreambuf_iterator<char>(b)), {}));
  std::filesystem::remove(path); std::filesystem::remove(other);
}
TEST(Persistence, EmptyRoundTrip) {
  auto index = Index::build({}, {}, 3, "test", "empty"); auto path = temp_file("-empty.idx");
  index.save(path); auto loaded = Index::load(path); EXPECT_EQ(loaded.size(),0); std::filesystem::remove(path);
}
TEST(Persistence, RejectsCorruptionAndTruncation) {
  auto index = tiny(); auto path = temp_file("-bad.idx"); index.save(path);
  std::fstream file(path, std::ios::in | std::ios::out | std::ios::binary);
  file.seekp(40); file.put('X'); file.close(); EXPECT_THROW(Index::load(path), std::runtime_error);
  std::filesystem::resize_file(path, 20); EXPECT_THROW(Index::load(path), std::runtime_error);
  std::filesystem::remove(path);
}
TEST(Persistence, RejectsForgedHeaderEvenWithValidChecksum) {
  auto path = temp_file("-forged.idx"); tiny().save(path);
  std::ifstream f(path, std::ios::binary); std::vector<unsigned char> data((std::istreambuf_iterator<char>(f)), {}); f.close();
  // Forge a huge row count; loader must reject before allocating from it.
  for (int i=16; i<20; ++i) data[i]=255;
  std::uint64_t h=14695981039346656037ULL;
  for (std::size_t i=0; i<data.size()-8; ++i) {h ^= data[i]; h *= 1099511628211ULL;}
  for (unsigned i=0; i<8; ++i) data[data.size()-8+i]=static_cast<unsigned char>(h >> (8*i));
  std::ofstream out(path, std::ios::binary); out.write(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(data.size())); out.close();
  EXPECT_THROW(Index::load(path), std::runtime_error); std::filesystem::remove(path);
}
TEST(Json, RejectsMismatchedModelAndInvalidOptions) {
  auto index = tiny(); json::object q{{"model_id","other"},{"vector",json::array{1,0,0}}};
  EXPECT_THROW(search_json(index,q), std::invalid_argument);
  q["model_id"]="test"; q["strategy"]="bogus"; EXPECT_THROW(search_json(index,q),std::invalid_argument);
  q["strategy"]="exact"; q["k"]=1.5; EXPECT_THROW(search_json(index,q),std::invalid_argument);
  q["k"]=2; auto result=search_json(index,q); EXPECT_EQ(result.at("hits").as_array().size(),2);
}
