"""The production cut path hears a kept clip's own sound: speech extends its cut, music flags it.

The GPU job's integration suite is the other place this path runs; it never ran there until
#2549, because that job lacked the editorial extra and the cut quietly kept its planned
length. Here the same entry point runs with the real vendored detector wherever it is
installed (`make dev` installs it, so every pre-commit run checks it).
"""

from __future__ import annotations

import shutil
from contextlib import ExitStack
from types import SimpleNamespace

import pytest

from immich_memories.analysis.runtime.ports import production_cut_resolvers
from immich_memories.config.loader import Config
from immich_memories.db import open_store
from immich_memories.speech.fireredvad import FireRedSpeechDetector
from tests.conftest import make_asset
from tests.speech_videos import SPOKEN, SUNG, video_with_sound

pytestmark = [
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not available"),
    pytest.mark.skipif(
        not FireRedSpeechDetector().available,
        reason="onnxruntime or kaldi-native-fbank not installed (the editorial extra)",
    ),
]


def _resolve(tmp_path, monkeypatch, fixture_name: str) -> dict:
    video = video_with_sound(tmp_path / "clip.mp4", fixture_name)
    downloads: list[str] = []

    # WHY: only Immich transport is replaced; decoding, detection and the cut are real.
    class Client:
        def __init__(self, **_kwargs):
            pass

        def download_playback(self, asset_id, path):
            downloads.append(asset_id)
            path.write_bytes(video.read_bytes())

        def close(self):
            pass

    monkeypatch.setattr("immich_memories.api.sync_client.SyncImmichClient", Client)
    source = SimpleNamespace(
        config=Config(),
        assets={"clip": make_asset("clip", duration=3)},
        companion_assets={},
        bank_dir=tmp_path / "banks",
        store=open_store(),
    )
    carrier = {"asset_id": "clip", "kind": "video", "seconds": 1.0, "raw_seconds": 3.0}
    with ExitStack() as resources:
        _windows, resolve_speech = production_cut_resolvers(source, resources=resources)
        assert resolve_speech is not None, "speech cuts are on by default"
        [resolved] = resolve_speech([carrier])
    assert downloads == ["clip"]
    return resolved


def test_a_cut_planned_mid_sentence_runs_on_to_the_end_of_the_spoken_line(tmp_path, monkeypatch):
    resolved = _resolve(tmp_path, monkeypatch, SPOKEN)

    # Planned for 1 s, inside the first of two lines spoken 0.46 s apart: one exchange, so
    # the cut ends with the second line rather than in the breath (#1950).
    assert resolved["seconds"] == pytest.approx(3.0, abs=0.05)
    assert resolved["has_music"] is False


def test_a_clip_whose_own_sound_sings_is_carried_as_music(tmp_path, monkeypatch):
    assert _resolve(tmp_path, monkeypatch, SUNG)["has_music"] is True
