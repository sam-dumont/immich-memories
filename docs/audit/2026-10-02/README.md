# Docs audit, pre-1.0.0-rc.1: issue list

Audit of `main` @ `b371427`, 2 October 2026. Filed as #1777 (owner rulings) and #1778-#1796,
under #928. Every item comes from a finding with evidence (code path:line, command output, or a
real `kustomize build`/PostgreSQL run). Full evidence: the auditor reports in this folder
(`A-start-make.md` … `H-contribute.md`), quoted below by finding ID. `K-` items are the ones
verified in the first review.

Coverage: all 103 public pages plus README, CONTRIBUTING, DISCLAIMER, SECURITY, the K8s README,
`examples/config.example.yaml`, `sidebars.ts` and `redirects.ts`. Nine auditor reports
(`A`, `B`, `C`, `D`, `E`, `F`, `G1`, `G2`, `H`), 256 findings: 5 blockers, 73 wrong.
Clean pages: `preparation.md`, `sentence-parser.md` (spot-checked), `demo-assets.md`,
`code-of-conduct.md`, `DeploymentDiagram`.

Already clean: all 686 internal links and 217 anchors resolve; `docs-voice`, `docs-cli-check`,
`docs-config-check`, `docs-brand` pass; 206/209 config defaults match the schema.

**Priority:** P0 = blocks a first run, security or a false privacy claim. P1 = states something
untrue. P2 = missing info a reader needs. P3 = clarity/polish.
**[decision]** = needs an owner ruling before it can be fixed. **[code]** = the fix is in code,
not (only) in the docs. **LIKELY** = not executed end to end.

---

## Owner decisions first (they unblock items below)

1. **RC docs:** `release.yml:351` skips the docs deploy for candidates, so during RC1 the public site stays on v0.103.0 and #956's "published docs only" gate tests old docs. Publish RC docs (separate path?) or run the gate on a preview? (K3)
2. **Hosted reader without `base_url`:** docs say "the provider preset supplies the API URL"; the code runs it locally (`resolved_llm_config`, verified). Fix the docs or the code? (K1)
3. **Implicit reader enabling:** `model` or `base_url` without `enabled:` turns the reader on (`config_models_llm.py:206`), against "disabled by default". Keep the shim or remove it? (K11)
4. **Title styles:** `title_screens.style_mode` accepts only `auto|random`; the page says you can choose a style. Widen the schema to the five style names, or reword? (A-1)
5. **`strict_sharing: false`:** doc says a caption can't clear an exposure flag; the code's own field description says it can. Which is true? (G1-12, LIKELY)
6. **Partial `title_llm:` block:** `title_llm.model` defaults to Gemma, so a partial block redirects or disables titles. Document or change the fallback? (G1-2)
7. **Birthday from the people store:** detection uses the store date, the film uses Immich's. Pass the resolved date or document? (B-4)
8. **`FORWARDED_ALLOW_IPS` with header auth:** refuse or warn in code, besides the docs fix? (E-1)
9. **`store status` migrates:** document it, or make `status` load without stored settings? (E-4)

---

## G01 Release pipeline and version pins [code]
One PR in `scripts/`, `release.yml`, `docs-site/src/components/InstallationFiles`.

- [P0] fix(release): repin `render-sidecar` and `maximalist` overlays in the deploy bundle. `package_deployment.py:22` rewrites only 3 files; the v0.103.0 bundle builds render-sidecar with all containers on 0.100.4 and maximalist with app 0.100.4 + inference 0.103.0-cuda (kustomize, verified). (K2, F-28)
- [P1] fix(release): Terraform `examples/basic` has no `image_tag`, so `latest` + `Always` pull upgrades the app and store schema on every restart; add the variable, stamp it in the bundle. (D-1)
- [P2] docs(install): the Quick start override pins only the app image; `INFERENCE_TAG` still defaults to `latest` (the previous final during an RC). Pin it too. (D-10)
- [P2] docs(install): `run/docker.md:19-20` curls the compose file from `main`; use the same pinned-tag download as the Quick start. (K, cross-page)
- [P2] docs(install): uv/pip during an RC needs `--prerelease allow` / `==1.0.0rc1`. (D-26, LIKELY)
- [P2] build(compose): pin the `llama.cpp:server`/`server-cuda` images (compose + `captioner-cuda` overlay); weights are pinned, the server isn't, and the compose comments depend on build b10920. (K12)
- [P3] docs(install): `InstallationFiles` says "RC tag"; say "release tag". (A-20)

