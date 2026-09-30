# Contributing to flatpak-index

Thank you for your work on the TunaOS Flatpak index. This repository holds
scripts, templates, and CI actions to build and audit the Flatpak remote in
[README.md](README.md). It is not the live index. Cloudflare Pages serves the
live index from `tuna-os/docs`; see the README's "Index format" section for
that distinction.

## Repository layout

| Path | What lives here |
|---|---|
| `scripts/update-index.py` | Canonical script that adds/replaces one app's entry in an OCI index. Application repos vendor a copy of this at `.github/scripts/update-index.py` — see the README's "How to add a new Flatpak" section before changing its interface. |
| `scripts/enrich-index.py` | Re-reads AppStream labels from the registry and repairs/audits an index file in place (missing metadata, missing screenshots). |
| `scripts/oci.py` | Shared OCI layout/registry helpers used by the other scripts. |
| `.github/actions/capture-screenshots` | Composite action that captures an app's own window under a headless X server for AppStream screenshots; see `docs/SCREENSHOTS.md`. |
| `templates/` | Starting points for new app metainfo files; see `docs/METAINFO.md`. |
| `tests/` | `unittest`-based test suite for the scripts above. |

## Development

You need Python 3.11+ and the standard library only — no extra dependencies
to install.

Run the test suite locally:

```bash
python3 -m unittest discover -s tests -v
```

Audit the live remote index against what the registry publishes (this
check needs no local setup beyond `curl`):

```bash
curl -sSfL -o served-index.json https://tunaos.org/flatpak/index/static
./scripts/enrich-index.py served-index.json --check
```

## Making a change

1. Branch from `main`.
2. Keep `scripts/update-index.py` self-contained (one file, standard library
   only). Application repos vendor it directly; a new dependency or file split
   breaks every consumer.
3. If you change the CLI contract for `update-index.py` or `enrich-index.py`,
   check the docs. Update the README, `docs/METAINFO.md`, and
   `docs/SCREENSHOTS.md` if needed.
4. Run `python3 -m unittest discover -s tests -v` before you open a PR; add
   or extend tests under `tests/` for any behavior change.
5. Open a PR that describes what changed and why, and link any related issue.

Changes to the **production** index (`static/flatpak/index/static`) belong in
`tuna-os/docs` or in the publish workflow of the target application
repository. Do not change it here; see the README's "Index format" note.

## Questions or problems

Open an issue in this repository: <https://github.com/tuna-os/flatpak-index/issues>.

<!-- hive-contribute-plea: donated-compute appeal, keep in sync across repos -->
## Contribute compute — no code needed

No time to write code? You can still push this project's backlog forward. TunaOS AI-agent hives work on this repository. Lend a hive your AI subscription or API tokens, and your machine runs contributor tasks from this project's backlog.

- 🪸 [Contribute compute to the reef hive](https://reef.tunaos.org/contribute)
- 🏫 [Contribute compute to the school hive](https://school.tunaos.org/contribute)
