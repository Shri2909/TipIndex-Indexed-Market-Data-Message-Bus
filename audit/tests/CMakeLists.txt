# Audit-only test project. It builds the project under test as a subdirectory
# from an isolated copy (TIPLOG_ROOT) and never writes into that source tree.
#
#   cmake -S audit/tests -B <build> -DTIPLOG_ROOT=<isolated copy> \
#         -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=g++
#   cmake --build <build> -j4 && ctest --test-dir <build>
cmake_minimum_required(VERSION 3.30)
project(tiplog_audit LANGUAGES CXX)

if(NOT TIPLOG_ROOT)
  message(FATAL_ERROR "Set -DTIPLOG_ROOT to an isolated copy of the project")
endif()
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(BUILD_TESTING ON CACHE BOOL "" FORCE)
include(CTest)
# Imported targets are directory-scoped; find the same exact GoogleTest the
# project requires before adding it, so both scopes see GTest::gtest_main.
find_package(GTest 1.17.0 EXACT CONFIG REQUIRED)
add_subdirectory(${TIPLOG_ROOT} tiplog EXCLUDE_FROM_ALL)
include(GoogleTest)

function(audit_test name)
  add_executable(${name} cpp/${name}.cpp)
  target_include_directories(${name} PRIVATE ${TIPLOG_ROOT}/tests ${TIPLOG_ROOT}/tests/ref)
  target_link_libraries(${name} PRIVATE ${ARGN} GTest::gtest_main)
  gtest_discover_tests(${name} TEST_PREFIX "audit." DISCOVERY_MODE PRE_TEST
                       DISCOVERY_TIMEOUT 60 PROPERTIES TIMEOUT 600)
endfunction()

audit_test(audit_engine_test tiplog::engine tiplog::ref)
audit_test(audit_pressure_test tiplog::engine tiplog::ref)
audit_test(audit_layout_test tiplog::layout)
audit_test(audit_trace_test tiplog::trace)
audit_test(audit_redteam_test tiplog::engine tiplog::trace)
audit_test(audit_red_spec_test tiplog::engine tiplog::layout tiplog::trace)
audit_test(audit_checker_test tiplog::engine)