## G02 Docker: what reaches the container
One PR, mostly `run/docker.md`, `reference/automation-contract.md`, `docker-compose.yml` comments.

- [P0] docs(automation): `automation-contract.md:30-31` says to put `IMMICH_MEMORIES_AUTOMATION__*` in `.env`; compose has no `env_file:`, so the timer never turns on. Say "uncomment the lines in compose" (as automate.md does), or make the compose lines `${VAR:-false}`. (B-1)
- [P1] docs(automation): the trigger token exported in `.env` never reaches the app either; add the compose line. (B-14)
- [P1] docs(config): compose always sets `IMMICH_URL`, `IMMICH_MEMORIES_TIER` and the home coordinates (default 0), so YAML/Settings values for them are silently ignored on Docker (home becomes 0,0, verified). List the pinned keys. (E-9)
- [P1] build(compose): fix the comment at `docker-compose.yml:204` ("set the tier to full"); tier stays `auto`. (K13)
- [P2] docs(make): automation, titles and notifications show YAML only; add the Docker route (Settings, and the secret key for `notifications.urls`). (A-5)
- [P2] docs(cli): `days-export`/`people export --to` write inside the container; use stdout and `/app/output`. (B-27, LIKELY)
- [P2] docs(titles): `titles test` in Docker writes to an unwritable `/app`; add `-o /app/output/...`. (A-4, LIKELY)
- [P2] docs(docker): custom music path has no mount example (`./music:/app/music:ro`). (D-24)
- [P2] docs(multi-account): `${IMMICH_URL}` has no default in the partner block. (E-23)
- [P2] docs(upgrade): pin `X.Y.Z` in compose before upgrading; give one ordered rollback block (stop, old tag, `compose run --rm ... store restore --force`, up). (E-18, E-19)
- [P3] docs(backup): `docker cp` vs `docker compose cp` across two pages. (E-16)

## G03 Text reader (LLM) pages
One PR: `better/reader.md`, `reference/llm-providers.md`, `reference/config-reference.md` LLM section.

- [P0] docs(reader): hosted examples (`reader.md:59-68`, `llm-providers.md:99`) run locally; preflight then says "install llama-server". Add `base_url` (or the code fix, decision 2). (K1)
- [P0] docs(reader): add an Ollama recipe (native `provider: ollama` and `/v1`), with `num_ctx` 32768 via `extra_params.options` (the app sends none) and `OLLAMA_CONTEXT_LENGTH` for the `/v1` route. The "native Ollama examples" pointer leads nowhere. (K4)
- [P1] docs(reader): the app-owned reader can't run in the Docker image or on Kubernetes (no `llama-server`); say so and point to an external server. (K5)
- [P1] docs(reader): the existing-server example `reader.example.lan` counts as *hosted* (dotted hostname): 4 parallel requests, schema on (oMLX stall). Use an IP, or document the rule plus `reader_concurrency: 1`. (F-2)
- [P1] docs(tiers): "without GPU inference, selection stays NAS" is false: a Mac's Metal GPU or a local CUDA runtime selects GPU, which then needs captions and Laya. Fix in reader.md, inference.md, hardware.md, what-a-gpu-or-a-model-adds.md. (F-3, A-21)
- [P1] docs(llm): "1,024 tokens on top of the cap" is 16,384. (F-1)
- [P1] docs(llm): Anthropic preset: `claude-haiku-4-5` with `thinking: high` is rejected; the `budget_tokens` escape hatch still sends `output_config`; bulk `thinking: disabled` is refused by current models; point to `thinking: auto`. (F-4, F-5, LIKELY on API side)
- [P1] docs(config): `llm.thinking` affects one call (titles), not two. (G1-6, LIKELY)
- [P2] docs(reader): Linux llama.cpp install link is circular; add the supported routes. (F-13)
- [P2] docs(config): `reader_concurrency` is ignored by the owned reader. (G1-15)
- [P2] docs(privacy): clarify the implicit-enable sentence (`privacy-egress.md:9`) per decision 3. (K11)
- [P3] docs(measured): "Gemma" in the conformance table is the 6-bit MLX on oMLX, not the bundled Q4_0. (F-17)
- [P3] docs(llm): "Text only" means the selection reader; point to the caption opt-in. (F-22)
- [P3] docs(env): `llm.api_key` shorthand wording ("when no other source sets it"). (E-17)

