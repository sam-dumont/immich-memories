# Security model

Immich Memories is a self-hosted, single-replica application. Every signed-in user is an administrator. Its security boundary protects the operator's library and credentials from unintended network access and protects the project's build and release process from untrusted contributions.

## Assets and entry points

| Assets | Entry points |
|---|---|
| Primary and partner Immich API keys; library photos, videos, thumbnails and people | Web UI/API on 8080, trigger API, CLI |
| SQLite or PostgreSQL store: people, decisions, run history and sealed settings; finished films | Browser actions, configuration loading, file uploads and store operations |
| Settings encryption key, session/storage secret, trigger and worker tokens, database credentials | Environment/configuration, service connections and process startup |
| Model files, release packages and container images | Model fetches, CI jobs, release workflows and registries |

Optional services add entry points: inference on 8092; the caption server on its configured port (the compose profile publishes 8094); and the render worker on 8093 or its `/render` route. Outbound connections include Immich, configured reader/caption/worker services, and optional geocoding, map tiles, notifications and music providers.

## Trust boundaries

The browser crosses into the app; the app accesses Immich using server-side credentials. Separate model and render services are trusted service connections, and a render worker can receive private content and credentials needed for its task. Internet services receive data only through the corresponding configured functionality. The network/privacy documentation describes those exchanges.

Contributors supply untrusted code and text to the repository. PR checks, the maintainer's agents, merge decisions, privileged CI jobs and registries are separate boundaries. A passing test is not authorization to merge a contribution. External agent and merge-train policies must identify which authors and exact revisions they are authorized to act on.

## Actors and scope

Protect against people on the LAN who can reach a published service, a website visited while the app is running, outside repository contributors and dependency/image/action compromise. Treat accidental or unexpected UI use as a robustness requirement.

The operator's Immich media and deliberately connected partner libraries are trusted inputs for this model. Signed-in administrators are trusted to configure the app. Host permissions, backups at rest, NAS sharing and TLS termination belong to the operator. Roles, enterprise audit trails, WAFs and mandatory SSO are not product requirements.

## Deployment defaults

Authentication is off by default. The ordinary CLI path uses loopback, and the compose quickstart publishes the app on `127.0.0.1:8080`. Enable authentication before exposing it beyond localhost. Optional compose model services also publish on loopback. Kubernetes uses a ClusterIP service, one replica and read-only container roots; network reachability inside a cluster is the operator's responsibility.

SQLite private state and secrets are created with restrictive file permissions. The core model-fetch path validates pinned digests before making downloaded files available. Container base images and external GitHub Actions are pinned, but deployment tags and some optional provider checkpoints are mutable; pinning claims must identify the artifact concerned.

## Accepted limits

There are no roles: all authenticated users are administrators. Model-service routes can be unauthenticated on a private network and should remain unreachable to untrusted clients. The operator owns storage, backup and TLS policy. This model does not claim that every optional service or model has identical authentication or artifact-verification guarantees. Deployment changes and external agent permissions require their own review.
