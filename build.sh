#!/bin/sh
# Builds mmini.app: one Ghostty window with three panes. Sidebar on the left (needs you, spaces,
# servers, dev servers, agents),
# tab bar on top (one tab per terminal of the chosen space or server), and below it the chosen terminal itself
# (view.sh runs `hc attach`). The app gets Ghostty's icon.
#
# Install (clones this repo to ~/.local/share/mmini, then builds):
#
#   git clone https://github.com/PerIPan/herdr-core-ghostty-UI ~/.local/share/mmini && sh ~/.local/share/mmini/build.sh
#
# Update:
#
#   git -C ~/.local/share/mmini pull && sh ~/.local/share/mmini/build.sh
#
# Needs on this Mac: Ghostty 1.3.0 or newer (AppleScript control), python3 with curses, hc with the machines added.
# Safe to run again: the new app is compiled beside the old one and only replaces it when the compile worked.
#
# What to expect from Ghostty (read from its source; the automated tests run without Ghostty):
# - Every start of mmini.app opens its own window with its own state folder (~/.local/state/mmini/w-XXXXXX), so
#   two mmini windows never switch each other's view. The remembered space and terminals are shared.
# - No split can be smaller than a tenth of the window: the tab bar is about a tenth of the window height (not 2
#   rows) and uses the spare rows for wrapped tabs and a line about the shown terminal.
# - The sidebar goes back to its width after the window changes size: Ghostty keeps a split as a share of the
#   window, never as a number of columns. Its width is MMINI_WIDTH columns (30) until the divider between the
#   sidebar and the right side is dragged with the mouse (Ghostty lets every split divider be dragged): the sidebar
#   then keeps the dragged width, and the open sidebar of every later window starts with it (the file
#   ~/.local/state/mmini/width; remove it to go back to 30). A drag of the folded strip lasts until the next c or o.
#   The sidebar tells a drag from a resized window by the tab bar's width: a drag moves the two widths in opposite
#   directions.
# - The sidebar has three states: open, strip and hidden. The key c steps through them in that order; the line at
#   the bottom of the sidebar says the next step ("‹ fold", then "‹ hide") and a click on it does the same.
#   - strip: status dots and the start of each name. Ghostty stops the strip at a tenth of the window, so on a wide
#     window it is wider than MMINI_NARROW (6 columns): about 12 columns on a 120-column window, 25 on a 250-column
#     one. The line above "‹ hide" reads "› open": a click on it, or the key o, opens the sidebar again. s and m
#     open it too before they ask.
#   - hidden: the sidebar's program ends and Ghostty closes its pane; the tab bar and the view take the full width.
#     q does the same from either state: q now closes the sidebar's pane, it never leaves a shell prompt behind.
#     The tab bar then lists the terminals itself and shows "›" in its top left corner. A click on "›", or the key
#     c in the tab bar, brings the sidebar back, open and at full height: two new splits of the view (sidebar, then
#     a new tab bar), after which the old tab bar ends. Should that not happen within 10 seconds, the old tab bar
#     stays and says "could not open the sidebar".
#   The state is kept for the next start of any mmini window. A window that starts hidden shows the sidebar's pane
#   for about a second, then that pane closes.
# - z (in the sidebar or the tab bar) gives the whole window to the shown terminal: Ghostty's split zoom. The
#   sidebar and the tab bar cannot be seen then, so they cannot show the way back: cmd+shift+enter (Ghostty's own
#   key for the split zoom) brings them back; a Ghostty config that binds toggle_split_zoom to another key makes
#   that key the way back. While a zoom may last, the sidebar and the tab bar do not size themselves: Ghostty
#   ignores a resize of a pane hidden by the zoom, and a resize of the zoomed pane would end the zoom. A window
#   that changed size meanwhile gets its sidebar width back at the next key or click in the sidebar.
# - Each sidebar row has a menu: the key a, or a right click on the row (Open, New terminal here, Rename, Move to
#   space, Delete space / Forget server / End terminal, as the row allows, and Show / Hide servers; e renames and d
#   deletes without the menu). A right click reaches mmini only when Ghostty passes it on to the program, which asks
#   for the mouse; Ghostty may show its own context menu instead (untested). The key a
#   always works. A delete asks for the name first. "+ add server" opens a new terminal on this Mac that runs
#   `hc machine add`: its questions (install hc there, a password, a code) are answered in that terminal, which
#   gets the view and the keyboard.
# - The sidebar shows no key hints. The key ? lists the keys (a dim "?" at the end of the sidebar's last line does
#   the same on a click); any key or click closes the list. In the tab bar ? shows its keys in its message line.
# - Servers: every machine hc knows, the home machine included, plus this Mac while it runs terminals, each named
#   user@host of its ssh target (me@mini). The section is hidden until v (or "Show servers" in any row menu)
#   shows it; the choice is kept for every window. The home machine's row holds all its terminals; it is never
#   forgotten. The home machine is MMINI_FIRST; unset, the only machine `hc machine ls` knows, else this Mac.
# - The first click on a pane that does not have the keyboard only moves the focus there; the second click acts.
#   Ghostty 1.3 decides this itself (it keeps the focusing click from the program) and has no setting for one pane
#   or one window, only "focus-follows-mouse = true" for all of Ghostty: the pane under the pointer then already
#   has the focus, so one click is enough. The limit: the keyboard then follows the pointer. After a click on a tab
#   or sidebar row the pointer is still over that pane, and the next pointer movement brings the keyboard back to
#   it, where typed letters are mmini's keys (q, a, e, d, n, s, m, v, g, w, c, z, h, l, [, ], -, =, ?). So the pointer goes into the
#   terminal before typing. A right click is not held back: it reaches an unfocused pane at once.
# - The window title names the shown terminal and its server ("web · me@mini", "t9 · this Mac"; nothing
#   shown: "mmini"), from whichever pane has the keyboard: the sidebar and the tab bar set it when it changes, the
#   view before each attach and after one. While attached, the program may set its own: Claude Code does, unless
#   CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 is in the env block of its settings.json where it runs (mmini never
#   changes it).
# - The folder icon next to the window title (macOS proxy icon) is the focused pane's folder. mmini's panes clear
#   theirs; only the setting "macos-titlebar-proxy-icon = hidden" (for all of Ghostty; Ghostty 1.3 has no way to
#   set it per window) also hides it while a terminal of this Mac is shown in the view.
#   This script checks both settings and prints the lines to add, last; it never edits the config.
# - Switching: a click on a tab or a row acts when the button goes down (ncurses no longer waits up to a third of a
#   second for a possible double click), and the view keeps the old terminal on screen until the new one is drawn,
#   with no blank pane between. Timed on one Mac (its own terminals, no network): 18 ms from the pick to the new
#   attach's first byte, was 62. Network time to another machine comes on top and was not timed.
# - The separator above the agents in the sidebar can be moved: press on it, move the pointer with the button held
#   (the line follows; the sidebar asks Ghostty for these moves, mode 1002, which Ghostty's source honours), let go.
#   [ or - moves it up a row, ] or = down; a double click on it brings back the automatic layout. Kept for every
#   window as a share of the sidebar's height (~/.local/state/mmini/split; remove it to go back). Should Ghostty
#   send no moves, the line still goes where the button is let go, without following the pointer.
# - "needs you" at the top of the sidebar: agents blocked or in error, and agents done that were not shown since
#   (kept for every window in ~/.local/state/mmini/seen.json). Enter or a click shows one; a done one then goes.
# - Claude Code agents can carry a mark for the login they bill, on their row and their tab, read from the
#   terminal's label "account" in the core where it runs and looked up in MMINI_MARKS ("personal=¹,work=²"; a
#   value not in it gets ³; unset: no marks). An unlabelled one on a server whose ssh user is MMINI_SHARED_USER gets
#   MMINI_SHARED_MARK (³). Set with `hc label <t> account=<name>` (on another machine: `hc label <machine>/<t> ...`).
# - A red line "keychain locked: API billing" at the bottom of the sidebar while the home machine's login keychain
#   is locked, as its herdr-core sees it (`hc exec --on <home> security show-keychain-info`, read-only; at the
#   start, then every 4 hours; every minute while locked; after a failed check 5 minutes, doubled up to 4 hours;
#   MMINI_KEYCHAIN=0 turns it off). A click shows the home machine's terminal "unlock" (or opens a shell of that
#   name there); nothing is typed into it.
# - "dev servers": node programs (MMINI_DEV_PROGRAM) of the account the home machine's herdr-core runs as,
#   listening on the home machine (another account's programs are not seen without admin rights), asked with
#   `hc exec --on <home> lsof` every 60 seconds. Enter or a click opens http://<host>:<port>/ in the default browser.
#   w hides or shows the section, g the agents (also in every row menu); both kept for every window.
#
# Tested without Ghostty (tests/test_mmini.py, written hc answers, pseudo terminals): the sidebar, the tab bar, view
# switching, menus, prompts, the separator drag, "needs you", the account marks, the keychain line and the dev
# servers. Untested: the launcher app itself, the window, the splits and their sizes, dragging the divider, the
# folder icon, the window title in Ghostty, bringing the sidebar back at full height, the zoom and the way back from
# it, mouse clicks, a right click in Ghostty, adding and forgetting a real machine, switch time over the network, a
# locked keychain (the answer of security when locked is taken from macOS's error codes), and opening a page in the
# browser.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
# /Applications when this account may write there (an admin account can, without admin rights asked), else
# ~/Applications.
apps=/Applications
[ -w "$apps" ] || { apps="$HOME/Applications"; mkdir -p "$apps"; }
app="$apps/mmini.app"
install="$HOME/.local/share/mmini"

