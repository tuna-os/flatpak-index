#!/usr/bin/env python3
"""Check advertised installs against docs' coverage manifest and optionally a served index."""

import argparse
import json
import re
from pathlib import Path


def check_coverage(readme, manifest, index=None):
    expected = {
        app_id
        for app in manifest['apps']
        for app_id in app.get('ids', [app.get('id')])
    }
    table = readme.split('## Available apps\n', 1)[1].split('\n---', 1)[0]
    advertised = re.findall(r'`flatpak install tuna-os ([\w.]+)`', table)
    errors = []
    if len(advertised) != len(set(advertised)):
        errors.append('README contains duplicate app installs')
    for label, ids in [('missing from README', expected - set(advertised)),
                       ('not in coverage manifest', set(advertised) - expected)]:
        if ids:
            errors.append(f'{label}: {", ".join(sorted(ids))}')
    if index is not None:
        served = {
            ref.split('/')[1]
            for result in index['Results']
            for image in result.get('Images', [])
            if (ref := image.get('Labels', {}).get('org.flatpak.ref', '')).startswith('app/')
        }
        for label, ids in [('served but not covered', served - expected),
                           ('covered but not served', expected - served)]:
            if ids:
                errors.append(f'{label}: {", ".join(sorted(ids))}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--readme', type=Path, default=Path('README.md'))
    parser.add_argument('--index', type=Path)
    args = parser.parse_args()
    errors = check_coverage(
        args.readme.read_text(), json.loads(args.manifest.read_text()),
        json.loads(args.index.read_text()) if args.index else None,
    )
    for error in errors:
        print(error)
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
