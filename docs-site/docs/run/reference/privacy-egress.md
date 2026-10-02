---
title: "Network calls and data sent"
---

# Network calls and data sent

The reader is disabled by default. With `llm.enabled: true` and blank `base_url`, the app starts
an owned local `llama-server`; its prompts stay local. A nonblank URL sends them to that endpoint.
Explicit model or endpoint configuration can enable the reader unless `enabled: false` is set.

## Everything that can leave, and when

| Destination | When | What leaves your network | Default |
|---|---|---|---|
| Your Immich server | always | the reads above; the film, its tag and its album with upload on | upload off |
| `llm.base_url` (reader) | a model reads a period | text only: the annotation lines of the candidates, with people and place names, and the Immich album names holding those pictures. Never a picture | `llm.enabled: false`: no call; blank `base_url` with an enabled reader runs locally |
| `llm.base_url` (titles) | a people or occasion film's opening title, whenever a reader is configured; trips only with `--llm-title` | text only: first names, birth dates and ages, the relationships your people registry records, the span, place names, the album the cut mostly sits in | `--no-llm-title` or `--title` |
| `llm.base_url` (music, special days) | music selection and special-day scans, with a model | text only: the cut's story labels and captions; for a day, capture times, places, coordinates and recognised names | disabled reader: no call |
| A hosted reader endpoint | An enabled reader has an explicit remote `llm.base_url` | the reader rows above, to the configured endpoint | blank `base_url` uses an owned local reader; provider names alone do not select a vendor endpoint |
| `caption_base_url` | GPU and Full with the default SmolVLM provider, for selected shots and actual candidates; a wider scope only with an explicit `prepare` job | a 400 px JPEG per picture; a strip of three keyframes per video and per playing Live Photo; `caption_api_key` as a bearer token if set | `localhost:8092`; NAS does not call it |
| `llm.base_url` (caption provider) | explicit `advanced.editorial.preparation.caption_provider: llm`, on any tier | synthetic schema controls, then missing picture tiles and candidate video frame strips; configured LLM credentials | off; existing valid SmolVLM captions are reused first |
| `inference.facts_base_url` | preparation, when set | picture previews and up to eight sampled frames per video or Live Photo companion, for the heads and detectors | unset: the app runs them itself |
| `render.worker_base_url` | rendering on another box | the chosen cut, plus your Immich URL and API key so the worker can fetch the clips | unset: renders here |
| `nominatim.openstreetmap.org`, or your `network.geocoding_url` | `network.geocoding: true` | each trip's centre, and the coordinates of the pictures in the film's own window, home included, rounded to about a kilometre, once per place ever | off |
| `server.arcgisonline.com` | `network.map_tiles: true` | tile requests over the trip area and your home base | off |
| `ace_step.api_url`, `musicgen.base_url` | AI music through a remote API | mood, tempo and genre text; MusicGen is also sent the generated track, for stem separation | off |
| Apprise or ntfy targets | `notifications.enabled: true` | memory type, outcome, duration, output path, a redacted error tail; a frame if `attach_thumbnail: true` | off |
| Your OIDC provider | login with `provider: oidc` | the standard OIDC flow with PKCE | authentication off |
| Hugging Face, `github.com` | only when you run `models fetch` (and ACE-Step or Demucs on first use) | nothing about your library: pinned weights, checked by SHA-256; ACE-Step's own first-use download takes the library's current checkpoint, not a pinned revision | a run never downloads |
| `raw.githubusercontent.com` | only `titles fonts --install`, `models fetch`, or while the Docker image builds | nothing about your library: 42 Noto files, 43 MB; the WordNet 3.0 corpus, 11 MB, checked by SHA-256 | a render never downloads |

`preflight` prints one row per outside switch you turned on, naming the host. A default install
prints none.


## The one picture seat

| Seat | Setting | What it is shown |
|---|---|---|
| captioner | `editorial.preparation.caption_base_url` | 400 px tiles, a 960 × 320 strip of three keyframes per video, no metadata |
| explicit LLM caption provider | `editorial.preparation.caption_provider: llm` | the same tiles and frame strips, sent through the configured LLM provider |

The LLM caption option is less efficient and can be much more expensive, especially on hosted
infrastructure. Configuring a prose reader alone never enables it.

The heads and detectors run locally or on `advanced.inference.facts_base_url` and bank their facts.
The rules editor builds the NAS draft first. GPU and Full then acquire missing captions and clip
evidence for selected shots and actual candidates. An explicit LLM-caption opt-in permits those
image requests on NAS too. Later films reuse valid entries under their actual producer;
missing facts or a changed producer can require another read. `prepare` can explicitly cover a
wider scope. The selection reader uses the resulting text and never decides sharing.
A film you share outside the family also leaves out every picture a detector or an exposure flag
marked, whatever the reader says about it (`advanced.editorial.strict_sharing`, on by default).

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

- **The right district.** Immich names a picture after the nearest town in GeoNames' list of
  places over 500 people. A district that is not its own municipality gets its neighbour's name:
  a picture in Wilrijk says "Hoboken". OpenStreetMap knows the district, so captions, location
  cards and trip map pins say "Wilrijk".
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
