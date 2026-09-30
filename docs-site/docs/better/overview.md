---
title: Choose an upgrade
---

# Choose an upgrade

Make a few films before adding services. A plain NAS already selects, renders and adds bundled music. Add a service when it solves a problem you have.

| You want | Start here | What it sends |
|---|---|---|
| Faster picture analysis on a slow NAS | [GPU inference](./inference.md) | Picture previews to your service |
| Faster video rendering | [GPU render worker](./gpu-render.md) | Your cut and Immich API key; the worker downloads originals |
| Titles or music mood from a text model | [Text reader](./reader.md) | Annotation text, including people and place names |
| Descriptions and activity checks | [Picture captions](./captions.md) | Small picture tiles to your caption service |
| Model refinement of the selection draft | [Text reader](./reader.md), with GPU inference, captions and Laya ready | Text to the reader; images to the captioner |
| An original soundtrack | [Generated music](./music.md) | A mood prompt to your music backend |

Use services you trust. A hosted text reader receives names and places even though it receives no photos. [Privacy](../run/privacy.md) lists the destinations and switches.

## The model's role

On Full, the rules editor still makes the draft. The model can propose changes, which must pass the selection checks. Favourites and sharing decisions retain their protections. If the model cannot answer, the app keeps the rules draft and reports why.

A larger model does not guarantee a film you prefer. Compare the result on the same material. [What a model adds](../how-it-chooses/what-a-model-adds.md) explains the general behaviour; [measurements](./measured.md) keep time, hardware and costs separate from selection quality.
