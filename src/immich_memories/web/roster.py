"""The people registry, read and answered from the browser: the one `people scan` writes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from immich_memories.api.person_expression import PersonExpression
from immich_memories.config_loader import Config
from immich_memories.config_models import PRIMARY_ACCOUNT
from immich_memories.db import Store, open_store
from immich_memories.people.editor import (
    ROLE_SUGGESTIONS,
    PersonView,
    add_person,
    add_relationship,
    bind_person_alias,
    curation_flags,
    decline_person_alias,
    keep_apart,
    load_people,
    remove_relationship,
    save_person,
    unbind_person_alias,
)
from immich_memories.people.groups import add_group, list_groups, remove_group
from immich_memories.people.relationships import RELATIONSHIP_CHOICES
from immich_memories.web.dependencies import current_config
from immich_memories.web.schemas import RosterPerson

router = APIRouter(prefix="/api/v1/roster", tags=["people"])


def people_store(config: Annotated[Config, Depends(current_config)]) -> Store:
    """The store holding the people registry this server reads, the one the CLI writes."""
    return open_store(config)


class RosterFlag(BaseModel):
    kind: str
    names: list[str]
    person_ids: list[str]
    # Where each person opens in Immich, in the same order; None without a server URL.
    person_urls: list[str | None]


class FlagAnswer(BaseModel):
    kind: str
    person_ids: tuple[str, str]


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


class AliasBind(BaseModel):
    account: str
    alias_id: str


class SavedGroupView(BaseModel):
    label: str
    # The grammar --people-expression takes, re-parseable as typed: e.g. ("id-a" OR "id-b").
    expression: str


class NewGroup(BaseModel):
    label: str
    expression: str


def _shown(person: PersonView, config: Config) -> RosterPerson:
    urls = {
        alias: _alias_url(config, account, alias)
        for account, ids in person.aliases.items()
        for alias in ids
    }
    return RosterPerson.model_validate({**asdict(person), "alias_urls": urls})


def _alias_url(config: Config, account: str, alias_id: str) -> str | None:
    """Where an account's person opens: the address links use, or that account's own server."""
    if account == PRIMARY_ACCOUNT:
        return config.immich.person_url(alias_id)
    connection = config.immich.accounts.get(account)
    if connection is None or not connection.url:
        return None
    same_server = connection.url.rstrip("/") == config.immich.url.rstrip("/")
    base = config.immich.link_base if same_server else connection.url.rstrip("/")
    return f"{base}/people/{alias_id}"


@router.get("", response_model=Roster)
def roster(
    store: Annotated[Store, Depends(people_store)],
    config: Annotated[Config, Depends(current_config)],
) -> Roster:
    """Everyone in the people registry, inner circle first, with what needs curating."""
    people = load_people(store)
    return Roster(
        people=[_shown(person, config) for person in people],
        flags=[
            RosterFlag(
                **asdict(flag),
                person_urls=[config.immich.person_url(pid) for pid in flag.person_ids],
            )
            for flag in curation_flags(people)
        ],
        relationships=[Choice(kind=c.kind, label=c.label) for c in RELATIONSHIP_CHOICES],
        roles=list(ROLE_SUGGESTIONS),
    )


@router.post("/flags/keep-apart", status_code=204)
def keep_flag_apart(answer: FlagAnswer, store: Annotated[Store, Depends(people_store)]) -> None:
    """Answer a curation flag "keep apart": the pair stops being flagged."""
    try:
        keep_apart(store, answer.kind, *answer.person_ids)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


@router.put("/{person_id}", response_model=RosterPerson)
def answer(
    person_id: str,
    answers: PersonAnswers,
    store: Annotated[Store, Depends(people_store)],
    config: Annotated[Config, Depends(current_config)],
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
    return _shown(saved, config)


@router.post("", response_model=RosterPerson, status_code=201)
def add(
    new: NewPerson,
    store: Annotated[Store, Depends(people_store)],
    config: Annotated[Config, Depends(current_config)],
) -> RosterPerson:
    """Add someone Immich has not tagged, or who is never on camera."""
    try:
        person_id = add_person(store, new.name)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    person = next(p for p in load_people(store) if p.person_id == person_id)
    return _shown(person, config)


@router.post("/{person_id}/relationships", response_model=RosterPerson)
def relate(
    person_id: str,
    relationship: Relationship,
    store: Annotated[Store, Depends(people_store)],
    config: Annotated[Config, Depends(current_config)],
) -> RosterPerson:
    """Record one relationship; the registry keeps its reciprocal."""
    try:
        add_relationship(store, person_id, relationship.kind, relationship.target_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    person = next(p for p in load_people(store) if p.person_id == person_id)
    return _shown(person, config)


@router.delete("/{person_id}/relationships", response_model=RosterPerson)
def unrelate(
    person_id: str,
    relationship: Relationship,
    store: Annotated[Store, Depends(people_store)],
    config: Annotated[Config, Depends(current_config)],
) -> RosterPerson:
    """Remove a relationship somebody recorded, and its reciprocal."""
    if not any(p.person_id == person_id for p in load_people(store)):
        raise HTTPException(404, "Nobody with that id is in the people registry.")
    remove_relationship(store, person_id, relationship.kind, relationship.target_id)
    person = next(p for p in load_people(store) if p.person_id == person_id)
    return _shown(person, config)


@router.post("/{person_id}/aliases", response_model=RosterPerson)
def bind_alias_route(
    person_id: str,
    bind: AliasBind,
    store: Annotated[Store, Depends(people_store)],
    config: Annotated[Config, Depends(current_config)],
) -> RosterPerson:
    """Declare that `bind.alias_id`, as `bind.account` reads it, is this person.

    The account has to be `primary` or a name under `immich.accounts` (`people bind`'s own
    rule); an id already bound to somebody else is refused, an id this person already has
    for this account is a no-op. Name, birth date and confirmations are untouched.
    """
    try:
        bind_person_alias(store, person_id, bind.account, bind.alias_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    person = next((p for p in load_people(store) if p.person_id == person_id), None)
    if person is None:
        raise HTTPException(404, "Nobody with that id is in the people registry.")
    return _shown(person, config)


def _alias_answer(
    answered: Callable[[Store, str, str, str], None],
    person_id: str,
    bind: AliasBind,
    store: Store,
    config: Config,
) -> RosterPerson:
    try:
        answered(store, person_id, bind.account, bind.alias_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    person = next((p for p in load_people(store) if p.person_id == person_id), None)
    if person is None:
        raise HTTPException(404, "Nobody with that id is in the people registry.")
    return _shown(person, config)


@router.delete("/{person_id}/aliases", response_model=RosterPerson)
def unbind_alias_route(
    person_id: str,
    bind: AliasBind,
    store: Annotated[Store, Depends(people_store)],
    config: Annotated[Config, Depends(current_config)],
) -> RosterPerson:
    """Unlink another account's person from this one. The person and their answers stay."""
    return _alias_answer(unbind_person_alias, person_id, bind, store, config)


