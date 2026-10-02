# Audit B: CLI pages, CLI reference, automation contract

Auditor B. Read-only. `make docs-cli-check` was run: output `CLI reference is up to date`, and `git status --short` was empty afterwards.
Every flag in every example on the assigned pages was checked against `uv run --no-sync immich-memories <cmd> [sub] --help`: all 61 flag/argument checks matched (script output: every line `OK`). The bare `--birthday --person "Riley"` form was checked against Click 8.4.2's parser in isolation (it yields `birthday='auto'`, `person=('Riley',)`).

## 1. Coverage

| Page | Claims checked (approx.) | Findings | Verdict |
|---|---|---|---|
| make/cli/discover-days.md | 18 | 2 (B-27, B-32) | Accurate. Docker users cannot follow the export/import step as written |
| make/cli/generate.md | 34 | 4 (B-21, B-22, B-23, B-24) | Accurate on flags. Upload/local-copy behaviour and the `--quality` names are incomplete |
| make/cli/people.md | 20 | 2 (B-27, B-33) | Accurate. Same Docker export/import gap |
| make/cli/pictures.md | 16 | 2 (B-19, B-31) | Accurate. Where to get an ASSET_ID is circular |
| make/cli/prepare.md | 17 | 1 (B-28) | Accurate. The `--overviews` preconditions are misstated |
| make/cli/report.md | 15 | 2 (B-25, B-26) | Accurate. Needs the full run ID, unlike `runs` |
| make/cli/runs.md | 26 | 2 (B-29, B-30) | One false claim (`show` and delivery) |
| reference/cli-reference.md (generated) | ~250 rows plus prose | 8 (B-17 to B-21, B-24, B-31, B-33) | In sync with Click. One false help string, a time bomb in the drift gate, global options missing |
| reference/automation-contract.md | ~95 | 16 (B-1 to B-16) | Most numbers are right. The Docker `.env` route, the Kubernetes section, the birthday claim and the `action` contract are wrong |

Unique findings: 33 (1 BLOCKER, 13 WRONG, 11 GAP, 6 CLARITY, 2 POLISH). Findings shared between pages: B-24 (generate.md, cli-reference.md), B-27 (discover-days.md, people.md), B-31 (pictures.md, cli-reference.md), B-33 (people.md, cli-reference.md, pictures, generate.md).

## 2. Findings

### B-1 [BLOCKER] reference/automation-contract.md:30-31: putting the automation variables in `.env` does not reach the container
- **Claim:** "or `IMMICH_MEMORIES_AUTOMATION__ENABLED=true` and `IMMICH_MEMORIES_AUTOMATION__DAILY_AT=09:00` in your `.env`, then recreate the container with `docker compose up -d`."
- **Reality:** `docker-compose.yml` has no `env_file:`. Compose reads `.env` only to fill `${...}` in the compose file, and the service's `environment:` block carries only explicitly mapped variables. The two automation lines are commented out and have no `${}` interpolation (`docker-compose.yml:88-89`). A variable set only in `.env` never reaches the process, so the timer stays off and nothing reports an error.
- **Evidence:** `grep -n "env_file\|AUTOMATION" docker-compose.yml` returns only lines 88-89, both commented. Cross-page contradiction: `make/automate.md:14-19` and `run/docker.md:199-205` correctly say to uncomment the lines in `docker-compose.yml`.
- **Fix:** Replace the `.env` sentence with "uncomment the two `IMMICH_MEMORIES_AUTOMATION__*` lines under the service's `environment:` in `docker-compose.yml`" (the same wording as automate.md). Alternatively, change the compose lines to `"${IMMICH_MEMORIES_AUTOMATION__ENABLED:-false}"` so `.env` works.
- **Confidence:** VERIFIED by reading the compose file. `docker compose` was not run.

