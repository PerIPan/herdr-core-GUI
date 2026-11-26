#!/bin/sh
# hcGUI view: the main pane of the hcGUI window. Shows the terminal the sidebar or tab bar (hcgui.py) picked, by
# running `hc attach` on the address in the window's state folder. A pick writes "target" and bumps the counter
# "gen"; this loop then attaches to the new address. ctrl+\ detaches and waits for the next pick.
#
# How a pick always wins, also two picks a few milliseconds apart:
# - the attach is this script's own child; view.pid holds its pid, view.loop this script's pid. hcgui.py ends the
#   attach at once (SIGTERM, only when the pid is a child of this loop and its command line is an attach);
# - a watcher beside every attach ends it as soon as "gen" differs from the value read BEFORE "target". So when
#   hcgui.py found nothing to end (the attach was not started yet), the watcher still does it within 0.2 s.
# Signals only ever go to the attach this script started itself.
#
# How a switch stays quick (measured on one Mac, two terminals of its own core, from the pick to the new
# attach's first byte: 62 ms before, 18 ms now): between two attaches the pane is not wiped (hc attach clears and
# draws the whole pane itself as it starts; a wipe here only showed a blank pane until then), the files are read
# with the shell's own `read`, and the only process started besides hc is the input flush. While nothing is
# attached, a pick is seen within 10 ms (idle_wait).
set -u

hc="${HCGUI_HC:-$HOME/.local/bin/hc}"
shared="${HCGUI_STATE:-$HOME/.local/state/hcgui}"
# The right pane's view (a shell beside the shown terminal) has a folder of its own inside the window's: HCGUI_VIEW_DIR.
state="${HCGUI_VIEW_DIR:-${HCGUI_WINDOW:-$shared}}"
mkdir -p "$state"

if [ ! -x "$hc" ]; then
  printf 'hcGUI view: hc not found at %s (set HCGUI_HC, or install herdr-core).\n' "$hc"
  # On screen the message stays: in tmux the pane would close with this script.
  if [ -t 1 ]; then while :; do sleep 3600; done; fi
  exit 1
fi

# ctrl+\ a second time, ctrl+C or ctrl+Z while nothing is attached would otherwise end or stop this loop, and
# later picks would do nothing without a word. hc attach reads its keys raw, so it is not affected.
trap '' QUIT INT TSTP

pid=""
idler=""
cleanup() {
  [ -n "$pid" ] && kill "$pid" 2>/dev/null
  [ -n "$idler" ] && kill "$idler" 2>/dev/null
  rm -f "$state/view.pid" "$state/view.pid.tmp"
  [ "$(cat "$state/view.loop" 2>/dev/null)" = "$$" ] && rm -f "$state/view.loop"
  stty sane 2>/dev/null
}
trap 'cleanup; exit 0' HUP TERM
trap cleanup EXIT

# Between a pick and the next attach every started process costs 1-12 ms (a cat 1-3, perl with a module 12), so
# that path reads files with the shell's own `read` and starts one process only (the input flush) besides hc.

# The pick counter into $now_gen ("0" while there is none). The redirect's error goes to /dev/null first.
read_gen() {
  now_gen=0
  IFS= read -r now_gen 2>/dev/null <"$state/gen"
  [ -n "$now_gen" ] || now_gen=0
}

# The picked address into $target ("" while there is none).
read_target() {
  target=""
  IFS= read -r target 2>/dev/null <"$state/target"
}

target=""

# The window title for the address $1 into $tt, as the sidebar or the tab bar wrote it to the file "title"
# (hcgui.py's write_title: the address, then its title, e.g. "web · me@mini"). Nothing shown, or the
# file names another terminal: "hcGUI". Control characters are dropped (hcgui.py writes none): none may reach the
# escape. Only a title that has one costs a process (tr).
title_of() {
  tt=hcGUI
  if [ -n "$1" ] && [ -r "$state/title" ]; then
    { IFS= read -r ta; IFS= read -r tb; } <"$state/title"
    [ "$ta" = "$1" ] && [ -n "$tb" ] && tt=$tb
  fi
  case $tt in
    *[[:cntrl:]]*) tt=$(printf '%s' "$tt" | tr -d '\000-\037\177') ;;
  esac
  [ -n "$tt" ] || tt=hcGUI
}

# The pane's title (OSC 2) for the address $1.
set_title() {
  title_of "$1"
  printf '\033]2;%s\007' "$tt"
}

