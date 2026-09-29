"""Local report assembly; callers receive the same sanitized object."""

from pathlib import Path

from immich_memories.db import Store
from immich_memories.people.account_ids import entry_ids
from immich_memories.people.companion import load_document, people_entries
from immich_memories.security import configured_secret_values
from immich_memories.tracking.report import RunReport, build_report
from immich_memories.tracking.report_privacy import ReportPrivacy
from immich_memories.tracking.run_database import RunDatabase
from immich_memories.tracking.span_store import SpanStore


def report_for_run(
    store: Store, config, run_id: str | None = None, *, include_flagged_captions: bool = False
) -> RunReport:
    """Resolve one run and its redaction vocabulary without network calls."""
    database = RunDatabase(store)
    if run_id is None:
        latest = database.list_runs(limit=1)
        run = latest[0] if latest else None
    else:
        run = database.get_run(run_id)
    if run is None:
        raise LookupError("No matching run. Generate or prepare a memory first.")
    spans = SpanStore(store)
    diagnostics = spans.diagnostics(run.run_id)
    terms = set(diagnostics.get("private_terms", []))
    terms.update(configured_secret_values(config))
    terms.update(filter(None, (run.person_name, run.output_path, run.delivery_album)))
    terms.update((str(Path.home()), str(config.output.output_path), str(config.cache.cache_path)))
    ids = set(diagnostics.get("private_ids", []))
    ids.update(filter(None, (run.run_id, run.person_id, run.immich_asset_id)))
    for person in people_entries(load_document(store)):
        ids.update(entry_ids(person))
        if person.get("name"):
            terms.add(person["name"])
    privacy = ReportPrivacy(terms=terms, ids=ids)
    return build_report(
        run,
        spans.load(run.run_id),
        privacy=privacy,
        diagnostics=diagnostics,
        include_flagged_captions=include_flagged_captions,
    )
