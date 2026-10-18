"""V01–V03 integration: deterministic time windows, inversions and L1 sums."""

import gzip
import json
import struct

import pytest

from tiplog_py.itch.__main__ import main
from tiplog_py.trace import TraceReader


def payload(kind, size, timestamp, symbol=None):
    data = bytearray(size)
    data[0] = ord(kind)
    data[1:3] = (1 if kind != "S" else 0).to_bytes(2, "big")
    data[5:11] = timestamp.to_bytes(6, "big")
    if symbol is not None:
        data[11:19] = symbol.ljust(8, b" ")
    return bytes(data)


def source(tmp_path, complete=True):
    messages = [payload("R", 39, 10, b"AAA"), payload("D", 19, 30),
                payload("D", 19, 50), payload("D", 19, 35), payload("S", 12, 60)]
    content = b"".join(struct.pack(">H", len(item)) + item for item in messages)
    if complete:
        content += b"\0\0"
    path = tmp_path / "synthetic.gz"
    path.write_bytes(gzip.compress(content, mtime=0))
    return path, messages, content


def test_cli_window_keeps_later_inverted_timestamps_and_hflat(tmp_path):
    path, messages, _ = source(tmp_path)
    spec = tmp_path / "spec.tpl"
    flat = tmp_path / "flat.tpl"
    args = ["convert", str(path), "--output", str(spec), "--also-flat", str(flat), "--start", "20", "--end", "40"]
    assert main(args) == 0
    original_spec, original_flat = spec.read_bytes(), flat.read_bytes()
    assert main(args) == 0
    assert original_spec == spec.read_bytes()
    assert original_flat == flat.read_bytes()
    with TraceReader(spec) as reader:
        assert [item.payload for item in reader] == [messages[1], messages[3]]
        assert reader.dictionary == {1: "itch/AAA/modify/delete"}
    with TraceReader(flat) as reader:
        assert reader.dictionary == {1: "itch/AAA/D"}
    metadata = json.loads((tmp_path / "spec.tpl.meta.json").read_text())
    assert metadata["source"]["terminated"]
    assert metadata["timestamp_inversions_full_scanned_stream"] == 1


def test_cli_measure_reconciles_all_counts_bytes_runs_and_window(tmp_path):
    path, messages, content = source(tmp_path)
    output = tmp_path / "counts.json"
    tables = tmp_path / "tables"
    assert main(["measure", str(path), "--output", str(output), "--volumes-dir", str(tables), "--start", "20", "--end", "40"]) == 0
    result = json.loads(output.read_text())
    assert result["message_count"] == len(messages)
    assert result["total_uncompressed_bytes"] == len(content)
    assert result["payload_bytes"] == sum(map(len, messages))
    assert result["by_type"]["D"]["count"] == 3
    assert result["by_locate"]["1"]["count"] == 4
    assert result["timestamp_inversions"] == 1
    assert result["window"]["message_count"] == 2
    assert result["routing"]["unknown_locate_messages"] == 0
    assert (tables / "itch_20191230_full_day_topic_volumes.csv").is_file()
    assert (tables / "itch_20191230_window_partition_complexity.csv").is_file()
    assert (tables / "itch_20191230_full_day_run_lengths.csv").read_text().splitlines() == [
        "run_length,runs,messages", "1,1,1", "4,1,4"]


def test_cli_missing_terminator_propagates_incomplete_metadata(tmp_path):
    path, _, _ = source(tmp_path, False)
    output = tmp_path / "spec.tpl"
    assert main(["convert", str(path), "--output", str(output), "--start", "0", "--end", "100"]) == 0
    metadata = json.loads((tmp_path / "spec.tpl.meta.json").read_text())
    assert metadata["source"]["incomplete"]
    assert not metadata["source"]["terminated"]


def test_cli_rejects_mismatched_source_identity_before_output(tmp_path):
    path, _, _ = source(tmp_path)
    output = tmp_path / "invalid.tpl"
    with pytest.raises(ValueError, match="does not match"):
        main(["convert", str(path), "--output", str(output), "--source-sha256", "00" * 32])
    assert not output.exists()


def test_cli_combined_conversion_counts_equal_standalone_measurement(tmp_path):
    path, _, _ = source(tmp_path)
    measured = tmp_path / "measured.json"
    combined = tmp_path / "combined.json"
    measure_tables = tmp_path / "measure-tables"
    combined_tables = tmp_path / "combined-tables"
    assert main(["measure", str(path), "--output", str(measured), "--volumes-dir", str(measure_tables),
                 "--start", "20", "--end", "40"]) == 0
    assert main(["convert", str(path), "--output", str(tmp_path / "spec.tpl"), "--also-flat", str(tmp_path / "flat.tpl"),
                 "--counts-output", str(combined), "--volumes-dir", str(combined_tables),
                 "--start", "20", "--end", "40"]) == 0
    first = json.loads(measured.read_text())
    second = json.loads(combined.read_text())
    for key in ("elapsed_seconds", "uncompressed_bytes_per_second", "measurement_boundary", "source_sha256"):
        first.pop(key, None)
        second.pop(key, None)
    assert first == second
    for original in measure_tables.iterdir():
        assert original.read_bytes() == (combined_tables / original.name).read_bytes()


def test_cli_rejects_source_overwrite_and_duplicate_outputs(tmp_path):
    path, _, _ = source(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="preserve the source"):
        main(["convert", str(path), "--output", str(path)])
    with pytest.raises(ValueError, match="distinct"):
        main(["convert", str(path), "--output", str(tmp_path / "both.tpl"),
              "--also-flat", str(tmp_path / "both.tpl")])
    with pytest.raises(ValueError, match="preserve the source"):
        main(["convert", str(path), "--output", str(tmp_path / "spec.tpl"),
              "--counts-output", str(path)])
    assert path.read_bytes() == before
