"""The album names a run may quote, indexed once from Immich."""

from __future__ import annotations

from collections.abc import Sequence

from immich_memories.api.album_service import AlbumRef


class _Albums:
    """The two Immich album reads an index needs.

    # WHY: replaces the Immich HTTP boundary — the album listing and one album's
    # assets — so the request shape can be counted without a server.
    """

    def __init__(self, albums: Sequence[tuple[AlbumRef, tuple[str, ...]]]) -> None:
        self._albums = tuple(albums)
        self.listings = 0
        self.read: list[str] = []

    def list_albums(self) -> list[AlbumRef]:
        self.listings += 1
        return [ref for ref, _assets in self._albums]

    def list_album_assets(self, album_id: str) -> list[dict[str, str]]:
        self.read.append(album_id)
        return [
            {"id": asset_id}
            for ref, assets in self._albums
            if ref.id == album_id
            for asset_id in assets
        ]


def _source() -> _Albums:
    return _Albums(
        (
            (AlbumRef(id="al-1", name="Summer Festival 2022", asset_count=2), ("a1", "a2")),
            (AlbumRef(id="al-2", name="Sunday at the lake", asset_count=1), ("a2",)),
        )
    )


def test_the_index_costs_one_listing_and_one_read_per_album() -> None:
    from immich_memories.analysis.sources.album_index import build_album_index

    source = _source()
    index = build_album_index(source)

    assert source.listings == 1
    assert source.read == ["al-1", "al-2"]
    assert index.names_for(("a1",)) == ("Summer Festival 2022",)
    assert index.names_for(("a2", "a1")) == ("Summer Festival 2022", "Sunday at the lake")
    assert index.names_for(("unheld",)) == ()
    assert index.indexed_albums == ("Summer Festival 2022", "Sunday at the lake")


def test_an_album_above_the_cap_is_never_read() -> None:
    from immich_memories.analysis.sources.album_index import build_album_index

    source = _Albums(
        (
            (AlbumRef(id="al-smart", name="Recents", asset_count=40_000), ("a1",)),
            (AlbumRef(id="al-1", name="Summer Festival 2022", asset_count=2), ("a1", "a2")),
        )
    )

    index = build_album_index(source, max_album_assets=10)

    assert source.read == ["al-1"]
    assert index.skipped_albums == ("Recents",)
    assert index.names_for(("a1",)) == ("Summer Festival 2022",)


def test_a_source_that_cannot_list_albums_names_nothing() -> None:
    from immich_memories.analysis.sources.album_index import NO_ALBUMS, build_album_index

    assert build_album_index(object()) is NO_ALBUMS


def test_the_index_is_built_once_however_many_episodes_ask() -> None:
    from immich_memories.analysis.sources.album_index import RunAlbumNames

    source = _source()
    recorded = []
    names = RunAlbumNames(source, record=recorded.append)

    assert names(("a1",)) == ("Summer Festival 2022",)
    assert names(("a2",)) == ("Summer Festival 2022", "Sunday at the lake")
    assert source.listings == 1
    assert [index.indexed_albums for index in recorded] == [
        ("Summer Festival 2022", "Sunday at the lake")
    ]


def _dated(album_id: str, name: str, assets: tuple[str, ...], updated: str | None):
    return (AlbumRef(id=album_id, name=name, asset_count=len(assets), updated_at=updated), assets)


def test_a_later_run_reads_only_the_albums_that_changed_since(tmp_path) -> None:
    # Each run used to read every album again (#2711). An album's members change only with
    # its own update stamp or count, so an unchanged album is answered from the last run.
    from immich_memories.analysis.sources.album_index import build_album_index

    memo = tmp_path / "album-members.private.json"
    first = _Albums(
        (
            _dated("al-1", "Summer Festival 2022", ("a1", "a2"), "2025-07-01T10:00:00.000Z"),
            _dated("al-2", "Sunday at the lake", ("a2",), "2025-07-02T10:00:00.000Z"),
        )
    )
    build_album_index(first, memo_path=memo)
    later = _Albums(
        (
            _dated("al-1", "Summer Festival 2022", ("a1", "a2"), "2025-07-01T10:00:00.000Z"),
            _dated("al-2", "Sunday at the lake", ("a2", "a3"), "2025-08-01T10:00:00.000Z"),
        )
    )

    index = build_album_index(later, memo_path=memo)

    assert first.read == ["al-1", "al-2"]
    assert later.read == ["al-2"]
    assert index.names_for(("a1",)) == ("Summer Festival 2022",)
    assert index.names_for(("a3",)) == ("Sunday at the lake",)
    assert index.indexed_albums == ("Summer Festival 2022", "Sunday at the lake")


def test_a_renamed_album_answers_with_its_new_name_from_the_memo(tmp_path) -> None:
    from immich_memories.analysis.sources.album_index import build_album_index

    memo = tmp_path / "album-members.private.json"
    stamp = "2025-07-01T10:00:00.000Z"
    build_album_index(_Albums((_dated("al-1", "Summer", ("a1",), stamp),)), memo_path=memo)
    renamed = _Albums((_dated("al-1", "Summer Festival", ("a1",), stamp),))

    assert build_album_index(renamed, memo_path=memo).names_for(("a1",)) == ("Summer Festival",)
    assert renamed.read == []


def test_an_album_without_an_update_stamp_is_read_every_run(tmp_path) -> None:
    from immich_memories.analysis.sources.album_index import build_album_index

    memo = tmp_path / "album-members.private.json"
    for _ in range(2):
        source = _Albums((_dated("al-1", "Summer", ("a1",), None),))
        build_album_index(source, memo_path=memo)
        assert source.read == ["al-1"]


def test_an_unreadable_memo_reads_every_album_again(tmp_path) -> None:
    from immich_memories.analysis.sources.album_index import build_album_index

    memo = tmp_path / "album-members.private.json"
    memo.write_text("{not json")
    source = _Albums((_dated("al-1", "Summer", ("a1",), "2025-07-01T10:00:00.000Z"),))

    assert build_album_index(source, memo_path=memo).names_for(("a1",)) == ("Summer",)
    assert source.read == ["al-1"]
