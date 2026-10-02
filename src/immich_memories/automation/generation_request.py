"""Typed boundary from automation candidates to the public generate CLI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from immich_memories.api.person_expression import PersonExpression
from immich_memories.automation.candidates import (
    CandidateCategory,
    MemoryCandidate,
    bind_people_expression_key,
)
from immich_memories.self_command import self_command


@dataclass(frozen=True)
class GenerationRequest:
    """An immutable, exhaustively mapped automation generation request."""

    memory_type: str
    category: CandidateCategory
    memory_key: str
    start: date
    end: date
    people: tuple[str, ...] = ()
    upload: bool = False
    album_name: str | None = None
    automation_attempt_id: str | None = None
    config_path: Path | None = None
    event_id: str | None = None
    birth_date: date | None = None
    person_expression: PersonExpression | None = None
    accounts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.accounts and self.category is CandidateCategory.TRIP:
            # --accounts reads date-range memories only (cli/run_people.py); a trip
            # candidate never carries the multi-account scope discovery attaches.
            raise ValueError("accounts scope is unsupported for a trip candidate")
        if self.person_expression is not None:
            if not isinstance(self.person_expression, PersonExpression):
                raise ValueError("generation people condition must be a validated expression")
            if self.category in {
                CandidateCategory.BIRTHDAY,
                CandidateCategory.PERSON_SPOTLIGHT,
                CandidateCategory.TRIP,
            }:
                raise ValueError("grouped people condition is unsupported for this category")
            if self.people and set(self.people) != set(self.person_expression.leaf_values):
                raise ValueError("generation names and grouped people condition disagree")
            object.__setattr__(self, "people", self.person_expression.leaf_values)
            object.__setattr__(
                self,
                "memory_key",
                bind_people_expression_key(self.memory_key, self.person_expression),
            )

    @classmethod
    def from_candidate(
        cls,
        candidate: MemoryCandidate,
        upload: bool,
        automation_attempt_id: str | None = None,
        config_path: Path | None = None,
        album_name: str | None = None,
    ) -> GenerationRequest:
        """Validate a candidate category and choose its rendering preset."""
        match candidate.category:
            case CandidateCategory.MONTHLY_REVIEW | CandidateCategory.ACTIVITY_BURST:
                memory_type = "monthly_highlights"
            case CandidateCategory.YEAR_IN_REVIEW:
                memory_type = "year_in_review"
            case CandidateCategory.PERSON_SPOTLIGHT | CandidateCategory.BIRTHDAY:
                memory_type = "person_spotlight"
            case CandidateCategory.MULTI_PERSON:
                memory_type = "multi_person"
            case CandidateCategory.ON_THIS_DAY:
                memory_type = "on_this_day"
            case CandidateCategory.TRIP:
                memory_type = "trip"
            case CandidateCategory.EMERGENT_DAY:
                memory_type = "special_day"
            case _:
                raise ValueError(f"Unsupported automation category: {candidate.category!r}")

        event_id = (
            candidate.extra_params.get("event_id")
            if candidate.category == CandidateCategory.EMERGENT_DAY
            else None
        )
        if event_id is not None and (not isinstance(event_id, str) or not event_id.strip()):
            raise ValueError("special-day event_id must be a nonempty catalogue ID")
        expression_record = candidate.extra_params.get("person_expression")
        accounts_record = candidate.extra_params.get("accounts")
        return cls(
            memory_type=memory_type,
            category=candidate.category,
            memory_key=candidate.memory_key,
            start=candidate.date_range_start,
            end=candidate.date_range_end,
            people=tuple(candidate.person_names),
            upload=upload,
            album_name=album_name,
            automation_attempt_id=automation_attempt_id,
            config_path=config_path,
            event_id=event_id,
            birth_date=(
                date.fromisoformat(candidate.extra_params["birth_date"])
                if candidate.category is CandidateCategory.BIRTHDAY
                and candidate.extra_params.get("birth_date")
                else None
            ),
            person_expression=(
                PersonExpression.from_dict(expression_record)
                if expression_record is not None
                else None
            ),
            accounts=tuple(accounts_record) if accounts_record else (),
        )

    def to_argv(self) -> list[str]:
        """Build shell-safe argv for the public generate command."""
        argv = self_command()
        if self.config_path is not None:
            argv.extend(["--config", str(self.config_path)])
        argv.extend(["generate", "--memory-type", self.memory_type])
        argv.extend(self._category_args())

        if self.person_expression is not None:
            argv = [arg for arg in argv if not arg.startswith("--person=")]
            argv.append(f"--people-expression={self.person_expression.display_label}")
        if self.accounts:
            argv.append(f"--accounts={','.join(self.accounts)}")
        argv.extend(
            [
                "--source=auto",
                f"--memory-key={self.memory_key}",
                f"--memory-category={self.category.value}",
            ]
        )
        if self.upload:
            argv.append("--upload-to-immich")
            if self.album_name is not None:
                argv.extend(["--album", self.album_name])
        if self.automation_attempt_id is not None:
            argv.append(f"--automation-attempt-id={self.automation_attempt_id}")
        return argv

    def _category_args(self) -> list[str]:
        """The argv this category alone contributes, before people scope and bookkeeping."""
        match self.category:
            case CandidateCategory.MONTHLY_REVIEW | CandidateCategory.ACTIVITY_BURST:
                return ["--year", str(self.start.year), "--month", str(self.start.month)]
            case CandidateCategory.YEAR_IN_REVIEW:
                return ["--year", str(self.start.year)]
            case CandidateCategory.PERSON_SPOTLIGHT:
                return ["--year", str(self.start.year), *self._person_args()]
            case CandidateCategory.BIRTHDAY:
                # WHY end and not start: --year names the birthday being celebrated, and
                # a birthday memory is the year *leading up to* it -- so the year the
                # window ends in is the one to ask for.
                return [
                    "--year",
                    str(self.end.year),
                    "--birthday",
                    (self.birth_date or self.end).strftime("%m-%d"),
                    *self._person_args(),
                ]
            case CandidateCategory.MULTI_PERSON:
                return ["--year", str(self.start.year), *self._person_args()]
            case CandidateCategory.ON_THIS_DAY:
                # The day travels explicitly: a child that starts after midnight would
                # otherwise look back from a different anniversary than the candidate
                # the runner chose.
                return ["--day", self.start.isoformat()]
            case CandidateCategory.TRIP:
                return [
                    "--year",
                    str(self.start.year),
                    "--start",
                    self.start.isoformat(),
                    "--end",
                    self.end.isoformat(),
                ]
            case CandidateCategory.EMERGENT_DAY:
                # Only the date and opaque selector travel in the logged argv. The child
                # re-reads the catalogue for private names and members.
                args = ["--day", self.start.isoformat()]
                if self.event_id is not None:
                    args.extend(["--event-id", self.event_id])
                return args
            case _:
                raise ValueError(f"Unsupported automation category: {self.category!r}")

    def _person_args(self) -> list[str]:
        return [f"--person={name}" for name in self.people]
