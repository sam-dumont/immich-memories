"""A report is safe in every format, including logs and exception text."""

from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.report import build_report
from immich_memories.tracking.report_privacy import ReportPrivacy
from immich_memories.tracking.timing import Collector, Span


def test_private_fixture_has_no_names_paths_or_secrets_in_any_format():
    private = ["Marigold", "Family picnic", "Brookhaven", "/Users/example/Films", "secret-key-123"]
    asset_id = "fixture-asset-id"
    run = RunMetadata(
        "fixture-run-id",
        datetime.now(UTC),
        status="failed",
        person_name=private[0],
        output_path=private[3],
        delivery_album=private[1],
        warnings=[" ".join(private)],
    )
    collected = Collector(
        logs=[f"{asset_id} " + " ".join(private)],
        spans=[
            Span(
                1,
                "preparation.detectors",
                None,
                0,
                2,
                items=4,
                error={"type": "ValueError", "message": " ".join(private), "frames": []},
            )
        ],
    )
    privacy = ReportPrivacy(terms=private, ids=[asset_id, run.run_id])
    report = build_report(run, collected, privacy=privacy)
    with ZipFile(BytesIO(report.bundle())) as archive:
        bundled = "\n".join(archive.read(name).decode() for name in archive.namelist())
    for rendered in (report.markdown(), report.json(), bundled):
        assert not any(value in rendered for value in [*private, asset_id, run.run_id])
        assert privacy.hash_id(asset_id) in rendered
    assert privacy.hash_id(asset_id) != ReportPrivacy(ids=[asset_id]).hash_id(asset_id)
    assert "| Phase | Seconds | Items | s/item | s/output second |" in report.markdown()
    assert "| preparation.detectors | 2.000 | 4 | 0.500 |" in report.markdown()


def test_long_logs_stay_under_issue_limit_with_complete_details():
    run = RunMetadata("long-run", datetime.now(UTC))
    logs = [f"line {number}: " + "<private>" * 100 for number in range(5000)]
    report = build_report(run, Collector(logs=logs), privacy=ReportPrivacy())
    markdown = report.markdown()
    assert len(markdown) < 60_000
    assert markdown.count("<details>") == markdown.count("</details>")
    assert "Logs trimmed to the last" in markdown
    assert "line 4999:" in markdown
    assert len(report.data["logs"]) == 5000


def test_many_reader_calls_do_not_push_render_rates_out_of_the_report():
    spans = [Span(index, "reader.call", None, index, 1.0, items=1) for index in range(500)]
    spans.append(Span(501, "render.assembly", None, 500, 10.0, items=5))
    report = build_report(
        RunMetadata("large-run", datetime.now(UTC)), Collector(spans=spans), privacy=ReportPrivacy()
    )
    assert "| reader.call | 500.000 | 500 | 1.000 |" in report.markdown()
    assert "| render.assembly | 10.000 | 5 | 2.000 |" in report.markdown()


def test_cli_report_defaults_to_latest_failed_run(tmp_path):
    from click.testing import CliRunner

    from immich_memories.cli import main
    from immich_memories.tracking import RunTracker

    tracker = RunTracker(capture_system=False)
    tracker.start_run(source="prepare")
    tracker.fail_run("no model configured")
    result = CliRunner().invoke(
        main, ["report", "--json", "--bundle", str(tmp_path / "report.zip")]
    )
    assert result.exit_code == 0, result.output
    assert '"status": "failed"' in result.stdout
    assert tracker.run_id not in result.stdout
    assert (tmp_path / "report.zip").is_file()


def test_api_uses_the_same_builder_and_keeps_logs_private():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from immich_memories.config_loader import Config
    from immich_memories.tracking import RunTracker
    from immich_memories.tracking.report_api import report_config, router
    from immich_memories.tracking.span_store import SpanStore

    tracker = RunTracker(capture_system=False)
    tracker.start_run(person_name="Marigold")
    tracker.fail_run("Marigold is missing")
    SpanStore(tracker.db.store).save(tracker.run_id, Collector(logs=["Marigold missing"]))
    app = FastAPI()
    app.include_router(router)
    # WHY: supply isolated configuration instead of the developer's configuration file.
    app.dependency_overrides[report_config] = lambda: Config()
    response = TestClient(app).get(f"/api/v1/runs/{tracker.run_id}/report")
    assert response.status_code == 200
    assert "Marigold" not in response.text
    assert "Run logs (redacted)" in response.json()["markdown"]


