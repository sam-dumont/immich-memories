---
title: Picking each shot
sidebar_position: 3
---

# Picking each shot

`generate --include` steers a new cut and has the selection protections described here. A web pool tick saves an owner revision without scoring or choosing pictures again.

Once a story has its shots, each one has to be a moment and a frame. You shot 30 frames of the
agility run in four minutes: that is one moment, and it gets one frame. The one you starred wins.
Without a star, the one that moves wins (a video, or a Live Photo whose clip moves), then the frame
with more of the people Immich knows, then the frame where the runner you named fills the picture
over the one where they're a speck at the edge, then the sharp one over the blurry one. Only then
does the clock decide.

Every rule here runs on a plain NAS. With a model, the draft is picked exactly this way and the
model then polishes it ([What a model adds](./what-a-model-adds.md)).

## The chain

Five steps, in order: offer moments, rank their frames, check eligibility and standing, check
spacing and repetition, admit and deepen. The gates below run in that order; where a favourite
wins outright and where it still has to clear a gate is marked as it comes up.

<Diagram name="decide-keep-drop" headline="A favourite skips two of the six checks. The other four drop it anyway." />
## Which frame carries a moment

`rule_representative_rank` (`editorial_rule_quality.py`) sorts a moment's frames by these keys, in
order. Each key only breaks the ties of the one before it.

1. **Your favourite.**
2. **A frame an earlier model reading named** for its episode. Empty on a library no model has
   read; on one that has, the no-model draft reads it for free.
3. **It moves**: a video, or a Live Photo whose clip measured at least 1.5 (see below).
4. **More people Immich knows** in it, or more faces.
5. **The frame shows the person**: a subject rung from 1 to 3, one point for having a face's width
   of air to every border and one for being the largest face in the picture
   (`subject_framing.py`). In a person film only that person's face counts, and a bigger face of
   someone else costs the rung.
6. **More of the frame** is that person.
7. **No pixel warning**: `SOFT (blurry)`, `DARK` or `BLOWN OUT` lose.
8. **The `people` head saw somebody.**
9. **The middle of the burst** over its first and last frames.
10. **The clock.**

On a story with more moments than `max(6, 3 × its shots)`, the moments offered to it are also sorted
first: starred ones, then moving ones, then lively ones, and it reaches for a few more moving
moments if the list filled up with stills. Below that size every moment is offered.

**Unrecognised people come later.** A moment with no named, visible person in Immich (unnamed faces, hidden people, or people only the `people` head saw) is not "lively" for that sort, and when
the draft picks a story's moments without a model it takes them after every other moment of the
story: stars, then the rest spread over the story's span, then moments with unrecognised people. So a frame of the crowd
at a race loses its one slot to a frame of the same day with someone you named in it. A moment with
no people at all (a view, a place) is not demoted, and a library that names nobody keeps its order.

## What a frame must pass

Draft picks and replacements use the same admission rules. A replacement gets its own story
weight and purpose, then passes standing, audience, spacing and repetition checks against the
shots it would join. Newly acquired caption or motion facts are read before that decision.
This also applies when replacing a duplicate or giving a missing family member a seat.
The existing depth pass can add a distinct view inside an already shown moment; that exception
does not transfer to a replacement. Candidate decisions are kept with the run; `runs why` reads
them back for one picture.

**Free.** Not already a shot, and not a picture the carrier rules keep as evidence only
(`excluded_carrier_sources`): a document the detector names, a screen the `screen` head flags, a
still at an exact phone-screen size, and, where there is a caption, a caption about a screen, a face
close-up, medical care or a grid of identical items.
The check covers every burst member and motion clip, before standing is scored. New evidence
from preparing a replacement runs through the same check; a refusal leaves its slot open for
another eligible candidate. A refused companion does not mark its clean lead as permanently bad.

**Spaced.** Two shots of the same moment must be at least five minutes apart in capture time.

**Standing.** Does it stand on its own? Objects and empty rooms out, people and animals in. No
model is asked, on any tier: `RuleStructureReader.standing` scores every picture 0, 1 or 2 from its
facts, and `StandingGate` refuses a score under 1.

