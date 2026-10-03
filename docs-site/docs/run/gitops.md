---
title: Pin deployment inputs
---

import InstallationFiles from '@site/src/components/InstallationFiles';

# Pin deployment inputs

Use the **same rehearsal/RC version as this documentation build**. Do not substitute v0.103.0:
its manifests, CLI and UI differ from the current instructions. The promoted route vendors the
published deployment bundle, whose packaging substitutes app/inference image tags and Terraform
example pins. A raw source archive or floating Git URL skips those substitutions.

## Download and verify

From an empty directory with curl, tar, shasum and awk installed:

<InstallationFiles kind="bundle" />

The generated commands pin this docs build's exact version, verify the bundle against its
published SHA-256 list and extract into `vendor/immich-memories`. Commit that clean vendored
tree and the recorded version/checksum. Keep your own overlay, credentials and state separate.
A development preview without published assets deliberately supplies no install command.

## Kustomize

With kubectl/Kustomize installed, from the same directory:

```bash
kubectl kustomize vendor/immich-memories/deploy/kubernetes/base > rendered.yaml
```

The current base expects an existing `immich-memories-secrets` Secret. Supply the real reachable
Immich URL, minimum read key and app authentication outside Git using
[the Secret setup](./kubernetes.md#quick-start), or SOPS/External Secrets. Choose the actual
cluster context and local/block StorageClass before applying. Never commit a credential-bearing
render or generated plaintext Secret. Your custom overlay can refer to the vendored base;
keep the bundle unchanged so the next update produces a useful diff.

## Terraform

The bundle's example already has a real relative module path, `../../`, and a release-pinned
`image_tag`. With Terraform 1.9+ installed:

```bash
terraform -chdir=vendor/immich-memories/deploy/terraform/examples/basic init -backend=false -input=false
terraform -chdir=vendor/immich-memories/deploy/terraform/examples/basic validate
```

Before plan/apply, configure your protected state backend and cluster provider, then copy
`terraform.tfvars.example` to a private `terraform.tfvars` and set Immich's URL/read key and
storage/authentication choices. `-backend=false` above is **validation only**. Retain the
versioned image pin. The [module reference](./reference/terraform.md) shows the module path
when called from a root configuration beside `vendor`.

## Update and review

Download the next matching release bundle into a second directory, verify its checksum, then
`diff -ru` the two vendored `deploy` trees. Review image pins, PVCs, resource budgets, policies and
Secret-layout changes before updating your overlay. Commit `.terraform.lock.hcl` with the chosen
provider versions. Render/init/validate again before plan/apply; keep credentials, plans and state
out of the public repository.

The checksum detects changed bytes against the published value, not who built them.
[Provenance verification](../contribute/ci.md) checks attested identity where supplied;
neither validates your cluster configuration, network policies or secrets.

## Validation status

A locally packaged bundle of the current manifests rendered with kubectl 1.34.1 / Kustomize
5.7.1; its Basic Terraform example passed init/validate with Terraform 1.14.7 on darwin/arm64.
That check used a synthetic rehearsal version to test packaging, not a public release.
The public prebuilt rehearsal still needs its empty-directory download/render/init/validate
transcript with exact asset digest and tool versions. A local render check is not a live
Kubernetes rollout, observed QoS class, provider connectivity test or Immich outage/recovery test.
[The deployment matrix](./tested-deployments.md) keeps these statuses separate.
