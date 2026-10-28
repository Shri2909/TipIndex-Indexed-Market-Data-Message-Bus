#!/usr/bin/env python3
"""Rebuild the retained legacy-poll diagnostic without replacing its evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    here = Path(__file__).resolve().parent
    root = here.parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="new scratch directory; existing directories are refused")
    parser.add_argument("--libraries", type=Path, default=root / "build/release",
                        help="Release build containing non-Engine tiplog static libraries")
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--compile-only", action="store_true")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    manifest = json.loads((here / "manifest.json").read_text())
    # The retained Engine snapshots differ; every shared implementation/header
    # is verified identical to the original feature baseline before linking.
    for name, expected in manifest["shared_sources_identical_to_baseline"].items():
        if sha256(root / name) != expected:
            raise SystemExit(f"shared source changed: {name}")
    for path in [here / "legacy_diagnostic.cpp"] + [
            here / arm / "tiplog/engine" / name
            for arm in ("baseline", "final")
            for name in ("engine.cpp", "engine.hpp")]:
        name = str(path.relative_to(root))
        if sha256(path) != manifest["file_identities"][name]:
            raise SystemExit(f"retained source changed: {name}")
    libraries = [args.libraries.resolve() / f"libtiplog_{name}.a"
                 for name in ("ring", "topics_subs", "index", "merge")]
    if any(not path.is_file() for path in libraries):
        raise SystemExit("missing libraries; build tiplog_ring, tiplog_topics_subs, "
                         "tiplog_index and tiplog_merge in the selected Release directory")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    commands = []
    flags = manifest["compiler_flags"]
    for arm in ("baseline", "final"):
        command = [args.compiler, *flags, "-I", str(here / arm),
                   "-I", str(root / "src"), str(here / "legacy_diagnostic.cpp"),
                   str(here / arm / "tiplog/engine/engine.cpp"),
                   *(str(path) for path in libraries), "-o", str(output / arm)]
        commands.append(command)
        with (output / f"{arm}-build.log").open("x") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    rows = []
    if not args.compile_only:
        for repetition in range(args.repetitions):
            for scenario in manifest["measurement"]["scenarios"]:
                arms = ("baseline", "final") if repetition % 2 == 0 else ("final", "baseline")
                for arm in arms:
                    command = [str(output / arm), scenario]
                    value = json.loads(subprocess.check_output(command, text=True))
                    value.update(arm=arm, repetition=repetition, command=command)
                    rows.append(value)
    summary = {}
    for scenario in sorted({row["scenario"] for row in rows}):
        ratios = []
        for repetition in range(args.repetitions):
            arms = {row["arm"]: row for row in rows
                    if row["scenario"] == scenario and row["repetition"] == repetition}
            if arms["baseline"]["digest"] != arms["final"]["digest"]:
                raise SystemExit(f"output digest mismatch: {scenario}, repetition {repetition}")
            ratios.append(arms["final"]["cpu_seconds"] / arms["baseline"]["cpu_seconds"])
        summary[scenario] = {"median_ratio": statistics.median(ratios), "pair_ratios": ratios}
    result = {
        "scope": "Exploratory noisy-host CPU-time diagnostic; no guaranteed nonregression or speedup.",
        "commands": commands,
        "compiler": subprocess.check_output([args.compiler, "--version"], text=True).splitlines()[0],
        "file_identities": {str(path): sha256(path)
                            for path in [*libraries, output / "baseline", output / "final"]},
        "rows": rows, "summary": summary,
    }
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(output / "result.json"), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
