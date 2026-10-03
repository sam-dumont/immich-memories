mock_provider "kubernetes" {}

run "existing_secret" {
  command = plan
  variables {
    existing_secret_name          = "operator-owned-secret"
    render_worker_sidecar_enabled = true
  }
  assert {
    condition     = length(kubernetes_secret_v1.this) == 0
    error_message = "Existing Secret must not be created, read or overwritten."
  }
  assert {
    condition     = kubernetes_deployment_v1.this.spec[0].template[0].spec[0].container[0].env_from[0].secret_ref[0].name == "operator-owned-secret"
    error_message = "App must use the operator Secret."
  }
  assert {
    condition     = alltrue([for item in kubernetes_deployment_v1.this.spec[0].template[0].spec[0].container[1].env : item.value_from[0].secret_key_ref[0].name == "operator-owned-secret" if length(item.value_from) > 0])
    error_message = "Worker must use the same operator Secret for token and Immich URL."
  }
}

run "missing_managed_credentials" {
  command         = plan
  expect_failures = [var.immich_url, var.immich_api_key]
}

run "managed_secret" {
  command = plan
  variables {
    immich_url     = "https://photos.example.com"
    immich_api_key = "synthetic-fixture-key"
  }
  assert {
    condition     = length(kubernetes_secret_v1.this) == 1
    error_message = "Ordinary Terraform install must still create its Secret."
  }
}
