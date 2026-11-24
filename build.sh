#!/bin/sh
# Builds mmini.app: each start opens one Ghostty window with three panes, run by a tmux of the window's own
# (start.sh, mmini.tmux.conf). Sidebar on the left (needs you, spaces, servers, dev servers, agents), tab bar on top
# (one tab per terminal of the chosen space or server), and below it the chosen terminal itself (view.sh runs
# `hc attach`). The app gets Ghostty's icon.
#
# Install (clones this repo to ~/.local/share/mmini, then builds):
#
#   git clone https://github.com/PerIPan/herdr-core-ghostty-UI ~/.local/share/mmini && sh ~/.local/share/mmini/build.sh
#
# Update:
#
#   git -C ~/.local/share/mmini pull && sh ~/.local/share/mmini/build.sh
#
# Needs on this Mac: Ghostty 1.3.0 or newer (AppleScript control), tmux (brew install tmux), python3 with curses,
# hc with the machines added. Safe to run again: the new app is compiled beside the old one and only replaces it
# when the compile worked.
#
# What to expect (the automated tests run without Ghostty; tmux was tried in a pseudo terminal):
# - Every start of mmini.app opens its own window with its own state folder (~/.local/state/mmini/w-XXXXXX) and its
#   own tmux server, so two mmini windows never switch each other's view. The remembered space and terminals are
#   shared. Closing the window ends its tmux and the panes; the terminals in herdr-core keep running.
# - One click acts, in any pane: tmux passes the click to the pane under the pointer at once. After a pick the
#   keyboard goes to the shown terminal. A right click on a sidebar row or a tab, or in the shown terminal, opens
#   its menu; keys typed then go on to the terminal. A file dropped on the window lands in the terminal.
# - The sidebar is MMINI_WIDTH columns (30) until the divider is dragged with the mouse; then it keeps the dragged
#   width, also in later windows (~/.local/state/mmini/width; remove it to go back to 30). The tab bar is 3 rows. A
#   resized window keeps both.
# - The sidebar has three states: open, strip (status dots and the start of each name, MMINI_NARROW columns) and
#   hidden (its pane closes; the tab bar then shows "›", whose click or the key c brings the sidebar back at full
#   height). c steps through them; the state is kept for the next window.
# - z gives the whole window to the shown terminal (tmux's zoom); a line on top, "‹ back", brings the panes back on
#   a click.
# - Selecting text in the shown terminal: a drag selects with tmux and copies to the clipboard; shift+drag is
#   Ghostty's own selection.
# - The window title names the shown terminal and its server ("web · me@mini"). Claude Code sets its own unless
#   CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 is in the env block of its settings.json where it runs.
#
# Tested without Ghostty (tests/test_mmini.py, written hc answers, pseudo terminals; tmux in a pseudo terminal):
# the sidebar, the tab bar and its menu, view switching, menus, prompts, the separator drag, "needs you", the
# account marks, the keychain line, the dev servers; the tmux layout, clicks, sizes, zoom and divider drag. Untested:
# the launcher app itself and the window in Ghostty, the title in Ghostty, switch time over the network, a locked
# keychain, adding and forgetting a real machine, opening a page in the browser.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
# /Applications when this account may write there (an admin account can, without admin rights asked), else
# ~/Applications.
apps=/Applications
[ -w "$apps" ] || { apps="$HOME/Applications"; mkdir -p "$apps"; }
app="$apps/mmini.app"
install="$HOME/.local/share/mmini"

command -v python3 >/dev/null 2>&1 || { echo "mmini: python3 not found (xcode-select --install)" >&2; exit 1; }
tmux=$(command -v tmux 2>/dev/null || true)
for t in /opt/homebrew/bin/tmux /usr/local/bin/tmux; do
  if [ -z "$tmux" ] && [ -x "$t" ]; then tmux=$t; fi
done
[ -n "$tmux" ] || { echo "mmini: tmux not found (brew install tmux)" >&2; exit 1; }
# mmini.tmux.conf needs tmux 3.5 (extended-keys-format). A version that cannot be read (a build from git) only gets
# a note.
tv=$("$tmux" -V 2>/dev/null | sed -n 's/^tmux \([0-9][0-9]*\)\.\([0-9][0-9]*\).*/\1 \2/p')
case "$tv" in
  '') echo "mmini: note: could not read tmux's version ($("$tmux" -V 2>&1)); 3.5 or newer is needed" >&2 ;;
  *)
    if [ "${tv% *}" -lt 3 ] || { [ "${tv% *}" -eq 3 ] && [ "${tv#* }" -lt 5 ]; }; then
      echo "mmini: tmux 3.5 or newer needed, found $("$tmux" -V) (brew upgrade tmux)" >&2
      exit 1
    fi
    ;;
