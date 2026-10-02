# Security Policy

## Supported Versions

Only the latest release receives security fixes. The project follows semantic
versioning and ships from `main`; upgrade to the newest tag on
[GitHub Releases](https://github.com/sam-dumont/immich-video-memory-generator/releases)
before reporting.

| Version | Supported          |
| ------- | ------------------ |
| [latest release](https://github.com/sam-dumont/immich-video-memory-generator/releases) | :white_check_mark: |
| older   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in Immich Memories, please report it responsibly:

1. **Do NOT** open a public GitHub issue for security vulnerabilities
2. Use [GitHub's private vulnerability reporting](https://github.com/sam-dumont/immich-video-memory-generator/security/advisories/new) (preferred), or email the maintainer at the address on the [GitHub profile](https://github.com/sam-dumont)
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

I'm a solo maintainer on a hobby project, so there is no SLA. Security reports go to the front
of the queue, but "the front of the queue" realistically means a few days, sometimes longer. If a
week passes with no reply, open a public issue asking me to check my inbox, without describing
the vulnerability.

The [threat model](docs/security/threat-model.md) describes assets, trust boundaries and accepted limits.

## Deployment posture (short version)

- Authentication is **off by default**. Outside Docker the UI then binds `127.0.0.1` unless you
  name another address. The container listens on `0.0.0.0:8080` and the shipped compose file
  publishes `127.0.0.1:8080:8080`, so the port mapping is the boundary. Enable
  [authentication](https://sam-dumont.github.io/immich-video-memory-generator/docs/run/authentication)
  before exposing the port beyond localhost, and put a TLS reverse proxy in front.
- The UI never sends the saved Immich key to a URL typed into it: a new server URL needs its key
  typed in too. Whoever reaches an unauthenticated UI can still use your library through it.
- Read access is enough to generate a local video. Upload-back needs upload/album scopes.
  Cleanup can also move an older generated copy to Immich's trash when the album, filename
  and this app's own upload identity all match; it requires delete permission and never
  hard-deletes. Anything without that upload identity is left alone, unmarked Immich v3
  uploads included.
- What leaves your network (geocoding, map tiles, LLM, music, notifications) is listed on the
  [network & privacy page](https://sam-dumont.github.io/immich-video-memory-generator/docs/run/privacy).
- CI runs five security scans on every change: Bandit, Semgrep, pip-audit, Gitleaks and Hadolint.
  OpenSSF Scorecard runs on its schedule, branch-protection changes and manual dispatch, not pushes to `main`. The Docker image is
  digest-pinned and runs as a non-root user.

## Security Considerations

### API Keys

- Never commit API keys to the repository
- Use environment variables or the config file (which should be in `.gitignore`)
- The config file is stored in `~/.immich-memories/config.yaml`

### Network Security

- All communication with Immich should be over HTTPS
- Verify your Immich server's SSL certificate is valid

### Local Storage

- Downloaded videos are cached locally
- Cache directory: `~/.immich-memories/cache/`
- Clear cache periodically if disk space is a concern

## Verifying a release

Releases carry SLSA build provenance, signed through Sigstore by the GitHub
Actions workflow that produced them: nothing is built on a laptop. A release
that carries it has a `.sigstore.json` asset alongside the wheel.

Choose a release that actually has a `.sigstore.json` asset. This verifies the downloaded
wheel against that bundle; release tags and wheel versions differ for release candidates:

```bash
# Set this to an existing release tag whose assets include the bundle.
TAG=vX.Y.Z
mkdir release-verification
cd release-verification
gh release download "$TAG" --repo sam-dumont/immich-video-memory-generator \
  --pattern '*.whl' --pattern '*.sigstore.json'
# Use actual filenames, including Python's normalized RC version.
set -- ./*.whl
[ "$#" -eq 1 ] && [ -f "$1" ] || exit 1
WHEEL=$1
set -- ./*.sigstore.json
[ "$#" -eq 1 ] && [ -f "$1" ] || exit 1
gh attestation verify "$WHEEL" \
  --repo sam-dumont/immich-video-memory-generator --bundle "$1"
```

The application image carries provenance for each platform digest. Verify the digest for your
platform rather than the multi-platform tag. Inference images do not yet have the same explicit
GitHub attestation step. For the Linux amd64 application image:

```bash
IMAGE=ghcr.io/sam-dumont/immich-video-memory-generator:0.103.0
DIGEST=$(docker buildx imagetools inspect "$IMAGE" --raw | jq -r \
  '.manifests[] | select(.platform.os == "linux" and .platform.architecture == "amd64") | .digest')
gh attestation verify "oci://${IMAGE%:*}@$DIGEST" \
  --repo sam-dumont/immich-video-memory-generator
```

The `.intoto.jsonl` asset is the same statement as a bare in-toto envelope, for
tools that expect the SLSA layout rather than a Sigstore bundle.

## Dependencies

`make pip-audit` checks the locked development dependencies and the `all` extra used by the
application image. It excludes the local music package itself from PyPI resolution, while
including its exported dependencies. Findings fail unless they match the exact reviewed NLTK
package, version and advisory below with no fix available. `make npm-audit` checks the full web
client dependency tree (its build dependencies become shipped assets) and the docs runtime tree.
GitHub dependency review checks newly introduced high/critical advisories on PRs. Dependabot's
weekly configuration proposes dependency updates; alerts and security updates also require the
repository settings to be enabled. These checks do not inventory OS packages or every separately
installed inference-service variant.

To pick up patches, upgrade:

```bash
uv tool upgrade immich-memories        # or: pip install --upgrade immich-memories
docker compose pull                    # Docker installs
```

### Reviewed NLTK advisory

NLTK 3.10.3 remains affected by [GHSA-8mgp-746c-j5xp](https://github.com/advisories/GHSA-8mgp-746c-j5xp),
with no official patched release as of September 30, 2026. The app actively uses NLTK for WordNet:
it verifies the pinned corpus hash before opening the reader, and request words enter read-only
dictionary lookups. The supported WordNet and ACE-Step routes do not call the affected model
save/load APIs. This is a reviewed reachability finding, not a patched package or a blanket
scanner exception. Keep the advisory tracked and re-audit any new NLTK training or export integration.