@router.post("/{person_id}/aliases/declined", response_model=RosterPerson)
def decline_alias_route(
    person_id: str,
    bind: AliasBind,
    store: Annotated[Store, Depends(people_store)],
    config: Annotated[Config, Depends(current_config)],
) -> RosterPerson:
    """Say that another account's person is not this one; it is never suggested again."""
    return _alias_answer(decline_person_alias, person_id, bind, store, config)


@router.get("/groups", response_model=list[SavedGroupView])
def groups(store: Annotated[Store, Depends(people_store)]) -> list[SavedGroupView]:
    """Every saved group, in the order they were added — the labels `--group` takes."""
    return [
        SavedGroupView(label=saved.label, expression=saved.expression.display_label)
        for saved in list_groups(store)
    ]


@router.post("/groups", response_model=SavedGroupView, status_code=201)
def add_group_route(
    new: NewGroup, store: Annotated[Store, Depends(people_store)]
) -> SavedGroupView:
    """Save a group. EXPRESSION is the --people-expression grammar over canonical person ids.

    Parsed and size-checked first: a malformed expression saves nothing.
    """
    try:
        parsed = PersonExpression.parse(new.expression)
        add_group(store, new.label, parsed)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return SavedGroupView(label=new.label, expression=parsed.display_label)


@router.delete("/groups/{label}", status_code=204)
def remove_group_route(label: str, store: Annotated[Store, Depends(people_store)]) -> None:
    """Remove a saved group. Never touches the people it named."""
    try:
        remove_group(store, label)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
