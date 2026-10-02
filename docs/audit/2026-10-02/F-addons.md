# F-addons: audit of the add-on, hardware and service reference pages

Audited at HEAD `b371427b` (shallow clone, 50 commits). Repo left read-only. Every YAML example on the reader and LLM pages was resolved with real code. The script is `scratchpad/llm.py`. It runs `LLMConfig(**example)`, `resolved_llm_config`, `is_local_endpoint` and `batch_route_for`.

Resolved results (from `uv run --no-sync python scratchpad/llm.py`):

| Example | enabled | runs_locally | wire provider | is_local_endpoint | batch route |
|---|---|---|---|---|---|
| reader.md:21-27 local | True | True | openai-compatible | True | None |
| reader.md:42-49 existing server (`reader.example.lan`) | True | False | openai-compatible | **False** | openai |
| reader.md:59-66 hosted (known) | True | True | (no URL) | True | None |
| llm-providers.md:166-174 local | True | True | openai-compatible | True | None |
| llm-providers.md:249-256 anthropic (known) | True (implicit) | True | (no URL) | True | None |
| llm-providers.md:265-274 zai | True | False | anthropic, think/no-think `{"thinking":{"type":"low"}}` | False | anthropic |
| zai with `/api/paas/v4` | True | False | openai-compatible | False | openai |
| caption-service.md:26-35 LLM captions | True (implicit) | False | openai-compatible | True | openai |
| anthropic with base_url + thinking high | True | False | anthropic, `thinking adaptive` + `output_config.effort high`, bulk `thinking disabled`, drop temperature | False | anthropic |

## 1. Coverage

| Page | Claims checked (approx.) | Findings | Verdict |
|---|---|---|---|
| better/overview.md | 12 | 0 new | Accurate. Table rows match code and the routes on the other pages |
| better/reader.md | 25 | 5 | The external-server example lands on the "hosted" code path. The tier rule omits Metal. The Linux install link goes round in a circle |
| better/captions.md | 20 | 1 (+1 shared) | Mostly accurate. Ports, env names and alias all verified |
| better/inference.md | 22 | 2 | URLs and auth verified. The tier rule omits Metal and local CUDA. The `/health` signal the app actually uses is not described |
| better/gpu-render.md | 30 | 5 | Timeouts, ports, env prefix and transport rule verified. The MOV claim is wrong. The URL example does not match the shown deployment. The K8s gaps are not covered |
| better/music.md | 18 | 2 | The memory table is consistent. The check target uses a different, heavier profile. The API server is never defined |
| better/measured.md | 40 (CSV recomputed) | 3 | The LLM table and motion table match the CSV exactly. One cited revision does not exist publicly. "Gemma" is not the default reader |
| run/hardware.md | 30 | 2 | Presets, VAAPI levels, drivers, `vainfo` and the NAS cap all verified. Recommending `all-mac` silently changes the tier. No driver minimum |
| reference/llm-providers.md | 60 | 7 | Dialect routing verified. One wrong number (1,024). The Claude-preset guidance breaks on Haiku 4.5 and on current Claude models. #1385 is described as open but is closed. Units are mixed |
| reference/caption-service.md | 55 | 3 | The contract, pins, digests, motion keys and K8s overlays all verified. Two preflight claims are wrong |
| reference/inference-service.md | 55 | 3 | Endpoints, queue fields, settings and images verified. The stem upload limit is wrong. The DETECTOR_CACHE_DIR default is half right |
| reference/local-audio.md | 35 | 1 | Memory and disk tables recomputed from `memory_budget.py`. The Makefile pins match |
| reference/performance-evidence.md | 10 | 0 | Accurate. Commands exist and links resolve |

Severity counts: BLOCKER 0, WRONG 8, GAP 8, CLARITY 10, POLISH 2. Total 28 new findings.

## 2. Findings

