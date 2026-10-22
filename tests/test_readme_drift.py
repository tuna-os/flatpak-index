"""Offline tests for scripts/check-readme-drift.py.

The live README-vs-served-catalog comparison runs in CI
(.github/workflows/tests.yml) against the manifest in tuna-os/docs. These tests
hold the comparison logic and the CLI contract to their shape without needing
network access.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "check_readme_drift", ROOT / "scripts" / "check-readme-drift.py"
)
check_readme_drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_readme_drift)

# A served set and two READMEs: one clean, one that drifts by advertising a
# wrong-cased id (org.tunaos.BlueShell instead of the served org.tunaos.blueshell)
# and omitting a served app (org.tunaos.Quickcast).
SERVED = {"org.tunaos.letters", "org.tunaos.blueshell", "org.tunaos.Quickcast"}

CLEAN_README = """\
## Available apps

| App | Install |
|-----|---------|
| Letters | `flatpak install tuna-os org.tunaos.letters` |
| BlueShell | `flatpak install tuna-os org.tunaos.blueshell` |
| Quickcast | `flatpak install tuna-os org.tunaos.Quickcast` |
"""

DRIFT_README = """\
## Available apps

| App | Install |
|-----|---------|
| Letters | `flatpak install tuna-os org.tunaos.letters` |
| BlueShell | `flatpak install tuna-os org.tunaos.BlueShell` |
"""


def manifest_for(ids):
    """An expected-apps.json-shaped manifest whose served set is ``ids``."""
    return {"apps": [{"name": "tuna-os/x", "ids": sorted(ids)}]}


class DriftLogicTests(unittest.TestCase):
    def test_clean_readme_reports_no_drift(self):
        self.assertEqual(check_readme_drift.drift(CLEAN_README, SERVED), [])

    def test_wrong_casing_is_reported(self):
        problems = check_readme_drift.drift(DRIFT_README, SERVED)
        self.assertTrue(any("org.tunaos.BlueShell" in p for p in problems))

    def test_omitted_app_is_reported(self):
        problems = check_readme_drift.drift(DRIFT_README, SERVED)
        self.assertTrue(any("org.tunaos.Quickcast" in p for p in problems))

    def test_served_ids_collects_a_list_and_skips_none(self):
        manifest = {"apps": [{"name": "tuna-os/bootc", "ids": ["a", "b", None]}]}
        self.assertEqual(check_readme_drift.served_ids(manifest), {"a", "b"})


class CliTests(unittest.TestCase):
    def _write(self, text, suffix):
        handle = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False)
        handle.write(text)
        handle.close()
        return Path(handle.name)

    def test_cli_returns_zero_when_clean(self):
        readme = self._write(CLEAN_README, ".md")
        manifest = self._write(json.dumps(manifest_for(SERVED)), ".json")
        try:
            self.assertEqual(check_readme_drift.main([str(readme), str(manifest)]), 0)
        finally:
            readme.unlink()
            manifest.unlink()

    def test_cli_returns_one_on_drift(self):
        readme = self._write(DRIFT_README, ".md")
        manifest = self._write(json.dumps(manifest_for({"org.tunaos.letters"})), ".json")
        try:
            self.assertEqual(check_readme_drift.main([str(readme), str(manifest)]), 1)
        finally:
            readme.unlink()
            manifest.unlink()


if __name__ == "__main__":
    unittest.main()
