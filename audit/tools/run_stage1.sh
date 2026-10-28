#!/usr/bin/env bash
# Stage 1 audit pipeline. Read-only with respect to the project: it copies the
# repository into a scratch directory, builds and tests only there, reads the
# raw/trace data in place, and writes evidence only under audit/evidence/.
#   audit/tools/run_stage1.sh <scratch-dir> [stages...]   (default: A B C D)
set -u
ROOT=${TIPLOG_AUDIT_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)}
SP=${1:?scratch directory required}; shift
STAGES=${*:-A B C D E}
EV="$ROOT/audit/evidence"
TOOLS=${TIPLOG_AUDIT_TOOLS:-$ROOT/audit/tools}
PY="$ROOT/.venv/bin/python"
W="$SP/work"
mkdir -p "$SP/stray" "$EV"
# Any instrumented binary that runs without an explicit profile path lands here,
# never in the project tree.
export LLVM_PROFILE_FILE="$SP/stray/%p.profraw"
export MPLCONFIGDIR="$SP/mpl" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
cd "$SP"

step() {  # step STAGE NAME CMD... ; logs to evidence, records rc and seconds
  local stage=$1 name=$2; shift 2
  local dir="$EV/$stage"; mkdir -p "$dir"
  local start; start=$(date +%s.%N)
  "$@" > "$dir/$name.log" 2>&1
  local rc=$?
  printf '%s\t%s\t%s\t%.1f\n' "$(date -u +%FT%TZ)" "$name" "$rc" "$(echo "$(date +%s.%N) - $start" | bc)" >> "$dir/steps.tsv"
  return $rc
}

stage_A() {
  local S=A_baseline
  rm -rf "$EV/$S"; mkdir -p "$EV/$S"
  rm -rf "$W"; mkdir -p "$W"
  step $S copy rsync -a --exclude=/build --exclude=/data/raw --exclude=/data/traces --exclude=/results/raw \
    --exclude=/results/derived --exclude=/.venv --exclude=/.tiplog-git --exclude=__pycache__ \
    --exclude=.pytest_cache --exclude=/audit "$ROOT/" "$W/"
  mkdir -p "$W/build" && cp -a "$ROOT/build/downloads" "$W/build/"
  step $S environment bash -c 'uname -a; nproc; free -g; g++ --version | head -1; clang++ --version | head -1;
    cmake --version | head -1; "$0" --version; "$0" -m pip list; "$0" -m pip check; git --version' "$PY"
  for p in release debug asan-ubsan fuzz; do
    (cd "$W" && step $S "configure-$p" cmake --preset "$p")
    (cd "$W" && step $S "build-$p" nice cmake --build --preset "$p" --parallel 6)
  done
  for p in release debug asan-ubsan fuzz; do
    (cd "$W" && step $S "ctest-$p" ctest --preset "$p" -j4 --output-junit "$EV/$S/ctest-$p.xml")
  done
  (cd "$W" && step $S pytest-documented-root "$PY" -m pytest -c py/pytest.ini py/tests -q -p no:cacheprovider -rs)
  (cd "$W/py" && step $S pytest-from-py-dir "$PY" -m pytest -q -p no:cacheprovider -rf)
}

