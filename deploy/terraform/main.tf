terraform {
  required_version = ">= 1.0"

  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.20"
    }
  }
}

locals {
  labels = merge({
    "app.kubernetes.io/name"       = "immich-memories"
    "app.kubernetes.io/component"  = "video-compiler"
    "app.kubernetes.io/managed-by" = "terraform"
  }, var.labels)

  # The image runs as `immich`, UID/GID 1000, HOME=/home/immich. The app writes
  # config.yaml, cache.db, the video cache and automation history under
  # ~/.immich-memories, so that directory is a writable PVC, not a ConfigMap.
  data_dir   = "/home/immich/.immich-memories"
  output_dir = "/app/output"
  models_dir = "/models"
  model_env = {
    IMMICH_MEMORIES_TRIAGE__ENCODER                            = "/models/triage/dinov2-small.onnx"
    IMMICH_MEMORIES_EDITORIAL__PREPARATION__MARQO_ONNX         = "/models/detectors/nsfw-marqo-384.onnx"
    IMMICH_MEMORIES_EDITORIAL__PREPARATION__DETECTOR_CACHE_DIR = "/models/huggingface"
    IMMICH_MEMORIES_FREE_TEXT__WORDNET                         = "/models/wordnet/wordnet.zip"
  }

  # Everything is configured through IMMICH_MEMORIES_<SECTION>__<KEY> env vars,
  # the same way docker-compose does it. Secrets live in the Secret (envFrom).
  env = merge(
    local.model_env,
    {
      IMMICH_MEMORIES_OUTPUT__DIRECTORY  = local.output_dir
      IMMICH_MEMORIES_OUTPUT__RESOLUTION = var.output_resolution
      IMMICH_MEMORIES_TIER               = "auto"
    },
    var.llm_base_url != "" ? {
      IMMICH_MEMORIES_LLM__BASE_URL = var.llm_base_url
      IMMICH_MEMORIES_LLM__MODEL    = var.llm_model
    } : {},
    var.musicgen_enabled ? {
      IMMICH_MEMORIES_MUSICGEN__ENABLED  = "true"
      IMMICH_MEMORIES_MUSICGEN__BASE_URL = var.musicgen_base_url
    } : {},
    var.gpu_enabled || var.render_worker_sidecar_enabled ? {
      NVIDIA_VISIBLE_DEVICES     = "all"
      NVIDIA_DRIVER_CAPABILITIES = "compute,video,utility"
    } : {},
    # The schema only matters once the store is on PostgreSQL; unset stays SQLite.
    var.database_url != "" ? {
      IMMICH_MEMORIES_DATABASE_SCHEMA = var.database_schema
    } : {},
    # Third-party hosts (config_models_network.py); both off by default.
    var.network_geocoding ? { IMMICH_MEMORIES_NETWORK__GEOCODING = "true" } : {},
    var.network_map_tiles ? { IMMICH_MEMORIES_NETWORK__MAP_TILES = "true" } : {},
    # Cache caps (config_models.py); null keeps the app's own 10 GB default.
    var.cache_video_max_size_gb != null ? {
      IMMICH_MEMORIES_CACHE__VIDEO_CACHE_MAX_SIZE_GB = tostring(var.cache_video_max_size_gb)
    } : {},
    var.cache_thumbnail_max_size_mb != null ? {
      IMMICH_MEMORIES_CACHE__THUMBNAIL_CACHE_MAX_SIZE_MB = tostring(var.cache_thumbnail_max_size_mb)
    } : {},
    # ACE-Step 1.5, API mode (config_models_soundtrack.py ACEStepConfig).
    var.ace_step_enabled ? {
      IMMICH_MEMORIES_ACE_STEP__ENABLED = "true"
      IMMICH_MEMORIES_ACE_STEP__MODE    = "api"
      IMMICH_MEMORIES_ACE_STEP__API_URL = var.ace_step_api_url
    } : {},
    # OIDC behind a reverse proxy (config_models_auth.py AuthConfig). List-valued
    # fields take JSON, the same as the environment-variables.md convention.
    var.oidc_enabled ? merge(
      {
        IMMICH_MEMORIES_AUTH__ENABLED         = "true"
        IMMICH_MEMORIES_AUTH__PROVIDER        = "oidc"
        IMMICH_MEMORIES_AUTH__ISSUER_URL      = var.oidc_issuer_url
        IMMICH_MEMORIES_AUTH__CLIENT_ID       = var.oidc_client_id
        IMMICH_MEMORIES_AUTH__PUBLIC_URL      = var.oidc_public_url
        IMMICH_MEMORIES_AUTH__TRUSTED_PROXIES = jsonencode(var.oidc_trusted_proxies)
      },
      length(var.oidc_allowed_emails) > 0 ? {
        IMMICH_MEMORIES_AUTH__ALLOWED_EMAILS = jsonencode(var.oidc_allowed_emails)
      } : {},
    ) : {},
    var.secure_cookies ? { IMMICH_MEMORIES_SERVER__SECURE_COOKIES = "true" } : {},
    var.captioner_enabled ? {
      IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_BASE_URL = "http://${local.captioner_service_name}:8092/v1"
    } : {},
    # The sidecar shares a network namespace with the app, so loopback needs
    # neither TLS nor render.allow_insecure_http (config_models_render.py).
    var.render_worker_sidecar_enabled ? {
      IMMICH_MEMORIES_RENDER__WORKER_BASE_URL = "http://127.0.0.1:8093"
    } : {},
    var.env,
  )

  secret_data = merge(
    {
      IMMICH_URL     = var.immich_url
      IMMICH_API_KEY = var.immich_api_key
    },
    var.llm_api_key != "" ? { IMMICH_MEMORIES_LLM__API_KEY = var.llm_api_key } : {},
    var.musicgen_api_key != "" ? { IMMICH_MEMORIES_MUSICGEN__API_KEY = var.musicgen_api_key } : {},
    var.database_url != "" ? { IMMICH_MEMORIES_DATABASE_URL = var.database_url } : {},
    var.ace_step_enabled && var.ace_step_api_key != "" ? {
      IMMICH_MEMORIES_ACE_STEP__API_KEY = var.ace_step_api_key
    } : {},
    var.oidc_enabled && var.oidc_client_secret != "" ? {
      IMMICH_MEMORIES_AUTH__CLIENT_SECRET = var.oidc_client_secret
    } : {},
    # envFrom on the app container turns this into IMMICH_MEMORIES_RENDER__WORKER_TOKEN
    # for free (render.worker_token). The render-worker container reads the same
    # value back under its own, differently-prefixed name via a secret_key_ref
    # instead, since it needs no other key from this Secret.
    var.render_worker_sidecar_enabled ? {
      IMMICH_MEMORIES_RENDER__WORKER_TOKEN = var.render_worker_token
    } : {},
    var.secret_env,
  )

  # Named once so the app's own env (caption_base_url above) and the Service
  # resource in captioner.tf cannot drift apart.
  captioner_service_name = "immich-memories-captioner"
}

