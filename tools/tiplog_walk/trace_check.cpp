#include "tiplog/trace/reader.hpp"

#include <iostream>

int main(int argc, char** argv) {
  try {
    if (argc != 2) throw std::runtime_error("usage: tiplog_trace_check TRACE");
    const tiplog::trace::Reader reader{std::filesystem::path(argv[1])};
    std::uint64_t count = 0;
    std::uint64_t payload_bytes = 0;
    std::uint64_t payload_fnv1a64 = 14695981039346656037ULL;
    reader.for_each([&](const tiplog::trace::Record& record) {
      ++count;
      payload_bytes += record.payload.size();
      for (const auto byte : record.payload) {
        payload_fnv1a64 ^= std::to_integer<unsigned char>(byte);
        payload_fnv1a64 *= 1099511628211ULL;
      }
    });
    std::cout << "{\"record_count\":" << count << ",\"payload_bytes\":" << payload_bytes
              << ",\"topic_count\":" << reader.dictionary().size()
              << ",\"payload_fnv1a64\":" << payload_fnv1a64 << "}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "tiplog_trace_check: " << error.what() << '\n';
    return 2;
  }
}
