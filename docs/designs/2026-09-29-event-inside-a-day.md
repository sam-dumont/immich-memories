# A dense one-off inside an ordinary day is its own story (no-model draft)

Status: approved 2026-09-29. Slice 2 of 2. Slice 1 (a recurring kind in one month takes one
story's depth) is `2026-09-29-same-kind-threads.md`.

## The problem

At home the no-model reader groups a week's photographed days into one story (`_runs`, cut on the
ISO week). The episode cut itself works: an evening across town after a 90-minute gap is its own
episode. The dilution happens one level up. The week becomes one story, and with no favourite a
story is `minor`: one shot, maybe two if the budget lasts, which in a long film it doesn't.

So a one-off event on an ordinary weekday (a race, a concert, a prize evening, a graduation)
shares a single shot with the morning's errands and the next day's clip. The shot the story gets
can be any of its moments. Nothing about the evening can lift it: it has no stars, and the
big-story floor needs close family on most pictures, which an event with the owner behind the
camera doesn't have.

## The rule

Inside a home story below `major` (fewer than three favourites, not big, not a trip), an episode
is an **event** when every fact agrees:

1. **Dense**: its own pictures reach the day threshold the gate already uses for a whole day,
   `max(4 x median photographed day, 75th percentile)`.
2. **More than one burst**: at least `EVENT_MIN_BURSTS` (2) moments. A cake, a pet or a sunset
   shot 50 times in one go is one moment.
3. **Different activity**: its activity label differs from every other episode of its day, or,
   alone on its day, from the episodes either side of it in the story. A label alone never
   qualifies: rules 1 and 2 must hold too.
4. **Different place**, when both sides have GPS: at least `EVENT_MIN_KM` (1 km) away. Without
   GPS, rules 1 to 3 decide.

The event leaves its story and becomes its own, funded first among stories of its weight (as a
trip is) and reserving `EVENT_PICTURES` (2) shots at its turn, the most the `minor` word allows.
Its weight comes from its own facts through the existing floors: three favourites inside it make
it `major`. The rest of the story keeps its own reading.

## Corroboration by printed text

A screen or document can add one shot, never make an event. When a picture no camera made (a
screenshot, a scan: a still with no EXIF make) taken in the `CORROBORATION_HOURS` (18) after the
event reads one of `RESULT_WORDS` through Immich's own OCR, the event reserves 3.

- The read uses the repo's existing OCR path, `ImmichPrintedText` (Immich's metadata search with
  its `ocr` filter), with a time window. It runs only for events the draft already found: at
  most one search per word per event.
- The words name an outcome and no activity: result, finish, time, rank, position, podium,
  winner, record, score, certificate, award, prize, PR, PB.
- A camera photo of a sign reads words too, so it doesn't count.

## Examples (synthetic, all in `tests/test_editorial_event_story.py`)

Written before the rule ran. An ordinary week at home, the case replacing one day:

| day | event? | why |
|---|---|---|
| morning at home + evening across town, 40 pictures in 2 bursts, new label | yes | all four facts |
| a cake shot 40 times in one burst at home | no | one burst, same place |
| a pet shot 30 times in 3 bursts at home | no | same place |
| the dog at the park 300 m away, under another town name | no | under 1 km |
| a sunset shot 45 times in one burst across town | no | one burst |
| an ordinary meal out, 8 pictures | no | not dense |
| a dense evening with the same label as the morning | no | same activity |
| one picture labelled as sport (a misread wall socket) | no | label alone |
| a cake burst with no GPS | no | one burst |
| a graduation afternoon 8 km away, 60 pictures in 4 bursts | yes | all four facts |
| a concert day with no GPS, 3 bursts, new label | yes | 1 to 3, no place test possible |
| a dinner out photographed like an occasion | yes | a known limit |
| a dense evening on a trip | no | trips stay whole |
| a story with three favourites | no | already major |
| a day dense with close family | no | big story, stays whole and major |
| an exam morning, 3 pictures, a certificate on screen next day | no | a screen never makes one |

The CC0 demo month holds no event.

## Limits

- A dinner out, or any ordinary outing photographed at four times a normal day's volume, in
  several bursts, somewhere else, under a new label, is an event. Counts, places and labels alone
  can't tell it from one.
- The corroboration words are English. A screen in another language is missed unless Immich's
  OCR search matches the word, which leaves the event at 2 shots, never 0.
- The rest of a split story keeps its reading, including a "dense day" reading the event earned
  for it. It can still take its own shot.
