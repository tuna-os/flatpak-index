"""Catalog drift must fail even when every advertised app still exists."""

import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    'app_coverage', Path(__file__).resolve().parents[1] / 'scripts/check-app-coverage.py'
)
coverage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coverage)


class CoverageTests(unittest.TestCase):
    def test_manifest_and_served_ids(self):
        manifest = {'apps': [{'id': 'a'}, {'ids': ['b', 'c']}]}
        readme = '## Available apps\n' + '\n'.join(
            f'| App | `flatpak install tuna-os {app_id}` |' for app_id in ['a', 'b', 'c']
        )
        index = {'Results': [{'Images': [
            {'Labels': {'org.flatpak.ref': f'app/{app_id}/x86_64/master'}}
            for app_id in ['a', 'b', 'c']
        ]}]}
        self.assertEqual(coverage.check_coverage(readme, manifest, index), [])
        self.assertTrue(coverage.check_coverage(readme.replace('tuna-os c', 'tuna-os old'),
                                              manifest, index))
        index['Results'][0]['Images'].append(
            {'Labels': {'org.flatpak.ref': 'app/new/aarch64/master'}}
        )
        self.assertIn('served but not covered: new',
                      coverage.check_coverage(readme, manifest, index))
