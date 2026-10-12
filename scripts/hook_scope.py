#!/usr/bin/env python3
"""Pick the unit tests a commit can affect, for the pre-commit hook.

The hook used to run the whole unit suite on every Python commit. Here it runs the
test files that can see what changed, read from a coverage map: which test files
executed which source files on the last green full run. Static imports are no
guide in this codebase, since lazy imports put almost every module within reach
of every test; what a test executed is.

What reaches which tests:

- A source module whose change stays inside function bodies reaches the test files
  that executed it. A change at import level (a signature, a constant, a decorator,
  an import, a new or removed function) or to a line that runs at import time also
  reaches every module that imports it at import time, the modules that import those,
  and the tests that executed any of them. A name it no longer defines reaches every
  test that imports, at any depth, a module whose load imports that name. A change to
  what the package itself imports at start-up reaches everything.
- Tests that start the app in a child interpreter run on every source change: the
  map cannot see into the child.
- Any other file (a doc page, a workflow, a script, a prompt) reaches the files that
  name it: its path, its file name, or its directory as a quoted string. A source
  module that names it inside a function runs the tests that executed it; one that
  names it at module level counts as changed at import level. Tests that walk the
  repository (`git ls-files`, `rglob`, `os.walk`) run on every commit.
- A changed test file runs; a conftest.py runs the tests below it.

The map is recorded after a green full run, keyed by the git tree that was tested,
and kept in the git directory every worktree shares. Everything that changed since
that tree counts as changed, so a map from another branch or an older main stays
sound; it only selects more.

Anything this cannot vouch for runs the whole suite: no map yet, the shared test
fixtures, build and dependency files, the hook itself, a source file nothing reads,
a source module no test reaches, a selection over half the suite, a file that does
not parse, or git failing to say what changed. `HOOK_FULL=1` runs it all on purpose.

Usage:
    python scripts/hook_scope.py tests [--base origin/main]
    python scripts/hook_scope.py record [--coverage .coverage]
    python scripts/hook_scope.py import-check [--base origin/main]

`tests` prints `all`, nothing, or the test files to run on one line; the reason goes
to stderr. `record` stores the map from a full run's coverage data with test contexts.
`import-check` imports each changed source module in a fresh interpreter and fails when
one no longer imports.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import os
import re
import sqlite3
import subprocess  # nosec B404 - runs git with fixed arguments
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAP_FILE = "immich-memories-hook/test-map.json"
MAP_VERSION = 1

# Changing one of these can change any test's outcome, so the whole suite runs.
FULL_SUITE = (
    "pyproject.toml",
    "uv.lock",
    "Makefile",
    ".python-version",
    ".pre-commit-config.yaml",
    "scripts/hook_scope.py",
    "tests/__init__.py",
    "tests/conftest.py",
    "tests/immich_fakes.py",
    "tests/e2e/fake_*.py",
)

# Python trees whose modules import each other by dotted name: (directory, package).
PACKAGE_ROOTS = (
    ("src/immich_memories", "immich_memories"),
    ("services/inference/immich_memories_inference", "immich_memories_inference"),
    ("services/render-worker/immich_memories_render_worker", "immich_memories_render_worker"),
    ("tests", "tests"),
)
PACKAGE_INIT = "src/immich_memories/__init__.py"
SOURCE_ROOTS = ("src/", "services/")
# Scripts run with their own directory on sys.path, so they import each other bare.
SCRIPTS = "scripts"
DOTTED = re.compile(r"\b(?:immich_memories(?:_inference|_render_worker)?|tests)(?:\.[A-Za-z_]\w*)+")
WALKS = ("ls-files", "rglob(", "os.walk(", 'glob("**', "glob('**")
# A walk only reaches committed files when it starts from the repository, not tmp_path.
FROM_THE_REPO = ("REPO", "ROOT", "parents[", "__file__", "_PACKAGE", "ls-files")
CHILD_PROCESS = ("sys.executable", '"uv", "run"')
APP_PACKAGES = ("immich_memories",)
APP_MARKERS = ("immich_memories", "immich-memories")
UNNAMED = {"__init__.py", "__main__.py", "conftest.py"}
# Top-level trees every contract test names; naming one says nothing about a file in it.
GENERIC_DIRS = {"src", "tests", "services", "scripts", "immich_memories"}
# Directory paths so many tests name that naming one says nothing about a file below.
ROOT_DIRS = {
    "src/immich_memories",
    "docs-site/docs",
    "docs-site/static",
    "tests/integration",
    "tests/e2e",
}
# Over this share of the suite, a full run costs little more and records a fresh map.
MOST_OF_THE_SUITE = 0.5


@dataclass(frozen=True)
class Selection:
    everything: bool
    reason: str
    tests: tuple[str, ...] = ()

    def render(self) -> str:
        return "all" if self.everything else " ".join(self.tests)


def _all(reason: str) -> Selection:
    return Selection(everything=True, reason=reason)


class _RunEverything(Exception):
    """Raised deep in the selection when only the whole suite is safe."""


# ── The modules and what they import ────────────────────────────────────────


@dataclass
class _Module:
    path: str
    name: str
    text: str
    loads: set[str] = field(default_factory=set)  # modules run when this one is imported
    uses: set[str] = field(default_factory=set)  # modules whose names it reads, anywhere
    derives: set[str] = field(default_factory=set)  # modules whose names it reads on import
    bindings: dict[str, set[str]] = field(default_factory=dict)  # name -> where it comes from
    stars: set[str] = field(default_factory=set)  # `from x import *`


def _prefixes(name: str) -> Iterator[str]:
    parts = name.split(".")
    for end in range(1, len(parts) + 1):
        yield ".".join(parts[:end])


def module_name(path: str) -> str | None:
    for directory, package in PACKAGE_ROOTS:
        if path == f"{directory}/__init__.py":
            return package
        if path.startswith(f"{directory}/") and path.endswith(".py"):
            dotted = path[len(directory) + 1 : -3].replace("/", ".").removesuffix(".__init__")
            return f"{package}.{dotted}"
    parent, _, base = path.rpartition("/")
    if parent == SCRIPTS and base.endswith(".py"):
        return f"{SCRIPTS}:{base[:-3]}"
    return None


def _is_test(path: str) -> bool:
    base = path.rpartition("/")[2]
    return path.startswith("tests/") and base.startswith("test_") and base.endswith(".py")


def _is_source(path: str) -> bool:
    return path.startswith(SOURCE_ROOTS)


class _Imports(ast.NodeVisitor):
    """What a module imports, and which imported names it reads while it is imported.

    Module level here means what runs on import: the module body, class bodies,
    decorators, default values and annotations. Function bodies run later.
    """

    def __init__(self, name: str, is_package: bool) -> None:
        self.package = name if is_package else name.rpartition(".")[0]
        self.loads: set[str] = set()
        self.uses: set[str] = set()
        self.read_on_import: set[str] = set()
        self.bindings: dict[str, set[str]] = defaultdict(set)
        self.stars: set[str] = set()
        self._depth = 0

    def _imported(self, local: str, targets: Iterable[str]) -> None:
        targets = set(targets)
        self.uses |= targets
        if self._depth == 0:
            self.loads |= targets
            self.bindings[local] |= targets

    def _later(self, nodes: Iterable[ast.AST]) -> None:
        self._depth += 1
        for node in nodes:
            self.visit(node)
        self._depth -= 1

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for expression in (*node.decorator_list, node.args, node.returns):
            if expression is not None:
                self.visit(expression)
        self._later(node.body)

    visit_FunctionDef = visit_AsyncFunctionDef = _function

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.visit(node.args)
        self._later([node.body])

    def visit_If(self, node: ast.If) -> None:
        if "TYPE_CHECKING" in ast.unparse(node.test):
            self._later([*node.body, *node.orelse])
        else:
            self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            target = alias.name if alias.asname else local
            self._imported(local, {target, alias.name})

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = node.module or ""
        if node.level:
            anchor = self.package.split(".")
            anchor = anchor[: len(anchor) - (node.level - 1)] if node.level > 1 else anchor
            base = ".".join([*anchor, base] if base else anchor)
        for alias in node.names:
            if alias.name == "*":
                self._imported("*", {base})
                if self._depth == 0:
                    self.stars.add(base)
            else:
                self._imported(alias.asname or alias.name, {f"{base}.{alias.name}"})

    def visit_Name(self, node: ast.Name) -> None:
        if self._depth == 0 and isinstance(node.ctx, ast.Load):
            self.read_on_import.add(node.id)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            self.uses.update(DOTTED.findall(node.value))


def _python_files(repo: Path) -> Iterator[str]:
    for directory, _ in PACKAGE_ROOTS:
        for file in sorted((repo / directory).rglob("*.py")):
            yield file.relative_to(repo).as_posix()
    for file in sorted((repo / SCRIPTS).glob("*.py")):
        yield file.relative_to(repo).as_posix()


def _ancestors(directory: str) -> Iterator[str]:
    parts = directory.split("/") if directory else []
    for end in range(1, len(parts) + 1):
        yield "/".join(parts[:end])


class _Graph:
    """Every module in the trees above, what it imports, and its text for name lookups."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.modules: dict[str, _Module] = {}
        self.by_name: dict[str, _Module] = {}
        scripts = {file.stem for file in (repo / SCRIPTS).glob("*.py")}
        raw = {}
        for path in _python_files(repo):
            if (name := module_name(path)) is not None:
                raw[path] = self._parse(path, name)
        for path, visitor in raw.items():
            self._link(self.modules[path], visitor, scripts)
        self.loaded_by = self._reverse("loads")
        self.users = self._reverse("uses")
        self.derived_by = self._reverse("derives")

    def _parse(self, path: str, name: str) -> _Imports:
        text = (self.repo / path).read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError as error:
            raise _RunEverything(f"{path} does not parse") from error
        visitor = _Imports(name, path.endswith("__init__.py"))
        visitor.visit(tree)
        module = _Module(path=path, name=name, text=text, stars=visitor.stars)
        module.bindings = dict(visitor.bindings)
        self.modules[path] = self.by_name[name] = module
        return visitor

    def _link(self, module: _Module, visitor: _Imports, scripts: set[str]) -> None:
        def resolve(names: Iterable[str]) -> set[str]:
            return {found for name in names for found in self._origin(name, scripts)}

        module.loads = {
            prefix for name in visitor.loads for prefix in _prefixes(name) if prefix in self.by_name
        }
        module.uses = resolve(visitor.uses)
        read = visitor.read_on_import & set(visitor.bindings)
        module.derives = resolve(target for name in read for target in visitor.bindings[name])

    def _origin(self, name: str, scripts: set[str], depth: int = 0) -> set[str]:
        """The modules a dotted name lives in, following re-exports: `pkg.Name` -> `pkg.mod`."""
        top = name.split(".")[0]
        if top in scripts:
            return {f"{SCRIPTS}:{top}"}
        module = next((p for p in reversed(list(_prefixes(name))) if p in self.by_name), None)
        if module is None:
            return set()
        found = {module}
        attribute = name[len(module) + 1 :].split(".")[0]
        owner = self.by_name[module]
        if attribute and depth < 8:
            for target in owner.bindings.get(attribute, ()):
                found |= self._origin(target, scripts, depth + 1)
            if attribute not in owner.bindings:
                for star in owner.stars:
                    found |= self._origin(f"{star}.{attribute}", scripts, depth + 1)
        return found

    def _reverse(self, edges: str) -> dict[str, set[str]]:
        reverse: dict[str, set[str]] = defaultdict(set)
        for path, module in self.modules.items():
            for name in getattr(module, edges):
                reverse[name].add(path)
        return reverse

    def loaded_on_start(self) -> set[str]:
        """What the package and the root conftest load on import: every test runs it."""
        found: set[str] = set()
        queue = [PACKAGE_INIT, "tests/conftest.py"]
        while queue:
            path = queue.pop()
            if path in found or path not in self.modules:
                continue
            found.add(path)
            queue.extend(self.by_name[name].path for name in self.modules[path].loads)
        return found

    def naming(self, path: str) -> set[str]:
        """Files that name `path`: in full, by file name, by a directory path above it, or
        (data in the source tree) by its directory quoted, the way package data is read."""
        parent, _, base = path.rpartition("/")
        needles = [path] if base in UNNAMED else [path, base]
        # A test that scans a directory names its path: src/immich_memories/audio.
        needles += [a for a in _ancestors(parent) if a.count("/") >= 1 and a not in ROOT_DIRS]
        is_data = not path.endswith(".py")
        if is_data:
            top = path.split("/")[0]
            if top not in GENERIC_DIRS and top != base:
                needles += [f'"{top}"', f"'{top}'"]
            directory = parent.rpartition("/")[2]
            if _is_source(path) and directory and directory not in GENERIC_DIRS:
                needles += [f'"{directory}"', f"'{directory}'"]
        named = {
            file
            for file, module in self.modules.items()
            if file != path and any(needle in module.text for needle in needles)
        }
        # Data inside a package is read through the package's dotted name (importlib.resources).
        package = module_name(f"{parent}/__init__.py")
        if is_data and package in self.by_name:
            named |= self.users.get(package, set())
        return named

    def names_it_on_import(self, reader: str, path: str) -> bool:
        """Whether `reader` names `path` outside a function body, so it may read it on import."""
        text = self.modules[reader].text
        parent, _, base = path.rpartition("/")
        needles = [needle for needle in (path, base, parent.rpartition("/")[2]) if needle]
        body = _body_lines(text)
        return any(
            number not in body
            for number, line in enumerate(text.splitlines(), start=1)
            if any(needle in line for needle in needles)
        )

    def child_processes(self) -> set[str]:
        """Test-tree files that start a Python child able to run app code.

        The map cannot see into a child, so these run on every source change. A child
        reaches the app when the test file, or a test module it imports, names or
        imports the app, or runs a script that imports it. A child may run the test
        file itself (`runpy`), so its imports count.
        """
        app_scripts = [
            module.path.rpartition("/")[2]
            for module in self.modules.values()
            if module.path.startswith(f"{SCRIPTS}/")
            and any(name.startswith(APP_PACKAGES) for name in module.uses)
        ]
        reaching: dict[str, bool] = {}

        def reaches_app(path: str) -> bool:
            if path not in reaching:
                reaching[path] = False  # a cycle adds nothing
                module = self.modules[path]
                reaching[path] = (
                    any(marker in module.text for marker in (*APP_MARKERS, *app_scripts))
                    or any(name.startswith(APP_PACKAGES) for name in module.uses)
                    or any(
                        reaches_app(self.by_name[name].path)
                        for name in module.uses
                        if name.startswith("tests") and name in self.by_name
                    )
                )
            return reaching[path]

        return {file for file in self.matching(CHILD_PROCESS) if reaches_app(file)}

    def matching(self, *requirements: tuple[str, ...]) -> set[str]:
        """Test-tree files whose text holds one pattern of each requirement."""
        return {
            file
            for file, module in self.modules.items()
            if file.startswith("tests/")
            and all(
                any(pattern in module.text for pattern in patterns) for patterns in requirements
            )
        }


