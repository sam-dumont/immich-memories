# Immich sharing and merged household libraries

Research dated 2026-10-03. No issues, comments or PRs were opened. Production behavior is unchanged.

We started household linking before Immich 3.2. There is now overlap, and the goal is to use Immich's native sharing wherever it can replace our work. We still need one merged source library for a film, with both accounts' pictures, favourites and people represented.

**Recommendation: adopt native person identity behind an explicit setting and version checks, but keep household account linking.** A local 3.3 RC experiment confirmed that a primary key can read partner pictures and shared people. It also confirmed that the same key loses the partner's favourite flags. Removing the second key today would change selection.

## What comes from each version

| Immich version | What Immich supplies | What we gain | What it does not replace |
| --- | --- | --- | --- |
| Before 3.2 | Partner asset sharing already exists. Our current account reads and manual person aliases support the older model. | Existing installs keep working. | We still combine account reads and bind separate people identities where needed. |
| 3.2 | Cluster groups connect recognition across trusted users. A person's own record can apply to shared assets. API person IDs map to person-group IDs. Search API v2 adds composable filters. | A shared person-group ID can represent someone across selected owners, avoiding redundant local bindings where Immich has already connected them. | Cluster membership alone does not grant asset access. It is not 3.3's explicit people-sharing API. It does not supply a merged household library or partner favourites. |
| 3.3 | Explicit people sharing within a cluster group, including sharing all people and access roles for managing names and birthdays. The tested RC exposes `GET/PUT/DELETE /people/users` and sharing metadata on people responses. | We can consume Immich's shared roster and stop asking users to recreate those identity links in our store. The experiment resolved a shared name and ID through our existing client. | Asset sharing remains separate. Person permissions do not expose the asset owner's favourites. Our library selection, duplicate merging and film semantics still apply. |

