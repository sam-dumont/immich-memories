"""`generate --ask "<sentence>"`: a film asked for in a sentence (#1436, highly experimental).

The sentence is translated against the library before anything runs: the configured reader
reads it, code links it, and the pool of pictures that mean it is built from the store. The
trace is printed first and saved with the run. The film is then an ordinary `generate` run:
the pool filmed like an album whose written subject is the sentence, or a special day.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import click

from immich_memories.analysis.editorial_shareability import level_of
from immich_memories.api.access_clients import AccessBoundClient
from immich_memories.cli._album_generation import CuratedPool
from immich_memories.cli._helpers import print_info
from immich_memories.config_models import PRIMARY_ACCOUNT
from immich_memories.free_text.account_scope import (
    AccountScope,
    likely_household,
    resolve_account_scope,
    visible_pictures,
)
from immich_memories.free_text.handoff import CatalogueEvent, Film, film_for
from immich_memories.free_text.lexicon import WordNetUnavailable, load_wordnet
from immich_memories.free_text.library import (
    LibraryPerson,
    LibraryUnavailable,
    LibraryView,
    read_library,
)
from immich_memories.free_text.printed import ImmichPrintedText
from immich_memories.free_text.reading import WireAsker
from immich_memories.free_text.trace import explain, pool_counts, save_with_run, trace_record
from immich_memories.free_text.translate import household_of, translate
from immich_memories.security import write_secret_file

if TYPE_CHECKING:
    from immich_memories.api.sync_client import SyncImmichClient
    from immich_memories.config_loader import Config
    from immich_memories.db import Store
    from immich_memories.free_text.rule_preview import RulePreview


# `--ask` is the whole scope: the sentence says what, who, when and where.
_SCOPE_FLAGS = (
    "year",
    "start",
    "end",
    "period",
    "birthday",
    "from_album",
    "subject",
    "person",
    "person_expression",
    "memory_type",
    "holiday",
    "season",
    "month",
    "day",
    "event_id",
    "trip_index",
    "all_trips",
    "near_date",
    "years_back",
)


@dataclass(frozen=True)
class RunScope:
    """The scope `generate` resolves its run from; `--ask` puts its sentence's in its place."""

    memory_type: str | None = None
    day: date | None = None
    event_id: str | None = None
    # The pool route: filmed like an album of the pool, whose written subject is the sentence.
    from_album: str | None = None
    subject: str | None = None
    accept_any_provenance: bool = False
    curated: CuratedPool | None = None

    def fields(
        self,
    ) -> tuple[
        str | None, date | None, str | None, str | None, str | None, bool, CuratedPool | None
    ]:
        """The scope in `generate`'s order of assignment."""
        return (
            self.memory_type,
            self.day,
            self.event_id,
            self.from_album,
            self.subject,
            self.accept_any_provenance,
            self.curated,
        )


def scope_of_ask(
    ctx: click.Context,
    config: Config,
    request: str | None,
    *,
    dry_run: bool,
    typed: RunScope,
    trace_file: Path | None = None,
    accounts: Sequence[str] = (),
) -> RunScope:
    """The run's scope: as typed without `--ask`, else the one its sentence asks for.

    Flags the sentence already says are refused. A dry run, or a sentence the library
    cannot show, ends the command after the trace: there is nothing to film. `accounts` is
    the run's chosen household accounts (#2044): the pool only ever names a picture they
    can see; empty is the one-account run every `--ask` has been.
    """
    if request is None:
        return typed
    given = [
        f"--{name.replace('_', '-')}"
        for name in _SCOPE_FLAGS
        if ctx.get_parameter_source(name) is click.core.ParameterSource.COMMANDLINE
    ]
    if given:
        raise click.UsageError(f"--ask is the whole scope; drop {', '.join(given)}")
    film = translate_ask(config, request, dry_run=dry_run, trace_file=trace_file, accounts=accounts)
    if film is None:
        sys.exit(0)
    # A requested film keeps forwarded pictures: a club's photos arrive by group chat.
    if film.route == "special_day":
        return RunScope(
            memory_type="special_day",
            day=film.day,
            event_id=film.event_id,
            accept_any_provenance=True,
        )
    ref = "ask-" + hashlib.sha256(request.encode()).hexdigest()[:12]
    if film.window is None:
        raise click.ClickException("The pool holds no picture to film")
    pool = CuratedPool(name=request, ref=ref, asset_ids=film.asset_ids, window=film.window)
    return RunScope(from_album=ref, subject=film.subject, accept_any_provenance=True, curated=pool)


