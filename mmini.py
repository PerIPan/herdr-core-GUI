#!/usr/bin/env python3
"""mmini: sidebar and tab bar for herdr-core (`hc`) terminals, in one Ghostty window.

herdr-core draws nothing itself, so the window runs a tmux of its own (start.sh, mmini.tmux.conf) with three panes:
this file draws two of them ("python3 mmini.py sidebar" on the left, "python3 mmini.py tabs" on top), view.sh is the
third (it runs `hc attach` on the terminal the other two picked). tmux passes a click to the pane under the pointer
at once, so no click is spent on moving the keyboard first; after a pick the keyboard goes to the view (focus_view).

The sidebar lists, top to bottom, "needs you" (agents blocked or in error, and agents done that were not shown
since; only while there is one), "spaces" (projects on the home machine), "servers" (every machine
`hc machine ls` knows, the home machine included, plus "this Mac" while it runs terminals; each drawn as user@host of
its ssh target), "dev servers" (node programs, or MMINI_DEV_PROGRAM, of the home core's own account listening on
the home machine, opened in this Mac's browser; only while there is one) and "agents". The servers section is hidden until shown (v, or "Show servers" in any row menu;
the file "servers"); the agents (g) and the dev servers (w) are shown until hidden (the files "agents",
"devservers"). While the home machine's login keychain is locked (checked through its core at the start, then every
4 hours; MMINI_KEYCHAIN=0 turns the check off), a red line at the bottom says so; a click on it shows the terminal
"unlock" there (or opens one). A Claude Code agent's name can carry a mark for the login it bills: its label
"account" looked up in MMINI_MARKS ("personal=¹,work=²"; a value not in it gets ³; no setting, no marks), and with
no label MMINI_SHARED_MARK (³) on a server whose ssh user is MMINI_SHARED_USER.
The tab bar shows one tab per terminal of the current space or server. A terminal's space is its herdr-core label
"space", else its parent's space, else the repo folder below ~/dev, else the last folder of its cwd. In the code a
server is still a "rig" (Group.kind, names.json keys "rig:<machine>"); only what is drawn says "server".

The sidebar has three states: open (MMINI_WIDTH columns), strip (folded to status dots and the start of each
name) and hidden (its program ends, tmux closes its pane, and the tab bar and the view take the full width). The
data side (Engine: `hc ls`, `hc get`, the current group, last.json, the tab snapshot) runs in the sidebar; while a
window has no live sidebar the tab bar runs it itself, so its tabs stay fresh. The tab bar brings the sidebar back
at full height with one tmux split (split_sidebar).

The panes talk through files. Per window ($MMINI_WINDOW, set by the launcher app; without it the shared folder):
target, gen, view.pid, view.loop, tabs.json, poke, poke.full (the engine asks every label again), ask (a right click
in the view: the tab bar opens the shown terminal's menu), panes (tmux pane ids: side=, tabs=, view=), sidebar.pid,
title (the window title of the shown terminal, for view.sh), terminfo (xterm-mmini, compiled by start.sh).
Shared by all windows ($MMINI_STATE): group, last.json, names.json (display names: {"space:dev": "Main",
"rig:guest": "Guest", "term:mini/t5": "web"}), sidebar ("open", "strip" or "hidden": how the next sidebar
starts; while it does not exist, the old file "collapsed" is read instead, 1 = strip), servers ("shown" or
"hidden", default hidden), agents and devservers (the same words, default shown), width (the open sidebar's width
once its divider was dragged), split (where the separator above the agents was moved to; no file: the automatic
layout), seen.json (address -> hc's turn at which that terminal was last shown while done: "needs you" drops it). So
a second mmini window never switches or signals the first one's view.

Rename, create, delete. A rename is a display name kept in names.json: the space's label and folder, the machine's
hc name and every address stay as they are (herdr-core 0.1.21 has no way to rename a terminal, so terminals get a
display name too). "+ new space" and "+ add server" are the last rows of their sections; adding a server runs
`hc machine add` in a new terminal on this Mac, where its questions can be answered. Deleting a space ends and
removes its terminals (end_steps), ending an agent does the same for one, forgetting a server is `hc machine rm`;
each only after its name was typed.

Keys. Sidebar: up/down (j/k), enter, a the menu of the row (also a right click: Open, New terminal here, Rename,
Move to space, Delete space / Forget server / End terminal, as the row allows, and Show / Hide servers, agents, dev
servers), n new shell, e rename, d delete, s new space, m move an agent, v show or hide the servers, g the agents, w
the dev servers, c one step smaller (open, strip, hidden; also a click on "‹" on its last line), o open the strip
again (also a click on "›" on the line above), q hide (the same as hidden: the program ends), z zoom, [ ] (also
- =) the separator up or down, r refresh (also the keychain and the dev servers), ? the list of keys, then the
account marks (also a click on the "?" at the end of the last line; any key or click closes it). Tab bar:
left/right (h/l), enter, z zoom, ? its keys, a right click on a tab (or in the view: the shown terminal) its menu
(New terminal, Rename, Move to space, Close; Close asks for "y"), clicks only: keys typed then go on to the view;
a paste (a dropped file) in the sidebar or the tab bar goes on to the view too; without a sidebar, c or o (also a click on "›" at its left edge) brings the sidebar
back, open. z gives the whole window to the shown terminal (tmux's zoom); a click on the line it shows on top
("‹ back") brings the panes back.

The separator (the line between the upper part and the agents) can be moved: a press on it, the pointer moved with
the button held (the sidebar asks the terminal for such moves, mode 1002, and the line follows), the release puts
it; [ and ] (also - and =) move it one line; a double press gives the automatic layout back. It is kept as a share
of the pane's height in the shared file "split" ("12/40": line 12 of a 40-line pane), so a resized window keeps the
proportion and a notice or a prompt at the bottom does not move it, unless it is so low that the agents would lose
their heading or last row: then it moves up only that far (also in the strip, whose "› open" takes a line). A drag
quiet for DRAG_IDLE that gets a move is dropped (a lost release: ncurses reads the next press as a move).

A dragged divider (tmux lets a pane border be dragged with the mouse) is kept: the sidebar (refit) tells a drag
from a resized window by the window's width (unchanged for a drag), as tmux has it (curses learns sizes late), keeps
the new width and, when open, writes it to "width" for the next window. A resized window (tmux spreads it over the panes)
brings the sidebar back to its width and the tab bar to TAB_ROWS rows. start.sh clears the login shell's folder (an
empty OSC 7), so Ghostty shows no folder icon next to the window title. tmux shows the title of the pane with the
keyboard (set-titles): the sidebar, the tab bar and view.sh each set it to the shown terminal and its server ("web ·
me@mini"; nothing shown: "mmini"), each time it changes: the engine writes it to the window's file "title"
(address, then title) and to the snapshot; view.sh sets it before each attach and again after one.

Switching is quick: a click acts on the press of the button (no mouse interval, so ncurses holds nothing back; the
release is dropped, unless it ends a drag of the separator), the other pane sees a pick within LOOP_WAIT_MS
(pick_stamp), the attach to end is found by asking the kernel instead of ps (proc_info), and view.sh no longer wipes
the pane between two attaches.

Runs on Python 3.9, standard library only. Settings (environment): MMINI_HC, MMINI_STATE, MMINI_WINDOW,
MMINI_FIRST (the home machine; unset: the only machine `hc machine ls` knows, else this Mac), MMINI_WIDTH (the open
width until a divider is dragged), MMINI_NARROW (width of the folded strip, default 6), MMINI_MARKS, MMINI_SHARED_USER, MMINI_SHARED_MARK (account marks), MMINI_DEV_PROGRAM (default node),
MMINI_KEYCHAIN=0, MMINI_BROWSER=0, MMINI_AUTOSIZE=0, MMINI_AUTOOPEN=0, MMINI_TMUX=0 (no tmux calls at all, for the
tests).
"""

from __future__ import annotations

import base64
import concurrent.futures
import curses
import errno
import json
import locale
import os
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Collection, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


def env_int(name: str, default: int, low: int, high: int) -> int:
    """An integer setting; junk or out-of-range values fall back instead of stopping the program."""
    try:
        return max(low, min(high, int(os.environ.get(name, ""))))
    except ValueError:
        return default


HC = os.environ.get("MMINI_HC") or str(Path.home() / ".local/bin/hc")
STATE = Path(os.environ.get("MMINI_STATE") or str(Path.home() / ".local/state/mmini"))  # shared: group, last.json
WINDOW = Path(os.environ.get("MMINI_WINDOW") or str(STATE))  # this window's files (see the docstring)
FIRST = (os.environ.get("MMINI_FIRST") or "").strip()  # the home machine; "" = chosen by first_machine
WIDTH = env_int("MMINI_WIDTH", 30, 10, 200)
NARROW = env_int("MMINI_NARROW", 6, 3, 200)  # the folded sidebar
LOCAL = "this Mac"
REFRESH_SECONDS = 2.0  # hc ls
INFO_SECONDS = 30.0  # hc get of every terminal (labels, parents)
NOTICE_SECONDS = 6.0
NOTICE_LINES = 3  # a long notice (the keychain warning) wraps onto at most this many lines
SNAPSHOT_MAX_AGE = 20.0
SNAPSHOT_BEAT = 5.0
PLAIN_PROGRAMS = ("zsh", "bash", "sh", "fish", "login")
STATUS_ORDER = ("blocked", "error", "working", "done", "idle")
# status -> colour pair (1 red, 2 green, 3 yellow, 4 blue); anything else is dim.
STATUS_COLOR = {"blocked": 1, "error": 1, "working": 3, "done": 2, "idle": 4}
ASCII_GLYPHS = {"›": ">", "‹": "<", "●": "*", "○": "o", "│": "|", "·": ".", "←": "<", "→": ">", "↑": "^", "↓": "v",
                "…": "~", "─": "-", "⌘": "cmd+", "⇧": "shift+", "↵": "enter", "┌": "+", "┐": "+", "└": "+", "┘": "+",
                "¹": "1", "²": "2", "³": "3"}
HOME_ROOTS = ("Users", "home")
SIDEBAR_STATES = ("open", "strip", "hidden")  # c steps through them in this order
# Seconds without a live sidebar before the tab bar runs the engine itself: at a normal start both panes start
# together and the sidebar writes its pid a moment later, so two engines never run side by side.
ENGINE_GRACE = 3.0
# A double click is two presses: after a press opened, closed or used the menu or the list of keys, or folded or
# opened the sidebar, presses are dropped for this long, so the second one never acts on what is under it now.
MOUSE_QUIET = 0.4
# A drag of the separator with no mouse event for this long: the next move is taken for the press of a new click whose
# drag lost its release (mouse_route), and the drag is dropped. A hand that held the line still this long and moves on
# sees it go back and drags again.
DRAG_IDLE = 2.0
ENGINE_BEAT = 0.25  # seconds between two syncs of the tab bar's engine (the sidebar syncs at every key or 0.25 s)
# The sidebar and the tab bar wait for a key at most LOOP_WAIT_MS, then look at two files (gen: a pick; tabs.json:
# the tabs) and draw again only when one changed or ROUND_SECONDS went by. So a pick in the other pane shows here
# within about 50 ms instead of up to 250 ms, and a quiet pane still does a full round only 4 times a second.
LOOP_WAIT_MS = 50
ROUND_SECONDS = 0.25
OPEN_TIMEOUT = 10.0  # seconds the tab bar waits for the sidebar it brought back ("›") to run
BASE = Path(os.path.abspath(__file__)).parent  # the folder of this file: the panes a rebuild makes start it there
ENV_NAME = re.compile(r"MMINI_[A-Z0-9_]+")


# ---------------------------------------------------------------------------------------------------------------
# Data: terminals, spaces, groups (pure)
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Term:
    """One live terminal as `hc ls --json` reports it."""

    address: str
    machine: str
    name: str
    agent: str
    status: str
    cwd: str
    title: str = ""  # the display name from names.json ("" = none)
    turn: int = 0  # hc's count of the times its status left "working": a "done" is new when this moved on
    mark: str = ""  # the account mark (account_mark): "¹", "²", "³" or ""

    @property
    def label(self) -> str:
        return self.name or self.address.rsplit("/", 1)[-1]

    @property
    def shown(self) -> str:
        """The name drawn everywhere: the display name, else the hc name, else the id."""
        return self.title or self.label

    @property
    def is_agent(self) -> bool:
        return self.agent not in PLAIN_PROGRAMS or bool(self.status)


@dataclass(frozen=True)
class Info:
    """What only `hc get` knows about a terminal: its "space" label, its parent's address ("" = none), whether it
    ends with that parent (hc's die_with_parent; unknown counts as yes, so a warning is never left out), and its
    "account" label."""

    space: str = ""
    parent: str = ""
    dies: bool = True
    account: str = ""  # its label "account" (which Claude subscription it runs on; account_mark)


@dataclass
class Group:
    """What the tab bar shows: a space of the home machine or one whole machine (a server; kind "rig")."""

    key: str
    name: str  # the space's own name (its label and folder rules use it) or the machine's hc name
    kind: str  # "space" or "rig" (drawn as "server")
    machine: str
    cwd: str  # where a new shell of this group starts ("" = that machine's default)
    terms: List[Term] = field(default_factory=list)
    title: str = ""  # the display name from names.json ("" = none)
    alias: str = ""  # a server's user@host (server_label), drawn when it has no display name
    home: bool = False  # the server row of the home machine: its agents are listed under their spaces only

    @property
    def shown(self) -> str:
        """The name drawn everywhere: the display name, else a server's user@host, else the name."""
        return self.title or self.alias or self.name

    @property
    def own(self) -> str:
        """The name drawn without a display name: typing it at "rename" removes the display name."""
        return self.alias or self.name


@dataclass(frozen=True)
class Machine:
    """One machine of `hc machine ls --json`: its hc name, its ssh target, and whether that target is a command
    (`via`) rather than an ssh target."""

    name: str
    target: str = ""
    via: bool = False


def server_label(machine: Machine) -> str:
    """How a server is drawn: user@host of its ssh target ("me@mini"; a port is left out). A target without a
    user is drawn as hc gives it ("vps", a Host of ~/.ssh/config). A machine reached through a command (`via`), or
    with an empty or unprintable target, is drawn by its hc name."""
    target = machine.target.strip()
    if machine.via or not target or not target.isprintable() or any(c.isspace() for c in target):
        return machine.name
    if "@" not in target:
        return target
    user, _, host = target.rpartition("@")
    host = host.split("]", 1)[0] + "]" if host.startswith("[") else host.split(":", 1)[0]  # [v6]:port, host:port
    return f"{user}@{host}" if user and host else target


def machine_of(address: str) -> str:
    """`rig/t1` is on machine `rig`; a bare `t1` is on this Mac."""
    return address.rsplit("/", 1)[0] if "/" in address else LOCAL


def parse(raw: str) -> List[Term]:
    """Terminals from `hc ls --json` output (name, status and cwd may be null or missing). Anything that is not
    the expected shape raises ValueError, so the caller shows one red line instead of crashing."""
    data = json.loads(raw)
    listed = data.get("terminals") if isinstance(data, dict) else None
    if not isinstance(listed, list):
        raise ValueError("unexpected hc ls output")
    terms: List[Term] = []
    for t in listed:
        if not isinstance(t, dict):
            continue
        address = str(t.get("address") or "")
        if address:
            turn = t.get("turn")
            terms.append(Term(address, machine_of(address), str(t.get("name") or ""), str(t.get("agent") or ""),
                              str(t.get("status") or ""), str(t.get("cwd") or ""),
                              turn=turn if isinstance(turn, int) and not isinstance(turn, bool) and turn >= 0 else 0))
    return terms


def parse_info(raw: str, address: str) -> Info:
    """Labels "space" and "account" and the parent from `hc get <address> --json`. The parent is an id on the same
    machine ("t19"), so it gets the address's machine prefix. Junk raises ValueError; junk fields count as absent."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("unexpected hc get output")
    labels = data.get("labels")
    space = labels.get("space") if isinstance(labels, dict) else None
    account = labels.get("account") if isinstance(labels, dict) else None
    parent = data.get("parent")
    parent = parent.strip() if isinstance(parent, str) else ""
    if parent and "/" not in parent and "/" in address:
        parent = address.rsplit("/", 1)[0] + "/" + parent
    return Info(space.strip() if isinstance(space, str) else "", parent, data.get("die_with_parent") is not False,
                account.strip() if isinstance(account, str) else "")


def parse_machines(raw: str) -> List[Machine]:
    """The machines of `hc machine ls --json` ({"machines": [{"name", "target", "via", ...}]}, herdr-core 0.1.21's
    MachineView). Junk raises ValueError; an entry without a name is left out, junk fields count as absent."""
    data = json.loads(raw)
    listed = data.get("machines") if isinstance(data, dict) else None
    if not isinstance(listed, list):
        raise ValueError("unexpected hc machine ls output")
    return [Machine(m["name"], m["target"] if isinstance(m.get("target"), str) else "", m.get("via") is True)
            for m in listed if isinstance(m, dict) and isinstance(m.get("name"), str) and m["name"]]


def as_machine(m: object) -> Machine:
    """A Machine, also from a bare name (target unknown: drawn by its name)."""
    return m if isinstance(m, Machine) else Machine(str(m))


def cwd_space(cwd: str) -> str:
    """Space from a folder alone: below a dev root (/Users/<u>/dev/<repo>/...) it is <repo>, the dev root itself
    is "dev", a home folder (or nothing) is "home", anything else is its last folder."""
    parts = [p for p in cwd.split("/") if p]
    if len(parts) >= 2 and parts[0] in HOME_ROOTS:
        if len(parts) == 2:
            return "home"
        if parts[2] == "dev":
            return parts[3] if len(parts) > 3 else "dev"
    return parts[-1] if parts else "home"


def resolve_space(address: str, cwds: Mapping[str, str], infos: Mapping[str, Info]) -> str:
    """The space of a home-machine terminal. `cwds` holds every live terminal of that machine. First its own
    label; else up the parent chain to the first labelled terminal; else the folder of the top of the chain.
    The chain stops at a parent that is missing or has ended; a loop falls back to the terminal's own folder."""
    seen = set()
    current = address
    while True:
        info = infos.get(current)
        if info is not None and info.space:
            return info.space
        seen.add(current)
        parent = info.parent if info is not None else ""
        if not parent or parent not in cwds:
            break
        if parent in seen:
            current = address
            break
        current = parent
    return cwd_space(cwds.get(current, ""))


def space_cwd(name: str, terms: Sequence[Term]) -> str:
    """Where a new shell of a space starts: the folder the space is named after when a terminal is in it (the repo
    folder, not a subfolder), else the folder of its first terminal."""
    for t in terms:
        if t.cwd and cwd_space(t.cwd) == name:
            parts = [p for p in t.cwd.split("/") if p]
            if len(parts) > 3 and parts[0] in HOME_ROOTS and parts[2] == "dev":
                parts = parts[:4]
            return "/" + "/".join(parts)
    return next((t.cwd for t in terms if t.cwd), "")


def natural(text: str) -> List[Tuple[int, int, str]]:
    """Sort key that puts t9 before t13. Only 0-9 count as digits: "²" or "①" pass str.isdigit() but int() refuses
    them, and a name from another machine may hold anything."""
    return [(0, int(p), "") if p[0] in "0123456789" else (1, 0, p.lower())
            for p in re.findall(r"[0-9]+|[^0-9]+", text)]


def first_machine(machines: Sequence[object] = (), setting: Optional[str] = None) -> str:
    """The home machine's hc name: `setting` (MMINI_FIRST, read at each call) when set; else the only machine
    `hc machine ls` knows (`machines`); else this Mac (LOCAL)."""
    setting = (FIRST if setting is None else setting).strip()
    if setting:
        return setting
    names = list(dict.fromkeys(m.name for m in map(as_machine, machines) if m.name and m.name != LOCAL))
    return names[0] if len(names) == 1 else LOCAL


def home_machine(terms: Sequence[Term], first: str = FIRST) -> str:
    """The default machine: `first` (first_machine) if any terminal is on it, otherwise this Mac."""
    return first if first and any(t.machine == first for t in terms) else LOCAL


def build_groups(terms: Sequence[Term], first: str = FIRST, infos: Optional[Mapping[str, Info]] = None,
                 machines: Sequence[object] = (), names: Optional[Mapping[str, str]] = None,
                 marks: Optional[Mapping[str, str]] = None) -> Tuple[List[Group], List[Group]]:
    """(spaces, servers). Spaces: the home machine's terminals by space. Servers: every machine as one group with
    all its terminals: each machine `hc machine ls` knows (`machines`, Machine or bare names), also one that runs no
    terminal, so a server just added shows up and an empty one can be forgotten; the home machine (its agents stay
    listed under their spaces: `home`); this Mac only while it runs terminals. A server is drawn as user@host of its
    ssh target (server_label). `names`: the display names (names.json); they only change what is drawn and the
    order. `marks`: address -> account mark (account_marks). Servers come home machine first, then by name, this Mac
    last."""
    infos, names, marks = infos or {}, names or {}, marks or {}
    home = home_machine(terms, first)
    known = {m.name: m for m in map(as_machine, machines)}
    cwds = {t.address: t.cwd for t in terms if t.machine == home}
    spaces: Dict[str, Group] = {}
    rigs: Dict[str, Group] = {}

    def server(name: str) -> Group:
        if name not in rigs:
            alias = server_label(known[name]) if name in known else ""
            rigs[name] = Group("rig:" + name, name, "rig", name, "", alias="" if alias == name else alias,
                               home=name == home)
        return rigs[name]

    for t in terms:
        shown = replace(t, title=names.get("term:" + t.address, ""), mark=marks.get(t.address, "")) \
            if names or marks else t
        if t.machine == home:
            name = resolve_space(t.address, cwds, infos)
            spaces.setdefault(name, Group("space:" + name, name, "space", home, "")).terms.append(shown)
        server(t.machine).terms.append(shown)
    for m in known:
        if m != LOCAL:
            server(m)
    for g in list(spaces.values()) + list(rigs.values()):
        g.title = names.get(g.key, "")
        g.terms.sort(key=lambda t: (natural(t.shown), t.address))
        if g.kind == "space":
            g.cwd = space_cwd(g.name, g.terms)
    return (sorted(spaces.values(), key=lambda g: (g.name != "home", g.shown.lower(), g.shown, g.key)),
            sorted(rigs.values(), key=lambda g: (not g.home, g.name == LOCAL, g.shown.lower(), g.shown, g.key)))


# ---------------------------------------------------------------------------------------------------------------
# Window title (pure): "<shown terminal> · <server>", sent by every pane of the window (OSC 2)
# ---------------------------------------------------------------------------------------------------------------
NO_TITLE = "mmini"  # nothing shown
TITLE_SEP = " · "
TITLE_MAX = 80  # characters
# Ghostty 1.3 (stream_handler windowTitle) ignores a title of 256 bytes or more; an ignored title leaves its "no
# title seen" flag as it was, and an empty OSC 7 after it would then clear the title.
TITLE_BYTES = 240


def title_part(text: str) -> str:
    """One name made safe for the title: every unprintable character (controls, escape, bell, line breaks, format
    marks, odd spaces) becomes a space, runs of spaces become one, none at either end."""
    return " ".join("".join(c if c.isprintable() else " " for c in text).split())


def cut_title(text: str, n: int) -> str:
    """`text` in at most `n` characters, "…" marking a cut."""
    return text if len(text) <= n else (text[:n - 1] + "…" if n > 1 else text[:n])


