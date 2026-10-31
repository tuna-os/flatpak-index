import base64
import configparser
import json
import os
import re
import unittest
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
REQUIRED_LABELS = {
    "org.flatpak.metadata",
    "org.flatpak.ref",
    "org.flatpak.commit",
    "org.flatpak.timestamp",
}
SERVED_INDEX_URL = "https://tunaos.org/flatpak/index/static"


def load_index():
    index_file = os.environ.get("FLATPAK_INDEX_FILE")
    if index_file:
        return json.loads(Path(index_file).read_text())
    served_local = ROOT / "served-index.json"
    if served_local.is_file():
        return json.loads(served_local.read_text())
    index_url = os.environ.get("FLATPAK_INDEX_URL", SERVED_INDEX_URL)
    req = urllib.request.Request(index_url, headers={"User-Agent": "curl/7.88.1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        raise unittest.SkipTest(f"Live catalog unavailable from {index_url}: {exc}") from exc


class IndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = load_index()

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
                digests = []
                for image in result["Images"]:
                    digests.append(image["Digest"])
                    self.assertRegex(image["Digest"], DIGEST)
                    self.assertEqual(
                        image["MediaType"], "application/vnd.oci.image.manifest.v1+json"
                    )
                    self.assertEqual(image["OS"], "linux")
                    self.assertTrue(image["Tags"])
                    self.assertLessEqual(REQUIRED_LABELS, image["Labels"].keys())
                    self.assertRegex(image["Labels"]["org.flatpak.commit"], r"^[0-9a-f]{64}$")
                    self.assertTrue(image["Labels"]["org.flatpak.ref"].startswith("app/"))
                self.assertEqual(len(digests), len(set(digests)))
                all_tags = [tag for img in result["Images"] for tag in img.get("Tags", [])]
                self.assertIn("latest", all_tags)

    def test_image_size_labels_are_positive_integers(self):
        size_labels = (
            "org.flatpak.installed-size",
            "org.flatpak.download-size",
        )
        for result in self.index["Results"]:
            for image in result["Images"]:
                with self.subTest(name=result["Name"], arch=image["Architecture"]):
                    labels = image["Labels"]
                    for label in size_labels:
                        value = labels[label]
                        self.assertTrue(value.isdigit())
                        self.assertGreater(int(value), 0)


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

    def test_no_authenticator_is_declared(self):
        # The backend registry is public GHCR: installs were verified to work
        # with and without org.flatpak.Authenticator.Oci, while `remote-info`
        # returns 401 either way (issue #96 — a flatpak client limitation, not
        # a missing authenticator). Declaring one only sends users down a
        # privileged dead end, so the descriptor must not name one.
        self.assertIsNone(self.repo.get("AuthenticatorName"))

    def test_remote_uses_oci_over_https(self):
        self.assertTrue(self.repo["Url"].startswith("oci+https://"))
        parsed = urlparse(self.repo["Url"].removeprefix("oci+"))
        self.assertEqual(parsed.scheme, "https")
        self.assertTrue(parsed.netloc)

    def test_icon_url_is_https(self):
        parsed = urlparse(self.repo["Icon"])
        self.assertEqual(parsed.scheme, "https")
        self.assertTrue(parsed.netloc)

    def test_remote_descriptor_points_to_canonical_catalog(self):
        # The canonical remote is served from tuna-os/docs at tunaos.org/flatpak.
        self.assertEqual(self.repo["Url"], "oci+https://tunaos.org/flatpak")
        self.assertEqual(self.repo["Homepage"], "https://tunaos.org")


class AppStreamTests(unittest.TestCase):
    """Validate the AppStream metadata carried by the index.

    flatpak builds the remote's AppStream catalogue out of the
    org.freedesktop.appstream.* labels; that catalogue is what gives software
    centres an app name, icon, licence and screenshots. These tests check that
    whatever metadata the index does carry is well formed and complete enough
    to render.

    Whether every published app *has* metadata is a property of the live
    remote -- check that with ``./scripts/enrich-index.py <index> --check``.
    """

    APPSTREAM = "org.freedesktop.appstream.appdata"
    ICONS = (
        "org.freedesktop.appstream.icon-64",
        "org.freedesktop.appstream.icon-128",
    )

    @classmethod
    def setUpClass(cls):
        cls.index = load_index()

    def images(self):
        for result in self.index["Results"]:
            for image in result["Images"]:
                yield result["Name"], image

    def test_appstream_metadata_is_a_valid_catalogue(self):
        for name, image in self.images():
            appdata = image["Labels"].get(self.APPSTREAM)
            if appdata is None:
                continue
            with self.subTest(name=name, arch=image["Architecture"]):
                root = ElementTree.fromstring(appdata)
                self.assertEqual(root.tag, "components")
                components = root.findall("component")
                self.assertTrue(components, "catalogue lists no components")
                app_id = image["Labels"]["org.flatpak.ref"].split("/")[1]
                self.assertIn(app_id, [c.findtext("id") for c in components])

    def test_components_have_the_fields_software_centres_render(self):
        for name, image in self.images():
            appdata = image["Labels"].get(self.APPSTREAM)
            if appdata is None:
                continue
            for component in ElementTree.fromstring(appdata).findall("component"):
                with self.subTest(name=name, component=component.findtext("id")):
                    for field in ("name", "summary", "project_license"):
                        value = component.findtext(field)
                        self.assertTrue(
                            value and value.strip(),
                            f"<{field}> is missing or empty",
                        )

    def test_icons_are_png_data_uris(self):
        prefix = "data:image/png;base64,"
        for name, image in self.images():
            if self.APPSTREAM not in image["Labels"]:
                continue
            for label in self.ICONS:
                with self.subTest(name=name, label=label):
                    icon = image["Labels"].get(label)
                    self.assertTrue(icon is not None, f"{label} is missing")
                    self.assertTrue(icon.startswith(prefix), "not a PNG data URI")
                    decoded = base64.b64decode(icon[len(prefix):], validate=True)
                    self.assertTrue(
                        decoded.startswith(b"\x89PNG\r\n\x1a\n"),
                        "does not decode to a PNG",
                    )


if __name__ == "__main__":
    unittest.main()
