#!/usr/bin/env bash
# Package the setup files a release or a nightly attaches to its GitHub release:
# Compose files and the deployment bundle pinned to $VERSION (the image tag), the
# wheel from $RUNNER_TEMP/dist-release, the pushed image manifests, an
# installation.json naming the source commit, and SHA256SUMS over all of it.
# Run from the repository root after the image tags exist in GHCR.
set -euo pipefail
: "${VERSION:?VERSION is the image tag the files pin}"
: "${RUNNER_TEMP:?}"
: "${GITHUB_SHA:?}"

bundle="$RUNNER_TEMP/immich-memories-deploy-${VERSION}.tar.gz"
python3 scripts/package_deployment.py "$VERSION" "$bundle"
compose_assets="$RUNNER_TEMP/immich-memories-compose-${VERSION}"
python3 scripts/package_compose.py "$VERSION" "$compose_assets"
cp "$bundle" "$compose_assets/"
cp "$RUNNER_TEMP"/dist-release/*.whl "$compose_assets/"
for variant in app inference inference-cuda; do
  image="ghcr.io/sam-dumont/immich-memories"
  suffix=""
  if [[ "$variant" != app ]]; then image="$image/inference"; fi
  if [[ "$variant" == inference-cuda ]]; then suffix="-cuda"; fi
  docker buildx imagetools inspect "$image:$VERSION$suffix" \
    --format '{{json .Manifest}}' > "$compose_assets/$variant-image.json"
done
jq -n --arg version "$VERSION" --arg source "$GITHUB_SHA" \
  --slurpfile app "$compose_assets/app-image.json" \
  --slurpfile inference "$compose_assets/inference-image.json" \
  --slurpfile cuda "$compose_assets/inference-cuda-image.json" \
  '{version: $version, source_commit: $source, images: {app: $app[0], inference: $inference[0], cuda: $cuda[0]}}' \
  > "$compose_assets/installation.json"
(cd "$compose_assets" && for asset in *; do sha256sum "$asset"; done) > "$RUNNER_TEMP/SHA256SUMS"
mv "$RUNNER_TEMP/SHA256SUMS" "$compose_assets/SHA256SUMS"
