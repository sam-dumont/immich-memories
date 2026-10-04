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

- **A pet household's year turns into its days out.** Basic gives a slot to days with an occasion (a trip, a favourite, a video, close family). A cat asleep on the sofa is none of those, so a year with cats on dozens of ordinary days kept 3 of 14 clear cat pictures and 37 shots of a single town walk.
- **A sparse year mostly vanishes.** For someone who takes a few snapshots a month, those quiet weeks ARE the year. One test year with 55 pictures across 36 days came out at 8 shots for a 300 second target, with February to August empty. Funding each quiet week with its best clean picture is planned ([#2048](https://github.com/sam-dumont/immich-memories/issues/2048)).
- **A face Immich rarely sees makes a thin person film.** A rider in a helmet was recognised on 31 of 1,411 pictures in a year, so her film had 4 shots from one day. The editor only knows who is in a picture through Immich's face recognition.
- **A couple film needs both faces in one picture.** One of you usually holds the camera, so a year may hold only 15 to 24 pictures of the two of you together.

Full does not fix the subject problem on its own: it refines the shortlist Basic draws, so the cat year still kept 3 of 14. Basic has no way to ask for the pet or the hobby either.

## Asking in your own words is the way in, on Full

[Free text](../make/free-text.md) is what gets these households their film, once the pictures are prepared:

| Request | Library not prepared | Library prepared |
| --- | --- | --- |
| "our cats over the years" | no film | 74 shots, all the cats, nine years in order |
| "our dog along the years" | no film | 76 shots of the dogs |
| "our horses" | no film | 70 shots across four years |
| "my knitting projects" | no film | 72 shots, all knitting |

Preparing a whole library of 1,200 to 3,100 pictures took 8 to 26 minutes on an Apple M5 Max.

Two things still get in the way:

- **An unprepared library answers "not possible".** Today a request only searches pictures that are already captioned. A request will soon prepare the period it needs on its own, after telling you how long that takes ([#2045](https://github.com/sam-dumont/immich-memories/issues/2045)). Until then, run `immich-memories prepare` for the period first.
- **A year in the sentence can be misread.** "the horses in 2024" makes no film because the year gets read as text printed on something in the photos ([#2046](https://github.com/sam-dumont/immich-memories/issues/2046)). "our horses" works.

## Other things to know

- **A blurry or nearly black picture can slip in** when it is the only picture of its moment, mostly in narrow selections like free text ([#2049](https://github.com/sam-dumont/immich-memories/issues/2049)).
- **The run can occasionally exit with an error after the cut is saved.** The film and the saved cut are fine; a script reading the exit code sees a failure ([#2025](https://github.com/sam-dumont/immich-memories/issues/2025)).

Figures on this page come from the test households, never from a real family library. For timings on your own hardware, see [Measure your setup](../better/measured.md).
