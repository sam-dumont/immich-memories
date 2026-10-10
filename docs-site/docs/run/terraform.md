---
title: "Terraform"
---

# Terraform

The module in `deploy/terraform/` runs the app in an existing Kubernetes cluster. Use this
route when you already manage that cluster with Terraform. For a setup that also generates
the GPU model-service deployments, use [Kustomize](./kubernetes.md).

## Prerequisites

Terraform 1.9+, Kubernetes provider 2.20+, a working kubeconfig and storage class.
Immich must be reachable from the pod. For NVIDIA scheduling, add GPU Operator and the `nvidia` RuntimeClass.

## Quick start

Download and extract the [matching release bundle](./gitops.md) into `vendor/immich-memories`,
then choose the private CPU example:

```bash
cd vendor/immich-memories/deploy/terraform/examples/basic
cp terraform.tfvars.example terraform.tfvars
```

Edit the Immich URL, [scoped API key](./docker.md#the-api-key) and pinned `image_tag`.
Choose the tier through the example's `env` map:

| Tier | Configuration |
|---|---|
| **Basic** | `IMMICH_MEMORIES_TIER = "basic"`; no model services |
| **GPU** | `IMMICH_MEMORIES_TIER = "gpu"`; set the [inference and caption endpoints](../get-started/choose-your-setup.md#gpu-understand-more-of-the-pictures) |
| **Full** | GPU configuration with `IMMICH_MEMORIES_TIER = "full"`, `IMMICH_MEMORIES_LLM__ENABLED = "true"`, plus `llm_base_url`, `llm_model` and any `llm_api_key` |

GPU/Full require working CUDA inference, captions and Laya; Full also needs a reader with 32k
context. The module does not deploy an inference or reader server. See the
[service inputs](./reference/terraform.md#additional-supported-inputs) for the optional captioner.
`gpu_enabled` controls app GPU scheduling for rendering; it does not start those services.
Keep `replicas = 1`. Terraform state and plan artifacts can contain keys, so protect them.

Then:

```bash
terraform init
terraform plan
terraform apply
terraform output -raw port_forward_command
```

`terraform apply` waits for the deployment rollout and a Ready pod. The `/health/ready` probe stays unready until configuration is present and Immich answers; inspect the pod events and logs if apply waits or times out. Run the printed port-forward command and open `http://localhost:8080`.
The production example adds ingress/TLS; enable authentication before exposing it.
Authentication is disabled by default. Keep one UI replica (`replicas = 1`).

## What it creates

<Diagram name="deploy-terraform" headline="The module creates the app and its storage. Cron, network policy and PostgreSQL are yours to add." />
Namespace (optional), Secret, three PVCs, Deployment and Service, plus optional ingress.
`config_yaml` creates a ConfigMap and init container to install the file. Otherwise configuration
comes from `env`/`secret_env` and saved Settings. The module does **not** create the Kustomize base's
NetworkPolicy; define one separately if you need an egress boundary.

Terraform state can contain API keys and Secret values even when inputs are marked sensitive.
Protect the state backend and plan artifacts as credentials.

## After the apply

Manage values in Terraform: a later apply overwrites `kubectl set env` changes.
With the default namespace and deployment names, check preparation and readiness, then open the UI:

```bash
kubectl exec -n immich-memories deploy/immich-memories -- immich-memories models fetch
kubectl exec -n immich-memories deploy/immich-memories -- immich-memories preflight
kubectl port-forward -n immich-memories svc/immich-memories 8080:80
```

Use your chosen names if you changed them. [Your first film](../get-started/first-film.mdx) starts from the connected UI.
For home coordinates, timezone and uploads, use the `env` map.
[Input examples and the variable reference](./reference/terraform.md).

## Model preparation and tiers

The init container fetches pinned files. Without an explicit tier in `env`, the app uses automatic tier selection.
After adding GPU/Full services, run `models fetch` and `preflight` in the app container.
[Model preparation caveats](reference/kubernetes-operations.md#the-models-the-first-cut-needs).

## Daily automation

The module has no CronJob. Enable the in-process timer in `env`, or use
[an authenticated external trigger](../make/automate.md#trigger-it-over-http).

## Upgrading

Back up the store, change `image_tag`, plan/apply, fetch current pins and run preflight.
[Upgrade and rollback](./maintenance/upgrading.md#kubernetes-and-terraform).

## Module usage

[Module example](./reference/terraform.md#module-usage).

## Variables

[Supported inputs](./reference/terraform.md#variables), including
[config, captioner and sidecar inputs](./reference/terraform.md#additional-supported-inputs).

## Troubleshooting

[Configuration ownership and monitoring](./reference/kubernetes-operations.md#configuration-ownership)
covers deployment-controlled settings, probes and Immich outages.
[Deployment evidence](./tested-deployments.md) records tested versions and routes.

[Pod, storage and GPU checks](./reference/terraform.md#troubleshooting).

## Stop or remove this installation

[Stop, reset and uninstall](./lifecycle.md) separates retaining data for reinstall from deleting app state.
