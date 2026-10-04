# Where the speech/music fixtures come from

`synthetic_speech_16k.npy` is synthesised (see `generate_synthetic_speech.py`);
it contains no one's recorded voice.

`singing_excerpt_16k.npy` is a 3 s trim of a real CC0 recording, needed because
#1951's music/singing detection has to be proven against real sung audio, not
a model of speech.

| File | Title | Author | Source | Licence |
| --- | --- | --- | --- | --- |
| `singing_excerpt_16k.npy` | Twinkle Twinkle Little Star - sung with full lyrics | Dcoetzee | https://commons.wikimedia.org/wiki/File:Twinkle_Twinkle_Little_Star_-_sung_with_full_lyrics.ogg | CC0 1.0 |

See `generate_singing_excerpt.py` for the exact trim and resample.
