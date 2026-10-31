"""Unit tests for .github/actions/capture-screenshots/capture.py.

Tests target identity resolution, window matching rules, bounded deadline
logic, sensitive credential redaction, versioned receipt schema, and owned
process cleanup isolation.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ACTION_DIR = (
    Path(__file__).resolve().parent.parent / ".github" / "actions" / "capture-screenshots"
)
spec = importlib.util.spec_from_file_location("capture", ACTION_DIR / "capture.py")
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureArgumentParsingTests(unittest.TestCase):
    def test_legacy_positional_arguments(self):
        args = ["docs/shots", "01-main", "--", "myapp", "--flag"]
        parsed = capture.parse_arguments(args)
        self.assertEqual(parsed["out_dir"], "docs/shots")
        self.assertEqual(parsed["name"], "01-main")
        self.assertEqual(parsed["command_args"], ["myapp", "--flag"])
        self.assertEqual(parsed["geometry"], "1000x700")
        self.assertEqual(parsed["settle"], 6.0)
        self.assertTrue(parsed["required"])
        self.assertEqual(parsed["capture_mode"], "window")

    def test_explicit_flag_arguments(self):
        args = [
            "--out-dir=custom/dir",
            "--name=test-shot",
            "--geometry=800x600",
            "--settle=3.5",
            "--deadline=15.0",
            "--app-id=org.tunaos.tavern",
            "--wm-class=Tavern",
            "--readiness-predicate=test -f ready.txt",
            "--capture-mode=display",
            "--required=false",
            "--",
            "flatpak",
            "run",
            "org.tunaos.tavern",
        ]
        parsed = capture.parse_arguments(args)
        self.assertEqual(parsed["out_dir"], "custom/dir")
        self.assertEqual(parsed["name"], "test-shot")
        self.assertEqual(parsed["geometry"], "800x600")
        self.assertEqual(parsed["settle"], 3.5)
        self.assertEqual(parsed["deadline"], 15.0)
        self.assertEqual(parsed["app_id"], "org.tunaos.tavern")
        self.assertEqual(parsed["wm_class"], "Tavern")
        self.assertEqual(parsed["readiness_predicate"], "test -f ready.txt")
        self.assertEqual(parsed["capture_mode"], "display")
        self.assertFalse(parsed["required"])
        self.assertEqual(parsed["command_args"], ["flatpak", "run", "org.tunaos.tavern"])

    def test_environment_variable_fallbacks(self):
        env = {
            "OUT_DIR": "env/dir",
            "APP_NAME": "env-shot",
            "GEOMETRY": "1200x800",
            "SETTLE": "5",
            "DEADLINE": "25",
            "APP_ID": "org.tunaos.finupdate",
            "WM_CLASS": "Finupdate",
            "READINESS_PREDICATE": "echo ready",
            "CAPTURE_MODE": "window",
            "CAPTURE_REQUIRED": "1",
            "APP_COMMAND": "finupdate-gui --check",
        }
        with patch.dict(capture.os.environ, env, clear=False):
            parsed = capture.parse_arguments([])
            self.assertEqual(parsed["out_dir"], "env/dir")
            self.assertEqual(parsed["name"], "env-shot")
            self.assertEqual(parsed["geometry"], "1200x800")
            self.assertEqual(parsed["settle"], 5.0)
            self.assertEqual(parsed["deadline"], 25.0)
            self.assertEqual(parsed["app_id"], "org.tunaos.finupdate")
            self.assertEqual(parsed["wm_class"], "Finupdate")
            self.assertEqual(parsed["readiness_predicate"], "echo ready")
            self.assertTrue(parsed["required"])
            self.assertEqual(parsed["command_args"], ["finupdate-gui", "--check"])

    def test_missing_name_or_command_raises(self):
        with self.assertRaises(ValueError):
            capture.parse_arguments(["docs/shots"])
        with self.assertRaises(ValueError):
            capture.parse_arguments(["--out-dir=docs/shots", "--name=foo"])


class TargetIdentityInferenceTests(unittest.TestCase):
    def test_infer_flatpak_app_id(self):
        cmd = ["flatpak", "run", "--user", "--socket=x11", "org.tunaos.tavern"]
        self.assertEqual(capture.infer_target_identity(cmd), "org.tunaos.tavern")

    def test_infer_binary_name(self):
        cmd = ["/usr/bin/xclock", "-analog"]
        self.assertEqual(capture.infer_target_identity(cmd), "xclock")

    def test_infer_script_stem(self):
        cmd = ["python3", "./src/myapp.py"]
        self.assertEqual(capture.infer_target_identity(cmd), "myapp")


class WindowMatchingTests(unittest.TestCase):
    def test_matches_by_direct_pid(self):
        props = {"wid": "0x1", "wm_class": ["xclock", "XClock"], "wm_name": "xclock", "pid": 1234}
        matches, reason = capture.window_matches_target(
            props=props,
            req_app_id=None,
            req_wm_class=None,
            inferred_identity="xclock",
            app_pid=1234,
            descendant_pids=set(),
        )
        self.assertTrue(matches)
        self.assertIn("1234", reason)

    def test_matches_by_descendant_pid(self):
        props = {"wid": "0x2", "wm_class": ["child_app"], "wm_name": "Child", "pid": 5678}
        matches, reason = capture.window_matches_target(
            props=props,
            req_app_id=None,
            req_wm_class=None,
            inferred_identity=None,
            app_pid=1000,
            descendant_pids={5678},
        )
        self.assertTrue(matches)
        self.assertIn("5678", reason)

    def test_matches_by_explicit_wm_class(self):
        props = {"wid": "0x3", "wm_class": ["Tavern", "org.tunaos.tavern"], "wm_name": "Tavern"}
        matches, reason = capture.window_matches_target(
            props=props,
            req_app_id=None,
            req_wm_class="Tavern",
            inferred_identity=None,
            app_pid=9999,
            descendant_pids=set(),
        )
        self.assertTrue(matches)
        self.assertIn("Tavern", reason)

    def test_rejects_non_matching_explicit_wm_class(self):
        props = {"wid": "0x4", "wm_class": ["OtherApp"], "wm_name": "Other"}
        matches, reason = capture.window_matches_target(
            props=props,
            req_app_id=None,
            req_wm_class="ExpectedClass",
            inferred_identity=None,
            app_pid=9999,
            descendant_pids=set(),
        )
        self.assertFalse(matches)
        self.assertIn("Did not match", reason)

    def test_matches_by_explicit_app_id(self):
        props = {
            "wid": "0x5",
            "wm_class": ["org.tunaos.tavern", "org.tunaos.tavern"],
            "wm_name": "Tavern",
        }
        matches, reason = capture.window_matches_target(
            props=props,
            req_app_id="org.tunaos.tavern",
            req_wm_class=None,
            inferred_identity=None,
            app_pid=9999,
            descendant_pids=set(),
        )
        self.assertTrue(matches)
        self.assertIn("org.tunaos.tavern", reason)

    def test_rejects_unrelated_window(self):
        props = {
            "wid": "0x6",
            "wm_class": ["unrelated_calc", "Calculator"],
            "wm_name": "Calculator",
            "pid": 8888,
        }
        matches, reason = capture.window_matches_target(
            props=props,
            req_app_id="org.tunaos.tavern",
            req_wm_class=None,
            inferred_identity="tavern",
            app_pid=1111,
            descendant_pids={1112},
        )
        self.assertFalse(matches)
        self.assertIn("Did not match", reason)


class RedactionAndProvenanceTests(unittest.TestCase):
    def test_redacts_tokens_and_passwords(self):
        text = "myapp --token=ghp_123456789012345678901234567890123456 --password secret123"
        redacted = capture.redact_sensitive(text)
        self.assertNotIn("ghp_1234", redacted)
        self.assertNotIn("secret123", redacted)
        self.assertIn("***REDACTED***", redacted)

    def test_binary_provenance_verified_for_existing_executable(self):
        prov = capture.resolve_binary_provenance(["python3"])
        self.assertEqual(prov["digest_status"], "verified")
        self.assertTrue(len(prov["binary_sha256"]) == 64)
        self.assertTrue(Path(prov["binary_path"]).exists())

    def test_binary_provenance_unknown_for_missing_executable(self):
        prov = capture.resolve_binary_provenance(["nonexistent-binary-12345"])
        self.assertEqual(prov["digest_status"], "unknown")
        self.assertEqual(prov["binary_sha256"], "unknown")
        self.assertIsNone(prov["binary_path"])


class ReceiptSchemaTests(unittest.TestCase):
    def test_receipt_structure_and_outcome(self):
        req = {
            "out_dir": "/tmp/dummy",
            "name": "dummy-shot",
            "geometry": "1000x700",
            "settle": 1.0,
            "deadline": 5.0,
            "app_id": "org.tunaos.test",
            "wm_class": None,
            "readiness_predicate": None,
            "capture_mode": "window",
            "required": True,
            "display": ":99",
            "command_args": ["test-cmd"],
        }
        with tempfile.TemporaryDirectory() as td:
            req["out_dir"] = td
            with (
                patch("shutil.which", return_value=None),
                patch("pathlib.Path.unlink"),
            ):
                code, receipt = capture.execute_capture(req)
                self.assertEqual(receipt["schema_version"], 1)
                self.assertIn("requested", receipt)
                self.assertIn("observed", receipt)
                self.assertIn("provenance", receipt)
                self.assertIn("environment", receipt)
                self.assertIn("predicates", receipt)
                self.assertIn("timing", receipt)
                self.assertIn("artifacts", receipt)
                self.assertIn("diagnostics", receipt)
                self.assertIn("cleanup", receipt)
                self.assertIn(
                    receipt["outcome"],
                    ["passed", "failed", "blocked", "not_run", "unsupported", "flaky"],
                )
                self.assertEqual(receipt["outcome"], "blocked")
                self.assertIsNone(receipt["artifacts"]["image_path"])
                self.assertTrue(receipt["artifacts"]["receipt_path"].endswith(".receipt.json"))


class ProcessCleanupTests(unittest.TestCase):
    def test_cleanup_only_signals_owned_processes(self):
        mock_xvfb = MagicMock()
        mock_xvfb.pid = 2001
        mock_xvfb.poll.return_value = 0

        mock_app = MagicMock()
        mock_app.pid = 2002
        mock_app.poll.return_value = 0

        with (
            patch.object(capture, "get_descendants", return_value={2003}),
            patch("os.killpg") as mock_killpg,
            patch("pathlib.Path.unlink"),
        ):
            res = capture.cleanup_owned_processes(mock_xvfb, mock_app, ":99")
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["owned_pids"], [2001, 2002, 2003])
            self.assertEqual(res["unrelated_pids_affected"], 0)
            mock_killpg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
