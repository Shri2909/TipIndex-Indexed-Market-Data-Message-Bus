#!/usr/bin/env python3
"""Write the P8 final acceptance review (results/p8/acceptance-evidence.json).

Every criterion cites executed evidence by path and SHA-256. final_identities binds the
current packaged source/documentation inventory, computed read-only by the closeout
checker's own packaging() routine. Run only after the final documents are complete.
"""
from argparse import Namespace
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import check_core_closeout as closeout  # noqa: E402


def sha(path):
    with (ROOT / path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def refs(*paths):
    return [{"path": p, "sha256": sha(p)} for p in paths]


def with_log(record):
    return [record, json.loads((ROOT / record).read_text())["log"]]


def latest(prefix):
    return str(sorted((ROOT / "results/p7").glob(prefix + "-2*.json"))[-1].relative_to(ROOT))


FIG = latest("figures-all-final")
CHECK = latest("figure-extension-check-final")
criteria = {
    "CC-1": ("Final source tree: complete (unfiltered) release and ASan/UBSan CTest runs each passed 186/186 "
             "including the 20 layout tests (V28-V32, V39), with no sanitizer report; full pytest passed 151. "
             "The verification builds compiled nothing.",
             [*with_log(latest("final-release-tests")), *with_log(latest("final-asan-ubsan-tests")),
              *with_log(latest("final-python-p7")), latest("final-build-release"), latest("final-build-asan-ubsan")]),
    "CC-2": ("Accepted P6 matrix: all 9 mode/kernel configurations with 1,000 release seeds and 200 ASan/UBSan seeds "
             "x 10,000 operations against the independent ScanOracle, 0 failures. Engine dependencies and the 19 core "
             "binaries are unchanged since (P6 integrity audit; P7 gate checks).",
             ["results/p6/CC2-all-configurations.json", "results/p6/final-core-integrity.json",
              "results/p7/gate-checks.json"]),
    "CC-3": ("F1 trace reader 1,801.9 s and F2 ITCH walker (real-prefix seed) 1,801.8 s at P1; F3 structure-aware "
             "engine fuzzer 1,802.6 s at its final P6 gate with frozen dependencies; no crash artifact at any last gate.",
             ["results/p1/fuzz-gate-verified.json", "results/p1/F1-trace-segmented-gate-20261017T142028.416744Z.json",
              "results/p1/F2-framing-real-segmented-gate-20261017T142151.850263Z.json",
              "results/p6/fuzz-prefix-final-verified.json", "results/p6/fuzz-source-freeze-prefix.json"]),
    "CC-4": ("Every measured P6 configuration matches the independent oracle's output and outcome: saved-output audit "
             "10,295,181 checks, 0 failures; the 5,364-file measurement inventory is unchanged.",
             ["results/raw/P6/campaign-20261024/evaluation/independent-audit.json",
              "results/p6/auditor-t5-compatibility/measurement-files-final.json", "results/p6/phase-gate.json"]),
    "CC-5": ("MASK-DP = ENUM on 10,000 random instances in each build for every applicable k, 57,461 exact-count and "
             "57,461 at-most comparisons, 0 mismatches; release and sanitizer results hash-identical.",
             ["results/p7/cc5-release.json", "results/p7/cc5-asan-ubsan.json",
              *with_log(latest("cc5-release")), "results/p7/phase-gate.json"]),
    "CC-6": ("Python converter and independent C++ framing walker agree on all 18 message-type keys and 8,907 locate "
             "keys (268,744,780 messages), 0 mismatches; converter dependencies unchanged.",
             ["results/p1/cc6-reconciliation.json", "results/p1/data-gate.json"]),
    "RC-1": ("One command (python -m tiplog_py.figures.build --all) regenerated F01-F18 from saved results after all "
             "inputs were final; P1/P6 outputs verified unchanged except PDF CreationDate.",
             [*with_log(FIG), *with_log(CHECK), "results/p7/figure-extension-compatibility.json",
              "results/figures/p6-figures.json", "results/figures/p7-figures.json"]),
    "RC-2": ("Converter rerun produced byte-identical H-spec and H-flat traces (SHA-256 equal); converter "
             "dependencies unchanged, so the accepted evidence still applies.",
             ["results/p1/data-gate.json", "data/manifest.json"]),
    "RC-3": ("180 child runs over all 9 configurations, GCC and Clang release builds, 2 repeats per compiler; 170 "
             "output equalities, 0 failures; RC-3's declared dependency set unchanged.",
             ["results/p6/rc3-final-verified.json", "results/p6/rc3-summary.json"]),
    "CORE-1": ("All core phase gates P0-P7 passed with their DoDs; P8's DoD is this review. PROGRESS records "
               "executed evidence per phase.",
               ["results/p0/artifact-checks.json", *[f"results/p{n}/phase-gate.json" for n in range(1, 8)],
                "docs/plan/PROGRESS.md"]),
    "CORE-2": ("CC-1-CC-6 and RC-1-RC-3 each pass with the evidence above; summarized with links in REPORT section 5.",
               ["docs/report/REPORT.md", "docs/plan/VALIDATION_PLAN.md"]),
    "CORE-3": ("Every core fuzz target (F1, F2, F3) ran >=1,800 confirmed seconds at its last gate; no crash was "
               "found, so none needed minimization or regression.",
               ["results/p1/fuzz-gate-verified.json", "results/p6/fuzz-prefix-final-verified.json"]),
    "CORE-4": ("Source checksum, size, URL and incompleteness are recorded; traces hashed in the data gate. "
               "Raw data, traces, raw results and real fuzz seeds are ignored; the packaging inventory has no "
               "tracked local-only, message-level or large file.",
               ["data/manifest.json", "results/p1/data-gate.json", ".gitignore", "docs/report/REPRODUCE.md"]),
    "CORE-5": ("F01-F18 regenerate through figures.build --all (RC-1); claims tables in both result reports link "
               "raw files and summaries.",
               [*with_log(FIG), "results/figures/p1-figures.json", "results/figures/p6-figures.json",
                "results/figures/p7-figures.json", "docs/report/results_tip.md", "docs/report/results_layout.md"]),
    "CORE-6": ("All non-ok outcomes (4,320 invalid_config, 1 interrupted attempt; P7 state_limit caps) and frequency "
               "flags are retained; uncertainty is reported as bootstrap CIs; no p99/p99.9 or throughput-to-latency claim.",
               ["docs/report/results_tip.md", "docs/report/results_layout.md", "results/derived/layout-runtime.json",
                "docs/report/REPORT.md"]),
    "CORE-7": ("Optimizer claims follow ARCHITECTURE 6.9: exact only where solved under frozen caps, gaps only on "
               "identical problems, global certificates only with complete curves (W0 uncertified); worked example "
               "reproduced exactly; the controlled runtime campaign passed its predeclared quiescence rule.",
               ["results/p7/runtime-campaign.json", "results/p7/runtime-quiescence.json",
                "results/p7/phase-gate.json", "results/p7/gate-checks.json", "results/p7/worked-example.json",
                "results/derived/layout-global.json", "docs/report/results_layout.md"]),
    "CORE-8": ("REPORT section 9 lists limitations and threats to validity; resume bullets use only measured or "
               "modeled numbers with their scope (40.6x [39.5-41.7] for BOOK-top1; 27.9% modeled W1 bytes; 2.5% "
               "aggregate greedy gap; 0 CC-5 mismatches; 108 M differential operations).",
               ["docs/report/REPORT.md", "docs/report/results_tip.md", "docs/report/results_layout.md"]),
}

figure_inputs = ["results/data/itch_20191230_counts.json",
                 *[f"results/data/itch_20191230_full_day_{n}.csv" for n in
                   ("partition_volumes", "family_volumes", "topic_volumes", "run_lengths", "per_second",
                    "partition_complexity")],
                 "results/p6/analysis-inputs.json",
                 json.loads((ROOT / "results/p6/analysis-inputs.json").read_text())["rows_path"],
                 "results/derived/tip-summary.json", "results/p7/analysis-inputs.json",
                 "results/derived/layout-summary.json", "results/derived/layout-global.json",
                 "results/p7/worked-example.json", "results/derived/layout-runtime.json"]
figure_outputs = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "results/figures").iterdir()
                        if p.suffix in (".png", ".pdf", ".json"))

audit = closeout.Audit(Namespace(evidence="results/p8/acceptance-evidence.json", output="results/p8/checks.json",
                                 manifest="results/p8/artifact-manifest.json", historical_links=None,
                                 max_file_bytes=10 * 1024 * 1024))
audit.packaging()
contract = {
    "schema": 1,
    "reviewed_by": "Claude Code (P7 -> P8 continuation), 2026-10-25",
    "criteria": {name: {"status": "passed", "note": note, "evidence": refs(*paths)}
                 for name, (note, paths) in criteria.items()},
    "final_identities": audit.package["source_and_documentation"],
    "figure_regeneration": {"command_record": {"path": FIG, "sha256": sha(FIG)},
                            "inputs": {p: sha(p) for p in figure_inputs},
                            "outputs": {p: sha(p) for p in figure_outputs}},
}
(ROOT / "results/p8/acceptance-evidence.json").write_text(json.dumps(contract, indent=2) + "\n")
print(json.dumps({"criteria": len(contract["criteria"]), "final_identities": len(contract["final_identities"]),
                  "figure_inputs": len(figure_inputs), "figure_outputs": len(figure_outputs)}))