def test_cli_json_stdout_excludes_startup_logs(monkeypatch):
    import json
    import logging

    from click.testing import CliRunner

    from immich_memories.cli import main
    from immich_memories.config_loader import Config
    from immich_memories.tracking import RunTracker

    tracker = RunTracker(capture_system=False)
    tracker.start_run()
    tracker.fail_run("fixture")

    def noisy_config():
        logging.getLogger("immich_memories.config").warning("startup diagnostic")
        return Config()

    # WHY: simulate startup logging at the config boundary without reading a user's config.
    monkeypatch.setattr("immich_memories.cli.get_config", noisy_config)
    result = CliRunner().invoke(main, ["report", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["run"]["status"] == "failed"
    assert "startup diagnostic" in result.stderr


def test_free_text_report_redacts_the_request_and_omits_captions_by_default():
    run = RunMetadata("request-run", datetime.now(UTC))
    diagnostics = {
        "free_text": {
            "request": "Marigold at Rose Cottage in Brookhaven with words SECRET SIGN",
            "spec": {"people": "Marigold", "where": "Rose Cottage", "subject": "building"},
            "funnel": {"pool": 30, "kept": 4},
            "flagged": [
                {
                    "asset_id": "private-shot",
                    "stage": "photo",
                    "reason": "Marigold builds",
                    "caption": "PRIVATE SCENE",
                }
            ],
            "missing": "Brookhaven",
            "privacy": {
                "people": {"Marigold": "son"},
                "homes": ["Rose Cottage"],
                "areas": ["Brookhaven"],
                "text": ["SECRET SIGN"],
            },
        }
    }
    report = build_report(run, Collector(), privacy=ReportPrivacy(), diagnostics=diagnostics)
    text = report.json()
    for value in (
        "Marigold",
        "Rose Cottage",
        "Brookhaven",
        "SECRET SIGN",
        "private-shot",
        "PRIVATE SCENE",
        "builds",
    ):
        assert value not in text
    assert "the owner's son" in text
    assert "home 1" in text
    assert "area A" in text
    assert "text-1" in text
    assert "id-" in text


def test_flagged_reasons_and_captions_come_only_with_the_opt_in():
    run = RunMetadata("request-run", datetime.now(UTC))
    flagged = {"asset_id": "shot", "stage": "photo", "reason": "why", "caption": "what"}
    diagnostics = {"free_text": {"request": "the beach", "flagged": [flagged]}}
    rows = {}
    for opted_in in (False, True):
        report = build_report(
            run,
            Collector(),
            privacy=ReportPrivacy(),
            diagnostics=diagnostics,
            include_flagged_captions=opted_in,
        )
        rows[opted_in] = report.data["free_text"]["flagged"][0]
    assert set(rows[False]) == {"asset_id", "stage"}
    assert rows[True]["reason"] == "why"
    assert rows[True]["caption"] == "what"


def test_geocoded_names_are_private_even_when_read_from_cache(tmp_path):
    from immich_memories.analysis.place_name_cache import PlaceNameCache
    from immich_memories.tracking import timing

    # WHY: replace the external geocoder; both calls use the real place-name cache.
    cache = PlaceNameCache(tmp_path, "en", lambda _lat, _lon: "Brookhaven, Testland")
    cache.name_for(1, 2, None)
    with timing.collecting() as collected:
        assert cache.name_for(1, 2, None) == "Brookhaven, Testland"
    report = build_report(
        RunMetadata("geo-run", datetime.now(UTC), warnings=["Brookhaven in Testland"]),
        collected,
        privacy=ReportPrivacy(terms=collected.private_terms),
    )
    assert "Brookhaven" not in report.json()
    assert "Testland" not in report.json()


def test_report_route_publishes_no_config_reload_parameter():
    from fastapi import FastAPI

    from immich_memories.tracking.report_api import router

    app = FastAPI()
    app.include_router(router)
    operation = app.openapi()["paths"]["/api/v1/runs/{run_id}/report"]["get"]
    assert {parameter["name"] for parameter in operation["parameters"]} == {
        "run_id",
        "include_flagged_captions",
    }
