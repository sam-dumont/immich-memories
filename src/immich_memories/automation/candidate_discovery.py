"""Turn one live Immich library snapshot into ranked memory candidates."""

from __future__ import annotations

import itertools
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol

from immich_memories.analysis.person_resolution import store_people
from immich_memories.api.accounts import AccountUnavailable, OpenAccount, open_accounts
from immich_memories.automation.calendar_detectors import birthday_film_windows
from immich_memories.automation.candidate_scorer import score_and_rank
from immich_memories.automation.candidates import (
    CandidateCategory,
    MemoryCandidate,
    completed_memory_key_aliases,
)
from immich_memories.automation.catalogue import entries_from, load_catalogue
from immich_memories.automation.closeness import closeness_by_person, is_close
from immich_memories.automation.discovery_extras import ExtraPlan, ExtraReads, read_account_extras
from immich_memories.automation.extra_detectors import run_extra_detectors
from immich_memories.automation.failure_backoff import drop_backed_off
from immich_memories.automation.group_candidates import GroupCandidateDetector
from immich_memories.automation.people_merge import (
    canonical_person_map,
    merge_counts,
    merge_people,
    overlay_birth_dates,
    store_birth_dates,
    sum_month_counts,
)
from immich_memories.automation.state_store import FailureStreak
from immich_memories.automation.trip_input_cache import load_or_fetch_trip_assets
from immich_memories.automation.variety import VarietyDecision, apply_variety_rules
from immich_memories.config_loader import Config
from immich_memories.config_models import PRIMARY_ACCOUNT
from immich_memories.config_models_automation import AutomationConfig
from immich_memories.db import open_store
from immich_memories.home_country import known_home_country
from immich_memories.people.companion import load_document
from immich_memories.people.context import load_people_prompt_context
from immich_memories.people.groups import SavedGroup, list_groups
from immich_memories.timeperiod import DateRange, same_day_in_year
from immich_memories.tracking.models import RunMetadata


class ImmichDiscoveryError(RuntimeError):
    """A live Immich library snapshot could not be collected."""


class MemoryHistoryReader(Protocol):
    """Small durable-history read seam required to avoid repeating a memory."""

    def get_generated_memory_keys(self) -> set[str]: ...

    def get_last_run_of_type(
        self,
        memory_type: str,
        source: str | None = None,
    ) -> RunMetadata | None: ...

    def get_last_run_of_category(
        self,
        memory_category: str,
        source: str | None = None,
    ) -> RunMetadata | None: ...


class FailureStreakReader(Protocol):
    """Small attempt-history read seam required by failure backoff."""

    def consecutive_failures_by_key(self) -> dict[str, FailureStreak]: ...


@dataclass(frozen=True)
class DiscoveryResult:
    """Ranked candidates plus the filtering decisions that produced them."""

    candidates: list[MemoryCandidate]
    variety_decision: VarietyDecision
    backoff_skips: dict[str, str]
    # Why a detector proposed nothing where it could have, for `auto suggest`.
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class _LibrarySnapshot:
    """One live Immich read shared by every detector in a discovery pass.

    Merged across every account discovery read (`automation.accounts`): the store's aliases
    fold two accounts' rosters and counts into one person, the way a household run does.
    """

    assets_by_month: dict[str, int]
    people: list
    # Per person, the pictures in the windows each person candidate's film will read:
    # last year for a spotlight, the birthday film's windows for a birthday (#2182).
    spotlight_counts: dict[str, int]
    birthday_counts: dict[str, int]
    # Pairs (canonical ids, sorted) to the pictures holding both in last year, and each
    # saved-group member to theirs: what multi_person and group films would read.
    shared_counts: dict[tuple[str, str], int]
    group_counts: dict[str, int]
    groups: list[SavedGroup]
    gps_assets: list | None
    extras: ExtraReads = field(default_factory=ExtraReads)


