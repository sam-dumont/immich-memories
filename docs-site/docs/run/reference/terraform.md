---
title: "Terraform module reference"
---

# Terraform module reference

## Module usage

First [vendor the pinned release bundle](../gitops.md) at `vendor/immich-memories`.

```hcl
module "immich_memories" {
  source = "./vendor/immich-memories/deploy/terraform"

  # Required
  immich_url     = "https://photos.example.com"
  immich_api_key = var.immich_api_key

  # The reader, a separate deployment. It reads text only and must hold 32k of context; `llm_model`
  # is the tag that server reports at /v1/models.
  llm_base_url = "http://your-model-host:8000/v1"
  llm_model    = "gemma-4-e4b-it-6bit"

  # Optional: the in-pod daily run, NVIDIA nodes, bigger claims
  env = {
    IMMICH_MEMORIES_LLM__ENABLED         = "true"
    IMMICH_MEMORIES_AUTOMATION__ENABLED  = "true"
    IMMICH_MEMORIES_AUTOMATION__DAILY_AT = "09:00"
  }
  gpu_enabled         = true
  output_storage_size = "100Gi"
  cache_storage_size  = "50Gi"
}
```

Which model to serve at `llm_base_url` is on [Readers](../../better/reader.md). Preparation goes through the
same `env` map: [Inference on a GPU box](../../better/inference.md) and [Add captions](../../better/captions.md).
So do the [render worker](../../better/gpu-render.md) and ACE-Step
([Generated music](../../better/music.md)); MusicGen has its own `musicgen_*` variables. The module can deploy a caption service or render sidecar through explicit inputs; other endpoints are existing services.

`gpu_enabled` schedules on an NVIDIA node for NVENC and the title kernels
([Hardware encoding](.././hardware.md#nvidia)). Intel Quick Sync and AMD VA-API need `/dev/dri` in the
pod, which the module does not map: those encode on the CPU here.

Setting `database_url` moves the store off the default SQLite file onto PostgreSQL. The four
modes, and the SQL for a dedicated schema in Immich's own database, are on
[Database and the store](.././database.md).


## Variables

`immich_url` and `immich_api_key` are required. Everything else has a default:

| Name | Description | Default |
|------|-------------|---------|
| `namespace`, `create_namespace` | Kubernetes namespace, and whether to create it | `"immich-memories"`, `true` |
| `image_repository`, `image_tag` | Container image. No `v` prefix, so release `vX.Y.Z` is tag `X.Y.Z` | `ghcr.io/sam-dumont/immich-memories`, `"latest"` |
| `replicas` | Keep at 1; the UI is single-replica | `1` |
| `resources` | Requests/limits object (`requests.memory/cpu`, `limits.memory/cpu`) | `2Gi/1000m` to `8Gi/4000m` |
| `tmp_size` | `/tmp` emptyDir for FFmpeg intermediates (8Gi for 4K) | `"4Gi"` |
| `env`, `secret_env` | Extra env vars, the second stored in the Secret | `{}` |
| `labels` | Extra labels on every resource | `{}` |
| `gpu_enabled`, `gpu_count` | Schedule on NVIDIA GPU nodes: RuntimeClass, `nvidia.com/gpu`, node selector, toleration, `NVIDIA_*` env | `false`, `1` |
| `gpu_node_selector`, `runtime_class_name` | how GPU nodes are found | `{"nvidia.com/gpu.present": "true"}`, `"nvidia"` |
| `output_storage_size`, `cache_storage_size` | PVC sizes | `"50Gi"`, `"30Gi"` |
| `models_storage_size` | Models PVC size (the Kubernetes manifests ship `5Gi`) | `"10Gi"` |
| `storage_class_name` | Storage class for all three PVCs | `null` (cluster default) |
| `ingress_enabled`, `ingress_class_name`, `ingress_host` | Ingress, off by default | `false`, `"nginx"`, `"memories.example.com"` |
| `ingress_tls_enabled`, `ingress_tls_secret_name`, `ingress_annotations` | TLS and extras for it | `false`, `"immich-memories-tls"`, `{}` |
| `llm_base_url`, `llm_model`, `llm_api_key` | Optional text reader (Ollama: append `/v1`). URL and model do not enable it; set `IMMICH_MEMORIES_LLM__ENABLED = "true"` in `env` | `""` |
| `musicgen_enabled`, `musicgen_base_url`, `musicgen_api_key` | AI music through a MusicGen server | `false`, the in-cluster service, `""` |
| `database_url`, `database_schema` | The store on PostgreSQL instead of the default SQLite file. Empty stays SQLite | `""`, `"immich_memories"` |
| `output_resolution` | `720p`, `1080p` or `4k` | `"1080p"` |

For a local-network reader, set `IMMICH_MEMORIES_LLM__ENABLED = "true"` in `env` and provide
an external server. The app image does not include llama-server. Follow [reader setup](../../better/reader.md#let-the-app-run-the-local-model).

`terraform output` gives the namespace, service name and endpoint, the ingress host, the deployment
and PVC names, whether GPU is on, and a ready-to-run `port_forward_command`.


## Troubleshooting

```bash
# Pod events: scheduling, PVC binding, GPU
kubectl describe pod -n immich-memories -l app.kubernetes.io/name=immich-memories
kubectl get pvc -n immich-memories

# Readiness stays 503 until Immich answers: check the payload
kubectl port-forward -n immich-memories svc/immich-memories 8080:80
curl -s localhost:8080/health/ready

# GPU: operator pods, node label, RuntimeClass
kubectl get pods -n gpu-operator
kubectl get nodes -L nvidia.com/gpu.present
kubectl get runtimeclass nvidia
```

A Pending pod is usually a storage class that does not exist, resource requests the cluster cannot
meet, or `gpu_enabled = true` without GPU nodes.


## Additional supported inputs

| Input | What it controls |
|---|---|
| `config_yaml` | Optional ConfigMap and init container to install a declarative config file |
| `render_worker_sidecar_enabled`, `render_worker_token` | Worker sidecar; a token is required when enabled (32+ random characters, no placeholder words). Generate with `openssl rand -hex 32`; empty is accepted only with the sidecar off |
| `captioner_enabled`, `captioner_cuda`, `captioner_storage_size` | Caption service deployment |
| `oidc_*`, `secure_cookies` | SSO and HTTPS session settings |
| `network_geocoding`, `network_map_tiles` | Optional outside map calls |
| `ace_step_enabled`, `ace_step_api_url`, `ace_step_api_key` | Existing music API integration |
| `cache_video_max_size_gb`, `cache_thumbnail_max_size_mb` | Cache limits |

The exact types and defaults are in
[variables.tf](https://github.com/sam-dumont/immich-memories/blob/main/deploy/terraform/variables.tf).
The module does not deploy an inference or reader server. A caption service and render sidecar are
available through the explicit inputs above; the app's `gpu_enabled` only schedules encoding/title GPU use.

## Persistent mount and probes

The data PVC mounts at `/home/immich/.immich-memories`; output at `/app/output`, models at `/models`.
The module probes `/health/live` and `/health/ready`, just like the Kustomize base. Terraform waits for rollout completion: an app pod must become Ready before apply succeeds. `/health/ready` requires configuration and a reachable Immich server. Check pod events and logs when apply waits or times out.