### B-2 [WRONG] reference/automation-contract.md:233-234, 242-243: the "monthly" CronJob does not run `generate` and shares no volumes
- **Claim:** "`job.yaml` holds a one-off `generate` Job plus monthly and `auto run` CronJobs. It reads the `immich-memories-secrets` Secret and shares the volumes…" Also: "A cron line (or a Kubernetes CronJob like the monthly one above) that runs `generate` says it."
- **Reality:** Both CronJobs are curl containers that `POST http://immich-memories/api/trigger`. That route takes no parameters and runs whatever `auto run` would pick, not last month's highlights. They mount no volumes, and they read only one key of the Secret. The file says so itself: "`POST /api/trigger` takes no parameters … not this fixed 'last month' command … point your own cron at `kubectl exec deploy/immich-memories -- immich-memories generate …`".
- **Evidence:** `deploy/kubernetes/base/job.yaml:182-196` (comment), `:229-251` (monthly CronJob: curl image, `secretKeyRef … key: IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN`, no volumes), `:300-320` (auto CronJob, same shape).
- **Fix:** Describe the CronJobs as trigger callers. Drop "like the monthly one above" from the named-date section, and give the `kubectl exec deploy/immich-memories -- immich-memories generate …` form that job.yaml recommends.
- **Confidence:** VERIFIED (file read).

### B-3 [WRONG] reference/automation-contract.md:236-238: `kubectl apply -f deploy/kubernetes/base/job.yaml` starts a one-off Job that must not run beside the Deployment
- **Claim:** The page gives `kubectl apply -f deploy/kubernetes/base/job.yaml` as the way to install the scheduled jobs.
- **Reality:** The same file also defines `Job immich-memories-generate`, which runs straight away with hard-coded `generate --year 2024 --person "Ada" --duration 600` on the `data`/`output`/`models` PVCs. The file header says: "only start it while the Deployment is down", because "a second pod writing that same file from another node over ReadWriteMany corrupts it". Applying the whole file next to a running Deployment does exactly that. The Job also fails on any library without a person named "Ada".
- **Evidence:** `deploy/kubernetes/base/job.yaml:4-15` (warning), `:28-31` (Job kind), `:109-131` (command with `"Ada"`, `"2024"`).
- **Fix:** Tell readers to apply only the CronJobs, or split job.yaml into `cronjobs.yaml` and `generate-job.yaml`, and repeat the "Deployment must be down" warning next to the Job.
- **Confidence:** VERIFIED (file read). Not applied to a cluster.

### B-4 [WRONG] reference/automation-contract.md:94: "A birth date you gave the people store wins over the one Immich holds" holds for the decision only, not for the film
- **Claim:** The store's birth date wins over Immich's.
- **Reality:** Candidate discovery does overlay store birth dates (`automation/people_merge.py:117-124`, `candidate_discovery.py:373-374`). But the birthday candidate is executed as `generate --year Y --birthday --person=NAME` with a bare `--birthday` (`automation/generation_request.py:157`). In `generate`, a bare `--birthday` resolves through `client.get_person_by_name(...)` and `birthday_anchor(found.birth_date, None, …)` (`cli/generate.py:582-589`), which reads Immich only. When Immich has no birth date, it raises "has no birth date … Set one in Immich" (`memory_types/date_builders.py:238-244`). So a birth date held only in the store produces a candidate whose run fails. When the two dates differ, the film's window follows Immich, not the store.
- **Evidence:** The paths above. `make/cli/generate.md:45` ("set the birth date in Immich") is correct for `generate`.
- **Fix:** Either pass the resolved `--birthday MM-DD` from the candidate in `generation_request.py`, or reword: "Detection prefers the people store's birth date; the film's window uses Immich's, so set it there too."
- **Confidence:** VERIFIED by code reading. Not executed.

### B-5 [WRONG] reference/automation-contract.md:129-130: "`action` is `generation` on every path" is false
- **Claim:** "Key a wrapper on `outcome`: `action` is `generation` on every path."
- **Reality:** `AutoAction` has `DELIVERY_RETRY = "delivery_retry"` (`automation/models.py:25-29`). The pending-upload retry leg returns `action=AutoAction.DELIVERY_RETRY` (`automation/delivery_retry.py:173-181`), and `runner.py:593-597` returns that result before any generation. Line 122 of the same page says a run retries a pending upload first, so `delivery_retry` shows up in practice.
- **Fix:** "`action` is `generation`, or `delivery_retry` when the run retried a pending upload instead."
- **Confidence:** VERIFIED.