def _time_buckets_to_month_counts(
    buckets: list,
) -> dict[str, int]:
    """Convert Immich TimeBucket list to {YYYY-MM: count} dict."""
    result: dict[str, int] = {}
    for bucket in buckets:
        try:
            dt = datetime.fromisoformat(bucket.time_bucket)
            key = f"{dt.year}-{dt.month:02d}"
            result[key] = bucket.count
        except (ValueError, AttributeError):
            continue
    return result


def _trailing_year_range(today: date) -> DateRange:
    """Return one inclusive calendar-year lookback ending on ``today``."""
    try:
        start_day = today.replace(year=today.year - 1)
    except ValueError:
        # February 29 has no same-day counterpart in a non-leap year.
        start_day = today.replace(year=today.year - 1, day=28)

    return DateRange(
        start=datetime.combine(start_day, datetime.min.time()),
        end=datetime.combine(today, datetime.max.time()),
    )


def _build_last_runs_by_type(db: MemoryHistoryReader) -> dict[str, date]:
    """Query DB for the most recent completed run date per memory type."""
    result: dict[str, date] = {}
    for mem_type in (
        "monthly_highlights",
        "year_in_review",
        "person_spotlight",
        "trip",
        "multi_person",
        "special_day",
        "season",
        "holiday",
        "album",
    ):
        run = db.get_last_run_of_type(mem_type, source="auto")
        if run and run.created_at:
            result[mem_type] = (run.completed_at or run.created_at).date()
    # Backfill and the per-person months render as monthly_highlights: only the category
    # keeps their cooldown apart from the monthly's.
    for mem_type, category in (
        ("monthly_backfill", "backfill"),
        ("person_monthly", "person_monthly"),
    ):
        run = db.get_last_run_of_category(category, source="auto")
        if run and run.created_at:
            result[mem_type] = (run.completed_at or run.created_at).date()
    return result


def _compute_upcoming_birthday_ids(people: list, today: date, lookahead_days: int = 7) -> set[str]:
    """Return person IDs whose birthday falls within the next N days."""
    ids: set[str] = set()
    for person in people:
        if not getattr(person, "birth_date", None):
            continue
        bday = person.birth_date
        next_bday = same_day_in_year(bday, today.year)
        if next_bday < today:
            next_bday = same_day_in_year(bday, today.year + 1)
        days_until = (next_bday - today).days
        if 0 <= days_until <= lookahead_days:
            ids.add(person.id)
    return ids


