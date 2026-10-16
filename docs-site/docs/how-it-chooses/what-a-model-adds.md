---
title: What a model changes
---

# What a model changes

A text model can refine the film after the rules editor has made its draft. It reads descriptions and library facts, looks for shots that add little, and tries replacements. Each replacement still has to pass the film’s checks.

It can also write the film's short summary once the cut is settled, with `title_screens.llm_titles: true` (or `--llm-title` for one run). That is experimental and off by default: without it a film has no summary, and its Immich description is the title alone. A [rework](https://github.com/sam-dumont/immich-memories/issues/2594) is planned.

That summary says what happened and who it was with, from the period's account and what the film's shots show people doing, with no list of places and no dates. A holiday, trip or birthday film's summary starts with its occasion.

Your favourites and close family have protections. The model does not decide sharing: picture classifiers, rules and the local Laya classifier do that. The selection reader (a text model) receives text, including names and places, so a hosted reader sends that information outside your network.

It is an optional upgrade, not a guarantee that you will prefer every cut. Compare a draft with the refined film before committing more time or money. If the refinement cannot run, the app can keep the rules draft and report the problem.

[Choose an upgrade](../better/overview.md) explains the requirements. [Add a reader](../better/reader.md) sets one up. The [model refinement reference](../reference/selection-internals/what-a-model-adds.md) covers its routes, request budgets, cached readings and replacement rules.
