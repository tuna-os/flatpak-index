"""Check advertised apps and served coverage against the production declaration."""

import argparse
import json
import re
from pathlib import Path

ARCHES = {"amd64": "x86_64", "arm64": "aarch64"}


def declared_apps(declaration):
    apps = {}
    for app in declaration["apps"]:
        name = app["name"]
        ids = set(app["ids"] if "ids" in app else [app["id"]])
        if name in apps or not ids or not app["archs"]:
            raise ValueError(f"invalid or duplicate declaration: {name}")
        apps[name] = (ids, set(app["archs"]))
    return apps


def check_readme(declaration, readme):
    apps = declared_apps(declaration)
    expected = {app_id for ids, _ in apps.values() for app_id in ids}
    if "## Available apps\n" not in readme:
        return ["README missing Available apps section"]
    section = readme.split("## Available apps\n", 1)[1].split("\n## ", 1)[0]
    ids = re.findall(r"`flatpak install tuna-os ([^`]+)`", section)
    errors = []
    if len(ids) != len(set(ids)):
        errors.append("README contains duplicate app IDs")
    if set(ids) != expected:
        errors.append(f"README missing {sorted(expected - set(ids))}; "
                      f"extra {sorted(set(ids) - expected)}")
    return errors


def check_coverage(declaration, index):
    apps = declared_apps(declaration)
    seen = {name: set() for name in apps}
    errors = []
    for entry in index["Results"]:
        name = entry["Name"]
        if name not in apps:
            errors.append(f"undeclared registry entry: {name}")
            continue
        ids, _ = apps[name]
        for image in entry.get("Images", []):
            arch = image.get("Architecture")
            ref = image.get("Labels", {}).get("org.flatpak.ref", "").split("/")
            if (len(ref) != 4 or ref[0] != "app" or ref[1] not in ids
                    or ref[2] != ARCHES.get(arch, arch) or not ref[3]):
                errors.append(f"{name}: invalid or undeclared ref {'/'.join(ref)!r}")
                continue
            seen[name].add((ref[1], arch))
    for name, (ids, archs) in apps.items():
        for app_id in sorted(ids):
            for arch in sorted(archs):
                if (app_id, arch) not in seen[name]:
                    errors.append(f"{name}: missing {app_id} on {arch}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("declaration", type=Path)
    parser.add_argument("--readme", type=Path)
    parser.add_argument("--index", type=Path)
    args = parser.parse_args()
    if not args.readme and not args.index:
        parser.error("provide --readme and/or --index")
    declaration = json.loads(args.declaration.read_text())
    errors = []
    if args.readme:
        errors.extend(check_readme(declaration, args.readme.read_text()))
    if args.index:
        errors.extend(check_coverage(declaration, json.loads(args.index.read_text())))
    for error in errors:
        print(error)
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
