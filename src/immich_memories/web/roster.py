"""The people registry, read and answered from the browser: the one `people scan` writes."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from immich_memories.config_loader import Config
from immich_memories.db import Store, open_store
from immich_memories.people.editor import (
    ROLE_SUGGESTIONS,
    add_person,
    add_relationship,
    curation_flags,
    load_people,
    remove_relationship,
    save_person,
)
from immich_memories.people.relationships import RELATIONSHIP_CHOICES
from immich_memories.web.dependencies import current_config

router = APIRouter(prefix="/api/v1/roster", tags=["people"])


def people_store(config: Annotated[Config, Depends(current_config)]) -> Store:
    """The store holding the people registry this server reads, the one the CLI writes."""
    return open_store(config)


class RosterLink(BaseModel):
    kind: str
    target_id: str
    target_name: str
    confidence: float
    via: str
    inferred: bool
    decision: str | None = None
    reverse_kind: str | None = None


class RosterPerson(BaseModel):
    person_id: str
    name: str
    birth_date: str | None
    tier: str
    count: int
    counts_reliable: bool
    evidence: str
    links: list[RosterLink]
    role: str | None = None
    notes: str | None = None


class RosterFlag(BaseModel):
    kind: str
    names: list[str]
    person_ids: list[str]
    message: str


class Choice(BaseModel):
    kind: str
    label: str


class Roster(BaseModel):
    people: list[RosterPerson]
    flags: list[RosterFlag]
    relationships: list[Choice]
    roles: list[str]


class LinkAnswer(BaseModel):
    kind: str
    target_id: str
    decision: Literal["confirmed", "rejected"] | None


class PersonAnswers(BaseModel):
    role: str | None = None
    notes: str | None = None
    links: list[LinkAnswer] = []


class NewPerson(BaseModel):
    name: str


class Relationship(BaseModel):
    kind: str
    target_id: str


@router.get("", response_model=Roster)
def roster(store: Annotated[Store, Depends(people_store)]) -> Roster:
    """Everyone in the people registry, inner circle first, with what needs curating."""
    people = load_people(store)
    return Roster(
        people=[RosterPerson.model_validate(asdict(person)) for person in people],
        flags=[RosterFlag.model_validate(asdict(flag)) for flag in curation_flags(people)],
        relationships=[Choice(kind=c.kind, label=c.label) for c in RELATIONSHIP_CHOICES],
        roles=list(ROLE_SUGGESTIONS),
    )


@router.put("/{person_id}", response_model=RosterPerson)
def answer(
    person_id: str, answers: PersonAnswers, store: Annotated[Store, Depends(people_store)]
) -> RosterPerson:
    """Keep this person's role, notes and answers to the graph's guesses."""
    person = next((p for p in load_people(store) if p.person_id == person_id), None)
    if person is None:
        raise HTTPException(404, "Nobody with that id is in the people registry.")
    decided = {(a.kind, a.target_id): a.decision for a in answers.links}
    person.role, person.notes = answers.role, answers.notes
    for link in person.links:
        if (link.kind, link.target_id) in decided:
            link.decision = decided[(link.kind, link.target_id)]
    save_person(store, person)
    saved = next(p for p in load_people(store) if p.person_id == person_id)
    return RosterPerson.model_validate(asdict(saved))


@router.post("", response_model=RosterPerson, status_code=201)
def add(new: NewPerson, store: Annotated[Store, Depends(people_store)]) -> RosterPerson:
    """Add someone Immich has not tagged, or who is never on camera."""
    try:
        person_id = add_person(store, new.name)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    person = next(p for p in load_people(store) if p.person_id == person_id)
    return RosterPerson.model_validate(asdict(person))


@router.post("/{person_id}/relationships", response_model=RosterPerson)
def relate(
    person_id: str, relationship: Relationship, store: Annotated[Store, Depends(people_store)]
) -> RosterPerson:
    """Record one relationship; the registry keeps its reciprocal."""
    try:
        add_relationship(store, person_id, relationship.kind, relationship.target_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    person = next(p for p in load_people(store) if p.person_id == person_id)
    return RosterPerson.model_validate(asdict(person))


@router.delete("/{person_id}/relationships", response_model=RosterPerson)
def unrelate(
    person_id: str, relationship: Relationship, store: Annotated[Store, Depends(people_store)]
) -> RosterPerson:
    """Remove a relationship somebody recorded, and its reciprocal."""
    remove_relationship(store, person_id, relationship.kind, relationship.target_id)
    person = next(p for p in load_people(store) if p.person_id == person_id)
    return RosterPerson.model_validate(asdict(person))
