"""Settings page: every setting with its source; what is edited here is saved to the database.

A setting the environment or config.yaml sets is greyed out and names what sets it, because
a save underneath it would change nothing. This page never writes config.yaml.
"""

from __future__ import annotations

import json
import logging
from itertools import groupby
from typing import Any

from nicegui import ui

from immich_memories.config import get_config, get_config_path
from immich_memories.config_sources import SettingSource, describe_settings
from immich_memories.settings_edit import SettingRefused, save_settings
from immich_memories.settings_store import SECRET_KEY_ENV, secret_key_from_env
from immich_memories.ui.components import im_button, im_info_card, im_section_header
from immich_memories.ui.i18n import tr

logger = logging.getLogger(__name__)

_OPEN_SECTIONS = {"immich", "defaults", "output"}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


def form_changes(entries: list[SettingSource], values: dict[str, Any]) -> dict[str, Any]:
    """The form values that differ from what the page showed, ready for `save_settings`.

    A blank secret keeps the stored one; lists and mappings are edited as JSON.
    Raises `SettingRefused` when a JSON field does not parse.
    """
    changes: dict[str, Any] = {}
    for entry in entries:
        if entry.key not in values or not entry.editable:
            continue
        raw = values[entry.key]
        if entry.secret:
            if raw:
                changes[entry.key] = raw
            continue
        if raw in (entry.value, _as_text(entry.value)):
            continue
        if isinstance(entry.value, (list, dict)):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raise SettingRefused(f"{entry.key}: not valid JSON") from None
        changes[entry.key] = raw
    return changes


def save_form(entries: list[SettingSource], values: dict[str, Any]) -> str | None:
    """Save the edited values to the database; the refusal to show, or None when saved."""
    try:
        changes = form_changes(entries, values)
        if changes:
            save_settings(changes)
    except SettingRefused as refusal:
        return str(refusal)
    return None


def _origin(entry: SettingSource) -> str:
    if entry.source == "env":
        return tr("Set by {name} (environment)", name=entry.override)
    if entry.source == "file":
        return tr("Set in config.yaml as {key}", key=entry.override)
    if entry.source == "database":
        return tr("Saved here")
    return tr("Default")


def _widget(entry: SettingSource, values: dict[str, Any], locked: bool) -> None:
    def remember(event: Any) -> None:
        values[entry.key] = event.value

    if isinstance(entry.value, bool):
        widget: Any = ui.switch(value=entry.value, on_change=remember)
    elif entry.secret:
        widget = ui.input(
            password=True,
            placeholder=tr("Saved - type a new key to replace it") if entry.value else "",
            on_change=remember,
        )
    else:
        widget = ui.input(value=_as_text(entry.value), on_change=remember)
    widget.classes("flex-1").props("dense")
    if locked:
        widget.disable()


def _render_row(entry: SettingSource, prefix: str, values: dict[str, Any], can_seal: bool) -> None:
    locked = not entry.editable or (entry.secret and not can_seal)
    with (
        ui.row()
        .classes("w-full items-center gap-3 no-wrap")
        .style("opacity: 0.5" if locked else "")
    ):
        ui.label(entry.key.removeprefix(prefix)).classes("text-sm").style(
            "min-width: 16rem; color: var(--im-text-secondary); font-family: monospace"
        )
        _widget(entry, values, locked)
        ui.label(_origin(entry)).classes("text-xs").style(
            "min-width: 16rem; color: var(--im-text-muted)"
        )


def _render_section(section: str, entries: list[SettingSource], can_seal: bool) -> None:
    values: dict[str, Any] = {}
    overridden = sum(entry.source in ("env", "file") for entry in entries)
    title = tr(
        "{title}  ({n_keys} keys)", title=section.replace("_", " ").title(), n_keys=len(entries)
    )
    if overridden:
        title += "  · " + tr("{count} set outside this page", count=overridden)
    with (
        ui.expansion(title, icon="tune", value=section in _OPEN_SECTIONS)
        .classes("w-full mt-1")
        .style(
            "background:var(--im-bg-elevated);border:1px solid var(--im-border-light);"
            "border-radius:8px"
        )
    ):
        for entry in entries:
            _render_row(entry, f"{section}.", values, can_seal)

        def save() -> None:
            refusal = save_form(entries, values)
            if refusal:
                ui.notify(refusal, type="negative", multi_line=True)
                return
            ui.notify(tr("Saved to the database"), type="positive")
            ui.navigate.reload()

        im_button(tr("Save"), variant="secondary", on_click=save, icon="save")


def _section_of(entry: SettingSource) -> str:
    return entry.key.split(".")[0]


def render_config_viewer() -> None:
    """Every setting grouped by section, with its source; editable ones save to the database."""
    entries = describe_settings(get_config(reload=True))
    can_seal = secret_key_from_env() is not None

    im_info_card(
        tr(
            "Settings come from four places, strongest first: environment variables, "
            "config.yaml, what you save here (kept in the database), then the defaults. "
            "A greyed-out setting is set by the environment or config.yaml; change it there."
        ),
        variant="info",
    )
    if not can_seal:
        im_info_card(
            tr(
                "{name} is not set, so API keys and passwords cannot be saved here. "
                "Set it, or put those secrets in the environment or config.yaml.",
                name=SECRET_KEY_ENV,
            ),
            variant="warning",
        )

    for section, grouped in groupby(entries, key=_section_of):
        _render_section(section, list(grouped), can_seal)


def render_config_page() -> None:
    """Render the full config settings page."""
    im_section_header(tr("Active Configuration"), icon="description")
    render_config_viewer()

    im_section_header(tr("Actions"), icon="build")
    with ui.row().classes("gap-3"):

        def reload_config():
            get_config(reload=True)
            ui.notify(tr("Configuration reloaded from disk"), type="positive")
            ui.navigate.reload()

        im_button(
            tr("Reload from Disk"), variant="secondary", on_click=reload_config, icon="refresh"
        )

        config_path = get_config_path()
        ui.label(tr("Config file: {config_path}", config_path=config_path)).classes(
            "text-sm self-center"
        ).style("color: var(--im-text-secondary)")