# The title of the address $1 ("hcGUI" while none), then an empty working directory (OSC 7 without a URL; as
# hcgui.py's PANE_TITLE): Ghostty shows the focused pane's folder as an icon next to the window title, and the login
# shell that started this script reported its home folder. Again before and after each attach: what ran there may
# have set them. The title comes first: Ghostty 1.3 lets an empty OSC 7 clear the title only while it has seen
# none, and a title of under 256 bytes (hcgui.py keeps it so) counts as seen.
own_title() {
  set_title "$1"
  printf '\033]7;\007'
}

# Before an attach to $1: hcgui.py writes "title" before the target (show), so it is there at once. When the file
# names another terminal (an engine wrote it a moment late), wait up to 0.5 s for the right one, unless a newer
# pick comes first ($2: the counter read before the target). No file (nothing of hcGUI runs): no wait.
wait_title() {
  i=0
  while [ "$i" -lt 5 ] && [ -r "$state/title" ]; do
    ta=""
    IFS= read -r ta 2>/dev/null <"$state/title"
    [ "$ta" = "$1" ] && return 0
    read_gen
    [ "$now_gen" = "$2" ] || return 0
    sleep 0.1
    i=$((i + 1))
  done
}

# The modes an attached program may have left on (hc attach resets them itself when it ends, also on SIGTERM; this
# is for one that did not): main screen, no mouse reporting, no bracketed paste, cursor on, plain colours. A
# builtin printf, no process.
reset_modes() {
  printf '\033[?1049l\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?2004l\033[?25h\033[0m'
}

# Leave the pane usable when no attach follows: sane input, reset_modes, the pane's own title (of $target). $1 =
# clear: also wipe the screen (not after a failed attach, whose message must stay readable).
clean_screen() {
  stty sane 2>/dev/null
  reset_modes
  own_title "$target"
  [ "$1" = clear ] && printf '\033[2J\033[H'
  return 0
}

# Throw away input that arrived while nothing was attached (keys, a terminal's late answers to the queries of an
# attach that was ended at once): hc attach would pass it to the next terminal picked. TIOCFLUSH (FREAD) is what
# tcflush(TCIFLUSH) does on macOS; plain perl starts in 3-4 ms, perl with POSIX in 12.
flush_input() {
  /usr/bin/perl -e 'my $w = pack("i", 1); ioctl(STDIN, 0x80047410, $w) or exit 1' <&3 2>/dev/null ||
    /usr/bin/perl -MPOSIX -e 'tcflush(0, TCIFLUSH)' <&3 2>/dev/null ||
    python3 -c 'import termios; termios.tcflush(0, termios.TCIFLUSH)' <&3 2>/dev/null || true
}

# Beside one attach ($1 its pid, $2 the counter it was started for): end it when the counter moves on. Stops by
# itself when the attach or this script is gone.
watch() {
  while kill -0 "$1" 2>/dev/null && kill -0 "$$" 2>/dev/null; do
    read_gen
    if [ "$now_gen" != "$2" ]; then
      kill "$1" 2>/dev/null
      return 0
    fi
    sleep 0.2
  done
}

# While nothing is attached: wait until the counter differs from $1. 0 = a pick came; 1 = the pane is gone (looked
# at every 5 s, see gone). One perl process reads the file every 10 ms (no measurable load), so a pick is seen
# within that; the shell loop below, the fallback, needs up to 0.2 s and a process per look.
idle_wait() {
  /usr/bin/perl -e '
    my ($file, $seen, $tty) = @ARGV;
    for (my $n = 1; ; $n++) {
      my $now = "0";
      if (open(my $fh, "<", $file)) { my $line = <$fh>; close $fh; $now = $line if defined $line; }
      chomp $now; $now = "0" if $now eq "";
      exit 0 if $now ne $seen;
      exit 3 if $tty && $n % 500 == 0 && !defined(syswrite(STDOUT, "", 0));
      select(undef, undef, undef, 0.01);
    }' "$state/gen" "$1" "$on_tty" >&3 2>/dev/null &
  idler=$! # in the background and waited for: a signal to this script is handled at once, not after the wait
  wait "$idler"
  idle_rc=$?
  idler=""
  case $idle_rc in
    0) return 0 ;;
    3) return 1 ;;
  esac
  n=0
  while :; do
    read_gen
    [ "$now_gen" = "$1" ] || return 0
    n=$((n + 1))
    if [ "$n" -ge 25 ]; then # every 5 s
      n=0
      gone && return 1
    fi
    sleep 0.2
  done
}

