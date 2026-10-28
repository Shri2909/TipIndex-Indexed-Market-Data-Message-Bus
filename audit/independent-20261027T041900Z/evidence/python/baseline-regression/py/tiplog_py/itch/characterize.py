"""L1 streaming counters, volume tables and exact descriptive summaries."""

from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path


def _add(table, key, payload_length):
    row = table[key]
    row[0] += 1
    row[1] += payload_length
    row[2] += payload_length + 2
    row[3] += (16 + payload_length + 7) & ~7


def _counter():
    return [0, 0, 0, 0]


def counter_dict(values):
    return dict(zip(("count", "payload_bytes", "framed_bytes", "record_bytes"), values))


class Statistics:
    def __init__(self):
        self.by_type = defaultdict(_counter)
        self.by_locate = defaultdict(_counter)
        self.by_topic = defaultdict(_counter)
        self.topic_type = {}
        self._topic_partitions = {}
        self.per_second = defaultdict(_counter)
        self.run_lengths = Counter()
        self.previous_partition = None
        self.run_length = 0
        self.timestamp_inversions = 0
        self.previous_timestamp = None
        self.minimum_timestamp = None
        self.maximum_timestamp = None
        self.count = 0
        self.payload_bytes = 0

    def add(self, payload, topic, timestamp):
        length = len(payload)
        kind = chr(payload[0])
        locate = (payload[1] << 8) | payload[2]
        _add(self.by_type, kind, length)
        _add(self.by_locate, locate, length)
        _add(self.by_topic, topic, length)
        self.topic_type[topic] = kind
        _add(self.per_second, timestamp // 1_000_000_000, length)
        self.count += 1
        self.payload_bytes += length
        if self.previous_timestamp is not None and timestamp < self.previous_timestamp:
            self.timestamp_inversions += 1
        self.previous_timestamp = timestamp
        if self.minimum_timestamp is None or timestamp < self.minimum_timestamp:
            self.minimum_timestamp = timestamp
        if self.maximum_timestamp is None or timestamp > self.maximum_timestamp:
            self.maximum_timestamp = timestamp
        partition = self._topic_partitions.get(topic)
        if partition is None:
            partition = "/".join(topic.split("/", 2)[:2])
            self._topic_partitions[topic] = partition
        if partition == self.previous_partition:
            self.run_length += 1
        else:
            if self.run_length:
                self.run_lengths[self.run_length] += 1
            self.previous_partition = partition
            self.run_length = 1

    def runs(self):
        values = self.run_lengths.copy()
        if self.run_length:
            values[self.run_length] += 1
        return values

    def summary(self):
        return {
            "message_count": self.count,
            "payload_bytes": self.payload_bytes,
            "by_type": {key: counter_dict(value) for key, value in sorted(self.by_type.items())},
            "by_locate": {str(key): counter_dict(value) for key, value in sorted(self.by_locate.items())},
            "timestamp_inversions": self.timestamp_inversions,
            "minimum_timestamp_ns": self.minimum_timestamp,
            "maximum_timestamp_ns": self.maximum_timestamp,
            "topic_count": len(self.by_topic),
        }


def inequality(values):
    """Exact rank Gini formula; no assumed distribution or estimated skew."""
    ordered = sorted(values)
    total = sum(ordered)
    n = len(ordered)
    if not total or not n:
        return {"gini": 0.0, "top_1_percent_share": 0.0, "top_10_percent_share": 0.0}
    return {
        "gini": (2 * sum((i + 1) * value for i, value in enumerate(ordered)) / (n * total)) - (n + 1) / n,
        "top_1_percent_share": sum(ordered[-max(1, math.ceil(n * .01)):]) / total,
        "top_10_percent_share": sum(ordered[-max(1, math.ceil(n * .1)):]) / total,
    }


def _csv(path, fieldnames, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _active_classes(topics):
    """Nonempty BOOK/TAPE/AUCT/STAT match sets for this symbol's partition."""
    suffixes = [topic.split("/", 2)[2] for topic in topics]
    sets = (
        {suffix for suffix in suffixes if suffix.split("/")[0] in ("add", "modify", "stock")},
        {suffix for suffix in suffixes if suffix in ("modify/executed", "modify/executed_px") or suffix.startswith("trade/")},
        {suffix for suffix in suffixes if suffix in ("noii", "trade/cross")},
        {suffix for suffix in suffixes if suffix.startswith("stock/")},
    )
    return sets


TABLE_SUFFIXES = ("topic_volumes.csv", "H-flat_topic_volumes.csv", "partition_volumes.csv",
                  "family_volumes.csv", "run_lengths.csv", "per_second.csv",
                  "partition_complexity.csv", "summary.json")


def table_paths(directory, prefix):
    if Path(prefix).name != prefix or prefix in ("", ".", ".."):
        raise ValueError("table prefix must be a nonempty filename")
    return [Path(directory) / f"{prefix}_{suffix}" for suffix in TABLE_SUFFIXES]


def write_tables(stats: Statistics, directory: str | Path, prefix: str, *, destinations=None):
    """Save L1 inputs; record_bytes = align8(16+payload), excluding ring PAD.

    raw b counts active consumers; effective b combines identical nonempty match
    masks for complexity reporting only. It does not silently authorize a P7
    solver optimization. W3's random-100 basket uses a recorded deterministic seed.
    """
    import random

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    def target(suffix):
        path = directory / f"{prefix}_{suffix}"
        return destinations[path] if destinations is not None else path
    metric_columns = ["count", "payload_bytes", "framed_bytes", "record_bytes"]
    topics = []
    flat = defaultdict(_counter)
    partitions = defaultdict(_counter)
    families = defaultdict(_counter)
    partition_topics = defaultdict(list)
    for topic, values in sorted(stats.by_topic.items()):
        segments = topic.split("/")
        partition = "/".join(segments[:2])
        family = segments[2]
        topics.append({"hierarchy": "H-spec", "topic": topic, "partition": partition,
                       "type": stats.topic_type[topic], **counter_dict(values)})
        flat_path = f"{partition}/{stats.topic_type[topic]}" if segments[1] != "_unmapped" else topic
        for index, value in enumerate(values):
            flat[flat_path][index] += value
            partitions[partition][index] += value
            families[partition, family][index] += value
        partition_topics[partition].append(topic)
    _csv(target("topic_volumes.csv"), ["hierarchy", "topic", "partition", "type"] + metric_columns, topics)
    _csv(target("H-flat_topic_volumes.csv"), ["hierarchy", "topic", "partition"] + metric_columns,
         ({"hierarchy": "H-flat", "topic": topic, "partition": "/".join(topic.split("/")[:2]),
           **counter_dict(values)} for topic, values in sorted(flat.items())))
    _csv(target("partition_volumes.csv"), ["partition"] + metric_columns,
         ({"partition": partition, **counter_dict(values)} for partition, values in sorted(partitions.items())))
    _csv(target("family_volumes.csv"), ["partition", "family"] + metric_columns,
         ({"partition": partition, "family": family, **counter_dict(values)}
          for (partition, family), values in sorted(families.items())))
    _csv(target("run_lengths.csv"), ["run_length", "runs", "messages"],
         ({"run_length": length, "runs": runs, "messages": length * runs}
          for length, runs in sorted(stats.runs().items())))
    _csv(target("per_second.csv"), ["second_since_midnight"] + metric_columns,
         ({"second_since_midnight": second, **counter_dict(values)} for second, values in sorted(stats.per_second.items())))

    ranked = sorted((partition for partition in partitions if not partition.split("/")[1].startswith("_")),
                    key=lambda key: (-partitions[key][0], key))
    ranks = {partition: rank + 1 for rank, partition in enumerate(ranked)}
    basket_top = set(ranked[:100])
    basket_random = set(random.Random(20191230).sample(sorted(ranked), min(100, len(ranked))))
    complexity = []
    for partition, partition_paths in sorted(partition_topics.items()):
        nodes = {partition}
        for topic in partition_paths:
            segments = topic.split("/")
            nodes.update("/".join(segments[:depth]) for depth in range(3, len(segments) + 1))
        if partition == "itch/_market":
            # Every symbol's BOOK class includes the market subtree.
            b1 = len(ranked)
            b2 = min(1000, len(ranked))
            effective1 = effective2 = int(bool(ranked))
            b3 = b1
            effective3 = effective1
        elif partition in ranks:
            masks = _active_classes(partition_paths)
            active = [mask for mask in masks if mask]
            b1 = len(active)
            effective1 = len({frozenset(mask) for mask in active})
            masks2 = [mask for index, mask in enumerate(masks) if mask and (index == 3 or ranks[partition] <= 1000)]
            b2 = len(masks2)
            effective2 = len({frozenset(mask) for mask in masks2})
            replay_count = int(partition in basket_top) + int(partition in basket_random)
            b3 = b1 + replay_count
            effective3 = len({frozenset(mask) for mask in active} | ({frozenset(topic.split("/", 2)[2] for topic in partition_paths)} if replay_count else set()))
        else:
            b1 = b2 = b3 = effective1 = effective2 = effective3 = 0
        complexity.append({"partition": partition, "nodes": len(nodes), "edges": len(nodes) - 1,
                           "positive_topics": len(partition_paths), "b_W0_raw": len(partition_paths),
                           "b_W1_raw": b1, "b_W1_effective": effective1, "b_W2_raw": b2,
                           "b_W2_effective": effective2, "b_W3_raw": b3, "b_W3_effective": effective3})
    complexity_fields = ["partition", "nodes", "edges", "positive_topics", "b_W0_raw", "b_W1_raw",
                         "b_W1_effective", "b_W2_raw", "b_W2_effective", "b_W3_raw", "b_W3_effective"]
    _csv(target("partition_complexity.csv"), complexity_fields, complexity)
    symbols = [partitions[partition] for partition in ranked]
    summary = {
        "prefix": prefix, "symbol_partitions": len(symbols), "partitions": len(partitions),
        "volume_definition": "payload_bytes original ITCH; framed_bytes payload+2 BinaryFILE; record_bytes align8(16+payload), no ring PAD",
        "messages": inequality([row[0] for row in symbols]),
        "payload_bytes": inequality([row[1] for row in symbols]),
        "record_bytes": inequality([row[3] for row in symbols]),
        "w3_random_basket_seed": 20191230,
        "class_count_definition": "raw active consumers and effective distinct nonempty local match sets; no solver coverage claim",
        "complexity_histograms": {field: dict(sorted(Counter(row[field] for row in complexity).items()))
                                  for field in complexity_fields[1:]},
    }
    (target("summary.json")).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary
