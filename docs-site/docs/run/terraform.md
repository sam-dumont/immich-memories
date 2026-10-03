---
title: "Terraform"
---

# Terraform

The module in `deploy/terraform/` deploys the app to Kubernetes. Use it if you already manage
the cluster with Terraform. The [existing-Secret validation runs](./reference/kubernetes.md#verified-terraform-runs)
include an unmodified-module rollout with a published app release. Read the plan before applying
it to your cluster.

The project supports this module and the [Kustomize deployment](./kubernetes.md#supported-deployment-paths).
There is no project Helm chart; request one if your setup needs it.

Read [configuration ownership, probes and resources](./kubernetes.md#configuration-ownership)
for environment/file versus Settings precedence, singleton behavior and Immich outages.
Use [pinned bundle vendoring](./gitops.md) for repeatable module inputs.

## Prerequisites

Terraform 1.9+, Kubernetes provider 2.20+, a working kubeconfig and storage class.
Immich must be reachable from the pod. For NVIDIA scheduling, add GPU Operator and the `nvidia` RuntimeClass.

## Quick start

From the release deployment bundle, choose the private CPU example:

```bash
cd deploy/terraform/examples/basic
cp terraform.tfvars.example terraform.tfvars
```

Edit the Immich URL, API key and pinned `image_tag`. Then:

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

The init container fetches pinned files. The app starts with automatic tier selection.
After adding GPU/Full services, run `models fetch` and `preflight` in the app container.
[Model preparation caveats](./kubernetes.md#the-models-the-first-cut-needs).

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

[Pod, storage and GPU checks](./reference/terraform.md#troubleshooting).
