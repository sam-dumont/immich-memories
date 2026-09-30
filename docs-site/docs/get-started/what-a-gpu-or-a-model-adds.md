---
title: What a GPU or a model adds
description: Choose an optional add-on by what it changes in your films.
---

# What a GPU or a model adds

Make a few films on the default install first. A plain NAS prepares pictures on its CPU, chooses the shots and renders with template titles and bundled music. You do not need to host another service.

| You want | Add | What changes |
|---|---|---|
| Faster picture preparation | [GPU inference](../better/inference.md) | Picture measurements run on a GPU, locally or on another machine |
| Picture descriptions and extra sharing checks | [Captions](../better/captions.md) with the GPU tier | The cut gains descriptions and additional checks |
| A second pass over the edit | [A text reader](../better/reader.md) with GPU preparation and captions | The Full tier reads the draft and can replace weak shots |
| Written titles and a music mood | [A text reader](../better/reader.md) | Works on the NAS tier too; these calls use text |
| Faster encoding | [Hardware encoding](../run/hardware.md) | Makes the finished video faster; this is separate from selecting pictures |
| An original soundtrack | [Generated music](../better/music.md) | Generates a track instead of choosing a bundled one |

The app detects the selection tier with `tier: auto`: NAS, GPU, or Full (GPU plus a reader). GPU and Full also need the configured caption service. Run `immich-memories preflight` after changing the setup.

Adding an encoding GPU alone does not enable Full selection. Adding a text reader alone does not enable sentence films or the model's edit pass.

Compatible prepared facts are reused after an upgrade or an add-on change; newly required facts are computed when needed. [Measured results](../better/measured.md) give the costs. [Privacy](../run/privacy.md) describes what each service receives.
