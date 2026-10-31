"""Exercise the versioned action runner against the OCI/index contract."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_update_index import APPSTREAM_LABELS, FLATPAK_LABELS, write_oci_layout

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / '.github/actions/update-flatpak-index/run.sh'


class PublisherActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.oci = self.workspace / 'app layout'
        self.index = self.workspace / 'index checkout' / 'static'
        self.labels = {**FLATPAK_LABELS, **APPSTREAM_LABELS}
        self.digest = write_oci_layout(self.oci, self.labels)

    def run_action(self, **inputs):
        env = dict(os.environ, OCI_DIR=str(self.oci), INDEX_FILE=str(self.index),
                   REPO_NAME='tuna-os/example', REGISTRY='ghcr.io',
                   TAGS='latest stable', REQUIRE_APPSTREAM='true')
        env.update(inputs)
        # An unrelated caller checkout proves the runner uses its own release.
        return subprocess.run(['bash', str(RUNNER)], cwd=self.workspace, env=env,
                              text=True, capture_output=True)

    def test_output_contract_and_repeat_publish(self):
        self.index.parent.mkdir()
        other = {'Name': 'tuna-os/other', 'Images': []}
        self.index.write_text(json.dumps({'Registry': 'https://ghcr.io',
                                         'Results': [other]}))
        result = self.run_action()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(self.index.read_text())
        self.assertEqual(output, {
            'Registry': 'https://ghcr.io',
            'Results': [
                {'Name': 'tuna-os/example', 'Images': [{
                    'Digest': self.digest,
                    'MediaType': 'application/vnd.oci.image.manifest.v1+json',
                    'OS': 'linux', 'Architecture': 'amd64',
                    'Tags': ['latest', 'stable'], 'Labels': self.labels,
                }]}, other,
            ],
        })
        original = self.index.read_bytes()
        result = self.run_action()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.index.read_bytes(), original)

    def test_appstream_failure_preserves_index(self):
        write_oci_layout(self.oci, FLATPAK_LABELS)
        self.index.parent.mkdir()
        original = '{"Registry":"https://ghcr.io","Results":[]}'
        self.index.write_text(original)
        result = self.run_action()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No AppStream metadata', result.stderr)
        self.assertEqual(self.index.read_text(), original)

    def test_optional_appstream_and_new_registry(self):
        write_oci_layout(self.oci, FLATPAK_LABELS)
        result = self.run_action(REQUIRE_APPSTREAM='false', REGISTRY='example.org')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.index.read_text())['Registry'],
                         'https://example.org')

    def test_invalid_inputs_fail_without_writing(self):
        for inputs in ({'REQUIRE_APPSTREAM': 'yes'}, {'TAGS': '  '}):
            with self.subTest(inputs=inputs):
                result = self.run_action(**inputs)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.index.exists())

    def test_input_is_passed_as_data(self):
        name = 'tuna-os/$(touch should-not-exist)'
        result = self.run_action(REPO_NAME=name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.workspace / 'should-not-exist').exists())
        self.assertEqual(json.loads(self.index.read_text())['Results'][0]['Name'], name)
