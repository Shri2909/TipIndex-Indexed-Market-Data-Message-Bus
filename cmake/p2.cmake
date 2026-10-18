add_library(tiplog_topics_subs
  src/tiplog/topics/registry.cpp
  src/tiplog/subs/compiled.cpp
)
add_library(tiplog::topics_subs ALIAS tiplog_topics_subs)
target_include_directories(tiplog_topics_subs PUBLIC "${PROJECT_SOURCE_DIR}/src")
target_link_libraries(tiplog_topics_subs PUBLIC tiplog::build_options)

if(BUILD_TESTING)
  add_executable(tiplog_topics_subs_test tests/unit/topics_subs_test.cpp)
  target_link_libraries(tiplog_topics_subs_test PRIVATE tiplog::topics_subs GTest::gtest_main)
  gtest_discover_tests(tiplog_topics_subs_test TEST_PREFIX "topics.subs." DISCOVERY_MODE PRE_TEST)
endif()
