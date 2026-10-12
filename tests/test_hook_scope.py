"""The pre-commit hook runs the unit tests a change can affect, and the whole suite when unsure.

The selection runs against a small repository built here: a package, the tests that
import or execute it, and a map of which test files executed which source files.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "hook_scope.py"


@pytest.fixture(scope="module")
def hook_scope():
    spec = importlib.util.spec_from_file_location("hook_scope", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # dataclasses resolve the owning module by name
    spec.loader.exec_module(module)
    return module


LETTERS = """\
SIZE = 3


def upper(text):
    return text.upper()
"""

FILES = {
    "src/immich_memories/__init__.py": "from immich_memories.config import Config\n",
    "src/immich_memories/config.py": "class Config:\n    width = 1\n",
    "src/immich_memories/titles/__init__.py": "",
    "src/immich_memories/titles/letters.py": LETTERS,
    # Reads SIZE while it is imported: a change to SIZE reaches what render builds.
    "src/immich_memories/titles/render.py": (
        "from immich_memories.titles.letters import SIZE\n\nWIDTH = SIZE * 2\n\n\n"
        "def render():\n    return WIDTH\n"
    ),
    # Never imports letters, but uses what render built from it.
    "src/immich_memories/layout.py": (
        "def layout():\n    from immich_memories.titles.render import WIDTH\n\n    return WIDTH\n"
    ),
    # Imports `upper` on load; a test imports it inside a test body, so only running sees it.
    "src/immich_memories/shouting.py": "from immich_memories.titles.letters import upper\n",
    # Reads the prompt package's data only when called.
    "src/immich_memories/prompts/__init__.py": "",
    "src/immich_memories/prompts/story.md": "Tell the story.\n",
    "src/immich_memories/reader.py": (
        "from importlib.resources import files\n\n\n"
        "def prompt():\n    return files('immich_memories.prompts').joinpath('story.md').read_text()\n"
    ),
    "src/immich_memories/unread.yaml": "nobody: reads me\n",
    "docs-site/docs/guide.md": "A page.\n",
    "docs-site/docs/other.md": "Another page.\n",
    "tests/__init__.py": "",
    "tests/conftest.py": "",
    "tests/helpers.py": "from immich_memories.titles.letters import upper\n",
    "tests/test_letters.py": "from immich_memories.titles.letters import upper\n",
    "tests/test_render.py": "from immich_memories.titles import render\n",
    "tests/test_layout.py": "from immich_memories import layout\n",
    "tests/test_shouting.py": "def test_shouts():\n    from immich_memories import shouting\n",
    "tests/test_reader.py": "from immich_memories import reader\n",
    "tests/test_uses_helper.py": "from tests.helpers import upper\n",
    "tests/test_guide.py": "PAGE = 'docs-site/docs/guide.md'\n",
    "tests/test_walks.py": "REPO = None\nFILES = 'REPO.rglob(\"*\")'\n",
    "tests/test_child.py": "import sys\nCMD = [sys.executable, '-m', 'immich_memories']\n",
    # Runs itself in a child (runpy): reaches the app only through the helper it imports.
    "tests/test_child_via_helper.py": "import sys\nfrom tests.helpers import upper\nCMD = [sys.executable, __name__]\n",
    # A child that runs nothing of the app.
    "tests/test_child_tool.py": "import sys\nCMD = [sys.executable, '-c', 'print(1)']\n",
    "tests/e2e/__init__.py": "",
    "tests/e2e/fake_immich.py": "",
    "pyproject.toml": "",
    **{f"tests/test_unrelated_{n}.py": "" for n in range(12)},
}

EXECUTED = {
    "src/immich_memories/titles/letters.py": ["tests/test_letters.py", "tests/test_uses_helper.py"],
    "src/immich_memories/titles/render.py": ["tests/test_render.py"],
    "src/immich_memories/layout.py": ["tests/test_layout.py"],
    "src/immich_memories/reader.py": ["tests/test_reader.py"],
    "src/immich_memories/config.py": ["tests/test_unrelated_0.py"],
}
ALWAYS = {"tests/test_walks.py"}  # walks the repository: runs on every commit
# Start the app in a child, directly or through a helper: they run on every source change.
ON_SOURCE = {"tests/test_child.py", "tests/test_child_via_helper.py"}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for path, text in FILES.items():
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
    return tmp_path


@pytest.fixture
def test_map(hook_scope):
    tests = tuple(sorted({test for found in EXECUTED.values() for test in found}))
    return hook_scope.TestMap(
        tree="0" * 40,
        tests=tests,
        executed_by={
            path: tuple(tests.index(t) for t in found) for path, found in EXECUTED.items()
        },
        at_import={"src/immich_memories/titles/letters.py": (1,)},
    )


def _edit(repo: Path, path: str, old: str, new: str) -> dict[str, str]:
    file = repo / path
    before = file.read_text(encoding="utf-8")
    file.write_text(before.replace(old, new), encoding="utf-8")
    return {path: before}


def test_a_change_inside_a_function_runs_the_tests_that_executed_it(hook_scope, repo, test_map):
    before = _edit(
        repo, "src/immich_memories/titles/letters.py", "text.upper()", "text.upper().strip()"
    )

    selection = hook_scope.select(list(before), repo, test_map, before)

    assert (
        set(selection.tests)
        == {"tests/test_letters.py", "tests/test_uses_helper.py"} | ALWAYS | ON_SOURCE
    )


def test_a_change_at_import_runs_what_reads_it_on_import_and_its_users(hook_scope, repo, test_map):
    before = _edit(repo, "src/immich_memories/titles/letters.py", "SIZE = 3", "SIZE = 4")

    selection = hook_scope.select(list(before), repo, test_map, before)

    # render reads SIZE on import, so WIDTH changes: render's tests and layout's (which
    # reads WIDTH) can see it, as can the files that import letters (test_letters,
    # helpers, and through helpers test_uses_helper).
    assert (
        set(selection.tests)
        == {
            "tests/test_letters.py",
            "tests/test_uses_helper.py",
            "tests/test_render.py",
            "tests/test_layout.py",
        }
        | ALWAYS
        | ON_SOURCE
    )


def test_what_the_package_loads_on_start_runs_everything(hook_scope, repo, test_map):
    before = _edit(repo, "src/immich_memories/config.py", "width = 1", "width = 2")

    selection = hook_scope.select(list(before), repo, test_map, before)

    assert selection.everything
    assert "starts" in selection.reason


@pytest.mark.parametrize(
    "path",
    ["pyproject.toml", "tests/conftest.py", "tests/e2e/fake_immich.py", "scripts/hook_scope.py"],
)
def test_shared_test_infrastructure_and_build_files_run_everything(
    hook_scope, repo, test_map, path
):
    selection = hook_scope.select([path], repo, test_map, {})

    assert selection.everything
    assert path in selection.reason


def test_a_source_change_without_a_map_runs_everything(hook_scope, repo):
    before = _edit(repo, "src/immich_memories/titles/letters.py", "text.upper()", "text.lower()")

    selection = hook_scope.select(list(before), repo, None, before)

    assert selection.everything
    assert "no test map" in selection.reason


def test_a_docs_page_runs_the_tests_that_name_it(hook_scope, repo):
    selection = hook_scope.select(["docs-site/docs/guide.md"], repo, None, {})

    assert set(selection.tests) == {"tests/test_guide.py"} | ALWAYS


def test_a_page_no_test_names_runs_only_the_repository_walkers(hook_scope, repo):
    selection = hook_scope.select(["docs-site/docs/other.md"], repo, None, {})

    assert set(selection.tests) == ALWAYS


def test_package_data_runs_the_tests_of_the_code_that_reads_it(hook_scope, repo, test_map):
    selection = hook_scope.select(["src/immich_memories/prompts/story.md"], repo, test_map, {})

    assert set(selection.tests) == {"tests/test_reader.py"} | ALWAYS | ON_SOURCE


def test_source_data_nothing_names_runs_everything(hook_scope, repo, test_map):
    selection = hook_scope.select(["src/immich_memories/unread.yaml"], repo, test_map, {})

    assert selection.everything
    assert "unread.yaml" in selection.reason


def test_a_changed_test_runs_and_a_changed_helper_runs_its_users(hook_scope, repo):
    selection = hook_scope.select(["tests/test_letters.py", "tests/helpers.py"], repo, None, {})

    assert (
        set(selection.tests)
        == {
            "tests/test_letters.py",
            "tests/test_uses_helper.py",
            "tests/test_child_via_helper.py",
        }
        | ALWAYS
    )


def test_a_source_module_no_test_reaches_runs_everything(hook_scope, repo, test_map):
    (repo / "src/immich_memories/lonely.py").write_text("def alone():\n    return 1\n")
    before = {"src/immich_memories/lonely.py": "def alone():\n    return 0\n"}
    (repo / "tests/test_walks.py").write_text("")  # no walker, no child: nothing reaches it
    (repo / "tests/test_child.py").write_text("")
    (repo / "tests/test_child_via_helper.py").write_text("")

    selection = hook_scope.select(["src/immich_memories/lonely.py"], repo, test_map, before)

    assert selection.everything
    assert "lonely.py" in selection.reason


def test_a_selection_over_half_the_suite_runs_everything(hook_scope, repo):
    changed = [f"tests/test_unrelated_{n}.py" for n in range(12)]

    selection = hook_scope.select(changed, repo, None, {})

    assert selection.everything


def test_a_file_that_does_not_parse_runs_everything(hook_scope, repo, test_map):
    (repo / "tests/test_letters.py").write_text("def broken(:\n")

    selection = hook_scope.select(["docs-site/docs/guide.md"], repo, test_map, {})

    assert selection.everything
    assert "does not parse" in selection.reason


@pytest.mark.parametrize(
    ("before", "after", "on_import"),
    [
        ("def f():\n    return 1\n", "def f():\n    return 2\n", False),
        ("def f():\n    return 1\n", "def f(x=0):\n    return 1\n", True),  # signature
        ("def f():\n    return 1\n", "def f():\n    return 1\n\n\ndef g():\n    return 2\n", True),
        ("X = 1\n", "X = 2\n", True),
        ("# old\nX = 1\n", "# new\nX = 1\n", False),  # a comment runs nothing
        ("@d\ndef f():\n    return 1\n", "@e\ndef f():\n    return 1\n", True),  # decorator
        ("def f():\n    return 1\n", None, True),  # deleted
    ],
)
def test_import_level_changes_are_told_from_function_bodies(hook_scope, before, after, on_import):
    assert hook_scope.changes_at_import(before, after, ()) is on_import


def test_a_body_line_that_ran_at_import_counts_as_import_level(hook_scope):
    # A function called while its module loads: line 2 ran outside any test.
    before, after = "def f():\n    return 1\nX = f()\n", "def f():\n    return 2\nX = f()\n"

    assert hook_scope.changes_at_import(before, after, (2,)) is True


def test_the_map_records_which_test_files_ran_which_source_files(hook_scope, tmp_path):
    from coverage import CoverageData

    source = tmp_path / "src" / "immich_memories" / "a.py"
    source.parent.mkdir(parents=True)
    source.write_text("X = 1\ndef f():\n    return X\n")
    data = CoverageData(basename=str(tmp_path / ".coverage"))
    data.set_context("")
    data.add_arcs({str(source): {(-1, 1), (1, 2)}})
    data.set_context("tests/test_a.py::test_f|run")
    data.add_arcs({str(source): {(-2, 3), (3, -2)}})
    data.set_context("tests/test_b.py::TestB::test_g|setup")
    data.add_arcs({str(source): {(-2, 3)}})
    data.write()

    test_map = hook_scope.map_from_coverage(tmp_path / ".coverage", tmp_path, "abc")

    assert test_map.tests_of("src/immich_memories/a.py") == {"tests/test_a.py", "tests/test_b.py"}
    assert test_map.at_import["src/immich_memories/a.py"] == (1, 2)
    assert hook_scope.TestMap.from_json(test_map.to_json()) == test_map


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_the_change_counts_everything_since_the_mapped_tree(hook_scope, repo, test_map):
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    mapped = _git(repo, "rev-parse", "HEAD^{tree}").strip()
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _edit(repo, "docs-site/docs/guide.md", "A page.", "A new page.")
    _git(repo, "commit", "-qam", "since the map")
    _edit(repo, "src/immich_memories/reader.py", "story.md", "tale.md")
    _git(repo, "add", "-A")

    found = hook_scope.changed_paths(
        repo, "origin/main", dataclasses.replace(test_map, tree=mapped)
    )

    assert found == ["docs-site/docs/guide.md", "src/immich_memories/reader.py"]


def test_the_map_is_saved_where_every_worktree_finds_it(hook_scope, repo, test_map):
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    tree = _git(repo, "write-tree").strip()
    worktree = repo.parent / "other-worktree"
    _git(repo, "worktree", "add", "-q", "--detach", str(worktree))
    saved = dataclasses.replace(test_map, tree=tree)

    hook_scope.save_map(saved, repo)

    assert hook_scope.load_map(worktree) == saved
    assert hook_scope.map_location(repo) == (repo / ".git" / hook_scope.MAP_FILE).resolve()


def test_a_map_whose_tree_is_gone_is_no_map(hook_scope, repo, test_map):
    _git(repo, "init", "-q", "-b", "main")
    hook_scope.save_map(test_map, repo)  # tree 000...: not an object in this repository

    assert hook_scope.load_map(repo) is None


def test_hook_full_runs_everything(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "tests"],
        cwd=ROOT,
        env={**os.environ, "HOOK_FULL": "1"},
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "all"
    assert "HOOK_FULL=1" in result.stderr


# ── Which gates the hook runs ───────────────────────────────────────────────

PYTHON_GATES = {
    "mypy",
    "file-length",
    "refurb",
    "complexity",
    "dead-code",
    "security-lint",
    "cognitive-complexity",
    "dep-check",
    "arch-check",
    "duplication",
}
EVERY_COMMIT = {"gitleaks", "private-terms", "hook-tests"}


def _gates_for(staged: list[str]) -> set[str]:
    """The pre-commit hooks a commit of `staged` runs, by pre-commit's own rules."""
    import re

    import yaml

    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    running = set()
    for repo in config["repos"]:
        for hook in repo["hooks"]:
            if "commit-msg" in hook.get("stages", ["pre-commit"]):
                continue
            if repo["repo"] != "local" and not hook.get("always_run"):
                continue  # ruff's own manifest limits it to Python files
            files = re.compile(hook.get("files", ""))
            types = hook.get("types", [])
            matched = [
                path
                for path in staged
                if files.search(path)
                and (not types or ("python" in types and path.endswith(".py")))
            ]
            if hook.get("always_run") or matched:
                running.add(hook["id"])
    return running