### B-6 [WRONG] reference/automation-contract.md:129-146: the quiet-output example contradicts the sentence above it
- **Claim:** "Quiet output is a stable JSON object with `runtime` as its first key". The example that follows has no `runtime` key and is spread over 15 lines.
- **Reality:** `_auto_result_to_json` puts `"runtime": runtime` first (`cli/auto_cmd.py:74-79`) and prints one line (`--quiet` help: "One machine-readable line per decision").
- **Fix:** Add a `"runtime": {…}` member as the first key, and note that the real output is a single line.
- **Confidence:** VERIFIED.

### B-7 [WRONG] reference/automation-contract.md:45-47: `auto install` writes the scheduler files but does not activate them
- **Claim:** "This writes a launcher … and schedules it". "`--uninstall` removes both."
- **Reality:** `install_scheduler` only writes files. launchd and systemd return an `activate_command` that the CLI prints as `Activate: launchctl load …` or `systemctl --user enable --now immich-memories-auto.timer`, and never runs. For cron it writes nothing and prints a `crontab -` pipeline. So a reader who stops at the page's command has no running timer. `--uninstall` deletes the files without `launchctl unload` or `systemctl --user disable`.
- **Evidence:** `automation/system_scheduler.py:417-517` (install, the three `_install_*` functions), `:519-541` (uninstall), `cli/auto_cmd.py:420-424` (prints Activate/Deactivate).
- **Fix:** "It writes the files and prints one activation command (`launchctl load …` or `systemctl --user enable --now immich-memories-auto.timer`, or a crontab line); run it." Do the same for deactivation before `--uninstall`.
- **Confidence:** VERIFIED (code). Not executed on macOS or Linux.

### B-8 [GAP] reference/automation-contract.md:39-57: a systemd user timer on a headless Linux box needs lingering
- **Claim:** "a systemd user timer on Linux".
- **Reality:** User units run only while the user has a session, unless `loginctl enable-linger <user>` is set. On a headless server or NAS (audience a), the timer will not fire after logout. No page mentions it: `grep -rn linger docs-site/docs` returns nothing.
- **Fix:** Add one line: "On a server you do not stay logged in to, run `loginctl enable-linger $USER` once."
- **Confidence:** LIKELY (standard systemd behaviour, not executed here).

### B-9 [WRONG] reference/automation-contract.md:96: `auto suggest` does not print "the rule that rejected the others"
- **Claim:** "`auto suggest` prints the ranked list, each candidate's reason, the rule that rejected the others and anything held back."
- **Reality:** `suggest` prints only the backoff skips ("Backing off …") and the table of eligible candidates (`cli/auto_cmd.py:196-208`). Discovery returns only `ranked[:limit]` of the eligible list (`automation/candidate_discovery.py:322-340`), and the CLI never reads `last_variety_decision`. Rejections are printed by `auto run --dry-run` (`auto_cmd.py:110-111`, "Rejected …") and summarized by `auto status` ("Current rejection rules", `:338-339`).
- **Fix:** Point to `auto run --dry-run` for rejections, or make `suggest` print `runner.last_variety_decision.rejected`.
- **Confidence:** VERIFIED.

### B-10 [WRONG] reference/automation-contract.md:155-156, 161: `auto status` shows neither "the live suggestion" nor "what is next"
- **Claim:** "`auto status` shows … the timer, the last attempt, the cooldown and the live suggestion". The comment on line 161 adds "what is next".
- **Reality:** The suggestion payload is only `{"outcome", "error"}` (`automation/status.py:123-126`). The text output mentions it only when it failed (`cli/auto_cmd.py:340-342`). No next-fire time is computed for the system scheduler (`system_scheduler.py:364-404`). "The timer" here means the host launchd/systemd/cron state. When run with `docker compose exec` (line 167), it inspects the container's cron, not the in-process timer, whose state is only in `/health/ready` → `in_process_scheduler` (`web/health.py:312`).
- **Fix:** List what it actually prints (scheduler state, running code, last attempt, last auto run, cooldown, recent categories, current rejection rules, notification and pending-delivery health). For Docker, point to `/health/ready` for the timer's `next_run`.
- **Confidence:** VERIFIED for the payload. LIKELY for the Docker output (not executed in a container).

