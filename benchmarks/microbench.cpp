#include "catalog/index.hpp"
#include <benchmark/benchmark.h>
#include <random>

static void BM_Dot(benchmark::State& state) {
  std::vector<float> a(static_cast<std::size_t>(state.range(0)), 0.25F), b(a.size(), 0.125F);
  for (auto _ : state) benchmark::DoNotOptimize(catalog::dot(a,b));
  state.SetItemsProcessed(state.iterations() * state.range(0));
}
BENCHMARK(BM_Dot)->Arg(128)->Arg(384)->Arg(768);