def window_title(terminal: str, server: str, limit: int = TITLE_MAX) -> str:
    """The window title: "web · me@mini". Both names are cleaned (title_part); one missing: the other
    alone; both: NO_TITLE. Too long: the server keeps up to half the room (more when the terminal's name is short),
    the terminal the rest; it also stays under TITLE_BYTES bytes of UTF-8."""
    name, server = title_part(terminal), title_part(server)
    while True:
        if name and server:
            room = max(2, limit - len(TITLE_SEP))
            keep = min(len(server), max(room // 2, room - len(name)))
            text = cut_title(name, max(1, room - keep)) + TITLE_SEP + cut_title(server, keep)
        else:
            text = cut_title(name or server or NO_TITLE, limit)
        if len(text.encode("utf-8")) <= TITLE_BYTES or limit <= 8:
            return text
        limit -= 4


def server_name(machine: str, machines: Sequence[object] = (), names: Optional[Mapping[str, str]] = None) -> str:
    """A machine's name as its server row draws it (Group.shown): the display name, else user@host of its ssh target
    (server_label), else its hc name; LOCAL for this Mac. Known also while the servers section is hidden."""
    names = names or {}
    known = {m.name: m for m in map(as_machine, machines)}
    return names.get("rig:" + machine) or (server_label(known[machine]) if machine in known else machine)


def shown_title(address: str, terms: Sequence[Term], machines: Sequence[object] = (),
                names: Optional[Mapping[str, str]] = None) -> str:
    """The window title for the terminal at `address` ("" = nothing shown: NO_TITLE): its name as the tab draws it
    (display name, else hc name, else its id), then its server's (server_name). Also for a terminal not listed
    (yet): its id and its machine."""
    if not address:
        return NO_TITLE
    names = names or {}
    term = next((t for t in terms if t.address == address), None)
    name = names.get("term:" + address) or (term.label if term else address.rsplit("/", 1)[-1])
    return window_title(name, server_name(machine_of(address), machines, names))


def tab_title(snap: Optional[dict], address: str) -> Optional[str]:
    """The window title for a tab of the snapshot (its label and server), None when `address` is no tab of it."""
    for t in (snap or {}).get("tabs") or []:
        if isinstance(t, dict) and t.get("address") == address:
            server = str(t.get("server") or (snap or {}).get("server") or machine_of(address))
            return window_title(str(t.get("label") or address.rsplit("/", 1)[-1]), server)
    return None


def tabs_title(snap: Optional[dict], shown: str) -> Optional[str]:
    """The tab bar's window title for the shown terminal: NO_TITLE when nothing is shown, the engine's own title
    when the snapshot was made for that terminal, else the title of its tab. None (keep the title) when not known:
    no snapshot yet, or the terminal is no tab of it."""
    if not shown:
        return NO_TITLE
    if snap is None:
        return None
    if snap.get("shown") == shown and isinstance(snap.get("shown_title"), str) and snap["shown_title"]:
        return window_title(snap["shown_title"], "")
    return tab_title(snap, shown)


def title_escape(title: str) -> bytes:
    """OSC 2 (the pane's title) with `title`, cleaned again: no control character ever reaches the terminal."""
    return b"\033]2;" + window_title(title, "").encode("utf-8") + b"\007"


def summary_status(terms: Sequence[Term]) -> str:
    """The most urgent status in a group: blocked/error, working, done, idle; "" when none has one."""
    present = {t.status for t in terms}
    return next((s for s in STATUS_ORDER if s in present), "")


@dataclass(frozen=True)
class Item:
    """One selectable sidebar row: a group (address ""), an agent of a group, one of the two "+" rows ("new_space",
    "add_rig" = "+ add server"; group and address ""), a "needs you" row ("needs": group "", the terminal's address)
    or a dev server ("dev": group "", address the port)."""

    kind: str
    group: str
    address: str


NEW_SPACE = Item("new_space", "", "")
ADD_RIG = Item("add_rig", "", "")
PLUS_TEXT = {"new_space": "new space", "add_rig": "add server"}


def agent_groups(spaces: Sequence[Group], rigs: Sequence[Group]) -> List[Group]:
    """The groups whose agents are listed: every space and server, but not the home machine's server row (its
    terminals are the spaces' terminals: each agent is listed once, under its space)."""
    return [g for g in list(spaces) + list(rigs) if not g.home]


def selectable_items(spaces: Sequence[Group], rigs: Sequence[Group], servers: bool = True,
                     needs: Sequence[Term] = (), devs: Sequence[DevServer] = (), agents: bool = True) -> List[Item]:
    """Cursor order, as drawn: "needs you", the spaces, "+ new space", the servers, "+ add server", the dev servers,
    then the agents of each group. `servers` False: the servers section is hidden (no server rows, no "+ add
    server", no agents of servers). `needs`, `devs`: those sections' rows (empty: not drawn). `agents` False: the
    agents section is hidden."""
    rigs = rigs if servers else []
    items = [Item("needs", "", t.address) for t in needs]
    items += [Item("group", g.key, "") for g in spaces] + [NEW_SPACE]
    items += [Item("group", g.key, "") for g in rigs] + [ADD_RIG] if servers else []
    items += [Item("dev", "", str(d.port)) for d in devs]
    if agents:
        items += [Item("agent", g.key, t.address) for g in agent_groups(spaces, rigs) for t in g.terms if t.is_agent]
    return items


def fallback_group(spaces: Sequence[Group], rigs: Sequence[Group], shown: str = "") -> str:
    """The group to open when the saved one cannot be used (first start, or it has gone): the group of the terminal
    shown right now (`shown`, its key); else the first space with an agent, so a first start does not open on an
    empty "home"; else the first space; else the first server; "" when there is nothing at all."""
    if shown and any(g.key == shown for g in list(spaces) + list(rigs)):
        return shown
    with_agent = next((g for g in spaces if any(t.is_agent for t in g.terms)), None)
    if with_agent:
        return with_agent.key
    return (list(spaces) + list(rigs))[0].key if spaces or rigs else ""


# ---------------------------------------------------------------------------------------------------------------
# Account marks (pure): which Claude subscription a session bills, from its label "account" in the core it runs in
# ---------------------------------------------------------------------------------------------------------------
CLAUDE_AGENT = "claude-code"  # hc's word for Claude Code; only its terminals get a mark
OTHER_MARK = "³"  # an account label that MMINI_MARKS does not name


def valid_mark(mark: str) -> bool:
    """A mark is one printable character one column wide: not a space, not a combining or wide character, not an
    ASCII letter or digit (a tab label ending with one would be taken for a mark)."""
    return (len(mark) == 1 and mark.isprintable() and not mark.isspace() and not unicodedata.combining(mark)
            and unicodedata.east_asian_width(mark) not in ("W", "F") and not (mark.isascii() and mark.isalnum()))


def parse_marks(text: str) -> Dict[str, str]:
    """MMINI_MARKS ("personal=¹,work=²") as label value -> mark, in the order given. An entry without "=", with
    an empty label or with a mark that is not valid_mark is left out; a label given twice keeps its last mark."""
    marks: Dict[str, str] = {}
    for entry in text.split(","):
        label, sep, mark = entry.partition("=")
        label, mark = label.strip(), mark.strip()
        if sep and label and valid_mark(mark):
            marks[label] = mark
    return marks


# label account=<value> -> mark (MMINI_MARKS). No setting: no account label gives a mark. Set: a value it does not
# name gets OTHER_MARK. An unlabelled Claude session on a server whose ssh user is SHARED_USER (MMINI_SHARED_USER,
# no default) gets SHARED_MARK (MMINI_SHARED_MARK, default ³): that account bills its own login.
ACCOUNT_MARKS = parse_marks(os.environ.get("MMINI_MARKS") or "")
SHARED_USER = (os.environ.get("MMINI_SHARED_USER") or "").strip()
SHARED_MARK = (os.environ.get("MMINI_SHARED_MARK") or "").strip()
SHARED_MARK = SHARED_MARK if valid_mark(SHARED_MARK) else OTHER_MARK
MARK_CHARS = frozenset(ACCOUNT_MARKS.values()) | {OTHER_MARK, SHARED_MARK}


def ssh_user(machine: Optional[Machine]) -> str:
    """The user part of a machine's ssh target ("guest@mini" -> "guest"); "" without one, or when the target is a
    command (`via`)."""
    if machine is None or machine.via or "@" not in machine.target:
        return ""
    return machine.target.strip().rpartition("@")[0]


def account_mark(agent: str, account: str, user: str = "", marks: Optional[Mapping[str, str]] = None,
                 shared_user: Optional[str] = None, shared_mark: Optional[str] = None) -> str:
    """The mark of one terminal: only Claude Code gets one. A label `account`: its mark in `marks` (MMINI_MARKS),
    OTHER_MARK for a value not in it, none while `marks` is empty. No label: `shared_mark` on a server whose ssh user
    (`user`) is `shared_user` (MMINI_SHARED_USER), else none. Unset arguments: the settings, read at each call."""
    marks = ACCOUNT_MARKS if marks is None else marks
    shared_user = SHARED_USER if shared_user is None else shared_user
    shared_mark = SHARED_MARK if shared_mark is None else shared_mark
    if agent != CLAUDE_AGENT:
        return ""
    if account:
        return marks.get(account, OTHER_MARK) if marks else ""
    return shared_mark if shared_user and user == shared_user else ""


def mark_legend(marks: Optional[Mapping[str, str]] = None, shared_user: Optional[str] = None,
                shared_mark: Optional[str] = None) -> List[Tuple[str, str]]:
    """The marks for the "?" list: (mark, what it stands for), one line per mark, in the order of MMINI_MARKS:
    its labels, then "other" (OTHER_MARK, only when there are marks), then the shared ssh user. Nothing set: []."""
    marks = ACCOUNT_MARKS if marks is None else marks
    shared_user = SHARED_USER if shared_user is None else shared_user
    shared_mark = SHARED_MARK if shared_mark is None else shared_mark
    legend: Dict[str, List[str]] = {}
    for label, mark in marks.items():
        legend.setdefault(mark, []).append(label)
    if marks:
        legend.setdefault(OTHER_MARK, []).append("other")
    if shared_user:
        legend.setdefault(shared_mark, []).append(shared_user)
    return [(mark, ", ".join(texts)) for mark, texts in legend.items()]


def account_marks(terms: Sequence[Term], infos: Mapping[str, Info], machines: Sequence[object] = ()) -> Dict[str, str]:
    """address -> mark for every terminal that gets one (account_mark), from the labels hc get gave (`infos`) and
    the machines' ssh users."""
    known = {m.name: m for m in map(as_machine, machines)}
    out: Dict[str, str] = {}
    for t in terms:
        info = infos.get(t.address)
        mark = account_mark(t.agent, info.account if info else "", ssh_user(known.get(t.machine)))
        if mark:
            out[t.address] = mark
    return out


def with_mark(name: str, mark: str, room: int) -> str:
    """`name` and its mark in `room` screen columns: the name is cut (marked "…"), never the mark, unless the room
    is too small for anything but the mark's own column."""
    if not mark:
        return clip(name, room)
    if text_width(name) + text_width(mark) <= room:
        return name + mark
    return clip(name, room - text_width(mark)) + mark if room > text_width(mark) else clip(name + mark, room)


def clip_marked(text: str, room: int) -> str:
    """clip() for a label that may end with an account mark (the tab bar's labels): the mark stays."""
    if len(text) > 1 and text[-1] in MARK_CHARS:
        return with_mark(text[:-1], text[-1], room)
    return clip(text, room)


# ---------------------------------------------------------------------------------------------------------------
# "needs you" (pure): agents waiting for the user
# ---------------------------------------------------------------------------------------------------------------
# hc's statuses (OSC 7501): "blocked" = a person is needed (a permission or a question), "error" = read why, then
# send or kill. Both stay listed while they last. "done" stays listed until the terminal was shown after it got done.
NEEDS_ALWAYS = ("blocked", "error")
SEEN_MAX = 500  # entries kept in seen.json


def needs_you(terms: Sequence[Term], seen: Mapping[str, int], shown: str = "") -> List[Term]:
    """The terminals for "needs you": blocked or error, and done that was not looked at since it got done (seen:
    address -> the turn it was last shown at; hc's turn goes up each time the status leaves "working", so a newer
    "done" has a higher turn). The terminal this window shows is left out: it is being looked at. Blocked and error
    first, then done, each by name."""
    out = [t for t in terms if t.address != shown and t.is_agent
           and (t.status in NEEDS_ALWAYS or (t.status == "done" and seen.get(t.address) != t.turn))]
    return sorted(out, key=lambda t: (t.status == "done", natural(t.shown), t.address))


def mark_seen(seen: Mapping[str, int], terms: Sequence[Term], shown: str) -> Dict[str, int]:
    """seen.json after a look: the shown terminal, when it is done, counts as looked at for its turn. Entries of a
    machine that has terminals listed but no longer this one go (ended); a machine that is not listed now (asleep,
    not connected) keeps its entries, so its done agents do not all come back once it is. At most SEEN_MAX."""
    out = dict(seen)
    term = next((t for t in terms if t.address == shown), None) if shown else None
    if term is not None and term.status == "done":
        out.pop(shown, None)  # to the end: the newest are kept
        out[shown] = term.turn
    listed = {t.address for t in terms}
    machines = {t.machine for t in terms}
    out = {a: n for a, n in out.items() if a in listed or machine_of(a) not in machines}
    return dict(list(out.items())[-SEEN_MAX:])


def clean_seen(data: Mapping[object, object]) -> Dict[str, int]:
    """The usable entries of seen.json: address -> a whole number of 0 or more."""
    return {k: v for k, v in data.items()
            if isinstance(k, str) and k and isinstance(v, int) and not isinstance(v, bool) and v >= 0}


def needs_text(name: str, mark: str, server: str, room: int) -> str:
    """A "needs you" row's name in `room` columns: the name with its account mark, then " · <server>" when it is not
    on the home machine. The name keeps at least half the room; the server is cut, or left out (the name gets the
    whole room) when under 3 of its own columns would be left."""
    own = name + mark
    if not server:
        return with_mark(name, mark, room)
    tail = " · " + server
    if text_width(own) + text_width(tail) <= room:
        return own + tail
    head = with_mark(name, mark, max(room // 2, room - text_width(tail)))
    rest = room - text_width(head)
    return head + clip(tail, rest) if rest >= len(" · ") + 3 else with_mark(name, mark, room)


# ---------------------------------------------------------------------------------------------------------------
# The keychain check (pure): is the home machine's login keychain unlocked, as its core sees it?
# ---------------------------------------------------------------------------------------------------------------
# Run by `hc exec` (in the home core: its child, so in the core's own login context, not this Mac's or an ssh
# login's). show-keychain-info only reads the keychain's settings: exit 0 when unlocked; locked, macOS refuses
# without a prompt ("User interaction is not allowed.", exit 36 = errSecInteractionNotAllowed). It never unlocks
# and never asks for a password. $HOME is the home machine's: nothing typed here reaches the line.
KEYCHAIN_SCRIPT = 'exec /usr/bin/security show-keychain-info "$HOME/Library/Keychains/login.keychain-db"'
KEYCHAIN_SECONDS = 4 * 3600.0  # at the start, then every 4 hours
KEYCHAIN_LOCKED_SECONDS = 60.0  # only while locked (the red line is up): so it goes soon after the unlock
# the check could not run (machine asleep, not connected, an hc without exec): again in 5 minutes, then twice as
# long after each failure in a row, up to the 4 hours; never a call every 5 minutes for good
KEYCHAIN_FAILED_SECONDS = 300.0
EXEC_TIMEOUT = 20  # seconds hc lets the program run
KEYCHAIN_TEXTS = (" keychain locked: sessions bill the API", " keychain locked: API billing", " keychain locked",
                  " keychain", "! key", "!")
KEYCHAIN_NOTICE = ("keychain locked: Claude sessions bill the API (\"Credit balance too low\"). Terminal unlock is "
                   "shown.")
UNLOCK_NAME = "unlock"


def exec_args(machine: str, script: str) -> List[str]:
    """`hc exec` arguments for a fixed sh script on `machine` (no --on for this Mac): JSON, so its exit code and its
    output come back apart from hc's own."""
    on = [] if machine == LOCAL else ["--on", machine]
    return ["exec", "--json", "--timeout", str(EXEC_TIMEOUT), *on, "/bin/sh", "-c", script]


def exec_result(raw: str) -> Tuple[Optional[int], str, str, bool]:
    """(exit code or None, stdout, stderr, timed out) from `hc exec --json` (herdr-core 0.1.21's ExecResult: the
    output base64). Junk raises ValueError."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("unexpected hc exec output")
    code = data.get("code")

    def text(key: str) -> str:
        value = data.get(key, "")
        if not isinstance(value, str):
            raise TypeError(key)
        return base64.b64decode(value, validate=True).decode("utf-8", "replace")

    try:
        out, err = text("stdout"), text("stderr")
    except (ValueError, TypeError) as exc:
        raise ValueError("unexpected hc exec output") from exc
    return (code if isinstance(code, int) and not isinstance(code, bool) else None), out, err, \
        data.get("timed_out") is True


def parse_keychain(raw: str) -> str:
    """"unlocked", "locked" or "failed" from the keychain check's `hc exec --json` answer. Exit 0: unlocked. No
    login keychain there ("could not be found"), a signal or a timeout: failed (nothing is drawn). Any other exit
    of security: locked."""
    try:
        code, _, err, timed_out = exec_result(raw)
    except ValueError:
        return "failed"
    if timed_out or code is None:
        return "failed"
    if code == 0:
        return "unlocked"
    return "failed" if "could not be found" in err else "locked"


def keychain_due(last: Optional[float], state: str, now: float, fails: int = 1) -> bool:
    """Is a keychain check due? At the start (`last` None), then KEYCHAIN_SECONDS after the last one; sooner while it
    is locked (KEYCHAIN_LOCKED_SECONDS), and after a failed check (`fails` in a row) KEYCHAIN_FAILED_SECONDS,
    doubled for each further failure, at most KEYCHAIN_SECONDS."""
    if last is None:
        return True
    if state == "locked":
        wait = KEYCHAIN_LOCKED_SECONDS
    elif state == "failed":
        wait = min(KEYCHAIN_FAILED_SECONDS * 2 ** min(max(0, fails - 1), 16), KEYCHAIN_SECONDS)
    else:
        wait = KEYCHAIN_SECONDS
    return now - last >= wait


def keychain_text(room: int) -> str:
    """The red line in `room` columns: the longest of KEYCHAIN_TEXTS that fits."""
    return next((t for t in KEYCHAIN_TEXTS if text_width(t) <= room), "")


# ---------------------------------------------------------------------------------------------------------------
# Dev servers (pure): node programs (MMINI_DEV_PROGRAM) listening on the home machine, opened in this Mac's browser
# ---------------------------------------------------------------------------------------------------------------
# Only the listeners of one program name are listed (MMINI_DEV_PROGRAM, default node). lsof once for the listeners
# (-a: TCP, listening, and named DEV_PROGRAM), then once for their folders (cwd), the two parts apart by a line
# "--cwd". lsof ends with 1 when it found nothing: the script always ends with 0, so only hc's own failures fail.
# Without admin rights lsof sees only the programs of the account the core runs as: another account's pages are not
# listed.
DEV_PROGRAM_RE = re.compile(r"[A-Za-z0-9._+-]{1,15}")  # a macOS program name: at most 15 characters (MAXCOMLEN)


def dev_program(setting: str) -> str:
    """The program name whose listeners are dev servers: MMINI_DEV_PROGRAM, "node" when unset or not a plain name."""
    setting = setting.strip()
    return setting if DEV_PROGRAM_RE.fullmatch(setting) and not setting.startswith("-") else "node"


def dev_script(program: str) -> str:
    """The sh script `hc exec` runs on the home machine to list the listeners of `program` and their folders."""
    return ('l=$(/usr/sbin/lsof -nP -iTCP -sTCP:LISTEN -a -c ' + shlex.quote(program) + ' -F pcn 2>/dev/null); '
            'printf "%s\\n" "$l"; '
            'echo --cwd; p=$(printf "%s\\n" "$l" | /usr/bin/sed -n "s/^p//p" | /usr/bin/paste -sd, -); '
            'if [ -n "$p" ]; then /usr/sbin/lsof -a -p "$p" -d cwd -Fpn 2>/dev/null; fi; exit 0')


DEV_PROGRAM = dev_program(os.environ.get("MMINI_DEV_PROGRAM") or "")
DEV_SCRIPT = dev_script(DEV_PROGRAM)
DEV_SECONDS = 60.0
LOOPBACK_HOSTS = ("127.", "[::1]", "localhost", "[::ffff:127.")
HOST_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,252})|\[[0-9A-Fa-f:.]{2,45}\]")


@dataclass(frozen=True)
class DevServer:
    """A port a DEV_PROGRAM program (node) listens on, reachable from other machines, and the folder it runs in
    ("" unknown)."""

    port: int
    folder: str = ""
    pid: int = 0

    @property
    def label(self) -> str:
        """":3917 feature": the port, then the last folder of where it runs (its project)."""
        name = self.folder.rstrip("/").rsplit("/", 1)[-1] if self.folder.strip("/") else ""
        return f":{self.port}" + (f" {name}" if name else "")


def lsof_records(text: str) -> List[Dict[str, str]]:
    """lsof -F output as one dict per file: a "p" line starts a process (its "c" and the pid carry on), an "f" line
    a file of it, an "n" line names that file."""
    records: List[Dict[str, str]] = []
    process: Dict[str, str] = {}
    for line in text.splitlines():
        if not line:
            continue
        tag, value = line[0], line[1:]
        if tag == "p":
            process = {"p": value}
        elif tag == "c":
            process["c"] = value
        elif tag == "f":
            records.append(dict(process, f=value))
        elif tag == "n" and records and "n" not in records[-1]:
            records[-1]["n"] = value
    return records


def listen_port(name: str) -> Optional[int]:
    """The port of an lsof name ("*:3917", "[::]:3000", "192.168.1.5:8080") when other machines can reach it: None
    for a loopback address (127.0.0.1, [::1]: only the machine itself) or anything that is no port 1-65535."""
    host, sep, port = name.rpartition(":")
    if not sep or not port.isdigit() or host.startswith(LOOPBACK_HOSTS):
        return None
    number = int(port)
    return number if 1 <= number <= 65535 else None


def parse_dev_servers(out: str, program: Optional[str] = None) -> List[DevServer]:
    """The listeners of `program` (DEV_PROGRAM when unset) in DEV_SCRIPT's output, one per port (IPv4 and IPv6 of
    one program are one row), by port. Another program (lsof -c matches the start of a name) and loopback addresses
    are left out."""
    program = DEV_PROGRAM if program is None else program
    listen, _, cwds = out.partition("--cwd")
    folders = {r.get("p", ""): r.get("n", "") for r in lsof_records(cwds) if r.get("f") == "cwd"}
    found: Dict[int, DevServer] = {}
    for r in lsof_records(listen):
        port = listen_port(r.get("n", ""))
        if port is None or r.get("c") != program or port in found:
            continue
        pid = r.get("p", "")
        found[port] = DevServer(port, folders.get(pid, ""), int(pid) if pid.isdigit() else 0)
    return [found[p] for p in sorted(found)]


def dev_due(last: Optional[float], now: float) -> bool:
    """At the start, then every DEV_SECONDS (r: at once)."""
    return last is None or now - last >= DEV_SECONDS


def home_host(machines: Sequence[object], home: str) -> str:
    """The host a browser on this Mac reaches the home machine by: the host part of its ssh target ("me@mini"
    -> "mini", a port left out), else its hc name; "localhost" when the home machine is this Mac. "" when that is
    no usable host name."""
    if home == LOCAL:
        return "localhost"
    known = {m.name: m for m in map(as_machine, machines)}
    machine = known.get(home)
    target = machine.target.strip() if machine is not None and not machine.via else ""
    host = target.rpartition("@")[2] if target else home
    host = host.split("]", 1)[0] + "]" if host.startswith("[") else host.split(":", 1)[0]
    return host if HOST_RE.fullmatch(host) else ""


def open_url_args(host: str, port: object) -> List[str]:
    """`open http://<host>:<port>/` as an argument list (never a shell line). Raises ValueError for a port that is
    not 1-65535 or a host that is not a plain name or address."""
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("not a port")
    if not HOST_RE.fullmatch(host or ""):
        raise ValueError("no usable host")
    return ["/usr/bin/open", f"http://{host}:{port}/"]


# ---------------------------------------------------------------------------------------------------------------
# The "s" and "m" prompts (pure)
# ---------------------------------------------------------------------------------------------------------------
def valid_space_name(name: str) -> bool:
    """A space name the prompts accept: 1-40 printable characters, no "/", not starting with "~" or "-"."""
    return (0 < len(name) <= 40 and "/" not in name and name[0] not in "~-" and name not in (".", "..")
            and all(32 <= ord(c) < 127 for c in name))


def classify_space_input(text: str) -> Tuple[str, str]:
    """What was typed at the "s" prompt: ("empty", ""), ("folder", path), ("name", name) or ("bad", why).
    Anything with "/" or a leading "~" is a folder and must be absolute or start with "~/": the folder is on the
    home machine, so nothing here may depend on this Mac's shell or home."""
    text = text.strip()
    if not text:
        return ("empty", "")
    if "/" in text or text.startswith("~"):
        if text == "~" or text.startswith("~/") or text.startswith("/"):
            return ("folder", text)
        return ("bad", "start a folder with / or ~/")
    if valid_space_name(text):
        return ("name", text)
    return ("bad", "not a usable space name")


def probe_arg(kind: str, value: str) -> str:
    """The folder to look for on the home machine: absolute, or relative to that machine's home folder."""
    if kind == "name":
        return "dev/" + value
    if value.startswith("~"):
        return value[1:].lstrip("/") or "."
    return value


def join_home(home_dir: str, path: str) -> str:
    """`path` as an absolute folder ("" when it is relative and the home folder is not known)."""
    if not path.startswith("/"):
        if not home_dir.startswith("/"):
            return ""
        path = home_dir + "/" + path
    return os.path.normpath(path)


def plan_new_space(kind: str, value: str, home_dir: str, exists: Optional[bool]) -> Tuple[str, str, str]:
    """(cwd, space label, problem) for the "s" prompt. `exists`: is probe_arg's folder there (None = could not ask).
    A folder: start there, the folder names the space. A name: dev/<name> under the home folder when that exists,
    otherwise the home folder with the label space=<name>."""
    path = join_home(home_dir, probe_arg(kind, value))
    if kind == "folder":
        if not path:
            return ("", "", "home unknown: use a full path")
        if exists is False:
            return ("", "", "no folder " + value)
        return (path, "", "")
    if exists and path:
        return (path, "", "")
    return (home_dir if home_dir.startswith("/") else "", value, "")


PROBE = ('printf "%s\\n" "$HOME"; case "$1" in /*) p=$1;; *) p=$HOME/$1;; esac; '
         'if [ -d "$p" ]; then echo dir; else echo none; fi')


def parse_probe(out: str) -> Tuple[str, bool]:
    """(home folder, folder exists) from the probe's two lines."""
    lines = out.splitlines()
    if len(lines) < 2 or not lines[0].startswith("/") or lines[-1] not in ("dir", "none"):
        raise ValueError("unexpected answer about the folder")
    return (lines[0].rstrip("/") or "/", lines[-1] == "dir")


def home_dir_from_cwds(cwds: Iterable[str]) -> str:
    """Best guess of a machine's home folder from its terminals' folders ("" when none is below one)."""
    counts: Dict[str, int] = {}
    for cwd in cwds:
        parts = [p for p in cwd.split("/") if p]
        if len(parts) >= 2 and parts[0] in HOME_ROOTS:
            home = "/" + "/".join(parts[:2])
            counts[home] = counts.get(home, 0) + 1
    return max(counts, key=lambda h: counts[h]) if counts else ""


# ---------------------------------------------------------------------------------------------------------------
# Display names: names.json (pure, apart from the file helpers further down)
# ---------------------------------------------------------------------------------------------------------------
NAME_MAX = 32
NAME_KEY = re.compile(r"(?:space|rig|term):.+")


def valid_display_name(text: str) -> bool:
    """1-32 printable characters (no control characters, no line breaks), without spaces at either end."""
    return 0 < len(text) <= NAME_MAX and text == text.strip() and text.isprintable()


def clean_names(data: Mapping[object, object]) -> Dict[str, str]:
    """The usable entries of names.json: keys "space:…", "rig:…" or "term:…", values valid display names."""
    return {k: v for k, v in data.items()
            if isinstance(k, str) and NAME_KEY.fullmatch(k) and isinstance(v, str) and valid_display_name(v)}


def plan_rename(text: str, own: str, taken: Iterable[str]) -> Tuple[str, str]:
    """What the rename prompt does: ("remove", "") for an empty name or the thing's own name (the display name goes),
    ("set", name), or ("bad", why). A name another group (or terminal) already shows is refused, ignoring case: two
    rows with one name could not be told apart, and a suffix nobody typed would be a surprise."""
    name = text.strip()
    if not name or name == own:
        return ("remove", "")
    if not valid_display_name(name):
        return ("bad", f"a name is 1-{NAME_MAX} printable characters")
    if name.casefold() in {t.casefold() for t in taken}:
        return ("bad", f"{name} is taken")
    return ("set", name)


def renamed(names: Mapping[str, str], key: str, value: str) -> Dict[str, str]:
    """`names` with `key` set to `value`, or removed when `value` is ""."""
    out = dict(names)
    if value:
        out[key] = value
    else:
        out.pop(key, None)
    return out


# ---------------------------------------------------------------------------------------------------------------
# The action menu (pure)
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Entry:
    """One line of the action menu: what it does, what it says, and the key that does the same without the menu."""

    action: str
    label: str
    key: str


OPEN = Entry("open", "Open", "↵")
NEW_HERE = Entry("new", "New terminal here", "n")
RENAME = Entry("rename", "Rename", "e")


SERVERS_KEY = "v"  # shows or hides the servers section
AGENTS_KEY = "g"  # shows or hides the agents section ("a" is the menu)
DEVS_KEY = "w"  # shows or hides the dev servers (web pages)


def servers_entry(shown: bool) -> Entry:
    """The servers section's switch (in every menu), named for what it does now."""
    return Entry("servers", "Hide servers" if shown else "Show servers", SERVERS_KEY)


def agents_entry(shown: bool) -> Entry:
    """The agents section's switch (in every menu), named for what it does now."""
    return Entry("agents", "Hide agents" if shown else "Show agents", AGENTS_KEY)


def devs_entry(shown: bool) -> Entry:
    """The dev servers section's switch (in every menu), named for what it does now."""
    return Entry("devs", "Hide dev servers" if shown else "Show dev servers", DEVS_KEY)


def menu_entries(item: Item, group: Optional[Group], first: str = FIRST, servers: bool = False,
                 agents: bool = True, devs: bool = True) -> List[Entry]:
    """The menu of a row, ending with the three section switches: "Show servers" / "Hide servers", "Show agents" /
    "Hide agents", "Show dev servers" / "Hide dev servers" (`servers`, `agents`, `devs`: the section is shown now). A
    space can be deleted; a server (another machine) forgotten; this Mac and the home machine (`first`, its server
    row) never. An agent can be moved only when it is in a space. A "+" row has only its own action."""
    return menu_actions(item, group, first) + [servers_entry(servers), agents_entry(agents), devs_entry(devs)]


def menu_actions(item: Item, group: Optional[Group], first: str = FIRST) -> List[Entry]:
    """The entries of a row's menu that act on that row (see menu_entries)."""
    if item.kind == "needs":
        return [OPEN]
    if item.kind == "dev":
        return [Entry("browse", "Open in browser", "↵")]
    if item.kind == "new_space":
        return [Entry("new_space", "New space", "s")]
    if item.kind == "add_rig":
        return [Entry("add_rig", "Add server", "↵")]
    if item.kind == "agent":
        entries = [OPEN, RENAME]
        if item.group.startswith("space:"):
            entries.append(Entry("move", "Move to space", "m"))
        return entries + [Entry("end", "End terminal", "d")]
    if group is not None and group.kind == "space":
        return [OPEN, NEW_HERE, RENAME, Entry("delete", "Delete space", "d")]
    entries = [OPEN, NEW_HERE, RENAME]
    if group is not None and group.machine not in (LOCAL, first) and not group.home:
        entries.append(Entry("forget", "Forget server", "d"))
    return entries


@dataclass(frozen=True)
class MenuBox:
    """Where the menu is drawn: top line, left column, width, with or without a border, and which entries are on
    screen (from `offset`, `shown` of them) when the screen is too short for all."""

    top: int
    left: int
    width: int
    bordered: bool
    offset: int
    shown: int

    @property
    def height(self) -> int:
        return self.shown + (2 if self.bordered else 0)

    def entry_y(self, index: int) -> int:
        return self.top + (1 if self.bordered else 0) + index - self.offset


def menu_width(entries: Sequence[Entry]) -> int:
    """Border, a space, the longest label, two spaces, the key as drawn (ASCII "enter" for ↵), a space, border."""
    labels = max((len(e.label) for e in entries), default=0)
    return 4 + labels + 2 + max((len(glyph(e.key)) for e in entries), default=0)


def menu_box(row_y: int, count: int, selected: int, height: int, width: int, want: int) -> Optional[MenuBox]:
    """The menu next to the row on line `row_y`: below it when it fits, else above it, else as low as the screen
    allows. Two columns in from the left, like a list that drops down from the row, and never in the last column
    (Screen keeps it empty). The border goes when the screen is too short for it; then the entries scroll so the
    selected one is on screen. None when there is no room at all."""
    usable = width - 1
    if height <= 0 or usable <= 0 or count <= 0:
        return None
    box_w = min(want, usable)
    left = max(0, min(2, usable - box_w))
    bordered = height >= count + 2 and box_w >= 6
    shown = count if bordered else min(count, height)
    h = shown + (2 if bordered else 0)
    if row_y + 1 + h <= height:
        top = row_y + 1
    elif row_y - h >= 0:
        top = row_y - h
    else:
        top = max(0, height - h)
    offset = min(max(0, selected - shown + 1), count - shown)
    return MenuBox(top, left, box_w, bordered, offset, shown)


def menu_hit(box: MenuBox, x: int, y: int) -> Tuple[str, int]:
    """A click with the menu open: ("entry", index), ("box", -1) on its border, or ("outside", -1)."""
    if not (box.left <= x < box.left + box.width and box.top <= y < box.top + box.height):
        return ("outside", -1)
    index = y - box.entry_y(box.offset) + box.offset
    if box.offset <= index < box.offset + box.shown:
        return ("entry", index)
    return ("box", -1)


def menu_lines(title: str, entries: Sequence[Entry], box: MenuBox, selected: int) -> List[Tuple[int, str, bool]]:
    """The menu as (line, text, selected) at column box.left. The top border carries the row's name."""
    inner = box.width - 2 if box.bordered else box.width
    lines: List[Tuple[int, str, bool]] = []
    if box.bordered:
        head = clip(f" {title} ", max(0, inner - 1)) if inner >= 4 else ""
        lines.append((box.top, "┌" + "─" + head + "─" * max(0, inner - 1 - text_width(head)) + "┐", False))
    for i in range(box.offset, box.offset + box.shown):
        e = entries[i]
        key = glyph(e.key)
        room = inner - 2 - len(key) - 1
        body = " " + clip(e.label, max(1, room)).ljust(max(1, room)) + " " + key + " " if room >= 1 else \
            " " + clip(e.label, max(1, inner - 1))
        body = fit_columns(body, inner).ljust(inner)
        lines.append((box.entry_y(i), ("│" + body + "│") if box.bordered else body, i == selected))
    if box.bordered:
        lines.append((box.top + box.height - 1, "└" + "─" * inner + "┘", False))
    return lines


# ---------------------------------------------------------------------------------------------------------------
# Add a server (pure)
# ---------------------------------------------------------------------------------------------------------------
# What may be typed at "add server": user@host[:port] or a bare Host of ~/.ssh/config, ASCII letters, digits and
# . _ - only (plus the one @ and the one :), never a leading dash: ssh would read "-oProxyCommand=..." as an option.
RIG_TARGET = re.compile(r"(?:[A-Za-z0-9._][A-Za-z0-9._-]*@)?[A-Za-z0-9._][A-Za-z0-9._-]*(?::[0-9]{1,5})?")
RIG_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
# Run in the new terminal as `sh -c ADD_RIG_SCRIPT add-server <hc> <target> [<name>]`: what was typed arrives as
# arguments, never as part of a shell line. "--" ends hc's options, so a target can never be read as one.
ADD_RIG_SCRIPT = ('hc=$1; target=$2; shift 2; '
           'if [ $# -gt 0 ]; then "$hc" machine add --name "$1" -- "$target"; '
           'else "$hc" machine add -- "$target"; fi; rc=$?; echo; '
           'if [ "$rc" -eq 0 ]; then echo "add server: done."; else echo "add server: hc ended with exit $rc."; fi; '
           'printf "%s" "This terminal can be closed: press enter. "; read -r _')


def valid_rig_target(text: str) -> bool:
    return 0 < len(text) <= 255 and RIG_TARGET.fullmatch(text) is not None


def valid_rig_name(text: str) -> bool:
    return RIG_NAME.fullmatch(text) is not None


def add_rig_args(hc: str, target: str, name: str, home: str) -> List[str]:
    """`hc run` arguments for a new terminal on this Mac (the local core, no --on) that adds the machine. Adding
    asks questions (install hc there? a password, a code), so it runs where the user can answer, never inside
    curses. Raises ValueError for a target or name that is not allowed: nothing is built from them then."""
    if not valid_rig_target(target):
        raise ValueError("not a usable ssh target")
    if name and not valid_rig_name(name):
        raise ValueError("name: a-z 0-9 _ -, 32 at most")
    args = ["run", "--bg", "--json", "--no-parent", "--rm", "--name", "add-server"]
    args += ["--cwd", home] if home.startswith("/") else []
    return args + ["/bin/sh", "-c", ADD_RIG_SCRIPT, "add-server", hc, target] + ([name] if name else [])


# ---------------------------------------------------------------------------------------------------------------
# Delete: end terminals, forget a server (pure)
# ---------------------------------------------------------------------------------------------------------------
END_WAIT = 15  # seconds `hc wait` may take after the kill (it returns at once for a finished terminal)


def end_steps(address: str) -> List[Tuple[str, ...]]:
    """The hc calls that end a terminal for good, in this order (proved on herdr-core 0.1.21, see the README):
    recovery off first (a kept terminal is otherwise given a shell after a signal death), then end its program,
    wait until it has finished, then remove it from the list."""
    return [("keep", address, "--off"), ("kill", address), ("wait", address, "--timeout", str(END_WAIT)),
            ("rm", address)]


def forget_args(machine: str) -> Tuple[str, ...]:
    """Forget a rig: hc stops reaching it; its terminals keep running there."""
    return ("machine", "rm", machine)


def ending(terms: Sequence[Term], everything: Sequence[Term], infos: Mapping[str, Info]) -> List[Term]:
    """What ends: `terms`, then the child terminals that end with them (their parent's end ends them too, unless
    started with --outlive-parent), children of children included. Only the home machine's parents are known."""
    out = list(terms)
    seen = {t.address for t in out}
    at = 0
    while at < len(out):
        parent = out[at].address
        at += 1
        for t in everything:
            info = infos.get(t.address)
            if t.address not in seen and info is not None and info.parent == parent and info.dies:
                out.append(t)
                seen.add(t.address)
    return out


def ends_text(terms: Sequence[Term]) -> str:
    """ "ends 3: web (claude-code), api (claude-code), t1f (zsh)": by name and program."""
    return ends_line([(t.shown, t.agent) for t in terms])


def ends_line(pairs: Sequence[Tuple[str, str]]) -> str:
    """ends_text from (shown name, program) pairs."""
    return f"ends {len(pairs)}: " + ", ".join(f"{name} ({agent or '?'})" for name, agent in pairs)


def confirm_matches(typed: str, accepted: Sequence[str]) -> bool:
    """A delete goes ahead only on exactly one of the accepted names (spaces at the ends do not count)."""
    typed = typed.strip()
    return bool(typed) and typed in accepted


def neighbour(before: Sequence[Item], index: int, after: Sequence[Item]) -> Optional[Item]:
    """The row the cursor goes to once before[index] has gone: for an agent the next agent of its group that is
    still there, else the one before it, else its group; for a group (or when that found nothing) the next group of
    the same section (spaces, servers) still there, else the one before it, else any group. None: nothing left (then
    the existing fall-back rule decides)."""
    if not 0 <= index < len(before):
        return None
    gone = before[index]
    still = set(after)
    order = list(before[index + 1:]) + list(reversed(before[:index]))
    if gone.kind == "agent":
        found = next((i for i in order if i.kind == "agent" and i.group == gone.group and i in still), None)
        if found:
            return found
        group = Item("group", gone.group, "")
        if group in still:
            return group
        if group in before:  # its group has gone too: that group's neighbour
            return neighbour(before, list(before).index(group), after)
    section = gone.group.split(":", 1)[0]
    groups = [i for i in order if i.kind == "group" and i in still]
    return next((i for i in groups if i.group.split(":", 1)[0] == section), groups[0] if groups else None)


# ---------------------------------------------------------------------------------------------------------------
# Sidebar layout (pure)
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class Row:
    """One line of the sidebar. kind: header, group, plus ("+ new space", "+ add server"), blank, rule, agents,
    agent_group, agent, more, needs (a "needs you" row), dev (a dev server)."""

    kind: str
    text: str = ""
    group: Optional[Group] = None
    term: Optional[Term] = None
    item: int = -1  # index into selectable_items() for group, plus, agent, needs and dev rows
    count: int = 0
    dev: Optional[DevServer] = None


MENU_KEY = "a"  # opens the action menu of the row under the cursor (a right click does the same)
HELP_KEY = "?"  # the list of keys (KEY_HELP), drawn over the sidebar until the next key or click
# The sidebar's keys, for "?": (key, what it does). Every line fits 29 columns (a 30-column sidebar keeps its last
# column empty). The way back from a zoom has a line of its own: while zoomed nothing of mmini can be seen.
KEY_HELP = (("↑↓ j k", "move"), ("enter", "show it"), (MENU_KEY, "menu (right click)"), ("e", "rename"),
            ("d", "delete, forget, end"), ("n", "new terminal here"), ("s", "new space"), ("m", "move to a space"),
            (SERVERS_KEY, "show/hide servers"), (AGENTS_KEY, "show/hide agents"), (DEVS_KEY, "dev servers on/off"),
            ("c", "fold, then hide"), ("o", "open the strip"), ("q", "hide"),
            ("z", "zoom the view"), ("‹ back", "click: zoom ends"), ("[ ] - =", "separator up/down"), ("r", "refresh"),
            (HELP_KEY, "this list"))
HELP_TITLE = "keys · any key closes"


def help_entries() -> List[Tuple[str, str]]:
    """The "?" list's lines: KEY_HELP, then the account marks (mark_legend; none while no mark is set)."""
    return list(KEY_HELP) + mark_legend()


def help_lines(width: int, height: int) -> List[str]:
    """The "?" list in `width` columns and `height` lines: a title, then one key per line, the key in a column of
    its own. When the lines do not all fit, the last one that does says "…" (any key closes the list, so it never
    scrolls; the sidebar is full height, so this only happens on a very short window)."""
    if width <= 0 or height <= 0:
        return []
    # the key column is 7 wide; an ASCII stand-in that is longer ("cmd+shift+enter") pushes its text along
    # then the account marks after an agent's name (mark_legend): not keys, but this is where they are explained
    lines = [" " + glyph(HELP_TITLE)] + [f" {glyph(k).ljust(7)} {text}" for k, text in help_entries()]
    lines = [clip(line, width) for line in lines]
    if len(lines) > height:
        lines = lines[:height - 1] + [" …"]
    return lines
PROMPT_TITLE_MAX = 8  # lines a prompt's question may take (a delete lists what ends); the list keeps the rest


def next_sidebar_state(current: str) -> str:
    """The key c: open -> strip -> hidden. From hidden (the tab bar's c) it is open again."""
    at = SIDEBAR_STATES.index(current) if current in SIDEBAR_STATES else 0
    return SIDEBAR_STATES[(at + 1) % len(SIDEBAR_STATES)]


def sidebar_frame(height: int, message: bool, prompt: bool, strip: bool = False, title_lines: int = 1,
                  keychain: bool = False, message_lines: int = 1) -> Tuple[int, int, int, int]:
    """(lines for the list, line of "‹" or -1, line of "›" or -1, lines for the prompt or message just above them).
    "‹" (fold; in the strip: hide) always takes the last line, except on a one-line screen, where that line is the
    cursor's. In the strip "›" (open) takes the line above it from three lines on: the cursor's line wins, then "‹",
    then "›". Then the keychain warning (`keychain`) takes the line above those (keychain_line), and a message
    (notice, hc error; up to `message_lines` lines) or the prompt gets a line above that, the prompt its question too
    (up to `title_lines` lines) when there is room; the list keeps at least two lines then, one for the cursor."""
    height = max(0, height)
    arrow = 1 if height >= 2 else 0
    opener = 1 if strip and height >= 3 else 0
    left = height - arrow - opener
    left -= 1 if keychain and left >= 2 else 0
    if prompt and left >= 2:
        extra = 1 + max(0, min(title_lines, left - 3))
    elif message and left >= 2:
        extra = max(1, min(message_lines, left - 2))
    else:
        extra = 0
    return left - extra, height - 1 if arrow else -1, height - 2 if opener else -1, extra


def keychain_line(height: int, strip: bool, keychain: bool) -> int:
    """The line of the keychain warning in sidebar_frame's layout: just above "‹" (and the strip's "›"), or -1 when
    it is not drawn (unlocked or unknown, or a sidebar too short: the cursor's line wins)."""
    height = max(0, height)
    arrow = 1 if height >= 2 else 0
    opener = 1 if strip and height >= 3 else 0
    left = height - arrow - opener
    return left - 1 if keychain and left >= 2 else -1


def wrap_words(text: str, width: int) -> List[str]:
    """`text` in lines of at most `width` screen columns, broken at spaces; a word longer than a line is cut."""
    lines: List[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}" if line else word
        if text_width(candidate) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = clip(word, width) if text_width(word) > width else word
    if line:
        lines.append(line)
    return lines


def prompt_lines(title: str, ask: str, width: int, room: int) -> List[str]:
    """The question of a prompt in `room` lines: the title wrapped, then `ask` (what to type). When it does not all
    fit the end of the title goes (marked "…"), never `ask`: without it nobody would know what to type."""
    if room <= 0:
        return []
    head, tail = wrap_words(title, width), wrap_words(ask, width) if ask else []
    if len(head) + len(tail) <= room:
        return head + tail
    tail = tail[-room:]
    keep = room - len(tail)
    if keep <= 0:
        return tail
    return head[:keep - 1] + [clip(head[keep - 1] + " …", width) if keep < len(head) else head[keep - 1]] + tail


def line_label(arrow: str, word: str, room: int) -> str:
    """One of the sidebar's arrow lines: " ‹ fold", " ‹ hide" or " › open", the word only when it fits."""
    whole = f" {arrow} {word}"
    return whole if room >= len(whole) else f" {arrow}" if room >= 2 else arrow


def fold_label(mode: str, room: int) -> str:
    """The last line names the next step of c: "fold" in the open sidebar, "hide" in the strip."""
    return line_label("‹", "fold" if mode == "open" else "hide", room)


def open_label(room: int) -> str:
    """The strip's line above the last one: back to the open sidebar."""
    return line_label("›", "open", room)


def help_column(label: str, width: int) -> int:
    """The column of the dim "?" at the end of the "‹" line (a click on it opens the list of keys), or -1 when the
    line has no room for it beside its label: the last column stays empty, one space keeps them apart."""
    x = width - 2
    return x if x > len(label) else -1


def sidebar_hit(y: int, arrow_y: int, open_y: int, rows: Mapping[int, Item], x: int = -1,
                help_x: int = -1, rule_y: int = -1, keychain_y: int = -1) -> Tuple[str, Optional[Item]]:
    """What a click at column x of line y of the sidebar hits: ("help", None) on the "?" at the end of the "‹" line
    (help_x), ("step", None) anywhere else on the "‹" line (what c does), ("open", None) anywhere on the "›" line,
    ("rule", None) anywhere on the separator's line (rule_y: a drag starts there; never a row, never a menu),
    ("keychain", None) anywhere on the keychain warning (keychain_y), ("item", the item drawn on that line) or
    ("", None)."""
    if keychain_y >= 0 and y == keychain_y:
        return ("keychain", None)
    if arrow_y >= 0 and y == arrow_y:
        return ("help", None) if help_x >= 0 and x == help_x else ("step", None)
    if open_y >= 0 and y == open_y:
        return ("open", None)
    if rule_y >= 0 and y == rule_y:
        return ("rule", None)
    item = rows.get(y)
    return ("item", item) if item else ("", None)


def pick_agent_rows(entries: Sequence[Row], cap: int, cursor: int) -> List[Row]:
    """The agent lines that fit in `cap` lines. When they do not all fit: a window that always holds the cursor's
    agent, with its group heading on top when there is room, and a last line "+N more"."""
    if cap <= 0 or not entries:
        return []
    if len(entries) <= cap:
        return list(entries)
    pos = next((i for i, e in enumerate(entries) if e.kind == "agent" and e.item == cursor), -1)
    body = cap - 1 if cap >= 2 else (1 if pos >= 0 else 0)

    def window(start: int) -> List[Row]:
        rows: List[Row] = []
        if body >= 2 and entries[start].kind == "agent":
            rows.append(next(e for e in entries if e.kind == "agent_group" and e.group is entries[start].group))
        return rows + list(entries[start:start + body - len(rows)])

    start = 0
    while pos >= 0 and all(r is not entries[pos] for r in window(start)):
        start += 1
    shown = window(start) if body else []
    hidden = sum(1 for e in entries if e.kind == "agent") - sum(1 for e in shown if e.kind == "agent")
    if hidden and (cap >= 2 or not shown):
        shown.append(Row("more", f"+{hidden} more", count=hidden))
    return shown


# The separator (the rule between the upper part and the agents) can be moved: dragged with the mouse, or [ ] (also
# - =). Each part keeps at least its heading and one row: above it "spaces" and a row, from it down the line itself,
# "agents  grouped" and a row.
RULE_TOP_MIN = 2
RULE_LOW_MIN = 3
SPLIT_MAX = 1000  # lines: a "split" file naming a taller pane is junk
SPLIT_RE = re.compile(r"([0-9]{1,4})/([0-9]{1,4})")
RULE_KEYS = {ord("["): -1, ord("-"): -1, ord("]"): 1, ord("="): 1}  # the separator one line up or down


def rule_limits(height: int) -> Optional[Tuple[int, int]]:
    """The first and the last line the separator may be on in a list of `height` lines, or None when the list is
    too short for both parts (the automatic layout then)."""
    low, high = RULE_TOP_MIN, height - RULE_LOW_MIN
    return (low, high) if low <= high else None


def clamp_rule(y: int, height: int) -> Optional[int]:
    """Line y for the separator, moved into rule_limits (a drag let go above or below the pane lands at the limit);
    None when the list has no room for a moved separator."""
    limits = rule_limits(height)
    return max(limits[0], min(limits[1], y)) if limits else None


def rule_step(current: int, step: int, height: int) -> Optional[int]:
    """The separator's line after [ (step -1) or ] (+1), from `current` (its line as drawn; `height` when none is
    drawn: the upper part took every line). A separator already past a limit in that direction stays: ] never
    moves it up. None when the list has no room for a moved separator."""
    limits = rule_limits(height)
    if limits is None:
        return None
    to = max(limits[0], min(limits[1], current + step))
    return current if (to - current) * step < 0 else to


RULE_DROPPED = {"rule": 0, "agents": 1}  # lines above the agents part's first row that the automatic layout gave up


def rule_line(plan: Sequence[Tuple[int, "Row"]], height: int) -> int:
    """The separator's line in a plan, for [ and ]: where it is drawn, else where it would be above the same agent
    rows (a crowded upper part makes the automatic layout drop the line, then "agents"), else `height` (no agents
    part: the upper part took every line). So [ always gives the agents a row and ] always takes one."""
    lower = [(y, row.kind) for y, row in plan if row.kind in ("rule", "agents", "agent_group", "agent", "more")]
    if not lower:
        return height
    y, kind = min(lower)
    return y - RULE_DROPPED.get(kind, 2)


def parse_split(text: str) -> Optional[Tuple[int, int]]:
    """The file "split": "12/40" = the separator on line 12 of a 40-line pane. None for anything else (no file,
    junk, a line outside the pane): the automatic layout."""
    match = SPLIT_RE.fullmatch(text.strip())
    if not match:
        return None
    row, of = int(match.group(1)), int(match.group(2))
    return (row, of) if 0 < of <= SPLIT_MAX and 0 <= row < of else None


def split_row(split: Optional[Tuple[int, int]], height: int) -> Optional[int]:
    """The line the separator was put on, for a pane of `height` lines now: the same share of the pane, rounded
    (exact at the height it was set at). None without a split. The caller clamps it (clamp_rule)."""
    if split is None or height <= 0:
        return None
    row, of = split
    return (2 * row * height + of) // (2 * of)


def plan_sidebar(spaces: Sequence[Group], rigs: Sequence[Group], height: int, cursor: int = 0,
                 compact: bool = False, servers: bool = True, rule: Optional[int] = None,
                 needs: Sequence[Term] = (), devs: Sequence[DevServer] = (),
                 agents: bool = True) -> List[Tuple[int, Row]]:
    """Rows with their screen line. The top part ("needs you", spaces, servers, dev servers) always wins. The
    bottom block (rule, agents) is anchored to the last line; when the screen is short the rule and the header go
    first, so the agents keep at least a heading, the cursor's agent and "+N more". No key hints: "?" lists the keys. `compact`: the folded
    strip (drawn narrower, same rows). `servers` False: the servers section is hidden (no heading, no server rows,
    no "+ add server", no agents of servers), as selectable_items. `height` is what sidebar_frame leaves for the
    list: the collapse arrow's line is not part of it.

    `rule`: the line the separator was moved to (a drag, [ or ]), clamped by clamp_rule; None (or a list too
    short for it) is the automatic layout above. The upper part then has the lines above it and scrolls to keep
    the cursor's row, the agents the lines from it down (the line, "agents", then the rows, with "+N more" and the
    cursor's agent as above).

    `needs`: the "needs you" rows, a section at the very top (none: not drawn). `devs`: the dev servers, a section
    below the servers (none: not drawn). `agents` False: the agents section is hidden: no separator, no "agents", no
    rows; the upper part has every line (a moved separator is kept for when they come back)."""
    height = max(0, height)
    manual = clamp_rule(rule, height) if rule is not None and agents else None
    top_room = height if manual is None else manual
    rigs = rigs if servers else []
    # while shown, the servers section is always there: "+ add server" lives in it. Rows in selectable_items' order.
    top: List[Row] = []
    if needs:
        top += [Row("header", "needs you")] + [Row("needs", term=t) for t in needs] + [Row("blank")]
    top += [Row("header", "spaces")] + [Row("group", group=g) for g in spaces] + [Row("plus", "new_space")]
    if servers:
        top += [Row("blank"), Row("header", "servers")] + [Row("group", group=g) for g in rigs]
        top += [Row("plus", "add_rig")]
    if devs:
        top += [Row("blank"), Row("header", "dev servers")] + [Row("dev", dev=d) for d in devs]
    index = 0
    for row in top:
        if row.kind in ("group", "plus", "needs", "dev"):
            row.item, index = index, index + 1
    n_groups = index
    scroll = 0
    if len(top) > top_room:  # keep the cursor's group visible
        at = next((i for i, r in enumerate(top) if r.item == cursor), 0) if cursor < n_groups else 0
        scroll = max(0, min(at - top_room + 1, len(top) - top_room))
    placed = [(i - scroll, r) for i, r in enumerate(top) if 0 <= i - scroll < top_room]
    if not agents:
        return placed
    room = height - len(placed)

    entries: List[Row] = []
    for g in agent_groups(spaces, rigs):
        agents = [t for t in g.terms if t.is_agent]
        if agents:
            entries.append(Row("agent_group", group=g, count=len(agents)))
            for t in agents:
                entries.append(Row("agent", group=g, term=t, item=index))
                index += 1
    fixed = [Row("rule"), Row("agents", "agents")]
    if manual is not None:
        block = fixed + pick_agent_rows(entries, height - manual - len(fixed), cursor)
        return placed + [(manual + i, r) for i, r in enumerate(block)]
    want = min(len(entries), 3)
    while fixed and len(fixed) + want > room:
        fixed.pop(0)
    block = fixed + pick_agent_rows(entries, room - len(fixed), cursor)
    y0 = height - len(block)
    return placed + [(y0 + i, r) for i, r in enumerate(block)]


# ---------------------------------------------------------------------------------------------------------------
# Tab bar layout (pure)
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class Seg:
    """A piece of the tab bar at row y, column x. kind: "tab" (index), "sep", "plus" or "cut" (‹ › at a cut edge)."""

    y: int
    x: int
    text: str
    kind: str
    index: int = -1

    @property
    def end(self) -> int:
        return self.x + len(self.text)

    @property
    def dot_x(self) -> int:
        return self.x + 1 if self.kind == "tab" else -1


@dataclass
class TabLayout:
    segs: List[Seg]
    rows: int  # rows used
    left_cut: bool = False  # tabs hidden before the first visible row
    right_cut: bool = False  # tabs hidden after the last visible row


def cell_width(c: str) -> int:
    """Screen columns a character takes: 2 for a wide one (CJK, most emoji), 0 for a combining mark, else 1."""
    if unicodedata.combining(c) or unicodedata.category(c) in ("Mn", "Me"):
        return 0
    return 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1


def text_width(text: str) -> int:
    """Screen columns `text` takes (see cell_width)."""
    return len(text) if text.isascii() else sum(cell_width(c) for c in text)


def fit_columns(text: str, room: int) -> str:
    """The longest start of `text` that takes at most `room` screen columns. curses counts characters, not
    columns: a wide name cut by its length alone runs past the pane's edge and wraps onto the next line."""
    if text.isascii():
        return text[:max(0, room)]
    used = 0
    for i, c in enumerate(text):
        used += cell_width(c)
        if used > room:
            return text[:i]
    return text


def clip(text: str, n: int) -> str:
    """`text` in at most n screen columns, the cut marked with "…"."""
    if text_width(text) <= n:
        return text
    return fit_columns(text, n - 1) + "…" if n > 1 else fit_columns(text, max(0, n))


def flow_tabs(labels: Sequence[str], width: int) -> Tuple[List[Seg], int, int]:
    """Tabs " ● name " with "│" between them, wrapped onto as many rows as it takes. Returns the pieces and where
    the next piece would go (row, column). A label too long for a whole row is shortened (an account mark at its
    end stays)."""
    segs: List[Seg] = []
    y = x = 0
    for i, label in enumerate(labels):
        cell = " ● " + clip_marked(label, max(1, width - 4)) + " "
        if x and x + 1 + len(cell) > width:
            y, x = y + 1, 0
        if x:
            segs.append(Seg(y, x, "│", "sep"))
            x += 1
        segs.append(Seg(y, x, cell, "tab", i))
        x += len(cell)
    return segs, y, x


def tab_label(tab: Mapping[str, object]) -> str:
    """A tab of the snapshot as drawn: its label, then its account mark (only a known mark character)."""
    mark = str(tab.get("mark") or "")
    return str(tab.get("label", "")) + (mark if mark in MARK_CHARS else "")


def layout_tabs(labels: Sequence[str], active: int, width: int, max_rows: int = 1) -> TabLayout:
    """Lay out " ● name │ ● name │ + " in `width` columns and up to `max_rows` rows. Tabs wrap onto further rows.
    Only when even all rows are not enough: the "+" is pinned to the right end of the first row and the rows
    scroll so the active tab is visible, with "‹" / "›" where tabs are cut off."""
    width, max_rows = max(0, width), max(1, max_rows)
    segs, y, x = flow_tabs(labels, width)
    if x and x + 4 > width:
        y, x = y + 1, 0
    if x:
        segs.append(Seg(y, x, "│", "sep"))
        x += 1
    segs.append(Seg(y, x, " + ", "plus"))
    if y < max_rows:
        return TabLayout(segs, y + 1)

    avail = max(1, width - 4)
    segs, y, _ = flow_tabs(labels, avail)
    total = y + 1
    active_row = next((s.y for s in segs if s.kind == "tab" and s.index == active), 0)
    first = min(max(0, active_row - max_rows + 1), max(0, total - max_rows))
    shown = [Seg(s.y - first, s.x, s.text, s.kind, s.index) for s in segs if first <= s.y < first + max_rows]
    shown += [Seg(0, width - 4, "│", "sep"), Seg(0, width - 3, " + ", "plus")]
    left, right = first > 0, first + max_rows < total
    if left:
        shown.append(Seg(0, 0, "‹", "cut"))
    if right:
        shown.append(Seg(min(max_rows, total) - 1, avail - 1, "›", "cut"))
    return TabLayout(shown, min(max_rows, total), left, right)


def with_opener(layout: TabLayout) -> TabLayout:
    """The tab bar of a window without a sidebar: "›" in the first cell of the first row brings the sidebar back,
    and every piece moves one column right (the caller lays the tabs out one column narrower)."""
    segs = [Seg(0, 0, "›", "open")] + [Seg(s.y, s.x + 1, s.text, s.kind, s.index) for s in layout.segs]
    return TabLayout(segs, max(1, layout.rows), layout.left_cut, layout.right_cut)


def hit_test(layout: TabLayout, x: int, y: int = 0) -> Optional[Tuple[str, int]]:
    """What a click at column x of row y hits: ("tab", index), ("plus", -1), ("open", -1) or None."""
    for s in layout.segs:
        if s.kind in ("tab", "plus", "open") and s.y == y and s.x <= x < s.end:
            return (s.kind, s.index)
    return None


TAB_HINTS = ("←→ switch  enter focus  right click menu  z zoom", "←→ switch  right click menu  z zoom",
             "←→ switch  z zoom", "z zoom")
TAB_HINTS_ALONE = ("c sidebar  ←→ switch  enter focus  right click menu  z zoom",
                   "c sidebar  ←→ switch  right click menu  z zoom", "c sidebar  ←→ switch  z zoom", "c sidebar  z zoom",
                   "z zoom")  # without a sidebar


def tab_hint(room: int, alone: bool = False) -> str:
    """The longest tab bar hint that fits in `room` columns as drawn (ASCII stand-ins may be longer). The way back
    from a zoom needs no hint: the line it is clicked on says it. `alone`: no sidebar, so the hint names the key
    that brings it back first."""
    return next((h for h in (TAB_HINTS_ALONE if alone else TAB_HINTS) if len(glyph(h)) <= room), "")


def tab_keys(alone: bool = False) -> str:
    """The tab bar's "?": all of its keys in one notice line (its hint line drops some when the pane is narrow)."""
    keys = "←→ h l switch · enter ↓ focus · right click: menu · z zoom (a click on the top line ends it)"
    return "keys: " + ("c o sidebar · " if alone else "") + keys


def tab_bar_rows(height: int) -> Tuple[int, int]:
    """(rows the tabs may use, row of the hints or -1) for a pane of `height` rows (TAB_ROWS in an mmini window).
    The hints take the last row when there are two."""
    if height < 2:
        return (max(0, height), -1)
    return (height - 1, height - 1)


def short_folder(cwd: str) -> str:
    """A folder with the home part written as "~"."""
    parts = [p for p in cwd.split("/") if p]
    if len(parts) >= 2 and parts[0] in HOME_ROOTS:
        return "/".join(["~"] + parts[2:])
    return cwd


def tab_info(tab: Mapping[str, object], room: int = 200) -> str:
    """One line about the shown terminal: address, folder, program, state. In a narrow pane the folder loses its
    start, so the program and the state stay readable."""
    address, folder = str(tab.get("address") or ""), short_folder(str(tab.get("cwd") or ""))
    rest = [str(tab.get(k) or "") for k in ("agent", "status")]
    left = room - len(" · ".join(p for p in [address] + rest if p)) - 3
    if len(folder) > left:
        folder = "…" + folder[len(folder) - left + 1:] if left >= 8 else ""
    return " · ".join(p for p in [address, folder] + rest if p)


# ---------------------------------------------------------------------------------------------------------------
# The tab menu (pure): a right click on a tab
# ---------------------------------------------------------------------------------------------------------------
CLOSE_YES = "y"  # the one key that closes a tab after its question; any other key or a click cancels
TAB_MENU_HINT = "a click picks · a key closes"
CLOSE_ROWS = 10  # the most rows the tab bar takes while Close's question shows what ends
CLOSE_AGAIN = 1.0  # seconds a y is not taken after Close asked again (what ends had changed)
TAB_ASK = {"rename": "enter saves · empty: own name · esc cancels", "move": "enter moves · esc cancels",
           "close": f"{CLOSE_YES} closes · any other key cancels"}


def tab_menu_entries(kind: str) -> List[Entry]:
    """The menu of a tab (and of the shown terminal, a right click in the view): New terminal (in the tab bar's space
    or server), Rename, Move to space (only in a space), Close. Clicks pick; the keys are the sidebar's for the same
    actions, kept only to match its entries (the tab menu takes no keys)."""
    entries = [Entry("new", "New terminal", "n"), Entry("rename", "Rename", "e")]
    if kind == "space":
        entries.append(Entry("move", "Move to space", "m"))
    return entries + [Entry("close", "Close", "d")]


def tab_menu_segs(title: str, entries: Sequence[Entry], width: int) -> List[Seg]:
    """The tab menu in one row of `width` columns, from column 0: "api: New terminal · Rename · Close". When it does
    not fit: without the title, then each entry by its first word in lower case ("new", "rename", "move",
    "close"); entries that still do not fit are left out. Pieces: "title", "entry" (its index), "sep"."""
    long = [e.label for e in entries]
    short = [e.label.split()[0].lower() for e in entries]
    segs: List[Seg] = []
    for head, labels in ((clip(title, 16) + ":", long), ("", long), ("", short)):
        segs, x = [], 0
        if head != ":" and head:
            segs.append(Seg(0, 0, head, "title"))
            x = len(head) + 1
        for i, label in enumerate(labels):
            if i:
                segs.append(Seg(0, x + 1, "·", "sep"))
                x += 3
            segs.append(Seg(0, x, label, "entry", i))
            x += len(label)
        if x <= width:
            return segs
    kept = [s for s in segs if s.end <= width]
    return kept[:-1] if kept and kept[-1].kind == "sep" else kept


def menu_entry_at(segs: Sequence[Seg], x: int) -> Optional[int]:
    """The index of the tab menu entry at column x, None between or after them."""
    return next((s.index for s in segs if s.kind == "entry" and s.x <= x < s.end), None)


def tab_of(snap: Optional[Mapping[str, object]], address: str) -> Optional[Mapping[str, object]]:
    """The tab of `address` in the snapshot, None when it is not there (any more)."""
    tabs = snap.get("tabs") if snap else None
    return next((t for t in tabs if t.get("address") == address), None) if isinstance(tabs, list) else None


def tab_ends(tab: Mapping[str, object]) -> List[Tuple[str, str, str]]:
    """The child terminals that end with a tab, as the snapshot has them: (address, shown name, program). Entries
    that are not three strings are left out."""
    ends = tab.get("ends")
    out: List[Tuple[str, str, str]] = []
    for e in ends if isinstance(ends, list) else []:
        if isinstance(e, list) and len(e) == 3 and all(isinstance(v, str) for v in e) and e[0]:
            out.append((e[0], e[1], e[2]))
    return out


def snapshot_names(snap: Optional[Mapping[str, object]]) -> Dict[str, str]:
    """address -> shown name of every listed terminal (the snapshot's "names"), for the rename's "taken" check."""
    names = snap.get("names") if snap else None
    return {a: v for a, v in names.items() if isinstance(a, str) and isinstance(v, str)} \
        if isinstance(names, dict) else {}


def close_question(tab: Mapping[str, object]) -> Prompt:
    """Close's question for a tab of the snapshot: what ends (the tab's terminal, then the children that end with
    it), and those addresses as the prompt's data."""
    address = str(tab.get("address") or "")
    label = str(tab.get("label") or address)
    ends = tab_ends(tab)
    question = f"close {tab_label(tab) or address}? " + ends_line([(label, str(tab.get("agent") or ""))] +
                                                                  [(name, agent) for _, name, agent in ends])
    return Prompt("close", question, address=address, data=(address,) + tuple(a for a, _, _ in ends))


def tab_after_close(order: Sequence[str], gone: Collection[str], shown: str) -> str:
    """The tab to show once the shown one closed: the next one after it that stays, else the nearest before it,
    else "" (nothing). `shown` still open: it stays."""
    if shown not in gone:
        return shown
    at = order.index(shown) if shown in order else len(order)
    after = [a for a in order[at + 1:] if a not in gone]
    before = [a for a in order[:at] if a not in gone]
    return after[0] if after else (before[-1] if before else "")


# ---------------------------------------------------------------------------------------------------------------
# State folders
# ---------------------------------------------------------------------------------------------------------------
def write_atomic(path: Path, text: str, encoding: Optional[str] = None) -> None:
    """Write via a temp file and os.replace, so readers never see half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


def read_text(path: Path) -> str:
    try:
        return path.read_text().strip()
    except (OSError, ValueError):
        return ""


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def current_target(win: Path = WINDOW) -> str:
    return read_text(win / "target")


def pick_stamp(win: Path = WINDOW) -> Tuple[int, int, int]:
    """What a pane's loop watches between two rounds: the times gen (each pick), tabs.json (the tabs) and ask (a
    right click in the view, written by mmini.tmux.conf) last changed. Three stats, no read: cheap enough for every
    LOOP_WAIT_MS."""
    return mtime(win / "gen"), mtime(win / "tabs.json"), mtime(win / "ask")


def round_due(stamp: Tuple[int, ...], seen: Tuple[int, ...], now: float, last_round: float,
              beat: float = ROUND_SECONDS) -> bool:
    """After a getch without a key: draw again now? Yes when a pick or the tabs changed since the last round, or
    `beat` seconds went by (the data, a notice running out, a resize loop)."""
    return stamp != seen or now - last_round >= beat


def read_last(state: Path = STATE) -> Dict[str, str]:
    return {str(k): str(v) for k, v in read_json(state / "last.json").items()}


def write_last(last: Dict[str, str], state: Path = STATE) -> None:
    write_atomic(state / "last.json", json.dumps(last, sort_keys=True) + "\n")


def remember(key: str, address: str, state: Path = STATE) -> Dict[str, str]:
    """Record the terminal last shown for a group. Read, change, write: another window's entries stay."""
    last = read_last(state)
    if last.get(key) != address:
        last[key] = address
        write_last(last, state)
    return last


def read_names(state: Path = STATE) -> Dict[str, str]:
    """The display names (names.json, shared by all windows): {"space:dev": "Main", "rig:guest": "Guest",
    "term:mini/t5": "web"}. Junk entries are left out."""
    return clean_names(read_json(state / "names.json"))


def change_names(changes: Mapping[str, str], state: Path = STATE) -> Dict[str, str]:
    """Set (or, for "", remove) display names. Read, change, write: another window's renames stay."""
    names = read_names(state)
    for key, value in changes.items():
        names = renamed(names, key, value)
    write_atomic(state / "names.json", json.dumps(names, sort_keys=True, ensure_ascii=False) + "\n")
    return names


def read_panes(win: Path = WINDOW) -> Dict[str, str]:
    """The window's tmux pane ids, written by start.sh (a sidebar brought back writes its own):
    {"side": "%1", "tabs": "%2", "view": "%0"}."""
    panes: Dict[str, str] = {}
    for line in read_text(win / "panes").splitlines():
        key, _, value = line.partition("=")
        if key.strip() and value.strip():
            panes[key.strip()] = value.strip()
    return panes


def parse_sidebar_state(text: Optional[str], collapsed: str = "") -> str:
    """The sidebar's state from the file "sidebar" (None: there is no such file). Without that file the old file
    "collapsed" counts ("1" = strip), so an older install keeps its folded sidebar; junk counts as open."""
    if text is None:
        return "strip" if collapsed == "1" else "open"
    return text if text in SIDEBAR_STATES else "open"


def read_sidebar_state(state: Path = STATE) -> str:
    """"open", "strip" or "hidden": how the next sidebar starts (shared by all windows)."""
    path = state / "sidebar"
    if path.exists():
        return parse_sidebar_state(read_text(path))
    return parse_sidebar_state(None, read_text(state / "collapsed"))


def write_sidebar_state(value: str, state: Path = STATE) -> None:
    write_atomic(state / "sidebar", value + "\n")


def read_servers_shown(state: Path = STATE) -> bool:
    """Is the servers section shown? The shared file "servers" says "shown"; anything else (no file: the default)
    is hidden."""
    return read_text(state / "servers") == "shown"


def write_servers_shown(shown: bool, state: Path = STATE) -> None:
    write_atomic(state / "servers", ("shown" if shown else "hidden") + "\n")


def read_agents_shown(state: Path = STATE) -> bool:
    """Is the agents section shown? The shared file "agents" says "hidden"; anything else (no file: the default) is
    shown."""
    return read_text(state / "agents") != "hidden"


def write_agents_shown(shown: bool, state: Path = STATE) -> None:
    write_atomic(state / "agents", ("shown" if shown else "hidden") + "\n")


def read_devs_shown(state: Path = STATE) -> bool:
    """Is the dev servers section shown (while it has rows)? The shared file "devservers" says "hidden"; anything
    else (no file: the default) is shown."""
    return read_text(state / "devservers") != "hidden"


def write_devs_shown(shown: bool, state: Path = STATE) -> None:
    write_atomic(state / "devservers", ("shown" if shown else "hidden") + "\n")


def read_seen(state: Path = STATE) -> Dict[str, int]:
    """seen.json: address -> the turn at which that terminal was last shown while done (needs_you)."""
    return clean_seen(read_json(state / "seen.json"))


def write_seen(seen: Mapping[str, int], state: Path = STATE) -> None:
    write_atomic(state / "seen.json", json.dumps(dict(seen)) + "\n")  # in order: mark_seen keeps the newest


WIDTH_LIMITS = (10, 200)  # as MMINI_WIDTH


def read_open_width(state: Path = STATE, default: int = WIDTH) -> int:
    """The open sidebar's width: the one its divider was last dragged to (the shared file "width"), else
    MMINI_WIDTH. Junk or a width out of 10-200 counts as no file."""
    try:
        width = int(read_text(state / "width"))
    except ValueError:
        return default
    return width if WIDTH_LIMITS[0] <= width <= WIDTH_LIMITS[1] else default


def write_open_width(width: int, state: Path = STATE) -> int:
    """Keep a dragged width for the next sidebar (all windows), within 10-200 columns; returns what was kept."""
    width = max(WIDTH_LIMITS[0], min(WIDTH_LIMITS[1], width))
    write_atomic(state / "width", f"{width}\n")
    return width


def read_split(state: Path = STATE) -> Optional[Tuple[int, int]]:
    """Where the separator was moved to (the shared file "split", parse_split); None: the automatic layout."""
    return parse_split(read_text(state / "split"))


def write_split(row: int, height: int, state: Path = STATE) -> None:
    """Keep the separator on line `row` of a `height`-line pane, for every sidebar (all windows, the next start)."""
    write_atomic(state / "split", f"{row}/{height}\n")


def clear_split(state: Path = STATE) -> None:
    """Back to the automatic layout: the file "split" goes (no file is fine)."""
    try:
        (state / "split").unlink()
    except FileNotFoundError:
        pass


def sidebar_alive(win: Path = WINDOW) -> bool:
    """Does this window have a running sidebar? The pid in sidebar.pid, looked at with signal 0 (nothing is sent).
    A sidebar ended by a hangup leaves its file behind: a dead pid counts as no sidebar."""
    try:
        pid = int(read_text(win / "sidebar.pid"))
    except ValueError:
        return False
    if pid <= 0:  # 0 or less would address a process group
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True  # it exists, as another user's process
    except OSError:
        return False
    return True


def remove_own_pid(win: Path = WINDOW) -> None:
    """Remove sidebar.pid when it holds this program's pid: a newer sidebar's file is never touched."""
    if read_text(win / "sidebar.pid") == str(os.getpid()):
        try:
            (win / "sidebar.pid").unlink()
        except OSError:
            pass


def tab_engine_wanted(alive: bool, missing_for: float, hidden: bool, grace: float = ENGINE_GRACE) -> bool:
    """Should the tab bar run the engine? Only while this window has no live sidebar: at once when the sidebar was
    hidden (it writes "hidden" before it ends), else after `grace` seconds without one, so a normal start (both
    panes start together, the sidebar writes its pid a moment later) never runs two engines."""
    return not alive and (hidden or missing_for >= grace)


def make_snapshot(group: Group, now: float, servers: Optional[Mapping[str, str]] = None, shown: str = "",
                  shown_title: str = NO_TITLE, everything: Sequence[Term] = (),
                  infos: Optional[Mapping[str, Info]] = None) -> dict:
    """What the tab bar needs about the current group. "name" is the space's own name (the label a new shell gets),
    "title" what is drawn (the display name); a tab's "label" is the terminal's shown name, its "mark" the account
    mark drawn after it (never part of the window title). "server" (the group's,
    and each tab's) is the server's drawn name (`servers`: machine -> server_name; a machine missing there: its hc
    name), known also while the servers are hidden: the tab bar builds the window title from it. "shown" and
    "shown_title": the terminal shown when this was written and its window title (the engine's own).

    For the tab menu: a tab's "own" is its name without a rename (a rename to it removes the rename), its "ends"
    the child terminals that end with it ([address, shown name, program], from `everything` and `infos`, see
    ending); "names" is the shown name of every listed terminal (`everything`), so a rename can refuse a taken one."""
    servers, infos = servers or {}, infos or {}

    def ends(t: Term) -> List[List[str]]:
        return [[c.address, c.shown, c.agent] for c in ending([t], everything, infos)[1:]]

    return {"group": group.key, "name": group.name, "title": group.shown, "kind": group.kind, "machine": group.machine,
            "server": servers.get(group.machine, group.machine), "cwd": group.cwd, "ts": now, "shown": shown,
            "shown_title": shown_title, "names": {t.address: t.shown for t in everything},
            "tabs": [{"address": t.address, "label": t.shown, "status": t.status, "agent": t.agent, "cwd": t.cwd,
                      "server": servers.get(t.machine, t.machine), "mark": t.mark, "own": t.label, "ends": ends(t)}
                     for t in group.terms]}


def write_snapshot(group: Optional[Group], win: Path = WINDOW, now: Optional[float] = None,
                   servers: Optional[Mapping[str, str]] = None, shown: str = "", shown_title: str = NO_TITLE,
                   everything: Sequence[Term] = (), infos: Optional[Mapping[str, Info]] = None) -> None:
    now = time.time() if now is None else now
    snap = make_snapshot(group, now, servers, shown, shown_title, everything, infos) if group else {
        "group": "", "name": "", "title": "", "kind": "", "machine": LOCAL, "server": LOCAL, "cwd": "", "ts": now,
        "shown": shown, "shown_title": shown_title, "names": {}, "tabs": []}
    write_atomic(win / "tabs.json", json.dumps(snap) + "\n")


def write_title(address: str, title: str, win: Path = WINDOW) -> None:
    """The file "title" of the window, for view.sh (it sets the view's title before each attach): the address on
    the first line, its window title on the second. The title holds no line break (window_title)."""
    write_atomic(win / "title", f"{address}\n{window_title(title, '')}\n", encoding="utf-8")


def read_snapshot(win: Path = WINDOW, now: Optional[float] = None) -> Optional[dict]:
    """The sidebar's snapshot, or None when missing, broken or older than SNAPSHOT_MAX_AGE (sidebar not running)."""
    now = time.time() if now is None else now
    snap = read_json(win / "tabs.json")
    try:
        if not snap or now - float(snap.get("ts", 0)) > SNAPSHOT_MAX_AGE:
            return None
    except (TypeError, ValueError):
        return None
    tabs = snap.get("tabs")
    if not isinstance(tabs, list):
        return None
    snap["tabs"] = [t for t in tabs if isinstance(t, dict) and t.get("address")]
    return snap


ATTACH_RE = re.compile(r"(?:^|[\s/])(?:hc|herdr-core) attach\b")


def attach_pid(win: Path = WINDOW) -> int:
    """The pid of this window's running `hc attach`, or 0. Nobody is signalled unless three things hold: the pid
    is in this window's view.pid, the process is a child of this window's view loop (pid in view.loop), and its
    command line is an attach. A stale file or a reused pid therefore never reaches another program."""
    try:
        pid, loop = int(read_text(win / "view.pid")), int(read_text(win / "view.loop"))
        found = proc_info(pid)
        if found is None:  # the kernel could not be asked: ps (2-7 ms more on every pick)
            out = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "ppid=,command="], capture_output=True, text=True,
                                 check=False, timeout=5, stdin=subprocess.DEVNULL).stdout.split(None, 1)
            found = (int(out[0]), out[1]) if len(out) == 2 else (0, "")
        if found[0] == loop and ATTACH_RE.search(found[1]):
            return pid
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 0


