#pragma once

#include "../../tools/tiplog_bench/contracts.hpp"

#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <optional>
#include <string>
#include <string_view>
#include <stdexcept>
#include <sys/resource.h>
#include <sched.h>

// Diagnostic logging, called only outside the Google Benchmark timed range.
namespace tiplog::benchlog {
inline std::optional<std::uint64_t> frequency() {
  std::ifstream stream("/sys/devices/system/cpu/cpu2/cpufreq/scaling_cur_freq");
  std::uint64_t value{};
  if (stream >> value) return value;
  return std::nullopt;
}
inline std::int64_t cpu_nanoseconds(const timeval& value) {
  return static_cast<std::int64_t>(value.tv_sec) * 1000000000LL +
         static_cast<std::int64_t>(value.tv_usec) * 1000LL;
}
inline std::uint64_t& ordinal() { static std::uint64_t value{}; return value; }
class Invocation {
 public:
  explicit Invocation(std::string_view profile, std::uint64_t seed)
      : profile_(profile), seed_(seed), ordinal_(ordinal()++),
        cpu_before_(::sched_getcpu()), frequency_before_(frequency()),
        start_(std::chrono::steady_clock::now()) {
    usage_ok_ = ::getrusage(RUSAGE_SELF, &before_) == 0;
  }
  void finish(std::uint64_t iterations, std::uint64_t outputs_per_iteration,
              std::uint64_t digest, bool failed = false,
              std::string_view details_json = "{}") {
    const auto stop = std::chrono::steady_clock::now();
    const auto cpu_after = ::sched_getcpu();
    const auto frequency_after = frequency();
    rusage after{};
    const bool usage_ok = ::getrusage(RUSAGE_SELF, &after) == 0 && usage_ok_;
    const auto* path = std::getenv("TIPLOG_BENCH_INVOCATIONS");
    if (!path || !*path) return;
    std::ofstream out(path, std::ios::app);
    out << "{\"invocation\":" << ordinal_ << ",\"profile\":" << tiplog::bench::json(profile_)
        << ",\"seed\":" << seed_ << ",\"iterations\":" << iterations
        << ",\"outputs_per_iteration\":" << outputs_per_iteration
        << ",\"digest_hex\":\"" << std::hex << digest << std::dec << '"'
        << ",\"cpu_start\":" << cpu_before_ << ",\"cpu_end\":" << cpu_after
        << ",\"cpu2_frequency_start_khz\":";
    if (frequency_before_) out << *frequency_before_; else out << "null";
    out << ",\"cpu2_frequency_end_khz\":";
    if (frequency_after) out << *frequency_after; else out << "null";
    out << ",\"whole_invocation_wall_ns\":"
        << std::chrono::duration_cast<std::chrono::nanoseconds>(stop - start_).count()
        << ",\"whole_invocation_user_ns\":";
    if (usage_ok) out << cpu_nanoseconds(after.ru_utime) - cpu_nanoseconds(before_.ru_utime);
    else out << "null";
    out << ",\"whole_invocation_system_ns\":";
    if (usage_ok) out << cpu_nanoseconds(after.ru_stime) - cpu_nanoseconds(before_.ru_stime);
    else out << "null";
    out << ",\"failed\":" << (failed ? "true" : "false")
        << ",\"details\":" << details_json
        << ",\"boundary\":\"whole function including setup; primary hot-loop time is gbench JSON\"}\n";
    out.flush();
    out.close();
    if (!out) throw std::runtime_error("cannot save benchmark invocation diagnostics");
  }
 private:
  std::string profile_;
  std::uint64_t seed_{};
  std::uint64_t ordinal_{};
  int cpu_before_{};
  std::optional<std::uint64_t> frequency_before_;
  std::chrono::steady_clock::time_point start_;
  rusage before_{};
  bool usage_ok_{};
};
}  // namespace tiplog::benchlog
