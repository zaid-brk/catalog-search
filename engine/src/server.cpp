#include "catalog/json.hpp"
#include <boost/asio.hpp>
#include <boost/beast.hpp>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <iostream>
#include <thread>
#include <poll.h>

namespace asio = boost::asio;
namespace beast = boost::beast;
namespace http = beast::http;
using tcp = asio::ip::tcp;

namespace {
void wait_ready(tcp::socket& socket, short events, std::chrono::steady_clock::time_point deadline) {
  for (;;) {
    auto remaining=std::chrono::duration_cast<std::chrono::milliseconds>(deadline-std::chrono::steady_clock::now()).count();
    if (remaining<=0) throw std::runtime_error("connection deadline exceeded");
    pollfd descriptor{socket.native_handle(),events,0};
    auto result=::poll(&descriptor,1,static_cast<int>(remaining));
    if (result>0) return;
    if (result<0 && errno==EINTR) continue;
    throw std::runtime_error(result==0 ? "connection deadline exceeded" : "socket poll failed");
  }
}
}

int main(int argc, char** argv) {
  try {
    if (argc < 2 || argc > 4) throw std::invalid_argument("usage: catalog-server INDEX [PORT=8081] [THREADS=4]");
    auto index = catalog::Index::load(argv[1]);
    auto parse_integer = [](const char* s, unsigned max) {
      std::size_t end = 0; auto v = std::stoul(s, &end);
      if (s[0] == '-' || end != std::string(s).size() || v < 1 || v > max) throw std::invalid_argument("invalid port/thread count");
      return static_cast<unsigned>(v);
    };
    unsigned port = argc > 2 ? parse_integer(argv[2], 65535) : 8081;
    unsigned threads = argc > 3 ? parse_integer(argv[3], 64) : 4;
    asio::io_context io;
    tcp::acceptor acceptor(io, {asio::ip::make_address("127.0.0.1"), static_cast<unsigned short>(port)});
    asio::thread_pool pool(threads);
    std::atomic<unsigned> pending{0};
    auto handle = [&](tcp::socket socket) {
      try {
        socket.non_blocking(true);
        beast::flat_buffer buffer;
        http::request_parser<http::string_body> parser;
        parser.body_limit(128 * 1024); parser.header_limit(8192);
        auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(5);
        while (!parser.is_done()) {
          beast::error_code error;
          http::read(socket,buffer,parser,error);
          if (error==asio::error::would_block || error==asio::error::try_again) wait_ready(socket,POLLIN,deadline);
          else if (error) throw beast::system_error(error);
        }
        auto request = parser.release();
        http::status status = http::status::ok;
        catalog::json::object body;
        auto target = request.target();
        if (request.method() == http::verb::get && target == "/health") body = {{"status", "ok"}};
        else if (request.method() == http::verb::get && target == "/info") body = catalog::info_json(index);
        else if (request.method() == http::verb::post && target == "/search") {
          try { body = catalog::search_json(index, catalog::json::parse(request.body()).as_object()); }
          catch (const std::exception& e) { status = http::status::bad_request; body = {{"error", e.what()}}; }
        } else { status = http::status::not_found; body = {{"error", "route not found"}}; }
        http::response<http::string_body> response{status, 11};
        response.set(http::field::content_type, "application/json");
        response.set(http::field::server, "catalog-search");
        response.keep_alive(false); response.body() = catalog::json::serialize(body); response.prepare_payload();
        http::response_serializer<http::string_body> serializer{response};
        deadline=std::chrono::steady_clock::now()+std::chrono::seconds(5);
        while (!serializer.is_done()) {
          beast::error_code error;
          http::write_some(socket,serializer,error);
          if (error==asio::error::would_block || error==asio::error::try_again) wait_ready(socket,POLLOUT,deadline);
          else if (error) throw beast::system_error(error);
        }
        beast::error_code ignored; socket.shutdown(tcp::socket::shutdown_both, ignored);
      } catch (const std::exception& e) { std::cerr << "connection: " << e.what() << '\n'; }
      --pending;
    };
    std::function<void()> accept;
    accept = [&] {
      acceptor.async_accept([&](beast::error_code error, tcp::socket socket) {
        if (!error) {
          // Bound queued work and accepted sockets; overload connections close.
          if (pending.load() < threads * 4) {
            ++pending;
            asio::post(pool, [&, socket = std::move(socket)]() mutable { handle(std::move(socket)); });
          }
        }
        if (acceptor.is_open()) accept();
      });
    };
    asio::signal_set signals(io, SIGINT, SIGTERM);
    signals.async_wait([&](beast::error_code, int) { acceptor.close(); io.stop(); });
    accept();
    std::cout << "C++ search API: http://127.0.0.1:" << port << " (" << threads << " workers)" << std::endl;
    io.run(); pool.join();
  } catch (const std::exception& e) { std::cerr << "catalog-server: " << e.what() << '\n'; return 1; }
}
