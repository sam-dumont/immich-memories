"""Read capture facts into stories, using the existing story weight floors."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from operator import itemgetter
from statistics import median
from typing import Any

import numpy as np

from immich_memories.analysis.editorial_clip_frames import CLIP_FRAMES_HEAD, SUBJECT_OFTEN_MISSING
from immich_memories.analysis.editorial_event_story import (
    EpisodeShape,
    PrintedNear,
    episode_shapes,
    split_events,
)
from immich_memories.analysis.editorial_home_radius import home_of, near_home_of
from immich_memories.analysis.editorial_rule_episodes import RULES_VERSION
from immich_memories.analysis.editorial_rule_quality import quality_facts, quality_key
from immich_memories.analysis.editorial_same_kind import EpisodeKind, same_kind_threads
from immich_memories.analysis.editorial_shareability import (
    SHAREABLE,
    never_auto_ids,
    owner_cleared_ids,
)
from immich_memories.analysis.editorial_shareability_audience import exposure_flagged
from immich_memories.analysis.editorial_standing_facts import (
    carries_nothing,
    face_evidence,
    shows_only_a_body_part,
)
from immich_memories.analysis.editorial_story_reading import (
    PeriodStory,
    StoryEpisode,
    _same_episode_day,
)
from immich_memories.analysis.editorial_story_replies import (
    WEIGHT_ROLE,
    film_close_family,
    relations_on,
)
from immich_memories.analysis.editorial_story_shortlist import _spread
from immich_memories.analysis.editorial_story_slots import weight_caps
from immich_memories.analysis.editorial_story_weighing import (
    _FAMILY_WORD,
    _floor_weights,
    consecutive_runs,
)
from immich_memories.analysis.editorial_structure_budget import NOMINAL_STILL_SECONDS
from immich_memories.analysis.place_names import shown_city
from immich_memories.analysis.trip_legs import legs_of_days

# The place labels of the shipped head bundle the standing rule reads. A picture is in a
# private or utility interior, or in a public place; every other venue label says nothing.
PRIVATE_VENUES = frozenset({"bedroom", "medical", "private_facility"})
PUBLIC_VENUES = frozenset({"water"})
OUTDOOR_LOCATION = "outdoor"
# Owner ruling 2026-10-04 (option a): when at least this share of a household's at-home
# weeks carry no occasion indicator at all, BASIC funds them from their own best picture
# instead of going short. Below this share the 2026-09-23 rule stands: an indicator-less
# week among mostly-indicated ones still goes short.
SPARSE_NONE_SHARE = 2 / 3


def _calendar_week(day: str) -> tuple[int, int] | tuple[()]:
    """The ISO (year, week) of a day episode; empty when the episode has no dated unit."""
    try:
        return date.fromisoformat(day[:10]).isocalendar()[:2]
    except ValueError:
        return ()


class NoModelJudge:
    """Guard the inference boundary; rules never answer serialized prompts."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def ask(self, *args, **kwargs) -> str:
        raise RuntimeError("rules reader reached a model-only decision")

    def record_failure(self, stage: str, record: Mapping[str, Any]) -> None:
        """Rules answer nothing, so nothing can fail to parse; keep any claim visible anyway."""
        self.calls.append({"stage": stage, "failure": dict(record)})


