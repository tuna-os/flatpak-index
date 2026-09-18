"""Tests for scripts/oci.py, the read-only OCI registry client.

Before this file, nothing in the test suite imported oci.py at all: no test
exercised token auth, retry/backoff on a failing curl, or the manifest-list
vs. image-manifest branch in Registry.image_labels. A regression in any of
those (e.g. a token that's fetched but never cached, or a manifest-list
image silently treated as an image manifest) would ship unnoticed.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import oci  # noqa: E402


def _completed(returncode=0, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess(
        args=["curl"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class KeepLabelTests(unittest.TestCase):
    def test_flatpak_prefixed_label_is_kept(self):
        self.assertTrue(oci.keep_label("org.flatpak.ref"))

    def test_appstream_prefixed_label_is_kept(self):
        self.assertTrue(oci.keep_label("org.freedesktop.appstream.appdata"))

    def test_unrelated_label_is_dropped(self):
        self.assertFalse(oci.keep_label("org.opencontainers.image.source"))

    def test_filter_labels_keeps_only_recognised_prefixes(self):
        labels = {
            "org.flatpak.ref": "app/org.tunaos.demo/x86_64/stable",
            "org.freedesktop.appstream.appdata": "<components/>",
            "org.opencontainers.image.source": "https://example/repo",
        }
        self.assertEqual(
            oci.filter_labels(labels),
            {
                "org.flatpak.ref": "app/org.tunaos.demo/x86_64/stable",
                "org.freedesktop.appstream.appdata": "<components/>",
            },
        )

    def test_filter_labels_tolerates_none(self):
        self.assertEqual(oci.filter_labels(None), {})


class CurlRetryTests(unittest.TestCase):
    @mock.patch("oci.time.sleep")
    @mock.patch("oci.subprocess.run")
    def test_succeeds_on_first_attempt(self, run, sleep):
        run.return_value = _completed(0, b'{"ok": true}')
        result = oci._curl("https://example/x")
        self.assertEqual(result, b'{"ok": true}')
        run.assert_called_once()
        sleep.assert_not_called()

    @mock.patch("oci.time.sleep")
    @mock.patch("oci.subprocess.run")
    def test_retries_then_succeeds(self, run, sleep):
        run.side_effect = [_completed(22, b"", b"HTTP 500"), _completed(0, b'{"ok": true}')]
        result = oci._curl("https://example/x")
        self.assertEqual(result, b'{"ok": true}')
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(1)  # 2 ** 0

    @mock.patch("oci.time.sleep")
    @mock.patch("oci.subprocess.run")
    def test_exhausts_attempts_and_raises_registry_error(self, run, sleep):
        run.return_value = _completed(22, b"", b"HTTP 404 not found")
        with self.assertRaises(oci.RegistryError) as ctx:
            oci._curl("https://example/missing", attempts=4)
        self.assertEqual(run.call_count, 4)
        self.assertIn("HTTP 404 not found", str(ctx.exception))
        self.assertIn("rc=22", str(ctx.exception))

    @mock.patch("oci.time.sleep")
    @mock.patch("oci.subprocess.run")
    def test_blank_stdout_on_success_is_treated_as_a_failure(self, run, sleep):
        # returncode 0 with empty stdout is what curl gives on some
        # transparent-proxy failures; it must not be mistaken for a real body.
        run.return_value = _completed(0, b"   ", b"")
        with self.assertRaises(oci.RegistryError):
            oci._curl("https://example/x", attempts=1)

    @mock.patch("oci.time.sleep")
    @mock.patch("oci.subprocess.run")
    def test_headers_are_passed_through_to_curl(self, run, sleep):
        run.return_value = _completed(0, b"{}")
        oci._curl("https://example/x", headers=("Authorization: Bearer t",))
        called_cmd = run.call_args.args[0]
        self.assertIn("Authorization: Bearer t", called_cmd)


class RegistryAuthTests(unittest.TestCase):
    def test_static_token_skips_the_network(self):
        registry = oci.Registry("ghcr.io", token="fixed-token")
        with mock.patch("oci._curl") as curl:
            header = registry._auth_header("tuna-os/demo")
        curl.assert_not_called()
        self.assertEqual(header, "Authorization: Bearer fixed-token")

    @mock.patch("oci._curl")
    def test_anonymous_token_is_fetched_and_cached(self, curl):
        curl.return_value = b'{"token": "anon-token"}'
        registry = oci.Registry("ghcr.io")
        first = registry._auth_header("tuna-os/demo")
        second = registry._auth_header("tuna-os/demo")
        self.assertEqual(first, "Authorization: Bearer anon-token")
        self.assertEqual(second, "Authorization: Bearer anon-token")
        curl.assert_called_once()  # cached on the second call

    @mock.patch("oci._curl")
    def test_access_token_key_is_also_accepted(self, curl):
        curl.return_value = b'{"access_token": "anon-token"}'
        registry = oci.Registry("ghcr.io")
        self.assertEqual(
            registry._auth_header("tuna-os/demo"), "Authorization: Bearer anon-token"
        )

    @mock.patch("oci._curl")
    def test_refused_anonymous_pull_raises_registry_error(self, curl):
        curl.return_value = b'{"error": "denied"}'
        registry = oci.Registry("ghcr.io")
        with self.assertRaises(oci.RegistryError) as ctx:
            registry._auth_header("tuna-os/private")
        self.assertIn("tuna-os/private", str(ctx.exception))


class RegistryImageLabelsTests(unittest.TestCase):
    def _registry(self):
        return oci.Registry("ghcr.io", token="t")

    @mock.patch("oci._curl")
    def test_returns_the_configs_labels_unfiltered(self, curl):
        # Filtering to the flatpak/appstream prefixes is the caller's job
        # (see filter_labels) -- image_labels hands back whatever the
        # config blob says, so a caller that wants everything still can.
        curl.side_effect = [
            b'{"config": {"digest": "sha256:abc"}}',
            b'{"config": {"Labels": {"org.flatpak.ref": "x", "unrelated": "y"}}}',
        ]
        labels = self._registry().image_labels("tuna-os/demo", "latest")
        self.assertEqual(labels, {"org.flatpak.ref": "x", "unrelated": "y"})

    @mock.patch("oci._curl")
    def test_missing_labels_key_returns_empty_dict(self, curl):
        curl.side_effect = [
            b'{"config": {"digest": "sha256:abc"}}',
            b'{"config": {}}',
        ]
        self.assertEqual(self._registry().image_labels("tuna-os/demo", "latest"), {})

    @mock.patch("oci._curl")
    def test_manifest_list_is_rejected(self, curl):
        # A manifest list has no top-level "config" key -- only per-arch
        # manifests do. Reading it as an image manifest would silently
        # produce an empty label set instead of failing loudly.
        curl.return_value = b'{"manifests": [{"digest": "sha256:one"}]}'
        with self.assertRaises(oci.RegistryError) as ctx:
            self._registry().image_labels("tuna-os/demo", "latest")
        self.assertIn("manifest list", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
