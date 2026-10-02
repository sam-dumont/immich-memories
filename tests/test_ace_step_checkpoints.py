"""Local ACE-Step initialization uses immutable model snapshots, never a moving branch."""

from pathlib import Path

import pytest

from immich_memories.audio.generators.ace_step_checkpoints import (
    CHECKPOINT_REVISIONS,
    MAIN_REPO,
    pinned_checkpoints,
)


def test_downloads_pinned_main_dit_and_planner_into_a_separate_cache(tmp_path, monkeypatch):
    calls = []

    # WHY: replace the multi-gigabyte Hugging Face downloads with tiny local weight fixtures.
    def download(*, repo_id, revision, local_dir):
        calls.append((repo_id, revision, Path(local_dir)))
        names = (
            ("vae", "Qwen3-Embedding-0.6B", "acestep-v15-turbo", "acestep-5Hz-lm-1.7B")
            if repo_id == MAIN_REPO
            else ("",)
        )
        for name in names:
            folder = Path(local_dir) / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "model.safetensors").write_bytes(b"synthetic")
        return str(local_dir)

    monkeypatch.setattr("huggingface_hub.snapshot_download", download)
    monkeypatch.setenv("ACESTEP_CHECKPOINTS_DIR", str(tmp_path))
    import os

    with pinned_checkpoints(tmp_path, "acestep-v15-xl-turbo", "acestep-5Hz-lm-4B") as prepared:
        assert prepared != tmp_path
        assert os.environ["ACESTEP_CHECKPOINTS_DIR"] == str(prepared)
        assert (prepared / "acestep-v15-xl-turbo/model.safetensors").is_file()
        assert (prepared / "acestep-5Hz-lm-4B/model.safetensors").is_file()

    assert os.environ["ACESTEP_CHECKPOINTS_DIR"] == str(tmp_path)
    assert [(repo, revision) for repo, revision, _ in calls] == [
        (repo, CHECKPOINT_REVISIONS[repo])
        for repo in (MAIN_REPO, "ACE-Step/acestep-v15-xl-turbo", "ACE-Step/acestep-5Hz-lm-4B")
    ]


def test_unknown_model_is_refused_before_downloading(tmp_path):
    with (
        pytest.raises(ValueError, match="No pinned ACE-Step checkpoint"),
        pinned_checkpoints(tmp_path, "../untrusted", None),
    ):
        pytest.fail("unknown model admitted")


def test_failed_download_does_not_enter_initialization(tmp_path, monkeypatch):
    # WHY: simulate the download boundary failing, without contacting the model host.
    def fail(**kwargs):
        raise OSError("offline")

    monkeypatch.setattr("huggingface_hub.snapshot_download", fail)
    with (
        pytest.raises(OSError, match="offline"),
        pinned_checkpoints(tmp_path, "acestep-v15-turbo", None),
    ):
        pytest.fail("failed download admitted")


def test_incomplete_snapshot_does_not_fall_back_to_upstream_downloads(tmp_path, monkeypatch):
    # WHY: emulate an incomplete cached download; no model bytes cross the network.
    monkeypatch.setattr("huggingface_hub.snapshot_download", lambda **_kwargs: str(tmp_path))
    with (
        pytest.raises(RuntimeError, match="incomplete"),
        pinned_checkpoints(tmp_path, "acestep-v15-turbo", None),
    ):
        pytest.fail("incomplete snapshot admitted")


def test_default_models_share_one_snapshot_and_restore_unset_environment(tmp_path, monkeypatch):
    import os

    from tests.ace_step_downloads import snapshot_module

    # WHY: tiny weight files replace the remote multi-gigabyte snapshot.
    monkeypatch.setattr("huggingface_hub.snapshot_download", snapshot_module().snapshot_download)
    monkeypatch.delenv("ACESTEP_CHECKPOINTS_DIR", raising=False)
    with (
        pytest.raises(RuntimeError, match="handler failed"),
        pinned_checkpoints(tmp_path, "acestep-v15-turbo", "acestep-5Hz-lm-1.7B") as directory,
    ):
        assert (directory / "vae/model.safetensors").is_file()
        raise RuntimeError("handler failed")
    assert "ACESTEP_CHECKPOINTS_DIR" not in os.environ
