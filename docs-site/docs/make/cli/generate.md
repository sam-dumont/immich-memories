---
title: Generate a film
description: CLI recipes for a month, a person, a trip and a saved cut.
---

# Generate a film

`generate` prepares pictures, selects a cut and renders it. For a first run, use a small
[album](../memory-types.mdx#album) of 20–50 pictures; a whole month can take much longer to prepare.
The month below is an example once your installation is ready.

Run `models fetch` only if you have not already used **Download models** in the browser:

```bash
immich-memories models fetch
immich-memories preflight
immich-memories generate --memory-type monthly_highlights --year 2025 --month 6
```

Generation connects to Immich before probing local encoding hardware and title rendering.
If the server cannot be reached, the run history records the failed attempt.

During a quiet step, the log repeats the latest progress about every 30 seconds.
Preparing clips includes both fetching sources and rendering photos.

In Docker, prefix every command with `docker compose exec immich-memories`.

## Review before rendering

```bash
immich-memories generate --memory-type monthly_highlights --year 2025 --month 6 --no-render
```

This selects and saves a real cut. Open it in the web UI, or inspect it and render later:

```bash
immich-memories runs story
immich-memories runs render
```

`--dry-run` is different: it previews inputs and required preparation without selecting a cut. Sentence requests also preview their translation.

## Examples

A year in review:

```bash
immich-memories generate --year 2025
```

One person:

```bash
immich-memories generate --memory-type person_spotlight --person "Riley" --year 2025
```

A birthday window (set the birth date in Immich):

```bash
immich-memories generate --year 2025 --birthday --person "Riley"
```

A portrait short:

```bash
immich-memories generate --year 2025 --month 8 --short-form 30 --orientation portrait
```

## Trips

Set [home coordinates](../../get-started/who-is-who.md). List the detected trips before choosing one:

```bash
immich-memories generate --memory-type trip --year 2025
```

Then use its index:

```bash
immich-memories generate --memory-type trip --year 2025 --trip-index 2
```

## A film from a sentence

[Sentence films](../free-text.md) are experimental and need Full preparation, captions and a reader. Preview first:

```bash
immich-memories generate --ask "our cat through the years" --dry-run
```

## Output

Each render writes a new folder under `output.directory`; reruns do not overwrite earlier films. `--output` changes the base name and location, but the actual file gains the recipe hash and run folder.

`--resolution` takes the config value; `auto` matches source clips. When `--resolution` is omitted, the command uses `output.resolution` (1080p by default). `--quality` takes `high`, `medium` or `low`: these map to config quality `high`, `balanced` and `fast`. The same names apply to `runs render`. Basic preparation can still limit source intermediates to 1080p.

Use `--upload-to-immich --album "Memories"` to deliver the film to Immich. Setting `upload.enabled: true` also enables delivery without the flag; `upload.album_name` supplies the default album. Once delivery is confirmed, the app removes the local output and keeps the run record and Immich link. Leave upload off to keep the file locally.

The key must have the [read permissions](../../run/docker.md#the-api-key) before a cut starts. Upload permissions are optional. If the key cannot upload, tag or file the film into its album, generation still completes and prints the retained local path with the reason. The run page offers **Download**. Missing `asset.delete` only keeps the previous version in Immich.

The [generated CLI reference](../../reference/cli-reference.md#generate) lists every flag. The [generation contract](../../reference/generation-contract.md) covers person expressions, accounts, title precedence, sharing, recipe hashes and timelines.
