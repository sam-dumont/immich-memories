---
title: People commands
---

# People commands

Scan the people Immich knows, confirm their roles, and reuse them in films. The browser's **Settings > People** edits the same registry. [People and home](../../get-started/who-is-who.md) is the simplest setup path.

## Scan and inspect

```bash
immich-memories people scan
immich-memories people show
```

The scan reads counts and dates, not pictures. It updates its suggestions without overwriting your confirmed roles and relationships. A rescan keeps your saved groups too.

## Say whose library it is

The scan guesses the owner: the name you passed with `--owner`, else the Immich account's own name, else whoever has the longest span of pictures. Say it once and no scan changes it:

```bash
immich-memories people owner "Alex Example"
immich-memories people owner --nobody
immich-memories people owner --account partner "Sam Sample"
immich-memories people owner
```

`--nobody` is for a shared family account where nobody in the library owns it. Without a person the command prints the current answer and how it was found. Changing the owner clears the roles the registry filled in from the old one and works them out again from the new one. Roles you typed stay. `--owner` on `people scan` still works as the guess for a library nobody has answered for.

## Export and edit

The live registry is in the store. Export it before editing YAML:

```bash
immich-memories people export --to people.yaml
```

Edit the export, then deliberately replace the registry with that file:

```bash
immich-memories people import --from people.yaml --replace
```

Import validates the whole file first. `--replace` can replace newer answers, so use a fresh export and keep a backup.

For Docker, export onto the host, edit `./output/people.yaml`, then import its container path:

```bash
(umask 077; docker compose exec -T immich-memories immich-memories people export > ./output/people.yaml)
docker compose exec immich-memories immich-memories people import --from /app/output/people.yaml --replace
```

`--to people.yaml` would write inside the container. The output mount exposes the edited file
to the app; `umask 077` keeps a new export's names and birth dates private on the host.

## Bind another account's face

When someone uploads through a second Immich account, their face can have another ID. Declare the connection instead of relying on matching names:

```bash
immich-memories people bind "Alex Example" --account partner --id PERSON_ID
```

Then include the account in a film with `generate --accounts primary,partner`. [Second-account setup](../../run/multi-account.mdx).

With `immich.native_sharing: true`, a shared Immich person ID that's already proven on one
account needs only this one binding: the app verifies it once against the other owner's
access and reuses it, instead of asking for a separate binding per account.

## Saved groups

A group names a reusable people condition. Use the canonical IDs shown by `people show`:

```bash
immich-memories people group add kids '"PERSON_ID_A" OR "PERSON_ID_B"'
immich-memories people group list
immich-memories generate --memory-type multi_person --group kids --year 2025
immich-memories people group rm kids
```

Film titles use the saved people's names, not their internal IDs. Unnamed people still
filter the film, but do not add an ID to its title.

Removing a group removes the label, not its people. The UI can create groups under **Settings > People**, then select them from **Memory**.

The [people registry reference](../../reference/people-registry.md) documents inference, export format and ID validation. Every flag: [CLI reference](../../reference/cli-reference.md#people).
