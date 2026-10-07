---
title: "Network calls and data sent"
---

# Network calls and data sent

The reader is disabled by default. With `llm.enabled: true`, a blank `base_url` and `openai-compatible` or `ollama`, the app starts
an owned local `llama-server`; its prompts stay local. Hosted provider presets fill a blank URL
with their vendor endpoint. A nonblank URL sends them to that endpoint.
Only `enabled: true` enables the reader. A model or endpoint alone leaves it disabled.

## Everything that can leave, and when

| Destination | When | What leaves your network | Default |
|---|---|---|---|
| Your Immich server | always | metadata, previews and source media; the film, its tag and its album with upload on | upload off |
| `llm.base_url` (reader) | an enabled model reads a period | text only: your memory brief/owner sentence, candidate annotations, capture dates/times, places, people and their relationships, and Immich album names holding those pictures. Never a picture | `llm.enabled: false`: no call; blank URL with `openai-compatible` or `ollama` runs locally |
| `llm.base_url` (titles) | a people or occasion film's opening title, with an enabled reader; trips only with `--llm-title` | text only: first names, birth dates and ages, recorded relationships, the date span, places by day (up to 30), and the album/occasion/holiday name. Trip prompts also include country, clip captions (up to 10) and object labels (up to 20), when available | `--no-llm-title` or `--title` |
| `llm.base_url` (music, special days) | music selection and special-day scans, with a model | text only: the cut's story labels and captions; for a day, capture times, places, coordinates and recognised names | disabled reader: no call |
| A hosted reader endpoint | an enabled reader uses a hosted provider or explicit remote `llm.base_url` | the reader rows above, with configured provider credentials | `openai`, `anthropic`, `zai` supply their preset URL when blank; blank `openai-compatible` or `ollama` runs locally |
| `caption_base_url` | GPU and Full with the default SmolVLM provider, for selected shots and actual candidates; a wider scope only with an explicit `prepare` job | a 400 px JPEG per picture; a strip of three keyframes per video and per playing Live Photo; `caption_api_key` as a bearer token if set | `localhost:8092`; Basic does not call it |
| `llm.base_url` (caption provider) | explicit `advanced.editorial.preparation.caption_provider: llm`, on any tier | synthetic schema controls, then missing picture tiles and candidate video frame strips; configured LLM credentials | off; existing valid SmolVLM captions are reused first |
| `inference.facts_base_url` | preparation, when set; generated music with stem separation; config load | picture previews and up to eight sampled frames per video or Live Photo companion; the generated WAV mix to `/audio/stems`; a GET `/health` at config load | unset: the app runs these locally |
| `render.worker_base_url` | rendering on another box | Immich URL, primary API key and every partner key needed by the cut; account routes, asset IDs, selected intervals and Live Photo material; person names, title/subtitle, dates, preset and timing metadata, audio categories/emotions, home coordinates, output/title options and the full `network` configuration | unset: renders here; the worker can make enabled geocoding/map requests itself |
| `nominatim.openstreetmap.org`, or your `network.geocoding_url` | `network.geocoding: true` | each trip's centre, and the coordinates of the pictures in the film's own window, home included, rounded to about a kilometre, once per place ever | off |
| The render worker's `IMMICH_MEMORIES_RENDER_WORKER_GEOCODING_URL` | a film rendered on the worker with `network.geocoding: true` | the same coordinates, from the worker; the app's `geocoding_url` is not used there | unset: the worker does not geocode |
| `server.arcgisonline.com` | `network.map_tiles: true` | tile requests over the trip area and your home base | off |
| `ace_step.api_url`, `musicgen.base_url` | AI music through a remote API | mood, tempo and genre text; MusicGen is also sent the generated track, for stem separation | off |
| Apprise notification URLs | `notifications.enabled: true` | memory type, outcome, duration, output path, the last 300 characters of the redacted error output; a frame if `attach_thumbnail: true` | off |
| Your OIDC provider | login with `provider: oidc` | the standard OIDC flow with PKCE | authentication off |
| Configured Immich, reader, caption, render and music endpoints | `preflight`, for enabled/configured services | service/health/model requests with their configured credentials; reader probes can request a one-token reply to `hi` | probes contain no library pictures; notifications are not sent by preflight |
| `huggingface.co`, `github.com` | `models fetch`, the web UI's **Fetch models** button (same command, as a job); permitted detector downloads during preparation; inference startup or first use | model requests, no library data | app detector downloads off unless `allow_model_downloads: true`; Compose inference allows them. The GPU overlay's one-shot `immich-memories-caption-models` container fetches the SmolVLM weights at `docker compose up`, before the captioner starts |
| `dl.fbaipublicfiles.com` | local Demucs on first use, including `capabilities --test-music` | Torch Hub weight requests, no library data | optional stem separation; cache prevents repeat downloads |
| Hugging Face and its download/CDN hosts | ACE-Step `lib` mode checkpoint preparation, including music capability tests | checkpoint requests, no library data | optional generated music; the app pins immutable snapshot revisions listed below and refuses incomplete snapshots |
| `raw.githubusercontent.com` | only `titles fonts --install`, `models fetch`, or while the Docker image builds | nothing about your library: 42 Noto files, 43 MB; the WordNet 3.0 corpus, 11 MB, checked by SHA-256 | a render never downloads |

