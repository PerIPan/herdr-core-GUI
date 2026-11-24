#!/bin/sh
# usage.sh: a Claude Code status line command that saves the 5-hour usage of one Claude subscription for hcGUI's
# sidebar. It prints nothing, so Claude Code's status line stays empty, and it always ends with exit 0.
#
#   sh usage.sh <name>        (name: 1 to 32 of A-Z a-z 0-9 . _ -; the account label, e.g. claude or claude-2)
#
# Put in the settings.json of each Claude Code config folder on the machine where Claude Code runs (one name per
# subscription), for example:
#
#   {"statusLine": {"type": "command", "command": "sh \"$HOME/.local/share/hcgui/usage.sh\" claude"}}
#
# Claude Code runs it at the start of a session and again after each answer (and a few other events), with a JSON
# object on stdin. For claude.ai subscribers, after the first answer of a session, that object holds
# rate_limits.five_hour.used_percentage (0 to 100) and rate_limits.five_hour.resets_at (Unix epoch seconds), and the
# same for seven_day; Claude Code drops a window once its resets_at has passed. Only these numbers are read: no
# login, no token, no network.
#
# When both numbers of five_hour are there, one line of JSON goes to ${HCGUI_STATE:-$HOME/.local/state/hcgui}/usage/
# <name>.json, written to a temporary file in that folder first and then renamed, so a reader never sees half a file:
#
#   {"name":"claude","five_hour":{"used_percentage":42,"resets_at":1764000000},"seven_day":{...},"at":1763990000}
#
# (seven_day only when present; resets_at as a whole number; at = when it was written.) Nothing else is written:
# no rate_limits (an API key, before the first answer, a passed window), a name that is not allowed, no jq.
#
# Every session of a subscription writes the same file, and an idle session may run the command again with the
# numbers of its last answer (a permission mode change, a changed statusLine setting). So a newer number is not
# replaced by an older one: while the saved window still runs and the saved number is under 10 minutes old, a value
# of the same window (resets_at within an hour of each other; windows are 5 hours long) replaces it only when it is
# not lower (usage only grows within a window); a value of an earlier window never does. The 10 minutes: a wrong
# number (a session still running on another login than its config folder's, as seen on 24 Nov 2026) is put
# right by the next answer of a right session after at most that long, not only when the window ends.
#
# jq: /usr/bin/jq (part of recent macOS versions), else the one in PATH, else /opt/homebrew/bin/jq.

# The C locale, before the name is checked: in a UTF-8 one (Claude Code passes on the session's, e.g.
# LANG=en_US.UTF-8) sh's [A-Za-z] can match letters such as é and ${#name} counts characters, not bytes, and hcGUI
# reads ASCII names only (a file it would never draw). jq reads and writes UTF-8 in any locale.
LC_ALL=C
export LC_ALL

name=${1-}
# stdin is read to its end in every case: Claude Code writes the JSON into a pipe
drain() { [ -t 0 ] || cat >/dev/null 2>&1; exit 0; }
case $name in
  '' | *[!A-Za-z0-9._-]*) drain ;;
esac
[ "${#name}" -le 32 ] || drain

jq=
for j in /usr/bin/jq "$(command -v jq 2>/dev/null)" /opt/homebrew/bin/jq; do
  if [ -n "$j" ] && [ -x "$j" ]; then jq=$j; break; fi
done
[ -n "$jq" ] || drain

# The terminal's label "account": inside a herdr-core terminal (HC_TERMINAL_ID, set by hc) with no such label yet,
# it is set to <name>, so hcGUI knows the subscription a session runs on (its mark, the row below the tabs) with no
# label typed by hand. A label already there is never changed: one set by hand, or one another tool reads, stays.
# Checked once per terminal and name: a small file per terminal in labels/ remembers it (HC_SCOPE in it too, so a
# reused terminal id is checked again); a failed `hc get` or `hc label` leaves none, so the next run tries again.
# HCGUI_ACCOUNT_LABEL=0 turns it off. hc: the one in PATH, else ~/.local/bin/hc.
label() {
  [ "${HCGUI_ACCOUNT_LABEL-1}" != 0 ] || return 0
  id=${HC_TERMINAL_ID-}
  case $id in
    '' | *[!A-Za-z0-9._-]*) return 0 ;;
  esac
  [ "${#id}" -le 64 ] || return 0
  hc=$(command -v hc 2>/dev/null) || hc=
  case $hc in
    /*) ;;
    *) hc=$HOME/.local/bin/hc ;;
  esac
  [ -x "$hc" ] || return 0
  seen=${HCGUI_STATE:-$HOME/.local/state/hcgui}/labels
  want="${HC_SCOPE-} $name"
  [ "$(/usr/bin/head -c 300 "$seen/$id" 2>/dev/null)" != "$want" ] || return 0
  info=$("$hc" get "$id" </dev/null 2>/dev/null) || return 0
  have=$(printf '%s' "$info" | "$jq" -r '.labels.account // "" | if type == "string" then . else "?" end' \
    2>/dev/null) || return 0
  if [ -z "$have" ]; then
    "$hc" label "$id" "account=$name" </dev/null >/dev/null 2>&1 || return 0
  fi
  mkdir -p "$seen" 2>/dev/null && printf '%s' "$want" >"$seen/$id" 2>/dev/null
  return 0
}

label

dir=${HCGUI_STATE:-$HOME/.local/state/hcgui}/usage
file=$dir/$name.json
mkdir -p "$dir" 2>/dev/null || drain
old=
if [ -f "$file" ]; then old=$(/usr/bin/head -c 4096 "$file" 2>/dev/null); fi
tmp=$(mktemp "$dir/.$name.XXXXXX" 2>/dev/null) || drain
trap 'rm -f "$tmp"; exit 0' HUP INT TERM

# empty output: nothing to write (no numbers, or the saved value is newer)
program='
def num: type == "number";
def window: if type == "object" and (.used_percentage | num) and (.resets_at | num)
  then {used_percentage, resets_at: (.resets_at | floor)} else null end;
def gap($a; $b): ($a - $b) | if . < 0 then -. else . end;
(now | floor) as $now
| (try (.rate_limits.five_hour | window) catch null) as $five
| (try (.rate_limits.seven_day | window) catch null) as $seven
| (try ($old | fromjson | .five_hour | window) catch null) as $saved
| (try ($old | fromjson | .at | if num then . else 0 end) catch 0) as $saved_at
| if $five == null then empty
  elif $saved != null and $saved.resets_at > $now and $saved.resets_at <= $now + 19200
       and (($saved.resets_at - $five.resets_at > 3600)
            or (gap($saved.resets_at; $five.resets_at) <= 3600 and $saved.used_percentage > $five.used_percentage
                and $now - $saved_at < 600))
  then empty
  else {name: $name, five_hour: $five} + (if $seven == null then {} else {seven_day: $seven} end) + {at: $now}
  end'
if "$jq" -c --arg name "$name" --arg old "$old" "$program" >"$tmp" 2>/dev/null && [ -s "$tmp" ]; then
  mv -f "$tmp" "$file" 2>/dev/null || rm -f "$tmp"
else
  rm -f "$tmp"
fi
exit 0
