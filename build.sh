#!/bin/sh
# Builds hcGUI.app: each start opens one Ghostty window with three panes, run by a tmux of the window's own
# (start.sh, hcgui.tmux.conf). Sidebar on the left (needs you, spaces, servers, dev servers, agents), tab bar on top
# (one tab per terminal of the chosen space or server), and below it the chosen terminal itself (view.sh runs
# `hc attach`, behind `hcgui.py view`, a relay that sends a file dropped for another machine's terminal there with
# `hc put`). The app gets Ghostty's icon.
#
# Install (clones this repo to ~/.local/share/hcgui, then builds):
#
#   git clone https://github.com/PerIPan/herdr-core-GUI ~/.local/share/hcgui && sh ~/.local/share/hcgui/build.sh
#
# Update:
#
#   git -C ~/.local/share/hcgui pull && sh ~/.local/share/hcgui/build.sh
#
# Needs on this Mac: Ghostty 1.3.0 or newer (AppleScript control), tmux (brew install tmux), python3 with curses,
# hc with the machines added. Safe to run again: the new app is compiled beside the old one and only replaces it
# when the compile worked.
#
# What to expect (the automated tests run without Ghostty; tmux was tried in a pseudo terminal):
# - Every start of hcGUI.app opens its own window with its own state folder (~/.local/state/hcgui/w-XXXXXX) and its
#   own tmux server, so two hcGUI windows never switch each other's view. The remembered space and terminals are
#   shared. Closing the window ends its tmux and the panes; the terminals in herdr-core keep running.
# - One click acts, in any pane: tmux passes the click to the pane under the pointer at once. After a pick the
#   keyboard goes to the shown terminal. A right click on a sidebar row or a tab, or in the shown terminal, opens
#   its menu; keys typed then go on to the terminal. A file dropped on the window lands in the terminal; for a
#   terminal on another machine the file is copied there first (hc put; an image over 8 MB as a smaller JPEG).
# - The sidebar is HCGUI_WIDTH columns (30) until the divider is dragged with the mouse; then it keeps the dragged
#   width, also in later windows (~/.local/state/hcgui/width; remove it to go back to 30). The tab bar is 2 rows. A
#   resized window keeps both.
# - The sidebar has three states: open, strip (status dots and the start of each name, HCGUI_NARROW columns) and
#   hidden (its pane closes; the tab bar then shows "›", whose click or the key c brings the sidebar back at full
#   height). c steps through them; the state is kept for the next window.
# - z gives the whole window to the shown terminal (tmux's zoom); a line on top, "‹ back", brings the panes back on
#   a click.
# - Selecting text in the shown terminal: a drag selects with tmux and copies to the clipboard; shift+drag is
#   Ghostty's own selection.
# - The window title names the shown terminal and its server ("web · me@mini"). Claude Code sets its own unless
#   CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 is in the env block of its settings.json where it runs.
# - At the bottom of the open sidebar, one line per Claude subscription: how much of its 5-hour window is used (u
#   or a right click on a line hides them). Only once usage.sh is Claude Code's status line command on the home
#   machine (README: 5-hour usage); without it nothing is drawn.
#
# Tested without Ghostty (tests/test_hcgui.py, written hc answers, pseudo terminals; tmux in a pseudo terminal):
# the sidebar, the tab bar and its menu, view switching, menus, prompts, the separator drag, "needs you", the
# account marks, the keychain line, the dev servers, the usage lines and usage.sh; the tmux layout, clicks,
# sizes, zoom and divider drag; drops sent with a stand-in hc put. Untested: the launcher app itself and the
# window in Ghostty, the title in Ghostty, switch time over the network, a locked keychain, adding and
# forgetting a real machine, opening a page in the browser, a real drop in Ghostty and hc put to a real machine.
# usage.sh also ran as the status line of Claude Code 2.1.331 on one Mac mini, for two subscriptions.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
# /Applications when this account may write there (an admin account can, without admin rights asked), else
# ~/Applications.
apps=/Applications
[ -w "$apps" ] || { apps="$HOME/Applications"; mkdir -p "$apps"; }
app="$apps/hcGUI.app"
install="$HOME/.local/share/hcgui"

command -v python3 >/dev/null 2>&1 || { echo "hcGUI: python3 not found (xcode-select --install)" >&2; exit 1; }
tmux=$(command -v tmux 2>/dev/null || true)
for t in /opt/homebrew/bin/tmux /usr/local/bin/tmux; do
  if [ -z "$tmux" ] && [ -x "$t" ]; then tmux=$t; fi
