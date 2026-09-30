"""Synthetic text, schema and vision verification for the explicit local capability probe."""

from immich_memories.config import Config


async def verify_reader(config: Config) -> None:
    import io
    import json

    from PIL import Image

    from immich_memories.analysis.llm_query import query_llm
    from immich_memories.local_inference import local_reader_paths

    if len(local_reader_paths(config.llm)) < 2:
        raise RuntimeError("Vision projector missing; configure local_mmproj before verification")
    text = await query_llm(
        "What color is a ripe banana? Answer one word.",
        config.llm,
        max_tokens=64,
        timeout_seconds=180,
    )
    if "yellow" not in text.lower():
        raise RuntimeError("Synthetic text answer did not identify yellow")
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "color",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"color": {"type": "string", "enum": ["yellow"]}},
                "required": ["color"],
                "additionalProperties": False,
            },
        },
    }
    answer = await query_llm(
        "Return the color of a ripe banana as JSON.",
        config.llm,
        max_tokens=64,
        timeout_seconds=180,
        response_format=schema,
    )
    if json.loads(answer) != {"color": "yellow"}:
        raise RuntimeError("Synthetic JSON enum contract failed")
    image = io.BytesIO()
    Image.new("RGB", (400, 400), "red").save(image, format="JPEG")
    answer = await query_llm(
        "What is the dominant color? Answer one word.",
        config.llm,
        max_tokens=64,
        timeout_seconds=180,
        images=(image.getvalue(),),
    )
    if "red" not in answer.lower():
        raise RuntimeError("Synthetic vision answer did not identify red")
