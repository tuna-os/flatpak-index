#!/usr/bin/env python3
"""Restore missing labels on an existing Flatpak OCI index.

Indexes published before the AppStream passthrough fix list the right images
but only carry their ``org.flatpak.*`` labels: the publisher filtered
``org.freedesktop.appstream.*`` out. The metadata is still on the images in
the registry, so it can be read back and written into the index without
rebuilding or republishing anything.

This only ever re-reads the digests already named in the index, so the set of
published images -- and every digest in it -- is unchanged. Only the Labels
maps grow.

    ./scripts/enrich-index.py index/static
    ./scripts/enrich-index.py index/static --check     # CI: report, change nothing
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oci import APPSTREAM_LABELS, Registry, RegistryError, filter_labels  # noqa: E402


def enrich(index_data, registry, verbose=True):
    """Merge registry labels into every image entry. Returns (updated, problems)."""
    updated = 0
    problems = []

    for result in index_data.get("Results", []):
        repository = result["Name"]
        for image in result.get("Images", []):
            digest = image["Digest"]
            label = f"{repository} ({image.get('Architecture', '?')})"
            try:
                registry_labels = filter_labels(registry.image_labels(repository, digest))
            except RegistryError as error:
                problems.append(f"{label}: could not read labels -- {error}")
                continue

            missing = [name for name in APPSTREAM_LABELS if name not in registry_labels]
            if missing:
                problems.append(
                    f"{label}: image has no AppStream metadata "
                    f"({', '.join(missing)}); it needs a metainfo file"
                )

            merged = dict(image.get("Labels") or {})
            merged.update(registry_labels)
            if merged != image.get("Labels"):
                added = sorted(set(merged) - set(image.get("Labels") or {}))
                image["Labels"] = merged
                updated += 1
                if verbose:
                    print(f"  + {label}: added {', '.join(added)}")
            elif verbose:
                print(f"  = {label}: already complete")

    return updated, problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index_file", type=Path, help="Path to the index/static file")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report what would change and exit non-zero, without writing",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("REGISTRY_TOKEN"),
        help="Bearer token for private packages (default: $REGISTRY_TOKEN)",
    )
    args = parser.parse_args()

    index_data = json.loads(args.index_file.read_text())
    registry = Registry(index_data["Registry"], token=args.token)

    print(f"Reading labels from {index_data['Registry']}")
    updated, problems = enrich(index_data, registry)

    for problem in problems:
        print(f"  ! {problem}", file=sys.stderr)

    if args.check:
        if updated:
            print(f"\n{updated} image(s) are missing labels present in the registry.")
        if updated or problems:
            return 1
        print("\nIndex is up to date with the registry.")
        return 0

    if updated:
        args.index_file.write_text(json.dumps(index_data, indent=2) + "\n")
        print(f"\nWrote {args.index_file}: {updated} image(s) updated.")
    else:
        print("\nNothing to do.")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
