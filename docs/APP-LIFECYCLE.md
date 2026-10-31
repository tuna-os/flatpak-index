# Flatpak application lifecycle

This repository contains index tooling and a reference snapshot.
The Worker for `tunaos.org` serves the production remote from `tuna-os/docs` at `https://tunaos.org/flatpak/`.
Per issue #171, `tuna-os/docs` is the canonical catalog.
Follow this distinction for every lifecycle change.

## Before changing an application

- Identify app ID, GHCR repository, supported architectures, current channel,
  and source revision.
- Work in the application repository for source, manifest, metainfo, and
  publisher workflow changes.
- Treat `tuna-os/docs/static/flatpak/index/static` as production. Do not expect
  edits to this repository's `index/static` snapshot to change the live remote.
- Keep `FLATPAK_INDEX_TOKEN` scoped to `tuna-os/docs` as documented in the
  publish workflow. Never put token values in commands or documentation.

## Add an application

1. Add the app's Flatpak manifest, metainfo, and icon in its application
   repository. Use the metadata and screenshot guides in this repository.
2. Configure the application publisher to build an OCI layout, push the image
   to GHCR, and update the production index. Prefer the shared
   `tuna-os/.github/actions/update-flatpak-index` action. If using the vendored
   script, pass:

   ```sh
   python3 .github/scripts/update-index.py \
     --oci-dir <app>.oci \
     --index-file index-repo/static/flatpak/index/static \
     --repo-name tuna-os/<app> \
     --require-appstream \
     --tags latest
   ```

3. Review the application change and publisher output together. The index
   entry must carry both Flatpak labels and AppStream labels.
4. Verify production after publication:

   ```sh
   curl -sSfL -o served-index.json \
     https://tunaos.org/flatpak/index/static
   ./scripts/enrich-index.py served-index.json --check
   ```

   This audit reads registry labels for the digests already named in the
   served index. It reports missing metadata but does not change the file.

## Update an application

1. Change source, manifest, metainfo, screenshots, or release notes in the
   application repository.
2. Publish a new OCI image through the existing application workflow. The
   updater replaces the matching application entry for the same architecture;
   it does not rewrite unrelated applications.
3. Confirm the candidate has the intended app ID, immutable manifest digest,
   architecture, channel, and AppStream labels. Then push the production
   index.
4. Run the production verification commands above. Check the app entry and
   metadata from the served index, not only the local OCI directory.

For a local reference snapshot or a reviewed candidate index, run
`scripts/update-index.py` with `--oci-dir`, `--index-file`, `--repo-name`, and
`--tags`. Remember that this checkout is not the production source.

## Pause publication

The current updater has no `--pause` operation. Do not silently delete an entry
or change an image tag to simulate a pause.

1. Open a reviewed maintenance decision naming the app ID, reason, owner,
   start date, and whether existing installs remain supported.
2. Coordinate the decision in the application repository and `tuna-os/docs`
   before you change production. Do not disable or alter a publisher workflow
   without maintainer approval.
3. If the decision changes the production index, update it in `tuna-os/docs`.
   Follow the normal review path and include the decision.
4. Run the served-index audit and record whether the app remains listed. A
   paused app must have an explicit reactivation or retirement owner; this
   repository does not automate that state.

## Retire an application

The current updater adds or replaces entries; it has no delete operation.
Retirement therefore needs a coordinated, reviewed production change.

1. Confirm the app ID, GHCR image, publisher workflow, supported users, and
   replacement or end-of-life notice.
2. Stop future publisher updates through the application repository's normal
   maintainer-controlled process before you remove the production entry.
3. Remove the app entry in `tuna-os/docs` through review. Do not treat a change
   to this repository's reference snapshot as a retirement.
4. Run the served-index audit and verify the retired app is absent from the
   served index. Keep the retirement decision and date in the change record.

## Respond to a bad publication

A publication is bad when the served remote does not match the registry or catalog.
For example, `enrich-index.py --check` reports missing metadata.
In this case, roll back to the previous good index.

The Worker for `tunaos.org` serves production from `tuna-os/docs`.
Therefore, a rollback is a change to `tuna-os/docs`, not this repository.
The `index/static` file in this repository is a reference snapshot.
Do not use it as the recovery source.

1. Confirm the publication error against the registry:

   ```sh
   curl -sSfL -o served-index.json \
     https://tunaos.org/flatpak/index/static
   ./scripts/enrich-index.py served-index.json --check
   ```

2. Identify the last good commit to `static/flatpak/index/static` in `tuna-os/docs`.

3. Revert the bad commit in `tuna-os/docs`.
   The Worker re-serves the asset after a push to `main`.
   Keep `FLATPAK_INDEX_TOKEN` scoped to `tuna-os/docs`.
   Never write token values in commands or commits.

4. Verify the served URL again with the check command from step 1.
   Confirm that catalog digests and metadata match the registry.

5. Record the incident details: commit SHA, restored state, date, and operator.

The owner for rollbacks is the `tuna-os/docs` maintainer team.

## Checks

From this repository, run the test suite, which uses the standard library,
after documentation or script changes:

```sh
python3 -m unittest discover -s tests -v
```

If a publication changed metadata, also run the served-index audit. A non-zero
`--check` result means the live index needs review; it is not proof that the
application build failed.
