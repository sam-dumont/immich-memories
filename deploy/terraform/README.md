# Terraform Module for Immich Memories

Deploys Immich Memories to Kubernetes with the `hashicorp/kubernetes` provider. CPU only by
default; NVIDIA GPU scheduling is a variable.

Authentication is disabled by default. Configure it before enabling Ingress. The UI is
single-user, single-replica because active workflow state is in-process; do not scale past one pod.

This module gets less exercise than Docker Compose: it is `terraform validate`d in the repo, not
applied to a live cluster on every release. Read the plan before you apply it.

## What it creates

Namespace (optional), Secret, three `ReadWriteOnce` PVCs, Deployment, Service, Ingress (optional).

The image runs as user `immich`, UID/GID 1000, `HOME=/home/immich`:

| Mount | Backed by | Holds |
|-------|-----------|-------|
| `/home/immich/.immich-memories` | cache PVC (writable) | `config.yaml`, `cache.db`, video cache, projects, automation history |
| `/app/output` | output PVC | generated videos (`IMMICH_MEMORIES_OUTPUT__DIRECTORY=/app/output`) |
| `/models` | models PVC (`models_storage_size`, 10Gi) | pinned encoder, sensitive-content model and detector snapshot |
| `/tmp` | emptyDir (`tmp_size`, 4Gi) | FFmpeg intermediates |

The init container runs `models fetch` on an empty models claim. The default tier is
`no_captions`; to use a caption server, set both `IMMICH_MEMORIES_EDITORIAL__PREPARATION__TIER`
to `full` and `IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_BASE_URL` in `env`.

