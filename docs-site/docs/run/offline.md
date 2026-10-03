---
title: "Fetch once, then keep traffic local"
---

# Fetch once, then keep traffic local

This recipe runs Basic with the rules reader and bundled music. After preparation, the app
contacts Immich; it does not need a hosted reader, a caption service or a music generator.
The network boundary enforces that choice. Turning off features alone is not a firewall.
Both recipes passed real isolated runs with fresh models and a synthetic CC0 Immich library:
Docker Desktop on Apple Silicon, and RKE2 1.33.4 with Cilium 1.18.0. Each kept Immich reachable,
blocked unrelated outbound HTTPS, passed preflight and produced a 19-second 1080p H.264/AAC
film with a complete audio/video decode.

The Docker run used app source `5466706b` and Compose recipe `00cd41df`; the Kubernetes run
used candidate source tree `75077f27` and the documented fixed-IP/no-DNS policy variant.
These were local candidate images, not release-download tests. The DNS-service variant
needs a check on your cluster: in this run the allowed CoreDNS pod answered directly, but
its Service IP did not. Community validation is welcome; report your platform/version,
a denied outbound destination and your first film result in
[#1804](https://github.com/sam-dumont/immich-memories/issues/1804).

## Fetch before closing the network

Use the same release image for fetching and rendering. Pull it before isolating the app:

```bash
export IMMICH_MEMORIES_IMAGE=ghcr.io/sam-dumont/immich-video-memory-generator:YOUR_RELEASE
docker pull "$IMMICH_MEMORIES_IMAGE"
docker volume create immich-memories-offline-models
docker run --rm --user 0:0 --entrypoint sh \
  -v immich-memories-offline-models:/models "$IMMICH_MEMORIES_IMAGE" \
  -c 'chown 1000:1000 /models'
docker run --rm \
  -e IMMICH_MEMORIES_TIER=nas -e IMMICH_MEMORIES_LLM__ENABLED=false \
  -e IMMICH_MEMORIES_TRIAGE__ENCODER=/models/triage/dinov2-small.onnx \
  -e IMMICH_MEMORIES_FREE_TEXT__WORDNET=/models/wordnet/wordnet.zip \
  -v immich-memories-offline-models:/models "$IMMICH_MEMORIES_IMAGE" \
  immich-memories models fetch --no-detectors
```

Replace `YOUR_RELEASE` with your installed release tag or image digest. The root helper only
sets ownership on this new model volume; the fetch and running app use UID 1000.
Basic fetches the digest-pinned DINOv2 ONNX encoder from a GitHub release and WordNet from
`raw.githubusercontent.com`. The public context heads and bundled music ship in the image.
It does not fetch a reader when `llm.enabled` is false.

`--detectors` additionally fetches the Marqo ONNX export from GitHub and pinned detector
snapshots from Hugging Face. GPU/Full also fetch Laya; the configured owned default reader
fetches its model and image projector from Hugging Face. This is more than Basic needs.
`models fetch` does **not** prepare every optional service: captioner startup has its own
checkpoint fetch; Demucs obtains Torch Hub weights from `dl.fbaipublicfiles.com`; ACE-Step
has its own pinned snapshot downloader. See the [inventory](reference/privacy-egress.md).

The seed machine needs HTTPS to `github.com`, `raw.githubusercontent.com` and, for the
optional models, `huggingface.co`. Downloads can redirect to release/CDN/storage hosts;
those three names are starting points, not a complete fixed firewall allow-list. Inspect
redirect destinations on the seed machine. Container image pulls need the image registry
and its delivery hosts too; they are Docker/node traffic, not app traffic.

### Seed on another machine

Run the fetch above on the connected machine, then export only the model volume:

```bash
docker run --rm --entrypoint tar \
  -v immich-memories-offline-models:/models:ro "$IMMICH_MEMORIES_IMAGE" \
  -C /models -czf - . > immich-memories-models.tar.gz
```

Copy that archive and the same image to the offline host. On the destination, create the
volume and restore it before starting the app:

```bash
docker volume create immich-memories-offline-models
docker run --rm -i --user 0:0 --entrypoint sh \
  -v immich-memories-offline-models:/models "$IMMICH_MEMORIES_IMAGE" \
  -c 'tar -xzf - -C /models && chown -R 1000:1000 /models' < immich-memories-models.tar.gz
```

`docker save` / `docker load` transfers the image if the destination cannot pull it.
Do not copy the config/store volume: it can contain credentials and library metadata.
Preserve the complete model directory, including Hugging Face snapshot, blob and reference
files if you fetched detectors. Preserve its paths when mounting it; a cache under a
new location is not automatically found. Run `models fetch --no-detectors` with the same
paths on the isolated host to verify Basic artifact digests: it reports “already present”;
a missing or changed artifact tries a download and fails instead of proving readiness.

## Docker: one internal bridge

This variant requires Immich on the **same Docker daemon**. Create an internal bridge and
attach the Immich server with an alias; use your actual container name:

```bash
docker network create --internal immich-memories-offline
docker network connect --alias offline-immich immich-memories-offline YOUR_IMMICH_CONTAINER
```

Make that attachment part of your Immich Compose configuration before its next recreation.
It does not change Immich's other networks. The Memories app must have only this internal
network; adding a second ordinary bridge restores outbound routing.
[Docker documents this distinction](https://docs.docker.com/compose/how-tos/networking/).

Copy [the standalone example](https://github.com/sam-dumont/immich-memories/blob/main/deploy/offline/docker-compose.yml.example)
as `docker-compose.offline.yml`. Use a fresh data volume and set the two Immich values:

```bash
export IMMICH_URL=http://offline-immich:2283
read -rs IMMICH_API_KEY; export IMMICH_API_KEY
mkdir -p output
# The image uses UID 1000; give it write access to this output directory.
sudo chown 1000:1000 output
docker compose -f docker-compose.offline.yml up -d
docker compose -f docker-compose.offline.yml exec immich-memories immich-memories preflight -v
docker compose -f docker-compose.offline.yml exec immich-memories \
  immich-memories generate --year 2024 --month 6 --duration 20
```

Choose a month that has pictures. The UI stays on localhost. The example pins outbound
features off even if Settings later stores another value; remove an override deliberately
to enable a feature, and add its exact permitted destination first.

An internal bridge does **not** provide a route to `192.168.x.x` on another machine.
For remote LAN Immich, keep a routable app network and use the Docker host's container
forwarding firewall to permit only the app's source network/interface → Immich IP and TCP
port, plus explicit LAN services if needed, then deny other app egress. Cover IPv6 too.
Use your host's Docker firewall backend; a host OUTPUT rule alone does not filter forwarded
container packets. Do not paste these Docker-only assumptions into a Synology firewall UI.
[Docker's firewall guide](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
explains the backend and forwarding path. Verify allowed and denied destinations from
inside the app container before calling the setup isolated.

## Kubernetes: replace broad egress after the fetch

Start with the [Kubernetes installation](./kubernetes.md), let its model init finish,
and keep the warmed model PVC. The supplied base policy permits ports across destinations;
it is not an offline policy. Copy [the destination example](https://github.com/sam-dumont/immich-memories/blob/main/deploy/offline/networkpolicy.yaml.example)
as `networkpolicy.offline.yaml` and edit:

- `192.0.2.10/32` to the actual fixed Immich IP, and `2283` to its actual TCP port. For an
  in-cluster Immich pod, replace `ipBlock` with one peer containing both its exact
  `namespaceSelector` and `podSelector`.
- DNS selectors to your cluster's actual DNS pods. NodeLocal DNS needs its actual IP/32
  instead. DNS is an additional allowed destination; its resolver may contact upstreams.
  For strict DNS isolation, use fixed IP URLs and remove this rule, or a resolver restricted
  to your internal zones.
- If you enable LAN/in-cluster model services, add exact destination selectors/IPs and
  ports. Basic needs none. Apply equivalent restrictions to the service pods themselves;
  restricting the app does not stop a model server downloading weights.

After preparation, remove the fetch init container from your maintained manifest/overlay
and pin the same offline feature settings as the Docker example. To make that transition
on an already running Basic Deployment:

```bash
kubectl rollout status -n immich-memories deployment/immich-memories
kubectl patch deployment immich-memories -n immich-memories --type=json \
  -p='[{"op":"remove","path":"/spec/template/spec/initContainers"}]'
kubectl set env deployment/immich-memories -n immich-memories \
  IMMICH_MEMORIES_TIER=nas IMMICH_MEMORIES_LLM__ENABLED=false \
  IMMICH_MEMORIES_RENDER__WORKER_BASE_URL= IMMICH_MEMORIES_INFERENCE__FACTS_BASE_URL= \
  IMMICH_MEMORIES_NETWORK__GEOCODING=false IMMICH_MEMORIES_NETWORK__MAP_TILES=false \
  IMMICH_MEMORIES_ACE_STEP__ENABLED=false IMMICH_MEMORIES_MUSICGEN__ENABLED=false \
  IMMICH_MEMORIES_NOTIFICATIONS__URLS='[]' \
  IMMICH_MEMORIES_EDITORIAL__PREPARATION__ALLOW_MODEL_DOWNLOADS=false \
  IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_PROVIDER=smolvlm \
  IMMICH_MEMORIES_EDITORIAL__PREPARATION__TIER=no_captions \
  IMMICH_MEMORIES_EDITORIAL__DETECTORS_ENABLED=false IMMICH_MEMORIES_EDITORIAL__LAYA_AUDIENCE=false \
  HF_HUB_OFFLINE=1
kubectl apply -f networkpolicy.offline.yaml
kubectl rollout status -n immich-memories deployment/immich-memories
kubectl exec -n immich-memories deployment/immich-memories -- immich-memories preflight -v
```

Save those edits in your deployment source. Reapplying the original base restores the
fetch init and broad policy. The example uses the base policy's **same name**, replacing
its egress rules. NetworkPolicies are additive: another matching policy that permits
80/443 still permits that traffic. Remove broad matching rules/components, including
reader-egress, before claiming a destination allow-list. A policy needs a CNI that
actually enforces it. Service DNAT and `ipBlock` matching depend on the CNI; validate with
your actual Service/pod/LAN addresses. [Kubernetes documents these limits](https://kubernetes.io/docs/concepts/services-networking/network-policies/).

## What preflight can prove

Expect Immich and encoder checks to pass; LLM and caption checks should be skipped for Basic,
notifications should have no destinations, and there should be no geocoding/map
“Outside call” rows. Preflight does authenticated configured-service probes; it is not a
packet capture or a firewall test. Those outside-call rows cover geocoding/maps, not every
possible recipient. A successful first film and a denied unrelated destination check from
the app container/pod are separate evidence.

Leave hosted readers, image-caption opt-ins, geocoding, map tiles, notifications, generated
music and remote render workers off. LAN readers/captioners/inference can be deliberate
exceptions once their weights are seeded and their own egress is restricted. Open only
those destinations; do not open every host on port 443 to make a warning disappear.
