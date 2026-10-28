"""Second-pass audit probes. Writes only into this audit directory."""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(os.environ.get("TIPLOG_AUDIT_EVIDENCE", Path(__file__).resolve().parent))
HERE.mkdir(parents=True, exist_ok=True)
BIN = Path(os.environ.get("TIPLOG_AUDIT_BIN", ROOT / "build/release"))


def run(name, args, timeout=30):
    start = time.perf_counter()
    proc = subprocess.run([str(x) for x in args], cwd=ROOT, capture_output=True,
                          text=True, timeout=timeout)
    item = {"name": name, "argv": [str(x) for x in args],
            "returncode": proc.returncode, "wall_seconds": time.perf_counter()-start,
            "stdout": proc.stdout, "stderr": proc.stderr}
    (HERE / f"{name}.json").write_text(json.dumps(item, indent=2))
    return item


common = [BIN / "tiplog_bench", "--synthetic", "--records", "100", "--partitions", "2",
          "--ring-bytes", "2048"]
run("bench_output_full", common + ["--output", "/dev/full", "--memory"])
request = HERE / "valid_request.tsv"
request.write_text("probe\tT1\t36\tsubtree:synth/p0\tscan\tstdpq\trepeat-warm\t16\t1\n")
run("bench_output_full_with_request", common + ["--output", "/dev/full", "--requests", request])
run("example_output_full", [BIN / "tiplog_layout_example", "--output", "/dev/full"])
run("cc5_output_full", [BIN / "tiplog_layout_cc5", "--instances", "1", "--output", "/dev/full"])
run("recording_nan_json", [BIN / "tiplog_sim", "--trace", ROOT / "tests/fuzz/corpus/trace_reader/empty.mdt",
                           "--backend", "recording", "--auto-max-index-fraction", "nan"])
mix = HERE / "overflow_mix.csv"
mix.write_text("type,payload_bytes,count\nA,12,9223372036854775809\nB,64,9223372036854775809\n")
out = HERE / "overflow_mix_output.jsonl"
out.unlink(missing_ok=True)
run("bench_overflow_mix", common + ["--output", out, "--mix", mix])
mix_normal = HERE / "equal_mix.csv"
mix_normal.write_text("type,payload_bytes,count\nA,12,1\nB,64,1\n")
out_normal = HERE / "equal_mix_output.jsonl"
out_normal.unlink(missing_ok=True)
run("bench_equal_mix", common + ["--output", out_normal, "--mix", mix_normal])

for count in (() if os.environ.get("TIPLOG_AUDIT_SKIP_PREPARE") else (1000, 4000, 12000)):
    case = HERE / f"prepare_{count}.tsv"
    with case.open("w") as f:
        f.write("CASE\tprepare_probe\t1\nCOST\t1\t0\t0\nNODE\t-\t0\tr\n")
        for i in range(count):
            f.write(f"NODE\t0\t1\tr/n{i}\n")
        for i in range(count):
            f.write(f"CLASS\tc{i}\t1\nTERM\tE\tr/missing{i}\n")
        f.write("END\n")
    run(f"prepare_{count}", [BIN/"tiplog_layout", "--input", case, "--methods", "dp",
                             "--time-limit-ms", "1", "--max-work", "1"])

print("Probe results saved under", HERE)
