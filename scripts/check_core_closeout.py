#!/usr/bin/env python3
"""Verify saved final-core evidence without building, timing, fuzzing or converting.

This is a verifier, not a phase gate. It deliberately does not require a P8 gate:
the gate may be written only after this checker and the final review pass. See
results/p8/checker-design.md for the acceptance-evidence contract and limitations.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import stat
import statistics
import subprocess
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
CRITERIA = [f"CC-{n}" for n in range(1, 7)] + [f"RC-{n}" for n in range(1, 4)]
CORE = {
    "CORE-1": "All P0-P7 core phase DoDs and their executed evidence",
    "CORE-2": "CC-1 through CC-6 and RC-1 through RC-3",
    "CORE-3": "Every applicable fuzz target passed its last >=1800-second gate; crashes resolved/regressed",
    "CORE-4": "Input checksums/local-data requirements; no message-level data in tracked packaging",
    "CORE-5": "One-command F01-F18 regeneration and claims linked to saved raw evidence",
    "CORE-6": "Non-ok outcomes/uncertainty retained; no unsupported latency or percentile claims",
    "CORE-7": "Optimizer exactness/coverage correctly scoped and worked example reproduced",
    "CORE-8": "Limitations/threats and supported resume numbers, or resume bullets removed",
}
REQUIRED_DOCS = ["docs/report/REPORT.md", "docs/report/REPRODUCE.md",
                 "README.md", "docs/plan/INDEX.md", "docs/plan/PROGRESS.md"]
SOURCE_PREFIXES = ("src/", "include/", "bench/", "cmake/", "configs/", "scripts/",
                   "py/", "tests/", "tools/", "docs/")
OWNED_PREFIXES = tuple(x for x in SOURCE_PREFIXES if x != "docs/") + (
    "docs/report/", "results/p5/", "results/p6/", "results/p7/", "results/p8/",
    "results/env/", "results/figures/", "results/derived/")
LOCAL_ONLY = ("data/raw/", "data/traces/", "results/raw/", "results/p1/fuzz-artifacts/",
              "results/p1/fuzz-crashes/", ".git/", ".tiplog-git/", ".agents/", ".codex/", ".aws/")
OUTPUT_NAMES = {"results/p8/checks.json", "results/p8/artifact-manifest.json", "results/p8/phase-gate.json"}
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_json(path: str | Path):
    return json.loads((ROOT / path).read_text())


def local_path(name: str) -> Path:
    path = (ROOT / name).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"artifact escapes the workspace: {name}")
    return path


def markdown_links(text: str):
    """Yield line/destination for inline/image/reference links outside code blocks."""
    fence = None
    definitions = {}
    references = []
    for line_number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1][0]
            elif marker[1][0] == fence:
                fence = None
            continue
        if fence:
            continue
        line = re.sub(r"(`+).*?\1", "", line)
        definition = re.match(r"^\s{0,3}\[([^\]]+)\]:\s*(<[^>]+>|\S+)", line)
        if definition:
            definitions[definition[1].casefold()] = (line_number, definition[2].strip("<>"))
            continue
        for match in re.finditer(r"!?\[[^\]]*\]\(\s*(<[^>]*>|[^\s)]+)", line):
            yield line_number, match[1].strip("<>")
        for match in re.finditer(r"!?\[([^\]]+)\]\[([^\]]*)\]", line):
            references.append((line_number, (match[2] or match[1]).casefold()))
    for line_number, label in references:
        if label in definitions:
            yield line_number, definitions[label][1]


class Audit:
    def __init__(self, args):
        self.args = args
        self.checks = []
        self.warnings = []
        self.hash_cache = {}
        self.gates = {}
        self.historical_chain = []
        self.package = {}
        self.links = []

    def check(self, name, passed, details=None):
        item = {"check": name, "status": "passed" if bool(passed) else "failed"}
        if details is not None:
            item["details"] = details
        self.checks.append(item)
        return bool(passed)

    def sha(self, name):
        path = local_path(name)
        if name not in self.hash_cache:
            self.hash_cache[name] = digest(path)
        return self.hash_cache[name]

    def identity(self, name, expected, label=None):
        expected = expected.get("sha256") if isinstance(expected, dict) else expected
        try:
            actual = self.sha(name)
            return self.check(label or f"identity:{name}",
                              isinstance(expected, str) and SHA_RE.fullmatch(expected) and actual == expected,
                              {"path": name, "expected_sha256": expected, "actual_sha256": actual})
        except (OSError, ValueError) as error:
            return self.check(label or f"identity:{name}", False, str(error))

    def execute(self, name, function):
        try:
            function()
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, ArithmeticError, json.JSONDecodeError) as error:
            self.check(name, False, f"{type(error).__name__}: {error}")

    def evidence(self, ref, label):
        if not self.check(f"{label}:explicit identity", isinstance(ref, dict) and
                          isinstance(ref.get("path"), str) and bool(SHA_RE.fullmatch(str(ref.get("sha256", ""))))):
            return None
        name = ref["path"]
        if name in OUTPUT_NAMES or name == self.args.evidence:
            self.check(f"{label}:no circular evidence", False, name)
            return None
        if not self.identity(name, ref, label):
            return None
        if name.endswith(".json"):
            value = read_json(name)
            if "exit_code" in value:
                self.check(f"{label}:executed exit", value["exit_code"] == 0)
            if "status" in value:
                self.check(f"{label}:saved status", value["status"] == "passed", value["status"])
            return value
        return None

    def phase_gates(self):
        paths = {"P0": "results/p0/artifact-checks.json"}
        paths.update({f"P{n}": f"results/p{n}/phase-gate.json" for n in range(1, 8)})
        for phase, name in paths.items():
            def one(phase=phase, name=name):
                gate = read_json(name)
                self.gates[phase] = gate
                self.check(f"{phase}:accepted phase gate", gate.get("status") == "passed", name)
                if phase != "P0":
                    self.check(f"{phase}:phase identity", gate.get("phase") == phase)
                    self.check(f"{phase}:plan and tier", gate.get("plan_version") == "v1.1" and gate.get("tier") == "B")
                    criteria = gate.get("criteria", {})
                    self.check(f"{phase}:mandatory criteria recorded", bool(criteria) and
                               all(value in ("met", "passed", True) for value in criteria.values()))
                # Earlier gates remain historical records. Their explicit identity maps
                # are checked; they do not imply current source equality by themselves.
                refs = gate.get("evidence", gate.get("checks", {}))
                if isinstance(refs, dict):
                    for key, value in refs.items():
                        if SHA_RE.fullmatch(str(value)) and "/" in key:
                            self.identity(key, value, f"{phase}:historical evidence:{key}")
                        elif isinstance(value, str) and "/" in value and not urlsplit(value).scheme:
                            self.check(f"{phase}:evidence exists:{key}", local_path(value).is_file(), value)
                self.historical_chain.append({"phase": phase, "path": name, "sha256": self.sha(name),
                                               "role": "prerequisite gate; current applicability checked separately"})
            self.execute(f"{phase}:gate readable", one)
        bootstrap = read_json("results/p0/20261017T042909.444760Z/summary.json")
        self.check("P0:accepted all-preset bootstrap", bootstrap.get("status") == "passed")

    def dependencies(self):
        base = read_json("results/p7/baseline.json")
        for entry in base["core_files"]:
            if entry["path"] != "CMakeLists.txt":
                self.identity(entry["path"], entry)
        self.check("baseline:19 accepted core binaries", len(base["existing_binaries"]) == 19)
        for entry in base["existing_binaries"]:
            self.identity(entry["path"], entry)
        self.identity(base["P6_gate"]["path"], base["P6_gate"])
        self.identity(base["master"]["path"], base["master"])
        managed = ROOT / ".git"
        self.check("managed Git mode preserved", oct(stat.S_IMODE(managed.stat().st_mode)) == base["managed_git_mode"])
        self.check("managed Git remains empty", managed.is_dir() and not list(managed.iterdir()))
        original = (ROOT / "results/p7/baseline-CMakeLists.txt").read_text()
        self.identity("results/p7/baseline-CMakeLists.txt", next(x for x in base["core_files"] if x["path"] == "CMakeLists.txt"))
        current = (ROOT / "CMakeLists.txt").read_text()
        extra = "include(cmake/p7_layout.cmake)\n"
        self.check("CMake:only one additive layout include", current.count(extra) == 1 and current.replace(extra, "", 1) == original)
        layout = (ROOT / "cmake/p7_layout.cmake").read_text()
        links = re.findall(r"target_link_libraries\s*\(([^)]+)\)", re.sub(r"#.*", "", layout), re.S)
        permitted = {"PUBLIC", "PRIVATE", "INTERFACE", "tiplog::build_options", "tiplog::layout", "GTest::gtest_main"}
        self.check("CMake:layout links isolated from engine", bool(links) and all(
            tokens[0].startswith("tiplog_layout") and set(tokens[1:]) <= permitted
            for tokens in (group.split() for group in links)), links)
        for preset, snapshot in [("release", "results/p7/baseline-compile_commands.json"),
                                 ("asan-ubsan", "results/p7/baseline-compile_commands.json-asan")]:
            before = read_json(snapshot)
            after = read_json(f"build/{preset}/compile_commands.json")
            key = lambda x: json.dumps(x, sort_keys=True)
            missing = Counter(map(key, before)) - Counter(map(key, after))
            files = {x["file"] for x in before}
            added = [x for x in after if x["file"] not in files]
            changed = [x["file"] for x in after if x["file"] in files and key(x) not in set(map(key, before))]
            allowed = ["src/tiplog/layout/", "tests/layout/", "tools/tiplog_layout/"]
            isolated = all(any(local_path(x["file"]).is_relative_to(ROOT / prefix) for prefix in allowed) for x in added)
            self.check(f"compile commands:{preset}:all original entries unchanged", not missing and not changed,
                       {"baseline_entries": len(before), "current_entries": len(after), "changed_existing": changed})
            self.check(f"compile commands:{preset}:additions only layout", isolated, [x["file"] for x in added])

        # AST comparison permits only the P7 dispatch appended to main. It does
        # not bless arbitrary figure changes on the strength of an old gate.
        baseline = ast.parse((ROOT / "results/p7/baseline-figure-build.py").read_text())
        current_ast = ast.parse((ROOT / "py/tiplog_py/figures/build.py").read_text())
        removed = []
        for node in current_ast.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main":
                kept = []
                for statement in node.body:
                    if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "layout_manifest" for t in statement.targets):
                        removed.append(statement)
                    elif isinstance(statement, ast.If) and any(isinstance(x, ast.Name) and x.id == "layout_manifest" for x in ast.walk(statement.test)):
                        removed.append(statement)
                    else:
                        kept.append(statement)
                node.body = kept
        added_text = "\n".join(ast.unparse(x) for x in removed)
        self.check("figures:original P1/P6 builder preserved with P7 dispatch", len(removed) == 2 and
                   "results/p7/analysis-inputs.json" in added_text and "build_layout" in added_text and
                   ast.dump(baseline, include_attributes=False) == ast.dump(current_ast, include_attributes=False))
        figure_base = read_json("results/p7/p6-figure-extension-baseline.json")
        for name, entry in figure_base.items():
            if name not in {"py/tiplog_py/figures/build.py", "results/figures/p6-figures.json"}:
                self.identity(name, entry, f"P6 figure numerical/source identity:{name}")
        first = len(self.checks)
        self.execute("P6 figure extension:mandatory compatibility proof", self.figure_extension)
        allowed = len(self.checks) > first and all(item["status"] == "passed" for item in self.checks[first:])
        self.check("P6 figure manifest:historical hash exception requires complete compatibility proof", allowed,
                   "Only PDF CreationDate bytes and their manifest artifact hashes may change; final current manifest must be bound by RC-1.")
        if not allowed:
            self.identity("results/figures/p6-figures.json", figure_base["results/figures/p6-figures.json"],
                          "P6 figure manifest:original identity required when compatibility proof fails")

    def figure_extension(self):
        baseline = read_json("results/p7/p6-figure-extension-baseline.json")
        old_path = "results/p7/baseline-p6-figures.json"
        self.identity(old_path, baseline["results/figures/p6-figures.json"], "P6 figure manifest:preserved historical baseline identity")
        old = read_json(old_path)
        current = read_json("results/figures/p6-figures.json")
        rendered = read_json("results/p7/figure-regeneration-baseline.json")["files"]
        compatibility_path = "results/p7/figure-extension-compatibility.json"
        proof = read_json(compatibility_path)
        checks = proof.get("checks", [])
        self.check("P6 figure extension:saved compatibility status and all checks passed",
                   proof.get("status") == "passed" and bool(checks) and not proof.get("failures") and
                   all(item.get("status") == "passed" for item in checks),
                   {"path": compatibility_path, "sha256": self.sha(compatibility_path), "check_count": len(checks)})
        expected_names = {"P6 manifest semantic fields unchanged", "P6 manifest artifact names unchanged"}
        for name, entry in baseline.items():
            if name not in {"py/tiplog_py/figures/build.py", "results/figures/p6-figures.json"}:
                expected_names.add("P6 numerical/source byte identity:" + name)
                self.identity(name, entry, "P6 compatibility numerical/source:" + name)
        pairs = set()
        for name, entry in rendered.items():
            match = re.fullmatch(r"results/figures/F([0-9]{2})_[^/]+\.(png|pdf)", name)
            if match:
                pairs.add((int(match[1]), match[2]))
            raw = local_path(name).read_bytes()
            normalized = re.sub(rb"/CreationDate\s*\(D:[^)]*\)", b"/CreationDate (NORMALIZED)", raw) if name.endswith(".pdf") else raw
            expected_names.add("P1/P6 rendered content identity:" + name)
            self.check("P6 compatibility rendered content:" + name,
                       hashlib.sha256(normalized).hexdigest() == entry["normalized_sha256"],
                       "PDF CreationDate normalization only" if name.endswith(".pdf") else "PNG bytes must agree exactly")
            if name.endswith(".png"):
                self.check("P6 compatibility PNG baseline has no normalization:" + name,
                           entry["sha256"] == entry["normalized_sha256"])
            if name in old.get("artifacts", {}):
                self.check("P6 compatibility snapshot agrees with historical manifest:" + name,
                           entry["sha256"] == old["artifacts"][name])
        self.check("P6 compatibility:all 26 F01-F13 PNG/PDF baselines present", len(rendered) == 26 and
                   pairs == {(number, suffix) for number in range(1, 14) for suffix in ("png", "pdf")})
        self.check("P6 compatibility:all non-artifact manifest fields unchanged",
                   {k: v for k, v in old.items() if k != "artifacts"} == {k: v for k, v in current.items() if k != "artifacts"})
        self.check("P6 compatibility:manifest artifact names unchanged", set(old["artifacts"]) == set(current["artifacts"]))
        for name, expected in current["artifacts"].items():
            expected_names.add("P6 regenerated manifest actual artifact:" + name)
            self.identity(name, expected, "P6 compatibility current manifest artifact:" + name)
        self.check("P6 compatibility:saved proof covers every mandatory comparison",
                   expected_names <= {item.get("check") for item in checks},
                   {"expected_checks": len(expected_names), "missing": sorted(expected_names - {item.get("check") for item in checks})})

    def long_evidence(self):
        p6 = self.gates["P6"]
        evidence = p6["evidence"]
        integrity = read_json(evidence["core_integrity"])
        self.check("historical:accepted P6 dependency audit", integrity.get("status") == "passed")
        freeze = read_json("results/p6/fuzz-source-freeze-prefix.json")
        for name, expected in freeze["files"].items():
            if name != "CMakeLists.txt":
                self.identity(name, expected, f"F3 final dependency:{name}")
        # The figure builder has evolved through accepted postprocessing. It
        # was never a converter/parser dependency and is excluded explicitly.
        p1_sources = read_json("results/p1/real-data-source-hashes.json")["files"]
        for name, expected in p1_sources.items():
            if not name.startswith("py/tiplog_py/figures/"):
                self.identity(name, expected, f"P1 data/converter dependency:{name}")
        f1f2 = read_json("results/p1/fuzz-gate-verified.json")
        self.check("CC-3:F1/F2 independent accepted verification", f1f2.get("status") == "passed" and len(f1f2.get("checks", [])) == 2)
        for item in f1f2.get("checks", []):
            self.identity(item["gate"], item["gate_sha256"])
            gate = read_json(item["gate"])
            self.check(f"CC-3:last accepted parser gate >=1800s:{item['gate']}",
                       gate.get("status") == "passed" and gate.get("monotonic_seconds", 0) >= 1800)
            self.identity(gate["binary"], gate["binary_sha256"])
            for attempt in gate.get("attempts", []):
                if attempt.get("exit_code") == 0 and "log_sha256" in attempt:
                    self.identity(attempt["log"], attempt["log_sha256"])
        f3 = read_json(evidence["F3"])
        self.check("CC-3:last accepted engine gate >=1800s", f3.get("status") == "passed" and
                   f3.get("confirmed_monotonic_seconds", 0) >= 1800 and not f3.get("artifact_files"))
        for field in ("gate", "freeze", "verifier", "binary"):
            self.identity(f3[field], f3[f"{field}_sha256"])
        for segment in f3.get("segments", []):
            self.identity(segment["log"], segment["log_sha256"])
        cc2 = read_json(evidence["CC2"])
        expected_configs = {(mode, kernel) for mode in ("indexed", "auto") for kernel in ("stdpq", "binheap", "quad", "loser")} | {("scan", "stdpq")}
        self.check("CC-2:accepted complete matrix", cc2.get("status") == "passed" and len(cc2.get("rows", [])) == 18)
        for preset, minimum in [("release", 1000), ("asan-ubsan", 200)]:
            rows = [r for r in cc2["rows"] if r["preset"] == preset]
            self.check(f"CC-2:{preset}:all mode/kernel configurations", {(r["mode"], r["kernel"]) for r in rows} == expected_configs)
            for row in rows:
                value = row["result"]
                self.check(f"CC-2:{preset}:{row['mode']}:{row['kernel']}", row.get("exit_code") == 0 and
                           value.get("status") == "passed" and value.get("seeds", 0) >= minimum and
                           value.get("operations_per_seed", 0) >= 10000 and local_path(row["record"]).is_file())
        audit = read_json(evidence["actual_CC4_audit"])
        self.check("CC-4:accepted full output/outcome audit", audit.get("status") == "passed", evidence["actual_CC4_audit"])
        measurement_inventory = read_json(evidence["measurement_files_unchanged"])
        self.check("P6:accepted 5364-file measurement identity inventory retained", measurement_inventory.get("status") == "passed" and
                   measurement_inventory.get("files_verified") == 5364 and not measurement_inventory.get("changed_files"),
                   "Reuses the accepted 4.1 GB identity audit; does not rehash the raw campaign.")
        rc3 = read_json(evidence["RC3"])
        self.check("RC-3:accepted GCC/Clang repeated verification", rc3.get("status") == "passed" and
                   rc3.get("child_count", 0) >= 180 and not rc3.get("failures"))
        self.identity(rc3["summary"], rc3["summary_sha256"])
        for name, expected in rc3.get("child_file_sha256", {}).items():
            self.identity(name, expected)
        summary = read_json(rc3["summary"])
        for name, expected in summary.get("source_sha256", {}).items():
            if name != "CMakeLists.txt":
                self.identity(name, expected, f"RC-3 final dependency:{name}")
        # broad_sources_at_start is a start-of-run snapshot. Its source_scope
        # excludes the bench tool, which P6 later changed before its campaigns;
        # bind that tool to the accepted P6 campaign provenance instead.
        broad_only = {k: v for k, v in summary.get("broad_sources_at_start", {}).items()
                      if k not in summary.get("source_sha256", {}) and k != "CMakeLists.txt"}
        self.check("RC-3:declared scope excludes the bench tool", "bench tool excluded" in summary.get("source_scope", ""))
        campaign_sources = {}
        for name in ("results/p6/micro-M1-latest.json", "results/p6/micro-M2-latest.json", "results/p6/micro-M3-latest.json"):
            for item in read_json(name)["provenance"]["source_files"]:
                campaign_sources.setdefault(item["path"], set()).add(item["sha256"])
        for name, expected in broad_only.items():
            accepted = campaign_sources.get(name, set()) | {expected}
            self.check(f"RC-3 snapshot file matches RC-3 start or accepted P6 campaign provenance:{name}",
                       self.sha(name) in accepted, {"rc3_start": expected, "p6_campaign": sorted(campaign_sources.get(name, set()))})
        cc6 = read_json("results/p1/cc6-reconciliation.json")
        self.check("CC-6:full type and locate reconciliation", cc6.get("status") == "passed" and
                   not cc6.get("mismatches") and cc6.get("compared_type_keys", 0) >= 18 and cc6.get("compared_locate_keys", 0) >= 8907)
        for name, expected in cc6["inputs"].items():
            self.identity(name, expected)
        data = read_json("results/p1/data-gate.json")
        self.check("RC-2:both accepted hierarchy byte-identity checks", data.get("status") == "passed" and
                   data.get("checks", {}).get("RC2_both_hierarchies") == "passed" and
                   set(data.get("traces", {})) == {"H-spec", "H-flat"} and
                   all(x.get("sha256") == x.get("repeat_sha256") for x in data["traces"].values()),
                   "Historical executed repeat-conversion evidence reused with unchanged converter dependencies; large traces not rehashed.")
        for hierarchy, trace in data.get("traces", {}).items():
            for field in ("path", "repeat_path"):
                path = local_path(trace[field])
                self.check(f"RC-2:local saved {hierarchy}:{field} present at accepted size",
                           path.is_file() and path.stat().st_size == trace["bytes"], trace[field])
        manifest = read_json("data/manifest.json")
        self.check("input:recorded checksum and incompleteness preserved", manifest.get("sha256") == data.get("source_sha256") and
                   manifest.get("size_bytes") == data.get("source_bytes") and data.get("source_binaryfile_incomplete") is True and
                   manifest.get("stream_characterization", {}).get("binaryfile_incomplete") is True)
        source = local_path(manifest["path"])
        self.check("input:local source present at accepted size", source.is_file() and
                   source.stat().st_size == manifest.get("size_bytes"),
                   "Presence/size check only; the accepted compressed-source checksum is retained without another full-data hash.")

    def optimizer(self):
        for preset in ("release", "asan-ubsan"):
            name = f"results/p7/cc5-{preset}.json"
            value = read_json(name)
            self.check(f"CC-5:{preset}:10000 random instances, all applicable k", value.get("status") == "passed" and
                       value.get("completed_instances", 0) >= 10000 and value.get("mismatches") == 0 and
                       value.get("maximum_nodes") == 12 and value.get("maximum_classes") == 4 and
                       value.get("exact_count_comparisons", 0) >= value.get("completed_instances", 0) and
                       value.get("at_most_comparisons") == value.get("exact_count_comparisons") and
                       value.get("failure_instance_index") is None)
        left, right = (read_json(f"results/p7/cc5-{x}.json") for x in ("release", "asan-ubsan"))
        self.check("CC-5:release/ASan deterministic identities", all(left.get(k) == right.get(k) for k in
                   ("seed", "input_fnv1a64", "result_fnv1a64", "exact_count_comparisons")))
        expected = {"base": 5517460497, "km-max": 39881491,
                    "km-min": 30029491, "enum": 30029491, "dp": 30029491}
        for name in ("results/p7/worked-example.json", "results/p7/worked-example-asan-ubsan.json"):
            worked = read_json(name)
            rows = {row["method"]: row["waste"] for row in worked.get("rows", [])}
            self.check(f"P7:exact worked-example waste:{name}", worked.get("status") == "passed" and
                       all(rows.get(method) == waste for method, waste in expected.items()))
        # P7's gate carries the executed V28-V32/V39, worked-example, threshold,
        # global-sweep and L2-L5 evidence; final review must explicitly cite it.
        self.check("P7:mandatory gate is prerequisite for final verification", self.gates.get("P7", {}).get("status") == "passed")

    def runtime_evidence(self):
        """Check completed saved rounds; never execute a child or rehash big TSVs."""
        name = "results/p7/runtime-campaign.json"
        summary = read_json(name)
        protocol = read_json("results/p7/runtime-supplement.json")
        self.check("P7 runtime:completed 11-round/900-case campaign", summary.get("status") == "passed" and
                   summary.get("configuration_count") == 900 and summary.get("warmup_rounds") == 1 and
                   summary.get("measured_rounds") == 10 and summary.get("accepted_rounds") == 11 and
                   summary.get("accepted_measured_rounds") == 10 and summary.get("warmup_rows") == 900 and
                   summary.get("measured_rows") == 9000)
        self.check("P7 runtime:original caps and declared controls preserved",
                   summary.get("solver_limits") == protocol.get("solver_limits") == read_json("results/p7/protocol.json")["solver_limits"] and
                   all(protocol.get(key) == value for key, value in {
                       "configuration_count": 900, "warmup_rounds": 1, "measured_rounds": 10,
                       "shuffle_seed": 20191230, "settle_seconds": 60, "cpu": 2, "observer_cpu": 6}.items()))
        identities = summary.get("identities", {})
        toolchain = summary.get("toolchain_identities", {})
        encode = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        expected_fingerprint = hashlib.sha256(encode({"project": identities, "toolchain": toolchain})).hexdigest()
        self.check("P7 runtime:frozen project/toolchain identity fingerprint", bool(identities) and bool(toolchain) and
                   expected_fingerprint == summary.get("identity_fingerprint"))
        skipped_large_inputs = []
        for path, expected in identities.items():
            if path.startswith("results/raw/P7/inputs/"):
                skipped_large_inputs.append(path)
                self.check("P7 runtime:accepted original input remains local:" + path, local_path(path).is_file())
            else:
                self.identity(path, expected, "P7 runtime:final dependency/reference:" + path)
        self.check("P7 runtime:large input identity audit reused explicitly", bool(skipped_large_inputs),
                   {"scope": "The completed runtime campaign verified these source hashes before/after timing; final closeout reuses that accepted audit and hashes compressed round inputs, not all large original TSVs again.",
                    "paths": skipped_large_inputs})
        for label, item in toolchain.items():
            path = Path(item["path"])
            self.check("P7 runtime:tool executable identity:" + label,
                       bool(SHA_RE.fullmatch(str(item.get("sha256", "")))) and digest(path) == item["sha256"], str(path))
        original = read_json(summary["original_campaign"])
        self.check("P7 runtime:original accepted cost campaign retained", original.get("status") == "passed")
        cost_fields = ("scale", "objective", "stores", "read_bytes", "useful_bytes", "waste_bytes",
                       "stores_touched", "cuts", "curve", "complete_domain")
        metadata_fields = ("budget", "nodes", "classes", "positive_nodes", "total_bytes", "alpha", "beta", "gamma")
        reference = {}
        for batch in original.get("files", []):
            if batch.get("kind") != "synthetic":
                continue
            self.identity(batch["output"], batch["output_sha256"], "P7 runtime:original synthetic cost output:" + batch["output"])
            with local_path(batch["output"]).open() as stream:
                for line in stream:
                    row = json.loads(line)
                    if row.get("method") == "dp":
                        if row["id"] in reference:
                            raise ValueError("duplicate original synthetic DP reference")
                        reference[row["id"]] = row
        self.check("P7 runtime:900 unique original DP case references", len(reference) == 900 and
                   all(identifier.startswith("synthetic/") for identifier in reference))
        rounds = summary.get("rounds", [])
        self.check("P7 runtime:one saved entry per round 0-10", len(rounds) == 11 and
                   {item.get("round") for item in rounds} == set(range(11)))
        valid_frequency = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0
        measured_samples = []
        measured_rows = {}
        accepted_records = set()
        process_launches = set()
        for compact in rounds:
            number = compact["round"]
            prefix = f"P7 runtime:round {number}"
            record_path = compact["status_record"]
            self.identity(record_path, compact["record_sha256"], prefix + ":status record identity")
            record = read_json(record_path)
            accepted_records.add(record_path)
            accepted_path = str(Path(record_path).parent / f"round-{number:02}.accepted.json")
            self.check(prefix + ":accepted/status records identical", read_json(accepted_path) == record)
            self.check(prefix + ":exit-zero output/control acceptance", compact.get("status") == record.get("status") == "passed" and
                       compact.get("controls_validated") is True and record.get("controls_validated") is True and
                       record.get("exit_code") == 0 and record.get("identity_fingerprint") == summary.get("identity_fingerprint") and
                       record.get("kind") == compact.get("kind") == ("warmup" if number == 0 else "measured"))
            self.check(prefix + ":complete actual settling", record.get("settle", {}).get("complete") is True and
                       record["settle"].get("required_seconds") == 60 and record["settle"].get("actual_seconds", 0) >= 60)
            self.check(prefix + ":fresh process launch recorded", isinstance(record.get("process_pid"), int) and record["process_pid"] > 0 and
                       record.get("launcher_pid") != record.get("process_pid") and record.get("measurement_started_monotonic") is not None)
            process_launches.add((record.get("process_pid"), record.get("measurement_started_monotonic")))
            argv = record.get("argv", [])
            command_ok = "--methods" in argv and argv[argv.index("--methods") + 1] == "dp" and "--full-curves" not in argv
            for key, value in protocol["solver_limits"].items():
                flag = "--" + key.replace("_", "-")
                command_ok = command_ok and flag in argv and argv[argv.index(flag) + 1] == str(value)
            self.check(prefix + ":DP-only command retains caps", command_ok)
            boundary_ok = not record.get("overlap_threats")
            for side in ("before", "after"):
                controls = record.get(f"controls_{side}", {})
                boundary_ok = boundary_ok and controls.get("ac", {}).get("online") is True and valid_frequency(controls.get("frequency_khz"))
            self.check(prefix + ":AC/frequency boundaries and no observed overlap", boundary_ok)
            artifacts = record.get("artifact_identities", {})
            mandatory_artifacts = {record[field] for field in ("output", "log", "resources", "process_audit", "input_gzip", "order")}
            self.check(prefix + ":all raw output/log/resource/order/gzip/audit identities recorded", mandatory_artifacts <= set(artifacts))
            for path, expected in artifacts.items():
                self.identity(path, expected, prefix + ":saved artifact:" + path)
            self.check(prefix + ":compact output/order/gzip identities agree", all(
                compact.get(field) == record.get(field) for field in
                ("output", "output_sha256", "order", "order_sha256", "input_gzip", "input_gzip_sha256", "input_plain_sha256")) and
                artifacts.get(record["output"]) == record.get("output_sha256") and
                artifacts.get(record["order"]) == record.get("order_sha256") and
                artifacts.get(record["input_gzip"]) == record.get("input_gzip_sha256"))
            order = read_json(record["order"])
            ids = order["ids"]
            self.check(prefix + ":900 original cases in saved global shuffle", len(ids) == len(set(ids)) == 900 and set(ids) == set(reference) and
                       order.get("round") == number and order.get("seed") == 20191230 and
                       order.get("plain_input_sha256") == record.get("input_plain_sha256"))
            statuses = Counter()
            digest_value = hashlib.sha256()
            child_controls = True
            metadata_ok = True
            solved_parity = True
            both_solved = 0
            rows = []
            with local_path(record["output"]).open() as stream:
                for index, line in enumerate(stream):
                    row = json.loads(line)
                    identifier = row.get("id")
                    metadata_ok = metadata_ok and index < len(ids) and identifier == ids[index] and identifier in reference
                    if identifier not in reference:
                        raise ValueError("unknown case ID in saved runtime output")
                    old = reference[identifier]
                    metadata_ok = metadata_ok and row.get("type") == "layout" and row.get("method") == "dp" and all(
                        row.get(key) == old.get(key) for key in metadata_fields)
                    solver_status = row.get("solver_status")
                    metadata_ok = metadata_ok and solver_status in {"solved", "infeasible", "timeout", "state_limit", "representation_limit"}
                    metadata_ok = metadata_ok and row.get("exact") is (solver_status == "solved" and row.get("status") == "feasible")
                    if solver_status != "solved":
                        metadata_ok = metadata_ok and all(row.get(key) is None for key in
                            ("objective", "stores", "read_bytes", "useful_bytes", "waste_bytes", "stores_touched", "cuts"))
                    child_controls = child_controls and row.get("cpu_before") == row.get("cpu_after") == 2
                    child_controls = child_controls and not isinstance(row.get("cpu_before"), bool) and not isinstance(row.get("cpu_after"), bool)
                    child_controls = child_controls and row.get("ac_before") is True and row.get("ac_after") is True and all(
                        valid_frequency(row.get(key)) for key in ("freq_before_khz", "freq_after_khz"))
                    for key in ("seconds", "verified_seconds"):
                        value = row.get(key)
                        metadata_ok = metadata_ok and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
                    statuses[(str(row.get("status")), str(row.get("solver_status")))] += 1
                    if row.get("solver_status") == old.get("solver_status") == "solved":
                        both_solved += 1
                        solved_parity = solved_parity and all(row.get(key) == old.get(key) for key in cost_fields)
                    digest_value.update(encode({"id": identifier, "solver_status": row.get("solver_status"),
                                                **{key: row.get(key) for key in cost_fields}}))
                    if number > 0:
                        measured_rows[(number, identifier)] = row
                        measured_samples.extend([row["freq_before_khz"], row["freq_after_khz"]])
                    rows.append(row)
            validation = record.get("validation", {})
            observed_statuses = [{"status": a, "solver_status": b, "count": count} for (a, b), count in sorted(statuses.items())]
            self.check(prefix + ":900 unique DP rows match original metadata/order", metadata_ok and len(rows) == 900 and
                       len({row["id"] for row in rows}) == 900 and set(row["id"] for row in rows) == set(reference))
            self.check(prefix + ":every child CPU/AC/frequency observation valid", child_controls)
            self.check(prefix + ":solved exact cost/curve/cuts/read/useful parity", solved_parity and
                       both_solved == validation.get("both_solved_cost_comparisons"))
            self.check(prefix + ":validation, statuses and read/useful/curve digest retained", not validation.get("errors") and
                       not validation.get("bad_child_controls") and validation.get("rows") == validation.get("unique_cases") == 900 and
                       observed_statuses == validation.get("status_counts") and compact.get("validation") == validation and
                       digest_value.hexdigest() == validation.get("cost_read_useful_curve_sha256"))
        self.check("P7 runtime:11 separately recorded fresh process launches", len(process_launches) == 11)
        attempts = summary.get("attempts", [])
        self.check("P7 runtime:all accepted rounds retain executed attempt records", accepted_records <= {
            item.get("record") for item in attempts if item.get("status") == "passed"} and len(attempts) >= 11)
        for item in attempts:
            self.identity(item["record"], item["record_sha256"], "P7 runtime:retained attempt:" + item["record"])
            self.check("P7 runtime:attempt status preserved:" + item["record"], read_json(item["record"]).get("status") == item.get("status"))
        noise = summary.get("frequency_noise", {})
        self.identity(noise["path"], noise["sha256"], "P7 runtime:retained frequency-flag artifact")
        flags = read_json(noise["path"])
        self.check("P7 runtime:9000 measured rows and 18000 frequency samples retained", len(measured_rows) == 9000 and len(measured_samples) == 18000 and
                   flags.get("sample_count") == noise.get("sample_count") == 18000 and len(flags.get("rows", [])) == 9000)
        median = statistics.median(measured_samples)
        expected_flags = {}
        for key, row in measured_rows.items():
            expected_flags[key] = any(abs(Fraction(row[field]) - Fraction(median)) * 10 > Fraction(median)
                                      for field in ("freq_before_khz", "freq_after_khz"))
        observed_flags = {}
        counts = Counter()
        values_match = True
        for item in flags.get("rows", []):
            key = (item["round"], item["id"])
            if key in observed_flags or key not in measured_rows:
                values_match = False
                continue
            row = measured_rows[key]
            values_match = values_match and all(item.get(field) == row.get(field) for field in ("freq_before_khz", "freq_after_khz"))
            observed_flags[key] = item.get("more_than_10_percent_from_session_median")
            counts[item["round"]] += int(item.get("more_than_10_percent_from_session_median") is True)
        self.check("P7 runtime:every >10% flag recomputed and retained without filtering", values_match and observed_flags == expected_flags and
                   flags.get("measured_session_median_khz") == noise.get("measured_session_median_khz") == median and
                   flags.get("flagged_case_rows") == noise.get("flagged_case_rows") == sum(counts.values()) and
                   {int(key): value for key, value in flags.get("per_round_flagged_case_rows", {}).items()} == dict(counts) and
                   flags.get("policy") == noise.get("policy") and "retained" in str(flags.get("policy", "")))

    def documentation(self):
        for name in REQUIRED_DOCS:
            self.check(f"final document exists:{name}", local_path(name).is_file())
        documents = sorted(set(REQUIRED_DOCS) | {str(p.relative_to(ROOT)) for p in (ROOT / "docs/report").glob("*.md")})
        exceptions = {}
        if self.args.historical_links:
            exceptions = read_json(self.args.historical_links).get("historical_missing_links", {})
        for name in documents:
            path = local_path(name)
            if not path.is_file():
                continue
            for line, target in markdown_links(path.read_text()):
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                resolved = (path.parent / unquote(parsed.path)).resolve()
                exists = resolved.exists()
                key = f"{name}::{target}"
                historical = not exists and key in exceptions and bool(exceptions[key])
                self.links.append({"document": name, "line": line, "target": target,
                                   "exists": exists, "historical_missing": historical,
                                   "reason": exceptions.get(key) if historical else None})
                if historical:
                    self.warnings.append(f"Historical missing link {key}: {exceptions[key]}")
                else:
                    self.check(f"Markdown link:{name}:{line}", exists, target)
        if exceptions:
            missing = {f"{x['document']}::{x['target']}" for x in self.links if not x["exists"]}
            self.check("historical link exceptions are explicit and current", set(exceptions) <= missing)
        # An allowlist records a historical defect, never repairs it or permits
        # a new report to cite missing evidence as a passed completion item.
        self.check("new reports contain no missing local links", not any(
            not x["exists"] and x["document"] in REQUIRED_DOCS[:2] for x in self.links))

    def git(self, *args):
        run = subprocess.run([str(ROOT / "scripts/git.sh"), *args], cwd=ROOT, capture_output=True, check=False)
        if run.returncode:
            raise ValueError(f"git wrapper {' '.join(args)}: {run.stderr.decode(errors='replace').strip()}")
        return run.stdout

    def packaging(self):
        tracked = set(filter(None, self.git("ls-files", "-z").decode().split("\0")))
        untracked = set(filter(None, self.git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")))
        self.package = {"tracked_count": len(tracked), "untracked_visible_count": len(untracked),
                        "included": [], "excluded": [], "unattributed_untracked": [], "source_and_documentation": {}}
        violations = []
        excluded_outputs = OUTPUT_NAMES | {self.args.output, self.args.manifest}
        for name in sorted(tracked | untracked):
            path = local_path(name)
            provenance = "tracked" if name in tracked else "new_core_owned"
            owned = name.startswith(OWNED_PREFIXES)
            if name not in tracked and name.startswith("tests/fuzz/corpus/"):
                self.package["excluded"].append({"path": name, "provenance": "unattributed_untracked",
                                                 "reason": "local generated fuzz corpus; not automatically packaged"})
                continue
            if name not in tracked and not owned:
                self.package["unattributed_untracked"].append(name)
                continue
            reason = None
            if name in excluded_outputs:
                reason = "checker output or future P8 gate; excluded to prevent self-reference"
            elif name.startswith(LOCAL_ONLY):
                reason = "local-only data or managed metadata"
            elif name.startswith("results/p1/F2") and name.endswith(".log"):
                reason = "payload-derived parser-fuzz log"
            elif name != "results/p1/fuzz-F2-real-seed.json" and re.search(
                    r"(?:real[-_/]|nasdaq[-_/]).*(?:seed|fuzz)|(?:seed|fuzz).*(?:real[-_/]|nasdaq[-_/])", name, re.I):
                reason = "real-data fuzz input"
            elif path.is_symlink() or not path.is_file():
                reason = "symlink or absent/nonregular file"
            elif path.stat().st_size > self.args.max_file_bytes:
                reason = f"large local artifact >{self.args.max_file_bytes} bytes"
            elif path.suffix.lower() in {".mdt", ".itch", ".gz", ".bin"} and not name.startswith("tests/fuzz/corpus/"):
                reason = "potential message-level binary outside accepted synthetic test corpus"
            if reason:
                self.package["excluded"].append({"path": name, "provenance": provenance, "reason": reason})
                if name in tracked and name not in excluded_outputs:
                    violations.append(name)
                continue
            self.package["included"].append({"path": name, "provenance": provenance, "bytes": path.stat().st_size})
            if (name.startswith(SOURCE_PREFIXES) and not name.startswith("tests/fuzz/corpus/")) or path.suffix == ".md" or name in {"CMakeLists.txt", "CMakePresets.json", "README.md", "MASTER_PROJECT_PROMPT.md", "pyproject.toml", ".gitignore"}:
                self.package["source_and_documentation"][name] = {"sha256": self.sha(name), "bytes": path.stat().st_size}
        self.check("packaging:no tracked local-only, real-message, or large artifacts", not violations, violations)
        protected = ["data/raw/12302019.NASDAQ_ITCH50.gz", "data/raw/fuzz_itch_walker/nasdaq-20191230-first65536.bin",
                     "data/traces/itch_20191230_0930_1000_spec.mdt", "results/raw/P6/local-only-example"]
        ignored = set(self.git("check-ignore", "--no-index", *protected).decode().splitlines())
        self.check("packaging:raw data, traces, results and real fuzz seeds ignored", set(protected) <= ignored)
        self.package["git_head"] = subprocess.run([str(ROOT / "scripts/git.sh"), "rev-parse", "--verify", "HEAD"],
                                                   cwd=ROOT, capture_output=True, text=True).stdout.strip() or "unborn"
        self.package["git_status"] = self.git("status", "--porcelain=v1", "--untracked-files=no").decode().splitlines()
        self.package["scope"] = "Inventory only. No add, stage, commit, deletion or user-work mutation. Large untracked aggregates are local reproduction inputs."

    def final_contract(self):
        contract = read_json(self.args.evidence)
        criteria = contract.get("criteria", {})
        for name in CRITERIA + list(CORE):
            item = criteria.get(name, {})
            self.check(f"final review:{name}", item.get("status") == "passed" and bool(item.get("note")) and
                       isinstance(item.get("evidence"), list) and bool(item["evidence"]), CORE.get(name))
            for index, ref in enumerate(item.get("evidence", [])):
                self.evidence(ref, f"final review:{name}:evidence:{index}")
        final = contract.get("final_identities", {})
        required = set(self.package.get("source_and_documentation", {}))
        self.check("final identities cover current packaged source and documentation", bool(required) and required <= set(final),
                   {"required": len(required), "missing": sorted(required - set(final))})
        for name, expected in final.items():
            if name in OUTPUT_NAMES or name == self.args.evidence:
                self.check("final identities exclude circular outputs", False, name)
            else:
                self.identity(name, expected, f"final executed/reviewed identity:{name}")
        # CC-1 must identify executed full release/ASan CTest commands, including
        # P7 tests. A smoke command cannot satisfy this part of the contract.
        presets = set()
        for ref in criteria.get("CC-1", {}).get("evidence", []):
            if isinstance(ref, dict) and str(ref.get("path", "")).endswith(".json") and local_path(ref["path"]).is_file():
                value = read_json(ref["path"])
                argv = value.get("argv", [])
                if argv and Path(argv[0]).name == "ctest" and "--preset" in argv and "-R" not in argv and "--tests-regex" not in argv:
                    i = argv.index("--preset") + 1
                    if i < len(argv) and value.get("exit_code") == 0 and value.get("status") == "passed":
                        log = local_path(value["log"])
                        text = log.read_text(errors="replace")
                        summary_ok = ("100% tests passed, 0 tests failed" in text or
                                      bool(re.search(r"100% tests passed out of [0-9]+", text)))
                        good = summary_ok and "layout." in text and not re.search(
                            r"ERROR: (?:AddressSanitizer|LeakSanitizer)|runtime error:|SUMMARY: (?:AddressSanitizer|UndefinedBehaviorSanitizer)", text)
                        self.check(f"CC-1:full CTest log:{argv[i]}", good, value["log"])
                        if good:
                            presets.add(argv[i])
        self.check("CC-1:full final release and ASan suites executed", {"release", "asan-ubsan"} <= presets)
        figure = contract.get("figure_regeneration", {})
        command = self.evidence(figure.get("command_record", {}), "RC-1:final one-command regeneration")
        argv = command.get("argv", []) if command else []
        self.check("RC-1:actual all-figure command", command is not None and "tiplog_py.figures.build" in argv and "--all" in argv)
        self.check("RC-1:input and output identities supplied", bool(figure.get("inputs")) and bool(figure.get("outputs")))
        for field in ("inputs", "outputs"):
            for name, expected in figure.get(field, {}).items():
                self.identity(name, expected, f"RC-1:{field}:{name}")
        outputs = set(figure.get("outputs", {}))
        self.check("RC-1:regenerated current P6 figure manifest explicitly bound", "results/figures/p6-figures.json" in outputs)
        rc1_refs = criteria.get("RC-1", {}).get("evidence", [])
        self.check("RC-1:P6 figure-extension compatibility proof explicitly bound", any(
            isinstance(ref, dict) and ref.get("path") == "results/p7/figure-extension-compatibility.json" for ref in rc1_refs))
        runtime_refs = criteria.get("CORE-7", {}).get("evidence", [])
        self.check("CORE-7:completed controlled runtime campaign explicitly bound", any(
            isinstance(ref, dict) and ref.get("path") == "results/p7/runtime-campaign.json" for ref in runtime_refs))
        for number in range(1, 19):
            for suffix in (".png", ".pdf"):
                self.check(f"RC-1:F{number:02}{suffix}:regenerated identity", any(
                    Path(name).name.startswith(f"F{number:02}_") and name.endswith(suffix) for name in outputs))

    def run(self):
        for name, method in [("phase gates", self.phase_gates), ("dependency applicability", self.dependencies),
                             ("accepted long evidence", self.long_evidence), ("P7 correctness", self.optimizer),
                             ("P7 controlled runtime evidence", self.runtime_evidence),
                             ("final documentation", self.documentation), ("local packaging", self.packaging),
                             ("final acceptance contract", self.final_contract)]:
            self.execute(name, method)
        failures = [x for x in self.checks if x["status"] != "passed"]
        manifest = {"schema": 1, "source_and_documentation": self.package.get("source_and_documentation", {}),
                    "packaging_inventory": self.package, "excluded_self_references": sorted(OUTPUT_NAMES | {self.args.output, self.args.manifest}),
                    "historical_gate_chain": self.historical_chain}
        manifest_path = local_path(self.args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        result = {"schema": 1, "phase": "P8-verification", "status": "passed" if not failures else "failed",
                  "at_utc": datetime.now(timezone.utc).isoformat(), "check_count": len(self.checks),
                  "failed_checks": failures, "warnings": self.warnings, "checks": self.checks,
                  "local_markdown_links": self.links, "historical_gate_chain": self.historical_chain,
                  "artifact_manifest": {"path": self.args.manifest, "sha256": digest(manifest_path)},
                  "checker_sha256": self.sha("scripts/check_core_closeout.py"),
                  "scope": "Saved evidence, dependency applicability, document links and packaging only; no build/test/fuzz/conversion/timing executed. No P8 acceptance claimed by this script alone."}
        output = local_path(self.args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"status": result["status"], "check_count": len(self.checks), "failed_count": len(failures),
                          "output": self.args.output, "manifest": self.args.manifest}, sort_keys=True))
        return 0 if not failures else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", default="results/p8/acceptance-evidence.json")
    parser.add_argument("--output", default="results/p8/checks.json")
    parser.add_argument("--manifest", default="results/p8/artifact-manifest.json")
    parser.add_argument("--historical-links", help="Optional JSON explicit historical_missing_links map; never permits missing final-report links")
    parser.add_argument("--max-file-bytes", type=int, default=10 * 1024 * 1024)
    args = parser.parse_args(argv)
    if args.max_file_bytes <= 0:
        parser.error("--max-file-bytes must be positive")
    return Audit(args).run()


if __name__ == "__main__":
    sys.exit(main())