### B-11 [WRONG] reference/automation-contract.md:86: "only the latest completed month is eligible" is not a rule
- **Claim:** A hard rotation rule says only the latest completed month is eligible.
- **Reality:** No variety rule checks this (`automation/variety.py:56-78` has four rules: same category, two-of-six, monthly already this month, person in last two runs). Only `MonthlyDetector` limits itself to the last completed month. `ActivityBurstDetector` proposes `monthly_highlights` for any month from the same month last year onward, including the current, unfinished month if Immich has assets in it (`automation/event_detectors.py:146-176`, `cutoff_key = f"{today.year - 1}-{today.month:02d}"`). These are run as `generate --year Y --month M` (`generation_request.py:147-148`). The page's own table (line 70) lists the burst detector, which contradicts line 86.
- **Fix:** "The Monthly detector only offers the latest completed month; an activity burst can offer any month of the trailing year." Or add the restriction to the code.
- **Confidence:** VERIFIED for the code path. That the current month appears in `assets_by_month` was not executed.

### B-12 [CLARITY] reference/automation-contract.md:67, 72, 74: the score floors and the "On this day" row mislead
- **Claim:** Yearly "0.8, 10 % off per year of age, floor 0.3". Person spotlight "… floor 0.2". On this day: "dates with content in 5+ years".
- **Reality:** The floors apply to the multiplier: `0.8 * max(recency, 0.3)` gives a minimum of 0.24 (`calendar_detectors.py:118-120`), and `0.6 * max(0.2, ratio)` gives a minimum of 0.12 (`:187-190`). "On this day" proposes only today's date, when today's month has content in at least 5 earlier years. It never checks the day itself (`:232-266`). An operator reading `auto suggest` scores against the table will not see a 0.3 floor.
- **Fix:** "×(1 − 0.1/year), multiplier floored at 0.3 (score ≥ 0.24)". "Today, when this month has content in 5+ earlier years".
- **Confidence:** VERIFIED.

### B-13 [CLARITY] reference/automation-contract.md:204-225: the status payload's shape, and the 401 answer
- **Claim:** "GET the `status_url` for the live `phase`, then a final `state` … with `run_id`, `output_duration_seconds`, `delivery_status` and `immich_asset_id`." The table gives "token required".
- **Reality:** `run_id`, `output_duration_seconds`, `delivery_status` and `immich_asset_id` sit inside a nested `run` object (`web/trigger.py:117-140`). A script that reads `.run_id` at the top level gets nothing. `state` is also `running` while the run is live. A wrong or missing token gets **401** `{"detail":"invalid trigger token"}` (`trigger.py:143-149`), and an unknown attempt id gets 404. Neither appears on the page.
- **Fix:** Show a sample status body with `run: {…}`, and add 401 to the table and response list.
- **Confidence:** VERIFIED.

### B-14 [GAP] reference/automation-contract.md:211-220: in Docker, an exported trigger token never reaches the app
- **Claim:** `export IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN=…` followed by "Keep the token in the environment".
- **Reality:** In Docker, a variable exported in the host shell (or written to `.env`) is not passed into the container. The compose file has no mapping for it, so the route keeps answering 404 (see B-1 for the mechanism). Kubernetes is covered elsewhere (`run/kubernetes.md:200`). Docker is not.
- **Fix:** Add: "In Docker, add `IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN: "${IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN}"` under the service's `environment:` and put the value in `.env`."
- **Confidence:** VERIFIED (compose file). For a Docker reader this blocks the goal.

