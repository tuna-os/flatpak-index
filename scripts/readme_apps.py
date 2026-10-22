"""Compare the README app table with a downloaded production OCI index."""

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROW = re.compile(r"^\| (?P<app>[^|]+?) \| `flatpak install tuna-os (?P<id>[^`]+)` \|$")


def available_apps(text):
    section = text.split("## Available apps", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        if not line.startswith("|") or line.startswith(("| App ", "|---")):
            continue
        match = ROW.match(line)
        if match is None:
            raise ValueError(f"malformed Available apps row: {line!r}")
        rows.append((match["app"], match["id"]))
    if not rows:
        raise ValueError("Available apps table is empty")
    return rows


def served_app_ids(index):
    ids = set()
    for result in index["Results"]:
        for image in result["Images"]:
            ref = image["Labels"]["org.flatpak.ref"]
            parts = ref.split("/")
            if len(parts) != 4 or not all(parts):
                raise ValueError(f"malformed Flatpak ref: {ref!r}")
            if parts[0] == "app":
                ids.add(parts[1])
            elif parts[0] != "runtime":
                raise ValueError(f"unknown Flatpak ref kind: {ref!r}")
    if not ids:
        raise ValueError("served index contains no apps")
    return ids


def completeness_errors(rows, index):
    documented = {app_id for _, app_id in rows}
    served = served_app_ids(index)
    errors = []
    if missing := served - documented:
        errors.append("Served but missing from README: " + ", ".join(sorted(missing)))
    if stale := documented - served:
        errors.append("Listed in README but not served: " + ", ".join(sorted(stale)))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", type=Path, help="downloaded served index JSON")
    parser.add_argument("--readme", type=Path, default=ROOT / "README.md")
    args = parser.parse_args()
    try:
        errors = completeness_errors(
            available_apps(args.readme.read_text()), json.loads(args.index.read_text())
        )
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        parser.exit(1, f"Cannot compare README and served index: {exc}\n")
    if errors:
        parser.exit(1, "\n".join(errors) + "\n")
    print("README app IDs match the served index.")


if __name__ == "__main__":
    main()
