#!/usr/bin/env bash
# Pull every REF this Docker host lacks, retrying what a registry fails to serve.
#
#   scripts/docker_pull.sh REF...
#
# Docker Hub and ghcr answer a 502, a reset or a stalled blob now and then; one
# such answer used to fail a whole real-Immich leg (`docker run` pulled the
# throwaway postgres:16 once and gave up). Each attempt has its own timeout, so
# a stall costs one attempt, and the wait doubles between attempts. A ref
# already on the host is never pulled. A ref still missing after the last
# attempt exits non-zero: nothing runs without its image.
set -euo pipefail

ATTEMPTS=${DOCKER_PULL_ATTEMPTS:-${IMMICH_GATE_PULL_ATTEMPTS:-4}}
# A healthy pull of the biggest set (the v2 Immich server) takes under a minute.
TIMEOUT=${DOCKER_PULL_TIMEOUT:-${IMMICH_GATE_PULL_TIMEOUT:-180}}
# Seconds before the second attempt; each later wait doubles it.
BACKOFF=${DOCKER_PULL_BACKOFF:-10}

[ "$#" -gt 0 ] || { echo "usage: docker_pull.sh REF..." >&2; exit 2; }

# GNU timeout (gtimeout from Homebrew's coreutils); a stock Mac has neither, and
# there a pull runs untimed rather than not at all.
limit=()
if command -v timeout >/dev/null 2>&1; then
	limit=(timeout "$TIMEOUT")
elif command -v gtimeout >/dev/null 2>&1; then
	limit=(gtimeout "$TIMEOUT")
fi

missing() {
	local ref
	for ref in "$@"; do
		docker image inspect "$ref" >/dev/null 2>&1 || echo "$ref"
	done
}

# Refs never contain whitespace, so a space-separated list is safe (and keeps
# this runnable on macOS's bash 3.2, which has no mapfile).
wait_s=$BACKOFF
for attempt in $(seq 1 "$ATTEMPTS"); do
	todo=$(missing "$@")
	if [ -z "$todo" ]; then exit 0; fi
	echo "pull attempt $attempt/$ATTEMPTS: ${todo//$'\n'/ }"
	for ref in $todo; do
		${limit[@]+"${limit[@]}"} docker pull --quiet "$ref" || echo "pull of $ref failed or timed out"
	done
	if [ "$attempt" -lt "$ATTEMPTS" ] && [ -n "$(missing "$@")" ]; then
		sleep "$wait_s"
		wait_s=$((wait_s * 2))
	fi
done
todo=$(missing "$@")
if [ -z "$todo" ]; then exit 0; fi
echo "still missing after $ATTEMPTS attempts: ${todo//$'\n'/ }" >&2
exit 1