PROC_PIDTBSDINFO, BSDINFO_SIZE, BSDINFO_PPID = 3, 136, 16  # <sys/proc_info.h>: struct proc_bsdinfo, pbi_ppid
CTL_KERN, KERN_PROCARGS2 = 1, 49  # <sys/sysctl.h>


def proc_info(pid: int) -> Optional[Tuple[int, str]]:
    """(parent pid, command line) of a running process, asked from the macOS kernel (proc_pidinfo, sysctl
    KERN_PROCARGS2) in a tenth of a millisecond, where ps took 2-7 ms on one Mac. (0, "") when no such process
    runs (or it has ended and waits to be reaped). None when the kernel cannot be asked this way (not macOS, an
    error): the caller then runs ps."""
    if sys.platform != "darwin" or pid <= 0:
        return None
    try:
        import ctypes  # here: only this function needs it

        libc = ctypes.CDLL(None, use_errno=True)
        libc.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        libc.proc_pidinfo.restype = ctypes.c_int
        info = ctypes.create_string_buffer(BSDINFO_SIZE)
        if libc.proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, info, BSDINFO_SIZE) != BSDINFO_SIZE:
            return (0, "") if ctypes.get_errno() == errno.ESRCH else None  # not running
        ppid = struct.unpack_from("=I", info.raw, BSDINFO_PPID)[0]
        mib = (ctypes.c_int * 3)(CTL_KERN, KERN_PROCARGS2, pid)
        size = ctypes.c_size_t(os.sysconf("SC_ARG_MAX"))
        buf = ctypes.create_string_buffer(size.value)
        if libc.sysctl(mib, 3, buf, ctypes.byref(size), None, ctypes.c_size_t(0)) != 0:
            # gone, or ended and not reaped yet (EINVAL)
            return (0, "") if ctypes.get_errno() in (errno.ESRCH, errno.EINVAL) else None
        raw = buf.raw[:size.value]
        argc = struct.unpack_from("=i", raw, 0)[0]
        # argc, the executable's path, NUL padding, then the arguments (then the environment, not read)
        rest = raw[4:]
        rest = rest[rest.find(b"\0"):].lstrip(b"\0")
        args = rest.split(b"\0")[:argc]
        return ppid, " ".join(a.decode("utf-8", "replace") for a in args)
    except Exception:  # noqa: BLE001 - ps is the fallback
        return None


