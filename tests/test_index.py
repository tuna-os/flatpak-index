import base64
import configparser
import importlib.util
import json
import re
import unittest
from pathlib import Path
from xml.etree import ElementTree
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

    def test_image_size_labels_are_numeric(self):
        for result in self.index["Results"]:
            for image in result["Images"]:
                with self.subTest(name=result["Name"], arch=image["Architecture"]):
                    labels = image["Labels"]
                    if "org.flatpak.installed-size" in labels:
                        self.assertTrue(labels["org.flatpak.installed-size"].isdigit())
                    if "org.flatpak.download-size" in labels:
                        self.assertTrue(labels["org.flatpak.download-size"].isdigit())


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

    def test_icon_url_is_https(self):
        icon = self.repo.get("Icon")
        if icon:
            parsed = urlparse(icon)
            self.assertEqual(parsed.scheme, "https")
            self.assertTrue(parsed.netloc)


if __name__ == "__main__":
    unittest.main()



class AppStreamTests(unittest.TestCase):
    """Validate the AppStream metadata carried by the index.

    flatpak builds the remote's AppStream catalogue out of the
    org.freedesktop.appstream.* labels; that catalogue is what gives software
    centres an app name, icon, licence and screenshots. These tests check that
    whatever metadata the index does carry is well formed and complete enough
    to render.

    Whether every published app *has* metadata is a property of the live
    remote, not of this repository's historical snapshot -- check that with
    ``./scripts/enrich-index.py <index> --check``.
    """

    APPSTREAM = "org.freedesktop.appstream.appdata"
    ICONS = (
        "org.freedesktop.appstream.icon-64",
        "org.freedesktop.appstream.icon-128",
    )

    @classmethod
    def setUpClass(cls):
        cls.index = json.loads((ROOT / "index/static").read_text())

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


class ScreenshotCountTests(unittest.TestCase):
    """Cover the screenshot audit in scripts/enrich-index.py.

    An app with metadata but no screenshots renders an empty frame in a
    software centre. That is invisible from the index unless something looks
    inside the catalogue, which is what this guards.
    """

    @staticmethod
    def _load():
        spec = importlib.util.spec_from_file_location(
            "enrich_index", ROOT / "scripts" / "enrich-index.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def setUp(self):
        self.enrich = self._load()

    def catalogue(self, body):
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<components version="0.8" origin="flatpak">'
            '<component type="desktop-application">'
            "<id>org.tunaos.demo</id>" + body + "</component></components>"
        )

    def test_counts_screenshots(self):
        body = (
            "<screenshots>"
            '<screenshot type="default"><image>https://e/1.png</image></screenshot>'
            "<screenshot><image>https://e/2.png</image></screenshot>"
            "</screenshots>"
        )
        self.assertEqual(self.enrich.screenshot_count(self.catalogue(body)), 2)

    def test_no_screenshots_is_zero_not_none(self):
        # Zero and unparseable must stay distinguishable: one is a presentation
        # problem, the other a broken catalogue.
        self.assertEqual(self.enrich.screenshot_count(self.catalogue("")), 0)

    def test_empty_screenshots_element_is_zero(self):
        self.assertEqual(
            self.enrich.screenshot_count(self.catalogue("<screenshots></screenshots>")), 0
        )

    def test_unparseable_catalogue_is_none(self):
        self.assertIsNone(self.enrich.screenshot_count("<components><broken"))