### F-1 [WRONG] reference/llm-providers.md:313: "asks for 1,024 tokens on top of the caller's cap"
- Claim: on z.ai's `/api/anthropic` route the reader asks for 1,024 extra tokens.
- Reality: the extra room on the Messages dialect is the shared reasoning ledger, `REASONING_HEADROOM_TOKENS = 16384` (`src/immich_memories/analysis/llm_wire.py:161`). `apply_anthropic_reasoning` sets `max_tokens = max_tokens + headroom` (`llm_wire.py:307-313`). For GLM-5 the no-thinking level is `low`, so `asked_off` is False and the endpoint is declared from the first call. `grep -rn "1024\|1_024" analysis/llm*.py` finds nothing.
- Cross-page: `reference/config-reference.md:460-461` correctly says "add 16,384 tokens of room on top of the caller's cap".
- Fix: change "1,024" to "16,384", and say it is a ceiling that is learned or declared.
- Confidence: VERIFIED.

### F-2 [GAP] better/reader.md:47 (and llm-providers.md:319-321): a LAN server with a dotted hostname is treated as hosted
- Claim: the example `base_url: http://reader.example.lan:8000/v1` for "oMLX, vLLM, Ollama". llm-providers.md says "Local episode readings use prompt-only JSON because oMLX can stall".
- Reality: "local" is decided from the URL alone. A host counts as local only if it is localhost or a Docker host alias, has no dot, or is a private, loopback or link-local IP literal (`analysis/llm_providers.py:218-243`). `reader.example.lan`, `omlx.local` and `gpu-box.home.arpa` all resolve as hosted. Resolved example: `is_local_endpoint False`, `batch openai`. Consequences:
  1. `reader_concurrency` defaults to 4 instead of 1 (`llm_providers.py:267-276`). The code's own comment (`llm_providers.py:205-211`) says four sockets to a single local server buy "three requests queued inside a 300-second timeout, which fails quietly".
  2. Episode readings keep the JSON schema (`llm_providers.py:264`), which is the oMLX stall the page warns about.
  3. `repetition_penalty: 1.0` is not sent (`llm_wire.py:396`), so the server's 1.1 default applies.
- Neither reader.md nor llm-providers.md mentions `reader_concurrency`, the URL rule or `structured_output` for this case. `config-reference.md:466-471` mentions the rule only as "4 for a public host".
- Fix: use an IP or bare-name example (`http://192.168.1.20:8000/v1`), or state the rule. For a named LAN host, tell readers to set `reader_concurrency: 1` and, on oMLX, `structured_output: false`.
- Confidence: VERIFIED in code. The stall itself is the project's own claim and was not executed.

### F-3 [WRONG] better/reader.md:77-78 and better/inference.md:65: the tier rule names only GPU inference
- Claim: "With `tier: auto`, GPU inference plus an enabled reader selects Full. Without GPU inference, selection remains NAS". inference.md says "GPU inference enables GPU".
- Reality: `inference_acceleration` falls back to `local_inference_acceleration()` (`src/immich_memories/config_compute.py:15-16, 34-54`). That returns True for three things: a local onnxruntime that can allocate on CUDA, MLX with Metal, or any Mac where pyobjc `Metal` returns a device. `config_tiers.py:69-72` then picks gpu or full. `run/requirements.md:58` and `reference/caption-service.md:118-119` both state the Metal rule correctly, so the pages contradict each other.
- Knock-on: `run/hardware.md:79` tells Mac users to `uv tool install "immich-memories[all-mac]"` for VideoToolbox. `all-mac` pulls in `mac`, which ships `pyobjc-framework-Metal` (`pyproject.toml` `mac`/`all-mac`). The auto tier then becomes GPU, which needs a SmolVLM captioner and Laya. Per `caption-service.md:290`, "On GPU and Full with SmolVLM, prepare stops". hardware.md says nothing about this.
- Fix: in reader.md and inference.md, say "GPU inference, a local CUDA ONNX runtime, or a Mac's Metal GPU". In hardware.md's Apple section, add one line that this install moves `auto` to GPU, so set up captions and Laya or set `tier: nas`.
- Confidence: VERIFIED in code. Not executed on a Mac.

