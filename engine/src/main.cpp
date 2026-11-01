#include "catalog/json.hpp"
#include <algorithm>
#include <chrono>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>

namespace {
std::map<std::string, std::string> flags(int argc, char** argv) {
  std::map<std::string, std::string> result;
  for (int i = 2; i < argc; i += 2) {
    if (i + 1 == argc || std::string(argv[i]).rfind("--", 0) != 0 || !result.emplace(argv[i], argv[i + 1]).second)
      throw std::invalid_argument("options require unique --name value pairs");
  }
  return result;
}
std::string required(const auto& args, const std::string& key) {
  auto it = args.find(key); if (it == args.end()) throw std::invalid_argument("missing " + key); return it->second;
}
std::size_t number(const auto& args, const std::string& key, std::size_t fallback) {
  auto it = args.find(key); if (it == args.end()) return fallback;
  std::size_t end = 0; auto n = std::stoull(it->second, &end);
  if (it->second.empty() || it->second[0] == '-' || end != it->second.size()) throw std::invalid_argument("invalid " + key);
  return n;
}
}
int main(int argc, char** argv) {
  using namespace catalog;
  try {
    if (argc < 2 || std::string(argv[1]) == "--help") {
      std::cout << "catalog build --input catalog.jsonl --output catalog.csidx [--clusters 64 --iterations 12 --training-samples 10000 --seed 42 --exact-cost-factor 1]\n"
        "catalog info --index catalog.csidx\n"
        "catalog search --index catalog.csidx --request query.json\n"
        "catalog worker --index catalog.csidx   # one JSON request/response per line\n";
      return 0;
    }
    auto args = flags(argc, argv); std::string command(argv[1]);
    const std::map<std::string, std::vector<std::string>> allowed{
      {"build", {"--input", "--output", "--clusters", "--iterations", "--training-samples", "--seed", "--exact-cost-factor"}},
      {"info", {"--index"}}, {"search", {"--index", "--request"}}, {"worker", {"--index"}}};
    if (!allowed.contains(command)) throw std::invalid_argument("unknown command");
    for (const auto& [key, value] : args) {
      const auto& keys = allowed.at(command);
      if (std::find(keys.begin(), keys.end(), key) == keys.end()) throw std::invalid_argument("unknown option: " + key);
    }
    if (command == "build") {
      BuildOptions options;
      options.clusters = number(args, "--clusters", 64);
      options.iterations = number(args, "--iterations", 12);
      options.training_samples = number(args, "--training-samples", 10000);
      options.seed = static_cast<std::uint32_t>(number(args, "--seed", 42));
      if (args.contains("--exact-cost-factor")) {
        std::size_t end = 0; const auto& s = args.at("--exact-cost-factor");
        options.exact_cost_factor = std::stod(s, &end);
        if (end != s.size()) throw std::invalid_argument("invalid exact cost factor");
      }
      auto start = std::chrono::steady_clock::now();
      auto index = import_jsonl(required(args, "--input"), options);
      index.save(required(args, "--output"));
      auto out = info_json(index);
      out["build_seconds"] = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
      std::cout << json::serialize(out) << '\n';
    } else {
      auto index = Index::load(required(args, "--index"));
      if (command == "info") std::cout << json::serialize(info_json(index)) << '\n';
      else if (command == "search") {
        std::ifstream file(required(args, "--request"));
        if (!file) throw std::runtime_error("cannot open query file");
        std::string input((std::istreambuf_iterator<char>(file)), {});
        std::cout << json::serialize(search_json(index, json::parse(input).as_object())) << '\n';
      } else {
        std::string line;
        while (std::getline(std::cin, line)) {
          try {
            if (line.size() > 1024 * 1024) throw std::invalid_argument("request too large");
            auto request = json::parse(line).as_object();
            auto out = request.contains("info") ? info_json(index) : search_json(index, request);
            std::cout << json::serialize(out) << std::endl;
          } catch (const std::exception& e) { std::cout << json::serialize(json::object{{"error", e.what()}}) << std::endl; }
        }
      }
    }
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "catalog: " << e.what() << '\n'; return 1;
  }
}