# ── The coverage map ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TestMap:
    """Which test files executed which source files, on the green run of one git tree."""

    tree: str
    tests: tuple[str, ...]
    executed_by: dict[str, tuple[int, ...]]  # source path -> indexes into tests
    at_import: dict[str, tuple[int, ...]]  # source path -> lines run outside any test

    def tests_of(self, path: str) -> set[str]:
        return {self.tests[index] for index in self.executed_by.get(path, ())}

    def to_json(self) -> dict:
        return {
            "version": MAP_VERSION,
            "tree": self.tree,
            "tests": list(self.tests),
            "executed_by": {path: list(ids) for path, ids in self.executed_by.items()},
            "at_import": {path: list(lines) for path, lines in self.at_import.items()},
        }

    @classmethod
    def from_json(cls, data: dict) -> TestMap | None:
        if data.get("version") != MAP_VERSION:
            return None
        return cls(
            tree=data["tree"],
            tests=tuple(data["tests"]),
            executed_by={path: tuple(ids) for path, ids in data["executed_by"].items()},
            at_import={path: tuple(lines) for path, lines in data["at_import"].items()},
        )


def map_from_coverage(coverage_file: Path, repo: Path, tree: str) -> TestMap:
    """Read a coverage data file recorded with `--cov-context=test`."""
    db = sqlite3.connect(f"file:{coverage_file}?mode=ro", uri=True)
    try:
        contexts = dict(db.execute("select id, context from context"))
        files = {
            file_id: _relative(path, repo)
            for file_id, path in db.execute("select id, path from file")
        }
        executed: dict[str, set[str]] = defaultdict(set)
        at_import: dict[str, set[int]] = defaultdict(set)
        for file_id, context_id, start, end in db.execute(
            "select file_id, context_id, fromno, tono from arc"
        ):
            _note(files[file_id], contexts[context_id], (start, end), executed, at_import)
        for file_id, context_id in db.execute("select distinct file_id, context_id from line_bits"):
            _note(files[file_id], contexts[context_id], (), executed, at_import)
    finally:
        db.close()
    tests = tuple(sorted(set().union(*executed.values()))) if executed else ()
    index = {test: number for number, test in enumerate(tests)}
    return TestMap(
        tree=tree,
        tests=tests,
        executed_by={
            path: tuple(sorted(index[t] for t in found)) for path, found in executed.items()
        },
        at_import={path: tuple(sorted(lines)) for path, lines in at_import.items()},
    )


