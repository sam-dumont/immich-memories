variable "namespace" {
  description = "Kubernetes namespace for immich-memories"
  type        = string
  default     = "immich-memories"
}

variable "create_namespace" {
  description = "Whether to create the namespace"
  type        = bool
  default     = true
}

variable "image_repository" {
  description = "Container image repository"
  type        = string
  default     = "ghcr.io/sam-dumont/immich-video-memory-generator"
}

variable "image_tag" {
  description = "Container image tag. Published tags carry no `v` prefix: `vX.Y.Z` ships as `X.Y.Z`, plus `latest`"
  type        = string
  default     = "latest"
}

variable "replicas" {
  description = "Replica count. Keep at 1: the UI is single-user and keeps workflow state in-process"
  type        = number
  default     = 1
}

# Immich
variable "immich_url" {
  description = "URL of your Immich instance (in-cluster: http://immich-server.<ns>.svc.cluster.local:2283)"
  type        = string
}

variable "immich_api_key" {
  description = "Immich API key"
  type        = string
  sensitive   = true
}

# Optional text reader (OpenAI-compatible API; explicitly enable it in env)
variable "llm_base_url" {
  description = "Optional text reader endpoint, e.g. http://ollama.ollama.svc.cluster.local:11434/v1. Enable with IMMICH_MEMORIES_LLM__ENABLED in env"
  type        = string
  default     = ""
}

variable "llm_model" {
  description = "Text reader model name served at llm_base_url"
  type        = string
  default     = ""
}

variable "llm_api_key" {
  description = "API key for llm_base_url (stored in the Secret)"
  type        = string
  default     = ""
  sensitive   = true
}

# MusicGen (optional)
variable "musicgen_enabled" {
  description = "Enable AI music generation using a MusicGen API server"
  type        = bool
  default     = false
}

variable "musicgen_base_url" {
  description = "MusicGen API server URL"
  type        = string
  default     = "http://musicgen.musicgen.svc.cluster.local:8000"
}

variable "musicgen_api_key" {
  description = "MusicGen API key (stored in the Secret)"
  type        = string
  default     = ""
  sensitive   = true
}

# The store (optional; empty means the default SQLite file on the cache PVC)
variable "database_url" {
  description = "PostgreSQL URL for the store (postgresql+psycopg://user:pass@host:5432/db). Empty keeps the default SQLite file on the cache PVC"
  type        = string
  default     = ""
  sensitive   = true
}

variable "database_schema" {
  description = "Schema name for the store, PostgreSQL only. Only matters when database_url points at a database shared with something else, e.g. Immich's own"
  type        = string
  default     = "immich_memories"
}

# Any other setting: IMMICH_MEMORIES_<SECTION>__<KEY>
variable "env" {
  description = "Extra environment variables, e.g. { IMMICH_MEMORIES_AUTOMATION__ENABLED = \"true\" }"
  type        = map(string)
  default     = {}
}

variable "secret_env" {
  description = "Extra environment variables stored in the Secret, e.g. IMMICH_MEMORIES_AUTH_PASSWORD"
  type        = map(string)
  default     = {}
  sensitive   = true
}

# GPU (optional; the base deployment runs on CPU-only clusters)
variable "gpu_enabled" {
  description = "Schedule on NVIDIA GPU nodes (GPU Operator required)"
  type        = bool
  default     = false
}

variable "gpu_count" {
  description = "Number of GPUs to request"
  type        = number
  default     = 1
}

variable "gpu_node_selector" {
  description = "Node selector for GPU nodes"
  type        = map(string)
  default = {
    "nvidia.com/gpu.present" = "true"
  }
}

variable "runtime_class_name" {
  description = "RuntimeClass for NVIDIA GPU"
  type        = string
  default     = "nvidia"
}

# Resources
variable "resources" {
  description = "Resource requests and limits (idle ~100 MB; analysis 2-4 GB; FFmpeg assembly 4-8 GB)"
  type = object({
    requests = object({
      memory = string
      cpu    = string
    })
    limits = object({
      memory = string
      cpu    = string
    })
  })
  default = {
    requests = {
      memory = "2Gi"
      cpu    = "1000m"
    }
    limits = {
      memory = "8Gi"
      cpu    = "4000m"
    }
  }
}