### B-15 [GAP] reference/automation-contract.md:31: "Configure upload separately" names no setting
- **Reality:** Automatic runs upload when `automation.upload_to_immich` (album `automation.album_name`) or `upload.enabled` is set (`automation/runner.py:615-621`, `config_models_automation.py:62-63`, `cli/_run_inputs.py:63`). `make/automate.md:25` names only `upload.enabled` and `upload.album_name`. Neither page mentions the `automation.*` pair or `auto run --upload`.
- **Fix:** Name the keys and say which album wins.
- **Confidence:** VERIFIED.

### B-16 [GAP] reference/automation-contract.md:246-247: the crontab example ignores the page's own PATH warning
- **Claim:** Line 51 says scheduled jobs do not inherit your environment. The cron line still calls bare `immich-memories generate …`.
- **Reality:** cron runs with a minimal PATH (usually `/usr/bin:/bin`). A uv or pipx install in `~/.local/bin` is not found.
- **Fix:** Use the absolute path, or `~/.immich-memories/bin/immich-memories-auto`-style launcher logic, or set `PATH=` at the top of the crontab.
- **Confidence:** LIKELY (standard cron behaviour).

### B-17 [WRONG] reference/cli-reference.md:303 (`generate --output`): "so an identical rerun replaces itself"
- **Claim (help text):** "The run writes it inside its own directory and adds a recipe hash to the name, so an identical rerun replaces itself."
- **Reality:** Every run writes into `<parent>/<stem>_<run_id>/` (`generate.py:447-459`). The run id differs on every run (`tracking/run_id.py:10-39`), so a rerun never replaces an earlier film. The `recipe_hash` docstring (`filename_builder.py:203-210`) is stale in the same way.
- **Cross-page:** `make/cli/generate.md:81` ("reruns do not overwrite earlier films") and `reference/generation-contract.md:211-213` ("a rerun never overwrites an earlier result") are correct and contradict the reference.
- **Fix:** Edit the help in `cli/generate_options.py:257`, then run `make docs-cli`.
- **Confidence:** VERIFIED.

### B-18 [GAP] reference/cli-reference.md: the global options are missing
- **Reality:** `immich-memories --help` lists `--version`, `-c/--config PATH`, `--preset [fast]`, `-v/--verbose` and `--log-level [debug|info|warning|error]`. The generator walks only `parent.commands` (`scripts/generate_cli_docs.py:133-143`), so none of these appear. `grep -- '--config\|--preset\|--log-level'` finds no match, and the only `--verbose` is preflight's own. `automation-contract.md:55` tells readers "`--config` goes before `auto`", and the reference cannot confirm it. A Kubernetes operator looking for the config flag also misses `--preset fast`.
- **Fix:** Emit a "Global options" table for the root group in `generate_reference`.
- **Confidence:** VERIFIED (command output and generator source).

### B-19 [WRONG] reference/cli-reference.md:241: the `discover-days --until` default is a frozen year, and the drift gate will break on 1 January
- **Claim:** `--until … 2026`.
- **Reality:** The default is `date.today().year`, evaluated at import (`cli/special_days_cmd.py:39`). The generated page records whatever year `make docs-cli` ran in. From 2027-01-01, `make docs-cli-check` fails on every branch with no code change, and the published page shows a stale default.
- **Fix:** Set `show_default="current year"` (or `default=None` and resolve inside), and teach the generator to print `show_default` strings.
- **Confidence:** VERIFIED (code). The 2027 failure follows from the generator, which renders `param.default` (`generate_cli_docs.py:61-70`).

### B-20 [GAP] reference/cli-reference.md (all commands): usage lines drop arguments; required and repeatable markers are missing
- **Reality:** Every usage line is `immich-memories <cmd> [OPTIONS]` (`generate_cli_docs.py:96`). Commands that take arguments still show only `[OPTIONS]`: `runs show RUN_ID`, `pictures * ASSET_ID`, `people bind PERSON`, `people group add LABEL EXPRESSION`, `config show [PREFIXES]…`, and `music add VIDEO OUTPUT`. The argument list does not say whether an argument is required (`runs show`) or optional (`runs story`, `runs render`, `report`). Required options are unmarked: `days-import --from`, `people import --from`, `people bind --account/--id` (`special_days_cmd.py:142`, `people_cmd.py:196, 234, 240`). Repeatable options are unmarked unless their help says so (for example `discover-days --also-skip`, `multiple=True` at `special_days_cmd.py:42`).
- **Fix:** Use `cmd.collect_usage_pieces(ctx)` for the usage line, and add "required" and "repeatable" to the table.
- **Confidence:** VERIFIED.

