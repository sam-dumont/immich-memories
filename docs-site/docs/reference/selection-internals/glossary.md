---
title: Glossary
sidebar_position: 8
---

# Glossary

The words the pages of this section use, and what each one means. Pictures become moments and
episodes, episodes become stories, stories fund chosen shots, and the chosen shots are the film.

## Units of a library

Where it lives: `moment_grouping.py`, `editorial_rule_reader.py`, `editorial_film_reach.py`.

| Word | Meaning |
|---|---|
| **Moment** | pictures within 10 minutes and 2 km of each other; one moment is what one shot shows |
| **Capture run** | captures each within five minutes of the one before; it spaces shots and is the unit of an exposure chain |
| **Episode** | the block a moment sits in (an afternoon at the beach, a party), cut at a 90-minute gap or 2 km |
| **Happening** | a group of moments close in time and place; the unit the worthiness reading judges |
| **Story** | days grouped into one thing that happened: a week at home, a stretch away, a trip |
| **Reach** | the pictures a film can select, plus their Live Photo siblings and capture runs; only these get prepared |

## Preparation

Where it lives: `editorial_preparation_heads.py`, `editorial_preparation_detectors.py`, `editorial_description_contract.py`, `config_tiers.py`.

| Word | Meaning |
|---|---|
| **Producer** | anything that writes a fact about a picture: heads, detectors, caption server, pixel and motion readers |
| **Heads** | eight small classifiers over one pinned DINOv2 encoder: location, people, children, activity, venue, frame_kind, screen, uncovered_person |
| **Detectors** | `nsfw_marqo` (exposure, read on up to eight frames of a video) and `doc_docling` (documents) |
| **Caption** | a banked description or motion line, acquired for selected shots and candidates by SmolVLM2 500M or an explicitly approved LLM provider |
| **Tier** | `basic` (CPU heads; legacy `nas` alias), `gpu` (adds Marqo, Docling, captions and Laya), `full` (adds prose refinement); `auto` resolves from GPU inference and LLM configuration |
| **Scene print** | the pooled DINOv2 vector of a preview; two prints at a cosine of 0.65 or more are the same scene |
| **Residual** | the motion left in a clip once the camera's own movement is removed; 1.5 or more plays as motion |
| **Bank** | an answer stored under its exact inputs and producer version, so the next run asks nothing; no row means nobody asked |
| **Banked picture evidence** | matching facts and captions are reused; missing evidence is acquired for selected shots and actual candidates; the prose reader receives text only |

## Building the cut

Where it lives: `editorial_story_carriers.py`, `editorial_story_depth_fill.py`, `editorial_standing_facts.py`, `editorial_story_lookalike.py`.

| Word | Meaning |
|---|---|
| **Reader** | who plans the film: `rules` (no model) on the `basic` and `gpu` tiers, `model` on `full`. The tier sets it; an explicit value is ignored with a warning |
| **Draft** | the film the no-model reader cuts from facts; with no model, it is the film |
| **Worthiness** | remarkable, maybe or background, read per happening from facts |
| **Weight** | a story's size: `dominant`, `major`, `minor`, `glimpse`, `none`; `none` gets no shot |
| **Big story** | dense (twice the median day) and at least 30 % close-family pictures; weighs `major` |
| **Carrier** | the picture admitted to carry one moment of a funded story; a shot before it is rendered |
| **Carrier rule** | a picture kept as evidence and never a shot: a document, a screen, a screenshot, a face close-up |
| **Standing** | whether a picture stands on its own, scored 0 to 2 from its facts, never asked of a model |
| **Look-alike** | a story's next shot must not repeat one it holds (hash within 10 bits) |
| **Depth** | a story still short spends the film's free content seconds inside moments it already shows, one distinct shot at a time, round-robin across every funded story, until the budget or the distinct shots run out |
| **Family seat** | one shot for a close family member the cut left out |
| **Close family** | partner or spouse, child, parent, as confirmed in the people registry; in a person film, that person's too |
| **Owner-required** | a picture requested with `--include` for a new cut; kept through trim and duplicate review but still judged by the sharing gate |

## The gate and the checks

Where it lives: `editorial_shareability.py`, `editorial_exposure_chains.py`, `editorial_cut_invariants.py`.

| Word | Meaning |
|---|---|
| **Verdict** | `share`, `family_only`, `just_us` or `do_not_show`; the strictest wins |
| **Sharing level** | who a film is for: just us (plays up to `just_us`), family (up to `family_only`, the default), shareable (`share` only) |
| **Detector hold** | an exposure flag on a still, a video frame or a Live clip; `family_only`, never lifted by a reading, only by you |
| **Your decision** | per picture: hold cleared for a level, or never use; kept in the annotation store, read by every tier |
| **Exposure chain** | a capture run at least half flagged, with three or more flagged captures, held whole |
| **Laya** | a tier-enabled local model answering the audience check's activity question from the caption |
| **Review list** | shots with an exposure probability between 0.2 and 0.5, kept with the run for you to check; changes nothing |
| **Filler** | a shot with no indicator that the `frame_kind` head reads as showing nothing; leaves every rules-drafted film, polished or not |
| **Finished-cut check** | the cut read once against every promise; warns, changes nothing |

## The model tier

Where it lives: `text_episode_reader.py`, `editorial_thin_layer.py`, `editorial_block_votes.py`, `library_catalogue.py`.

| Word | Meaning |
|---|---|
| **Episode reading** | a model's answer about one episode: what happened, a representative, moments worth a record |
| **Record** | a picture an episode reading named as the record of something that happens once (an arrival, a milestone with its occasion visible, a change you can see, text naming the occasion), judged on the episode's own lines; protected from the vote |
| **Account** | what the library says a period was about, written once from episode readings and reused |
| **Thesis** | the account's statement of what the period was, up to 150 words |
| **Polish / thin layer** | the model reads the draft once, names the shots that add nothing, fills the seats |
| **Block vote** | every model yes or no: at most 12 rows, asked in up to two orders; both orders is firm, one is a maybe |
| **Seat** | a slot the polish may fill: N (a record with no shot), R (replaces a voted-out shot), T (replaces a gate refusal), D (a swap) |
| **Fill on demand** | a film reads only the episodes its shots sit in; reading a whole scope ahead is optional |
| **Route** | A: rules only (`basic`, `gpu`); B: the rules draft plus the model's polish (`full`, the default); C: the model plans the whole film (`full` with `thin_model_layer: false`); see [What a model adds](./what-a-model-adds.md) |
