# Audit E: operations, configuration, authentication, privacy

Repo HEAD: `b371427b`. Every page in scope was read line by line. Evidence comes from the source, `--help` output, and runtime experiments. All experiments ran with a sandbox `HOME` under the scratchpad. The repo was not modified.

How things were checked:
- Config loading: `get_config()` was run with chosen env vars and YAML.
- Header-auth bypass: the real `create_app()`, wrapped in uvicorn's `ProxyHeadersMiddleware` and driven through Starlette's `TestClient` with a forged peer address.
- PostgreSQL modes: a throwaway PostgreSQL 16.14 cluster on 127.0.0.1:54329, used to run `store backup`, `store restore` and `store copy` in modes 3 and 4. It was stopped and deleted afterwards.
- SQLite store downgrade: the store was downgraded one revision, then `store status` was run.

## 1. Coverage

| Page | Claims checked (approx.) | Findings | Verdict |
|---|---|---|---|
| run/config-file.md | 40 | 3 (E-9, E-17, E-24) | Precedence correct. The shipped compose silently pins several keys to env values. |
| run/environment-variables.md | 30 | 2 (E-17, E-21) | Names verified. The "all shortcuts and process variables" pointer is incomplete. |
| run/authentication.mdx | 35 | 4 (E-1, E-11, E-12, E-26) | Basic and OIDC are accurate. Header-auth trust claims are wrong once `FORWARDED_ALLOW_IPS` is set. Proxy logout does not end app sessions. |
| run/network-security.md | 30 | 3 (E-1, E-25, E-26) | `FORWARDED_ALLOW_IPS` advice is unsafe with header auth. Ports verified. |
| run/privacy.md | 30 | 5 (E-5, E-6, E-7, E-13, E-22) | The "preflight lists outside hosts" claim and the render-worker row understate what leaves. |
| run/multi-account.mdx | 30 | 3 (E-6, E-23, E-28) | Commands and env names work. "Partner key only goes to its configured server" is false with a render worker. |
| run/database.md | 25 | 3 (E-2, E-3, E-19) | Mode-4 restore destroys the store. Docker SQLite-to-PostgreSQL sequencing is missing. |
| run/maintenance/health-logs-cache.md | 35 | 3 (E-10, E-13, E-29) | Health codes and payload gating verified. `auto run --quiet` claim wrong. |
| run/maintenance/storage-backups.md | 35 | 2 (E-15, E-16) | Procedures work. Cache defaults verified. The K8s restore ignores the optional CronJob. |
| run/maintenance/upgrading.md | 20 | 2 (E-18, E-20) | Mostly accurate. Compose ships `:latest`, so "change the pinned tag" confuses. |
| run/reference/configuration.md | 45 | 4 (E-8, E-14, E-27, E-30) | `${VAR}` table misses `database.url`. "Logs never print a secret" overstated. |
| run/reference/environment.md | 30 | 3 (E-1, E-21, E-31) | `FORWARDED_ALLOW_IPS` row is dangerous with header auth. List incomplete. |
| run/reference/database.md | 25 | 3 (E-2, E-3, E-32) | Mode-4 SQL is insufficient for restore. Mode 3 verified working end to end. |
| run/reference/store-commands.md | 30 | 2 (E-2, E-4) | "`store status` never migrates" is false. Restore and copy flags verified. |
| run/reference/privacy-egress.md | 45 | 7 (E-5, E-6, E-7, E-13, E-22, E-33, E-34) | Most rows correct. Omissions: worker payload, Demucs host, inference-service and allow-download fetches, stem upload, preflight probes. |
| run/reference/household.mdx | 15 | 1 (E-28) | Commands verified. The page opens mid-thought and has a dangling "pictured above". |
| run/reference/detector-facts.md | 25 | 0 | Producer versions and `store facts` flags all match the code. |
| run/reference/rendering.md | 20 | 1 (E-35, cross-page) | Correct against `memory_budget.py`. `config-reference.md` contradicts it. |

Severity totals: **BLOCKER 2, WRONG 8, GAP 14, CLARITY 9, POLISH 3** (36 findings).

## 2. Findings

### E-1 [WRONG] run/reference/environment.md:57, run/network-security.md:186: `FORWARDED_ALLOW_IPS` presented as a plain override. With `provider: header` it breaks login, or with `*` lets anyone sign in as anyone.
- **Claim:** "`FORWARDED_ALLOW_IPS` ... Wins over `auth.trusted_proxies`." Also "`FORWARDED_ALLOW_IPS`, when set, overrides `auth.trusted_proxies`." authentication.mdx:97 says "Headers are read only when the immediate peer is in `trusted_proxies`".
- **Reality:**
  - For `provider: header` the app deliberately passes `forwarded_allow_ips=[]` to uvicorn, so the client address stays the real peer. This only happens when `FORWARDED_ALLOW_IPS` is absent from the environment (`src/immich_memories/web/reverse_proxy.py:28-35`).
  - Header auth then checks `request.client.host` against `trusted_proxies` (`web/server.py:95-103`).
  - Once `FORWARDED_ALLOW_IPS` is set, uvicorn rewrites `request.client` from `X-Forwarded-For`. If it names the proxy, the check sees the visitor and header login always fails. If it is `*`, uvicorn takes the leftmost XFF entry (`.venv/.../uvicorn/middleware/proxy_headers.py:132-133`). A client that reaches the port directly can then forge both headers and is signed in.
