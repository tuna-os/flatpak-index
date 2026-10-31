"""The check-metadata workflow must stay an *owned* monitor, not a silent one.

It runs on a schedule against the live served index, so a failure used to die
in the Actions UI with no one told. This pins the fix that in: the workflow
grants the `issues: write` permission it needs and adds a failure step that
files (or comments on) a GitHub issue, so a broken index is never undetected.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "check-metadata.yml"


class CheckMetadataWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text()

    def test_grants_issues_write_permission(self):
        # `contents: read` alone cannot file an issue; the routing fix needs write.
        self.assertIn("issues: write", self.text)

    def test_has_a_failure_step(self):
        # The escalation must only fire when the check itself fails.
        self.assertIn("if: failure()", self.text)

    def test_failure_step_files_an_issue(self):
        step = self.text.split("File an issue when the served index fails validation", 1)[1]
        # Files via the GitHub API (official action, no custom dependency).
        self.assertIn("actions/github-script", step)
        # Creates an issue and, to avoid daily duplicates, comments on an
        # existing open one with the same title.
        self.assertIn("issues.create", step)
        self.assertIn("issues.createComment", step)

    def test_failure_step_is_guarded_by_failure(self):
        # The issue-filing must sit under the failure() guard, not run every
        # successful check.
        step = self.text.split("File an issue when the served index fails validation", 1)[1]
        self.assertLess(step.index("if: failure()"), step.index("actions/github-script"))

    def test_still_runs_on_schedule(self):
        # It is a monitoring check against the live index, not a push gate.
        schedule = self.text.split("on:", 1)[1].split("permissions:", 1)[0]
        self.assertIn("schedule:", schedule)
        self.assertIn("cron:", schedule)


if __name__ == "__main__":
    unittest.main()
