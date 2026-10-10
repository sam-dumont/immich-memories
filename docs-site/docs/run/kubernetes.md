---
title: Kubernetes
description: Install Basic, GPU or Full in an existing Kubernetes cluster using the setup builder.
---

import SetupBuilder from '@site/src/components/SetupBuilder';

# Kubernetes

Install into an existing cluster with Kustomize and persistent storage. Choose Basic, GPU or Full;
the setup builder generates that tier's configuration and commands.
For Terraform-managed resources, use the [Terraform module](./terraform.md).

## Prerequisites

- Immich reachable from the cluster, with a [scoped API key](./docker.md#the-api-key).
- A default storage class for three ReadWriteOnce volumes: 30 GiB data/cache, 50 GiB output and
  5 GiB models. Use local/block storage for the SQLite data volume, not NFS/SMB. Check the
  storage class's reclaim policy before installation.
- Capacity for the app: it requests 1 CPU / 2 GiB and has a limit of 4 CPUs / 8 GiB.
- **GPU and Full:** NVIDIA GPU Operator, the `nvidia` RuntimeClass and labelled GPU nodes.
  The shipped inference and caption services share a GPU through time-slicing; configure that
  sharing first. They add two volumes (2 GiB captions and 10 GiB inference cache) and their own
  compute requirements. [GPU allocation details](./local-models.md#kubernetes-services).
- **Full:** an existing reader endpoint with a served model, 32k context and any required API key.

Keep one UI replica. Authentication is disabled by default. The initial route uses a private
port-forward; configure
[authentication](./authentication.mdx) before adding an Ingress.

## 1. Choose the tier {#generated-tier-setup}

| Tier | Generated setup |
|---|---|
| **Basic** | CPU app, persistent store and local models |
| **GPU** | Basic plus CUDA inference and captions; video rendering stays on the app CPU |
| **Full** | GPU plus your explicitly enabled reader connection |

Enter the namespace and addresses reachable from the cluster. For Full, fill in the reader URL
and the exact model name it serves. Leave scheduled films off until you have made your first film.

<SetupBuilder initialPlatform="kubernetes" showPlatform={false} />

## 2. Save the files

Follow the generated commands to download and extract the matching release bundle. Save each
file at its labelled path. In the Secret, replace `replace-with-your-immich-api-key` with your
own key. For a reader, replace its key placeholder too, or empty it when the reader needs no key.
Keep the Secret private and retain its Settings encryption key with your backups.

## 3. Apply and check {#quick-start}

Continue the generated commands: inspect the rendered Kustomize output, apply it, then wait for
the app and the model services your tier uses. First starts download images and model files.
Run `models fetch` and `preflight` after those rollouts finish.

Continue when the Immich connection, output and required model/service checks pass.
`capabilities` should report the tier you selected.

## 4. Open the app

Keep the generated `kubectl port-forward` command running and open
[http://localhost:8080](http://localhost:8080). Make [your first film](../get-started/first-film.mdx)
and download it from its run page.

## Operate this installation {#supported-deployment-paths}

Kustomize and [Terraform](./terraform.md) are the supplied deployment paths. There is no project
Helm chart. [Tested deployments](./tested-deployments.md) records the exact platform and release
coverage; the generated files do not imply every cluster or tier has been exercised.

| Task | Guide |
|---|---|
| Manual manifests, namespaces, Secret rotation | [Kubernetes operations](./reference/kubernetes-operations.md) |
| Ingress, probes, logs and outages | [Networking and monitoring](./reference/kubernetes-operations.md#authentication-and-ingress) |
| GPU rendering, PostgreSQL, workers or batch jobs | [Topology and add-ons](./reference/kubernetes.md) |
| Storage sizing, requests and scratch | [Resource budgets](./reference/kubernetes-operations.md#resource-requests-qos-and-scratch) |
| Repeatable release inputs | [GitOps](./gitops.md) |
| Upgrade, backup or removal | [Maintenance](./maintenance/upgrading.md#kubernetes-and-terraform), [backups](./maintenance/storage-backups.md), [uninstall](./lifecycle.md) |

<span id="another-namespace" />
<span id="rotating-a-key" />
<span id="keep-the-secret-key" />
<span id="home-base-time-zone-and-the-first-cut" />
<span id="getting-the-films" />
<span id="authentication-and-ingress" />
<span id="how-the-pod-is-wired" />
<span id="networkpolicy" />
<span id="gpu" />
<span id="set-the-preparation-tier" />
<span id="render-worker-as-a-sidecar" />
<span id="a-separate-render-deployment" />
<span id="the-two-model-services" />
<span id="database" />
<span id="batch-jobs" />
<span id="backups" />
<span id="probes" />
<span id="logs" />
<span id="upgrading-and-rollback" />
<span id="check-it-from-outside-the-pod" />
<span id="the-models-the-first-cut-needs" />
<span id="distribute-work-across-services" />
<span id="configuration-ownership" />
<span id="probes-outages-and-monitoring" />
<span id="resource-requests-qos-and-scratch" />
<span id="reproducible-gitops-inputs" />
<span id="stop-or-remove-this-installation" />
