"""Keep copyable workflow examples pinned to immutable commits."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WorkflowExampleTests(unittest.TestCase):
    def test_remote_actions_use_full_commit_shas(self):
        for name in ("README.md", "docs/SCREENSHOTS.md"):
            with self.subTest(document=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                references = re.findall(r"^\s*(?:-\s*)?uses:\s*(\S+)", text, re.MULTILINE)
                self.assertTrue(references, f"No action examples found in {name}")
                for reference in references:
                    self.assertRegex(
                        reference,
                        r"^[^@\s]+@[0-9a-f]{40}$",
                        f"{name} contains an unpinned action: {reference}",
                    )


if __name__ == "__main__":
    unittest.main()
