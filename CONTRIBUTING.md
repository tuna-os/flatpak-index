# Contributing to the Flatpak index

This repository documents the TunaOS Flatpak remote and maintains the scripts
used to validate and publish its OCI index. The production index is
`static/flatpak/index/static` in [`tuna-os/docs`](https://github.com/tuna-os/docs);
the `index/static` file and GitHub Pages deployment in this repository are
historical snapshots. Do not use them to infer or update production state.

## Repository layout

- `README.md` documents the remote, application onboarding, and index format.
- `ROADMAP.md` records the planned consolidation of index ownership and
  publication.
- `docs/` and `templates/` contain AppStream metadata and screenshot guidance.
- `scripts/update-index.py` adds or replaces one application's OCI entry. App
  repositories vendor this self-contained script in their publish workflows.
- `scripts/enrich-index.py` compares an index with image labels in the registry
  and can restore missing labels without changing image digests.
- `scripts/oci.py` is the read-only registry client used by
  `enrich-index.py`.
- `tests/` validates the snapshot, repository descriptor, metadata handling,
  and publisher behavior.

## Local validation

The Python scripts and tests use the standard library and require Python 3. A
full unit-test run is:

```bash
python3 -m unittest discover -s tests -v
```

The metadata audit also requires `curl` and network access to GHCR. Run it
against the served production index rather than the local snapshot:

```bash
curl -sSfL -o served-index.json https://tunaos.org/flatpak/index/static
./scripts/enrich-index.py served-index.json --check
```

`--check` never writes the index. It exits nonzero when registry labels are
missing from the index or an image lacks required AppStream metadata. Missing
screenshots are reported as warnings.

The screenshot capture action has additional end-to-end checks in
`.github/workflows/tests.yml`. CI runs those checks on both Debian/Ubuntu and
Fedora package-manager paths; contributors do not need to reproduce both
container environments before opening a pull request.

## Documentation and script changes

- Keep the README's available-app table aligned with the served production
  index.
- Treat `scripts/update-index.py` as the canonical publisher copy. When its
  interface or behavior changes, update the example workflow in `README.md`
  and any affected guidance in `docs/` in the same pull request.
- Add or update unit tests when changing script behavior. Tests must not write
  to the production index or require registry credentials.
- Do not commit downloaded served-index files, credentials, generated Python
  caches, or changes to the historical snapshot that are presented as
  production updates.

## Submitting a change

Create a focused branch, run the relevant validation above, and open a pull
request describing both the user-visible effect and the commands you ran.
Changes to the production index belong in `tuna-os/docs` or in the owning
application's publisher workflow, as described in the README.