def test_a_source_commit_runs_the_python_gates_and_the_references_built_from_source():
    gates = _gates_for(["src/immich_memories/titles/letters.py"])

    assert (
        PYTHON_GATES | EVERY_COMMIT | {"critique", "docs-cli-check", "docs-config-check"} <= gates
    )
    assert not {"docs-build", "docs-voice", "workflow-guard", "compose-check", "web-check"} & gates


def test_a_test_only_commit_skips_the_gates_that_read_only_source():
    gates = _gates_for(["tests/test_title_letter_case.py"])

    assert not PYTHON_GATES & gates
    assert EVERY_COMMIT | {"critique", "feature-check"} <= gates


def test_a_docs_commit_runs_the_docs_gates_and_no_python_gate():
    gates = _gates_for(["docs-site/docs/contribute/ci.md"])

    assert EVERY_COMMIT | {"docs-build", "docs-voice", "docs-commands", "feature-check"} <= gates
    assert not PYTHON_GATES & gates


def test_a_workflow_commit_runs_the_workflow_guard():
    gates = _gates_for([".github/workflows/ci.yml"])

    assert gates == EVERY_COMMIT | {"workflow-guard"}


def test_a_build_file_commit_runs_the_python_gates():
    assert _gates_for(["pyproject.toml"]) >= PYTHON_GATES
    assert _gates_for([".pre-commit-config.yaml"]) >= PYTHON_GATES


