---
title: People registry contracts
---

# People registry contracts

Inference, export format and identity rules. For normal scanning and editing, see [People commands](../make/cli/people.md).

The one rule doing most of the work: volume is a burst, continuity is a relationship. 160 pictures over four
active months is four events; the same 160 over forty months is part of your life.

| tier | shape |
|---|---|
| `inner` | at least 24 active months across 3 years, present in at least 35% of the months between; or the child rule below |
| `recurring` | a dozen months or more, failing one of the `inner` conditions |
| `episodic` | everything that is not one of the other three |
| `event` | four active months or fewer, averaging at least 20 pictures per active month: a burst |

The burst rule runs first. Otherwise, a person with a known birth date, whose first photographed
month is no later than a year after birth, counts as `inner` when present in at least half the
months between their first and last appearance. This lets a child born into the library qualify
without waiting three years. These are suggestions; confirmed relationships remain yours.

The scan also flags tight pairs (two people who are each a quarter or more of each other's pictures), possible twins
(same family name and birth date, marked `counts_reliable: false` because face recognition merges them) and one
name on two person records. These are metadata-based suggestions, not confirmed relationships; different surnames or missing dates can leave relationships undiscovered. You are behind the camera, so pairs with you are read from month curves, not shared
frames. The owner comes from `--owner` or `IMMICH_MEMORIES_OWNER` (`identified: told`), else your Immich account
name (`account`), else the longest-running person (`inferred`: check it).

The registry lives in the [store](../run/database.md), next to every other decision you made. Everything under
`inferred:` is recomputed on each scan; everything under `confirmed:` is yours and never overwritten, and wins
where the two disagree. `people export` writes it out in the shape below (to standard output, or to `--to FILE`
readable only by you):

```yaml
people:
  - ids: [5f2c…]
    name: Alex Example
    birth_date: '1988-04-02'
    inferred:
      tier: inner
      evidence: {count: 4210, active_months: 180, span_years: 17.2, onset: '2009-06', continuity: 0.87}
    confirmed:
      role: null
      links: []
```

`people import --from FILE` replaces the registry with an edited export. It checks the whole file first: a
person without valid `ids` (a primary list or per-account lists), or an id listed twice, is refused with its position, and nothing changes. Ids
come back exactly as written, `manual:` ids included. A registry that already holds people is only overwritten
with `--replace`, so an import cannot silently replace confirmed answers. A scan never reads the file; only an
import does.

A second Immich account on the same server gives the same person a different id. You say which ids are the same
person (the model @Mike7154 laid out in [#703](https://github.com/sam-dumont/immich-memories/issues/703)), and `ids:` becomes one list per account, `primary` first:

```yaml
people:
  - ids:
      primary: [5f2c…]
      partner: [a91e…, 07bd…]
    name: Alex Example
```

A flat `ids: [...]` list still works and means your main account only, so a one-account export looks exactly as
it always did. Account names follow the rule for `immich.accounts` (lowercase letters and digits joined by single
underscores), and the account doesn't have to be configured yet. An empty list, a name that breaks the rule, or an
id listed under two accounts or two people is refused, and nothing changes. A top-level `accounts:` map is refused
too, with the new shape in the message.

The first id listed is the person's own id: the one links and saved references point at. Adding ids never
changes it. When the person's own id isn't first (someone who came in through the partner account and later got
a `primary` id), the export names it with a `person_id:` line next to `ids:`, and an import keeps it.

To add one id without editing the file:

```bash
immich-memories people bind "Alex Example" --account partner --id a91e…
```

The person is a store id or a name exactly one person carries; if two people share the name, the command lists
their ids and asks for one. `bind` only adds the id: the name, birth date and your answers stay put. An id somebody
else holds is refused, never merged, and binding the same id twice changes nothing. Ids are never matched by name.
A film reads the second account with `generate --accounts primary,partner`
([generate](../make/cli/generate.md)), and a bound person counts as one person across both.

### Saved groups

A group is a label for a people condition, so `generate --group kids` reads the same as typing the expression
out. It saves nothing about the people themselves, just the condition:

```bash
immich-memories people group add kids '"5f2c…" OR "a91e…"'
immich-memories people group list
immich-memories people group rm kids
```

`add` takes the same grammar as `--people-expression`, but the leaves are ids (what `people show` lists), not
names: `people group list` prints them, `people group add` refuses a label already in use, and `people group rm`
never touches the people the group named. `generate --group kids` resolves the saved expression through the
people store exactly as `--people-expression` does, and it combines with `--accounts` the same way. Groups round-trip
with `people export`/`people import`, next to the people.

The scan also writes its measurements (every person's counts and the pairs seen together) to
`~/.immich-memories/people-graph.json`. That one stays a file: each scan recomputes all of it from Immich and
nothing reads it back.

It is the same registry as the **People** page in the web UI. The roles you confirm there decide who counts as close
family, and selection reads that on every tier: the family seat, the big-story rule, and the relations a model
sees. Setting it up is on [Home and people](../get-started/who-is-who.md); how selection uses it is on
[Family, audience and duplicates](../how-it-chooses/family-audience-duplicates.md).
