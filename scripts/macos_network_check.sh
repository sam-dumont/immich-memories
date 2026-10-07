#!/usr/bin/env bash
# Run a real film on macOS and fail if the process talks to anything but Immich.
#
# tcpdump on Linux sees the Microsoft telemetry that ONNX Runtime 1.30 can open;
# on macOS it goes through NSURLSession, which lsof and Python DNS hooks cannot
# see. nettop on the pid can. A violation also gets a `sample` of the process, so
# the thread that opened the socket is named in the evidence.
#
#   IMMICH_URL=http://nas:2283 scripts/macos_network_check.sh [generate args...]
#
# Env: IMMICH_URL (required, the one allowed remote), NETCHECK_ALLOW (extra egrep
# of allowed "host:port" remotes, e.g. a configured LLM endpoint), NETCHECK_OUT
# (evidence dir, default ./netcheck-out), IMMICH_MEMORIES_BIN (default
# immich-memories). Default film: the May 2021 monthly highlights.
set -u

[ "$(uname -s)" = "Darwin" ] || { echo "macOS only: use tcpdump on Linux" >&2; exit 2; }
: "${IMMICH_URL:?set IMMICH_URL to the Immich server the film may talk to}"

out="${NETCHECK_OUT:-./netcheck-out}"
bin="${IMMICH_MEMORIES_BIN:-immich-memories}"
mkdir -p "$out"

hostport="${IMMICH_URL#*://}"
hostport="${hostport%%/*}"
case "$hostport" in
  *:*) ;;
  *) case "$IMMICH_URL" in https://*) hostport="$hostport:443" ;; *) hostport="$hostport:80" ;; esac ;;
esac
host="${hostport%:*}"
if ! echo "$host" | grep -Eq '^[0-9.]+$'; then
  host="$(dscacheutil -q host -a name "$host" | awk '/ip_address/ {print $2; exit}')"
  hostport="$host:${hostport##*:}"
fi

if [ "$#" -eq 0 ]; then
  set -- --memory-type monthly_highlights --year 2021 --month 5 --include-photos
fi

"$bin" generate "$@" >"$out/generate.log" 2>&1 &
pid=$!
nettop -p "$pid" -m tcp -L 0 -s 1 -J bytes_in,bytes_out >"$out/nettop.txt" 2>&1 &
nt=$!

# nettop reports a process's sockets with a one second lag; poll the file while
# the film runs so a violation is sampled while the worker thread still exists.
# Only whole socket rows count: nettop's last line can be cut mid-address when the film ends.
remotes_seen() {
  grep -E '^tcp[46] [^,]*<->[^,]*,[0-9]+,[0-9]+,$' "$out/nettop.txt" | sed -e 's/.*<->//' -e 's/,.*//'
}

sampled=0
while kill -0 "$pid" 2>/dev/null; do
  if [ "$sampled" -eq 0 ] && remotes_seen \
      | grep -Ev "^(\\*|127\\.0\\.0\\.1|\\[?::1|localhost)" \
      | grep -vF "$hostport" | grep -Evq "${NETCHECK_ALLOW:-^\$}"; then
    sample "$pid" 2 -file "$out/sample.txt" >/dev/null 2>&1
    sampled=1
  fi
  sleep 1
done
wait "$pid"; film_rc=$?
kill "$nt" 2>/dev/null

remotes="$(remotes_seen | sort | uniq -c)"
echo "$remotes" >"$out/remotes.txt"
bad="$(remotes_seen | sort -u \
  | grep -Ev '^(\*|127\.0\.0\.1|\[?::1|localhost)' | grep -vF "$hostport" \
  | grep -Ev "${NETCHECK_ALLOW:-^\$}")"

echo "film exit code: $film_rc"
echo "remotes seen:"; echo "$remotes"
if [ -n "$bad" ]; then
  echo "FAIL: connections outside Immich ($hostport):" >&2
  echo "$bad" >&2
  grep -c "Microsoft::Applications" "$out/sample.txt" 2>/dev/null | sed 's/^/1DS frames in sample: /' >&2
  exit 1
fi
[ "$film_rc" -eq 0 ] || { echo "FAIL: the film itself failed, see $out/generate.log" >&2; exit "$film_rc"; }
echo "OK: only Immich"
