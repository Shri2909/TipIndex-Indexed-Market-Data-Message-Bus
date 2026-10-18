#include "tiplog/trace/reader.hpp"

#include <cstdlib>

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
  try {
    const tiplog::trace::Reader reader(std::span<const std::byte>(
        reinterpret_cast<const std::byte*>(data), size));
    std::uint64_t count = 0;
    std::uint64_t payload_bytes = 0;
    reader.for_each([&](const tiplog::trace::Record& record) {
      ++count;
      payload_bytes += record.payload.size();
      if (reader.topic_path(record.topic_id).empty()) std::abort();
    });
    if (count != reader.header().record_count || payload_bytes > size) std::abort();
    tiplog::trace::Reader::Cursor cursor;
    tiplog::trace::Record record;
    std::uint64_t count_again = 0;
    while (reader.next(cursor, record)) ++count_again;
    if (count_again != count || reader.next(cursor, record)) std::abort();
  } catch (const tiplog::trace::FormatError&) {
    // Malformed data is a reported parse failure, never undefined behavior.
  }
  return 0;
}
