"""Rendered deployment contracts for scheduled triggers and persistent storage."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1] / "deploy" / "kubernetes"


@pytest.fixture
def manifests(tmp_path):
    work = tmp_path / "kubernetes"
    shutil.copytree(ROOT, work)
    for example in work.rglob("*secret.yaml.example"):
        shutil.copy(example, example.with_suffix(""))
    return work


def render(root):
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not installed")
    result = subprocess.run(
        ["kubectl", "kustomize", str(root)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return list(yaml.safe_load_all(result.stdout))


def test_scheduled_trigger_can_reach_the_service_backend_port(manifests):
    resources = render(manifests / "base")
    service = next(row for row in resources if row["kind"] == "Service")
    deployment = next(row for row in resources if row["kind"] == "Deployment")
    pod = deployment["spec"]["template"]
    target = service["spec"]["ports"][0]["targetPort"]
    port = next(
        row["containerPort"]
        for row in pod["spec"]["containers"][0]["ports"]
        if row["name"] == target
    )
    policy = next(row for row in resources if row["kind"] == "NetworkPolicy")
    assert any(
        any(row.get("port") == port for row in rule.get("ports", []))
        and any(
            all(
                pod["metadata"]["labels"].get(key) == value
                for key, value in peer.get("podSelector", {}).get("matchLabels", {}).items()
            )
            and peer.get("podSelector", {}).get("matchLabels")
            for peer in rule.get("to", [])
        )
        for rule in policy["spec"]["egress"]
    )


def test_enabling_schedules_never_starts_a_second_sqlite_writer(manifests):
    base = manifests / "base"
    path = base / "kustomization.yaml"
    config = yaml.safe_load(path.read_text())
    config["resources"].append("cronjobs.yaml")
    path.write_text(yaml.safe_dump(config))
    resources = render(base)
    assert not [row for row in resources if row["kind"] == "Job"]
    schedules = [row for row in resources if row["kind"] == "CronJob"]
    assert len(schedules) == 2
    for schedule in schedules:
        pod = schedule["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        assert not pod.get("volumes")
        assert not pod["containers"][0].get("volumeMounts")
        assert "http://immich-memories/api/trigger" in pod["containers"][0]["command"]
    one_off = list(yaml.safe_load_all((base / "job.yaml").read_text()))
    assert len(one_off) == 1 and one_off[0]["kind"] == "Job"


def test_readonly_app_and_batch_pods_have_persistent_model_runtime_caches(manifests):
    deployment = next(row for row in render(manifests / "base") if row["kind"] == "Deployment")
    job = yaml.safe_load((manifests / "base" / "job.yaml").read_text())
    for workload in (deployment, job):
        pod = workload["spec"]["template"]["spec"]
        volumes = {row["name"]: row for row in pod["volumes"]}
        for container in pod["containers"] + pod["initContainers"]:
            mounts = {row["mountPath"]: row for row in container["volumeMounts"]}
            cache = mounts["/home/immich/.cache"]
            assert not cache.get("readOnly")
            assert (
                volumes[cache["name"]]["persistentVolumeClaim"]["claimName"]
                == "immich-memories-cache"
            )


def test_uncommenting_the_reader_recipe_produces_an_enabled_32k_endpoint():
    from immich_memories.config_models_llm import LLMConfig

    text = (ROOT / "base" / "deployment.yaml").read_text()
    block = text.split("# Optional: ", 1)[1].split("# Optional: daily", 1)[0]
    rows = yaml.safe_load(
        "\n".join(
            line.removeprefix("            # ")
            for line in block.splitlines()
            if line.startswith(("            # - name:", "            #   value:"))
        )
    )
    values = {
        row["name"].removeprefix("IMMICH_MEMORIES_LLM__").lower(): row["value"] for row in rows
    }
    if "extra_params" in values:
        values["extra_params"] = json.loads(values["extra_params"])
    config = LLMConfig(**values)
    assert config.enabled and not config.runs_locally
    assert config.provider == "ollama"
    assert config.extra_params["options"]["num_ctx"] == 32768


def test_documented_namespace_recipe_moves_every_overlay_secret(manifests):
    if shutil.which("kustomize") is None:
        pytest.skip("standalone kustomize not installed")
    docs = ROOT.parents[1] / "docs-site" / "docs" / "run" / "reference" / "kubernetes.md"
    recipe = docs.read_text().split("```bash\n", 1)[1].split("```", 1)[0]
    recipe = recipe.removeprefix("cd deploy/kubernetes\n")
    result = subprocess.run(
        ["bash", "-c", recipe], cwd=manifests, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    roots = [manifests / "base", *sorted((manifests / "overlays").iterdir())]
    for target in roots:
        for resource in render(target):
            metadata = resource["metadata"]
            if resource["kind"] == "Namespace":
                assert metadata["name"] == "photos-memories", target
            else:
                assert metadata["namespace"] == "photos-memories", (target, metadata)


def test_http_service_never_routes_requests_into_a_curl_job(manifests):
    base = manifests / "base"
    path = base / "kustomization.yaml"
    config = yaml.safe_load(path.read_text())
    config["resources"].append("cronjobs.yaml")
    path.write_text(yaml.safe_dump(config))
    resources = render(base)
    selector = next(row for row in resources if row["kind"] == "Service")["spec"]["selector"]
    deployment = next(row for row in resources if row["kind"] == "Deployment")
    labels = deployment["spec"]["template"]["metadata"]["labels"]
    assert all(labels.get(key) == value for key, value in selector.items())
    for row in resources:
        if row["kind"] != "CronJob":
            continue
        labels = row["spec"]["jobTemplate"]["spec"]["template"]["metadata"]["labels"]
        assert not all(labels.get(key) == value for key, value in selector.items())
