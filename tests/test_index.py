import configparser
import json
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
REQUIRED_LABELS = {
    "org.flatpak.metadata",
    "org.flatpak.ref",
    "org.flatpak.commit",
    "org.flatpak.timestamp",
}


class IndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads((ROOT / "index/static").read_text())

    def test_registry_is_https(self):
        registry = urlparse(self.index["Registry"])
        self.assertEqual(registry.scheme, "https")
        self.assertTrue(registry.netloc)

    def test_results_are_nonempty_and_names_are_unique(self):
        results = self.index["Results"]
        self.assertTrue(results)
        names = [result["Name"] for result in results]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(name.startswith("tuna-os/") for name in names))

    def test_images_have_valid_oci_and_flatpak_metadata(self):
        for result in self.index["Results"]:
            with self.subTest(name=result["Name"]):
                self.assertTrue(result["Images"])
                architectures = []
                for image in result["Images"]:
                    architectures.append(image["Architecture"])
                    self.assertRegex(image["Digest"], DIGEST)
                    self.assertEqual(image["MediaType"], "application/vnd.oci.image.manifest.v1+json")
                    self.assertEqual(image["OS"], "linux")
                    self.assertIn("latest", image["Tags"])
                    self.assertLessEqual(REQUIRED_LABELS, image["Labels"].keys())
                    self.assertRegex(image["Labels"]["org.flatpak.commit"], r"^[0-9a-f]{64}$")
                    self.assertTrue(image["Labels"]["org.flatpak.ref"].startswith("app/"))
                self.assertEqual(len(architectures), len(set(architectures)))


class RepositoryDescriptorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parser = configparser.ConfigParser(interpolation=None)
        loaded = parser.read(ROOT / "tuna-os.flatpakrepo")
        if not loaded:
            raise AssertionError("tuna-os.flatpakrepo could not be read")
        cls.repo = parser["Flatpak Repo"]

    def test_required_fields_are_present(self):
        for field in ("Title", "Url", "Homepage", "Comment", "Description"):
            with self.subTest(field=field):
                self.assertTrue(self.repo.get(field))

    def test_remote_uses_oci_over_https(self):
        self.assertTrue(self.repo["Url"].startswith("oci+https://"))
        parsed = urlparse(self.repo["Url"].removeprefix("oci+"))
        self.assertEqual(parsed.scheme, "https")
        self.assertTrue(parsed.netloc)


if __name__ == "__main__":
    unittest.main()
