"""Find model-asking functions, including callers of the shared prompt adapters."""

import ast
from pathlib import Path

# Include the prompt adapters so one successful HTTP call cannot cover every feature.
ASKERS = frozenset(
    {
        "query_llm",
        "TextRequest",
        "ask_llm_image",
        "ask_again_if_cut",
        "read_page_answer",
        "ask_complete_weights",
        "ask_moment_pick",
        "choose",
        "choose_several",
        "request_with_budget",
    }
)


def _asks(node: ast.Call, aliases: dict[str, str]) -> bool:
    if isinstance(node.func, ast.Name):
        name = aliases.get(node.func.id, node.func.id)
        if name in ASKERS:
            return True
        return name == "getattr" and any(
            isinstance(arg, ast.Constant) and arg.value == "request_with_budget"
            for arg in node.args
        )
    if isinstance(node.func, ast.Attribute):
        return node.func.attr in ASKERS or (
            node.func.attr == "ask"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in {"judge", "asker"}
        )
    return False


class _Sites(ast.NodeVisitor):
    def __init__(self, module: str, aliases: dict[str, str]) -> None:
        self.module = module
        self.aliases = aliases
        self.scope: list[str] = []
        self.found: set[str] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def visit_Call(self, node: ast.Call) -> None:
        if self.scope and _asks(node, self.aliases):
            self.found.add(f"{self.module}:{'.'.join(self.scope)}")
        self.generic_visit(node)


def discover_sites(root: Path) -> set[str]:
    sites: set[str] = set()
    for path in root.rglob("*.py"):
        if "conformance" in path.relative_to(root).parts:
            continue
        tree = ast.parse(path.read_text())
        aliases = {
            item.asname or item.name: item.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for item in node.names
        }
        visitor = _Sites(".".join(path.relative_to(root).with_suffix("").parts), aliases)
        visitor.visit(tree)
        sites.update(visitor.found)
    return sites
