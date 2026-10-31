# Flatpak application lifecycle

This repository contains index tooling and a reference snapshot. The
`tunaos-org` Cloudflare Worker serves the production remote from `tuna-os/docs`
at `https://tunaos.org/flatpak/`. Follow this distinction for every lifecycle
change.

## Before changing an application

- Identify app ID, GHCR repository, supported architectures, current channel,
  and source revision.
- Work in the application repository for source, manifest, metainfo, and
  publisher workflow changes.
- Treat `tuna-os/docs/static/flatpak/index/static` as production. Do not expect
  edits to this repository's `index/static` snapshot to change the live remote.
- Follow the [publishing migration](PUBLISHING.md). New application publishers
  need only package access to their own GHCR image, with no docs write token.

## Add an application

1. Add the app's Flatpak manifest, metainfo, and icon in its application
   repository. Use the metadata and screenshot guides in this repository.
2. Configure the application publisher to build an OCI layout and push the
   image to GHCR with its own repository token. Register its exact repository,
   tag, architecture, and Flatpak ref in the reviewed docs-side source policy.
   The docs-side refresh owns production index writes; see [Publishing](PUBLISHING.md).

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

## Checks

From this repository, run the test suite, which uses the standard library,
after documentation or script changes:

```sh
python3 -m unittest discover -s tests -v
```

If a publication changed metadata, also run the served-index audit. A non-zero
`--check` result means the live index needs review; it is not proof that the
application build failed.
