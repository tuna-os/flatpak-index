# AGENTS.md — agent guide for tuna-os/flatpak-index

The **TunaOS Flatpak remote**: the OCI index that `flatpak remote-add tuna-os`
resolves against, plus the scripts that maintain it.

Human docs: [`README.md`](README.md) (app list, and the step-by-step for adding
a new Flatpak), [`docs/`](docs/).

## This repo builds the index; it does not serve it

The remote is served **from [`tuna-os/docs`](https://github.com/tuna-os/docs)**
via Cloudflare Pages at `https://tunaos.org/flatpak/`. So publishing is a
two-repo operation, and a correct index here can still be stale in production.

That matters for CI: `check-metadata.yml` **curls the live served index** —

```yaml
run: curl -sSfL -o served-index.json https://tunaos.org/flatpak/index/static
run: ./scripts/enrich-index.py served-index.json --check
```

— so it validates production, not this branch. **A failure there can mean a
deploy hasn't propagated, not that your change is wrong.** Read it as a
monitoring signal that happens to live in CI.

## The label rule that has already bitten

`scripts/update-index.py` keeps only labels matching:

```python
KEEP_LABEL_PREFIXES = ("org.flatpak.", "org.freedesktop.appstream.")
```

Both prefixes are load-bearing. `flatpak build-bundle --oci` writes the app's
AppStream catalogue and scaled icons into the image config as
`org.freedesktop.appstream.appdata`, `.icon-64` and `.icon-128`, and Flatpak
builds the remote's AppStream catalogue from exactly those. An earlier revision
kept only `org.flatpak.*` and dropped them — the result was apps rendering in
Bazaar, GNOME Software and Discover as a bare `org.tunaos.<app>` string with an
"Unknown" licence and no screenshots, despite a complete catalogue already
being published. Do not narrow that tuple.

## Three copies of one script

`scripts/update-index.py` describes itself as *the canonical copy*, vendored by
application repositories at `.github/scripts/update-index.py` and run from
their publish workflow after `flatpak build-bundle --oci`. A third lives in
`tuna-os/.github` as the `update-flatpak-index` composite action.

They have **drifted structurally** — this copy is 146 lines, the composite
action's is 118 — while currently agreeing on the label behaviour above.
Nothing enforces the sync: "canonical" is asserted in a docstring, not checked
by any test or workflow. When you change this file, check the other two
deliberately; a fix landing in only one is the failure mode this arrangement
invites.

## Checks

```bash
python3 -m unittest discover -s tests -v   # 24 tests
ruff check .                               # config in ruff.toml
```

> **`ruff` is configured but not enforced.** `tests.yml` runs the unittest
> suite (and a screenshot capture); nothing runs ruff, and `ruff check .`
> reports 2 findings on `main`.

`scripts/oci.py` holds the registry plumbing, `enrich-index.py` the validation
used by the live check above.

## Skill: add-flatpak-to-remote

Adding a new app to the TunaOS remote (the long form is in the README):

1. Fork the upstream app into `tuna-os/` (`gh repo fork <upstream> --org tuna-os --fork-name <app>`).
2. Add `org.tunaos.<app>.json` at that repo's root. GNOME 50 apps use
   `org.gnome.Platform` / `org.gnome.Sdk` runtime-version `50`.
3. Have that repo's publish workflow run `flatpak build-bundle --oci` and then
   the vendored `update-index.py`, so the new entry carries both the
   `org.flatpak.*` and `org.freedesktop.appstream.*` labels.
4. Add the app to the README table here.
5. After publishing, confirm the served index really carries it —
   `curl -sSfL https://tunaos.org/flatpak/index/static` — since this repo is
   not what serves it.
