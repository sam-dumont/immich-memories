"""Setup metadata keeps editorial producers available in installed distributions."""

import tomllib
from pathlib import Path

from packaging.requirements import Requirement


def test_editorial_extra_declares_each_optional_runtime_and_all_includes_it():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    extras = project["project"]["optional-dependencies"]
    assert {Requirement(value).name for value in extras["editorial"]} == {
        "onnxruntime",
        "tokenizers",
        "huggingface-hub",
        "kaldi-native-fbank",
    }
    assert "immich-memories[editorial]" in extras["all"]
    assert "immich-memories[editorial]" in extras["all-mac"]


def test_a_cpu_install_resolves_no_cuda_wheel_and_no_torch_family():
    """The device split's whole point: `editorial` on a CPU box pulls neither.

    The torch family is what used to drag fifteen `nvidia-*` wheels into a Linux
    resolution, for one 5.6M-parameter classifier that now runs as an ONNX graph.
    """
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    extras = project["project"]["optional-dependencies"]
    cpu = {Requirement(value).name for value in extras["editorial"]}

    assert not cpu & {"torch", "torchvision", "timm", "onnxruntime-gpu"}
    assert {Requirement(value).name for value in extras["editorial-cuda"]} == {
        "onnxruntime-gpu",
        "tokenizers",
        "huggingface-hub",
        "kaldi-native-fbank",
    }
    # The CUDA variant replaces the CPU one; two distributions owning the same
    # import name must never be resolved into one environment.
    assert "immich-memories[editorial-cuda]" not in extras["all"]
    assert "immich-memories[editorial-cuda]" not in extras["all-mac"]


def test_worker_is_self_contained_for_detector_only_python_environments():
    """The worker entry point (``_worker``, run as ``__main__``) never needs the package.

    An import inside a function body only runs when that function is called, and one under
    ``if TYPE_CHECKING:`` never runs at all; the store-side banking the parent process does
    (``_FactSpool``, ``prepare_detectors``) may use either without the bare detector
    interpreter ever needing ``immich_memories`` installed. Only an unconditional
    module-level import would.
    """
    import ast

    path = (
        Path(__file__).parents[1]
        / "src/immich_memories/analysis/editorial_preparation_detectors.py"
    )
    tree = ast.parse(path.read_text())
    unconditional = [
        node
        for node in tree.body
        if not (isinstance(node, ast.If) and ast.unparse(node.test) == "TYPE_CHECKING")
    ]
    imports = [node.module for node in unconditional if isinstance(node, ast.ImportFrom)]
    assert not any(module and module.startswith("immich_memories") for module in imports)
