"""Tests for the publisher script.

The bug these guard against: an earlier revision of update-index.py copied
only labels starting with "org.flatpak." into the index, silently discarding
the org.freedesktop.appstream.* labels that flatpak build-bundle had written.
Flatpak builds a remote's AppStream catalogue from those labels, so every app
in the remote rendered in software centres as a bare application ID with an
"Unknown" licence and no screenshots.
"""

import base64
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "update_index", ROOT / "scripts" / "update-index.py"
)
update_index = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update_index)


# Smallest thing that satisfies a "decodes to a PNG" check.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

APPDATA = """<?xml version="1.0" encoding="UTF-8"?>
<components version="0.8" origin="flatpak">
  <component type="desktop-application">
    <id>org.tunaos.example</id>
    <name>Example</name>
    <summary>Do the thing you came for</summary>
    <project_license>MIT</project_license>
  </component>
</components>
"""

ICON = "data:image/png;base64," + base64.b64encode(PNG).decode()

FLATPAK_LABELS = {
    "org.flatpak.ref": "app/org.tunaos.example/x86_64/master",
    "org.flatpak.metadata": "[Application]\nname=org.tunaos.example\n",
    "org.flatpak.commit": "0" * 64,
    "org.flatpak.timestamp": "1780000000",
}

APPSTREAM_LABELS = {
    "org.freedesktop.appstream.appdata": APPDATA,
    "org.freedesktop.appstream.icon-64": ICON,
    "org.freedesktop.appstream.icon-128": ICON,
}


