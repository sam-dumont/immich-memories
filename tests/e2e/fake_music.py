"""A text model that reads a cut as playful and a music backend that writes one second of tone.

The music preview child runs the real `music preview` with these two remote services scripted,
and leaves what each was asked beside the state dir, for the test to read.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

MODEL_REQUEST = "model-request.json"
MUSIC_REQUEST = "music-request.json"

# The CLI child bootstrap with the two services scripted; argv is config, state dir, then the CLI's.
MUSIC_CLI_BOOTSTRAP = """
import sys
from pathlib import Path

from tests.e2e.fake_music import install_fake_music

install_fake_music(Path(sys.argv[2]))

from tests.e2e.cli_bootstrap import CLI_BOOTSTRAP

exec(CLI_BOOTSTRAP)
"""


def install_fake_music(records: Path) -> None:
    """Script the text model and the music backend for this process; record what each was asked."""
    import httpx

    from immich_memories.audio import music_pipeline
    from immich_memories.audio.generators.base import GenerationResult, MusicGenerator

    records.mkdir(parents=True, exist_ok=True)

    async def model_post(_self, url, **kwargs):
        (records / MODEL_REQUEST).write_text(json.dumps(kwargs["json"]))
        return httpx.Response(
            200,
            request=httpx.Request("POST", str(url)),
            json={
                "response": json.dumps(
                    {
                        "primary_mood": "playful",
                        "energy_level": "high",
                        "tempo_suggestion": "fast",
                        "genre_suggestions": ["pop"],
                        "specific_style": None,
                    }
                ),
                "done": True,
            },
        )

    class ToneGenerator(MusicGenerator):
        @property
        def name(self):
            return "synthetic audio"

        async def is_available(self):
            return True

        async def generate(self, request, progress_callback=None):
            (records / MUSIC_REQUEST).write_text(json.dumps(request.scenes))
            track = request.output_dir / "preview.wav"
            with wave.open(str(track), "wb") as output:
                output.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                output.writeframes(b"\x00\x00" * 8000)
            return GenerationResult(audio_path=track)

    # WHY: the text model is a remote service; only its reply is scripted, the request is real.
    httpx.AsyncClient.post = model_post
    # WHY: the music backend is a remote GPU service; a tone stands in for the track it returns.
    music_pipeline.create_pipeline = lambda *_args, **_kwargs: music_pipeline.MusicPipeline(
        [ToneGenerator()]
    )
