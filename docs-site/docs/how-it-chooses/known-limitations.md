---
title: Known limitations for now
---

# Known limitations for now

The editor was tested on eight synthetic households built from openly licensed pictures: families with kids, a retired couple who travels, a couple with a dog, a couple with cats, a horse rider, a knitter and a light user who takes a few pictures a month. This page says where the films hold up and where they don't yet. Each gap links to the issue that tracks it.

## Family libraries: Basic and Full both work

Months, trips, years and person films come out with the right people, in the order things happened, and almost always without screenshots or receipts (a photographed page got into 3 of 48 test films, all of them years or seasons). Basic got there on its own.

A story used to be granted more slots than it had distinct moments, with the final duplicate check removing the repeats and leaving those slots empty. The planner now caps a story's grant at the moments it can show distinctly and spends the rest on stories with unfunded moments elsewhere, so a film only comes out short when the library genuinely has no more distinct material to give it.

Full still does better on the same films: captions tell moments apart before the slots are handed out, so fewer picks get thrown away as copies in the first place.

## Pets, hobbies and light users: Basic gives something, but not their subject

Months and trips work for every household: the knitter's months, the cat household's spring, the light user's trip all came out full length and sensible.

What doesn't work yet is anything about what the household actually cares about:

- **A pet household's year used to turn into its days out; a mostly quiet household no longer loses its ordinary weeks.** Basic gives a slot to days with an occasion (a trip, a favourite, a video, close family); a cat asleep on the sofa is none of those. When at least two thirds of a household's at-home weeks carry no occasion indicator at all, Basic now funds each of them with its own sharpest, best-exposed clean picture instead of letting a single town walk take every leftover slot ([#2048](https://github.com/sam-dumont/immich-memories/issues/2048)). It still can't tell Basic that the subject is the cat: a week that holds both a cat and a dozen pictures of somewhere else just picks whichever reads as the better picture.
- **A sparse year used to mostly vanish; a mostly indicator-less period no longer does.** For someone who takes a few snapshots a month, those quiet weeks ARE the year. One test year with 55 pictures across 36 days came out at 8 shots for a 300 second target, with February to August empty. The same funding-by-best-picture rule covers this case ([#2048](https://github.com/sam-dumont/immich-memories/issues/2048)).
- **A face Immich rarely sees makes a thin person film.** A rider in a helmet was recognised on 31 of 1,411 pictures in a year, so her film had 4 shots from one day. The editor only knows who is in a picture through Immich's face recognition.
- **A couple film needs both faces in one picture.** One of you usually holds the camera, so a year may hold only 15 to 24 pictures of the two of you together.

Full does not fix the subject problem on its own: it refines the shortlist Basic draws, so a household still gets no film about the pet or the hobby specifically. Basic has no way to ask for the pet or the hobby either.

## Asking in your own words is the way in, on Full

[Free text](../make/free-text.md) is what gets these households their film. A request prepares
whatever its own period needs on its own, with a warning first if that takes a while:

| Request | Not prepared yet | Once prepared |
| --- | --- | --- |
| "our cats over the years" | 1,234 pictures, about 8 min to prepare | 74 shots, all the cats, nine years in order |
| "our dog along the years" | needs preparing first | 76 shots of the dogs |
| "our horses" | needs preparing first | 70 shots across four years |
| "my knitting projects" | needs preparing first | 72 shots, all knitting |

Measured on the cat household (M5 Max): preparing those 1,234 pictures took 500 s (about 8
min), in line with preparing a whole library of 1,200 to 3,100 pictures taking 8 to 26 minutes.
A second request over the same period pays nothing: the captions are already banked.

## Other things to know

- **Fixed:** a blurry or nearly black picture no longer ships as the only picture of its moment; a starred one still does, favourites rule unchanged ([#2049](https://github.com/sam-dumont/immich-memories/issues/2049)). A year in the sentence ("the horses in 2024") is no longer read as printed text ([#2046](https://github.com/sam-dumont/immich-memories/issues/2046)).

## Open after release

None of these stop a film. You may still notice them:

- **A repeat frame can be refused too early.** The up-front repeat checks don't yet spare a favourite, a close family member's only shot or the film's floor, while the final duplicate review does ([#2071](https://github.com/sam-dumont/immich-memories/issues/2071)).
- **Some exclusions slip in free text.** Russian and Polish case forms ("без публики") do nothing, "only the performers" drops stage shots with the crowd in frame, and "everyone except grandpa" can collide ([#2072](https://github.com/sam-dumont/immich-memories/issues/2072)).
- **Latvian, Lithuanian and Finnish places keep their admin word.** You get "Helsingin kaupunki" instead of Helsinki; Estonian labels are already clean ([#2074](https://github.com/sam-dumont/immich-memories/issues/2074)).
- **Docker automation rough edges.** A failure notification carries the start of the output rather than the error, and `/health/ready` forgets the timer's last fire after a restart ([#2077](https://github.com/sam-dumont/immich-memories/issues/2077)).
- **The people signal is a stopgap.** A library with face detection off reads "nobody" on every picture with no face box and no caption naming someone, and a face Immich recognises after `prepare` ran doesn't count yet ([#2079](https://github.com/sam-dumont/immich-memories/issues/2079)).

Figures on this page come from the test households, never from a real family library. For timings on your own hardware, see [Measure your setup](../better/measured.md).