# Namespace
resource "kubernetes_namespace_v1" "this" {
  count = var.create_namespace ? 1 : 0

  metadata {
    name   = var.namespace
    labels = local.labels
  }
}

# Secret
resource "kubernetes_secret_v1" "this" {
  metadata {
    name      = "immich-memories-secrets"
    namespace = var.namespace
    labels    = local.labels
  }

  data = local.secret_data
  type = "Opaque"

  depends_on = [kubernetes_namespace_v1.this]
}

# Output PVC (generated videos)
resource "kubernetes_persistent_volume_claim_v1" "output" {
  metadata {
    name      = "immich-memories-output"
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = var.storage_class_name

    resources {
      requests = {
        storage = var.output_storage_size
      }
    }
  }

  # WaitForFirstConsumer storage classes never bind before a pod mounts the PVC.
  wait_until_bound = false

  depends_on = [kubernetes_namespace_v1.this]
}

# Cache/state PVC (config.yaml, cache.db, video cache, automation history)
resource "kubernetes_persistent_volume_claim_v1" "cache" {
  metadata {
    name      = "immich-memories-cache"
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = var.storage_class_name

    resources {
      requests = {
        storage = var.cache_storage_size
      }
    }
  }

  wait_until_bound = false

  depends_on = [kubernetes_namespace_v1.this]
}

