#!/usr/bin/env python3
"""Run F-01 contract-test negative controls without editing production files.

Build the default GCC Release preset first. This script compiles isolated copies of the
current Engine and the focused test, and borrows only its unchanged dependency
libraries from --build-root. A positive control must pass, and all four deliberate
contract violations must fail their focused regression. Logs and SHA-256 source
identities go to the new F-01 results tree, never to historical phase outputs.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replacements(source: str, changes: list[tuple[str, str]]) -> str:
    for before, after in changes:
        if source.count(before) != 1:
            raise ValueError(f"mutation site must be unique: {before!r}")
        source = source.replace(before, after)
    return source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=pathlib.Path, default=ROOT / "build/release")
    parser.add_argument("--output-dir", type=pathlib.Path,
                        default=ROOT / "results/f01/contract-mutations")
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    build = args.build_root.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work_root = ROOT / "build/f01"
    work_root.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="contract-mutations-", dir=work_root))
    overlay = work / "include/tiplog/engine"
    overlay.mkdir(parents=True)
    cpp = ROOT / "src/tiplog/engine/engine.cpp"
    header = ROOT / "src/tiplog/engine/engine.hpp"
    test = ROOT / "tests/unit/poll_budget_test.cpp"
    source = cpp.read_text()
    (work / "engine.original.cpp").write_text(source)
    shutil.copyfile(header, overlay / "engine.hpp")
    shutil.copyfile(test, work / "poll_budget_test.cpp")
    source_identities = {
        str(path.relative_to(ROOT)): digest(path)
        for path in (cpp, header, test, pathlib.Path(__file__).resolve())
    }
    scan_charge = """    if constexpr (Report)
      ++inspections;
    work_.bytes_inspected += item.size;"""
    indexed_charge = """        if constexpr (Report)
          ++inspections;
        ++work_.entries_visited;"""
    indexed_match = """        if (filter != nullptr && filter->matches(topic.local_id)) {
          out.push_back"""
    controls = {
        "charge-matches-only": (
            [(scan_charge, """    if constexpr (Report)
      if (!item.pad && sub_.matches(item.topic))
        ++inspections;
    work_.bytes_inspected += item.size;"""),
             (indexed_charge, """        ++work_.entries_visited;"""),
             (indexed_match, """        if (filter != nullptr && filter->matches(topic.local_id)) {
          if constexpr (Report)
            ++inspections;
          out.push_back""")],
            "PollBudget.V01V02RejectingCandidatesHaveExactIndependentProgress"),
        "pad-is-free": (
            [(scan_charge, """    if constexpr (Report)
      if (!item.pad)
        ++inspections;
    work_.bytes_inspected += item.size;""")],
            "PollBudget.V01ScanPadConsumesOneUnitWithoutInventingSequenceProgress"),
        "reset-tail-inspection-allowance": (
            [("      *remaining.max_inspections -= inspections;",
              "      *remaining.max_inspections -= 0;")],
            "PollBudget.V04TailSharesInspectionAndOutputBudgetsAcrossRanges"),
        "forget-rejected-indexed-progress": (
            [("""          if (limits.max_inspections)
            checkpoint_ = ResumeCheckpoint{item.seq, item.pos + item.size};""",
              """          if (false && limits.max_inspections)
            checkpoint_ = ResumeCheckpoint{item.seq, item.pos + item.size};""")],
            "PollBudget.V02BudgetOneReachesMatchAtEndWithoutSkippingOrRepeating"),
    }
    common = [args.compiler, "-std=c++20", "-O2", "-g", "-march=x86-64-v3", "-DNDEBUG",
              "-I" + str(work / "include"), "-I" + str(ROOT / "src")]
    phases: list[dict] = []

    def command(name: str, number: int, argv: list[str]) -> dict:
        process = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                                 timeout=120)
        log = output / f"{name}.{number}.log"
        log.write_text(process.stdout + process.stderr)
        return {"argv": argv, "exit_code": process.returncode,
                "log": str(log.relative_to(ROOT)), "log_sha256": digest(log)}

    test_object = work / "poll_budget_test.o"
    test_compile = command("test-compile", 0, common + [
        "-I" + str(ROOT / "tests/ref"), "-isystem",
        str(build / "_deps/googletest-src/googletest/include"),
        "-c", str(work / "poll_budget_test.cpp"), "-o", str(test_object)])
    if test_compile["exit_code"] != 0:
        raise RuntimeError(f"test compilation failed; see {test_compile['log']}")

    def run_control(job: tuple[str, list[tuple[str, str]], str]) -> dict:
        name, changes, test_filter = job
        isolated_cpp = work / (name + ".cpp")
        obj = work / (name + ".o")
        binary = work / name
        isolated_cpp.write_text(replacements(source, changes))
        jobs = [
            common + ["-c", str(isolated_cpp), "-o", str(obj)],
            [args.compiler, "-O2", "-g", "-march=x86-64-v3", "-DNDEBUG",
             str(test_object), str(obj), "-o", str(binary),
             *[str(build / part) for part in [
                 "libtiplog_ref.a", "lib/libgtest_main.a", "libtiplog_ring.a",
                 "libtiplog_index.a", "libtiplog_merge.a", "libtiplog_topics_subs.a",
                 "lib/libgtest.a"]]],
            [str(binary), "--gtest_color=no", "--gtest_filter=" + test_filter],
        ]
        records = []
        for number, argv in enumerate(jobs):
            record = command(name, number, argv)
            records.append(record)
            if number < 2 and record["exit_code"] != 0:
                raise RuntimeError(f"control build failed; see {record['log']}")
        expected_exit = 0 if not changes else 1
        success = records[-1]["exit_code"] == expected_exit
        return {"name": name, "kind": "positive-control" if not changes else "negative-control",
                "status": ("passed" if not changes else "killed") if success else "failed",
                "source_sha256": digest(isolated_cpp), "phases": records}

    jobs = [("positive-control", [], "PollBudget.*")]
    jobs.extend((name, changes, selected) for name, (changes, selected) in controls.items())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        phases = list(pool.map(run_control, jobs))
    unchanged = all(digest(ROOT / path) == expected
                    for path, expected in source_identities.items())
    passed = unchanged and all(row["status"] != "failed" for row in phases)
    result = {"status": "passed" if passed else "failed", "source_identities": source_identities,
              "production_sources_unchanged": unchanged,
              "test_compile": test_compile, "test_object_sha256": digest(test_object),
              "controls": phases}
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({row["name"]: row["status"] for row in phases}, indent=2), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
