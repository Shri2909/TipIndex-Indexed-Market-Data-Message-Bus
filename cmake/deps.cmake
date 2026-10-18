include(FetchContent)

option(TIPLOG_FORCE_FETCH_GTEST "Exercise pinned GoogleTest FetchContent fallback" OFF)
option(TIPLOG_ENABLE_FUZZING "Instrument code for future libFuzzer targets" OFF)
set(TIPLOG_DOWNLOAD_CACHE "${PROJECT_SOURCE_DIR}/build/downloads" CACHE PATH
  "Optional directory containing SHA-256-verified dependency archives")

# Fixed commit archives are immutable pins. A previously downloaded local copy
# uses exactly the same hash check as the upstream download. Never disable TLS.
set(_benchmark_url
  "https://codeload.github.com/google/benchmark/tar.gz/192ef10025eb2c4cdd392bc502f0c852196baa48")
if(EXISTS "${TIPLOG_DOWNLOAD_CACHE}/benchmark-1.9.5.tar.gz")
  set(_benchmark_url "${TIPLOG_DOWNLOAD_CACHE}/benchmark-1.9.5.tar.gz")
endif()
FetchContent_Declare(benchmark
  URL "${_benchmark_url}"
  URL_HASH SHA256=f82705a2726d8f6cdcda274b841f6314dbfc6f731cdda06c946f310ec1cc3ad9
  DOWNLOAD_EXTRACT_TIMESTAMP FALSE
  TLS_VERIFY TRUE
  SYSTEM
)
# Benchmark v1.9.5, commit 192ef10025eb2c4cdd392bc502f0c852196baa48.
# Its own tests are outside P0 and would add another GoogleTest resolution path.
set(BENCHMARK_ENABLE_TESTING OFF CACHE BOOL "" FORCE)
set(BENCHMARK_ENABLE_GTEST_TESTS OFF CACHE BOOL "" FORCE)
set(BENCHMARK_ENABLE_WERROR OFF CACHE BOOL "" FORCE)
set(BENCHMARK_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
set(BENCHMARK_DOWNLOAD_DEPENDENCIES OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(benchmark)

if(BUILD_TESTING)
  if(NOT TIPLOG_FORCE_FETCH_GTEST)
    find_package(GTest 1.17.0 EXACT QUIET CONFIG)
  endif()
  if(TIPLOG_FORCE_FETCH_GTEST OR NOT GTest_FOUND)
    set(_gtest_url
      "https://codeload.github.com/google/googletest/tar.gz/52eb8108c5bdec04579160ae17225d66034bd723")
    if(EXISTS "${TIPLOG_DOWNLOAD_CACHE}/googletest-1.17.0.tar.gz")
      set(_gtest_url "${TIPLOG_DOWNLOAD_CACHE}/googletest-1.17.0.tar.gz")
    endif()
    # GoogleTest v1.17.0, commit 52eb8108c5bdec04579160ae17225d66034bd723.
    FetchContent_Declare(googletest
      URL "${_gtest_url}"
      URL_HASH SHA256=745c55415660044610f7fcd3af7a6420d5de16a7dbb9ebfe2e131275676232be
      DOWNLOAD_EXTRACT_TIMESTAMP FALSE
      TLS_VERIFY TRUE
      SYSTEM
    )
    set(BUILD_GMOCK OFF CACHE BOOL "" FORCE)
    set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)
    set(TIPLOG_GTEST_PROVIDER "FetchContent v1.17.0" CACHE INTERNAL "" FORCE)
  else()
    set(TIPLOG_GTEST_PROVIDER "system 1.17.0" CACHE INTERNAL "" FORCE)
  endif()
  message(STATUS "tiplog GoogleTest provider: ${TIPLOG_GTEST_PROVIDER}")
endif()
