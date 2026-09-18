"""Unit tests for scripts/oci.py — the OCI registry client helper.

All HTTP and subprocess interactions are mocked to enable fast, offline,
deterministic testing.
"""

import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from scripts import oci


class LabelFilterTests(unittest.TestCase):
    def test_keep_label(self):
        self.assertTrue(oci.keep_label("org.flatpak.ref"))
        self.assertTrue(oci.keep_label("org.flatpak.metadata"))
        self.assertTrue(oci.keep_label("org.freedesktop.appstream.appdata"))
        self.assertTrue(oci.keep_label("org.freedesktop.appstream.icon-64"))
        self.assertFalse(oci.keep_label("org.opencontainers.image.created"))
        self.assertFalse(oci.keep_label("maintainer"))

    def test_filter_labels(self):
        labels = {
            "org.flatpak.ref": "app/org.tunaos.letters/x86_64/master",
            "org.freedesktop.appstream.appdata": "<components/>",
            "custom.label": "ignored",
        }
        filtered = oci.filter_labels(labels)
        self.assertEqual(
            filtered,
            {
                "org.flatpak.ref": "app/org.tunaos.letters/x86_64/master",
                "org.freedesktop.appstream.appdata": "<components/>",
            },
        )

    def test_filter_labels_none_or_empty(self):
        self.assertEqual(oci.filter_labels(None), {})
        self.assertEqual(oci.filter_labels({}), {})


class CurlTests(unittest.TestCase):
    @patch("subprocess.run")
    def test_curl_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=b'{"token": "xyz"}\n')
        out = oci._curl("https://ghcr.io/token", headers=["Accept: application/json"])
        self.assertEqual(out, b'{"token": "xyz"}\n')
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("https://ghcr.io/token", cmd)
        self.assertIn("-H", cmd)
        self.assertIn("Accept: application/json", cmd)

    @patch("time.sleep")
    @patch("subprocess.run")
    def test_curl_retry_and_failure(self, mock_run, mock_sleep):
        mock_run.return_value = MagicMock(
            returncode=22, stdout=b"", stderr=b"404 Not Found"
        )
        with self.assertRaises(oci.RegistryError) as ctx:
            oci._curl("https://ghcr.io/missing", attempts=3)
        self.assertIn("404 Not Found", str(ctx.exception))
        self.assertEqual(mock_run.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)


class RegistryTests(unittest.TestCase):
    def test_init_parses_host(self):
        reg = oci.Registry("https://ghcr.io")
        self.assertEqual(reg.host, "ghcr.io")

        reg2 = oci.Registry("https://registry.example.com/v2")
        self.assertEqual(reg2.host, "registry.example.com")

    def test_auth_header_static_token(self):
        reg = oci.Registry("https://ghcr.io", token="secret-token")
        self.assertEqual(reg._auth_header("tuna-os/letters"), "Authorization: Bearer secret-token")

    @patch.object(oci, "_curl")
    def test_auth_header_fetch_token(self, mock_curl):
        mock_curl.return_value = json.dumps({"token": "bearer-123"}).encode("utf-8")
        reg = oci.Registry("https://ghcr.io")
        header = reg._auth_header("tuna-os/letters")
        self.assertEqual(header, "Authorization: Bearer bearer-123")
        # Ensure cached token is reused
        header2 = reg._auth_header("tuna-os/letters")
        self.assertEqual(header2, "Authorization: Bearer bearer-123")
        mock_curl.assert_called_once()

    @patch.object(oci, "_curl")
    def test_auth_header_missing_token_raises(self, mock_curl):
        mock_curl.return_value = json.dumps({"error": "denied"}).encode("utf-8")
        reg = oci.Registry("https://ghcr.io")
        with self.assertRaises(oci.RegistryError) as ctx:
            reg._auth_header("tuna-os/letters")
        self.assertIn("refused an anonymous pull token", str(ctx.exception))

    @patch.object(oci, "_curl")
    def test_manifest_and_blob(self, mock_curl):
        reg = oci.Registry("https://ghcr.io", token="tok")
        mock_curl.return_value = json.dumps({"schemaVersion": 2}).encode("utf-8")

        manifest = reg.manifest("tuna-os/letters", "latest")
        self.assertEqual(manifest, {"schemaVersion": 2})

        blob = reg.blob("tuna-os/letters", "sha256:abc")
        self.assertEqual(blob, {"schemaVersion": 2})

    @patch.object(oci.Registry, "manifest")
    @patch.object(oci.Registry, "blob")
    def test_image_labels_success(self, mock_blob, mock_manifest):
        mock_manifest.return_value = {
            "config": {"digest": "sha256:1111", "size": 100}
        }
        mock_blob.return_value = {
            "config": {
                "Labels": {
                    "org.flatpak.ref": "app/org.tunaos.letters/x86_64/master"
                }
            }
        }
        reg = oci.Registry("https://ghcr.io", token="tok")
        labels = reg.image_labels("tuna-os/letters", "latest")
        self.assertEqual(
            labels,
            {"org.flatpak.ref": "app/org.tunaos.letters/x86_64/master"},
        )

    @patch.object(oci.Registry, "manifest")
    def test_image_labels_manifest_list_error(self, mock_manifest):
        mock_manifest.return_value = {
            "manifests": [{"digest": "sha256:2222"}]
        }
        reg = oci.Registry("https://ghcr.io", token="tok")
        with self.assertRaises(oci.RegistryError) as ctx:
            reg.image_labels("tuna-os/letters", "latest")
        self.assertIn("manifest list, not an image manifest", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
