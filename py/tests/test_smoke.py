"""Verify the local package and the scientific Python environment load."""

import io

import matplotlib
import numpy as np

import tiplog_py


def test_python_plumbing():
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    assert tiplog_py.__name__ == "tiplog_py"
    values = np.arange(4, dtype=np.int64)
    assert int(values.sum()) == 6
    figure, axes = plt.subplots()
    axes.plot(values, values * values)
    output = io.BytesIO()
    figure.savefig(output, format="png")
    plt.close(figure)
    assert output.getvalue().startswith(b"\x89PNG\r\n\x1a\n")
