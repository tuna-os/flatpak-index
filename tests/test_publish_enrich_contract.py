"""End-to-end contract between the publish script and the auditor.

scripts/update-index.py (publish) and scripts/enrich-index.py (audit/repair)
are two independent implementations of one label rule, so unit tests that hit
each one in isolation cannot see a defect *between* them. This suite runs a
real entry produced by update_index.build_image_entry through
enrich_index.enrich, so the two data shapes and the label rule they share are
checked together.

That is where the headline failure of tuna-os/flatpak-index#145 lives: an entry
published incomplete (no AppStream labels) is silently bare in the index. The
auditor must either repair it from the registry or fail -- this proves both.
"""

import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "update_index", ROOT / "scripts" / "update-index.py"
)
update_index = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update_index)

_enrich_spec = importlib.util.spec_from_file_location(
    "enrich_index", ROOT / "scripts" / "enrich-index.py"
)
enrich_index = importlib.util.module_from_spec(_enrich_spec)
_enrich_spec.loader.exec_module(enrich_index)

# A catalogue with one screenshot: complete metadata that should not warn.
APPDATA = """<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>org.tunaos.example</id>
  <name>Demo</name>
  <screenshots>
    <screenshot type="default"><image>https://example.com/1.png</image></screenshot>
  </screenshots>
</component>
"""

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
ICON = "data:image/png;base64," + base64.b64encode(PNG).decode()

FLATPAK_LABELS = {
    "org.flatpak.ref": "app/org.tunaos.example/x86_64/stable",
    "org.flatpak.metadata": "[Application]\nname=org.tunaos.example\n",
    "org.flatpak.commit": "a" * 40,
    "org.flatpak.timestamp": "1780000000",
}
APPSTREAM_LABELS = {
    "org.freedesktop.appstream.appdata": APPDATA,
    "org.freedesktop.appstream.icon-64": ICON,
    "org.freedesktop.appstream.icon-128": ICON,
}


class FakeRegistry:
    """Returns preset labels per repository; nothing else is in it."""

    def __init__(self, labels_by_repo):
        self.labels_by_repo = labels_by_repo

    def image_labels(self, repository, digest):
        return self.labels_by_repo.get(repository, {})


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def build_entry(labels, require_appstream=False):
    """Produce an index entry the way a publish workflow would.

    Writes a real OCI layout (index -> manifest -> config) so read_oci_layout
    and build_image_entry exercise the same paths the publish script runs.
    """
    oci = Path(tempfile.mkdtemp())
    blobs = oci / "blobs" / "sha256"
    blobs.mkdir(parents=True, exist_ok=True)

    config = {
        "architecture": "amd64",
        "os": "linux",
        "config": {"Labels": dict(labels)},
    }
    config_payload = json.dumps(config).encode()
    config_digest = _digest(config_payload)
    (blobs / config_digest.split(":")[1]).write_bytes(config_payload)

    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {
            "mediaType": "application/vnd.oci.image.config.v1+json",
            "digest": config_digest,
            "size": len(config_payload),
        },
        "layers": [],
    }
    manifest_payload = json.dumps(manifest).encode()
    manifest_digest = _digest(manifest_payload)
    (blobs / manifest_digest.split(":")[1]).write_bytes(manifest_payload)

    (oci / "index.json").write_text(
        json.dumps({"manifests": [{"digest": manifest_digest}]})
    )

    _, config_out = update_index.read_oci_layout(oci)
    with contextlib.redirect_stderr(io.StringIO()) as stderr:
        entry = update_index.build_image_entry(
            manifest_digest, config_out, ["latest"], require_appstream
        )
    return entry, stderr.getvalue()


def publish(labels, require_appstream=False, repo="tuna-os/example"):
    """Publish one entry and return (index, stderr)."""
    entry, stderr = build_entry(labels, require_appstream)
    index = {"Registry": "https://ghcr.io", "Results": []}
    update_index.merge_entry(index, repo, entry)
    return index, stderr


class PublishEnrichContract(unittest.TestCase):
    def test_published_complete_entry_passes_the_auditor(self):
        index, stderr = publish({**FLATPAK_LABELS, **APPSTREAM_LABELS})
        updated, problems, warnings = enrich_index.enrich(
            index,
            FakeRegistry(
                {"tuna-os/example": {**FLATPAK_LABELS, **APPSTREAM_LABELS}}
            ),
            verbose=False,
        )
        # A complete entry needs no repair, no missing metadata, no empty frame.
        self.assertEqual(updated, 0)
        self.assertEqual(problems, [])
        self.assertEqual(warnings, [])
        self.assertNotIn("metainfo", stderr)

    def test_published_incomplete_entry_is_repaired_from_the_registry(self):
        index, stderr = publish(FLATPAK_LABELS)  # no AppStream labels on publish
        self.assertIn("metainfo", stderr)  # warned, as designed
        updated, problems, warnings = enrich_index.enrich(
            index,
            FakeRegistry(
                {"tuna-os/example": {**FLATPAK_LABELS, **APPSTREAM_LABELS}}
            ),
            verbose=False,
        )
        self.assertEqual(updated, 1)
        self.assertEqual(problems, [])
        labels = index["Results"][0]["Images"][0]["Labels"]
        self.assertIn("org.freedesktop.appstream.appdata", labels)

    def test_published_incomplete_entry_with_no_registry_metadata_is_a_problem(self):
        # The failure mode #145 is about: published bare, and the auditor cannot
        # repair it. The auditor must fail, not leave a bare entry standing.
        index, _ = publish(FLATPAK_LABELS)
        updated, problems, warnings = enrich_index.enrich(
            index, FakeRegistry({"tuna-os/example": {}}), verbose=False
        )
        self.assertEqual(updated, 0)
        self.assertEqual(len(problems), 1)
        self.assertIn("no AppStream metadata", problems[0])


if __name__ == "__main__":
    unittest.main()