def write_oci_layout(directory, labels, architecture="amd64"):
    """Build a minimal OCI layout the publisher can read."""
    blobs = directory / "blobs" / "sha256"
    blobs.mkdir(parents=True, exist_ok=True)

    config = {
        "architecture": architecture,
        "os": "linux",
        "config": {"Labels": dict(labels)},
    }
    config_bytes = json.dumps(config).encode()
    config_digest = "sha256:" + "c" * 64
    (blobs / config_digest.split(":")[1]).write_bytes(config_bytes)

    manifest = {
        "schemaVersion": 2,
        "config": {"digest": config_digest, "size": len(config_bytes)},
        "layers": [],
    }
    manifest_bytes = json.dumps(manifest).encode()
    manifest_digest = "sha256:" + "m" * 64
    (blobs / manifest_digest.split(":")[1]).write_bytes(manifest_bytes)

    (directory / "index.json").write_text(
        json.dumps({"manifests": [{"digest": manifest_digest}]})
    )
    return manifest_digest


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def build_entry(self, labels, require_appstream=False, architecture="amd64"):
        oci_dir = Path(tempfile.mkdtemp(dir=self.tmp, prefix=f"oci-{architecture}-"))
        digest = write_oci_layout(oci_dir, labels, architecture)
        _, config = update_index.read_oci_layout(oci_dir)
        return digest, update_index.build_image_entry(
            digest, config, ["latest"], require_appstream
        )

    def test_appstream_labels_survive_into_the_index(self):
        _, entry = self.build_entry({**FLATPAK_LABELS, **APPSTREAM_LABELS})
        for label in APPSTREAM_LABELS:
            self.assertIn(label, entry["Labels"], f"{label} was dropped")
        self.assertEqual(
            entry["Labels"]["org.freedesktop.appstream.appdata"], APPDATA
        )

    def test_flatpak_labels_survive_into_the_index(self):
        _, entry = self.build_entry({**FLATPAK_LABELS, **APPSTREAM_LABELS})
        for label in FLATPAK_LABELS:
            self.assertIn(label, entry["Labels"])

    def test_unrelated_labels_are_dropped(self):
        labels = {**FLATPAK_LABELS, "org.opencontainers.image.created": "now"}
        _, entry = self.build_entry(labels)
        self.assertNotIn("org.opencontainers.image.created", entry["Labels"])

    def test_missing_required_flatpak_label_is_an_error(self):
        labels = dict(FLATPAK_LABELS)
        del labels["org.flatpak.ref"]
        with self.assertRaises(ValueError):
            self.build_entry(labels)

    def test_missing_appstream_is_tolerated_by_default(self):
        with contextlib.redirect_stderr(io.StringIO()) as warning:
            _, entry = self.build_entry(FLATPAK_LABELS)
        self.assertIn("metainfo", warning.getvalue())
        self.assertNotIn("org.freedesktop.appstream.appdata", entry["Labels"])

    def test_require_appstream_rejects_an_image_without_metadata(self):
        with self.assertRaises(ValueError) as caught:
            self.build_entry(FLATPAK_LABELS, require_appstream=True)
        self.assertIn("metainfo", str(caught.exception))

    def test_second_architecture_is_added_not_replaced(self):
        index = {"Registry": "https://ghcr.io", "Results": []}
        for arch in ("amd64", "arm64"):
            _, entry = self.build_entry(
                {**FLATPAK_LABELS, **APPSTREAM_LABELS}, architecture=arch
            )
            update_index.merge_entry(index, "tuna-os/example", entry)

        images = index["Results"][0]["Images"]
        self.assertEqual([image["Architecture"] for image in images], ["amd64", "arm64"])

    def test_republishing_one_architecture_replaces_only_that_image(self):
        index = {"Registry": "https://ghcr.io", "Results": []}
        for arch in ("amd64", "arm64"):
            _, entry = self.build_entry(
                {**FLATPAK_LABELS, **APPSTREAM_LABELS}, architecture=arch
            )
            update_index.merge_entry(index, "tuna-os/example", entry)

        _, entry = self.build_entry({**FLATPAK_LABELS, **APPSTREAM_LABELS})
        entry["Digest"] = "sha256:" + "f" * 64
        update_index.merge_entry(index, "tuna-os/example", entry)

        images = index["Results"][0]["Images"]
        self.assertEqual(len(images), 2)
        by_arch = {image["Architecture"]: image["Digest"] for image in images}
        self.assertEqual(by_arch["amd64"], "sha256:" + "f" * 64)
        self.assertTrue(by_arch["arm64"].startswith("sha256:"))

    def test_an_app_is_indexed_under_its_repo_name_not_its_app_id(self):
        # Compass's ID is org.tunaos.compass and it publishes to
        # ghcr.io/tuna-os/compass: the index Name is the registry path, and
        # nothing may assume it matches the app ID.
        labels = {
            **FLATPAK_LABELS,
            **APPSTREAM_LABELS,
            "org.flatpak.ref": "app/org.tunaos.compass/x86_64/master",
            "org.flatpak.metadata": "[Application]\nname=org.tunaos.compass\n",
        }
        index = {"Registry": "https://ghcr.io", "Results": []}
        for name in ("tuna-os/mariner", "tuna-os/letters"):
            _, entry = self.build_entry({**FLATPAK_LABELS, **APPSTREAM_LABELS})
            update_index.merge_entry(index, name, entry)

        _, entry = self.build_entry(labels, require_appstream=True)
        update_index.merge_entry(index, "tuna-os/compass", entry)

        names = [result["Name"] for result in index["Results"]]
        self.assertEqual(names, ["tuna-os/compass", "tuna-os/letters", "tuna-os/mariner"])
        compass = index["Results"][0]["Images"][0]["Labels"]
        self.assertEqual(compass["org.flatpak.ref"], "app/org.tunaos.compass/x86_64/master")
        self.assertIn("org.freedesktop.appstream.appdata", compass)

    def test_two_apps_sharing_a_repo_and_arch_coexist(self):
        # Five installer frontends publish under tuna-os/bootc-installer.
        # Merging by architecture alone let concurrent frontend publishes
        # overwrite each other until a single frontend was left standing.
        index = {"Registry": "https://ghcr.io", "Results": []}
        refs = [
            "app/org.tunaos.InstallerCosmic/x86_64/stable",
            "app/org.tunaos.InstallerGnome/x86_64/stable",
        ]
        for ref in refs:
            labels = {**FLATPAK_LABELS, **APPSTREAM_LABELS, "org.flatpak.ref": ref}
            _, entry = self.build_entry(labels)
            update_index.merge_entry(index, "tuna-os/bootc-installer", entry)

        images = index["Results"][0]["Images"]
        self.assertEqual(len(images), 2)
        got = sorted(image["Labels"]["org.flatpak.ref"] for image in images)
        self.assertEqual(got, sorted(refs))

    def test_republishing_one_app_leaves_the_other_app_alone(self):
        index = {"Registry": "https://ghcr.io", "Results": []}
        refs = [
            "app/org.tunaos.InstallerCosmic/x86_64/stable",
            "app/org.tunaos.InstallerGnome/x86_64/stable",
        ]
        for ref in refs:
            labels = {**FLATPAK_LABELS, **APPSTREAM_LABELS, "org.flatpak.ref": ref}
            _, entry = self.build_entry(labels)
            update_index.merge_entry(index, "tuna-os/bootc-installer", entry)

        labels = {
            **FLATPAK_LABELS,
            **APPSTREAM_LABELS,
            "org.flatpak.ref": refs[0],
        }
        _, entry = self.build_entry(labels)
        entry["Digest"] = "sha256:" + "f" * 64
        update_index.merge_entry(index, "tuna-os/bootc-installer", entry)

        images = index["Results"][0]["Images"]
        self.assertEqual(len(images), 2)
        by_ref = {
            image["Labels"]["org.flatpak.ref"]: image["Digest"] for image in images
        }
        self.assertEqual(by_ref[refs[0]], "sha256:" + "f" * 64)
        self.assertTrue(by_ref[refs[1]].startswith("sha256:"))

    def test_read_oci_layout_missing_index_file(self):
        missing_dir = self.tmp / "nonexistent-oci"
        with self.assertRaises(FileNotFoundError):
            update_index.read_oci_layout(missing_dir)

    def test_read_oci_layout_empty_manifests(self):
        oci_dir = self.tmp / "empty-manifests-oci"
        oci_dir.mkdir(parents=True, exist_ok=True)
        (oci_dir / "index.json").write_text(json.dumps({"manifests": []}))
        with self.assertRaises(ValueError) as caught:
            update_index.read_oci_layout(oci_dir)
        self.assertIn("No manifests listed", str(caught.exception))


