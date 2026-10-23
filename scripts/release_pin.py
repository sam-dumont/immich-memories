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
import subprocess
import sys
from pathlib import Path

RELEASE_VERSION = re.compile(r"\d+\.\d+\.\d+(?:-rc\.\d+)?")
# The dev docs build pins its tree to the nightly it was built from; nothing commits that.
NIGHTLY_TAG = re.compile(r"nightly-\d{8}")

# Each pattern has a `pre` group, the pinned value, and an optional `post` group that is kept
# (a `-cuda` suffix, a closing quote or brace).
_COMPOSE = re.compile(r"(?P<pre>\$\{IMMICH_MEMORIES_VERSION:-)[^}]*(?P<post>\})")
_ENV_LINE = re.compile(r"(?m)^(?P<pre>IMMICH_MEMORIES_VERSION=).*$")
_VERSION_ASSIGN = re.compile(r"(?P<pre>IMMICH_MEMORIES_VERSION=)[^\s]+")
_UNRAID = re.compile(
    r"(?P<pre><Repository>ghcr\.io/sam-dumont/immich-memories:)[^<]*(?P<post></Repository>)"
)
_README = re.compile(r"(?m)^(?P<pre>\s*VERSION=)\S+$")
_CUDA_TAG = re.compile(r"(?P<pre>INFERENCE_TAG=)[^\s)]*(?P<post>-cuda)")
_MANIFEST_IMAGE = re.compile(
    r"(?P<pre>image: ghcr\.io/sam-dumont/immich-memories(?:/inference)?:)"
    r"(?:latest|nightly-\d{8}|\d[^\s\"]*?)(?P<post>-cuda)?(?=[\"\s]|$)"
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
# Only the `image_tag` row: the other defaults in these tables are sizes and resolutions.
_TABLE_DEFAULT = re.compile(
    r"(?m)(?P<pre>^\|[^\n]*`image_tag`[^\n]*`\")(?:latest|nightly-\d{8}|\d[^\"]*)(?P<post>\"`)"
)

_MANIFESTS = (_MANIFEST_IMAGE,)
_KUSTOMIZATIONS = (_NEW_TAG,)

PINNED_FILES: dict[str, tuple[re.Pattern[str], ...]] = {
    "docker-compose.yml": (_COMPOSE,),
    "docker-compose.gpu.yml": (_COMPOSE,),
    "docker-compose.cuda.yml": (_COMPOSE,),
    "docker-compose.gpu-worker.yml": (_COMPOSE,),
    "docker-compose.maximalist.yml": (_VERSION_ASSIGN,),
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
    if not (RELEASE_VERSION.fullmatch(version) or NIGHTLY_TAG.fullmatch(version)):
        raise ValueError("Expected a release version without the v prefix, or a nightly tag")
    changed = []
    for name in PINNED_FILES:
        path = root / name
        if not path.exists():  # an older tree (the dev docs' nightly) may predate a file
            continue
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


def _release_key(version: str) -> tuple[int, int, int, int]:
    """Order releases: 1.0.0-rc.9 < 1.0.0-rc.10 < 1.0.0."""
    core, _, rc = version.partition("-rc.")
    major, minor, patch = (int(part) for part in core.split("."))
    return major, minor, patch, int(rc) if rc else sys.maxsize


def newer_release_than_pin(readme: str, tags: list[str]) -> str | None:
    """The latest released version when the README still pins an older one, else None.

    A release stops here until the previous one's pin has landed on main: the files people
    copy from main never fall more than one release behind.
    """
    pinned = _README.search(readme)
    if pinned is None:
        raise ValueError("README.md pins no VERSION")
    current = readme[pinned.end("pre") : pinned.end()].strip()
    released = [
        tag[1:] for tag in tags if tag.startswith("v") and RELEASE_VERSION.fullmatch(tag[1:])
    ]
    if not released:
        return None
    latest = max(released, key=_release_key)
    return latest if _release_key(latest) > _release_key(current) else None


def pin_to_latest_release(root: Path, tags: list[str]) -> list[Path]:
    """Move every pin to the newest release in `tags` when the tree pins an older one."""
    behind = newer_release_than_pin((root / "README.md").read_text(encoding="utf-8"), tags)
    return pin_repository(root, behind) if behind else []


def _release_tags(root: Path) -> list[str]:
    """Version tags here and on origin: a release is tagged by CI, so a clone may not have it."""
    git = ["git", "-C", str(root)]
    local = subprocess.run([*git, "tag", "--list", "v*"], capture_output=True, text=True)
    remote = subprocess.run(
        [*git, "ls-remote", "--tags", "--refs", "origin", "v*"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    names = local.stdout.split() + [ref.rpartition("/")[2] for ref in remote.stdout.split()[1::2]]
    return list(dict.fromkeys(names))


def _pin_latest(root: Path) -> int:
    """The pre-commit hook: the first commit after a release moves the pins to it."""
    changed = pin_to_latest_release(root, _release_tags(root))
    for path in changed:
        print(f"pinned {path.relative_to(root)} to the latest release; stage it and commit again")
    return 1 if changed else 0


def _check_pin(root: Path) -> int:
    behind = newer_release_than_pin(
        (root / "README.md").read_text(encoding="utf-8"), _release_tags(root)
    )
    if behind is None:
        return 0
    print(
        f"::error::main still pins an older release than v{behind}. Commit anything on main "
        f"(the pre-commit hook moves the pins) or run `make pin-release VERSION={behind}`."
    )
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when main pins an older release than the latest tag",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="move every pin to the newest release; exit 1 when a file changed",
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    if args.check:
        sys.exit(_check_pin(repo))
    if args.latest:
        sys.exit(_pin_latest(repo))
    if args.version is None:
        parser.error("a version is required unless --check or --latest")
    for changed in pin_repository(repo, args.version):
        print(f"pinned {changed}")