command -v python3 >/dev/null 2>&1 || { echo "mmini: python3 not found (xcode-select --install)" >&2; exit 1; }
python3 -c 'import curses' 2>/dev/null || { echo "mmini: this python3 has no curses module" >&2; exit 1; }
[ -x "$HOME/.local/bin/hc" ] || { echo "mmini: $HOME/.local/bin/hc not found" >&2; exit 1; }
for f in mmini.py view.sh; do
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
-- One folder per window, so a second mmini window has its own target, view and pane ids.
-- View first; the sidebar is split off to its left, the tab bar above it. Each sizes itself (mmini.py).
-- The sidebar and the tab bar start with exec: the program replaces the login shell, so its pane closes when the
-- program ends (the sidebar ends when it is hidden). The view keeps its shell.
set homeDir to POSIX path of (path to home folder)
set base to homeDir & ".local/share/mmini/"
set stateDir to homeDir & ".local/state/mmini"
set winDir to do shell script "mkdir -p " & quoted form of stateDir & " && mktemp -d " & quoted form of (stateDir & "/w-XXXXXX")
set pre to "env MMINI_WINDOW=" & (quoted form of winDir) & " "
tell application "Ghostty"
    set viewCfg to new surface configuration
    set initial input of viewCfg to pre & "sh " & (quoted form of (base & "view.sh")) & linefeed
    set win to new window with configuration viewCfg
    -- after the window exists: a Ghostty that was not running opens no extra empty window when it becomes active
    activate
    set viewTerm to focused terminal of selected tab of win
    set sideCfg to new surface configuration
    set initial input of sideCfg to "exec " & pre & "python3 " & (quoted form of (base & "mmini.py")) & " sidebar" & linefeed
    set sideTerm to split viewTerm direction left with configuration sideCfg
    set tabsCfg to new surface configuration
    set initial input of tabsCfg to "exec " & pre & "python3 " & (quoted form of (base & "mmini.py")) & " tabs" & linefeed
    set tabsTerm to split viewTerm direction up with configuration tabsCfg
    set ids to "side=" & (id of sideTerm) & linefeed & "tabs=" & (id of tabsTerm) & linefeed & "view=" & (id of viewTerm) & linefeed
    tell current application to do shell script "printf %s " & quoted form of ids & " > " & quoted form of (winDir & "/panes.tmp") & " && mv " & quoted form of (winDir & "/panes.tmp") & " " & quoted form of (winDir & "/panes")
    -- Ghostty gives the keyboard to every new split itself, a little later: while the new pane is not in the
    -- window yet it tries again 50, 150, 350 and 750 ms after the split. Wait until that is over, or the
    -- keyboard ends in the tab bar (the last split) instead of the sidebar.
    tell current application to delay 0.8
    -- a sidebar started while it is hidden has ended by now (after the ids were written): then the view
    try
        focus sideTerm
    on error
        focus viewTerm
    end try
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