### B-21 [GAP] reference/cli-reference.md:793-813 (`runs render`): undocumented and untyped options
- **Reality:** `--transition`, `--no-music`, `--music-volume`, `--privacy-mode` and `--upload-to-immich` have empty Description cells (no `help=` at `cli/runs_render.py:34-36, 60-61, 72-73`). `--resolution`, `--orientation` and `--scale-mode` are free text, where `generate` takes choices (`:43-45`), so a typo surfaces only late.
- **Fix:** Add help strings, and reuse `generate`'s `click.Choice` values.
- **Confidence:** VERIFIED.

### B-22 [GAP] make/cli/generate.md:85: "Leave upload off to keep the file locally" ignores `upload.enabled`
- **Reality:** The run uploads when `--upload-to-immich` is given or `config.upload.enabled` is true (`cli/_run_inputs.py:63`). After a confirmed delivery it deletes the run's local folder (`generate_delivery.py:34-48`, `operations/local_output_cleanup.py:45-63`). No setting keeps the local copy. A reader with `upload.enabled: true` in config who omits the flag loses the local file.
- **Fix:** "Upload happens with `--upload-to-immich` or `upload.enabled: true`; with either, the local copy is removed once Immich confirms it."
- **Confidence:** VERIFIED.

### B-23 [CLARITY] make/cli/generate.md:8-14: no `models fetch` prerequisite on the recipe page
- **Reality:** `generate` prepares pictures (line 8). On a fresh install, preparation fails until `models fetch` has run ("public heads need the pinned DINOv2 ONNX export", `reference/troubleshooting.md:27`). `make/cli/prepare.md:17` tells readers to run it, but `generate.md` does not, though it is the more likely entry point. It is covered in `get-started/quick-start.md:36`.
- **Fix:** Add "Run `immich-memories models fetch` once first (Docker: prefix as below)."
- **Confidence:** VERIFIED that the docs omit it. The failure text was not reproduced.

### B-24 [CLARITY] make/cli/generate.md:83 and cli-reference.md:300, 803: `--quality` offers the retired names
- **Reality:** The CLI choices are `high|medium|low`. The config values are `high|balanced|fast` (`config_models_render.py:103`). `medium` maps to `balanced`, and `low` maps to `fast`, which "keeps the balanced picture and buys its speed from the encoder preset" (`:119-128`; `processing/hdr_utilities.py:389-390`). A user who picks `--quality low` for a smaller file gets the same picture, encoded faster. "Selects the encoder's calibrated quality" does not tell them that.
- **Fix:** Document the mapping, or accept `balanced|fast` on the CLI.
- **Confidence:** VERIFIED.

### B-25 [GAP] make/cli/report.md:11, 30: `report` needs the full run ID
- **Reality:** `report_for_run` uses an exact `database.get_run(run_id)` (`tracking/report_service.py:20-26`), and `--wrong`/`--missing` use the exact id too (`cli/report.py:18, 72-74`). `runs show`, `delete`, `story`, `why` and `render` accept a unique prefix among the 100 most recent runs (`runs.py:323-334`, `_runs_reading.py:55-68`, as `runs.md:17` says). A reader who pastes a prefix into `report` gets "No matching run".
- **Fix:** Say "the full run ID (as `runs list` prints it)", or add prefix resolution.
- **Confidence:** VERIFIED.

### B-26 [CLARITY] make/cli/report.md:23: names no flag for including captions
- **Reality:** "Captions stay out unless you explicitly include flagged captions" does not say how. The flag is `--include-flagged-captions` (`cli/report.py:39-43`).
- **Fix:** Name the flag.
- **Confidence:** VERIFIED.

