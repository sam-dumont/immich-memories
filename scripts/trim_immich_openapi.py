#!/usr/bin/env python3
"""Trim the Immich OpenAPI specs to the requests Immich Memories sends.

The test fakes (`tests/immich_fakes.py`) validate every request against this trimmed
contract, so a fake refuses what the real Immich refuses, version by version.

    curl -sSfLo /tmp/specs/v3.3.0.json \\
        https://raw.githubusercontent.com/immich-app/immich/v3.3.0/open-api/immich-openapi-specs.json
    uv run python scripts/trim_immich_openapi.py /tmp/specs/v2.7.5.json /tmp/specs/v3.2.2.json \\
        /tmp/specs/v3.3.0.json

Each input is named after its Immich release. The output keeps, per release and per
endpoint, the path, query and JSON body parameters with their type, format, pattern,
enum, bounds, and whether they are required or nullable. Nothing else.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "fixtures" / "immich-openapi" / "contract.json"

# Every Immich request the app sends (method, OpenAPI path). tests/test_immich_fakes.py
# fails when src/immich_memories/api/ calls an Immich endpoint this list lacks.
ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("GET", "/albums"),
    ("POST", "/albums"),
    ("GET", "/albums/{id}"),
    ("PUT", "/albums/{id}/assets"),
    ("GET", "/api-keys/me"),
    ("DELETE", "/assets"),
    ("POST", "/assets"),
    ("POST", "/assets/bulk-upload-check"),
    ("GET", "/assets/{id}"),
    ("GET", "/assets/{id}/edits"),
    ("GET", "/assets/{id}/ocr"),
    ("GET", "/assets/{id}/original"),
    ("GET", "/assets/{id}/thumbnail"),
    ("GET", "/assets/{id}/video/playback"),
    ("GET", "/faces"),
    ("GET", "/people"),
    ("GET", "/people/users"),
    ("GET", "/people/{id}"),
    ("GET", "/people/{id}/statistics"),
    ("GET", "/people/{id}/thumbnail"),
    ("POST", "/search/metadata"),
    ("POST", "/search/statistics"),
    ("GET", "/server/ping"),
    ("GET", "/server/version"),
    ("GET", "/stacks"),
    ("GET", "/tags"),
    ("PUT", "/tags"),
    ("PUT", "/tags/{id}/assets"),
    ("GET", "/timeline/bucket"),
    ("GET", "/timeline/buckets"),
    ("GET", "/users/me"),
)

_KEPT = ("type", "format", "pattern", "enum", "minimum", "maximum", "nullable")


def _resolve(schema: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Follow $ref and single-entry allOf/anyOf wrappers to the schema they name."""
    while True:
        if "$ref" in schema:
            schema = {
                **spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]],
                **{k: v for k, v in schema.items() if k != "$ref"},
            }
            continue
        for key in ("allOf", "anyOf", "oneOf"):
            options = [s for s in schema.get(key, []) if s.get("type") != "null"]
            if key in schema and len(options) == 1:
                nullable = len(schema[key]) > 1 or schema.get("nullable", False)
                rest = {k: v for k, v in schema.items() if k != key}
                schema = {**options[0], **rest, **({"nullable": True} if nullable else {})}
                break
        else:
            return schema


def _field(schema: dict[str, Any], spec: dict[str, Any], required: bool) -> dict[str, Any]:
    schema = _resolve(schema, spec)
    kept: dict[str, Any] = {k: schema[k] for k in _KEPT if k in schema}
    if isinstance(kept.get("type"), list):  # OpenAPI 3.1: ["string", "null"]
        types = [t for t in kept["type"] if t != "null"]
        kept["nullable"] = len(types) < len(kept["type"]) or kept.get("nullable", False)
        kept["type"] = types[0]
    if kept.get("type") == "array":
        kept["items"] = _field(schema.get("items", {}), spec, required=False)
        kept["items"].pop("required", None)
    if "properties" in schema:
        required_names = set(schema.get("required", []))
        kept["properties"] = {
            name: _field(prop, spec, name in required_names)
            for name, prop in sorted(schema["properties"].items())
        }
    if "maximum" in kept and kept["maximum"] >= 2**53 - 1:
        del kept["maximum"]  # Number.MAX_SAFE_INTEGER: no bound in practice
    kept["required"] = required
    return kept


def trim(spec: dict[str, Any]) -> dict[str, Any]:
    """The endpoints the app calls, reduced to what a request must satisfy."""
    trimmed: dict[str, Any] = {}
    for method, path in ENDPOINTS:
        operation = spec["paths"].get(path, {}).get(method.lower())
        if operation is None:
            continue
        entry: dict[str, Any] = {"path": {}, "query": {}, "body": None}
        for parameter in operation.get("parameters", []):
            if parameter["in"] in ("path", "query"):
                entry[parameter["in"]][parameter["name"]] = _field(
                    parameter.get("schema", {}), spec, parameter.get("required", False)
                )
        content = operation.get("requestBody", {}).get("content", {})
        if "application/json" in content:
            body = _resolve(content["application/json"]["schema"], spec)
            required = set(body.get("required", []))
            entry["body"] = {
                name: _field(prop, spec, name in required)
                for name, prop in sorted(body.get("properties", {}).items())
            }
        elif "multipart/form-data" in content:
            # A form upload: every field arrives as text (assetData as the file part).
            form = _resolve(content["multipart/form-data"]["schema"], spec)
            required = set(form.get("required", []))
            entry["form"] = {
                name: _field(prop, spec, name in required)
                for name, prop in sorted(form.get("properties", {}).items())
            }
        trimmed[f"{method} {path}"] = entry
    return trimmed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("specs", nargs="+", type=Path, help="<release>.json, e.g. v3.3.0.json")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    contract = {
        path.stem: trim(json.loads(path.read_text(encoding="utf-8"))) for path in sorted(args.specs)
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(contract, indent=1, sort_keys=True) + "\n")
    print(f"Wrote {args.output} ({', '.join(contract)})")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