### F-4 [WRONG] reference/llm-providers.md:253 and 262-263: "claude-haiku-4-5 for the cheap seat" with `thinking: "high"`, and the older-model escape hatch
- Claim: the Anthropic example suggests `claude-haiku-4-5` as a drop-in alternative under `thinking: "high"`. It says an older model needs `thinking_params: {thinking: {type: "enabled", budget_tokens: 2048}}`.
- Reality: with `thinking: high` the preset sends `thinking: {type: adaptive}` plus `output_config: {effort: "high"}` (`analysis/llm_providers.py:97-111`). A user-supplied `thinking_params` is merged with the preset, not used instead of it (`llm_providers.py:165-170`). Resolving the documented escape hatch gives `{'thinking': {'type': 'enabled', 'budget_tokens': 2048}, 'output_config': {'effort': 'high'}}`, so `output_config.effort` is still sent. Per the Claude API reference (claude-api skill, Thinking & Effort table), Haiku 4.5 does not take adaptive thinking (it requires `budget_tokens`), and `effort` "errors on Sonnet 4.5 / Haiku 4.5". So the two reasoning calls (titles and the `discover-days` special-day question) would get HTTP 400 on the suggested cheap seat, even with the escape hatch.
- Fix: drop the Haiku suggestion or pair it with `thinking: "disabled"` or `"auto"`. For the escape hatch, also say to add `drop_params: ["output_config"]`, or change code so a user `thinking_params` replaces the preset's.
- Confidence: LIKELY. The merge is VERIFIED by running the resolver. The API rejection comes from the bundled API reference and was not executed against the API.

### F-5 [GAP] reference/llm-providers.md:258-263: the preset always sends `thinking: {"type": "disabled"}` on bulk calls; current Claude models refuse it
- Claim: "Bulk calls send `thinking: {"type": "disabled"}`". This is presented as safe for Claude.
- Reality: the preset `no_thinking_params` is `{"thinking": {"type": "disabled"}}` (`llm_providers.py:48-55`). Per the Claude API reference, `{type: "disabled"}` returns 400 on Claude Opus 5.5 (at every effort), Claude Sonnet 5.5 (current Sonnet) and Fable 5/5.1. The `/v1/messages` path has no capability-adaptation retry: `_query_anthropic` calls `ensure_success` directly (`analysis/llm_query.py:566-570`). The adaptation table (`llm_adaptations.py:19-48`) only learns z.ai code 1210 and OpenAI-dialect refusals. The page's own example (`claude-sonnet-5`) accepts `disabled`, but a reader choosing the current Sonnet or Opus would get a 400 on every bulk call.
- Fix: say which models accept `disabled`. For Opus 5.5, Sonnet 5.5 and Fable, tell readers to use `thinking: "auto"`, which empties both param sets (`llm_providers.py:197-201`), or add an adaptation.
- Confidence: LIKELY. Code VERIFIED; API behaviour from the bundled reference, not executed.

### F-6 [WRONG] reference/caption-service.md:166-167: "Validate `/models` and the synthetic controls with preflight"
- Reality: preflight's `check_caption_endpoint` only does `GET {base_url}/models` and checks the alias (`src/immich_memories/preflight.py:577-618`). The three synthetic control tiles are sent by `check_provider` during preparation (`analysis/editorial_preparation_captions.py:300-345`). A wrong projector passes preflight as "Serving smolvlm2-500m-base-public" and only fails at the first `prepare`. `better/captions.md:143` puts "The app checks the served model and synthetic control pictures" right under "Look for Captions OK", which suggests the same thing.
- Fix: "preflight checks `/models`; the control tiles run at the start of preparation, before any library picture".
- Confidence: VERIFIED.

### F-7 [WRONG] reference/caption-service.md:285-286: "An explicit LLM-caption opt-in checks the configured LLM's vision responses instead"
- Reality: with `caption_provider: llm`, preflight returns a WARNING row "Explicit LLM captioning: <model>" carrying the cost warning and "Image schema controls run before missing captions are acquired". It sends no request (`preflight.py:566-575`).
- Fix: "preflight warns about the cost; the vision schema controls run at preparation".
- Confidence: VERIFIED.

