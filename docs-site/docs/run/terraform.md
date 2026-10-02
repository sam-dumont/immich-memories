---
title: "Terraform"
---

# Terraform

The module in `deploy/terraform/` deploys the app to Kubernetes. Use it if you already manage
the cluster with Terraform. The shipped module has not been validated/applied to every live setup:
read the plan before applying it.

## Prerequisites

Terraform 1.0+, Kubernetes provider 2.20+, a working kubeconfig and storage class.
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

Run the printed port-forward command and open `http://localhost:8080`.
[Verify the connection and make the first film](./kubernetes.md#check-it-from-outside-the-pod).
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
The [Kubernetes verification commands](./kubernetes.md#check-it-from-outside-the-pod) work with the
same deployment and namespace names unless you changed them.
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
