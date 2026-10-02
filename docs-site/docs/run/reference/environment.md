---
title: Environment variable exceptions
---

# Environment variable exceptions

For credential precedence, logging, local music and scheduling. Start with the
[common variables](../environment-variables.md).

## The ones that do not follow the pattern

**The captioner has its own credential.** `OPENAI_API_KEY` does not reach it: give it
`IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_API_KEY`, or leave it blank for a server that
needs none.

### Shorthands

| Variable | Overrides |
|----------|-----------|
| `IMMICH_URL` | `immich.url` |
| `IMMICH_API_KEY` | `immich.api_key` |
| `OPENAI_API_KEY` | `llm.api_key`, only when the config file states no key |
| `ANTHROPIC_API_KEY` | `llm.api_key` under the same rule, read instead of `OPENAI_API_KEY` when `llm.provider` is `anthropic` or `zai` |
| `MUSICGEN_ENABLED`, `MUSICGEN_BASE_URL`, `MUSICGEN_API_KEY` | `musicgen.enabled`, `.base_url`, `.api_key` |
| `ACE_STEP_ENABLED`, `ACE_STEP_API_URL`, `ACE_STEP_API_KEY` | `ace_step.enabled`, `.api_url`, `.api_key` |
| `ACE_STEP_MODE` | `ace_step.mode` (`api` or `lib`; other values ignored) |
| `IMMICH_MEMORIES_AUTH_USERNAME` + `IMMICH_MEMORIES_AUTH_PASSWORD` | `auth.username` and `auth.password`, and sets `auth.enabled=true`, `auth.provider=basic`. Both must be set |

An empty shorthand counts as unset.

:::caution An LLM key written in the file beats its shorthand
`OPENAI_API_KEY` is the name every OpenAI-SDK client reads, a local mlx or vLLM server included, so
on a machine that exports it for that server it says nothing about the endpoint the key will be
sent to. So a key in `llm.api_key` wins, and the variable fills the field only where the
file leaves it empty or holds a `${VAR}` nobody set. `ANTHROPIC_API_KEY` works the same way. To
replace a key that is in the file, use `IMMICH_MEMORIES_LLM__API_KEY`.
:::

`--config PATH` makes PATH the single config file, and the same variables apply to it.

### Not config keys

| Variable | Effect |
|----------|--------|
| `IMMICH_MEMORIES_STORAGE_SECRET` | Secret for the web UI session store. Priority: this variable, then the existing `~/.immich-memories/.storage_secret` file. If neither exists, the web UI generates and saves that file once; later starts reuse it. 32+ random characters (`openssl rand -hex 32`); a shorter one, or one with a placeholder word like `change-me`, stops the app at startup |
| `IMMICH_MEMORIES_SKIP_STORED_SETTINGS` | `1` starts without the settings saved in the database (env, `config.yaml` and defaults only). Without it, a store that is configured but unreadable stops the app ([where a setting comes from](../config-file.md#where-a-setting-comes-from)) |
| `IMMICH_MEMORIES_SECRET_KEY` | Encrypts the secrets saved to the database from the UI or CLI (API keys, passwords). Any string of 32+ characters, e.g. `openssl rand -base64 32`. Unset: secrets cannot be saved there, only in env or `config.yaml`. Read from the environment only, never from the store ([secrets in the database](../config-file.md#secrets-in-the-database)) |
| `IMMICH_MEMORIES_LOG_FORMAT` | `text` (default) or `json` |
| `IMMICH_MEMORIES_LOG_LEVEL` | `INFO` (default), `DEBUG`, `WARNING` or `ERROR`. The CLI's `-v` and `--log-level` win for one run |
| `IMMICH_MEMORIES_LOG_FILE` | Also write logs to this file |
| `IMMICH_FORCE_CPU` | `1`, `true` or `yes` puts the title renderer on the CPU even with a GPU |
| `IMMICH_MEMORIES_FONTS_DIR` | Where `titles fonts --install` puts the Noto fonts for other alphabets and where titles look for them (default `~/.immich-memories/fonts/noto`; the image sets its own) |
| `IMMICH_MEMORIES_OWNER` | Who "you" is in the people registry, for `people scan` (same as `--owner`) |
| `ACESTEP_CHECKPOINTS_DIR` | ACE-Step `lib` mode: where checkpoints go (default `~/.cache/ace-step/checkpoints`) |
| `ACESTEP_MLX_VAE_CHUNK` | ACE-Step `lib` mode on Apple Silicon: VAE decode chunk in latent frames (minimum 192). Lower it if MLX runs out of memory |
| `IMMICH_MEMORIES_ACESTEP_MLX_DIT_FP32` | ACE-Step `lib` mode on Apple Silicon: `1` keeps the decoder in fp32 (about twice the memory) |
| `FORWARDED_ALLOW_IPS` | uvicorn: proxies whose `X-Forwarded-*` headers are trusted. Wins over `auth.trusted_proxies`. With auth on, `*` stops the app at startup (list your proxy's address); with `auth.provider: header` remove the variable entirely, even if empty, and use `auth.trusted_proxies`. See [Authentication](../authentication.mdx) |

:::caution Scheduled jobs do not inherit your shell
A launchd or cron job starts from a login-less environment, so nothing you `export` interactively
reaches it. `auto install` copies `PATH`, `ACESTEP_CHECKPOINTS_DIR`, `ACESTEP_MLX_VAE_CHUNK`,
`IMMICH_MEMORIES_ACESTEP_MLX_DIT_FP32` and `PYTORCH_MPS_HIGH_WATERMARK_RATIO` into the plist or
unit, and nothing else, since `IMMICH_MEMORIES_*` also holds credentials. Change one of them and
run [`auto install`](../../make/automate.md) again.
:::