- A favourite or a picture passed with `generate --include` scores 2. Sharing checks still apply; a score does not clear a hold. Other pictures with an uncleared exposure flag score 0 in a Shareable film.
- 0 for a body part with no face: legs, feet, shoes or hands alone. The frame head calls it a
  body-part close-up, or the caption names a body part or footwear and no animal, and Immich found
  no face on it. A face makes it a person, and a paw is never a body part. This is a fixed rule on
  top of the points table, not fitted to it: the public set's teacher keeps many of these shots, so
  it costs agreement there, and it remains part of the app’s default selection policy.
- 0 when its video frames mostly miss the subject (`frames=subject_often_missing`: fewer than 6 of
  8 sampled frames show a moment), or when the points table below says it carries nothing.
- An album picture scores 2 after the zero rules, with or without a written subject. Otherwise the heads decide: people, an activity, or an outdoor or public place scores 2; nobody,
  no activity and a private interior scores 0; an indoor scene with nobody in it scores 1.

The points table (`editorial_standing_facts.py`) comes in two versions, and the caption version in
two fits: one for a library where Immich reads faces, one for a library where it recognised nobody
at all (face recognition off, or only pets and places). Weights were fitted on a public CC BY corpus
against a hosted reader's answers and rounded to half points; nothing in it came from anyone's
library.

| | Heads only (Basic default) | Heads and caption, faces read | Heads and caption, no faces |
|---|---|---|---|
| Refuses at | 3.0 points | 4.5 points | 4.5 points |
| `frame_kind` | empty room 4, accidental frame 4, lone object 3.5, body part 2.5, record 2.5, screen or document 2 | the four "nothing" kinds 2, record or screen 1, scenery -1 | the four "nothing" kinds 2.5, record or screen 1.5, scenery -0.5 |
| People head | two -0.5, small group -1, crowd -1.5 | two -0.5, small group -1, crowd -1.5 | two -0.5, small group or crowd -1 |
| Flags | children -1, document +1, screen +1, `BLOWN OUT` +1.5, `DARK` +1.5, `SOFT` +0.5 | children -0.5, document +1, screen +1, `BLOWN OUT` +1.5, `DARK` +2, `SOFT` +1 | children -0.5, document +1, screen +1, `BLOWN OUT` +2, `DARK` +2, `SOFT` +1 |
| Face | | people head saw somebody, Immich found no face +1 | |
| Caption | | nobody alive +1.5; objects +1, screens and devices +1; feet or hands, food, room or furniture, plants, text or signs +0.5 each; goods on display (a shelf, products, a showroom) make the frame a lone object | nobody alive +2; the same words; goods on display +1 |

A `SOFT (blurry)` or `DARK` picture never carries a moment alone: with no cleaner sibling to take
the frame, the moment goes unfunded. A starred one still ships.

The public `people` head almost never says "none" (0.66 % of the pictures in one real library, against about a third
on a hand-checked sample), so its word is checked first: a picture counts as having people only when
Immich found a face on it or its caption names a person. Anything else is read as `none`.

Two short cuts sit above the table. A frame the head calls a people moment is never refused when it
is sharp, not dark, and Immich found a face on it. A picture whose caption names a person is never
refused when Immich found a face on it, and one that names an animal never is (a stuffed dog or a
statue of one still counts as an object). With heads alone, `activity: animal-nature` also passes this refusal check. The frame head calls a pair of legs in a mirror a people
moment too; with no face in it, it is counted like anything else. A picture of your cat asleep on the
sofa stands; the sofa alone does not. In a library where Immich recognised nobody, an empty face list
says nothing, and the heads and the caption are taken at their word.

The same face rule decides whether a picture "shows life" for the gate: a picture with life in a
major or dominant story with more than two pictures is only ordered, never refused, and a person counts only when Immich supplies a recognised face.
A picture with nobody in it serves its story only when it is starred, or when the story is major,
dominant or minor and holds more than two pictures. Anywhere else it is refused as context
(kept with the run as `context_rejected`). A custom film about
something you wrote (a renovation, the works on a house) drops that rule: its pictures were chosen
for the subject, so a stripped wall or a room under construction can carry its story, as long as it
stands. A custom film of its window alone keeps the rule.

