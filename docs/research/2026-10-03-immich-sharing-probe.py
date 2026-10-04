"""Disposable v3.3.0-rc.1 sharing experiment, not a production fetch implementation.

Run from the repository root after make dev, against a fresh, isolated gate stack
on 127.0.0.1:2303. Run this script with `initialize`, then `measure`. Initialization
uses the existing synthetic library builder and creates three test users. Measurement
changes only their sharing settings and a favourite. It can be repeated.

State and downloaded fixtures stay in the ignored .immich-gate/sharing-probe directory. The state file holds
disposable credentials; do not commit it. Only results.json is public evidence.
The face boxes are manually assigned: this tests sharing semantics, not ML accuracy.
See the adjacent 2026-10-03-immich-sharing-results.json for the recorded outcome.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

import httpx
from tests.integration.immich_gate import media
from tests.integration.immich_gate.seed import ADMIN_PASSWORD, Seeder, _api_key, _checked

URL = "http://127.0.0.1:2303"
ROOT = Path(__file__).resolve().parents[2] / ".immich-gate" / "sharing-probe"
ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
STATE = ROOT / "state.json"


def new_user(admin, name):
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
        httpx.post(
            f"{URL}/api/auth/login",
            json={
                "email": email,
                "password": ADMIN_PASSWORD,
            },
        )
    )
    key = _checked(
        httpx.post(
            f"{URL}/api/api-keys",
            json={
                "name": "synthetic-sharing-probe",
                "permissions": ["all"],
            },
            headers={"Authorization": f"Bearer {login['accessToken']}"},
        )
    )["secret"]
    return Seeder(URL, key), key


def initialize():
    key = _api_key(URL)
    a = Seeder(URL, key)
    b, bkey = new_user(a, "Partner")
    c, ckey = new_user(a, "Outside")
    users = {
        name: api.call("GET", "/users/me")
        for name, api in [("primary", a), ("partner", b), ("outside", c)]
    }
    group = users["primary"]["clusterGroupId"]
    invite = a.call(
        "PUT", f"/cluster-groups/{group}/requests", json={"userId": users["partner"]["id"]}
    )
    b.call("POST", f"/cluster-groups/requests/{invite['id']}/accept")
    a.wait_for_queues()
    media.build(ROOT / "media")
    files = media.library_files(ROOT / "media")
    primary_files, partner_files = files[::2], files[1::2]
    aid = a.upload_all(primary_files)
    bid = b.upload_all(partner_files)
    duplicate_file = next(f for f in primary_files if f.path.suffix == ".jpg")
    duplicate = b.upload(duplicate_file)
    outsider = c.upload(next(f for f in files if f.path.suffix == ".jpg"))
    a.wait_for_queues()
    person = a.call("POST", "/people", json={"name": "Shared Child", "birthDate": "2020-01-02"})[
        "id"
    ]
    a.call(
        "PUT",
        "/people/users",
        json={"personIds": [person], "sharedWithIds": [users["partner"]["id"]], "role": "read"},
    )
    target = next(i for i, f in zip(bid, partner_files, strict=True) if f.path.suffix == ".jpg")
    b.call(
        "POST",
        "/faces",
        json={
            "assetId": target,
            "personId": person,
            "imageWidth": 1920,
            "imageHeight": 1280,
            "x": 100,
            "y": 100,
            "width": 300,
            "height": 300,
        },
    )
    a.wait_for_queues()
    state = {
        "keys": {"primary": key, "partner": bkey, "outside": ckey},
        "users": users,
        "person": person,
        "primary_assets": aid,
        "partner_assets": [*bid, duplicate],
        "duplicate": duplicate,
        "target": target,
        "outside_asset": outsider,
    }
    STATE.write_text(json.dumps(state))
    STATE.chmod(0o600)
    print(
        json.dumps(
            {
                "initialized": True,
                "primary_assets": len(aid),
                "partner_assets": len(bid) + 1,
                "outside_assets": 1,
            }
        )
    )


def measure():
    from datetime import UTC, datetime

    from immich_memories.analysis.exact_copies import fold_exact_copies
    from immich_memories.analysis.household_source import HouseholdWindows
    from immich_memories.api.access_clients import AccessBoundClient
    from immich_memories.api.person_expression import PersonExpression
    from immich_memories.api.person_scope import people_in_window
    from immich_memories.api.sync_client import SyncImmichClient
    from immich_memories.config_models import ImmichConfig
    from immich_memories.timeperiod import DateRange

    state = json.loads(STATE.read_text())
    apis = {name: Seeder(URL, key) for name, key in state["keys"].items()}
    a, b, c = (apis[name] for name in ("primary", "partner", "outside"))
    clients = {name: SyncImmichClient(URL, key) for name, key in state["keys"].items()}
    users = {name: user["id"] for name, user in state["users"].items()}
    person, target = state["person"], state["target"]
    window = DateRange(
        datetime(2024, 6, 1, tzinfo=UTC), datetime(2024, 6, 30, 23, 59, 59, tzinfo=UTC)
    )
    for sender, receiver in [(b, "primary"), (a, "partner"), (c, "primary")]:
        outgoing = sender.call("GET", "/partners", params={"direction": "shared-by"})
        if users[receiver] in {user["id"] for user in outgoing}:
            sender.call("DELETE", f"/partners/{users[receiver]}")

    def assets(name):
        client = clients[name]
        return [
            *client.get_photos_for_date_range(window),
            *client.get_videos_for_date_range(window),
        ]

    report = {"version": a.call("GET", "/server/version"), "checks": {}}
    checks = report["checks"]
    before = assets("primary")
    checks["people_sharing_alone_primary_assets"] = len(before)
    assert {x.id for x in before} == set(state["primary_assets"])
    shared_person = b.call("GET", f"/people/{person}")
    checks["shared_person_same_id"] = shared_person["id"] == person
    checks["recipient_person_name"] = shared_person["name"]
    checks["recipient_other_people_names"] = [p["name"] for p in shared_person["otherPeople"]]
    checks["product_recipient_lookup_by_shared_name"] = (
        clients["partner"].get_person_by_name("Shared Child") is not None
    )

    for sender, receiver in [(b, "primary"), (a, "partner"), (c, "primary")]:
        sender.call("POST", "/partners", json={"sharedWithId": users[receiver]})
    a.call("PUT", f"/partners/{users['partner']}", json={"inTimeline": False})
    checks["timeline_off_primary_assets"] = len(assets("primary"))
    assert len(assets("primary")) == len(state["primary_assets"])
    for reader, owner in [(a, "partner"), (b, "primary"), (a, "outside")]:
        reader.call("PUT", f"/partners/{users[owner]}", json={"inTimeline": True})
    b.call("PUT", f"/assets/{state['duplicate']}", json={"isFavorite": True})
    merged = assets("primary")
    checks["timeline_on_primary_assets"] = len(merged)
    assert {x.id for x in merged} == set(
        state["primary_assets"] + state["partner_assets"] + [state["outside_asset"]]
    )
    wanted = {users["primary"], users["partner"]}
    scoped = [x for x in merged if x.owner_id in wanted]
    checks["single_key_scoped_assets"] = len(scoped)
    folded = fold_exact_copies(scoped, primary_owner_id=users["primary"])
    checks["single_key_after_exact_dedup"] = len(folded.pool)
    duplicate_asset = next(x for x in scoped if x.id == state["duplicate"])
    checks["owner_sees_partner_favourite"] = b.call("GET", f"/assets/{state['duplicate']}")[
        "isFavorite"
    ]
    checks["primary_sees_partner_favourite"] = duplicate_asset.is_favorite
    checks["partner_favourite_survives_single_key_merge"] = any(
        x.checksum == duplicate_asset.checksum and x.is_favorite for x in folded.pool
    )
    checks["unselected_owner_excluded"] = state["outside_asset"] not in {x.id for x in scoped}
    assert len(scoped) == 134 and len(folded.pool) == 133
    partner_target = next(x for x in scoped if x.id == target)
    checks["primary_sees_shared_person_on_partner_asset"] = person in [
        p.id for p in partner_target.people
    ]
    read_results = {}
    for label, path in [
        ("detail", f"/assets/{target}"),
        ("thumbnail", f"/assets/{target}/thumbnail?size=preview"),
        ("original", f"/assets/{target}/original"),
        ("faces", f"/faces?id={target}"),
    ]:
        response = a.http.get(path)
        read_results[label] = response.status_code
        assert response.status_code == 200, (label, response.status_code)
    checks["partner_asset_reads_with_primary_key"] = read_results
    from tests.integration.immich_gate.seed import ADMIN_EMAIL

    from immich_memories.api.permissions import READ_PERMISSIONS

    login = _checked(
        httpx.post(f"{URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    )
    session = httpx.Client(
        base_url=f"{URL}/api", headers={"Authorization": f"Bearer {login['accessToken']}"}
    )
    key = _checked(
        session.post(
            "/api-keys", json={"name": "sharing-scoped-read", "permissions": list(READ_PERMISSIONS)}
        )
    )
    reader = SyncImmichClient(URL, key["secret"])
    try:
        reader.require_read_permissions()
        scoped_reads = [
            *reader.get_photos_for_date_range(window),
            *reader.get_videos_for_date_range(window),
        ]
        checks["read_only_key_assets"] = len(scoped_reads)
        checks["read_only_key_partner_faces"] = len(reader.get_asset_faces(target))
        checks["read_only_key_partner_thumbnail"] = bool(reader.get_asset_thumbnail(target))
        checks["read_only_key_partner_original"] = (
            reader.download_asset(target, ROOT / "partner-original.jpg").stat().st_size > 0
        )
        partner_video = next(
            x for x in scoped_reads if x.owner_id == users["partner"] and x.is_video
        )
        checks["read_only_key_partner_video_playback"] = bool(
            reader.get_video_playback(partner_video.id)
        )
        checks["read_only_key_partner_video_original"] = (
            reader.download_asset(partner_video.id, ROOT / "partner-original.mp4").stat().st_size
            > 0
        )
        checks["read_only_key_shared_person_lookup"] = (
            reader.get_person(person).name == "Shared Child"
        )
        assert all(checks[k] for k in checks if k.startswith("read_only_key_"))
    finally:
        reader.close()
        _checked(session.delete(f"/api-keys/{key['apiKey']['id']}"))
        session.close()
    config = ImmichConfig(
        url=URL,
        api_key=state["keys"]["primary"],
        accounts={"partner": {"url": URL, "api_key": state["keys"]["partner"]}},
    )
    with AccessBoundClient(config) as household_client:
        household = HouseholdWindows(household_client, ("primary", "partner"))
        household_pool = household.get_photos_for_date_range(
            window
        ) + household.get_videos_for_date_range(window)
        from immich_memories.analysis.selection_source import _coalesce_sources

        household_folded = fold_exact_copies(
            _coalesce_sources(household_pool)[0], primary_owner_id=users["primary"]
        )
        checks["partner_favourite_survives_household_merge"] = any(
            x.checksum == duplicate_asset.checksum and x.is_favorite for x in household_folded.pool
        )
        condition = PersonExpression("person", value=person)
        native_videos, native_photos = people_in_window(household, window, condition)
        legacy_videos, legacy_photos = people_in_window(
            household, window, condition, face_accounts={person: "primary"}
        )
        native_ids = {x.id for x in native_videos + native_photos}
        legacy_ids = {x.id for x in legacy_videos + legacy_photos}
        checks["native_person_episode_asset_count"] = len(native_ids)
        checks["legacy_account_bound_episode_asset_count"] = len(legacy_ids)
        checks["legacy_drops_partner_target"] = target in native_ids and target not in legacy_ids
    a.call("PUT", f"/partners/{users['partner']}", json={"inTimeline": False})
    checks["timeline_off_scoped_assets"] = len(
        [x for x in assets("primary") if x.owner_id in wanted]
    )
    b.call("DELETE", f"/partners/{users['primary']}")
    checks["original_after_partner_revocation"] = a.http.get(
        f"/assets/{target}/original"
    ).status_code
    for client in clients.values():
        client.close()
    (ROOT / "results.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    assert checks["original_after_partner_revocation"] in (400, 401, 403, 404)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("initialize", "measure"))
    args = parser.parse_args()
    initialize() if args.phase == "initialize" else measure()
