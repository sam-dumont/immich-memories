# Image dependency maintenance

`make image-audit-build image-audit` rebuilds the app image and audits its installed Python
distributions. The inventory includes the app's extras and bundled render-worker dependencies.
First-party distributions stay in `python.json` but are not queried as PyPI dependencies.
CPU/CUDA version suffixes remain in the requirements file. Missing inventories, failed probes,
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
