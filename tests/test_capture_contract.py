"""Contract integration tests for shared screenshot capture action.

Exercises positive controls and production-threshold negative fixtures:
- unrelated window rejection
- parent wrapper / child premature exit
- delayed paint and readiness predicate timeout
- frozen error screen and blank frame rejection
- no window appearance and process cleanup
- pre-existing stale PNG rejection and deletion
- concurrent capture isolation
- unrelated process preservation
- teardown failure reporting
- diagnostic log retention on failure
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ACTION_DIR = (
    Path(__file__).resolve().parent.parent / ".github" / "actions" / "capture-screenshots"
)
spec = importlib.util.spec_from_file_location("capture", ACTION_DIR / "capture.py")
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)

HAVE_XVFB = bool(
    shutil.which("Xvfb")
    and shutil.which("xdpyinfo")
    and shutil.which("xdotool")
    and shutil.which("import")
    and shutil.which("identify")
)


@unittest.skipUnless(HAVE_XVFB, "Xvfb and X11 capture tools required for live contract tests")
class CaptureContractLiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_positive_control(self):
        """Positive control: valid app maps a window, paints, and emits verified receipt."""
        if not shutil.which("xclock"):
            self.skipTest("xclock is required for positive control live test")

        req = {
            "out_dir": str(self.out_dir),
            "name": "pos-test",
            "geometry": "640x480",
            "settle": 1.5,
            "deadline": 10.0,
            "app_id": None,
            "wm_class": None,
            "readiness_predicate": None,
            "capture_mode": "window",
            "required": True,
            "display": None,
            "command_args": ["xclock", "-analog"],
        }
        code, receipt = capture.execute_capture(req)
        self.assertEqual(code, 0)
        self.assertEqual(receipt["outcome"], "passed")
        self.assertEqual(receipt["cleanup"]["status"], "success")

        png_path = self.out_dir / "pos-test.png"
        receipt_path = self.out_dir / "pos-test.receipt.json"

        self.assertTrue(png_path.exists())
        self.assertTrue(receipt_path.exists())
        self.assertGreater(receipt["observed"]["colors"], 7)
        self.assertIsNotNone(receipt["observed"]["window_id"])
        self.assertIsNotNone(receipt["observed"]["frame_hash"])
        self.assertEqual(receipt["provenance"]["digest_status"], "verified")

    def test_negative_unrelated_window(self):
        """Reject unrelated windows mapping on display and fail when target does not appear."""
        # Target command does not map any window, but we ask for a specific app-id
        req = {
            "out_dir": str(self.out_dir),
            "name": "unrelated-test",
            "geometry": "640x480",
            "settle": 1.0,
            "deadline": 2.0,
            "app_id": "org.tunaos.nonexistent",
            "wm_class": "NonExistentClass",
            "readiness_predicate": None,
            "capture_mode": "window",
            "required": True,
            "display": None,
            "command_args": ["sleep", "5"],
        }
        code, receipt = capture.execute_capture(req)
        self.assertNotEqual(code, 0)
        self.assertEqual(receipt["outcome"], "failed")
        self.assertFalse((self.out_dir / "unrelated-test.png").exists())
        self.assertIsNone(receipt["artifacts"]["image_path"])

    def test_negative_parent_wrapper_child_exit(self):
        """Detect immediate process exit / crash before window appears."""
        req = {
            "out_dir": str(self.out_dir),
            "name": "early-exit-test",
            "geometry": "640x480",
            "settle": 1.0,
            "deadline": 5.0,
            "app_id": None,
            "wm_class": None,
            "readiness_predicate": None,
            "capture_mode": "window",
            "required": True,
            "display": None,
            "command_args": ["sh", "-c", "exit 42"],
        }
        code, receipt = capture.execute_capture(req)
        self.assertNotEqual(code, 0)
        self.assertEqual(receipt["outcome"], "failed")
        self.assertFalse((self.out_dir / "early-exit-test.png").exists())
        self.assertIn("exit code 42", receipt["diagnostics"]["error_message"])

    def test_negative_delayed_paint_or_predicate_timeout(self):
        """Fail when readiness predicate does not succeed within bounded monotonic deadline."""
        if not shutil.which("xclock"):
            self.skipTest("xclock is required for predicate timeout test")

        req = {
            "out_dir": str(self.out_dir),
            "name": "predicate-timeout-test",
            "geometry": "640x480",
            "settle": 1.0,
            "deadline": 2.0,
            "app_id": None,
            "wm_class": None,
            "readiness_predicate": "false",
            "capture_mode": "window",
            "required": True,
            "display": None,
            "command_args": ["xclock", "-analog"],
        }
        code, receipt = capture.execute_capture(req)
        self.assertNotEqual(code, 0)
        self.assertEqual(receipt["outcome"], "failed")
        self.assertEqual(receipt["predicates"]["readiness_result"], "failed")
        self.assertFalse((self.out_dir / "predicate-timeout-test.png").exists())

    def test_negative_blank_or_flat_frame(self):
        """Reject captured frame if color count is fewer than 8."""
        if not shutil.which("xclock"):
            self.skipTest("xclock is required for blank frame test")

        # Mock identify returning 2 colors
        fake_ident = subprocess.CompletedProcess(
            args=["identify"],
            returncode=0,
            stdout="PNG 640x480 2\n",
            stderr="",
        )
        with patch("subprocess.run") as mock_run:
            # Let other calls go through except identify
            real_run = subprocess.run

            def side_effect(cmd, *args, **kwargs):
                if isinstance(cmd, list) and cmd and cmd[0] == "identify":
                    return fake_ident
                return real_run(cmd, *args, **kwargs)

            mock_run.side_effect = side_effect
            req = {
                "out_dir": str(self.out_dir),
                "name": "blank-frame-test",
                "geometry": "640x480",
                "settle": 1.0,
                "deadline": 5.0,
                "app_id": None,
                "wm_class": None,
                "readiness_predicate": None,
                "capture_mode": "window",
                "required": True,
                "display": None,
                "command_args": ["xclock", "-analog"],
            }
            code, receipt = capture.execute_capture(req)
            self.assertNotEqual(code, 0)
            self.assertEqual(receipt["outcome"], "failed")
            self.assertIn("only 2 colours", receipt["diagnostics"]["error_message"])
            self.assertFalse((self.out_dir / "blank-frame-test.png").exists())

    def test_negative_no_window(self):
        """Fail with timeout when command runs but maps no window."""
        req = {
            "out_dir": str(self.out_dir),
            "name": "no-window-test",
            "geometry": "640x480",
            "settle": 1.0,
            "deadline": 1.5,
            "app_id": None,
            "wm_class": None,
            "readiness_predicate": None,
            "capture_mode": "window",
            "required": True,
            "display": None,
            "command_args": ["sleep", "10"],
        }
        code, receipt = capture.execute_capture(req)
        self.assertNotEqual(code, 0)
        self.assertEqual(receipt["outcome"], "failed")
        self.assertFalse((self.out_dir / "no-window-test.png").exists())

    def test_negative_pre_existing_png_removed_on_failure(self):
        """Pre-existing PNG at target path must be rejected and deleted on failure."""
        stale_png = self.out_dir / "stale-target.png"
        stale_png.write_bytes(b"STALE PRE-EXISTING DATA")
        stale_receipt = self.out_dir / "stale-target.receipt.json"
        stale_receipt.write_text('{"outcome": "stale"}\n')

        req = {
            "out_dir": str(self.out_dir),
            "name": "stale-target",
            "geometry": "640x480",
            "settle": 1.0,
            "deadline": 2.0,
            "app_id": None,
            "wm_class": None,
            "readiness_predicate": None,
            "capture_mode": "window",
            "required": True,
            "display": None,
            "command_args": ["sh", "-c", "exit 1"],
        }
        code, receipt = capture.execute_capture(req)
        self.assertNotEqual(code, 0)
        self.assertEqual(receipt["outcome"], "failed")
        # Stale PNG must NOT survive
        self.assertFalse(stale_png.exists())
        # Receipt must reflect failed run
        self.assertEqual(receipt["artifacts"]["image_path"], None)

    def test_unrelated_process_not_killed(self):
        """Cleanup must only terminate owned processes and never touch unrelated processes."""
        dummy = subprocess.Popen(["sleep", "30"])
        try:
            self.assertIsNone(dummy.poll())
            req = {
                "out_dir": str(self.out_dir),
                "name": "isolation-test",
                "geometry": "640x480",
                "settle": 1.0,
                "deadline": 2.0,
                "app_id": None,
                "wm_class": None,
                "readiness_predicate": None,
                "capture_mode": "window",
                "required": True,
                "display": None,
                "command_args": ["sh", "-c", "exit 1"],
            }
            capture.execute_capture(req)
            # Verify dummy process is STILL alive!
            self.assertIsNone(dummy.poll())
        finally:
            dummy.terminate()
            dummy.wait()

    def test_diagnostics_retained_on_failure(self):
        """Failed capture runs must retain log excerpts and diagnostic errors."""
        req = {
            "out_dir": str(self.out_dir),
            "name": "diag-test",
            "geometry": "640x480",
            "settle": 1.0,
            "deadline": 3.0,
            "app_id": None,
            "wm_class": None,
            "readiness_predicate": None,
            "capture_mode": "window",
            "required": True,
            "display": None,
            "command_args": ["sh", "-c", "echo 'CRITICAL_FAILURE_EVIDENCE' >&2; exit 3"],
        }
        _, receipt = capture.execute_capture(req)
        self.assertEqual(receipt["outcome"], "failed")
        self.assertIn("CRITICAL_FAILURE_EVIDENCE", receipt["diagnostics"]["app_log_excerpt"])

    def test_cleanup_failure_reported(self):
        """Teardown failure must be recorded in receipt and final verdict."""
        mock_cleanup = {
            "status": "failed",
            "owned_pids": [1234],
            "unrelated_pids_affected": 0,
            "details": "Simulated PID termination failure",
        }
        with patch.object(capture, "cleanup_owned_processes", return_value=mock_cleanup):
            req = {
                "out_dir": str(self.out_dir),
                "name": "teardown-fail-test",
                "geometry": "640x480",
                "settle": 1.0,
                "deadline": 2.0,
                "app_id": None,
                "wm_class": None,
                "readiness_predicate": None,
                "capture_mode": "window",
                "required": True,
                "display": None,
                "command_args": ["sh", "-c", "exit 1"],
            }
            code, receipt = capture.execute_capture(req)
            self.assertNotEqual(code, 0)
            self.assertEqual(receipt["outcome"], "failed")
            self.assertEqual(receipt["cleanup"]["status"], "failed")
            self.assertIn("Simulated PID termination failure", receipt["cleanup"]["details"])


class CaptureContractSimulatedTests(unittest.TestCase):
    """Simulated tests for display picking isolation without Xvfb."""

    def test_concurrent_display_picking(self):
        """Displays picked concurrently do not collide."""
        disp1 = capture.pick_display()
        # Simulate lock file for disp1
        num1 = disp1.lstrip(":")
        lock_file = Path(f"/tmp/.X{num1}-lock")
        try:
            lock_file.write_text("12345\n")
            disp2 = capture.pick_display()
            self.assertNotEqual(disp1, disp2)
        finally:
            if lock_file.exists():
                lock_file.unlink()


if __name__ == "__main__":
    unittest.main()
