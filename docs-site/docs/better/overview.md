---
title: What a model adds, what it costs
---

# What a model adds, what it costs

Immich Memories makes the whole film on a plain NAS. The add-ons below make it better or faster,
and each one plugs into the same install. Everything they work out is banked next to what the NAS
already knows, so switching one off later loses nothing.

What each one adds, feature by feature, is on
[What a GPU or a model adds](../get-started/what-a-gpu-or-a-model-adds.md). This page is the
practical side: what each add-on needs, and what it sends where.

```mermaid
flowchart LR
    nas["The NAS makes the film<br/><small>rules editor, heads, detectors, render</small>"]
    reader(["A reader model<br/><small>titles; Full refinement</small>"]) -.-> nas
    captions(["A caption server<br/><small>selected shots and candidates</small>"]) -.-> nas
    inference(["Inference on a GPU box<br/><small>the same facts, sooner</small>"]) -.-> nas
    render(["A render worker<br/><small>the encode off the NAS</small>"]) -.-> nas
    music(["Generated music<br/><small>ACE-Step or MusicGen</small>"]) -.-> nas
```

## The add-ons

| Add-on | What it buys | What it needs | What leaves the box |
|---|---|---|---|
| [A reader](./reader.md) | Titles and music mood on every tier; on Full, an account of the period and refinement of the NAS draft | A text model with a 32k context, such as local Gemma 4 E4B. Selection refinement also needs GPU capability, captions and Laya | The candidates' annotation lines, people and place names included, to the model. Never a picture |
| [Captions](./captions.md) | Descriptions for selected pictures and replacement candidates, used by the reader and Laya | The supported 500M vision model, or explicit opt-in to a vision-capable LLM | A 400 px tile of each requested picture, once per caption generation, to the chosen provider |
| [Inference on a GPU box](./inference.md) | The encoder, its eight heads and the two detectors on a card or a bigger CPU | A second machine, CPU or NVIDIA | A preview of each picture, once, to your service |
| [A render worker](./gpu-render.md) | The encode on a GPU box instead of the NAS | An NVIDIA box running the same app version | The chosen cut and your Immich key; the worker fetches the originals itself |
| [Generated music](./music.md) | An original track per film instead of a bundled one | ACE-Step on a Mac or an NVIDIA box (7 to 29 GB free for its weights), or a MusicGen server | A text prompt (mood, tempo, length) to your music server |

Every destination defaults to `localhost` or off. Pointing one at another host is the consent step,
and [Privacy](../run/privacy.md) lists every switch.

## How the model changes the cut

On the `full` tier the rules editor still builds the draft. The model reads it, writes an account
of the period, and polishes it: it names the shots that add nothing and swaps in better pictures of
the same moments, while favourites, close family and the family-viewing holds stay put. If the model
can't answer, the rules draft ships and the log says why. How the polish decides, with diagrams:
[What a model adds](../how-it-chooses/what-a-model-adds.md). Which setup reaches `full`:
[The three tiers](../run/requirements.md#the-preparation-tier).

## What it costs

Time, memory and euros per setup belong on [Measured](./measured.md), with the code revision,
hardware and cache state. Plan for these costs:

- The reader and caption server need memory alongside the app. Reader memory also depends on
  context length and concurrent requests, not just the model's weight size.
- NAS does not require a caption server. GPU and Full need a caption provider and reuse existing captions.
- A hosted reader bills tokens, and the prose is banked, so a week is paid for once, not once per
  film.