def end_current_attach(win: Path = WINDOW) -> None:
    """End the view's `hc attach` so its loop attaches to the new target at once. Only the fast path: view.sh
    also ends its own attach when it sees the counter change, so a pick is never lost when this finds nothing."""
    pid = attach_pid(win)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def show(address: str, win: Path = WINDOW, title: Optional[str] = None) -> None:
    """Make the view show `address` ("": nothing, the view says to pick a terminal): write target, bump gen, end its
    current attach. Nothing happens when the view is already attached to it (no re-attach, no flash). `title`: the
    window title for it, written to "title" before the target, so view.sh finds it when it attaches."""
    if address and address == current_target(win) and attach_pid(win):
        return
    if title is not None:
        write_title(address, title, win)
    write_atomic(win / "target", address + "\n")
    write_atomic(win / "gen", f"{time.time_ns()}\n")
    end_current_attach(win)
    leave_copy_mode(win)


def leave_copy_mode(win: Path = WINDOW) -> None:
    """A view scrolled back (tmux's copy mode, the mouse wheel) would keep showing the old terminal's lines over the
    new one, and take the keys: a pick ends it."""
    view = pane_id("view", win)
    if view:
        tmux("if-shell", "-F", "-t", view, "#{pane_in_mode}", f"send-keys -X -t {view} cancel")


# ---------------------------------------------------------------------------------------------------------------
# hc
# ---------------------------------------------------------------------------------------------------------------
def run_hc(*args: str, timeout: float = 10.0) -> str:
    return subprocess.run([HC, *args], check=True, capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL).stdout


def describe_error(exc: BaseException) -> str:
    """Short text for a failure. hc --json reports errors as {"error": {"message", "kind", "hint"}} on stderr."""
    if isinstance(exc, subprocess.CalledProcessError):
        text = (exc.stderr or "").strip()
        try:
            error = json.loads(text.splitlines()[0]).get("error") if text else None
            if isinstance(error, dict):
                text = str(error.get("message") or error.get("kind") or text)
        except (ValueError, AttributeError):
            pass
        lines = text.splitlines()
        return lines[0][:60] if lines else f"hc exit {exc.returncode}"
    if isinstance(exc, subprocess.TimeoutExpired):
        return "hc did not answer"
    if isinstance(exc, FileNotFoundError):
        return "hc not found"
    return str(exc)[:60] or type(exc).__name__


Runner = Optional[Callable[..., str]]  # stands in for run_hc in tests


def new_shell(machine: str, cwd: str, win: Path = WINDOW, space: str = "", runner: Runner = None,
              name: str = "") -> str:
    """Start a shell (`hc run --bg --json`) on `machine` in `cwd`, with the label space=<space> when given, so it
    stays in that space whatever its folder is, and the name `name` when given. Returns its full address and pokes
    the sidebar."""
    runner = runner or run_hc
    args = ["run", "--bg", "--json", "--no-parent"]
    args += [] if machine == LOCAL else ["--on", machine]
    args += ["--name", name] if name else []
    args += ["--cwd", cwd] if cwd else []
    args += ["--label", "space=" + space] if space else []
    return started(runner(*args, timeout=30.0), machine, win)


def started(raw: str, machine: str, win: Path = WINDOW) -> str:
    """The full address from `hc run --bg --json`'s answer (with the machine in front when hc left it out), after
    poking the engine so the new terminal is listed at once."""
    data = json.loads(raw)
    address = str(data.get("address") or "") if isinstance(data, dict) else ""
    if not address:
        raise ValueError("hc returned no address")
    if "/" not in address and machine != LOCAL:
        address = f"{machine}/{address}"
    poke_engine(win)
    return address


def poke_engine(win: Path = WINDOW, full: bool = False) -> None:
    """Wake the window's engine for a listing now (refresh_forever watches the file "poke"). `full`: it also asks
    `hc get` again for every terminal (a label set by hand, a moved terminal): the file "poke.full", which only
    the engine removes, so a plain poke right after cannot hide it."""
    if full:
        write_atomic(win / "poke.full", f"{time.time_ns()}\n")
    write_atomic(win / "poke", f"{time.time_ns()}\n")


def start_add_rig(target: str, name: str, win: Path = WINDOW, runner: Runner = None) -> str:
    """A new terminal on this Mac that runs `hc machine add` (see add_rig_args); returns its address."""
    runner = runner or run_hc
    return started(runner(*add_rig_args(HC, target, name, str(Path.home())), timeout=30.0), LOCAL, win)


def error_kind(exc: BaseException) -> str:
    """The "kind" of an hc error ({"error": {"kind": ...}} on stderr), "" when there is none."""
    if not isinstance(exc, subprocess.CalledProcessError):
        return ""
    try:
        error = json.loads((exc.stderr or "").strip().splitlines()[0]).get("error")
    except (ValueError, AttributeError, IndexError):
        return ""
    return str(error.get("kind") or "") if isinstance(error, dict) else ""


def end_terminal(address: str, runner: Runner = None) -> None:
    """End a terminal for good and remove it (end_steps). A terminal that has finished already cannot be kept
    ("invalid_params"); one that is gone ("not_found": it ended with its parent, or was started with --rm) is done.
    Any other hc error raises."""
    runner = runner or run_hc
    for step in end_steps(address):
        try:
            runner(*step, timeout=END_WAIT + 10.0)
        except subprocess.CalledProcessError as exc:
            kind = error_kind(exc)
            if kind == "not_found":
                return
            if step[0] == "keep" and kind == "invalid_params":
                continue
            raise


def forget_rig(machine: str, runner: Runner = None) -> None:
    (runner or run_hc)(*forget_args(machine), timeout=30.0)


def fetch_infos(addresses: Sequence[str], runner: Runner = None) -> Dict[str, Optional[Info]]:
    """`hc get` for each address, side by side. None for one that failed or printed junk: it never raises."""
    runner = runner or run_hc

    def one(address: str) -> Optional[Info]:
        try:
            return parse_info(runner("get", address, "--json", timeout=5.0), address)
        except Exception:  # noqa: BLE001 - one bad terminal must not stop the refresh
            return None

    if not addresses:
        return {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(addresses))) as pool:
        return dict(zip(addresses, pool.map(one, addresses)))


def probe_folder(machine: str, folder: str, runner: Runner = None) -> Tuple[str, bool]:
    """(home folder of `machine`, does `folder` exist there), asked with `hc exec`. The folder is absolute or
    relative to that home folder; nothing is expanded by a shell on this Mac."""
    runner = runner or run_hc
    on = [] if machine == LOCAL else ["--on", machine]
    return parse_probe(runner("exec", *on, "/bin/sh", "-c", PROBE, "mmini", folder, timeout=15.0))


def keychain_enabled() -> bool:
    """Is the keychain check on? Not with MMINI_KEYCHAIN=0 (read at each call): no check, no red line."""
    return os.environ.get("MMINI_KEYCHAIN", "1") != "0"


def check_keychain(machine: str, runner: Runner = None) -> str:
    """The home machine's login keychain as its core sees it: "unlocked", "locked" or "failed" (parse_keychain; hc
    could not run it: failed). One `hc exec`, read-only."""
    try:
        return parse_keychain((runner or run_hc)(*exec_args(machine, KEYCHAIN_SCRIPT), timeout=EXEC_TIMEOUT + 10.0))
    except Exception:  # noqa: BLE001 - not known: nothing is drawn
        return "failed"


def fetch_dev_servers(machine: str, runner: Runner = None) -> Optional[List[DevServer]]:
    """The dev servers of `machine` (parse_dev_servers), from one `hc exec`; None when it could not be asked."""
    try:
        code, out, _, timed_out = exec_result(
            (runner or run_hc)(*exec_args(machine, DEV_SCRIPT), timeout=EXEC_TIMEOUT + 10.0))
    except Exception:  # noqa: BLE001 - the last list stays
        return None
    return parse_dev_servers(out) if code == 0 and not timed_out else None


def browser_enabled() -> bool:
    """May a dev server be opened in this Mac's browser? Not with MMINI_BROWSER=0 (a Mac without a screen, the
    tests)."""
    return os.environ.get("MMINI_BROWSER", "1") != "0"


def open_url(host: str, port: int) -> bool:
    """Open http://<host>:<port>/ in this Mac's default browser (open_url_args; raises ValueError for a bad host or
    port). False when that is switched off (browser_enabled) or `open` could not start."""
    args = open_url_args(host, port)
    if not browser_enabled():
        return False
    try:
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------------------------------------------
# tmux: the window's three panes run in a tmux server of the window's own (start.sh, mmini.tmux.conf), so a click
# reaches the pane under the pointer at once. The panes file names them by tmux pane id. Nothing here raises.
# ---------------------------------------------------------------------------------------------------------------
PANE_ID = re.compile(r"%[0-9]+")
TERM_NAME = "xterm-mmini"  # the terminal type of mmini's own panes (mmini.terminfo)
TAB_ROWS = 3  # the tab bar: the tabs, the line about the shown terminal (or a tab's menu), the hints
ZOOM_LOOK = 0.25  # seconds between two looks at a zoomed window by a pane that waits to size itself (a round)
MIN_VIEW = 20  # columns the view keeps at least: a sidebar width dragged in a wide window is capped in a narrow one
_TMUX: List[str] = []  # the tmux program, once found


def tmux_enabled() -> bool:
    """Inside the window's tmux ($TMUX, set by tmux in its panes), unless MMINI_TMUX=0 (the tests)."""
    return bool(os.environ.get("TMUX")) and os.environ.get("MMINI_TMUX", "1") != "0"


def tmux_program() -> str:
    """tmux from PATH, else Homebrew's (Apple silicon, then Intel)."""
    if not _TMUX:
        found = shutil.which("tmux") or next(
            (p for p in ("/opt/homebrew/bin/tmux", "/usr/local/bin/tmux") if os.access(p, os.X_OK)), "tmux")
        _TMUX.append(found)
    return _TMUX[0]


def tmux(*args: str, input: Optional[str] = None) -> Optional[str]:
    """Run tmux commands in this window's server (several: joined by a ";" argument); their output, None when tmux
    is off, could not run or failed. `input`: what tmux reads on stdin (load-buffer -: no size limit, where an
    argument over 16 KB is refused). Waits at most 3 s."""
    if not tmux_enabled():
        return None
    try:
        feed = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
        done = subprocess.run([tmux_program(), *args], capture_output=True, text=True, timeout=3.0, **feed)
    except Exception:  # noqa: BLE001 - the UI must never die because of tmux
        return None
    return done.stdout if done.returncode == 0 else None


def pane_id(pane: str, win: Path = WINDOW) -> str:
    """The tmux id of one of the window's panes ("side", "tabs", "view"), "" when the panes file has none."""
    value = read_panes(win).get(pane, "")
    return value if PANE_ID.fullmatch(value) else ""


def own_pane() -> str:
    """This program's tmux pane ($TMUX_PANE), "" outside tmux."""
    value = os.environ.get("TMUX_PANE", "")
    return value if PANE_ID.fullmatch(value) else ""


def focus_pane(pane: str, win: Path = WINDOW) -> None:
    """Give the keyboard to one of the window's panes ("side", "tabs", "view")."""
    target = pane_id(pane, win)
    if target:
        tmux("select-pane", "-t", target)


