"""Seed an isolated 3.2/3.3 sharing gate with the existing CC0 fixture month."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from uuid import UUID

import httpx
from tests.integration.immich_gate import media
from tests.integration.immich_gate.seed import ADMIN_PASSWORD, Seeder, _api_key, _checked
from tests.integration.native_sharing.ocr_fixture import seed_ocr


def _user(admin: Seeder, url: str, name: str) -> tuple[Seeder, str]:
    email = f"{name}@example.invalid"
    admin.call(
        "POST",
        "/admin/users",
        json={
            "email": email,
            "password": ADMIN_PASSWORD,
            "name": name,
            "shouldChangePassword": False,
        },
    )
    login = _checked(
        httpx.post(f"{url}/api/auth/login", json={"email": email, "password": ADMIN_PASSWORD})
    )
    key = _checked(
        httpx.post(
            f"{url}/api/api-keys",
            json={"name": "sharing-gate", "permissions": ["all"]},
            headers={"Authorization": f"Bearer {login['accessToken']}"},
        )
    )["secret"]
    return Seeder(url, key), key


def seed(url: str, root: Path, media_root: Path, database_container: str | None = None) -> None:
    """Create disposable users, explicit grants and one partner-only face; save private state."""
    key = _api_key(url)
    a = Seeder(url, key)
    b, partner_key = _user(a, url, "Partner")
    c, outside_key = _user(a, url, "Outside")
    apis = {"primary": a, "partner": b, "outside": c}
    try:
        users = {name: api.call("GET", "/users/me") for name, api in apis.items()}
        version = a.call("GET", "/server/version")
        group = users["primary"]["clusterGroupId"]
        invitation = a.call(
            "PUT", f"/cluster-groups/{group}/requests", json={"userId": users["partner"]["id"]}
        )
        b.call("POST", f"/cluster-groups/requests/{invitation['id']}/accept")
        a.wait_for_queues()
        for sender, receiver in ((b, "primary"), (a, "partner"), (c, "primary")):
            sender.call("POST", "/partners", json={"sharedWithId": users[receiver]["id"]})
        for reader, owner in ((a, "partner"), (b, "primary"), (a, "outside")):
            reader.call("PUT", f"/partners/{users[owner]['id']}", json={"inTimeline": True})
        media.build(media_root)
        files = media.library_files(media_root)
        own_files, partner_files = files[::2], files[1::2]
        own = a.upload_all(own_files)
        partner = b.upload_all(partner_files)
        copied_file = next(f for f in own_files if f.path.suffix == ".jpg")
        duplicate = b.upload(copied_file)
        outside = c.upload(copied_file)
        a.wait_for_queues()
        b.call("PUT", f"/assets/{duplicate}", json={"isFavorite": True})
        person = a.call("POST", "/people", json={"name": "Shared Child"})["id"]
        tagger = b
        face_person = person
        if version["minor"] == 3:
            a.call(
                "PUT",
                "/people/users",
                json={
                    "personIds": [person],
                    "sharedWithIds": [users["partner"]["id"]],
                    "role": "read",
                },
            )
        else:
            if not database_container or not database_container.startswith("immich-gate-"):
                raise ValueError("3.2 fixture needs its disposable immich-gate database container")
            face_person = b.call("POST", "/people", json={"name": "Shared Child"})["id"]
        target = next(
            i for i, f in zip(partner, partner_files, strict=True) if f.path.suffix == ".jpg"
        )
        tagger.call(
            "POST",
            "/faces",
            json={
                "assetId": target,
                "personId": face_person,
                "imageWidth": 1920,
                "imageHeight": 1280,
                "x": 100,
                "y": 100,
                "width": 300,
                "height": 300,
            },
        )
        a.wait_for_queues()
        if version["minor"] == 2:
            # Recognition normally supplies the shared group. Manual boxes test identity
            # semantics without an ML model; this mutation is confined to the gate DB.
            old, new = str(UUID(face_person)), str(UUID(person))
            sql = """BEGIN;
UPDATE person SET "personGroupId" = :'new' WHERE "personGroupId" = :'old';
UPDATE asset_face SET "personGroupId" = :'new' WHERE "personGroupId" = :'old';
COMMIT;"""
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    database_container,
                    "psql",
                    "-U",
                    "postgres",
                    "-d",
                    "immich",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-v",
                    f"old={old}",
                    "-v",
                    f"new={new}",
                ],
                input=sql,
                text=True,
                check=True,
                capture_output=True,
            )
        seed_ocr(database_container, target)
        root.mkdir(parents=True, exist_ok=True)
        state = root / "state.json"
        state.touch(mode=0o600)
        state.write_text(
            json.dumps(
                {
                    "url": url,
                    "version": version,
                    "keys": {"primary": key, "partner": partner_key, "outside": outside_key},
                    "users": users,
                    "person": person,
                    "primary_assets": own,
                    "partner_assets": [*partner, duplicate],
                    "duplicate": duplicate,
                    "target": target,
                    "outside_asset": outside,
                }
            )
        )
        print(
            f"Seeded Immich {version['major']}.{version['minor']}.{version['patch']}: 134 selected records, 133 unique assets"
        )
    finally:
        for api in apis.values():
            api.http.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--database-container")
    args = parser.parse_args()
    seed(args.url, args.state_dir, args.media, args.database_container)
