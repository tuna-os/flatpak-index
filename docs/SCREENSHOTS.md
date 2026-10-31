# Automated screenshots

An app with no `<screenshots>` renders an empty frame in Bazaar, GNOME
Software and Discover. Screenshots are also the one part of AppStream metadata
that goes stale on its own: the app changes, the picture does not.

So CI generates them from the real app and references them from
`main`. Nobody takes them by hand.

## The shape

```
.github/workflows/screenshots.yml     runs on push to main
  │  builds the app, then for each screen:
  ▼
tuna-os/flatpak-index/.github/actions/capture-screenshots
  │  Xvfb + target readiness + ImageMagick
  ▼
docs/screenshots/NN-name.png          committed back to main
docs/screenshots/NN-name.receipt.json provenance and evidence
  │  referenced by
  ▼
data/<app-id>.metainfo.xml            <screenshot><image>raw.githubusercontent…/main/…
```

The workflow re-commits on every push to `main`, and the metainfo
points at `main`. The pictures in the software centre follow the app with no
further upkeep.

## Using the shared action

```yaml
- uses: tuna-os/flatpak-index/.github/actions/capture-screenshots@main
  id: capture
  with:
    command: ./target/release/myapp
    name: 01-main
    out-dir: docs/screenshots      # default
    geometry: 1000x700             # default, Flathub's maximum
    settle: "6"                    # seconds to let the window paint
    app-id: org.tunaos.myapp       # optional explicit application ID
    wm-class: MyApp                # optional explicit WM_CLASS
    readiness-predicate: ""        # optional command asserting target readiness
    deadline: "30"                 # optional monotonic deadline in seconds
    capture-mode: window           # "window" (default) or "display"
    required: "true"               # "true" (default) or "false" (advisory)
```

It drives a real X server and photographs the application's own window. It
is toolkit-agnostic: GTK, Qt, Electron and plain Xt apps all work, without an
in-process harness written per toolkit.

### Action outputs

The action provides step outputs for pipeline verification:

- `image`: Path to the captured PNG file.
- `receipt`: Path to the versioned JSON receipt file.
- `outcome`: Execution outcome (`passed`, `failed`, `blocked`, `not_run`, `unsupported`, `flaky`).
- `window-id`: Observed X11 window ID.
- `frame-hash`: SHA-256 digest of the captured frame.
- `target-pid`: Observed target process ID.

### Correctness contract

- **Target readiness and window identity**: Matches the window by host PID or descendants, explicit `app-id`, or explicit `wm-class`. Flatpak and sandboxed PID namespaces use explicit or inferred application identity. It rejects unrelated windows and does not capture empty or wrong-window surfaces.
- **Process liveness and late crash detection**: Detects exit before window mapping, enforces monotonic deadlines, and verifies app liveness and window integrity after paint settles.
- **Rejection of stale output and atomic publishing**: Pre-existing PNG files at the target path are deleted before capture. Fresh output is published atomically on verified success. Failed captures do not write or retain a success-shaped PNG or receipt.
- **Owned process cleanup**: Isolates temporary state in private directories and display numbers (:97 to :128). Terminates only owned processes and descendants. Unrelated processes stay untouched. Teardown failures are recorded in the receipt and verdict.
- **Versioned evidence receipt**: Writes a versioned JSON receipt (`schema_version: 1`) that records source and action revisions, run and attempt numbers, requested and observed identities, executable binary digest, environment details, frame hash, timing, diagnostics, and outcome.

An app that renders its own screens more precisely should keep that setup.
`tuna-installer-kde` renders each wizard step from the real QML module with
only `main.cpp` swapped. That beats a photo of a live window
because it can reach states a cold start cannot. Use the shared action when
there is no such harness.

## What to capture

Follow [Flathub's quality guidelines](https://docs.flathub.org/docs/for-app-authors/metainfo-guidelines/quality-guidelines):

- **3–6 screenshots** for a typical app; one is the bare minimum.
- **Window only**, no desktop background, default theme.
- **1000×700 maximum** (2000×1400 for HiDPI). The action defaults to 1000×700
  and fits the window to it.
- **Captions**: one sentence, no trailing period. Describe what the
  image shows, not the filename. Three captions from filenames were wrong;
  one described a language picker that does not exist.
- The first entry should be `type="default"`.

## Checking it

`enrich-index.py` reports any published app whose catalogue declares no
screenshots:

```bash
curl -sSfL -o served.json https://tunaos.org/flatpak/index/static
./scripts/enrich-index.py served.json --check
```

Screenshot-less apps come back as `~` warnings, not `!` problems: such
an app is installable and correctly described, but poorly presented. The daily
[`check-metadata.yml`](../.github/workflows/check-metadata.yml) run surfaces
them.