# $1 = a pid file: is the process it names still running?
alive() {
  p=$(cat "$1" 2>/dev/null || true)
  case "$p" in
    '' | *[!0-9]*) return 1 ;;
  esac
  kill -0 "$p" 2>/dev/null
}

# Window folders of closed windows (made by the launcher app, one per window): remove those older than two days
# that hold a panes file and whose sidebar and view are both not running. A view can outlive its sidebar (q in the
# sidebar) and stay attached for days: without its folder its watcher would end the attach.
sweep() {
  for d in "$shared"/w-*; do
    [ -d "$d" ] && [ "$d" != "$state" ] && [ -e "$d/panes" ] || continue
    [ -n "$(find "$d" -maxdepth 0 -mtime +2 2>/dev/null)" ] || continue
    alive "$d/sidebar.pid" && continue
    alive "$d/view.loop" && continue
    rm -rf "$d"
  done
}
[ "$state" != "$shared" ] && [ "$(dirname "$state")" = "$shared" ] && sweep

exec 3<&0 # the pane's keyboard, handed to each attach (a background child would get /dev/null otherwise)

# The pane was closed but the hangup signal did not end this script (whoever started it had switched it off):
# stop, instead of looping for ever beside a terminal that is gone. On macOS such a terminal still looks like
# one; only a write fails, so this writes nothing (zero bytes) and looks at the result.
on_tty=0
[ -t 3 ] && on_tty=1
gone() {
  [ "$on_tty" = 1 ] && /usr/bin/perl -e 'exit(defined(syswrite(STDOUT, "", 0)) ? 1 : 0)' >&3 2>/dev/null
}

rm -f "$state/view.pid" "$state/view.pid.tmp"
printf '%s\n' "$$" >"$state/view.loop.tmp" && mv -f "$state/view.loop.tmp" "$state/view.loop"
[ "$on_tty" = 1 ] && own_title "$target"

# With HCGUI_AUTOOPEN=0 nothing is shown until something is picked, also when an earlier run left a target.
first=1
dirty=0 # the pane holds what an attach or this loop drew, and no attach replaced it yet
while :; do
  read_gen
  gen=$now_gen # before target: a pick that lands in between costs one extra attach, never a lost pick
  read_target
  [ "$first" = 1 ] && [ "${HCGUI_AUTOOPEN:-1}" = 0 ] && target=""
  first=0
  rc=0
  if [ -n "$target" ]; then
    wait_title "$target" "$gen"
    read_gen
    [ "$now_gen" != "$gen" ] && continue # a newer pick came meanwhile: nothing was attached yet
    flush_input
    own_title "$target" # the attached program may set its own (Claude Code does)
    "$hc" attach "$target" <&3 &
    pid=$!
    printf '%s\n' "$pid" >"$state/view.pid.tmp" && mv -f "$state/view.pid.tmp" "$state/view.pid"
    watch "$pid" "$gen" </dev/null 3<&- &
    watcher=$!
    wait "$pid"
    rc=$?
    pid=""
    kill "$watcher" 2>/dev/null
    wait "$watcher" 2>/dev/null
    dirty=1
  fi
  read_gen
  if [ "$now_gen" != "$gen" ]; then
    # A new pick: its attach starts at once and draws the whole pane itself (hc attach clears it first), so the
    # pane is not wiped here: that only showed a blank pane until then. view.pid stays until the next attach
    # replaces it (hcgui.py checks the process behind it); an rm here would cost a process on the way.
    reset_modes
    continue
  fi
  rm -f "$state/view.pid"
  gone && exit 0
  if [ -z "$target" ]; then
    if [ "$dirty" = 1 ]; then clean_screen clear; else clean_screen keep; fi
  elif [ "$rc" -eq 0 ] || [ "$rc" -ge 128 ]; then
    clean_screen clear
    printf '\n  %s is not shown any more (detached or ended).\n' "$target"
  else
    clean_screen keep
    printf '\n  could not show %s (hc exit %s).\n' "$target" "$rc"
  fi
  printf '  Pick a terminal: a tab above, or a row in the sidebar (select it, press enter).\n'
  dirty=1
  stty -echo 2>/dev/null # keys typed now go nowhere, so they must not look accepted (the attach that follows
  # takes the input as it finds it and gives it back so; clean_screen makes it sane again)
  idle_wait "$gen" || exit 0
done
