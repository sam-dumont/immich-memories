"""Contracts for the shipped Kubernetes manifests and Terraform module (issue #307).

These files never boot in a cluster during CI, so the properties that made them
fail as shipped are pinned here: the Secret is applied, the config directory is
writable, probes hit the real endpoints, no GPU is required by default, and no
stale config keys survive.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
K8S_ROOT = REPO_ROOT / "deploy" / "kubernetes"
K8S_DIR = K8S_ROOT / "base"
TF_DIR = REPO_ROOT / "deploy" / "terraform"

# The image runs as `immich`, UID 1000, HOME=/home/immich (docker/Dockerfile).
CONFIG_DIR = "/home/immich/.immich-memories"
OUTPUT_DIR = "/app/output"
IMMICH_PORT = 2283
# The caption server default (editorial.preparation.caption_base_url).
CAPTION_PORT = 8092
MODELS_DIR = "/models"
# ggml-org/SmolVLM2-500M-Video-Instruct-GGUF, the revision and file digests the
# captioner overlay downloads. Docs and manifest must not drift apart.
CAPTION_GGUF_REVISION = "ccd7aae53bcb1997355c2f094959e72b3642ce17"
CAPTION_GGUF_SHA256 = (
    "6f67b8036b2469fcd71728702720c6b51aebd759b78137a8120733b4d66438bc",
    "921dc7e259f308e5b027111fa185efcbf33db13f6e35749ddf7f5cdb60ef520b",
)
# Every path-valued setting a pinned artifact lands on: the encoder, the
# sensitive-content export, the Hugging Face cache the detectors read and the
# WordNet corpus free-text requests are read with.
MODEL_PATH_ENV = (
    "IMMICH_MEMORIES_TRIAGE__ENCODER",
    "IMMICH_MEMORIES_EDITORIAL__PREPARATION__MARQO_ONNX",
    "IMMICH_MEMORIES_EDITORIAL__PREPARATION__DETECTOR_CACHE_DIR",
    "IMMICH_MEMORIES_FREE_TEXT__WORDNET",
)


def _yaml_docs(path: Path) -> list[dict]:
    return [doc for doc in yaml.safe_load_all(path.read_text()) if doc]


def _kustomization() -> dict:
    return yaml.safe_load((K8S_DIR / "kustomization.yaml").read_text())


def _deployment() -> dict:
    docs = _yaml_docs(K8S_DIR / "deployment.yaml")
    return next(doc for doc in docs if doc["kind"] == "Deployment")


def _pod_specs() -> list[tuple[str, dict]]:
    """Every pod template shipped in the base directory, labelled by its file."""
    specs = []
    for path in sorted(K8S_DIR.glob("*.yaml")):
        for doc in _yaml_docs(path):
            kind = doc.get("kind")
            if kind in ("Deployment", "Job"):
                specs.append(
                    (f"{path.name}:{doc['metadata']['name']}", doc["spec"]["template"]["spec"])
                )
            elif kind == "CronJob":
                pod = doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]
                specs.append((f"{path.name}:{doc['metadata']['name']}", pod))
    return specs


def _is_trigger_pod(pod: dict) -> bool:
    """A pod that only calls POST /api/trigger on the running Deployment.

    It never runs the app image, never touches the store, and so is exempt
    from the assertions that only make sense for a pod that does (models,
    config volume, Immich secret, output directory, app tier).
    """
    containers = pod.get("containers", [])
    return bool(containers) and containers[0]["name"] == "trigger"


def _app_pod_specs() -> list[tuple[str, dict]]:
    """Pods that run the app image: the Deployment and the one-off `generate` Job."""
    return [(name, pod) for name, pod in _pod_specs() if not _is_trigger_pod(pod)]


def _trigger_pod_specs() -> list[tuple[str, dict]]:
    """CronJob pods whose only job is curling the trigger route (#871)."""
    return [(name, pod) for name, pod in _pod_specs() if _is_trigger_pod(pod)]


def _deploy_texts() -> dict[str, str]:
    return {
        str(path.relative_to(REPO_ROOT)): path.read_text()
        for path in list(K8S_ROOT.rglob("*")) + list(TF_DIR.rglob("*"))
        if path.is_file()
    }


def test_kustomization_applies_the_secret_the_deployment_needs() -> None:
    """`kubectl apply -k .` must not leave the pod in CreateContainerConfigError."""
    resources = _kustomization()["resources"]

    assert "secret.yaml" in resources
    assert "configmap.yaml" not in resources
    assert (K8S_DIR / "secret.yaml.example").exists()
    assert not (K8S_DIR / "configmap.yaml").exists()


def test_kustomization_pins_a_published_image_tag() -> None:
    """Published image tags carry no `v` prefix; `v1.0.0` never existed."""
    kustomization = _kustomization()
    images = kustomization["images"]
    image = next(
        entry
        for entry in images
        if entry["name"] == "ghcr.io/sam-dumont/immich-video-memory-generator"
    )

    assert re.fullmatch(r"\d+\.\d+\.\d+", str(image["newTag"])), image
    assert "commonLabels" not in kustomization


def test_the_two_inference_overlays_name_the_same_release() -> None:
    """The CUDA image is the CPU tag with `-cuda` on the end, and only it carries that provider.

    They drift apart silently: a cluster applying one overlay and reading the
    other's release notes gets a service that answers with different weights.
    """
    tags = {}
    for overlay in ("inference", "inference-cuda"):
        kustomization = yaml.safe_load(
            (K8S_ROOT / "overlays" / overlay / "kustomization.yaml").read_text()
        )
        entry = next(
            image for image in kustomization["images"] if image["name"].endswith("/inference")
        )
        tags[overlay] = str(entry["newTag"])

    assert re.fullmatch(r"\d+\.\d+\.\d+", tags["inference"]), tags
    assert tags["inference-cuda"] == f"{tags['inference']}-cuda", tags
    assert tags["inference"] == _kustomization()["images"][0]["newTag"]


def test_every_app_pod_starts_without_a_caption_service() -> None:
    from immich_memories.config_loader import Config

    for name, pod in _app_pod_specs():
        for container in pod["containers"]:
            env = {row["name"]: row.get("value") for row in container.get("env", [])}
            assert env["IMMICH_MEMORIES_TIER"] == "auto", name
            assert not Config(
                tier=env["IMMICH_MEMORIES_TIER"]
            ).editorial.preparation.demands_captions


def test_compose_profiles_have_distinct_host_ports_and_persistent_detector_storage() -> None:
    services = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())["services"]
    inference = services["immich-memories-inference"]["ports"]
    captioner = services["immich-memories-captioner"]["ports"]
    assert set(inference).isdisjoint(captioner)
    app = services["immich-memories"]
    cache = app["environment"]["IMMICH_MEMORIES_EDITORIAL__PREPARATION__DETECTOR_CACHE_DIR"]
    assert cache.startswith(CONFIG_DIR + "/models/")
    assert any(volume.endswith(":" + CONFIG_DIR) for volume in app["volumes"])