resource "kubernetes_persistent_volume_claim_v1" "models" {
  metadata {
    name      = "immich-memories-models"
    namespace = var.namespace
    labels    = local.labels
  }
  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = var.storage_class_name
    resources {
      requests = { storage = var.models_storage_size }
    }
  }
  wait_until_bound = false
  depends_on       = [kubernetes_namespace_v1.this]
}

# Deployment
resource "kubernetes_deployment_v1" "this" {
  metadata {
    name      = "immich-memories"
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    # Single-user, single-replica: workflow state lives in-process.
    replicas = var.replicas

    strategy {
      type = "Recreate" # all PVCs are ReadWriteOnce
    }

    selector {
      match_labels = {
        "app.kubernetes.io/name" = "immich-memories"
      }
    }

    template {
      metadata {
        labels = local.labels
      }

      spec {
        # The sidecar needs the GPU node even when gpu_enabled (NVENC for the
        # app itself) is left false.
        runtime_class_name = var.gpu_enabled || var.render_worker_sidecar_enabled ? var.runtime_class_name : null
        node_selector      = var.gpu_enabled || var.render_worker_sidecar_enabled ? var.gpu_node_selector : null

        # A Service named "immich-memories" otherwise injects
        # IMMICH_MEMORIES_SERVICE_HOST/PORT into a pod reading
        # IMMICH_MEMORIES_* itself (#1608).
        enable_service_links            = false
        automount_service_account_token = false

        security_context {
          run_as_non_root = true
          run_as_user     = 1000
          run_as_group    = 1000
          fs_group        = 1000

          seccomp_profile {
            type = "RuntimeDefault"
          }
        }

        init_container {
          name    = "fetch-models"
          image   = "${var.image_repository}:${var.image_tag}"
          command = ["/bin/sh", "-c", "test -s /models/triage/dinov2-small.onnx && test -s /models/detectors/nsfw-marqo-384.onnx && test -d /models/huggingface && test -s /models/wordnet/wordnet.zip || immich-memories models fetch"]
          security_context {
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities { drop = ["ALL"] }
          }
          dynamic "env" {
            for_each = local.env
            content {
              name  = env.key
              value = env.value
            }
          }
          volume_mount {
            name       = "data"
            mount_path = local.data_dir
          }
          volume_mount {
            name       = "models"
            mount_path = local.models_dir
          }
          volume_mount {
            name       = "tmp"
            mount_path = "/tmp"
          }
        }

        # A ConfigMap volume's files belong to root, readable by the app's uid
        # only through group or world bits, which is exactly what
        # config_loader.py warns on ("Config file ... is readable by other
        # users"). This copies it onto the
        # writable cache PVC as the app's own uid instead, and chmods it
        # there. Only present when var.config_yaml is set: the default path
        # stays env-var only, like the rest of this module.
        dynamic "init_container" {
          for_each = var.config_yaml != "" ? [1] : []
          content {
            name    = "install-config"
            image   = "${var.image_repository}:${var.image_tag}"
            command = ["/bin/sh", "-c", "cp /config-src/config.yaml ${local.data_dir}/config.yaml && chmod 600 ${local.data_dir}/config.yaml"]
            security_context {
              run_as_user                = 1000
              run_as_group               = 1000
              allow_privilege_escalation = false
              read_only_root_filesystem  = true
              capabilities { drop = ["ALL"] }
            }
            volume_mount {
              name       = "config-src"
              mount_path = "/config-src"
              read_only  = true
            }
            volume_mount {
              name       = "data"
              mount_path = local.data_dir
            }
          }
        }

        container {
          name              = "immich-memories"
          image             = "${var.image_repository}:${var.image_tag}"
          image_pull_policy = "Always"

          security_context {
            allow_privilege_escalation = false
            # Sessions now live on the data volume, but ~/.cache still needs
            # a writable mount before this can flip to true (#445).
            read_only_root_filesystem = true

            capabilities {
              drop = ["ALL"]
            }
          }

          port {
            name           = "http"
            container_port = 8080
            protocol       = "TCP"
          }

          env_from {
            secret_ref {
              name = kubernetes_secret_v1.this.metadata[0].name
            }
          }

          dynamic "env" {
            for_each = local.env
            content {
              name  = env.key
              value = env.value
            }
          }

          resources {
            requests = merge(
              {
                memory = var.resources.requests.memory
                cpu    = var.resources.requests.cpu
              },
              var.gpu_enabled ? { "nvidia.com/gpu" = tostring(var.gpu_count) } : {}
            )
            limits = merge(
              {
                memory = var.resources.limits.memory
                cpu    = var.resources.limits.cpu
              },
              var.gpu_enabled ? { "nvidia.com/gpu" = tostring(var.gpu_count) } : {}
            )
          }

          volume_mount {
            name       = "data"
            mount_path = local.data_dir
          }

          volume_mount {
            name       = "output"
            mount_path = local.output_dir
          }

          volume_mount {
            name       = "models"
            mount_path = local.models_dir
          }

          volume_mount {
            name       = "tmp"
            mount_path = "/tmp"
          }

          # /health/live only says the process is up.
          liveness_probe {
            http_get {
              path = "/health/live"
              port = "http"
            }
            initial_delay_seconds = 15
            period_seconds        = 10
            timeout_seconds       = 5
            failure_threshold     = 3
          }

          # /health/ready is 503 until config is present and Immich answers.
          readiness_probe {
            http_get {
              path = "/health/ready"
              port = "http"
            }
            initial_delay_seconds = 10
            period_seconds        = 15
            timeout_seconds       = 5
            failure_threshold     = 3
          }
        }

        # The render worker as a second container in this same pod, sharing
        # its network namespace (see IMMICH_MEMORIES_RENDER__WORKER_BASE_URL
        # above). Mirrors deploy/kubernetes/overlays/render-sidecar.
        dynamic "container" {
          for_each = var.render_worker_sidecar_enabled ? [1] : []
          content {
            name    = "render-worker"
            image   = "${var.image_repository}:${var.image_tag}"
            command = ["python", "-m", "immich_memories_render_worker"]

            security_context {
              allow_privilege_escalation = false
              read_only_root_filesystem  = true
              capabilities { drop = ["ALL"] }
            }

            port {
              name           = "worker-http"
              container_port = 8093
            }

            env {
              name  = "IMMICH_MEMORIES_RENDER_WORKER_HOST"
              value = "127.0.0.1" # loopback only: the app is the only caller
            }
            env {
              name  = "IMMICH_MEMORIES_RENDER_WORKER_DIRECTORY"
              value = "/app/render-worker-output"
            }
            env {
              name = "IMMICH_MEMORIES_RENDER_WORKER_TOKEN"
              value_from {
                secret_key_ref {
                  name = kubernetes_secret_v1.this.metadata[0].name
                  key  = "IMMICH_MEMORIES_RENDER__WORKER_TOKEN"
                }
              }
            }
            env {
              name = "IMMICH_MEMORIES_RENDER_WORKER_IMMICH_URL"
              value_from {
                secret_key_ref {
                  name = kubernetes_secret_v1.this.metadata[0].name
                  key  = "IMMICH_URL"
                }
              }
            }
            env {
              name  = "NVIDIA_DRIVER_CAPABILITIES"
              value = "compute,video,utility"
            }

            resources {
              requests = { cpu = "500m", memory = "1Gi" }
              limits   = { cpu = "2", memory = "4Gi", "nvidia.com/gpu" = "1" }
            }

            # tcpSocket/httpGet both dial the pod IP, never 127.0.0.1: the
            # kubelet makes that call, not a process inside the container.
            # This worker binds loopback only, so either kind of probe fails
            # forever and the pod never goes Ready. exec runs inside the
            # worker's own network namespace instead.
            startup_probe {
              exec {
                command = ["python3", "-c", "import os, sys, urllib.request; req = urllib.request.Request('http://127.0.0.1:8093/health', headers={'Authorization': f\"Bearer {os.environ['IMMICH_MEMORIES_RENDER_WORKER_TOKEN']}\"}); sys.exit(0 if urllib.request.urlopen(req, timeout=3).status == 200 else 1)"]
              }
              period_seconds    = 5
              timeout_seconds   = 5
              failure_threshold = 36
            }
            readiness_probe {
              exec {
                command = ["python3", "-c", "import os, sys, urllib.request; req = urllib.request.Request('http://127.0.0.1:8093/health', headers={'Authorization': f\"Bearer {os.environ['IMMICH_MEMORIES_RENDER_WORKER_TOKEN']}\"}); sys.exit(0 if urllib.request.urlopen(req, timeout=3).status == 200 else 1)"]
              }
              period_seconds  = 10
              timeout_seconds = 5
            }

            volume_mount {
              name       = "worker-scratch"
              mount_path = "/app/render-worker-output"
            }
            volume_mount {
              name       = "worker-tmp"
              mount_path = "/tmp"
            }
            volume_mount {
              name       = "worker-state"
              mount_path = local.data_dir
            }
            volume_mount {
              name       = "worker-cache"
              mount_path = "/home/immich/.cache"
            }
          }
        }

        volume {
          name = "data"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim_v1.cache.metadata[0].name
          }
        }

        volume {
          name = "output"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim_v1.output.metadata[0].name
          }
        }

        # FFmpeg intermediates: 2Gi is enough for 1080p, use 8Gi for 4K.
        volume {
          name = "models"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim_v1.models.metadata[0].name
          }
        }

        volume {
          name = "tmp"
          empty_dir {
            size_limit = var.tmp_size
          }
        }

        dynamic "volume" {
          for_each = var.config_yaml != "" ? [1] : []
          content {
            name = "config-src"
            config_map {
              name = kubernetes_config_map_v1.config[0].metadata[0].name
            }
          }
        }

        # Its own scratch, matching deploy/kubernetes/overlays/render-sidecar,
        # distinctly named so it does not collide with the app container's own
        # volumes of the same purpose.
        dynamic "volume" {
          for_each = var.render_worker_sidecar_enabled ? {
            worker-scratch = "20Gi"
            worker-tmp     = "4Gi"
            worker-state   = "256Mi"
            worker-cache   = "1Gi"
          } : {}
          content {
            name = volume.key
            empty_dir {
              size_limit = volume.value
            }
          }
        }

        dynamic "toleration" {
          for_each = var.gpu_enabled || var.render_worker_sidecar_enabled ? [1] : []
          content {
            key      = "nvidia.com/gpu"
            operator = "Exists"
            effect   = "NoSchedule"
          }
        }
      }
    }
  }

  depends_on = [
    kubernetes_namespace_v1.this,
    kubernetes_secret_v1.this,
    kubernetes_persistent_volume_claim_v1.output,
    kubernetes_persistent_volume_claim_v1.cache,
    kubernetes_persistent_volume_claim_v1.models,
  ]
}