def test_the_privacy_and_secrets_gates_run_on_every_commit():
    assert _gates_for(["a-new-top-level-file.txt"]) >= EVERY_COMMIT


def test_the_web_client_runs_its_check():
    assert "web-check" in _gates_for(["web/src/lib/RenderPanel.svelte"])
    assert "web-check" in _gates_for(["src/immich_memories/web/job_routes.py"])


def test_a_removed_name_runs_the_tests_that_load_its_importers(hook_scope, repo, test_map):
    # shouting imports `upper` on load: renaming it breaks shouting's import, which
    # test_shouting meets only inside its test body (collection never imports it).
    before = _edit(repo, "src/immich_memories/titles/letters.py", "def upper(", "def shout(")

    selection = hook_scope.select(list(before), repo, test_map, before)

    assert "tests/test_shouting.py" in selection.tests


def test_a_body_change_keeps_every_name_and_skips_their_importers(hook_scope, repo, test_map):
    before = _edit(repo, "src/immich_memories/titles/letters.py", "text.upper()", "text.title()")

    selection = hook_scope.select(list(before), repo, test_map, before)

    assert "tests/test_shouting.py" not in selection.tests


@pytest.mark.parametrize(
    ("source", "fails"),
    [
        ("VALUE = 1\n", False),
        ("raise RuntimeError('broken on import')\n", True),
        ("from immich_memories.missing_module import thing\n", True),  # ours: a real break
        ("import a_package_this_machine_lacks\n", False),  # an optional extra
    ],
)
def test_the_import_check_fails_a_module_that_no_longer_imports(
    hook_scope, tmp_path, source, fails
):
    package = tmp_path / "src" / "immich_memories"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "changed.py").write_text(source)

    failures = hook_scope.import_failures(tmp_path, ["src/immich_memories/changed.py"])

    assert bool(failures) is fails