def _relative(path: str, repo: Path) -> str:
    try:
        return Path(path).resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return path


def _note(
    path: str,
    context: str,
    arc: tuple[int, ...],
    executed: dict[str, set[str]],
    at_import: dict[str, set[int]],
) -> None:
    if context:
        executed[path].add(context.split("::")[0])
    else:
        at_import[path].update(line for line in arc if line > 0)


def map_location(repo: Path) -> Path:
    common = _git(repo, "rev-parse", "--git-common-dir")[0]
    return (repo / common).resolve() / MAP_FILE


def load_map(repo: Path) -> TestMap | None:
    try:
        data = json.loads(map_location(repo).read_text(encoding="utf-8"))
        test_map = TestMap.from_json(data)
        if test_map is not None:
            _git(repo, "cat-file", "-e", test_map.tree)  # gone after a gc: record a new one
        return test_map
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        return None


def save_map(test_map: TestMap, repo: Path) -> Path:
    target = map_location(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{target.name}.{os.getpid()}")
    partial.write_text(json.dumps(test_map.to_json()), encoding="utf-8")
    partial.replace(target)  # atomic: worktrees committing at once never read half a map
    return target


# ── What changed, and how ───────────────────────────────────────────────────


def _body_lines(source: str) -> set[int]:
    """Lines inside function bodies: they run when the function is called, not on import."""
    lines: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            lines.update(range(node.body[0].lineno, (node.end_lineno or node.body[0].lineno) + 1))
    return lines


def top_level_names(source: str | None) -> set[str]:
    """The names a module defines when it is imported: what `from module import name` can find."""
    if source is None:
        return set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names: set[str] = set()
    queue: list[ast.stmt] = list(tree.body)
    while queue:
        node = queue.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in node.names if a.name != "*")
        elif isinstance(node, (ast.If, ast.Try)):
            queue += [
                *node.body,
                *node.orelse,
                *getattr(node, "handlers", []),
                *getattr(node, "finalbody", []),
            ]
        elif isinstance(node, ast.ExceptHandler):
            queue += node.body
        else:
            targets = getattr(node, "targets", None) or [getattr(node, "target", None)]
            for target in filter(None, targets):
                names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
    return names