variable "tmp_size" {
  description = "emptyDir size for /tmp (FFmpeg intermediates): 2Gi is enough for 1080p, 8Gi for 4K"
  type        = string
  default     = "4Gi"
}

# Storage
variable "output_storage_size" {
  description = "Size of the output PVC (generated videos, /app/output)"
  type        = string
  default     = "50Gi"
}

variable "cache_storage_size" {
  description = "Size of the cache/state PVC (/home/immich/.immich-memories: config, cache.db, video cache)"
  type        = string
  default     = "30Gi"
}

variable "storage_class_name" {
  description = "Storage class for PVCs (null for the cluster default)"
  type        = string
  default     = null
}

variable "models_storage_size" {
  description = "Size of the pinned-model PVC (/models)"
  type        = string
  default     = "10Gi"
}

# Ingress. Authentication is disabled by default: enable it before turning this on.
variable "ingress_enabled" {
  description = "Enable ingress"
  type        = bool
  default     = false
}

variable "ingress_class_name" {
  description = "Ingress class name"
  type        = string
  default     = "nginx"
}

variable "ingress_host" {
  description = "Ingress hostname"
  type        = string
  default     = "memories.example.com"
}

variable "ingress_tls_enabled" {
  description = "Enable TLS for ingress"
  type        = bool
  default     = false
}

variable "ingress_tls_secret_name" {
  description = "TLS secret name for ingress"
  type        = string
  default     = "immich-memories-tls"
}

variable "ingress_annotations" {
  description = "Additional ingress annotations"
  type        = map(string)
  default     = {}
}

# Application
variable "output_resolution" {
  description = "Output video resolution (720p, 1080p, 4k)"
  type        = string
  default     = "1080p"
}

variable "labels" {
  description = "Additional labels to apply to all resources"
  type        = map(string)
  default     = {}
}

# Third-party hosts (config_models_network.py). Off by default: a default run
# reaches Immich, the endpoints named in `env`, and nothing else.
variable "network_geocoding" {
  description = "Reverse geocode through nominatim.openstreetmap.org: trip names, place names"
  type        = bool
  default     = false
}

variable "network_map_tiles" {
  description = "Fetch satellite tiles from server.arcgisonline.com: the trip fly-over, location cards"
  type        = bool
  default     = false
}

# Cache caps (config_models.py CacheConfig). Both already default to 10 GB
# inside the app; these only override that default. Raising them without
# raising cache_storage_size just means the cache evicts what the higher cap
# was meant to keep.
variable "cache_video_max_size_gb" {
  description = "video_cache_max_size_gb override. null keeps the app's own 10 GB default"
  type        = number
  default     = null
}

variable "cache_thumbnail_max_size_mb" {
  description = "thumbnail_cache_max_size_mb override. null keeps the app's own 10 GB default"
  type        = number
  default     = null
}

# ACE-Step 1.5 music, API mode (config_models_soundtrack.py ACEStepConfig).
# Points at an ACE-Step API server (acestep-api: /release_task,
# /query_result), in-cluster or on a LAN machine (MLX/MPS on a Mac).
variable "ace_step_enabled" {
  description = "Enable ACE-Step music generation"
  type        = bool
  default     = false
}

variable "ace_step_api_url" {
  description = "ACE-Step API server URL. The XL variant wants >=12 GB VRAM upstream"
  type        = string
  default     = "http://localhost:8000"
}

variable "ace_step_api_key" {
  description = "ACE-Step API key (Secret), if the server requires one"
  type        = string
  default     = ""
  sensitive   = true
}

# OIDC behind a TLS-terminating reverse proxy (config_models_auth.py AuthConfig).
# Both oidc_public_url and oidc_trusted_proxies are required once oidc_enabled
# is true: without public_url the redirect_uri sent to the IdP is built from
# the in-cluster request and comes out http://, which every IdP refuses;
# without trusted_proxies naming the proxy, X-Forwarded-Proto is not trusted
# and the callback fails with 400 "Invalid callback origin".
variable "oidc_enabled" {
  description = "Turn on OIDC/SSO instead of basic auth"
  type        = bool
  default     = false
}

