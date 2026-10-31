# AGENTS.md — agent guide for tuna-os/flatpak-index

The **TunaOS Flatpak remote**: the OCI index that `flatpak remote-add tuna-os`
resolves against, plus the scripts that maintain it.

Human docs: [`README.md`](README.md) (app list, and the step-by-step for adding
a new Flatpak), [`docs/`](docs/).

## This repo builds the index; it does not serve it

The remote is served **from [`tuna-os/docs`](https://github.com/tuna-os/docs)**
via the `tunaos-org` Cloudflare Worker, which deploys that repository's static
assets at `https://tunaos.org/flatpak/`. So publishing is a two-repo operation,
and a correct index here can still be stale in production.

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

`scripts/oci.py` declares the same rule independently as
`FLATPAK_LABEL_PREFIX`/`APPSTREAM_LABEL_PREFIX` and `keep_label()`, used by
`enrich-index.py` to audit the *live* remote against the registry.
`update-index.py` stays self-contained, so this is two
declarations of one invariant. `tests/test_label_policy.py` pins them to each
other — update both together, and let that test tell you if they've drifted.

## One versioned publisher

`scripts/update-index.py` is the canonical implementation. The
[composite action](.github/actions/update-flatpak-index) invokes this file from
its own release checkout, so consumers need no vendored copy. Pin consumers to
a full commit SHA from a `publisher-vX.Y.Z` release; see
[the contract and release guide](docs/PUBLISHER.md).

Legacy copies remain in application repos and `tuna-os/.github`. The org's old
weekly drift check compares those copies against its own action, not this
repository. It does not establish conformance to this publisher. Migrate callers
to this action rather than updating or creating detached copies.

## Checks

```bash
python3 -m unittest discover -s tests -v
ruff check .                               # config in ruff.toml
```

> **CI enforces Ruff and the unittest suite.** `tests.yml` runs `ruff check .`,
> the unittest suite, and capture-action self-tests. Run both commands locally
> before opening a PR; keep `ruff check .` clean.

`scripts/oci.py` holds the registry plumbing, `enrich-index.py` the validation
used by the live check above.

## Skill: add-flatpak-to-remote

Adding a new app to the TunaOS remote (the long form is in the README):

1. Fork the upstream app into `tuna-os/` (`gh repo fork <upstream> --org tuna-os --fork-name <app>`).
2. Add `org.tunaos.<app>.json` at that repo's root. GNOME 50 apps use
   `org.gnome.Platform` / `org.gnome.Sdk` runtime-version `50`.
3. Have that repo's publish workflow run `flatpak build-bundle --oci` and then
   this repository's SHA-pinned `update-flatpak-index` action, so the new entry carries both the
   `org.flatpak.*` and `org.freedesktop.appstream.*` labels.
4. Add the app to the README table here.
5. After publishing, confirm the served index really carries it —
   `curl -sSfL https://tunaos.org/flatpak/index/static` — since this repo is
   not what serves it.
