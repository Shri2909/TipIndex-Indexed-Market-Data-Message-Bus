# The modeled storage optimizer does not link the timed replay engine.
add_library(tiplog_layout_lib
  src/tiplog/layout/model.cpp
  src/tiplog/layout/exact.cpp
  src/tiplog/layout/global.cpp
)
add_library(tiplog::layout ALIAS tiplog_layout_lib)
target_include_directories(tiplog_layout_lib PUBLIC ${PROJECT_SOURCE_DIR}/src)
target_link_libraries(tiplog_layout_lib PUBLIC tiplog::build_options)

add_executable(tiplog_layout tools/tiplog_layout/main.cpp)
target_link_libraries(tiplog_layout PRIVATE tiplog::layout)
add_executable(tiplog_layout_example tools/tiplog_layout/worked_example.cpp)
target_link_libraries(tiplog_layout_example PRIVATE tiplog::layout)
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
  add_executable(tiplog_layout_runtime tools/tiplog_layout/runtime_main.cpp)
  target_link_libraries(tiplog_layout_runtime PRIVATE tiplog::layout)
endif()

if(BUILD_TESTING)
  add_executable(tiplog_layout_test tests/layout/layout_test.cpp)
  target_link_libraries(tiplog_layout_test PRIVATE tiplog::layout GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(tiplog_layout_test TEST_PREFIX "layout." DISCOVERY_MODE PRE_TEST)
  add_executable(tiplog_layout_cc5 tests/layout/layout_cc5.cpp)
  target_link_libraries(tiplog_layout_cc5 PRIVATE tiplog::layout)
  find_package(Python3 COMPONENTS Interpreter REQUIRED)
  add_test(NAME tools.cli_contracts
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tests/layout/tool_contracts.py"
            "$<TARGET_FILE_DIR:tiplog_bench>")
endif()
