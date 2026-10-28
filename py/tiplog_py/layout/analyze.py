"""Audit and summarize actual P7 layout JSONL without inventing exact coverage.

Rows must be contiguous by case ID. Arithmetic used for claims is Fraction;
floating values are diagnostic plotting conveniences and solver timings only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from tiplog_py._outputs import OutputTransaction


METHODS = ("base", "km-min", "km-max", "enum", "dp")
EXACT_METHODS = ("enum", "dp")
DIMENSIONS = ("kind", "source_kind", "hierarchy", "workload", "alpha", "beta",
              "gamma", "budget_policy")
CSV_FIELDS = (*DIMENSIONS, "partition", "id", "method", "budget", "status",
              "solver_status", "exact", "objective", "stores", "nodes", "classes",
              "total_bytes", "active_class_weight", "weighted_read_bytes",
              "weighted_useful_bytes", "weighted_waste_bytes", "weighted_stores_touched",
              "max_waste_bytes", "worst_amplification", "worst_amplification_floor4096",
              "baseline_improvement", "exact_gap", "absolute_exact_gap", "gap_status",
              "baseline_comparison_status", "seconds", "states", "work")


def rational(value, label="rational") -> Fraction:
    """Accept explicitly encoded exact numbers; reject binary floating inputs."""
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{label}: an explicit integer/rational is required")
    if isinstance(value, dict):
        numerator = integer(value.get("numerator"), label + " numerator")
        denominator = integer(value.get("denominator"), label + " denominator")
        if denominator == 0:
            raise ValueError(f"{label}: zero denominator")
        return Fraction(numerator, denominator)
    try:
        result = Fraction(value)
    except (TypeError, ValueError, ZeroDivisionError) as error:
        raise ValueError(f"{label}: invalid exact rational {value!r}") from error
    if result < 0:
        raise ValueError(f"{label}: negative value")
    return result


def integer(value, label="integer") -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{label}: nonnegative integer required")
    if isinstance(value, str) and (not value or not value.isdecimal()):
        raise ValueError(f"{label}: invalid decimal integer")
    result = int(value)
    if result < 0:
        raise ValueError(f"{label}: negative integer")
    return result


def exact_text(value):
    return "" if value is None else str(value)


def json_exact(value):
    if isinstance(value, Fraction):
        return {"exact": str(value), "value": float(value)}
    if isinstance(value, dict):
        return {str(key): json_exact(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_exact(item) for item in value]
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def distribution(counter: Counter) -> dict:
    count = sum(counter.values())
    if not count:
        return {"count": 0, "minimum": None, "p25": None, "median": None,
                "p75": None, "p95": None, "maximum": None}
    ordered = sorted(counter)

    def quantile(numerator, denominator):
        target = max(1, (count * numerator + denominator - 1) // denominator)
        cumulative = 0
        for value in ordered:
            cumulative += counter[value]
            if cumulative >= target:
                return value
        raise AssertionError("unreachable quantile")

    return {"count": count, "minimum": ordered[0], "p25": quantile(1, 4),
            "median": quantile(1, 2), "p75": quantile(3, 4),
            "p95": quantile(95, 100), "maximum": ordered[-1],
            "quantile_rule": "nearest rank; median uses the lower middle for even counts"}


def dimensions(meta: dict) -> tuple:
    values = []
    for name in DIMENSIONS:
        default = "1" if name == "alpha" else "0" if name in {"beta", "gamma"} else "unspecified"
        value = meta.get(name, default)
        values.append(str(rational(value, name)) if name in {"alpha", "beta", "gamma"} else str(value))
    return tuple(values)


def labeled(key: tuple, names=DIMENSIONS) -> dict:
    return dict(zip(names, key, strict=True))


def new_tally() -> dict:
    return {"rows": 0, "feasible": 0, "exact_solved": 0, "stores": 0,
            "total_bytes": 0, "objective": Fraction(0),
            "weighted_read_bytes": Fraction(0), "weighted_useful_bytes": Fraction(0),
            "weighted_waste_bytes": Fraction(0), "weighted_stores_touched": Fraction(0),
            "max_waste_bytes": None, "worst_amplification": None,
            "worst_amplification_floor4096": None,
            "status_counts": Counter(), "solver_status_counts": Counter()}


def update_maximum(target, name, value):
    if value is not None and (target[name] is None or value > target[name]):
        target[name] = value


class Analyzer:
    def __init__(self, metadata: dict, *, methods=METHODS, kinds=()):
        self.metadata = metadata
        self.cases = metadata.get("case_index", {})
        if not isinstance(self.cases, dict) or not self.cases:
            raise ValueError("metadata requires a nonempty case_index map")
        self.methods = tuple(methods)
        self.kinds = set(kinds)
        self.failures = []
        self.failure_counts = Counter()
        self.quality = defaultdict(new_tally)
        self.consumer_quality = defaultdict(new_tally)
        self.exact_cohort_quality = defaultdict(new_tally)
        self.exact_cohort_consumer_quality = defaultdict(new_tally)
        self.coverage = {}
        self.comparisons = {}
        self.scaling = {}
        self.observed_cases = set()
        self.row_count = 0
        self.flat_baseline_checks = 0
        self.class_cache = {}
        self.expected_by_group = Counter()
        for case_id, meta in self.cases.items():
            if self.selected(meta):
                self._add_denominator(case_id, meta)

    def selected(self, meta):
        return not self.kinds or meta.get("kind") in self.kinds

    def fail(self, code, *, case_id=None, method=None, detail=""):
        self.failure_counts[code] += 1
        if len(self.failures) < 200:
            self.failures.append({"code": code, "id": case_id, "method": method, "detail": detail})

    def classes(self, meta):
        key = meta.get("classes_metadata_key")
        if key not in self.class_cache:
            document = self.metadata.get("partition_workloads", {}).get(key)
            if document is None:
                raise ValueError(f"missing partition_workloads entry {key!r}")
            effective = document.get("effective_classes", [])
            weights = [rational(item["weight"], "class weight") for item in effective]
            active_weight = rational(document.get("active_class_weight", sum(weights)), "active class weight")
            if sum(weights) != active_weight:
                raise ValueError(f"{key}: effective weights differ from active class weight")
            self.class_cache[key] = (document, weights, active_weight)
        return self.class_cache[key]

    def _add_denominator(self, case_id, meta):
        _, _, weight = self.classes(meta)
        group = dimensions(meta)
        self.expected_by_group[group] += 1
        total_bytes = integer(meta.get("total_bytes"), "case total_bytes")
        for method in self.methods:
            if method not in EXACT_METHODS:
                continue
            key = group + (method,)
            if key not in self.coverage:
                self.coverage[key] = {"expected_cases": 0, "observed_cases": 0,
                    "solved_cases": 0, "complete_curve_cases": 0,
                    "total_bytes": 0, "solved_bytes": 0,
                    "active_class_weight": Fraction(0), "solved_active_class_weight": Fraction(0),
                    "status_counts": Counter(), "solver_status_counts": Counter()}
            record = self.coverage[key]
            record["expected_cases"] += 1
            record["total_bytes"] += total_bytes
            record["active_class_weight"] += weight

    def normalize(self, raw, case_id, meta):
        row = dict(raw)
        method = row.get("method")
        if method not in self.methods:
            raise ValueError(f"unexpected method {method!r}")
        for field in ("budget", "nodes", "classes", "total_bytes", "stores", "states", "work"):
            if row.get(field) is not None:
                row[field] = integer(row[field], field)
        for field in ("nodes", "classes", "total_bytes", "budget"):
            if row.get(field) is None:
                raise ValueError(f"missing {field}")
        if row.get("budget") != integer(meta.get("budget"), "metadata budget"):
            raise ValueError("row budget differs from case metadata")
        if row.get("total_bytes") != integer(meta["total_bytes"], "metadata total_bytes"):
            raise ValueError("row volume differs from case metadata")
        if row.get("objective_signature") not in (None, meta.get("objective_signature")):
            raise ValueError("row objective signature differs from case metadata")
        if meta.get("nodes") is not None and row["nodes"] != integer(meta["nodes"], "metadata nodes"):
            raise ValueError("row node count differs from case metadata")
        for coefficient in ("alpha", "beta", "gamma"):
            if row.get(coefficient) is not None and rational(row[coefficient], coefficient) != rational(meta.get(coefficient, 1 if coefficient == "alpha" else 0)):
                raise ValueError(f"row {coefficient} differs from case metadata")
        if not isinstance(row.get("exact"), bool):
            raise ValueError("row exact must be boolean")
        scale = integer(row.get("scale"), "objective scale")
        if scale == 0:
            raise ValueError("zero objective scale")
        row["objective_fraction"] = None if row.get("objective") is None else Fraction(integer(row["objective"], "objective"), scale)
        row["feasible"] = row.get("status") in {"ok", "feasible"} and row["objective_fraction"] is not None
        row["certified"] = (method in EXACT_METHODS and row["exact"] and
                            row.get("solver_status") == "solved" and row["feasible"])
        if row["exact"] and not row["certified"]:
            raise ValueError("exact flag lacks a solved feasible exact-method result")
        if row.get("seconds") is not None:
            if isinstance(row["seconds"], bool) or not isinstance(row["seconds"], (int, float)) or not math.isfinite(row["seconds"]) or row["seconds"] < 0:
                raise ValueError("invalid solver seconds")
        document, weights, active_weight = self.classes(meta)
        row["active_class_weight_fraction"] = active_weight
        if row.get("active_class_weight") is not None:
            weight_scale = integer(row.get("class_weight_scale"), "class weight scale")
            if weight_scale == 0 or Fraction(integer(row["active_class_weight"], "active class weight"), weight_scale) != active_weight:
                raise ValueError("CLI active class weight differs from metadata")
        if row.get("classes") != len(weights):
            raise ValueError("row class count differs from effective metadata classes")
        if not row["feasible"]:
            return row
        if row.get("stores") is None or row["stores"] > row["budget"]:
            raise ValueError("layout exceeds its requested materialized-store budget")
        arrays = {}
        for name in ("read_bytes", "useful_bytes", "waste_bytes", "stores_touched"):
            if not isinstance(row.get(name), list) or len(row[name]) != len(weights):
                raise ValueError(f"{name}: length differs from effective classes")
            arrays[name] = [integer(value, name) for value in row[name]]
        row.update(arrays)
        row["max_waste_bytes"] = max(arrays["waste_bytes"], default=0)
        amplification, amplification_floor = [], []
        for j, weight in enumerate(weights):
            read, useful, waste, touched = (arrays[name][j] for name in ("read_bytes", "useful_bytes", "waste_bytes", "stores_touched"))
            if read < useful or waste != read - useful or touched > row["stores"]:
                raise ValueError("invalid class byte/count accounting")
            if useful == 0 and (read != 0 or touched != 0):
                raise ValueError("zero-useful class reads a materialized store")
            if weight > 0 and useful:
                amplification.append(Fraction(read, useful))
                if useful >= 4096:
                    amplification_floor.append(Fraction(read, useful))
        for field, source in (("weighted_read_bytes", "read_bytes"), ("weighted_useful_bytes", "useful_bytes"),
                              ("weighted_waste_bytes", "waste_bytes"), ("weighted_stores_touched", "stores_touched")):
            row[field] = sum((weight * value for weight, value in zip(weights, arrays[source], strict=True)), Fraction(0))
        row["worst_amplification"] = max(amplification, default=None)
        row["worst_amplification_floor4096"] = max(amplification_floor, default=None)
        expected = (rational(meta.get("alpha", "1")) * row["weighted_read_bytes"] +
                    rational(meta.get("beta", "0")) * row["weighted_stores_touched"] +
                    rational(meta.get("gamma", "0")) * row["stores"])
        if expected != row["objective_fraction"]:
            raise ValueError(f"objective disagrees with independent weighted-byte/touch reconstruction ({expected} != {row['objective_fraction']})")
        if row["certified"]:
            curve = row.get("curve")
            positive = integer(meta["positive_nodes"], "positive nodes")
            cap = min(row["budget"], positive)
            if not isinstance(curve, list) or len(curve) <= cap:
                raise ValueError("exact curve does not cover every count through the requested budget")
            values = [Fraction(integer(value, "curve cost"), scale) for value in curve[:cap + 1] if value is not None]
            if not values or min(values) != row["objective_fraction"]:
                raise ValueError("exact selected objective differs from curve prefix minimum")
            if row.get("complete_domain") is True and len(curve) != positive + 1:
                raise ValueError("complete curve does not span the declared count domain")
            if row.get("complete_domain") is True:
                feasible_counts = range(1, positive + 1) if positive else (0,)
                if any(curve[count] is None for count in feasible_counts):
                    raise ValueError("complete curve omits a feasible materialized count")
        if meta.get("hierarchy") == "H-flat" and meta.get("workload") == "W0" and method == "base":
            self.flat_baseline_checks += 1
            if row["weighted_waste_bytes"] != 0:
                self.fail("hflat_exact_baseline_nonzero_waste", case_id=case_id, method=method)
        return row

    def update_quality(self, key, row, target=None):
        tally = (self.quality if target is None else target)[key]
        tally["rows"] += 1
        tally["status_counts"][str(row.get("status"))] += 1
        tally["solver_status_counts"][str(row.get("solver_status"))] += 1
        tally["exact_solved"] += int(row["certified"])
        if not row["feasible"]:
            return
        tally["feasible"] += 1
        tally["stores"] += row["stores"]
        tally["total_bytes"] += row["total_bytes"]
        tally["objective"] += row["objective_fraction"]
        for field in ("weighted_read_bytes", "weighted_useful_bytes", "weighted_waste_bytes", "weighted_stores_touched"):
            tally[field] += row[field]
        for field in ("max_waste_bytes", "worst_amplification", "worst_amplification_floor4096"):
            update_maximum(tally, field, row[field])

    def update_consumers(self, group, row, meta, target=None):
        if not row["feasible"]:
            return
        document, weights, _ = self.classes(meta)
        raw = document.get("raw_classes", [])
        for j, effective in enumerate(document["effective_classes"]):
            members = effective.get("members")
            contributions = [(effective.get("name", "effective"), weights[j])]
            if members is not None:
                contributions = [(raw[index]["name"], rational(raw[index]["weight"])) for index in members]
                if sum((weight for _, weight in contributions), Fraction(0)) != weights[j]:
                    raise ValueError("effective class membership weights do not sum to its weight")
            for name, weight in contributions:
                role = str(name).split(":", 1)[0]
                tally = (self.consumer_quality if target is None else target)[group + (row["method"], role)]
                tally["rows"] += 1
                tally["feasible"] += 1
                for field, source in (("weighted_read_bytes", "read_bytes"), ("weighted_useful_bytes", "useful_bytes"),
                                      ("weighted_waste_bytes", "waste_bytes"), ("weighted_stores_touched", "stores_touched")):
                    tally[field] += weight * row[source][j]
                update_maximum(tally, "max_waste_bytes", row["waste_bytes"][j])
                useful = row["useful_bytes"][j]
                if weight > 0 and useful:
                    ratio = Fraction(row["read_bytes"][j], useful)
                    update_maximum(tally, "worst_amplification", ratio)
                    if useful >= 4096:
                        update_maximum(tally, "worst_amplification_floor4096", ratio)

    def process_case(self, case_id, raw_rows, writer=None):
        if case_id not in self.cases:
            self.fail("unknown_case_id", case_id=case_id)
            return
        meta = self.cases[case_id]
        if not self.selected(meta):
            return
        if case_id in self.observed_cases:
            self.fail("noncontiguous_or_duplicate_case", case_id=case_id)
            return
        self.observed_cases.add(case_id)
        group = dimensions(meta)
        rows = {}
        for raw in raw_rows:
            if raw.get("type") == "error":
                self.fail("case_error", case_id=case_id, detail=str(raw.get("message", "CLI error")))
                continue
            if raw.get("method") not in METHODS:
                self.fail("unknown_method", case_id=case_id, method=raw.get("method"))
                continue
            if raw.get("method") not in self.methods:
                continue
            self.row_count += 1
            method = raw.get("method")
            if method in rows:
                self.fail("duplicate_method_row", case_id=case_id, method=method)
                continue
            try:
                rows[method] = self.normalize(raw, case_id, meta)
            except (ValueError, KeyError, TypeError, IndexError) as error:
                self.fail("invalid_row", case_id=case_id, method=method, detail=str(error))
        useful_vectors = {tuple(row["useful_bytes"]) for row in rows.values() if row["feasible"]}
        if len(useful_vectors) > 1:
            self.fail("same_case_useful_volume_mismatch", case_id=case_id)
        exact_values = {row["objective_fraction"] for row in rows.values() if row["certified"]}
        if len(exact_values) > 1:
            self.fail("exact_solver_disagreement", case_id=case_id, detail=str(sorted(exact_values)))
        optimum = next(iter(exact_values)) if len(exact_values) == 1 else None
        baseline = rows.get("base")
        cohort_methods = [m for m in ("base", "km-min", "km-max") if m in self.methods]
        if optimum is not None and all(m in rows and rows[m]["feasible"] for m in cohort_methods):
            chosen = next((rows[m] for m in ("dp", "enum") if m in rows and rows[m]["certified"]), None)
            cohort = [rows[m] for m in cohort_methods]
            if chosen is not None:
                cohort.append({**chosen, "method": "best-exact"})
            for row in cohort:
                self.update_quality(group + (row["method"],), row, self.exact_cohort_quality)
                self.update_consumers(group, row, meta, self.exact_cohort_consumer_quality)
        for method, row in rows.items():
            key = group + (method,)
            self.update_quality(key, row)
            self.update_consumers(group, row, meta)
            if method in EXACT_METHODS:
                coverage = self.coverage[key]
                coverage["observed_cases"] += 1
                coverage["status_counts"][str(row.get("status"))] += 1
                coverage["solver_status_counts"][str(row.get("solver_status"))] += 1
                if row["certified"]:
                    coverage["solved_cases"] += 1
                    coverage["solved_bytes"] += row["total_bytes"]
                    coverage["solved_active_class_weight"] += row["active_class_weight_fraction"]
                    coverage["complete_curve_cases"] += int(row.get("complete_domain") is True)
            self.compare(key, case_id, row, optimum, baseline)
            self.update_scaling(group, row, meta)
            if writer:
                output = {**labeled(group), "partition": meta.get("partition"), **row,
                          "objective": row["objective_fraction"],
                          "active_class_weight": row["active_class_weight_fraction"]}
                writer.writerow({name: exact_text(output.get(name)) for name in CSV_FIELDS})

    def compare(self, key, case_id, row, optimum, baseline):
        if key not in self.comparisons:
            self.comparisons[key] = {"rows": 0, "same_budget_exact_comparisons": 0,
                "absolute_gaps": Counter(), "relative_gaps": Counter(), "baseline_improvements": Counter(),
                "gap_status_counts": Counter(), "baseline_status_counts": Counter()}
        record = self.comparisons[key]
        record["rows"] += 1
        row["absolute_exact_gap"] = row["exact_gap"] = row["baseline_improvement"] = None
        if not row["feasible"]:
            reason = "no_feasible_layout"
        elif optimum is None:
            reason = "no_agreed_certified_same_budget_optimum"
        else:
            gap = row["objective_fraction"] - optimum
            row["absolute_exact_gap"] = gap
            record["absolute_gaps"][gap] += 1
            record["same_budget_exact_comparisons"] += 1
            if gap < 0:
                self.fail("feasible_cost_below_exact_optimum", case_id=case_id, method=row["method"])
            reason = "zero_optimum_relative_gap_undefined" if optimum == 0 else "compared"
            if optimum:
                row["exact_gap"] = gap / optimum
                record["relative_gaps"][row["exact_gap"]] += 1
        row["gap_status"] = reason
        record["gap_status_counts"][reason] += 1
        if not row["feasible"]:
            reason = "no_feasible_layout"
        elif baseline is None or not baseline["feasible"]:
            reason = "no_feasible_baseline"
        elif baseline["objective_fraction"] == 0:
            reason = "zero_baseline_objective"
        else:
            reason = "compared"
            improvement = (baseline["objective_fraction"] - row["objective_fraction"]) / baseline["objective_fraction"]
            row["baseline_improvement"] = improvement
            record["baseline_improvements"][improvement] += 1
        row["baseline_comparison_status"] = reason
        record["baseline_status_counts"][reason] += 1

    def update_scaling(self, group, row, meta):
        names = DIMENSIONS + ("method", "nodes", "classes", "budget", "shape")
        key = group + (row["method"], row.get("nodes"), row.get("classes"), row["budget"], meta.get("shape", "observed"))
        if key not in self.scaling:
            self.scaling[key] = {"dimensions": labeled(key, names), "rows": 0,
                                 "seconds": Counter(), "states": Counter(), "work": Counter(),
                                 "solved_seconds": Counter(),
                                 "solver_status_counts": Counter()}
        record = self.scaling[key]
        record["rows"] += 1
        if row["certified"]:
            record["solved_seconds"][row["seconds"]] += 1
        record["solver_status_counts"][str(row.get("solver_status"))] += 1
        for field in ("seconds", "states", "work"):
            if field in {"states", "work"} and row["method"] not in EXACT_METHODS:
                continue
            if row.get(field) is not None:
                record[field][row[field]] += 1

    def finish(self):
        coverage = []
        for key, record in sorted(self.coverage.items()):
            item = {**labeled(key, DIMENSIONS + ("method",)), **record}
            item["missing_rows"] = record["expected_cases"] - record["observed_cases"]
            for name, numerator, denominator in (
                    ("case_fraction", "solved_cases", "expected_cases"),
                    ("byte_fraction", "solved_bytes", "total_bytes"),
                    ("active_class_weight_fraction", "solved_active_class_weight", "active_class_weight")):
                item[name] = Fraction(record[numerator], record[denominator]) if record[denominator] else None
                item[name + "_denominator_status"] = "positive" if record[denominator] else "zero_denominator"
            if item["missing_rows"]:
                self.fail("missing_exact_method_rows", method=key[-1], detail=f"{key}: {item['missing_rows']}")
            coverage.append(item)
        expected_cases = sum(self.selected(meta) for meta in self.cases.values())
        if len(self.observed_cases) != expected_cases:
            self.fail("missing_cases", detail=f"expected {expected_cases}, observed {len(self.observed_cases)}")
        for group, expected in self.expected_by_group.items():
            for method in self.methods:
                observed = self.quality.get(group + (method,), {}).get("rows", 0)
                if observed != expected and method not in EXACT_METHODS:
                    self.fail("missing_method_rows", method=method,
                              detail=f"{group}: expected {expected}, observed {observed}")
        quality = [{**labeled(key, DIMENSIONS + ("method",)), **record} for key, record in sorted(self.quality.items())]
        for item in quality:
            useful = item["weighted_useful_bytes"]
            item["weighted_read_amplification"] = item["weighted_read_bytes"] / useful if useful else None
            item["metric_scope"] = "feasible rows only; status counts retain every valid observation"
            if not item["feasible"]:
                for field in ("objective", "stores", "total_bytes", "weighted_read_bytes", "weighted_useful_bytes",
                              "weighted_waste_bytes", "weighted_stores_touched"):
                    item[field] = None
        consumers = [{**labeled(key, DIMENSIONS + ("method", "consumer_role")),
                      **{name: value for name, value in record.items() if name in {
                          "rows", "weighted_read_bytes", "weighted_useful_bytes", "weighted_waste_bytes",
                          "weighted_stores_touched", "max_waste_bytes", "worst_amplification",
                          "worst_amplification_floor4096"}}}
                     for key, record in sorted(self.consumer_quality.items())]
        for item in consumers:
            item["class_observations"] = item.pop("rows")
            useful = item["weighted_useful_bytes"]
            item["weighted_read_amplification"] = item["weighted_read_bytes"] / useful if useful else None
        comparisons = []
        for key, record in sorted(self.comparisons.items()):
            item = {**labeled(key, DIMENSIONS + ("method",)), **record}
            for field in ("absolute_gaps", "relative_gaps", "baseline_improvements"):
                item[field] = distribution(record[field])
            comparisons.append(item)
        scaling = []
        for _, record in sorted(self.scaling.items(), key=lambda item: str(item[0])):
            item = dict(record)
            for field in ("seconds", "states", "work", "solved_seconds"):
                item[field] = distribution(record[field])
            scaling.append(item)
        cohort_quality = [{**labeled(key, DIMENSIONS + ("method",)), **value}
                          for key, value in sorted(self.exact_cohort_quality.items())]
        cohort_consumers = [{**labeled(key, DIMENSIONS + ("method", "role")),
                             **{name: value for name, value in record.items() if name in {
                                 "rows", "weighted_read_bytes", "weighted_useful_bytes", "weighted_waste_bytes",
                                 "weighted_stores_touched", "max_waste_bytes", "worst_amplification",
                                 "worst_amplification_floor4096"}}}
                            for key, record in sorted(self.exact_cohort_consumer_quality.items())]
        for item in cohort_quality + cohort_consumers:
            useful = item["weighted_useful_bytes"]
            item["weighted_read_amplification"] = item["weighted_read_bytes"] / useful if useful else None
            item["metric_scope"] = "identical exact-solved cases on which every requested heuristic is feasible"
        for item in cohort_consumers:
            item["class_observations"] = item.pop("rows")
        return {"schema": "tiplog-layout-analysis-v1", "status": "failed" if self.failure_counts else "analyzed",
                "expected_cases": expected_cases, "observed_cases": len(self.observed_cases), "rows": self.row_count,
                "quality": quality, "consumer_quality": consumers, "exact_coverage": coverage,
                "exact_cohort_quality": cohort_quality,
                "exact_cohort_consumer_quality": cohort_consumers,
                "comparisons": comparisons, "scaling": scaling,
                "hierarchy_sensitivity": {"rows": [item for item in quality if item["kind"] == "real"],
                    "hflat_w0_baseline_partitions_checked": self.flat_baseline_checks,
                    "comparison_scope": "parallel hierarchy observations; hierarchy changes the tree and feasible set, so cross-hierarchy values are not optimality gaps"},
                "failure_counts": dict(self.failure_counts), "failures": self.failures,
                "failure_details_truncated": sum(self.failure_counts.values()) > len(self.failures),
                "interpretation": {"coverage_weight_denominator": "sum of active per-partition class weights, including repeated participation of a global basket in different partitions",
                    "bytes": "modeled record-framing-inclusive bytes; not measured physical disk I/O",
                    "runtime": "solver seconds include solver-internal reconstruction and formula consistency checks; exclude prepare and CLI independent formula/materialized verification; diagnostic nonexclusive host",
                    "memory": "states and work are solver proxies, not allocated-byte or RSS measurements",
                    "gap": "only identical case ID, metadata objective and requested materialized-store budget, with an agreed certified exact result",
                    "zero_denominators": "reported null with an explicit status; never silently replaced with zero",
                    "acceptance": "analysis does not establish a P7 phase gate"}}


def read_case_groups(paths):
    current_id, group = None, []
    for path in paths:
        with Path(path).open() as stream:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path}:{number}: invalid JSON") from error
                if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                    raise ValueError(f"{path}:{number}: row requires string id")
                if current_id is not None and row["id"] != current_id:
                    yield current_id, group
                    group = []
                current_id = row["id"]
                group.append(row)
    if current_id is not None:
        yield current_id, group


def build(inputs, metadata_path, *, csv_path=None, kinds=(), methods=METHODS, global_paths=()):
    inputs, global_paths = list(inputs), list(global_paths)
    if csv_path is None:
        return _build(inputs, metadata_path, kinds=kinds, methods=methods, global_paths=global_paths)
    with OutputTransaction(metadata_path, [csv_path], additional_sources=[*inputs, *global_paths]) as transaction:
        summary = _build(inputs, metadata_path, csv_path=transaction.path(csv_path),
                         kinds=kinds, methods=methods, global_paths=global_paths)
        transaction.commit()
    return summary


def _build(inputs, metadata_path, *, csv_path=None, kinds=(), methods=METHODS, global_paths=()):
    inputs = [Path(path) for path in inputs]
    metadata_path = Path(metadata_path)
    metadata = json.loads(metadata_path.read_text())
    analyzer = Analyzer(metadata, methods=methods, kinds=kinds)
    output = None
    try:
        writer = None
        if csv_path is not None:
            csv_path = Path(csv_path)
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            output = csv_path.open("w", newline="")
            writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
            writer.writeheader()
        for case_id, rows in read_case_groups(inputs):
            analyzer.process_case(case_id, rows, writer)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        analyzer.fail("input_processing_error", detail=str(error))
    finally:
        if output is not None:
            output.close()
    summary = analyzer.finish()
    summary["provenance"] = {"metadata": {"path": str(metadata_path), "sha256": sha256(metadata_path)},
        "inputs": [{"path": str(path), "sha256": sha256(path)} for path in inputs],
        "metadata_schema": metadata.get("schema"), "source_hashes": metadata.get("source_hashes", metadata.get("sources")),
        "methods": list(methods), "kinds": list(kinds),
        "comparison_identity": "case_index id, budget, objective_signature if echoed, dimensions, exact rational coefficient/weight reconstruction"}
    if global_paths:
        summary["global_observations"] = []
        for path in global_paths:
            path = Path(path)
            summary["global_observations"].append({"path": str(path), "sha256": sha256(path),
                "document": json.loads(path.read_text()),
                "audit_status": "retained as separately produced observations; this analyzer does not infer certificates from incomplete curves"})
    return json_exact(summary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--kind", action="append", default=[])
    parser.add_argument("--method", choices=METHODS, action="append")
    parser.add_argument("--global", dest="global_paths", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    with OutputTransaction(args.metadata, [args.output, args.csv],
                           additional_sources=[*args.input, *args.global_paths]) as transaction:
        summary = build(args.input, args.metadata, csv_path=transaction.path(args.csv), kinds=args.kind,
                        methods=args.method or METHODS, global_paths=args.global_paths)
        transaction.path(args.output).write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n")
        transaction.commit()
    print(json.dumps({"status": summary["status"], "rows": summary["rows"],
                      "failure_counts": summary["failure_counts"], "output": str(args.output)}))
    return 1 if summary["failure_counts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
