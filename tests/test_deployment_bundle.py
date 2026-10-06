import os
import shutil
import subprocess
import tarfile

import pytest
import yaml
from scripts.package_deployment import package_bundle


def test_release_bundle_pins_all_images_and_omits_untracked_secrets(tmp_path, monkeypatch):
    # A commit hook exports Git paths for the parent repo; this fixture owns its checkout.
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for directory in (
        "base",
        "overlays/inference",
        "overlays/inference-cuda",
        "overlays/render-sidecar",
        "overlays/maximalist",
    ):
        path = tmp_path / "deploy/kubernetes" / directory / "kustomization.yaml"
        path.parent.mkdir(parents=True)
        image = "ghcr.io/sam-dumont/immich-memories" + (
            "/inference" if "inference" in directory else ""
        )
        tag = "0.1.0-cuda" if "inference-cuda" in directory else "0.1.0"
        path.write_text(f'images:\n  - name: {image}\n    newTag: "{tag}"\n')
    subprocess.run(["git", "add", "deploy"], cwd=tmp_path, check=True)
    (tmp_path / "deploy/kubernetes/base/secret.yaml").write_text("private credential")
    destination = tmp_path / "bundle.tgz"
    package_bundle(tmp_path, "1.2.3", destination)
    with tarfile.open(destination) as archive:
        assert len(archive.getnames()) == 5
        for name in archive.getnames():
            value = yaml.safe_load(archive.extractfile(name).read())
            assert value["images"][0]["newTag"] == (
                "1.2.3-cuda" if "inference-cuda" in name else "1.2.3"
            )


def test_release_bundle_rejects_unversioned_tags(tmp_path):
    with pytest.raises(ValueError, match="release version"):
        package_bundle(tmp_path, "latest", tmp_path / "bundle.tgz")


def test_release_bundle_accepts_a_release_candidate(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / "deploy/kubernetes/base/kustomization.yaml"
    path.parent.mkdir(parents=True)
    path.write_text('images:\n  - name: ghcr.io/sam-dumont/immich-memories\n    newTag: "0.1.0"\n')
    subprocess.run(["git", "add", "deploy"], cwd=tmp_path, check=True)
    destination = tmp_path / "bundle.tgz"
    package_bundle(tmp_path, "1.0.0-rc.1", destination)
    with tarfile.open(destination) as archive:
        value = yaml.safe_load(archive.extractfile(archive.getnames()[0]).read())
    assert value["images"][0]["newTag"] == "1.0.0-rc.1"


def test_release_bundle_stamps_terraform_examples(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / "deploy/terraform/examples/basic/terraform.tfvars.example"
    path.parent.mkdir(parents=True)
    path.write_text('image_tag = "replace-with-a-release-tag"\n')
    subprocess.run(["git", "add", "deploy"], cwd=tmp_path, check=True)
    destination = tmp_path / "bundle.tgz"
    package_bundle(tmp_path, "1.0.0-rc.1", destination)
    with tarfile.open(destination) as archive:
        assert (
            archive.extractfile(str(path.relative_to(tmp_path))).read()
            == b'image_tag = "1.0.0-rc.1"\n'
        )


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
@pytest.mark.parametrize("overlay", ["render-sidecar", "maximalist"])
def test_packaged_overlay_keeps_every_app_container_on_the_release(tmp_path, overlay):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    destination = tmp_path / "bundle.tgz"
    package_bundle(root, "1.0.0-rc.1", destination)
    with tarfile.open(destination) as archive:
        archive.extractall(tmp_path, filter="data")
    kubernetes = tmp_path / "deploy/kubernetes"
    for example in kubernetes.rglob("*.yaml.example"):
        example.with_suffix("").write_bytes(example.read_bytes())
    rendered = subprocess.check_output(
        ["kubectl", "kustomize", str(kubernetes / "overlays" / overlay)], text=True
    )
    own_repo = "ghcr.io/sam-dumont/immich-memories"
    images = [
        container["image"]
        for document in yaml.safe_load_all(rendered)
        if document["kind"] == "Deployment"
        for key in ("initContainers", "containers")
        for container in document["spec"]["template"]["spec"].get(key, [])
        if container["image"].startswith(own_repo)
    ]
    assert len(images) >= 3
    for image in images:
        expected = "1.0.0-rc.1-cuda" if "/inference:" in image else "1.0.0-rc.1"
        assert image == image.split(":")[0] + ":" + expected


@pytest.mark.parametrize(
    "image,current,expected",
    [
        ("ghcr.io/sam-dumont/immich-memories", "0.1.0", "1.2.3"),
        ("ghcr.io/sam-dumont/immich-memories/inference", "0.1.0-cuda", "1.2.3-cuda"),
    ],
)
def test_release_bundle_pins_component_images_without_a_directory_allowlist(
    tmp_path, monkeypatch, image, current, expected
):
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / "deploy/kubernetes/components/another-option/kustomization.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(f'images:\n  - name: {image}\n    newTag: "{current}"\n')
    subprocess.run(["git", "add", "deploy"], cwd=tmp_path, check=True)
    destination = tmp_path / "bundle.tgz"

    package_bundle(tmp_path, "1.2.3", destination)

    with tarfile.open(destination) as archive:
        value = yaml.safe_load(archive.extractfile(str(path.relative_to(tmp_path))).read())
    assert value["images"][0]["newTag"] == expected


def test_gpu_services_init_container_runs_on_the_gpu_tier():
    # Without the pin the fetch init container resolves "auto" to basic and logs a tier
    # the app container never runs, while it fetches the GPU detectors anyway.
    path = "deploy/kubernetes/components/gpu-services/deployment-services.yaml"
    with open(path) as handle:
        docs = [d for d in yaml.safe_load_all(handle) if d]
    init = next(d for d in docs if d.get("kind") == "Deployment")["spec"]["template"]["spec"][
        "initContainers"
    ][0]
    env = {e["name"]: e.get("value") for e in init["env"]}
    assert env["IMMICH_MEMORIES_DEPLOYMENT_TIER"] == "gpu"
