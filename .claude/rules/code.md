---
paths:
  - "src/**/*.py"
  - "services/**/*.py"
  - "scripts/**/*.py"
---

# Python code

## Gates

CI enforces ruff lint and format, mypy, the file-length gate (a warning above 800 lines, a failure
above 1000), Xenon grade C (cyclomatic complexity up to 20 per function), complexipy up to 15,
vulture, bandit (no HIGH), semgrep (no ERROR), refurb, deptry, import-linter boundaries,
conventional commit messages and all tests.

## Structure

- Compose with constructor injection and Protocol contracts; inject state from other modules rather
  than reaching for it. Mixins are not used here.
- Import from the source module. Re-exports belong only in `__init__.py`, and only for more than one
  consumer.
- Give every file a descriptive name; no `_`-prefixed overflow files.
- A PR that pushes a file past 800 lines includes the split, or queues it immediately; the
  1000-line failure is a backstop, not a target. Split along cohesion boundaries: extract a service
  with a Protocol contract for its dependencies, independently importable and testable, update every
  import site, and update `ARCHITECTURE.md`. If a file is genuinely one cohesive unit, extract
  helpers rather than arbitrary groups of methods.

## Comments and docstrings

- Comments explain why something non-obvious is done; the code says what it does.
- Public functions get docstrings that explain behaviour. Private functions get one only when their
  behaviour is non-obvious.

## Config

- New options ship with a sane default.
- User-facing options are Tier 1 (top-level YAML); everything else is Tier 2 under `advanced:`
  (`_TIER2_SECTIONS` in `config_loader.py`). At runtime every section is flat on `Config`.
- Renaming or removing a key follows the deprecation rule in `AGENTS.md`: keep accepting the old key
  with a warning that names the new one, and remove it at the next major.
- Config values never appear in errors, logs or reports.

## Self-review

After a change touching more than five files, read the diff as a skeptical senior engineer would:
abstractions with no consumer, helpers called from one place, registries for three items, tests that
test mocks, splits by line count. Then run `make critique`.
