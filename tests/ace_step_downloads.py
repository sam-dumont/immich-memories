"""Tiny on-disk stand-in for ACE-Step's multi-gigabyte Hugging Face snapshots."""

from pathlib import Path
from types import ModuleType


def snapshot_module() -> ModuleType:
    # WHY: model downloads are the external boundary; runtime path selection stays real.
    hub = ModuleType("huggingface_hub")

    def download(*, repo_id, revision, local_dir):
        assert len(revision) == 40
        names = (
            ("vae", "Qwen3-Embedding-0.6B", "acestep-v15-turbo", "acestep-5Hz-lm-1.7B")
            if repo_id == "ACE-Step/Ace-Step1.5"
            else ("",)
        )
        for name in names:
            directory = Path(local_dir) / name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "model.safetensors").write_bytes(b"synthetic weights")
        return str(local_dir)

    hub.snapshot_download = download
    return hub
