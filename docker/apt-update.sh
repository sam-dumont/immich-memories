#!/bin/sh
# `apt-get update` that survives one unreachable package host.
#
# Every apt call gets retries and short timeouts. On Ubuntu, the update is tried against
# each mirror in turn and the sources keep the first one that answers, so the install that
# follows downloads from it too. A release once stopped because GitHub's runners could not
# reach archive.ubuntu.com:80 for hours while every other host answered.
set -eu

cat > /etc/apt/apt.conf.d/80-retries <<'CONF'
Acquire::Retries "3";
Acquire::http::Timeout "20";
CONF

[ -f /etc/os-release ] && . /etc/os-release
if [ "${ID:-}" != "ubuntu" ]; then
    exec apt-get update
fi

# Azure's mirror sits next to GitHub's runners; Canonical's archive is the reference;
# kernel.org is a third, independent host. Plain HTTP: the image has no CA bundle yet, and
# apt checks every file's signature whatever the transport.
current="http://archive.ubuntu.com/ubuntu"
for mirror in http://azure.archive.ubuntu.com/ubuntu http://archive.ubuntu.com/ubuntu \
    http://mirrors.edge.kernel.org/ubuntu; do
    for sources in /etc/apt/sources.list /etc/apt/sources.list.d/ubuntu.sources; do
        [ -f "$sources" ] || continue
        sed -i -e "s#$current/\?#$mirror/#g" -e "s#http://security.ubuntu.com/ubuntu/\?#$mirror/#g" \
            "$sources"
    done
    current="$mirror"
    if apt-get update -o APT::Update::Error-Mode=any; then
        exit 0
    fi
    echo "apt-update: $mirror did not answer, trying the next mirror" >&2
done
exit 1