def _run_all_detectors(
    auto_cfg: AutomationConfig,
    assets_by_month: dict[str, int],
    people: list,
    generated_keys: set[str],
    config: Config,
    today: date,
    spotlight_counts: dict[str, int],
    birthday_counts: dict[str, int],
    shared_counts: dict[tuple[str, str], int],
    group_counts: dict[str, int],
    gps_assets: list | None,
    catalogue: list | None,
    groups: list[SavedGroup],
    extras: ExtraReads | None = None,
    notes: list[str] | None = None,
) -> list[MemoryCandidate]:
    """Run all enabled detectors and collect candidates.

    ``extras`` are the reads behind the season, holiday, album, backfill and per-person month
    detectors and the closeness weights; without them those detectors stay out. Reasons a
    detector proposed nothing are appended to ``notes``.
    """
    from immich_memories.automation.calendar_detectors import (
        BirthdayDetector,
        MonthlyDetector,
        OnThisDayDetector,
        PersonSpotlightDetector,
        YearlyDetector,
    )
    from immich_memories.automation.event_detectors import (
        ActivityBurstDetector,
        MultiPersonDetector,
        TripDetector,
    )
    from immich_memories.automation.special_day_detector import SpecialDayDetector

    all_candidates: list[MemoryCandidate] = []
    closeness = extras.closeness if extras else None
    notes = notes if notes is not None else []

    if auto_cfg.detect_monthly:
        all_candidates.extend(
            MonthlyDetector().detect(
                assets_by_month, people, generated_keys, config, today, notes=notes
            )
        )
    if auto_cfg.detect_yearly:
        all_candidates.extend(
            YearlyDetector().detect(
                assets_by_month, people, generated_keys, config, today, notes=notes
            )
        )
    if auto_cfg.detect_person_spotlight:
        # WHY: suppress spotlights for people whose birthday is within 7 days
        # so BirthdayDetector fires at the right time instead
        upcoming_birthday_ids = _compute_upcoming_birthday_ids(people, today)
        all_candidates.extend(
            PersonSpotlightDetector().detect(
                assets_by_month,
                people,
                generated_keys,
                config,
                today,
                person_asset_counts=spotlight_counts,
                upcoming_birthday_ids=upcoming_birthday_ids,
                closeness=closeness,
                notes=notes,
            )
        )
        all_candidates.extend(
            MultiPersonDetector().detect(
                assets_by_month,
                people,
                generated_keys,
                config,
                today,
                person_asset_counts=spotlight_counts,
                shared_counts=shared_counts,
                closeness=closeness,
                notes=notes,
            )
        )
    if auto_cfg.detect_activity_burst:
        all_candidates.extend(
            ActivityBurstDetector().detect(
                assets_by_month,
                people,
                generated_keys,
                config,
                today,
                burst_threshold=auto_cfg.burst_threshold,
                notes=notes,
            )
        )

    all_candidates.extend(
        OnThisDayDetector().detect(
            assets_by_month, people, generated_keys, config, today, notes=notes
        )
    )

    # Birthday detector — always on, high priority near birthdays
    all_candidates.extend(
        BirthdayDetector().detect(
            assets_by_month,
            people,
            generated_keys,
            config,
            today,
            person_asset_counts=birthday_counts,
            closeness=closeness,
            busiest_count=max(spotlight_counts.values(), default=0),
            distinct_days={k: len(v) for k, v in extras.birthday_days.items()} if extras else None,
            notes=notes,
        )
    )

    if auto_cfg.detect_trips:
        all_candidates.extend(
            TripDetector().detect(
                assets_by_month,
                people,
                generated_keys,
                config,
                today,
                assets=gps_assets,
                notes=notes,
            )
        )

    all_candidates.extend(
        SpecialDayDetector().detect(
            assets_by_month,
            people,
            generated_keys,
            config,
            today,
            catalogue=catalogue,
            notes=notes,
        )
    )

    if auto_cfg.detect_groups:
        all_candidates.extend(
            GroupCandidateDetector().detect(
                assets_by_month,
                people,
                generated_keys,
                config,
                today,
                groups=groups,
                person_asset_counts=group_counts,
                closeness=closeness,
                notes=notes,
            )
        )

    if extras is not None:
        found = run_extra_detectors(
            auto_cfg,
            extras,
            hemisphere=config.trips.hemisphere,
            people=people,
            assets_by_month=assets_by_month,
            generated_keys=generated_keys,
            proposed=all_candidates,
            today=today,
        )
        all_candidates.extend(found.candidates)
        notes.extend(found.notes)

    return all_candidates


