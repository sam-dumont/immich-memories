#!/usr/bin/env bash
# Run a command with a PostgreSQL URL in the environment variable VAR.
#
#   scripts/with_throwaway_postgres.sh VAR IMAGE -- command [args...]
#
# When VAR is already set (CI names its service there) the command runs as it is.
# Otherwise a throwaway postgres container starts on a free local port, with its data
# on tmpfs, and is removed however the command ends: the Mac's Docker disk is small
# and a stopped database left behind is a volume nobody asked for.
set -euo pipefail

var=$1
image=$2
shift 2
[ "${1:-}" = "--" ] && shift

if [ -n "${!var:-}" ]; then
	exec "$@"
fi

name="immich-memories-pg-$$"
docker run -d --rm --name "$name" --tmpfs /var/lib/postgresql/data \
	-e POSTGRES_PASSWORD=store-test -p 127.0.0.1::5432 "$image" >/dev/null
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT INT TERM

ready=0
for _ in $(seq 1 60); do
	if docker exec "$name" pg_isready -U postgres -h 127.0.0.1 >/dev/null 2>&1; then
		ready=1
		break
	fi
	sleep 1
done
if [ "$ready" -ne 1 ]; then
	echo "postgres did not become ready" >&2
	docker logs "$name" >&2
	exit 1
fi

port=$(docker port "$name" 5432/tcp | head -n 1 | sed 's/.*://')
export "$var=postgresql://postgres:store-test@127.0.0.1:$port/postgres"
"$@"
