if(TIPLOG_ENABLE_FUZZING)
  if(NOT BUILD_TESTING)
    message(FATAL_ERROR "Engine differential fuzzing requires the test-only oracle")
  endif()
  add_executable(fuzz_engine_ops tests/fuzz/targets/fuzz_engine_ops.cpp)
  target_link_libraries(fuzz_engine_ops PRIVATE
    tiplog::engine tiplog::ref tiplog::fuzzer_options)
endif()