class CandidateDiscovery:
    """Detect, filter, score, and rank memory candidates for one library snapshot."""

    def __init__(
        self,
        config: Config,
        runs: MemoryHistoryReader,
        attempts: FailureStreakReader,
    ) -> None:
        self._config = config
        self._runs = runs
        self._attempts = attempts

    def discover(
        self,
        *,
        limit: int | None,
        recent_auto_runs: list[RunMetadata],
    ) -> DiscoveryResult:
        """Detect, score, and rank memory candidates from the Immich library."""
        auto_cfg = self._config.automation
        generated_keys = completed_memory_key_aliases(self._runs.get_generated_memory_keys())
        last_runs = _build_last_runs_by_type(self._runs)
        today = date.today()

        store = open_store(self._config)
        snapshot = self._library_snapshot(auto_cfg, today, store, generated_keys)
        notes: list[str] = []

        all_candidates = _run_all_detectors(
            auto_cfg,
            snapshot.assets_by_month,
            snapshot.people,
            generated_keys,
            self._config,
            today,
            snapshot.spotlight_counts,
            snapshot.birthday_counts,
            snapshot.shared_counts,
            snapshot.group_counts,
            snapshot.gps_assets,
            # Read here rather than in _LibrarySnapshot: that exists to bundle
            # the live Immich reads into one session, and this is the store.
            entries_from(load_catalogue(store)),
            snapshot.groups,
            snapshot.extras,
            notes,
        )

        all_candidates, backoff_skips = drop_backed_off(
            all_candidates,
            self._attempts.consecutive_failures_by_key(),
            datetime.now(tz=UTC),
        )

        variety_decision = apply_variety_rules(
            all_candidates,
            recent_auto_runs,
            today,
        )
        ranked = score_and_rank(
            variety_decision.eligible,
            generated_keys,
            today,
            last_runs,
        )
        _attach_accounts(ranked, tuple(auto_cfg.accounts))
        return DiscoveryResult(
            candidates=ranked[:limit],
            variety_decision=variety_decision,
            backoff_skips=backoff_skips,
            notes=tuple(dict.fromkeys([*snapshot.extras.notes, *notes])),
        )

    def _library_snapshot(
        self,
        auto_cfg: AutomationConfig,
        today: date,
        store: Any,
        generated_keys: Collection[str] = (),
    ) -> _LibrarySnapshot:
        """Collect every selected account's read in one session (#1500 slice 10).

        `automation.accounts` reads those accounts the way a household run does
        (`analysis/household_source.py`): each is proven with `/users/me` first, and a
        read that fails on any of them fails discovery, naming the account. Empty reads
        the primary account alone, exactly as before this setting existed.
        """
        document = load_document(store)
        groups = list_groups(store) if auto_cfg.detect_groups else []
        canon = canonical_person_map(store_people(document))
        accounts = tuple(auto_cfg.accounts) or (PRIMARY_ACCOUNT,)
        contexts = load_people_prompt_context(store)
        store_dates = store_birth_dates(document)
        plan = ExtraPlan(
            auto_cfg=auto_cfg,
            today=today,
            hemisphere=self._config.trips.hemisphere,
            # Once per discovery: Immich is asked where the home base is, not once per holiday.
            country=known_home_country(self._config) if auto_cfg.detect_holidays else None,
            generated_keys=generated_keys,
            canon=canon,
            close_ids={pid for pid, context in contexts.items() if is_close(context)},
            birth_dates=lambda account, people: _birth_dates(account, people, canon, store_dates),
        )
        extras = ExtraReads(
            closeness=closeness_by_person(contexts), close_ids=plan.close_ids, country=plan.country
        )

        try:
            opened = open_accounts(self._config.immich, accounts)
        except AccountUnavailable as exc:
            raise ImmichDiscoveryError(str(exc)) from exc

        try:
            if self._config.immich.native_sharing:
                from immich_memories.api.native_sharing import discover_native_people

                connections = {PRIMARY_ACCOUNT: self._config.immich} | self._config.immich.accounts
                native = discover_native_people(
                    opened,
                    binding_servers={
                        name: connection.url.rstrip("/") for name, connection in connections.items()
                    },
                )
                canon.update(canonical_person_map(store_people(document), native=native))
            reads = self._read_every_account(
                opened, auto_cfg, today, canon, store_dates, groups, plan, extras
            )
        except Exception as exc:
            # Broad on purpose, as this replaces: any transport fault ends discovery,
            # whichever account it came from.
            raise ImmichDiscoveryError(str(exc)) from exc
        finally:
            for account in opened.values():
                account.client.close()

        people = overlay_birth_dates(
            merge_people({n: r.people for n, r in reads.per_account.items()}, canon),
            store_birth_dates(document),
        )
        return _LibrarySnapshot(
            sum_month_counts({n: r.months for n, r in reads.per_account.items()}),
            people,
            merge_counts({n: r.spotlight for n, r in reads.per_account.items()}, canon),
            merge_counts({n: r.birthday for n, r in reads.per_account.items()}, canon),
            _summed(r.shared for r in reads.per_account.values()),
            _summed(r.leaves for r in reads.per_account.values()),
            groups,
            reads.gps_assets,
            extras,
        )

    def _read_every_account(
        self,
        opened: dict[str, OpenAccount],
        auto_cfg: AutomationConfig,
        today: date,
        canon: dict[tuple[str, str], str],
        store_dates: dict[str, date],
        groups: list[SavedGroup],
        plan: ExtraPlan,
        extras: ExtraReads,
    ) -> _AccountReads:
        """Every opened account's raw reads, kept separate so the caller can merge them."""
        per_account: dict[str, _AccountRead] = {}
        gps_assets: list | None = None
        for name, account in opened.items():
            client = account.client
            owner_id = account.user.id if self._config.immich.native_sharing else None
            buckets = client.get_time_buckets()
            read = _AccountRead(months=_time_buckets_to_month_counts(buckets))
            wants_people = auto_cfg.detect_person_spotlight or auto_cfg.detect_groups
            if wants_people or auto_cfg.detect_person_monthly:
                read.people = client.get_all_people()
                read.spotlight = _spotlight_window_counts(
                    client, read.people, today, owner_id=owner_id
                )
                read.shared = _shared_window_counts(
                    client, name, read.spotlight, canon, today, owner_id=owner_id
                )
                read.leaves = _group_leaf_counts(
                    client, name, groups, canon, today, owner_id=owner_id
                )
                read.birthday = _birthday_window_counts(
                    client,
                    read.people,
                    today,
                    _birth_dates(name, read.people, canon, store_dates),
                    owner_id=owner_id,
                )
            read_account_extras(
                client,
                name,
                account.user.id,
                read.people,
                read.birthday,
                plan,
                name == PRIMARY_ACCOUNT,
                extras,
            )
            per_account[name] = read
            # Trips stay primary-account only: --accounts refuses trip memories
            # (cli/run_people.py::refuse_household_scope), so discovery never scopes one.
            if auto_cfg.detect_trips and name == PRIMARY_ACCOUNT and gps_assets is None:
                gps_assets = self._trip_assets(client, buckets, today)
        return _AccountReads(per_account, gps_assets)

    def _trip_assets(self, client: Any, buckets: list, today: date) -> list | None:
        """Trips are measured against a homebase; without one there is nothing to measure."""
        trips_cfg = self._config.trips
        if trips_cfg.homebase_latitude == trips_cfg.homebase_longitude == 0.0:
            return None
        return load_or_fetch_trip_assets(
            client,
            cache_root=self._config.cache.cache_path,
            server_url=self._config.immich.url,
            buckets=buckets,
            requested_range=_trailing_year_range(today),
            now=datetime.now(tz=UTC),
        )


