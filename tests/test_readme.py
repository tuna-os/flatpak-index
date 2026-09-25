"""The README's "Available apps" table is what people copy install commands from.

A typo there fails at `flatpak install` time with "Nothing matches", on the
user's machine, with nothing in CI to notice. These tests hold the table to
the shape Flatpak itself accepts.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROW = re.compile(r"^\| (?P<app>[^|]+?) \| `flatpak install tuna-os (?P<id>[^`]+)` \|$")

# flatpak's own rule (common/flatpak-utils-base.c, flatpak_is_valid_name):
# at least three dot-separated elements, each starting with a letter or
# underscore and made of [A-Za-z0-9_-], 255 characters at most.
ELEMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def available_apps():
    text = (ROOT / "README.md").read_text()
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


class AvailableAppsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = available_apps()

    def test_table_is_not_empty(self):
        self.assertTrue(self.rows)

    def test_every_app_id_is_a_valid_flatpak_name(self):
        for app, app_id in self.rows:
            with self.subTest(app=app):
                self.assertLessEqual(len(app_id), 255)
                elements = app_id.split(".")
                self.assertGreaterEqual(len(elements), 3, app_id)
                for element in elements:
                    self.assertRegex(element, ELEMENT)

    def test_app_ids_are_unique(self):
        ids = [app_id for _, app_id in self.rows]
        self.assertEqual(len(ids), len(set(ids)))

    def test_compass_keeps_the_vicinae_compatible_id(self):
        # Compass publishes under the ID its manifest declares
        # (packaging/flatpak/com.vicinae.Vicinae.yaml in tuna-os/compass).
        # An org.tunaos.compass row would install nothing.
        self.assertIn(("Compass", "com.vicinae.Vicinae"), self.rows)


if __name__ == "__main__":
    unittest.main()
