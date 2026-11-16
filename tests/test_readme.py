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

    def test_compass_uses_its_own_id(self):
        # Compass publishes under the ID its manifest declares
        # (packaging/flatpak/org.tunaos.compass.yaml in tuna-os/compass).
        # The old com.vicinae.Vicinae row would install nothing.
        self.assertIn(("Compass", "org.tunaos.compass"), self.rows)
        self.assertNotIn("com.vicinae.Vicinae", [app_id for _, app_id in self.rows])


def publish_template():
    text = (ROOT / "README.md").read_text()
    after = text.split("Create `.github/workflows/publish-flatpak.yml`:", 1)[1]
    return after.split("```yaml\n", 1)[1].split("\n```", 1)[0]


class PublishTemplateTests(unittest.TestCase):
    """New app repositories copy this workflow, and zizmor does not read Markdown.

    The build job runs the app's whole build in a privileged container, so it
    must not hold a token that can push to the registry.
    """

    @classmethod
    def setUpClass(cls):
        cls.template = publish_template()
        cls.build, cls.publish = cls.template.split("\n  publish:\n", 1)

    def test_only_the_publish_job_can_write_packages(self):
        self.assertNotIn("write", self.build)
        self.assertEqual(self.publish.count("packages: write"), 1)

    def test_checkouts_keep_no_token_unless_they_push(self):
        steps = re.split(r"\n      - ", self.template)
        checkouts = [step for step in steps if "uses: actions/checkout@" in step]
        self.assertTrue(checkouts)
        for step in checkouts:
            if "token:" not in step:
                self.assertIn("persist-credentials: false", step)

    def test_run_steps_expand_no_expressions(self):
        for step in re.split(r"\n      - ", self.template):
            if "run: |" in step:
                self.assertNotIn("${{", step.split("run: |", 1)[1])


if __name__ == "__main__":
    unittest.main()
