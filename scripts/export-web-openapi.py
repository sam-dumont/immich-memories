"""Write the /api/v1 OpenAPI document the web client's TypeScript types are generated from."""

import argparse
import json
from pathlib import Path

from fastapi import FastAPI

from immich_memories.web import mount_web

TARGET = Path(__file__).resolve().parents[1] / "src/immich_memories/web/openapi.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=TARGET)
    app = FastAPI(title="Immich Memories", version="1")
    mount_web(app)
    parser.parse_args().out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
