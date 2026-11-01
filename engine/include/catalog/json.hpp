#pragma once
#include "catalog/index.hpp"
#include <boost/json.hpp>

namespace catalog {
namespace json = boost::json;
SearchOptions parse_options(const json::object& request);
json::object info_json(const Index& index);
json::object search_json(const Index& index, const json::object& request);
Index import_jsonl(const std::filesystem::path& path, const BuildOptions& options);
}  // namespace catalog
