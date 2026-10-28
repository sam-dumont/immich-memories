"""One process, one GPU lane; the submitting app owns orchestration."""

import uvicorn

from immich_memories.logging_config import configure_logging
from immich_memories.tracking import otel
from immich_memories_render_worker.app import create_app
from immich_memories_render_worker.native import NativeRenderer
from immich_memories_render_worker.settings import WorkerSettings


def main() -> None:
    """Start the authenticated worker using its environment settings."""
    # WHY (#2785): the job's Python log reaches the container log, not only the run's collector.
    configure_logging()
    # Requests from a traced run carry its trace; the render's spans join it.
    otel.setup()
    settings = WorkerSettings()
    app = create_app(settings, renderer=NativeRenderer(geocoding_url=settings.geocoding_url))
    otel.instrument_app(app)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        workers=1,
        access_log=False,
    )


if __name__ == "__main__":
    main()
