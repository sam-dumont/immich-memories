mock_provider "kubernetes" {}

variables {
  immich_url     = "http://immich.test:2283"
  immich_api_key = "fixture-only"
  image_tag      = "test-fixture"
}

run "disabled_worker_allows_default_empty_token" {
  command = plan
}

run "enabled_worker_rejects_empty_token" {
  command = plan
  variables {
    render_worker_sidecar_enabled = true
  }
  expect_failures = [var.render_worker_token]
}

run "enabled_worker_accepts_generated_length_token" {
  command = plan
  variables {
    render_worker_sidecar_enabled = true
    render_worker_token           = join("", [for n in range(64) : "a"])
  }
}

run "enabled_worker_rejects_short_token" {
  command = plan
  variables {
    render_worker_sidecar_enabled = true
    render_worker_token           = "too-short"
  }
  expect_failures = [var.render_worker_token]
}

run "enabled_worker_rejects_placeholder_token" {
  command = plan
  variables {
    render_worker_sidecar_enabled = true
    render_worker_token           = join("", ["example", join("", [for n in range(64) : "a"])])
  }
  expect_failures = [var.render_worker_token]
}
