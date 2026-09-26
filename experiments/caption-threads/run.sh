#!/bin/sh
# run.sh <household> <prototype args...>: private data in the household folder, code here.
N=$1; shift
B=$HOME/.immich-memories-public-e2e/households/$N
export THREADS_ROOT=$B/threads-proto HOME=$B/captions-home
cd "$(dirname "$0")" && exec /private/tmp/imm-threads/.venv/bin/python prototype.py "$@"
