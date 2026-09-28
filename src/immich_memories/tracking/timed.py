"""Function boundaries for spans, including async reader calls."""

from functools import wraps
from inspect import iscoroutinefunction

from immich_memories.tracking.timing import span


def timed(name: str, *, items: int | None = None):
    """Measure an operation without changing its public call signature."""

    def decorate(function):
        if iscoroutinefunction(function):

            @wraps(function)
            async def measured_async(*args, **kwargs):
                with span(name, items=items):
                    return await function(*args, **kwargs)

            return measured_async

        @wraps(function)
        def measured(*args, **kwargs):
            with span(name, items=items):
                return function(*args, **kwargs)

        return measured

    return decorate
