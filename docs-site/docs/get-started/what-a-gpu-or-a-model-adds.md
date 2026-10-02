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

The app detects the selection tier with `tier: auto`: NAS, GPU, or Full (GPU plus a reader). GPU capability can come from a remote inference service, a working local CUDA ONNX runtime, or a Mac's Metal GPU. GPU and Full also need the configured caption service and Laya. Run `immich-memories preflight` after changing the setup. On native Linux or macOS, the reader can run inside the app. Docker and Kubernetes use an external API server.

Adding an encoding GPU alone does not enable Full selection. Adding a text reader alone does not enable sentence films or the model's edit pass.

Compatible prepared facts are reused when you add a service; newly required facts are computed when needed. [Measure your setup](../better/measured.md) to find which stage costs time and memory. [Privacy](../run/privacy.md) describes what each service receives.
