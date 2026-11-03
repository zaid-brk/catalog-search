#include "catalog/index.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <new>
#include <random>
#include <stdexcept>
#include <string>

// Only this benchmark executable replaces new/delete. Count requested bytes,
// not allocator overhead or RSS, and only while Index::search is running.
namespace {
struct Allocations { std::size_t calls = 0, bytes = 0; };
thread_local bool counting = false;
thread_local Allocations allocations;

void* allocate(std::size_t bytes, std::size_t alignment = alignof(std::max_align_t)) {
  void* pointer = nullptr;
  if (alignment <= alignof(std::max_align_t)) pointer = std::malloc(bytes ? bytes : 1);
  else if (posix_memalign(&pointer, alignment, bytes ? bytes : 1) != 0) throw std::bad_alloc();
  if (!pointer) throw std::bad_alloc();
  if (counting) { ++allocations.calls; allocations.bytes += bytes; }
  return pointer;
}

struct CountSearch {
  CountSearch() { allocations = {}; counting = true; }
  ~CountSearch() { counting = false; }
  Allocations finish() { counting = false; return allocations; }
};
}

void* operator new(std::size_t bytes) { return allocate(bytes); }
void* operator new[](std::size_t bytes) { return allocate(bytes); }
void* operator new(std::size_t bytes, std::align_val_t alignment) { return allocate(bytes, static_cast<std::size_t>(alignment)); }
void* operator new[](std::size_t bytes, std::align_val_t alignment) { return allocate(bytes, static_cast<std::size_t>(alignment)); }
void operator delete(void* pointer) noexcept { std::free(pointer); }
void operator delete[](void* pointer) noexcept { std::free(pointer); }
void operator delete(void* pointer, std::size_t) noexcept { std::free(pointer); }
void operator delete[](void* pointer, std::size_t) noexcept { std::free(pointer); }
void operator delete(void* pointer, std::align_val_t) noexcept { std::free(pointer); }
void operator delete[](void* pointer, std::align_val_t) noexcept { std::free(pointer); }
void operator delete(void* pointer, std::size_t, std::align_val_t) noexcept { std::free(pointer); }
void operator delete[](void* pointer, std::size_t, std::align_val_t) noexcept { std::free(pointer); }

int main(int argc, char** argv) {
  try {
    if (argc < 2 || argc > 3) throw std::invalid_argument("usage: catalog-allocation-bench INDEX [ITERATIONS=200]");
    std::size_t iterations = 200;
    if (argc == 3) {
      std::size_t end = 0;
      iterations = std::stoull(argv[2], &end);
      if (argv[2][0] == '-' || end != std::string(argv[2]).size() || !iterations || iterations > 1000000)
        throw std::invalid_argument("iterations must be 1..1000000");
    }
    const auto index = catalog::Index::load(argv[1]);
    if (!index.size()) throw std::invalid_argument("benchmark requires a nonempty index");
    std::mt19937 rng(42);
    std::normal_distribution<float> normal;
    std::vector<float> query(index.dimensions());
    for (auto& value : query) value = normal(rng);
    const auto brands = index.brands();
    const auto colors = index.colors();
    const std::string brand = brands.empty() ? "" : brands.front();
    const std::string color = colors.empty() ? "" : colors.front();
    std::cout << "method,filter,products,eligible,iterations,allocations_per_query,requested_bytes_per_query,median_retrieval_us\n";
    for (const auto strategy : {catalog::Strategy::Exact, catalog::Strategy::Ivf}) {
      for (const auto filter : {0, 1, 2}) {
        if ((filter == 1 && brand.empty()) || (filter == 2 && color.empty())) continue;
        catalog::SearchOptions options;
        options.strategy = strategy;
        if (filter == 1) options.filter.brand = brand;
        if (filter == 2) options.filter.color = color;
        index.search(query, options); // Warm up before tracking.
        Allocations total;
        std::size_t eligible = 0;
        std::vector<double> times;
        times.reserve(iterations);
        for (std::size_t i = 0; i < iterations; ++i) {
          CountSearch scope;
          const auto result = index.search(query, options);
          const auto used = scope.finish();
          total.calls += used.calls; total.bytes += used.bytes;
          eligible = result.eligible;
          times.push_back(result.retrieval_ms * 1000);
        }
        std::sort(times.begin(), times.end());
        std::cout << (strategy == catalog::Strategy::Exact ? "exact" : "ivf") << ','
          << (filter == 0 ? "none" : filter == 1 ? "brand" : "color") << ',' << index.size() << ','
          << eligible << ',' << iterations << ',' << std::fixed << std::setprecision(2)
          << static_cast<double>(total.calls) / static_cast<double>(iterations) << ','
          << static_cast<double>(total.bytes) / static_cast<double>(iterations) << ','
          << times[times.size() / 2] << '\n';
      }
    }
  } catch (const std::exception& error) {
    std::cerr << "catalog-allocation-bench: " << error.what() << '\n'; return 1;
  }
}
