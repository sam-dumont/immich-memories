# Image dependency maintenance

`make image-audit-build image-audit` rebuilds the app image and audits its installed Python
distributions. The inventory includes the app's extras and bundled render-worker dependencies.
The runtime images remove pip and wheel after installation; neither is needed to run the app.
First-party distributions stay in `python.json` but are not queried as PyPI dependencies.
CPU/CUDA version suffixes remain in `requirements.txt`. `advisory-requirements.txt` maps only
official `torch`, `torchaudio` and `torchvision` CPU/CUDA suffixes to their public release for
PyPI advisory lookup; PyPI does not index local version suffixes. This checks upstream Python
advisories, not variant-specific native binary vulnerabilities. Unrecognized local builds remain
unchanged and a failed lookup fails the audit. Missing inventories, failed probes,
and failed audits fail the job; only the exact reviewed advisory in `SECURITY.md` is excepted.

The Image Maintenance workflow runs every Monday, manually, and on relevant pull requests.
Its five native-runner builds cover app amd64/arm64, inference CPU amd64/arm64 and inference CUDA
amd64. No private GPU runner or registry write permission is used. Metadata probes run without
network access, Linux capabilities, or a writable root filesystem. This is an inventory check,
not a GPU inference test.

Each rebuild pulls the digest-pinned base and reruns the distro package installation without
cached layers. `os-packages.tsv` records the installed OS package versions; it is not an OS CVE
scan. Base digest updates still need review. Scheduled builds do not move release tags: publish
updated images through the existing Release workflow after reviewing the audit artifacts.

To inspect another local image, run `make image-audit IMAGE_AUDIT_IMAGE=your-image`.
`IMAGE_AUDIT_FILE=docker/Dockerfile.inference IMAGE_AUDIT_DEVICE=cuda` selects the inference build.
Artifacts contain the image identity, complete Python inventory, exact audit input, OS inventory
and pip-audit output. No third-party scanner action or Trivy is used.

## Publication provenance

Release builds attest the inference image digests as well as the application images. After
multi-platform assembly, each app, inference CPU and inference CUDA manifest receives its own
attestation using the digest returned by Buildx's metadata file. Missing or malformed digests
stop publication checks. This takes effect for releases built with the updated workflow; it does
not add attestations to older registry objects.
Use the [release verification instructions](../../SECURITY.md#verifying-a-release) to select
the appropriate app, CPU or CUDA manifest and verify its digest against the release workflow.

Publication jobs record outbound connections with `harden-runner` in audit mode. Blocking remains
an operator choice until a complete release has supplied an allowlist covering package downloads,
registries and signing endpoints. The workflow does not assume that an untested allowlist works.

The private GPU mirror checks out the exact submitted commit. Its callback repository, commit,
branch and test suite are validated before a status is written. Dispatch payloads are serialized
as JSON, and benchmark submissions reach the validator through environment variables.
