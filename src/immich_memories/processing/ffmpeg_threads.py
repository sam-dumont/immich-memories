"""Size FFmpeg's and OpenCV's thread pools from the CPU this process may use.

FFmpeg's default is one thread per core of the host. In a container with a CPU
limit that is far more than the limit allows: the threads fight over the quota
and the render burns its budget on contention. Every FFmpeg a render starts goes
through `with_cpu_threads`, which reads the limit from `available_cpus`.
"""

from __future__ import annotations

from collections.abc import Sequence

from immich_memories.processing.memory_budget import available_cpus

# libx265 reads the output's `-threads` as its frame threads and refuses to open past 16.
_MOST_ENCODER_THREADS = 16
_THREAD_OPTIONS = ("-threads", "-filter_threads", "-filter_complex_threads")


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
