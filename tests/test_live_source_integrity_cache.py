"""Integrity proof reuse is bound to original bytes and the decoding contract."""

import hashlib
from types import SimpleNamespace

from immich_memories.analysis.live_source_integrity import OriginalSourceIntegrity


class Decoder:
    """# WHY: replaces only the external decoder boundary, not proof-cache behavior."""

    def __init__(self):
        self.calls = 0
        self.version = "synthetic-ffprobe-v1"

    def decoder_identity(self):
        return self.version

    def get(self, path):
        return SimpleNamespace(video_stream_index=0)

    def complete_video_presentation(self, path):
        self.calls += 1
        return {
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "video_stream_index": 0,
            "decoder_identity": self.version,
            "presentation_policy": "synthetic-policy-v1",
        }


def test_exact_original_proof_reuses_across_paths_and_changes_with_source_bytes(tmp_path):
    original = tmp_path / "original.mov"
    original.write_bytes(b"synthetic original bytes")
    decoder = Decoder()
    kwargs = {"directory": tmp_path / "proofs", "probes": decoder, "policy": "synthetic-policy-v1"}
    first = OriginalSourceIntegrity(fetch=lambda _: original, **kwargs)(["video"])
    renamed = tmp_path / "renamed.mov"
    renamed.write_bytes(original.read_bytes())
    second = OriginalSourceIntegrity(fetch=lambda _: renamed, **kwargs)(["video"])
    assert first == second and first["video"]["valid"] is True
    assert decoder.calls == 1
    renamed.write_bytes(b"changed original bytes")
    changed = OriginalSourceIntegrity(fetch=lambda _: renamed, **kwargs)(["video"])
    assert changed["video"]["source_sha256"] != first["video"]["source_sha256"]
    assert decoder.calls == 2


def test_decoder_version_invalidates_original_byte_proof(tmp_path):
    original = tmp_path / "original.mov"
    original.write_bytes(b"unchanged original")
    decoder = Decoder()
    verifier = OriginalSourceIntegrity(
        fetch=lambda _: original,
        directory=tmp_path / "proofs",
        probes=decoder,
        policy="synthetic-policy-v1",
    )
    first = verifier(["video"])
    decoder.version = "synthetic-ffprobe-v2"
    second = verifier(["video"])
    assert first["video"]["decoder_identity"] != second["video"]["decoder_identity"]
    assert decoder.calls == 2


def test_backend_reuses_original_verifier_for_planning_refinement(monkeypatch):
    from contextlib import ExitStack

    from immich_memories.analysis import editorial_runtime_backend as module

    built = []

    def verifier(_ids):
        return {}

    def create(source, *, resources):
        # WHY: replace only external source acquisition, retaining backend lifecycle.
        built.append(source)
        return verifier

    monkeypatch.setattr(module, "production_live_source_integrity", create)
    backend = module.ProductionPostCardBackend(
        config=None,
        context=None,
        people=None,
        thumbnail_cache=None,
        store=None,
        bank_root=None,
        ports=None,
    )
    with ExitStack() as resources:
        assert backend.source_integrity("source", resources) is verifier
        assert backend.source_integrity("refined", resources) is verifier
    assert built == ["source"]


def test_original_changed_during_verification_is_not_banked(tmp_path):
    import pytest

    original = tmp_path / "original.mov"
    original.write_bytes(b"original before verification")

    class ChangingDecoder(Decoder):
        def complete_video_presentation(self, path):
            result = super().complete_video_presentation(path)
            path.write_bytes(b"replacement after verification")
            return result

    directory = tmp_path / "proofs"
    verifier = OriginalSourceIntegrity(
        fetch=lambda _: original,
        directory=directory,
        probes=ChangingDecoder(),
        policy="synthetic-policy-v1",
    )
    with pytest.raises(ValueError, match="changed"):
        verifier(["video"])
    assert not list(directory.glob("*.json"))


def test_unavailable_original_is_not_a_corruption_verdict_or_persisted(tmp_path):
    import pytest

    def unavailable(_video):
        raise TimeoutError("original transport timed out")

    directory = tmp_path / "proofs"
    verifier = OriginalSourceIntegrity(
        fetch=unavailable,
        directory=directory,
        probes=Decoder(),
        policy="synthetic-policy-v1",
    )
    with pytest.raises(TimeoutError, match="transport"):
        verifier(["video"])
    assert not list(directory.glob("*.json"))