def focus_view(win: Path = WINDOW) -> None:
    """The keyboard to the shown terminal: after a pick, and when a menu or a question has gone."""
    focus_pane("view", win)


def zoom_view(win: Path = WINDOW) -> str:
    """The "z" key: the whole window for the shown terminal (tmux's zoom). A line on top, "‹ back", brings the panes
    back on a click (mmini.tmux.conf). Returns a notice instead when nothing is shown (no target, or the view is
    not attached to it), "" when done."""
    if not current_target(win) or not attach_pid(win):
        return "z: nothing shown"
    target = pane_id("view", win)
    if target:
        tmux("select-pane", "-t", target, ";", "resize-pane", "-Z", "-t", target)
    return ""


# Keys typed in a pane of mmini that go on to the view (send_keys_to_view): bytes as they came (send-keys -H: the
# exact bytes, ";" and control keys included), keys curses decoded by their tmux name.
KEY_NAMES = {curses.KEY_ENTER: "Enter", curses.KEY_BACKSPACE: "BSpace", curses.KEY_UP: "Up", curses.KEY_DOWN: "Down",
             curses.KEY_LEFT: "Left", curses.KEY_RIGHT: "Right", curses.KEY_HOME: "Home", curses.KEY_END: "End",
             curses.KEY_DC: "DC", curses.KEY_IC: "IC", curses.KEY_PPAGE: "PPage", curses.KEY_NPAGE: "NPage",
             curses.KEY_BTAB: "BTab"}
# terminfo names of modified keys (kLFT5: ctrl+left) -> tmux's: the key, then the modifier digit
TERMINFO_KEYS = {"LFT": "Left", "RIT": "Right", "UP": "Up", "DN": "Down", "HOM": "Home", "END": "End", "DC": "DC",
                 "IC": "IC", "PRV": "PPage", "NXT": "NPage"}
MODIFIERS = {"2": "S-", "3": "M-", "4": "S-M-", "5": "C-", "6": "C-S-", "7": "C-M-", "8": "C-S-M-"}
FORWARD_GRACE = 0.3  # seconds after a key closed a right-click menu in which keys still go on to the view


def key_name(key: int) -> str:
    """tmux's name for a key curses decoded (>= 256), "" when it has none."""
    if key in KEY_NAMES:
        return KEY_NAMES[key]
    if curses.KEY_F0 < key <= curses.KEY_F0 + 24:
        n = key - curses.KEY_F0
        return f"F{n}" if n <= 12 else f"S-F{n - 12}"
    try:
        name = curses.keyname(key).decode("ascii", "replace")
    except (curses.error, ValueError, OverflowError):
        return ""
    found = re.fullmatch(r"k(LFT|RIT|UP|DN|HOM|END|DC|IC|PRV|NXT)([2-8])", name)
    return MODIFIERS[found.group(2)] + TERMINFO_KEYS[found.group(1)] if found else ""


def view_key_args(keys: Sequence[int], view: str) -> List[str]:
    """tmux arguments that type `keys` into the view: bytes as they came (send-keys -H, so ";", esc and control
    keys arrive unchanged), enter (10 or 13: curses reads the return key as 10) by name, keys curses decoded by
    their tmux name (key_name); a key without one is left out."""
    args: List[str] = []
    run: List[str] = []

    def flush() -> None:
        if run:
            args.extend(["send-keys", "-t", view, "-H", *run, ";"])
            run.clear()

    for key in keys:
        name = "Enter" if key in (10, 13) else ("" if 0 <= key < 256 else key_name(key))
        if 0 <= key < 256 and not name:
            run.append(f"{key:02x}")
        elif name:
            flush()
            args.extend(["send-keys", "-t", view, name, ";"])
    flush()
    return args


def drain_keys(scr: "curses.window", limit: int = 4096) -> List[int]:
    """The keys typed ahead and not read yet (mouse events are read and dropped)."""
    keys: List[int] = []
    scr.nodelay(True)
    try:
        while len(keys) < limit:
            key = scr.getch()
            if key == -1:
                break
            if key == curses.KEY_MOUSE:
                read_mouse_event()
                continue
            keys.append(key)
    finally:
        scr.nodelay(False)
        scr.timeout(LOOP_WAIT_MS)
    return keys


def send_keys_to_view(keys: Sequence[int], win: Path = WINDOW) -> None:
    """Type `keys` into the view and give it the keyboard: keys typed in a pane of mmini that were meant for the
    terminal (after a right click) are not lost. A lone esc (no bytes after it) only closed the menu."""
    view = pane_id("view", win)
    if not view:
        return
    tmux(*view_key_args([] if list(keys) == [27] else keys, view), "select-pane", "-t", view)


PASTE_START = [ord(c) for c in "[200~"]  # after the esc that bracketed paste starts with
PASTE_END = [27] + [ord(c) for c in "[201~"]


def read_paste(scr: "curses.window", wait: float = 1.0, limit: int = 64 * 1024 * 1024) -> Optional[str]:
    """After an esc: the text of a bracketed paste (mode 2004, which the sidebar and the tab bar ask for), or None
    when the esc was a key of its own (the keys read to tell are given back). A dropped file arrives as such a
    paste of its path. Read until the end marker; given up only after `wait` seconds without a byte (a long paste
    may come in slowly), or at `limit` bytes."""
    got: List[int] = []
    scr.nodelay(True)
    try:
        for want in PASTE_START:
            key = scr.getch()
            if key != want:
                unget = getattr(scr, "unget", None) or curses.ungetch  # the tests' screen keeps its own queue
                for back in reversed(got + ([key] if key != -1 else [])):
                    unget(back)
                return None
            got.append(key)
        body: List[int] = []
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline and len(body) < limit:
            key = scr.getch()
            if key == -1:
                time.sleep(0.005)
                continue
            deadline = time.monotonic() + wait
            if 0 <= key < 256:
                body.append(key)
            if body[-len(PASTE_END):] == PASTE_END:
                del body[-len(PASTE_END):]
                break
        return bytes(body).decode("utf-8", "replace")
    finally:
        scr.nodelay(False)
        scr.timeout(LOOP_WAIT_MS)


def paste_to_view(text: str, win: Path = WINDOW) -> bool:
    """A paste (a dropped file) that reached a pane of mmini: into the view, as a paste (bracketed when the
    program there asks for it), and the view gets the keyboard either way. Before tmux each pane got its own drops;
    now a drop goes to the pane with the keyboard. The text goes on tmux's stdin (load-buffer -): an argument over
    16 KB would be refused. False when it could not be passed on (the caller says so)."""
    view = pane_id("view", win)
    if not view:
        return False
    loaded = bool(text) and tmux("load-buffer", "-b", "mmini-paste", "-", input=text) is not None
    if loaded:
        loaded = tmux("paste-buffer", "-p", "-d", "-b", "mmini-paste", "-t", view) is not None
    tmux("select-pane", "-t", view)
    return loaded or not text


def prompt_text(text: str) -> str:
    """A paste typed into a question: one line, printable ASCII only (as the keys a question takes)."""
    return "".join(c for c in text.replace("\r", " ").replace("\n", " ") if 32 <= ord(c) < 127)


BRACKETED_PASTE_ON, BRACKETED_PASTE_OFF = b"\x1b[?2004h", b"\x1b[?2004l"


def bracketed_paste(on: bool, fd: int = 1) -> None:
    """Ask the terminal (tmux) to mark pastes in this pane (mode 2004), or stop: a paste is then told from typing."""
    try:
        os.write(fd, BRACKETED_PASTE_ON if on else BRACKETED_PASTE_OFF)
    except OSError:
        pass


@dataclass(frozen=True)
class WindowLook:
    """What a pane needs to know before it sizes itself: is the view zoomed (a resize would end the zoom), the
    window's size and the pane's own size, as tmux has them now. curses learns a new size later (tmux holds a
    pane's next size signal up to 250 ms), so a pane decides on these, never on getmaxyx. tmux gives a width change
    of the window to the sidebar first (it is the window's first column): the sidebar's own width changing while the
    window kept its width is a dragged divider."""

    zoomed: bool
    width: int
    height: int
    pane_width: int
    pane_height: int


LOOK_FORMAT = "#{window_zoomed_flag} #{window_width} #{window_height} #{pane_width} #{pane_height}"


def parse_window_look(out: Optional[str]) -> Optional[WindowLook]:
    """tmux's answer to LOOK_FORMAT (the last line: size_pane asks after a resize); None for anything else."""
    lines = (out or "").strip().splitlines()
    parts = lines[-1].split() if lines else []
    if len(parts) != 5 or parts[0] not in ("0", "1") or not all(p.isdigit() for p in parts[1:]):
        return None
    return WindowLook(parts[0] == "1", *(int(p) for p in parts[1:]))


def window_look(pane: str) -> Optional[WindowLook]:
    return parse_window_look(tmux("display", "-p", "-t", pane, LOOK_FORMAT))


def pane_active(pane: str) -> Optional[bool]:
    """Has `pane` the keyboard? None when tmux cannot tell."""
    out = (tmux("display", "-p", "-t", pane, "#{pane_active}") or "").strip()
    return {"1": True, "0": False}.get(out)


def size_pane(pane: str, cols: int = 0, rows: int = 0) -> Optional[WindowLook]:
    """Make a pane exactly `cols` columns wide or `rows` rows high (tmux leaves every other pane at least one cell);
    returns the window and the pane as they are right after, in the same tmux call (a window change in between
    cannot be missed), None when unknown."""
    flag, value = ("-x", cols) if cols else ("-y", rows)
    return parse_window_look(tmux("resize-pane", "-t", pane, flag, str(value), ";", "display", "-p", "-t", pane,
                                  LOOK_FORMAT))


def mmini_env(environ: Mapping[str, str]) -> List[Tuple[str, str]]:
    """This program's MMINI_* settings, sorted, for a sidebar brought back (MMINI_WINDOW is passed apart); then its
    TERM and TERMINFO when the terminal type is mmini's own (TERM_NAME)."""
    pairs = sorted((k, v) for k, v in environ.items() if ENV_NAME.fullmatch(k) and k != "MMINI_WINDOW")
    if environ.get("TERM") == TERM_NAME:
        pairs += [(k, environ[k]) for k in ("TERM", "TERMINFO") if environ.get(k)]
    return pairs


def pane_command(mode: str, win: Path, base: Path, env: Sequence[Tuple[str, str]]) -> str:
    """The command of a new pane (tmux runs it with sh -c): `exec` replaces the shell, so the pane closes when the
    program ends. MMINI_WINDOW first, then the other settings, then this pane's terminal type when it is mmini's
    own (TERM xterm-mmini with its TERMINFO folder, see start.sh): the new pane gets the same mouse codes."""
    pairs = [("MMINI_WINDOW", str(win))] + [(k, v) for k, v in env if k != "MMINI_WINDOW" and ENV_NAME.fullmatch(k)]
    pairs += [(k, v) for k, v in env if k in ("TERM", "TERMINFO") and env_get(env, "TERM") == TERM_NAME]
    assigns = " ".join(f"{k}={shlex.quote(v)}" for k, v in pairs)
    return f"exec env {assigns} python3 {shlex.quote(str(base / 'mmini.py'))} {mode}"


def env_get(env: Sequence[Tuple[str, str]], name: str) -> str:
    return next((v for k, v in env if k == name), "")


def split_sidebar(win: Path, base: Path, env: Sequence[Tuple[str, str]], width: int) -> str:
    """Bring the sidebar back: a new pane on the left of the view and the tab bar, at the window's full height
    (split-window -f), `width` columns wide, running `mmini.py sidebar`. Its id goes into the panes file. Returns
    the id, "" when nothing was made (no pane to split from, tmux off or failed)."""
    target = pane_id("view", win) or own_pane()  # with -f the target only names the window
    if not target:
        return ""
    out = tmux("split-window", "-f", "-hb", "-d", "-l", str(max(1, width)), "-t", target, "-P", "-F", "#{pane_id}",
               pane_command("sidebar", win, base, env))
    new = (out or "").strip()
    if not PANE_ID.fullmatch(new):
        return ""
    panes = dict(read_panes(win), side=new)
    write_atomic(win / "panes", "".join(f"{k}={v}\n" for k, v in panes.items()))
    return new


def autosize_enabled() -> bool:
    """Do the sidebar and the tab bar size their panes? In tmux, unless MMINI_AUTOSIZE=0."""
    return os.environ.get("MMINI_AUTOSIZE", "1") != "0" and tmux_enabled()


# ---------------------------------------------------------------------------------------------------------------
# Curses helpers
# ---------------------------------------------------------------------------------------------------------------
def setup_locale() -> None:
    """Take the user's locale; when it is unusable or not UTF-8 (LANG=xx_YY.UTF-8 does not exist on macOS, LANG=C),
    switch only the character set to UTF-8, which Ghostty always shows. Never raises."""
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    for name in ("", "en_US.UTF-8", "UTF-8", "C.UTF-8"):
        if utf8_screen():
            return
        try:
            locale.setlocale(locale.LC_CTYPE, name)
        except locale.Error:
            pass


def utf8_screen() -> bool:
    """Can curses draw non-ASCII? It follows the C locale's character set, not Python's own UTF-8 mode."""
    try:
        return locale.nl_langinfo(locale.CODESET).lower().replace("-", "") == "utf8"
    except (AttributeError, ValueError, locale.Error):
        return False


def glyph(text: str) -> str:
    """Text with non-ASCII glyphs swapped for ASCII when the screen cannot show them."""
    if text.isascii() or utf8_screen():
        return text
    return "".join(ASCII_GLYPHS.get(c, c if ord(c) < 128 else "?") for c in text)


class Screen:
    """Thin wrapper: every draw is cut to the window by screen columns (a wide character takes two) and cannot
    raise. The last column stays empty."""

    def __init__(self, scr: "curses.window") -> None:
        self.scr = scr

    def size(self) -> Tuple[int, int]:
        return self.scr.getmaxyx()

    def put(self, y: int, x: int, text: str, attr: int = 0) -> None:
        height, width = self.scr.getmaxyx()
        if not (0 <= y < height and 0 <= x < width - 1) or not text:
            return
        try:
            shown = fit_columns(glyph(text), width - x - 1)
            if shown:
                self.scr.addnstr(y, x, shown, len(shown), attr)
        except (curses.error, UnicodeError, ValueError):
            pass

    def fill(self, y: int, attr: int) -> None:
        _, width = self.scr.getmaxyx()
        self.put(y, 0, " " * max(0, width - 1), attr)


def setup_curses(scr: "curses.window", right: bool = False, motion: bool = False) -> None:
    """`right`: take the right button too (the menus of the sidebar and of a tab). `motion`: ncurses
    also reports the pointer moving (the sidebar's separator drag; report_drags asks the terminal for it)."""
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    try:
        curses.use_default_colors()
        for pair, color in ((1, curses.COLOR_RED), (2, curses.COLOR_GREEN), (3, curses.COLOR_YELLOW),
                            (4, curses.COLOR_BLUE)):
            curses.init_pair(pair, color, -1)
    except curses.error:
        pass
    # ncurses holds a press for mouseinterval (166 ms by default), and after the release as long again, to see
    # whether it becomes a click or a double click. Interval 0 and no CLICKED in the mask: each press is reported
    # the moment it arrives, and acted on; its release is reported apart and ignored (read_mouse).
    try:
        curses.mouseinterval(0)
    except curses.error:
        pass
    try:  # ctrl+C, ctrl+\ and ctrl+Z read as keys: as signals they would end this pane for good
        curses.raw()
    except curses.error:
        pass
    curses.mousemask(mouse_buttons(right) | (curses.REPORT_MOUSE_POSITION if motion else 0))
    scr.timeout(LOOP_WAIT_MS)
    scr.keypad(True)


def mouse_buttons(right: bool) -> int:
    """The mouse events asked for: presses and releases of the left button, and of the right one when `right`. The
    releases are asked for so that ncurses reports and drops each one at once instead of keeping it back."""
    left = curses.BUTTON1_PRESSED | curses.BUTTON1_RELEASED
    return left | (curses.BUTTON3_PRESSED | curses.BUTTON3_RELEASED if right else 0)


# xterm's mode 1002: the terminal (tmux, for its pane) also reports the pointer moving while a button is held, in
# the encoding already asked for. ncurses 6.0 asks only for mode 1000 (X10 codes with the panes' screen-256color;
# SGR with a terminfo that has "1006;1000": XM), never for 1002, but decodes such moves in both encodings as
# REPORT_MOUSE_POSITION (tried in a pseudo terminal). Mode 1003 (every move, no button) is never asked for: ncurses 6.0 reads its SGR
# code 35 as a release.
DRAG_REPORTS_ON, DRAG_REPORTS_OFF = b"\x1b[?1002h", b"\x1b[?1002l"


def report_drags(scr: "curses.window", on: bool, fd: int = 1) -> None:
    """Ask the terminal for moves with a button held (mode 1002), or stop them. After the refresh: ncurses sends its
    own mouse mode from its buffer at the first refresh, and a 1000 after the 1002 would turn the moves off again
    (curses.putp is no good: its bytes wait in another buffer until the program ends). Resetting 1000 at the end
    (ncurses' endwin) turns 1002 off as well (tmux and Ghostty: any of 9, 1000, 1002, 1003 reset means no
    tracking); `on` False says it once more first."""
    try:
        scr.refresh()
        os.write(fd, DRAG_REPORTS_ON if on else DRAG_REPORTS_OFF)
    except (OSError, curses.error):
        pass


def wait_key(scr: "curses.window", win: Path, seen: Tuple[int, ...], last_round: float) -> Optional[int]:
    """The next key or click; -1 as soon as a round is due without one (round_due: a pick or the tabs changed, or
    ROUND_SECONDS went by since `last_round`); None when the pane was closed (terminal_gone)."""
    while True:
        key = scr.getch()  # at most LOOP_WAIT_MS
        if key != -1:
            return key
        if terminal_gone():
            return None
        if round_due(pick_stamp(win), seen, time.monotonic(), last_round):
            return -1


def terminal_gone() -> bool:
    """True when the pane was closed and this program was not ended by the hangup signal (it can be switched off
    by whoever started us): the loop must end then, not spin on a keyboard that returns at once."""
    try:
        os.write(1, b"")  # nothing is written; on macOS only a write still tells that the terminal is gone
        return False
    except OSError:
        return True


def dot_attr(status: str) -> int:
    pair = STATUS_COLOR.get(status, 0)
    return curses.color_pair(pair) if pair else curses.A_DIM


def read_click() -> Optional[Tuple[int, int]]:
    """(x, y) of a left press, else None (a release, or nothing)."""
    mouse = read_mouse()
    return (mouse[0], mouse[1]) if mouse and mouse[2] == 1 else None


def read_mouse() -> Optional[Tuple[int, int, int]]:
    """(x, y, button) of a left (1) or right (3) press, else None. Only presses act: a release is no new click (it
    must not close the menu or the list of keys that its own press opened), and neither is a move."""
    event = read_mouse_event()
    if event is None or event[2] not in ("press", "right"):
        return None
    return (event[0], event[1], 1 if event[2] == "press" else 3)


def read_mouse_event() -> Optional[Tuple[int, int, str]]:
    """(x, y, what) of the mouse event ncurses has: what is "press" (left), "right" (a right press), "release" (of
    either button) or "motion" (the pointer moved with a button held); None for anything else."""
    try:
        _, x, y, _, buttons = curses.getmouse()
    except curses.error:
        return None
    if buttons & curses.REPORT_MOUSE_POSITION:  # first: a move carries no button bits of its own
        return (x, y, "motion")
    if buttons & curses.BUTTON1_PRESSED:
        return (x, y, "press")
    if buttons & curses.BUTTON3_PRESSED:
        return (x, y, "right")
    if buttons & (curses.BUTTON1_RELEASED | curses.BUTTON3_RELEASED):
        return (x, y, "release")
    return None


def mouse_route(what: str, dragging: bool, quiet: bool = False) -> str:
    """What the sidebar does with a mouse event (read_mouse_event's `what`, "" for none). "press": a press, acted on
    (and a drag that still ran is dropped). While the separator is dragged: "follow" for a move (the line goes
    along), "end" for the release (the line stays there). Else releases and moves are "drop": the press already
    acted, and they keep the notice, the menu and the list of keys.

    `quiet`: the drag got no event for DRAG_IDLE. A move then is "lost": most likely the press of a new click after
    the drag's release got lost (ncurses 6.0, still thinking the button is held, reads that press as a move, in X10
    and SGR alike), so the drag is dropped instead of putting the line where that click went."""
    if what in ("press", "right"):
        return "press"
    if dragging and what == "motion":
        return "lost" if quiet else "follow"
    if dragging and what == "release":
        return "end"
    return "drop"


@dataclass
class Notice:
    """One line about the last action (a failed n, s, m, +, rename or delete). It goes after NOTICE_SECONDS or at the
    next key, and is kept apart from the `hc ls` error, which the background refresh sets and clears."""

    text: str = ""
    bad: bool = True
    until: float = 0.0
    lines: int = 1  # lines it may wrap onto (the keychain warning's whole text); else cut to one

    def say(self, text: str, bad: bool = True, lines: int = 1) -> None:
        self.text, self.bad, self.until, self.lines = text, bad, time.monotonic() + NOTICE_SECONDS, lines

    def clear(self) -> None:
        self.text = ""

    def current(self) -> str:
        if self.text and time.monotonic() > self.until:
            self.text = ""
        return self.text


@dataclass
class Prompt:
    """A question above the sidebar's last line. kind: "space" (new space), "move" (an agent to a space), "rename"
    (`key` in names.json, `own` the name that removes the rename), "rig_target" and "rig_name" (add a server; `data`
    holds the target), "delete" (`data`: the group key or terminal address, then the addresses that end; `accept`:
    what may be typed to confirm), "forget" (`data`: the server's key and machine). `ask` is the question's last part,
    which stays on screen when the rest is cut."""

    kind: str
    title: str
    text: str = ""
    address: str = ""
    key: str = ""
    own: str = ""
    ask: str = ""
    accept: Tuple[str, ...] = ()
    data: Tuple[str, ...] = ()
    by_mouse: bool = False  # opened from a right-click menu: a click in another pane cancels it


@dataclass
class Menu:
    """The open action menu: the row it belongs to, its entries, the selected one. `by_mouse`: opened with a right
    click, so it takes clicks only (keys typed then were meant for the terminal: a key closes it)."""

    item: Item
    title: str
    entries: List[Entry]
    selected: int = 0
    by_mouse: bool = False


@dataclass
class TabMenu:
    """A tab's open menu (a right click): the tab's address, its drawn name (with the account mark), the entries. It
    takes clicks only: a key closes it."""

    address: str
    label: str
    entries: List[Entry]


def autoopen_enabled() -> bool:
    return os.environ.get("MMINI_AUTOOPEN", "1") != "0"