## G04 Privacy: egress inventory corrections
One PR: `run/privacy.md`, `run/reference/privacy-egress.md`, `run/multi-account.mdx`.

- [P0] docs(privacy): the render-worker request carries every selected partner account's API key, home coordinates, names, titles and the `network` config; the row says "the cut + URL + key", and multi-account says the partner key only goes to its server. (E-6)
- [P0] docs(privacy): "a run never downloads" is false: `allow_model_downloads`, the compose inference profile (`ALLOW_MODEL_DOWNLOADS: "true"`), the captioner puller, Demucs via `dl.fbaipublicfiles.com` (Torch Hub), ACE-Step's unpinned downloader. (E-7)
- [P1] docs(privacy): "preflight lists outside hosts you enabled" covers only geocoding and map tiles. (E-5) [or code: extend the check]
- [P1] docs(privacy): add the preflight probes to every configured endpoint, and the inference stem upload + health probe on config load. (E-34, E-13)
- [P1] docs(config): "logs never print a secret": secrets under 8 characters aren't redacted. (E-14)
- [P2] docs(privacy): reader and title rows omit payload fields; list download hosts for allow-list firewalls. (E-22, E-33)
- [P2] docs(automate): `ntfy://` is plain HTTP; use `ntfys://`, warn that public topics are readable. (A-6)
- [P1] docs(config): `strict_sharing` per decision 5. (G1-12)

## G05 Auth and network security
One PR: `run/authentication.mdx`, `run/network-security.md`, `run/reference/environment.md`, README.

- [P0] fix(auth)+docs: `FORWARDED_ALLOW_IPS` with `provider: header`: set to the proxy breaks login (200 to 401), set to `*` lets anyone forge `Remote-User` (401 to 200), reproduced with the real app. Docs present it as a plain override. (E-1, decision 8)
- [P1] docs(security): the image CMD is `ui --host 0.0.0.0`; only Compose's `127.0.0.1` mapping protects the UI. `docker run -p`, Unraid templates or Portainer expose it unauthenticated. README:41 "listens on localhost" is Compose-only. (K7)
- [P1] docs(config): `server.host: "0.0.0.0"` in config.yaml is ignored (verified); the example block suggests it. (G1-3)
- [P2] docs(auth): header auth keeps the first user for the whole session TTL; OIDC logout URL is never used (no `post_logout_redirect_uri`). (E-11, E-12)
- [P2] docs(network): how to find the peer address for `trusted_proxies`; mention `server.allow_unauthenticated_lan`. (E-25, E-26)
- [P2] docs(docker): minimal API-key list probably misses user read and face read (`/users/me`, `/faces`); add a gate test with a minimal key. (D-7, LIKELY)

## G06 Store and PostgreSQL
One PR: `run/database.md`, `run/reference/database.md`, `run/reference/store-commands.md`, `run/maintenance/storage-backups.md`.