def test_unreadable_cached_proof_requires_a_new_decoder_verdict(tmp_path):
    original = tmp_path / "original.mov"
    original.write_bytes(b"unchanged original")
    decoder = Decoder()
    directory = tmp_path / "proofs"
    verifier = OriginalSourceIntegrity(
        fetch=lambda _: original,
        directory=directory,
        probes=decoder,
        policy="synthetic-policy-v1",
    )
    expected = verifier(["video"])
    [record] = directory.glob("*.json")
    record.write_text("{broken json")
    assert verifier(["video"]) == expected
    assert decoder.calls == 2


def test_positive_media_refusal_is_cached_with_byte_bound_reason(tmp_path):
    from immich_memories.processing.probe_cache import PresentationIntegrityError

    original = tmp_path / "original.mov"
    original.write_bytes(b"decoder-rejected original")

    class RefusingDecoder(Decoder):
        def complete_video_presentation(self, path):
            evidence = super().complete_video_presentation(path)
            raise PresentationIntegrityError("non-increasing-decoded-presentation", evidence)

    decoder = RefusingDecoder()
    verifier = OriginalSourceIntegrity(
        fetch=lambda _: original,
        directory=tmp_path / "proofs",
        probes=decoder,
        policy="synthetic-policy-v1",
    )
    first = verifier(["video"])
    assert first["video"]["valid"] is False
    assert first["video"]["reason"] == "non-increasing-decoded-presentation"
    assert first == verifier(["video"])
    assert decoder.calls == 1


def test_decoder_infrastructure_failure_is_not_cached_or_reclassified(tmp_path):
    import pytest

    from immich_memories.processing.probe_cache import ProbeError

    original = tmp_path / "original.mov"
    original.write_bytes(b"original with unavailable decoder")

    class UnavailableDecoder(Decoder):
        def complete_video_presentation(self, path):
            self.calls += 1
            raise ProbeError("decoder invocation unavailable")

    decoder = UnavailableDecoder()
    directory = tmp_path / "proofs"
    verifier = OriginalSourceIntegrity(
        fetch=lambda _: original,
        directory=directory,
        probes=decoder,
        policy="synthetic-policy-v1",
    )
    for _ in range(2):
        with pytest.raises(ProbeError, match="invocation unavailable"):
            verifier(["video"])
    assert decoder.calls == 2
    assert not list(directory.glob("*.json"))


def test_production_original_acquisition_is_lazy_and_closes_owned_client(tmp_path, monkeypatch):
    from contextlib import ExitStack

    from immich_memories.analysis import editorial_runtime_ports
    from immich_memories.analysis.live_source_integrity import production_live_source_integrity
    from immich_memories.processing import probe_cache
    from tests.test_editorial_event_motion_material import live_source

    source = live_source(tmp_path, pictures=1, add_context=False)
    source.config.cache.directory = str(tmp_path / "cache")
    downloads, closed = [], []

    class Client:
        def download_asset(self, video_id, path):
            # WHY: replaces only original transport; real cache and lifecycle stay active.
            downloads.append(video_id)
            path.write_bytes(b"transported original bytes")

        def close(self):
            closed.append(True)

    class OwnedDecoder(Decoder):
        def complete_video_presentation(self, path):
            return super().complete_video_presentation(path) | {
                "presentation_policy": probe_cache.PRESENTATION_POLICY
            }

    monkeypatch.setattr(editorial_runtime_ports, "_stage_reads", lambda _: Client())
    monkeypatch.setattr(probe_cache, "ProbeCache", OwnedDecoder)
    with ExitStack() as resources:
        verifier = production_live_source_integrity(source, resources=resources)
        assert not downloads
        assert verifier is not None
        assert verifier(["video-0"])["video-0"]["valid"] is True
        assert downloads == ["video-0"]
        assert not closed
    assert closed == [True]


def test_backend_does_not_reuse_an_original_download_batch_after_its_edit_closes(monkeypatch):
    from contextlib import ExitStack

    from immich_memories.analysis import editorial_runtime_backend as module

    built = []

    def create(source, *, resources):
        built.append(source)
        return lambda _: {}

    monkeypatch.setattr(module, "production_live_source_integrity", create)
    backend = module.ProductionPostCardBackend(
        config=None,
        context=None,
        people=None,
        thumbnail_cache=None,
        store=None,
        bank_root=None,
        ports=None,
    )
    with ExitStack() as first:
        backend.source_integrity("first edit", first)
    with ExitStack() as second:
        backend.source_integrity("second edit", second)
    assert built == ["first edit", "second edit"]
