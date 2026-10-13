"""Pin the image references of the files people copy from `main` to one release.

The files carry a real version, never `latest`. A release run stamps it into the
published assets (`package_compose.py`, `package_deployment.py`);
`make pin-release VERSION=X.Y.Z` moves the pin in the repository after a release,
in one commit. The README's browser URLs move with it, to the host port of the Compose
file that release ships.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

RELEASE_VERSION = re.compile(r"\d+\.\d+\.\d+(?:-rc\.\d+)?")

# Each pattern has a `pre` group, the pinned value, and an optional `post` group that is kept
# (a `-cuda` suffix, a closing quote or brace).
_COMPOSE = re.compile(r"(?P<pre>\$\{IMMICH_MEMORIES_VERSION:-)[^}]*(?P<post>\})")
_ENV_LINE = re.compile(r"(?m)^(?P<pre>IMMICH_MEMORIES_VERSION=).*$")
_UNRAID = re.compile(
    r"(?P<pre><Repository>ghcr\.io/sam-dumont/immich-memories:)[^<]*(?P<post></Repository>)"
)
_README = re.compile(r"(?m)^(?P<pre>\s*VERSION=)\S+$")
_CUDA_TAG = re.compile(r"(?P<pre>INFERENCE_TAG=)[^\s)]*(?P<post>-cuda)")
_MANIFEST_IMAGE = re.compile(
    r"(?P<pre>image: ghcr\.io/sam-dumont/immich-memories(?:/inference)?:)"
    r"(?:latest|\d[^\s\"]*?)(?P<post>-cuda)?(?=[\"\s]|$)"
)
_NEW_TAG = re.compile(
    r"(?P<pre>- name: ghcr\.io/sam-dumont/immich-memories(?:/inference)?\s*\n\s*newTag: \")"
    r"[^\"\n]*?(?P<post>(?:-cuda)?\")"
)
_TERRAFORM_DEFAULT = re.compile(
    r"(?P<pre>variable \"image_tag\" \{[^}]*?default\s*=\s*\")[^\"]*(?P<post>\")", re.DOTALL
)
_TFVARS = re.compile(r"(?m)^(?P<pre>image_tag\s*=\s*\")[^\"]*(?P<post>\")")
_COMPOSE_HOST_PORT = re.compile(r"(?m)^\s*-\s*\S*:(?P<port>\d+):8080\s*$")
_README_URL = re.compile(r"(?P<pre>http://(?:localhost|your-server-address):)\d+")
_TABLE_DEFAULT = re.compile(r"(?P<pre>`\")(?:latest|\d[^\"]*)(?P<post>\"`)")

_MANIFESTS = (_MANIFEST_IMAGE,)
_KUSTOMIZATIONS = (_NEW_TAG,)

PINNED_FILES: dict[str, tuple[re.Pattern[str], ...]] = {
    "docker-compose.yml": (_COMPOSE,),
    "docker-compose.gpu.yml": (_COMPOSE,),
    "docker-compose.cuda.yml": (_COMPOSE,),
    "docker-compose.gpu-worker.yml": (_COMPOSE,),
    "docker-compose.maximalist.yml": (_CUDA_TAG,),
    "docker/hwaccel.inference.yml": (_CUDA_TAG,),
    "example.env": (_ENV_LINE,),
    "deploy/unraid/immich-memories.xml": (_UNRAID,),
    "docs-site/src/components/SetupBuilder/sources.json": (_COMPOSE,),
    "README.md": (_README,),
    "services/render-worker/kubernetes.yaml": _MANIFESTS,
    "deploy/kubernetes/base/deployment.yaml": _MANIFESTS,
    "deploy/kubernetes/base/job.yaml": _MANIFESTS,
    "deploy/kubernetes/base/kustomization.yaml": _KUSTOMIZATIONS,
    "deploy/kubernetes/components/render-sidecar/deployment-sidecar.yaml": _MANIFESTS,
    "deploy/kubernetes/components/render-sidecar/kustomization.yaml": _KUSTOMIZATIONS,
    "deploy/kubernetes/overlays/inference/deployment.yaml": _MANIFESTS,
    "deploy/kubernetes/overlays/inference/kustomization.yaml": _KUSTOMIZATIONS,
    "deploy/kubernetes/overlays/inference-cuda/kustomization.yaml": _KUSTOMIZATIONS,
    "deploy/kubernetes/overlays/maximalist/deployment-maximalist.yaml": _MANIFESTS,
    "deploy/kubernetes/overlays/maximalist/kustomization.yaml": _KUSTOMIZATIONS,
    "deploy/terraform/variables.tf": (_TERRAFORM_DEFAULT,),
    "deploy/terraform/examples/production/variables.tf": (_TERRAFORM_DEFAULT,),
    "deploy/terraform/examples/maximalist/variables.tf": (_TERRAFORM_DEFAULT,),
    "deploy/terraform/examples/maximalist/terraform.tfvars.example": (_TFVARS,),
    "deploy/terraform/README.md": (_TABLE_DEFAULT,),
    "docs-site/docs/run/reference/terraform.md": (_TABLE_DEFAULT,),
}


def pin_text(name: str, text: str, version: str) -> str:
    """Return `text` with every image pin of the file `name` set to `version`."""
    for pattern in PINNED_FILES.get(name, ()):
        text = pattern.sub(
            lambda m: (
                m["pre"] + version + (m["post"] if "post" in m.re.groupindex and m["post"] else "")
            ),
            text,
        )
    return text


def pin_repository(root: Path, version: str) -> list[Path]:
    """Rewrite every pinned file under `root`; return the files that changed."""
    if not RELEASE_VERSION.fullmatch(version):
        raise ValueError("Expected a release version without the v prefix")
    changed = []
    for name in PINNED_FILES:
        path = root / name
        before = path.read_text(encoding="utf-8")
        after = pin_text(name, before, version)
        if after != before:
            path.write_text(after, encoding="utf-8")
            changed.append(path)
    if _pin_readme_port(root) and root / "README.md" not in changed:
        changed.append(root / "README.md")
    return changed


def _pin_readme_port(root: Path) -> bool:
    """Point the README's browser URLs at the host port the pinned Compose file publishes."""
    port = _COMPOSE_HOST_PORT.search((root / "docker-compose.yml").read_text(encoding="utf-8"))
    if port is None:
        raise ValueError("docker-compose.yml publishes no host port for the app")
    readme = root / "README.md"
    before = readme.read_text(encoding="utf-8")
    after = _README_URL.sub(lambda m: m["pre"] + port["port"], before)
    if after != before:
        readme.write_text(after, encoding="utf-8")
    return after != before


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    args = parser.parse_args()
    for changed in pin_repository(Path(__file__).resolve().parents[1], args.version):
        print(f"pinned {changed}")
