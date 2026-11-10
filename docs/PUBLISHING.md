# Publishing without a shared index credential

The maintainer decision on [#25](https://github.com/tuna-os/flatpak-index/issues/25)
defers signatures and prioritizes credential isolation. This repository supplies
the pull-based updater and a docs-side workflow template. To install them and
retire the existing credentials, you need coordinated changes in other repos.
Until that rollout is complete, existing shared-token writers remain a risk.

## Ownership and permissions

Each application workflow publishes its public OCI images to its own GHCR
package. It uses its local `GITHUB_TOKEN` with `contents: read` and
`packages: write`. Package administrators must check that each publisher can
write only its own package. In particular, installer workflows now share
`tuna-os/bootc-installer`. A further isolation step is to separate those
packages.

Only a workflow that runs in `tuna-os/docs` writes the production index. Its
short-lived repository `GITHUB_TOKEN` has `contents: write`. It also needs
`actions: write` to dispatch the existing `deploy-flatpak.yml`: pushes made
with `GITHUB_TOKEN` do not trigger push workflows. No cross-repository token,
App private key, or dispatch secret is distributed to application repos.

The receiver runs on a schedule or a docs-side manual dispatch. This design
does not give publishers a credential with docs Contents permission only to
call `repository_dispatch`. A repository dispatch token with Contents write
would retain the index-write capability that this change removes.

## Reviewed source policy

Copy [the example policy](../templates/flatpak-sources.json) into
`tuna-os/docs/.github/flatpak-sources.json` and add every supported image.
Each entry binds a public GHCR repository and tag to an exact application
ref and architecture. Add separate entries for `amd64` / `x86_64` and
`arm64` / `aarch64`, and for each installer tag. Review those mappings against
the application's manifest and the served index; the example is not a full
production inventory.

An optional `tags` array declares the tags exposed in the Flatpak index. It
must include the source `tag`. By default, the index exposes only that tag. For the
GNOME installer, for example, retain `"tag": "gnome"` with
`"tags": ["gnome", "latest"]` so both existing index aliases survive.

`scripts/pull-index.py` uses skopeo to read only manifest and config metadata,
resolve each approved tag, and select its Linux platform. It verifies manifest and config
blob hashes, needs Flatpak and AppStream labels, and checks the exact
Flatpak ref and architecture before it merges. A publisher cannot use its
labels to replace an unrelated application's entry. All sources must succeed
before the candidate replaces the index. Unlisted entries remain unchanged;
removal still needs a reviewed production edit.

Vendor `scripts/pull-index.py` and `scripts/update-index.py` together in
`tuna-os/docs/.github/scripts/`. The new pull script imports the existing
updater; it does not change that standalone updater's CLI or other copies.
With Python 3.11+ and skopeo installed:

```sh
python3 .github/scripts/pull-index.py \
  --policy .github/flatpak-sources.json \
  --index-file static/flatpak/index/static
```

## Migration order

1. In `tuna-os/docs`, review the complete policy and vendor both scripts.
   Run the command on a candidate index and inspect every changed digest,
   repository, app ref, architecture, and metadata label. A registry or
   metadata failure must leave the original index unchanged.
2. Install [the workflow template](../templates/refresh-flatpak-index.yml)
   as `.github/workflows/refresh-flatpak-index.yml` in docs. It runs only on
   docs `main`. Confirm repository rules allow this reviewed bot publication;
   do not bypass a branch protection or review requirement. If repository
   rules do not allow direct bot pushes, publish through the reviewed PR path
   of the repository.
3. Manually run the receiver and confirm `deploy-flatpak.yml` succeeds and
   the live index reflects the expected images. Scheduled refreshes introduce
   up to an hour of publication delay. You can retry dispatch failures: run
   the refresh again, even when the committed index has not changed.
4. Remove docs checkout, index mutation, and push steps from publishers in
   `Tavern`, `gtk-office-suite`, `tuna-installer-niri`,
   `tuna-installer-cosmic`, `tuna-installer-xfce`, `tuna-installer-kde`,
   `blueshell`, `mandelbrot`, `finupdate`, and `dualcut`. Inventory newer
   publishers too. In docs `build-flatpaks.yml`, retain image publication
   and let the receiver own index writes. Update the starter workflow and
   the guidance for index publication in `tuna-os/.github`, so they no longer
   provision `FLATPAK_INDEX_TOKEN`.
5. A credential owner must revoke the shared PAT and remove its org/repo
   secret grants, including the docs builder's secret. A leaked credential
   stays valid if you only remove a YAML reference. Audit all
   remaining `FLATPAK_INDEX_TOKEN` references and package grants.
6. Verify another application release reaches the remote with no docs write
   credential in its publisher. Record the receiver run, deployment run,
   and served digest. Keep #25 open until the rollout and revocation finish.

## Recovery and remaining trust

A failed refresh does not publish a partial index. Through review, correct or
pause the source that causes the failure, then rerun. A concurrent edit to
production causes a non-fast-forward push to fail. Rerun on the current
branch; do not force-push. To roll back, review and restore the known-good
index digests in docs, and pause refresh until you correct the approved tags
or policy.

This limits an application publisher to approved refs in its allowed GHCR
packages. Compromise of docs, its workflow, deployment credentials, or a
shared package remains significant. HTTPS and OCI digest checks provide no
independent signature verification. Signatures, key ownership, rotation,
revocation, and migration of existing clients remain separate work.
