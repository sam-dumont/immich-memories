# The caption server the gpu and full tiers need (docs-site/docs/better/captions.md):
# llama.cpp serving the pinned SmolVLM2-500M GGUF under the alias the app
# demands. Gated by var.captioner_enabled and entirely separate from
# kubernetes_deployment_v1.this: it holds no Immich credential and never
# talks to Immich, so it can be created (or torn down) on its own.
#
# Mirrors deploy/kubernetes/overlays/captioner and overlays/captioner-cuda:
# same weights, same alias, same port; var.captioner_cuda only changes the
# image tag and adds --n-gpu-layers 99.

resource "kubernetes_persistent_volume_claim_v1" "captioner" {
  count = var.captioner_enabled ? 1 : 0

  metadata {
    name      = "immich-memories-caption-models"
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = var.storage_class_name
    resources {
      requests = { storage = var.captioner_storage_size }
    }
  }

  wait_until_bound = false
  depends_on       = [kubernetes_namespace_v1.this]
}

resource "kubernetes_deployment_v1" "captioner" {
  count = var.captioner_enabled ? 1 : 0

  metadata {
    name      = "immich-memories-captioner"
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    replicas = 1
    strategy { type = "Recreate" }

    selector {
      match_labels = { "app.kubernetes.io/name" = "immich-memories-captioner" }
    }

    template {
      metadata {
        labels = { "app.kubernetes.io/name" = "immich-memories-captioner" }
      }

      spec {
        enable_service_links            = false
        automount_service_account_token = false

        security_context {
          run_as_non_root        = true
          run_as_user            = 1000
          run_as_group           = 1000
          fs_group               = 1000
          fs_group_change_policy = "OnRootMismatch"
          seccomp_profile { type = "RuntimeDefault" }
        }

        runtime_class_name = var.captioner_cuda ? var.runtime_class_name : null
        node_selector      = var.captioner_cuda ? var.gpu_node_selector : null

        dynamic "toleration" {
          for_each = var.captioner_cuda ? [1] : []
          content {
            key      = "nvidia.com/gpu"
            operator = "Exists"
            effect   = "NoSchedule"
          }
        }

        # Pinned to one revision of ggml-org/SmolVLM2-500M-Video-Instruct-GGUF
        # and checked by digest, because llama-server serves whatever file is
        # at the path. Re-running this is cheap: the digest check short-circuits.
        init_container {
          name    = "fetch-weights"
          image   = "ghcr.io/ggml-org/llama.cpp:server-b10920"
          command = ["/bin/sh", "-euc"]
          args = [
            <<-EOT
            cd /models
            {
              echo "6f67b8036b2469fcd71728702720c6b51aebd759b78137a8120733b4d66438bc  SmolVLM2-500M-Video-Instruct-Q8_0.gguf"
              echo "921dc7e259f308e5b027111fa185efcbf33db13f6e35749ddf7f5cdb60ef520b  mmproj-SmolVLM2-500M-Video-Instruct-Q8_0.gguf"
            } > SHA256SUMS
            if sha256sum -c SHA256SUMS >/dev/null 2>&1; then
              echo "caption weights already present"
              exit 0
            fi
            base=https://huggingface.co/ggml-org/SmolVLM2-500M-Video-Instruct-GGUF/resolve/ccd7aae53bcb1997355c2f094959e72b3642ce17
            curl -fL --retry 3 -o SmolVLM2-500M-Video-Instruct-Q8_0.gguf "$base/SmolVLM2-500M-Video-Instruct-Q8_0.gguf"
            curl -fL --retry 3 -o mmproj-SmolVLM2-500M-Video-Instruct-Q8_0.gguf "$base/mmproj-SmolVLM2-500M-Video-Instruct-Q8_0.gguf"
            sha256sum -c SHA256SUMS
            EOT
          ]
          security_context {
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities { drop = ["ALL"] }
          }
          resources {
            requests = { memory = "64Mi", cpu = "100m" }
            limits   = { memory = "256Mi", cpu = "1000m" }
          }
          volume_mount {
            name       = "models"
            mount_path = "/models"
          }
        }

        container {
          name  = "captioner"
          image = var.captioner_cuda ? "ghcr.io/ggml-org/llama.cpp:server-cuda-b10920" : "ghcr.io/ggml-org/llama.cpp:server-b10920"

          args = concat(
            [
              "--model", "/models/SmolVLM2-500M-Video-Instruct-Q8_0.gguf",
              "--mmproj", "/models/mmproj-SmolVLM2-500M-Video-Instruct-Q8_0.gguf",
              "--alias", "smolvlm2-500m-base-public",
              "--host", "0.0.0.0",
              "--port", "8092",
              "--jinja",
              "--ctx-size", "8192",
              # Bound llama.cpp's prompt cache inside the 2Gi memory limit.
              "--cache-ram", "128",
              "--parallel", "1",
              "--threads", "4",
            ],
            # No nvidia.com/gpu request below on purpose (see
            # deploy/kubernetes/overlays/captioner-cuda): a 500M model at
            # Q8_0 is 546 MB of weights, small enough to share a card with
            # the inference service on a cluster that time-slices one GPU
            # per node. Add a request back if the cluster does not.
            var.captioner_cuda ? ["--n-gpu-layers", "99"] : [],
          )

          security_context {
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities { drop = ["ALL"] }
          }

          port {
            name           = "http"
            container_port = 8092
          }

          dynamic "env" {
            for_each = var.captioner_cuda ? { NVIDIA_VISIBLE_DEVICES = "all", NVIDIA_DRIVER_CAPABILITIES = "compute,utility" } : {}
            content {
              name  = env.key
              value = env.value
            }
          }

          resources {
            requests = { memory = "1Gi", cpu = "500m" }
            limits   = { memory = "3Gi", cpu = "4000m" }
          }

          volume_mount {
            name       = "models"
            mount_path = "/models"
            read_only  = true
          }

          liveness_probe {
            http_get {
              path = "/health"
              port = "http"
            }
            initial_delay_seconds = 30
            period_seconds        = 20
            timeout_seconds       = 5
            failure_threshold     = 3
          }
          readiness_probe {
            http_get {
              path = "/health"
              port = "http"
            }
            initial_delay_seconds = 10
            period_seconds        = 15
            timeout_seconds       = 5
            failure_threshold     = 3
          }
        }

        volume {
          name = "models"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim_v1.captioner[0].metadata[0].name
          }
        }
      }
    }
  }

  depends_on = [
    kubernetes_namespace_v1.this,
    kubernetes_persistent_volume_claim_v1.captioner,
  ]
}

resource "kubernetes_service_v1" "captioner" {
  count = var.captioner_enabled ? 1 : 0

  metadata {
    name      = local.captioner_service_name
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    type = "ClusterIP"
    port {
      name        = "http"
      port        = 8092
      target_port = "http"
    }
    selector = { "app.kubernetes.io/name" = "immich-memories-captioner" }
  }

  depends_on = [kubernetes_namespace_v1.this]
}

resource "kubernetes_config_map_v1" "config" {
  count = var.config_yaml != "" ? 1 : 0

  metadata {
    name      = "immich-memories-config"
    namespace = var.namespace
    labels    = local.labels
  }

  data = {
    "config.yaml" = var.config_yaml
  }

  depends_on = [kubernetes_namespace_v1.this]
}
