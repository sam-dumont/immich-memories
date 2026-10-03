---
title: Choose your setup
description: What Basic, GPU and Full add, what they cost, and where to start.
---

import SetupBuilder from '@site/src/components/SetupBuilder';

# Choose your setup

The Basic tier makes a complete film: stories, favourites, people, trips, time order, titles and
bundled music. It runs on a NAS, a Mac or a cluster without GPU inference. Start there. Add services for a change you want to see in the film.

<SetupBuilder />

For an existing installation, change service URLs and reader credentials in Settings.
The generated commands configure reader authentication before preflight.

| Setup | What you gain | What runs |
|---|---|---|
| **Basic** | A complete edit from metadata and small CPU picture classifiers | The app |
| **GPU** | Picture descriptions, more context for selection and extra sharing checks | The app, inference and a caption service, with Laya ready |
| **Full** | GPU features plus a text reader's small corrections to the draft | The GPU setup and an explicitly enabled reader |

A **video encoder** speeds up rendering. It does not enable the GPU selection tier.
[Hardware encoding](../run/hardware.md) and the [render worker](../better/gpu-render.md) are
separate choices.

Use `tier: basic` to select it explicitly. Existing `tier: nas` settings remain accepted as
an alias and resolve to `basic`; GPU and Full values are unchanged.

See [Can I run this?](../run/tested-deployments.md) for exact platform evidence, candidate versions and untested routes.

## Basic: start with the film

The app reads your library's dates, favourites, people and locations, prepares picture facts on
its CPU, and builds the edit. Template titles and bundled music are included. There is no model
server to run and no hosted AI subscription to buy.

**Fast path:** follow the [Quick start](./quick-start.md), then the
[After install](./after-install.md) steps. Docker Compose needs two CPU cores, 4 GiB free RAM
and about 25 GB for persistent data, plus room for the image and finished films.
[NAS notes](../run/nas.md) cover permissions and access from your desktop.

**Cost:** the first cut prepares the pictures in its period. Later cuts reuse compatible facts;
they still render the video. Basic output stops at 1080p. The
[finished-film measurements](../better/measured.md#whole-film-controls) include a one-minute
NAS month that took 7m 23s with picture facts already prepared. That is not a first-install time.

**Check:** `capabilities` should report Basic. A software encoder is a valid result. Run
`preflight` after `models fetch` and resolve errors before cutting a month.

## GPU: understand more of the pictures

Captions add information beyond dates and faces: what is happening, what objects are present,
and how a picture fits the story. The GPU tier also adds document and sensitive-content checks
and a family-viewing pre-screen. Review the cut before sharing it; model checks can miss things.
See [what GPU changed in one CC0 month](../better/gpu-example.md): two different videos and
two additional source exclusions. Both tiers kept all four favourites. The example records
the changed cut and its limits; it does not claim that a model always improves a film.

**Fast path:** on Apple Silicon, use the [native Mac setup](../run/reference/mac-example.md).
The `all-mac` extra makes Metal available to automatic tier detection; captions still need a
server. On a NAS, use [GPU inference](../better/inference.md) and
[captions](../better/captions.md) on a machine you control. The
[combined GPU service](../run/reference-setup.md#one-gpu-service) can host both.

**Cost:** more model downloads and preparation work, plus memory for the model services.
For 4K output, allow at least 8 GB for the app in addition to those services. A second machine
adds network transfer and another service to maintain; a GPU does not remove the first preparation.

**Check:** `capabilities` should report GPU. `preflight` must also find the caption service and
Laya runtime/checkpoint. Detecting a GPU alone does not prove either is ready.

## Full: refine the draft

The rules editor still builds the film. A text model reads that draft and can propose small
changes, such as replacing a weak shot or tightening a story. Each change must pass the selection
checks. If the reader cannot answer, the app keeps the rules draft and reports why.
Watch the separate [Basic and Full example](../better/tier-example.md): 13 of 14 shots overlap,
with one replacement. It is one observed cut, not a quality guarantee.

**Fast path:** start with the GPU setup, then enable a [text reader](../better/reader.md).
Use its exact served model name and URL, and explicitly set `llm.enabled` to `true`.
Entering a URL alone does not turn the reader on. Native Mac and Linux installs can run the
app-owned reader locally; Docker and Kubernetes use an external reader server.

**Cost:** another model's memory and time, or the hosted provider's fees. The reader receives
annotation text, including people and place names. It does not receive the original pictures
for this edit pass. [Privacy](../run/privacy.md) lists each service and what it receives.

**Check:** `capabilities` should report Full. `preflight` checks the reader as well as the GPU
requirements. Compare the same month before deciding whether the changes are worth it to you.
[What a model adds](../how-it-chooses/what-a-model-adds.md) explains which edits it may propose.

### A reader on NAS

You can enable a reader for written titles and music mood while keeping Basic selection. It does
not enable the Full edit pass or sentence films by itself. Generated music is another optional
service; [bundled music already works](../make/titles-maps-music.md).

## Pick the platform

| You already have | Install path |
|---|---|
| Linux with Docker | [Docker Compose](../run/docker.md) |
| Synology or another NAS | [NAS setup](../run/nas.md) |
| Apple Silicon Mac | [Native Mac setup](../run/reference/mac-example.md) |
| Kubernetes cluster | [Kubernetes](../run/kubernetes.md) |

The [tested setups table](../better/measured.md#tested-setups) separates installation checks,
picture preparation and finished films. It names missing measurements too. Rendering benchmarks
alone do not prove that a new user can install and finish a film.

## Change services later

Use **Settings** for inference and caption URLs, and the reader's URL, model and enabled switch.
If a field is locked, its source tells you which environment variable or YAML value controls it;
[move that value into Settings](../run/config-file.md#moving-a-key-out-of-the-file) first.
Compatible picture facts and your review decisions survive a tier change.

Check after each change:

```bash
immich-memories preflight
immich-memories capabilities
```

For Docker, prefix each command with `docker compose exec immich-memories`.
Then [cut the same month](./first-film.mdx) again and compare the results.
