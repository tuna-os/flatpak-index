"""Unit tests for scripts/enrich-index.py's enrich() merge logic.

enrich() already has end-to-end coverage via .github/workflows/check-metadata.yml,
which runs `enrich-index.py served-index.json --check` against a live registry
pull on every push. These tests add the missing unit coverage for its
update/problem/warning branches using a fake Registry.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
