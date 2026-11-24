#!/bin/sh
# mmini window: a tmux server of its own (only this folder's mmini.tmux.conf is read) with three panes: the sidebar
# (left, full height: mmini.py sidebar), the tab bar (top right: mmini.py tabs) and the view (below it: mmini.py
# view, a relay around view.sh, which shows the picked terminal through `hc attach`; the relay sends a file dropped
# for a terminal of another machine there with `hc put`, see mmini.py's ViewRelay).
#
# mmini.app types `exec env MMINI_WINDOW=<folder> sh start.sh` into a new Ghostty window's login shell, so the
# settings exported in ~/.zshrc apply. Any other terminal works too: `sh ~/.local/share/mmini/start.sh` (a window
# folder is made then). Closing the window ends this tmux and its panes; the terminals in herdr-core keep running.
set -u

tmux=""
sock=""
# Something went wrong before the window could show anything: say so, and leave no tmux behind.
fail() {
  if [ -n "$sock" ]; then "$tmux" -L "$sock" kill-server 2>/dev/null; fi
  printf 'mmini: %s\n(enter closes this window)\n' "$1"
  read -r _ || true
  exit 1
}

here=$(cd "$(dirname "$0")" && pwd)
shared="${MMINI_STATE:-$HOME/.local/state/mmini}"
mkdir -p "$shared" || fail "cannot make $shared"
win="${MMINI_WINDOW:-}"
[ -n "$win" ] || win=$(mktemp -d "$shared/w-XXXXXX") || fail "cannot make a window folder in $shared"
mkdir -p "$win" || fail "cannot make $win"
export MMINI_WINDOW="$win"
# Started from inside another tmux: this one is separate, not nested in it.
unset TMUX TMUX_PANE

for t in "$(command -v tmux 2>/dev/null || true)" /opt/homebrew/bin/tmux /usr/local/bin/tmux; do
  if [ -n "$t" ] && [ -x "$t" ]; then
    tmux=$t
    break
  fi
done
[ -n "$tmux" ] || fail "tmux not found: brew install tmux"

# A path as one shell word, for the commands tmux runs with sh -c.
q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }

# The window title "mmini", then no folder: an empty OSC 7 makes Ghostty forget the login shell's folder, so no
# folder icon shows next to the title. From here on tmux sets the title (the pane with the keyboard).
printf '\033]2;mmini\007\033]7;\007'

size=$(stty size 2>/dev/null || echo "40 120")
rows=${size% *}
cols=${size#* }
case "$rows$cols" in '' | *[!0-9]*) rows=40 cols=120 ;; esac
if [ "$rows" -lt 2 ] || [ "$cols" -lt 2 ]; then rows=40 cols=120; fi
# The sidebar's first width, as mmini.py reads MMINI_WIDTH (10 to 200, else 30); it sets its exact width itself.
width=${MMINI_WIDTH:-30}
case "$width" in '' | *[!0-9]*) width=30 ;; esac
if [ "$width" -lt 10 ] || [ "$width" -gt 200 ]; then width=30; fi

sock="mmini-$(basename "$win")"
t() { "$tmux" -L "$sock" "$@"; }
# The window closed before the attach below set destroy-unattached: end this window's tmux here.
trap 't kill-server 2>/dev/null; exit 129' HUP TERM INT
# mmini's own panes get a terminal type with SGR mouse codes (mmini.terminfo), so a click far right in a wide window
# keeps its column. Compiled with macOS's own tic, in the format macOS's curses reads (a newer tic first in PATH may
# write another), and tried with the python3 that runs the panes. Else: tmux's screen-256color.
term=""
tic=/usr/bin/tic
[ -x "$tic" ] || tic=$(command -v tic 2>/dev/null || true)
if [ -n "$tic" ] && "$tic" -x -o "$win/terminfo" "$here/mmini.terminfo" 2>/dev/null &&
  TERM=xterm-mmini TERMINFO="$win/terminfo" python3 -c 'import curses; curses.setupterm()' >/dev/null 2>&1; then
  term="env TERM=xterm-mmini TERMINFO=$(q "$win/terminfo") "
fi
py="exec ${term}python3 $(q "$here/mmini.py")"
pane() { case "$1" in %[0-9]*) return 0 ;; *) return 1 ;; esac; }

# The view first (the window's whole size), then the sidebar split off at full height on the left, then the tab bar
# above the view. Each pane sizes itself exactly afterwards (mmini.py: the sidebar's width, the tab bar's rows).
# The view keeps tmux's terminal type (screen-256color): xterm-mmini is for mmini's own curses panes, and what the
# view shows is hc attach's output, passed on unchanged.
view=$(t -f "$here/mmini.tmux.conf" new-session -d -s mmini -x "$cols" -y "$rows" -P -F '#{pane_id}' \
  "exec python3 $(q "$here/mmini.py") view" 2>&1)
pane "$view" || fail "tmux could not start: $view"
side=$(t split-window -f -hb -d -l "$width" -t "$view" -P -F '#{pane_id}' "$py sidebar" 2>&1)
pane "$side" || fail "tmux could not make the sidebar: $side"
tabs=$(t split-window -vb -d -l 2 -t "$view" -P -F '#{pane_id}' "$py tabs" 2>&1)
pane "$tabs" || fail "tmux could not make the tab bar: $tabs"
printf 'side=%s\ntabs=%s\nview=%s\n' "$side" "$tabs" "$view" >"$win/panes.tmp" && mv -f "$win/panes.tmp" "$win/panes" ||
  fail "cannot write $win/panes"
t set -p -t "$view" @mmini_role view # a right click there opens mmini's menu for the shown terminal (mmini.tmux.conf)
t select-pane -t "$view"
# Only once attached: a session nobody is attached to is ended (the window was closed). An attach that fails leaves
# the server behind without that: it is ended here.
t attach -t mmini \; set -g destroy-unattached on
rc=$?
t kill-server 2>/dev/null
exit "$rc"
