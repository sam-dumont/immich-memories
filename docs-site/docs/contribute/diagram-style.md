---
title: Diagram style
description: How the docs draw diagrams, the icons they use and where the shared diagrams live.
---

import ArchitectureDetailed from '@site/docs/_diagrams/architecture-detailed.mdx';
import ArchitectureDetailedTwo from '@site/docs/_diagrams/architecture-detailed-2.mdx';
import ArchitectureOverview from '@site/docs/_diagrams/architecture-overview.mdx';
import DecideInstall from '@site/docs/_diagrams/decide-install.mdx';
import DecideKeepDrop from '@site/docs/_diagrams/decide-keep-drop.mdx';
import DecideLength from '@site/docs/_diagrams/decide-length.mdx';
import DecideTier from '@site/docs/_diagrams/decide-tier.mdx';
import DeployCompose from '@site/docs/_diagrams/deploy-compose.mdx';
import DeployKubernetes from '@site/docs/_diagrams/deploy-kubernetes.mdx';
import DeployMac from '@site/docs/_diagrams/deploy-mac.mdx';
import DeployNas from '@site/docs/_diagrams/deploy-nas.mdx';
import DeployTerraform from '@site/docs/_diagrams/deploy-terraform.mdx';
import PrivacyMap from '@site/docs/_diagrams/privacy-map.mdx';
import SeqAsk from '@site/docs/_diagrams/seq-ask.mdx';
import SeqGenerateReference from '@site/docs/_diagrams/seq-generate-reference.mdx';
import SeqGenerate from '@site/docs/_diagrams/seq-generate.mdx';
import SeqScheduledRun from '@site/docs/_diagrams/seq-scheduled-run.mdx';
import SeqWebJob from '@site/docs/_diagrams/seq-web-job.mdx';
import StateRun from '@site/docs/_diagrams/state-run.mdx';
import StateScheduledAttempt from '@site/docs/_diagrams/state-scheduled-attempt.mdx';

# Diagram style

Every diagram in these docs is Mermaid text in the repo, drawn by the docs build. No exported
images: a diagram is a few lines of text, so it changes in the same pull request as the code it
describes. Draw from the code, never from another page.

## Where diagrams live

A diagram that more than one page shows lives in `docs-site/docs/_diagrams/`, one `.mdx` file
each. The underscore keeps Docusaurus from making them pages. A page shows one with:

```mdx
import ArchitectureOverview from '@site/docs/_diagrams/architecture-overview.mdx';

<ArchitectureOverview />
```

Each file opens with a one-line comment: what it shows, which pages use it, and which code it
was drawn from. A one-off diagram can sit in its page as a plain `mermaid` block.

## Which diagram

| Question | Mermaid type |
|---|---|
| What are the parts and what talks to what? | `flowchart` with icon nodes |
| What runs where for my install? | `flowchart` with icon nodes, one per install path |
| What happens, in order? | `sequenceDiagram` with `autonumber` and `box` |
| Which option should I pick? Why was this picture dropped? | `flowchart TD`, questions in diamonds |
| What states can a run be in? | `stateDiagram-v2` with the real state names |

Architecture and deployment flowcharts start with `%%{init: {"layout": "elk"}}%%`. ELK keeps
the boxes from overlapping and draws square edges; the default layout piles groups on top of
each other once edges cross them. Leave ELK off a diagram where every edge leaves one node (the
privacy map): it bundles those edges into a knot.

Mermaid's `architecture-beta` renders the same icons, but its layout bends edges between groups
and moves boxes on every change. Use icon nodes in a flowchart instead.

## Groups

- **Your app host**: the container, NAS app, pod or Mac running immich-memories, with FFmpeg and
  the store.
- **Your network**: Immich and the services you run yourself (GPU box, reader, ACE-Step).
- **Outside your network**: anything on the internet. These are all opt-in, so the group gets the
  dashed `optional` class, and so does a group of optional services.

```text
classDef optional stroke-dasharray: 6 4
class outside optional
```

## Edges

- Solid arrow: always happens. Thick (`==>`): the main path, usually the Immich API key.
- Dashed arrow (`-.->`): only when a setting turns it on. Label it with that setting
  (`network.geocoding`, `render.worker_base_url`), not with a description of it.
- Labels are short verbs or settings: "starts a run", "reads, uploads if on". No sentences.
- In sequences, a step the app does on its own is a `Note over`, not an arrow to itself. Wrap
  branches in `alt` and `opt` where the code branches, with the condition as the label.

## Icons

Icon nodes look like `cli@{ icon: "mdi:console", form: "square", label: "Film runs", pos: "b", h: 48 }`.
Three icon sets are installed: `logos` (Docker, Kubernetes, PostgreSQL, FFmpeg, Python, Svelte),
`simple-icons` (Immich, NVIDIA, Synology, Unraid, TrueNAS, OpenStreetMap) and `mdi` (generic
parts: `mdi:database`, `mdi:harddisk`, `mdi:timer-outline`, `mdi:chip`). Use a product's own
icon where one exists; Immich is `simple-icons:immich`. Browse the sets at icon-sets.iconify.design.

The site ships only the icons the docs use, bundled with the site: a reader's browser never
fetches an icon from a CDN. After adding a new icon, run `npm run diagram-icons` in
`docs-site/` and commit `src/theme/Mermaid/diagram-icons.json`. The build fails when that file is
stale, and names the icon when it doesn't exist.

## Size

About 12 boxes per diagram. Past that, split it (`architecture-detailed` and
`architecture-detailed-2`). Keep box labels to a few words: ports and settings belong in edge
labels or the text around the diagram. Wide diagrams shrink to the column down to 60%, then
scroll; every diagram has zoom buttons and an expanded view.

## Check it

`make docs-build` builds the site, but Mermaid only draws in the browser, so a broken block still
builds. Open the page with `npm start` in `docs-site/` and look at it, in light and dark mode.

## The shared diagrams

### architecture-detailed

<ArchitectureDetailed />

### architecture-detailed-2

<ArchitectureDetailedTwo />

### architecture-overview

<ArchitectureOverview />

### decide-install

<DecideInstall />

### decide-keep-drop

<DecideKeepDrop />

### decide-length

<DecideLength />

### decide-tier

<DecideTier />

### deploy-compose

<DeployCompose />

### deploy-kubernetes

<DeployKubernetes />

### deploy-mac

<DeployMac />

### deploy-nas

<DeployNas />

### deploy-terraform

<DeployTerraform />

### privacy-map

<PrivacyMap />

### seq-ask

<SeqAsk />

### seq-generate-reference

<SeqGenerateReference />

### seq-generate

<SeqGenerate />

### seq-scheduled-run

<SeqScheduledRun />

### seq-web-job

<SeqWebJob />

### state-run

<StateRun />

### state-scheduled-attempt

<StateScheduledAttempt />