def _meaningful(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def changes_at_import(before: str | None, after: str | None, ran_at_import: Iterable[int]) -> bool:
    """True when the change touches code that runs when the module is imported."""
    if before is None or after is None:
        return True
    try:
        body_before, body_after = _body_lines(before), _body_lines(after)
    except SyntaxError:
        return True
    old, new = before.splitlines(), after.splitlines()
    imported = set(ran_at_import)
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        for number in range(old_start + 1, old_end + 1):
            if _meaningful(old[number - 1]) and (number not in body_before or number in imported):
                return True
        for number in range(new_start + 1, new_end + 1):
            if _meaningful(new[number - 1]) and number not in body_after:
                return True
    return False


# ── Selection ───────────────────────────────────────────────────────────────


@dataclass
class _Selector:
    graph: _Graph
    test_map: TestMap | None
    before: dict[str, str | None]  # source text at the map's tree, by path
    tests: set[str] = field(default_factory=set)
    reached: set[str] = field(default_factory=set)
    named_seen: set[str] = field(default_factory=set)
    on_start: set[str] = field(default_factory=set)

    def run_tests_reaching(self, files: Iterable[str], *, readers: bool = False) -> None:
        """Select the tests among `files`, below their conftests, and importing their helpers.

        With `readers`, the test files themselves read the change: a test that imports
        one of them borrows its helpers, not its reads, so the selection stops there.
        """
        queue = [file for file in files if file.startswith("tests/")]
        while queue:
            path = queue.pop()
            if path in self.reached:
                continue
            self.reached.add(path)
            if _is_test(path):
                self.tests.add(path)
                if readers:
                    continue
            elif path.rpartition("/")[2] == "conftest.py":
                self.tests |= self._tests_below(path)
            name = module_name(path)
            if name is not None:
                queue.extend(p for p in self.graph.users.get(name, ()) if p.startswith("tests/"))

    def _tests_below(self, conftest: str) -> set[str]:
        directory = conftest.rpartition("/")[0] + "/"
        return {
            path for path in self.graph.modules if path.startswith(directory) and _is_test(path)
        }

    def source_changed(self, path: str) -> None:
        ran_on_import = self.test_map.at_import.get(path, ()) if self.test_map else ()
        if changes_at_import(self.before.get(path), self._text(path), ran_on_import):
            self.changed_on_import(path)
        else:
            self._executed(path)

    def changed_on_import(self, path: str) -> None:
        """An import-level change: whatever reads its names, or reads what was built from them.

        A module that reads its names while it is imported (a constant, a base class, a
        decorator, a default) carries the change on, and so on up. Every test that executed
        one of those modules, or imports one, can see it. What the package and the root
        conftest load on start reaches every test. Import-time breakage elsewhere (a
        circular import) is caught by the hook collecting the whole suite.
        """
        if path in self.on_start:
            raise _RunEverything(f"{path} loads whenever the package or the suite starts")
        derived = self._derived_from(path)
        names = {self.graph.modules[file].name for file in derived if file in self.graph.modules}
        names.add(module_name(path) or "")
        users = {user for name in names for user in self.graph.users.get(name, ())}
        for file in derived | users:
            self._executed(file)
        self.run_tests_reaching(derived | users)
        self._names_removed(path)

    def _names_removed(self, path: str) -> None:
        """A name it no longer defines breaks every module importing that name on load.

        Their own importers break on load too, lazily or not, so every test that imports
        one of them, at any depth, runs. (The hook's import check catches a module that
        no longer imports at all; collection catches a test module that does not.)
        """
        name = module_name(path)
        removed = top_level_names(self.before.get(path)) - top_level_names(self._text(path))
        if not name or not removed:
            return
        broken = {
            module.path
            for module in self.graph.modules.values()
            for targets in module.bindings.values()
            for target in targets
            if target.rpartition(".")[2] in removed and target.rpartition(".")[0] == name
        }
        loading = set()
        for file in broken:
            loading |= self._loads(file)
        names = {self.graph.modules[file].name for file in loading}
        self.run_tests_reaching({user for n in names for user in self.graph.users.get(n, ())})

    def _loads(self, path: str) -> set[str]:
        """The modules whose import runs `path`, at any depth."""
        found: set[str] = set()
        queue = [path]
        while queue:
            file = queue.pop()
            if file in found:
                continue
            found.add(file)
            name = module_name(file)
            queue.extend(self.graph.loaded_by.get(name, ()) if name else ())
        return found

    def _derived_from(self, path: str) -> set[str]:
        found: set[str] = set()
        queue = [path]
        while queue:
            file = queue.pop()
            if file in found:
                continue
            found.add(file)
            name = module_name(file)
            queue.extend(self.graph.derived_by.get(name, ()) if name else ())
        return found

    def _executed(self, path: str) -> None:
        if self.test_map is not None and _is_source(path):
            self.tests |= self.test_map.tests_of(path)

    def file_named(self, path: str) -> None:
        """A file that is not a source module: whatever names it reads it."""
        if path in self.named_seen:
            return
        self.named_seen.add(path)
        named = self.graph.naming(path)
        readers = {file for file in named if _is_source(file)}
        if _is_source(path) and not readers:
            raise _RunEverything(f"no source file names {path}, so any code may read it")
        if readers and self.test_map is None:
            raise _RunEverything(f"source code reads {path} and there is no test map yet")
        for reader in readers:
            if self.graph.names_it_on_import(reader, path):
                self.changed_on_import(reader)
            else:
                self._executed(reader)
        self.run_tests_reaching(named, readers=True)
        for script in {file for file in named if file.startswith(f"{SCRIPTS}/")}:
            self.file_named(script)

    def _text(self, path: str) -> str | None:
        file = self.graph.repo / path
        return file.read_text(encoding="utf-8", errors="replace") if file.exists() else None


def select(
    changed: list[str],
    repo: Path = REPO,
    test_map: TestMap | None = None,
    before: dict[str, str | None] | None = None,
) -> Selection:
    """Select the unit test files the changed paths can affect."""
    if not changed:
        return Selection(everything=False, reason="nothing changed")
    if full := [path for path in changed if any(fnmatch(path, pattern) for pattern in FULL_SUITE)]:
        return _all(f"{full[0]} is shared by every test")
    sources = [path for path in changed if _is_source(path) and path.endswith(".py")]
    if sources and test_map is None:
        return _all("no test map yet: this run records one")
    try:
        return _select(changed, sources, _Graph(repo), test_map, before or {})
    except _RunEverything as reason:
        return _all(str(reason))


def _select(
    changed: list[str],
    sources: list[str],
    graph: _Graph,
    test_map: TestMap | None,
    before: dict[str, str | None],
) -> Selection:
    selector = _Selector(
        graph=graph, test_map=test_map, before=before, on_start=graph.loaded_on_start()
    )
    for path in changed:
        if path in sources:
            selector.source_changed(path)
        elif module_name(path) is not None and not path.startswith(f"{SCRIPTS}/"):
            selector.run_tests_reaching([path])
        else:
            selector.file_named(path)
        if path.endswith(".py"):
            selector.run_tests_reaching(graph.naming(path), readers=True)  # read as text
    selector.run_tests_reaching(graph.matching(WALKS, FROM_THE_REPO), readers=True)
    if any(_is_source(path) for path in changed):
        selector.run_tests_reaching(graph.child_processes())
    tests = {path for path in selector.tests if (graph.repo / path).exists()}
    if sources and not tests:
        return _all(f"no test reaches {sources[0]}, so diff-cover needs every test")
    every_test = [path for path in graph.modules if _is_test(path)]
    if every_test and len(tests) > MOST_OF_THE_SUITE * len(every_test):
        return _all(f"{len(tests)} of {len(every_test)} test files can see the change")
    reason = (
        f"{len(tests)} of {len(every_test)} test files can see the {len(changed)} changed files"
    )
    return Selection(everything=False, reason=reason, tests=tuple(sorted(tests)))


# ── git ─────────────────────────────────────────────────────────────────────


def _git(repo: Path, *args: str) -> list[str]:
    result = subprocess.run(  # nosec B603 B607 - fixed git invocation
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return [line for line in result.stdout.splitlines() if line]


def changed_paths(repo: Path, base: str, test_map: TestMap | None) -> list[str]:
    """What differs from the map's tree, plus the branch's changes since `base`.

    diff-cover reads the branch against `base`, so the tests that cover an earlier
    commit on the branch (an amend, a second commit) run as well.
    """
    found = set(_git(repo, "diff", "--name-only", "--no-renames", "HEAD"))
    found |= set(_git(repo, "diff", "--name-only", "--no-renames", f"{base}...HEAD"))
    if test_map is not None:
        found |= set(_git(repo, "diff", "--name-only", "--no-renames", test_map.tree))
    return sorted(found)


def text_at(repo: Path, tree: str, paths: Iterable[str]) -> dict[str, str | None]:
    texts: dict[str, str | None] = {}
    for path in paths:
        result = subprocess.run(  # nosec B603 B607 - fixed git invocation
            ["git", "show", f"{tree}:{path}"], cwd=repo, capture_output=True, text=True
        )
        texts[path] = result.stdout if result.returncode == 0 else None
    return texts


def tested_tree(repo: Path) -> str | None:
    """The tree a full run just tested: the index, when the worktree matches it."""
    if subprocess.run(["git", "diff", "--quiet"], cwd=repo).returncode != 0:  # nosec B603 B607
        return None  # unstaged edits were tested too; no tree names that state
    return _git(repo, "write-tree")[0]


IMPORT_PATHS = ("src", "services/inference", "services/render-worker")
MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'")


def import_failures(repo: Path, paths: Iterable[str]) -> list[str]:
    """Import each changed source module in a fresh interpreter; return what failed.

    A test that imports the app inside its body (or a module that imports it lazily)
    meets a module that no longer loads only when it runs; this finds it first. The
    child gets a throwaway HOME. A missing third-party package is an optional extra
    this machine lacks, not a break.
    """
    names = [
        name
        for path in paths
        if _is_source(path)
        and path.endswith(".py")
        and (repo / path).exists()
        and (name := module_name(path))
        and not name.endswith("__main__")
    ]
    if not names:
        return []
    with tempfile.TemporaryDirectory() as home:
        env = {
            **os.environ,
            "HOME": home,
            "PYTHONPATH": os.pathsep.join(str(repo / p) for p in IMPORT_PATHS),
        }
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = pool.map(lambda name: (name, _import(name, env, repo)), names)
            return [f"{name}:\n{error}" for name, error in results if error]


def _import(name: str, env: dict[str, str], repo: Path) -> str:
    result = subprocess.run(  # nosec B603 - our own interpreter, a module name we derived
        [sys.executable, "-c", f"import {name}"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode == 0:
        return ""
    missing = MISSING_MODULE.search(result.stderr)
    if missing and not missing.group(1).startswith(APP_PACKAGES + ("tests",)):
        print(f"hook-tests: {name} needs {missing.group(1)}, not installed here", file=sys.stderr)
        return ""
    return "\n".join(result.stderr.strip().splitlines()[-12:])


def _tests_command(repo: Path, base: str) -> Selection:
    if os.environ.get("HOOK_FULL") == "1":
        return _all("HOOK_FULL=1")
    test_map = load_map(repo)
    try:
        changed = changed_paths(repo, base, test_map)
        python = [path for path in changed if path.endswith(".py")]
        before = text_at(repo, test_map.tree, python) if test_map else {}
    except (subprocess.CalledProcessError, OSError) as error:
        return _all(f"could not read the change ({error})")
    return select(changed, repo, test_map, before)


def _record_command(repo: Path, coverage_file: Path) -> int:
    tree = tested_tree(repo)
    if tree is None:
        print("hook-tests: unstaged changes were tested; no map recorded", file=sys.stderr)
        return 0
    test_map = map_from_coverage(coverage_file, repo, tree)
    target = save_map(test_map, repo)
    print(
        f"hook-tests: recorded what {len(test_map.tests)} test files run, in {target}",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["tests", "record", "import-check"])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--coverage", type=Path, default=Path(".coverage"))
    args = parser.parse_args()

    if args.what == "record":
        return _record_command(REPO, args.coverage)
    if args.what == "import-check":
        failures = import_failures(REPO, changed_paths(REPO, args.base, None))
        for failure in failures:
            print(f"hook-tests: no longer imports: {failure}", file=sys.stderr)
        return 1 if failures else 0
    selection = _tests_command(REPO, args.base)
    print(f"hook-tests: {selection.reason}", file=sys.stderr)
    print(selection.render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