No ConfigMap by default. `immich_url` / `immich_api_key` (and `llm_api_key`, `musicgen_api_key`,
`secret_env`) land in the Secret and reach the pod through `envFrom`; every other setting is an
`IMMICH_MEMORIES_<SECTION>__<KEY>` env var (`env`). Probes: `/health/live` (liveness) and
`/health/ready` (readiness, `503` until config is present and Immich answers). Setting
`config_yaml` is the one exception: see [A maximalist setup](#a-maximalist-setup) below.

## Prerequisites

1. **Terraform** >= 1.0, `hashicorp/kubernetes` provider >= 2.20
2. **Kubernetes cluster** with a storage class for PVCs and Immich reachable from it
   (port 2283 by default). GPU only: NVIDIA GPU Operator + RuntimeClass `nvidia`
3. **kubeconfig** configured

## Quick Start

```bash
cd examples/basic            # CPU, no ingress, port-forward
# or: cd examples/production # pinned tag, basic auth, ingress + TLS, GPU optional
# or: cd examples/maximalist # every optional piece: render sidecar, CUDA captioner,
#                             OIDC, LAN LLM/ACE-Step, geocoding, cache caps

cp terraform.tfvars.example terraform.tfvars
vim terraform.tfvars

terraform init
terraform plan
terraform apply
$(terraform output -raw port_forward_command)   # http://localhost:8080
```

## A maximalist setup

`examples/maximalist` wires every optional variable in the table below at once. Walkthrough,
what runs where, and the two error strings OIDC fails with when a step is skipped:
[docs-site/docs/run/maximalist.md](../../docs-site/docs/run/maximalist.md). The
Kubernetes-manifests equivalent is `deploy/kubernetes/overlays/maximalist`; both express the same
features, so pick whichever tool manages the rest of your cluster.

Every variable behind this defaults to the minimal path: `render_worker_sidecar_enabled`,
`captioner_enabled`, `oidc_enabled`, `ace_step_enabled`, `network_geocoding`, `network_map_tiles`
and `secure_cookies` are all `false`, and `config_yaml` is `""`, until you set them.

## Module Usage

```hcl
module "immich_memories" {
  source = "path/to/deploy/terraform"

  # Required
  immich_url     = "https://photos.example.com"
  immich_api_key = var.immich_api_key

  # Optional: LLM clip content analysis (any OpenAI-compatible API)
  llm_base_url = "http://ollama.ollama.svc.cluster.local:11434/v1"
  llm_model    = "qwen2.5-vl"

  # Optional: anything else, e.g. the in-pod daily automation
  env = {
    IMMICH_MEMORIES_AUTOMATION__ENABLED  = "true"
    IMMICH_MEMORIES_AUTOMATION__DAILY_AT = "09:00"
  }

  # Optional: NVIDIA GPU nodes
  gpu_enabled = true

  # Storage
  output_storage_size = "100Gi"
  cache_storage_size  = "50Gi"

  # Ingress — enable auth first (secret_env = { IMMICH_MEMORIES_AUTH_USERNAME = ..., IMMICH_MEMORIES_AUTH_PASSWORD = ... })
  ingress_enabled = false
}
```

## Variables

### Required

| Name | Description | Type |
|------|-------------|------|
| `immich_url` | URL of your Immich instance | `string` |
| `immich_api_key` | Immich API key | `string` |

### Deployment

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `namespace` | Kubernetes namespace | `string` | `"immich-memories"` |
| `create_namespace` | Create the namespace | `bool` | `true` |
| `image_repository` | Container image | `string` | `"ghcr.io/sam-dumont/immich-video-memory-generator"` |
| `image_tag` | Image tag (no `v` prefix: `vX.Y.Z` ships as `X.Y.Z`, plus `latest`) | `string` | `"latest"` |
| `replicas` | Keep at 1 | `number` | `1` |
| `resources` | Requests/limits object | `object` | `2Gi/1000m` – `8Gi/4000m` |
| `tmp_size` | `/tmp` emptyDir (8Gi for 4K) | `string` | `"4Gi"` |
| `env` | Extra `IMMICH_MEMORIES_*` env vars | `map(string)` | `{}` |
| `secret_env` | Extra env vars stored in the Secret | `map(string)` | `{}` |
| `labels` | Extra labels on every resource | `map(string)` | `{}` |

### LLM and music

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `llm_base_url` | OpenAI-compatible endpoint; empty disables LLM analysis | `string` | `""` |
| `llm_model` | Vision model name | `string` | `""` |
| `llm_api_key` | API key (Secret) | `string` | `""` |
| `musicgen_enabled` | AI music via a MusicGen server | `bool` | `false` |
| `musicgen_base_url` | MusicGen server URL | `string` | in-cluster URL |
| `musicgen_api_key` | MusicGen API key (Secret) | `string` | `""` |
| `output_resolution` | `720p`, `1080p`, `4k` | `string` | `"1080p"` |

### GPU

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `gpu_enabled` | Schedule on NVIDIA GPU nodes | `bool` | `false` |
| `gpu_count` | GPUs to request | `number` | `1` |
| `gpu_node_selector` | Node selector | `map(string)` | `{"nvidia.com/gpu.present": "true"}` |
| `runtime_class_name` | RuntimeClass | `string` | `"nvidia"` |

### Storage

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `output_storage_size` | Output PVC | `string` | `"50Gi"` |
| `cache_storage_size` | Cache/state PVC | `string` | `"20Gi"` |
| `storage_class_name` | Storage class (`null` = cluster default) | `string` | `null` |

### Ingress

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `ingress_enabled` | Enable ingress | `bool` | `false` |
| `ingress_class_name` | Ingress class | `string` | `"nginx"` |
| `ingress_host` | Hostname | `string` | `"memories.example.com"` |
| `ingress_tls_enabled` | TLS | `bool` | `false` |
| `ingress_tls_secret_name` | TLS secret | `string` | `"immich-memories-tls"` |
| `ingress_annotations` | Annotations | `map(string)` | `{}` |

### Network and cache

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `network_geocoding` | Reverse geocode through nominatim.openstreetmap.org | `bool` | `false` |
| `network_map_tiles` | Fetch satellite tiles from server.arcgisonline.com | `bool` | `false` |
| `cache_video_max_size_gb` | `video_cache_max_size_gb` override; `null` keeps the app's 10 GB default | `number` | `null` |
| `cache_thumbnail_max_size_mb` | `thumbnail_cache_max_size_mb` override; `null` keeps the app's 10 GB default | `number` | `null` |

### ACE-Step music (API mode)

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `ace_step_enabled` | Enable ACE-Step music generation | `bool` | `false` |
| `ace_step_api_url` | ACE-Step API server URL (in-cluster or a LAN machine) | `string` | `"http://localhost:8000"` |
| `ace_step_api_key` | API key (Secret), if the server requires one | `string` | `""` |

### OIDC behind a reverse proxy

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `oidc_enabled` | Turn on OIDC/SSO instead of basic auth | `bool` | `false` |
| `oidc_issuer_url` | Issuer URL | `string` | `""` |
| `oidc_client_id` | Client ID | `string` | `""` |
| `oidc_client_secret` | Client secret (Secret); empty for a public client | `string` | `""` |
| `oidc_public_url` | The externally reachable URL users type | `string` | `""` |
| `oidc_trusted_proxies` | Addresses `X-Forwarded-*` is trusted from | `list(string)` | `[]` |
| `oidc_allowed_emails` | Email allow-list; empty admits anyone the IdP authenticates | `list(string)` | `[]` |
| `secure_cookies` | Mark the session cookie `Secure`; only once every visitor arrives over HTTPS | `bool` | `false` |

Both `oidc_public_url` and `oidc_trusted_proxies` are needed once `oidc_enabled` is true. Without
`oidc_public_url` the `redirect_uri` sent to the IdP is built from the in-cluster request and comes
out `http://`, which every IdP refuses. Without `oidc_trusted_proxies` naming the proxy,
`X-Forwarded-Proto` is not trusted and the callback fails with `400 {"detail": "Invalid callback
origin"}`.

### Render worker sidecar

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `render_worker_sidecar_enabled` | Run the render worker as a second container in this Deployment's own pod, on a GPU node | `bool` | `false` |
| `render_worker_token` | Bearer token both containers share (Secret) | `string` | `""` |

Implies GPU scheduling for the whole pod even when `gpu_enabled` is left `false`: the app container
itself needs no card, but the worker does.

### Caption server

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `captioner_enabled` | Deploy the SmolVLM2 caption server (a separate Deployment/Service/PVC) | `bool` | `false` |
| `captioner_cuda` | Run it on an NVIDIA card (`--n-gpu-layers 99`) | `bool` | `false` |
| `captioner_storage_size` | Size of the caption weights PVC | `string` | `"2Gi"` |

llama.cpp's CUDA build still runs on Pascal (`sm_61`), where PyTorch cu128 wheels have already
dropped that architecture.

### A declarative config.yaml

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `config_yaml` | Literal `config.yaml` content | `string` | `""` |

A ConfigMap volume mounts every key world-readable with no way to `chmod` it, which is exactly what
the app warns on at startup ("Config file ... is readable by other users"). Setting `config_yaml`
adds an `install-config` init container that copies it onto the writable cache PVC as the app's own
uid and `chmod 600`s it there, instead of mounting the ConfigMap directly at
`~/.immich-memories/config.yaml`.

## Outputs

`namespace`, `service_name`, `service_endpoint`, `ingress_host`, `deployment_name`,
`pvc_output`, `pvc_cache`, `port_forward_command`, `gpu_enabled`.

## Troubleshooting

```bash
# Pod events (scheduling, PVC binding, GPU)
kubectl describe pod -n immich-memories -l app.kubernetes.io/name=immich-memories
kubectl get pvc -n immich-memories

# Readiness: 503 until Immich answers
kubectl port-forward -n immich-memories svc/immich-memories 8080:80
curl -s localhost:8080/health/ready

# GPU: operator pods, node label, RuntimeClass
kubectl get pods -n gpu-operator
kubectl get nodes -L nvidia.com/gpu.present
kubectl get runtimeclass nvidia
```