def test_terraform_initializes_models_on_a_persistent_claim() -> None:
    main = (TF_DIR / "main.tf").read_text()
    assert 'resource "kubernetes_persistent_volume_claim_v1" "models"' in main
    assert "init_container {" in main
    assert "immich-memories models fetch" in main
    assert "kubernetes_persistent_volume_claim_v1.models.metadata[0].name" in main
    assert all(key in main for key in MODEL_PATH_ENV)
    assert "IMMICH_MEMORIES_TIER" in main


def test_only_the_kustomization_pin_names_a_concrete_version() -> None:
    """One `0.59.2` was copied into five prose sites and all six rotted together (#732).

    The pin is the only number a reader should trust, so everything else states the rule
    (`vX.Y.Z` ships as `X.Y.Z`) instead of quoting a release that goes stale within a day.
    """
    offenders = {}
    for name, text in _deploy_texts().items():
        if name.endswith("kustomization.yaml"):
            text = re.sub(r"(?m)^\s*newTag:.*$", "", text)
        # A dotted quad is an address, not a release: the captioner binds 0.0.0.0.
        text = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "", text)
        # A digest-pinned third-party image (the trigger pods' curl) is pinned by
        # the digest, not the tag beside it: that tag cannot drift out of sync
        # with anything, unlike a copied-around app release number.
        text = re.sub(r"\S+:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", "", text)
        if found := re.findall(r"\d+\.\d+\.\d+", text):
            offenders[name] = found

    assert not offenders, offenders


def test_config_directory_is_a_writable_persistent_volume() -> None:
    """The app writes cache/, projects/, cache.db and .storage_secret at startup."""
    for label, pod in _app_pod_specs():
        container = pod["containers"][0]
        mounts = {mount["mountPath"]: mount for mount in container["volumeMounts"]}
        volumes = {volume["name"]: volume for volume in pod["volumes"]}

        config_mount = mounts[CONFIG_DIR]
        assert not config_mount.get("readOnly"), label
        assert "subPath" not in config_mount, label
        assert "persistentVolumeClaim" in volumes[config_mount["name"]], label

        output_mount = mounts[OUTPUT_DIR]
        assert "persistentVolumeClaim" in volumes[output_mount["name"]], label

        tmp = volumes[mounts["/tmp"]["name"]]["emptyDir"]
        assert re.fullmatch(r"([2-9]|\d{2,})Gi", tmp["sizeLimit"]), label

        assert not any(path.startswith("/home/appuser") for path in mounts), label
        assert "/output" not in mounts, label


def test_pods_write_output_to_the_mounted_directory() -> None:
    for label, pod in _app_pod_specs():
        env = {item["name"]: item.get("value") for item in pod["containers"][0].get("env", [])}
        assert env.get("IMMICH_MEMORIES_OUTPUT__DIRECTORY") == OUTPUT_DIR, label
        assert "HOME" not in env, label


def test_pods_read_immich_credentials_from_the_secret() -> None:
    for label, pod in _app_pod_specs():
        container = pod["containers"][0]
        secret_refs = {ref["secretRef"]["name"] for ref in container.get("envFrom", [])}
        assert "immich-memories-secrets" in secret_refs, label


def test_probes_use_liveness_and_readiness_endpoints() -> None:
    """`/health` and `/` always answer 200, so they cannot signal anything."""
    container = _deployment()["spec"]["template"]["spec"]["containers"][0]

    assert container["livenessProbe"]["httpGet"]["path"] == "/health/live"
    assert container["readinessProbe"]["httpGet"]["path"] == "/health/ready"


def test_base_manifests_do_not_require_a_gpu() -> None:
    """The base must schedule on a CPU-only cluster; GPU is an overlay."""
    for label, pod in _pod_specs():
        container = pod["containers"][0]
        assert "runtimeClassName" not in pod, label
        assert "nodeSelector" not in pod, label
        assert "tolerations" not in pod, label
        for section in ("requests", "limits"):
            assert "nvidia.com/gpu" not in container["resources"][section], label
        env_names = {item["name"] for item in container.get("env", [])}
        assert not any(name.startswith("NVIDIA_") for name in env_names), label


