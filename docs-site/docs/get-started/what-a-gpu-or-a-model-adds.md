---
title: What a GPU or a model adds
---

# What a GPU or a model adds

Immich Memories makes the whole film on a plain NAS: one container, one `models fetch`, no GPU, no
model to host. A GPU and a text model each add features on top of that. Nothing is lost when you
add one later, because everything the app works out about a picture is banked and reused.

The app picks its setup by itself (`tier: auto`): a plain NAS by default, **GPU** once it finds a
usable GPU and the caption server, **Full** when a text model is configured as well.

## Feature by feature

| Feature | Plain NAS | + GPU | + GPU and a model (Full) |
|---|---|---|---|
| **Choosing the pictures** | The rules editor builds the film from dates, places, favourites, the people Immich knows, and a picture encoder with eight small classifiers and two detectors, all on the CPU | Same draft | The model reads the finished draft in blocks of 12 shots, names the ones that add nothing and swaps in better pictures of the same moments |
| **A description of each picture** | None | A one-line caption for every picture in the cut and every candidate to replace one | Same, and the model reads them |
| **Family-viewing check** | Rules and a sensitive-content detector hold back what isn't for sharing | A second reader checks the captions and can hold more pictures back (never fewer) | Same as GPU. The text model never decides what is shareable |
| **The title** | Built from the dates, the people and the year, or the album, holiday or trip name | Same | Written by the model from what the film holds |
| **The music** | A bundled track, calm by default | Same | The model picks the mood, tempo and genre from what the cut is about |
| **Reading the pictures** | On the CPU, once per picture, then banked | The encoder and classifiers run on the GPU: the same answers, sooner | Same as GPU |

A text model on its own, with no GPU, still writes titles and picks the music mood. Choosing the
pictures stays on the NAS rules until the GPU tier is there too, because the model's polish reads the
captions.

## What each one needs

- **A GPU:** an NVIDIA card or a Mac, either in this box or running the
  [inference service](../better/inference.md) on another machine, plus the
  [caption server](../better/captions.md).
- **A model:** any OpenAI-compatible text model with a 32k context, local (such as Gemma 4 E4B)
  or hosted: [Add a reader](../better/reader.md).

## Two more, separate from the tiers

- **Encoding and title effects:** any GPU the render can reach (an Intel or AMD iGPU through VA-API
  or Quick Sync, NVIDIA through NVENC, a Mac through VideoToolbox) encodes the film faster and draws
  the animated title effects. Without one, the CPU encodes and the titles keep their text and timing
  without the effects: [Hardware encoding](../run/hardware.md). A
  [render worker](../better/gpu-render.md) moves the whole render to an NVIDIA box.
- **Generated music:** an original track for each film instead of a bundled one, from ACE-Step or
  MusicGen: [Generated music](../better/music.md).

What each add-on sends where is on [Privacy](../run/privacy.md), and the time and memory each one
costs is on [Measured](../better/measured.md).