### F-8 [WRONG] reference/inference-service.md:76-77: stem endpoint "accepts one multipart `file`, up to 64 MiB"
- Reality: `MAX_AUDIO_BYTES = 256 * 1024 * 1024`, and larger uploads get "413 audio is larger than 256 MiB" (`services/inference/immich_memories_inference/audio.py:17-30`). The code comment says "Long stereo PCM soundtracks can exceed 64 MiB", so 64 MiB is the old limit.
- Fix: 256 MiB.
- Confidence: VERIFIED.

### F-9 [WRONG] better/gpu-render.md:183: "MOV and ProRes render locally"
- Claim: it reads as an automatic local fallback.
- Reality: with a worker configured, `build_render_request` raises `ValueError("Render workers support H.264 or H.265 MP4; use local rendering for MOV")` (`src/immich_memories/processing/remote_render_plan.py:34-35`). `RemoteRenderClient.render` wraps it as `GenerationError` (`processing/remote_render.py:143-146`). `render_base` re-raises unless `fallback_to_local` is set (`generate_render.py:224-226`). The page's own recommended config uses `fallback_to_local: false` (gpu-render.md:130), so a MOV or ProRes film fails the run.
- Fix: "MOV and ProRes need local rendering: unset `render.worker_base_url` for those films, or enable `fallback_to_local`". The worker README:69 already says "require local rendering".
- Confidence: VERIFIED by code reading. Not executed.

### F-10 [CLARITY] better/gpu-render.md:126-134: the app example does not match the deployment just shown
- The `.env` binds plain HTTP on `RENDER_BIND_ADDRESS=192.168.1.50:8093` (`services/render-worker/compose.yaml:7`). The very next block uses `worker_base_url: https://render.example.com`. That needs a TLS reverse proxy the page never sets up.
- A NAS reader following the page literally needs `http://192.168.1.50:8093` plus `allow_insecure_http: true` (`config_models_render.py:209-220`). The page only says this in prose two lines later.
- Fix: show the LAN form next to the HTTPS form.

### F-11 [CLARITY] better/gpu-render.md:172-175: the worker's `/health` needs the bearer token
- All worker routes depend on `authorize`. An unauthenticated call gets 401 "Worker authentication required" (`services/render-worker/immich_memories_render_worker/app.py:35-64`).
- A reader who runs `curl http://worker:8093/health` to look at `accelerated` gets 401.
- Fix: show `curl -H "Authorization: Bearer $RENDER_WORKER_TOKEN" .../health`.

### F-12 [GAP] better/music.md:25-41: `make check-local-audio` tests a heavier profile than the one the page recommends
- Reality: `scripts/validate_local_audio.py:49-54` validates `model_variant="turbo", lm_model_size="0.6B", use_lm=True`. The user's config is not used. Per the page's own table (`local-audio.md:333`), that profile needs about 9 GB free and about 7 GB on disk, and downloads the 1.2 GB planner. The page recommends `use_lm: false` at "about 7 GB free / 6 GB on disk".
- A 16 GB Mac that fits the recommended profile can fail the check, or download a planner it will never use.
- Fix: state the profile and memory the check uses, or make the check honour the config. `capabilities --verify-local` checks the configured profile (`local_capabilities.py:206-230`).
- Confidence: VERIFIED.

### F-13 [GAP] better/reader.md:19: the Linux llama.cpp install link goes in a circle
- reader.md:19 says "Linux needs a llama.cpp build for its CPU or GPU; follow the installation reference" and links to `reference/llm-providers.md`. That page has no install steps, and line 164 says "For the install recipe, use Add a reader", which links back.
- Related: the owned server is started with fixed flags and no GPU-layer option. It also strips every `LLAMA_*` variable from its environment (`src/immich_memories/local_inference.py:183-211`), so `LLAMA_ARG_N_GPU_LAYERS` cannot be used to tune it. Whether layers are offloaded depends on the build's default.
- Fix: one paragraph naming the supported routes for Linux, CUDA and CPU, and a note that offload follows the llama.cpp build default.
- Confidence: circular link VERIFIED. Offload behaviour LIKELY (llama.cpp default not checked).