- **Evidence:** real `create_app()` wrapped in `ProxyHeadersMiddleware`. Config: `provider: header`, `trusted_proxies: [172.20.0.2]`.
  - Attacker at `6.6.6.6` sending `X-Forwarded-For: 172.20.0.2`, `Remote-User: attacker` to `GET /api/v1/runs`: **401** without `FORWARDED_ALLOW_IPS`, **200** with `FORWARDED_ALLOW_IPS=*`.
  - Legitimate request from proxy `172.20.0.2` (XFF `192.168.1.50`, `Remote-User: user-a`): **200** without the variable, **401** with `FORWARDED_ALLOW_IPS=172.20.0.2`.
- **Fix:** In all three places, say that `FORWARDED_ALLOW_IPS` must never be set with `provider: header`. Say it only affects the rate limiter and OIDC redirect for Basic and OIDC, and that `*` is unsafe. Ideally also refuse or warn in code.
- **Confidence:** VERIFIED (behaviour executed through uvicorn's own middleware; not run under a live uvicorn process).

### E-2 [BLOCKER] run/reference/database.md:75-83 (mode 4), run/database.md:96-100: `store restore` in the documented mode-4 setup drops the store and cannot recreate it.
- **Claim:** "Create the role and schema ... `CREATE ROLE ...; CREATE SCHEMA immich_memories AUTHORIZATION immich_memories;` That is the whole grant." The restore procedure on database.md and store-commands.md is presented as working for every backend.
- **Reality:**
  - `_restore_postgresql` runs `DROP SCHEMA <schema> CASCADE`, then `pg_restore` of a `--schema` dump (`src/immich_memories/db/backup.py:237-248`).
  - That dump contains `CREATE SCHEMA`, which needs the CREATE privilege on the database. The documented role does not have it.
  - Result: schema gone, restore fails, and every later command fails with "permission denied for database immich".
- **Evidence:** PostgreSQL 16.14, the exact doc SQL as superuser in database `immich`, then `store backup` (succeeds), then `store restore --from <dump> --force`:
  ```
  Error: pg_restore failed: pg_restore: error: could not execute query: ERROR:  permission denied for database immich
  Command was: CREATE SCHEMA immich_memories;
  ```
  `psql ... -c "select nspname from pg_namespace where nspname='immich_memories'"` then returns no row. The next `store status` reports "could not be read: permission denied for database immich". Mode 3 (role owns its own database) ran the same backup and restore successfully.
- **Fix:** Document the extra privilege for mode 4. Either add `GRANT CREATE ON DATABASE immich TO immich_memories;`, or tell DBAs to pre-create the schema and change the code to restore into an existing schema. Warn that restore drops the schema first.
- **Confidence:** VERIFIED.

### E-3 [BLOCKER] run/database.md:73-83 with run/reference/database.md:13-22: SQLite-to-PostgreSQL move on Docker cannot be done in the order the pages give.
- **Claim:** database.md: "Create the target database/role using one of the PostgreSQL modes, then: `immich-memories store copy --to ...` ... Point `IMMICH_MEMORIES_DATABASE_URL` at the target and restart." The mode-2 recipe says "Uncomment all three [service, URL line, volume] ... and `docker compose up -d`".
- **Reality:**
  - Following mode 2 first puts the app on the empty PostgreSQL, because `IMMICH_MEMORIES_DATABASE_URL` is now set.
  - `store copy` then reads from the configured store (PostgreSQL), not the SQLite file (`cli/store_cmd.py:156-166`, `resolve_location`). With the compose URL it refuses: "the target is the store itself".
  - The working order is: uncomment and start only the `postgres` service, run `store copy` while the app still uses SQLite, then uncomment the URL and run `docker compose up -d`.
  - "restart" is also wrong on Docker. env-vars.md:30 itself says `restart` does not reload environment variables.
- **Evidence:** `store_cmd.py:156-166` (source = `_location(ctx)` = configured store). The self-copy guard is at line 164.
- **Fix:** Add an explicit Docker sequence. Replace "restart" with `docker compose up -d`.
- **Confidence:** LIKELY (code path read; the Docker sequence was not executed).

### E-4 [WRONG] run/reference/store-commands.md:21: "`store status` ... never migrates it".
- **Reality:** every CLI command loads config, and loading config reads the stored settings through `open_store()`, which migrates to head (`settings_store.py:207-211`, `config_loader.py:258-271`). An existing older store is upgraded before `status` prints, so the "not at head" branch (`store_cmd.py:65`) never shows.
- **Evidence:** a SQLite store downgraded to `0010_run_film_timeline` (confirmed with `current_revisions`), then `immich-memories store status` printed `Revision:  0011_people_groups (at head)`. A PostgreSQL schema was likewise at head on the first `status`.
- **Fix:** Reword ("any command, `status` included, upgrades an existing store first; it does not create a missing SQLite file"). Also warn in upgrading/rollback that any new-version CLI command migrates the store. Or fix the code so `status` loads config with stored settings skipped.
- **Confidence:** VERIFIED.

### E-5 [WRONG] run/privacy.md:37, run/reference/privacy-egress.md:32, run/maintenance/health-logs-cache.md:23: "`preflight` also lists outside hosts you have enabled" / "one row per outside switch".
- **Reality:** `outside_call_checks` lists only `network.geocoding` and `network.map_tiles` (`src/immich_memories/preflight_network.py:7-10`). None of these get an "Outside call" row: a hosted reader (`api.openai.com`, any remote `llm.base_url`), `title_llm`, notification URLs, a remote render worker, a remote inference service, or a hosted ACE-Step or MusicGen. A privacy reader will take a clean preflight as "nothing leaves".
- **Fix:** Say "preflight names the two `network` switches", or extend the check to every non-private endpoint.
- **Confidence:** VERIFIED.

### E-6 [WRONG] run/multi-account.mdx:170, run/reference/privacy-egress.md:23, run/privacy.md:28: render-worker payload understated, and the partner key leaves for the worker.
- **Claims:**
  - multi-account.mdx:170: "The partner key only goes to its configured server."
  - privacy-egress.md:23: "the chosen cut, plus your Immich URL and API key".
- **Reality:** `render_access` adds every selected extra account's `api_key` to the worker request (`processing/remote_render_access.py:23-40`). `build_render_request` also sends:
  - `person_name`
  - home coordinates (`options.homebase_latitude/longitude`)
  - the whole `network` config
  - title text

  See `processing/remote_render_plan.py:39-88`. Because the network config travels, a worker with `map_tiles` or `geocoding` on makes those outside calls from the worker host.
- **Fix:** List the partner keys, home coordinates, names, titles and network switches in the render-worker row. Correct multi-account's privacy note.
- **Confidence:** VERIFIED (code).

### E-7 [WRONG] run/reference/privacy-egress.md:29, run/privacy.md:8: "a run never downloads" / "rendering does not download them". Several shipped paths do download.
- **Reality:**
  - (a) `advanced.editorial.preparation.allow_model_downloads: true` lets the detector worker fetch Docling from Hugging Face during a run (`analysis/editorial_preparation_detectors.py:250-262`, `editorial_preparation.py:426`).
  - (b) The shipped compose `immich-memories-inference` profile sets `IMMICH_MEMORIES_INFERENCE_ALLOW_MODEL_DOWNLOADS: "true"` ("A cold cache fetches the pinned encoder, the pinned Marqo export and the Docling snapshot once, on first use", `docker-compose.yml:164-167`).
  - (c) The captioner profile's puller curls `huggingface.co` at `up` (`docker-compose.yml:240-242`).
  - (d) `capabilities --test-music` "may download models" (`--help`).
  - (e) Local Demucs downloads from Torch Hub, which is `dl.fbaipublicfiles.com`, not Hugging Face or GitHub (`local_capabilities.py:131-140` patches `torch.hub.download_url_to_file`).
  - (f) The ACE-Step `lib` downloader (`acestep.model_downloader.ensure_lm_model`, `ace_step_runtime.py:311`) is not digest-pinned by this app, contrary to "pinned weights, checked by SHA-256".
  - privacy.md:8 also contradicts its own line 80.
- **Fix:** Add rows or footnotes for `allow_model_downloads`, the inference and captioner profiles, Torch Hub's host, and ACE-Step's unpinned downloader. Drop "a run never downloads" or qualify it.
- **Confidence:** VERIFIED for a-e (code and compose). LIKELY for f (`acestep` is not installed here, so the remote host and absence of pinning could not be observed).

### E-8 [GAP] run/reference/configuration.md:128-139: `${VAR}` table omits `database.url`, `editorial.laya_checkpoint`, and `immich.accounts.<name>.url/api_key`.
- **Evidence:**
  - `DatabaseConfig.expand_env` (`config_models.py:150-156`) has the docstring "Expand `${VAR}` so a password can stay out of the file".
  - `ImmichConnection.expand_env` (`config_models.py:96`) covers accounts.
  - `config_models_editorial.py:184` covers `annotation_database` and `laya_checkpoint`.
  - The table claims to be the list ("These fields expand").
- **Fix:** Add the rows. `database.url` is the one a PostgreSQL user most needs.
- **Confidence:** VERIFIED.

### E-9 [GAP] run/config-file.md:30-43: precedence is correct, but the shipped compose always sets env vars that silently beat YAML and Settings.
- **Reality:** `docker-compose.yml` always sets the following, even with an empty `.env`:
  - `IMMICH_URL` (default `http://immich-server:2283`)
  - `IMMICH_MEMORIES_TRIPS__HOMEBASE_LATITUDE/LONGITUDE` (default `0`)
  - `IMMICH_MEMORIES_TIER: auto`
  - `IMMICH_MEMORIES_EDITORIAL__PREPARATION__DETECTOR_CACHE_DIR`
  - `TZ`

  A Docker user who writes the quick-start `trips:` block (config-file.md:18-20) into `config.yaml` or saves home in Settings gets `0,0`, so no trips.
- **Evidence:** YAML `trips.homebase_latitude: 50.85` plus env `IMMICH_MEMORIES_TRIPS__HOMEBASE_LATITUDE=0` gives `get_config().trips.homebase_latitude == 0.0`. With both `IMMICH_URL=https://short` and `IMMICH_MEMORIES_IMMICH__URL=https://nested`, the result is `https://short`.
- **Fix:** Add a "Docker: these keys are pinned by the compose file; set them in `.env` or delete the lines" note, listing them.
- **Confidence:** VERIFIED.

### E-10 [WRONG] run/maintenance/health-logs-cache.md:64-65: "`generate --quiet` and `auto run --quiet` change what the terminal shows, not what is logged."
- **Reality:** `auto run --quiet` calls `logging.disable(logging.CRITICAL)` for the whole run (`cli/auto_cmd.py:239-256`, comment: "--quiet turns logging off entirely"). Nothing is logged, `-v` included, despite the option help saying "-v adds log detail".
- **Fix:** Correct the sentence for `auto run --quiet`.
- **Confidence:** VERIFIED (code).

### E-11 [GAP] run/authentication.mdx:80-100: header auth keeps the first user for the whole session TTL.
- **Reality:** `_try_header_auth` only starts a session when none exists (`web/server.py:101`). The header is never re-read while a session lives, up to `session_ttl_hours` (24h). A sign-out at Authelia or oauth2-proxy, or a different `Remote-User` from the same browser, does not change who the app thinks is signed in.
- **Fix:** State this, and suggest a short `session_ttl_hours` with header auth, or signing out through `/logout` too.
- **Confidence:** VERIFIED (code).

### E-12 [CLARITY] run/authentication.mdx:59-60, run/network-security.md:184-185: "Register ... the logout URL `https://your-host/logout`".
- **Reality:** `/logout` redirects to the IdP's `end_session_endpoint` with no `post_logout_redirect_uri` or `id_token_hint` (`web/server.py:180-190`; `grep -rn post_logout src/` finds nothing). The IdP never sends the browser back to a registered logout URL, so registering it does nothing.
- `get_end_session_url` also returns None until the process has built its OIDC client (`auth_oidc.py:110-119`). After a restart, the first logout of a pre-restart session stops at the app's sign-in page and leaves the IdP session alive.
- **Fix:** Drop the logout-URL instruction, or implement `post_logout_redirect_uri`. Document the after-restart case.
- **Confidence:** VERIFIED (code). LIKELY for IdP behaviour.

### E-13 [GAP] run/reference/privacy-egress.md:22: inference-service row omits the stem upload and the health probe.
- **Reality:**
  - With music generation and `separate_stems`, the generated mix (WAV) is posted to `{facts_base_url}/audio/stems` (`audio/music_pipeline.py:504-514`, `audio/generators/inference_demucs.py:46-51`).
  - Every config load with inference enabled also GETs `{facts_base_url}/health` (`config_compute.py:18`).
- **Fix:** Add "the generated music track, for stem separation" and the health probe.
- **Confidence:** VERIFIED.

### E-14 [WRONG] run/reference/configuration.md:78: "Logs never print a secret, whichever source it came from."
- **Reality:** redaction ignores secrets shorter than 8 characters (`logging_config.py:59,77`, `MIN_REDACTABLE_SECRET_LENGTH = 8`). A 6-character Basic-auth password or token is not redacted.
- **Fix:** Qualify the claim ("secrets of 8+ characters").
- **Confidence:** VERIFIED.

### E-15 [GAP] run/maintenance/storage-backups.md:73-80: K8s restore ignores the optional CronJob or Job.
- **Reality:** `deploy/kubernetes/base/job.yaml` (optional, commented in `kustomization.yaml:17`) labels its Job and CronJob pods `app.kubernetes.io/name: immich-memories` (lines 33, 41, 204, 217), with `ttlSecondsAfterFinished: 604800` and `successfulJobsHistoryLimit: 3`.
- Two consequences:
  - `kubectl wait --for=delete pod -l app.kubernetes.io/name=immich-memories --timeout=120s` then waits on completed batch pods and times out.
  - A CronJob firing during the restore writes to the same PVC. The page says "Stop the UI, timers and workers first" but gives no `kubectl patch cronjob ... suspend: true`.
- **Fix:** Add `-l app.kubernetes.io/name=immich-memories,!app.kubernetes.io/component` or select by Deployment. Add suspend and resume steps for CronJobs.
- **Confidence:** LIKELY (manifests read; not applied to a cluster).

### E-16 [CLARITY] run/maintenance/storage-backups.md:38 vs run/database.md:34: `docker cp immich-memories:...` vs `docker compose cp immich-memories:...`.
- Both work because `container_name: immich-memories` (`docker-compose.yml:36`). A reader who renamed the container will find only one of them works.
- **Fix:** Use `docker compose cp` in both.
- **Confidence:** VERIFIED.

### E-17 [CLARITY] run/environment-variables.md:79-80, run/reference/environment.md:22: "only when the config file states no key".
- **Reality:** `_llm_key_from_env` yields to any non-empty `llm.api_key` after env, YAML and the database are merged (`config_loader.py:455-469`). A key saved in Settings also beats `OPENAI_API_KEY`, not just one in the file.
- **Fix:** Say "when no other source sets `llm.api_key`".
- **Confidence:** VERIFIED (code).

### E-18 [CLARITY] run/maintenance/upgrading.md:24: "Change the pinned `image:` tag before pulling."
- The shipped compose uses `:latest` (`docker-compose.yml:35`), so there is no pinned tag. The snippet above it (`pull` then `up -d`) silently takes whatever `latest` is. Rollback (lines 82-91) needs a tag the reader never wrote down.
- **Fix:** Tell readers to pin `X.Y.Z` in compose first and record it before upgrading.
- **Confidence:** VERIFIED.

### E-19 [GAP] run/database.md:51-63, run/maintenance/upgrading.md:76-91: rollback sequencing on Docker.
- The Docker rollback snippet only changes the tag and runs `up -d`. With a store migrated by the newer release, old code fails on the unknown Alembic revision. The restore must run with the old image before `up -d`.
- No Docker command sequence ties the two together.
- **Fix:** Give one ordered block: stop, set the old tag, pull, `docker compose run --rm ... store restore --from ... --force`, then `up -d`.
- **Confidence:** LIKELY (no "newer revision" handling in `db/migrate.py`, so Alembic's own error surfaces; not executed).

### E-20 [POLISH] run/maintenance/upgrading.md:41: "`all-mac` (and `auth` if added)".
- Correct: `all-mac` lacks `auth` (`pyproject.toml:144-150`). Spelling out `immich-memories[all-mac,auth]` would be clearer.

### E-21 [GAP] run/environment-variables.md:83, run/reference/environment.md:41-57: "lists all shortcuts and process variables" is incomplete.
- The process variables read from `os.environ` but missing from the exception list:
  - `IMMICH_MEMORIES_DATABASE_URL`
  - `IMMICH_MEMORIES_DATABASE_SCHEMA` (`db/bootstrap.py:21-22`)
  - `IMMICH_MEMORIES_ALLOW_NETWORK_SQLITE` (`db/network_guard.py:22`)
  - `IMMICH_MEMORIES_IMPORT_FROM` (`store/legacy_imports.py:41`)
  - `PYTORCH_MPS_HIGH_WATERMARK_RATIO` (copied by `auto install`, `automation/system_scheduler.py:53`, mentioned only inside the caution box)
- `IMMICH_MEMORIES_DATABASE_URL` does not follow the `<SECTION>__<FIELD>` pattern, although `__URL` also works (tested).
- **Fix:** Add rows.
- **Confidence:** VERIFIED.

### E-22 [GAP] run/reference/privacy-egress.md:16-19: reader and title rows omit payloads.
- **Reality:**
  - Free-text requests send the owner's sentence (`free_text/reading.py:33-38`).
  - The trip title prompt also sends "Clip content: ..." captions, "Objects: ...", daily locations and country (`titles/llm_titles.py:508-525`).
  - `title_llm` (`config_loader.py:344`) can name a separate endpoint, which the table never mentions.
- **Fix:** Add these to the rows.
- **Confidence:** VERIFIED.

### E-23 [GAP] run/multi-account.mdx:41-46: the Docker partner URL uses `${IMMICH_URL}` with no default.
- The app service's own `IMMICH_URL` falls back to `http://immich-server:2283` (`docker-compose.yml:46`). The suggested `IMMICH_MEMORIES_IMMICH__ACCOUNTS__PARTNER__URL: "${IMMICH_URL}"` becomes empty when `.env` leaves `IMMICH_URL` unset, and the partner connection fails.
- The page also says "a read-only API key" without listing the permissions the partner key needs.
- **Fix:** Use `"${IMMICH_URL:-http://immich-server:2283}"`, and link the permission list.
- **Confidence:** VERIFIED (compose substitution semantics).

### E-24 [CLARITY] run/config-file.md:139-141: "Substitution is supported for credentials and selected service/path fields".
- A reader cannot tell which fields from this page. The table lives in reference/configuration.md and is incomplete (E-8).
- **Fix:** Link it.

### E-25 [CLARITY] run/network-security.md:141-152: `trusted_proxies: [127.0.0.1]` with the shipped `127.0.0.1:8080:8080` mapping.
- With Docker's default userland proxy, the container sees the bridge gateway (e.g. `172.17.0.1` or the compose network's `.1`), not `127.0.0.1`. The page says "may", but on default Docker it is the normal case. Nothing tells the reader how to find the address.
- authentication.mdx:104 promises "the four settings that make HTTPS login work". The recipe shows three YAML keys, and "four" is never enumerated.
- **Fix:** Give `docker network inspect` or a log-line method, and list the settings.
- **Confidence:** LIKELY (Docker default behaviour, not executed here).

### E-26 [GAP] run/network-security.md:125-134: `server.allow_unauthenticated_lan` not mentioned.
- The page explains when an unauthenticated app binds beyond localhost. It omits the explicit escape hatch (`config_models_server.py:46-53`, honoured in `effective_host` lines 63-64) that the loader's own warning names (`config_loader.py:185-189`).
- **Confidence:** VERIFIED.

### E-27 [CLARITY] run/reference/configuration.md:83-84: `title_llm` listed as an "everyday" top-level section.
- The loader docstring calls it "Tier 3 (internal)" (`config_loader.py:308`). Listing it beside `immich` and `output` invites newcomers to set it. Separately, `config-reference.md:13-14` omits `speech` from its Tier-2 list, while `_TIER2_SECTIONS` (`config_loader.py:58-75`) and this page include it (cross-page).

### E-28 [CLARITY] run/reference/household.mdx:7-9, 58-59: the page opens with an H3 and has a dangling "pictured above".
- The page starts with `### Someone only the partner account knows` and no introduction (the import sits after the H1). It duplicates multi-account.mdx:143-166.
- Line 59, "(pictured above, with both accounts picked)", refers to a New-memory screenshot that is on multi-account.mdx (`memory-brief-accounts`), not on this page. The only image above it here is `people-saved-groups`.
- **Fix:** Add an introductory line, de-duplicate, and fix the reference.

### E-29 [CLARITY] run/maintenance/health-logs-cache.md:53-57: the example JSON is a fragment.
- The real payload also carries `configuration`, the `immich` object (`status`, `reachable`, `api_version_policy`, `resolved_api_version`), `disk`, `in_process_scheduler` and others (`web/health.py:289-315`). For unauthenticated probes with auth on, the detail fields are present but `null` (`_for`, lines 146-158), not absent.
- Also cross-page: reference/automation-contract.md:37 says "`/health/ready` shows the timer under `in_process_scheduler`". That holds only for a signed-in session or with auth off.
- **Confidence:** VERIFIED.

### E-30 [GAP] run/reference/configuration.md:19-25: the unreadable-store rule versus PostgreSQL boot order.
- Accurate as written (`settings_store.py:214-231`, `web/server.py:334-338`).
- The shipped compose `postgres` service has no `depends_on` on the app service (`docker-compose.yml:340-359`). On first `up`, the app can start before PostgreSQL accepts connections, refuse to start, and rely on `restart: unless-stopped`.
- **Fix:** Note it or add `depends_on: {postgres: {condition: service_healthy}}` to the commented block.
- **Confidence:** LIKELY.

### E-31 [POLISH] run/reference/environment.md:43: `IMMICH_MEMORIES_STORAGE_SECRET` "then generated on first start".
- Correct (`web/server.py:71-83`). The compose comment (`docker-compose.yml:56`, "set to preserve sessions on restart") contradicts it, since the generated file sits on the persistent config volume. That is a cross-surface inconsistency, not a page error.

### E-32 [GAP] run/reference/database.md:35: "Plain PostgreSQL 14+" with the mode-3 and mode-4 SQL.
- Mode 3 verified working on 16.14 (copy, backup, restore all succeeded).
- The mode-3 SQL block puts `CREATE ROLE` and `CREATE DATABASE` together. Pasted as one `psql -c` string it fails with "CREATE DATABASE cannot run inside a transaction block" (observed). Interactive `psql` is fine.
- Mode 4 lacks the CREATE privilege (E-2).
- **Fix:** Say "run each statement separately".
- **Confidence:** VERIFIED.

### E-33 [GAP] run/reference/privacy-egress.md:29-30: download destinations for allow-listing firewalls.
- `github.com` release assets and `huggingface.co` files redirect to CDN hosts (`release-assets.githubusercontent.com` / `objects.githubusercontent.com`, and HF's LFS or Xet CDN). `urllib.request.urlopen` follows redirects (`pinned_models.py:128-135`). A privacy user allow-listing only the named hosts will see `models fetch` fail.
- **Confidence:** LIKELY (redirect targets are external behaviour; not fetched).

### E-34 [GAP] run/reference/privacy-egress.md (no row): `preflight` sends requests to every configured endpoint.
- `check_llm` POSTs `{"messages":[{"role":"user","content":"hi"}],"max_tokens":1}` to an OpenAI-compatible endpoint, or a one-token `/v1/messages` to Anthropic, with the API key (`preflight.py:222-262, 312-341`). Hosted endpoints bill for this.
- The caption endpoint gets `GET /models` (`preflight.py:586`). No library data, but it is outbound.
- **Fix:** Add one row: "`preflight`: an auth probe to each configured endpoint".
- **Confidence:** VERIFIED.

### E-35 [WRONG, cross-page] reference/config-reference.md:185 vs run/reference/rendering.md:12-15: preparation-worker sizing.
- **Contradiction:** config-reference says "auto: 1 per 2 GB". rendering.md says a 1 GiB reserve, then 3 GiB per worker.
- **Code:** `processing/memory_budget.py:25-26,127-128` (`_SOURCE_GIB_PER_WORKER = 3`, `_PARENT_RESERVE = 1 GiB`). rendering.md is right. The config-reference text comes from the stale field description at `config_models_analysis.py:34-36`.
- **Confidence:** VERIFIED.

### E-36 [POLISH] run/reference/privacy-egress.md:15, run/reference/database.md:9: leftovers from page splits.
- privacy-egress row 1, "the reads above": there are no reads above on this page.
- reference/database.md starts its numbering at "## 2." with no "1." (the SQLite mode lives on the parent page).

## 3. Egress completeness

Method: grep of `httpx|requests|urllib|urlopen|hf_hub_download|torch.hub|Nominatim|StaticMap|apprise|socket` across `src/immich_memories/**.py`. Every importing file was checked, and files that only catch `httpx.HTTPError` were excluded. Also checked: hard-coded `https://` hosts, `web/src` (no external hosts besides docs links), and `docker-compose.yml`. No telemetry, analytics, update check or PyPI/GitHub API call exists.

| Call site | Destination | Trigger | Documented? |
|---|---|---|---|
| `api/immich.py:162` (+ `api/accounts.py`, `api/access_clients.py`, `cache/video_cache.py`, `processing/download_coordinator.py`, `generate_downloads.py`) | `immich.url` and each `immich.accounts.<n>.url` | every run / UI | Y. Extra-account servers are not named in the table. |
| `web/dependencies.py:79` | `immich.url` | UI media proxy | Y (privacy.md "Thumbnails") |
| `home_country.py:55` | `immich.url/api/map/reverse-geocode` | holidays with home set | Y (Immich) |
| `web/health.py:55` (ImmichClient) | Immich | `/health*` (10 s cache) | Y implicitly |
| `api/album_service.py:222-449` | Immich writes (upload, tags, albums, trash) | upload on | Y |
| `analysis/llm_query.py:492,564,716`; `llm_batch.py:527` | `llm.base_url`, `title_llm.base_url`, provider batch routes | reader, titles, music, special days, free text, overviews | Partial: `title_llm` and free-text sentence missing (E-22) |
| `local_inference.py:227` | `127.0.0.1:<port>` owned llama-server | blank `base_url` | Y (local) |
| `analysis/editorial_preparation_captions.py`, `editorial_preparation_motion.py` | `caption_base_url` or LLM caption provider | GPU/Full or `caption_provider: llm` | Y |
| `analysis/remote_facts.py:90` | `inference.facts_base_url` | preparation | Y |
| `config_compute.py:18` | `{facts_base_url}/health` | every config load with inference enabled | N (E-13) |
| `audio/generators/inference_demucs.py:46` | `{facts_base_url}/audio/stems` (generated WAV) | stems with music generation | N (E-13) |
| `audio/music_generator_client.py:98` | `musicgen.base_url` (+ generated track for stems) | MusicGen on | Y |
| `audio/generators/ace_step_backend.py:159,399` | `ace_step.api_url` | API mode, or `lib` mode with no library (fallback) | Y. The lib-to-API fallback is not stated. |
| `ace_step_runtime.py:311` (acestep downloader) | ACE-Step weights host (not verified) | `lib` first use, `capabilities --test-music` | Partial: host not named, SHA claim unsupported (E-7) |
| `audio/generators/demucs_local.py:94` (torch.hub) | `dl.fbaipublicfiles.com` | local stems, first use | Wrong host listed (E-7) |
| `processing/remote_render.py:46` | `render.worker_base_url` (+ Immich and partner keys, home, names, network config) | remote render | Partial (E-6) |
| `analysis/place_geocoder.py:124` (geopy) | `nominatim.openstreetmap.org` or `network.geocoding_url` | `network.geocoding: true` | Y (also sends `language`, cached per cell and language) |
| `titles/map_animation.py:181`, `titles/map_renderer.py:122` (staticmap) | `server.arcgisonline.com` | `network.map_tiles: true` | Y. The `osm` and `topo` styles in `MAP_STYLES` are unreachable from config. |
| `automation/notifications.py:121` (apprise) | notification URLs | `notifications.enabled` | Y (also sends run warnings; error is first 200 chars, redacted only on the automation path) |
| `web/auth_oidc.py` (authlib) | IdP discovery, token, JWKS, userinfo, end-session | OIDC login | Y |
| `pinned_models.py:133` | `huggingface.co` (reader GGUF), `github.com` releases (encoder, Marqo, Laya), `raw.githubusercontent.com` (WordNet), plus CDN redirects | `models fetch`, K8s init container | Y (redirect hosts missing, E-33) |
| `cli/models_cmd.py:160` | `huggingface.co` detector snapshots | `models fetch` (GPU/Full or `--detectors`) | Y |
| `analysis/editorial_preparation_detectors.py:255` | `huggingface.co` (Docling) | run, with `allow_model_downloads: true` | N (E-7) |
| `titles/script_fonts.py:328` | `raw.githubusercontent.com` | `titles fonts --install`, image build | Y |
| `model_bundle.py:23-46` | HF and GitHub | CUDA image build only | Y (build) |
| `preflight.py:153,238,336,586` | LLM endpoint ("hi" probe, key), caption `/models` | `preflight` | N (E-34) |
| compose `immich-memories-inference` (`ALLOW_MODEL_DOWNLOADS=true`) | HF and GitHub from the inference container | first use in a run | N (E-7) |
| compose `immich-memories-caption-models` | `huggingface.co` | `docker compose --profile captioner up` | N (E-7) |

## 4. Unverifiable claims (not reported as wrong)

- `pip install --upgrade "immich-memories[all]"` (upgrading.md:38) and `uv tool install ... immich-memories[all]==X.Y.Z`: PyPI publication was not checked.
- That the Docker base image ships `postgresql-client` 17 (database.md:47, store-commands.md:39). Taken from the Dockerfile comment; the image was not built.
- Docker userland-proxy peer addresses (network-security.md:150-152), and `kubectl wait --for=delete` behaviour with zero or completed matches.
- Authelia, Keycloak and Auth0 client-type advice (authentication.mdx:60-63), and IdP behaviour without `post_logout_redirect_uri`.
- ACE-Step lib weight host and pinning. Demucs host was confirmed from the Torch Hub patch, not from an installed `demucs` package.
- household.mdx:205-206 ("A later `people scan` keeps the entry") and :237-238 (automation skips a named group under its default settings). The code paths were not traced.
- health-logs-cache.md:104 "Web jobs keep their own output under `cache/web-jobs/`": cut jobs pass `--output cache/web-jobs/web-<id>.mp4` (`web/job_routes.py:207`). Whether a film rendered from the web stays there or in `output.directory` was not traced. If it stays, storage-backups.md:20's "cache.directory: Disposable" would lose web films.
- rendering.md encoder lookahead and decode-thread figures (lines 19-26), beyond the worker sizing checked in E-35.
- Release-notes link and the "older code will refuse" behaviour (upgrading.md:9-10): no explicit handling found; Alembic's generic error is assumed.

Verified correct and worth keeping as written:
- Precedence order and the merge rules: both `advanced:` and top-level accepted, top level wins a tie, unknown top-level sections fail (`extra_forbidden` observed), unknown in-section keys ignored.
- Shortcut set and empty-is-unset. `IMMICH_URL` beats `IMMICH_MEMORIES_IMMICH__URL`.
- 32-character secret key, Fernet + HKDF, and the secret-name list.
- Basic auth shortcut forces `provider: basic`. OIDC PKCE S256. `allowed_domains` exact match. `email_verified` must be literal `true`. 403 "Not authorised" page. `/auth/callback` and `/logout` paths.
- Health routes and status codes: live 200, ready 200/503, `/health` 200 with `ok`; 5 s bound, 10 s cache, detail gating.
- Log format, stderr routing, JSON logs.
- Cache defaults (10 GB / 7 d / 10000 MB). Local film removed after a confirmed upload.
- `store backup`/`restore`/`copy` flags, manifest, never-overwrite, SQLite sidecar removal, foreign-table refusal.
- 42 Noto files. Geocoding rounding to 2 decimals, 1 request/s, User-Agent. Map tiles gated by `network.map_tiles` in all three render paths.
- Detector producer versions. Rate-control table.
- Every `IMMICH_MEMORIES_*` example on the pages, tested through `get_config()`: `AUTH__ALLOWED_EMAILS`, `ANALYSIS__EXCLUDE_FILENAME_PATTERNS`, `TITLE_SCREENS__FADE_COLOR`, `EDITORIAL__PREPARATION__CAPTION_BASE_URL`, `IMMICH__ACCOUNTS__PARTNER__*`, `AUTOMATION__ACCOUNTS`, `DATABASE__SCHEMA`.
- Voice gate: `make`'s `scripts/docs_voice_gate.py` reports "docs-voice: clean".
