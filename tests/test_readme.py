"""The README's "Available apps" table is what people copy install commands from.

A typo there fails at `flatpak install` time with "Nothing matches", on the
user's machine, with nothing in CI to notice. These tests hold the table to
the shape Flatpak itself accepts.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT / "scripts"))
from readme_apps import available_apps, completeness_errors, served_app_ids  # noqa: E402

# flatpak's own rule (common/flatpak-utils-base.c, flatpak_is_valid_name):
# at least three dot-separated elements, each starting with a letter or
# underscore and made of [A-Za-z0-9_-], 255 characters at most.
ELEMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


class AvailableAppsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = available_apps((ROOT / "README.md").read_text())

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

    def test_compass_uses_its_own_id(self):
        # Compass publishes under the ID its manifest declares
        # (packaging/flatpak/org.tunaos.compass.yaml in tuna-os/compass).
        # The old com.vicinae.Vicinae row would install nothing.
        self.assertIn(("Compass", "org.tunaos.compass"), self.rows)
        self.assertNotIn("com.vicinae.Vicinae", [app_id for _, app_id in self.rows])


class CompletenessTests(unittest.TestCase):
    @staticmethod
    def index(*refs):
        return {"Results": [{"Images": [{"Labels": {"org.flatpak.ref": ref}} for ref in refs]}]}

    def test_collects_each_app_across_architectures_and_shared_registry_names(self):
        index = self.index(
            "app/org.example.One/x86_64/stable",
            "app/org.example.One/aarch64/stable",
            "app/org.example.Two/x86_64/stable",
            "runtime/org.example.Platform/x86_64/stable",
        )
        rows = [("One", "org.example.One"), ("Two", "org.example.Two")]
        self.assertEqual(served_app_ids(index), {app_id for _, app_id in rows})
        self.assertEqual(completeness_errors(rows, index), [])

    def test_reports_both_missing_and_stale_ids_case_sensitively(self):
        errors = completeness_errors(
            [("App", "org.example.App")], self.index("app/org.example.app/x86_64/stable")
        )
        self.assertEqual(errors, [
            "Served but missing from README: org.example.app",
            "Listed in README but not served: org.example.App",
        ])

    def test_empty_or_malformed_index_fails_closed(self):
        for index in ({}, {"Results": []}, self.index("app/broken"),
                      {"Results": [{"Images": [{"Labels": {}}]}]}):
            with self.subTest(index=index), self.assertRaises((KeyError, ValueError)):
                served_app_ids(index)

    def test_empty_or_malformed_table_fails_closed(self):
        for text in ("## Available apps\n", "## Available apps\n| broken |"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                available_apps(text)


if __name__ == "__main__":
    unittest.main()