done
[ -n "$tmux" ] || { echo "hcGUI: tmux not found (brew install tmux)" >&2; exit 1; }
# hcgui.tmux.conf needs tmux 3.5 (extended-keys-format). A version that cannot be read (a build from git) only gets
# a note.
tv=$("$tmux" -V 2>/dev/null | sed -n 's/^tmux \([0-9][0-9]*\)\.\([0-9][0-9]*\).*/\1 \2/p')
case "$tv" in
  '') echo "hcGUI: note: could not read tmux's version ($("$tmux" -V 2>&1)); 3.5 or newer is needed" >&2 ;;
  *)
    if [ "${tv% *}" -lt 3 ] || { [ "${tv% *}" -eq 3 ] && [ "${tv#* }" -lt 5 ]; }; then
      echo "hcGUI: tmux 3.5 or newer needed, found $("$tmux" -V) (brew upgrade tmux)" >&2
      exit 1
    fi
    ;;
esac
python3 -c 'import curses' 2>/dev/null || { echo "hcGUI: this python3 has no curses module" >&2; exit 1; }
[ -x "$HOME/.local/bin/hc" ] || { echo "hcGUI: $HOME/.local/bin/hc not found" >&2; exit 1; }
for f in hcgui.py view.sh start.sh hcgui.tmux.conf usage.sh; do
  [ -r "$install/$f" ] || { echo "hcGUI: $install/$f missing; install: git clone https://github.com/PerIPan/herdr-core-GUI $install && sh $install/build.sh" >&2; exit 1; }
done
[ "$here" = "$install" ] || echo "hcGUI: note: build.sh runs from $here, the app starts the files in $install" >&2

ghostty=""
for p in /Applications/Ghostty.app "$HOME/Applications/Ghostty.app"; do
  if [ -d "$p" ]; then ghostty=$p; break; fi
done
if [ -z "$ghostty" ]; then
  ghostty=$(mdfind "kMDItemCFBundleIdentifier == 'com.mitchellh.ghostty'" 2>/dev/null | head -1)
fi
[ -n "$ghostty" ] || { echo "hcGUI: Ghostty.app not found" >&2; exit 1; }

# AppleScript control came with Ghostty 1.3.0. A version that cannot be read (a tip build) only gets a warning.
version=$(defaults read "$ghostty/Contents/Info" CFBundleShortVersionString 2>/dev/null || true)
major=${version%%.*}
rest=${version#*.}
minor=${rest%%.*}
case "$major$minor" in
  '' | *[!0-9]*) echo "hcGUI: note: could not read Ghostty's version ('$version'); 1.3.0 or newer is needed" >&2 ;;
  *)
    if [ "$major" -lt 1 ] || { [ "$major" -eq 1 ] && [ "$minor" -lt 3 ]; }; then
      echo "hcGUI: Ghostty 1.3.0 or newer needed, found $version ($ghostty)" >&2
      exit 1
    fi
    ;;
esac

# From the old name (mmini, until 24 Nov 2026), once: its state folder (display names, widths, window folders) moves
# to the new one when there is none yet; its app goes when it is the old launcher (it names start.sh in the old
# install folder). Close every old window first: one still open keeps the old folder.
old_state="$HOME/.local/state/mmini"
new_state="$HOME/.local/state/hcgui"
if [ -d "$old_state" ] && [ ! -e "$new_state" ]; then
  mkdir -p "$(dirname "$new_state")" && mv "$old_state" "$new_state" && echo "moved $old_state to $new_state"
fi
for old_app in /Applications/mmini.app "$HOME/Applications/mmini.app" "$HOME/Desktop/mmini.app"; do
  if [ -d "$old_app" ] && osadecompile "$old_app/Contents/Resources/Scripts/main.scpt" 2>/dev/null |
    grep -q ".local/share/mmini"; then
    rm -rf "$old_app" && echo "removed the old $old_app"
  fi
done
old_settings=$(env | sed -n 's/^\(MMINI_[A-Z_]*\)=.*/\1/p' | sort -u | tr '\n' ' ')

# Compile beside the old app; replace it only when the compile worked.
new="$apps/.hcgui-build-$$.app"
trap 'rm -rf "$new"' EXIT
rm -rf "$new"
osacompile -o "$new" <<'EOF'
-- One folder per window, so a second hcGUI window has its own target, view, panes and tmux.
-- start.sh is typed into the new window's login shell, so the settings exported in ~/.zshrc apply; exec: the
-- window closes when hcGUI's tmux ends.
set homeDir to POSIX path of (path to home folder)
set base to homeDir & ".local/share/hcgui/"
set stateDir to homeDir & ".local/state/hcgui"
set winDir to do shell script "mkdir -p " & quoted form of stateDir & " && mktemp -d " & quoted form of (stateDir & "/w-XXXXXX")
tell application "Ghostty"
    set cfg to new surface configuration
    set initial input of cfg to "exec env HCGUI_WINDOW=" & (quoted form of winDir) & " sh " & (quoted form of (base & "start.sh")) & linefeed
    set win to new window with configuration cfg
    -- after the window exists: a Ghostty that was not running opens no extra empty window when it becomes active
    activate