class RuleStructureReader:
    def __init__(
        self,
        source,
        *,
        printed: PrintedNear | None = None,
        promote_sparse_quality: bool = True,
    ) -> None:
        self.source = source
        self._face: Callable[[str], bool | None] | None = None
        # Immich's OCR over the screens and documents near a moment, when the run can reach it.
        self._printed = printed
        # False for the draft a thin model layer polishes (#2048 review, point C): the
        # owner's ruling is BASIC-only, and the model tier may still read a bare week itself.
        self._promote_sparse_quality_enabled = promote_sparse_quality

    def _day_threshold(self) -> float:
        """A day at least this dense is an occasion by its capture count alone."""
        days = Counter(a.file_created_at.date() for a in self.source.assets.values())
        masses = list(days.values())
        return max(4 * median(masses), float(np.percentile(masses, 75)))

    def worthiness(self, wall, near_home):
        assets = self.source.assets
        days = Counter(a.file_created_at.date() for a in assets.values())
        threshold = self._day_threshold()
        cities = Counter(self._city(a) for a in assets.values() if self._city(a))
        usual = {city for city, _ in cities.most_common(12)}
        required = self._required_families(wall)
        votes = {
            family: self._vote(
                [assets[a] for a in wall.event_assets[family]],
                days=days,
                threshold=threshold,
                usual=usual,
                away=near_home(family) is False,
                required=family in required,
            )
            for family in wall.fam_ids
        }
        return {f: v[0] for f, v in votes.items()}, {f: v[1] for f, v in votes.items()}

    def _required_families(self, wall) -> set[str]:
        families: dict[str, set[str]] = {}
        for family in wall.fam_ids:
            for asset_id in wall.event_assets[family]:
                day = self.source.assets[asset_id].file_created_at.date()
                part = self.source.intent.partition_for(day)
                if part is not None and part.required:
                    families.setdefault(part.key, set()).add(family)
        return {next(iter(values)) for values in families.values() if len(values) == 1}

    def _vote(self, members, *, days, threshold, usual, away, required):
        if self.source.intent.product == "album":
            return 0, "Owner chose this album as the memory's source"
        if any(days[a.file_created_at.date()] >= threshold for a in members):
            return 0, "Capture count at least four times the median photographed day"
        city = self._dominant_city(members)
        if away or city and city not in usual:
            return 0, "Outside home radius or the twelve usual cities"
        return self._indicator(members, required=required)

    def _indicator(self, members, *, required):
        if any(a.is_favorite for a in members):
            return 1, "Owner favourite present"
        relations = (
            rel for a in members for rel in relations_on(self.source.annotations.get(a.id, ""))
        )
        if any(_FAMILY_WORD.search(rel) for rel in relations):
            return 1, "Close family recorded in people metadata"
        if any(a.is_video for a in members):
            return 1, "Recorded video present"
        if required:
            return 1, "Only happening in a required partition"
        return 2, "No occasion indicator in available facts"

    def _dominant_city(self, members) -> str:
        cities = Counter(self._city(a) for a in members if self._city(a))
        return cities.most_common(1)[0][0] if cities else ""

    @staticmethod
    def _city(asset) -> str:
        return (asset.exif_info.city or "") if asset.exif_info else ""

    def _activity(self, members) -> str:
        activities = Counter(
            label
            for a in members
            if (record := self.source.audience_annotations.get(a.id))
            for head, label in record.heads
            if head == "activity" and label != "other"
        )
        return activities.most_common(1)[0][0] if activities else ""

    def _title(self, members) -> str:
        # The title is read by a viewer: the shown place, not the city the usual-city vote uses.
        cities = Counter(shown for a in members if (shown := shown_city(a.exif_info)))
        city = cities.most_common(1)[0][0] if cities else ""
        activity = self._activity(members)
        return (
            f"{activity} at {city}"
            if activity and city
            else city or activity or f"{members[0].file_created_at:%Y-%m-%d}"
        )

    def _day_chunks(self):
        groups = []
        for moment, ids in self.source.moment_asset_ids.items():
            # A people condition can leave a moment with nothing selectable (#1954); it
            # contributes no day, chunk or title, never an IndexError on `members[0]`.
            if not ids:
                continue
            members = sorted((self.source.assets[a] for a in ids), key=lambda a: a.file_created_at)
            groups.append((members[0].file_created_at.isoformat(), moment, members))
        groups.sort(key=itemgetter(0, 1))
        chunks: list[list] = []
        for row in groups:
            if chunks:
                first, last = chunks[-1][0], chunks[-1][-1]
                gap = (
                    datetime.fromisoformat(row[0]) - datetime.fromisoformat(last[0])
                ).total_seconds()
                changed = self._city(row[2][0]) != self._city(last[2][0])
                joins = _same_episode_day(row[0], first[0], last[0]) and not (
                    gap > 5400 and changed
                )
            else:
                joins = False
            if joins:
                chunks[-1].append(row)
            else:
                chunks.append([row])
        return chunks

    def _day_episodes(self, evidence):
        episodes = []
        for index, chunk in enumerate(self._day_chunks(), 1):
            members = [a for row in chunk for a in row[2]]
            moments = [row[1] for row in chunk]
            covered = set(moments)
            observations = [
                o
                for row in evidence
                if covered.intersection(row["moments"])
                for o in row.get("observations", ())
            ]
            account = " ".join("; ".join(observations).split()[:60])
            episodes.append(
                StoryEpisode(
                    f"R{index:03}",
                    self._title(members),
                    account,
                    "",
                    "supporting",
                    "",
                    moments=moments,
                )
            )
        return episodes

    def _away_from_home(self, episode) -> bool | None:
        points = [
            self.source.gps.get(asset_id)
            for moment in episode.moments
            for asset_id in self.source.moment_asset_ids.get(moment, ())
        ]
        near = near_home_of(home_of(self.source.config.trips), points)
        return None if near is None else not near

    def _runs(self, episodes, hints) -> list[list[str]]:
        """Consecutive photographed days, cut into stories a film can spend a grant on.

        A stretch away from home stays whole however long it lasts, because a trip is one
        story, and a day at home ends it: two trips either side of a week at home are two
        stories, not one. The one cut inside it is a change of where it stays: a hike then a
        city stay is two legs, each its own story (`trip_legs`, #1563). A run at home is cut on the calendar week; without that, a
        densely photographed year merges into a single 129-day story whose grant is spent
        on its first week and whose remaining months never come into view. A day whose
        pictures say nothing about where they were does not end a trip.
        """
        away_of = {e.key: self._away_from_home(e) for e in episodes}
        runs: list[list[str]] = []
        for keys in consecutive_runs({e.key: e for e in episodes}, lambda key: hints[key]["day"]):
            chunks: dict[tuple, list[str]] = {}
            dated = next((w for k in keys if (w := _calendar_week(hints[k]["day"]))), ())
            away, was_away, trips = False, False, 0
            for key in keys:
                known = away_of[key]
                if known is not None:
                    away = known
                trips += away and not was_away
                was_away = away
                week = _calendar_week(hints[key]["day"]) or dated
                chunks.setdefault((True, trips) if away else (False, week), []).append(key)
            for (away_run, _), chunk in chunks.items():
                runs.extend(self._legs(chunk, episodes, hints) if away_run else [chunk])
        return runs

    def _legs(self, keys: list[str], episodes, hints) -> list[list[str]]:
        moments_of = {e.key: e.moments for e in episodes}
        points: dict[str, list[tuple[float, float]]] = {}
        for key in keys:
            day = str(hints[key]["day"])
            points.setdefault(day, []).extend(
                point
                for moment in moments_of[key]
                for asset_id in self.source.moment_asset_ids.get(moment, ())
                if (point := self.source.gps.get(asset_id)) is not None
            )
        leg_of = legs_of_days(points)
        legs: dict[int, list[str]] = {}
        for key in keys:
            legs.setdefault(leg_of[str(hints[key]["day"])], []).append(key)
        return list(legs.values())

    def _stories(self, episodes, hints):
        by_key = {e.key: e for e in episodes}
        stories = []
        for index, keys in enumerate(self._runs(episodes, hints), 1):
            relations: Counter[str] = Counter()
            for key in keys:
                relations.update(hints[key].get("relations", {}))
            gate = min(
                (hints[k].get("gate", "background") for k in keys),
                key=("remarkable", "maybe", "background").index,
            )
            stories.append(
                {
                    "key": f"S{index:03}",
                    "episodes": keys,
                    "title": " / ".join(dict.fromkeys(by_key[k].title for k in keys)),
                    "purpose": "Capture dates, places and owner favourites",
                    "weight": "",
                    "gate": gate,
                    "people_counts": dict(relations),
                    "seen": {
                        field: sum(hints[k].get(field, 0) for k in keys)
                        for field in ("moments", "pictures", "favourites")
                    },
                }
            )
        return stories

    def _big_stories(self, stories, episodes) -> list[dict[str, Any]]:
        """Mark the stories that are unusually dense AND mostly close family.

        Only those may be floored to major without three favourites: a dense day of strangers
        (a race, a fair) has the pictures and not the people, and a quiet week with the family
        has the people and not the pictures. Density is the story's pictures per photographed
        day against the period's median photographed day; the share is how many of its
        pictures name a partner, child or parent: the owner's, and in a film about people, the
        subject's own as well. Every story's two numbers are recorded.
        """
        policy = self.source.config.editorial.people
        moments_of = {e.key: e.moments for e in episodes}
        members_of = {
            story["key"]: [
                asset
                for key in story["episodes"]
                for moment in moments_of[key]
                for asset in self.source.moment_asset_ids.get(moment, ())
            ]
            for story in stories
        }
        day_of = {
            asset: self.source.assets[asset].file_created_at.date()
            for members in members_of.values()
            for asset in members
        }
        mass = Counter(day_of.values())
        typical = median(mass.values()) if mass else 0
        close_family = film_close_family(self.source)
        rows = []
        for story in stories:
            members = members_of[story["key"]]
            days = {day_of[asset] for asset in members}
            family = sum(
                bool(close_family(self.source.annotations.get(asset, ""))) for asset in members
            )
            density = len(members) / len(days) / typical if days and typical else 0.0
            share = family / len(members) if members else 0.0
            story["big"] = (
                density >= policy.big_story_density and share >= policy.big_story_family_share
            )
            rows.append(
                {
                    "story": story["key"],
                    "pictures": len(members),
                    "days": len(days),
                    "density": round(density, 2),
                    "family_share": round(share, 3),
                    "big": story["big"],
                }
            )
        return rows

    def read_story(self, _judge, *, evidence, enrich, record, **kwargs) -> PeriodStory:
        episodes = self._day_episodes(evidence)
        hints = enrich(episodes)
        stories = self._stories(episodes, hints)
        by_key = {e.key: e for e in episodes}
        self._big_stories(stories, episodes)
        events = split_events(
            stories,
            shape_of=self._episode_shapes(episodes),
            hints=hints,
            title_of={e.key: e.title for e in episodes},
            threshold=self._day_threshold(),
            away=lambda story: any(self._away_from_home(by_key[k]) for k in story["episodes"]),
            printed_near=self._printed,
        )
        big = self._big_stories(stories, episodes)
        floors = _floor_weights(stories, journey=False)
        # BASIC-only (owner ruling 2026-10-04): the model tier may still read a mostly
        # indicator-less week itself, so a draft the model then polishes never carries this
        # promotion (#2048 review, point C).
        sparse_quality = (
            self._promote_sparse_quality(stories, by_key, hints)
            if self._promote_sparse_quality_enabled
            else {}
        )
        kinds = same_kind_threads(
            stories,
            kind_of=self._episode_kinds(episodes),
            threshold=self._day_threshold(),
            away=lambda story: any(self._away_from_home(by_key[k]) for k in story["episodes"]),
        )
        for story in stories:
            for key in story["episodes"]:
                by_key[key].role = WEIGHT_ROLE[story["weight"]]
        meta = {
            "producer": RULES_VERSION,
            "hints": hints,
            "floors": floors,
            "big_stories": big,
            "same_kind": kinds,
            "events": events,
        }
        # Absent, not empty, when the mechanism never engaged: a below-threshold or FULL
        # plan stays byte-identical to one built before #2048 existed.
        if sparse_quality.get("promoted") or sparse_quality.get("left_short"):
            meta["sparse_quality"] = sparse_quality
        result = PeriodStory("", episodes, [], [], [], meta, stories)
        record(result.as_record())
        return result

    def _at_home(self, story, by_key) -> bool:
        return not any(self._away_from_home(by_key[k]) for k in story["episodes"])

    def _story_members(self, story, by_key) -> list[str]:
        return [
            asset
            for key in story["episodes"]
            for moment in by_key[key].moments
            for asset in self.source.moment_asset_ids.get(moment, ())
        ]

    def _pixel_facts_of(self, asset_id: str) -> tuple[float, float] | None:
        """A still's sharpness and brightness, or None when it was never measured (a video,
        or a picture the pixel pass has not reached yet). A missing row must disqualify a
        sparse week's candidate, never read as a sharpness of 0 that a floor of 0 would pass."""
        facts = getattr(self.source, "pixel_facts", None) or {}
        return facts.get(asset_id)

    def _sharpness_floor(self) -> float:
        """The library's own p10 sharpness over still images with a measured pixel row: the
        no-model bar a sparse week's pick must clear. A video or an unmeasured picture would
        otherwise read as sharpness 0 and drag the floor down to nothing."""
        sharpness = [
            facts[0]
            for asset_id, asset in self.source.assets.items()
            if not asset.is_video and (facts := self._pixel_facts_of(asset_id)) is not None
        ]
        return float(np.percentile(sharpness, 10)) if sharpness else 0.0

    def _free_quality_slots(self, stories: Sequence[Mapping[str, Any]], by_key, candidates) -> int:
        """What the film's slot budget is likely to leave for a glimpse-weight promotion:
        the total nominal still slots, less what the stories that already carry a real
        indicator would claim under the same weight-to-slots rule `allocate_slots` applies.
        An estimate, not a simulation of `allocate_slots` itself (#2048 review, point E) — it
        only has to keep the chronological spread from promoting more weeks than the film can
        actually fund; overestimating what the indicated stories take is the safe direction."""
        case = getattr(self.source, "case", None)
        target = getattr(case, "target_seconds", 0.0) or 0.0
        total = max(int(target // NOMINAL_STILL_SECONDS), 0)
        candidate_keys = {s["key"] for s in candidates}
        indicated = [s for s in stories if s["weight"] != "none" and s["key"] not in candidate_keys]
        caps = weight_caps(total)
        claimed = sum(
            min(caps.get(s["weight"], 0), len(self._story_members(s, by_key))) for s in indicated
        )
        return max(total - claimed, 0)

    def _quality_pick(self, story, by_key, floor: float, never_auto: frozenset) -> str | None:
        """The sharpest, best-exposed, most central clean picture of a sparse week's own
        pool, or None when every candidate fails a hard filter or was never measured."""
        members = self._story_members(story, by_key)
        if not members:
            return None
        midweek = median(self.source.assets[a].file_created_at.timestamp() for a in members)
        rows = []
        for asset_id in members:
            pixel = self._pixel_facts_of(asset_id)
            if pixel is None or self.source.assets[asset_id].is_video:
                continue
            sharpness, brightness = pixel
            rows.append(
                (
                    asset_id,
                    quality_facts(
                        self.source.assets[asset_id],
                        line=self.source.annotations.get(asset_id, ""),
                        heads=self._heads_of(asset_id),
                        standing=self.standing(asset_id),
                        sharpness=sharpness,
                        sharpness_floor=floor,
                        brightness=brightness,
                        distance_from_midweek=abs(
                            self.source.assets[asset_id].file_created_at.timestamp() - midweek
                        ),
                        never_auto=asset_id in never_auto,
                    ),
                )
            )
        if not rows:
            return None
        asset_id, facts = min(rows, key=lambda row: quality_key(row[1]))
        return None if facts.disqualified else asset_id

    def _promote_sparse_quality(self, stories, by_key, hints) -> dict[str, Any]:
        """Fund a mostly-indicator-less household's at-home weeks from their own best
        picture instead of going short (owner ruling 2026-10-04, option a). A household
        with real indicators keeps the 2026-09-23 rule: an indicator-less week among
        mostly-indicated ones still goes short.
        """
        at_home = [story for story in stories if self._at_home(story, by_key)]
        candidates = [story for story in at_home if story["weight"] == "none"]
        share = len(candidates) / len(at_home) if at_home else 0.0
        audit: dict[str, Any] = {
            "share": round(share, 4),
            "threshold": SPARSE_NONE_SHARE,
            "promoted": [],
            "left_short": [],
        }
        if not candidates or share < SPARSE_NONE_SHARE:
            return audit
        ordered = sorted(
            candidates, key=lambda story: min(hints[k]["day"] for k in story["episodes"])
        )
        free_slots = self._free_quality_slots(stories, by_key, candidates)
        chosen = _spread(ordered, free_slots) if len(ordered) > free_slots else ordered.copy()
        chosen_keys = {s["key"] for s in chosen}
        # Weeks the spread had no room for wait behind the chosen ones: a chosen week that
        # fails its own filters hands its slot to the next of these, in the same
        # chronological order, before the slot is given up for good (#2048 review, point E).
        waiting = [s for s in ordered if s["key"] not in chosen_keys]
        floor = self._sharpness_floor()
        never_auto = never_auto_ids(getattr(self.source, "shareability_flags", {}))
        pool = chosen.copy()
        while pool:
            story = pool.pop(0)
            asset_id = self._quality_pick(story, by_key, floor, never_auto)
            if asset_id is None:
                story["sparse_quality_reason"] = "No clean picture of the week"
                audit["left_short"].append(story["key"])
                if waiting:
                    pool.append(waiting.pop(0))
                continue
            story["weight"] = "glimpse"
            story["funded_by"] = "quality"
            story["quality_asset_id"] = asset_id
            story["sparse_quality_reason"] = (
                "The household's period is mostly indicator-less; "
                "funded by this week's best picture"
            )
            audit["promoted"].append(story["key"])
        for story in waiting:
            story["sparse_quality_reason"] = "No free slot for the film's length"
            audit["left_short"].append(story["key"])
        return audit

    def _episode_kinds(self, episodes) -> dict[str, EpisodeKind]:
        partition_for = getattr(self.source.intent, "partition_for", lambda _day: None)
        kinds = {}
        for episode in episodes:
            ids = [a for m in episode.moments for a in self.source.moment_asset_ids.get(m, ())]
            members = [self.source.assets[a] for a in ids]
            points = [p for a in ids if (p := self.source.gps.get(a)) is not None]
            part = partition_for(members[0].file_created_at.date()) if members else None
            kinds[episode.key] = EpisodeKind(
                pictures=len(members),
                activity=self._activity(members),
                place=self._dominant_city(members),
                gps=(median(p[0] for p in points), median(p[1] for p in points))
                if points
                else None,
                partition=part.key if part is not None else None,
            )
        return kinds

    def _episode_shapes(self, episodes) -> dict[str, EpisodeShape]:
        assets, moments = self.source.assets, self.source.moment_asset_ids
        return episode_shapes(
            episodes,
            members_of=lambda e: [assets[a] for m in e.moments for a in moments.get(m, ())],
            activity_of=self._activity,
            gps_of=lambda asset: self.source.gps.get(asset.id),
        )

    def _face_on(self, asset_id: str) -> bool | None:
        if self._face is None:
            self._face = face_evidence(self.source.assets)
        return self._face(asset_id)

    def _heads_of(self, asset_id: str) -> dict[str, str]:
        record = self.source.audience_annotations.get(asset_id)
        return dict(record.heads) if record else {}

    def standing(self, asset_id: str) -> int:
        asset = self.source.assets[asset_id]
        required = getattr(self.source, "owner_required_asset_ids", ())
        if asset.is_favorite or asset_id in required:
            return 2
        heads = self._heads_of(asset_id)
        line = self.source.annotations.get(asset_id, "")
        record = self.source.audience_annotations.get(asset_id)
        description = getattr(record, "description", None)
        if shows_only_a_body_part(heads, description, face=self._face_on(asset_id)):
            return 0
        # An exposure hold says who may see a picture, not whether it stands. The household may
        # see it, so a family film judges it like any other; a film sent further keeps the zero.
        exposure_zero = (
            exposure_flagged(heads)
            and self.source.audience == SHAREABLE
            and asset_id not in owner_cleared_ids(getattr(self.source, "shareability_flags", {}))
        )
        if (
            exposure_zero
            or heads.get(CLIP_FRAMES_HEAD) == SUBJECT_OFTEN_MISSING
            or carries_nothing(heads, line, description, face=self._face_on(asset_id))
        ):
            return 0
        if self.source.intent.product == "album":
            return 2
        return self._visual_standing(heads, known_people=bool(asset.people))

    @staticmethod
    def _visual_standing(heads: dict[str, str], *, known_people: bool) -> int:
        """Nobody, nothing happening and a private or utility interior does not stand on its
        own; people, an activity, or an outdoor or public place does.

        Every label here is one the shipped head bundle can produce. The rule this replaces
        asked for `venue == "home"` and four place labels no head has ever emitted, so two of
        its branches were dead and it could not answer 0 from the heads at all.
        """
        if heads.get("people") == "none":
            if heads.get("activity", "other") == "other" and heads.get("venue") in PRIVATE_VENUES:
                return 0
            if heads.get("location") == "indoor":
                return 1
        if known_people or heads.get("people", "undetermined") not in {"none", "undetermined"}:
            return 2
        if (
            heads.get("activity", "other") != "other"
            or heads.get("location") == OUTDOOR_LOCATION
            or heads.get("venue") in PUBLIC_VENUES
        ):
            return 2
        return 1