- [P0] docs(store): mode 4 (schema inside Immich's DB) with the documented SQL: `store restore` drops the schema and can't recreate it (`permission denied ... CREATE SCHEMA`), reproduced on PostgreSQL 16. Add `GRANT CREATE ON DATABASE immich` or restore into an existing schema [code]. (E-2)
- [P0] docs(store): SQLite to PostgreSQL on Docker can't work in the documented order (the app switches to the empty PG, then `store copy` refuses). Give an explicit Docker sequence; "restart" means `docker compose up -d`. (E-3, LIKELY)
- [P1] docs(store): "`store status` never migrates" is false (verified on a downgraded store); warn in upgrading/rollback. (E-4, decision 9)
- [P2] docs(config): `${VAR}` table omits `database.url`, `laya_checkpoint`, account url/api_key. (E-8)
- [P2] docs(store): PG boot order (`depends_on: service_healthy` in the commented block); run the SQL statements one by one. (E-30, E-32)
- [P2] docs(backup): K8s restore selector picks CronJob pods too; suspend CronJobs during restore. (E-15)

## G07 Kubernetes manifests and pages
One PR: `deploy/kubernetes/**`, `run/kubernetes.md`, `run/reference/kubernetes.md`.

- [P0] fix(k8s): the CronJobs in `base/job.yaml` carry the app label, so the base NetworkPolicy applies; they curl Service port 80 (pod 8080), and egress has no 8080. Add an egress rule to the app pods on 8080. (D-2, LIKELY: CNI-dependent)
- [P0] docs(automation): `kubectl apply -f base/job.yaml` also starts the one-off `generate` Job next to the running Deployment (the file warns a second writer corrupts SQLite). Split the file or say to apply only the CronJobs. (B-3)
- [P1] docs(automation): the "monthly" CronJob runs `POST /api/trigger`, not `generate`, and mounts nothing. (B-2)
- [P1] docs(k8s): the namespace loop misses `render-sidecar`, `postgres`, `maximalist` (Secrets stay behind; maximalist hard-codes the namespace), verified with kustomize. (D-3)
- [P1] fix(k8s): NetworkPolicy ingress has no `from:` (any pod reaches the unauthenticated UI); egress is port-only, opens 11434 but not 8000/9999/8093. Document, ideally tighten. (K8, F-20)
- [P2] fix(k8s): the commented reader example in `base/deployment.yaml:124-129` is invalid YAML once uncommented, uses blocked port 8080 and a vision model. (D-4)
- [P2] docs(k8s): data PVC is 20Gi (k8s and TF), docs ask 25 GB, default caches alone are 20 GB. Raise to 30Gi or document lowering the caps. (D-5)
- [P2] docs(k8s): document the resources (app 8Gi/4 CPU, init 2Gi) vs Compose's 4 GB. (K9)
- [P2] fix(k8s): no writable `~/.cache` in the app container (local Demucs needs it). (D-12, LIKELY)
- [P2] docs(k8s): render-sidecar Secret needs `immich-url` too; standalone worker on k8s is undescribed. (D-11, F-20)
- [P2] docs(k8s): `captioner-cuda` makes no GPU request; say so. (D-25)
- [P2] docs(security): how to verify image provenance (`gh attestation verify oci://...`); the release already attests every digest. (K14)
- [P3] docs(k8s): `/models` doesn't hold Laya or the reader GGUF (data PVC); init guard never passes on NAS tier; `kustomize edit` needs the standalone CLI; oMLX port stated as 8000 and 9999. (D-6, D-13, D-16, D-17)

## G08 Terraform
One PR: `run/terraform.md`, `run/reference/terraform.md`, `deploy/terraform/`.

- [P2] docs(terraform): `render_worker_token` defaults to empty and the worker refuses an empty token; add a `validation` block. (D-11)
- [P2] docs(terraform): `apply` waits for a Ready pod; reader wording conflicts with the module; inline the verification commands instead of a pointer chain. (D-18, D-19, D-23)
- (image_tag is in G01.)

## G09 NAS and newcomer path
One PR: `get-started/quick-start.md`, `run/nas.md`, `run/requirements.md`.

- [P0] docs(start): state the first-preparation duration (NAS: hours for a month; Mac/cluster: about an hour). `measured.md` excludes preparation; no page gives it. (K6)
- [P2] docs(nas): use `sudo docker exec immich-memories ...` (works whatever the project name); one line each for Unraid (Compose Manager plugin), TrueNAS (no `.env` beside the YAML), DSM/Portainer terminals as an alternative to SSH. (D-8, LIKELY)
- [P2] docs(nas): "chown the config volume" has no command. (D-9)
- [P2] docs(cli): `generate.md` doesn't mention running `models fetch` first. (B-23)
- [P2] docs(tiers): forcing `full` without a reader stops the app from loading. (D-15)
- [P3] docs(start): disk wording ("25 GB for data, plus image and films"); cores/RAM in the README and Quick start vs the compose header comment. (A-14, A-15)
- [P3] docs: "If it stops" / "Preflight says" labels don't match what preflight prints. (A-22, D-14)

## G10 Config reference corrections
One PR: `reference/config-reference.md` (+ `examples/config.example.yaml`).

- [P1] `ultra` is not a quality value (high, balanced, fast). (G1-1)
- [P1] Compose inference host is `immich-memories-inference`, not `inference` (with fallback on, the wrong host silently runs everything locally). (G1-4)
- [P1] "top-level section wins": placements merge key by key. (G1-7)
- [P1] Tier-2 list omits `speech`. (G1-8)
- [P1] `hardware.backend: none` also forces software encode; name the stage clip extraction ignores. (G1-10, G1-11, LIKELY)
- [P1] Worker sizing "1 per 2 GB" vs code/rendering.md "1 GiB reserve + 3 GiB per worker". (E-35)
- [P1] `examples/config.example.yaml`: dead `network.font_downloads`, retired `medium`/`low`, "six heads" (eight), a link to a missing page. (G1-22)
- [P2] `fallback_to_local: false` + unreachable service fails every command at config load. (G1-5)
- [P2] Bundled music needs Docker or the `music` extra; `scripts/tier_settings.py` is checkout-only; undocumented exclusion rules; missing ranges. (G1-13, G1-14, G1-16, G1-19)
- [P3] Wrap Tier-2 examples in `advanced:`; `notifications.urls` example looks like a default; Laya defaults shown are Apple-only; `title_llm` listed as everyday; env shortcut table incomplete; polish. (G1-9, G1-17, G1-18, E-27, E-21, G1-20, G1-21)

## G11 Make-a-film pages (titles, photos, memory types, web UI)
One PR: `make/*.md(x)`, `get-started/first-film.mdx`.

- [P0] Title styles per decision 4. (A-1)
- [P2] Live Photos / photos keys without their section; a bare `include_live_photos: false` breaks config load. Give the UI checkbox, the flag and the full key. (A-2)
- [P2] Web UI length is in minutes ("30" = 30 minutes); portrait is under Render > Orientation. (A-3)
- [P2] free-text: name `immich-memories prepare`; marking wrong/missing is CLI-only (`report --wrong/--missing`); album subject is CLI-only. (A-7, A-8, A-18)
- [P2] Upload: `upload.enabled: true` also uploads and deletes the local copy; two overlapping upload switches. (B-22, A-23, A-16)
- [P3] web-ui.mdx: review/render happen on the run page under Runs; report buttons are on every run; exact UI labels; link texts; stale anchor; H.264-only tone-mapping is NAS-tier only; re-render a revision from Runs. (A-9..A-13, A-17, A-19)

## G12 Automation outside Docker
One PR: `reference/automation-contract.md`, `make/automate.md`, `run/uv-pip.md`.

- [P1] `auto install` writes the scheduler files but doesn't activate them (prints the command); `--uninstall` doesn't unload. (B-7)
- [P1] `action` can be `delivery_retry`; the quiet-output example misses `runtime` and is one line. (B-5, B-6)
- [P1] `auto suggest` prints no rejection rule; `auto status` shows no live suggestion or "what is next"; "only the latest completed month" isn't a rule. (B-9, B-10, B-11)
- [P1] `auto run --quiet` turns logging off entirely. (E-10)
- [P2] Headless Linux needs `loginctl enable-linger`; the crontab example ignores the PATH warning; "configure upload separately" names no key. (B-8, B-16, B-15, LIKELY on the first two)
- [P3] Score floors / "On this day" row; status payload shape and 401; FAQ "one a day at most" is a default. (B-12, B-13, G1-23)

## G13 CLI help strings and the reference generator [code]
One PR: `src/immich_memories/cli/*`, `scripts/generate_cli_docs.py`, then `make docs-cli`.

- [P0] `discover-days --until` default is the current year, baked into the generated page: `make docs-cli-check` fails on every branch from 1 January 2027. Use `show_default`. (B-19)
- [P1] `generate --output` help says "an identical rerun replaces itself"; every run writes its own folder. (B-17)
- [P1] `runs show` shows no delivery; `pictures` ASSET_ID source; `--quality` offers retired names. (B-29, B-31, B-24)
- [P2] Generator: global options missing; usage lines drop arguments; required/repeatable markers; `runs render` untyped options. (B-18, B-20, B-21)
- [P2] `report` needs the full run ID; name the captions flag; `runs delete` asks first (`--yes`); `prepare --overviews` preconditions and silent skip. (B-25, B-26, B-30, B-28)
- [P3] Docker prefix note on discover-days; wording. (B-32, B-33)

## G14 Add-on services (captions, inference, render worker, music)
One PR: `better/*`, `reference/caption-service.md`, `inference-service.md`, `local-audio.md`.

- [P1] Preflight doesn't validate caption control tiles or LLM vision; it checks `/models` / warns only. (F-6, F-7)
- [P1] Stem upload limit is 256 MiB, not 64. (F-8)
- [P1] MOV/ProRes don't "render locally" with `fallback_to_local: false`: they fail. (F-9)
- [P1] Source revision `f74936b657d7` (measured.md, twice) doesn't exist publicly. (F-16)
- [P1] Laya on a Mac: `laya-mlx` is in no extra; `pip install` doesn't reach a `uv tool` env (`--with laya-mlx`); without it sharing silently falls back to heads + rules. Docs and the runtime message. (K10)
- [P2] `make check-local-audio` tests a ~9 GB profile, not the 7 GB one recommended; "ACE-Step API server" never defined; no minimum NVIDIA driver; render worker example vs the deployment just shown; worker `/health` needs the token. (F-12, F-26, F-21, F-10, F-11)
- [P3] Detector cache default wording; `/health` signal; "pulls 546 MB" = weights; Laya size units; RC wording; #1385 note; one wrong cross-link; preflight form for the one-GPU worker; unclear volume sentence. (F-18, F-19, F-23, F-15, F-27, F-14, F-24, F-25, D-22, D-21)

## G15 Troubleshooting and FAQ
One PR: `reference/troubleshooting.md`, `reference/faq.md`.

- [P3] FAQ: upload also writes a tag and an album; "one Immich API key" next to multi-account. (G1-24, G1-25)
- [P3] Troubleshooting: a heading describes a failure the code now prevents; quoted messages are prefixes; env var name differs from the other pages. (G1-26, G1-27, G1-28)

## G17 Selection pages (how-it-chooses, selection-internals)
One PR: `how-it-chooses/*`, `reference/selection-internals/*`, `docs-site/sidebars.ts`.

- [P1] overrule-it.md:25: "undo Never use before ticking it in" isn't enforced; the pool checkbox and revision checks allow it. Fix the page or enforce it [decision]. (C-1, LIKELY)
- [P1] "Every year gets a shot": wrong for multi-range person films (only single windows over 548 days) and custom films (split per calendar year); albums with a subject also get it. (C-2)
- [P1] Hold decisions can't be answered "on the storyboard"; only the pool page and the CLI. (C-4)
- [P1] Slots = content budget (target minus title/ending cards) / fixed 4.0 s, not target / average hold. (C-5)
- [P1] "415 of 2,028 files" vs the code comment "352 of 2,028" (`picture_copies.py:6`); confirm which. (C-7)
- [P2] Three how-it-chooses pages missing from `sidebars.ts`; `moments-and-stories` has no inbound link. (C-3)
- [P2] Length pages send readers to Memory types for default lengths, which lists none; link `film-types.mdx#how-long-a-film-runs`. (C-8)
- [P2] Other gaps. (C-11, C-18)
- [P2] "Ticked" means `generate --include` in four internals pages (standing 2, trim protection); a web pool tick gets none of that. Say so. (C-6)
- [P3] `--subject` help says "needs a model reader" while the docs say it works without; brief "Who may see it" default shows "As configured"; `pixel-evidence.md` duplicates the overview and the section has no `sidebar_position` (alphabetical order); stale `thin_model_layer` field description; wording. (C-12, C-9, C-16, C-10, C-13..C-15, C-17, C-19, C-20)

## G18 Film and contract references
One PR: `reference/film-types.mdx`, `generation-contract.md`, `media-processing.md`, `output-rendering.md`, `special-days.md`, `people-registry.md`.

- [P1] media-processing.md:169,184: "a film keeps its sources' dynamic range" / "`hdr_mode: auto` gives HDR": false by default; `output.codec` is `h264` and HDR needs H.265 (resolved plan: H.264, tone-mapped SDR). config-reference gets it right. (G2-1)
- [P1] film-types.mdx:269-271: a trip doesn't take "everything in its window"; photos without GPS or within 50 km of home are dropped (videos by date only). (G2-2)
- [P1] `special_day` also refuses a day with several events without `--event-id`, and an unmatched `--event-id`; neither page names `--event-id`. (G2-3)
- [P1] media-processing.md:147-153: the merge table durations are wrong by the documented midpoint rule (about 1.0 s and 2.25 s; the total should be 5.0 s). (G2-4)
- [P1] film-types.mdx:31-33: "30 s a day, so three days is about 20 s" doesn't follow (up to 90 s plus titles). (G2-5)
- [P2] output-rendering.md: the five named styles can only be previewed, not set (same as decision 4). (G2-6)
- [P2] NAS tier caps at 1080p, so `--resolution 4k` gives 1080p; `special_days_per_year` lives under `advanced.automation`; `discover-days --also-skip` undocumented and holiday handling contradicts `--help`; people tier rule for a child born into the library, "20+ pictures" is a monthly average; `--trip-index` from 1, `--month` picks a trip, trip file names. (G2-7..G2-11)
- [P3] Month dividers need one calendar year; On this day reaches 30 years; `thanksgiving` is US-only; ending colour is `fade_color`; albums/trips reject `--accounts`; `modern_warm` is semibold. (G2-12..G2-16)

## G19 Contributor docs and repo files
One PR: `contribute/*`, `CONTRIBUTING.md`, `SECURITY.md`, `DISCLAIMER.md`, `deploy/kubernetes/README.md`, `Makefile`, `CLAUDE.md`.

- [P1] [code] `make dev`/`check`/`ci` on Linux install both `onnxruntime` and `onnxruntime-gpu` (pyproject says never together; no uv conflict declared; `uv sync --all-extras --dry-run` lists both). `make dev-test` also pulls torch + ~15 nvidia wheels unannounced. (H-14, H-15)
- [P1] `deploy/kubernetes/README.md`: backup advice names `annotations.sqlite`/`cache.db`; the store is `store.db`. "Six heads" is eight. (H-24, H-25)
- [P1] SECURITY.md: pip-audit covers base + dev only (the image ships `all`; unfixable CVEs pass); verify example `VERSION=0.59.2` has no `.sigstore.json`; Scorecard doesn't run on pushes to main; verify commands break for RC file names. (H-20..H-23)
- [P1] `make help` is a hand list of 47 targets but three pages say it lists every target; `make test-fast` overrides the addopts marker filter (likely runs integration/e2e/container). (H-1, H-2, LIKELY on H-2)
- [P1] architecture.md:75: the web Memory page uses a hard-coded `FIELDS` map, not `OFFERED_MEMORY_TYPES`; a new type following the recipe never shows in the UI. (H-3)
- [P1] testing.md / ci.md: Docker builds and the Immich gate are change-scoped, not every PR; gate config isn't "no model, no network"; clips must be 15 s or shorter; docs-voice/notices-check don't run in pre-commit (only `make ci`, so the merge train can merge them red); CI doesn't run on main pushes. (H-4..H-10, H-28)
- [P1] DISCLAIMER "800-line limit": the gate fails above 1000, four files exceed 800; CLAUDE.md coverage floor 55 vs pyproject 65; "unit tests need nothing external" but they need FFmpeg. (H-18, H-31, H-32)
- [P2] CONTRIBUTING.md:135 links to an empty anchor; remaining gaps/clarity items in the report. (H-16, H-11..H-44)
- [P2] Owner check: branch protection for `CI Success` / `Immich Gate` couldn't be confirmed with this token (ci.md claims both are required).

## G16 Small leftovers
- [P3] Page-split leftovers, household page starts with an H3 and says "pictured above", JSON fragment, `STORAGE_SECRET` wording, `all-mac` + `auth` wording, substitution link, web-ui-details command. (E-36, E-28, E-29, E-31, E-20, E-24, G1-29)
- [P3] `run/reference/python-install.md:145`: `pip install -e ".[editorial]"`. (D-20)
