# Every optional piece this project ships, on one cluster: the render worker
# as a sidecar, a CUDA caption server, OIDC behind a reverse proxy, an LLM and
# ACE-Step on a LAN machine, geocoding and map tiles, and cache caps sized to
# the volume that holds them. Written up on docs-site/docs/run/reference-setup.md.
# The Kubernetes-manifests equivalent is deploy/kubernetes/overlays/maximalist.
#
# Most installs want a fraction of this. Start from examples/basic or
# examples/production and add one variable at a time instead of copying this
# file whole.

terraform {
  required_version = ">= 1.9"

  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.20"
    }
  }
}

provider "kubernetes" {
  config_path    = var.kubeconfig_path
  config_context = var.kubeconfig_context
}

module "immich_memories" {
  source = "../../"

  namespace        = var.namespace
  create_namespace = true

  image_repository = "ghcr.io/sam-dumont/immich-memories"
  image_tag        = var.image_tag

  immich_url     = var.immich_url
  immich_api_key = var.immich_api_key

  # An LLM and ACE-Step on another LAN machine, e.g. an Apple Silicon Mac
  # running an OpenAI-compatible server bound to 0.0.0.0.
  llm_base_url = var.lan_llm_base_url
  llm_model    = var.lan_llm_model

  ace_step_enabled = true
  ace_step_api_url = var.ace_step_api_url
  ace_step_api_key = var.ace_step_api_key

  # Geocoding and map tiles: place names, the trip fly-over, location cards.
  network_geocoding = true
  network_map_tiles = true

  # Below the app's own 10 GB default for each cap, well inside the module's
  # 20Gi cache claim. Raise both for a bigger library; past about 15 GB
  # together, grow cache_storage_size first (a bound claim never shrinks).
  cache_video_max_size_gb     = 5
  cache_thumbnail_max_size_mb = 3000

  # OIDC behind a TLS-terminating reverse proxy. Without oidc_public_url the
  # redirect_uri sent to the IdP comes out http://, which every IdP refuses;
  # without oidc_trusted_proxies the callback fails with 400 "Invalid
  # callback origin" (X-Forwarded-Proto is only trusted from these addresses).
  oidc_enabled         = true
  oidc_issuer_url      = var.oidc_issuer_url
  oidc_client_id       = var.oidc_client_id
  oidc_client_secret   = var.oidc_client_secret
  oidc_public_url      = var.oidc_public_url
  oidc_trusted_proxies = var.oidc_trusted_proxies
  oidc_allowed_emails  = var.oidc_allowed_emails
  secure_cookies       = true

  # The render worker as a second container in this Deployment's own pod,
  # on a GPU node, reachable over loopback without TLS.
  render_worker_sidecar_enabled = true
  render_worker_token           = var.render_worker_token

  # The caption server the full tier needs, on a card. llama.cpp's CUDA
  # build still runs on Pascal (sm_61), so an older card can carry it.
  captioner_enabled = true
  captioner_cuda    = true

  # The module sets IMMICH_MEMORIES_TIER=auto, which picks gpu or full only
  # once it finds GPU picture reading, and `env` is merged last, so this pins
  # the tier the captioner and the LLM are for. The module does not deploy
  # the inference service (encoder, heads, detectors on a GPU): apply
  # deploy/kubernetes/overlays/inference-cuda beside it, on the newer card,
  # and the app reads pictures there instead of on its CPU. Check what the
  # pod resolved with `immich-memories config show` (the tier row). Daily
  # automation inside the pod.
  env = {
    IMMICH_MEMORIES_TIER                      = "full"
    IMMICH_MEMORIES_INFERENCE__FACTS_BASE_URL = "http://inference:8092"
    IMMICH_MEMORIES_AUTOMATION__ENABLED       = "true"
    IMMICH_MEMORIES_AUTOMATION__DAILY_AT      = "09:00"
  }

  # Storage: the render worker's own scratch (20Gi) is a separate emptyDir,
  # not part of these PVCs.
  output_storage_size = "200Gi"
  storage_class_name  = var.storage_class_name

  labels = {
    "environment" = "maximalist"
  }
}

output "port_forward_command" {
  value = module.immich_memories.port_forward_command
}
