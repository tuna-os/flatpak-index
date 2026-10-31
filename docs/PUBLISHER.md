# Versioned index publisher

The supported entry point is
`tuna-os/flatpak-index/.github/actions/update-flatpak-index@<full-commit-sha>`.
It runs this release's `scripts/update-index.py`; it never executes a script
from the consuming application repository. The action requires a Linux host
runner with Bash and Python 3.11+ (for example `ubuntu-latest`). Run it outside
a job container, after downloading the OCI layout and checking out the index.

## Contract (publisher-v1)

| Input | Meaning / default |
| --- | --- |
| `oci-dir` | Required local single-image OCI layout from `flatpak build-bundle --oci`. |
| `index-file` | Local JSON index to update; default `index/static`. |
| `repo-name` | Required registry repository name, e.g. `tuna-os/tavern`. |
| `registry` | Hostname for a newly created index; default `ghcr.io`. Existing index registry is preserved. |
| `tags` | Space-separated tags; default `latest`. At least one is required. |
| `require-appstream` | `true` rejects missing AppStream labels; `false` (default) warns, matching the CLI. |

Paths are relative to the caller's working directory, or absolute. The action
changes only the local index file. It has no token input, does not push OCI
images, and does not commit, push or deploy the index. The caller owns those
steps and the narrowly scoped `tuna-os/docs` credential. See the complete
[consumer workflow](../README.md#3-add-a-publish-workflow).

The output contract is the existing OCI index object: `Registry` and `Results`,
with repository `Name` and `Images`. Each image retains its digest, media type,
OS, architecture, tags, and all `org.flatpak.*` and
`org.freedesktop.appstream.*` labels. An update replaces only the same
repository, architecture and application ref; other entries survive. A failed
metadata check exits nonzero before writing the index. `tests/test_publisher_action.py`
exercises this contract through the action's runner with a synthetic OCI layout.
No publisher-version field is added to the production index: the immutable action
SHA selects the implementation, and a missing action/ref fails in GitHub Actions.

## Releases and SHA pins

Publisher releases use separate SemVer tags: `publisher-v1.0.0`,
`publisher-v1.0.1`, etc. A breaking input or output change needs a new major;
compatible features increment minor, fixes increment patch. Never move or reuse
a published tag, and do not publish floating `v1` aliases. Consumers must pin
full commit SHAs, including when updating within a major release.

After this change merges, a maintainer can create the first release from the
reviewed `main` commit (replace `REVIEWED_MAIN_SHA` with its full SHA):

```bash
git fetch upstream main
git tag -a publisher-v1.0.0 REVIEWED_MAIN_SHA -m 'Index publisher v1.0.0'
git push upstream publisher-v1.0.0
```

The tag workflow runs lint and conformance tests before creating a GitHub release
whose notes include the exact pin. This PR does not publish a tag from a fork;
release tags must point to the reviewed upstream commit. To resolve a published
release yourself:

```bash
git fetch upstream tag publisher-v1.0.0
git rev-parse 'publisher-v1.0.0^{commit}'
```

Substitute that 40-character SHA for `PUBLISHER_SHA` in the README example.
Keep the release tag as a comment next to `uses:` for update reviews. Roll back
by restoring the previous reviewed SHA, without moving release tags.

## Migrating consumers

1. Locate workflows invoking `.github/scripts/update-index.py` or the legacy
   `tuna-os/.github` `update-flatpak-index` action. Include scheduled and manual
   publishing paths, not just the default push workflow.
2. Replace the invocation with this action at a released SHA. Carry over
   `oci-dir`, `index-file`, `repo-name`, `registry`, `tags` and AppStream policy.
   Keep OCI upload, index checkout and index commit steps in the caller.
3. Verify a publish against a disposable copy of the index. Check that both
   Flatpak and AppStream labels survive and unrelated applications remain.
4. Remove the vendored script once no workflow references it. Record each
   consumer's old entry point and new release SHA in its migration PR. Migration
   is per consumer repository; this repository's release does not update them.

Do not treat the old org drift check (which compares vendored copies to a
different script) as evidence that a consumer uses this release.
