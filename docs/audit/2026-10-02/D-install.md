# D: Install and deployment pages audit

Auditor scope: docs-site/docs/run/{overview,requirements,docker,nas,uv-pip,kubernetes,terraform,reference-setup}.md,
docs-site/docs/run/reference/{kubernetes,terraform,cluster-example,mac-example,python-install}.md,
docs-site/src/components/DeploymentDiagram.tsx and InstallationFiles/index.tsx.

Repo HEAD: b371427b. Tools used: kustomize v5.4.3 on the extracted bundle copy (`tmp.JRWmHJqity/deploy`, pins 0.103.0)
and on scratch copies of it; `docker compose config -q` on docker-compose.yml + example.env (OK);
`uv run --no-sync immich-memories <cmd> --help` for every CLI command the pages use; a local
anchor/link checker over all 13 pages (no broken file links or anchors); `scripts/docs_voice_gate.py`
(clean) and `scripts/check_docs_commands.py` (clean). Terraform is not installed: HCL read by hand.

## 1. Coverage

| Page | Claims checked (approx.) | Findings | Verdict |
|---|---|---|---|
| run/overview.md | 12 | 0 | Accurate; links resolve. |
| run/requirements.md | 30 | 2 (D-5, D-15) | Accurate on tiers and resolver; 25 GB disk figure is contradicted by the k8s/TF claim sizes; forcing `full` failure mode missing. |
| run/docker.md | 55 | 4 (D-7, D-10, D-14, D-24) | Commands and compose facts all correct; API-key minimal list likely incomplete; preflight table misquotes messages. |
| run/nas.md | 30 | 2 (D-8, D-9) | Facts correct; NAS-manager specifics (Unraid/TrueNAS, project names, chowning a named volume) thin for a newcomer. |
| run/uv-pip.md | 35 | 1 (D-26) | Extras, CLI flags, bind rule, scheduler all verified. RC install line installs the last final. |
| run/kubernetes.md | 60 | 7 (D-2, D-5, D-6, D-11, D-13, D-16, D-25) | Manifest facts (PVCs, ports, probes, securityContext, mounts) verified by build; CronJob path likely blocked by the shipped NetworkPolicy. |
| run/terraform.md | 20 | 3 (D-1, D-18, D-23) | Quick start tells the reader to pin `image_tag` in an example that has no such variable. |
| run/reference-setup.md | 25 | 2 (D-21, D-22) | Matches compose.gpu-worker.yaml, captioner script and render config; two unclear sentences. |
| run/reference/kubernetes.md | 45 | 3 (D-3, D-4, D-17) | Namespace loop leaves Secrets of render-sidecar/postgres behind and cannot move maximalist (verified by kustomize). Reader example in the base manifest is broken YAML. |
| run/reference/terraform.md | 40 | 2 (D-11, D-19) | Variable table matches variables.tf exactly; sidecar token requirement and reader-model wording gaps. |
| run/reference/cluster-example.md | 30 | 1 (D-17) | Matches the maximalist overlay build; port wording inconsistent with the other k8s pages. |
| run/reference/mac-example.md | 20 | 0 | Make targets, config keys, memory figures (7 GB / 6 GB) all consistent with Makefile and local-audio.md. |
| run/reference/python-install.md | 15 | 1 (D-20) | Extras table matches pyproject exactly. |
| DeploymentDiagram.tsx | 25 | 0 | Every port, path and boundary it shows matches the manifests and compose recipes. |
| InstallationFiles/index.tsx | 8 | 2 (D-10, D-27) | Download commands correct; the override pins the app only, not the inference/captioner tags. |
| Manifests referenced by the pages | n/a | 1 (D-27) | Stale comments and dead doc anchors inside deploy/ that the pages send readers to. |

Totals: BLOCKER 1, WRONG 2, GAP 13, CLARITY 10, POLISH 1 (27 findings).

## 2. Findings

