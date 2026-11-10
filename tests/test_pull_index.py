"""Security boundaries of the index-owner pull publisher (no live registry)."""

import copy
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pull_index", ROOT / "scripts/pull-index.py")
pull = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pull)

SOURCE = {
    "repository": "tuna-os/example",
    "tag": "latest",
    "architecture": "amd64",
    "ref": "app/org.tunaos.example/x86_64/master",
}
LABELS = {
    "org.flatpak.ref": SOURCE["ref"],
    "org.flatpak.metadata": "[Application]\nname=org.tunaos.example\n",
    **{label: "metadata" for label in pull.updater.APPSTREAM_LABELS},
}


def image_bytes(labels=None, architecture="amd64", os_name="linux"):
    config = json.dumps({"os": os_name, "architecture": architecture,
                         "config": {"Labels": LABELS if labels is None else labels}}).encode()
    manifest = json.dumps({"mediaType": "application/vnd.oci.image.manifest.v1+json",
                           "config": {"digest": digest(config)}}).encode()
    return manifest, config


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class PullTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.policy = self.root / "sources.json"
        self.policy.write_text(json.dumps([SOURCE]))
        self.index = self.root / "index"
        self.index.write_text(json.dumps({"Registry": "https://ghcr.io", "Results": []}))
        self.before = self.index.read_bytes()

    def test_policy_rejects_injection_and_ambiguous_ownership(self):
        cases = [
            [{**SOURCE, "repository": "other-org/example"}],
            [{**SOURCE, "repository": "tuna-os/../evil"}],
            [{**SOURCE, "tag": "latest;id"}],
            [{**SOURCE, "tag": "--help"}],
            [{**SOURCE, "architecture": "s390x"}],
            [{**SOURCE, "ref": "app/org.tunaos.example/aarch64/master"}],
            [{**SOURCE, "index-file": "/tmp/elsewhere"}],
            [{**SOURCE, "tags": ["other"]}],
            [{**SOURCE, "tags": ["latest", "latest"]}],
            [{**SOURCE, "tags": "latest"}],
            [SOURCE, {**SOURCE, "repository": "tuna-os/another"}],
            [],
        ]
        for policy in cases:
            with self.subTest(policy=policy):
                self.policy.write_text(json.dumps(policy))
                with self.assertRaises(ValueError):
                    pull.read_policy(self.policy)

    def test_inspect_uses_fixed_registry_without_layers_or_credentials(self):
        with patch.object(pull.subprocess, "run") as run:
            run.return_value.stdout = b"raw bytes"
            self.assertEqual(pull.inspect(SOURCE, ":latest"), b"raw bytes")
        run.assert_called_once_with([
            "skopeo", "--override-os", "linux", "--override-arch", "amd64",
            "inspect", "--raw", "--no-creds", "--tls-verify=true", "--retry-times", "3",
            "docker://ghcr.io/tuna-os/example:latest",
        ], check=True, stdout=subprocess.PIPE)

    def test_pull_retains_digest_and_metadata(self):
        manifest, config = image_bytes()
        with patch.object(pull, "inspect", side_effect=[manifest, config]) as inspect:
            entry = pull.pull_entry(SOURCE)
        self.assertEqual(entry["Digest"], digest(manifest))
        self.assertEqual(entry["Labels"], LABELS)
        self.assertEqual(entry["Tags"], ["latest"])
        inspect.assert_any_call(SOURCE, "@" + digest(manifest), config=True)

    def test_multiarch_selects_exact_platform_and_checks_digest(self):
        manifest, config = image_bytes()
        index = json.dumps({"manifests": [
            {"platform": {"os": "linux", "architecture": "arm64"}, "digest": "unused"},
            {"platform": {"os": "linux", "architecture": "amd64"}, "digest": digest(manifest)},
        ]}).encode()
        with patch.object(pull, "inspect", side_effect=[index, manifest, config]):
            self.assertEqual(pull.pull_entry(SOURCE)["Digest"], digest(manifest))
        with patch.object(pull, "inspect", side_effect=[index, b"{}"]), self.assertRaisesRegex(
            ValueError, "digest mismatch"
        ):
            pull.pull_entry(SOURCE)

    def test_reviewed_tag_aliases_survive_refresh(self):
        source = {**SOURCE, "tags": ["latest", "gnome"]}
        self.policy.write_text(json.dumps([source]))
        pull.read_policy(self.policy)
        with patch.object(pull, "inspect", side_effect=image_bytes()):
            self.assertEqual(pull.pull_entry(source)["Tags"], ["latest", "gnome"])

    def test_rejects_wrong_app_platform_and_missing_appstream(self):
        variants = [
            {"labels": {**LABELS, "org.flatpak.ref": "app/org.tunaos.victim/x86_64/master"}},
            {"architecture": "arm64"},
            {"os_name": "windows"},
            {"labels": {k: v for k, v in LABELS.items() if not k.startswith(
                "org.freedesktop.appstream.")}},
        ]
        for variant in variants:
            with (
                self.subTest(variant=variant),
                patch.object(pull, "inspect", side_effect=image_bytes(**variant)),
                self.assertRaises(ValueError),
            ):
                pull.pull_entry(SOURCE)

    def test_rejects_tampered_config(self):
        manifest, _ = image_bytes()
        with patch.object(pull, "inspect", side_effect=[manifest, b"{}"]), self.assertRaisesRegex(
            ValueError, "digest mismatch"
        ):
            pull.pull_entry(SOURCE)

    def test_rejects_invalid_digest(self):
        with self.assertRaises(ValueError):
            pull.verify_blob(b"{}", "sha256:../../secret")

    def test_later_failure_preserves_original_index(self):
        self.policy.write_text(json.dumps([
            SOURCE, {**SOURCE, "ref": "app/org.tunaos.second/x86_64/master"},
        ]))
        entry = pull.updater.build_image_entry("sha256:" + "a" * 64,
                                              {"config": {"Labels": LABELS}}, ["latest"], True)
        with patch.object(pull, "pull_entry", side_effect=[entry, subprocess.CalledProcessError(
            1, "skopeo"
        )]), self.assertRaises(subprocess.CalledProcessError):
            pull.refresh(self.policy, self.index)
        self.assertEqual(self.index.read_bytes(), self.before)

    def test_refresh_preserves_unlisted_app_and_is_repeatable(self):
        other = {"Name": "tuna-os/unlisted", "Images": []}
        self.index.write_text(json.dumps({"Registry": "https://ghcr.io", "Results": [other]}))
        entry = pull.updater.build_image_entry("sha256:" + "a" * 64,
                                              {"config": {"Labels": LABELS}}, ["latest"], True)
        with patch.object(pull, "pull_entry", return_value=entry):
            pull.refresh(self.policy, self.index)
            first = self.index.read_bytes()
            pull.refresh(self.policy, self.index)
        self.assertEqual(first, self.index.read_bytes())
        self.assertIn(other, json.loads(first)["Results"])

    def test_existing_ref_cannot_be_claimed_by_another_repository(self):
        image = {"Architecture": "amd64", "Labels": copy.deepcopy(LABELS)}
        self.index.write_text(json.dumps({"Registry": "https://ghcr.io", "Results": [
            {"Name": "tuna-os/victim", "Images": [image]},
        ]}))
        with patch.object(pull, "pull_entry") as fetch, self.assertRaisesRegex(
            ValueError, "conflicts with policy"
        ):
            pull.refresh(self.policy, self.index)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
