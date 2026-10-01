"""Diagnostics call the shipped still-detector interface and stay offline."""

from types import SimpleNamespace

import pytest
from scripts.benchmark_preparation import Stage, Unavailable, run_nsfw_marqo


def test_marqo_benchmark_requires_the_pinned_export_path():
    options = SimpleNamespace(
        marqo_onnx="", provider="cpu", allow_downloads=False, detector_cache=""
    )
    with pytest.raises(Unavailable, match="marqo-onnx"):
        run_nsfw_marqo(Stage("nsfw_marqo"), [], options)


def test_marqo_benchmark_reports_a_missing_local_export_without_fetching(tmp_path):
    options = SimpleNamespace(marqo_onnx=str(tmp_path / "absent.onnx"), provider="cpu")
    with pytest.raises(Unavailable, match="no model"):
        run_nsfw_marqo(Stage("nsfw_marqo"), [], options)