### D-1 [WRONG] run/terraform.md:25 (also :70) — "pinned `image_tag`" cannot be set in the basic example
- Claim: "From the release deployment bundle, choose the private CPU example ... Edit the Immich URL, API key and pinned `image_tag`." Upgrading (:70): "change `image_tag`, plan/apply".
- Reality: `deploy/terraform/examples/basic` declares no `image_tag` variable and does not pass one to the module, so the module default `latest` is always used. Terraform will warn "Value for undeclared variable" and ignore the line if the reader adds it to terraform.tfvars. The bundle does not repin anything under deploy/terraform either. The module pulls with `image_pull_policy = "Always"`, so every pod restart silently upgrades the app (and its store schema) with no backup step. During an RC, `latest` is not even the RC: release.yml never moves `latest` for a prerelease.
- Evidence: deploy/terraform/examples/basic/variables.tf (only immich_url, immich_api_key, llm_*, gpu_enabled); examples/basic/main.tf:22-41 (no image_tag); deploy/terraform/variables.tf:19-23 (`default = "latest"`); main.tf:332-333 (`image_pull_policy = "Always"`); scripts/package_deployment.py:22-26 (pins only the three kustomize files); .github/workflows/release.yml:655-664 (`elif [ "$PRERELEASE" = "true" ]; then latest=()`).
- Fix: add `variable "image_tag"` (no default, or the release version) to examples/basic and pass it through, put `image_tag = "X.Y.Z"` in basic/terraform.tfvars.example, and have package_deployment.py stamp the release version into the example tfvars. Or change the page to say "use examples/production, which takes image_tag".
- Confidence: VERIFIED (files read; terraform plan not executed).

### D-2 [BLOCKER] run/kubernetes.md:199-202, run/reference/kubernetes.md:136-149 — CronJobs are very likely blocked by the base NetworkPolicy
- Claim: "Its CronJobs call `POST /api/trigger` on the running app"; the NetworkPolicy section (:118-123) lists the allowed egress ports with no warning for the jobs.
- Reality: the CronJob pods carry `app.kubernetes.io/name: immich-memories`, so the base policy (podSelector on that label, policyTypes Egress) applies to them. They curl `http://immich-memories` (Service port 80, targetPort 8080). Egress allows 53, 80, 443, 2283, 11434, 8092 but not 8080. Common enforcing CNIs (Calico, Cilium) evaluate egress after Service DNAT, against the backend pod port 8080, so the curl times out and both CronJobs fail on any cluster that enforces NetworkPolicy.
- Evidence: deploy/kubernetes/base/job.yaml:214-218 and 285-289 (pod labels), :242 and :313 (`http://immich-memories/api/trigger`); base/networkpolicy.yaml:9-12 (podSelector), :22-47 (egress ports); base/service.yaml:10-13 (port 80 -> targetPort http=8080).
- Fix: add an egress rule `to: [{podSelector: {matchLabels: {app.kubernetes.io/name: immich-memories}}}] ports: [{port: 8080}]` to the base policy, or give the CronJob pods a different `app.kubernetes.io/name` and their own small policy. Then say in both pages that the jobs need it.
- Confidence: LIKELY (manifests read; not applied to a live cluster with an enforcing CNI; behaviour is CNI-dependent).

### D-3 [WRONG] run/reference/kubernetes.md:12-23 — the namespace loop does not move render-sidecar, postgres or maximalist
- Claim: run the `kustomize edit set namespace` loop over base, inference, captioner, inference-lan; "`overlays/gpu`, `overlays/inference-cuda` and `overlays/captioner-cuda` build on those roots and follow them. Three things do not: ...".
- Reality: built after running that exact loop with `photos-memories`:
  - `overlays/render-sidecar`: Secret `immich-memories-render-worker` stays in `immich-memories` while the Deployment moves, so the pod cannot mount its token (and the apply fails if that namespace does not exist).
  - `overlays/postgres`: Secret `immich-memories-database` stays in `immich-memories`; same failure.
  - `overlays/maximalist`: its own `namespace: immich-memories` forces every resource (19) back to `immich-memories`.
