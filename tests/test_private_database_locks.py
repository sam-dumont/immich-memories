"""Permission enforcement must preserve SQLite's coordination with other processes."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from contextlib import closing

from immich_memories.store.editorial_preparation import private_database_path


def test_private_permissions_keep_subprocess_facts_visible_to_an_open_reader(tmp_path):
    path = private_database_path(tmp_path / "facts.sqlite")
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        connection.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO facts VALUES (?, ?)", (1, "x" * 5000))
        connection.commit()
        assert connection.execute("SELECT id FROM facts").fetchall() == [(1,)]

        private_database_path(path)

        for asset in (2, 3):
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sqlite3, sys; connection = sqlite3.connect(sys.argv[1]); "
                    "connection.execute('INSERT INTO facts VALUES (?, ?)', "
                    "(int(sys.argv[2]), 'y' * 5000)); "
                    "connection.commit(); connection.close()",
                    str(path),
                    str(asset),
                ],
                check=True,
                timeout=10,
            )
            assert connection.execute("SELECT id FROM facts ORDER BY id").fetchall() == [
                (number,) for number in range(1, asset + 1)
            ]
