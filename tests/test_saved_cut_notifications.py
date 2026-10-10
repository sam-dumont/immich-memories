"""Saved-cut renders send the configured completion message, like a full generation."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from immich_memories.automation.notification_state import NotificationStateStore
from immich_memories.db import open_store
from immich_memories.generate_saved_cut import CutRenderRequest, render_saved_cut
from tests.test_generate_saved_cut import RUN
from tests.test_revision_render import cut  # noqa: F401 - the saved-cut fixture


def test_saved_cut_sends_one_success_message_after_the_film_is_written(cut, monkeypatch):  # noqa: F811
    params, attempt = cut
    params.config.notifications.enabled = True
    params.config.notifications.urls = ["slack://unit-test-target"]
    film = attempt / "film.mp4"
    apprise = MagicMock()
    apprise.Apprise.return_value.notify.return_value = True

    def render(given):
        assert not apprise.Apprise.return_value.notify.called
        film.write_bytes(b"rendered film")
        return film

    # WHY: FFmpeg's write and Apprise's external delivery are the two I/O boundaries.
    monkeypatch.setattr("immich_memories.generate_saved_cut.generate_memory", render)
    monkeypatch.setitem(sys.modules, "apprise", apprise)

    result = render_saved_cut(
        config=params.config,
        client=None,
        run=RUN,
        attempt_dir=attempt,
        revision=None,
        request=CutRenderRequest(),
    )

    assert result == film and film.is_file()
    apprise.Apprise.return_value.notify.assert_called_once()
    sent = apprise.Apprise.return_value.notify.call_args.kwargs
    assert sent["title"] == "Memory Generated: Monthly Highlights"
    assert f"Output: {film}" in sent["body"]
    health = NotificationStateStore(open_store(params.config)).get()
    assert health is not None and health.last_success_at is not None


def test_saved_render_message_uses_its_own_warnings_and_uploaded_film_link(cut, monkeypatch):  # noqa: F811
    from dataclasses import replace

    from immich_memories.operations.run_index import record_run_attempt
    from immich_memories.tracking import RunDatabase

    params, attempt = cut
    config = params.config
    config.notifications.enabled = True
    config.notifications.urls = ["slack://unit-test-target"]
    config.immich.public_url = "https://photos.example.test"
    store = open_store(config)
    database = RunDatabase(store)
    database.save_run(replace(RUN, warnings=["Old cut warning"]))
    record_run_attempt(RUN.run_id, attempt, "", store=store)
    rendered = replace(
        RUN,
        run_id="20260927_090000_beef",
        output_path=str(attempt / "film.mp4"),
        warnings=["Output space is running low"],
        immich_asset_id="12345678-1234-1234-1234-123456789abc",
    )
    apprise = MagicMock()
    apprise.Apprise.return_value.notify.return_value = True

    def render(given):
        from pathlib import Path

        database.save_run(rendered)
        record_run_attempt(rendered.run_id, attempt, rendered.output_path, store=store)
        return Path(rendered.output_path)

    # WHY: the renderer writes its run; Apprise would deliver outside the sealed test.
    monkeypatch.setattr("immich_memories.generate_saved_cut.generate_memory", render)
    monkeypatch.setitem(sys.modules, "apprise", apprise)
    render_saved_cut(
        config=config,
        client=None,
        run=RUN,
        attempt_dir=attempt,
        revision=None,
        request=CutRenderRequest(),
    )

    apprise.Apprise.return_value.notify.assert_called_once()
    body = apprise.Apprise.return_value.notify.call_args.kwargs["body"]
    assert "Warning: Output space is running low" in body
    assert "Old cut warning" not in body
    assert (
        "Watch in Immich: https://photos.example.test/photos/12345678-1234-1234-1234-123456789abc"
        in body
    )


@pytest.mark.parametrize("policy", ["disabled", "success_off", "no_targets", "cooldown"])
def test_saved_render_respects_the_existing_notification_policy(cut, monkeypatch, policy):  # noqa: F811
    from immich_memories.automation.notification_state import NotificationFailureCategory

    params, attempt = cut
    config = params.config
    config.notifications.enabled = policy != "disabled"
    config.notifications.on_success = policy != "success_off"
    config.notifications.urls = [] if policy == "no_targets" else ["slack://unit-test-target"]
    if policy == "cooldown":
        NotificationStateStore(open_store(config)).record_failure(NotificationFailureCategory.QUOTA)
    film = attempt / "film.mp4"
    apprise = MagicMock()
    # WHY: do not run FFmpeg or contact the external notification target.
    monkeypatch.setattr("immich_memories.generate_saved_cut.generate_memory", lambda _given: film)
    monkeypatch.setitem(sys.modules, "apprise", apprise)

    assert (
        render_saved_cut(
            config=config,
            client=None,
            run=RUN,
            attempt_dir=attempt,
            revision=None,
            request=CutRenderRequest(),
        )
        == film
    )
    apprise.Apprise.return_value.notify.assert_not_called()


def test_a_failed_render_never_sends_a_success_message(cut, monkeypatch):  # noqa: F811
    params, attempt = cut
    params.config.notifications.enabled = True
    params.config.notifications.urls = ["slack://unit-test-target"]
    apprise = MagicMock()

    def fail(given):
        raise RuntimeError("encoding failed")

    # WHY: simulate encoder failure and prevent any external notification delivery.
    monkeypatch.setattr("immich_memories.generate_saved_cut.generate_memory", fail)
    monkeypatch.setitem(sys.modules, "apprise", apprise)

    with pytest.raises(RuntimeError, match="encoding failed"):
        render_saved_cut(
            config=params.config,
            client=None,
            run=RUN,
            attempt_dir=attempt,
            revision=None,
            request=CutRenderRequest(),
        )
    apprise.Apprise.return_value.notify.assert_not_called()


def test_failed_notification_delivery_does_not_discard_the_finished_film(cut, monkeypatch):  # noqa: F811
    params, attempt = cut
    params.config.notifications.enabled = True
    params.config.notifications.urls = ["slack://unit-test-target"]
    film = attempt / "film.mp4"
    film.write_bytes(b"rendered film")
    apprise = MagicMock()
    apprise.Apprise.return_value.notify.side_effect = RuntimeError("provider unavailable")
    # WHY: keep film generation and the unavailable provider at their I/O boundaries.
    monkeypatch.setattr("immich_memories.generate_saved_cut.generate_memory", lambda _given: film)
    monkeypatch.setitem(sys.modules, "apprise", apprise)

    result = render_saved_cut(
        config=params.config,
        client=None,
        run=RUN,
        attempt_dir=attempt,
        revision=None,
        request=CutRenderRequest(),
    )

    assert result == film and film.is_file()
    health = NotificationStateStore(open_store(params.config)).get()
    assert health is not None and health.last_failure_at is not None
    assert health.last_success_at is None
