---
paths:
  - "README.md"
  - "docs-site/**"
---

# Docs

User-visible changes (CLI flags, config, web UI, API, behaviour) update their docs page in the same
PR, and `make docs-build` passes. The full rules are in `docs-site/docs/contribute/writing-docs.md`.

- Every page serves the reader of its layer: README, Welcome, Get started, Make, How it chooses,
  Run, Better, Reference, Help, How this was built, Contribute. The page table in `writing-docs.md`
  says what belongs where.
- Public pages describe the product as it is today. Issue and PR numbers, commit hashes, calendar
  dates and "added in / since / used to / no longer" history stay out. *How this was built* is the
  one page with dates; `better/measured.md` names the release and the hardware instead.
- What doesn't work yet lives in the issue tracker, which pages link; there is no limitations page.
- Deprecations and upgrade steps go in `run/maintenance/upgrading.md`.
- Diagrams are drawn from the code (architecture, deployment per install path, sequence, decision,
  state), rendered by `make docs-diagrams`, and checked by eye before committing.
- Load the `sams-voice:sams-voice` skill before writing public text. `make docs-voice` catches em
  dashes and chatbot words.

## Where things go

| Change | Page |
|---|---|
| CLI commands and flags | `make/cli/` (and `make docs-cli` for the generated reference) |
| Web UI | `make/web-ui.mdx` |
| Memory types | `make/memory-types.mdx` |
| Titles, maps, music | `make/titles-maps-music.md` |
| Photos, Live Photos, HDR | `make/photos-and-live-photos.md` |
| Automation and the daily timer | `make/automate.md` |
| How a cut is chosen | `how-it-chooses/` |
| Config options | `run/config-file.md`, `run/environment-variables.md`, `reference/config-reference.md` (`make docs-config-check`) |
| Install and deployment | `run/` |
| Anything that can leave the network | `run/privacy.md` |
| Hardware encoding | `run/hardware.md` |
| Optional add-ons | `better/` |
| First run | `get-started/` |
| Flags, config, FAQ, troubleshooting | `reference/` |

New pages also go in `docs-site/sidebars.ts`.
