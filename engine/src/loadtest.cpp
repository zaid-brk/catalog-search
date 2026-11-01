#include "catalog/json.hpp"
#include <algorithm>
#include <barrier>
#include <chrono>
#include <fstream>
#include <iostream>
#include <numeric>
#include <thread>
#include <sys/resource.h>

int main(int argc, char** argv) {
  using namespace catalog;
  try {
    if (argc != 5) throw std::invalid_argument("usage: catalog-loadtest INDEX QUERIES.jsonl THREADS ITERATIONS_PER_THREAD");
    auto number = [](const char* s, unsigned max) {
      std::size_t end = 0; auto n = std::stoul(s,&end);
      if (s[0]=='-' || end!=std::string(s).size() || n<1 || n>max) throw std::invalid_argument("invalid thread/iteration count");
      return static_cast<unsigned>(n);
    };
    auto threads = number(argv[3],64), iterations = number(argv[4],1000000);
    auto index = Index::load(argv[1]);
    struct Request { std::vector<float> query; SearchOptions options; };
    std::vector<Request> requests; std::ifstream input(argv[2]); std::string line;
    if (!input) throw std::runtime_error("cannot open queries");
    while (std::getline(input,line)) {
      auto object = json::parse(line).as_object();
      if (object.at("model_id").as_string() != index.model_id()) throw std::invalid_argument("query model mismatch");
      Request request;
      for (const auto& v : object.at("vector").as_array()) request.query.push_back(static_cast<float>(v.to_number<double>()));
      request.options = parse_options(object);
      index.search(request.query,request.options); // Validate and warm before threads start.
      requests.push_back(std::move(request));
    }
    if (requests.empty()) throw std::invalid_argument("no queries");
    std::barrier start(static_cast<std::ptrdiff_t>(threads+1));
    std::vector<std::vector<double>> latencies(threads);
    std::vector<std::thread> workers;
    for (unsigned t=0; t<threads; ++t) workers.emplace_back([&,t] {
      auto& times=latencies[t]; times.reserve(iterations); start.arrive_and_wait();
      for (unsigned i=0; i<iterations; ++i) {
        const auto& request=requests[(i+t)%requests.size()];
        times.push_back(index.search(request.query,request.options).retrieval_ms);
      }
    });
    auto before=std::chrono::steady_clock::now(); start.arrive_and_wait();
    for (auto& worker:workers) worker.join();
    auto seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-before).count();
    std::vector<double> times;
    for (const auto& group:latencies) times.insert(times.end(),group.begin(),group.end());
    std::sort(times.begin(),times.end());
    rusage usage{}; getrusage(RUSAGE_SELF,&usage);
#ifdef __APPLE__
    auto peak_bytes=usage.ru_maxrss;
#else
    auto peak_bytes=usage.ru_maxrss*1024;
#endif
    json::object result{{"threads",threads},{"queries",times.size()},{"elapsed_seconds",seconds},
      {"queries_per_second",static_cast<double>(times.size())/seconds},
      {"p50_ms",times[times.size()/2]},{"p95_ms",times[static_cast<std::size_t>(.95*static_cast<double>(times.size()-1))]},
      {"peak_process_rss_bytes",peak_bytes},{"scope","in-process C++ retrieval over cyclic precomputed queries; excludes HTTP, model inference, and load time; peak RSS includes index loading"}};
    std::cout << json::serialize(result) << '\n';
  } catch (const std::exception& e) { std::cerr << "catalog-loadtest: " << e.what() << '\n'; return 1; }
}
