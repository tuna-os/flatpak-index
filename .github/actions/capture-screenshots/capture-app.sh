#!/usr/bin/env bash
# Capture screenshots of a GUI application under a headless X server.
#
# Toolkit-agnostic: it drives a real X server (Xvfb) and photographs the
# application's own window, so it works for GTK, Qt, Electron or anything else
# that maps a window -- unlike an in-process harness, which has to be written
# per toolkit.
#
# Usage: capture-app.sh <out-dir> <name> -- <command> [args...]
#
#   WIDTHxHEIGHT   screen size            (default 1000x700, Flathub's maximum)
#   SETTLE         seconds to wait for the window to paint and settle
#                  (default 6)
#
# Exits non-zero if the app dies or never maps a window, so a broken build
# fails the job instead of publishing a blank or stale image.
set -euo pipefail

OUT="${1:?usage: capture-app.sh <out-dir> <name> -- <command> [args...]}"; shift
NAME="${1:?missing <name>}"; shift
[ "${1:-}" = "--" ] && shift
[ $# -gt 0 ] || { echo "capture-app.sh: no command given" >&2; exit 2; }

GEOM="${WIDTHxHEIGHT:-1000x700}"
SETTLE="${SETTLE:-6}"
# Pick a display number nobody is using. A fixed number races against both a
# previous run that has not finished tearing down and any capture running in
# parallel, and the loser reports "Xvfb never came up" for what is really a
# collision.
pick_display() {
  local n
  for n in $(seq 97 128); do
    [ -e "/tmp/.X${n}-lock" ] || [ -e "/tmp/.X11-unix/X${n}" ] && continue
    echo ":$n"; return 0
  done
  echo "capture-app.sh: no free X display in :97-:128" >&2; return 1
}
DISPLAY_NUM="${DISPLAY_NUM:-$(pick_display)}"

mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

Xvfb "$DISPLAY_NUM" -screen 0 "${GEOM}x24" >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!
cleanup() {
  [ -n "${APP_PID:-}" ] && kill "$APP_PID" 2>/dev/null || true
  kill "$XVFB_PID" 2>/dev/null || true
}
trap cleanup EXIT
export DISPLAY="$DISPLAY_NUM"

# Wait for the X server itself before starting the app, rather than sleeping a
# fixed amount and hoping.
for _ in $(seq 50); do xdpyinfo >/dev/null 2>&1 && break; sleep 0.2; done
xdpyinfo >/dev/null 2>&1 || { echo "capture-app.sh: Xvfb never came up" >&2; exit 1; }

export GDK_BACKEND=x11 QT_QPA_PLATFORM=xcb
"$@" >/tmp/app.log 2>&1 &
APP_PID=$!

# Wait for the app to map a window OF ITS OWN.
#
# Three strategies, in order of how specific they are:
#
#   --pid / --any-pid-descendant  Exact, but only works for a toolkit that
#       sets _NET_WM_PID (GTK and Qt do) AND a process in this PID namespace.
#       A Flatpak fails both halves: it runs in its own PID namespace, so the
#       _NET_WM_PID its window advertises is the pid *inside* the sandbox and
#       never matches the host pid we hold.
#
#   --class '.'  Any window carrying a WM_CLASS of at least one character.
#       Toolkit windows set WM_CLASS; Xvfb's root window does not, so this
#       cannot silently match an empty display. It also covers plain Xt apps
#       (xmessage, xclock), which set no _NET_WM_PID at all.
#
# What is deliberately NOT used is --name '.*': the empty string matches, so
# it returns the root window on a bare display. That made a failed launch look
# like a success and photograph a blank screen.
WIN=""
for _ in $(seq $((SETTLE * 10))); do
  if ! kill -0 "$APP_PID" 2>/dev/null; then
    echo "capture-app.sh: app exited before showing a window" >&2
    tail -20 /tmp/app.log >&2; exit 1
  fi
  WIN="$(xdotool search --onlyvisible --pid "$APP_PID" 2>/dev/null | tail -1 || true)"
  [ -n "$WIN" ] || WIN="$(xdotool search --onlyvisible --any-pid-descendant "$APP_PID" 2>/dev/null | tail -1 || true)"
  [ -n "$WIN" ] || WIN="$(xdotool search --onlyvisible --class '.' 2>/dev/null | tail -1 || true)"
  [ -n "$WIN" ] && break
  sleep 0.2
done
if [ -z "$WIN" ]; then
  echo "capture-app.sh: no window appeared within $((SETTLE * 2))s" >&2
  tail -20 /tmp/app.log >&2; exit 1
fi

# Fit the window to the screen and square it into the corner, so the capture is
# the whole app at exactly $GEOM rather than whatever size it opened at with the
# right-hand side falling off the display.
W="${GEOM%x*}"; H="${GEOM#*x}"
xdotool windowmove "$WIN" 0 0 2>/dev/null || true
xdotool windowsize "$WIN" "$W" "$H" 2>/dev/null || true

sleep "$SETTLE"   # let fonts, icons and any async first paint settle

import -window root "$OUT/$NAME.png"

# A window that never painted yields a single flat colour; that is a failure,
# not a screenshot. The threshold is a heuristic aimed at real applications:
# a strictly monochrome client (xmessage, say -- unantialiased black on white
# is exactly 2 colours) trips it even though it painted correctly. No GTK or
# Qt app gets anywhere near this few.
COLOURS="$(identify -format '%k' "$OUT/$NAME.png")"
if [ "$COLOURS" -lt 8 ]; then
  echo "capture-app.sh: captured image has only $COLOURS colours - window never painted" >&2
  # Remove it: a blank PNG left on disk gets committed and published as though
  # it were a real screenshot.
  rm -f "$OUT/$NAME.png"
  tail -20 /tmp/app.log >&2
  exit 1
fi

identify -format "captured %f: %wx%h, %k colours\n" "$OUT/$NAME.png"