@dataclass
class _AccountRead:
    """What one account's Immich returned, before accounts are merged."""

    months: dict[str, int]
    people: list = field(default_factory=list)
    spotlight: dict[str, int] = field(default_factory=dict)
    birthday: dict[str, int] = field(default_factory=dict)
    shared: dict[Any, int] = field(default_factory=dict)
    leaves: dict[Any, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _AccountReads:
    per_account: dict[str, _AccountRead]
    gps_assets: list | None


def _pictures_in(
    client: Any,
    person_ids: list[str],
    windows: list[DateRange],
    *,
    owner_id: str | None = None,
) -> int:
    """How many pictures Immich holds of all these people together across these windows."""
    scope = {"owner_id": owner_id} if owner_id else {}
    return sum(
        client.count_assets_with_people(
            person_ids, taken_after=w.start, taken_before=w.end, **scope
        )
        for w in windows
    )


def _spotlight_window_counts(
    client: Any,
    people: list,
    today: date,
    *,
    owner_id: str | None = None,
) -> dict[str, int]:
    """Pictures last year, the one window a spotlight film reads, for the top named people."""
    year = today.year - 1
    window = DateRange(start=datetime(year, 1, 1), end=datetime(year, 12, 31, 23, 59, 59))
    named = [p for p in people if p.name and p.thumbnail_path][:10]
    return {p.id: _pictures_in(client, [p.id], [window], owner_id=owner_id) for p in named}


def _birthday_window_counts(
    client: Any,
    people: list,
    today: date,
    birth_dates: dict[str, date],
    *,
    owner_id: str | None = None,
) -> dict[str, int]:
    """Pictures in the film windows of everyone whose birthday is being proposed today."""
    counts: dict[str, int] = {}
    for person in people:
        bday = birth_dates.get(person.id)
        windows = birthday_film_windows(bday, today) if person.name and bday else None
        if windows:
            counts[person.id] = _pictures_in(client, [person.id], windows, owner_id=owner_id)
    return counts


def _birth_dates(
    account: str,
    people: list,
    canon: dict[tuple[str, str], str],
    store_dates: dict[str, date],
) -> dict[str, date]:
    """Each account-local person id to the birth date the detector will see (store wins)."""
    result: dict[str, date] = {}
    for person in people:
        stored = store_dates.get(canon.get((account, person.id), person.id))
        own = getattr(person, "birth_date", None)
        chosen = stored or (own.date() if isinstance(own, datetime) else own)
        if chosen:
            result[person.id] = chosen
    return result


def _last_year(today: date) -> DateRange:
    year = today.year - 1
    return DateRange(start=datetime(year, 1, 1), end=datetime(year, 12, 31, 23, 59, 59))


def _shared_window_counts(
    client: Any,
    account: str,
    spotlight: dict[str, int],
    canon: dict[tuple[str, str], str],
    today: date,
    *,
    owner_id: str | None = None,
) -> dict[tuple[str, str], int]:
    """Pictures holding both people of a pair last year (statistics' personIds is an AND)."""
    window = [_last_year(today)]
    present = [pid for pid, count in spotlight.items() if count > 0]
    result: dict[tuple[str, str], int] = {}
    for one, other in itertools.combinations(present, 2):
        first, second = sorted((canon.get((account, one), one), canon.get((account, other), other)))
        key = (first, second)
        result[key] = result.get(key, 0) + _pictures_in(
            client, [one, other], window, owner_id=owner_id
        )
    return result


def _group_leaf_counts(
    client: Any,
    account: str,
    groups: list[SavedGroup],
    canon: dict[tuple[str, str], str],
    today: date,
    *,
    owner_id: str | None = None,
) -> dict[str, int]:
    """Last year's pictures of every person a saved group names, by canonical id."""
    window = [_last_year(today)]
    leaves = {leaf for group in groups for leaf in group.expression.leaf_values}
    local_ids: dict[str, set[str]] = {leaf: {leaf} for leaf in leaves}
    for (acc, face), canonical in canon.items():
        if acc == account and canonical in leaves:
            local_ids[canonical].add(face)
    return {
        leaf: sum(_pictures_in(client, [pid], window, owner_id=owner_id) for pid in ids)
        for leaf, ids in local_ids.items()
    }


def _summed(per_account: Any) -> dict[Any, int]:
    result: dict[Any, int] = {}
    for counts in per_account:
        for key, count in counts.items():
            result[key] = result.get(key, 0) + count
    return result


def _attach_accounts(candidates: list[MemoryCandidate], accounts: tuple[str, ...]) -> None:
    """Every ranked candidate carries the run's account scope, so its generate call reads
    the same accounts discovery did — except a trip, which reads the primary alone."""
    if not accounts:
        return
    for candidate in candidates:
        if candidate.category not in (CandidateCategory.TRIP, CandidateCategory.ALBUM):
            candidate.extra_params["accounts"] = list(accounts)
