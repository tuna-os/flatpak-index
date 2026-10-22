#!/usr/bin/env python3
"""Fail CI when the README's install commands drift from the served catalog.

The README's "Available apps" table is what people copy install commands from.
It lives in tuna-os/flatpak-index; the manifest the sanity and smoke checks are
built on -- the full list of apps the remote serves -- lives in tuna-os/docs at
static/flatpak/expected-apps.json. They are maintained by different people in
different repos, so they drift: the README can advertise a command that installs
nothing, or leave a served app invisible to everyone who reads it.

This compares the two so that divergence fails a build instead of surfacing on a
user's machine as "Nothing matches" or a missing app. It runs on push and pull
requests (.github/workflows/tests.yml) against the live manifest.

    ./scripts/check-readme-drift.py                 # compare README.md to the live manifest
    ./scripts/check-readme-drift.py README.md path  # compare a local README to the live manifest
    ./scripts/check-readme-drift.py README.md manifest.json  # compare both against local files
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

EXPECTED_APPS_URL = (
    "https://raw.githubusercontent.com/tuna-os/docs/main/"
    "static/flatpak/expected-apps.json"
)

# Same shape the README tests already parse: a table row whose install cell is a
# single `flatpak install tuna-os <id>` code span.
ROW = re.compile(r"^\| (?P<app>[^|]+?) \| `flatpak install tuna-os (?P<id>[^`]+)` \|$")


def readme_rows(text):
    """Return (display_name, flatpak_id) for every Available apps row."""
    section = text.split("## Available apps", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        if not line.startswith("|") or line.startswith(("| App ", "|---")):
            continue
        match = ROW.match(line)
        if match is None:
            raise AssertionError(f"malformed Available apps row: {line!r}")
        rows.append((match["app"], match["id"]))
    return rows


def served_ids(manifest):
    """Every flatpak ID the manifest says the remote serves."""
    ids = set()
    for app in manifest["apps"]:
        for app_id in app.get("ids", [app.get("id")]):
            if app_id:
                ids.add(app_id)
    return ids


def drift(readme_text, served_ids):
    """List every way the README diverges from the served set; empty when clean."""
    advertised = {app: app_id for app, app_id in readme_rows(readme_text)}
    advertised_ids = set(advertised.values())
    problems = [
        f"{app} advertises {app_id!r}, which the served catalog does not contain"
        for app, app_id in advertised.items()
        if app_id not in served_ids
    ]
    problems += [
        f"the served catalog contains {app_id!r}, but the README advertises it nowhere"
        for app_id in sorted(served_ids)
        if app_id not in advertised_ids
    ]
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check the README against the served catalog.")
    parser.add_argument("readme", nargs="?", default="README.md", help="README to check")
    parser.add_argument(
        "manifest",
        nargs="?",
        help="expected-apps.json to compare against (default: fetched from tuna-os/docs)",
    )
    args = parser.parse_args(argv)

    if args.manifest:
        manifest = json.loads(Path(args.manifest).read_text())
    else:
        manifest = json.loads(urllib.request.urlopen(EXPECTED_APPS_URL, timeout=30).read())

    served = served_ids(manifest)
    problems = drift(Path(args.readme).read_text(), served)
    if problems:
        print("README advertises a catalog that differs from the served one:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"OK: README advertises all {len(served)} served app(s) and nothing else")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
