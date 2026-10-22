"""Unit tests for scripts/enrich-index.py.

Covers enrich() merge logic, AppStream screenshot counting, and the CLI interface.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from oci import RegistryError  # noqa: E402

spec = importlib.util.spec_from_file_location("enrich_index", SCRIPTS / "enrich-index.py")
enrich_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(enrich_index)

APPDATA_OK = "<component><screenshots><screenshot>x</screenshot></screenshots></component>"
APPDATA_NO_SHOTS = "<component></component>"
APPDATA_BROKEN = "<component"


class FakeRegistry:
    def __init__(self, labels_by_repo=None, errors=None):
        self.labels_by_repo = labels_by_repo or {}
        self.errors = errors or {}
        self.calls = []

    def image_labels(self, repository, digest):
        self.calls.append((repository, digest))
        if repository in self.errors:
            raise RegistryError(self.errors[repository])
        return self.labels_by_repo.get(repository, {})


def make_index(*images):
    return {
        "Registry": "example.com/repo",
        "Results": [{"Name": "app/one", "Images": list(images)}],
    }


class EnrichTests(unittest.TestCase):
    def test_adds_missing_appstream_labels(self):
        index = make_index({"Digest": "sha256:aaa", "Architecture": "amd64", "Labels": {}})
        registry = FakeRegistry(
            labels_by_repo={
                "app/one": {
                    "org.freedesktop.appstream.appdata": APPDATA_OK,
                    "org.freedesktop.appstream.icon-64": "icon64",
                    "org.freedesktop.appstream.icon-128": "icon128",
                }
            }
        )
        updated, problems, warnings = enrich_index.enrich(index, registry, verbose=False)
        self.assertEqual(updated, 1)
        self.assertEqual(problems, [])
        self.assertEqual(warnings, [])
        labels = index["Results"][0]["Images"][0]["Labels"]
        self.assertIn("org.freedesktop.appstream.appdata", labels)

    def test_already_complete_reports_no_update(self):
        labels = {
            "org.freedesktop.appstream.appdata": APPDATA_OK,
            "org.freedesktop.appstream.icon-64": "icon64",
            "org.freedesktop.appstream.icon-128": "icon128",
        }
        index = make_index(
            {"Digest": "sha256:aaa", "Architecture": "amd64", "Labels": dict(labels)}
        )
        registry = FakeRegistry(labels_by_repo={"app/one": labels})
        updated, problems, warnings = enrich_index.enrich(index, registry, verbose=False)
        self.assertEqual(updated, 0)
        self.assertEqual(problems, [])
        self.assertEqual(warnings, [])

    def test_registry_error_becomes_problem_not_crash(self):
        index = make_index({"Digest": "sha256:aaa", "Architecture": "amd64", "Labels": {}})
        registry = FakeRegistry(errors={"app/one": "401 unauthorized"})
        updated, problems, warnings = enrich_index.enrich(index, registry, verbose=False)
        self.assertEqual(updated, 0)
        self.assertEqual(len(problems), 1)
        self.assertIn("could not read labels", problems[0])

    def test_missing_appstream_metadata_is_a_problem(self):
        index = make_index({"Digest": "sha256:aaa", "Architecture": "amd64", "Labels": {}})
        registry = FakeRegistry(labels_by_repo={"app/one": {}})
        updated, problems, warnings = enrich_index.enrich(index, registry, verbose=False)
        self.assertEqual(len(problems), 1)
        self.assertIn("no AppStream metadata", problems[0])

    def test_zero_screenshots_is_a_warning_not_a_problem(self):
        index = make_index({"Digest": "sha256:aaa", "Architecture": "amd64", "Labels": {}})
        registry = FakeRegistry(
            labels_by_repo={
                "app/one": {
                    "org.freedesktop.appstream.appdata": APPDATA_NO_SHOTS,
                    "org.freedesktop.appstream.icon-64": "icon64",
                    "org.freedesktop.appstream.icon-128": "icon128",
                }
            }
        )
        updated, problems, warnings = enrich_index.enrich(index, registry, verbose=False)
        self.assertEqual(problems, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("no <screenshots>", warnings[0])

    def test_unparseable_appdata_is_a_problem(self):
        index = make_index({"Digest": "sha256:aaa", "Architecture": "amd64", "Labels": {}})
        registry = FakeRegistry(
            labels_by_repo={
                "app/one": {
                    "org.freedesktop.appstream.appdata": APPDATA_BROKEN,
                    "org.freedesktop.appstream.icon-64": "icon64",
                    "org.freedesktop.appstream.icon-128": "icon128",
                }
            }
        )
        updated, problems, warnings = enrich_index.enrich(index, registry, verbose=False)
        self.assertEqual(len(problems), 1)
        self.assertIn("does not parse", problems[0])

    def test_site_icon_stripped_appdata_matches_registry_and_keeps_existing(self):
        site_appdata = (
            "<component><screenshots><screenshot>x</screenshot></screenshots></component>\n"
            '    <icon type="remote" width="128" height="128">'
            "https://tunaos.org/flatpak/icons/foo.png</icon>\n"
        )
        registry_appdata = (
            "<component><screenshots><screenshot>x</screenshot></screenshots></component>\n"
        )
        index = make_index(
            {
                "Digest": "sha256:aaa",
                "Architecture": "amd64",
                "Labels": {
                    "org.freedesktop.appstream.appdata": site_appdata,
                    "org.freedesktop.appstream.icon-64": "icon64",
                    "org.freedesktop.appstream.icon-128": "icon128",
                },
            }
        )
        registry = FakeRegistry(
            labels_by_repo={
                "app/one": {
                    "org.freedesktop.appstream.appdata": registry_appdata,
                    "org.freedesktop.appstream.icon-64": "icon64",
                    "org.freedesktop.appstream.icon-128": "icon128",
                }
            }
        )
        updated, problems, warnings = enrich_index.enrich(index, registry, verbose=False)
        self.assertEqual(updated, 0)
        self.assertEqual(
            index["Results"][0]["Images"][0]["Labels"]["org.freedesktop.appstream.appdata"],
            site_appdata,
        )

    def test_multiple_images_processed_independently(self):
        index = make_index(
            {"Digest": "sha256:aaa", "Architecture": "amd64", "Labels": {}},
            {"Digest": "sha256:bbb", "Architecture": "arm64", "Labels": {}},
        )
        registry = FakeRegistry(
            labels_by_repo={
                "app/one": {
                    "org.freedesktop.appstream.appdata": APPDATA_OK,
                    "org.freedesktop.appstream.icon-64": "icon64",
                    "org.freedesktop.appstream.icon-128": "icon128",
                }
            }
        )
        updated, problems, warnings = enrich_index.enrich(index, registry, verbose=False)
        self.assertEqual(updated, 2)
        self.assertEqual(len(registry.calls), 2)


class ScreenshotCountTests(unittest.TestCase):
    """Cover the screenshot audit in scripts/enrich-index.py.

    An app with metadata but no screenshots renders an empty frame in a
    software centre. That is invisible from the index unless something looks
    inside the catalogue, which is what this guards.
    """

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
        self.assertEqual(enrich_index.screenshot_count(self.catalogue(body)), 2)

    def test_no_screenshots_is_zero_not_none(self):
        # Zero and unparseable must stay distinguishable: one is a presentation
        # problem, the other a broken catalogue.
        self.assertEqual(enrich_index.screenshot_count(self.catalogue("")), 0)

    def test_empty_screenshots_element_is_zero(self):
        self.assertEqual(
            enrich_index.screenshot_count(self.catalogue("<screenshots></screenshots>")), 0
        )

    def test_unparseable_catalogue_is_none(self):
        self.assertIsNone(enrich_index.screenshot_count("<components><broken"))

    def test_site_icon_extension_does_not_make_catalogue_stale(self):
        # Pin prepare-flatpak-icons.mjs's stock-icon insertion format; see the
        # producer link beside SITE_ICON. Preserve the registry's stock icon.
        original = self.catalogue(
            '<name>Demo</name>\n    <icon type="stock">org.tunaos.demo</icon>\n'
        )
        remote_icon = (
            '<icon type="remote" width="128" height="128">'
            'https://tunaos.org/flatpak/icons/org.tunaos.demo-x86_64.png'
            '</icon>\n'
        )
        enriched = original.replace(
            '<icon type="stock">', remote_icon + '    <icon type="stock">'
        )
        self.assertEqual(enrich_index.without_site_icon(enriched), original)


class EnrichIndexTests(unittest.TestCase):
    """Cover enrich() and main() in scripts/enrich-index.py."""

    def test_enrich_success_and_warnings(self):
        catalogue = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<components version="0.8" origin="flatpak">'
            '<component type="desktop-application">'
            '<id>org.tunaos.demo</id>'
            '</component></components>'
        )
        mock_registry = MagicMock()
        mock_registry.image_labels.return_value = {
            "org.freedesktop.appstream.appdata": catalogue,
            "org.freedesktop.appstream.icon-64": "data:image/png;base64,123",
            "org.freedesktop.appstream.icon-128": "data:image/png;base64,456",
        }
        index_data = {
            "Results": [
                {
                    "Name": "tuna-os/demo",
                    "Images": [
                        {
                            "Architecture": "amd64",
                            "Digest": "sha256:" + "a" * 64,
                            "Labels": {},
                        }
                    ],
                }
            ]
        }
        updated, problems, warnings = enrich_index.enrich(
            index_data, mock_registry, verbose=False
        )
        self.assertEqual(updated, 1)
        self.assertEqual(len(problems), 0)
        self.assertEqual(len(warnings), 1)
        self.assertIn("no <screenshots> declared", warnings[0])

    def test_enrich_registry_error_and_missing_metadata(self):
        mock_registry = MagicMock()
        mock_registry.image_labels.side_effect = RegistryError("404 Not Found")
        index_data = {
            "Results": [
                {
                    "Name": "tuna-os/demo",
                    "Images": [{"Architecture": "amd64", "Digest": "sha256:" + "a" * 64}],
                }
            ]
        }
        updated, problems, warnings = enrich_index.enrich(
            index_data, mock_registry, verbose=False
        )
        self.assertEqual(updated, 0)
        self.assertEqual(len(problems), 1)
        self.assertIn("could not read labels", problems[0])

        mock_registry.image_labels.side_effect = None
        mock_registry.image_labels.return_value = {}
        index_data_2 = {
            "Results": [
                {
                    "Name": "tuna-os/demo",
                    "Images": [
                        {
                            "Architecture": "amd64",
                            "Digest": "sha256:" + "a" * 64,
                            "Labels": {},
                        }
                    ],
                }
            ]
        }
        updated, problems, warnings = enrich_index.enrich(
            index_data_2, mock_registry, verbose=False
        )
        self.assertEqual(updated, 0)
        self.assertEqual(len(problems), 1)
        self.assertIn("image has no AppStream metadata", problems[0])

    def test_main_check_mode(self):
        catalogue = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<components version="0.8" origin="flatpak">'
            '<component type="desktop-application">'
            '<id>org.tunaos.demo</id>'
            '<screenshots><screenshot><image>https://e/1.png</image></screenshot></screenshots>'
            '</component></components>'
        )
        index = {
            "Registry": "https://ghcr.io",
            "Results": [
                {
                    "Name": "tuna-os/demo",
                    "Images": [
                        {
                            "Architecture": "amd64",
                            "Digest": "sha256:" + "a" * 64,
                            "Labels": {
                                "org.freedesktop.appstream.appdata": catalogue,
                                "org.freedesktop.appstream.icon-64": "icon64",
                                "org.freedesktop.appstream.icon-128": "icon128",
                            },
                        }
                    ],
                }
            ],
        }

        with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
            json.dump(index, tmp)
            tmp_path = Path(tmp.name)

        try:
            with patch.object(enrich_index.Registry, "image_labels") as mock_labels:
                mock_labels.return_value = {
                    "org.freedesktop.appstream.appdata": catalogue,
                    "org.freedesktop.appstream.icon-64": "icon64",
                    "org.freedesktop.appstream.icon-128": "icon128",
                }
                with patch("sys.argv", ["enrich-index.py", str(tmp_path), "--check"]):
                    res = enrich_index.main()
                    self.assertEqual(res, 0)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_main_write_mode_and_check_failures(self):
        catalogue = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<components version="0.8" origin="flatpak">'
            '<component type="desktop-application">'
            '<id>org.tunaos.demo</id>'
            '<screenshots><screenshot><image>https://e/1.png</image></screenshot></screenshots>'
            '</component></components>'
        )
        index = {
            "Registry": "https://ghcr.io",
            "Results": [
                {
                    "Name": "tuna-os/demo",
                    "Images": [
                        {
                            "Architecture": "amd64",
                            "Digest": "sha256:" + "a" * 64,
                            "Labels": {},
                        }
                    ],
                }
            ],
        }

        with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
            json.dump(index, tmp)
            tmp_path = Path(tmp.name)

        try:
            with patch.object(enrich_index.Registry, "image_labels") as mock_labels:
                mock_labels.return_value = {
                    "org.freedesktop.appstream.appdata": catalogue,
                    "org.freedesktop.appstream.icon-64": "icon64",
                    "org.freedesktop.appstream.icon-128": "icon128",
                }
                with patch("sys.argv", ["enrich-index.py", str(tmp_path), "--check"]):
                    res = enrich_index.main()
                    self.assertEqual(res, 1)

                with patch("sys.argv", ["enrich-index.py", str(tmp_path)]):
                    res = enrich_index.main()
                    self.assertEqual(res, 0)

                with patch("sys.argv", ["enrich-index.py", str(tmp_path)]):
                    res = enrich_index.main()
                    self.assertEqual(res, 0)
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
