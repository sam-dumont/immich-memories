---
title: Distributed services on Kubernetes
description: Put preparation and rendering in separate services when your cluster needs independent placement.
---

import DeploymentDiagram from '@site/src/components/DeploymentDiagram';

# Distributed services on Kubernetes

Use separate services when you need independent GPU placement or already run a reader and music
server. Start with the [base Kubernetes install](../kubernetes.md). For one GPU shared between
preparation and rendering, the [one GPU service](../reference-setup.md) is simpler.

<DeploymentDiagram topology="cluster" />

## What runs where

The shipped `deploy/kubernetes/overlays/maximalist` example composes these pieces. Use it as a
starting point and keep the services you need.

| Component | Deployed by the overlay | Needs |
|---|---|---|
| App and persistent store | Yes, one app replica | Immich access and the base PVCs |
| Render worker | Yes, sidecar in the app pod | NVIDIA GPU allocation; shared bearer token |
| Classifiers and Demucs stems | Yes, separate inference pod | NVIDIA GPU allocation; model cache |
| Captions | Yes, separate caption pod | NVIDIA runtime; reviewed GPU-sharing settings |
| Text reader | No | Existing compatible endpoint with 32k context |
| ACE-Step music | No | Existing ACE-Step API server, if music generation is enabled |
| HTTPS proxy and identity provider | No | Ingress/proxy and OIDC registration, if keeping the example's login settings |

Laya remains in the app. The reader receives selection text; inference and captions receive picture
previews. The render worker downloads originals from Immich with the API key supplied by the app.
[Privacy](../privacy.md) lists the data sent to each service.

## Before applying

Keep the storage, namespace and NVIDIA prerequisites from the [base install](../kubernetes.md#prerequisites).
The render sidecar and inference pod each claim one advertised GPU allocation. Putting both on
one physical card requires device-plugin sharing configured by the cluster operator; the overlay
does not set that up. Choose node selectors that match your available allocations.

The caption overlay intentionally has no `nvidia.com/gpu` request. It can share devices exposed
by the NVIDIA runtime, but this provides no scheduler reservation or memory guarantee.
For a dedicated card, add the [explicit GPU request](../../reference/caption-service.md#kubernetes)
and set its node selector. Confirm driver/runtime support and memory headroom for every service.

Use a release deployment bundle or a checkout of the release you will run. Keep the app and render
worker tags equal. Inspect image pins in the base and each add-on kustomization; the caption image
uses a separate llama.cpp build. [Caption image pinning](../../reference/caption-service.md#kubernetes)
explains that serving contract.

## Configure your endpoints and access

From the deployment bundle or release checkout:

```bash
cd deploy/kubernetes
cp base/secret.yaml.example base/secret.yaml
cp overlays/render-sidecar/render-worker-secret.yaml.example overlays/render-sidecar/render-worker-secret.yaml
cp overlays/maximalist/maximalist-secret.yaml.example overlays/maximalist/maximalist-secret.yaml
openssl rand -hex 32
```

Edit those three Secrets and `overlays/maximalist/config-map.yaml` before applying:

| File or setting | Replace or confirm |
|---|---|
| Base Secret | Your Immich URL and API key |
| Render-worker Secret | Same Immich URL and the generated token |
| Extra Secret | Your OIDC credentials and any reader/music API keys |
| `advanced.llm` | Reader URL and the exact model name served there |
| `advanced.ace_step` | Music API URL, or `enabled: false` to use bundled/chosen music |
| `advanced.auth`, `advanced.server` | Public HTTPS URL, allowed accounts, trusted proxy addresses and secure cookies |
| `network` and cache limits | Outside map calls you permit and limits that fit the PVC |

The example enables OIDC and assumes HTTPS. Configure your own
[authentication and proxy](../authentication.mdx#behind-a-reverse-proxy-with-tls), and register
its callback/logout URLs with the identity provider. The overlay does not create an Ingress.
For a private port-forward install, replace the OIDC settings with the access method you chose;
keep the app private until that method works.

The additional NetworkPolicy permits reader port 9999 and music port 8001. Change those ports
with your endpoint URLs. These are port rules, not destination allow-lists. The inference and
caption listeners have no built-in authentication; keep them private and restrict their clients
in your network policy. A ClusterIP does not authenticate requests.

## Render, apply and verify

```bash
kubectl kustomize overlays/maximalist
kubectl apply -k overlays/maximalist
kubectl rollout status -n immich-memories deploy/immich-memories
kubectl rollout status -n immich-memories deploy/immich-memories-inference
kubectl rollout status -n immich-memories deploy/immich-memories-captioner
kubectl get pods -n immich-memories -o wide
kubectl exec -n immich-memories deploy/immich-memories -c immich-memories -- immich-memories models fetch
kubectl exec -n immich-memories deploy/immich-memories -c immich-memories -- immich-memories config show tier
kubectl exec -n immich-memories deploy/immich-memories -c immich-memories -- immich-memories preflight -v
```

The overlay explicitly sets `IMMICH_MEMORIES_TIER=full`: the environment wins over the config
file. Seeing Full in `config show` confirms the setting; preflight checks its required services
and models. Run preparation on a small date window, review a first film and confirm its reported
render path before enabling daily automation.

If a pod stays Pending, check GPU allocations, node selectors and PVC events. If preflight fails,
check the relevant endpoint, model name, credentials and NetworkPolicy before changing tiers.
Keep the worker's loopback `exec` probes; kubelet HTTP probes cannot reach its loopback listener.
[Service diagnostics](../maintenance/health-logs-cache.md) has the logs and health routes.

## Adapt the example

Remove unwanted services from your own composition rather than copying every option. Applying
sibling app overlays one after another replaces earlier patches; combine the patches into one
kustomization. Preserve `enableServiceLinks: false` and one app replica.

For PostgreSQL, add the database Secret and egress port to that composition; the overlay does
not deploy PostgreSQL. [Database setup](../database.md) and
[overlay composition](./kubernetes.md#database) cover the details.

Terraform users can start from `deploy/terraform/examples/maximalist`. That example creates the
app, render sidecar and captions, but **not inference**: deploy inference separately in the same
namespace and match the configured URL. Reader, music and identity services remain external.
[Terraform inputs](./terraform.md) describe those switches.