The 3.2 behavior is documented in the [release notes](https://immich.app/blog/v3.2.0-release) and its [person mapping code](https://github.com/immich-app/immich/blob/v3.2.0/server/src/dtos/person.dto.ts). The 3.3 description comes from the [September recap](https://immich.app/blog/2026-september-recap) and the [pinned RC people API](https://github.com/immich-app/immich/blob/v3.3.0-rc.1/server/src/controllers/person.controller.ts). On the research date, 3.3 was a release candidate; this is not a stable-release compatibility claim.

Search API v2 is an API-generation name, not Immich server v2. Our current `/search/metadata` payload worked on the RC. Adopting native sharing does not require replacing it with the new filter syntax immediately.

## What the local experiment proved

The test used an isolated ARM64 Docker stack running `v3.3.0-rc.1`, pinned to server digest `sha256:b281989600c55905b1ac347f29aeed3a96bc94dec544b086c3299f2ce002d13f`. The product checkout was `a3bfc5dbe66efceaf6985abed72c78600a0fbb37`.

The existing synthetic fixture library contains 133 assets. We gave 67 to the primary account and 66 to a partner, then uploaded one exact duplicate to the partner and one asset to an outside account. Face boxes were assigned manually through Immich's API. No personal library was used.

| Check | Observed result | Consequence |
| --- | --- | --- |
| Cluster group plus people sharing, without partner asset sharing | Primary search returned its own 67 assets. | Sharing a person is not sharing a library. |
| Partner sharing with the timeline toggle off | Primary search still returned 67 assets. | Search completeness depends on a UI preference. |
| Partner and outside account shared into the primary timeline | Primary search returned 135 assets. | Accessible does not mean selected for this film. |
| Restrict to the two selected owners, then run our exact-copy merge | 134 asset records became 133 unique pictures/videos. | Native access works with our existing merge logic; Immich did not remove the cross-account duplicate. |
| Shared person ID and name | Recipient lookup worked; primary saw the person on the partner's photo. | Native identity is usable by the current API client. |
| Existing household person restriction | 0 matching assets, versus a 4-asset episode when the shared ID was allowed across selected owners. | Our account-bound face assumption needs a version-aware change. This is our compatibility bug. |
| Partner stars its duplicate | Owner read: `true`. Primary read: `false`. One-key merge lost the star; current household merge kept it. | A single key is not behaviorally equivalent to the current merge. |
| Documented read-only API permissions | Partner photo original, preview and faces; video original and playback; shared person lookup all succeeded. | Reading the shared material does not require an unrestricted key. Setup mutations used separate disposable credentials. |
| Partner revokes its outgoing asset share | Primary original download returned 404. | The upstream access boundary works in this case. A future run must treat lost access as incomplete input. |

Evidence: [machine-readable results](2026-10-03-immich-sharing-results.json) and [reproducible probe](2026-10-03-immich-sharing-probe.py).

This is an API and source-selection experiment, not an end-to-end film validation. We did not test real recognition quality, a Live Photo pair, a full render, every people-sharing role, identity migration after merges or cluster changes, or a live 3.2 stack. Those remain validation work.

## Gains and losses by approach

| Approach | Gains | Losses or remaining cost |
| --- | --- | --- |
| Keep the current path | Both owners' favourites, explicit library membership, existing deduplication and download routing. | Separate credentials and manual person bindings; the old face-owner restriction is wrong for shared person IDs. |
| Native identities with selected owner-account reads | Reuse Immich's recognition and shared roster while preserving each owner's metadata and complete account reads. | Still needs the selected accounts' keys. We need capability detection and safe identity migration. This is the recommended first implementation. |
| Fetch everything through one primary key | Less credential setup; one accessible shared source pool. | Loses partner favourites in the tested RC. Timeline settings can silently remove an owner's assets. Unselected shared owners must be filtered out. This cannot replace the current path while promising identical behavior. |

There are two different kinds of local link. A binding that says two Immich IDs represent the same person may become unnecessary once Immich supplies that identity. A relationship that says someone is a parent, child or partner still belongs in our store. The same applies to saved people groups, owner-confirmed facts and film-specific decisions. Shared names and birthdays do not replace them.

## Gaps and where they belong

**Partner favourites: an upstream capability gap for a one-key integration.** The RC deliberately masks the flag for a non-owner: `mapAsset` computes `isFavorite` from both ownership and the stored flag. This matches the live result. It is not a missing parameter in our client. See the [RC asset response mapping](https://github.com/immich-app/immich/blob/v3.3.0-rc.1/server/src/dtos/asset-response.dto.ts).

What we need is optional, permission-controlled access to the owner's favourite state, with its provenance clear. An eventual API proposal could expose an owner-favourite field or shared favourite metadata while keeping the viewer's own state distinct. Those names are proposals, not existing endpoints. We should not ask Immich to silently redefine `isFavorite` or expose everyone's favourites by default. Until a supported upstream route exists, read favourites with each selected owner's key and keep our existing union rule.

**Complete partner search independent of the timeline toggle: an integration gap to investigate.** The RC's general metadata search includes partners through `timelineEnabled: true`; we measured the selected source shrinking from 134 records to 67 when that toggle was disabled. See [search scope resolution](https://github.com/immich-app/immich/blob/v3.3.0-rc.1/server/src/services/search.service.ts). We have not proved that every other API lacks an explicit partner scope. Check those before proposing an upstream change. Owner-account reads already preserve our current behavior.

**Cross-account duplicate merging: keep our implementation.** Sharing the two libraries returned both copies. We still need checksum folding, unioned favourites and people, deterministic representative choice, and correct Live Photo companion ownership. Similar pictures, edited exports and re-encodes must not be treated as byte-identical copies. This is not a blocker on upstream deduplication.

**Shared person identity: fix our assumptions.** `analysis/person_presence.py` restricts a face to the first access account, which household reads deliberately set to the asset owner. A shared person-group ID can occur on another owner's picture. `analysis/person_resolution.py` also maps each alias to one account, and `db/tables/people.py` stores one account per alias. The fix must separate person identity from the account that supplied or can read it. Do not simply remove owner filtering everywhere: selected-library boundaries and older-server behavior still matter.

**Migration and revoked access: our responsibility, still untested.** Keep canonical store IDs, saved expressions, relationships and confirmations stable when upstream IDs change. Match explicit IDs and server identity, not names. Test upstream person merges, leaving a cluster group, unilateral sharing, expired keys, lost person permissions, reruns and remote rendering. Do not silently reuse stale identity or access facts after a sharing change.

## Proposed version and setting behavior

This is a design for later implementation, not a shipped setting.

| Configuration and server | Fetch and identity behavior |
| --- | --- |
| Native sharing disabled, on any supported version | Current path. No requests to newer sharing APIs. |
| Native sharing enabled, server older than 3.2 | Current path, with a clear explanation that native sharing is unavailable. |
| Native sharing enabled, 3.2.x | Cluster-group-aware person identity and shared-asset handling. Do not call 3.3 people-sharing endpoints. Preserve owner-account reads for favourites and completeness. |
| Native sharing enabled, supported 3.3.x | Shared roster/access discovery plus cluster-group-aware identity. Preserve owner-account metadata and the existing library merge. |
| 3.3 prerelease | Explicit experimental validation against the exact RC. Do not treat an RC number as proof of stable compatibility. |
| Unknown version or unsupported future major | Follow the existing unsupported-version policy; do not assume native capabilities. |

The current `api_version` policy only distinguishes v2 from v3. Add separately detected minor-version capabilities; `api_version: v3` is not evidence that `/people/users` exists. Detect per server/connection, check actual permissions and sharing state, and distinguish an unsupported endpoint from access denial or a server failure. A denied native read must not silently produce a smaller film or fall back to a broader source scope. Missing discovery permissions need a specific preflight explanation.

The first release should preserve results with a hybrid read strategy. Fewer credentials can follow only when all required metadata is available, or if a user deliberately accepts a separately described reduced behavior. Our current requirement is to preserve the merge, including both owners' favourites.

## Existing upstream discussions

Statuses checked on 2026-10-03. These are references for later discussion, not requests opened by this investigation.

| Reference | Status | Relevance |
| --- | --- | --- |
| [12614 Better sharing in Immich](https://github.com/immich-app/immich/issues/12614) | Open; a maintainer comment says the thread was locked | Broad sharing tracker. The latest retrieved maintainer update points to 3.3.0-rc.1 people sharing. There are existing requests for partner favourites in the discussion. |
| [30579 Family library with shared recognition favourites and dedup](https://github.com/immich-app/immich/issues/30579) | Closed as duplicate | Direct overlap with our needs. Its face-sharing description predates the latest changes; its existence does not prove those gaps all remain. The automated closure does not identify a canonical duplicate. |
| [21968 Partner favourite icon shown in timeline](https://github.com/immich-app/immich/issues/21968) | Closed as completed | Historical report treated exposing a partner's favourite flag as a bug. Any future proposal should specify opt-in access, not call the current behavior a regression. |
| [31434 People page excludes partner assets while search includes them](https://github.com/immich-app/immich/issues/31434) | Closed as completed | Reported on 3.2.0. Useful regression case; do not present it as an outstanding 3.3 defect. |
| [30337 Partner search and people inconsistency](https://github.com/immich-app/immich/issues/30337) | Closed as duplicate | A maintainer explicitly points back to 12614 and work already underway. Another broad sharing request would repeat that conversation. |

The search found related requests, but did not establish a dedicated, open API proposal for consented owner-favourite reads. Before posting later, recheck current issues, discussions and implementation. Bring the small reproduction and exact metadata requirement, rather than opening another general family-library request.

## Next implementation checks

1. Run the equivalent live cases on a pinned 3.2 patch and the eventual 3.3 stable release. Keep the current-path tests for older supported servers and for the setting being off.
2. Add one shared-identity compatibility test first: a face recognized only on a selected partner's picture must retain the same episode. Preserve the owner boundary for unselected libraries.
3. Compare hybrid and current merges for exact copies, owner favourites, people expressions, selected/excluded assets, private visibility, Live Photos, downloads and remote workers.
4. Exercise identity migration and permission loss before making native sharing the normal setup recommendation.
5. Revisit the remaining upstream gaps with the owner, then decide what deserves an issue or PR. Nothing is to be opened yet.

## Reproduce the experiment

From the repository root, with Docker and the normal development dependencies available:

```bash
make dev
make immich-gate-up IMMICH_GATE_VERSION=v33-sharing \
  IMMICH_GATE_PORT=127.0.0.1:2303 \
  IMMICH_GATE_SERVER_v33-sharing=ghcr.io/immich-app/immich-server:v3.3.0-rc.1@sha256:b281989600c55905b1ac347f29aeed3a96bc94dec544b086c3299f2ce002d13f \
  IMMICH_GATE_VALKEY_v33-sharing=valkey/valkey:9@sha256:418652cfb58ef879d4978c33553735d7147016032d5aefaa14c828e611eb9dfd
.venv/bin/python docs/research/2026-10-03-immich-sharing-probe.py initialize
.venv/bin/python docs/research/2026-10-03-immich-sharing-probe.py measure
make immich-gate-down IMMICH_GATE_VERSION=v33-sharing \
  IMMICH_GATE_PORT=127.0.0.1:2303 \
  IMMICH_GATE_SERVER_v33-sharing=ghcr.io/immich-app/immich-server:v3.3.0-rc.1@sha256:b281989600c55905b1ac347f29aeed3a96bc94dec544b086c3299f2ce002d13f \
  IMMICH_GATE_VALKEY_v33-sharing=valkey/valkey:9@sha256:418652cfb58ef879d4978c33553735d7147016032d5aefaa14c828e611eb9dfd
```

The gate uses disposable tmpfs storage. `immich-gate-up` resets only the named `v33-sharing` project; initialization requires that fresh instance. The probe is fixed to loopback port 2303. Its temporary state includes disposable keys and must not be published. The saved research JSON contains no keys or account IDs.
