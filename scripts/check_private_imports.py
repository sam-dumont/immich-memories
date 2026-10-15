"""No module reaches into another module's private names, or past a stage's public modules.

Two rules, checked over the app, the services and the scripts:

1. A module never imports a `_private` name from another module (`from x import _name`), and
   never reads one off a module it imported (`x._name`). A name another module needs is public:
   drop the underscore, or move the name to where it belongs.
2. A module outside an analysis stage package (`immich_memories.analysis.<stage>`) imports only
   the modules that stage lists in its `__all__`; the rest are the stage's own business.

Tests are out of scope. A test may read the private names of the module it tests, and nothing
here can tell which module a test is for.

Usage: python scripts/check_private_imports.py [paths...]   (exits 1 on any finding)
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Where each first-party package lives: the directory its top-level package sits in.
PACKAGE_ROOTS = (
    ROOT / "src",
    ROOT / "services" / "inference",
    ROOT / "services" / "render-worker",
)
SCANNED = (
    ROOT / "src",
    ROOT / "services" / "inference" / "immich_memories_inference",
    ROOT / "services" / "render-worker" / "immich_memories_render_worker",
    ROOT / "scripts",
)
FIRST_PARTY = ("immich_memories", "immich_memories_inference", "immich_memories_render_worker")
STAGES = "immich_memories.analysis"


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path.relative_to(ROOT)}:{self.line}: {self.message}"


def _private(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


def _module_name(path: Path) -> str:
    for root in PACKAGE_ROOTS:
        if path.is_relative_to(root):
            parts = path.relative_to(root).with_suffix("").parts
            return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
    return f"scripts.{path.stem}"


def _module_file(module: str) -> Path | None:
    parts = module.split(".")
    for root in PACKAGE_ROOTS:
        for candidate in (
            root.joinpath(*parts).with_suffix(".py"),
            root.joinpath(*parts, "__init__.py"),
        ):
            if candidate.is_file():
                return candidate
    return None


def _first_party(module: str) -> bool:
    return module.split(".")[0] in FIRST_PARTY


_public_cache: dict[str, frozenset[str] | None] = {}


def _stage_public(stage: str) -> frozenset[str] | None:
    """The modules a stage package lists in `__all__`, or None when it declares none."""
    if stage not in _public_cache:
        init = _module_file(stage)
        names: frozenset[str] | None = None
        if init is not None and init.name == "__init__.py":
            for node in ast.parse(init.read_text()).body:
                if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
                ):
                    names = frozenset(ast.literal_eval(node.value))
        _public_cache[stage] = names
    return _public_cache[stage]


def _stage_of(module: str) -> str | None:
    parts = module.split(".")
    if module.startswith(STAGES + ".") and len(parts) >= 3:
        return ".".join(parts[:3])
    return None


def _stage_finding(own: str, target: str) -> str | None:
    """Why importing the module `target` from `own` crosses into a stage's internals."""
    stage = _stage_of(target)
    if stage is None or stage == target or _stage_of(own) == stage:
        return None
    public = _stage_public(stage)
    leaf = target.split(".")[3]
    if public is None or leaf in public:
        return None
    return f"{target} is internal to {stage}; import one of the modules its __all__ lists"


def _resolve(own: str, node: ast.ImportFrom, is_package: bool) -> str:
    if not node.level:
        return node.module or ""
    base = own.split(".") if is_package else own.split(".")[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def check_file(path: Path) -> list[Finding]:
    own = _module_name(path)
    tree = ast.parse(path.read_text(), filename=str(path))
    findings: list[Finding] = []
    modules: dict[str, str] = {}  # local name -> first-party module it is bound to
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            source = _resolve(own, node, path.name == "__init__.py")
            if not _first_party(source):
                continue
            for alias in node.names:
                submodule = f"{source}.{alias.name}"
                if _module_file(submodule) is not None:
                    modules[alias.asname or alias.name] = submodule
                    target = submodule
                else:
                    target = source
                if _private(alias.name) and source != own:
                    findings.append(
                        Finding(path, node.lineno, f"imports private {alias.name} from {source}")
                    )
                if why := _stage_finding(own, target):
                    findings.append(Finding(path, node.lineno, why))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if not _first_party(alias.name):
                    continue
                if alias.asname:
                    modules[alias.asname] = alias.name
                if why := _stage_finding(own, alias.name):
                    findings.append(Finding(path, node.lineno, why))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and _private(node.attr)
            and isinstance(node.value, ast.Name)
            and (module := modules.get(node.value.id)) is not None
            and module != own
        ):
            findings.append(Finding(path, node.lineno, f"reads private {node.attr} off {module}"))
    return findings


def main(argv: list[str]) -> int:
    roots = [Path(arg).resolve() for arg in argv] or list(SCANNED)
    files = sorted(
        {f for root in roots for f in ([root] if root.is_file() else root.rglob("*.py"))}
    )
    findings = [finding for path in files for finding in check_file(path)]
    for finding in findings:
        print(finding)
    if findings:
        print(
            f"\n{len(findings)} reach(es) into another module's internals. A name another module "
            "needs is public: drop its underscore or move it where it belongs. A stage module "
            "other packages need goes in that stage's __all__."
        )
        return 1
    print(f"No private or stage-internal imports across {len(files)} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