variable "oidc_issuer_url" {
  description = "OIDC issuer, e.g. https://idp.example.com/realms/family"
  type        = string
  default     = ""
}

variable "oidc_client_id" {
  description = "OIDC client ID"
  type        = string
  default     = ""
}

variable "oidc_client_secret" {
  description = "OIDC client secret (Secret); empty for a public client"
  type        = string
  default     = ""
  sensitive   = true
}

variable "oidc_public_url" {
  description = "The externally reachable URL users type, e.g. https://memories.example.com"
  type        = string
  default     = ""
}

variable "oidc_trusted_proxies" {
  description = "Addresses X-Forwarded-* is trusted from: the proxy's own address, or the cluster's pod CIDR (IPv4 and IPv6)"
  type        = list(string)
  default     = []
}

variable "oidc_allowed_emails" {
  description = "Email allow-list. Empty means anyone the IdP authenticates is admitted"
  type        = list(string)
  default     = []
}

variable "secure_cookies" {
  description = "Mark the session cookie Secure. Only correct once every visitor arrives over HTTPS"
  type        = bool
  default     = false
}

# The render worker as a sidecar in this Deployment's own pod, rather than a
# separate Deployment (see docs-site/docs/run/kubernetes.md#render-worker-as-a-sidecar).
# The app refuses a cleartext-HTTP render.worker_base_url to any host but
# loopback, since the request carries the Immich API key; sharing a pod
# reaches the worker at 127.0.0.1 with neither TLS nor
# render.allow_insecure_http needed. Implies GPU scheduling for the whole
# pod even when gpu_enabled is left false, since the app container itself
# needs no card but the worker does.
variable "render_worker_sidecar_enabled" {
  description = "Run the render worker as a second container in the app's own pod, on a GPU node"
  type        = bool
  default     = false
}

variable "render_worker_token" {
  description = "Required when the render worker sidecar is enabled: 32+ random characters shared by both containers (Secret)"
  type        = string
  default     = ""
  sensitive   = true

  validation {
    condition = !var.render_worker_sidecar_enabled || (
      length(trimspace(var.render_worker_token)) >= 32 &&
      !can(regex("change-me|changeme|secret|password|example", lower(var.render_worker_token)))
    )
    error_message = "When render_worker_sidecar_enabled is true, render_worker_token must contain 32+ random characters and no placeholder words. Generate one with openssl rand -hex 32."
  }
}

# A declarative config.yaml (config_loader.py). A ConfigMap volume mounts
# files owned by root, readable by the app's uid only through group or world
# bits, which is exactly what the app warns on ("Config file ... is readable by other users"); when this is
# set, an init container copies it onto the writable cache PVC as the app's
# own uid and chmods it 600 there, instead of mounting the ConfigMap directly
# at ~/.immich-memories/config.yaml.
variable "config_yaml" {
  description = "Literal config.yaml content. Empty (the default) ships no ConfigMap at all: every setting stays an env var, as in the base module"
  type        = string
  default     = ""
}

# The caption server the gpu and full tiers need (see docs-site/docs/better/captions.md).
# A separate Deployment/Service/PVC, gated by captioner_enabled, on its own
# because a fresh cluster can run it alone with no Immich credential at all.
variable "captioner_enabled" {
  description = "Deploy the SmolVLM2 caption server (llama.cpp, alias smolvlm2-500m-base-public)"
  type        = bool
  default     = false
}

variable "captioner_cuda" {
  description = "Run the caption server on an NVIDIA card (server-cuda image, --n-gpu-layers 99). llama.cpp's CUDA build still runs on Pascal (sm_61), where PyTorch cu128 wheels have already dropped that architecture"
  type        = bool
  default     = false
}

variable "captioner_storage_size" {
  description = "Size of the caption weights PVC (the two GGUF files: 437 MB + 109 MB)"
  type        = string
  default     = "2Gi"
}