### B-27 [GAP] make/cli/discover-days.md:41, 47 and make/cli/people.md:23, 29: in Docker the export/import files live inside the container
- **Reality:** With the `docker compose exec immich-memories` prefix (generate.md:14 and prepare.md:17 tell readers to add it), `days-export --to days.json` and `people export --to people.yaml` write relative to the container's WORKDIR `/app` (`docker/Dockerfile:121`). Only `/app/output` and the config volume are owned by `immich` (`Dockerfile:182-183`), so the write most likely fails with a permission error. Even if it succeeds, the file is not on the host and cannot be edited there. `--from days.json` likewise reads inside the container. Audience (a) cannot complete "Edit the catalogue" or "Export and edit".
- **Fix:** Docker form: `docker compose exec -T immich-memories immich-memories days-export > days.json` (stdout, which the command supports when `--to` is omitted). For import, copy to `./output/` and use `--from /app/output/days.json`. Do the same for people.
- **Confidence:** LIKELY (ownership read from the Dockerfile; not executed in a container).

### B-28 [CLARITY] make/cli/prepare.md:35-41: the `--overviews` preconditions are misstated, and the skip is silent
- **Claim:** "With Full selection configured and its caption and reader services ready".
- **Reality:** The only check is "a configured model reader" (`cli/prepare_cmd.py:217-218`, UsageError otherwise). Overviews are then banked only `if overviews and result.complete` (`:233`). When preparation is incomplete they are silently skipped: the command exits 1 for the missing facts but says nothing about overviews.
- **Fix:** State the real requirement, and add: "skipped when preparation is incomplete; rerun after exit 0."
- **Confidence:** VERIFIED.

### B-29 [WRONG] make/cli/runs.md:17: `runs show` shows no delivery details
- **Claim:** "`show` gives status, scope, output/delivery, title source, timing and system details."
- **Reality:** `_print_run_details_table` prints Status, Created, Completed, Person, Date Range, Clips, Title From, Timeline, Output, Output Duration/Size and Errors (`cli/runs.py:63-112`). `runs_show` then adds cut checks, sharing, phases, model spend, spans and system info (`:341-351`). Nothing reads `delivery_status`, `immich_asset_id` or `delivery_album`, although `RunMetadata` has them (`tracking/models.py:165-169`).
- **Fix:** Drop "/delivery", or add delivery rows to `runs show`.
- **Confidence:** VERIFIED.

### B-30 [GAP] make/cli/runs.md:57-60: `runs delete` asks for confirmation
- **Reality:** `@click.confirmation_option(prompt="Are you sure…")` (`cli/runs.py:394`) adds `--yes`. A script, or `docker compose exec -T`, aborts at the prompt. The page does not mention it. The reference row exists (cli-reference.md:747).
- **Fix:** Add "(asks first; `--yes` for scripts)".
- **Confidence:** VERIFIED.

### B-31 [WRONG] make/cli/pictures.md:9 and cli-reference.md:584-585: where an ASSET_ID comes from
- **Claim:** pictures.md says "Use the asset ID shown by Immich or `runs why`". The group help in the reference says "The asset id is the one `runs why`, `runs story` and Immich show."
- **Reality:** `runs story` prints no asset IDs. Its lines are timecode, day, kind, seconds, story title and reason (`operations/storyboard.py:268-283`). `runs why` takes the ID as its required input (`_runs_reading.py:177`) and only echoes it back. So neither CLI command helps a reader find an ID. The practical sources are the Immich photo URL (`/photos/<id>`) or `generate --trace-selection`.
- **Fix:** "the ID in the Immich photo URL (…/photos/ASSET_ID)". Drop `runs story` from the help in `cli/pictures_cmd.py:24-25`.
- **Confidence:** VERIFIED.

### B-32 [POLISH] make/cli/discover-days.md: no Docker prefix note
- **Reality:** generate.md:14 and prepare.md:17 say to prefix with `docker compose exec immich-memories`. discover-days.md, which a NAS user reaches from prepare.md:46, does not. Combined with B-27 this matters.
- **Confidence:** VERIFIED.