The film-title caller passes names, date bounds, clip captions and preset/album facts. The title
prompt also accepts daily locations, country and object labels when a caller supplies them;
the ordinary film-title caller currently leaves those three optional inputs unset.

`preflight`'s **Outside call** rows cover geocoding and map tiles only, naming their configured
destinations. No rows means those two switches are off; it is not a complete egress audit.
The service probes above can still contact remote endpoints.

The app and inference service disable Hugging Face Hub telemetry before imports, including its
agent-detection request. This does not disable explicitly allowed model downloads.
App-managed model pins and the captioner weights are digest-checked; a Docling snapshot is
revision-pinned. Local ACE-Step prepares immutable, app-pinned Hugging Face snapshots before
initializing its handlers; API mode uses the remote server's checkpoint policy. Download URLs can redirect to CDN hosts;
a firewall allow-list needs those actual destinations too, not just the origin hosts above.


## The one picture seat

| Seat | Setting | What it is shown |
|---|---|---|
| captioner | `editorial.preparation.caption_base_url` | 400 px tiles, a 960 × 320 strip of three keyframes per video, no metadata |
| explicit LLM caption provider | `editorial.preparation.caption_provider: llm` | the same tiles and frame strips, sent through the configured LLM provider |

The LLM caption option is less efficient and can be much more expensive, especially on hosted
infrastructure. Configuring a prose reader alone never enables it.

The heads and detectors run locally or on `advanced.inference.facts_base_url` and bank their facts.
The rules editor builds the Basic draft first. GPU and Full then acquire missing captions and clip
evidence for selected shots and actual candidates. An explicit LLM-caption opt-in permits those
image requests on Basic too. Later films reuse valid entries under their actual producer;
missing facts or a changed producer can require another read. `prepare` can explicitly cover a
wider scope. The selection reader uses the resulting text and never decides sharing.
A shareable film keeps detector and exposure holds even with
`advanced.editorial.strict_sharing: false`; a caption cannot clear them. Only your explicit
clearance on a picture can lift those holds. `strict_sharing` also permits clean-evidence sharing
on Basic without captions.

Two features ask a reader something besides the editor, and both send text only. Music
selection reads the cut's text (thesis, story titles, ingest captions) and falls back to the clips'
own mood, then `calm`; `music add` on a standalone video takes `--mood` or plays calm, and sends
nothing. A special-day scan uses prepared captions for a day with at least 20 described pictures
over 6 hours of the clock, and the day's recorded facts below that.


## Fonts

A render never downloads a font. Titles use fonts for the supported scripts, and where it comes from
depends on how you installed:

- **Docker:** the image fetches all 42 Noto script files at build time, each checked against a
  SHA-256 pinned in the code. A running container includes the shipped script-font collection and makes no font download.
- **pip / uv:** the wheel carries the title families and Noto Sans (Latin, Greek, Cyrillic,
  Vietnamese). Arabic, Hebrew, the Indic scripts, Thai, Chinese, Japanese, Korean and the rest are
  43 MB, so they come from one explicit step:

```bash
immich-memories titles fonts --install
```

It fetches from `raw.githubusercontent.com` (the Noto project's repositories, pinned to one commit
and one tag) and refuses any file whose digest doesn't match. Skip it, and a title with letters no
installed font covers draws what it can and logs one line naming the step.


## Geocoding and maps

Both off. Both worth turning on if you are fine with what they send.

```yaml
network:
  geocoding: false
  geocoding_url: ""       # a self-hosted Nominatim, e.g. http://nominatim.lan:8080
  map_tiles: false
```

**`geocoding`** asks Nominatim about each trip's centre and about the places of the pictures in
the film's own window (a month, a year), home included, each rounded to 2 decimals (about a
kilometre) before it leaves. Nothing else goes with it: no picture, no date, no name. One request
per place, at most one a second, with a User-Agent naming this app, and every answer is kept in the
[store](.././database.md), "nothing here" included, so a place is asked about once, ever, not once per
film. A first year at home is a few hundred places; after that almost nothing. The rest of the
library is never walked.

What it buys:

- **City and village names.** Immich can label a picture after a nearby town or district.
  The display uses OpenStreetMap's city, town or village: Berlin across its neighborhoods,
  rather than a new label for Mitte or Kreuzberg. Captions, location cards and map pins agree.
