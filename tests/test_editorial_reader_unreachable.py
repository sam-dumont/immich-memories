"""A reader that stops answering leaves the film to the rules, as the docs promise.

docs: run/local-models.md and reference/troubleshooting.md, "Reader failure falls back to
rules and default wording rather than stopping the run", said in one line per endpoint.
"""

from __future__ import annotations

import json
import socket
from datetime import date

import pytest

from immich_memories.analysis.film.contract import StructurePlannerPorts
from immich_memories.analysis.judgments.text_failures import (
    ReaderUnreachable,
    StageCallFailure,
)
from immich_memories.analysis.judgments.text_judge import StructureTextJudge
from immich_memories.analysis.llm import query
from immich_memories.analysis.polish.layer import ThinPolish
from immich_memories.analysis.stories.rule_reader import RuleStructureReader
from immich_memories.analysis.structure.planner import plan_structure
from immich_memories.config.models.llm import LLMConfig
from tests.editorial_film_fixtures import FilmJudge, film_source, home_days, trip_days

MAY = (date(2030, 5, 1), date(2030, 5, 31))
ACCOUNT = "A month of ordinary days and one week away."
UNREACHABLE_LINE = "Reader unreachable at"


def _closed_port() -> int:
    """A loopback port nothing listens on: every connect is refused at once."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def dead_reader(monkeypatch):
    """# WHY: skip the transport retries' real waits; the refusals themselves stay real."""

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(query.asyncio, "sleep", no_wait)
    monkeypatch.setattr(query, "_WARNED_UNREACHABLE", set())
    return LLMConfig(
        enabled=True, base_url=f"http://127.0.0.1:{_closed_port()}/v1", model="model-a"
    )


def _film(tmp_path):
    days = [*home_days(date(2030, 5, 1), 4), *trip_days(date(2030, 5, 6), 6)]
    source = film_source(tmp_path, days, seconds=60, span=MAY, pictures=2)
    source.config.title_screens.llm_titles = True
    return source


def _thin_plan(source, judge):
    return plan_structure(
        source,
        StructurePlannerPorts(
            judge=judge,
            thumbnail_hash=lambda _asset: None,
            rules=RuleStructureReader(source),
            thin=ThinPolish(
                store=source.bank_store,
                bank_scope=source.case.key,
                read_period=lambda _stories: (ACCOUNT, {}),
            ),
        ),
    ).plan


def _nas_plan(source):
    return plan_structure(
        source,
        StructurePlannerPorts(
            judge=FilmJudge(), thumbnail_hash=lambda _asset: None, rules=RuleStructureReader(source)
        ),
    ).plan


def test_a_reader_that_never_answers_ships_the_rules_film_and_says_so_once(
    tmp_path, dead_reader, caplog
):
    source = _film(tmp_path)
    source.config.llm = dead_reader
    judge = StructureTextJudge(source.config, source.artifact_dir)

    with caplog.at_level("WARNING"):
        plan = _thin_plan(source, judge)

    nas = _nas_plan(_film(tmp_path / "nas"))
    assert [c["asset_id"] for c in plan["carriers"]] == [c["asset_id"] for c in nas["carriers"]]
    audit = json.loads(
        (source.artifact_dir / "derived-decisions/thin-polish.private.json").read_text()
    )
    assert audit["ran"] is False
    assert "unreachable" in audit["reason"]
    said = [r.message for r in caplog.records if r.message.startswith(UNREACHABLE_LINE)]
    assert len(said) == 1
    assert "falling back to rules and default wording" in said[0]


def test_once_the_reader_is_unreachable_the_run_stops_asking_it(tmp_path, dead_reader):
    source = _film(tmp_path)
    source.config.llm = dead_reader
    source.artifact_dir.mkdir(parents=True, exist_ok=True)
    judge = StructureTextJudge(source.config, source.artifact_dir)

    with pytest.raises(ReaderUnreachable):
        judge.ask("first", "a question")
    sent = len(judge.calls)
    with pytest.raises(ReaderUnreachable):
        judge.ask("second", "another question")

    # The second question is refused without another trip to a dead host, and is recorded.
    assert len(judge.calls) == sent + 1
    assert "unreachable" in judge.calls[-1]["warning"]


def test_a_rejected_key_is_not_an_unreachable_reader(tmp_path):
    """A 401 is configuration: loud, never a quiet rules film (llm/provider_failure.py)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 -- stdlib server interface
            body = json.dumps({"error": {"message": "invalid api key"}}).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        source = _film(tmp_path)
        source.config.llm = LLMConfig(
            enabled=True,
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            model="model-a",
            api_key="wrong",
        )
        source.artifact_dir.mkdir(parents=True, exist_ok=True)
        judge = StructureTextJudge(source.config, source.artifact_dir)
        with pytest.raises(StageCallFailure) as raised:
            judge.ask("first", "a question")
        assert not isinstance(raised.value, ReaderUnreachable)
    finally:
        server.shutdown()
        server.server_close()


def test_a_model_planned_film_whose_reader_is_gone_is_planned_again_by_the_rules(
    tmp_path, dead_reader
):
    """With the model planning the whole film there is no draft to keep: the rules plan it."""
    from datetime import timedelta

    from immich_memories.analysis.runtime.composition import (
        EditorialRunContext,
        build_editorial_planner,
    )
    from immich_memories.analysis.runtime.ports import EditorialRuntimePorts
    from immich_memories.analysis.runtime.smart_pipeline import SmartPipeline
    from immich_memories.analysis.sources.pool import EditorialSourcePool
    from immich_memories.cache.thumbnail_cache import ThumbnailCache
    from immich_memories.config.loader import Config
    from immich_memories.timeperiod import DateRange
    from tests.test_editorial_rule_reader import _distinct_preview
    from tests.test_editorial_runtime import _window
    from tests.test_editorial_source_route import photo

    first = _window(2024, 2, 1)
    window = DateRange(first.start, first.end + timedelta(days=27))
    sources = [photo(f"p-{n:02}", at=window.start + timedelta(days=n, hours=9)) for n in range(8)]
    config = Config(
        cache={"directory": str(tmp_path / "cache")},
        analysis={"min_source_short_side": 0},
        llm=dead_reader.model_dump(),
    )
    config.editorial.preparation.tier = "metadata_only"
    config.editorial.thin_model_layer = False
    config.editorial.reader = "model"
    readers = []

    def planner_seeing(source, ports):
        readers.append(source.config.editorial.resolve_reader(source.config.llm.model))
        return plan_structure(source, ports)

    planner = build_editorial_planner(
        source_pool=EditorialSourcePool(tuple(sources)),
        client=object(),
        config=config,
        thumbnail_cache=ThumbnailCache(tmp_path / "thumbnails"),
        context=EditorialRunContext(
            "gone", "February", "monthly_highlights", (window,), 60, tmp_path / "artifacts"
        ),
        ports=EditorialRuntimePorts(
            load_people=lambda: {},
            fetch_preview=lambda _client, key: _distinct_preview(key),
            structure_planner=planner_seeing,
        ),
    )
    clips, _result = SmartPipeline(planner=planner).run_editorial_source(
        sources, include_live_photos=True
    )

    assert readers == ["model", "rules"]
    assert clips
