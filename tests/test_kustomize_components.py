"""App options compose into one rendered Kubernetes deployment."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1] / "deploy/kubernetes"
pytestmark = pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")


def _workspace(tmp_path):
    target = tmp_path / "kubernetes"
    shutil.copytree(ROOT, target)
    for example in target.rglob("*.yaml.example"):
        shutil.copyfile(example, example.with_suffix(""))
    return target


def _render(path):
    output = subprocess.check_output(["kubectl", "kustomize", str(path)], text=True)
    return [doc for doc in yaml.safe_load_all(output) if doc]


def test_gpu_and_postgres_components_share_one_base_without_losing_credentials(tmp_path):
    root = _workspace(tmp_path)
    setup = root / "composed"
    setup.mkdir()
    shutil.copyfile(root / "overlays/postgres/database-secret.yaml", setup / "database-secret.yaml")
    (setup / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
        "resources: [../base, database-secret.yaml]\n"
        "components: [../components/gpu, ../components/postgres]\n"
    )

    docs = _render(setup)
    deployments = [doc for doc in docs if doc["kind"] == "Deployment"]
    assert len(deployments) == 1
    pod = deployments[0]["spec"]["template"]["spec"]
    app = pod["containers"][0]
    assert pod["runtimeClassName"] == "nvidia"
    assert app["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert {source["secretRef"]["name"] for source in app["envFrom"]} == {
        "immich-memories-secrets",
        "immich-memories-database",
    }
    assert len([doc for doc in docs if doc["kind"] == "PersistentVolumeClaim"]) == 3


def test_postgres_and_render_sidecar_components_keep_both_credentials_and_loopback_transport(
    tmp_path,
):
    root = _workspace(tmp_path)
    setup = root / "composed"
    setup.mkdir()
    for directory, filename in (
        ("postgres", "database-secret.yaml"),
        ("render-sidecar", "render-worker-secret.yaml"),
    ):
        shutil.copyfile(root / "overlays" / directory / filename, setup / filename)
    (setup / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
        "resources: [../base, database-secret.yaml, render-worker-secret.yaml]\n"
        "components: [../components/postgres, ../components/render-sidecar]\n"
    )

    docs = _render(setup)
    deployments = [doc for doc in docs if doc["kind"] == "Deployment"]
    assert len(deployments) == 1
    containers = deployments[0]["spec"]["template"]["spec"]["containers"]
    assert {container["name"] for container in containers} == {"immich-memories", "render-worker"}
    app = next(container for container in containers if container["name"] == "immich-memories")
    assert {source["secretRef"]["name"] for source in app["envFrom"]} == {
        "immich-memories-secrets",
        "immich-memories-database",
    }
    env = {item["name"]: item.get("value") for item in app["env"]}
    assert env["IMMICH_MEMORIES_RENDER__WORKER_BASE_URL"] == "http://127.0.0.1:8093"
    assert env.get("IMMICH_MEMORIES_RENDER__ALLOW_INSECURE_HTTP", "false") == "false"


@pytest.mark.parametrize(
    "option,patch,secret",
    [
        ("gpu", "deployment-gpu.yaml", None),
        ("postgres", "deployment-database-env.yaml", "database-secret.yaml"),
        ("render-sidecar", "deployment-sidecar.yaml", "render-worker-secret.yaml"),
    ],
)
def test_compatibility_wrappers_render_exactly_like_their_former_app_patches(
    tmp_path, option, patch, secret
):
    root = _workspace(tmp_path)
    legacy = root / "legacy"
    legacy.mkdir()
    fixtures = Path(__file__).parent / "fixtures/kubernetes-legacy-app-patches"
    shutil.copyfile(fixtures / patch, legacy / patch)
    resources = ["../base"]
    if secret:
        shutil.copyfile(root / "overlays" / option / secret, legacy / secret)
        resources.append(secret)
    kustomization = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "resources": resources,
        "patches": [{"path": patch}],
    }
    if option == "render-sidecar":
        base = yaml.safe_load((root / "base/kustomization.yaml").read_text())
        kustomization["images"] = base["images"]
    (legacy / "kustomization.yaml").write_text(yaml.safe_dump(kustomization))

    def resources_by_identity(docs):
        return {
            (doc["kind"], doc["metadata"].get("namespace"), doc["metadata"]["name"]): doc
            for doc in docs
        }

    assert resources_by_identity(_render(root / "overlays" / option)) == resources_by_identity(
        _render(legacy)
    )


def test_components_preserve_optional_scheduled_trigger_security(tmp_path):
    root = _workspace(tmp_path)
    base = root / "base/kustomization.yaml"
    config = yaml.safe_load(base.read_text())
    config["resources"].append("job.yaml")
    # The split CronJob manifest is present after the deployment audit lands.
    if (root / "base/cronjobs.yaml").exists():
        config["resources"].append("cronjobs.yaml")
    base.write_text(yaml.safe_dump(config))
    before = [doc for doc in _render(root / "base") if doc["kind"] == "CronJob"]
    after = [doc for doc in _render(root / "overlays/gpu") if doc["kind"] == "CronJob"]
    assert len(after) == 2
    assert after == before
    for job in after:
        pod = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        assert pod["automountServiceAccountToken"] is False
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        for container in pod["containers"]:
            assert container["securityContext"]["allowPrivilegeEscalation"] is False
            assert container["securityContext"]["readOnlyRootFilesystem"] is True


def test_reader_egress_component_adds_port_without_replacing_existing_policy(tmp_path):
    root = _workspace(tmp_path)
    setup = root / "composed"
    setup.mkdir()
    (setup / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
        "resources: [../base]\ncomponents: [../components/reader-egress]\n"
    )
    original = next(doc for doc in _render(root / "base") if doc["kind"] == "NetworkPolicy")
    rendered = next(doc for doc in _render(setup) if doc["kind"] == "NetworkPolicy")
    assert rendered["spec"]["egress"][:-1] == original["spec"]["egress"]
    assert rendered["spec"]["egress"][-1] == {"ports": [{"port": 8000, "protocol": "TCP"}]}
    assert rendered["spec"]["ingress"] == original["spec"]["ingress"]