class MainTests(unittest.TestCase):
    """The command-line entry point that application repos' publish workflows run."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.oci_dir = self.tmp / "oci"
        self.index_file = self.tmp / "index" / "static"

    def run_main(self, *extra):
        argv = [
            "update-index.py",
            "--oci-dir", str(self.oci_dir),
            "--index-file", str(self.index_file),
            "--repo-name", "tuna-os/example",
            *extra,
        ]
        out = io.StringIO()
        with (
            mock.patch.object(sys, "argv", argv),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            update_index.main()
        return out.getvalue()

    def test_creates_the_index_and_its_parent_directory(self):
        write_oci_layout(self.oci_dir, {**FLATPAK_LABELS, **APPSTREAM_LABELS})
        output = self.run_main()

        index = json.loads(self.index_file.read_text())
        self.assertEqual(index["Registry"], "https://ghcr.io")
        self.assertEqual([r["Name"] for r in index["Results"]], ["tuna-os/example"])
        self.assertEqual(index["Results"][0]["Images"][0]["Tags"], ["latest"])
        self.assertIn("appstream=yes", output)

    def test_registry_and_tags_options_reach_the_index(self):
        write_oci_layout(self.oci_dir, {**FLATPAK_LABELS, **APPSTREAM_LABELS})
        self.run_main("--registry", "registry.example", "--tags", "stable", "beta")

        index = json.loads(self.index_file.read_text())
        self.assertEqual(index["Registry"], "https://registry.example")
        self.assertEqual(index["Results"][0]["Images"][0]["Tags"], ["stable", "beta"])

    def test_merges_into_an_existing_index_and_keeps_other_apps(self):
        self.index_file.parent.mkdir(parents=True)
        other = {"Name": "tuna-os/other", "Images": []}
        self.index_file.write_text(
            json.dumps({"Registry": "https://ghcr.io", "Results": [other]})
        )
        write_oci_layout(self.oci_dir, FLATPAK_LABELS)
        output = self.run_main()

        index = json.loads(self.index_file.read_text())
        self.assertEqual(
            [r["Name"] for r in index["Results"]], ["tuna-os/example", "tuna-os/other"]
        )
        self.assertIn("appstream=no", output)

    def test_require_appstream_failure_leaves_the_index_untouched(self):
        self.index_file.parent.mkdir(parents=True)
        before = json.dumps({"Registry": "https://ghcr.io", "Results": []})
        self.index_file.write_text(before)
        write_oci_layout(self.oci_dir, FLATPAK_LABELS)

        with self.assertRaises(ValueError):
            self.run_main("--require-appstream")
        self.assertEqual(self.index_file.read_text(), before)


if __name__ == "__main__":
    unittest.main()

