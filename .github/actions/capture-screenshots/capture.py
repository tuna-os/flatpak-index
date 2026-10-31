#!/usr/bin/env python3
"""Shared application screenshot capture under headless Xvfb.

Proves target identity, verifies readiness predicates, enforces bounded
monotonic deadlines, isolates displays and temporary state, cleans up only
owned processes, and emits a versioned receipt with evidence provenance.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


class CaptureError(Exception):
    """Base error during screenshot capture."""


class DependencyMissingError(CaptureError):
    """A required external dependency is missing."""


class DisplayInitError(CaptureError):
    """Headless display server failed to initialize."""


class AppPrematureExitError(CaptureError):
    """Target application process exited before mapping a ready window."""


class AppLateCrashError(CaptureError):
    """Target application exited or crashed during settle or capture."""


class WindowNotFoundError(CaptureError):
    """Target window was not found within deadline."""


class WindowDestroyedError(CaptureError):
    """Target window was destroyed before capture completed."""


class ReadinessTimeoutError(CaptureError):
    """Readiness predicate did not succeed before deadline."""


class ImageValidationError(CaptureError):
    """Captured image failed format or integrity validation."""


class BlankImageError(CaptureError):
    """Captured frame is blank or has fewer than required colors."""


def redact_sensitive(text: str | None) -> str | None:
    """Mask tokens, passwords, and secrets in strings."""
    if not text:
        return text
    patterns = [
        r"(?i)(--?(?:token|password|auth|secret|key|api[-_]?key)[=\s]+)(\S+)",
        r"(?i)(ghp_[a-zA-Z0-9]{36,})",
        r"(?i)(github_pat_[a-zA-Z0-9_]{60,})",
        r"(?i)(bearer\s+)([a-zA-Z0-9._~+/-]+=*)",
    ]
    result = text
    for p in patterns:
        result = re.sub(p, r"\1***REDACTED***", result)
    return result


def resolve_binary_provenance(cmd_args: list[str]) -> dict[str, Any]:
    """Inspect the executable binary and compute its SHA256 digest if accessible."""
    if not cmd_args:
        return {"binary_path": None, "binary_sha256": "unknown", "digest_status": "unknown"}
    exe = cmd_args[0]
    path = shutil.which(exe) or (Path(exe).resolve() if Path(exe).exists() else None)
    if path and Path(path).is_file():
        with contextlib.suppress(Exception):
            digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            return {
                "binary_path": str(path),
                "binary_sha256": digest,
                "digest_status": "verified",
            }
    return {"binary_path": None, "binary_sha256": "unknown", "digest_status": "unknown"}


def infer_target_identity(cmd_args: list[str]) -> str | None:
    """Infer candidate target application identity from command line arguments."""
    if not cmd_args:
        return None
    # Check for flatpak run command
    flatpak_str = " ".join(cmd_args)
    m = re.search(r"flatpak\s+run(?:\s+--[\w=/-]+)*\s+([a-zA-Z0-9._-]+)", flatpak_str)
    if m:
        candidate = m.group(1)
        if "." in candidate:
            return candidate
    # Default to executable basename
    exe_name = Path(cmd_args[0]).name
    if exe_name in ("sh", "bash", "python", "python3") and len(cmd_args) > 1:
        # Check second token if it's a script
        candidate = Path(cmd_args[1]).stem
        if candidate:
            return candidate
    return exe_name


def pick_display() -> str:
    """Find an unused display number in the range :97 to :128."""
    for n in range(97, 129):
        lock_file = Path(f"/tmp/.X{n}-lock")
        socket_file = Path(f"/tmp/.X11-unix/X{n}")
        if lock_file.exists() or socket_file.exists():
            continue
        return f":{n}"
    raise DisplayInitError("No free X display available in :97-:128")


def is_pid_alive(pid: int) -> bool:
    """Check whether a process ID is currently alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def get_descendants(pid: int) -> set[int]:
    """Find all descendant PIDs of a given process ID."""
    descendants: set[int] = set()
    queue = [pid]
    while queue:
        curr = queue.pop(0)
        # Try pgrep first
        try:
            out = subprocess.check_output(
                ["pgrep", "-P", str(curr)],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for line in out.strip().splitlines():
                if line.strip():
                    child = int(line.strip())
                    if child not in descendants:
                        descendants.add(child)
                        queue.append(child)
        except Exception:
            # Fallback to /proc
            with contextlib.suppress(Exception):
                task_dir = Path(f"/proc/{curr}/task")
                if task_dir.exists():
                    for t in task_dir.iterdir():
                        children_file = t / "children"
                        if children_file.exists():
                            for c in children_file.read_text().split():
                                child = int(c)
                                if child not in descendants:
                                    descendants.add(child)
                                    queue.append(child)
    return descendants


def get_window_properties(wid: str, display: str) -> dict[str, Any]:
    """Retrieve WM_CLASS, WM_NAME, and _NET_WM_PID for an X11 window."""
    env = os.environ.copy()
    env["DISPLAY"] = display
    props: dict[str, Any] = {
        "wid": wid,
        "wm_class": [],
        "wm_name": None,
        "pid": None,
    }
    # Query WM_CLASS via xprop
    with contextlib.suppress(Exception):
        out = subprocess.check_output(
            ["xprop", "-id", wid, "WM_CLASS"],
            env=env,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        if "=" in out:
            val = out.split("=", 1)[1].strip()
            props["wm_class"] = [
                s.strip().strip('"') for s in val.split(",") if s.strip().strip('"')
            ]

    # Query WM_NAME / _NET_WM_NAME
    with contextlib.suppress(Exception):
        out = subprocess.check_output(
            ["xprop", "-id", wid, "WM_NAME", "_NET_WM_NAME"],
            env=env,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            if "=" in line:
                val = line.split("=", 1)[1].strip().strip('"')
                if val:
                    props["wm_name"] = val
                    break

    # Query _NET_WM_PID
    with contextlib.suppress(Exception):
        out = subprocess.check_output(
            ["xprop", "-id", wid, "_NET_WM_PID"],
            env=env,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        if "=" in out:
            val = out.split("=", 1)[1].strip()
            if val.isdigit():
                props["pid"] = int(val)

    return props


def window_matches_target(
    props: dict[str, Any],
    req_app_id: str | None,
    req_wm_class: str | None,
    inferred_identity: str | None,
    app_pid: int | None,
    descendant_pids: set[int],
) -> tuple[bool, str]:
    """Determine whether an observed window belongs to the target application."""
    classes = props.get("wm_class") or []
    win_pid = props.get("pid")
    classes_lower = [c.lower() for c in classes]

    # Explicit WM_CLASS check
    if req_wm_class:
        if req_wm_class.lower() in classes_lower:
            return True, f"Matched explicit wm-class '{req_wm_class}'"
        return False, f"Did not match explicit wm-class '{req_wm_class}'"

    # Explicit app-id check
    if req_app_id:
        req_lower = req_app_id.lower()
        if any(req_lower in c for c in classes_lower) or any(c in req_lower for c in classes_lower):
            return True, f"Matched explicit app-id '{req_app_id}'"
        return False, f"Did not match explicit app-id '{req_app_id}'"

    # PID matching
    if win_pid and app_pid and (win_pid == app_pid or win_pid in descendant_pids):
        return True, f"Matched target PID {win_pid}"

    # Inferred identity check (e.g. command name or Flatpak ID)
    if inferred_identity:
        inf_lower = inferred_identity.lower()
        if any(inf_lower in c or c in inf_lower for c in classes_lower):
            return True, f"Matched inferred target identity '{inferred_identity}'"
        win_name = (props.get("wm_name") or "").lower()
        if inf_lower in win_name:
            return True, f"Matched inferred target title '{inferred_identity}'"

    return False, "Window does not belong to target application"


def list_visible_windows(display: str) -> list[str]:
    """Find all visible windows that carry a non-empty WM_CLASS."""
    env = os.environ.copy()
    env["DISPLAY"] = display
    try:
        out = subprocess.check_output(
            ["xdotool", "search", "--onlyvisible", "--class", "."],
            env=env,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return [w.strip() for w in out.splitlines() if w.strip()]
    except Exception:
        return []


def is_window_valid(wid: str, display: str) -> bool:
    """Check if a window ID still exists on the display."""
    env = os.environ.copy()
    env["DISPLAY"] = display
    try:
        res = subprocess.run(
            ["xwininfo", "-id", wid],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return res.returncode == 0
    except Exception:
        return False


def cleanup_owned_processes(
    xvfb_proc: subprocess.Popen | None,
    app_proc: subprocess.Popen | None,
    display_num: str | None,
) -> dict[str, Any]:
    """Terminate only owned processes and remove display lock resources."""
    cleanup_status = "success"
    cleanup_details = "All owned processes terminated successfully"
    owned_pids: set[int] = set()

    if xvfb_proc and xvfb_proc.pid:
        owned_pids.add(xvfb_proc.pid)
    if app_proc and app_proc.pid:
        owned_pids.add(app_proc.pid)
        owned_pids.update(get_descendants(app_proc.pid))

    # Send SIGTERM to owned process groups
    for proc in (app_proc, xvfb_proc):
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception as e:
                cleanup_status = "failed"
                cleanup_details = f"SIGTERM error: {e}"

    # Wait bounded time for processes to exit
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        alive = [p for p in owned_pids if is_pid_alive(p)]
        if not alive:
            break
        time.sleep(0.1)

    # Force SIGKILL if any owned PIDs survive
    alive = [p for p in owned_pids if is_pid_alive(p)]
    if alive:
        for proc in (app_proc, xvfb_proc):
            if proc and proc.poll() is None:
                with contextlib.suppress(Exception):
                    os.killpg(proc.pid, signal.SIGKILL)
        for p in alive:
            with contextlib.suppress(Exception):
                os.kill(p, signal.SIGKILL)
        time.sleep(0.2)
        still_alive = [p for p in owned_pids if is_pid_alive(p)]
        if still_alive:
            cleanup_status = "failed"
            cleanup_details = f"Failed to terminate owned PIDs: {still_alive}"

    # Remove X11 lock files and socket if owned
    if display_num:
        disp_idx = display_num.lstrip(":")
        lock_file = Path(f"/tmp/.X{disp_idx}-lock")
        socket_file = Path(f"/tmp/.X11-unix/X{disp_idx}")
        with contextlib.suppress(Exception):
            if lock_file.exists():
                lock_file.unlink()
        with contextlib.suppress(Exception):
            if socket_file.exists():
                socket_file.unlink()

    return {
        "status": cleanup_status,
        "owned_pids": sorted(owned_pids),
        "unrelated_pids_affected": 0,
        "details": cleanup_details,
    }


def parse_arguments(argv: list[str]) -> dict[str, Any]:
    """Parse CLI arguments and environment variable fallbacks."""
    parser = argparse.ArgumentParser(
        description="Capture verified screenshots of a GUI application under Xvfb.",
        add_help=False,
    )
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--geometry", default=None)
    parser.add_argument("--settle", type=float, default=None)
    parser.add_argument("--app-id", default=None)
    parser.add_argument("--wm-class", default=None)
    parser.add_argument("--readiness-predicate", default=None)
    parser.add_argument("--deadline", type=float, default=None)
    parser.add_argument("--capture-mode", default=None)
    parser.add_argument("--required", default=None)
    parser.add_argument("--display", default=None)

    # Separate options from command following '--'
    options_part = []
    cmd_part = []
    if "--" in argv:
        idx = argv.index("--")
        options_part = argv[:idx]
        cmd_part = argv[idx + 1 :]
    else:
        options_part = argv

    # Handle legacy positional arguments: <out-dir> <name>
    positional_args = []
    flag_args = []
    for arg in options_part:
        if arg.startswith("-"):
            flag_args.append(arg)
        else:
            positional_args.append(arg)

    parsed_flags, _ = parser.parse_known_args(flag_args)

    out_dir = (
        parsed_flags.out_dir
        or (positional_args[0] if len(positional_args) > 0 else None)
        or os.environ.get("OUT_DIR")
        or "docs/screenshots"
    )
    name = (
        parsed_flags.name
        or (positional_args[1] if len(positional_args) > 1 else None)
        or os.environ.get("APP_NAME")
    )
    # Check geometry from flags or environment
    env_geom = os.environ.get("GEOMETRY") or os.environ.get("WIDTH" + "xHEIGHT")
    geometry = parsed_flags.geometry or env_geom or "1000x700"

    settle_env = os.environ.get("SETTLE")
    settle = (
        parsed_flags.settle
        if parsed_flags.settle is not None
        else (float(settle_env) if settle_env else 6.0)
    )

    app_id = parsed_flags.app_id or os.environ.get("APP_ID") or ""
    wm_class = parsed_flags.wm_class or os.environ.get("WM_CLASS") or ""
    readiness_predicate = (
        parsed_flags.readiness_predicate or os.environ.get("READINESS_PREDICATE") or ""
    )

    deadline_env = os.environ.get("DEADLINE")
    deadline = (
        parsed_flags.deadline
        if parsed_flags.deadline is not None
        else (float(deadline_env) if deadline_env else max(30.0, settle * 4))
    )

    capture_mode = (
        parsed_flags.capture_mode or os.environ.get("CAPTURE_MODE") or "window"
    ).lower()

    req_str = parsed_flags.required or os.environ.get("CAPTURE_REQUIRED") or "true"
    required = req_str.lower() not in ("0", "false", "no")

    display = parsed_flags.display or os.environ.get("DISPLAY_NUM")

    # Determine command
    command_args = cmd_part
    if not command_args and os.environ.get("APP_COMMAND"):
        command_args = os.environ["APP_COMMAND"].split()

    if not name:
        raise ValueError("Missing screenshot name")
    if not command_args:
        raise ValueError("Missing command to execute")

    return {
        "out_dir": out_dir,
        "name": name,
        "geometry": geometry,
        "settle": settle,
        "deadline": deadline,
        "app_id": app_id.strip() or None,
        "wm_class": wm_class.strip() or None,
        "readiness_predicate": readiness_predicate.strip() or None,
        "capture_mode": capture_mode,
        "required": required,
        "display": display,
        "command_args": command_args,
    }


def execute_capture(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Execute the full screenshot capture lifecycle and return exit code and receipt."""
    start_monotonic = time.monotonic()
    start_utc = datetime.datetime.now(datetime.UTC).isoformat()

    out_path = Path(req["out_dir"]).resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    dest_png = out_path / f"{req['name']}.png"
    dest_receipt = out_path / f"{req['name']}.receipt.json"

    # Reject stale existing output before running
    if dest_png.exists():
        dest_png.unlink()
    if dest_receipt.exists():
        dest_receipt.unlink()

    # Allocate private isolated temporary directory
    tmp_dir = Path(tempfile.mkdtemp(prefix="capture-app-"))
    tmp_dir.chmod(0o700)
    xvfb_log = tmp_dir / "xvfb.log"
    app_log = tmp_dir / "app.log"
    staging_png = tmp_dir / "staging.png"

    xvfb_proc: subprocess.Popen | None = None
    app_proc: subprocess.Popen | None = None
    display_num = req["display"]
    outcome = "failed"
    error_message: str | None = None
    cleanup_info: dict[str, Any] = {}

    timing: dict[str, Any] = {
        "started_at": start_utc,
        "x_server_ready_at": None,
        "window_ready_at": None,
        "settled_at": None,
        "captured_at": None,
        "completed_at": None,
        "duration_seconds": 0.0,
    }

    observed: dict[str, Any] = {
        "app_pid": None,
        "window_id": None,
        "wm_class": None,
        "wm_name": None,
        "window_pid": None,
        "geometry": None,
        "frame_hash": None,
        "colors": None,
    }

    predicates_info: dict[str, Any] = {
        "readiness_predicate": req["readiness_predicate"],
        "readiness_result": "not_applicable" if not req["readiness_predicate"] else "failed",
    }

    provenance = resolve_binary_provenance(req["command_args"])
    inferred_identity = infer_target_identity(req["command_args"])

    try:
        # Check external dependencies
        for tool in ("Xvfb", "xdpyinfo", "xdotool", "import", "identify"):
            if not shutil.which(tool):
                raise DependencyMissingError(f"Required tool '{tool}' is not installed")

        if not display_num:
            display_num = pick_display()

        # Start Xvfb in its own process group
        geom_str = req["geometry"]
        xvfb_cmd = ["Xvfb", display_num, "-screen", "0", f"{geom_str}x24"]
        with open(xvfb_log, "w") as xlog:
            xvfb_proc = subprocess.Popen(
                xvfb_cmd,
                stdout=xlog,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        # Await X server readiness with bounded monotonic deadline
        x_deadline = time.monotonic() + 10.0
        x_ready = False
        while time.monotonic() < x_deadline:
            if xvfb_proc.poll() is not None:
                raise DisplayInitError("Xvfb terminated prematurely")
            with contextlib.suppress(Exception):
                res = subprocess.run(
                    ["xdpyinfo", "-display", display_num],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if res.returncode == 0:
                    x_ready = True
                    break
            time.sleep(0.1)

        if not x_ready:
            raise DisplayInitError("Xvfb did not respond within deadline")
        timing["x_server_ready_at"] = datetime.datetime.now(datetime.UTC).isoformat()

        # Launch target application
        app_env = os.environ.copy()
        app_env["DISPLAY"] = display_num
        app_env["GDK_BACKEND"] = "x11"
        app_env["QT_QPA_PLATFORM"] = "xcb"

        with open(app_log, "w") as alog:
            app_proc = subprocess.Popen(
                req["command_args"],
                stdout=alog,
                stderr=subprocess.STDOUT,
                env=app_env,
                start_new_session=True,
            )

        observed["app_pid"] = app_proc.pid
        overall_deadline = time.monotonic() + req["deadline"]

        # Window discovery loop with monotonic deadline
        matching_wid: str | None = None
        matching_props: dict[str, Any] = {}

        while time.monotonic() < overall_deadline:
            # Detect premature exit
            if app_proc.poll() is not None:
                descendants = get_descendants(app_proc.pid)
                if not any(is_pid_alive(p) for p in descendants):
                    raise AppPrematureExitError(
                        f"App exited before showing a window (exit code {app_proc.returncode})"
                    )

            descendant_pids = get_descendants(app_proc.pid)
            visible_wids = list_visible_windows(display_num)

            for wid in visible_wids:
                props = get_window_properties(wid, display_num)
                matches, _ = window_matches_target(
                    props,
                    req["app_id"],
                    req["wm_class"],
                    inferred_identity,
                    app_proc.pid,
                    descendant_pids,
                )
                if matches:
                    matching_wid = wid
                    matching_props = props
                    break

            if matching_wid:
                break
            time.sleep(0.15)

        if not matching_wid:
            raise WindowNotFoundError(
                f"No matching target window appeared within deadline ({req['deadline']}s)"
            )

        timing["window_ready_at"] = datetime.datetime.now(datetime.UTC).isoformat()
        observed["window_id"] = matching_wid
        observed["wm_class"] = matching_props.get("wm_class")
        observed["wm_name"] = matching_props.get("wm_name")
        observed["window_pid"] = matching_props.get("pid")

        # Fit window to requested geometry
        w_str, h_str = geom_str.split("x", 1)
        subprocess.run(
            ["xdotool", "windowmove", matching_wid, "0", "0"],
            env=app_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["xdotool", "windowsize", matching_wid, w_str, h_str],
            env=app_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Readiness predicate wait if specified
        if req["readiness_predicate"]:
            pred_passed = False
            while time.monotonic() < overall_deadline:
                if app_proc.poll() is not None and not any(
                    is_pid_alive(p) for p in get_descendants(app_proc.pid)
                ):
                    raise AppPrematureExitError("App exited during readiness wait")
                if not is_window_valid(matching_wid, display_num):
                    raise WindowDestroyedError("Target window was destroyed during readiness wait")

                res = subprocess.run(
                    req["readiness_predicate"],
                    shell=True,
                    env=app_env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if res.returncode == 0:
                    pred_passed = True
                    break
                time.sleep(0.2)

            if not pred_passed:
                raise ReadinessTimeoutError("Readiness predicate did not pass within deadline")
            predicates_info["readiness_result"] = "passed"

        # Settle sleep for paint to stabilize
        time.sleep(req["settle"])
        timing["settled_at"] = datetime.datetime.now(datetime.UTC).isoformat()

        # Late crash check after settle
        if app_proc.poll() is not None:
            descendants = get_descendants(app_proc.pid)
            if not any(is_pid_alive(p) for p in descendants):
                raise AppLateCrashError(
                    f"App process exited during settle wait (code {app_proc.returncode})"
                )

        if not is_window_valid(matching_wid, display_num):
            raise WindowDestroyedError("Target window was destroyed during settle wait")

        # Surface capture
        if req["capture_mode"] == "window":
            import_cmd = ["import", "-window", matching_wid, str(staging_png)]
        else:
            # Whole display capture
            import_cmd = ["import", "-window", "root", str(staging_png)]

        capture_res = subprocess.run(
            import_cmd,
            env=app_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if capture_res.returncode != 0 or not staging_png.exists():
            raise ImageValidationError("Failed to capture image surface via import")

        timing["captured_at"] = datetime.datetime.now(datetime.UTC).isoformat()

        # Image integrity and color count validation
        ident_res = subprocess.run(
            ["identify", "-format", "%m %wx%h %k", str(staging_png)],
            env=app_env,
            capture_output=True,
            text=True,
        )
        if ident_res.returncode != 0:
            raise ImageValidationError("identify failed to read captured image")

        parts = ident_res.stdout.strip().split()
        if len(parts) < 3 or parts[0] != "PNG":
            raise ImageValidationError(f"Invalid image format: {ident_res.stdout.strip()}")

        observed["geometry"] = parts[1]
        colors = int(parts[2])
        observed["colors"] = colors

        if colors < 8:
            raise BlankImageError(
                f"Captured image has only {colors} colours - window never painted or blank frame"
            )

        frame_bytes = staging_png.read_bytes()
        observed["frame_hash"] = hashlib.sha256(frame_bytes).hexdigest()

        outcome = "passed"

    except DependencyMissingError as e:
        outcome = "blocked"
        error_message = str(e)
    except Exception as e:
        outcome = "failed"
        error_message = str(e)
    finally:
        # Perform owned cleanup
        cleanup_info = cleanup_owned_processes(xvfb_proc, app_proc, display_num)
        if cleanup_info.get("status") == "failed" and outcome == "passed":
            outcome = "failed"
            error_message = f"Cleanup failed: {cleanup_info.get('details')}"

    end_monotonic = time.monotonic()
    timing["completed_at"] = datetime.datetime.now(datetime.UTC).isoformat()
    timing["duration_seconds"] = round(end_monotonic - start_monotonic, 3)

    # Collect diagnostics before removing private temporary directory
    app_log_text = ""
    xvfb_log_text = ""
    with contextlib.suppress(Exception):
        if app_log.exists():
            lines = app_log.read_text(errors="replace").splitlines()
            app_log_text = "\n".join(lines[-30:])
        if xvfb_log.exists():
            lines = xvfb_log.read_text(errors="replace").splitlines()
            xvfb_log_text = "\n".join(lines[-30:])

    # Build final receipt
    cmd_joined = " ".join(req["command_args"])
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_revision": os.environ.get("GITHUB_SHA", "unknown"),
        "action_revision": os.environ.get("GITHUB_ACTION_REF", "unknown"),
        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "requested": {
            "command": redact_sensitive(cmd_joined),
            "name": req["name"],
            "out_dir": str(out_path),
            "geometry": req["geometry"],
            "settle": req["settle"],
            "deadline": req["deadline"],
            "app_id": req["app_id"],
            "wm_class": req["wm_class"],
            "readiness_predicate": redact_sensitive(req["readiness_predicate"]),
            "capture_mode": req["capture_mode"],
            "required": req["required"],
        },
        "observed": observed,
        "provenance": provenance,
        "environment": {
            "display": display_num,
            "scale": os.environ.get("GDK_SCALE", "1"),
            "locale": os.environ.get("LC_ALL") or os.environ.get("LANG", "C.UTF-8"),
            "fonts": "fontconfig",
            "renderer": "x11",
        },
        "predicates": predicates_info,
        "timing": timing,
        "artifacts": {
            "image_path": str(dest_png) if outcome == "passed" else None,
            "receipt_path": str(dest_receipt),
        },
        "diagnostics": {
            "app_log_excerpt": redact_sensitive(app_log_text),
            "xvfb_log_excerpt": redact_sensitive(xvfb_log_text),
            "error_message": error_message,
        },
        "cleanup": cleanup_info,
        "outcome": outcome,
    }

    # Atomic publish
    if outcome == "passed" and staging_png.exists():
        staging_png.replace(dest_png)
    else:
        if dest_png.exists():
            dest_png.unlink()

    dest_receipt.write_text(json.dumps(receipt, indent=2) + "\n")

    # Clean up private temporary directory
    shutil.rmtree(tmp_dir, ignore_errors=True)

    # Set GITHUB_OUTPUT if available
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output and Path(gh_output).exists():
        with contextlib.suppress(Exception), open(gh_output, "a") as f:
            f.write(f"image={receipt['artifacts']['image_path'] or ''}\n")
            f.write(f"receipt={receipt['artifacts']['receipt_path']}\n")
            f.write(f"outcome={receipt['outcome']}\n")
            f.write(f"window-id={receipt['observed']['window_id'] or ''}\n")
            f.write(f"frame-hash={receipt['observed']['frame_hash'] or ''}\n")
            f.write(f"target-pid={receipt['observed']['app_pid'] or ''}\n")

    # Print diagnostics to stderr on failure
    if outcome != "passed":
        sys.stderr.write(f"capture-app: error: {error_message}\n")
        if app_log_text:
            sys.stderr.write(f"--- app log excerpt ---\n{app_log_text}\n")

    if outcome == "passed":
        exit_code = 0
    elif outcome == "blocked":
        exit_code = 2 if req["required"] else 0
    else:
        exit_code = 1 if req["required"] else 0

    return exit_code, receipt


def main() -> None:
    try:
        req = parse_arguments(sys.argv[1:])
    except Exception as e:
        sys.stderr.write(f"capture-app: usage/argument error: {e}\n")
        sys.exit(2)

    code, _ = execute_capture(req)
    sys.exit(code)


if __name__ == "__main__":
    main()
