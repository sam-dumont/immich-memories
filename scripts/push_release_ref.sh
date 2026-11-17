#!/usr/bin/env bash
# Push one release ref (a version tag, or the moved `nightly` tag) with the token in
# RELEASE_TAG_TOKEN.
#
# GitHub refuses a ref the workflow's GITHUB_TOKEN writes when the move changes a
# workflow file to content the default branch doesn't have at that moment (#2615).
# A release takes about two hours, so a workflow change merged meanwhile left the
# tag unpushable. release.yml mints a one-hour token from the CI GitHub App
# (immich-memories-ci-bot, Contents and Workflows write on this repository) just
# before its two ref-writing steps, the only callers; everything else keeps
# GITHUB_TOKEN.
#
# Usage: scripts/push_release_ref.sh [--force] <refspec>
# Needs RELEASE_TAG_TOKEN in the environment. The token is never printed.
set -euo pipefail

force=()
if [ "${1:-}" = "--force" ]; then
  force=(--force)
  shift
fi
refspec="${1:?usage: push_release_ref.sh [--force] <refspec>}"

if [ -z "${RELEASE_TAG_TOKEN:-}" ]; then
  echo "::error::RELEASE_TAG_TOKEN is missing or empty, so $refspec cannot be pushed."
  echo "The step before mints it from the CI GitHub App immich-memories-ci-bot: check that"
  echo "the variable CI_APP_CLIENT_ID and the secret CI_APP_PRIVATE_KEY are set, then re-run the failed job."
  exit 1
fi

header="AUTHORIZATION: basic $(printf 'x-access-token:%s' "$RELEASE_TAG_TOKEN" | base64 | tr -d '\n')"
if [ -n "${GITHUB_ACTIONS:-}" ]; then
  echo "::add-mask::$header"
fi

# The first value clears any header actions/checkout left behind; the second is ours.
# Passed through the environment, so neither the token nor the header reaches argv.
if ! GIT_CONFIG_COUNT=2 \
  GIT_CONFIG_KEY_0="http.https://github.com/.extraheader" GIT_CONFIG_VALUE_0="" \
  GIT_CONFIG_KEY_1="http.https://github.com/.extraheader" GIT_CONFIG_VALUE_1="$header" \
  git push ${force[@]+"${force[@]}"} origin "$refspec"; then
  echo "::error::Pushing $refspec with the app token failed."
  echo "If the output above is an authentication or permission error, the CI GitHub App"
  echo "immich-memories-ci-bot lacks Contents or Workflows write on this repository, or is not"
  echo "installed on it: fix the app's permissions or installation, then re-run the failed job."
  exit 1
fi
