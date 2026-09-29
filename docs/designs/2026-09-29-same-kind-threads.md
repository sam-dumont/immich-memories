# A recurring kind is one story's worth (no-model draft)

Status: approved 2026-09-29. Slice 1 of 2: slice 2 (a dense one-off inside an ordinary day
becomes its own event) follows in its own PR.

## The problem

In the no-model draft a story's weight word comes from facts: three favourites make it `major`,
anything remarkable without them is `minor`. Slots then go out in order (`allocate_slots`): one
per `major`, one `minor` per day, then the `major` stories round-robin up to their ceiling
(`ceil(slots / 4)`), and only then the rest.

In a long film that ceiling never binds. The budget runs out during the round-robin, so every
`major` story stops at the same water level `L`:

```
grant(major) = min(capture groups it offers, L)
L solves  sum over majors of min(capacity_i, L) = slots - minor presence
```

Worked example, the synthetic year in the regression test (175 slots, 14 `major` stories, 60
`minor` ones on separate days): 175 - 14 - 60 = 101 slots for depth; the eight small majors fill
their capacity (27 more); the six others share the remaining 74 at a level of about 15. A story of
two evenings with a handful of stars gets as many shots as a trip of ten days with a hundred.
Stars act as a step (0 to 2 stars: one shot; 3 or more: the full level) and the count past three
changes nothing.

Three starred evenings of the same activity at the same place in one month therefore take three
full shares, and the month that holds them outweighs every other month of the year. The
model tier folds such stories into one thread after asking the reader; the no-model tier asks
nothing and did nothing.

## The rule

Two or more stories are one **kind** when:

1. the densest episode of each carries the **same activity label**;
2. that episode alone reaches the **day threshold** the gate already uses
   (`max(4 x median photographed day, 75th percentile)`), so a label on a few pictures links nothing;
3. they are at **one place**: the GPS medians of those episodes are within `NEAR_KM` (10 km, the
   event-family radius), or they have the same place name when one side has no GPS;
4. they fall in the **same partition** of the film (a month of a year film; the film itself when
   it has none).

Guards: a story away from home (a trip) and a **big** story (dense and mostly close family, the
existing floor) never fold. `none` and `glimpse` stories never fold.

A kind keeps every member's own picture. Its further depth goes to its **heaviest** member (most
favourites, then most moments, then first in order), marked `depth_to` on every member. In the
allocation, a member that is not the depth holder stops at one picture, and the holder counts the
whole kind against its weight's ceiling, so the kind deepens like one story of its weight.

The label is never evidence on its own: rules 2 and 3 must agree with it.

## Numbers (synthetic)

The regression test `tests/test_editorial_same_kind_threads.py` builds a year shaped like a busy
library: three trips, one recurring kind of evening three times in one month, eight small starred
days and sixty quiet ones, 175 slots.

| story | before | after |
|---|---|---|
| kind, heaviest member | 15 | 19 |
| kind, second member | 10 | 1 |
| kind, third member | 9 | 1 |
| each trip | 15-16 | 19-20 |
| each quiet day | 1 | 1 |

The slots the kind gives back deepen the other `major` stories (the trips first), in the order
the allocation already has. Months of unstarred `minor` stories don't move: that's the separate
"a week with no indicator goes short" ruling.

## Limits

- Grouping by label depends on the activity head. A wrong label can only fold two dense stories
  at one place in one month, and every member still keeps its picture.
- Two different starred occasions of the same label at home in one month (two birthdays) fold
  unless one of them is big. They each keep a shot and the heavier one keeps the depth.
- The kind spans a partition, not the whole film: the same activity in two months is two stories.
