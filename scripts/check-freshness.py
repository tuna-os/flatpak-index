#!/usr/bin/env python3
"""Check the served Flatpak index against the live registry.

This is the production freshness and install check. It reads an index that was
fetched from the served remote and answers two questions about every entry:

* **Installable** -- does the registry still serve the tag the index recorded,
  and does that entry carry the AppStream metadata software centres need?
* **Fresh** -- has a newer publish moved the tag past the digest the index
  recorded? If the registry now serves a different digest for the tag, the
  served index lags production.

    curl -sSfL -o served-index.json https://tunaos.org/flatpak/index/static
    ./scripts/check-freshness.py served-index.json --check

The network is reached through ``scripts/oci.py``. The classification in
``evaluate`` takes an injected resolver so it can be unit-tested offline.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oci import Registry, RegistryError  # noqa: E402

APPDATA_LABEL = "org.freedesktop.appstream.appdata"
ICON_64_LABEL = "org.freedesktop.appstream.icon-64"
ICON_128_LABEL = "org.freedesktop.appstream.icon-128"
REQUIRED_APPSTREAM = (APPDATA_LABEL, ICON_64_LABEL, ICON_128_LABEL)


@dataclass(frozen=True)
class EntryResult:
    """The verdict for one served entry (one app + architecture)."""

    label: str
    served_digest: str
    current_digest: str | None
    stale: bool
    uninstallable: bool
    missing_metadata: bool


def evaluate(index_data, resolver, require_appstream=True):
    """Classify every served entry against the registry.

    ``resolver`` maps ``(repository, tag)`` to the digest the registry currently
    assigns to that tag, or ``None`` if the tag no longer resolves. Injecting it
    keeps this function pure and unit-testable without the network.
    """
    results = []
    for result in index_data.get("Results", []):
        repository = result["Name"]
        for image in result.get("Images", []):
            digest = image["Digest"]
            architecture = image.get("Architecture", "?")
            labels = image.get("Labels") or {}
            tags = image.get("Tags") or ()
            label = f"{repository} ({architecture})"

            current_digest = None
            stale = False
            uninstallable = False
            for tag in tags:
                resolved = resolver(repository, tag, architecture)
                if resolved is None:
                    uninstallable = True
                    break
                current_digest = resolved
                if resolved != digest:
                    stale = True

            missing_metadata = False
            if require_appstream:
                missing = [name for name in REQUIRED_APPSTREAM if name not in labels]
                if missing:
                    missing_metadata = True

            results.append(
                EntryResult(
                    label=label,
                    served_digest=digest,
                    current_digest=current_digest,
                    stale=stale,
                    uninstallable=uninstallable,
                    missing_metadata=missing_metadata,
                )
            )
    return results


def summarize(results):
    """Split results into the three problem lists, in index order."""
    stale = [r for r in results if r.stale]
    uninstallable = [r for r in results if r.uninstallable]
    missing_metadata = [r for r in results if r.missing_metadata]
    return stale, uninstallable, missing_metadata


def _short_digest(digest):
    """``sha256:abcd...`` -> ``abcd..efgh`` so a mismatch fits on one line."""
    if not digest:
        return "(unresolved)"
    payload = digest.split(":", 1)[1] if ":" in digest else digest
    return f"{payload[:8]}…{payload[-4:]}" if len(payload) > 12 else payload


def _registry_resolver(registry_url, token=None):
    """Build a ``(repository, tag, architecture) -> current digest`` resolver over GHCR."""
    registry = Registry(registry_url, token=token)

    def resolve(repository, tag, architecture):
        try:
            return registry.reference_digest(repository, tag, architecture)
        except RegistryError:
            # A tag that no longer resolves means the served entry cannot be
            # installed; report it rather than aborting the whole check.
            return None

    return resolve



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index_file", type=Path, help="Path to a served index/static file")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report what is wrong and exit non-zero, without doing anything else",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("REGISTRY_TOKEN"),
        help="Bearer token for private packages (default: $REGISTRY_TOKEN)",
    )
    args = parser.parse_args()

    index_data = json.loads(args.index_file.read_text())
    resolver = _registry_resolver(index_data["Registry"], token=args.token)
    results = evaluate(index_data, resolver)
    stale, uninstallable, missing_metadata = summarize(results)

    for entry in stale:
        print(
            f"  ! {entry.label}: stale -- served {_short_digest(entry.served_digest)}, "
            f"registry now {_short_digest(entry.current_digest)}"
        )
    for entry in uninstallable:
        print(f"  ! {entry.label}: not installable -- registry no longer serves its tag")
    for entry in missing_metadata:
        print(f"  ~ {entry.label}: missing AppStream metadata in the served index")

    if args.check:
        print(
            f"\n{len(results)} entry(ies) checked. "
            f"{len(stale)} stale, {len(uninstallable)} not installable, "
            f"{len(missing_metadata)} missing metadata."
        )
        if stale or uninstallable or missing_metadata:
            return 1
        print("Served index is fresh and installable.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
