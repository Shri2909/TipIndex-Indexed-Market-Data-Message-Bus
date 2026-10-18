add_executable(publish_bench bench/micro/publish_bench.cpp)
target_link_libraries(publish_bench PRIVATE tiplog::engine benchmark::benchmark)
