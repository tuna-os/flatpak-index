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

    ./scripts/enrich-index.py served-index.json
    ./scripts/enrich-index.py served-index.json --check     # CI: report, change nothing
"""

import argparse
import contextlib
import json
import os
import re
import sys
import tempfile
import xml.parsers.expat as expat
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oci import APPSTREAM_LABELS, Registry, RegistryError, filter_labels  # noqa: E402

APPDATA_LABEL = "org.freedesktop.appstream.appdata"
# Producer: tuna-os/docs scripts/prepare-flatpak-icons.mjs, run by package.json prebuild.
# https://github.com/tuna-os/docs/blob/1cdc86a3f03e406a95d6886b207dc09a11ae7ad2/scripts/prepare-flatpak-icons.mjs#L45-L53
# Keep this exact-format exception narrow so other AppStream drift is still reported.
SITE_ICON = re.compile(
    r'    <icon type="remote" width="128" height="128">'
    r'https://tunaos\.org/flatpak/icons/[A-Za-z0-9._-]+\.png</icon>\n'
)


def without_site_icon(appdata):
    """Remove only the docs build's remote icon extension for comparison."""
    return SITE_ICON.sub("", appdata)


class ForbiddenDTD(ElementTree.ParseError):
    """An AppStream catalogue declared a DOCTYPE.

    A DOCTYPE enables XML-external-entity and entity-expansion ("billion
    laughs") attacks; AppStream catalogues never declare one, so its presence
    is treated as unparseable.
    """


def _reject_dtd(*_args):
    raise ForbiddenDTD("DOCTYPE not permitted in AppStream catalogue")


def _parse_appdata(appdata):
    """Parse AppStream XML, rejecting any DOCTYPE (XXE / entity-expansion bomb).

    Routes the raw expat parser into ElementTree's tree builder so the DOCTYPE
    and external-entity handlers fire before any entity can expand. stdlib only:
    ElementTree.XMLParser does not expose doctype handling.
    """
    builder = ElementTree.XMLParser().target
    parser = expat.ParserCreate()
    parser.StartElementHandler = builder.start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    parser.StartDoctypeDeclHandler = _reject_dtd
    parser.EndDoctypeDeclHandler = _reject_dtd
    parser.ExternalEntityRefHandler = _reject_dtd
    parser.Parse(appdata, True)
    return builder.close()


def screenshot_count(appdata):
    """Number of <screenshot> entries in an AppStream catalogue, or None.

    None means the catalogue could not be parsed -- including a DOCTYPE-bearing,
    i.e. potentially malicious catalogue -- which is a different problem from an
    app that simply ships no screenshots.
    """
    try:
        root = _parse_appdata(appdata)
    except (ElementTree.ParseError, expat.ExpatError):
        return None
    return len(root.findall(".//screenshot"))


def enrich(index_data, registry, verbose=True, registry_errors=None):
    """Merge registry labels into every image entry.

    Returns (updated, problems, warnings). Problems are things that make an
    entry wrong; warnings are things that make it look bad. When ``registry_errors``
    is a list, each registry read failure is appended to it so the caller can
    refuse to write a partially reconciled index.
    """
    updated = 0
    problems = []
    warnings = []

    for result in index_data.get("Results", []):
        repository = result["Name"]
        for image in result.get("Images", []):
            digest = image["Digest"]
            label = f"{repository} ({image.get('Architecture', '?')})"
            try:
                registry_labels = filter_labels(registry.image_labels(repository, digest))
            except RegistryError as error:
                message = f"{label}: could not read labels -- {error}"
                problems.append(message)
                if registry_errors is not None:
                    registry_errors.append(message)
                continue

            missing = [name for name in APPSTREAM_LABELS if name not in registry_labels]
            if missing:
                problems.append(
                    f"{label}: image has no AppStream metadata "
                    f"({', '.join(missing)}); it needs a metainfo file"
                )
            else:
                # Metadata alone still leaves an empty frame in a software
                # centre. Report it as a warning rather than a hard problem:
                # a screenshot-less app is installable and correctly described,
                # just poorly presented.
                shots = screenshot_count(registry_labels[APPDATA_LABEL])
                if shots is None:
                    problems.append(f"{label}: AppStream catalogue does not parse")
                elif shots == 0:
                    warnings.append(
                        f"{label}: no <screenshots> declared; software centres "
                        f"will show an empty frame. See docs/SCREENSHOTS.md"
                    )

            merged = dict(image.get("Labels") or {})
            merged.update(registry_labels)
            existing_appdata = image.get("Labels", {}).get(APPDATA_LABEL)
            registry_appdata = registry_labels.get(APPDATA_LABEL)
            if (
                existing_appdata is not None
                and registry_appdata is not None
                and without_site_icon(existing_appdata) == registry_appdata
            ):
                merged[APPDATA_LABEL] = existing_appdata
            if merged != image.get("Labels"):
                added = sorted(set(merged) - set(image.get("Labels") or {}))
                image["Labels"] = merged
                updated += 1
                if verbose:
                    print(f"  + {label}: added {', '.join(added)}")
            elif verbose:
                print(f"  = {label}: already complete")

    return updated, problems, warnings


def write_index_atomic(path, data):
    """Serialize ``data`` to ``path`` atomically via a temp file + ``os.replace``.

    ``os.replace`` is atomic on POSIX, so a concurrent reader sees either the old
    complete index or the new one, never a half-written file. The temp file is
    created in the same directory so ``os.replace`` stays on one filesystem, and
    its mode is matched to the destination so the index keeps its permissions.
    """
    payload = json.dumps(data, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(payload)
        with contextlib.suppress(FileNotFoundError):
            os.chmod(tmp_name, os.stat(path).st_mode)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


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
    registry_errors = []
    updated, problems, warnings = enrich(index_data, registry, registry_errors=registry_errors)

    for warning in warnings:
        print(f"  ~ {warning}", file=sys.stderr)
    for problem in problems:
        print(f"  ! {problem}", file=sys.stderr)

    if args.check:
        if updated:
            print(f"\n{updated} image(s) are missing labels present in the registry.")
        if updated or problems:
            return 1
        print("\nIndex is up to date with the registry.")
        return 0

    if registry_errors:
        print(
            f"\nSkipped write: {len(registry_errors)} registry error(s) left "
            f"reconciliation incomplete. Re-run once they clear so the whole "
            f"index updates atomically."
        )
    elif updated:
        write_index_atomic(args.index_file, index_data)
        print(f"\nWrote {args.index_file}: {updated} image(s) updated.")
    else:
        print("\nNothing to do.")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
