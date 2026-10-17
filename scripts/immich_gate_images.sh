#!/usr/bin/env bash
# Get the gate's pinned images onto this Docker host, or save them for the next run.
#
#   immich_gate_images.sh fetch TARBALL REF...   load TARBALL if it holds every REF, else pull
#   immich_gate_images.sh save  TARBALL REF...   docker save every REF into TARBALL
#
# A registry that stalls mid-pull used to hold the gate for its whole timeout
# (run 36002698337, #1267). CI keeps the tarball in actions/cache, so a warm
# run never talks to a registry. A cold one pulls through docker_pull.sh, which
# retries a registry's 5xx, resets and stalls with a growing wait. A ref that is
# still missing after the last attempt exits non-zero: the gate fails, it never
# runs without Immich.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)

missing() {
	local ref
	for ref in "$@"; do
		docker image inspect "$ref" >/dev/null 2>&1 || echo "$ref"
	done
}

cmd=${1:?usage: immich_gate_images.sh fetch|save TARBALL REF...}
tarball=${2:?tarball path required}
shift 2
[ "$#" -gt 0 ] || { echo "no image refs given" >&2; exit 2; }

case "$cmd" in
fetch)
	if [ -s "$tarball" ]; then
		docker load --quiet --input "$tarball" || echo "docker load failed"
		# A digest-pinned save loads back nameless, as an image whose ID is the
		# pinned digest. Naming that exact ID repo:tag lets repo:tag@digest
		# resolve; a tarball without the pinned content has no such ID to name.
		for ref in "$@"; do
			docker tag "sha256:${ref##*@sha256:}" "${ref%@*}" 2>/dev/null || true
		done
		if [ -z "$(missing "$@")" ]; then
			echo "all pinned images loaded from $tarball"
			exit 0
		fi
		echo "the cached tarball did not provide:" $(missing "$@")
	fi
	"$here/docker_pull.sh" "$@"
	;;
save)
	mkdir -p "$(dirname "$tarball")"
	docker save --output "$tarball" "$@"
	echo "saved $(du -h "$tarball" | cut -f1) to $tarball"
	;;
*)
	echo "unknown command: $cmd" >&2
	exit 2
	;;
esac