### B-33 [POLISH] several pages: wording and rendering
- `make/cli/people.md:42`: "[Second-account setup](../../run/multi-account.mdx)." is a sentence fragment.
- `reference/cli-reference.md:498-499`: "canonical person ids : the ids `people show` lists : not names". The generator replaces every "—" with ":" (`generate_cli_docs.py:33`), which leaves " : ". Rewrite the docstring at `people_cmd.py:279-281` without dashes, or replace "—" with ", ".
- `reference/cli-reference.md:827-828`: the `runs show` "Example:" followed by an indented command renders as running paragraph text, because the docstring lacks `\b`.
- Vocabulary drift: `pictures clear-hold --level anyone|family|just-us` against `generate --sharing just-us|family|shareable` (`pictures_cmd.py:44`, `generate` table). The same idea goes by "anyone" in one and "shareable" in the other.
- `make/cli/generate.md:68`: the trip index is 1-based (`_trip_display.py:58-71`) and the page does not say so. The listing shows the numbers, so this is minor.
- **Confidence:** VERIFIED.

## 3. Unverifiable (not reported as wrong)

- `runs.md:41` ("For a film across accounts, the saved cut also keeps the exact file copy and the account that can read it…"): needs a two-account render. The render-input format was not traced.
- `prepare.md:23` ("Changing home coordinates or people roles does not invalidate picture facts"): needs the fact-key composition traced across every producer. Not done.
- `pictures.md:37` ("clearing a hold on a screenshot does not make it ordinary footage"): needs the media-kind classifier traced against owner decisions.
- `pictures.md:49` ("A Live Photo decision covers its still and motion clip"): true when the still is in `annotation_assets` (`store/owner_decisions.py:52-62`). For a never-prepared still the clip id is not found, so the behaviour depends on preparation state.
- `generate.md:83` ("NAS preparation can still limit source intermediates to 1080p"): the tier cap was not traced.
- `automation-contract.md:57` ("launchd does not wake it"): macOS behaviour, not testable here.
- `automation-contract.md:192` ("the database stores them encrypted"): true for values saved through Settings with `IMMICH_MEMORIES_SECRET_KEY`. URLs in config.yaml are plaintext in the file. The storage path was not traced.
- `automation-contract.md:17` ("makes the same cuts you would get by hand there"): a product claim with no single code check.
- `discover-days.md:15` ("Full selection can check proposed occasions using its text reader"): the code switches on `reader="model"|"rules"` (`special_day_scan.py:237-256`), not on the tier. The tier-to-reader mapping was not traced, so this is not reported.

## Verified correct (sample, so reviewers can see what was checked)

days-due window ±3 days (`special_day_scan.py:678-707`); scorer constants 1.2 / 365-day linear floor 0.5 / 30% log-1000 richness / cooldown 0.3 (≤7 days) and 0.7 (≤30 days) / caps 3, 1, 1, 2 (`candidate_scorer.py`); every detector base score in the table; backoff 24 h / 3 d / 7 d after 2 failures (`failure_backoff.py`); cooldown from the run's start, minus 30 min (`status.py:21,150-165`); `max_delivery_attempts` 5 and `min_free_space_gb` 5.0; `automation-output/<id>.private.log` (`operations/auto_output.py:16`); `--candidate` stale key gives FAILED (`runner.py:433-435`); exit 0 for skipped, dry_run and completed; the trigger auth matrix, 202/409, `x-api-key` plus Bearer, and the `server` section without `${VAR}` expansion; trips primary-only; `/health/ready` → `in_process_scheduler`; launcher path `~/.immich-memories/bin/immich-memories-auto`; the copied env list (PATH, ACESTEP_*, PYTORCH_MPS_HIGH_WATERMARK_RATIO); `--config` resolved to an absolute path; `--no-render` records a completed run that `runs story` and `runs render` pick up; `--group` with `multi_person`; `people show` prints store IDs; run-folder output layout; the UI labels Clear hold, Never use, Undo, Copy report, Download report, Special day picker "any day", Settings > People groups and the Memory nav item; every link target and #anchor on the nine pages resolves.
