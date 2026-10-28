# Local correction to the verified Google Benchmark 1.9.5 source. Its result
# ofstream otherwise closes without checking buffered write/close failures.
# Never modify the archive pin or accept unexpected/generated source contents.
set(_tiplog_benchmark_cc "${benchmark_SOURCE_DIR}/src/benchmark.cc")
set(_tiplog_benchmark_original "93dd058ff126b0e50f53f8d5d31d6fa5132b345b3132781c692b7d8538c72da3")
set(_tiplog_benchmark_patched "4fc57e51c4bf1aa76e8c61bc4538f4a00fce0f03dd96e8f8ba577870da16fce8")
file(SHA256 "${_tiplog_benchmark_cc}" _tiplog_benchmark_hash)
if(_tiplog_benchmark_hash STREQUAL _tiplog_benchmark_original)
  file(READ "${_tiplog_benchmark_cc}" _tiplog_benchmark_text)
  string(REPLACE "#include <string>\n" "#include <string>\n#include <stdexcept>\n"
    _tiplog_benchmark_text "${_tiplog_benchmark_text}")
  set(_tiplog_benchmark_before [=[  Out.flush();
  Err.flush();
  return benchmarks.size();]=])
  set(_tiplog_benchmark_after [=[  Out.flush();
  Err.flush();
  // tiplog TOOL-05: final result-file failures must fail the invocation.
  if (output_file.is_open()) {
    output_file.flush();
    if (!output_file) throw std::runtime_error("failed writing benchmark result file");
    output_file.close();
    if (!output_file) throw std::runtime_error("failed closing benchmark result file");
  }
  return benchmarks.size();]=])
  string(REPLACE "${_tiplog_benchmark_before}" "${_tiplog_benchmark_after}"
    _tiplog_benchmark_text "${_tiplog_benchmark_text}")
  string(SHA256 _tiplog_benchmark_hash "${_tiplog_benchmark_text}")
  if(NOT _tiplog_benchmark_hash STREQUAL _tiplog_benchmark_patched)
    message(FATAL_ERROR "Google Benchmark output patch did not produce the approved source identity")
  endif()
  file(WRITE "${_tiplog_benchmark_cc}" "${_tiplog_benchmark_text}")
elseif(NOT _tiplog_benchmark_hash STREQUAL _tiplog_benchmark_patched)
  message(FATAL_ERROR "Unexpected Google Benchmark source identity; refusing to patch or use it")
endif()
if(NOT BENCHMARK_ENABLE_EXCEPTIONS)
  message(FATAL_ERROR "tiplog benchmark output-error propagation requires BENCHMARK_ENABLE_EXCEPTIONS=ON")
endif()
