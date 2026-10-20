"""Size FFmpeg's, OpenCV's, OpenMP's and BLAS's thread pools from the CPU this process may use.

FFmpeg's default is one thread per core of the host. In a container with a CPU
limit that is far more than the limit allows: the threads fight over the quota
and the render burns its budget on contention. Every FFmpeg a render starts goes
through `with_cpu_threads`, which reads the limit from `available_cpus`. torch's
OpenMP pool and the OpenBLAS copies NumPy and OpenCV carry make the same mistake
when they load, so `limit_native_pools` runs when the package is imported.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping, Sequence

from immich_memories.processing.memory_budget import available_cpus

# libx265 reads the output's `-threads` as its frame threads and refuses to open past 16.
_MOST_ENCODER_THREADS = 16
_THREAD_OPTIONS = ("-threads", "-filter_threads", "-filter_complex_threads")
# Read once, when torch (OpenMP), NumPy and OpenCV (OpenBLAS) or an MKL build load.
_NATIVE_POOL_VARIABLES = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")


def with_cpu_threads(
    cmd: Sequence[str], cpus: int | None = None, *, program_tokens: int = 1
) -> list[str]:
    """Return `cmd` with thread counts set wherever it left them to FFmpeg.

    The pools set are the filter graph's (global), each input's decoder (before
    its `-i`) and the output's encoder (before the output path). The first
    `program_tokens` entries are the program and its own arguments. A count the
    caller already chose is kept, so callers with their own budget are untouched.
    """
    count = str(max(1, cpus if cpus is not None else available_cpus()))
    command = list(cmd)
    if len(command) <= program_tokens:
        return command

    present = {option for option in command if option in _THREAD_OPTIONS}
    head = command[:program_tokens]
    for option in ("-filter_threads", "-filter_complex_threads"):
        if option not in present:
            head += [option, count]
    rest = command[program_tokens:]

    out: list[str] = []
    group_has_threads = False
    for arg in rest:
        if arg == "-threads":
            group_has_threads = True
        if arg == "-i" and not group_has_threads:
            out += ["-threads", count]
        out.append(arg)
        if arg == "-i":
            group_has_threads = False
    # FFmpeg ends every command with its output; the encoder's pool is set before it.
    if len(out) >= 2 and out[-2] != "-i" and not group_has_threads:
        out[-1:-1] = ["-threads", str(min(int(count), _MOST_ENCODER_THREADS))]
    return head + out


def limit_opencv_threads(cpus: int | None = None) -> None:
    """Keep OpenCV's pool, which defaults to the host's cores, inside the CPU limit."""
    import cv2

    cv2.setNumThreads(max(1, cpus if cpus is not None else available_cpus()))


def limit_native_pools(
    environ: MutableMapping[str, str] | None = None, cpus: int | None = None
) -> None:
    """Size the OpenMP and BLAS pools from the CPU limit before any library reads them.

    Left unset, each sizes itself from the host's cores: on a 16-core node with a 12-CPU
    limit torch separated stems on 16 threads, and under a 4-CPU limit on a 10-core host
    NumPy and OpenCV each kept 9 OpenBLAS threads. A value the operator set is kept.
    """
    environ = os.environ if environ is None else environ
    count = str(max(1, cpus if cpus is not None else available_cpus()))
    for name in _NATIVE_POOL_VARIABLES:
        environ.setdefault(name, count)


def limit_torch_threads() -> None:
    """Keep torch's intra-op pool inside the CPU limit, even if torch loaded before the package.

    An operator's OMP_NUM_THREADS is the count; otherwise the limit is.
    """
    import torch

    configured = os.environ.get("OMP_NUM_THREADS", "")
    torch.set_num_threads(max(1, int(configured)) if configured.isdigit() else available_cpus())