echo "built $app ($icon; Ghostty ${version:-version unknown})"
if [ -d "$HOME/Desktop/mmini.app" ]; then
  echo "  old:    $HOME/Desktop/mmini.app is an older build that is no longer updated: drag it to the Trash"
fi
echo "  starts: $install/mmini.py (sidebar, tabs) and $install/view.sh"
echo "  state:  $HOME/.local/state/mmini (one w-XXXXXX folder per window)"

# --- Ghostty settings mmini cannot set for its own window (see the header). Read only, printed last so it is seen.
# The last setting wins, in the order Ghostty 1.3.0 reads its config files: ~/.config/ghostty first, then
# Application Support; in each folder "config" (the name before 1.2.3), then "config.ghostty". Files pulled in with
# "config-file = ..." are not followed.
xdg="${XDG_CONFIG_HOME:-$HOME/.config}/ghostty"
mac="$HOME/Library/Application Support/com.mitchellh.ghostty"
cfg="$xdg/config.ghostty" # where to add the lines: the last config file there is, else this one
setting() { # $1 = a Ghostty setting: its value as the config files leave it, "" when not set
  v=""
  for c in "$xdg/config" "$xdg/config.ghostty" "$mac/config" "$mac/config.ghostty"; do
    if [ -r "$c" ]; then
      x=$(sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$c" | tail -1 | tr -d '"[:space:]')
      if [ -n "$x" ]; then v=$x; fi
    fi
  done
  printf '%s' "$v"
}
for c in "$xdg/config" "$xdg/config.ghostty" "$mac/config" "$mac/config.ghostty"; do
  if [ -r "$c" ]; then cfg=$c; fi
done
ffm=$(setting focus-follows-mouse)
proxy=$(setting macos-titlebar-proxy-icon)
if [ "$ffm" != true ] || [ "$proxy" != hidden ]; then
  echo
  echo "mmini: hint: add these lines to the Ghostty config ($cfg), then reload it in Ghostty (cmd+shift+,):"
  echo
  if [ "$ffm" != true ]; then echo "    focus-follows-mouse = true"; fi
  if [ "$proxy" != hidden ]; then echo "    macos-titlebar-proxy-icon = hidden"; fi
  echo
  if [ "$ffm" != true ]; then
    echo "  focus-follows-mouse: one click on a tab or a sidebar row is enough. Without it the first click on a pane only gives it the keyboard (Ghostty 1.3 keeps that click from the program); the second click acts. The keyboard then follows the pointer: move the pointer into the terminal before typing."
  fi
  if [ "$proxy" != hidden ]; then
    echo "  macos-titlebar-proxy-icon: no folder icon next to the window title. mmini already clears the folder of its own panes; this line also hides it while a terminal of this Mac is shown. Ghostty applies it once a pane's folder changes again."
  fi
  echo "  Both lines count for every Ghostty window, so build.sh only prints them and never edits the config."
fi
