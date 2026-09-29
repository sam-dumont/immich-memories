---
title: A second Immich account
---

# A second Immich account

The classic couple: two phones, two Immich accounts, one server. Without any of this, a
film only ever sees the primary account's library, and a person tagged on the partner's
photos is invisible to `--person`. This page connects a second account, proves the person
in both accounts is the same person, and reads both into one film, by hand and on
automation's schedule.

Nothing here writes to Immich beyond the film upload you may already have on: no face reset,
no re-tagging, no upgrade to Immich 3.2. Two separate, already-tagged accounts on the current
server are all this needs.

## Connect the account

Add it under `immich.accounts`, by name, next to the primary account, which stays the only
upload target:

```yaml
immich:
  url: "https://photos.example.com"
  api_key: "${IMMICH_API_KEY}"
  accounts:
    partner:
      url: "https://photos.example.com"
      api_key: "${PARTNER_IMMICH_API_KEY}"
```

A name is lowercase letters and digits joined by single underscores (`partner`,
`grandma_2`); `primary` is reserved for the top-level account. The key is a secret like the
primary one: redacted from logs and issue reports, sealed with `IMMICH_MEMORIES_SECRET_KEY` when
saved to the database, and settable from the environment as
`IMMICH_MEMORIES_IMMICH__ACCOUNTS__PARTNER__API_KEY`. Full field reference:
[extra accounts](../reference/config-reference.md#extra-accounts).

Create the key while signed in to Immich as the partner. It only ever reads: the read
permissions in [the API key table](docker.md#the-api-key) are enough, since nothing is uploaded,
tagged or deleted through it.

Configuring it changes no film by itself. Prove the key first:

```bash
immich-memories config test
```

This checks every account, one line per account, each proving who its key belongs to
against `/users/me`. Nothing else is read until a run explicitly asks for the account.

## Bind the same person across accounts

Immich gives the same real person a different person ID in each account it's tagged in.
Nothing here guesses that two IDs are one person: you say so, once, and it's confirmed from
then on.

Binding adds to a person the people store already holds, so run `immich-memories people scan`
first if you never have: it fills the store from the primary account. Then find the person's ID
in the partner account: sign in to Immich as the partner, open the person from the People page,
and copy the ID from the address bar (`/people/<id>`). Then:

```bash
immich-memories people bind "Alex" --account partner --id <person-id-in-partner-account>
```

`PERSON` is a store person ID or a name exactly one person carries. Binding only adds the
ID: the person's name, birth date and everything already confirmed about them stay exactly
as they were, whatever the partner account calls them. An ID already bound to somebody else
is refused, never merged; binding the same ID again changes nothing. A missing binding is
unresolved evidence, not permission to match the two accounts by name.

## Read both accounts into one film

```bash
immich-memories generate --accounts primary,partner --person "Alex" --memory-type person_spotlight --year 2026
```

`--accounts` takes the household through: the same file in both libraries (identical bytes, such
as a photo one partner saved from the other), or a picture one partner shares with the other,
counts once ([duplicates](../how-it-chooses/family-audience-duplicates.md#duplicates)); each picture
downloads through the account that owns it; and either owner's favourite counts. If a
selected account can't be read, the run stops and names the account, rather than delivering
a film with half a household silently missing.

Leaving `--accounts` off reads the primary account alone, exactly as before this existed.
`--accounts` reads exactly the accounts it names, so keep `primary` in the list: `--accounts partner`
reads the partner alone. Albums and trips still read the primary account only: `--accounts` is
refused there. The web UI has no account choice yet: a film you make there reads the primary alone.

## Saved groups

A label for a people condition you'll reuse, instead of retyping `--person` every time:

```bash
immich-memories people group add "Kids" '"<alex-id>" OR "<sam-jr-id>"'
immich-memories people group list
immich-memories generate --group "Kids" --accounts primary,partner --memory-type multi_person --year 2026
```

Write the people as store person IDs, not names: `people bind` prints the ID next to the name
(`Alex (<id>)`), and `people export` lists every person's `ids`. A name is accepted but kept as
typed: a rename breaks it, and automation, which counts a group's pictures by ID, skips a named
group under its default settings.

`--group` resolves like `--people-expression`, against the people store, at generate time:
renaming or re-binding somebody in the store is picked up the next time the group runs,
with no group edit needed. A group holds no copied names or dates, and groups don't nest.

## What automation does across accounts

Automation (`immich-memories auto suggest` / the scheduled daily run) reads the accounts
named in `automation.accounts`, the same way a manual `--accounts` run does: each proven
with `/users/me` first, and a read that fails on any of them fails that day's discovery
rather than silently proposing a film from half a household.

```yaml
advanced:
  automation:
    accounts: ["primary", "partner"]  # list primary too; empty reads the primary alone
    detect_groups: true               # propose last year's film for each saved group
```

As with `--accounts`, the list is exactly what is read: `["partner"]` alone leaves the primary
library out, and with it trips. A saved group's film is a `multi_person` film of the year
before, not proposed again once made, and skipped when none of its people is among the
most-pictured people discovery counts.

Every film automation proposes, trips aside, carries the same `--accounts` scope
automatically; you don't repeat it. Trips still discover from the primary account only, the
same restriction `--accounts` has on the CLI. A birth date in the people store wins over what
either account's Immich says.

## Privacy notes

- The partner account's key is only sent to the partner's own `url`. It's sealed when saved to
  the database, and redacted from logs, issue reports and `config test` output the same way the
  primary key is.
- Reading a second account never contacts a third one. Partner sharing can make an account
  visible in another's response; only pictures the accounts you actually selected *own* are
  kept, so sharing doesn't pull a stranger's library into the film.
- Favourites are read live, through the account that owns the picture. A partner's response
  saying `false` proves nothing about whether the owner starred it; the run reads the
  owner's own account for that.
- The primary account stays the only upload target, always. Connecting a second account
  never adds it as somewhere a finished film gets written back to.
