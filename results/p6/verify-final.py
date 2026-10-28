"""Verify P6 closeout artifacts; never execute or modify a measurement."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
checks = []


def check(ok, name, detail=None):
    checks.append({"check": name, "status": "passed" if ok else "failed", "detail": detail})


def read(name):
    path = ROOT / name
    check(path.is_file(), "exists:" + name)
    return json.loads(path.read_text())


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


manifest = read("results/p6/closeout-evidence.json")
for name, path in manifest["checks"].items():
    result = read(path)
    check(result.get("status") == "passed", "terminal-check:" + name, path)
    if "exit_code" in result:
        check(result["exit_code"] == 0, "exit-zero:" + name)

campaign = read("results/raw/P6/campaign-20261024/campaign.json")
for stage in ("pilot-M1", "pilot", "pilot-independent-audit", "training",
              "training-independent-audit", "M1", "M2", "M3", "evaluation",
              "evaluation-independent-audit", "figures"):
    check(campaign["stages"][stage]["status"] == "passed", "campaign-stage:" + stage)

state = read("results/raw/P6/campaign-20261024/evaluation/state.json")
processes = state["completed_processes"]
check(len(processes) == 861, "41-saved-warmups-plus-820-measured-rounds")
check(sum(p["rep"] >= 0 for p in processes) == 820, "820-measured-process-rounds")
check(sum(p["rep"] == -1 for p in processes) == 41, "41-saved-warmup-processes")
check(all(not p.get("oracle_failures") and p.get("measurement_command_ok") is True
          and p["returncode"] == 0 for p in processes), "all-completed-rounds-validated")

audit = read("results/raw/P6/campaign-20261024/evaluation/independent-audit.json")
check(audit["status"] == "passed" and not audit["failures"], "independent-CC4-all-configurations")
check(audit["checks"] >= 10_295_181, "full-persisted-output-audit-coverage", audit["checks"])
check(audit["raw_request_outcomes_including_warmup"] == {"ok": 534240, "invalid_config": 4536},
      "all-raw-query-outcomes-preserved")

summary = read("results/derived/tip-summary.json")
check(summary["row_count"] == 135751, "complete-consolidated-row-count")
check(len(summary["configurations"]) == 6759, "all-configurations-plus-retained-failed-attempt")
check(summary["all_status_counts"] == {"ok": 125700, "invalid_config": 4320, "crash": 1},
      "complete-measured-status-accounting")
check(summary["bootstrap_resamples"] == 10000, "required-bootstrap-resample-count")
check(sha(ROOT / summary["input"]) == summary["input_sha256"], "summary-input-identity")
for group in summary["configurations"]:
    normal = group["n_measured"] == (15 if group["exp"].startswith("M") else 20)
    interrupted = group["status_counts"].get("crash") == 1 and group["n_measured"] == 1
    check(normal or interrupted, "configuration-repetition-count:" + group["config_id"])
    check(group["noise_observed_count"] + group["noise_unknown_count"] == group["n_measured"],
          "noise-accounting:" + group["config_id"])
    if interrupted:
        check(not group["metrics"], "interrupted-attempt-has-no-performance-statistics")

figures = read("results/figures/p6-figures.json")
check(figures["figures"] == [f"F{i:02}" for i in range(6, 14)], "F06-through-F13-generated")
check(len(figures["artifacts"]) == 16, "eight-PNG-and-eight-PDF-artifacts")
check(figures["input_sha256"] == summary["input_sha256"], "figures-use-actual-summary-input")
for name, digest in figures["artifacts"].items():
    check((ROOT / name).is_file() and sha(ROOT / name) == digest, "figure-identity:" + name)
for i in range(1, 6):
    check(bool(list((ROOT / "results/figures").glob(f"F{i:02}_*.png"))), f"P1-F{i:02}-regenerated")

before = read("results/p6/f12-layout-compatibility/before.json")
for item in before["numerical_artifacts_before"]:
    check(sha(ROOT / item["path"]) == item["sha256"],
          "plot-fix-preserves-numerical-artifact:" + item["path"])

t2 = read("results/derived/t2-adjusted-paired.json")
check(len(t2["cohorts"]) == 8 and len(t2["paired_comparisons"]) == 64,
      "T2-maintenance-adjusted-complete-cohorts-and-pairs")
check(all(v["status"] == "ok" and v["paired_rounds"] == 20
          and v["bootstrap_resamples"] == 10000 for v in t2["paired_comparisons"]),
      "T2-adjusted-ratios-preserve-whole-round-pairing")
t5 = read("results/derived/t5-high-water.json")
check(t5.get("status") == "passed", "T5-raw-peak-allocation-extraction")

report = ROOT / "docs/report/results_tip.md"
text = report.read_text()
check(all(f"C{i:02}" in text for i in range(1, 12)), "eleven-raw-linked-claims")
check("incomplete=true" in text and "not exclusive" in text, "input-and-host-limitations-disclosed")
for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
    target = target.strip().strip("<>")
    if target.startswith(("http://", "https://", "#")):
        continue
    target = unquote(target.split("#", 1)[0])
    check((report.parent / target).exists(), "report-local-link:" + target)

tracked = subprocess.run([str(ROOT / "scripts/git.sh"), "ls-files", "-z"],
                         cwd=ROOT, check=True, capture_output=True).stdout.decode().split("\0")
for prefix in ("data/raw/", "data/traces/", "results/raw/"):
    check(not any(p.startswith(prefix) for p in tracked), "message-data-excluded-from-git:" + prefix)
check(sha(ROOT / "MASTER_PROJECT_PROMPT.md") ==
      "89c0fe2ab7be8304d5cf9b9b8da07ee554efffc9c75596822fdd4f353f7d3067",
      "master-prompt-preserved")
check((ROOT / ".git").stat().st_mode & 0o777 == 0o555, "managed-git-preserved-read-only")
check(not (ROOT / "src/tiplog/layout").exists() and not (ROOT / "results/p7/phase-gate.json").exists(),
      "stop-at-P6-no-P7-start")

result = {"status": "passed" if all(v["status"] == "passed" for v in checks) else "failed",
          "scope": "P6 artifact/evidence closeout; not a replacement for the independent matrix/source/oracle audits",
          "checks": checks, "check_count": len(checks),
          "failed_checks": [v for v in checks if v["status"] != "passed"],
          "source_sha256": sha(Path(__file__))}
destination = ROOT / "results/p6/closeout-checks.json"
destination.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"status": result["status"], "checks": len(checks),
                  "failures": result["failed_checks"], "output": str(destination.relative_to(ROOT))}))
raise SystemExit(0 if result["status"] == "passed" else 1)
