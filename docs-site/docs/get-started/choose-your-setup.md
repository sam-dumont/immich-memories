---
title: Choose your setup
description: Choose Basic, GPU or Full and follow its installation path.
---

# Choose your setup

Every tier makes a complete film with titles and music. Choose the one that fits your hardware
and the extra picture interpretation you want.

| Tier | What changes in the film | Install |
|---|---|---|
| **Basic** | Dates, favourites, people and places guide the edit; small CPU classifiers read the pictures. Output is up to 1080p. | [Docker Compose](./quick-start.md), [NAS](../run/nas.md) or [native Mac/Linux](../run/uv-pip.md) |
| **GPU** | Adds picture descriptions, document/sensitive-content checks and a family-viewing pre-screen. | Choose **GPU** in [Quick start](./quick-start.md) or the [setup builder](/setup); on Apple Silicon use [native Mac](../run/uv-pip.md#apple-silicon) |
| **Full** | Adds an enabled text reader that can refine the draft and write titles. | Choose **Full** in [Quick start](./quick-start.md) or the [setup builder](/setup); on Apple Silicon use [native Mac](../run/uv-pip.md#apple-silicon) |

For an existing cluster, [Kubernetes](../run/kubernetes.md) covers all three tiers.
[Compare the same source material](../better/tier-example.md) to see what the tiers can change.

## Basic: start with the film {#basic-start-with-the-film}

Basic runs on the app's CPU without a separate model server. Allow two cores, 4 GiB for the app,
and 25 GB of app data plus images and finished films. A plain NAS can do the whole job.

The first cut prepares pictures it needs; later cuts reuse compatible facts. Rendering still
runs each time. Start with a small album to get a film before preparing a large period.

## GPU: understand more of the pictures {#gpu-understand-more-of-the-pictures}

GPU adds inference, a caption service and the Laya family-viewing check. On NVIDIA, the Compose
route starts the inference and caption containers together. On Apple Silicon, the native app
uses Metal and a local caption server. A NAS can use services on a separate NVIDIA machine.

Allow room for the models as well as the app: the GPU Compose app limit is 8 GiB, with separate
limits for its model services. Check [hardware and memory requirements](../run/requirements.md).
Review the cut before sharing; model checks can miss things.

## Full: refine the draft {#full-refine-the-draft}

Full needs the GPU setup and an explicitly enabled reader with a 32k context window. Native
installs can run the app-owned reader; Docker and Kubernetes connect to a reader server.
[Reader setup](../better/reader.md) covers local and hosted choices.

The reader receives annotation text, including people and places. Each proposed edit must pass
the selection checks. If refinement fails, the app keeps the rules draft and reports why.

## What each tier includes {#what-you-give-up-with-basic}

| Feature | Basic | GPU | Full |
|---|---|---|---|
| Dates, favourites, people, trips, titles and bundled music | Yes | Yes | Yes |
| Captions and additional sharing checks | No | Yes | Yes |
| Text-reader refinement | No | No | Yes |
| Maximum resolution | 1080p | 4K when the renderer supports it | 4K when the renderer supports it |
| Generated music | Optional | Optional | Optional |

Hardware video encoding speeds up rendering and does not select the GPU tier.
[Encoding](../run/hardware.md), [remote rendering](../better/gpu-render.md) and
[generated music](../better/music.md) can be configured separately.
A reader on Basic can write titles and music mood; it does not enable Full selection by itself.

## Change services later

Use **Settings** for inference and caption URLs and the reader's URL, model and enabled switch.
A locked field names the [configuration source](../run/config-file.md#where-a-setting-comes-from)
that controls it. Compatible facts and review decisions survive a tier change.

After changing tiers, run `models fetch`, then `preflight` and `capabilities` in the app's
terminal. The resolved tier and its required checks must agree with what you requested.
Then [make a film](./first-film.mdx).
