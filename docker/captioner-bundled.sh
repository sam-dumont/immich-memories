#!/bin/sh
# Same CUDA image, second service: all paths are baked and never downloaded.
# Leave room for the model and worker; upstream permits an 8 GiB host cache.
export LLAMA_ARG_CACHE_RAM="${LLAMA_ARG_CACHE_RAM:-128}"
exec /opt/llama/llama-server \
    --model /opt/immich-models/captioner/model.gguf \
    --mmproj /opt/immich-models/captioner/mmproj.gguf \
    --alias smolvlm2-500m-base-public \
    --host "${CAPTION_HOST:-0.0.0.0}" --port "${CAPTION_PORT:-8092}" \
    --jinja --ctx-size 8192 --n-gpu-layers 99 "$@"