A written subject requires a configured text reader; these subject rules are not available to the rules reader alone. An album handed over with a written subject (`generate --from-album "Bread" --subject "bread making
along the years"`) goes one step further. The album is a pool picked for that subject, so its
pictures stand on the subject even with a standing score of 0: a loaf on a counter scores 0
like any lone object, and stays. A video whose frames mostly miss its subject is still refused, and
every other gate still runs: sharing and the family-viewing holds, source eligibility, provenance,
look-alikes, duplicates and length. The allocation gives every year the album holds a shot, even a
year whose stories the reader weighed `none`. Each shot that got in this way is kept with the run
as `stood_on_subject`, with its score and why. A
custom date range with a written subject is not a pool and keeps the rules above.

Once a moment's frames are through the gate, the ones that stand are sorted again: favourite first,
then the higher standing score, then the order above. A still that scores 2 can beat a video that
scores 1.

**New.** The story's next shot must not look like one it already holds: a preview hash within 10
bits, compared inside the same story or the same calendar day, against the shots of its own moment
and the kept shot just before and after it. A video or a moving Live Photo is never a repeat of a
still, and a favourite is never refused for looking like a picture you did not star. A refused frame
comes back when nothing else can fill its slot. No model compares pictures, on any tier.

## Videos and Live Photos

A video always plays, from 2 seconds long (shorter clips are stubs and never become shots) up to a
6-second hold. When someone is mid-sentence at the cut, the end stretches to the end of what they
say, never more than 12 seconds from the start.

The six seconds don't have to be the first six. Once a film's videos are picked, each one is read
once for where to cut, and the answer is banked for every later film. The picture decides first:
every predicted frame in the clip's encoding stores only what changed since the one before it, so
frame sizes jump when something moves across an otherwise still shot. That size is in the clip's
own frame index, so nothing needs decoding to read it; from a static camera the jump marks the
action (riders crossing a finish line, not the empty road before them). The sound decides next for
a handheld clip, which changes everywhere: the loudest moment (the cheer when the candles go out, a
squeal) with a second and a half of build-up before it, or, with no standout moment, the stretch
with the most talking. Only the sound is fetched, a minute of it at most, so a five-minute clip
costs what a one-minute one does. A clip with nothing that stands out keeps its opening.

A Live Photo plays as motion on every tier, Basic included, when its clip moves and shows its
subject. The motion is measured during the cut, for the Live Photos the cut kept, and banked
per picture so the next cut reads it instead (`store/cut_measurements`).

A selected Live Photo's clip is read or measured for motion, then checked for subject
visibility; it plays as motion only when both pass, otherwise it keeps the still.

The residual is the optical flow left after the camera's own movement is taken out, over 12 frames
at 320x240. A clip only ever costs a Live Photo its motion, never its place: a starred Live Photo
whose clip is mostly pocket lining plays as its still. The burst and stitching rules are on
[Photos, Live Photos and HDR](../../make/photos-and-live-photos.md#live-photos).

A true video whose sampled frames mostly miss its subject scores 0 on standing and is refused,
unless you starred it: a starred video of a wall means something happened there.

## With a model planning the whole film

On the model's own route (`thin_model_layer: false`), the model picks
the moments of each story from a shortlist of their captions, and reads each video's motion line: the
sentence the caption server wrote at ingest from three keyframes. A Live Photo's sentence reaches it
only once its residual measured at least 1.5, and a video whose frames measured under 1.5 has its
sentence withheld unless you starred it. Standing, spacing and the look-alike check are the same
facts as above. Missing motion sentences use plain clip facts; the cut does not contact the
motion-description server. Explicit `prepare` reports missing sentences. Normal film refinement
reuses its rules draft without consuming them, so that pass does not report them as missing.

## Favourite guarantees


A favourite is the strongest signal you can give, and it costs nothing. What a star guarantees:

- it wins its moment over every other frame, and always stands on its own;
- its story counts as present, so it gets at least a `minor` weight; three favourites make it `major`;
- the duplicate review keeps it over a look-alike you didn't star. Two near-identical favourites
  taken within 2 days of each other are one moment: the best of them stays (a video, then more
  faces, then the sharper, then the earlier) and the other's slot is refilled;
- the model's vote never removes it, and a polish refill picks it first inside its moment;
- a shot nothing vouches for never takes its place: not when the place bound refuses it, not in the
  trim.

What it doesn't guarantee: a place in the film. The gate, the five-minute spacing and the length
still apply.
