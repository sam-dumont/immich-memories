# Code-scanning review

Reviewed on October 9, 2026, against main `0b26fef77a4de90654c5f064549710c5f68de498`.
The review covers seven open code-scanning alerts and two dependency advisories.

## Code-scanning findings

| Alert | Finding | Disposition |
|---|---|---|
| 261, 262 | Config-file path injection | False positive. The three reported route parameters use `Annotated[Path, Depends(config_file)]`. `config_file()` returns the process config path, selected at startup. It accepts no request arguments. HTTP probes against settings GET/POST and connection PUT confirmed that a `path` query naming an invalid YAML file cannot replace that path. |
| 264 | Password written to the startup log | False positive. `startup_warnings()` returns static guidance and the fixed minimum length. No password value enters the returned text. The reported source is the literal word `password` in the weak-secret vocabulary. A server-startup log probe confirmed that the configured password is absent. |
| 266, 267 | Incomplete script-tag filtering | False positive. The production regex extracts inline script bodies from the app's packaged HTML to calculate CSP hashes; it does not filter user HTML. An unmatched script gets no hash permission and is blocked by CSP. The other occurrence is the corresponding test. The existing bundle/CSP test passes. |
| 268 | Incomplete URL substring sanitization | False positive. This is a test assertion that a connection error names its host, followed by assertions that it omits the username and password. It is not URL validation or sanitization code. |
| 265 | Diagram packages lack artifact hashes | Fixed by installing the existing package versions from `docs-site/diagrams/requirements.txt` with `pip --require-hashes`. The hashes select wheels for the pinned CPython 3.12 Alpine amd64 renderer. |

The route and logging probes ran with the test suite's sealed home and real temporary config
files. Together with the existing startup, settings, connection and web-security tests,
54 checks passed. The hash-pinned image passed `make docs-diagrams-check`: all 44 committed
SVGs matched. No scanner rule or workflow was disabled.

The CSP extractor still assumes the shape of the packaged client HTML. A future client build
with different script tags must pass the bundle/CSP and browser checks; this review does not
claim that the extractor supports arbitrary HTML.

## Unpatched dependencies

The two dependency alerts remain open. GitHub reports no patched release for either finding:

- NLTK 3.10.3, GHSA-8mgp-746c-j5xp: the affected model-artifact save/load APIs are outside the
  supported WordNet and ACE-Step routes. The app verifies the pinned WordNet corpus before
  read-only lookups. See the [NLTK review](../../SECURITY.md#reviewed-nltk-advisory).
- braces 3.0.3, GHSA-vfj7-8cjw-p6xm: nested glob patterns can stop the docs build. This sits
  inside the existing PR build-code execution boundary, not the published static site.
  The owner-approved review expires October 17, 2026. See the
  [docs advisory review](../../SECURITY.md#approved-temporary-docs-advisory-review).

These are reviewed exceptions, not patched dependencies. The audit gates still reject new
findings, available fixes, changed reviewed versions and an expired docs review.
