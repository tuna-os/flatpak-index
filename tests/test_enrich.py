"""Tests for the enrich() merge logic in scripts/enrich-index.py.

Before this file, only screenshot_count() (a small helper enrich() calls)
had coverage -- see ScreenshotCountTests in test_index.py. The merge logic
itself -- which images get updated, when a registry read failure becomes a
"problem" instead of crashing the whole run, and how missing-metadata vs.
missing-screenshots are told apart -- had none.
"""

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "enrich_index", ROOT / "scripts" / "enrich-index.py"
)
enrich_index = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(enrich_index)

RegistryError = enrich_index.RegistryError

APPDATA_WITH_SHOTS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<components version="0.8" origin="flatpak">'
    "<component><id>org.tunaos.demo</id>"
    '<screenshots><screenshot><image>https://e/1.png</image></screenshot></screenshots>'
    "</component></components>"
)
APPDATA_NO_SHOTS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<components version="0.8" origin="flatpak">'
    "<component><id>org.tunaos.demo</id></component></components>"
)
FULL_LABELS = {
    "org.freedesktop.appstream.appdata": APPDATA_WITH_SHOTS,
    "org.freedesktop.appstream.icon-64": "data",
    "org.freedesktop.appstream.icon-128": "data",
}


class FakeRegistry:
    """Stands in for oci.Registry: enrich() only calls .image_labels()."""

    def __init__(self, labels_by_digest=None, errors=None):
        self.labels_by_digest = labels_by_digest or {}
        self.errors = errors or {}
        self.calls = []

    def image_labels(self, repository, digest):
        self.calls.append((repository, digest))
        if digest in self.errors:
            raise RegistryError(self.errors[digest])
        return self.labels_by_digest.get(digest, {})


def _index(images):
    return {"Registry": "https://ghcr.io", "Results": [{"Name": "tuna-os/demo", "Images": images}]}


class EnrichTests(unittest.TestCase):
    def test_adds_missing_labels_and_counts_the_update(self):
        index_data = _index([{"Digest": "sha256:a", "Architecture": "x86_64", "Labels": {}}])
        registry = FakeRegistry({"sha256:a": FULL_LABELS})

        updated, problems, warnings = enrich_index.enrich(index_data, registry, verbose=False)

        self.assertEqual(updated, 1)
        self.assertEqual(problems, [])
        self.assertEqual(warnings, [])
        image = index_data["Results"][0]["Images"][0]
        self.assertEqual(image["Labels"], FULL_LABELS)

    def test_already_complete_entry_is_left_unchanged(self):
        index_data = _index(
            [{"Digest": "sha256:a", "Architecture": "x86_64", "Labels": dict(FULL_LABELS)}]
        )
        registry = FakeRegistry({"sha256:a": FULL_LABELS})

        updated, problems, warnings = enrich_index.enrich(index_data, registry, verbose=False)

        self.assertEqual(updated, 0)
        self.assertEqual(problems, [])

    def test_registry_error_becomes_a_problem_not_a_crash(self):
        index_data = _index([{"Digest": "sha256:a", "Architecture": "x86_64", "Labels": {}}])
        registry = FakeRegistry(errors={"sha256:a": "GET failed: rc=22"})

        updated, problems, warnings = enrich_index.enrich(index_data, registry, verbose=False)

        self.assertEqual(updated, 0)
        self.assertEqual(len(problems), 1)
        self.assertIn("could not read labels", problems[0])

    def test_missing_appstream_metadata_is_a_problem(self):
        index_data = _index([{"Digest": "sha256:a", "Architecture": "x86_64", "Labels": {}}])
        registry = FakeRegistry({"sha256:a": {}})

        updated, problems, warnings = enrich_index.enrich(index_data, registry, verbose=False)

        self.assertEqual(len(problems), 1)
        self.assertIn("no AppStream metadata", problems[0])
        self.assertEqual(warnings, [])

    def test_zero_screenshots_is_a_warning_not_a_problem(self):
        labels = dict(FULL_LABELS)
        labels["org.freedesktop.appstream.appdata"] = APPDATA_NO_SHOTS
        index_data = _index([{"Digest": "sha256:a", "Architecture": "x86_64", "Labels": {}}])
        registry = FakeRegistry({"sha256:a": labels})

        updated, problems, warnings = enrich_index.enrich(index_data, registry, verbose=False)

        self.assertEqual(problems, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("no <screenshots> declared", warnings[0])

    def test_unparseable_catalogue_is_a_problem(self):
        labels = dict(FULL_LABELS)
        labels["org.freedesktop.appstream.appdata"] = "<not-xml"
        index_data = _index([{"Digest": "sha256:a", "Architecture": "x86_64", "Labels": {}}])
        registry = FakeRegistry({"sha256:a": labels})

        updated, problems, warnings = enrich_index.enrich(index_data, registry, verbose=False)

        self.assertEqual(len(problems), 1)
        self.assertIn("does not parse", problems[0])

    def test_one_bad_image_does_not_block_the_others(self):
        index_data = _index(
            [
                {"Digest": "sha256:bad", "Architecture": "x86_64", "Labels": {}},
                {"Digest": "sha256:good", "Architecture": "aarch64", "Labels": {}},
            ]
        )
        registry = FakeRegistry(
            labels_by_digest={"sha256:good": FULL_LABELS},
            errors={"sha256:bad": "boom"},
        )

        updated, problems, warnings = enrich_index.enrich(index_data, registry, verbose=False)

        self.assertEqual(updated, 1)
        self.assertEqual(len(problems), 1)
        self.assertEqual(
            index_data["Results"][0]["Images"][1]["Labels"], FULL_LABELS
        )

    def test_verbose_default_prints_added_and_unchanged_lines(self):
        """Every test above passes verbose=False, which left the two print
        branches (added-labels, already-complete) never executed. This is
        the actual default used by main()'s real invocation."""
        index_data = _index(
            [
                {"Digest": "sha256:a", "Architecture": "x86_64", "Labels": {}},
                {"Digest": "sha256:b", "Architecture": "aarch64", "Labels": dict(FULL_LABELS)},
            ]
        )
        registry = FakeRegistry(
            {"sha256:a": FULL_LABELS, "sha256:b": FULL_LABELS}
        )

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            updated, problems, warnings = enrich_index.enrich(index_data, registry)

        self.assertEqual(updated, 1)
        self.assertEqual(problems, [])
        self.assertIn("added org.freedesktop.appstream", out.getvalue())
        self.assertIn("already complete", out.getvalue())


if __name__ == "__main__":
    unittest.main()
