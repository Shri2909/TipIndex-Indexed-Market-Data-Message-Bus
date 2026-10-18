# Phase 0 CMake source inspection — 2026-10-17

This note records actual inspection for P0.2 / the C++ portion of P0.5. It does not claim that engine tests or benchmarks ran. All CMake commands below ran in `/home/abc/Desktop/Jane Street`.

## Original sources inspected

| Finding/source | Inspected original material and revision | Implementation consequence |
|---|---|---|
| S42 / S48; ARCHITECTURE DD-15 | [Google Benchmark CMakeLists.txt at v1.9.5](https://github.com/google/benchmark/blob/192ef10025eb2c4cdd392bc502f0c852196baa48/CMakeLists.txt), first 115 lines locally from the verified archive, including project version, dependency-download, testing, Werror and install options; remaining CMakeLists.txt via raw web view, including tests block. GitHub API `git/ref/tags/v1.9.5` resolves to commit `192ef10025eb2c4cdd392bc502f0c852196baa48`. | Keep approved 1.9.5; fixed commit archive and SHA-256; turn upstream tests/Werror/install/dependency downloading off. P0 builds the library without running benchmark measurements. |
| DD-15 / system 1.17.0 + fallback | [GoogleTest top-level CMakeLists.txt](https://github.com/google/googletest/blob/52eb8108c5bdec04579160ae17225d66034bd723/CMakeLists.txt) (34 lines, web); `googletest/CMakeLists.txt` lines 90–155 from the pinned archive (gtest/gtest_main definitions and dependencies). GitHub API tag `v1.17.0` resolves to commit `52eb8108c5bdec04579160ae17225d66034bd723`. Installed `/usr/lib/x86_64-linux-gnu/cmake/GTest/GTestConfigVersion.cmake` says 1.17.0. | `find_package(GTest 1.17.0 EXACT CONFIG)` first; same immutable fallback; `TIPLOG_FORCE_FETCH_GTEST` allows meaningful validation of the fallback. No GoogleMock/installation is needed. |
| S45 / VALIDATION §4 | [ASan Usage](https://clang.llvm.org/docs/AddressSanitizer.html#usage): compile and link with sanitizer flags, Clang final linker, frame pointers, `-O1`. [UBSan Usage and stack traces](https://clang.llvm.org/docs/UndefinedBehaviorSanitizer.html#usage): compile/link flags, stop-on-error and stacktrace runtime options. | Clang sanitizer presets compile and link with ASan/UBSan, disable recovery and retain frame pointers; CTest presets set ASAN_OPTIONS and UBSAN_OPTIONS. |
| S45 / no fake P0 fuzz target | [LLVM libFuzzer Fuzzer Usage](https://llvm.org/docs/LibFuzzer.html#fuzzer-usage), specifically the distinction between `fuzzer` linking main and `fuzzer-no-link` instrumentation. | Fuzz preset instruments normal plumbing without replacing GoogleTest main. `tiplog::fuzzer_options` adds `-fsanitize=fuzzer` for future real F1–F3 targets. P0 does not claim a timed fuzz run. |
| CMake reproducible dependency setup | [CMake 4.4 FetchContent Overview, Declare, MakeAvailable](https://cmake.org/cmake/help/v4.4/module/FetchContent.html); [CMake presets](https://cmake.org/cmake/help/v4.4/manual/cmake-presets.7.html) schema overview and configure/build/test presets. | Use FetchContent_MakeAvailable, immutable URL_HASH checks, TLS verification and local archive cache; Unix Makefiles; separate named build directories and test presets. Online docs render 4.4.4, while installed executable is 4.4.0; only supported local behavior is relied on. |

The online LLVM documentation is live documentation, not a source-code audit or a new compiler pin. Actual local compilers remain GCC 15.2.0 and Clang 21.1.8. No algorithm or implementation detail is taken from Jane Street for this P0 plumbing. No external implementation code was copied into project-owned source files.

## Exact dependency identities

| Dependency | Fixed URL | SHA-256 | Local archive |
|---|---|---|---|
| Google Benchmark v1.9.5 | `https://codeload.github.com/google/benchmark/tar.gz/192ef10025eb2c4cdd392bc502f0c852196baa48` | `f82705a2726d8f6cdcda274b841f6314dbfc6f731cdda06c946f310ec1cc3ad9` | `build/downloads/benchmark-1.9.5.tar.gz` |
| GoogleTest v1.17.0 | `https://codeload.github.com/google/googletest/tar.gz/52eb8108c5bdec04579160ae17225d66034bd723` | `745c55415660044610f7fcd3af7a6420d5de16a7dbb9ebfe2e131275676232be` | `build/downloads/googletest-1.17.0.tar.gz` |

Inspected license headers: Benchmark archive `LICENSE` is Apache 2.0; GoogleTest archive `LICENSE` has the Google copyright and redistribution conditions. Complete upstream license files remain in original archives and extracted dependency directories. Dependencies are linked/compiled as dependencies; no upstream code was adapted into project sources.

## Executed commands and observations

- `g++ --version`, `clang++ --version`, `cmake --version`: GCC 15.2.0, Clang 21.1.8, CMake 4.4.0.
- Initial sandboxed `curl -L --fail --silent --show-error https://api.github.com/repos/google/benchmark/git/ref/tags/v1.9.5`: failed DNS, exit 6. Retried with automatic sandbox review for the authorized dependency fetch; both tag metadata requests succeeded, exit 0. No system configuration changed.
- `curl -L --fail --silent --show-error https://api.github.com/repos/google/benchmark/git/ref/tags/v1.9.5` and corresponding `/google/googletest/git/ref/tags/v1.17.0`: returned commit objects above.
- `curl -L --fail --silent --show-error https://codeload.github.com/google/benchmark/tar.gz/192ef10025eb2c4cdd392bc502f0c852196baa48 -o build/downloads/benchmark-1.9.5.tar.gz`: exit 0.
- `curl -L --fail --silent --show-error https://codeload.github.com/google/googletest/tar.gz/52eb8108c5bdec04579160ae17225d66034bd723 -o build/downloads/googletest-1.17.0.tar.gz`: exit 0.
- `sha256sum build/downloads/*.tar.gz`: hashes above, exit 0.
- `tar -xOf` reads of the pinned CMakeLists.txt and license headers: exit 0; no archive content was executed during source inspection.
- `cmake --list-presets=all`: exit 0; debug/release/asan-ubsan/fuzz appear for configure, build and test.

Build/test execution is owned by the parent agent and must be recorded from its actual logs. At this handoff, the commands above do not establish that any build or CTest passed.

## Files written

`CMakeLists.txt`, `CMakePresets.json`, `cmake/deps.cmake`, `tests/unit/smoke_test.cpp` only. No changes to `.git`, scripts, planning documents, MASTER_PROJECT_PROMPT.md, engine source, datasets or optional dependencies.

The project smoke test is `plumbing.Plumbing.Cxx20AndGoogleTest`. There are no fake fuzz targets. The fallback flag is `TIPLOG_FORCE_FETCH_GTEST=ON`; configuring it in `build/gtest-fallback` preserves the named preset builds. Use a separate `build/release-clang` directory for the RC-3 cross-compiler check.
