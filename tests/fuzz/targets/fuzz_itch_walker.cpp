#include "tiplog/trace/itch_walker.hpp"
#include "tiplog/trace/reader.hpp"

#include <cstdlib>
#include <memory>

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
  try {
    auto walker = std::make_unique<tiplog::trace::ItchWalker>();
    const auto bytes = std::span<const std::byte>(reinterpret_cast<const std::byte*>(data), size);
    // Exercise incremental boundaries in addition to complete-buffer decoding.
    const auto split = size == 0 ? 0 : static_cast<std::size_t>(data[0]) % (size + 1);
    walker->feed(bytes.first(split));
    walker->feed(bytes.subspan(split));
    walker->finish();
    auto whole = std::make_unique<tiplog::trace::ItchWalker>();
    whole->feed(bytes);
    whole->finish();
    if (walker->message_count() != whole->message_count() ||
        walker->payload_bytes() != whole->payload_bytes() ||
        walker->terminated() != whole->terminated() ||
        walker->timestamp_inversions() != whole->timestamp_inversions()) std::abort();
  } catch (const tiplog::trace::FormatError&) {
  }
  return 0;
}
