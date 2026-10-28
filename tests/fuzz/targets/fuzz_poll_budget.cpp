#include "differential/poll_campaign.hpp"
extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
  tiplog::poll_differential::Counts counts;
  tiplog::poll_differential::run_input({data, size}, counts);
  return 0;
}
