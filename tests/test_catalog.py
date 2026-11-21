"""Production declaration parity and per-app architecture coverage."""

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.catalog import check_coverage, check_readme, main


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.declaration = {"apps": [{"name": "tuna-os/installers",
                                      "ids": ["org.example.One", "org.example.Two"],
                                      "archs": ["amd64", "arm64"]}]}
        self.index = {"Results": [{"Name": "tuna-os/installers", "Images": [
            {"Architecture": arch, "Labels": {"org.flatpak.ref": f"app/{app}/{refarch}/stable"}}
            for app in self.declaration["apps"][0]["ids"]
            for arch, refarch in [("amd64", "x86_64"), ("arm64", "aarch64")]
        ]}]}

    def test_multi_app_coverage(self):
        self.assertEqual(check_coverage(self.declaration, self.index), [])
        self.index["Results"][0]["Images"].pop()
        self.assertEqual(len(check_coverage(self.declaration, self.index)), 1)

    def test_unlisted_registry_even_empty_fails(self):
        self.index["Results"].append({"Name": "tuna-os/unknown", "Images": []})
        self.assertIn("undeclared registry", check_coverage(self.declaration, self.index)[0])

    def test_bad_refs_fail(self):
        for ref in ["app/org.example.one/x86_64/stable", "runtime/org.example.One/x86_64/stable",
                    "app/org.example.One/aarch64/stable", "", "app/org.example.One/x86_64/"]:
            with self.subTest(ref=ref):
                index = copy.deepcopy(self.index)
                index["Results"][0]["Images"][0]["Labels"]["org.flatpak.ref"] = ref
                self.assertTrue(check_coverage(self.declaration, index))

    def test_missing_registry_fails(self):
        self.assertEqual(len(check_coverage(self.declaration, {"Results": []})), 4)

    def test_readme_exact_parity(self):
        readme = "## Available apps\n" + "\n".join(
            f"| App | `flatpak install tuna-os {app}` |"
            for app in self.declaration["apps"][0]["ids"])
        self.assertEqual(check_readme(self.declaration, readme), [])
        for changed in [readme.replace("One", "one"), readme.splitlines()[0],
                        readme + "\n| Extra | `flatpak install tuna-os org.example.Extra` |",
                        readme + "\n| Again | `flatpak install tuna-os org.example.One` |"]:
            self.assertTrue(check_readme(self.declaration, changed))

    def test_invalid_or_duplicate_declarations_are_rejected(self):
        app = {"name": "tuna-os/one", "ids": ["org.example.One"], "archs": ["amd64"]}
        bad = {
            "duplicate name": [app, dict(app)],
            "empty ids": [{**app, "ids": []}],
            "empty archs": [{**app, "archs": []}],
        }
        for label, apps in bad.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    check_readme({"apps": apps}, "")
                with self.assertRaises(ValueError):
                    check_coverage({"apps": apps}, {"Results": []})


class CatalogCommandTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.declaration = self.tmp / "expected-apps.json"
        self.declaration.write_text(json.dumps({"apps": [
            {"name": "tuna-os/one", "ids": ["org.example.One"], "archs": ["amd64"]}]}))

    def run_main(self, *args):
        out = io.StringIO()
        with (mock.patch("sys.argv", ["catalog.py", str(self.declaration), *args]),
              contextlib.redirect_stdout(out)):
            return main(), out.getvalue()

    def test_requires_a_readme_or_an_index(self):
        with (self.assertRaises(SystemExit) as caught,
              contextlib.redirect_stderr(io.StringIO())):
            self.run_main()
        self.assertEqual(caught.exception.code, 2)

    def test_matching_readme_and_index_pass(self):
        readme = self.tmp / "README.md"
        readme.write_text("## Available apps\n| One | `flatpak install tuna-os org.example.One` |")
        index = self.tmp / "index.json"
        index.write_text(json.dumps({"Results": [{"Name": "tuna-os/one", "Images": [
            {"Architecture": "amd64",
             "Labels": {"org.flatpak.ref": "app/org.example.One/x86_64/stable"}}]}]}))
        failed, output = self.run_main("--readme", str(readme), "--index", str(index))
        self.assertFalse(failed)
        self.assertEqual(output, "")

    def test_a_missing_app_fails_and_is_reported(self):
        index = self.tmp / "index.json"
        index.write_text(json.dumps({"Results": []}))
        failed, output = self.run_main("--index", str(index))
        self.assertTrue(failed)
        self.assertIn("tuna-os/one", output)

    def test_a_readme_alone_is_enough_and_a_mismatch_fails(self):
        readme = self.tmp / "README.md"
        readme.write_text("## Available apps\n| One | `flatpak install tuna-os org.example.One` |")
        failed, output = self.run_main("--readme", str(readme))
        self.assertFalse(failed)
        self.assertEqual(output, "")
        readme.write_text("## Available apps\n")
        failed, output = self.run_main("--readme", str(readme))
        self.assertTrue(failed)
        self.assertIn("org.example.One", output)