### F-14 [CLARITY] reference/llm-providers.md:229-230: "validation of the complete NVIDIA image is tracked in #1385"
- #1385 has been closed as completed since 2026-09-26, by PR #1394 (GitHub `issue_read`).
- "Tracked" suggests the work is still open. Either cite the result or remove the sentence.

### F-15 [POLISH] reference/llm-providers.md:203-204: mixed units in the Laya download sizes
- `gh api repos/.../releases/tags/models-v2` gives `laya-audience-a79ad9fa.tar 850780160` and `laya-audience-onnx-90420ef3.tar.gz 877012710`.
- The page's "811 MB" is MiB (decimal would be 851 MB). Its "877 MB" is decimal (836 MiB).
- Pick one unit.

### F-16 [WRONG] better/measured.md:106 and 116: source revision `f74936b657d7` cannot be found
- GitHub `get_commit` returns "No commit found for SHA: f74936b657d7". It is not in the local clone either.
- The other revisions resolve: `c4c7356304c5` (#1698), `dec8f20e609c` (local), `cb06e4ba0e0d`, `f82de21b5bf5`, `b96d7d6a`.
- Two rows (the M2 Full month and the 30-minute NAS stress film) cite it. A reader cannot check out the revision the page gives as provenance.
- Fix: correct the hash, or say it is a private-mirror revision.
- Confidence: VERIFIED absent from the public repo.

### F-17 [CLARITY] better/measured.md:136 and 152-157: "Gemma" is not the app's default reader
- The row is `gemma-4-e4b-it-6bit`, an MLX 6-bit build served externally (CSV `docs/research/2026-10-01-llm-contract-fixes.csv`, column `model`). The app-owned default is `gemma-4-E4B-it-Q4_0` GGUF on llama.cpp (`config_models_llm.py:22`, `pinned_models.py:74-87`).
- A reader coming from reader.md will assume the default they installed was the one measured.
- Fix: say "Gemma 4 E4B, 6-bit MLX on oMLX; not the bundled Q4_0 GGUF".

### F-18 [CLARITY] reference/inference-service.md:295: DETECTOR_CACHE_DIR default "`/cache/huggingface` in the published image"
- True for the CPU image only (`docker/Dockerfile.inference:119`). The CUDA image sets `/opt/immich-models/huggingface` (line 140).
- Also, `PROVIDER` defaults to `auto` in code but the CUDA image sets `cuda` (line 141), and the table does not say so.

### F-19 [CLARITY] better/inference.md:61-69 and inference-service.md:124-130: the `/health` signal the app uses is not the one described
- Tier selection reads the top-level `provider` field (`config_compute.py:18-24`). Before any producer has loaded, that field is a promise of what a session *would* use (`services/inference/.../app.py:243-247`). The docs only describe the per-producer lists, which start empty.
- Also undocumented: if the service is unreachable and `fallback_to_local: true` (the inference.md example), the tier quietly falls back to local detection, usually NAS (`config_compute.py:27-31`). With `false`, config loading fails with "Cannot verify the required inference service's compute".
- inference.md:69-70 only covers the fallback for facts and stems.

### F-20 [GAP] better/gpu-render.md:119-122 and 136-140: Kubernetes path for the standalone worker
- The page does not name the Secret (`immich-memories-render-worker`, `services/render-worker/kubernetes.yaml:50-59`). It does not say the manifest's image is `:latest` and must be pinned (line 34).
- The app's base NetworkPolicy allows egress only on 53, 80, 443, 2283, 11434 and 8092 (`deploy/kubernetes/base/networkpolicy.yaml:23-49`). An in-cluster app cannot reach the worker Service on 8093 without an extra rule, and the HTTP ClusterIP also needs `allow_insecure_http`. The same policy blocks the port-8000 reader example in reader.md:47 and the ACE-Step `api_url` in music.md:58.
- `run/kubernetes.md` covers the policy, but none of my pages link to it from these examples. The README covers the Secret.
- Fix: two sentences plus a link.
- Confidence: VERIFIED.

### F-21 [GAP] better/inference.md, reference/inference-service.md:94-101, run/hardware.md:53-74: no minimum NVIDIA driver version
- The CUDA image is built on `nvidia/cuda:12.8.1-cudnn-runtime` (`docker/Dockerfile.inference:22`), with llama.cpp `server-cuda-b10920` (line 24). The test command uses a 12.4 base image.
- `grep -rn "driver version\|525\|535\|550\|570" docs-site/docs` finds no driver floor anywhere.
- Confidence: LIKELY a real-world stumbling point. The exact floor was not determined.

### F-22 [CLARITY] reference/llm-providers.md:371 versus 390-391: "Text only. No request to the reader carries a picture"
- The same page's conformance suite probes "image captions and motion" through the configured LLM. `caption_provider: llm` sends images to the same `advanced.llm` endpoint (`analysis/editorial_preparation_captions.py:228-240`).
- Fix: say "the selection reader" and point to the opt-in.

### F-23 [CLARITY] reference/caption-service.md:137: "The first `up` pulls 546 MB"
- 437 + 109 MB is the GGUF weights only. The llama.cpp `server` image is pulled as well.
- Fix: "downloads 546 MB of weights".

### F-24 [CLARITY] cross-page: reference/config-reference.md:437-439 points to the wrong page
- It says dialect routing, `thinking` behaviour, the param dialects and batching "are all on The reader (`../better/reader.md`)".
- They are on `reference/llm-providers.md`. reader.md:68 itself defers to that page.
- Fix: retarget the link (config-reference is outside my scope).

### F-25 [CLARITY] reference/llm-providers.md:215-216 versus 392-393: why sharing readers are in the suite
- The page says "Sharing never asks the prose LLM", yet the conformance suite includes `audience activity` and `audience exposure`. Running `cases(...)` lists 34 cases ending in these two.
- "Both audience text readers still present in the code" will confuse a privacy-minded reader: does the LLM see sharing questions or not?
- Fix: one clause on when those call sites run, if ever.

### F-26 [GAP] better/music.md:49-61 and local-audio.md:380-383: "ACE-Step API server" is never defined
- The client expects the ACE-Step REST shape: `GET /health` returning `data.status == "ok"`, `POST /release_task`, `POST /query_result`, then a file GET (`audio/generators/ace_step_backend.py:160-163, 415, 471, 517`). It defaults to port 8000.
- No page says which upstream server or command provides this, or which port it uses. The config docstring calls it a "remote Gradio API server", which adds to the confusion.
- A reader with a GPU box cannot stand one up from these pages.
- Confidence: VERIFIED for the client shape. The upstream server command was not checked.

### F-27 [POLISH] reference/inference-service.md:63: "Use the release candidate's published image tag matching your app"
- This wording goes stale at 1.0.0 final.
- Use "the published image tag matching your app version".

### F-28 [GAP] reference/inference-service.md:146-147 and caption-service.md:272-273 (relates to the known repin bug)
- The pages tell operators to "bump both together and match them to the app version". The shipped overlays still pin `0.100.4` and `0.100.4-cuda` (`deploy/kubernetes/overlays/inference/kustomization.yaml:30`, `inference-cuda/kustomization.yaml:22`, `render-sidecar/kustomization.yaml:22`, `base/kustomization.yaml:28`).
- An rc.1 operator applying the overlays as-is gets a version mismatch, and the render worker refuses it (`processing/remote_render.py:85-86`).
- Report only if this differs from the known "release bundle repin bug".

### New detail on a known item
- The hosted examples without `base_url` (reader.md:59-68, llm-providers.md:249-256) also mislead preflight. It reports the owned-reader check: "Install llama.cpp and put llama-server on PATH", or "Local reader installed; generation not tested" (`preflight.py:372-385`, `local_inference.py:87-89`). It never mentions the missing URL, so a hosted user is pointed at installing llama.cpp.

### Verified correct (selected, for the record)
- Dialect paths: `{base_url}/chat/completions`, `{base_url}/v1/messages`, Ollama `/api/generate`. Headers `x-api-key` and `anthropic-version: 2023-06-01`. Batch routes `/v1/batches` and `/v1/messages/batches`. Provider errors are cut at 300 characters. The Ollama `think`/`num_predict` behaviour and the 16,384 headroom.
- Model pins and digests: Gemma reader pair, SmolVLM GGUF repo, revision and SHA-256 values. These match `pinned_models.py` and the compose and K8s init scripts byte for byte.
- Laya: names, the 0.185 and 0.186 thresholds, platform selection, the 1 GiB cap. Calibration counts (15, 23 and one added, 3,143) match #1385.
- Ports: inference 8092, captioner host 8094 to container 8092, worker 8093, unified `/v1` and `/render`. Render waits 60 s; other requests get 503 with `Retry-After: 1`. The queue returns 429 at 32. All `/queue` fields. Settings defaults. Retry backoff from 10 s to 120 s.
- Render: timeout defaults of 3600 on both sides, the env prefix, loopback detection, the version refusal, the `accelerated` rule.
- Hardware: backend literals, VAAPI levels 7/4/1, the driver packages and `vainfo` in the amd64 image only, the NAS 1080p cap, `IMMICH_FORCE_CPU`.
- Audio: the memory table (29/21/11/9/7) and disk table recomputed from `memory_budget.py`. The MLX cache rule (0 at 16 GiB or less, otherwise 4 GiB). The ACE-Step `v0.1.8` and torch 2.13 / torchvision 0.28 / torchaudio 2.11 / cu126 pins. `TORCH_DISABLE_NATIVE_JIT`. `cpu_offload` defaults to True through the factory. Stem priority: MusicGen, then inference, then local.
- measured.md LLM table: 33/34 at 213.63 s with 86 attempts, 33/34 at 206.59 s with 87, 34/34 at 294.78 s with 85, 34/34 at 223.44 s with 85. Rows: 136 complete plus 74 held-out. Motion: 1/5, 2/5, 3/5, 3/5. All recomputed from the CSV.
- The conformance suite has exactly 34 cases. It reads `advanced.llm` or `llm`.
- Voice gate: `scripts/docs_voice_gate.py` prints "docs-voice: clean". I saw no em dashes or chatbot words on these pages.
- Every relative link and anchor I followed resolves.

## 3. Unverifiable claims (not reported as wrong)
- Laya is "0.4B", runs "about 14 ms a shot on Apple silicon", and its training set and credits are as described. Whether the MLX 0.186 threshold "kept every hold".
- GGUF sizes of 437 MB and 109 MB (Hugging Face is blocked by the egress proxy). Whether SmolLM-based SmolVLM2-500M "has 32" layers.
- The mlxcel commands (`brew install lablup/tap/mlxcel`, `mlxcel serve --alias ... --host --port`) and that mlxcel binds 127.0.0.1 by default.
- All whole-film timings and memory figures in measured.md: 7m 23s, 78m 51s, 15m 29s, 5m 43s, 39m 40s, 12.38 and 17.02 GB RSS, the 4h 20m 45s stress run at 2.87 and 3.74 GiB, the nine maps taking 911 s or 43%. No in-repo data file holds them.
- The qualitative motion failure descriptions ("exceeded the 120-character contract", "acquired a horizontal direction"). The CSV records only a pass or fail plus a short reason such as `ValueError`. The earlier Melious leftward run. The z.ai race and routine tie.
- Captioner speeds (3.5 s per picture on CPU, 0.08 to 0.23 s on GPU) and the CPU concurrency measurement.
- "Mac wheels require macOS 14 or newer". The FFmpeg 5.1, 6.1, 7.1 and 8.1 keyframe behaviour. Whether Gemini Lake (J4125) has HEVC encode.
- DINOv2 at 88 MB (consistent with a code comment) and Marqo at 22.5 MB.
- Claude model behaviour: model IDs `claude-sonnet-5` and `claude-haiku-4-5` exist per the bundled API reference. "From the 4.7 line on, Claude refuses any sampling parameter" matches that reference. None of it was executed against the API.
