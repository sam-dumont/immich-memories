"""Two runs writing one library bank at once keep both runs' answers.

Two `generate` runs, a web UI cut beside a CLI run, or a film beside idle fill all plan at the
same time: the pipeline lock only covers assembly. Each case here opens the bank twice, as two
runs do, lets each writer bank a different key, and reads back both. The audience and vote
banks' cases run on every store backend in `tests/store/test_banks.py`.
"""

from concurrent.futures import ThreadPoolExecutor

from immich_memories.analysis.place_geocoder import PlaceGeocoder
from immich_memories.db import open_store
from immich_memories.people.companion import add_confirmed_person, load_document, people_entries


def test_two_runs_naming_different_places_keep_both_names():
    store = open_store()
    # WHY: each fetch stands in for Nominatim, the only outside call the geocoder makes.
    first = PlaceGeocoder(store, "fr", lambda *_: {"city": "Lyon"})
    second = PlaceGeocoder(store, "fr", lambda *_: {"city": "Gand"})

    first.address(45.76, 4.84)
    second.address(51.05, 3.72)

    offline = PlaceGeocoder(store, "fr", lambda *_: None)
    assert offline.address(45.76, 4.84) == {"city": "Lyon"}
    assert offline.address(51.05, 3.72) == {"city": "Gand"}


def test_people_added_from_the_web_ui_and_the_cli_at_once_are_all_kept():
    store = open_store()
    names = [f"person-{writer}-{n}" for writer in range(4) for n in range(10)]

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda name: add_confirmed_person(store, name), names))

    assert {entry["name"] for entry in people_entries(load_document(store))} == set(names)
