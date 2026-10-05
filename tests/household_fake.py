"""One fake Immich server shared by two synthetic accounts, for people across a household.

Each key answers `/users/me`, its own roster at `/people` and its own library at
`/search/metadata`. Every person, face id and picture here is invented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

URL = "https://immich.example.test"
PRIMARY_KEY = "primary-" * 4
PARTNER_KEY = "partner-" * 4
USERS = {PRIMARY_KEY: "user-primary", PARTNER_KEY: "user-partner"}
OWNERS = {"primary": "user-primary", "partner": "user-partner"}


def picture(asset_id: str, account: str, day: int, faces: tuple[str, ...], *, minute: int = 0):
    """One photo on a June 2025 day; pictures on one day within the hour share an episode."""
    taken = datetime(2025, 6, day, 12, minute, tzinfo=UTC).isoformat()
    return {
        "id": asset_id,
        "ownerId": OWNERS[account],
        "type": "IMAGE",
        "originalFileName": f"IMG_{asset_id}.HEIC",
        "fileCreatedAt": taken,
        "fileModifiedAt": taken,
        "updatedAt": taken,
        "isFavorite": False,
        "width": 4032,
        "height": 3024,
        "checksum": f"sum-{asset_id}",
        "exifInfo": {"make": "Apple", "model": "iPhone"},
        "people": [{"id": face, "name": ""} for face in faces],
    }


@dataclass
class FakeHousehold:
    """What each key's library and roster hold, and every request that reached the server."""

    library: dict[str, list[dict]] = field(default_factory=dict)
    roster: dict[str, list[dict]] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)
    # (the user whose key asked, the path): which account read what.
    reads: list[tuple[str, str]] = field(default_factory=list)

    version: dict = field(default_factory=lambda: {"major": 2, "minor": 7, "patch": 5})
    clusters: dict[str, str] = field(default_factory=dict)
    shares: list[dict] = field(default_factory=list)
    direct_people: dict[str, list[dict]] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)
    people_page_size: int = 1000

    def handler(self, request: httpx.Request) -> httpx.Response:
        key = request.headers["x-api-key"]
        self.requests.append(request.url.path)
        self.reads.append((USERS[key], request.url.path))
        if status := self.errors.get(request.url.path):
            return httpx.Response(status, json={"message": "Synthetic endpoint refusal"})
        if request.url.path.endswith("/server/version"):
            return httpx.Response(200, json=self.version)
        if request.url.path.endswith("/people/users"):
            return httpx.Response(200, json=self.shares)
        if request.url.path.endswith("/api-keys/me"):
            return httpx.Response(200, json={"permissions": ["all"]})
        if request.url.path.endswith("/users/me"):
            return httpx.Response(
                200,
                json={
                    "id": USERS[key],
                    "email": f"{USERS[key]}@x.test",
                    "clusterGroupId": self.clusters.get(key),
                },
            )
        if request.url.path.endswith("/people"):
            people = self.roster.get(key, [])
            start = (int(request.url.params.get("page", 1)) - 1) * self.people_page_size
            end = start + self.people_page_size
            return httpx.Response(
                200, json={"people": people[start:end], "hasNextPage": end < len(people)}
            )
        if "/people/" in request.url.path:
            face = request.url.path.rsplit("/", 1)[1]
            person = next(
                (
                    p
                    for p in [*self.roster.get(key, []), *self.direct_people.get(key, [])]
                    if p["id"] == face
                ),
                None,
            )
            return (
                httpx.Response(200, json=person)
                if person
                else httpx.Response(404, json={"message": "Person unavailable"})
            )
        if not request.url.path.endswith("/search/metadata"):
            return httpx.Response(200, json=[])
        # `--ask`'s pool read (`cli/_album_generation.py::pool_media`) names no type at all.
        wanted = json.loads(request.content).get("type")
        items = [
            item for item in self.library.get(key, []) if wanted is None or item["type"] == wanted
        ]
        return httpx.Response(200, json={"assets": {"items": items, "total": len(items)}})

    def install(self, monkeypatch) -> FakeHousehold:
        real_client = httpx.AsyncClient
        # WHY: the Immich HTTP boundary; every request goes to this in-process fake server.
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: real_client(transport=httpx.MockTransport(self.handler), **kwargs),
        )
        return self


def immich_config() -> dict:
    """The `immich:` section of a household config: the primary key and one partner."""
    return {
        "url": URL,
        "api_key": PRIMARY_KEY,
        "api_version": "v2",
        "accounts": {"partner": {"url": URL, "api_key": PARTNER_KEY, "api_version": "v2"}},
    }