# ---------------------------------------------------------------------------------------------------------------
# Engine: the data side. The sidebar is built on it; the tab bar runs one itself while its window has no sidebar.
# ---------------------------------------------------------------------------------------------------------------
class Engine:
    """Polls `hc ls` / `hc get` and keeps the current group, last.json and the tab snapshot (tabs.json) in step
    with the data and the shown target. Nothing here draws."""

    def __init__(self, state: Path = STATE, win: Path = WINDOW) -> None:
        self.state = state
        self.win = win
        self.terms: List[Term] = []
        self.machines: List[Machine] = []  # from `hc machine ls`: servers without terminals show too
        self.infos: Dict[str, Info] = {}  # per address, from `hc get`
        self.info_time = 0.0  # when all of them were last fetched
        self.error = ""  # the last `hc ls` failure
        self.version = 0
        self.lock = threading.Lock()  # terms, infos, error, version
        self.refreshing = threading.Lock()  # one refresh at a time, so an older answer never replaces a newer one
        self.loaded = threading.Event()
        self.wake = threading.Event()
        self.stopped = threading.Event()  # stop(): the tab bar's engine when a sidebar has come (back)
        self.full_due = False
        self.cache: Tuple[Tuple[int, int, bool], List[Group], List[Group]] = ((-1, -1, False), [], [])
        self.cur = read_text(state / "group")  # current group key
        self.last = read_last(state)
        self.written: Tuple[object, ...] = ()  # what the last snapshot was written for (sync)
        self.written_at = 0.0
        self.seen: Tuple[str, str] = ("", "")  # (shown address, key of its group) at the last sync
        self.names: Dict[str, str] = {}  # names.json as groups() last read it
        self.title = NO_TITLE  # the window title for the shown terminal, at the last sync
        self.title_written: Tuple[str, str] = ("", "")  # (address, title) last written to the file "title"
        self.rigs_all: List[Group] = []  # every server, also while the section is hidden ("needs you" lists them)
        self.seen_turns: Dict[str, int] = {}  # seen.json (needs_you), read again when the file changed
        self.seen_stamp = -1
        # The extras (the sidebar only, extras_forever): the keychain check and the dev servers, with when they were
        # last asked (None: not yet), and r asking for both at once.
        # They belong to one home machine (extras_home): when another machine becomes home, both start over. Not run
        # before a listing came back (listed): a failed first `hc ls` says nothing about which machine is home.
        self.keychain = "unknown"
        self.keychain_at: Optional[float] = None
        self.keychain_fails = 0  # failed checks in a row (keychain_due waits longer after each)
        self.devs: List[DevServer] = []
        self.devs_at: Optional[float] = None
        self.extras_home: Optional[str] = None
        self.listed = False
        self.keychain_asked = False  # r
        self.devs_asked = False  # r, or the dev servers shown again
        self.extras_wake = threading.Event()

    def refresh_once(self, full: bool = False, also: Sequence[str] = ()) -> None:
        """`hc ls`, `hc machine ls`, then `hc get` for the home machine's terminals and the Claude Code terminals of
        other machines (their label "account") that are new (all of them when `full` or every INFO_SECONDS, plus
        `also`). A failed get keeps what was known; a new terminal then stays on
        the folder rules until the next full round. A failed machine list keeps the last one, without a word: the
        terminals are what matters."""
        with self.refreshing:
            try:
                terms: Optional[List[Term]] = parse(run_hc("ls", "--json"))
                error = ""
            except Exception as exc:  # noqa: BLE001 - shown as one red line
                terms, error = None, describe_error(exc)
            try:
                machines: Optional[List[Machine]] = parse_machines(run_hc("machine", "ls", "--json"))
            except Exception:  # noqa: BLE001
                machines = None
            with self.lock:
                infos = dict(self.infos)
            if terms is not None:
                home = home_machine(terms, self.first(machines))
                # the home machine's terminals (space, parent, account), and Claude Code anywhere else (its account)
                wanted = [t.address for t in terms if t.machine == home or t.agent == CLAUDE_AGENT]
                now = time.monotonic()
                full = full or now - self.info_time >= INFO_SECONDS
                fetch = [a for a in wanted if full or a not in infos or a in also]
                for address, info in fetch_infos(fetch).items():
                    info = info if info is not None else infos.get(address, Info())
                    # off the home machine only the account counts: no space, and ending() keeps to known parents
                    infos[address] = info if machine_of(address) == home else Info(account=info.account)
                infos = {a: infos[a] for a in wanted if a in infos}
                if full:
                    self.info_time = now
            with self.lock:
                if terms is not None:
                    self.terms, self.infos, self.listed = terms, infos, True
                if machines is not None:
                    self.machines = machines
                self.error = error
                self.version += 1
        self.loaded.set()

    def refresh_forever(self) -> None:
        poke = self.win / "poke"
        while not self.stopped.is_set():
            seen = mtime(poke)  # read before the listing: a poke that arrives during it starts the next one
            with self.lock:
                full, self.full_due = self.full_due, False
            try:
                self.refresh_once(full)
            except Exception as exc:  # noqa: BLE001 - this thread must never end
                with self.lock:
                    self.error = describe_error(exc)
                    self.version += 1
                self.loaded.set()
            end = time.monotonic() + REFRESH_SECONDS
            while time.monotonic() < end and mtime(poke) == seen and not self.wake.is_set():
                self.wake.wait(0.2)
            self.wake.clear()
            if (self.win / "poke.full").exists():  # poke_engine(full=True)
                try:
                    (self.win / "poke.full").unlink()
                except OSError:
                    pass
                with self.lock:
                    self.full_due = True

    def servers_shown(self) -> bool:
        """Is the servers section shown (the shared file "servers", read each time: a few bytes, and another
        window may switch it)?"""
        return read_servers_shown(self.state)

    def groups(self) -> Tuple[List[Group], List[Group]]:
        """(spaces, servers), built again when the data, names.json or the servers switch changed (also in another
        window). While the servers section is hidden there are no servers: no row, no tab bar and no current group
        of one, and no agent of one in the list; a current group that was a server falls back (sync)."""
        with self.lock:
            version, terms, infos, machines = self.version, self.terms, self.infos, self.machines
        shown = self.servers_shown()
        stamp = (version, mtime(self.state / "names.json"), shown)
        if self.cache[0] != stamp:
            self.names = read_names(self.state)
            marks = account_marks(terms, infos, machines)
            spaces, rigs = build_groups(terms, first_machine(machines), infos, machines, self.names, marks)
            self.cache, self.rigs_all = (stamp, spaces, rigs if shown else []), rigs
        return self.cache[1], self.cache[2]

    def title_for(self, address: str) -> str:
        """The window title for `address` (shown_title), from every machine and terminal, so a hidden servers
        section changes nothing. names.json as groups() last read it."""
        with self.lock:
            terms, machines = self.terms, self.machines
        return shown_title(address, terms, machines, self.names)

    def server_names(self, group: Optional[Group]) -> Dict[str, str]:
        """machine -> server_name for the machines of `group` (for the snapshot)."""
        if group is None:
            return {}
        with self.lock:
            machines = self.machines
        return {m: server_name(m, machines, self.names) for m in {group.machine} | {t.machine for t in group.terms}}

    def all_terms(self) -> List[Term]:
        """Every listed terminal once (a home machine's terminal is in its space and in the home server's row)."""
        return list({t.address: t for g in self.everything() for t in g.terms}.values())

    def everything(self) -> List[Group]:
        spaces, rigs = self.groups()
        return spaces + rigs

    def find_group(self, key: str) -> Optional[Group]:
        return next((g for g in self.everything() if g.key == key), None)

    def group_of(self, address: str) -> Optional[Group]:
        return next((g for g in self.everything() if any(t.address == address for t in g.terms)), None)

    def set_current(self, key: str) -> None:
        if key != self.cur or read_text(self.state / "group") != key:
            self.cur = key
            write_atomic(self.state / "group", key + "\n")

    def sync(self) -> None:
        """Keep the current group, last.json and the tab snapshot in step with the data and the shown target (the
        tab bar changes the target too)."""
        spaces, rigs = self.groups()
        everything = spaces + rigs
        shown = current_target(self.win)
        holder = self.group_of(shown) if shown else None
        if holder:
            if self.seen == (shown, self.cur) and holder.key != self.cur:
                self.set_current(holder.key)  # the shown terminal changed space (label, folder): the tabs follow it
            if self.last.get(holder.key) != shown:
                self.last = remember(holder.key, shown, self.state)
            # a home machine's terminal is in its space and in the home server's row: that row remembers it too
            current = self.find_group(self.cur) if holder.key != self.cur else None
            if current is not None and self.last.get(current.key) != shown and any(
                    t.address == shown for t in current.terms):
                self.last = remember(current.key, shown, self.state)
        self.seen = (shown, holder.key if holder else "")
        self.look(shown)
        if everything and self.cur not in [g.key for g in everything]:
            self.set_current(fallback_group(spaces, rigs, holder.key if holder else ""))
        self.title = self.title_for(shown)
        if (shown, self.title) != self.title_written:  # only on a change: view.sh reads it before each attach
            write_title(shown, self.title, self.win)
            self.title_written = (shown, self.title)
        # the data and names.json as groups() last built them (a rename counts), the shown terminal and its title
        stamp = (self.cache[0], self.cur, shown, self.title)
        now = time.monotonic()
        if stamp != self.written or now - self.written_at > SNAPSHOT_BEAT:
            group = self.find_group(self.cur)
            with self.lock:
                infos = dict(self.infos)
            write_snapshot(group, self.win, servers=self.server_names(group), shown=shown, shown_title=self.title,
                           everything=self.all_terms(), infos=infos)
            self.written, self.written_at = stamp, now

    def seen_now(self) -> Dict[str, int]:
        """seen.json (shared by all windows: one person uses them all, a look in any window counts), read again only
        when the file changed."""
        stamp = mtime(self.state / "seen.json")
        if stamp != self.seen_stamp:
            self.seen_stamp, self.seen_turns = stamp, read_seen(self.state)
        return self.seen_turns

    def look(self, shown: str) -> None:
        """The shown terminal counts as looked at (mark_seen); seen.json is written only when that changed it."""
        with self.lock:
            terms = self.terms
        seen = self.seen_now()
        after = mark_seen(seen, terms, shown) if terms else seen
        if after != seen:
            try:
                write_seen(after, self.state)
            except OSError:
                return
            self.seen_turns, self.seen_stamp = after, mtime(self.state / "seen.json")

    def needs(self, shown: str) -> List[Term]:
        """The "needs you" rows (needs_you) from every terminal, also of a hidden server, as the groups draw them
        (display name, account mark)."""
        self.groups()
        terms = {t.address: t for g in self.cache[1] + self.rigs_all for t in g.terms}
        return needs_you(list(terms.values()), self.seen_now(), shown)

    def first(self, machines: Optional[Sequence[Machine]] = None) -> str:
        """The home machine's hc name (first_machine) from `machines`, else the last machine list."""
        if machines is None:
            with self.lock:
                machines = self.machines
        return first_machine(machines)

    def home(self) -> str:
        with self.lock:
            return home_machine(self.terms, first_machine(self.machines))

    def refresh_extras(self, now: float, runner: Runner = None) -> None:
        """The keychain check and the dev servers, each when due (keychain_due, dev_due) or asked for (r; the dev
        servers also when shown again), on the home machine (its core: `hc exec`). Not before a listing came back:
        only that says which machine is home. When another machine has become home (a server listed after a start
        without it), both are dropped and asked again at once: an answer of this Mac is never kept for a server.
        The dev servers only while their section is not hidden."""
        with self.lock:
            if not self.listed:
                return
            home = home_machine(self.terms, first_machine(self.machines))
            if home != self.extras_home:
                self.extras_home = home
                self.keychain, self.keychain_at, self.keychain_fails = "unknown", None, 0
                self.devs, self.devs_at = [], None
            keychain_asked, self.keychain_asked = self.keychain_asked, False
            devs_asked, self.devs_asked = self.devs_asked, False
            keychain, keychain_at, fails, devs_at = self.keychain, self.keychain_at, self.keychain_fails, self.devs_at
        if keychain_enabled() and (keychain_asked or keychain_due(keychain_at, keychain, now, fails)):
            state = check_keychain(home, runner)
            with self.lock:  # home changed meanwhile: the next call drops this answer
                self.keychain, self.keychain_at = state, now
                self.keychain_fails = fails + 1 if state == "failed" else 0
        if read_devs_shown(self.state) and (devs_asked or dev_due(devs_at, now)):
            devs = fetch_dev_servers(home, runner)
            with self.lock:
                self.devs_at = now
                if devs is not None:
                    self.devs = devs

    def extras_forever(self) -> None:
        """The sidebar's thread for refresh_extras: apart from the listing, so a slow machine never holds it up."""
        while not self.stopped.is_set():
            try:
                self.refresh_extras(time.monotonic())
            except Exception:  # noqa: BLE001 - this thread must never end
                pass
            self.extras_wake.wait(1.0)
            self.extras_wake.clear()

    def show_group(self, key: str, address: str = "") -> bool:
        """Make `key` the current group and show `address`, else its remembered terminal, else its first tab. False
        when the group is gone or empty (nothing changes then)."""
        group = self.find_group(key)
        if not group or not group.terms:
            return False
        addresses = [t.address for t in group.terms]
        if address not in addresses:
            address = self.last.get(key, "")
        target = address if address in addresses else addresses[0]
        self.set_current(key)
        show(target, self.win, self.title_for(target))
        self.sync()
        return True

    def begin(self, autoopen: bool) -> None:
        """A start, once the first listing is in (at most 8 s): pick the current group and show its terminal. A view
        that already shows a terminal (the sidebar came back, the tab bar took over) keeps it, and that terminal's
        group becomes the current one. With MMINI_AUTOOPEN=0 nothing is shown, and a target an earlier run left
        behind (not on screen) is cleared, so nothing carries the marker."""
        self.loaded.wait(timeout=8.0)
        if self.stopped.is_set():
            return
        attached = bool(current_target(self.win)) and bool(attach_pid(self.win))
        if not autoopen and current_target(self.win) and not attached:
            write_atomic(self.win / "target", "\n")
        spaces, rigs = self.groups()
        shown = current_target(self.win)
        holder = self.group_of(shown) if shown else None
        keep = attached and holder is not None
        if holder is not None and keep:
            self.set_current(holder.key)
        elif (spaces or rigs) and self.cur not in [g.key for g in spaces + rigs]:  # no saved group, or it has gone
            self.set_current(fallback_group(spaces, rigs, holder.key if holder else ""))
        self.sync()
        if autoopen and self.cur and not keep:
            self.show_group(self.cur)  # show only: the keyboard stays where it is

    def drive(self, autoopen: bool, beat: float = ENGINE_BEAT) -> None:
        """The tab bar's engine thread: a start (begin), then a sync every `beat` seconds until stop(). It never
        ends on an error: the tab bar would then wait for a snapshot that never comes."""
        try:
            self.begin(autoopen)
        except Exception:  # noqa: BLE001
            pass
        while not self.stopped.is_set():
            try:
                self.sync()
            except Exception:  # noqa: BLE001
                pass
            self.stopped.wait(beat)

    def stop(self) -> None:
        self.stopped.set()
        self.wake.set()


# ---------------------------------------------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class Sections:
    """What the sidebar draws now: the groups, the switches of the servers and agents sections, the "needs you"
    rows and the dev servers (empty while hidden or none). items() and plan() keep the two in one order."""

    spaces: List[Group]
    rigs: List[Group]
    servers: bool = False
    needs: List[Term] = field(default_factory=list)
    devs: List[DevServer] = field(default_factory=list)
    agents: bool = True

    def items(self) -> List[Item]:
        return selectable_items(self.spaces, self.rigs, self.servers, self.needs, self.devs, self.agents)

    def plan(self, height: int, cursor: int = 0, compact: bool = False,
             rule: Optional[int] = None) -> List[Tuple[int, Row]]:
        return plan_sidebar(self.spaces, self.rigs, height, cursor, compact, self.servers, rule, self.needs, self.devs,
                            self.agents)