def test_gpu_overlay_adds_nvidia_scheduling_to_the_deployment() -> None:
    overlay = yaml.safe_load((K8S_ROOT / "overlays" / "gpu" / "kustomization.yaml").read_text())
    patch_name = overlay["patches"][0]["path"]
    patch = yaml.safe_load((K8S_ROOT / "overlays" / "gpu" / patch_name).read_text())
    pod = patch["spec"]["template"]["spec"]

    assert overlay["resources"] == ["../../base"]
    assert patch["kind"] == "Deployment"
    assert pod["runtimeClassName"] == "nvidia"
    assert pod["containers"][0]["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert pod["nodeSelector"] == {"nvidia.com/gpu.present": "true"}


def test_security_context_is_kept() -> None:
    for label, pod in _app_pod_specs():
        assert pod["securityContext"]["runAsUser"] == 1000, label
        assert pod["securityContext"]["fsGroup"] == 1000, label
        assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault", label
        container = pod["containers"][0]
        assert container["securityContext"]["readOnlyRootFilesystem"] is True, label
        assert container["securityContext"]["capabilities"]["drop"] == ["ALL"], label
        assert container["securityContext"]["allowPrivilegeEscalation"] is False, label


def _pod_spec(path: Path) -> dict:
    deployment = next(doc for doc in _yaml_docs(path) if doc["kind"] == "Deployment")
    return deployment["spec"]["template"]["spec"]


def _overlay_deployment_pod_specs() -> list[tuple[str, dict]]:
    """Every standalone Deployment shipped under overlays/ (not a strategic-merge patch).

    A patch (deployment-gpu.yaml, deployment-cuda.yaml, deployment-database-env.yaml)
    only sets the fields it changes and inherits the rest from base, so it is exempt:
    base already carries enableServiceLinks: false and the merge keeps it. A file that
    is a Deployment in its own right — inference and captioner — ships nothing from
    base and must set the field itself.
    """
    specs = []
    for path in sorted((K8S_ROOT / "overlays").glob("*/deployment.yaml")):
        for doc in _yaml_docs(path):
            if doc.get("kind") == "Deployment":
                specs.append((str(path.relative_to(REPO_ROOT)), doc["spec"]["template"]["spec"]))
    return specs


def test_every_shipped_pod_disables_kubernetes_service_links() -> None:
    """A Service named after a Deployment injects an env var per Service in the
    namespace by default (SERVICE_HOST, SERVICE_PORT...), and this app's own env
    prefix collides with its own Service name: `immich-memories-render-worker`
    injects IMMICH_MEMORIES_RENDER_WORKER_PORT=tcp://<ip>:8093, which pydantic-settings
    then fails to parse as the worker's `port` field ("Input should be a valid
    integer"). The app and the inference service carry the same risk under their
    own IMMICH_MEMORIES_*/IMMICH_MEMORIES_INFERENCE_* prefixes (#1608).
    """
    worker = _pod_spec(REPO_ROOT / "services" / "render-worker" / "kubernetes.yaml")
    pods = [
        *_pod_specs(),
        ("services/render-worker/kubernetes.yaml", worker),
        *_overlay_deployment_pod_specs(),
    ]
    assert len(pods) >= 6, pods  # sanity: base (Deployment+Job+2 CronJobs), worker, 2 overlays

    for label, pod in pods:
        assert pod.get("enableServiceLinks") is False, label


def test_no_shipped_pod_mounts_a_kubernetes_api_token() -> None:
    """Nothing the app, the worker or a sidecar runs calls the Kubernetes API, so a
    compromised process should not find a service-account token on disk either."""
    worker = _pod_spec(REPO_ROOT / "services" / "render-worker" / "kubernetes.yaml")
    pods = [
        *_pod_specs(),
        ("services/render-worker/kubernetes.yaml", worker),
        *_overlay_deployment_pod_specs(),
    ]

    for label, pod in pods:
        assert pod.get("automountServiceAccountToken") is False, label
    for name in ("main.tf", "captioner.tf"):
        terraform = (TF_DIR / name).read_text()
        assert terraform.count("automount_service_account_token = false") == terraform.count(
            "enable_service_links"
        ), name


def test_trigger_pods_keep_a_minimal_security_context() -> None:
    """The curl pod (#871) never touches the store, but it keeps the same hardening.

    No `fsGroup` here on purpose: that field exists to make a mounted volume
    group-writable, and a trigger pod mounts nothing (see
    test_trigger_pods_mount_no_store_volumes).
    """
    trigger_pods = _trigger_pod_specs()
    assert trigger_pods, "expected at least one trigger CronJob in job.yaml"
    for label, pod in trigger_pods:
        assert pod["securityContext"]["runAsNonRoot"] is True, label
        assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault", label
        container = pod["containers"][0]
        assert container["securityContext"]["readOnlyRootFilesystem"] is True, label
        assert container["securityContext"]["capabilities"]["drop"] == ["ALL"], label
        assert container["securityContext"]["allowPrivilegeEscalation"] is False, label


def test_trigger_pods_mount_no_store_volumes() -> None:
    """The corruption guard #871 asks for: no PVC, so no second writer on the store."""
    trigger_pods = _trigger_pod_specs()
    assert trigger_pods, "expected at least one trigger CronJob in job.yaml"
    for label, pod in trigger_pods:
        assert "volumes" not in pod, label
        assert "volumeMounts" not in pod["containers"][0], label


def test_trigger_pods_pin_the_curl_image_by_digest() -> None:
    for label, pod in _trigger_pod_specs():
        image = pod["containers"][0]["image"]
        assert re.search(r"@sha256:[0-9a-f]{64}$", image), label


def test_trigger_pods_read_the_token_from_a_secret() -> None:
    for label, pod in _trigger_pod_specs():
        env = {item["name"]: item for item in pod["containers"][0].get("env", [])}
        key_ref = env["TRIGGER_TOKEN"]["valueFrom"]["secretKeyRef"]
        assert key_ref["key"] == "IMMICH_MEMORIES_SERVER__TRIGGER_TOKEN", label


def test_trigger_pods_call_the_in_cluster_trigger_route() -> None:
    """The URL, and the path it hits, are the real contract `web/trigger.py` serves."""
    from immich_memories.web.trigger import TRIGGER_PATH

    for label, pod in _trigger_pod_specs():
        command = " ".join(pod["containers"][0]["command"])
        assert f"http://immich-memories{TRIGGER_PATH}" in command, label


def test_network_policy_allows_the_immich_port() -> None:
    policy = _yaml_docs(K8S_DIR / "networkpolicy.yaml")[0]
    egress_ports = {
        port["port"] for rule in policy["spec"]["egress"] for port in rule.get("ports", [])
    }

    assert IMMICH_PORT in egress_ports
    assert 3001 not in egress_ports


def test_service_file_ships_no_ingress() -> None:
    """Auth is off by default; an Ingress must be an explicit opt-in."""
    kinds = {doc["kind"] for doc in _yaml_docs(K8S_DIR / "service.yaml")}
    resources = _kustomization()["resources"]

    assert kinds == {"Service"}
    assert not any(name.startswith("ingress") for name in resources)
    assert (K8S_DIR / "ingress.yaml.example").exists()


def test_batch_jobs_use_realistic_durations_and_current_flags() -> None:
    """`--duration` is seconds: 10 produced a ten-second video.

    The scheduled CronJobs no longer pass `--cooldown`: they call the trigger
    route, which takes its cooldown from `automation.cooldown_hours` (#871).
    """
    text = (K8S_DIR / "job.yaml").read_text()

    for match in re.finditer(r"--duration\s+\"?(\d+)", text):
        assert int(match.group(1)) >= 60, match.group(0)
    assert "--cooldown" not in text
    assert "/output/" not in text.replace(OUTPUT_DIR, "")


def test_no_stale_config_keys_or_paths_survive_in_deploy_files() -> None:
    stale = (
        "appuser",
        "PIXABAY",
        "OLLAMA_URL",
        "ollama_url",
        "ollama_model",
        "content_analysis.provider",
        "CONTENT_ANALYSIS__ENABLED",
        'provider = "auto"',
        "hardware_backend",
        "target_duration_seconds",
        "output_orientation",
        "v1.0.0",
        "3001",
        "0.2.0",
    )
    for name, text in _deploy_texts().items():
        for needle in stale:
            assert needle not in text, f"{needle!r} in {name}"


def test_terraform_module_defaults_to_cpu_and_writable_state() -> None:
    variables = (TF_DIR / "variables.tf").read_text()
    main = (TF_DIR / "main.tf").read_text()

    gpu_default = re.search(r'variable "gpu_enabled"[^}]*default\s*=\s*(\w+)', variables, re.S)
    assert gpu_default and gpu_default.group(1) == "false"
    assert f'"{CONFIG_DIR}"' in main
    assert f'"{OUTPUT_DIR}"' in main
    # The one legitimate exception: install-config's config-src mount is a
    # ConfigMap, meant to be read-only. Every `read_only = true` in the file
    # must be that one mount -- the data/output/models mounts stay writable.
    for match in re.finditer(r"read_only\s*=\s*true", main):
        nearby = main[max(0, match.start() - 120) : match.start()]
        assert "config-src" in nearby, nearby
    assert "IMMICH_MEMORIES_OUTPUT__DIRECTORY" in main
    probe_paths = re.findall(r'http_get \{\s*path\s*=\s*"([^"]+)"', main)
    assert probe_paths == ["/health/live", "/health/ready"]
    assert 'dynamic "node_selector"' not in main
    # config_yaml (deploy/terraform/captioner.tf's kubernetes_config_map_v1.config)
    # is opt-in: the default "" ships no ConfigMap at all, so the base module
    # stays env-var only unless a caller sets it (test_terraform_config_yaml_
    # ships_no_configmap_by_default covers the plan-time side of this).
    config_yaml_default = re.search(
        r'variable "config_yaml"[^}]*default\s*=\s*(".*?")', variables, re.S
    )
    assert config_yaml_default and config_yaml_default.group(1) == '""'


def test_terraform_examples_only_set_declared_variables() -> None:
    declared = set(re.findall(r'variable "(\w+)"', (TF_DIR / "variables.tf").read_text()))
    for example in ("basic", "production", "maximalist"):
        example_dir = TF_DIR / "examples" / example
        example_vars = set(
            re.findall(r'variable "(\w+)"', (example_dir / "variables.tf").read_text())
        )
        tfvars = (example_dir / "terraform.tfvars.example").read_text()
        assigned = set(re.findall(r"(?m)^(\w+)\s*=", tfvars))
        assert assigned <= example_vars, f"{example}: {sorted(assigned - example_vars)}"
        module_block = re.search(
            r'module "immich_memories" \{\n(.*?)\n\}', (example_dir / "main.tf").read_text(), re.S
        )
        assert module_block, example
        module_args = set(re.findall(r"(?m)^  (\w+)\s*=", module_block.group(1)))
        assert module_args - {"source"} <= declared, f"{example}: {sorted(module_args - declared)}"


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
@pytest.mark.parametrize("target", ["base", "overlays/gpu"])
def test_kustomize_renders_with_a_secret_created_from_the_example(
    tmp_path: Path, target: str
) -> None:
    """The documented quick start: copy the secret example, then `kubectl apply -k`."""
    workdir = tmp_path / "kubernetes"
    shutil.copytree(K8S_ROOT, workdir)
    shutil.copy(workdir / "base" / "secret.yaml.example", workdir / "base" / "secret.yaml")

    result = subprocess.run(
        ["kubectl", "kustomize", str(workdir / target)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    rendered = list(yaml.safe_load_all(result.stdout))
    kinds = {doc["kind"] for doc in rendered}
    assert {"Namespace", "Secret", "PersistentVolumeClaim", "Deployment", "Service"} <= kinds
    assert "Ingress" not in kinds
    deployment = next(doc for doc in rendered if doc["kind"] == "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert re.fullmatch(
        r"ghcr\.io/sam-dumont/immich-video-memory-generator:\d+\.\d+\.\d+", container["image"]
    )
    has_gpu = "nvidia.com/gpu" in container["resources"]["limits"]
    assert has_gpu == (target == "overlays/gpu")


def _kustomize(path: Path) -> list[dict]:
    result = subprocess.run(
        ["kubectl", "kustomize", str(path)], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
@pytest.mark.parametrize("target", ["overlays/inference", "overlays/inference-cuda"])
def test_inference_overlays_build_without_the_secret(target: str) -> None:
    """The inference service holds no credential, so its overlay must not need base/secret.yaml."""
    rendered = _kustomize(K8S_ROOT / target)

    assert "Secret" not in {doc["kind"] for doc in rendered}
    deployment = next(doc for doc in rendered if doc["kind"] == "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert container["ports"][0]["containerPort"] == CAPTION_PORT
    cuda = target.endswith("-cuda")
    assert ("nvidia.com/gpu" in container["resources"]["limits"]) == cuda
    assert container["image"].endswith("-cuda") == cuda


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
@pytest.mark.parametrize("target", ["overlays/inference", "overlays/inference-cuda"])
def test_the_inference_pod_can_write_everywhere_it_downloads_to(target: str) -> None:
    """readOnlyRootFilesystem plus a Hugging Face cache under $HOME is how a cold
    PVC answered 503 to every request: the snapshot download had nowhere to land."""
    deployment = next(doc for doc in _kustomize(K8S_ROOT / target) if doc["kind"] == "Deployment")
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]
    env = {entry["name"]: entry.get("value") for entry in container["env"]}
    mounts = {mount["mountPath"]: mount["name"] for mount in container["volumeMounts"]}
    volumes = {volume["name"]: volume for volume in pod["volumes"]}

    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert env["TMPDIR"] == "/tmp"
    assert "emptyDir" in volumes[mounts["/tmp"]]
    # One variable covers the hub, xet and assets caches: huggingface_hub derives
    # all three from HF_HOME unless each is named separately.
    assert env["HF_HOME"] == "/cache/huggingface"
    assert "persistentVolumeClaim" in volumes[mounts["/cache"]]


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_lan_overlay_adds_a_service_and_changes_nothing_else() -> None:
    """A patch on the ClusterIP Service would put every in-cluster caller on an external address."""
    rendered = _kustomize(K8S_ROOT / "overlays/inference-lan")

    assert [doc["kind"] for doc in rendered] == ["Service"]
    service = rendered[0]
    assert service["metadata"]["name"] == "inference-lan"
    assert service["spec"]["type"] == "LoadBalancer"
    assert service["spec"]["ports"][0]["port"] == CAPTION_PORT
    # Same pods as the ClusterIP Service, which keeps its own name and type.
    assert service["spec"]["selector"] == {"app.kubernetes.io/name": "immich-memories-inference"}


def test_every_pod_can_reach_the_pinned_encoder_and_the_detector_cache() -> None:
    """A first cut stops without the encoder, and the root filesystem is read-only."""
    for label, pod in _app_pod_specs():
        for container in pod.get("initContainers", []) + pod["containers"]:
            where = f"{label}:{container['name']}"
            mounts = {mount["name"]: mount["mountPath"] for mount in container["volumeMounts"]}
            env = {entry["name"]: entry.get("value") for entry in container["env"]}

            assert mounts.get("models") == MODELS_DIR, where
            for key in MODEL_PATH_ENV:
                assert env[key].startswith(f"{MODELS_DIR}/"), f"{where}: {key}"


def test_every_pod_fetches_the_pinned_models_before_its_first_cut() -> None:
    """A fresh models claim holds nothing, and prepare is where that surfaces.

    The pod came up, the cut ran, and it stopped naming three files nobody had
    told the operator to fetch. The init step is the same image running the same
    `models fetch` the docs give a Docker user, so an empty claim fills itself
    and a warm one costs a `test`.
    """
    for label, pod in _app_pod_specs():
        fetch = next(
            (item for item in pod.get("initContainers", []) if item["name"] == "fetch-models"),
            None,
        )
        assert fetch, label
        assert fetch["image"] == pod["containers"][0]["image"], label
        script = " ".join(fetch["command"])
        assert "immich-memories models fetch" in script, label
        # Idempotent: a claim that already carries all three is left alone, so a
        # restart and a nightly CronJob do not go back to the network.
        assert script.count("test -") == len(MODEL_PATH_ENV), label
        mounts = {mount["mountPath"] for mount in fetch["volumeMounts"]}
        assert {MODELS_DIR, CONFIG_DIR} <= mounts, label


def test_network_policy_allows_the_caption_endpoint() -> None:
    """The shipped policy used to block the caption port this app documents by default."""
    policy = _yaml_docs(K8S_DIR / "networkpolicy.yaml")[0]
    egress_ports = {
        port["port"] for rule in policy["spec"]["egress"] for port in rule.get("ports", [])
    }

    assert {CAPTION_PORT, 11434} <= egress_ports


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_captioner_overlay_serves_the_alias_the_app_demands() -> None:
    """`tier: full` refuses any endpoint that advertises something else at /models.

    Three flags carry the whole contract, and each has a failure that looks like
    something else: no `--alias` and preflight reads "serves another model", no
    `--mmproj` and every picture is described as if it were blank.
    """
    from immich_memories.analysis.editorial_description_contract import API_MODEL

    rendered = _kustomize(K8S_ROOT / "overlays/captioner")

    assert "Secret" not in {doc["kind"] for doc in rendered}
    deployment = next(doc for doc in rendered if doc["kind"] == "Deployment")
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]
    args = container["args"]

    assert container["ports"][0]["containerPort"] == CAPTION_PORT
    assert args[args.index("--alias") + 1] == API_MODEL
    assert args[args.index("--mmproj") + 1].startswith(f"{MODELS_DIR}/mmproj-")
    assert "--jinja" in args
    assert "nvidia.com/gpu" not in container["resources"]["limits"]

    service = next(doc for doc in rendered if doc["kind"] == "Service")
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["ports"][0]["port"] == CAPTION_PORT


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_captioner_init_container_pins_the_weights_it_downloads() -> None:
    """llama-server serves whatever file is at the path, so the digest is the only pin."""
    rendered = _kustomize(K8S_ROOT / "overlays/captioner")
    deployment = next(doc for doc in rendered if doc["kind"] == "Deployment")
    pod = deployment["spec"]["template"]["spec"]
    init = pod["initContainers"][0]
    script = "\n".join(init["args"])

    assert CAPTION_GGUF_REVISION in script
    for digest in CAPTION_GGUF_SHA256:
        assert digest in script
    assert "sha256sum -c" in script
    # The serving container mounts the same claim read-only: nothing rewrites a
    # verified file after the check.
    assert next(m for m in pod["containers"][0]["volumeMounts"] if m["name"] == "models")[
        "readOnly"
    ]


def _captioner_pod(target: str) -> dict:
    deployment = next(doc for doc in _kustomize(K8S_ROOT / target) if doc["kind"] == "Deployment")
    return deployment["spec"]["template"]["spec"]


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_cuda_captioner_is_the_cpu_recipe_with_the_layers_offloaded() -> None:
    """Same weights, same alias, same port. What changes is where the layers run.

    Restating the args in the patch is how the two recipes drift apart, so the
    overlay appends to them and this is what it must come out as: the CPU list,
    in its own order, with the offload flag on the end.
    """
    cpu, cuda = _captioner_pod("overlays/captioner"), _captioner_pod("overlays/captioner-cuda")
    on_cpu, on_gpu = cpu["containers"][0], cuda["containers"][0]

    assert on_gpu["args"] == [*on_cpu["args"], "--n-gpu-layers", "99"]
    assert on_gpu["image"] == f"{on_cpu['image'].split(':')[0]}:server-cuda"
    # One image on the node, not two: the init container only curls and hashes,
    # so it has no reason to pull the CPU build beside a CUDA one.
    assert cuda["initContainers"][0]["image"] == on_gpu["image"]


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_cuda_captioner_takes_a_card_without_holding_an_allocatable_slot() -> None:
    """No `nvidia.com/gpu` request, deliberately, and the overlay says why.

    A time-sliced card has one allocatable slot per node and the inference
    Deployment holds it. Requesting a second one leaves the captioner Pending
    forever on the cluster this was measured on, so it takes the device through
    the runtime class instead and shares.
    """
    pod = _captioner_pod("overlays/captioner-cuda")
    container = pod["containers"][0]
    env = {entry["name"]: entry["value"] for entry in container["env"]}

    assert pod["runtimeClassName"] == "nvidia"
    assert pod["nodeSelector"]["nvidia.com/gpu.present"] == "true"
    assert {"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"} in pod[
        "tolerations"
    ]
    assert env["NVIDIA_VISIBLE_DEVICES"] == "all"
    # No `video`: the captioner decodes no stream and encodes nothing.
    assert env["NVIDIA_DRIVER_CAPABILITIES"] == "compute,utility"
    resources = container["resources"]
    assert "nvidia.com/gpu" not in resources["limits"]
    assert "nvidia.com/gpu" not in resources["requests"]


def _render_sidecar_pod(tmp_path: Path) -> dict:
    """Build overlays/render-sidecar with both secret examples copied in.

    The overlay needs base/secret.yaml (Immich credentials) and its own
    render-worker-secret.yaml (the bearer token both containers share), same
    as the documented quick start in kubernetes.md.
    """
    workdir = tmp_path / "kubernetes"
    shutil.copytree(K8S_ROOT, workdir)
    shutil.copy(workdir / "base" / "secret.yaml.example", workdir / "base" / "secret.yaml")
    shutil.copy(
        workdir / "overlays" / "render-sidecar" / "render-worker-secret.yaml.example",
        workdir / "overlays" / "render-sidecar" / "render-worker-secret.yaml",
    )
    result = subprocess.run(
        ["kubectl", "kustomize", str(workdir / "overlays" / "render-sidecar")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    rendered = list(yaml.safe_load_all(result.stdout))
    deployment = next(doc for doc in rendered if doc["kind"] == "Deployment")
    return deployment["spec"]["template"]["spec"]


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_render_sidecar_overlay_points_the_app_at_loopback(tmp_path: Path) -> None:
    """The whole point of the sidecar: no TLS, no `allow_insecure_http`.

    The app refuses a cleartext-HTTP render.worker_base_url to any host but
    loopback, because the request carries the Immich API key
    (config_models_render.py: require_explicit_cleartext_transport). Sharing
    a pod puts the worker on 127.0.0.1, where that rule already allows plain
    HTTP.
    """
    pod = _render_sidecar_pod(tmp_path)
    app = next(c for c in pod["containers"] if c["name"] == "immich-memories")
    env = {item["name"]: item for item in app["env"]}

    assert env["IMMICH_MEMORIES_RENDER__WORKER_BASE_URL"]["value"] == "http://127.0.0.1:8093"
    token_ref = env["IMMICH_MEMORIES_RENDER__WORKER_TOKEN"]["valueFrom"]["secretKeyRef"]
    assert token_ref == {"name": "immich-memories-render-worker", "key": "token"}


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_render_sidecar_overlay_schedules_the_whole_pod_on_a_gpu_node(
    tmp_path: Path,
) -> None:
    """The app itself needs no GPU, but sharing a pod with the worker moves it there too."""
    pod = _render_sidecar_pod(tmp_path)
    worker = next(c for c in pod["containers"] if c["name"] == "render-worker")

    assert pod["runtimeClassName"] == "nvidia"
    assert pod["nodeSelector"]["nvidia.com/gpu.present"] == "true"
    assert {"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"} in pod[
        "tolerations"
    ]
    assert worker["resources"]["limits"]["nvidia.com/gpu"] == "1"


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_render_sidecar_overlay_pins_both_containers_to_the_same_release(
    tmp_path: Path,
) -> None:
    """The app refuses a worker on a different app version before sending any footage."""
    pod = _render_sidecar_pod(tmp_path)
    images = {c["name"]: c["image"] for c in pod["containers"]}

    assert images["immich-memories"] == images["render-worker"]
    assert re.fullmatch(
        r"ghcr\.io/sam-dumont/immich-video-memory-generator:\d+\.\d+\.\d+",
        images["render-worker"],
    )


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_render_sidecar_overlay_worker_container_is_hardened(tmp_path: Path) -> None:
    pod = _render_sidecar_pod(tmp_path)
    worker = next(c for c in pod["containers"] if c["name"] == "render-worker")

    assert worker["securityContext"]["allowPrivilegeEscalation"] is False
    assert worker["securityContext"]["readOnlyRootFilesystem"] is True
    assert worker["securityContext"]["capabilities"]["drop"] == ["ALL"]
    mounted = {mount["mountPath"] for mount in worker["volumeMounts"]}
    assert {"/tmp", "/home/immich/.immich-memories", "/home/immich/.cache"} <= mounted


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_render_sidecar_worker_probes_run_inside_the_container(tmp_path: Path) -> None:
    """tcpSocket and httpGet both dial the pod IP, never 127.0.0.1 -- the kubelet makes
    the call, not a process inside the container. This worker binds loopback only, so
    either kind of probe fails forever and the pod never goes Ready (reproduced live).
    exec runs inside the worker's own network namespace instead, where loopback is
    reachable, and it must carry the bearer token /health sits behind.
    """
    pod = _render_sidecar_pod(tmp_path)
    worker = next(c for c in pod["containers"] if c["name"] == "render-worker")

    for probe_name in ("startupProbe", "readinessProbe"):
        probe = worker[probe_name]
        assert "tcpSocket" not in probe, probe_name
        assert "httpGet" not in probe, probe_name
        command = probe["exec"]["command"]
        assert command[0] == "python3", probe_name
        script = command[-1]
        assert "127.0.0.1:8093/health" in script, probe_name
        assert "IMMICH_MEMORIES_RENDER_WORKER_TOKEN" in script, probe_name
        assert "Bearer" in script, probe_name


def _maximalist_rendered(tmp_path: Path) -> list[dict]:
    """Build overlays/maximalist with all three secret examples copied in.

    The overlay composes overlays/render-sidecar (base + render-worker-secret)
    and overlays/captioner-cuda, and adds its own maximalist-secret for the
    OIDC/LLM/ACE-Step values config-map.yaml's config.yaml expands with ${VAR}.
    """
    workdir = tmp_path / "kubernetes"
    shutil.copytree(K8S_ROOT, workdir)
    shutil.copy(workdir / "base" / "secret.yaml.example", workdir / "base" / "secret.yaml")
    shutil.copy(
        workdir / "overlays" / "render-sidecar" / "render-worker-secret.yaml.example",
        workdir / "overlays" / "render-sidecar" / "render-worker-secret.yaml",
    )
    shutil.copy(
        workdir / "overlays" / "maximalist" / "maximalist-secret.yaml.example",
        workdir / "overlays" / "maximalist" / "maximalist-secret.yaml",
    )
    result = subprocess.run(
        ["kubectl", "kustomize", str(workdir / "overlays" / "maximalist")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return list(yaml.safe_load_all(result.stdout))


def _maximalist_pod(tmp_path: Path) -> dict:
    deployment = next(
        doc
        for doc in _maximalist_rendered(tmp_path)
        if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "immich-memories"
    )
    return deployment["spec"]["template"]["spec"]


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_maximalist_overlay_builds(tmp_path: Path) -> None:
    """The documented quick start: three secret examples copied in, then apply -k."""
    rendered = _maximalist_rendered(tmp_path)
    kinds = {doc["kind"] for doc in rendered}
    assert {"Deployment", "ConfigMap", "Secret", "PersistentVolumeClaim", "Service"} <= kinds


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_maximalist_overlay_disables_service_links_everywhere(tmp_path: Path) -> None:
    """Every pod the overlay ships, not just the app's own: the captioner too (#1608)."""
    rendered = _maximalist_rendered(tmp_path)
    pod_specs = [doc["spec"]["template"]["spec"] for doc in rendered if doc["kind"] == "Deployment"]
    assert pod_specs, "expected at least one Deployment in the rendered overlay"
    for spec in pod_specs:
        assert spec["enableServiceLinks"] is False


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_maximalist_overlay_keeps_the_render_worker_exec_probes(tmp_path: Path) -> None:
    """Composing render-sidecar must not lose the loopback-only exec probes
    (tcpSocket/httpGet both dial the pod IP, never 127.0.0.1, so a worker bound
    to loopback only would never go Ready with either)."""
    pod = _maximalist_pod(tmp_path)
    worker = next(c for c in pod["containers"] if c["name"] == "render-worker")

    for probe_name in ("startupProbe", "readinessProbe"):
        probe = worker[probe_name]
        assert "tcpSocket" not in probe, probe_name
        assert "httpGet" not in probe, probe_name
        assert "127.0.0.1:8093/health" in probe["exec"]["command"][-1], probe_name


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_maximalist_overlay_installs_config_yaml_at_0600(tmp_path: Path) -> None:
    """A ConfigMap volume mounts every key world-readable with no way to chmod it,
    which is exactly what config_loader.py warns on. install-config copies the
    file onto the writable cache PVC, as the app's own uid, and chmods it there."""
    pod = _maximalist_pod(tmp_path)
    init = next(c for c in pod["initContainers"] if c["name"] == "install-config")

    assert init["securityContext"]["runAsUser"] == 1000
    script = init["command"][-1]
    assert "chmod 600" in script
    assert "/home/immich/.immich-memories/config.yaml" in script
    mounts = {m["mountPath"]: m for m in init["volumeMounts"]}
    assert mounts["/config-src"]["readOnly"] is True
    assert not mounts["/home/immich/.immich-memories"].get("readOnly")

    volumes = {v["name"]: v for v in pod["volumes"]}
    config_src = volumes[mounts["/config-src"]["name"]]
    assert config_src["configMap"]["name"] == "immich-memories-config"

    # The base's own fetch-models init container must still be there: this
    # overlay appends, it does not replace.
    assert {c["name"] for c in pod["initContainers"]} >= {"install-config", "fetch-models"}


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_maximalist_overlay_config_yaml_carries_every_advertised_feature(
    tmp_path: Path,
) -> None:
    """The table in docs-site/docs/run/reference-setup.md promises these config keys;
    pin the ConfigMap content so a rename or a dropped key is caught here first."""
    rendered = _maximalist_rendered(tmp_path)
    config_map = next(doc for doc in rendered if doc["kind"] == "ConfigMap")
    config_yaml = yaml.safe_load(config_map["data"]["config.yaml"])

    assert config_yaml["tier"] == "full"
    assert config_yaml["network"]["geocoding"] is True
    assert config_yaml["network"]["map_tiles"] is True
    # Deliberately below the app's own 10+10 GB defaults, to fit the 10Gi PVC
    # this reference setup ships (test_..._cache_pvc_fits_its_own_cache_caps
    # covers the PVC side of this).
    assert 0 < config_yaml["cache"]["video_cache_max_size_gb"] < 10
    assert 0 < config_yaml["cache"]["thumbnail_cache_max_size_mb"] < 10_000

    advanced = config_yaml["advanced"]
    auth = advanced["auth"]
    assert auth["provider"] == "oidc"
    assert auth["public_url"].startswith("https://")
    assert auth["trusted_proxies"]
    assert advanced["server"]["secure_cookies"] is True
    assert advanced["editorial"]["preparation"]["caption_base_url"] == "http://captioner:8092/v1"
    assert advanced["llm"]["provider"] == "openai-compatible"
    assert advanced["ace_step"]["enabled"] is True
    assert advanced["ace_step"]["mode"] == "api"
    assert advanced["automation"]["enabled"] is True


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_maximalist_overlay_cache_pvc_fits_its_own_cache_caps(tmp_path: Path) -> None:
    """The reference setup's caps (5 GB video + 3 GB thumbnails) sit inside the base's
    20Gi cache PVC, which the overlay keeps: a bound claim cannot shrink, so an overlay
    that sized it down would fail over an existing install. Whichever way a reader
    changes the caps, the PVC must still hold config.yaml/store.db/automation history
    on top of both of them."""
    rendered = _maximalist_rendered(tmp_path)
    config_map = next(doc for doc in rendered if doc["kind"] == "ConfigMap")
    config_yaml = yaml.safe_load(config_map["data"]["config.yaml"])
    cache_caps_gb = config_yaml["cache"]["video_cache_max_size_gb"] + (
        config_yaml["cache"]["thumbnail_cache_max_size_mb"] / 1000
    )

    pvc = next(
        doc
        for doc in rendered
        if doc["kind"] == "PersistentVolumeClaim"
        and doc["metadata"]["name"] == "immich-memories-cache"
    )
    storage = pvc["spec"]["resources"]["requests"]["storage"]
    assert storage.endswith("Gi")
    assert int(storage[:-2]) > cache_caps_gb


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_maximalist_overlay_reuses_the_cuda_captioner_overlay(tmp_path: Path) -> None:
    """Composed, not duplicated: the same weights, alias and n-gpu-layers patch
    as overlays/captioner-cuda on its own (test_the_cuda_captioner_is_the_cpu_recipe_
    with_the_layers_offloaded covers that overlay directly)."""
    rendered = _maximalist_rendered(tmp_path)
    captioner = next(
        doc
        for doc in rendered
        if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "immich-memories-captioner"
    )
    container = captioner["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "ghcr.io/ggml-org/llama.cpp:server-cuda"
    assert container["args"][-2:] == ["--n-gpu-layers", "99"]


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_maximalist_overlay_pins_or_digests_every_third_party_image(tmp_path: Path) -> None:
    """Every image this overlay pulls is either this repo's own release tag
    (rewritten by the kustomization's images: transformer, checked elsewhere by
    test_only_the_kustomization_pin_names_a_concrete_version) or a third-party
    image pinned by digest or a named, documented floating tag -- never `latest`
    on an image this repo does not publish."""
    rendered = _maximalist_rendered(tmp_path)
    own_repo = "ghcr.io/sam-dumont/immich-video-memory-generator"
    for doc in rendered:
        spec = doc.get("spec", {}).get("template", {}).get("spec")
        if not spec:
            continue
        for container in spec.get("initContainers", []) + spec.get("containers", []):
            image = container["image"]
            if image.startswith(own_repo):
                # A release tag; the inference service's CUDA build is published as `X.Y.Z-cuda`.
                assert re.search(r":\d+\.\d+\.\d+(-cuda)?$", image), image
            else:
                # Third-party: llama.cpp's documented floating server/server-cuda
                # tag, or a sha256 digest. Never a bare `latest`.
                assert image != "latest", image
                assert "@sha256:" in image or re.search(r":server(-cuda)?$", image), image


# ── Terraform mirror of the same maximalist reference ──────────────────────
#
# deploy/terraform/{main,variables,captioner}.tf and
# deploy/terraform/examples/maximalist express the same features as
# overlays/maximalist: render worker sidecar, CUDA captioner, OIDC behind a
# proxy, config.yaml a ConfigMap can own, LAN LLM/ACE-Step, network and cache
# caps. Every new variable defaults to the minimal path (off/empty), checked
# statically here; test_terraform_module_defaults_to_cpu_and_writable_state
# covers the pre-existing gpu_enabled/config_yaml defaults.


def test_terraform_maximalist_variables_default_to_the_minimal_path() -> None:
    variables = (TF_DIR / "variables.tf").read_text()
    off_by_default = (
        "render_worker_sidecar_enabled",
        "captioner_enabled",
        "captioner_cuda",
        "oidc_enabled",
        "ace_step_enabled",
        "network_geocoding",
        "network_map_tiles",
        "secure_cookies",
    )
    for name in off_by_default:
        match = re.search(rf'variable "{name}"[^}}]*default\s*=\s*(\w+)', variables, re.S)
        assert match and match.group(1) == "false", name

    empty_by_default = (
        "oidc_issuer_url",
        "oidc_client_id",
        "oidc_public_url",
        "render_worker_token",
    )
    for name in empty_by_default:
        match = re.search(rf'variable "{name}"[^}}]*default\s*=\s*(".*?")', variables, re.S)
        assert match and match.group(1) == '""', name


def test_terraform_render_worker_sidecar_mirrors_the_kubernetes_overlay() -> None:
    """Same contract as overlays/render-sidecar: loopback, no TLS, no
    render.allow_insecure_http, GPU scheduling implied even without gpu_enabled."""
    main = (TF_DIR / "main.tf").read_text()
    assert 'IMMICH_MEMORIES_RENDER__WORKER_BASE_URL = "http://127.0.0.1:8093"' in main
    assert "IMMICH_MEMORIES_RENDER__WORKER_TOKEN" in main
    assert "var.gpu_enabled || var.render_worker_sidecar_enabled" in main
    # The kubelet dials the pod IP for tcpSocket/httpGet, never 127.0.0.1, so a
    # worker bound to loopback only needs an exec probe, same as the manifest.
    assert '"tcpSocket"' not in main
    assert "startup_probe" in main and "exec {" in main


def test_terraform_installs_config_yaml_at_0600_when_set() -> None:
    """Mirrors deploy/kubernetes/overlays/maximalist's install-config init
    container: a ConfigMap volume mounts every key world-readable with no way
    to chmod it, so this copies the file onto the writable cache PVC first."""
    main = (TF_DIR / "main.tf").read_text()
    assert "install-config" in main
    assert "chmod 600" in main
    assert 'for_each = var.config_yaml != "" ? [1] : []' in main
    captioner = (TF_DIR / "captioner.tf").read_text()
    assert 'count = var.config_yaml != "" ? 1 : 0' in captioner
    assert 'resource "kubernetes_config_map_v1" "config"' in captioner


def test_terraform_captioner_module_pins_the_same_weights_as_the_kubernetes_overlay() -> None:
    """One set of digests, not two that can drift apart."""
    captioner = (TF_DIR / "captioner.tf").read_text()
    assert CAPTION_GGUF_REVISION in captioner
    for digest in CAPTION_GGUF_SHA256:
        assert digest in captioner
    assert '"smolvlm2-500m-base-public"' in captioner
    assert 'var.captioner_cuda ? "ghcr.io/ggml-org/llama.cpp:server-cuda"' in captioner
    assert '"--n-gpu-layers", "99"' in captioner


def test_terraform_oidc_error_strings_are_the_ones_the_app_actually_raises() -> None:
    """The two failure modes docs-site/docs/run/reference-setup.md tells readers to
    search for; both must still be the literal strings the app produces."""
    auth_oidc = (REPO_ROOT / "src" / "immich_memories" / "web" / "auth_oidc.py").read_text()
    server = (REPO_ROOT / "src" / "immich_memories" / "web" / "server.py").read_text()
    assert "Invalid callback origin" in server
    # Without public_url, oidc_redirect_uri falls back to the request-derived
    # URL, and validate_callback_origin has nothing trustworthy to compare
    # against -- both documented right where the fallback happens.
    assert "forwarded headers are trusted" in auth_oidc
    assert "nothing trustworthy to compare against" in auth_oidc


def test_terraform_maximalist_example_sets_public_url_and_trusted_proxies() -> None:
    """oidc_enabled with neither set is exactly the misconfiguration
    docs-site/docs/run/reference-setup.md warns about."""
    example_main = (TF_DIR / "examples" / "maximalist" / "main.tf").read_text()
    assert "oidc_public_url" in example_main
    assert "oidc_trusted_proxies" in example_main
    assert "secure_cookies       = true" in example_main


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform not installed")
def test_terraform_module_and_maximalist_example_are_valid_hcl(tmp_path: Path) -> None:
    """terraform validate against the real provider schema, no live cluster
    needed. Runs in an isolated copy so init's .terraform/ never lands in the
    repo (a stray lock file has broken a test here before)."""
    workdir = tmp_path / "terraform"
    shutil.copytree(TF_DIR, workdir)
    for target in (workdir, workdir / "examples" / "maximalist"):
        init = subprocess.run(
            ["terraform", "init", "-backend=false", "-input=false"],
            cwd=target,
            check=False,
            capture_output=True,
            text=True,
        )
        assert init.returncode == 0, init.stdout + init.stderr
        result = subprocess.run(
            ["terraform", "validate"],
            cwd=target,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform not installed")
def test_terraform_deploy_tree_is_formatted() -> None:
    result = subprocess.run(
        ["terraform", "fmt", "-check", "-recursive", str(TF_DIR)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"needs `terraform fmt -recursive {TF_DIR}`:\n{result.stdout}"


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_maximalist_overlay_reads_pictures_on_a_gpu_and_points_the_app_at_it(
    tmp_path: Path,
) -> None:
    """`tier: full` in a pod that reads pictures on its CPU is the tier the file names, not
    what the install does: the reference setup ships the CUDA inference service (encoder,
    context heads, detectors) beside the app, and the app's config names it."""
    rendered = _maximalist_rendered(tmp_path)
    inference = next(
        doc
        for doc in rendered
        if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "immich-memories-inference"
    )
    pod = inference["spec"]["template"]["spec"]
    assert pod["runtimeClassName"] == "nvidia"
    assert pod["containers"][0]["image"].endswith("-cuda")

    config_map = next(doc for doc in rendered if doc["kind"] == "ConfigMap")
    config_yaml = yaml.safe_load(config_map["data"]["config.yaml"])
    assert config_yaml["advanced"]["inference"]["facts_base_url"] == "http://inference:8092"
