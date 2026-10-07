"""Who owns each Immich account's library: a guess a scan makes, an answer a person gives.

The registry header keeps both. `owner` is the one the rest of the code reads: whatever the
last scan guessed (told, matched on the account name, or inferred), or the confirmed answer
once there is one. `owners` holds only the answers, one per account, as
`{person_id, identified: "confirmed"}`; `person_id: null` is "nobody in this library", a
shared family account. A scan rewrites `owner` and never touches `owners`.
"""

from __future__ import annotations

from typing import Any

from immich_memories.config_models import PRIMARY_ACCOUNT
from immich_memories.people.account_ids import entry_ids, primary_ids
from immich_memories.people.graph import ConfirmedOwner
from immich_memories.people.relationships import owner_role

OWNERS = "owners"
# Marks a role the registry filled in because a relationship pointed at the owner, so a
# change of owner can take it back without touching a role somebody typed.
ROLE_DERIVED = "role_derived_from_owner"


def confirmed_owner(
    document: dict[str, Any], account: str = PRIMARY_ACCOUNT
) -> ConfirmedOwner | None:
    """The answer given for `account`, in the ids the primary scan reads; None when unanswered.

    The name is the registry's own, so the header can be written without asking Immich again.
    """
    answers = document.get(OWNERS)
    answer = answers.get(account) if isinstance(answers, dict) else None
    if not isinstance(answer, dict):
        return None
    person_id = answer.get("person_id")
    if person_id is None:
        return ConfirmedOwner(None, "")
    entry = _entry_holding(document, str(person_id))
    if entry is None:
        return None
    seen = primary_ids(entry)
    return ConfirmedOwner(seen[0] if seen else entry_ids(entry)[0], str(entry.get("name") or ""))


def apply_owner(document: dict[str, Any], person_id: str | None, account: str) -> None:
    """Record the answer for `account`; the primary's also becomes the owner the code reads."""
    entry = None
    if person_id is not None:
        entry = _entry_holding(document, person_id)
        if entry is None:
            msg = f"{person_id!r} is not in the people registry"
            raise ValueError(msg)
    document.setdefault(OWNERS, {})[account] = {
        "person_id": entry_ids(entry)[0] if entry else None,
        "identified": "confirmed",
    }
    if account != PRIMARY_ACCOUNT:
        return
    document["owner"] = owner_block(confirmed_owner(document))
    rederive_owner_roles(document)


def owner_block(answer: ConfirmedOwner | None) -> dict[str, Any] | None:
    """The `owner` header an answer stands for; None when nobody owns the library."""
    if answer is None or answer.person_id is None:
        return None
    return {"person_id": answer.person_id, "name": answer.name, "identified": "confirmed"}


def rederive_owner_roles(document: dict[str, Any]) -> None:
    """Take back every role derived from the previous owner, then derive from the current one."""
    for entry in _entries(document):
        confirmed = entry.get("confirmed")
        if isinstance(confirmed, dict) and confirmed.pop(ROLE_DERIVED, None):
            confirmed["role"] = None
    held = owner_ids(document)
    for other in _entries(document):
        for link in _links(other):
            if link.get("with") in held and link.get("decision", "confirmed") != "rejected":
                derive_owner_role(other, str(link.get("kind")))


def derive_owner_role(entry: dict[str, Any], kind: str) -> None:
    """Give `entry` the role `kind` implies towards the owner, unless it already has one."""
    confirmed = entry.get("confirmed")
    if not isinstance(confirmed, dict) or confirmed.get("role") or not owner_role(kind):
        return
    confirmed["role"] = owner_role(kind)
    confirmed[ROLE_DERIVED] = True


def owner_ids(document: dict[str, Any]) -> set[str]:
    """Every id the current owner answers to."""
    owner = document.get("owner")
    entry = (
        _entry_holding(document, str(owner.get("person_id"))) if isinstance(owner, dict) else None
    )
    return set(entry_ids(entry)) if entry else set()


def _entries(document: dict[str, Any]) -> list[dict[str, Any]]:
    people = document.get("people")
    return [e for e in people if isinstance(e, dict)] if isinstance(people, list) else []


def _entry_holding(document: dict[str, Any], person_id: str) -> dict[str, Any] | None:
    return next((e for e in _entries(document) if person_id in entry_ids(e)), None)


def _links(entry: dict[str, Any]) -> list[dict[str, Any]]:
    confirmed = entry.get("confirmed")
    links = confirmed.get("links") if isinstance(confirmed, dict) else None
    return [link for link in links if isinstance(link, dict)] if isinstance(links, list) else []
