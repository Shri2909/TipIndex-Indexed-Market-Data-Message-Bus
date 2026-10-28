add_executable(tiplog_bench tools/tiplog_bench/main.cpp)
target_link_libraries(tiplog_bench PRIVATE tiplog::engine tiplog::trace)

add_executable(tiplog_poll_bench tools/tiplog_poll_bench.cpp)
target_link_libraries(tiplog_poll_bench PRIVATE tiplog::engine)

add_executable(index_bench bench/micro/index_bench.cpp)
target_link_libraries(index_bench PRIVATE tiplog::index tiplog::topics_subs tiplog::trace benchmark::benchmark)

if(BUILD_TESTING)
  add_executable(tiplog_bench_contract_test tests/unit/bench_contract_test.cpp)
  target_include_directories(tiplog_bench_contract_test PRIVATE "${PROJECT_SOURCE_DIR}/tools")
  target_link_libraries(tiplog_bench_contract_test PRIVATE tiplog::engine GTest::gtest_main)
  gtest_discover_tests(tiplog_bench_contract_test TEST_PREFIX "bench_contract." DISCOVERY_MODE PRE_TEST)
endif()
