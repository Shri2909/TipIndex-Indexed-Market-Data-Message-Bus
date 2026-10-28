"""Red-team input (AUD-001): a *valid* trace v1 file with a few deep topic paths.
Usage: PYTHONPATH=<copy>/py python make_deep_trace.py OUT DEPTH PATHS"""
import sys

from tiplog_py.trace import TraceWriter

out, depth, paths = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
with TraceWriter(out, "0" * 64) as writer:
    for k in range(paths):
        writer.append(f"b{k}" + "/a" * (depth - 1), b"\x00" * 16, k)
    writer.append("itch/AAPL/add/anon", b"\x00" * 20, paths)
