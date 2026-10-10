---
title: Operate and configure
description: Run Immich Memories with Docker, on a NAS, with Python or in Kubernetes. Configure storage, authentication, networking and backups.
---

Start with [Quick start](../get-started/quick-start.md) for Basic, GPU or Full beside Immich. Use this section when you need a different deployment or want to manage it over time.

<Diagram name="architecture-overview" headline="Everything runs on your machine. Nothing leaves your network unless you switch it on." />
## Choose a deployment

| Your setup | Start here |
|---|---|
| Docker on a server or desktop | [Docker Compose](docker.md) |
| Synology or Unraid | [On a NAS](nas.md) |
| Python on your own host | [pip / uv](uv-pip.md) |
| Kubernetes cluster | [Kubernetes](kubernetes.md) |
| Infrastructure managed as code | [Terraform](terraform.md) |

[Requirements](requirements.md) explains hardware limits and what extra resources buy you.

Already running the app and ready to move work elsewhere? Choose [one GPU service](reference-setup.md) for a shared NVIDIA worker, [distributed Kubernetes services](reference/cluster-example.md) for independently managed workloads, or [local Apple Silicon services](reference/mac-example.md) for a native Mac installation. Each guide explains what you must provide and what stays on the app host.

For an example of independently managed services, [How I run it](how-i-run-it.md) describes my own setup: the app and one GPU worker on Kubernetes, the reader on a Mac, and what each piece costs.

## Protect access and keep your data

The default UI listens on localhost with authentication off. It holds an Immich API key: enable [authentication](authentication.mdx) before publishing it to other machines. Run one UI replica.

- [Network and security](network-security.md): bind addresses, proxies and service access.
- [Privacy](privacy.md): what leaves your network and the switches that enable it.
- [Storage and backups](maintenance/storage-backups.md): what to preserve and how to restore it.
- [Database](database.md): SQLite or PostgreSQL for the store.

## Configure and maintain it

Use [Configuration](config-file.md) to understand where settings come from, then look up an individual key in the [config reference](../reference/config-reference.md). [Environment variables](environment-variables.md) are useful for container deployments.

[Upgrading](maintenance/upgrading.md) covers a version change. [Health, logs and caches](maintenance/health-logs-cache.md) covers a service that is slow or not starting.

For optional caption, text or GPU services, start with [Optional upgrades](../better/overview.md). Add them to solve a specific need; the default film does not require them.