class Sidebar(Engine):
    def __init__(self, stdscr: "curses.window", state: Path = STATE, win: Path = WINDOW) -> None:
        super().__init__(state, win)
        self.s = Screen(stdscr)
        self.cursor: Optional[Item] = None
        self.cursor_pos = 0
        self.body_height = 0
        self.rows: Dict[int, Item] = {}  # screen line -> the item drawn there, for clicks
        self.pane_title = PaneTitle()  # this pane's window title (the engine's self.title)
        self.prompt: Optional[Prompt] = None
        self.notice = Notice()
        self.sized_at = -1  # the width the pane had after its last sizing (refit); -1: not sized yet
        self.window_width = -1  # the window's width at refit's last look (-1: none yet)
        self.sized_h = -1  # the pane's height at refit's last look (a zoom's end changes it)
        self.zoom_look: Optional[float] = None  # when refit last found the view zoomed (None: it was not)
        # "open" or "strip"; "hidden" never runs a sidebar (main ends it before it draws), so it counts as open
        self.mode = "strip" if read_sidebar_state(state) == "strip" else "open"
        self.open_width = read_open_width(state)  # the open width: the last dragged one, else MMINI_WIDTH
        self.strip_width = 0  # a width the strip was dragged to, kept until the next state change (0 = none)
        self.aimed = -1  # the width the last sizing aimed at (-1: none yet)
        self.arrow_y = -1  # the line of "‹" (fold, or hide in the strip), for clicks
        self.open_y = -1  # the strip's line of "›" (open), for clicks
        self.menu: Optional[Menu] = None  # the open action menu
        self.menu_at: Optional[MenuBox] = None  # where it was drawn, for clicks
        # Presses are dropped until then (MOUSE_QUIET): the second press of a double click never acts on the row
        # under a menu that the first one closed.
        self.mouse_quiet = 0.0
        self.forward_until = 0.0  # until then keys go on to the view (FORWARD_GRACE after a key closed a menu)
        self.help = False  # the list of keys ("?") is drawn over the sidebar
        self.help_x = -1  # the column of the dim "?" on the "‹" line, for clicks (-1: not drawn)
        # The separator between the upper part and the agents: where it was drawn (-1: not drawn), the line asked of
        # plan_sidebar at the last draw (None: automatic), and the moved one from the shared file "split" (read
        # again only when the file changed).
        self.rule_y = -1
        self.rule_plan: Optional[int] = None
        self.split: Optional[Tuple[int, int]] = None
        self.split_stamp = -1
        # A drag of the separator: the line it is held on (None: no drag) and the line it started from. A press on
        # it that moved nothing (rule_pressed, a time; None: none) and a second one within MOUSE_QUIET: the automatic
        # layout. None, not 0: time.monotonic() may start near 0 when the program starts.
        self.drag_y: Optional[int] = None
        self.drag_from = -1
        self.drag_seen = 0.0  # the drag's last mouse event (mouse_route's `quiet`)
        self.rule_pressed: Optional[float] = None
        self.rule_at = 0  # the separator's line for [ and ], also where the automatic layout dropped it (rule_line)
        self.keychain_y = -1  # the line of the keychain warning, for clicks (-1: not drawn)

    # cursor ----------------------------------------------------------------------------------------------------
    def sections(self) -> Sections:
        """The sections as they are drawn now (the shared switches, the shown terminal, the extras)."""
        spaces, rigs = self.groups()
        with self.lock:
            devs = list(self.devs)
        return Sections(spaces, rigs, self.servers_shown(), self.needs(current_target(self.win)),
                        devs if read_devs_shown(self.state) else [], read_agents_shown(self.state))

    def items(self) -> List[Item]:
        return self.sections().items()

    def cursor_index(self, items: Optional[Sequence[Item]] = None) -> int:
        """Where the cursor is now: its row; for an agent that changed space, that agent; else the same position."""
        items = self.items() if items is None else items
        cursor = self.cursor
        if cursor is None:
            cursor = Item("group", self.cur, "")
        if cursor in items:
            return list(items).index(cursor)
        if cursor.kind == "agent":
            for i, item in enumerate(items):
                if item.kind == "agent" and item.address == cursor.address:
                    return i
        return max(0, min(len(items) - 1, self.cursor_pos))

    def placed(self, index: int) -> bool:
        plan = self.sections().plan(self.body_height, index, self.mode == "strip", self.rule_plan)
        return any(row.item == index for _, row in plan)

    def move(self, step: int) -> None:
        """Move the cursor, but never onto a row the screen has no line for."""
        items = self.items()
        if items:
            index = max(0, min(len(items) - 1, self.cursor_index(items) + step))
            if self.placed(index):
                self.cursor, self.cursor_pos = items[index], index

    def cursor_item(self) -> Optional[Item]:
        items = self.items()
        return items[self.cursor_index(items)] if items else None

    # actions ---------------------------------------------------------------------------------------------------
    def open_group(self, key: str, address: str = "", focus: bool = True) -> None:
        """show_group, then the keyboard to the view."""
        if self.show_group(key, address) and focus:
            focus_view(self.win)

    def activate(self, item: Item) -> None:
        """Enter or a click on a row. An agent is looked up again: it may have changed space or ended meanwhile. A
        "+" row asks its question; a server without terminals only says so."""
        if item.kind in ("agent", "needs"):
            holder = self.group_of(item.address)
            if holder:
                self.open_group(holder.key, item.address)
            elif item.kind == "needs" and any(t.address == item.address for g in self.rigs_all for t in g.terms):
                self.show_alone(item.address)  # on a server whose section is hidden: no group to show it in
            else:
                self.notice.say("that terminal has ended")
        elif item.kind == "dev":
            self.browse(item.address)
        elif item.kind == "new_space":
            self.ask_new_space()
        elif item.kind == "add_rig":
            self.ask_add_rig()
        else:
            group = self.find_group(item.group)
            if group is not None and not group.terms:
                self.notice.say(f"no terminals on {group.shown}: n starts one", bad=False)
                return
            self.open_group(item.group)

    def show_alone(self, address: str) -> None:
        """Show a terminal that no drawn group holds (a server of a hidden section): the view shows it, the tab bar
        keeps its group."""
        show(address, self.win, self.title_for(address))
        self.sync()
        focus_view(self.win)

    def browse(self, port: str) -> None:
        """Enter or a click on a dev server: open it in this Mac's browser, at the home machine's host."""
        with self.lock:
            machines = self.machines
        host = home_host(machines, self.home())
        try:
            opened = open_url(host, int(port))
        except ValueError as exc:
            self.notice.say(f"open: {exc}")
            return
        url = f"http://{host}:{port}/"
        self.notice.say(("opened " if opened else "not opened here: ") + url, bad=False, lines=NOTICE_LINES)

    def show_unlock(self) -> None:
        """A click on the keychain warning: the whole warning in the notice, and the view shows the home machine's
        terminal "unlock", or a new shell of that name there. Nothing is typed into it: the unlock is done there
        (security unlock-keychain asks for the password itself)."""
        self.notice.say(KEYCHAIN_NOTICE, lines=NOTICE_LINES)
        home = self.home()
        with self.lock:
            terms = self.terms
        found = next((t for t in terms if t.machine == home and t.name == UNLOCK_NAME), None)
        if found is not None:
            holder = self.group_of(found.address)
            if holder is not None:
                self.open_group(holder.key, found.address)
            else:
                self.show_alone(found.address)
            return
        try:
            address = new_shell(home, "", self.win, name=UNLOCK_NAME)
            self.refresh_once(also=(address,))
        except Exception as exc:  # noqa: BLE001
            self.notice.say("unlock: " + describe_error(exc))
            return
        holder = self.group_of(address)
        if holder is not None:
            self.open_group(holder.key, address)
        else:
            self.show_alone(address)

    def busy(self, text: str) -> None:
        self.notice.say(text, bad=False)
        self.draw()

    def start_shell(self, machine: str, cwd: str, space: str, to_cursor: bool = False, here: str = "") -> None:
        """A new shell, then show it. `here`: the group it was started from; that group shows it when it holds it
        (the home server's row holds every terminal of its spaces), else the group it landed in."""
        self.busy("starting a shell…")
        try:
            address = new_shell(machine, cwd, self.win, space)
            self.refresh_once(also=(address,))
        except Exception as exc:  # noqa: BLE001
            self.notice.say("new: " + describe_error(exc))
            return
        self.notice.clear()
        holder = self.group_of(address)
        started_in = self.find_group(here) if here else None
        if started_in is not None and any(t.address == address for t in started_in.terms):
            holder = started_in
        if not holder:
            self.notice.say(f"started {address}, not listed yet", bad=False)
            return
        self.open_group(holder.key, address)
        if to_cursor:
            self.cursor = Item("group", holder.key, "")

    def new_in_cursor_group(self) -> None:
        """n: a new shell in the space or server under the cursor. On a "+" row: that row's own question."""
        item = self.cursor_item()
        if item is not None and item.kind in ("new_space", "add_rig"):
            self.activate(item)
            return
        group = self.find_group(item.group) if item else None
        if group:
            self.start_shell(group.machine, group.cwd, group.name if group.kind == "space" else "", here=group.key)

    def ask_new_space(self) -> None:
        self.expand()
        self.prompt = Prompt("space", "new space: name or folder")

    def ask_add_rig(self) -> None:
        self.expand()
        self.prompt = Prompt("rig_target", "add server: ssh target (me@host, or a Host of ~/.ssh/config)")

    def rig_target_given(self, text: str) -> None:
        """The first question of "+ add server": checked here, so a bad target never gets as far as hc."""
        target = text.strip()
        if not target:
            return
        if not valid_rig_target(target):
            self.notice.say("not a usable ssh target")
            return
        self.prompt = Prompt("rig_name", f"name for {target} (empty = host)", data=(target,))

    def add_rig(self, target: str, text: str) -> None:
        """The second question: start the terminal that adds the server, show it, and give it the keyboard."""
        name = text.strip()
        if name and not valid_rig_name(name):
            self.notice.say("name: a-z 0-9 _ -, a letter first, 32 at most")
            return
        self.busy("starting add-server…")
        try:
            address = start_add_rig(target, name, self.win)
            self.refresh_once(also=(address,))
        except Exception as exc:  # noqa: BLE001
            self.notice.say("add server: " + describe_error(exc))
            return
        self.notice.clear()
        holder = self.group_of(address)
        if not holder:
            self.notice.say(f"started {address}, not listed yet", bad=False)
            return
        self.open_group(holder.key, address)
        self.cursor = Item("agent", holder.key, address) if any(
            t.address == address and t.is_agent for t in holder.terms) else Item("group", holder.key, "")

    # rename ----------------------------------------------------------------------------------------------------
    def term_of(self, address: str) -> Optional[Term]:
        """The terminal at `address` as drawn, also on a server whose section is hidden (a "needs you" row)."""
        self.groups()
        return next((t for g in self.cache[1] + self.rigs_all for t in g.terms if t.address == address), None)

    def ask_rename(self, item: Optional[Item]) -> None:
        """e: rename the space, server or agent under the cursor. The current shown name is filled in; enter keeps
        what is there, an empty line or the own name removes the rename, esc cancels."""
        self.expand()
        group = self.find_group(item.group) if item else None
        if item is not None and item.kind in ("agent", "needs"):
            term = self.term_of(item.address)
            if term is None:
                self.notice.say("that terminal has ended")
                return
            self.prompt = Prompt("rename", f"rename {term.shown} to:", term.shown, key="term:" + term.address,
                                 own=term.label)
        elif item is not None and item.kind == "group" and group is not None:
            self.prompt = Prompt("rename", f"rename {group.shown} to:", group.shown, key=group.key, own=group.own)
        else:
            self.notice.say("e: cursor on a space, server or agent first")

    def rename(self, prompt: Prompt) -> None:
        """Keep the new display name in names.json (see plan_rename). Nothing of hc changes."""
        if prompt.key.startswith("term:"):
            taken = [t.shown for t in self.all_terms() if "term:" + t.address != prompt.key]
        else:
            taken = [g.shown for g in self.everything() if g.key != prompt.key]
        what, value = plan_rename(prompt.text, prompt.own, taken)
        if what == "bad":
            self.notice.say("rename: " + value)
            return
        try:
            change_names({prompt.key: value}, self.state)
        except OSError as exc:
            self.notice.say("rename: " + describe_error(exc))

    # delete ----------------------------------------------------------------------------------------------------
    def ask_delete(self, item: Optional[Item]) -> None:
        """d: delete the space, forget the server, or end the agent under the cursor, each after its name was
        typed. The terminals listed in the question are the ones that end, nothing else."""
        self.expand()
        group = self.find_group(item.group) if item else None
        with self.lock:
            infos = dict(self.infos)
        everything = self.all_terms()
        if item is not None and item.kind in ("agent", "needs"):
            term = self.term_of(item.address)
            if term is None:
                self.notice.say("that terminal has ended")
                return
            ends = ending([term], everything, infos)
            asked = term.title or term.name or term.address
            self.prompt = Prompt("delete", f"end {term.shown}? {ends_text(ends)}.", ask=f"type {asked} to confirm:",
                                 accept=tuple(dict.fromkeys(a for a in (asked, term.name, term.address) if a)),
                                 data=(term.address,) + tuple(t.address for t in ends))
        elif item is not None and item.kind == "group" and group is not None and group.kind == "space":
            ends = ending(group.terms, everything, infos)
            self.prompt = Prompt("delete", f"delete space {group.shown}? {ends_text(ends)}.",
                                 ask=f"type {group.shown} to confirm:",
                                 accept=tuple(dict.fromkeys((group.shown, group.name))),
                                 data=(group.key,) + tuple(t.address for t in ends))
        elif item is not None and item.kind == "group" and group is not None:
            if group.machine in (LOCAL, self.first()) or group.home:
                self.notice.say(f"d: {group.shown} cannot be removed")
                return
            self.prompt = Prompt("forget", f"forget server {group.shown}? its terminals keep running there.",
                                 ask=f"type {group.shown} to confirm:",
                                 accept=tuple(dict.fromkeys(a for a in (group.shown, group.alias, group.name) if a)),
                                 data=(group.key, group.machine))
        else:
            self.notice.say("d: cursor on a space, server or agent first")

    def confirmed(self, prompt: Prompt) -> None:
        """The typed name matched: do it, then move the cursor (and, when what was shown has gone, the view) to a
        neighbour (after_delete)."""
        before = self.items()
        index = self.cursor_index(before)
        shown = current_target(self.win)
        problem = ""
        if prompt.kind == "forget":
            key, machine = prompt.data
            self.busy(f"forgetting {self.find_group(key).shown if self.find_group(key) else machine}…")
            try:
                forget_rig(machine)
            except Exception as exc:  # noqa: BLE001
                self.notice.say("forget: " + describe_error(exc))
                return
            gone = [t.address for t in self.all_terms() if t.machine == machine]
            names = {key: ""}
        else:
            what, addresses = prompt.data[0], prompt.data[1:]
            self.busy(f"ending {len(addresses)} terminal{'s' if len(addresses) != 1 else ''}…")
            failed: List[str] = []
            for address in addresses:
                try:
                    end_terminal(address)
                except Exception as exc:  # noqa: BLE001 - the others still end
                    failed.append(f"{address}: {describe_error(exc)}")
            gone = list(addresses)
            names = {"term:" + a: "" for a in addresses}
            if what.startswith("space:"):
                names[what] = ""
            if failed:
                problem = f"end: {len(failed)} of {len(addresses)} failed, " + failed[0]
        try:
            change_names(names, self.state)  # an address or a space may come back later: it starts unnamed
        except OSError:
            pass
        self.refresh_once(full=True)
        self.notice.clear()
        if problem:
            self.notice.say(problem)
        self.after_delete(before, index, shown, gone)

    def after_delete(self, before: Sequence[Item], index: int, shown: str, gone: Sequence[str]) -> None:
        """The cursor goes to the neighbour of the row that went (see neighbour); without one the existing fall-back
        rule (fallback_group) picks the group. When the current group has gone, the neighbour group becomes the
        current one; when the shown terminal has gone, the view shows that group's terminal, or nothing."""
        after = self.items()
        spaces, rigs = self.groups()
        target = neighbour(before, index, after)
        if target is None:
            key = fallback_group(spaces, rigs)
            target = Item("group", key, "") if key else None
        self.cursor = target
        if target is not None:
            self.cursor_pos = after.index(target) if target in after else 0
        keys = [g.key for g in spaces + rigs]
        if self.cur not in keys and target is not None and target.group:
            self.set_current(target.group)
        if shown and shown in gone and not (self.cur in keys and self.show_group(self.cur)):
            show("", self.win, NO_TITLE)
        self.sync()

    def new_space(self, text: str) -> None:
        """The "s" prompt: a folder or a space name on the home machine (see plan_new_space)."""
        kind, value = classify_space_input(text)
        if kind == "empty":
            return
        if kind == "bad":
            self.notice.say(value)
            return
        with self.lock:
            terms, machines = self.terms, self.machines
        home = home_machine(terms, first_machine(machines))
        self.busy("looking on " + home + "…")
        exists: Optional[bool]
        try:
            home_dir, exists = probe_folder(home, probe_arg(kind, value))
        except Exception:  # noqa: BLE001 - go on without the answer
            guess = home_dir_from_cwds(t.cwd for t in terms if t.machine == home)
            home_dir, exists = (str(Path.home()) if home == LOCAL else guess), None
        cwd, label, problem = plan_new_space(kind, value, home_dir, exists)
        if problem:
            self.notice.say(problem)
            return
        self.start_shell(home, cwd, label, to_cursor=True)

    def ask_move(self) -> None:
        item = self.cursor_item()
        term = next((t for g in self.everything() for t in g.terms if item and t.address == item.address), None)
        if not item or item.kind != "agent" or term is None:
            self.notice.say("m: cursor on an agent first")
        elif not item.group.startswith("space:"):
            self.notice.say("m: servers have no spaces")
        else:
            self.prompt = Prompt("move", f"move {term.label} to space:", address=item.address)

    def move_agent(self, address: str, text: str) -> None:
        """The "m" prompt: set the terminal's "space" label; the refresh then shows it in its new space."""
        name = text.strip()
        if not name:
            return
        if not valid_space_name(name):
            self.notice.say("not a usable space name")
            return
        try:
            run_hc("label", address, "space=" + name)
            self.refresh_once(also=(address,))
        except Exception as exc:  # noqa: BLE001
            self.notice.say("move: " + describe_error(exc))

    def submit(self, prompt: Prompt) -> None:
        if prompt.kind == "space":
            self.new_space(prompt.text)
        elif prompt.kind == "move":
            self.move_agent(prompt.address, prompt.text)
        elif prompt.kind == "rename":
            self.rename(prompt)
        elif prompt.kind == "rig_target":
            self.rig_target_given(prompt.text)
        elif prompt.kind == "rig_name":
            self.add_rig(prompt.data[0], prompt.text)
        elif prompt.kind in ("delete", "forget"):
            if confirm_matches(prompt.text, prompt.accept):
                self.confirmed(prompt)
            else:
                self.notice.say("cancelled: the name did not match", bad=False)

    # the action menu -------------------------------------------------------------------------------------------
    def open_menu(self, item: Optional[Item], by_mouse: bool = False) -> None:
        """a, or a right click on a row (`by_mouse`): the menu of that row. The strip opens first (the menu needs the
        room)."""
        if item is None:
            return
        self.expand()
        group = self.find_group(item.group) if item.group else None
        if item.kind in ("agent", "needs"):
            term = self.term_of(item.address)
            title = term.shown if term else item.address
        elif item.kind in PLUS_TEXT:
            title = PLUS_TEXT[item.kind]
        elif item.kind == "dev":
            title = ":" + item.address
        else:
            title = group.shown if group else item.group
        self.cursor = item
        self.menu = Menu(item, title, menu_entries(item, group, self.first(), self.servers_shown(),
                                                   read_agents_shown(self.state), read_devs_shown(self.state)),
                         by_mouse=by_mouse)

    def run_entry(self, entry: Entry, item: Item) -> None:
        """What a menu entry does: the same as its direct key."""
        self.menu = None
        self.cursor = item
        if entry.action == "open":
            self.activate(item)
        elif entry.action == "new":
            self.new_in_cursor_group()
        elif entry.action == "rename":
            self.ask_rename(item)
        elif entry.action == "move":
            self.ask_move()
        elif entry.action in ("delete", "forget", "end"):
            self.ask_delete(item)
        elif entry.action == "new_space":
            self.ask_new_space()
        elif entry.action == "add_rig":
            self.ask_add_rig()
        elif entry.action == "servers":
            self.toggle_servers()
        elif entry.action == "agents":
            self.toggle_agents()
        elif entry.action == "devs":
            self.toggle_devs()
        elif entry.action == "browse":
            self.activate(item)

    def toggle_servers(self) -> None:
        """v, or "Show servers" / "Hide servers" in a menu: the servers section comes or goes, for every window (the
        shared file "servers"). Hidden, nothing of it is drawn; a current group that was a server falls back with
        the usual rule (fallback_group), and the view then shows that group's terminal, as nothing on screen could
        reach the one it showed. Shown, the cursor goes to the first server."""
        shown = not self.servers_shown()
        try:
            write_servers_shown(shown, self.state)
        except OSError as exc:
            self.notice.say("servers: " + describe_error(exc))
            return
        spaces, rigs = self.groups()
        if shown:
            self.cursor = Item("group", rigs[0].key, "") if rigs else ADD_RIG
            self.notice.say(f"servers shown ({SERVERS_KEY} hides them)", bad=False)
            return
        self.notice.say(f"servers hidden ({SERVERS_KEY} shows them)", bad=False)
        if self.cursor is not None and (self.cursor.kind == "add_rig" or self.cursor.group.startswith("rig:")):
            self.cursor = None  # back to the current group's row
        if self.cur not in [g.key for g in spaces]:
            target = current_target(self.win)
            holder = self.group_of(target) if target else None
            key = fallback_group(spaces, [], holder.key if holder else "")
            if holder is not None and holder.key == key:
                self.set_current(key)  # the shown terminal is in a space: that space, the view stays
            elif key and not self.show_group(key):
                self.set_current(key)
        self.sync()

    def toggle_agents(self) -> None:
        """g, or "Show agents" / "Hide agents" in a menu: the agents section comes or goes, for every window (the
        shared file "agents"). Hidden, its heading, rows and the separator are not drawn, and the upper part gets the
        lines; a cursor on an agent goes back to the current group's row, a drag of the separator is dropped. A moved
        separator is kept for when they come back."""
        shown = not read_agents_shown(self.state)
        try:
            write_agents_shown(shown, self.state)
        except OSError as exc:
            self.notice.say("agents: " + describe_error(exc))
            return
        if not shown:
            self.drag_y = None
            if self.cursor is not None and self.cursor.kind == "agent":
                self.cursor = None
        self.notice.say(f"agents {'shown' if shown else 'hidden'} ({AGENTS_KEY} {'hides' if shown else 'shows'} them)",
                        bad=False)

    def toggle_devs(self) -> None:
        """w, or "Show dev servers" / "Hide dev servers" in a menu: the dev servers come or go, for every window (the
        shared file "devservers"). Shown, they are asked for at once; a section without one is not drawn."""
        shown = not read_devs_shown(self.state)
        try:
            write_devs_shown(shown, self.state)
        except OSError as exc:
            self.notice.say("dev servers: " + describe_error(exc))
            return
        if shown:
            with self.lock:
                self.devs_asked = True  # only the dev servers: the keychain keeps its own schedule
            self.extras_wake.set()
            with self.lock:
                none = not self.devs
            self.notice.say(f"dev servers shown ({DEVS_KEY} hides them)" + (": none found yet" if none else ""),
                            bad=False)
            return
        if self.cursor is not None and self.cursor.kind == "dev":
            self.cursor = None
        self.notice.say(f"dev servers hidden ({DEVS_KEY} shows them)", bad=False)

    def handle_menu(self, key: int, click: Optional[Tuple[int, int, int]] = None) -> None:
        """Keys and presses while the menu is open: up/down (k/j), enter, a direct key shown in it, esc or a to
        close; a press on an entry runs it, a press outside closes the menu (and does nothing else). The release of
        the press that opened it never gets here (on_key drops releases). A menu opened with a right click takes
        presses only: any key closes it and gives the keyboard back to the view."""
        menu = self.menu
        if menu is None:
            return
        if menu.by_mouse and key != curses.KEY_MOUSE:  # typed after a right click: meant for the terminal
            self.menu = None
            send_keys_to_view([key] + drain_keys(self.s.scr), self.win)
            self.forward_until = time.monotonic() + FORWARD_GRACE
            return
        if key in (curses.KEY_UP, ord("k")):
            menu.selected = max(0, menu.selected - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            menu.selected = min(len(menu.entries) - 1, menu.selected + 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            self.run_entry(menu.entries[menu.selected], menu.item)
        elif key in (27, ord(MENU_KEY), ord("q")):
            self.menu = None
        elif key == curses.KEY_MOUSE:
            click = click if click is not None else read_mouse()
            if click is None or time.monotonic() < self.mouse_quiet:
                return
            self.mouse_quiet = time.monotonic() + MOUSE_QUIET
            what, index = menu_hit(self.menu_at, click[0], click[1]) if self.menu_at else ("outside", -1)
            if what == "entry":
                menu.selected = index
                self.run_entry(menu.entries[index], menu.item)
                if menu.by_mouse and self.prompt is not None:
                    self.prompt.by_mouse = True
            elif what == "outside":
                self.menu = None
            if menu.by_mouse and self.menu is None and self.prompt is None and not self.help:
                focus_view(self.win)  # a right-click menu gone without a question: the keyboard back to the view
        elif 32 <= key < 127:
            entry = next((e for e in menu.entries if e.key == chr(key).lower()), None)
            if entry is not None:
                self.run_entry(entry, menu.item)

    def set_mode(self, mode: str) -> None:
        """The open sidebar or the folded strip. Kept for the next start (all windows); the pane sizes itself for
        the new mode (refit; not outside tmux, nor with MMINI_AUTOSIZE=0)."""
        if mode == self.mode:
            return
        self.mode = mode
        self.strip_width = 0  # a dragged strip width lasts until the next state change
        if mode == "open":
            self.open_width = read_open_width(self.state)  # dragged in another window meanwhile, perhaps
        write_sidebar_state(mode, self.state)
        self.refit()

    def step(self) -> bool:
        """c, or a click on "‹": one state smaller (next_sidebar_state). False when that is hidden: the program
        ends (hide)."""
        after = next_sidebar_state(self.mode)
        if after == "hidden":
            return self.hide()
        self.set_mode(after)
        return True

    def hide(self) -> bool:
        """q, or c in the strip: the sidebar goes. "hidden" is written first, so this window's tab bar takes over the
        engine at once (tab_engine_wanted) and the next start begins hidden; then the keyboard goes to the view,
        sidebar.pid goes, and False ends the program: tmux closes its pane, and the tab bar and the view take its
        columns. tabs.json stays: the tab bar draws it until its own engine writes the next one."""
        write_sidebar_state("hidden", self.state)
        focus_view(self.win)
        remove_own_pid(self.win)
        return False

    def expand(self) -> None:
        """The prompts and their messages need room: open the strip first."""
        self.set_mode("open")

    def zoom(self) -> None:
        text = zoom_view(self.win)
        if text:
            self.notice.say(text)

    # drawing ---------------------------------------------------------------------------------------------------
    def draw(self) -> None:
        s = self.s
        s.scr.erase()
        height, width = s.size()
        sections = self.sections()
        spaces, rigs = sections.spaces, sections.rigs
        if not sections.agents:
            self.drag_y = None  # hidden meanwhile (in another window too): no separator to hold
        with self.lock:
            error, loaded, locked, machines = self.error, self.loaded.is_set(), self.keychain == "locked", self.machines
        notice = self.notice.current()
        compact = self.mode == "strip"
        message = bool(notice or error)
        said = prompt_lines(notice, "", max(1, width - 1), self.notice.lines) if notice and self.notice.lines > 1 \
            else [notice]
        asked: List[str] = []
        if self.prompt is not None:  # the whole question, wrapped; the frame then says how much of it fits
            asked = prompt_lines(self.prompt.title, self.prompt.ask, max(1, width - 1), PROMPT_TITLE_MAX)
        self.body_height, self.arrow_y, self.open_y, reserved = sidebar_frame(
            height, message, self.prompt is not None, compact, max(1, len(asked)), locked, max(1, len(said)))
        self.keychain_y = keychain_line(height, compact, locked)
        items = sections.items()
        cursor = self.cursor_index(items)
        # held but not moved yet: drawn where it was (an automatic line below the limit would jump up a row)
        dragged = self.drag_y is not None and self.drag_y != self.drag_from
        self.rule_plan = rule = self.drag_y if dragged else split_row(self.read_split(), height)
        plan = sections.plan(self.body_height, cursor, compact, rule)
        if items and not any(row.item == cursor for _, row in plan):  # no line for that row: back to its group
            group = Item("group", items[cursor].group, "")
            cursor = items.index(group) if group in items else 0
            plan = sections.plan(self.body_height, cursor, compact, rule)
        self.rule_y = next((y for y, row in plan if row.kind == "rule"), -1)
        self.rule_at = rule_line(plan, self.body_height)
        if items:
            self.cursor, self.cursor_pos = items[cursor], cursor
        shown = current_target(self.win)
        home = self.home()
        self.rows = {}
        if not spaces and not rigs:
            s.put(1, 1, "no terminals" if loaded else "loading…", curses.A_DIM)
        for y, row in plan:
            if compact:
                self.draw_compact(y, row, width, cursor, shown)
                if row.kind in ("group", "agent", "plus", "needs", "dev"):
                    self.rows[y] = items[row.item]
            elif row.kind == "needs" and row.term:
                t = row.term
                attr = curses.A_REVERSE if row.item == cursor else 0
                s.fill(y, attr)
                server = server_name(t.machine, machines, self.names) if t.machine != home else ""
                s.put(y, 1, "●", attr | dot_attr(t.status))
                s.put(y, 3, needs_text(t.shown, t.mark, server, max(1, width - 5 - len(t.status))), attr)
                s.put(y, max(4, width - 1 - len(t.status)), t.status, attr | curses.A_DIM)
                self.rows[y] = items[row.item]
            elif row.kind == "dev" and row.dev:
                attr = curses.A_REVERSE if row.item == cursor else 0
                s.fill(y, attr)
                label = clip(row.dev.label, width - 5)
                port = len(f":{row.dev.port}")
                s.put(y, 3, label[:port], attr)
                s.put(y, 3 + port, label[port:], attr | curses.A_DIM)
                self.rows[y] = items[row.item]
            elif row.kind == "plus":
                attr = curses.A_REVERSE if row.item == cursor else 0
                s.fill(y, attr)
                s.put(y, 1, "+", attr | curses.A_BOLD)
                s.put(y, 3, clip(PLUS_TEXT[row.text], width - 5), attr | curses.A_DIM)
                self.rows[y] = items[row.item]
            elif row.kind == "header":
                s.put(y, 1, row.text, curses.A_DIM)
            elif row.kind == "rule":
                s.put(y, 0, "─" * (width - 1), self.rule_attr())
            elif row.kind == "agents":
                s.put(y, 1, "agents", curses.A_DIM)
                s.put(y, max(8, width - 9), "grouped", curses.A_DIM)
            elif row.kind == "more":
                s.put(y, 2, row.text, curses.A_DIM)
            elif row.kind == "agent_group" and row.group:
                s.put(y, 1, clip(f"{row.group.shown} · {row.count}", width - 3))
            elif row.kind == "group" and row.group:
                g = row.group
                attr = curses.A_REVERSE if row.item == cursor else 0
                s.fill(y, attr)
                mark = g.key == self.cur
                status = summary_status(g.terms)
                s.put(y, 0, "›" if mark else " ", attr | curses.A_BOLD)
                s.put(y, 1, "●" if status else "○", attr | dot_attr(status))
                s.put(y, 3, clip(g.shown, width - 5), attr | (curses.A_BOLD if mark else 0))
                self.rows[y] = items[row.item]
            elif row.kind == "agent" and row.term:
                t = row.term
                attr = curses.A_REVERSE if row.item == cursor else 0
                s.fill(y, attr)
                mark = t.address == shown
                s.put(y, 0, "›" if mark else " ", attr | curses.A_BOLD)
                s.put(y, 2, "●" if t.status else "○", attr | dot_attr(t.status))
                s.put(y, 4, with_mark(t.shown, t.mark, max(1, width - 6 - len(t.status))),
                      attr | (curses.A_BOLD if mark else 0))
                s.put(y, max(5, width - 1 - len(t.status)), t.status, attr | curses.A_DIM)
                self.rows[y] = items[row.item]
        # the keychain warning just above the arrow lines, the prompt or message just above that
        if self.keychain_y >= 0:
            s.put(self.keychain_y, 0, keychain_text(width - 1), curses.color_pair(1) | curses.A_BOLD)
        last = next((y for y in (self.keychain_y, self.open_y, self.arrow_y) if y >= 0), height)
        if self.prompt and reserved:
            question = prompt_lines(self.prompt.title, self.prompt.ask, max(1, width - 1), reserved - 1)
            for i, line in enumerate(question):
                s.put(last - reserved + i, 0, line, curses.A_DIM)
            typed = "> " + self.prompt.text + "_"
            s.put(last - 1, 0, typed if len(typed) < width else "…" + typed[-(width - 2):], curses.A_BOLD)
        elif notice and reserved:
            lines = said if len(said) <= reserved else prompt_lines(notice, "", max(1, width - 1), reserved)
            for i, line in enumerate(lines):
                s.put(last - len(lines) + i, 0, clip(line, width - 1),
                      curses.color_pair(1) if self.notice.bad else curses.A_DIM)
        elif error and reserved:
            s.put(last - 1, 0, clip("hc: " + error, width - 1), curses.color_pair(1))
        for y, label in ((self.arrow_y, fold_label(self.mode, width - 1)), (self.open_y, open_label(width - 1))):
            if y >= 0:
                at = len(label) - len(label.lstrip())  # the arrow itself, bold; the word dim
                s.put(y, 0, label, curses.A_DIM)
                s.put(y, at, label[at], curses.A_BOLD)
        # a dim "?" at the end of the "‹" line of the open sidebar: the only sign of the list of keys on screen (the
        # strip has no room for it; "?" works there too)
        self.help_x = -1
        if self.arrow_y >= 0 and not compact:
            self.help_x = help_column(fold_label(self.mode, width - 1), width)
        if self.help_x >= 0:
            s.put(self.arrow_y, self.help_x, HELP_KEY, curses.A_DIM)
        self.draw_menu(height, width, items)
        if self.help:
            self.draw_help(height, width)
        s.scr.refresh()

    def draw_help(self, height: int, width: int) -> None:
        """The list of keys ("?") over the whole pane; nothing under it can be clicked until it closes."""
        self.s.scr.erase()
        self.rows, self.menu_at, self.help_x = {}, None, -1
        for y, line in enumerate(help_lines(width - 1, height)):
            self.s.put(y, 0, line, curses.A_DIM if y == 0 else 0)

    def draw_menu(self, height: int, width: int, items: Sequence[Item]) -> None:
        """The open menu, over everything else, next to its row (menu_box). A menu whose row has gone (ended, deleted
        in another window) closes."""
        self.menu_at = None
        menu = self.menu
        if menu is None:
            return
        if menu.item not in items:
            self.menu = None
            return
        row_y = next((y for y, item in self.rows.items() if item == menu.item), 0)
        # the arrow lines and the keychain warning stay readable
        room = next((y for y in (self.keychain_y, self.open_y, self.arrow_y) if y > row_y), height)
        # a menu opened with a right click takes clicks only: no keys shown, nothing selected
        entries = [replace(e, key="") for e in menu.entries] if menu.by_mouse else menu.entries
        selected = -1 if menu.by_mouse else menu.selected
        box = menu_box(row_y, len(entries), max(0, selected), room, width, menu_width(entries))
        if box is None:
            return
        self.menu_at = box
        for y, text, chosen in menu_lines(menu.title, entries, box, selected):
            self.s.put(y, box.left, text, curses.A_REVERSE if chosen else 0)

    def draw_compact(self, y: int, row: Row, width: int, cursor: int, shown: str) -> None:
        """One line of the folded strip, for any width from 3 columns: marker, status dot and as much of the name as
        fits (Screen.put cuts it at the pane's edge, by columns), no status words, titles cut the same way."""
        s = self.s
        if row.kind in ("header", "agents"):
            s.put(y, 0, row.text, curses.A_DIM)
        elif row.kind == "rule":
            s.put(y, 0, "─" * (width - 1), self.rule_attr())
        elif row.kind == "more":
            s.put(y, 0, row.text if len(row.text) < width else f"+{row.count}", curses.A_DIM)
        elif row.kind == "agent_group" and row.group:
            s.put(y, 0, f"{row.group.shown} · {row.count}")
        elif row.kind == "group" and row.group:
            g = row.group
            self.compact_item(y, g.key == self.cur, summary_status(g.terms), g.shown, row.item == cursor)
        elif row.kind == "agent" and row.term:
            t = row.term
            name = with_mark(t.shown, t.mark, width - 3) if t.mark else t.shown  # the mark stays at the edge
            self.compact_item(y, t.address == shown, t.status, name, row.item == cursor)
        elif row.kind == "needs" and row.term:
            t = row.term
            name = with_mark(t.shown, t.mark, width - 3) if t.mark else t.shown
            self.compact_item(y, False, t.status, name, row.item == cursor)
        elif row.kind == "dev" and row.dev:
            attr = curses.A_REVERSE if row.item == cursor else 0
            s.fill(y, attr)
            s.put(y, 1, f":{row.dev.port}", attr)
        elif row.kind == "plus":  # "+" only: the strip has no room for the words
            attr = curses.A_REVERSE if row.item == cursor else 0
            s.fill(y, attr)
            s.put(y, 1, "+", attr | curses.A_BOLD)

    def compact_item(self, y: int, mark: bool, status: str, name: str, at_cursor: bool) -> None:
        attr = curses.A_REVERSE if at_cursor else 0
        self.s.fill(y, attr)
        self.s.put(y, 0, "›" if mark else " ", attr | curses.A_BOLD)
        self.s.put(y, 1, "●" if status else "○", attr | dot_attr(status))
        self.s.put(y, 2, name, attr | (curses.A_BOLD if mark else 0))

    # the separator ---------------------------------------------------------------------------------------------
    def read_split(self) -> Optional[Tuple[int, int]]:
        """The moved separator from the shared file "split" (another window may move it too). One stat per draw;
        read again only when the file changed (also when it went: the automatic layout)."""
        stamp = mtime(self.state / "split")
        if stamp != self.split_stamp:
            self.split_stamp, self.split = stamp, read_split(self.state)
        return self.split

    def rule_attr(self) -> int:
        """Dim; bold while it is dragged, so a drag shows also where the terminal sends no moves."""
        return curses.A_BOLD if self.drag_y is not None else curses.A_DIM

    def set_split(self, row: int) -> None:
        """Keep the separator on `row` of this pane's height (write_split), for every window."""
        height = self.s.size()[0]
        try:
            write_split(row, height, self.state)
        except OSError as exc:
            self.notice.say("separator: " + describe_error(exc))
            return
        self.split, self.split_stamp = (row, height), mtime(self.state / "split")

    def reset_split(self) -> None:
        """A double press on the separator: the automatic layout again (the file "split" goes)."""
        try:
            clear_split(self.state)
        except OSError as exc:
            self.notice.say("separator: " + describe_error(exc))
            return
        self.split, self.split_stamp = None, 0
        self.notice.say("separator: automatic again", bad=False)

    def press_rule(self) -> None:
        """A left press on the separator: a drag starts (its release puts the line, end_drag); the second press of a
        double press (within MOUSE_QUIET of one that moved nothing) gives the automatic layout back instead."""
        now = time.monotonic()
        if self.rule_pressed is not None and now - self.rule_pressed < MOUSE_QUIET:
            self.rule_pressed = None
            self.reset_split()
            return
        self.rule_pressed = now
        if clamp_rule(self.rule_y, self.body_height) is not None:
            # from the line as drawn, not clamped: an automatic line below the limit, let go one row up, moved
            self.drag_y = self.drag_from = self.rule_y
            self.drag_seen = now

    def drag_to(self, y: int) -> Optional[int]:
        """The line a drag held at row y puts the separator on: back on its own line there, else clamped."""
        return self.drag_from if y == self.drag_from else clamp_rule(y, self.body_height)

    def follow_drag(self, y: int) -> None:
        """The pointer moved with the button held: the separator goes along (drawn only; written at the release)."""
        self.drag_seen = time.monotonic()
        to = self.drag_to(y)
        if to is not None:
            self.drag_y = to

    def end_drag(self, y: int) -> None:
        """The release that ends a drag: the separator stays on that line (clamped: a release above or below the
        pane lands at the limit) and is kept (the file "split"). On the line it started from nothing is written: a
        click on the separator moves nothing, and a quick second one is a double press (press_rule)."""
        start, self.drag_y = self.drag_from, None
        to = self.drag_to(y)
        if to is None or to == start:
            return
        self.rule_pressed = None
        self.set_split(to)

    def nudge_rule(self, step: int) -> None:
        """[ or - (step -1), ] or = (+1): the separator one line up or down (rule_step), kept as a drag is. From
        rule_line's line: also right when the automatic layout dropped the line for a crowded upper part."""
        if not read_agents_shown(self.state):
            self.notice.say(f"agents hidden ({AGENTS_KEY} shows them)", bad=False)
            return
        current = self.rule_at
        to = rule_step(current, step, self.body_height)
        if to is None:
            self.notice.say("no room to move the separator", bad=False)
        elif to != current:
            self.set_split(to)

    # size ------------------------------------------------------------------------------------------------------
    def width_goal(self) -> int:
        """The width of the current mode: open, the width its divider was last dragged to, else MMINI_WIDTH; the
        folded strip, a width it was dragged to since the last state change, else MMINI_NARROW."""
        if self.mode == "strip":
            return self.strip_width or NARROW
        return self.open_width

    def keep_width(self, width: int) -> None:
        """The divider was dragged to `width` columns: that is the width now, never undone by refit. Open, it is also
        kept for the next sidebar of every window (the file "width"); in the strip only until the next state change.
        A width that cannot be written is still kept here."""
        if self.mode == "open":
            self.open_width = max(WIDTH_LIMITS[0], min(WIDTH_LIMITS[1], width))
            try:
                write_open_width(width, self.state)
            except OSError:
                pass
        else:
            self.strip_width = width
        self.sized_at = width
        # dragged past the open width's limits (10-200): the next round sizes the pane to the limit it is kept at
        self.aimed = self.width_goal() if self.width_goal() == width else -1

    def refit(self) -> None:
        """Size the pane for the current mode, exactly (tmux). Nothing to do while curses shows the width the last
        sizing left and the mode wants no other (no tmux call then). Else it looks at tmux's own sizes (curses learns
        them up to 250 ms late, so its width is never taken for a drag): a new mode (c, o) or a window of another
        width (tmux spreads that over the panes, the sidebar first) gets the mode's width, capped so the view keeps
        MIN_VIEW columns; a new width of this pane in a window of the same width is a dragged divider, kept
        (keep_width), at every step of the drag. Never while the view is zoomed (a resize would end the zoom):
        looked at again every ZOOM_LOOK seconds until it is not."""
        if not autosize_enabled():
            return
        goal = self.width_goal()
        height, width = self.s.size()
        if goal == self.aimed and width == self.sized_at and height == self.sized_h:
            return
        now = time.monotonic()
        if self.zoom_look is not None and now - self.zoom_look < ZOOM_LOOK:
            return
        pane = own_pane()
        look = window_look(pane) if pane else None
        if look is None:
            return
        self.zoom_look = now if look.zoomed else None
        if look.zoomed:
            # no drag can happen while zoomed: the first look after it sizes the pane (the window width is
            # forgotten); until curses shows another size (the zoom's end does) nothing is asked again
            self.window_width, self.sized_at, self.sized_h = -1, width, height
            return
        self.sized_h = look.pane_height
        if goal == self.aimed and look.width == self.window_width:
            if look.pane_width != self.sized_at:
                self.keep_width(look.pane_width)  # the divider was dragged
            return  # else curses has not caught up with tmux yet: nothing changed
        self.aimed = goal
        after = size_pane(pane, cols=max(1, min(goal, look.width - 1 - MIN_VIEW)))
        if after is not None:
            self.sized_at, self.window_width = after.pane_width, after.width
        else:
            self.sized_at, self.window_width = look.pane_width, look.width

    def watch_menu(self) -> None:
        """A menu opened with a right click, and any question, go once another pane has the keyboard (a click
        there): they would stay on screen, with no key to reach them. One tmux call a round, only while such a menu
        or a question is open."""
        mouse_menu = self.menu is not None and self.menu.by_mouse
        pane = own_pane()
        if (mouse_menu or self.prompt is not None) and pane and pane_active(pane) is False:
            self.menu = None  # a question too: with the keyboard elsewhere it can no longer be answered
            if self.prompt is not None:
                self.prompt = None
                self.notice.say("cancelled", bad=False)

    # loop ------------------------------------------------------------------------------------------------------
    def handle_prompt(self, key: int) -> None:
        prompt = self.prompt
        if prompt is None:
            return
        if key in (curses.KEY_ENTER, 10, 13):
            self.prompt = None
            self.submit(prompt)
        elif key == 27:
            self.prompt = None
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            prompt.text = prompt.text[:-1]
        elif key == 21:  # ctrl+U: clear the line (a rename starts with the current name filled in)
            prompt.text = ""
        elif 32 <= key < 127 and len(prompt.text) < 200:
            prompt.text += chr(key)

    def handle_key(self, key: int, click: Optional[Tuple[int, int, int]] = None) -> bool:
        """One key or press (`click`: the press on_key read already); False to quit (the sidebar was hidden: see
        hide)."""
        if key in (ord("q"), ord("Q")):
            return self.hide()  # the pane would close anyway: quitting is hiding
        if key in (curses.KEY_UP, ord("k")):
            self.move(-1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.move(1)
        elif key in (curses.KEY_ENTER, 10, 13):
            item = self.cursor_item()
            if item:
                self.activate(item)
        elif key in (ord("n"), ord("N")):
            self.new_in_cursor_group()
        elif key in (ord("s"), ord("S")):
            self.ask_new_space()
        elif key in (ord(MENU_KEY), ord(MENU_KEY.upper())):
            self.open_menu(self.cursor_item())
        elif key in (ord("e"), ord("E")):
            self.ask_rename(self.cursor_item())
        elif key in (ord("d"), ord("D")):
            self.ask_delete(self.cursor_item())
        elif key in (ord("m"), ord("M")):
            self.expand()
            self.ask_move()
        elif key in (ord("c"), ord("C")):
            return self.step()
        elif key in (ord("o"), ord("O")):
            self.set_mode("open")
        elif key in (ord("z"), ord("Z")):
            self.zoom()
        elif key in (ord("r"), ord("R")):
            with self.lock:
                self.full_due = self.keychain_asked = self.devs_asked = True
            self.wake.set()
            self.extras_wake.set()
        elif key in (ord(SERVERS_KEY), ord(SERVERS_KEY.upper())):
            self.toggle_servers()
        elif key in (ord(AGENTS_KEY), ord(AGENTS_KEY.upper())):
            self.toggle_agents()
        elif key in (ord(DEVS_KEY), ord(DEVS_KEY.upper())):
            self.toggle_devs()
        elif key == ord(HELP_KEY):
            self.open_help()
        elif key in RULE_KEYS:
            self.nudge_rule(RULE_KEYS[key])
        elif key == curses.KEY_MOUSE:
            click = click if click is not None else read_mouse()
            if click is None or time.monotonic() < self.mouse_quiet:
                return True
            # the item that was drawn on that line, not a new lookup
            what, item = sidebar_hit(click[1], self.arrow_y, self.open_y, self.rows, click[0], self.help_x,
                                     self.rule_y, self.keychain_y)
            if click[2] == 3:  # the right button: the row's menu (none on the separator: it is no row)
                if item:
                    self.mouse_quiet = time.monotonic() + MOUSE_QUIET
                    self.open_menu(item, by_mouse=True)
                return True
            if what == "keychain":
                self.mouse_quiet = time.monotonic() + MOUSE_QUIET  # a double click opens one terminal
                self.show_unlock()
                return True
            if what == "rule":
                self.press_rule()
                return True
            if what == "help":
                self.mouse_quiet = time.monotonic() + MOUSE_QUIET  # a double click must not close it again
                self.open_help()
                return True
            if what in ("step", "open"):  # a double click must not fold and then hide (or open, then fold)
                self.mouse_quiet = time.monotonic() + MOUSE_QUIET
            if what == "step":
                return self.step()
            if what == "open":
                self.set_mode("open")
            elif item:
                self.cursor = item
                self.activate(item)
        return True

    def open_help(self) -> None:
        """?: the list of keys over the sidebar (the strip opens first: the list needs the room)."""
        self.expand()
        self.menu = None
        self.help = True

    def close_help(self, key: int, click: Optional[Tuple[int, int, int]] = None) -> None:
        """Any key or press closes the list of keys, and does nothing else. A release (no press) does not count,
        neither does a second press within MOUSE_QUIET of the one that opened it (a double click)."""
        if key == curses.KEY_MOUSE:
            click = click if click is not None else read_mouse()
            if click is None or time.monotonic() < self.mouse_quiet:
                return
            self.mouse_quiet = time.monotonic() + MOUSE_QUIET
        self.help = False

    def on_key(self, key: int) -> bool:
        """What the loop got from getch (not -1); False to quit. A size change is no key: it keeps the notice and,
        unlike a key or a click, does not show that the pane can be seen again after a zoom."""
        if key == curses.KEY_RESIZE:
            return True  # the next round's refit looks at the new size
        click = None
        if key == curses.KEY_MOUSE:
            event = read_mouse_event()
            quiet = time.monotonic() - self.drag_seen >= DRAG_IDLE
            route = mouse_route(event[2] if event else "", self.drag_y is not None, quiet)
            if route == "lost":  # a new click, read as a move: the drag goes, the line back; the click is dropped
                self.drag_y = None
                return True
            if event is not None and route == "follow":
                self.follow_drag(event[1])
                return True
            if event is not None and route == "end":
                self.end_drag(event[1])
                return True
            if event is None or route == "drop":
                return True  # a button let go, or a move: the press already acted; notice, menu and key list stay
            click = (event[0], event[1], 1 if event[2] == "press" else 3)
        # a key or a right press ends a drag, the separator back where it was. So would a left press, but ncurses
        # 6.0 reads one during a drag as a move ("lost" above, after DRAG_IDLE)
        if key == 27:
            pasted = read_paste(self.s.scr)
            if pasted is not None:
                self.drag_y = None
                self.pasted(pasted)
                return True
        if click is None and self.menu is None and self.prompt is None and time.monotonic() < self.forward_until:
            # typed on after a key closed a right-click menu: meant for the terminal too
            self.forward_until = time.monotonic() + FORWARD_GRACE
            send_keys_to_view([key] + drain_keys(self.s.scr), self.win)
            return True
        if self.drag_y is not None:
            self.drag_y = None
            if key == 27:
                return True  # esc only ends the drag
        self.notice.clear()
        if self.help:
            self.close_help(key, click)
            return True
        if self.prompt is not None and click is not None and time.monotonic() >= self.mouse_quiet:
            self.prompt = None  # a press elsewhere: the question goes, the press acts (not a double click's second)
            self.notice.say("cancelled", bad=False)
        if self.prompt is not None:
            self.handle_prompt(key)
            return True
        if self.menu is not None:
            self.handle_menu(key, click)
            return True
        return self.handle_key(key, click)

    def pasted(self, text: str) -> None:
        """A paste reached the sidebar (a file dropped while it had the keyboard): into the open question, else to
        the terminal in the view."""
        if self.prompt is not None:
            self.prompt.text = (self.prompt.text + prompt_text(text))[:200]
            return
        self.menu = None
        if not paste_to_view(text, self.win):
            self.notice.say("the paste could not be passed on to the terminal")

    def run(self) -> None:
        setup_curses(self.s.scr, right=True, motion=True)
        report_drags(self.s.scr, True)  # the separator follows the pointer while it is dragged
        bracketed_paste(True)  # a paste (a dropped file) is told from typing, and goes on to the view
        write_atomic(self.win / "sidebar.pid", f"{os.getpid()}\n")  # first: the tab bar's engine stops on it
        threading.Thread(target=self.refresh_forever, daemon=True).start()
        threading.Thread(target=self.extras_forever, daemon=True).start()
        try:
            self.begin(autoopen_enabled())
            while True:
                seen, last_round = pick_stamp(self.win), time.monotonic()  # before: a pick meanwhile is not missed
                self.sync()
                self.draw()
                self.pane_title.send(self.title)  # after the refresh: curses has written all it holds
                self.refit()
                self.watch_menu()
                key = wait_key(self.s.scr, self.win, seen, last_round)
                if key is None:
                    return
                if key != -1 and not self.on_key(key):
                    return
        finally:
            report_drags(self.s.scr, False)
            bracketed_paste(False)
            remove_own_pid(self.win)  # tabs.json stays: the tab bar takes over from it (tab_engine_wanted)


# ---------------------------------------------------------------------------------------------------------------
# Tab bar
# ---------------------------------------------------------------------------------------------------------------
class TabBar:
    def __init__(self, stdscr: "curses.window", win: Path = WINDOW, state: Path = STATE) -> None:
        self.s = Screen(stdscr)
        self.win = win
        self.state = state
        self.notice = Notice()
        self.layout: Optional[TabLayout] = None
        self.last_plus = float("-inf")  # monotonic() may start near 0: the first click must count
        self.sized_rows = -1  # the height the pane had after its last sizing (refit); -1: not sized yet
        self.rows_aimed = -1  # the height the last sizing aimed at (rows_goal)
        self.zoom_look: Optional[float] = None  # when refit last found the view zoomed (None: it was not)
        self.engine: Optional[Engine] = None  # this tab bar's own engine, while the window has no sidebar
        self.missing_since: Optional[float] = None  # since when no live sidebar was seen (None: one runs)
        self.alone = False  # no sidebar: the engine runs here and "›" is drawn
        self.opening: Optional[float] = None  # after "›": when the sidebar's pane was made (until it runs)
        self.pane_title = PaneTitle()  # this pane's window title (tabs_title)
        self.menu: Optional[TabMenu] = None  # a tab's menu (a right click on it), drawn on the row below the tabs
        self.prompt: Optional[Prompt] = None  # its rename, move or close question, on that row
        self.menu_segs: List[Seg] = []  # the menu's pieces as last drawn (for a click on an entry)
        self.close_cut = False  # Close's question did not fit when last drawn: y does nothing then
        self.forward_until = 0.0  # until then keys go on to the view (FORWARD_GRACE after a key closed a menu)
        self.mouse_quiet = 0.0  # presses until then are a double click's second, dropped while a question opens
        self.asked_again = 0.0  # when Close last asked again (CLOSE_AGAIN)

    def draw(self, snap: Optional[dict], shown: str) -> None:
        s = self.s
        s.scr.erase()
        height, width = s.size()
        notice = self.notice.current()
        lead = 1 if self.alone else 0  # the column of "›"
        self.layout = None
        if snap is None:
            if lead:
                self.layout = TabLayout([Seg(0, 0, "›", "open")], 1)
                s.put(0, 0, "›", curses.A_BOLD)
            s.put(0, 1 + lead, "loading…" if self.alone else "waiting for the sidebar…", curses.A_DIM)
            s.scr.refresh()
            return
        tabs = snap["tabs"]
        addresses = [str(t.get("address", "")) for t in tabs]
        active = addresses.index(shown) if shown in addresses else -1
        tab_rows, hint_row = tab_bar_rows(height)
        bad = self.notice.bad
        if not notice and self.opening is not None:  # from the state, not a notice: the next key would clear that
            notice, bad = "opening the sidebar…", False
        say = curses.color_pair(1) if bad else curses.A_DIM
        if notice and hint_row < 0:  # a one-row pane: the message takes the row for its few seconds
            s.put(0, 1, clip(notice, width - 3), say)
            s.scr.refresh()
            return
        if self.prompt is not None and self.prompt.kind == "close":
            tab_rows = min(tab_rows, TAB_ROWS - 1)  # the rows the bar grows by are the question's (rows_goal)
        layout = layout_tabs([tab_label(t) for t in tabs], active, width - 1 - lead, tab_rows)
        layout = with_opener(layout) if lead else layout
        self.layout = layout
        marked = self.menu.address if self.menu else (self.prompt.address if self.prompt else "")
        for seg in layout.segs:
            if seg.kind == "tab":
                attr = curses.A_REVERSE if seg.index == active else 0
                if marked and tabs[seg.index].get("address") == marked:  # the tab the menu belongs to
                    attr |= curses.A_UNDERLINE | curses.A_BOLD
                status = str(tabs[seg.index].get("status") or "")
                s.put(seg.y, seg.x, seg.text, attr)
                s.put(seg.y, seg.dot_x, "●" if status else "○", attr | dot_attr(status))
            else:
                s.put(seg.y, seg.x, seg.text, curses.A_DIM if seg.kind == "sep" else curses.A_BOLD)
        self.menu_segs = []
        if marked:
            self.draw_tab_menu(layout.rows if layout.rows < hint_row else max(0, hint_row), hint_row, width, lead)
            s.scr.refresh()
            return
        if 0 <= active and layout.rows < hint_row:  # a spare row between the tabs and the hints
            s.put(layout.rows, 1 + lead, clip(tab_info(tabs[active], width - 3 - lead), width - 3 - lead),
                  curses.A_DIM)
        if hint_row >= 0:
            if notice:
                s.put(hint_row, 1 + lead, clip(notice, width - 3 - lead), say)
            else:
                name = str(snap.get("title") or snap.get("name") or "")
                s.put(hint_row, 1 + lead, clip(name, max(1, width - 3 - lead)), curses.A_DIM)
                hint = tab_hint(width - 6 - lead - len(name), self.alone)  # 2 columns between the name and the hint
                if hint:
                    s.put(hint_row, width - 2 - len(glyph(hint)), hint, curses.A_DIM)
        s.scr.refresh()

    def draw_tab_menu(self, y: int, hint_row: int, width: int, lead: int) -> None:
        """The open tab menu, or its question, on row y (the row below the tabs, else the last row), and what the
        keys do on the hint row when that is another row."""
        s = self.s
        x0 = 1 + lead
        room = max(1, width - 2 - x0)
        s.fill(y, 0)  # on a short pane the row may hold tabs
        if self.menu is not None:
            self.menu_segs = [Seg(y, g.x + x0, g.text, g.kind, g.index)
                              for g in tab_menu_segs(self.menu.label, self.menu.entries, room)]
            for g in self.menu_segs:
                s.put(g.y, g.x, g.text, curses.A_BOLD if g.kind == "entry" else curses.A_DIM)
            hint = TAB_MENU_HINT
        elif self.prompt is not None:
            p = self.prompt
            hint = TAB_ASK.get(p.kind, "")
            if p.kind == "close":
                rows = max(1, hint_row - y) if hint_row > y else 1
                lines = wrap_words(p.title, room)
                self.close_cut = len(lines) > rows or (hint_row <= y and len(lines) > 0 and
                                                       text_width(f"{hint} · {p.title}") > room)
                if self.close_cut:
                    lines = lines[:max(1, rows)]
                    hint = "the list is cut: widen the window, or end it in the sidebar · any key cancels"
                for i, line in enumerate(lines if hint_row > y else [f"{hint} · {p.title}"]):
                    s.fill(y + i, 0)
                    s.put(y + i, x0, clip(line, room), curses.A_BOLD)
            else:
                typed = f"{p.title} {p.text}_"
                s.put(y, x0, typed if text_width(typed) <= room else "…" + typed[-max(1, room - 1):], curses.A_BOLD)
        else:
            return
        if 0 <= hint_row != y:
            s.put(hint_row, x0, clip(hint, room), curses.A_DIM)

    def open_tab_menu(self, snap: dict, address: str) -> None:
        """A right click on a tab: its menu (tab_menu_entries), on the row below the tabs."""
        tab = tab_of(snap, address)
        if tab is None:
            return
        self.prompt = None
        self.menu = TabMenu(address, tab_label(tab), tab_menu_entries(str(snap.get("kind") or "")))

    def close_menu(self) -> None:
        """The menu or its question went without an action: the keyboard back to the shown terminal."""
        self.menu = self.prompt = None
        focus_view(self.win)

    def handle_menu(self, key: int, snap: Optional[dict], click: Optional[Tuple[int, int, int]]) -> None:
        """While a tab's menu is open: a press on an entry runs it; a right press on a tab opens that tab's menu;
        any other press closes the menu. A key closes it too, and goes on to the terminal with the keys typed after
        it (they were meant for the terminal; none of them may pick an entry); esc only closes."""
        menu = self.menu
        if key != curses.KEY_MOUSE:  # typed after a right click: meant for the terminal
            self.menu = self.prompt = None
            send_keys_to_view([key] + drain_keys(self.s.scr), self.win)
            self.forward_until = time.monotonic() + FORWARD_GRACE
            return
        if menu is None or snap is None or click is None:
            self.close_menu()
            return
        hit = hit_test(self.layout, click[0], click[1]) if self.layout else None
        index = menu_entry_at([g for g in self.menu_segs if g.y == click[1]], click[0])
        if click[2] == 3 and hit and hit[0] == "tab" and hit[1] < len(snap["tabs"]):
            self.open_tab_menu(snap, str(snap["tabs"][hit[1]]["address"]))
        elif click[2] == 1 and index is not None and index < len(menu.entries):
            self.run_tab_entry(menu.entries[index], snap)
        else:
            self.close_menu()

    def watch_menu(self) -> None:
        """A menu or question goes once another pane has the keyboard (a click there): it would stay on screen, with
        no key to close it. One tmux call a round, only while one is open."""
        pane = own_pane()
        if (self.menu is not None or self.prompt is not None) and pane and pane_active(pane) is False:
            if self.prompt is not None and self.prompt.kind == "close":
                self.notice.say("not closed", bad=False)
            self.menu = self.prompt = None

    def run_tab_entry(self, entry: Entry, snap: dict) -> None:
        """What a tab menu entry does. Rename, move and close ask first, on the menu's row; this pane takes the
        keyboard for the answer."""
        menu = self.menu
        self.menu = None
        tab = tab_of(snap, menu.address) if menu else None
        if menu is None or tab is None:
            self.notice.say("that terminal has ended")
            focus_view(self.win)
            return
        label = str(tab.get("label") or menu.address)
        self.mouse_quiet = time.monotonic() + MOUSE_QUIET
        if entry.action == "new":
            self.plus(snap)
            focus_view(self.win)
            return
        if entry.action == "rename":
            self.prompt = Prompt("rename", f"rename {label} to:", label, address=menu.address,
                                 key="term:" + menu.address, own=str(tab.get("own") or label))
        elif entry.action == "move":
            self.prompt = Prompt("move", f"move {label} to space:", address=menu.address)
        elif entry.action == "close":
            self.prompt = close_question(tab)
        else:
            return
        focus_pane("tabs", self.win)

    def handle_prompt(self, key: int, snap: Optional[dict], shown: str) -> None:
        """Keys while a tab's question is open. Close: CLOSE_YES closes, any other key or a press cancels. Rename and
        move: typed text (plain ASCII), backspace, ctrl+U clears, enter does it, esc or a press cancels."""
        prompt = self.prompt
        if prompt is None:
            return
        if prompt.kind == "close":
            if key not in (ord(CLOSE_YES), ord(CLOSE_YES.upper())) or snap is None:
                self.notice.say("not closed", bad=False)
                self.close_menu()
                return
            tab = tab_of(snap, prompt.address)
            if tab is None:
                self.notice.say("that terminal has ended")
                self.close_menu()
                return
            if self.close_cut or time.monotonic() - self.asked_again < CLOSE_AGAIN:
                return  # the list is not all on screen, or it changed a moment ago: y does nothing yet
            again = close_question(tab)
            if set(again.data) != set(prompt.data):  # what ends changed since the question: ask again
                again.title = "changed: " + again.title
                self.prompt = again
                self.asked_again = time.monotonic()
                return
            self.prompt = None
            self.close_tabs(prompt, snap)
            return
        if key in (curses.KEY_ENTER, 10, 13):
            self.prompt = None
            if prompt.kind == "rename" and snap is not None:
                self.rename_tab(prompt, snap)
            elif prompt.kind == "move":
                self.move_tab(prompt)
            focus_view(self.win)
        elif key in (27, curses.KEY_MOUSE):
            self.close_menu()
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            prompt.text = prompt.text[:-1]
        elif key == 21:  # ctrl+U: clear the line (a rename starts with the current name filled in)
            prompt.text = ""
        elif 32 <= key < 127 and len(prompt.text) < 200:
            prompt.text += chr(key)

    def rename_tab(self, prompt: Prompt, snap: dict) -> None:
        """A display name for the terminal (names.json), as the sidebar's rename: refused when another terminal
        shows it already."""
        taken = [name for address, name in snapshot_names(snap).items() if address != prompt.address]
        what, value = plan_rename(prompt.text, prompt.own, taken)
        if what == "bad":
            self.notice.say("rename: " + value)
            return
        try:
            change_names({prompt.key: value}, self.state)
        except OSError as exc:
            self.notice.say("rename: " + describe_error(exc))

    def move_tab(self, prompt: Prompt) -> None:
        """The terminal's label "space" (as the sidebar's m); the engine reads labels again at once."""
        name = prompt.text.strip()
        if not name:
            return
        if not valid_space_name(name):
            self.notice.say("not a usable space name")
            return
        try:
            run_hc("label", prompt.address, "space=" + name)
        except Exception as exc:  # noqa: BLE001
            self.notice.say("move: " + describe_error(exc))
            return
        poke_engine(self.win, full=True)

    def close_tabs(self, prompt: Prompt, snap: dict) -> None:
        """End the tab's terminal and those that end with it (end_terminal, as the sidebar's End terminal), drop
        their display names, then show the next tab when the shown one closed (the one shown after the ends: a
        pick meanwhile wins)."""
        addresses = prompt.data
        self.notice.say(f"closing {len(addresses)} terminal{'s' if len(addresses) != 1 else ''}…", bad=False)
        self.draw(snap, current_target(self.win))
        failed: List[str] = []
        for address in addresses:
            try:
                end_terminal(address)
            except Exception as exc:  # noqa: BLE001 - the others still end
                failed.append(f"{address}: {describe_error(exc)}")
        try:
            change_names({"term:" + a: "" for a in addresses}, self.state)
        except OSError:
            pass
        poke_engine(self.win)
        order = [str(t.get("address", "")) for t in snap["tabs"]]
        shown = current_target(self.win)
        after = tab_after_close(order, addresses, shown)
        if after != shown:
            show(after, self.win, tab_title(snap, after) if after else NO_TITLE)
        self.notice.clear()
        if failed:
            self.notice.say(f"close: {len(failed)} of {len(addresses)} failed, " + failed[0])
        focus_view(self.win)

    def check_ask(self, snap: Optional[dict], shown: str) -> None:
        """A right click in the view (mmini.tmux.conf writes the file "ask"): the shown terminal's tab menu, here,
        with the keyboard, as a right click on its tab."""
        ask = self.win / "ask"
        if not ask.exists():
            return
        word = read_text(ask)
        try:
            ask.unlink()
        except OSError:
            pass
        if word != "menu":
            return
        if snap is None or tab_of(snap, shown) is None:
            self.notice.say("nothing shown", bad=False)
            return
        self.notice.clear()
        self.open_tab_menu(snap, shown)
        focus_pane("tabs", self.win)

    def rows_goal(self) -> int:
        """TAB_ROWS; while Close's question is open, as many rows as it needs (up to CLOSE_ROWS), so the whole list
        of what ends is on screen before y."""
        p = self.prompt
        if p is None or p.kind != "close":
            return TAB_ROWS
        room = max(1, self.s.size()[1] - 3 - (1 if self.alone else 0))
        tab_rows = self.layout.rows if self.layout is not None else 1
        return max(TAB_ROWS, min(CLOSE_ROWS, tab_rows + len(wrap_words(p.title, room)) + 1))

    def step(self, snap: dict, shown: str, delta: int) -> None:
        """Previous / next tab. At either end nothing happens: showing the shown tab again would only make the view
        flash."""
        addresses = [str(t.get("address", "")) for t in snap["tabs"]]
        if not addresses:
            return
        if shown in addresses:
            index = max(0, min(len(addresses) - 1, addresses.index(shown) + delta))
            if addresses[index] == shown:
                return
        else:
            index = 0 if delta > 0 else len(addresses) - 1
        show(addresses[index], self.win, tab_title(snap, addresses[index]))

    def plus(self, snap: dict) -> None:
        """A new shell in the current group (the same helper as the sidebar's n), then show it."""
        if time.monotonic() - self.last_plus < 0.5:  # one shell per click, also on a double click
            return
        self.last_plus = time.monotonic()
        space = str(snap.get("name") or "") if snap.get("kind") == "space" else ""
        try:
            address = new_shell(str(snap.get("machine") or LOCAL), str(snap.get("cwd") or ""), self.win, space)
        except Exception as exc:  # noqa: BLE001
            self.notice.say("new: " + describe_error(exc))
            return
        # not a tab yet: its id and the group's server (the engine writes the full title once it is listed)
        show(address, self.win, window_title(address.rsplit("/", 1)[-1], str(snap.get("server") or "")))

    def handle_key(self, key: int, snap: Optional[dict], shown: str,
                   click: Optional[Tuple[int, int, int]] = None) -> None:
        """One key or press (`click`: the press on_key read already, (x, y, 1 left or 3 right)). Without a snapshot
        (still loading) only z, enter and bringing the sidebar back work. A tab's menu or question takes every key
        while it is open."""
        if key == curses.KEY_MOUSE and click is None:
            click = read_mouse()
            if click is None:
                return
        if self.prompt is not None:
            if key == curses.KEY_MOUSE and time.monotonic() < self.mouse_quiet:
                return  # the second press of the double click that opened the question
            self.handle_prompt(key, snap, shown)
            return
        if self.menu is not None:
            self.handle_menu(key, snap, click)
            return
        if key in (curses.KEY_LEFT, ord("h")):
            if snap is not None:
                self.step(snap, shown, -1)
        elif key in (curses.KEY_RIGHT, ord("l")):
            if snap is not None:
                self.step(snap, shown, 1)
        elif key in (curses.KEY_ENTER, 10, 13, curses.KEY_DOWN):
            focus_view(self.win)
        elif key in (ord("z"), ord("Z")):
            text = zoom_view(self.win)
            if text:
                self.notice.say(text)
        elif key in (ord("c"), ord("C"), ord("o"), ord("O")):
            if self.alone:  # with a sidebar in the window these keys belong to it
                self.open_sidebar(time.monotonic())
        elif key == ord(HELP_KEY):
            self.notice.say(tab_keys(self.alone), bad=False)
        elif key == curses.KEY_MOUSE and click is not None:
            hit = hit_test(self.layout, click[0], click[1]) if self.layout else None
            if click[2] == 3:  # the right button: a tab's menu
                if snap is not None and hit and hit[0] == "tab" and hit[1] < len(snap["tabs"]):
                    self.open_tab_menu(snap, str(snap["tabs"][hit[1]]["address"]))
            elif hit and hit[0] == "open":
                self.open_sidebar(time.monotonic())
            elif snap is not None and hit and hit[0] == "tab" and hit[1] < len(snap["tabs"]):
                address = str(snap["tabs"][hit[1]]["address"])
                show(address, self.win, tab_title(snap, address))
                focus_view(self.win)
            elif snap is not None and hit and hit[0] == "plus":
                self.plus(snap)
                focus_view(self.win)

    # the window without a sidebar ------------------------------------------------------------------------------
    def watch_sidebar(self, now: float) -> None:
        """Run the engine here while this window has no live sidebar (tab_engine_wanted), stop it as soon as one
        has written its pid. Called at every round of the loop."""
        alive = sidebar_alive(self.win)
        if alive:
            self.missing_since = None
        elif self.missing_since is None:
            self.missing_since = now
        missing_for = 0.0 if self.missing_since is None else now - self.missing_since
        self.alone = tab_engine_wanted(alive, missing_for, read_sidebar_state(self.state) == "hidden")
        if self.alone and self.engine is None:
            self.start_engine()
        elif not self.alone and self.engine is not None:
            self.stop_engine()

    def start_engine(self) -> None:
        engine = Engine(self.state, self.win)
        self.engine = engine
        threading.Thread(target=engine.refresh_forever, daemon=True).start()
        threading.Thread(target=engine.drive, args=(autoopen_enabled(),), daemon=True).start()

    def stop_engine(self) -> None:
        if self.engine is not None:
            self.engine.stop()
            self.engine = None

    def open_sidebar(self, now: float) -> None:
        """c or a click on "›": the sidebar back, open and at full height (split_sidebar, one tmux call). "open" is
        written first, so the new sidebar starts with it. Until the new sidebar runs (check_opening) another "›" does
        nothing, so a double click makes one sidebar."""
        if self.opening is not None:
            return
        write_sidebar_state("open", self.state)
        if not split_sidebar(self.win, BASE, mmini_env(os.environ), read_open_width(self.state)):
            write_sidebar_state("hidden", self.state)
            self.notice.say("could not open the sidebar")
            return
        self.opening = now

    def check_opening(self, now: float) -> None:
        """After "›": done once the new sidebar runs (its pid file). A sidebar that has not started within
        OPEN_TIMEOUT seconds is reported, and the state goes back to "hidden"."""
        if self.opening is None:
            return
        if sidebar_alive(self.win):
            self.opening = None
        elif now - self.opening >= OPEN_TIMEOUT:
            self.opening = None
            write_sidebar_state("hidden", self.state)
            self.notice.say("could not open the sidebar")

    def refit(self) -> None:
        """Keep the pane TAB_ROWS rows high, exactly (tmux): a resized window is spread over the panes by tmux, and a
        dragged line under the tabs is put back. No tmux call while the height is the one the last sizing left.
        Never while the view is zoomed (a resize would end the zoom): looked at again every ZOOM_LOOK seconds until
        it is not."""
        if not autosize_enabled():
            return
        goal = self.rows_goal()
        if self.s.size()[0] == self.sized_rows and goal == self.rows_aimed:
            return
        now = time.monotonic()
        if self.zoom_look is not None and now - self.zoom_look < ZOOM_LOOK:
            return
        pane = own_pane()
        look = window_look(pane) if pane else None
        if look is None:
            return
        self.zoom_look = now if look.zoomed else None
        if look.zoomed:
            self.sized_rows, self.rows_aimed = self.s.size()[0], goal  # nothing asked again until the size changes
            return
        if look.pane_height == goal:  # tmux has it right; curses has not caught up yet
            self.sized_rows, self.rows_aimed = goal, goal
            return
        after = size_pane(pane, rows=goal)
        self.sized_rows = after.pane_height if after is not None else look.pane_height
        self.rows_aimed = goal

    def on_key(self, key: int, snap: Optional[dict], shown: str) -> None:
        """What the loop got from getch (not -1). A size change is no key: the next round's refit looks at it. A
        paste (a dropped file) goes into the open question, else on to the view."""
        if key == curses.KEY_RESIZE:
            self.notice.clear()
            return
        if key == 27:
            pasted = read_paste(self.s.scr)
            if pasted is not None:
                if self.prompt is not None and self.prompt.kind != "close":
                    self.prompt.text = (self.prompt.text + prompt_text(pasted))[:200]
                else:
                    self.menu = self.prompt = None
                    if not paste_to_view(pasted, self.win):
                        self.notice.say("the paste could not be passed on to the terminal")
                return
        if key not in (curses.KEY_MOUSE, curses.KEY_RESIZE) and self.menu is None and self.prompt is None \
                and time.monotonic() < self.forward_until:
            self.forward_until = time.monotonic() + FORWARD_GRACE  # typed on after a key closed the menu
            send_keys_to_view([key] + drain_keys(self.s.scr), self.win)
            return
        click = None
        if key == curses.KEY_MOUSE:
            click = read_mouse()
            if click is None:
                return  # a button let go: its press already acted, and the notice it set stays
        self.notice.clear()
        self.handle_key(key, snap, shown, click)

    def run(self) -> None:
        setup_curses(self.s.scr, right=True)  # the right button: a tab's menu
        self.s.scr.refresh()
        bracketed_paste(True)  # a paste (a dropped file) is told from typing, and goes on to the view
        try:
            while True:
                now = time.monotonic()
                seen = pick_stamp(self.win)  # before reading: a pick meanwhile is not missed
                self.watch_sidebar(now)
                self.check_opening(now)
                snap = read_snapshot(self.win)
                shown = current_target(self.win)
                self.check_ask(snap, shown)
                self.draw(snap, shown)
                self.pane_title.send(tabs_title(snap, shown))  # after the refresh: curses has written all it holds
                self.refit()
                self.watch_menu()
                key = wait_key(self.s.scr, self.win, seen, now)
                if key is None:
                    return
                if key != -1:
                    self.on_key(key, snap, shown)
        finally:
            bracketed_paste(False)
            self.stop_engine()


def start_hidden() -> int:
    """A sidebar started while the state is "hidden" (start.sh always makes three panes) ends at once, without
    drawing: tmux closes its pane, and the tab bar and the view take its columns. start.sh gives the view the
    keyboard."""
    return 0


# The pane's title "mmini" (OSC 2), then an empty working directory (OSC 7 with no URL), sent once at the start;
# later titles (PaneTitle) are OSC 2 alone. In an mmini window tmux keeps both for the pane (the window shows the
# title of the pane with the keyboard; start.sh cleared Ghostty's folder icon). Run straight in Ghostty, the empty
# OSC 7 makes it forget the shell's folder (1.3, stream_handler reportPwd), so no folder icon shows; the title goes
# first, as an empty OSC 7 also clears a title while none was seen.
PANE_TITLE = f"\033]2;{NO_TITLE}\007\033]7;\007"


class PaneTitle:
    """Sends the window title of this pane (OSC 2) when it changes, never every frame. `sent` starts as what
    claim_pane sent."""

    def __init__(self, fd: int = 1, sent: str = NO_TITLE) -> None:
        self.fd = fd
        self.sent = sent

    def send(self, title: Optional[str]) -> bool:
        """Send `title` unless it is None (not known: the title stays) or was the last one sent. True when it was
        written. Never raises; not a terminal: nothing is written, and it counts as sent."""
        if title is None or title == self.sent:
            return False
        self.sent = title
        try:
            if os.isatty(self.fd):
                os.write(self.fd, title_escape(title))
                return True
        except OSError:
            pass
        return False


def claim_pane(fd: int = 1) -> None:
    """Send PANE_TITLE when `fd` is a terminal. Never raises."""
    try:
        if os.isatty(fd):
            os.write(fd, PANE_TITLE.encode())
    except OSError:
        pass


def main(argv: Sequence[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("sidebar", "tabs"):
        print("usage: mmini.py sidebar|tabs", file=sys.stderr)
        return 2
    if argv[1] == "sidebar" and read_sidebar_state() == "hidden":
        return start_hidden()
    claim_pane()
    setup_locale()
    os.environ.setdefault("ESCDELAY", "25")
    cls = Sidebar if argv[1] == "sidebar" else TabBar
    try:
        curses.wrapper(lambda stdscr: cls(stdscr).run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