- **Trip names from the map**, at the trip's scale: the village rather than the merged
  municipality it belongs to, the town, or the region.
- **Names in the film's language** ("Nicosie" instead of "Nicosia"). Country names are translated
  offline either way.

A nightly `auto run` that finds a trip geocodes it the same way. Set `geocoding_url` to your own
Nominatim and the requests go there instead; the switch still has to be on.

**`map_tiles`** fetches ArcGIS World Imagery for the trip fly-over, the static trip map and the
background of location cards: hundreds of tiles for a fly-over, a handful for a card. Off, a trip
opens on the ordinary title card and location cards keep their text on the style's background.

Privacy mode stops the cut's places from being asked about, but not the trip names: with
`geocoding: true` a trip's real centre has been asked about before the fake city is picked.


## Files on disk, and cancellation

The annotation database and its SQLite sidecars are restricted to the current user. Previews are
replaced atomically at mode `0600`; a corrupt preview gets one fresh fetch. Cancellation stops
before the next caption request and terminates the detector worker's process group; committed
facts stay for the next run.

## ACE-Step checkpoint revisions

Local `ace_step.mode: lib` downloads these immutable Hugging Face revisions before
initializing ACE-Step 1.5. The shared snapshot is always needed; only the selected
extra DiT and planner are downloaded. API mode uses the remote server's checkpoints.

| Repository | Commit |
| --- | --- |
| [ACE-Step/Ace-Step1.5](https://huggingface.co/ACE-Step/Ace-Step1.5/tree/19671f406d603126926c1b7e2adc169acbcade22) | `19671f406d603126926c1b7e2adc169acbcade22` |
| [ACE-Step/acestep-5Hz-lm-0.6B](https://huggingface.co/ACE-Step/acestep-5Hz-lm-0.6B/tree/148d8ea0225bdab342ee1ae3a354275ccd60ca80) | `148d8ea0225bdab342ee1ae3a354275ccd60ca80` |
| [ACE-Step/acestep-5Hz-lm-4B](https://huggingface.co/ACE-Step/acestep-5Hz-lm-4B/tree/0a3ec94b557aea7d508da38b31cfe7341f6ff737) | `0a3ec94b557aea7d508da38b31cfe7341f6ff737` |
| [ACE-Step/acestep-v15-turbo-shift3](https://huggingface.co/ACE-Step/acestep-v15-turbo-shift3/tree/625a282f7c8d882c930a5e500be4c82800f84fb4) | `625a282f7c8d882c930a5e500be4c82800f84fb4` |
| [ACE-Step/acestep-v15-sft](https://huggingface.co/ACE-Step/acestep-v15-sft/tree/c410d249e71ea9385a7b586865e65b1473e1098d) | `c410d249e71ea9385a7b586865e65b1473e1098d` |
| [ACE-Step/acestep-v15-base](https://huggingface.co/ACE-Step/acestep-v15-base/tree/e432212fec32b8965a14ffa57ae653438d6abd14) | `e432212fec32b8965a14ffa57ae653438d6abd14` |
| [ACE-Step/acestep-v15-turbo-shift1](https://huggingface.co/ACE-Step/acestep-v15-turbo-shift1/tree/5b86586cc1faecd5214281b05440c8903b6da20f) | `5b86586cc1faecd5214281b05440c8903b6da20f` |
| [ACE-Step/acestep-v15-turbo-continuous](https://huggingface.co/ACE-Step/acestep-v15-turbo-continuous/tree/f8e893768347fd42f5988e07d1d80675fc3e5718) | `f8e893768347fd42f5988e07d1d80675fc3e5718` |
| [ACE-Step/acestep-v15-xl-base](https://huggingface.co/ACE-Step/acestep-v15-xl-base/tree/220c1166efbdd9583eafcb12eb160594bbfcb241) | `220c1166efbdd9583eafcb12eb160594bbfcb241` |
| [ACE-Step/acestep-v15-xl-sft](https://huggingface.co/ACE-Step/acestep-v15-xl-sft/tree/d06de46b4622f781cf07f4a013a67d591ca52819) | `d06de46b4622f781cf07f4a013a67d591ca52819` |
| [ACE-Step/acestep-v15-xl-turbo](https://huggingface.co/ACE-Step/acestep-v15-xl-turbo/tree/d4a0b288b83ebb7e25a8c0b32c573c22e134e8ee) | `d4a0b288b83ebb7e25a8c0b32c573c22e134e8ee` |

The snapshots live in a `pinned-<checkpoint-set>` subdirectory of
`ACESTEP_CHECKPOINTS_DIR` (default `~/.cache/ace-step/checkpoints`). Existing
unpinned files stay untouched and are not used. A failed or incomplete download
stops initialization instead of falling back to the latest upstream weights.
Updating a pin selects a new cache directory.
