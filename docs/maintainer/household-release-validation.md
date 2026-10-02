# Household release validation

Maintainer procedure; no private testlab media or reports belong in this repository.

## Household validation before release

Before publishing the first RC, recheck all eight households in the maintainer's private testlab. Update its pinned product dependency to the exact candidate revision and refresh the environment before running the household scenarios. An older report does not validate the candidate.

Record the revision, tier, scenarios checked and failures. Check people and saved groups, selection, titles and wording, and the holidays or celebrations relevant to each household. Verify expected no-film outcomes as well as successful films. NAS results establish NAS coverage; check other tiers separately before claiming they passed. Fix failures or state the remaining limits before publishing.

The testlab uses real people's photos from a controversial dataset. Its household material and detailed reports stay on the maintainer's laptop. Do not upload them to CI, hosted previews or the public website. This includes photos, thumbnails, screenshots and rendered films.

Only anonymous aggregate results may be published, after the testlab's public-report check: counts, pass rates and timings, without names, identifiers, source links, locations or picture-level details. Public screenshots and demos use the separate [CC0 demo fixture](../../docs-site/docs/contribute/demo-assets.md#fixture-and-asset-contracts).

This is a release validation requirement, not a claim that eight households cover every family or culture. New examples from contributors should extend that coverage. See [Households and cultures](../../docs-site/docs/contribute/development-setup.md#households-and-cultures).
