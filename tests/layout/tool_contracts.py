#!/usr/bin/env python3
"""Functional CLI contracts; tiny fixtures only, no performance acceptance runs."""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

BIN = Path(sys.argv[1]).resolve()
sys.argv[1:] = []


class ToolContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tiplog-tools-")
        self.root = Path(self.temporary.name)
        self.mix = self.root / "mix.csv"
        self.mix.write_text("type,payload_bytes,count\nA,12,1\nB,64,1\n")
        self.trace = self.root / "empty.mdt"
        self.write_trace(self.trace, 0)
        self.case = "CASE\tone\t2\nCOST\t1\t0\t0\nNODE\t-\t1\tr\nNODE\t0\t1\tr/a\nCLASS\ta\t1\nTERM\tS\tr\nEND\n"

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def write_trace(path, records):
        data = bytearray(64)
        data[:8] = b"TPLTRC\0\1"
        struct.pack_into("<I", data, 8, 1)
        for i in range(records):
            data.extend(struct.pack("<IHHQ", 1, 16, 0, i))
            data.extend(bytes(range(16)))
        offset = len(data)
        data.extend(struct.pack("<IIH", 1, 1, 5) + b"r/a/e")
        struct.pack_into("<QQQ", data, 16, records, offset, len(data) - offset)
        path.write_bytes(data)

    def command(self, name, *args, text=None, success=True, stdout=None, env=None, cwd=None):
        result = subprocess.run([str(BIN / name), *map(str, args)], input=text,
                                text=True, stdout=stdout or subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=30, env=env, cwd=cwd)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def bench(self, output, *args, success=True):
        return self.command("tiplog_bench", "--synthetic", "--records", "100",
                            "--partitions", "4", "--mix", self.mix,
                            "--ring-bytes", "8192", "--output", output,
                            *args, success=success)

    def test_final_evidence_write_failures(self):
        if not Path("/dev/full").exists():
            self.skipTest("requires /dev/full")
        self.bench("/dev/full", success=False)
        self.bench("/dev/full", "--memory", success=False)
        self.bench("/dev/full", "--allocator-replay", success=False)
        self.command("tiplog_layout_example", "--output", "/dev/full", success=False)
        self.command("tiplog_layout_cc5", "--instances", "1", "--output", "/dev/full", success=False)
        with open("/dev/full", "w") as full:
            self.command("tiplog_layout_example", stdout=full, success=False)
            self.command("tiplog_layout_cc5", "--instances", "1", stdout=full, success=False)
        valid = self.root / "valid.jsonl"
        self.bench(valid, "--memory")
        self.assertEqual([row["kind"] for row in map(json.loads, valid.read_text().splitlines())],
                         ["prefill", "memory"])
        example = self.root / "example.json"
        self.command("tiplog_layout_example", "--output", example)
        self.assertIn("rows", json.loads(example.read_text()))
        cc5 = self.root / "cc5.json"
        self.command("tiplog_layout_cc5", "--instances", "1", "--output", cc5)
        self.assertEqual(json.loads(cc5.read_text())["status"], "passed")

    def test_mix_validates_all_rows_and_uint64_sum(self):
        for data in ("bad\nA,12,1\n", "type,payload_bytes,count\nA,12,1\nB,bad,1\n",
                     "type,payload_bytes,count\nA,12,9223372036854775809\nB,64,9223372036854775809\n"):
            self.mix.write_text(data)
            output = self.root / "rejected.jsonl"
            output.unlink(missing_ok=True)
            self.bench(output, success=False)
            self.assertEqual(output.read_text(), "")
            self.command("publish_bench", "--verify-only", "--mix-file", self.mix, success=False)
        self.mix.write_text("type,payload_bytes,count\nA,12,1\nB,64,18446744073709551614\n")
        output = self.root / "boundary.jsonl"
        self.bench(output)
        self.assertEqual(json.loads(output.read_text())["publications"], 100)

    def test_sim_fraction_validation_is_backend_independent(self):
        for backend in ("recording", "engine"):
            for value in ("nan", "inf", "-inf", "-0.1", "1.01"):
                result = self.command("tiplog_sim", "--trace", self.trace, "--backend", backend,
                                      "--auto-max-index-fraction", value, success=False)
                self.assertIn("finite Auto fraction", result.stderr)
            for value in ("0", "1"):
                result = self.command("tiplog_sim", "--trace", self.trace, "--backend", backend,
                                      "--auto-max-index-fraction", value)
                self.assertEqual(json.loads(result.stdout)["auto_max_index_fraction"], int(value))

    def test_layout_run_budgets_cover_aggregate_curves_input_and_preparation(self):
        curves = "CURVE\ta\t1\t2\t0\nPOINT\t1\t1\nEND\nCURVE\tb\t1\t2\t0\nPOINT\t1\t2\nEND\n"
        for name in ("tiplog_layout", "tiplog_layout_runtime"):
            if not (BIN / name).exists():
                continue
            failed = self.command(name, "--global-curves", "-", "--max-curve-entries", "5",
                                  "--max-states", "3", text=curves, success=False)
            self.assertIn("aggregate CURVE entries", failed.stdout)
            valid = self.command(name, "--global-curves", "-", "--max-curve-entries", "6",
                                 "--max-states", "3", text=curves)
            self.assertIn("global_point", valid.stdout)
            self.command(name, "--input", "-", "--methods", "base", "--max-input-bytes",
                         str(len(self.case) - 1), text=self.case, success=False)
            # One class + one term, two positive nodes: conservative work=4.
            two_cases = self.case + self.case.replace("one", "two", 1)
            self.command(name, "--input", "-", "--methods", "base", "--max-prepare-work", "7",
                         text=two_cases, success=False)
            valid = self.command(name, "--input", "-", "--methods", "base", "--max-prepare-work", "8",
                                 "--max-prepared-entries", "2", text=two_cases)
            self.assertEqual(len(valid.stdout.splitlines()), 2)
            self.command(name, "--input", "-", "--methods", "base", "--max-prepared-entries", "1",
                         text=self.case, success=False)

    def test_expected_config_rejections_are_explicit_rows(self):
        requests = self.root / "requests.tsv"
        requests.write_text("rejected\tT1\t0\tsubtree:synth/p0\twrong\tquad\trepeat-warm\t64\t1\n"
                            + "deep\tT1\t0\tsubtree:" + "/".join(["a"] * 129)
                            + "\tscan\tquad\trepeat-warm\t64\t1\n")
        output = self.root / "requests.jsonl"
        self.bench(output, "--requests", requests)
        rows = list(map(json.loads, output.read_text().splitlines()))
        self.assertEqual([row["status"] for row in rows[1:]], ["invalid_config", "invalid_config"])
        self.assertIn("Prefill is always measured", self.command("tiplog_bench", "--help").stdout)

    def test_m3_filtering_precedes_input_preparation(self):
        # Selecting no arms should perform no fixture/input allocation at all.
        self.command("index_bench", "--trace", self.root / "absent.mdt",
                     "--benchmark_filter=DOES_NOT_MATCH")
        trace = self.root / "records.mdt"
        self.write_trace(trace, 64)
        verified = json.loads(self.command("index_bench", "--trace", trace, "--verify-only").stdout)
        measured = json.loads(self.command("index_bench", "--trace", trace,
                             "--benchmark_filter=^M3-seek/B64$", "--benchmark_min_time=1x",
                             "--benchmark_format=json").stdout)
        self.assertEqual(len(measured["benchmarks"]), 1)
        label = json.loads(measured["benchmarks"][0]["label"])
        self.assertEqual(label, verified["inputs"][0])
        if Path("/dev/full").exists():
            self.command("index_bench", "--trace", trace,
                         "--benchmark_filter=^M3-seek/B64$", "--benchmark_min_time=1x",
                         env={**os.environ, "TIPLOG_BENCH_INPUTS": "/dev/full"}, success=False)
            failed = self.command("index_bench", "--trace", trace,
                                  "--benchmark_filter=^M3-seek/B64$", "--benchmark_min_time=1x",
                                  "--benchmark_out=/dev/full", success=False)
            self.assertIn("failed writing benchmark result file", failed.stderr)
        output = self.root / "m3.json"
        self.command("index_bench", "--trace", trace,
                     "--benchmark_filter=^M3-seek/B64$", "--benchmark_min_time=1x",
                     "--benchmark_out=" + str(output))
        saved = json.loads(output.read_text())
        self.assertEqual(len(saved["benchmarks"]), 1)
        self.assertEqual(json.loads(saved["benchmarks"][0]["label"]), verified["inputs"][0])

    def test_replay_constructor_config_rejections_are_validated_before_execution(self):
        requests = self.root / "disabled.tsv"
        requests.write_text("disabled\tT1\t0\tsubtree:synth/p0\tindexed\tquad\trepeat-warm\t64\t1\n")
        output = self.root / "disabled.jsonl"
        self.bench(output, "--index-enabled", "0", "--requests", requests)
        rows = list(map(json.loads, output.read_text().splitlines()))
        self.assertEqual(rows[1]["status"], "invalid_config")
        self.assertIn("requires enabled index", rows[1]["reason"])

    def test_output_aliases_preserve_all_source_inputs(self):
        cases = self.root / "cases.tsv"
        cases.write_text(self.case)
        curves = self.root / "curves.tsv"
        curves.write_text("CURVE\tone\t1\t1\t1\nPOINT\t1\t2\nEND\n")
        framed = self.root / "framed.bin"
        framed.write_bytes(b"\0\0")
        requests = self.root / "requests.tsv"
        requests.write_text("one\tT1\t0\tsubtree:synth\tscan\tquad\trepeat-warm\t64\t1\n")
        dictionary = self.root / "terms.tsv"
        dictionary.write_text("")
        for kind in ("direct", "hardlink", "symlink"):
            def alias(source):
                if kind == "direct":
                    return source
                target = self.root / (source.name + "." + kind)
                if target.exists() or target.is_symlink():
                    target.unlink()
                if kind == "hardlink":
                    target.hardlink_to(source)
                else:
                    target.symlink_to(source)
                return target

            for name in ("tiplog_layout", "tiplog_layout_runtime"):
                if not (BIN / name).exists():
                    continue
                for option, source in (("--input", cases), ("--global-curves", curves)):
                    before = source.read_bytes()
                    self.command(name, option, source, "--output", alias(source), success=False)
                    self.assertEqual(source.read_bytes(), before)
            before = framed.read_bytes()
            self.command("tiplog_walk", framed, "--out", alias(framed), success=False)
            self.assertEqual(framed.read_bytes(), before)
            for source in (self.mix, requests, dictionary):
                before = source.read_bytes()
                self.bench(alias(source), "--requests", requests, "--term-dictionary", dictionary,
                           success=False)
                self.assertEqual(source.read_bytes(), before)
            before = self.trace.read_bytes()
            self.command("tiplog_bench", "--trace", self.trace, "--ring-bytes", "8192",
                         "--output", alias(self.trace), success=False)
            self.assertEqual(self.trace.read_bytes(), before)

    def test_microbenchmark_outputs_preserve_inputs_and_remain_distinct(self):
        for name, source, args in (
                ("publish_bench", self.mix, ["--mix-file", self.mix]),
                ("index_bench", self.trace, ["--trace", self.trace])):
            before = source.read_bytes()
            target = self.root / (name + ".hardlink")
            target.hardlink_to(source)
            variables = ["TIPLOG_BENCH_INVOCATIONS", "BENCHMARK_OUT"]
            if name == "index_bench":
                variables.append("TIPLOG_BENCH_INPUTS")
            for variable in variables:
                self.command(name, *args, "--benchmark_filter=DOES_NOT_MATCH",
                             env={**os.environ, variable: str(target)}, success=False)
                self.assertEqual(source.read_bytes(), before)
            self.command(name, *args, "--benchmark_filter=DOES_NOT_MATCH",
                         "--benchmark_out=" + str(target), success=False)
            self.assertEqual(source.read_bytes(), before)
        shared = self.root / "shared.jsonl"
        shared.write_text("preserve\n")
        self.command("merge_bench", "--benchmark_filter=DOES_NOT_MATCH",
                     env={**os.environ, "TIPLOG_BENCH_INPUTS": str(shared),
                          "TIPLOG_BENCH_INVOCATIONS": str(shared)}, success=False)
        self.assertEqual(shared.read_text(), "preserve\n")

    def test_input_filenames_resembling_benchmark_flags_keep_their_meaning(self):
        for name, source, option in (("publish_bench", self.mix, "--mix-file"),
                                     ("index_bench", self.trace, "--trace")):
            fixture_name = name + ".fixture"
            unusual_name = "--benchmark_out=" + fixture_name
            unusual = self.root / unusual_name
            unusual.write_bytes(source.read_bytes())
            (self.root / fixture_name).hardlink_to(unusual)
            before = unusual.read_bytes()
            self.command(name, option, unusual_name, "--benchmark_filter=DOES_NOT_MATCH", cwd=self.root)
            self.assertEqual(unusual.read_bytes(), before)

    def test_request_read_errors_fail_before_output_creation(self):
        rejected = self.root / "read-error.jsonl"
        self.bench(rejected, "--requests", self.root, success=False)
        self.assertFalse(rejected.exists())
        requests = self.root / "empty.tsv"
        requests.write_text("")
        valid = self.root / "empty.jsonl"
        self.bench(valid, "--requests", requests)
        self.assertEqual([row["kind"] for row in map(json.loads, valid.read_text().splitlines())],
                         ["prefill"])

    def test_request_id_named_id_is_not_mistaken_for_a_header(self):
        requests = self.root / "named-id.tsv"
        requests.write_text("id\texperiment\tafter_seq\tterms\tmode\tkernel\tcache\tbatch\treaders\n"
                            "id\tT1\t0\tsubtree:synth\tscan\tquad\trepeat-warm\t64\t1\n")
        output = self.root / "named-id.jsonl"
        self.bench(output, "--requests", requests)
        rows = list(map(json.loads, output.read_text().splitlines()))
        self.assertEqual([row["kind"] for row in rows], ["prefill", "replay"])
        self.assertEqual(rows[1]["id"], "id")
        self.assertEqual(rows[1]["status"], "ok")
        requests.write_text("id\tbad-header\n")
        rejected = self.root / "bad-header.jsonl"
        self.bench(rejected, "--requests", requests, success=False)
        self.assertFalse(rejected.exists())

    def test_microbenchmark_verification_rejects_ignored_and_malformed_arguments(self):
        for option in ("--outputs=8garbage", "--outputs=-1", "--outputs= 8",
                       "--outputs=18446744073709551616", "--touch-bytes=64x",
                       "--seed=-1", "--seed=8x", "--seed=+1"):
            self.command("merge_bench", "--diagnostic", "--profile=uniform64",
                         "--outputs=8", option, success=False)
        for name, args in (("merge_bench", ["--diagnostic", "--profile=uniform64", "--outputs=8"]),
                           ("publish_bench", ["--verify-only", "--mix-file", self.mix]),
                           ("index_bench", ["--verify-only", "--trace", self.trace])):
            result = self.command(name, *args, "--unknown-option", success=False)
            self.assertIn("unrecognized argument in verification mode", result.stderr)
        valid = self.command("merge_bench", "--diagnostic", "--profile=uniform64", "--outputs=8",
                             "--seed=18446744073709551615")
        self.assertEqual(len(valid.stdout.splitlines()), 4)
        for line in valid.stdout.splitlines():
            self.assertEqual(json.loads(line)["input"]["seed"], (1 << 64) - 1)


if __name__ == "__main__":
    unittest.main()