# Service
resource "kubernetes_service_v1" "this" {
  metadata {
    name      = "immich-memories"
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    type = "ClusterIP"

    port {
      name        = "http"
      port        = 80
      target_port = "http"
      protocol    = "TCP"
    }

    selector = {
      "app.kubernetes.io/name" = "immich-memories"
    }
  }

  depends_on = [kubernetes_namespace_v1.this]
}

# Ingress (optional). Authentication is disabled by default: enable it before
# turning this on.
resource "kubernetes_ingress_v1" "this" {
  count = var.ingress_enabled ? 1 : 0

  metadata {
    name        = "immich-memories"
    namespace   = var.namespace
    labels      = local.labels
    annotations = var.ingress_annotations
  }

  spec {
    ingress_class_name = var.ingress_class_name

    rule {
      host = var.ingress_host

      http {
        path {
          path      = "/"
          path_type = "Prefix"

          backend {
            service {
              name = kubernetes_service_v1.this.metadata[0].name
              port {
                name = "http"
              }
            }
          }
        }
      }
    }

    dynamic "tls" {
      for_each = var.ingress_tls_enabled ? [1] : []
      content {
        hosts       = [var.ingress_host]
        secret_name = var.ingress_tls_secret_name
      }
    }
  }

  depends_on = [kubernetes_service_v1.this]
}
