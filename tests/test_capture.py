"""Unit tests for .github/actions/capture-screenshots/capture.py.

Tests target identity resolution, window matching rules, bounded deadline
logic, sensitive credential redaction, versioned receipt schema, and owned
process cleanup isolation.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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

    def test_space_separated_options_keep_values_with_legacy_paths(self):
        parsed = capture.parse_arguments([
            "docs/shots", "--geometry=800x600", "main", "--deadline", "15", "--settle", "0.5",
            "--readiness-predicate", "test -f ready.txt", "--", "xclock", "-analog",
        ])
        self.assertEqual(parsed["out_dir"], "docs/shots")
        self.assertEqual(parsed["name"], "main")
        self.assertEqual(parsed["geometry"], "800x600")
        self.assertEqual(parsed["deadline"], 15.0)
        self.assertEqual(parsed["settle"], 0.5)
        self.assertEqual(parsed["readiness_predicate"], "test -f ready.txt")
        self.assertEqual(parsed["command_args"], ["xclock", "-analog"])

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

    def test_redacts_standalone_github_credentials_without_preserving_token(self):
        for token in ("ghp_" + "a" * 36, "github_pat_" + "b" * 60):
            with self.subTest(prefix=token.split("_")[0]):
                self.assertEqual(
                    capture.redact_sensitive(f"before {token} after"),
                    "before ***REDACTED*** after",
                )

    def test_redacts_every_github_token_prefix(self):
        # ghs_ is the Actions token of the job that commits the receipt.
        for prefix in ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"):
            with self.subTest(prefix=prefix):
                self.assertEqual(
                    capture.redact_sensitive(f"before {prefix}{'a' * 36} after"),
                    "before ***REDACTED*** after",
                )

    def test_redacts_url_passwords_env_assignments_and_auth_headers(self):
        cases = {
            "curl -fsS https://bot:hunter2@127.0.0.1:8080/health":
                "curl -fsS https://bot:***REDACTED***@127.0.0.1:8080/health",
            "git clone https://x-access-token:p@ss@github.com/o/r":
                "git clone https://x-access-token:***REDACTED***@github.com/o/r",
            "env API_TOKEN=hunter2 myapp": "env API_TOKEN=***REDACTED*** myapp",
            'DB_PASSWORD="two words" myapp': "DB_PASSWORD=***REDACTED*** myapp",
            "AUTHORIZATION: basic aHVudGVyMg==": "AUTHORIZATION: basic ***REDACTED***",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(capture.redact_sensitive(text), expected)

    def test_redaction_keeps_ordinary_diagnostics(self):
        for text in (
            "curl -fsS http://127.0.0.1:8080/health",
            "DISPLAY=:99 GDK_BACKEND=x11 myapp --geometry=1000x700",
            "mail user@example.org about https://example.org/a:b@c",
        ):
            with self.subTest(text=text):
                self.assertEqual(capture.redact_sensitive(text), text)

    def test_binary_provenance_verified_for_existing_executable(self):
        prov = capture.resolve_binary_provenance(["python3"])
        self.assertEqual(prov["digest_status"], "verified")
        expected_path = Path(shutil.which("python3")).resolve()
        self.assertEqual(Path(prov["binary_path"]).resolve(), expected_path)
        with expected_path.open("rb") as executable:
            expected_digest = hashlib.file_digest(executable, "sha256").hexdigest()
        self.assertEqual(prov["binary_sha256"], expected_digest)

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


class XWindowQueryTests(unittest.TestCase):
    """The xprop/xdotool/xwininfo wrappers that feed window matching."""

    def test_window_properties_parse_class_name_and_pid(self):
        outputs = [
            'WM_CLASS(STRING) = "xclock", "XClock"\n',
            'WM_NAME(STRING) = "analog clock"\n_NET_WM_NAME(UTF8_STRING) = "ignored"\n',
            "_NET_WM_PID(CARDINAL) = 4242\n",
        ]
        with patch("subprocess.check_output", side_effect=outputs) as run:
            props = capture.get_window_properties("0x1", ":99")
        self.assertEqual(props["wm_class"], ["xclock", "XClock"])
        self.assertEqual(props["wm_name"], "analog clock")
        self.assertEqual(props["pid"], 4242)
        self.assertEqual(run.call_args.kwargs["env"]["DISPLAY"], ":99")

    def test_window_properties_default_when_xprop_fails(self):
        with patch("subprocess.check_output", side_effect=OSError("no xprop")):
            props = capture.get_window_properties("0x1", ":99")
        self.assertEqual(
            props, {"wid": "0x1", "wm_class": [], "wm_name": None, "pid": None}
        )

    def test_window_properties_ignore_non_numeric_pid_and_empty_name(self):
        outputs = [
            "WM_CLASS(STRING) = \n",
            'WM_NAME(STRING) = ""\n',
            "_NET_WM_PID(CARDINAL) = not-a-pid\n",
        ]
        with patch("subprocess.check_output", side_effect=outputs):
            props = capture.get_window_properties("0x1", ":99")
        self.assertEqual(props["wm_class"], [])
        self.assertIsNone(props["wm_name"])
        self.assertIsNone(props["pid"])

    def test_list_visible_windows_splits_ids_and_drops_blank_lines(self):
        with patch("subprocess.check_output", return_value="123\n\n 456 \n"):
            self.assertEqual(capture.list_visible_windows(":99"), ["123", "456"])

    def test_list_visible_windows_is_empty_when_xdotool_fails(self):
        with patch("subprocess.check_output", side_effect=FileNotFoundError):
            self.assertEqual(capture.list_visible_windows(":99"), [])

    def test_is_window_valid_follows_xwininfo_exit_status(self):
        for returncode, expected in ((0, True), (1, False)):
            with patch("subprocess.run", return_value=Mock(returncode=returncode)):
                self.assertIs(capture.is_window_valid("0x1", ":99"), expected)

    def test_is_window_valid_is_false_when_xwininfo_is_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(capture.is_window_valid("0x1", ":99"))


class DisplayAndProcessTests(unittest.TestCase):
    def test_pick_display_skips_displays_with_a_lock_or_socket(self):
        taken = {"/tmp/.X97-lock", "/tmp/.X11-unix/X98"}
        with patch.object(Path, "exists", lambda self: str(self) in taken):
            self.assertEqual(capture.pick_display(), ":99")

    def test_pick_display_raises_when_every_display_is_taken(self):
        with (
            patch.object(Path, "exists", return_value=True),
            self.assertRaises(capture.DisplayInitError),
        ):
            capture.pick_display()

    def test_is_pid_alive(self):
        self.assertTrue(capture.is_pid_alive(os.getpid()))
        self.assertFalse(capture.is_pid_alive(0))
        self.assertFalse(capture.is_pid_alive(-1))
        with patch("os.kill", side_effect=ProcessLookupError):
            self.assertFalse(capture.is_pid_alive(12345))

    def test_get_descendants_walks_the_whole_tree(self):
        children = {1: "2\n3\n", 2: "4\n", 3: "", 4: ""}

        def pgrep(cmd, **_kwargs):
            return children[int(cmd[-1])]

        with patch("subprocess.check_output", side_effect=pgrep):
            self.assertEqual(capture.get_descendants(1), {2, 3, 4})

    def test_get_descendants_falls_back_to_proc_when_pgrep_is_missing(self):
        with tempfile.TemporaryDirectory() as td:
            task = Path(td) / "7" / "task" / "7"
            task.mkdir(parents=True)
            (task / "children").write_text("8 9\n")
            real_path = Path

            def fake_path(arg):
                return real_path(arg.replace("/proc", td, 1))

            with (
                patch("subprocess.check_output", side_effect=FileNotFoundError),
                patch.object(capture, "Path", fake_path),
            ):
                self.assertEqual(capture.get_descendants(7), {8, 9})

    def test_cleanup_reports_success_when_owned_processes_exit(self):
        app = Mock(pid=500)
        app.poll.return_value = 0
        xvfb = Mock(pid=501)
        xvfb.poll.return_value = 0
        with (
            patch.object(capture, "get_descendants", return_value={502}),
            patch.object(capture, "is_pid_alive", return_value=False),
        ):
            result = capture.cleanup_owned_processes(xvfb, app)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["owned_pids"], [500, 501, 502])
        self.assertEqual(result["unrelated_pids_affected"], 0)

    def test_cleanup_sigterms_running_process_groups(self):
        app = Mock(pid=500)
        app.poll.return_value = None
        with (
            patch.object(capture, "get_descendants", return_value=set()),
            patch.object(capture, "is_pid_alive", return_value=False),
            patch("os.killpg") as killpg,
        ):
            capture.cleanup_owned_processes(None, app)
        killpg.assert_called_once_with(500, capture.signal.SIGTERM)

    def test_cleanup_kills_survivors_and_fails_if_they_stay_alive(self):
        app = Mock(pid=500)
        app.poll.return_value = None
        # Fake clock jumps past the wait deadline so the test does not sleep 2s.
        ticks = iter([0.0, 10.0])
        with (
            patch.object(capture, "get_descendants", return_value=set()),
            patch.object(capture, "is_pid_alive", return_value=True),
            patch("time.monotonic", side_effect=lambda: next(ticks)),
            patch("time.sleep"),
            patch("os.killpg") as killpg,
            patch("os.kill") as kill,
        ):
            result = capture.cleanup_owned_processes(None, app)
        killpg.assert_any_call(500, capture.signal.SIGKILL)
        kill.assert_any_call(500, capture.signal.SIGKILL)
        self.assertEqual(result["status"], "failed")
        self.assertIn("500", result["details"])

    def test_cleanup_reports_sigterm_errors(self):
        app = Mock(pid=500)
        app.poll.return_value = None
        with (
            patch.object(capture, "get_descendants", return_value=set()),
            patch.object(capture, "is_pid_alive", return_value=False),
            patch("os.killpg", side_effect=PermissionError("denied")),
        ):
            result = capture.cleanup_owned_processes(None, app)
        self.assertEqual(result["status"], "failed")
        self.assertIn("denied", result["details"])

    def test_cleanup_ignores_a_process_group_that_already_exited(self):
        app = Mock(pid=500)
        app.poll.return_value = None
        with (
            patch.object(capture, "get_descendants", return_value=set()),
            patch.object(capture, "is_pid_alive", return_value=False),
            patch("os.killpg", side_effect=ProcessLookupError),
        ):
            result = capture.cleanup_owned_processes(None, app)
        self.assertEqual(result["status"], "success")


if __name__ == "__main__":
    unittest.main()
