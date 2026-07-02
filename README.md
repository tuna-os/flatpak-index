# TunaOS Flatpak Index

Add this remote to install TunaOS Flatpaks:

```bash
flatpak remote-add --if-not-exists tuna-os https://tunaos.org/flatpak/tuna-os.flatpakrepo
flatpak install tuna-os org.tunaos.mariner
```

The remote is served via Cloudflare Pages from the [tuna-os/docs](https://github.com/tuna-os/docs) repo at `https://tunaos.org/flatpak/`.

## Available apps

| App | Install |
|-----|---------|
| Tables | `flatpak install tuna-os io.github.hanthor.tables` |
| Tables (Rust) | `flatpak install tuna-os org.tunaos.tables-rust` |
| Decks | `flatpak install tuna-os io.github.hanthor.decks` |
| Decks (Rust) | `flatpak install tuna-os org.tunaos.decks-rust` |
| Letters | `flatpak install tuna-os net.codelogistics.letters` |
| Letters (Rust) | `flatpak install tuna-os org.tunaos.letters-rust` |
| Mariner | `flatpak install tuna-os org.tunaos.mariner` |

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
  contents: write
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
        run: |
          echo "${{ secrets.GITHUB_TOKEN }}" | skopeo login ghcr.io -u "${{ github.actor }}" --password-stdin
          skopeo copy oci:<app>.oci docker://ghcr.io/tuna-os/<app>:latest
      - name: Update central index (tuna-os/docs)
        env:
          FLATPAK_INDEX_TOKEN: ${{ secrets.FLATPAK_INDEX_TOKEN }}
        run: |
          git clone --depth 1 \
            https://x-access-token:${FLATPAK_INDEX_TOKEN}@github.com/tuna-os/docs.git \
            index-repo
          pip install requests
          python3 .github/scripts/update-index.py \
            --oci-dir <app>.oci \
            --index-file index-repo/static/flatpak/index/static \
            --repo-name tuna-os/<app> \
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

Also copy `.github/scripts/update-index.py` from an existing app (e.g. [tuna-os/mariner](https://github.com/tuna-os/mariner)).

### 4. Set repo secrets

- **`FLATPAK_INDEX_TOKEN`**: A GitHub PAT with push access to `tuna-os/docs`

```bash
gh secret set FLATPAK_INDEX_TOKEN --repo tuna-os/<app> --body "$(gh auth token)"
```

### 5. Push to trigger the build

```bash
git push origin main  # or master
```

The CI will:
1. Build the flatpak in the GNOME 50 container
2. Export it as an OCI image
3. Push to `ghcr.io/tuna-os/<app>:latest`
4. Update the central index in `tuna-os/docs/static/flatpak/index/static`
5. Cloudflare Pages redeploys `tunaos.org` with the new index

## Architecture

```
User
  │ flatpak remote-add https://tunaos.org/flatpak/tuna-os.flatpakrepo
  ▼
tunaos.org (Cloudflare Pages)
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

## Index format

The `index/static` file is a JSON array with OCI image references. Each entry maps an app name to its manifest digest and flatpak metadata labels. Flatpak downloads this index, finds the right image by app ID and architecture, then pulls it from the GHCR registry.