stage_B() {
  local S=B_audit_tests
  rm -rf "$EV/$S"; mkdir -p "$EV/$S"
  local SAN="-O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer"
  local COV="-O1 -g -fprofile-instr-generate -fcoverage-mapping"
  step $S configure-release cmake -S "$ROOT/audit/tests" -B "$SP/audit-release" -DTIPLOG_ROOT="$W" \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=g++ "-DCMAKE_CXX_FLAGS_RELEASE=-O2 -g -march=x86-64-v3 -DNDEBUG" \
    -DTIPLOG_DOWNLOAD_CACHE="$W/build/downloads"
  step $S build-release nice cmake --build "$SP/audit-release" -j6
  step $S configure-asan cmake -S "$ROOT/audit/tests" -B "$SP/audit-asan" -DTIPLOG_ROOT="$W" \
    -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_COMPILER=clang++ "-DCMAKE_CXX_FLAGS_DEBUG=$SAN" \
    "-DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address,undefined" -DTIPLOG_DOWNLOAD_CACHE="$W/build/downloads"
  step $S build-asan nice cmake --build "$SP/audit-asan" -j6
  step $S configure-cov cmake -S "$ROOT/audit/tests" -B "$SP/audit-cov" -DTIPLOG_ROOT="$W" \
    -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_COMPILER=clang++ "-DCMAKE_CXX_FLAGS_DEBUG=$COV" \
    "-DCMAKE_EXE_LINKER_FLAGS=-fprofile-instr-generate" -DTIPLOG_DOWNLOAD_CACHE="$W/build/downloads"
  step $S build-cov nice cmake --build "$SP/audit-cov" -j6
  local PROJ="tiplog_ring_test tiplog_index_test tiplog_engine_test tiplog_engine_index_test tiplog_engine_merge_test
    tiplog_merge_test tiplog_topics_subs_test tiplog_trace_test tiplog_driver_test tiplog_layout_test tiplog_oracle_test
    tiplog_oracle_tail_test tiplog_bench_contract_test"
  step $S build-cov-project nice make -C "$SP/audit-cov/tiplog" -j6 $PROJ
  local AUD="audit_trace_test audit_engine_test audit_layout_test audit_pressure_test audit_checker_test audit_redteam_test audit_red_spec_test"
  for t in $AUD; do (cd "$SP/audit-release" && step $S "release-$t" "./$t"); done
  export ASAN_OPTIONS=detect_leaks=1:abort_on_error=1 UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1
  for t in $AUD; do
    (cd "$SP/audit-asan" && step $S "asan-$t" "./$t" --gtest_filter=-AuditRedTeam.PressurePublishCostIsProportionalToEviction)
  done
  unset ASAN_OPTIONS UBSAN_OPTIONS
  (cd "$ROOT" && export TIPLOG_ROOT="$W" TIPLOG_BUILD="$W/build/release" && step $S pytest-audit \
    "$PY" -m pytest -p no:cacheprovider -q --rootdir=audit/tests/py audit/tests/py -rf)
  # Coverage: project unit tests alone, then project + audit tests.
  mkdir -p "$SP/cov"; rm -f "$SP/cov"/*.profraw
  local objs="" aobjs=""
  for t in $PROJ; do
    (cd "$SP/audit-cov" && LLVM_PROFILE_FILE="$SP/cov/proj-$t.profraw" "./tiplog/$t" > /dev/null 2>&1) || echo "coverage run failed: $t" >> "$EV/$S/coverage-runs.txt"
    objs="$objs -object $SP/audit-cov/tiplog/$t"
  done
  aobjs="$objs"
  for t in audit_trace_test audit_engine_test audit_layout_test audit_pressure_test audit_checker_test; do
    (cd "$SP/audit-cov" && LLVM_PROFILE_FILE="$SP/cov/audit-$t.profraw" "./$t" > /dev/null 2>&1) || echo "coverage run failed: $t" >> "$EV/$S/coverage-runs.txt"
    aobjs="$aobjs -object $SP/audit-cov/$t"
  done
  llvm-profdata-21 merge -o "$SP/cov/proj.profdata" "$SP"/cov/proj-*.profraw
  llvm-profdata-21 merge -o "$SP/cov/all.profdata" "$SP"/cov/proj-*.profraw "$SP"/cov/audit-*.profraw
  local first="$SP/audit-cov/tiplog/tiplog_ring_test" ignore='(tests/|_deps/|/usr/|audit/)'
  step $S coverage-project llvm-cov-21 report $first $objs -instr-profile="$SP/cov/proj.profdata" -ignore-filename-regex="$ignore"
  step $S coverage-project-plus-audit llvm-cov-21 report $first $aobjs -instr-profile="$SP/cov/all.profdata" -ignore-filename-regex="$ignore"
  for f in ring/ring.cpp engine/engine.cpp index/index.cpp topics/registry.cpp trace/reader.cpp; do
    llvm-cov-21 show $first $objs -instr-profile="$SP/cov/proj.profdata" "$W/src/tiplog/$f" 2>/dev/null |
      awk -F'|' -v f="$f" '$2 ~ /^ *0$/ {gsub(/^ +/,"",$1); s=$3; gsub(/^ +/,"",s); print f ":" $1 ": " substr(s,1,120)}'
  done > "$EV/$S/uncovered-lines-project-tests.txt"
  # Red-team probes (run while nothing else heavy is running).
  g++ -std=c++20 -O2 -march=x86-64-v3 -DNDEBUG -I"$W/src" "$TOOLS/depth_probe.cpp" \
    "$SP/audit-release/tiplog/libtiplog_engine.a" "$SP/audit-release/tiplog/libtiplog_topics_subs.a" \
    "$SP/audit-release/tiplog/libtiplog_ring.a" "$SP/audit-release/tiplog/libtiplog_index.a" \
    "$SP/audit-release/tiplog/libtiplog_merge.a" -o "$SP/depth_probe"
  step $S redteam-depth-probe bash -c 'for d in 1000 2000 4000 8000; do "$0" $d; "$0" $d hook; done' "$SP/depth_probe"
  mkdir -p "$SP/redteam"
  (cd "$SP/redteam" && export PYTHONPATH="$W/py" && step $S redteam-make-trace "$PY" "$TOOLS/make_deep_trace.py" "$SP/redteam/deep.mdt" 16000 4)
  step $S redteam-trace-check "$W/build/release/tiplog_trace_check" "$SP/redteam/deep.mdt"
  step $S redteam-sim-unlimited /usr/bin/time -v "$W/build/release/tiplog_sim" --trace "$SP/redteam/deep.mdt"
  step $S redteam-sim-1500MB bash -c 'ulimit -v 1500000; exec "$0" --trace "$1"' "$W/build/release/tiplog_sim" "$SP/redteam/deep.mdt"
  ls -l "$SP/redteam/deep.mdt" > "$EV/$S/redteam-trace-size.txt"
}

stage_C() {
  local S=C_reproductions
  rm -rf "$EV/$S"; mkdir -p "$EV/$S/cc2" "$EV/$S/rc3"
  local B="$W/build/release" seeds="--seeds 1000 --operations 10000 --seed-base 20191230"
  cc2() { "$B/tiplog_differential" $seeds --mode "$1" --kernel "$2" > "$EV/$S/cc2/cc2-$1-$2.json" 2> "$EV/$S/cc2/cc2-$1-$2.err"; }
  local start; start=$(date +%s)
  (cc2 scan stdpq & cc2 indexed stdpq & cc2 indexed binheap & cc2 indexed quad & wait)
  (cc2 indexed loser & cc2 auto stdpq & cc2 auto binheap & cc2 auto quad & wait)
  cc2 auto loser
  echo "cc2 wall seconds $(( $(date +%s) - start ))" >> "$EV/$S/steps.tsv"
  step $S cc2-compare python3 "$TOOLS/compare.py" cc2 "$EV/$S/cc2" "$ROOT/results/p5/CC2-all-configurations.json"
  step $S cc5 "$B/tiplog_layout_cc5" --instances 10000 --seed 20191230 --output "$SP/cc5-out.json"
  step $S cc5-compare-recorded python3 "$TOOLS/compare.py" cc5 "$SP/cc5-out.json" "$ROOT/results/p7/cc5-release.json"
  step $S v32 "$B/tiplog_layout_example" --output "$SP/worked-example.json"
  python3 -m json.tool "$SP/worked-example.json" > "$SP/v32-new.txt"
  python3 -m json.tool "$ROOT/results/p7/worked-example.json" > "$SP/v32-recorded.txt"
  step $S v32-diff-recorded diff "$SP/v32-new.txt" "$SP/v32-recorded.txt"
  step $S cc6-full-day-walker bash -o pipefail -c 'gzip -dc "$0" | nice "$1" - --out "$2"' \
    "$ROOT/data/raw/12302019.NASDAQ_ITCH50.gz" "$B/tiplog_walk" "$EV/$S/cc6-cpp-counts.json"
  step $S cc6-equal-recorded-cpp cmp "$EV/$S/cc6-cpp-counts.json" "$ROOT/results/data/itch_20191230_counts_cpp.json"
  step $S cc6-compare-recorded-python python3 "$TOOLS/compare.py" counts "$EV/$S/cc6-cpp-counts.json" "$ROOT/results/data/itch_20191230_counts.json"
  (cd "$W" && export PYTHONPATH=py && step $S cc6-python-prefix "$PY" -m tiplog_py.itch measure "$ROOT/data/raw/12302019.NASDAQ_ITCH50.gz" \
    --output "$SP/py-prefix.json" --limit-bytes 500000000)
  local N; N=$(python3 -c "import json;print(json.load(open('$SP/py-prefix.json'))['total_uncompressed_bytes'])")
  step $S cc6-cpp-prefix bash -c 'gzip -dc "$0" 2>/dev/null | head -c "$1" | "$2" - --out "$3"' \
    "$ROOT/data/raw/12302019.NASDAQ_ITCH50.gz" "$N" "$B/tiplog_walk" "$SP/cpp-prefix.json"
  step $S cc6-prefix-compare python3 "$TOOLS/compare.py" counts "$SP/py-prefix.json" "$SP/cpp-prefix.json"
  (cd "$W" && step $S rc3-clang-configure cmake -S . -B build/release-clang -DCMAKE_CXX_COMPILER=clang++ \
    -DCMAKE_BUILD_TYPE=Release "-DCMAKE_CXX_FLAGS_RELEASE=-O2 -g -march=x86-64-v3 -DNDEBUG" -DBUILD_TESTING=OFF)
  (cd "$W" && step $S rc3-clang-build nice cmake --build build/release-clang --target tiplog_sim -j6)
  local T="$ROOT/data/traces/itch_20191230_0930_1000_spec.mdt"
  sha256sum "$T" > "$EV/$S/rc3-trace-sha256.txt"
  for cc in release release-clang; do
    for cfg in "scan stdpq" "indexed loser" "indexed quad" "auto binheap"; do
      set -- $cfg
      "$W/build/$cc/tiplog_sim" --trace "$T" --seed 20191230 --max-records 2000000 --budget 64 --jitter-budget \
        --subtree itch/AAPL --subtree itch/MSFT --mode "$1" --kernel "$2" --ring-bytes 16777216 --max-record-bytes 4096 \
        --pool-blocks 16384 --block-entries 1024 > "$EV/$S/rc3/$cc-$1-$2-narrow.json"
      "$W/build/$cc/tiplog_sim" --trace "$T" --seed 20191230 --max-records 2000000 --budget 16 --consume-every 4 \
        --pause 1000:200000 --subtree itch/AAPL --subtree itch/MSFT --mode "$1" --kernel "$2" --ring-bytes 1048576 \
        --max-record-bytes 4096 --pool-blocks 16384 --block-entries 64 > "$EV/$S/rc3/$cc-$1-$2-expiry.json"
    done
    "$W/build/$cc/tiplog_sim" --trace "$T" --seed 20191230 --max-records 2000000 --budget 256 --mode scan \
      --ring-bytes 16777216 --max-record-bytes 4096 > "$EV/$S/rc3/$cc-scan-wide.json"
  done
  step $S rc3-compare python3 "$TOOLS/compare.py" rc3 "$EV/$S/rc3"
}

stage_D() {
  local S=D_static_mutation_deps_fuzz
  rm -rf "$EV/$S"; mkdir -p "$EV/$S"
  local files; files=$(cd "$W" && ls src/tiplog/*/*.cpp tools/*/*.cpp tools/*.cpp bench/micro/*.cpp)
  (cd "$W" && step $S clang-tidy nice clang-tidy -p build/release --quiet \
    -checks='-*,bugprone-*,cert-*,clang-analyzer-*,performance-*,concurrency-*,-bugprone-easily-swappable-parameters,-cert-err58-cpp,-bugprone-narrowing-conversions,-cert-dcl21-cpp' $files)
  (cd "$W" && step $S gcc-fanalyzer bash -c 'for f in src/tiplog/*/*.cpp; do g++ -std=c++20 -O1 -fanalyzer -Isrc -c "$f" -o /dev/null; done')
  rm -rf "$SP/mut" "$SP/mut-build"
  rsync -a --exclude=/build "$W/" "$SP/mut/" && mkdir -p "$SP/mut/build" && cp -a "$W/build/downloads" "$SP/mut/build/"
  step $S mutation-configure cmake -S "$ROOT/audit/tests" -B "$SP/mut-build" -DTIPLOG_ROOT="$SP/mut" \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=g++ "-DCMAKE_CXX_FLAGS_RELEASE=-O1 -DNDEBUG" \
    -DTIPLOG_DOWNLOAD_CACHE="$SP/mut/build/downloads"
  step $S mutation-run nice python3 "$TOOLS/run_mutants.py" "$SP/mut" "$SP/mut-build" "$EV/$S/mutation-results.json"
  rm -rf "$SP/auditvenv"
  /usr/bin/python3 -m venv "$SP/auditvenv" && "$SP/auditvenv/bin/python" -m pip install -q pip-audit==2.9.0 > "$EV/$S/pip-audit-install.log" 2>&1
  step $S pip-audit "$SP/auditvenv/bin/pip-audit" -r "$ROOT/py/requirements.txt" --no-deps --disable-pip \
    --progress-spinner off -f json -o "$EV/$S/pip-audit.json"
  step $S osv-cpp-pins bash -c 'for c in 52eb8108c5bdec04579160ae17225d66034bd723 192ef10025eb2c4cdd392bc502f0c852196baa48; do
    echo "$c $(curl -s --max-time 30 https://api.osv.dev/v1/query -d "{\"commit\":\"$c\"}")"; done'
  step $S dependency-archive-sha256 sha256sum "$ROOT"/build/downloads/*.tar.gz
  export ASAN_OPTIONS=detect_leaks=1:abort_on_error=1 UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1
  local F="$W/build/fuzz" D="$W/tests/fuzz"
  mkdir -p "$SP/fuzz"
  for c in itch_walker ops trace_reader; do rm -rf "$SP/fuzz/corpus-$c"; cp -a "$D/corpus/$c" "$SP/fuzz/corpus-$c"; done
  (cd "$SP/fuzz" && step $S fuzz-trace_reader-300s nice "$F/fuzz_trace_reader" -max_total_time=300 \
    -dict="$D/trace_reader.dict" -artifact_prefix="$SP/fuzz/art-trace-" "$SP/fuzz/corpus-trace_reader")
  (cd "$SP/fuzz" && step $S fuzz-itch_walker-300s nice "$F/fuzz_itch_walker" -max_total_time=300 \
    -dict="$D/itch_walker.dict" -artifact_prefix="$SP/fuzz/art-itch-" "$SP/fuzz/corpus-itch_walker")
  (cd "$SP/fuzz" && export TIPLOG_FUZZ_MODE=all && step $S fuzz-engine_ops-all-600s nice "$F/fuzz_engine_ops" \
    -max_total_time=600 -artifact_prefix="$SP/fuzz/art-ops-" "$SP/fuzz/corpus-ops")
  ls -la "$SP/fuzz" | grep art- > "$EV/$S/fuzz-artifacts.txt" || echo "no crash artifacts" > "$EV/$S/fuzz-artifacts.txt"
  unset ASAN_OPTIONS UBSAN_OPTIONS
}

stage_E() {
  local S=E_p7_recompute
  rm -rf "$EV/$S"; mkdir -p "$EV/$S"
  rm -rf "$SP/p7in"
  (cd "$W" && export PYTHONPATH=py && step $S p7-generate-inputs "$PY" -m tiplog_py.layout.inputs \
    --output-dir "$SP/p7in" --skip-synthetic --data-dir results/data)
  step $S p7-input-sha256 bash -c 'cd "$0" && sha256sum real-H-spec-W1-beta0.tsv real-H-spec-W2-beta0.tsv real-H-spec-W1-beta1048576.tsv' "$SP/p7in"
  local limits="--enum-max-edges 22 --dp-max-classes 16 --max-states 2000000 --max-work 2000000 --time-limit-ms 500"
  for w in W1 W2; do
    step $S "p7-layout-H-spec-$w-beta0" "$W/build/release/tiplog_layout" --input "$SP/p7in/real-H-spec-$w-beta0.tsv" \
      --output "$SP/p7-$w.jsonl" --methods base,km-min,dp --full-curves $limits
    step $S "p7-summary-H-spec-$w-beta0" python3 "$TOOLS/compare.py" p7sum "$SP/p7-$w.jsonl"
  done
}

for s in $STAGES; do "stage_$s"; echo "stage $s finished $(date -u +%FT%TZ)" >> "$EV/pipeline.txt"; done
ls -la "$SP/stray" > "$EV/stray-profraw-check.txt"
scripts_status=$("$ROOT/scripts/git.sh" status --short | wc -l)
echo "project git status entries after pipeline: $scripts_status (281 pre-audit + audit/)" >> "$EV/pipeline.txt"