- Evidence: commands run in a scratch copy: `for d in base overlays/inference overlays/captioner overlays/inference-lan; do (cd $d && kustomize edit set namespace photos-memories); done`, then `kustomize build overlays/render-sidecar` showed `Secret immich-memories-render-worker` in namespace `immich-memories`; `kustomize build overlays/postgres` showed `Secret immich-memories-database` in `immich-memories`; `kustomize build overlays/maximalist` printed `19 namespace: immich-memories`. Sources: overlays/maximalist/kustomization.yaml:26; overlays/render-sidecar/kustomization.yaml (no namespace field) with render-worker-secret.yaml.example:13; overlays/postgres/kustomization.yaml (no namespace field) with database-secret.yaml.example:17.
- Fix: add `overlays/render-sidecar overlays/postgres overlays/maximalist` to the loop (or add `namespace:` to those kustomizations), and list them in "follow / do not follow". kubernetes.md:245 ("Set `namespace:` in each kustomization root you apply") is correct and could be quoted instead.
- Confidence: VERIFIED (kustomize v5.4.3 build).

### D-4 [GAP] run/reference/kubernetes.md:126 (and :57-59) — the reader example it points to is broken YAML with a port the policy blocks
- Claim: "the reader (commented env vars on the Deployment, Add a reader)"; "the Deployment ... carries commented examples for the reader".
- Reality: the commented block has two `value:` keys under one entry; uncommenting it makes kustomize fail. It also points at port 8080 (not in the egress policy) and names `qwen2.5-vl`, a vision model, under "LLM clip content analysis", while the docs say the reader reads text only and needs 32k context.
- Evidence: base/deployment.yaml:124-129. After uncommenting lines 125-129 in a scratch copy: `kustomize build .` -> `Error: ... yaml: unmarshal errors: line 122: mapping key "value" already defined at line 121`.
- Fix: in deployment.yaml replace the block with `IMMICH_MEMORIES_LLM__BASE_URL` + `IMMICH_MEMORIES_LLM__MODEL` (a text model, e.g. the docs' `gemma-4-e4b-it-6bit`), drop the stray `value: "true"`, and use a port the policy allows (11434) or say to add one.
- Confidence: VERIFIED.

### D-5 [GAP] run/kubernetes.md:16 vs run/requirements.md:18,23 and get-started/quick-start.md:9 — the data PVC is smaller than the page's own disk requirement
- Claim: requirements: "25 GB for the persistent data volume ... default preview and video caches: 10 GB each, plus the store and model files". kubernetes.md: "data/cache 20Gi". Terraform default `cache_storage_size` is also 20Gi.
- Reality: on Kubernetes both caches (10 GB + 10 GB defaults), the store, the Laya checkpoint (up to 1 GiB) and an owned reader's GGUF all land on that 20Gi claim, so a default install can fill it. The maximalist overlay and the TF maximalist example lower both caps for exactly this reason, but the basic path does not.
- Evidence: src/immich_memories/config_models.py:192-194 (video 10 GB), :220-222 (thumbnails 10,000 MB); laya_checkpoints.py:29-31 (`~/.immich-memories/models/laya/`); local_inference.py:53 (`~/.immich-memories/models/reader`); pinned_models.py:57 (LAYA_MAX_BYTES 1 GiB); base/pvc.yaml:16; deploy/terraform/variables.tf:176-180; overlays/maximalist/config-map.yaml:79-85 ("lowered here so they sit well inside the base's 20Gi cache PVC").
- Fix: raise the base claim and TF default to 30Gi, or state on kubernetes.md that 20Gi needs `IMMICH_MEMORIES_CACHE__VIDEO_CACHE_MAX_SIZE_GB` / `..._THUMBNAIL_CACHE_MAX_SIZE_MB` lowered.
- Confidence: VERIFIED (numbers from code and manifests).

### D-6 [CLARITY] run/kubernetes.md:105-109 — `/models` does not hold the tier-dependent Laya or reader files
- Claim: "`/models` | Models PVC: encoder, WordNet and tier-dependent model files"; data PVC holds "store, settings, session key, previews and clips".
- Reality: only the encoder, WordNet, Marqo and the detector HF cache are redirected to /models by env. Laya (gpu/full) and the owned reader GGUF default to `~/.immich-memories/models/...`, which is the data PVC.
- Evidence: base/deployment.yaml:116-123 (only four env redirects); laya_checkpoints.py:31; local_inference.py:53.
- Fix: "`/models`: encoder, WordNet, sensitive-content export and detector cache. Laya and an owned reader's GGUF go to the data PVC."
- Confidence: VERIFIED.

### D-7 [GAP] run/docker.md:108-118 — the minimal API-key permission list probably misses user and face reads
- Claim: four permission rows: read assets/people/albums/timeline/search; tags; upload/albums; delete.
- Reality: the app also calls `GET /users/me` (readiness probe and connection check) and `GET /faces` (face boxes). In Immich's granular key model those are separate permissions (user read, face read). A key built from this table alone would likely leave `/health/ready` at 503 and preflight at "Connection failed". The Immich gate test only ever uses an `all` key, so this is untested.
- Evidence: src/immich_memories/api/immich.py:322-324 and :344 (`/users/me`); web/health.py:64 (readiness calls `get_current_user`); api/asset_service.py:83 (`/faces`); tests/integration/immich_gate/seed.py:94 (`"permissions": ["all"]`).
- Fix: add "Read your user" and "Read faces" rows (with Immich's exact permission names), and add a gate test with the minimal key.
- Confidence: LIKELY (Immich's endpoint-to-permission mapping not checked: no network access to Immich source).

### D-8 [GAP] run/nas.md:13-22 — "Import as a project" plus `docker compose exec` does not hold on every NAS listed
- Claim: "Import `docker-compose.yml` as a project in your NAS's container manager. Put `.env` and an `output` folder beside it." then `sudo docker compose exec immich-memories ...` from "that folder".
- Reality: Unraid's Docker manager has no compose projects without the Compose Manager plugin; TrueNAS SCALE's YAML app install has no `.env` beside it. `docker compose exec` also resolves the project from the folder name, so it fails if the manager's project name differs from the folder. The compose file sets `container_name: immich-memories`, so `sudo docker exec immich-memories immich-memories models fetch` works on every NAS no matter how the project is named.
- Evidence: docker-compose.yml:36 (`container_name: immich-memories`); nas.md:7 names Synology, QNAP, TrueNAS SCALE and Unraid.
- Fix: use `sudo docker exec immich-memories immich-memories ...` on the NAS page; add one line each for Unraid (Compose Manager plugin) and TrueNAS (put the values inline or in the app's env).
- Confidence: LIKELY (NAS UIs not exercised).

### D-9 [GAP] run/nas.md:36-37 — "chown the config volume to match" gives no command
- Claim: "set `user: "<uid>:<gid>"` in the Compose service and chown the config volume to match."
- Reality: the config store is a named volume (`<project>_immich-memories-config`), not a folder the newcomer can see, and the page gives no way to chown it.
- Evidence: docker-compose.yml:43, :362-363.
- Fix: add e.g. `sudo docker run --rm -v immich-memories_immich-memories-config:/v busybox chown -R <uid>:<gid> /v` (project prefix noted).
- Confidence: VERIFIED that no command is given.

### D-10 [GAP] InstallationFiles/index.tsx:12-27 and run/docker.md:13-22,157-168 — add-on images are not pinned with the app; `latest` is not the RC
- Claim: InstallationFiles: "The files and image use the same release." docker.md add-ons table points at the `inference` and `captioner` profiles.
- Reality: the override only sets `services.immich-memories.image`. The inference service still uses `${INFERENCE_TAG:-latest}`, and release.yml does not move `inference:latest` (or the app's `latest`) for a prerelease, so an RC install with `--profile inference` runs the previous final's inference service. The app rejects a service whose head versions differ. For docker.md (new aspect beyond the known "curls from main"): its compose uses the app's `:latest`, which during an RC is the previous final, not the RC.
- Evidence: docker-compose.yml:154 (`inference:${INFERENCE_TAG:-latest}`), :35 (`:latest`); release.yml:558-570 (prerelease: no `latest`/`latest-cuda`), :655-664 (app: no `latest` for prerelease); src/immich_memories/analysis/remote_facts.py:73-76 (`Remote classifiers do not support the requested head versions`).
- Fix: have the override also set `immich-memories-inference.image: ...inference:<version>`, or tell the reader to put `INFERENCE_TAG=<version>` in `.env`.
- Confidence: LIKELY (the mismatch error path read, not exercised).

### D-11 [GAP] run/kubernetes.md:157-158 and run/reference/terraform.md:189 — render-worker secret requirements are incomplete
- Claim (k8s): copy the example, "generate a token (`openssl rand -hex 32`), then apply". TF: "`render_worker_sidecar_enabled`, `render_worker_token` | Worker sidecar and shared token".
- Reality: the k8s Secret also carries `immich-url` (example value `https://photos.example.com`) that must be edited. In Terraform, `render_worker_token` defaults to `""` with no validation, and the worker refuses to start with an empty token, so the pod never goes Ready.
- Evidence: overlays/render-sidecar/render-worker-secret.yaml.example:19-21; deploy/terraform/variables.tf:365-370; services/render-worker/immich_memories_render_worker/settings.py:15,22-27 (`a worker bearer token is required`).
- Fix: k8s page: "set `token` and `immich-url`". TF table: "required when the sidecar is on"; add a `validation` block in variables.tf.
- Confidence: VERIFIED (code read).

### D-12 [GAP] run/kubernetes.md:100-110, run/reference/kubernetes.md:28-37 — no writable `~/.cache` in the app container
- Claim: "Four writable paths" (data, output, models, /tmp) under a read-only root.
- Reality: local Demucs (used for stems of generated music, which the maximalist example enables through ACE-Step) loads `htdemucs` through torch hub into `~/.cache/torch`, which is read-only in these pods. The manifests' own comment says `~/.cache` still needs a writable mount. The Docker hardening block includes a `/home/immich/.cache` tmpfs for this; the k8s base and TF module do not. The render sidecar gets its own `worker-cache` mount, the app container does not.
- Evidence: base/deployment.yaml:94-96 (comment) and :147-156 (mounts); deploy/terraform/main.tf:337-339; audio/generators/demucs_local.py:94-97 (`get_model`); docker-compose.yml:128-130 (tmpfs `/home/immich/.cache`); overlays/render-sidecar/deployment-sidecar.yaml:113-114.
- Fix: add an `emptyDir` at `/home/immich/.cache` (1Gi) to the base, job and TF pod, or set `TORCH_HOME` to the data volume; list it in the mount table.
- Confidence: LIKELY (not run in a pod).

### D-13 [CLARITY] run/kubernetes.md:46, :240 — the init guard never passes on the default NAS tier
- Claim: "The init container fetches model files needed by its configuration." (true) / "The init guard checks presence only".
- Reality: the guard requires `/models/detectors/nsfw-marqo-384.onnx`, which `models fetch` only writes when detectors are enabled (gpu/full). On NAS the guard always fails and `models fetch` re-runs on every pod start. The manifest comment says "a claim that already carries all three never goes back out". This is harmless (digest re-check) but surprising when reading init logs, and it needs HF egress if anything is missing.
- Evidence: base/deployment.yaml:36-41, :56-60; config_tiers.py:39-40 (nas: detectors False); cli/models_cmd.py:85-88 (returns before Marqo).
- Fix: guard only on encoder + WordNet, or fix the comment; one sentence in the page.
- Confidence: VERIFIED.

### D-14 [CLARITY] run/docker.md:73-78 — the "Preflight says" column does not match preflight's text
- Claim: "Pinned model missing or wrong digest", "Immich connection failed".
- Reality: preflight prints `Encoder: Pinned DINOv2 export missing` / `Not the pinned DINOv2 export` and `Immich: Connection failed`. A reader scanning the output for the quoted text will not find it.
- Evidence: src/immich_memories/preflight_run.py:34, :43; preflight.py:108-112.
- Fix: quote the real messages.
- Confidence: VERIFIED.

### D-15 [GAP] run/requirements.md:103-104 — forcing `full` without a reader stops the app from loading
- Claim: "You may force `nas`, `gpu` or `full`, but that does not install models or start servers."
- Reality: `full` without an enabled LLM and model raises at config load ("tier: full needs an enabled LLM ..."), so every command fails, not just preparation.
- Evidence: src/immich_memories/config_tiers.py:76-77, :117-123.
- Fix: add "`full` refuses to load until a reader is enabled with a model."
- Confidence: VERIFIED.

### D-16 [CLARITY] run/kubernetes.md:43, run/reference/kubernetes.md:15 — needs the standalone `kustomize` binary
- Claim: `kustomize edit set image ...=:X.Y.Z`, `kustomize edit set namespace ...`.
- Reality: the syntax works (tested: `edit set image ghcr.io/...=:1.2.3` produced `newTag: 1.2.3`), but every other command on these pages uses `kubectl`, which has no `edit` subcommand. A reader with only kubectl stops here.
- Evidence: ran in a scratch copy with kustomize v5.4.3; kubectl's built-in kustomize offers build only.
- Fix: "needs the kustomize CLI; or edit `newTag:` in base/kustomization.yaml by hand".
- Confidence: VERIFIED for the syntax; the kubectl limitation is from knowledge (kubectl not installed here).

### D-17 [CLARITY] run/kubernetes.md:121, run/reference/kubernetes.md:63-64 vs run/reference/cluster-example.md:82 — oMLX port stated two ways
- Claim: "oMLX commonly uses 8000" / "(Ollama's port; oMLX serves on 8000)" vs cluster-example "reader port 9999".
- Reality: the maximalist overlay configures oMLX at `:9999` and opens 9999. Both can be true, but an operator copying the maximalist example after reading "oMLX serves on 8000" will open the wrong port.
- Evidence: overlays/maximalist/config-map.yaml:120-124; networkpolicy-maximalist.yaml:178-182.
- Fix: cluster-example: "the example's oMLX listens on 9999 (its default is 8000)".
- Confidence: VERIFIED.

### D-18 [GAP] run/terraform.md:27-31 — `terraform apply` waits for a Ready pod
- Claim: `terraform apply`, then port-forward.
- Reality: `kubernetes_deployment_v1` waits for rollout by default, and readiness stays 503 until Immich answers. A wrong `immich_url` or a NetworkPolicy elsewhere makes `apply` hang until the provider timeout and report a failure, even though the resources exist.
- Evidence: deploy/terraform/main.tf:220 (no `wait_for_rollout` set) and :415-424 (readiness `/health/ready`); web/health.py:323-326 (503 unless ready).
- Fix: one sentence under Quick start, pointing to the readiness check in Troubleshooting.
- Confidence: LIKELY (provider default from knowledge; not applied).

### D-19 [CLARITY] run/reference/terraform.md:101-104, :151 — reader wording conflicts with the module and examples
- Claim: "The reader ... reads text only and must hold 32k of context".
- Reality: variables.tf describes `llm_model` as "Vision model name" and `llm_base_url` as "LLM clip content analysis"; examples/production/terraform.tfvars.example has an active (not commented) `llm_base_url = "http://ollama.ollama.svc.cluster.local:11434/v1"` with `qwen2.5-vl`, so a copied production example points at a server most clusters do not have.
- Evidence: deploy/terraform/variables.tf:43-54; examples/production/terraform.tfvars.example:22-25; examples/basic/variables.tf:12-22.
- Fix: update the variable descriptions; comment out the reader lines in the production tfvars example.
- Confidence: VERIFIED.

### D-20 [CLARITY] run/reference/python-install.md:145 — "`pip install -e .` works too"
- Reality: a bare editable install has no `onnxruntime`, which the same page calls "the one you need" for films.
- Evidence: pyproject.toml:31-67 (base deps without onnxruntime), :110-115 (`editorial`).
- Fix: `pip install -e ".[editorial]"`.
- Confidence: VERIFIED.

### D-21 [CLARITY] run/reference-setup.md:92-93 — unclear volume sentence
- Claim: "A model-only service's small temporary volume can fill during source preparation after rendering is added."
- Reality: the recipe on this page mounts no temporary volume (only `/cache` and `/app/output`); it is not clear which volume or which deployment is meant.
- Evidence: services/inference/compose.gpu-worker.yaml:16-18.
- Fix: name it (for example the inference overlay's `/tmp` emptyDir) or remove it.
- Confidence: VERIFIED.

### D-22 [CLARITY] run/reference-setup.md:53-57 — preflight from "the app's environment"
- Reality: this page's app is "on the NAS", which means Docker; the command needs `docker compose exec immich-memories` (docker.md's prefix). A newcomer will run it on the host and get "command not found".
- Fix: show the Docker form.
- Confidence: VERIFIED.

### D-23 [CLARITY] run/terraform.md:35, :52 — verification link points to a pointer
- Reality: kubernetes.md#check-it-from-outside-the-pod (:248-251) only says "Use the quick-start `kubectl exec ... preflight` command". The Terraform reader has to follow a second hop to find the commands.
- Fix: inline the three `kubectl exec` / port-forward lines (deployment `immich-memories`, namespace `var.namespace`).
- Confidence: VERIFIED.

### D-24 [GAP] run/docker.md:267-270 — custom music path has no mount example
- Claim: "bind-mount a music directory and use `--music /app/music/track.mp3`".
- Reality: nothing in docker-compose.yml mounts `/app/music`; the reader has to invent the volume line.
- Fix: show `- ./music:/app/music:ro` under `volumes:`.
- Confidence: VERIFIED.

### D-25 [GAP] run/kubernetes.md:133-138 — captioner-cuda has no GPU request
- Claim: apply `overlays/inference-cuda` and `overlays/captioner-cuda` for GPU preparation.
- Reality: captioner-cuda deliberately requests no `nvidia.com/gpu`. It relies on time-slicing or another way to share the device, with no scheduler reservation. cluster-example.md:42-45 explains this; kubernetes.md, where an operator is most likely to apply it, does not.
- Evidence: overlays/captioner-cuda/deployment-cuda.yaml:1-20.
- Fix: one sentence plus a link to the explicit-request recipe.
- Confidence: VERIFIED.

### D-26 [GAP] run/uv-pip.md:163 — RC testers get the last final
- Claim: `uv tool install "immich-memories[all]"`.
- Reality: uv (like pip) skips pre-releases unless asked, so during rc.1 this installs the previous final.
- Fix (RC docs only): `uv tool install --prerelease allow "immich-memories[all]==1.0.0rc1"` or an equivalent note.
- Confidence: LIKELY (uv default pre-release policy from knowledge).

### D-27 [POLISH] Manifests the pages send readers to carry stale comments and dead anchors
- overlays/maximalist/config-map.yaml:51 links `docs-site/docs/run/reference-setup.md#the-always-on-server-kubernetes`, and overlays/maximalist/kustomization.yaml:16-17 and examples/maximalist/main.tf:4 call reference-setup.md the walkthrough. That page is now "One GPU service"; the walkthrough is reference/cluster-example.md, and the anchor does not exist.
- base/job.yaml:1-2 says "or `kubectl apply -f job.yaml`"; kubernetes.md:206-207 correctly warns that this bypasses the image pin.
- overlays/gpu/deployment-gpu.yaml:1 says "CUDA analysis"; the app image is CPU-only ONNX (docker/Dockerfile:53-59) and kubernetes.md:127-128 correctly says encoding/titles only.
- InstallationFiles/index.tsx:21 dev-build text says "pin these files and the image to the RC tag", which is wrong wording once a final is released.
- Fix: update the comments and links.
- Confidence: VERIFIED.

## 3. Unverifiable claims (not reported as wrong)

- docker.md:243-263: the read-only-root hardening block works end to end. No container test runs with `read_only: true` (grep of tests/ and scripts/ found none).
- kubernetes.md:127-128 / reference/terraform.md:122: NVENC works with the app image's Debian FFmpeg on the gpu overlay (image not run).
- nas.md:13-22: Synology Container Manager reads `.env` from the project folder and ships `docker compose` v2.
- uv-pip.md:149-158: Homebrew's `ffmpeg-full` formula name and its zscale filter.
- nas.md:101 / hardware: J4125 cannot encode HEVC (the owner measured this; source comments agree, hardware.py:396).
- requirements.md:105 and nas.md:69: "Changing tier keeps compatible prepared facts and your review decisions".
- Whether `tier: auto` re-resolves after the app starts when the inference service comes up later (resolution happens in `apply_tier` at config load; fallback_to_local defaults true). On a fresh cluster this matters if the app pod starts before inference is Ready.
- reference-setup.md:76-80: the 429 on classifier queue overflow, and queue semantics (the 60 s phase timeout was verified at gpu_phases.py:21 and the 503/Retry-After at :120-121).
- D-2 and D-7 depend on CNI behaviour and Immich's permission table respectively (see each finding).
- Terraform HCL validity overall (terraform not installed; hand-read only).
- DeploymentDiagram layout on phone widths (not rendered in a browser).

## Verified as correct (selected, for the record)

PVC names/sizes (20Gi/50Gi/5Gi), Service 80->8080, probes and their paths/timings, `/health` always 200 vs `/health/ready` 503, securityContext (UID/GID 1000, fsGroup, RuntimeDefault, drop ALL, read-only root), `/tmp` 4Gi emptyDir, `enableServiceLinks: false` everywhere, base NP ports (53, 80, 443, 2283, 11434, 8092), inference/captioner Service names and port 8092, inference-lan LoadBalancer, render sidecar loopback 8093 and exec probes, postgres overlay envFrom (and the JSON-patch for 5432 builds), the kustomize namespace transformer renaming the Namespace object, `kustomize edit set image name=:tag` syntax, every overlay building, TF variable table rows (all defaults match variables.tf), TF outputs including `port_forward_command`, compose facts (127.0.0.1:8080, 4G limit, container_name, UID 1000, TZ, homebase `:-0`, profiles, captioner 8094->8092), example.env keys, CLI flags (`ui --host`, `auto install --hour/--uninstall`, `Activate:` line, `store backup` default path, `generate --year/--month/--music`, `models fetch` behaviour per tier, `config show tier`, `-v`), the bind rule (`effective_host`), extras composition (`all` vs `all-mac`), Make targets (`dev`, `dev-mac`, `web-client`, `install-acestep`, `check-local-audio`, `docker`), upload cleanup after confirmed delivery, the `preset: fast` three-view maps, `/health/live` in the Dockerfile HEALTHCHECK, and the gpu-worker compose recipe (bind default, volumes, no RAM limit, bearer only on `/render`).
