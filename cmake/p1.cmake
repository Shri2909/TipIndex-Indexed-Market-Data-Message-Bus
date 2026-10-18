add_library(tiplog_trace
  src/tiplog/trace/reader.cpp
  src/tiplog/trace/itch_walker.cpp
)
add_library(tiplog::trace ALIAS tiplog_trace)
target_include_directories(tiplog_trace PUBLIC "${PROJECT_SOURCE_DIR}/src")
target_link_libraries(tiplog_trace PUBLIC tiplog::build_options)

add_executable(tiplog_walk tools/tiplog_walk/main.cpp)
target_link_libraries(tiplog_walk PRIVATE tiplog::trace)
add_executable(tiplog_trace_check tools/tiplog_walk/trace_check.cpp)
target_link_libraries(tiplog_trace_check PRIVATE tiplog::trace)

if(BUILD_TESTING)
  add_executable(tiplog_trace_test tests/unit/trace_test.cpp)
  target_link_libraries(tiplog_trace_test PRIVATE tiplog::trace GTest::gtest_main)
  gtest_discover_tests(tiplog_trace_test TEST_PREFIX "trace." DISCOVERY_MODE PRE_TEST)
endif()

if(TIPLOG_ENABLE_FUZZING)
  add_executable(fuzz_trace_reader tests/fuzz/targets/fuzz_trace_reader.cpp)
  target_link_libraries(fuzz_trace_reader PRIVATE tiplog::trace tiplog::fuzzer_options)
  add_executable(fuzz_itch_walker tests/fuzz/targets/fuzz_itch_walker.cpp)
  target_link_libraries(fuzz_itch_walker PRIVATE tiplog::trace tiplog::fuzzer_options)
endif()