def translate_ask(
    config: Config,
    request: str,
    *,
    dry_run: bool,
    trace_file: Path | None = None,
    accounts: Sequence[str] = (),
) -> Film | None:
    """Translate the sentence and print its trace; the film to make, or None for no film.

    A dry run stops after the trace and the pool's counts. A request the library cannot
    show is no film, and the trace says why. `trace_file` keeps the same as JSON. `accounts`
    is the run's chosen household accounts (#2044): the pool, verdict, trace and rule
    preview only ever name a picture they can see; empty is the one-account run every
    `--ask` has been.
    """
    from immich_memories.db import open_store

    if config.tier != "full":
        raise click.UsageError(
            "--ask needs the model tier: set advanced.llm.base_url and advanced.llm.model "
            "to the reader that answers it (tier: full)"
        )
    try:
        lexicon = load_wordnet(config.free_text.wordnet_path)
        store = open_store(config)
        view = read_library(store, config.editorial)
    except (WordNetUnavailable, LibraryUnavailable) as error:
        raise click.ClickException(str(error)) from error
    if not view.pictures:
        raise click.ClickException(
            "The store holds no library to read: run immich-memories prepare first"
        )
    asker = WireAsker(config.llm, judgments=store)
    # A request naming no account still reads as the primary alone once a household run
    # (or native sharing) may have left another account's pictures in this store (#2044).
    scope_accounts = accounts or (
        (PRIMARY_ACCOUNT,)
        if likely_household(
            store,
            other_accounts=bool(config.immich.accounts),
            native_sharing=config.immich.native_sharing,
        )
        else ()
    )
    with _ask_client(config, scope_accounts) as client:
        scope = resolve_account_scope(client, scope_accounts, view.pictures, store)
        view = LibraryView(
            pictures=visible_pictures(view.pictures, scope),
            people=_scoped_people(view.people, scope),
            sharpness_line=view.sharpness_line,
            owner_id=view.owner_id,
        )
        asked = translate(
            request,
            view,
            household_of(view, home_base=_home_base(config)),
            lexicon,
            asker,
            today=date.today(),
            trips=config.trips,
            printed=ImmichPrintedText(client),
            face_accounts=scope.face_accounts,
            picture_accounts=scope.picture_accounts,
        )
        film = film_for(asked, asker, events_on=catalogue_events)
        # What the editor's rules would drop from the pool: shown by a dry run, and kept with a
        # film run so its report says which rules its pictures met.
        rules = _rule_preview(client, config, store, film)
    trace = explain(asked, film=film, rules=rules)
    click.echo(trace)
    # One record for the watcher's file and the run's report, so both show the same translation.
    record = trace_record(asked, film, rules)
    save_with_run(asked, film, trace, people=view.people, record=record)
    if trace_file is not None:
        write_secret_file(trace_file, json.dumps(record))
    if dry_run:
        counts = pool_counts(asked)
        print_info(
            f"Pool: {counts['pictures']} pictures ({counts['photos']} photos, "
            f"{counts['videos']} videos); dry run, nothing filmed"
        )
        return None
    if film.route == "none":
        print_info(f"Not possible, no film: {film.reason.outcome}")
        return None
    return film


def _rule_preview(
    client: SyncImmichClient, config: Config, store: Store, film: Film
) -> RulePreview | None:
    """The editor's rules asked about the pool before render, on the run's own source and lines.

    Only a pool is previewed: the special day reads its own day, and no film has no pool.
    """
    from immich_memories.analysis.editorial_runtime_evidence import AnnotationReadings
    from immich_memories.analysis.editorial_source import library_source_scope
    from immich_memories.analysis.thumbnail_prefetch import cached_preview_bytes
    from immich_memories.cache.thumbnail_cache import ThumbnailCache
    from immich_memories.cli._album_generation import pool_media
    from immich_memories.free_text.rule_preview import preview_rules
    from immich_memories.people.context import load_people_prompt_context

    if film.route != "pool" or film.window is None:
        return None
    media = pool_media(
        client,
        film.asset_ids,
        config,
        window=film.window,
        use_live_photos=config.analysis.include_live_photos,
        use_photos=config.photos.enabled,
    )
    if media.date_range is None:
        return None
    thumbnails = ThumbnailCache(
        cache_dir=config.cache.cache_path / "thumbnails",
        max_size_mb=config.cache.thumbnail_cache_max_size_mb,
    )
    sources = [*media.videos, *media.photos]
    return preview_rules(
        sources,
        # A pool picture Immich's timeline does not list never reaches the film.
        missing=sorted(set(film.asset_ids) - {source.id for source in sources}),
        # The film run's scope: `--ask` films keep forwarded pictures.
        scope=library_source_scope(client, config, (media.date_range,), accept_any_provenance=True),
        readings=AnnotationReadings(
            store=store, config=config, people=load_people_prompt_context(include_derived=True)
        ),
        audience=level_of(config.defaults.sharing),
        preview_jpeg=lambda asset: cached_preview_bytes(thumbnails, asset.id),
    )


def catalogue_events(day: date) -> list[CatalogueEvent]:
    """The occasions the special-days catalogue holds on a day."""
    from immich_memories.automation.catalogue import entries_from, load_catalogue

    return [
        CatalogueEvent(entry.event_id, entry.what or entry.title)
        for entry in entries_from(load_catalogue())
        if entry.day == day
    ]


def _home_base(config: Config) -> tuple[float, float] | None:
    trips = config.trips
    if trips.homebase_latitude == trips.homebase_longitude == 0.0:
        return None
    return trips.homebase_latitude, trips.homebase_longitude


def _ask_client(config: Config, accounts: Sequence[str]) -> SyncImmichClient:
    """The one-account client every `--ask` has used, or one that can open every account.

    `accounts` named (explicitly, or because the store might hold more than the primary's
    own pictures, #2044) needs an `AccessBoundClient` to read each one's own library, so
    the pool can be scoped to what they can see. Naming none keeps the plain client,
    unchanged.
    """
    from immich_memories.api.immich import SyncImmichClient

    if not accounts:
        return SyncImmichClient(
            base_url=config.immich.url,
            api_key=config.immich.api_key,
            api_version=config.immich.api_version,
        )
    return AccessBoundClient(config.immich)


def _scoped_people(
    people: Mapping[str, LibraryPerson], scope: AccountScope
) -> Mapping[str, LibraryPerson]:
    """`people` the asking accounts can name; every known person when `scope` names none.

    Outside a household run `scope.face_accounts` is empty and everybody the people file
    knows is nameable, as it always has been. In one, a person with no alias any chosen
    account can read is not linked or named in the trace at all (#2044): their pictures are
    already out of the pool, so showing them in WHO would just be a different leak.
    """
    if not scope.face_accounts:
        return people
    return {
        person_id: person
        for person_id, person in people.items()
        if person_id in scope.face_accounts
    }