esac
python3 -c 'import curses' 2>/dev/null || { echo "mmini: this python3 has no curses module" >&2; exit 1; }
[ -x "$HOME/.local/bin/hc" ] || { echo "mmini: $HOME/.local/bin/hc not found" >&2; exit 1; }
for f in mmini.py view.sh start.sh mmini.tmux.conf; do
  [ -r "$install/$f" ] || { echo "mmini: $install/$f missing; install: git clone https://github.com/PerIPan/herdr-core-ghostty-UI $install && sh $install/build.sh" >&2; exit 1; }
done
[ "$here" = "$install" ] || echo "mmini: note: build.sh runs from $here, the app starts the files in $install" >&2

ghostty=""
for p in /Applications/Ghostty.app "$HOME/Applications/Ghostty.app"; do
  if [ -d "$p" ]; then ghostty=$p; break; fi
done
if [ -z "$ghostty" ]; then
  ghostty=$(mdfind "kMDItemCFBundleIdentifier == 'com.mitchellh.ghostty'" 2>/dev/null | head -1)
fi
[ -n "$ghostty" ] || { echo "mmini: Ghostty.app not found" >&2; exit 1; }

# AppleScript control came with Ghostty 1.3.0. A version that cannot be read (a tip build) only gets a warning.
version=$(defaults read "$ghostty/Contents/Info" CFBundleShortVersionString 2>/dev/null || true)
major=${version%%.*}
rest=${version#*.}
minor=${rest%%.*}
case "$major$minor" in
  '' | *[!0-9]*) echo "mmini: note: could not read Ghostty's version ('$version'); 1.3.0 or newer is needed" >&2 ;;
  *)
    if [ "$major" -lt 1 ] || { [ "$major" -eq 1 ] && [ "$minor" -lt 3 ]; }; then
      echo "mmini: Ghostty 1.3.0 or newer needed, found $version ($ghostty)" >&2
      exit 1
    fi
    ;;
esac

# Compile beside the old app; replace it only when the compile worked.
new="$apps/.mmini-build-$$.app"
trap 'rm -rf "$new"' EXIT
rm -rf "$new"
osacompile -o "$new" <<'EOF'
-- One folder per window, so a second mmini window has its own target, view, panes and tmux.
-- start.sh is typed into the new window's login shell, so the settings exported in ~/.zshrc apply; exec: the
-- window closes when mmini's tmux ends.
set homeDir to POSIX path of (path to home folder)
set base to homeDir & ".local/share/mmini/"
set stateDir to homeDir & ".local/state/mmini"
set winDir to do shell script "mkdir -p " & quoted form of stateDir & " && mktemp -d " & quoted form of (stateDir & "/w-XXXXXX")
tell application "Ghostty"
    set cfg to new surface configuration
    set initial input of cfg to "exec env MMINI_WINDOW=" & (quoted form of winDir) & " sh " & (quoted form of (base & "start.sh")) & linefeed
    set win to new window with configuration cfg
    -- after the window exists: a Ghostty that was not running opens no extra empty window when it becomes active
    activate
end tell
EOF
rm -rf "$app"
mv "$new" "$app"
trap - EXIT

# Ghostty's own icon, as a custom Finder icon on the app.
icon="icon from $ghostty"
osascript -l JavaScript - "$ghostty" "$app" >/dev/null <<'EOF' || icon="no icon: could not set it"
ObjC.import("AppKit");
function run(argv) {
  const ws = $.NSWorkspace.sharedWorkspace;
  if (!ws.setIconForFileOptions(ws.iconForFile(argv[0]), argv[1], 0)) throw new Error("could not set the icon");
}
EOF

echo "built $app ($icon; Ghostty ${version:-version unknown}; $("$tmux" -V))"
if [ -d "$HOME/Desktop/mmini.app" ]; then
  echo "  old:    $HOME/Desktop/mmini.app is an older build that is no longer updated: drag it to the Trash"
fi
echo "  starts: $install/start.sh (tmux with mmini.py sidebar and tabs, and view.sh)"
echo "  state:  $HOME/.local/state/mmini (one w-XXXXXX folder per window)"
