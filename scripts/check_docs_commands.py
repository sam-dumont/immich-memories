"""Check documented CLI commands and Make targets without invoking their callbacks.

This verifies command paths, options, literal choice values and positional arity.
Shell expansion, external tools and runtime behavior remain outside this check.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import click
from click.core import UNSET

ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"^```(?:bash|sh|shell|console)\s*\n(.*?)^```", re.M | re.S)
BOUNDARIES = {";", "&&", "||", "|", ">", ">>", "<"}


def _placeholder(value: str) -> bool:
    return bool(re.search(r"[$<>…]", value)) or value.isupper() or value.startswith("[")


def check_cli(tokens: list[str], root: click.Group, *, fragment: bool = False) -> list[str]:
    """Inspect Click definitions only; never parse a context or invoke a callback."""
    command: click.Command = root
    errors: list[str] = []
    positional: list[str] = []
    scaffold = fragment or any(word.startswith("[") or "…" in word for word in tokens)
    i = 0
    while i < len(tokens):
        word = tokens[i]
        if word.startswith("[") or word in {"…", "..."} or (scaffold and word == "COMMAND"):
            i += 1
            continue
        if word.startswith("-"):
            flag, equal, inline = word.partition("=")
            options = {
                name: parameter
                for parameter in command.params
                if isinstance(parameter, click.Option)
                for name in (*parameter.opts, *parameter.secondary_opts)
            }
            option = options.get(flag)
            if option is None:
                errors.append(f"{command.name}: unknown option {flag}")
                i += 1
                continue
            count = 0 if option.is_flag or option.count else option.nargs
            if (
                count
                and option.flag_value not in (None, UNSET)
                and (i + 1 == len(tokens) or tokens[i + 1].startswith("--"))
            ):
                count = 0  # Click options such as --birthday accept an implicit value.
            values = [inline] if equal else tokens[i + 1 : i + 1 + count]
            if count and (len(values) < count or values[0].startswith("--")):
                if not fragment:
                    errors.append(f"{flag}: missing value")
            elif count and isinstance(option.type, click.Choice):
                for value in values:
                    if not _placeholder(value) and value not in option.type.choices:
                        errors.append(f"{flag}: {value!r} is not one of {option.type.choices}")
            i += 1 + (count if not equal else 0)
            continue
        if isinstance(command, click.Group):
            child = command.commands.get(word)
            if child is None:
                errors.append(f"{command.name}: unknown subcommand {word!r}")
                break
            command = child
        else:
            positional.append(word)
        i += 1
    arguments = [p for p in command.params if isinstance(p, click.Argument)]
    minimum = sum(p.nargs if p.nargs > 0 else 1 for p in arguments if p.required)
    maximum = sum(p.nargs for p in arguments) if all(p.nargs > 0 for p in arguments) else None
    if not scaffold and len(positional) < minimum:
        errors.append(f"{command.name}: requires {minimum} positional value(s)")
    if maximum is not None and len(positional) > maximum:
        errors.append(f"{command.name}: too many positional values")
    return errors


def shell_examples(source: str):
    """Keep source line numbers while joining shell continuation lines."""
    for block in FENCE.finditer(source):
        start = source.count("\n", 0, block.start(1)) + 1
        pending = ""
        line_number = start
        for offset, line in enumerate(block.group(1).splitlines()):
            if not pending:
                line_number = start + offset
            pending += line.strip().removeprefix("$ ")
            if pending.endswith("\\"):
                pending = pending[:-1] + " "
                continue
            yield line_number, pending, False
            pending = ""
    for inline in re.finditer(r"(?<!`)`(immich-memories [^`\n]+)`(?!`)", source):
        yield source.count("\n", 0, inline.start()) + 1, inline.group(1), True


def check_page(path: Path, root: click.Group, targets: set[str]) -> tuple[list[str], int]:
    errors: list[str] = []
    checked = 0
    for line, example, fragment in shell_examples(path.read_text()):
        try:
            example = re.sub(
                r"<([\w -]+)>", lambda m: m.group(1).upper().replace(" ", "_"), example
            )
            lexer = shlex.shlex(example, posix=True, punctuation_chars=";&|<>")
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            continue  # Fragments of heredocs are not complete shell commands.
        for i, word in enumerate(tokens):
            if word != "immich-memories" or (i + 1 < len(tokens) and tokens[i + 1] == word):
                continue
            executable = i == 0 or tokens[i - 1] in {"--", "immich-memories", "run"}
            executable = executable or (i > 0 and all("=" in part for part in tokens[:i]))
            if not executable:
                continue
            end = next(
                (j for j in range(i + 1, len(tokens)) if tokens[j] in BOUNDARIES), len(tokens)
            )
            if "$((" in example:
                continue  # A shell arithmetic expansion needs a shell parser, not shlex.
            checked += 1
            errors.extend(
                f"{path.relative_to(ROOT)}:{line}: {error}"
                for error in check_cli(tokens[i + 1 : end], root, fragment=fragment)
            )
        if tokens and tokens[0] == "make":
            for word in tokens[1:]:
                if word in BOUNDARIES:
                    break
                if word.startswith("-") or "=" in word or _placeholder(word):
                    continue
                checked += 1
                if word not in targets:
                    errors.append(f"{path.relative_to(ROOT)}:{line}: unknown Make target {word}")
    return errors, checked


def main() -> int:
    """Audit published Markdown against the CLI and root Makefile definitions."""
    from immich_memories.cli import main as cli

    targets = set(re.findall(r"^([a-zA-Z][\w-]*):", (ROOT / "Makefile").read_text(), re.M))
    pages = [
        ROOT / "README.md",
        *sorted((ROOT / "docs-site/docs").rglob("*.md")),
        *sorted((ROOT / "docs-site/docs").rglob("*.mdx")),
    ]
    errors: list[str] = []
    count = 0
    for page in pages:
        findings, checked = check_page(page, cli, targets)
        errors.extend(findings)
        count += checked
    print(f"Checked {count} CLI/Make examples across {len(pages)} pages; no commands executed")
    for error in sorted(set(errors)):
        print(error)
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
