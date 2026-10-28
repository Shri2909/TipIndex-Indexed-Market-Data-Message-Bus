"""Generate P7's declared full-window M-store input strata, without solving them.

Sources: ARCHITECTURE §§2.3/6; VALIDATION L2/L3/L5; P7 protocol.json;
itch.characterize.write_tables for ranking and the recorded W3 basket seed.
Volumes are the existing P1 record_bytes tables, never physical store-pack I/O.
No external code, external dependency or unavailable Aria algorithm is reused.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random
import sys
from typing import TextIO


UINT64_MAX = (1 << 64) - 1
SYNTHETIC_SIZES = (5, 10, 20, 50, 100, 250, 500, 1000)
BETAS = (0, 65536, 1048576)
METHODS = ("base", "km-min", "km-max", "enum", "dp")


def rational(value: Fraction | int) -> str:
    value = Fraction(value)
    return f"{value.numerator}/{value.denominator}"


def source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_path(path: str) -> bool:
    return bool(path) and all(path.split("/")) and not any(c in path for c in "\t\r\n")


def matches(path: str, kind: str, term: str) -> bool:
    return path == term or (kind == "S" and path.startswith(term + "/"))


@dataclass(frozen=True)
class Tree:
    nodes: tuple[tuple[int | None, int, str], ...]
    positive_nodes: int
    total_bytes: int
    baseline_stores: int


def make_tree(partition: str, volumes: dict[str, int]) -> Tree:
    """Insert all immediate ancestors and omit zero-only branches."""
    if not valid_path(partition):
        raise ValueError(f"invalid partition path: {partition!r}")
    positive = {path: value for path, value in volumes.items() if value > 0}
    all_paths = {partition}
    for path, value in volumes.items():
        if not valid_path(path) or not 0 <= value <= UINT64_MAX:
            raise ValueError(f"invalid topic or byte count: {path!r}")
        if path != partition and not path.startswith(partition + "/"):
            raise ValueError(f"topic outside its partition: {path}")
        if value == 0:
            continue
        cursor = path
        while cursor != partition:
            all_paths.add(cursor)
            cursor = cursor.rsplit("/", 1)[0]
    ordered = sorted(all_paths, key=lambda path: (path.count("/"), path))
    if ordered[0] != partition:
        raise ValueError("partition root must precede its descendants")
    indices = {path: index for index, path in enumerate(ordered)}
    nodes = []
    groups = set()
    total = 0
    for path in ordered:
        parent = None if path == partition else indices[path.rsplit("/", 1)[0]]
        value = positive.get(path, 0)
        total += value
        if total > UINT64_MAX:
            raise OverflowError("partition record_bytes exceeds uint64")
        nodes.append((parent, value, path))
        if value:
            suffix = path[len(partition):].lstrip("/")
            groups.add(partition if not suffix else partition + "/" + suffix.split("/", 1)[0])
    return Tree(tuple(nodes), len(positive), total, len(groups))


def read_table(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def load_volumes(directory: Path, prefix: str):
    spec_path = directory / f"{prefix}_topic_volumes.csv"
    flat_path = directory / f"{prefix}_H-flat_topic_volumes.csv"
    partition_path = directory / f"{prefix}_partition_volumes.csv"
    spec = defaultdict(dict)
    flat = defaultdict(dict)
    mapping = {}
    expected_flat = defaultdict(lambda: [0, 0])
    expected_partitions = defaultdict(lambda: [0, 0])
    for row in read_table(spec_path):
        path, partition = row["topic"], row["partition"]
        if row["hierarchy"] != "H-spec" or path in spec[partition]:
            raise ValueError("invalid or duplicate H-spec source topic")
        count, volume = int(row["count"]), int(row["record_bytes"])
        if count < 0 or volume < 0:
            raise ValueError("negative source count or volume")
        spec[partition][path] = volume
        # This is exactly P1's saved type mapping, with its unmapped exception.
        flat_topic = path if partition.split("/")[1] == "_unmapped" else f"{partition}/{row['type']}"
        mapping[path] = flat_topic
        expected_flat[flat_topic][0] += count
        expected_flat[flat_topic][1] += volume
        expected_partitions[partition][0] += count
        expected_partitions[partition][1] += volume
    observed_flat = {}
    for row in read_table(flat_path):
        path, partition = row["topic"], row["partition"]
        if row["hierarchy"] != "H-flat" or path in observed_flat:
            raise ValueError("invalid or duplicate H-flat source topic")
        observed_flat[path] = [int(row["count"]), int(row["record_bytes"])]
        flat[partition][path] = int(row["record_bytes"])
    if observed_flat != dict(expected_flat):
        raise ValueError("H-flat table differs from actual H-spec type projection")
    partition_rows = read_table(partition_path)
    partitions = {row["partition"]: [int(row["count"]), int(row["record_bytes"])] for row in partition_rows}
    if len(partitions) != len(partition_rows) or partitions != dict(expected_partitions):
        raise ValueError("partition table differs from source topic totals")
    ranked = sorted((partition for partition in partitions if not partition.split("/")[1].startswith("_")),
                    key=lambda key: (-partitions[key][0], key))
    basket_top = set(ranked[:100])
    basket_random = set(random.Random(20191230).sample(sorted(ranked), min(100, len(ranked))))
    sources = [{"path": str(path), "sha256": source_hash(path)}
               for path in (spec_path, flat_path, partition_path)]
    return {"H-spec": dict(spec), "H-flat": dict(flat)}, mapping, ranked, basket_top, basket_random, sources


def raw_classes(partition: str, hierarchy: str, workload: str, local: dict[str, int],
                spec_local: dict[str, int], mapping: dict[str, str], ranks: dict[str, int],
                basket_top: set[str], basket_random: set[str]):
    """Project original semantic subscriptions to positive local topic sets."""
    result = []

    def add(name: str, weight: Fraction | int, terms: list[tuple[str, str]]):
        wanted = {path for path, volume in spec_local.items()
                  if volume > 0 and any(matches(path, kind, term) for kind, term in terms)}
        if hierarchy == "H-flat":
            wanted = {mapping[path] for path in wanted}
        result.append({"name": name, "weight": Fraction(weight), "topics": tuple(sorted(wanted))})

    if workload == "W0":
        for path, volume in sorted(local.items()):
            if volume > 0:
                result.append({"name": f"EXACT:{path}", "weight": Fraction(1), "topics": (path,)})
        return result
    if partition == "itch/_market":
        for symbol, rank in ranks.items():
            weight = Fraction(1, 10) if workload == "W3" else Fraction(1)
            if workload == "W2":
                weight = Fraction(10 if rank <= 100 else 1 if rank <= 1000 else 0)
            add(f"BOOK:{symbol}", weight, [("S", partition)])
        return result
    if partition not in ranks:
        return result
    rank = ranks[partition]
    weights = [Fraction(1, 10) if workload == "W3" else Fraction(1)] * 4
    if workload == "W2":
        frequency = Fraction(10 if rank <= 100 else 1 if rank <= 1000 else 0)
        weights = [frequency, frequency, Fraction(int(rank <= 1000)), Fraction(1)]
    add("BOOK", weights[0], [("S", f"{partition}/{family}") for family in ("add", "modify", "stock")])
    add("TAPE", weights[1], [("E", f"{partition}/modify/executed"),
                             ("E", f"{partition}/modify/executed_px"), ("S", f"{partition}/trade")])
    add("AUCT", weights[2], [("E", f"{partition}/noii"), ("E", f"{partition}/trade/cross")])
    add("STAT", weights[3], [("S", f"{partition}/stock")])
    if workload == "W3":
        if partition in basket_top:
            add("REPLAY_TOP100", 1, [("S", partition)])
        if partition in basket_random:
            add("REPLAY_RANDOM100", 1, [("S", partition)])
    return result


def compress_classes(raw: list[dict]) -> dict:
    effective = []
    locations = {}
    aliases = []
    active_weight = Fraction(0)
    active_count = 0
    for index, item in enumerate(raw):
        active = item["weight"] > 0 and bool(item["topics"])
        aliases.append({"name": item["name"], "weight": rational(item["weight"]),
                        "active": active, "incidence_count": len(item["topics"])})
        if not active:
            continue
        active_count += 1
        active_weight += item["weight"]
        incidence = item["topics"]
        if incidence not in locations:
            locations[incidence] = len(effective)
            effective.append({"name": f"e{len(effective)}", "weight": Fraction(0),
                              "positive_topics": list(incidence), "members": []})
        target = effective[locations[incidence]]
        target["weight"] += item["weight"]
        target["members"].append(index)
    for item in effective:
        item["weight"] = rational(item["weight"])
    return {"raw_classes": aliases, "effective_classes": effective,
            "raw_class_count": len(raw), "active_class_count": active_count,
            "effective_class_count": len(effective), "active_class_weight": rational(active_weight)}


def objective_signature(tree: Tree, classes: dict, beta: int) -> str:
    model = {"nodes": tree.nodes,
             "classes": [{"weight": item["weight"], "positive_topics": item["positive_topics"]}
                         for item in classes["effective_classes"]],
             "alpha": "1/1", "beta": rational(beta), "gamma": "0/1"}
    return hashlib.sha256(json.dumps(model, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def case_text(identifier: str, budget: int, tree: Tree, classes: dict, beta: int) -> str:
    lines = [f"CASE\t{identifier}\t{budget}\n", f"COST\t1\t{beta}\t0\n"]
    lines.extend(f"NODE\t{'-' if parent is None else parent}\t{volume}\t{path}\n"
                 for parent, volume, path in tree.nodes)
    for item in classes["effective_classes"]:
        lines.append(f"CLASS\t{item['name']}\t{item['weight']}\n")
        lines.extend(f"TERM\tE\t{path}\n" for path in item["positive_topics"])
    lines.append("END\n")
    return "".join(lines)


def synthetic_tree(n: int, shape: str, seed: int) -> Tree:
    rng = random.Random(seed)
    volumes = [max(1, int(1_000_000_000 / rank**1.2)) for rank in range(1, n + 1)]
    rng.shuffle(volumes)
    paths = ["synthetic/root"]
    values = {paths[0]: volumes[0]}
    for index in range(1, n):
        parent = index - 1 if shape == "chain" else 0 if shape == "star" else rng.randrange(index)
        # Repeated one-character chain segments limit artifact size; a star's
        # siblings need distinct names. All paths retain immediate ancestry.
        segment = "x" if shape == "chain" else f"n{index}"
        paths.append(f"{paths[parent]}/{segment}")
        values[paths[-1]] = volumes[index]
    return make_tree(paths[0], values)


def synthetic_classes(tree: Tree, count: int) -> dict:
    raw = [{"name": f"SYNTHETIC{index}", "weight": Fraction(index + 1, index + 2), "topics": []}
           for index in range(count)]
    for index, (_, volume, path) in enumerate(tree.nodes):
        if volume:
            raw[index % count]["topics"].append(path)
    for item in raw:
        item["topics"] = tuple(sorted(item["topics"]))
    result = compress_classes(raw)
    if result["effective_class_count"] != count:
        raise ValueError("synthetic effective class count differs from declared stratum")
    return result


class Batch:
    def __init__(self, path: Path, estimate_only: bool):
        self.path = path
        self.bytes = 0
        self.cases = 0
        self.digest = hashlib.sha256()
        self.stream: TextIO | None = None
        if not estimate_only:
            self.stream = path.open("w", encoding="utf-8", newline="")

    def write(self, value: str):
        encoded = value.encode()
        self.bytes += len(encoded)
        self.cases += 1
        self.digest.update(encoded)
        if self.stream is not None:
            self.stream.write(value)

    def close(self) -> dict:
        if self.stream is not None:
            self.stream.close()
        return {"path": str(self.path), "kind": "synthetic" if self.path.name.startswith("synthetic-") else "real",
                "cases": self.cases, "bytes": self.bytes,
                "sha256": self.digest.hexdigest()}


def generate(args) -> dict:
    output = Path(args.output_dir)
    if not args.estimate_only:
        output.mkdir(parents=True, exist_ok=True)
    metadata = {"schema": "tiplog-layout-inputs-v1", "methods": list(METHODS),
                "volume_basis": "record_bytes=align8(16+ITCH_payload), excluding ring PAD",
                "scope": "full observed source; modeled full-window requests; no physical disk I/O",
                "sources": [], "case_index": {}, "partition_workloads": {}, "trees": {}, "batches": [],
                "traceability": {"requirements": ["ARCHITECTURE 2.3", "ARCHITECTURE 6", "VALIDATION L2/L3/L5", "results/p7/protocol.json"],
                                 "reused_implementation_contract": "itch.characterize.write_tables ranking and basket seed",
                                 "external_code_reuse": False},
                "class_compression": "drop inactive/zero-weight; merge equal positive local topic incidence; sum exact weights",
                "term_projection": "compressed classes use Exact terms for their positive local incidence",
                "synthetic": {"zipf_exponent": 1.2, "zipf_scale": 1_000_000_000,
                              "volumes": "max(1,int(1e9/rank**1.2)), Random(seed).shuffle",
                              "weights": "class j uses (j+1)/(j+2); disjoint round-robin positive topic incidence"}}
    metadata["generator"] = {"path": "py/tiplog_py/layout/inputs.py", "sha256": source_hash(Path(__file__))}
    protocol_path = Path("results/p7/protocol.json")
    if protocol_path.exists():
        metadata["protocol"] = {"path": str(protocol_path), "sha256": source_hash(protocol_path)}
    case_index = metadata["case_index"]

    def register(identifier: str, entry: dict, tree: Tree, classes: dict, beta: int):
        if identifier in case_index:
            raise ValueError(f"duplicate study case ID {identifier}")
        case_index[identifier] = {**entry, "alpha": "1/1", "beta": beta, "gamma": "0/1",
                                  "positive_nodes": tree.positive_nodes, "total_bytes": tree.total_bytes,
                                  "nodes": len(tree.nodes), "objective_signature": objective_signature(tree, classes, beta)}

    if not args.skip_real:
        tables, mapping, ranked, top, basket, sources = load_volumes(Path(args.data_dir), args.prefix)
        metadata["sources"] = sources
        metadata["real_population"] = {"partitions": len(tables["H-spec"]), "symbols": len(ranked),
                                       "rank_rule": "message count descending then path", "ranked_symbols": ranked,
                                       "w3_random_basket_seed": 20191230, "top100": sorted(top), "random100": sorted(basket)}
        ranks = {partition: index + 1 for index, partition in enumerate(ranked)}
        for hierarchy, volumes in tables.items():
            partitions = sorted(volumes)
            if args.partition_limit:
                partitions = partitions[:args.partition_limit]
            trees = {partition: make_tree(partition, volumes[partition]) for partition in partitions}
            for partition, tree in trees.items():
                metadata["trees"][f"{hierarchy}/{partition}"] = {
                    "nodes": len(tree.nodes), "positive_nodes": tree.positive_nodes,
                    "total_bytes": tree.total_bytes, "baseline_stores": tree.baseline_stores}
            for workload in ("W0", "W1", "W2", "W3"):
                classes_by_partition = {}
                for partition in partitions:
                    raw = raw_classes(partition, hierarchy, workload, volumes[partition],
                                      tables["H-spec"][partition], mapping, ranks, top, basket)
                    classes = compress_classes(raw)
                    classes_key = f"real/{hierarchy}/{workload}/{partition}"
                    metadata["partition_workloads"][classes_key] = classes
                    classes_by_partition[partition] = (classes_key, classes)
                for beta in BETAS:
                    batch = Batch(output / f"real-{hierarchy}-{workload}-beta{beta}.tsv", args.estimate_only)
                    for partition in partitions:
                        tree = trees[partition]
                        classes_key, classes = classes_by_partition[partition]
                        identifier = f"real/{hierarchy}/{workload}/beta{beta}/{partition}"
                        budget = tree.baseline_stores
                        register(identifier, {"kind": "real", "source_kind": "real_itch", "hierarchy": hierarchy,
                                              "workload": workload, "partition": partition, "budget": budget,
                                              "budget_policy": "baseline", "classes_metadata_key": classes_key},
                                 tree, classes, beta)
                        batch.write(case_text(identifier, budget, tree, classes, beta))
                    metadata["batches"].append(batch.close())
    if not args.skip_synthetic:
        for n in SYNTHETIC_SIZES:
            if n > args.synthetic_max_n:
                continue
            batch = Batch(output / f"synthetic-n{n}.tsv", args.estimate_only)
            for shape in ("chain", "star", "random"):
                for count in (1, 4):
                    for seed in range(5):
                        tree = synthetic_tree(n, shape, seed)
                        classes = synthetic_classes(tree, count)
                        classes_key = f"synthetic/n{n}/{shape}/b{count}/seed{seed}"
                        metadata["partition_workloads"][classes_key] = classes
                        for budget in sorted({min(n, value) for value in (1, 4, 16, 64)}):
                            identifier = f"{classes_key}/K{budget}"
                            register(identifier, {"kind": "synthetic", "source_kind": "synthetic_zipf",
                                                  "hierarchy": "synthetic", "workload": f"b{count}",
                                                  "partition": "synthetic/root", "budget": budget,
                                                  "budget_policy": "sweep", "classes_metadata_key": classes_key,
                                                  "n": n, "shape": shape, "seed": seed, "requested_classes": count},
                                     tree, classes, args.synthetic_beta)
                            batch.write(case_text(identifier, budget, tree, classes, args.synthetic_beta))
            metadata["batches"].append(batch.close())
    metadata["case_count"] = len(case_index)
    metadata["tsv_bytes"] = sum(batch["bytes"] for batch in metadata["batches"])
    metadata["estimate_only"] = args.estimate_only
    if not args.estimate_only:
        destination = Path(args.metadata) if args.metadata else output / "metadata.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        metadata["metadata_path"] = str(destination)
        metadata["metadata_bytes"] = destination.stat().st_size
        manifest = {"schema": "tiplog-layout-generation-v1", "files": metadata["batches"],
                    "batches": metadata["batches"], "case_count": metadata["case_count"],
                    "tsv_bytes": metadata["tsv_bytes"], "metadata_path": str(destination),
                    "metadata_bytes": metadata["metadata_bytes"], "metadata_sha256": source_hash(destination),
                    "source_tables": metadata["sources"], "generator": metadata["generator"],
                    "protocol": metadata.get("protocol")}
        (output / "generation-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metadata


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--metadata")
    parser.add_argument("--data-dir", default="results/data")
    parser.add_argument("--prefix", default="itch_20191230_full_day")
    parser.add_argument("--skip-real", action="store_true")
    parser.add_argument("--skip-synthetic", action="store_true")
    parser.add_argument("--partition-limit", type=int, default=0, help="explicit partial functional-check population")
    parser.add_argument("--synthetic-max-n", type=int, default=1000)
    parser.add_argument("--synthetic-beta", type=int, default=65536)
    parser.add_argument("--estimate-only", action="store_true", help="count/hash the exact TSV stream without creating files")
    args = parser.parse_args(argv)
    if args.partition_limit < 0 or args.synthetic_max_n < 0 or args.synthetic_beta < 0:
        parser.error("limits and beta must be nonnegative")
    try:
        metadata = generate(args)
        print(json.dumps({key: metadata[key] for key in ("schema", "case_count", "tsv_bytes", "estimate_only", "batches")}
                         | {key: metadata[key] for key in ("metadata_path", "metadata_bytes") if key in metadata}, indent=2))
    except (ValueError, OverflowError, OSError) as error:
        print(f"layout input generation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
