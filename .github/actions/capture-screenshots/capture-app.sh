#!/usr/bin/env bash
# Capture screenshots of a GUI application under a headless X server.
#
# Toolkit-agnostic: drives Xvfb, verifies target identity, checks readiness
# predicates, detects crashes/exits, enforces bounded monotonic deadlines,
# isolates displays/temporary state, cleans up only owned processes, and emits
# a versioned receipt with evidence provenance.
#
# Usage: capture-app.sh <out-dir> <name> -- <command> [args...]
#
#   WIDTHxHEIGHT / GEOMETRY   screen size (default 1000x700)
#   SETTLE                    seconds to wait for paint to settle (default 6)
#   DEADLINE                  monotonic deadline in seconds
#   APP_ID                    target application ID
#   WM_CLASS                  expected WM_CLASS
#   READINESS_PREDICATE       command to assert target readiness
#   CAPTURE_MODE              "window" (default) or "display"
#   CAPTURE_REQUIRED          "true" (default) or "false"
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "capture-app.sh: python3 is required" >&2
  exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/capture.py" "$@"
