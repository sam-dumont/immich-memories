#!/bin/sh
# `apt-get install PACKAGES` that survives unreachable package hosts.
#
# Every apt call gets retries and short timeouts. On Ubuntu, the update and the install run
# against one mirror at a time, moving to the next when either fails: HTTPS mirrors first when
# the image can check certificates, plain HTTP after. GitHub's runners once lost plain HTTP to
# every Ubuntu mirror for a night while HTTPS kept working, and an update that succeeds says
# nothing about the downloads that follow. apt checks every package's signature either way.
set -eu
[ "$#" -gt 0 ] || { echo "usage: apt-install.sh PACKAGE..." >&2; exit 2; }

cat > /etc/apt/apt.conf.d/80-retries <<'CONF'
Acquire::Retries "3";
Acquire::http::Timeout "20";
Acquire::https::Timeout "20";
CONF

install_from_current_sources() {
    apt-get update -o APT::Update::Error-Mode=any && apt-get install -y --no-install-recommends "$@"
}

[ -f /etc/os-release ] && . /etc/os-release
if [ "${ID:-}" != "ubuntu" ]; then
    install_from_current_sources "$@"
    exit
fi

mirrors="http://azure.archive.ubuntu.com/ubuntu http://archive.ubuntu.com/ubuntu"
if [ -s /etc/ssl/certs/ca-certificates.crt ]; then
    mirrors="https://archive.ubuntu.com/ubuntu https://mirrors.edge.kernel.org/ubuntu \
https://mirrors.mit.edu/ubuntu $mirrors"
fi

current="http://archive.ubuntu.com/ubuntu"
for mirror in $mirrors; do
    for sources in /etc/apt/sources.list /etc/apt/sources.list.d/ubuntu.sources; do
        [ -f "$sources" ] || continue
        sed -i -e "s#$current/\?#$mirror/#g" -e "s#http://security.ubuntu.com/ubuntu/\?#$mirror/#g" \
            "$sources"
    done
    current="$mirror"
    if install_from_current_sources "$@"; then
        exit 0
    fi
    echo "apt-install: $mirror failed, trying the next mirror" >&2
done
exit 1