end tell
EOF
rm -rf "$app"
mv "$new" "$app"
trap - EXIT

# From the name hcG-UI (24 Nov 2026): only the app had that name. It goes once the new app is in place (a failed
# build keeps it: it starts the same files), and only when it is this install's launcher (it names start.sh in
# ~/.local/share/hcgui); folders and settings stay as they are. A Dock icon of the old app needs the new one.
for old_app in /Applications/hcG-UI.app "$HOME/Applications/hcG-UI.app"; do
  if [ -d "$old_app" ] && osadecompile "$old_app/Contents/Resources/Scripts/main.scpt" 2>/dev/null |
    grep -q ".local/share/hcgui"; then
    rm -rf "$old_app" && echo "removed the old $old_app (pin $app in the Dock instead)"
  fi
done

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
if [ -n "$old_settings" ]; then
  echo "  rename: $old_settings in ~/.zshrc to HCGUI_... (the old names are no longer read)"
fi
if [ -d "$HOME/.local/share/mmini" ]; then
  echo "  old:    $HOME/.local/share/mmini is the old install, no longer used: rm -rf ~/.local/share/mmini"
fi
echo "  starts: $install/start.sh (tmux with hcgui.py sidebar, tabs and view; view.sh runs under the view)"
echo "  state:  $HOME/.local/state/hcgui (one w-XXXXXX folder per window)"

# What is set up and what is left (README: Setup), last, so whoever runs this sees it: a person, or an AI agent
# installing for one (AGENTS.md). Settings come from this shell, else from an export line in ~/.zshrc (an agent's
# shell may not read it). Only reads: nothing here changes a setting.
setting() {
  v=$(printenv "$1" 2>/dev/null || true)
  [ -n "$v" ] || v=$(sed -n "s/^[[:space:]]*export[[:space:]][[:space:]]*$1=[\"']\{0,1\}\([^\"' #]*\).*/\1/p" \
    "$HOME/.zshrc" 2>/dev/null | tail -1)
  printf '%s' "$v"
}
machines=$("$HOME/.local/bin/hc" machine ls --json 2>/dev/null | python3 -c '
import json, sys
try:
    print(" ".join(str(m.get("name", "")) for m in json.load(sys.stdin).get("machines", []) if m.get("name")))
except Exception:
    pass' 2>/dev/null || true)
count=$(printf '%s' "$machines" | wc -w | tr -d ' ')
first=$(setting HCGUI_FIRST)
echo "setup (README: Setup; AI agents: AGENTS.md):"
if [ -n "$first" ]; then
  home=$first
  echo "  home:   $first (HCGUI_FIRST)"
elif [ "$count" = 1 ]; then
  home=$machines
  echo "  home:   $machines, the only server (export HCGUI_FIRST=<name> in ~/.zshrc for another)"
elif [ "$count" = 0 ]; then
  home=""
  echo "  home:   this Mac (no servers; hc machine add adds one)"
else
  home=""
  echo "  home:   this Mac; servers: $machines. If one of them is home: export HCGUI_FIRST=<name> in ~/.zshrc"
fi
if [ -z "$home" ]; then
  # every Claude Code config folder of this account: ~/.claude, ~/.claude-*, and CLAUDE_CONFIG_DIR
  found=""
  for f in "$HOME/.claude/settings.json" "$HOME"/.claude-*/settings.json "${CLAUDE_CONFIG_DIR:-/nonexistent}/settings.json"; do
    if grep -qs "hcgui/usage.sh" "$f"; then found="$found ${f#"$HOME/"}"; fi
  done
  if [ -n "$found" ]; then
    echo "  usage:  on (usage.sh in$found)"
  else
    echo "  usage:  off (optional): a statusLine per Claude config folder, README: 5-hour usage"
  fi
  command -v jq >/dev/null 2>&1 || [ -x /usr/bin/jq ] || [ -x /opt/homebrew/bin/jq ] ||
    echo "  jq:     not found; the usage lines need it"
else
  echo "  usage:  optional, set up on $home: README: 5-hour usage"
fi
[ -n "$(setting HCGUI_MARKS)" ] ||
  echo "  marks:  none; only for two or more subscriptions: export HCGUI_MARKS=\"name=¹,other=²\" in ~/.zshrc"
echo "  then:   close every hcGUI window, start hcGUI.app (settings are read when a window opens)"
