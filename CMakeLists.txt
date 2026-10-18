cmake_minimum_required(VERSION 3.30)

project(tiplog VERSION 0.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

include(CTest)
include(cmake/deps.cmake)

# Only our targets inherit these warnings. Upstream dependencies keep their own.
add_library(tiplog_build_options INTERFACE)
add_library(tiplog::build_options ALIAS tiplog_build_options)
target_compile_features(tiplog_build_options INTERFACE cxx_std_20)
target_compile_options(tiplog_build_options INTERFACE
  -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Wformat=2
)

# Future real fuzz targets link this interface to obtain libFuzzer's main().
# The fuzz preset instruments all compiled code without replacing test main().
add_library(tiplog_fuzzer_options INTERFACE)
add_library(tiplog::fuzzer_options ALIAS tiplog_fuzzer_options)
if(TIPLOG_ENABLE_FUZZING)
  if(NOT CMAKE_CXX_COMPILER_ID MATCHES "Clang")
    message(FATAL_ERROR "TIPLOG_ENABLE_FUZZING requires Clang")
  endif()
  target_link_libraries(tiplog_fuzzer_options INTERFACE tiplog::build_options)
  target_link_options(tiplog_fuzzer_options INTERFACE -fsanitize=fuzzer)
endif()

if(BUILD_TESTING)
  add_executable(tiplog_smoke_test tests/unit/smoke_test.cpp)
  target_link_libraries(tiplog_smoke_test PRIVATE
    tiplog::build_options GTest::gtest_main
  )
  include(GoogleTest)
  # Discovery occurs during ctest, with the preset's sanitizer environment.
  gtest_discover_tests(tiplog_smoke_test
    TEST_PREFIX "plumbing."
    DISCOVERY_MODE PRE_TEST
  )
endif()

include(cmake/p1.cmake)
include(cmake/p2.cmake)
include(cmake/p2_ref.cmake)
include(cmake/p3_ring.cmake)
include(cmake/p4_index.cmake)
include(cmake/p5_merge.cmake)
include(cmake/p3_engine.cmake)
include(cmake/p3_fuzz.cmake)
include(cmake/p5_bench.cmake)

# Allocator diagnostics are separate from the portable index and its gauges.
if(CMAKE_SYSTEM_NAME STREQUAL "Linux" AND CMAKE_BUILD_TYPE STREQUAL "Release")
  add_executable(tiplog_index_memory tools/tiplog_index_memory.cpp)
  target_link_libraries(tiplog_index_memory PRIVATE tiplog::index)
endif()
