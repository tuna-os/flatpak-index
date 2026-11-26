"""Pin the update-flatpak-index composite action to the canonical script.

The action must run scripts/update-index.py in this repository, not a copy,
so there is one implementation (tuna-os/flatpak-index#45).
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github" / "actions" / "update-flatpak-index" / "action.yml"


class PublisherActionTests(unittest.TestCase):
    def setUp(self):
        self.text = ACTION.read_text()

    def test_runs_canonical_script(self):
        match = re.search(r'script="\$ACTION_PATH/((?:\.\./)+)scripts/update-index\.py"', self.text)
        self.assertIsNotNone(match)
        target = (ACTION.parent / match.group(1) / "scripts" / "update-index.py").resolve()
        self.assertEqual(target, ROOT / "scripts" / "update-index.py")

    def test_inputs_not_interpolated_into_shell(self):
        run_block = self.text.split("run: |", 1)[1]
        self.assertNotIn("${{", run_block)

    def test_flags_exist_in_script(self):
        script = (ROOT / "scripts" / "update-index.py").read_text()
        flags = (
            "--oci-dir", "--index-file", "--repo-name",
            "--registry", "--tags", "--require-appstream",
        )
        for flag in flags:
            self.assertIn(flag, script)
            self.assertIn(flag, self.text)


if __name__ == "__main__":
    unittest.main()
