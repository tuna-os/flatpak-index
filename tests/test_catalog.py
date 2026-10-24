"""Production declaration parity and per-app architecture coverage."""

import copy
import unittest

from scripts.catalog import check_coverage, check_readme


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
