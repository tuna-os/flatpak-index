# TunaOS Flatpak Index

Add this remote to install TunaOS Flatpaks:

```bash
flatpak remote-add --if-not-exists tuna-os https://tunaos.org/flatpak/tuna-os.flatpakrepo
flatpak install tuna-os org.tunaos.mariner
```

> **Note:** `flatpak remote-info` against this remote returns `error: Server
> returned status 401`. The flatpak client has this known limitation with OCI
> remotes: it fetches the manifest without the registry token handshake. This
> 401 does not show a fault in the remote; see
> [#96](https://github.com/tuna-os/flatpak-index/issues/96).
> The OCI authenticator does not change it. Check the remote with
> `flatpak remote-ls` or with an install instead.

Add the remote with `--user` for a user installation, or `--system` (with
sudo) for the whole machine. Then use the same scope to install and update.
A user-scope remote needs `flatpak update --user`: plain `flatpak update`
checks the system scope and reports nothing to update.

The Worker for `tunaos.org` serves `tunaos.org/flatpak/` from [tuna-os/docs](https://github.com/tuna-os/docs).
The `tuna-os/docs` repository is the canonical catalog for all Flatpak releases.
This repository provides tooling, templates, and AppStream validation.
For the lifecycle workflow, see the [application lifecycle runbook](docs/APP-LIFECYCLE.md).

<!-- hive-contribute-plea: donated-compute appeal, keep in sync across repos -->
## Contribute compute — no code needed

**[Donate time with your AI CLI](https://hub.tunaos.org/#contribute).**

Your machine runs one task at a time using your signed-in AI coding CLI.
The relay alternates between eligible **School** (OS) and **Reef** (apps)
hives after each task. If one hive has no work, the other can continue.

The guide covers prerequisites, verified `just` setup, credentials, provider
costs, and how to stop with Ctrl+C. Your subscription quota or API charges apply.
Never post account credentials or API keys in issues or pull requests.

## Available apps

| App | Install |
|-----|---------|
| Letters | `flatpak install tuna-os org.tunaos.letters` |
| Tables | `flatpak install tuna-os org.tunaos.tables` |
| Decks | `flatpak install tuna-os org.tunaos.decks` |
| Mariner | `flatpak install tuna-os org.tunaos.mariner` |
| Finupdate | `flatpak install tuna-os org.tunaos.finupdate` |
| Dualcut | `flatpak install tuna-os org.tunaos.dualcut` |
| Mandelbrot | `flatpak install tuna-os org.tunaos.mandelbrot` |
| Tavern | `flatpak install tuna-os org.tunaos.tavern` |
| Compass | `flatpak install tuna-os org.tunaos.compass` |
| BlueShell | `flatpak install tuna-os org.tunaos.BlueShell` |
| Ghostty | `flatpak install tuna-os com.mitchellh.ghostty` |
| Installer (bootc-installer) | `flatpak install tuna-os org.bootcinstaller.Installer` |
| Installer (KDE) | `flatpak install tuna-os org.tunaos.InstallerKde` |
| Installer (Niri) | `flatpak install tuna-os org.tunaos.InstallerNiri` |
| Installer (COSMIC) | `flatpak install tuna-os org.tunaos.InstallerCosmic` |
| Installer (XFCE) | `flatpak install tuna-os org.tunaos.InstallerXfce` |

> The installer frontends drive the [fisherman](https://github.com/projectbluefin/fisherman)
> bootc backend. The matching TunaOS live ISOs include these frontends
> (see `build_scripts/installer-frontend.sh` in [tuna-os/tunaOS](https://github.com/tuna-os/tunaOS)).

> **Compass** is a hard fork of [Vicinae](https://github.com/vicinaehq/vicinae).
> Its source is [tuna-os/compass](https://github.com/tuna-os/compass).
> On first start, Compass moves an existing Vicinae configuration into its own directory.
> Its image is `ghcr.io/tuna-os/compass`.
> It uses the `org.freedesktop.Platform//26.08` runtime from Flathub.

> **Note**: Letters, Tables and Decks are Rust rewrite versions from [gtk-office-suite](https://github.com/tuna-os/gtk-office-suite). The manifests use unsuffixed IDs (`org.tunaos.letters` etc.).
> The legacy Python versions are at [tables](https://github.com/tuna-os/tables), [decks](https://github.com/tuna-os/decks), [letters](https://github.com/tuna-os/letters).

---

## How to add a new Flatpak to the TunaOS remote

### 1. Fork the upstream app into `tuna-os/`

```bash
gh repo fork <upstream/repo> --org tuna-os --fork-name <app>
```

### 2. Add a Flatpak manifest

Create `org.tunaos.<app>.json` at the repo root. For apps that use **GNOME 50** (GTK4 + libadwaita):

```json
{
  "id": "org.tunaos.<app>",
  "runtime": "org.gnome.Platform",
  "runtime-version": "50",
  "sdk": "org.gnome.Sdk",
  "command": "<command>",
  "tags": ["latest"],
  "finish-args": [
    "--share=ipc",
    "--socket=fallback-x11",
    "--socket=wayland",
    "--device=dri"
  ],
  "modules": [
    {
      "name": "<app>",
      "buildsystem": "simple",
      "build-commands": [
        "mkdir -p /app/<app>",
        "cp -r /run/build/<app>/. /app/<app>/"
      ],
      "sources": [
        { "type": "dir", "path": "." }
      ]
    }
  ]
}
```

The app must also install `<app-id>.metainfo.xml` to `/app/share/metainfo/` and
an icon to `/app/share/icons/hicolor/`, or it will have no name, icon, licence
or screenshots in a software centre. See [App metadata](#app-metadata).

For apps that need **Node.js** (like Mariner), add a `nodejs` module:

```json
{
  "name": "nodejs",
  "buildsystem": "simple",
  "build-commands": [
    "mkdir -p /app/nodejs",
    "cp -r . /app/nodejs/"
  ],
  "sources": [{
    "type": "archive",
    "url": "https://nodejs.org/dist/v22.23.1/node-v22.23.1-linux-x64.tar.xz",
    "sha256": "9749e988f437343b7fa832c69ded82a312e41a03116d766797ac14f6f9eee578",
    "only-arches": ["x86_64"]
  }]
}
```

### 3. Add a publish workflow

Create `.github/workflows/publish-flatpak.yml`:

```yaml
name: Publish Flatpak
on:
  push:
    branches: [main]  # or master
    tags: ['v*']
  workflow_dispatch:

permissions:
  contents: read
  packages: write

jobs:
  build-oci:
    name: Build Flatpak OCI
    runs-on: ubuntu-latest
    container:
      image: ghcr.io/flathub-infra/flatpak-github-actions:gnome-50
      options: --privileged
    steps:
      - uses: actions/checkout@v4
      - name: Build Flatpak
        uses: flatpak/flatpak-github-actions/flatpak-builder@v6
        with:
          manifest-path: org.tunaos.<app>.json
          cache-key: flatpak-builder-${{ github.sha }}
          build-bundle: false
          upload-artifact: false
      - name: Export OCI
        run: |
          flatpak build-bundle --oci --arch=x86_64 repo <app>.oci org.tunaos.<app>
      - name: Upload OCI artifact
        uses: actions/upload-artifact@v4
        with:
          name: <app>-oci
          path: <app>.oci/
          retention-days: 1

  publish:
    name: Publish to GHCR
    needs: build-oci
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          name: <app>-oci
          path: <app>.oci
      - name: Push OCI to GHCR
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          echo "$GITHUB_TOKEN" | skopeo login ghcr.io -u "${{ github.actor }}" --password-stdin
          skopeo copy oci:<app>.oci docker://ghcr.io/tuna-os/<app>:latest
      - name: Check out central index
        uses: actions/checkout@v4
        with:
          repository: tuna-os/docs
          token: ${{ secrets.FLATPAK_INDEX_TOKEN }}
          path: index-repo
      - name: Update central index (tuna-os/docs)
        run: |
          python3 .github/scripts/update-index.py \
            --oci-dir <app>.oci \
            --index-file index-repo/static/flatpak/index/static \
            --repo-name tuna-os/<app> \
            --require-appstream \
            --tags latest
          cd index-repo
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add static/flatpak/index/static
          if git diff --cached --quiet; then
            echo "No index changes"
          else
            git commit -m "chore(flatpak): update <App> OCI index"
            git push origin main
          fi
```

Application workflows must write only to `tuna-os/docs`.
Publishers should use the `publish-flatpak-index` action in `tuna-os/.github`.
That action manages authentication, updates `static/flatpak/index/static`, and retries push conflicts.

Also vendor [`scripts/update-index.py`](scripts/update-index.py) from this repo
to `.github/scripts/update-index.py`, or use the `update-flatpak-index` action
from `tuna-os/.github` (`tuna-os/.github/actions/update-flatpak-index`). **Prefer
the composite action.** The weekly drift check in `tuna-os/.github` treats the
action as canonical, not this file. In the past, they drifted apart.
See [AGENTS.md](AGENTS.md#three-copies-of-one-script) for the history, and for
why that check does not look at this file. Do not copy an older version
from another app repository — see [App metadata](#app-metadata) for why.

### 4. Set repo secrets

- **`FLATPAK_INDEX_TOKEN`**: A fine-grained GitHub PAT with **Contents: read and
  write** access only to `tuna-os/docs`. Do not reuse a general-purpose CLI or
  account token.

```bash
gh secret set FLATPAK_INDEX_TOKEN --repo tuna-os/<app>
```

Enter the fine-grained token at the prompt. Do not place token values in command
arguments, repository URLs, or documentation.

### 5. Push to trigger the build

```bash
git push origin main  # or master
```

The CI will:
1. Build the flatpak in the GNOME 50 container
2. Export it as an OCI image
3. Push to `ghcr.io/tuna-os/<app>:latest`
4. Update the central index in `tuna-os/docs/static/flatpak/index/static`
5. The `tunaos-org` Cloudflare Worker publishes the new assets at `tunaos.org`

## App metadata

Software centres such as [Bazaar](https://github.com/kolunmi/bazaar), GNOME
Software and KDE Discover render an app page from **AppStream** metadata. On an
OCI remote that metadata travels as three image labels —
`org.freedesktop.appstream.appdata`, `.icon-64` and `.icon-128` — which
`flatpak build-bundle --oci` writes automatically from the app's
`/app/share/metainfo/<app-id>.metainfo.xml`.

The publisher must copy those labels into `index/static`. If it does not,
flatpak cannot build a catalogue. Every app in the remote then shows
as a bare application ID with an "Unknown" licence and no screenshots.

- **Metainfo file guide:** [`docs/METAINFO.md`](docs/METAINFO.md), based
  on [`templates/org.tunaos.example.metainfo.xml`](templates/org.tunaos.example.metainfo.xml).
  It follows [Flathub's quality guidelines](https://docs.flathub.org/docs/for-app-authors/metainfo-guidelines/quality-guidelines),
  which sets the standard for software centres.
- **Screenshots:** [`docs/SCREENSHOTS.md`](docs/SCREENSHOTS.md). The shared
  [capture action](.github/actions/capture-screenshots) takes pictures of an app
  window under a headless X server. CI generates screenshots from the app directly
  instead of by hand. The audit below reports apps that declare none.
- **Audit the live remote:**

  ```bash
  curl -sSfL -o served-index.json https://tunaos.org/flatpak/index/static
  ./scripts/enrich-index.py served-index.json --check
  ```

  This reports any published image whose metadata is missing from the index, or
  that has no metadata at all. Run daily by
  [`check-metadata.yml`](.github/workflows/check-metadata.yml).
- **Repair an index in place:** `./scripts/enrich-index.py <index-file>`
  reads labels from the registry and writes them back. It only touches listed
  digests, which keeps the set of published images unchanged.

## Architecture

```
User
  │ flatpak remote-add https://tunaos.org/flatpak/tuna-os.flatpakrepo
  ▼
tunaos.org (Cloudflare Worker + static assets)
  └── tuna-os.flatpakrepo     → points to oci+https://tunaos.org/flatpak
  └── index/static             → JSON index, lists all apps + OCI references
       │
       ▼
ghcr.io/tuna-os/<app>         → OCI images with flatpak metadata
  ├── tuna-os/mariner:latest
  ├── tuna-os/tables:latest
  ├── tuna-os/letters:latest
  └── ...
```

## Canonical catalog and index format

`tuna-os/docs` is the authoritative repository for the Flatpak catalog.
The live catalog file lives at `static/flatpak/index/static` in `tuna-os/docs`.
The Worker for `tunaos.org` deploys assets from `tuna-os/docs` to `https://tunaos.org/flatpak/`.
Users add the remote through `https://tunaos.org/flatpak/tuna-os.flatpakrepo`.

The `index/static` file is a JSON array with OCI image references. Each entry maps an app name to its manifest digest and flatpak metadata labels. Flatpak downloads this index, finds the right image by app ID and architecture, then pulls it from the GHCR registry.

### Ownership and responsibilities

- **Authoritative repository:** `tuna-os/docs` owns the production catalog (`static/flatpak/index/static`).
- **Tooling repository:** `tuna-os/flatpak-index` provides index scripts, metainfo templates, and AppStream validation. It is not an independent distribution host.
- **Publish target:** Release workflows send updates only to `tuna-os/docs` with `FLATPAK_INDEX_TOKEN`. Publishers do not write to `flatpak-index`.
- **Rollback:** Production rollback belongs to `tuna-os/docs` maintainers. If a release breaks the catalog, maintainers revert `static/flatpak/index/static` in `tuna-os/docs`. They then verify the live endpoint at `https://tunaos.org/flatpak/index/static`. Edits in `flatpak-index` do not change production.
- **Local snapshot status:** The root `tuna-os.flatpakrepo` file points to `oci+https://tunaos.org/flatpak`. Retirement of the local `index/static` snapshot proceeds under issue #173.
