"""Offline tests for hcgui.py and view.sh: no real hc, no Ghostty, no curses screen."""

import ast
import atexit
import dataclasses
import itertools
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
# The private notes: left out of the public copy (`git archive`, .gitattributes), which ships these tests. A test
# that compares them with what is drawn runs only where they are (skip_without_notes).
NOTES = ROOT / "INTERNAL.md"
skip_without_notes = unittest.skipUnless(NOTES.exists(), "INTERNAL.md: private notes, not in the public copy")
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
# Only the settings the fixtures are written for: none of the shell's HCGUI_* settings reach mini or view.sh. The
# home machine is "mini"; the account marks and the shared account are fixtures too.
for _name in [k for k in os.environ if k.startswith("HCGUI_")]:
    del os.environ[_name]
os.environ["HCGUI_TMUX"] = "0"  # no tmux calls (also when the tests run inside tmux)
os.environ["HCGUI_BROWSER"] = "0"
os.environ.pop("TMUX", None)
os.environ.pop("TMUX_PANE", None)
os.environ["HCGUI_FIRST"] = "mini"
os.environ["HCGUI_MARKS"] = "claude=¹,main=¹,work=²"
os.environ["HCGUI_SHARED_USER"] = "guest"
# mini's default folders come from these at import: a test that forgets to pass its own folder writes into a
# throwaway one, never into ~/.local/state/hcgui.
_DEFAULT_STATE = tempfile.mkdtemp(prefix="hcgui-tests-")
atexit.register(shutil.rmtree, _DEFAULT_STATE, True)
os.environ["HCGUI_STATE"] = _DEFAULT_STATE
os.environ.pop("HCGUI_WINDOW", None)

import hcgui  # noqa: E402

hcgui.HC = "/nonexistent/hc-must-never-run-in-tests"  # a test that forgets its stand-in fails, it never reaches hc
hcgui.setup_locale()


def ls(*terms):
    return json.dumps({"terminals": [dict(t) for t in terms]})


def term(address, cwd="/Users/x/dev/app", agent="zsh", name=None, status=None):
    d = {"address": address, "agent": agent, "cwd": cwd, "state": "live", "turn": 0}
    if name is not None:
        d["name"] = name
    if status is not None:
        d["status"] = status
    return d


SAMPLE = ls(
    term("mini/t5", "/Users/x/dev/atlas", "claude-code", "atlas", "idle"),
    term("mini/t6", "/Users/x/dev/atlas", "zsh", "zz"),
    term("mini/t7", "/Users/x", "zsh", None),
    term("mini/t8", "/Users/x/dev/appshop", "claude-code", "appshop", "working"),
    term("rig/t1", "/home/rig", "claude-code", "r1", "blocked"),
    term("t1", "/Users/me", "zsh", None),
)


def top_rows(spaces, rigs):
    """Lines of the sidebar's top part: "spaces", the spaces, "+ new space", a blank, "rigs", the rigs, "+ add rig"."""
    return len(spaces) + len(rigs) + 5


def fold_line(mode, width=30):
    """The sidebar's last line as drawn: "‹ fold" (or "‹ hide"), and in the open sidebar a dim "?" at its end."""
    label = hcgui.fold_label(mode, width - 1)
    x = hcgui.help_column(label, width)
    return hcgui.glyph(label).ljust(x) + "?" if mode == "open" and x >= 0 else hcgui.glyph(label)


def mouse_at(x, y, bstate):
    """What ncurses reports for one mouse event (read by read_mouse_event and read_mouse)."""
    return mock.patch.object(hcgui.curses, "getmouse", return_value=(0, x, y, 0, bstate))


def pressed(x, y, button=1):
    """A press of the left (1) or right (3) button at column x, line y."""
    return mouse_at(x, y, hcgui.curses.BUTTON1_PRESSED if button == 1 else hcgui.curses.BUTTON3_PRESSED)


def seen_done(state, terms):
    """The user has looked at every "done" agent of `terms` (seen.json), so no "needs you" section is drawn for
    them: the tests written before that section keep their screens."""
    done = {t["address"]: t.get("turn", 0) for t in terms if t.get("status") == "done"}
    if done:
        hcgui.write_seen(done, state)


def many_agents(n=6):
    """Two spaces, one of them with n agents (like the mini's real "dev" space)."""
    return hcgui.build_groups(hcgui.parse(ls(
        *[term(f"t{i}", "/Users/x/dev", "claude-code", f"a{i}", "idle") for i in range(n)],
        term("t90", "/Users/x/dev/other", "zsh", "sh"))), "mini")


class ParseTests(unittest.TestCase):
    def test_parse_fields_and_missing(self):
        raw = ls({"address": "t5", "agent": "claude-code", "cwd": "/a/b", "name": None, "status": "done"},
                 {"address": "rig/t2"}, {"name": "no-address"})
        terms = hcgui.parse(raw)
        self.assertEqual([t.address for t in terms], ["t5", "rig/t2"])
        self.assertEqual(terms[0].machine, hcgui.LOCAL)
        self.assertEqual(terms[1].machine, "rig")
        self.assertEqual(terms[0].label, "t5")
        self.assertEqual(terms[1].name, "")

    def test_unprintable_characters_become_spaces(self):
        raw = ls(term("mini/t9", name="a\nb\x1b[31mc", cwd="/Users/me/dev/re\tpo"))
        t = hcgui.parse(raw)[0]
        self.assertEqual(t.name, "a b [31mc")
        self.assertEqual(t.cwd, "/Users/me/dev/re\tpo")  # the real folder, for new terminals there
        self.assertEqual(hcgui.cwd_space(t.cwd), "re po")
        self.assertEqual(hcgui.short_folder(t.cwd), "~/dev/re po")
        info = hcgui.parse_info(json.dumps({"labels": {"space": "web\r", "account": "x\x07y"}}), "mini/t9")
        self.assertEqual((info.space, info.account), ("web", "x y"))

    def test_label_prefers_name(self):
        self.assertEqual(hcgui.parse(ls(term("mini/t9", name="atlas")))[0].label, "atlas")
        self.assertEqual(hcgui.parse(ls(term("mini/t9")))[0].label, "t9")

    def test_machine_of(self):
        self.assertEqual(hcgui.machine_of("t1"), hcgui.LOCAL)
        self.assertEqual(hcgui.machine_of("mini/t5"), "mini")
        self.assertEqual(hcgui.machine_of("a/b/t5"), "a/b")

    def test_junk_raises_value_error_only(self):
        for raw in ("not json", "[]", "null", "3", '{"terminals": null}', '{"terminals": {"a": 1}}', "{}"):
            with self.assertRaises(ValueError, msg=raw):
                hcgui.parse(raw)

    def test_junk_entries_are_skipped(self):
        raw = json.dumps({"terminals": [1, None, "x", [], {"address": "t3", "name": 7, "cwd": None}]})
        terms = hcgui.parse(raw)
        self.assertEqual([(t.address, t.name, t.cwd) for t in terms], [("t3", "7", "")])

    def test_parse_info(self):
        raw = json.dumps({"labels": {"space": " atlas "}, "parent": "t19"})
        self.assertEqual(hcgui.parse_info(raw, "mini/t20"), hcgui.Info("atlas", "mini/t19"))
        self.assertEqual(hcgui.parse_info(raw, "t20"), hcgui.Info("atlas", "t19"))
        self.assertEqual(hcgui.parse_info('{"labels": {}, "parent": null}', "t1"), hcgui.Info())
        self.assertEqual(hcgui.parse_info('{"labels": null, "parent": 5}', "t1"), hcgui.Info())
        self.assertEqual(hcgui.parse_info('{"labels": {"space": 3}}', "t1"), hcgui.Info())
        self.assertEqual(hcgui.parse_info('{"parent": "rig/t2"}', "rig/t3"), hcgui.Info("", "rig/t2"))
        for raw in ("junk", "[]", "null"):
            with self.assertRaises(ValueError):
                hcgui.parse_info(raw, "t1")

    def test_parse_info_ends_with_parent(self):
        self.assertTrue(hcgui.parse_info('{"parent": "t1", "die_with_parent": true}', "t2").dies)
        self.assertFalse(hcgui.parse_info('{"parent": "t1", "die_with_parent": false}', "t2").dies)
        self.assertTrue(hcgui.parse_info('{"parent": "t1"}', "t2").dies)  # unknown: listed as ending, to be safe

    def test_parse_machines(self):
        raw = json.dumps({"machines": [{"name": "vps", "target": "me@vps", "state": "connected"}, {"name": ""},
                                       {"target": "x"}, 3, {"name": 7}]})
        self.assertEqual(hcgui.parse_machines(raw), [hcgui.Machine("vps", "me@vps", False)])
        raw = json.dumps({"machines": [{"name": "rig", "target": "guest@mini", "via": False},
                                       {"name": "box", "target": "fly ssh console -C", "via": True},
                                       {"name": "odd", "target": 7}]})
        self.assertEqual(hcgui.parse_machines(raw), [hcgui.Machine("rig", "guest@mini"),
                                                     hcgui.Machine("box", "fly ssh console -C", True),
                                                     hcgui.Machine("odd", "")])
        self.assertEqual(hcgui.parse_machines('{"machines": []}'), [])
        for raw in ("junk", "[]", "{}", '{"machines": null}'):
            with self.assertRaises(ValueError):
                hcgui.parse_machines(raw)


class SpaceTests(unittest.TestCase):
    def test_cwd_space(self):
        self.assertEqual(hcgui.cwd_space("/Users/x/dev/atlas"), "atlas")
        self.assertEqual(hcgui.cwd_space("/Users/x/dev/atlas/src/deep/er"), "atlas")
        self.assertEqual(hcgui.cwd_space("/home/u/dev/repo/x"), "repo")
        self.assertEqual(hcgui.cwd_space("/Users/x/dev"), "dev")
        self.assertEqual(hcgui.cwd_space("/Users/x/dev/"), "dev")
        self.assertEqual(hcgui.cwd_space("/Users/x"), "home")
        self.assertEqual(hcgui.cwd_space("/Users/x/"), "home")
        self.assertEqual(hcgui.cwd_space("/home/rig"), "home")
        self.assertEqual(hcgui.cwd_space(""), "home")
        self.assertEqual(hcgui.cwd_space("/"), "home")
        self.assertEqual(hcgui.cwd_space("/Users"), "Users")
        self.assertEqual(hcgui.cwd_space("/Users/x/Documents/notes"), "notes")
        self.assertEqual(hcgui.cwd_space("/opt/dev/thing"), "thing")
        self.assertEqual(hcgui.cwd_space("/private/tmp/work"), "work")

    def test_own_label_wins(self):
        cwds = {"t1": "/Users/x/dev/a"}
        self.assertEqual(hcgui.resolve_space("t1", cwds, {"t1": hcgui.Info("mine", "")}), "mine")
        self.assertEqual(hcgui.resolve_space("t1", cwds, {}), "a")
        self.assertEqual(hcgui.resolve_space("t1", cwds, {"t1": hcgui.Info()}), "a")

    def test_parent_chain(self):
        cwds = {"t1": "/Users/x/dev/a", "t2": "/Users/x/dev/b", "t3": "/Users/x/dev/c"}
        infos = {"t1": hcgui.Info("top", ""), "t2": hcgui.Info("", "t1"), "t3": hcgui.Info("", "t2")}
        self.assertEqual(hcgui.resolve_space("t3", cwds, infos), "top")  # label two levels up
        infos["t1"] = hcgui.Info("", "")
        self.assertEqual(hcgui.resolve_space("t3", cwds, infos), "a")  # no label anywhere: the top's folder
        infos["t2"] = hcgui.Info("mid", "t1")
        self.assertEqual(hcgui.resolve_space("t3", cwds, infos), "mid")  # the nearest label wins
        infos["t3"] = hcgui.Info("own", "t2")
        self.assertEqual(hcgui.resolve_space("t3", cwds, infos), "own")

    def test_missing_or_ended_parent_stops_the_chain(self):
        cwds = {"t2": "/Users/x/dev/b", "t3": "/Users/x/dev/c"}  # t1 is not live any more
        infos = {"t1": hcgui.Info("gone", ""), "t2": hcgui.Info("", "t1"), "t3": hcgui.Info("", "t2")}
        self.assertEqual(hcgui.resolve_space("t3", cwds, infos), "b")
        self.assertEqual(hcgui.resolve_space("t2", cwds, infos), "b")
        self.assertEqual(hcgui.resolve_space("t3", cwds, {"t3": hcgui.Info("", "t99")}), "c")
        self.assertEqual(hcgui.resolve_space("t3", cwds, {"t3": hcgui.Info("", "t2")}), "b")  # parent without info

    def test_loops_end(self):
        cwds = {"t1": "/Users/x/dev/a", "t2": "/Users/x/dev/b"}
        infos = {"t1": hcgui.Info("", "t2"), "t2": hcgui.Info("", "t1")}
        self.assertEqual(hcgui.resolve_space("t1", cwds, infos), "a")
        self.assertEqual(hcgui.resolve_space("t2", cwds, infos), "b")
        self.assertEqual(hcgui.resolve_space("t1", cwds, {"t1": hcgui.Info("", "t1")}), "a")

    def test_unknown_terminal(self):
        self.assertEqual(hcgui.resolve_space("t9", {}, {}), "home")

    def test_space_cwd(self):
        def t(address, cwd):
            return hcgui.Term(address, "mini", "", "zsh", "", cwd)
        self.assertEqual(hcgui.space_cwd("atlas", [t("t1", "/Users/x/dev/atlas/src/a")]), "/Users/x/dev/atlas")
        self.assertEqual(hcgui.space_cwd("home", [t("t1", "/Users/x")]), "/Users/x")
        self.assertEqual(hcgui.space_cwd("dev", [t("t1", "/Users/x/dev")]), "/Users/x/dev")
        self.assertEqual(hcgui.space_cwd("notes", [t("t1", "/Users/x/Documents/notes")]), "/Users/x/Documents/notes")
        # a labelled space whose terminals sit elsewhere: the first terminal's folder
        self.assertEqual(hcgui.space_cwd("lab", [t("t1", ""), t("t2", "/Users/x/dev/other/sub")]),
                         "/Users/x/dev/other/sub")
        self.assertEqual(hcgui.space_cwd("lab", [t("t1", "/tmp/a"), t("t2", "/Users/x/dev/lab/z")]),
                         "/Users/x/dev/lab")
        self.assertEqual(hcgui.space_cwd("lab", []), "")


class GroupTests(unittest.TestCase):
    def test_home_machine(self):
        terms = hcgui.parse(SAMPLE)
        self.assertEqual(hcgui.home_machine(terms, "mini"), "mini")
        self.assertEqual(hcgui.home_machine(terms, "nothere"), hcgui.LOCAL)
        self.assertEqual(hcgui.home_machine([], "mini"), hcgui.LOCAL)

    def test_groups_remote_home(self):
        spaces, rigs = hcgui.build_groups(hcgui.parse(SAMPLE), "mini")
        self.assertEqual([g.name for g in spaces], ["home", "appshop", "atlas"])
        # servers: the home machine first (all its terminals, the spaces' ones), then the others, this Mac last
        self.assertEqual([g.name for g in rigs], ["mini", "rig", hcgui.LOCAL])
        self.assertEqual([g.home for g in rigs], [True, False, False])
        self.assertEqual([t.address for t in rigs[0].terms], ["mini/t8", "mini/t5", "mini/t7", "mini/t6"])
        self.assertEqual(spaces[2].key, "space:atlas")
        self.assertEqual(spaces[2].machine, "mini")
        self.assertEqual(spaces[2].cwd, "/Users/x/dev/atlas")
        self.assertEqual(rigs[1].kind, "rig")
        self.assertEqual(rigs[1].cwd, "")
        self.assertEqual(rigs[2].key, "rig:" + hcgui.LOCAL)

    def test_tabs_sorted_by_label(self):
        spaces, _ = hcgui.build_groups(hcgui.parse(SAMPLE), "mini")
        self.assertEqual([t.label for t in spaces[2].terms], ["atlas", "zz"])
        raw = ls(term("t13"), term("t9"), term("t100"), term("t2", name="beta"), term("t3", name="Alpha"))
        spaces, _ = hcgui.build_groups(hcgui.parse(raw), "mini")
        self.assertEqual([t.label for t in spaces[0].terms], ["Alpha", "beta", "t9", "t13", "t100"])

    def test_natural_key_takes_any_text(self):
        self.assertEqual(hcgui.natural("t13"), [(1, 0, "t"), (0, 13, "")])
        self.assertLess(hcgui.natural("t9"), hcgui.natural("t13"))
        for odd in ("²", "1²", "v1²", "①", "٣", "x٣9", "½", ""):  # str.isdigit() is True for some, int() refuses
            self.assertIsInstance(hcgui.natural(odd), list, odd)
        self.assertEqual(hcgui.natural("v1²"), [(1, 0, "v"), (0, 1, ""), (1, 0, "²")])
        raw = ls(term("mini/t5"), term("rig/t1", name="v1²"), term("rig/t2", name="①"), term("rig/t3", name="v1"))
        _, rigs = hcgui.build_groups(hcgui.parse(raw), "mini")  # a server may report any name: no crash, an order
        self.assertEqual([t.label for t in rigs[1].terms], ["v1", "v1²", "①"])

    def test_groups_all_local(self):
        raw = ls(term("t5", "/Users/x/dev/b"), term("t6", "/Users/x/dev/a"))
        spaces, rigs = hcgui.build_groups(hcgui.parse(raw), "mini")
        self.assertEqual([g.name for g in spaces], ["a", "b"])
        self.assertEqual(spaces[0].machine, hcgui.LOCAL)
        self.assertEqual([(g.key, g.home, len(g.terms)) for g in rigs], [("rig:" + hcgui.LOCAL, True, 2)])

    def test_labels_and_parents_make_the_spaces(self):
        raw = ls(term("mini/t1", "/Users/x/dev", "claude-code", "atlas", "idle"),
                 term("mini/t2", "/Users/x/dev", "claude-code", "tracker", "idle"),
                 term("mini/t3", "/Users/x/dev", "zsh", "helper"),        # started by t1
                 term("mini/t4", "/Users/x/dev/atlas-app/src", "zsh"),    # repo folder below dev
                 term("mini/t5", "/tmp/elsewhere", "zsh", "moved"),       # labelled into "atlas"
                 term("rig/t1", "/home/rig/dev/x", "claude-code", "r1"))
        infos = {"mini/t1": hcgui.Info("atlas", ""), "mini/t3": hcgui.Info("", "mini/t1"),
                 "mini/t5": hcgui.Info("atlas", ""), "rig/t1": hcgui.Info("ignored", "")}
        spaces, rigs = hcgui.build_groups(hcgui.parse(raw), "mini", infos)
        self.assertEqual([g.name for g in spaces], ["atlas", "atlas-app", "dev"])
        self.assertEqual([t.label for t in spaces[0].terms], ["atlas", "helper", "moved"])
        self.assertEqual([t.label for t in spaces[2].terms], ["tracker"])
        self.assertEqual(spaces[1].cwd, "/Users/x/dev/atlas-app")
        self.assertEqual(spaces[0].cwd, "/Users/x/dev")  # no terminal is in a folder called atlas: the first one's
        self.assertEqual([g.name for g in rigs], ["mini", "rig"])  # one group per machine, labels play no part

    def test_empty(self):
        self.assertEqual(hcgui.build_groups([], "mini"), ([], []))

    def test_summary_status(self):
        def terms(*statuses):
            return [hcgui.Term("t", hcgui.LOCAL, "", "claude-code", s, "") for s in statuses]
        self.assertEqual(hcgui.summary_status(terms("idle", "working")), "working")
        self.assertEqual(hcgui.summary_status(terms("done", "idle")), "done")
        self.assertEqual(hcgui.summary_status(terms("working", "blocked")), "blocked")
        self.assertEqual(hcgui.summary_status(terms("idle", "error")), "error")
        self.assertEqual(hcgui.summary_status(terms("")), "")
        self.assertEqual(hcgui.summary_status([]), "")


class AgentTests(unittest.TestCase):
    def test_is_agent(self):
        def t(agent, status=""):
            return hcgui.Term("t1", hcgui.LOCAL, "", agent, status, "")
        for plain in ("zsh", "bash", "sh", "fish", "login"):
            self.assertFalse(t(plain).is_agent)
        self.assertTrue(t("claude-code").is_agent)
        self.assertTrue(t("zsh", "working").is_agent)
        self.assertTrue(t("python3").is_agent)

    def test_selectable_items_order(self):
        spaces, rigs = hcgui.build_groups(hcgui.parse(SAMPLE), "mini")
        items = hcgui.selectable_items(spaces, rigs)
        # as drawn: the spaces, "+ new space", the servers, "+ add server", then the agents (the home machine's
        # agents once, under their spaces)
        self.assertEqual([i.kind for i in items], ["group"] * 3 + ["new_space"] + ["group"] * 3 + ["add_rig"]
                         + ["agent"] * 3)
        self.assertEqual([i.address for i in items[8:]], ["mini/t8", "mini/t5", "rig/t1"])
        plan = hcgui.plan_sidebar(spaces, rigs, 40)
        self.assertEqual([items[r.item] for _, r in plan if r.item >= 0], items)  # the drawn order is the cursor's
        # the servers section hidden: no server rows, no "+ add server", no agents of servers
        hidden = hcgui.selectable_items(spaces, rigs, servers=False)
        self.assertEqual([i.kind for i in hidden], ["group"] * 3 + ["new_space"] + ["agent"] * 2)
        self.assertEqual([i.address for i in hidden[4:]], ["mini/t8", "mini/t5"])
        plan = hcgui.plan_sidebar(spaces, rigs, 40, servers=False)
        self.assertEqual([hidden[r.item] for _, r in plan if r.item >= 0], hidden)
        self.assertNotIn("servers", [r.text for _, r in plan])


def foreground(*argv, name="2.1.331"):
    """hc get's "foreground" of a terminal: the leader of its foreground process group (made-up pid and folder)."""
    return {"pid": 4242, "name": name, "argv": list(argv), "cwd": "/Users/x/dev/app"}


class ForegroundTests(unittest.TestCase):
    """Claude Code typed in a terminal's shell: hc ls names the shell, hc get's foreground shows Claude Code (pure)."""

    def test_claude_argv_is_strict(self):
        for argv in (["/Users/x/.local/bin/claude"], ["claude"], ["claude", "--resume"],
                     ["/Users/x/.local/share/claude/versions/2.1.331"],
                     ["node", "/opt/homebrew/bin/claude"], ["/usr/local/bin/node", "--no-warnings", "/x/bin/claude"],
                     ["node", "/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/cli.js", "-c"],
                     ["bun", "/x/node_modules/@anthropic-ai/claude-code/cli.mjs"]):
            self.assertTrue(hcgui.claude_argv(argv), argv)
        for argv in ([], [""], ["claude-foo"], ["/x/bin/claudette"], ["/x/claude-code"], ["zsh", "-l"],
                     ["python3", "claude"], ["python3", "/x/claude.py"], ["node", "/x/claude-foo"],
                     ["node", "/x/cli.js"], ["node", "/x/other/claude-code/cli.js"], ["node"], ["node", "-e", "x"],
                     ["/x/versions/2.1.331"], ["/x/claude/versions/latest"], ["/x/claude/versions/2"],
                     ["/x/claude/2.1.331"], ["vim", "claude"]):
            self.assertFalse(hcgui.claude_argv(argv), argv)

    def test_parse_foreground_is_defensive(self):
        self.assertEqual(hcgui.parse_foreground(foreground("/Users/x/.local/bin/claude")), hcgui.CLAUDE_AGENT)
        self.assertEqual(hcgui.parse_foreground(foreground("-zsh", name="zsh")), "")
        for junk in (None, "claude", 5, [], {}, {"argv": "claude"}, {"argv": [3]}, {"argv": ["claude", None]},
                     {"name": "claude"}, {"argv": None}):
            self.assertEqual(hcgui.parse_foreground(junk), "", junk)

    def test_parse_info_reads_the_foreground(self):
        raw = json.dumps({"labels": {"account": "work"}, "parent": None, "reported": False,
                          "foreground": foreground("/Users/x/.local/bin/claude")})
        self.assertEqual(hcgui.parse_info(raw, "mini/t3"), hcgui.Info(account="work", foreground="claude-code"))
        for junk in ('{"foreground": null}', '{"foreground": {"argv": "x"}}', '{"foreground": 1}', "{}"):
            self.assertEqual(hcgui.parse_info(junk, "t1").foreground, "", junk)

    def test_with_foreground_judges_only_plain_programs(self):
        def t(address, agent, status=""):
            return hcgui.Term(address, hcgui.LOCAL, "", agent, status, "")
        terms = [t("t1", "zsh"), t("t2", "bash", "working"), t("t3", "python3"), t("t4", "zsh"), t("t5", "zsh")]
        claude = hcgui.Info(foreground=hcgui.CLAUDE_AGENT)
        infos = {"t1": claude, "t2": claude, "t3": claude, "t4": hcgui.Info()}  # t5: no hc get answer yet
        out = hcgui.with_foreground(terms, infos)
        self.assertEqual([x.agent for x in out], ["claude-code", "claude-code", "python3", "zsh", "zsh"])
        self.assertEqual([x.status for x in out], ["", "working", "", "", ""])  # the status stays hc's
        self.assertTrue(out[0].is_agent)
        self.assertFalse(out[3].is_agent)
        self.assertEqual(hcgui.account_marks(out, {"t1": hcgui.Info(account="work", foreground="claude-code")}),
                         {"t1": "²"})
        self.assertEqual(hcgui.account_marks(terms, {"t1": hcgui.Info(account="work")}), {})  # a shell: no mark


class LoneAgentTests(unittest.TestCase):
    """The agents section without a heading for a group with one agent: its row names the group (pure)."""

    def groups(self, *terms):
        return hcgui.build_groups(hcgui.parse(ls(*terms)), "mini")

    def test_one_agent_has_no_heading_and_names_its_group(self):
        spaces, rigs = self.groups(term("mini/t1", "/Users/x/dev/docs", "claude-code", "notes", "idle"),
                                   term("mini/t2", "/Users/x/dev/api", "claude-code", "api", "working"),
                                   term("mini/t3", "/Users/x/dev/web", "claude-code", "w1", "idle"),
                                   term("mini/t4", "/Users/x/dev/web", "claude-code", "w2", "done"),
                                   term("mini/t5", "/Users/x/dev/web", "zsh", "sh"))
        plan = hcgui.plan_sidebar(spaces, rigs, 30)
        lower = [(r.kind, r.group.name if r.group else "", r.term.label if r.term else "", r.place)
                 for _, r in plan if r.kind in ("agent_group", "agent")]
        self.assertEqual(lower, [("agent", "api", "api", ""),  # its name is its space's: no repetition
                                 ("agent", "docs", "notes", "docs"),
                                 ("agent_group", "web", "", ""), ("agent", "web", "w1", ""),
                                 ("agent", "web", "w2", "")])
        self.assertEqual([r.count for _, r in plan if r.kind == "agent_group"], [2])
        items = hcgui.selectable_items(spaces, rigs)
        self.assertEqual([items[r.item] for _, r in plan if r.item >= 0], items)  # the cursor's order stays

    def test_more_never_follows_a_heading_without_its_agents(self):
        # solo alone in aaa (no heading), then web's two: a short window would end on "web · 2" over none of them
        spaces, rigs = self.groups(term("mini/t1", "/Users/x/dev/aaa", "claude-code", "solo", "idle"),
                                   term("mini/t2", "/Users/x/dev/web", "claude-code", "w1", "idle"),
                                   term("mini/t3", "/Users/x/dev/web", "claude-code", "w2", "done"))
        items = hcgui.selectable_items(spaces, rigs)
        solo = next(i for i, item in enumerate(items) if item.kind == "agent" and item.address == "mini/t1")
        for height in range(6, 18):
            lower = [r.kind for _, r in hcgui.plan_sidebar(spaces, rigs, height, solo)
                     if r.kind in ("agent_group", "agent", "more")]
            for i, kind in enumerate(lower):
                if kind == "agent_group":
                    self.assertLess(i + 1, len(lower), height)
                    self.assertEqual(lower[i + 1], "agent", (height, lower))
        entries = [r for _, r in hcgui.plan_sidebar(spaces, rigs, 60, solo) if r.kind in ("agent_group", "agent")]
        rows = hcgui.pick_agent_rows(entries, 3, solo)
        self.assertEqual([(r.kind, r.term.label if r.term else r.text) for r in rows],
                         [("agent", "solo"), ("more", "+2 more")])

    def test_lone_place_ignores_case_and_follows_renames(self):
        group = hcgui.Group("space:api", "api", "space", "mini", "")
        agent = hcgui.Term("mini/t2", "mini", "API", "claude-code", "idle", "")
        self.assertEqual(hcgui.lone_place(group, agent), "")
        self.assertEqual(hcgui.lone_place(group, dataclasses.replace(agent, title="backend")), "api")
        group.title = "Backend"
        self.assertEqual(hcgui.lone_place(group, dataclasses.replace(agent, title="backend")), "")
        self.assertEqual(hcgui.lone_place(group, agent), "Backend")

    def test_lone_place_never_names_a_server(self):
        rig = hcgui.Group("rig:box", "box", "rig", "box", "", alias="me@box")
        agent = hcgui.Term("box/t2", "box", "notes", "claude-code", "done", "")
        self.assertEqual(hcgui.lone_place(rig, agent), "")

    def test_name_parts_cut_the_place_first(self):
        self.assertEqual(hcgui.name_parts("notes", "¹", "docs", 20), ("notes¹", " · docs"))
        self.assertEqual(hcgui.name_parts("notes", "¹", "", 20), ("notes¹", ""))
        self.assertEqual(hcgui.name_parts("notes", "¹", "documentation", 14), ("notes¹", " · docu…"))
        self.assertEqual(hcgui.name_parts("averyveryverylongname", "¹", "docs", 12), ("aver…¹", " · do…"))
        self.assertEqual(hcgui.name_parts("averyveryverylongname", "¹", "docs", 10), ("averyver…¹", ""))
        for room in range(1, 30):
            head, tail = hcgui.name_parts("averyveryverylongname", "²", "documentation", room)
            self.assertLessEqual(hcgui.text_width(head + tail), room, room)
            self.assertTrue(head.endswith("²") or room < 2, room)  # the mark is never cut (with_mark)

    def test_more_rows_and_the_cursor_without_headings(self):
        terms = [term(f"mini/t{i}", f"/Users/x/dev/s{i:02d}", "claude-code", f"a{i}", "idle") for i in range(8)]
        terms += [term("mini/t20", "/Users/x/dev/s03", "claude-code", "b3", "idle")]  # s03 has two
        spaces, rigs = self.groups(*terms)
        items = hcgui.selectable_items(spaces, rigs)
        agents = [i for i, item in enumerate(items) if item.kind == "agent"]
        self.assertEqual(len(agents), 9)
        for cap in range(0, 12):
            for cursor in agents:
                entries = [r for _, r in hcgui.plan_sidebar(spaces, rigs, 60, cursor)
                           if r.kind in ("agent_group", "agent")]
                rows = hcgui.pick_agent_rows(entries, cap, cursor)
                self.assertLessEqual(len(rows), max(cap, 0), (cap, cursor))
                if cap >= 1:
                    self.assertIn(cursor, [r.item for r in rows], (cap, cursor))
                shown = sum(1 for r in rows if r.kind == "agent")
                more = [r.count for r in rows if r.kind == "more"]
                if shown < 9 and cap >= 2:
                    self.assertEqual(more, [9 - shown], (cap, cursor))
                for i, r in enumerate(rows):  # a heading only right above one of its own group's agents
                    if r.kind == "agent_group":
                        self.assertLess(i + 1, len(rows), (cap, cursor))
                        self.assertIs(rows[i + 1].group, r.group, (cap, cursor))
        # the cursor on s03's second agent with room for 3: its heading on top, then its agents
        b3 = next(i for i in agents if items[i].address == "mini/t20")
        entries = [r for _, r in hcgui.plan_sidebar(spaces, rigs, 60, b3) if r.kind in ("agent_group", "agent")]
        rows = hcgui.pick_agent_rows(entries, 4, b3)
        self.assertEqual([(r.kind, r.term.label if r.term else r.text) for r in rows],
                         [("agent_group", ""), ("agent", "a3"), ("agent", "b3"), ("more", "+7 more")])


class FallbackGroupTests(unittest.TestCase):
    """Which group a start opens on when there is no usable saved group."""

    def test_first_space_with_an_agent_not_the_empty_home(self):
        spaces, rigs = hcgui.build_groups(hcgui.parse(SAMPLE), "mini")
        self.assertEqual([g.name for g in spaces], ["home", "appshop", "atlas"])  # home holds a shell only
        self.assertEqual(hcgui.fallback_group(spaces, rigs), "space:appshop")

    def test_the_shown_terminals_group_wins(self):
        spaces, rigs = hcgui.build_groups(hcgui.parse(SAMPLE), "mini")
        self.assertEqual(hcgui.fallback_group(spaces, rigs, "space:home"), "space:home")
        self.assertEqual(hcgui.fallback_group(spaces, rigs, "rig:rig"), "rig:rig")
        self.assertEqual(hcgui.fallback_group(spaces, rigs, "space:gone"), "space:appshop")  # not listed: ignored

    def test_no_agent_anywhere_first_space_then_first_rig(self):
        spaces, rigs = hcgui.build_groups(hcgui.parse(ls(term("mini/t1", "/Users/x"), term("mini/t2"),
                                                         term("rig/t1", agent="claude-code"))), "mini")
        self.assertEqual(hcgui.fallback_group(spaces, rigs), "space:home")  # an agent on a rig does not count
        _, rigs = hcgui.build_groups(hcgui.parse(ls(term("rig/t1"), term("box/t2"))), "mini")
        self.assertEqual(hcgui.fallback_group([], rigs), "rig:box")
        self.assertEqual(hcgui.fallback_group([], []), "")

    def test_a_shell_with_a_status_counts_as_an_agent(self):
        spaces, rigs = hcgui.build_groups(hcgui.parse(ls(
            term("t1", "/Users/x"), term("t2", "/Users/x/dev/a"), term("t3", "/Users/x/dev/b", status="working"))),
            "mini")
        self.assertEqual(hcgui.fallback_group(spaces, rigs), "space:b")


class PromptInputTests(unittest.TestCase):
    def test_classify(self):
        c = hcgui.classify_space_input
        self.assertEqual(c("  "), ("empty", ""))
        self.assertEqual(c("atlas"), ("name", "atlas"))
        self.assertEqual(c(" my space "), ("name", "my space"))
        self.assertEqual(c("~/dev/foo"), ("folder", "~/dev/foo"))
        self.assertEqual(c("~"), ("folder", "~"))
        self.assertEqual(c("/opt/x"), ("folder", "/opt/x"))
        self.assertEqual(c("dev/foo")[0], "bad")       # relative: relative to what, on another machine?
        self.assertEqual(c("~bob/x")[0], "bad")
        self.assertEqual(c("~bob")[0], "bad")
        self.assertEqual(c("-x")[0], "bad")
        self.assertEqual(c("..")[0], "bad")
        self.assertEqual(c("a" * 41)[0], "bad")

    def test_valid_space_name(self):
        for good in ("a", "atlas-app", "v1.2", "my space", "x=y", "A_b"):
            self.assertTrue(hcgui.valid_space_name(good), good)
        for bad in ("", "a/b", "~x", "-x", ".", "..", "tab\tname", "é"):
            self.assertFalse(hcgui.valid_space_name(bad), bad)

    def test_probe_arg(self):
        self.assertEqual(hcgui.probe_arg("name", "foo"), "dev/foo")
        self.assertEqual(hcgui.probe_arg("folder", "~"), ".")
        self.assertEqual(hcgui.probe_arg("folder", "~/"), ".")
        self.assertEqual(hcgui.probe_arg("folder", "~/dev/foo"), "dev/foo")
        self.assertEqual(hcgui.probe_arg("folder", "/opt/x"), "/opt/x")

    def test_plan_folder(self):
        p = hcgui.plan_new_space
        self.assertEqual(p("folder", "~/dev/foo", "/Users/r", True), ("/Users/r/dev/foo", "", ""))
        self.assertEqual(p("folder", "~", "/Users/r", True), ("/Users/r", "", ""))
        self.assertEqual(p("folder", "/opt/x/", "/Users/r", True), ("/opt/x", "", ""))
        self.assertEqual(p("folder", "/opt/x", "", None), ("/opt/x", "", ""))  # could not ask: try it
        self.assertEqual(p("folder", "~/nope", "/Users/r", False), ("", "", "no folder ~/nope"))
        self.assertTrue(p("folder", "~/x", "", None)[2])  # ~ without a known home folder: say so, never guess

    def test_plan_name(self):
        p = hcgui.plan_new_space
        self.assertEqual(p("name", "foo", "/Users/r", True), ("/Users/r/dev/foo", "", ""))
        self.assertEqual(p("name", "foo", "/Users/r", False), ("/Users/r", "foo", ""))
        self.assertEqual(p("name", "foo", "/Users/r", None), ("/Users/r", "foo", ""))
        self.assertEqual(p("name", "foo", "", None), ("", "foo", ""))  # hc starts it in that machine's home

    def test_parse_probe(self):
        self.assertEqual(hcgui.parse_probe("/Users/r\ndir\n"), ("/Users/r", True))
        self.assertEqual(hcgui.parse_probe("/home/u/\nnone\n"), ("/home/u", False))
        for junk in ("", "dir\n", "relative\ndir\n", "/Users/r\nmaybe\n"):
            with self.assertRaises(ValueError):
                hcgui.parse_probe(junk)

    def test_probe_folder_calls_hc_exec(self):
        calls = []

        def fake(*args, **kw):
            calls.append(args)
            return "/Users/r\nnone\n"

        self.assertEqual(hcgui.probe_folder("mini", "dev/foo", fake), ("/Users/r", False))
        self.assertEqual(calls[-1][:5], ("exec", "--on", "mini", "/bin/sh", "-c"))
        self.assertEqual(calls[-1][-1], "dev/foo")
        hcgui.probe_folder(hcgui.LOCAL, "/opt", fake)
        self.assertEqual(calls[-1][:3], ("exec", "/bin/sh", "-c"))

    def test_probe_script_runs_in_sh(self):
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "dev"))
            os.mkdir(os.path.join(d, "dev", "foo"))
            for arg, want in (("dev/foo", True), ("dev/nope", False), (d, True), (".", True), ("/nonexistent", False)):
                out = subprocess.run(["/bin/sh", "-c", hcgui.PROBE, "mini", arg], capture_output=True, text=True,
                                     env={"HOME": d, "PATH": "/usr/bin:/bin"}).stdout
                self.assertEqual(hcgui.parse_probe(out), (d, want), arg)

    def test_home_dir_from_cwds(self):
        self.assertEqual(hcgui.home_dir_from_cwds(["/Users/r/dev/a", "/Users/r", "/tmp", "/home/o/x"]), "/Users/r")
        self.assertEqual(hcgui.home_dir_from_cwds(["/tmp", ""]), "")


class SidebarPlanTests(unittest.TestCase):
    def setUp(self):
        self.spaces, self.rigs = hcgui.build_groups(hcgui.parse(SAMPLE), "mini")

    def test_tall_layout_bottom_anchored(self):
        plan = hcgui.plan_sidebar(self.spaces, self.rigs, 40)
        self.assertEqual(plan[0][1].text, "spaces")
        self.assertEqual(max(y for y, _ in plan), 39)
        order = [r.kind for _, r in plan]
        self.assertNotIn("hint", order)  # no key hints: "?" lists the keys
        self.assertLess(order.index("rule"), order.index("agents"))
        self.assertEqual(order.count("agent"), 3)
        self.assertIn("servers", [r.text for _, r in plan])
        self.assertNotIn("rigs", [r.text for _, r in plan])
        ys = [y for y, _ in plan]
        self.assertEqual(len(ys), len(set(ys)))

    def test_the_list_of_keys_names_every_key_and_fits(self):
        lines = hcgui.help_lines(29, 40)
        text = "\n".join(lines)
        self.assertEqual(lines[0], " keys · any key closes")
        for line in (" ↑↓ j k  move", " enter   show it", " a       menu (right click)", " e       rename",
                     " d       delete, forget, end", " n       new terminal here", " s       new space",
                     " m       move to a space", " v       show/hide servers", " c       fold, then hide",
                     " o       open the strip", " q       hide", " z       zoom the view",
                     " ‹ back  click: zoom ends", " [ ] - = separator up/down",
                     " r       refresh", " ?       this list"):
            self.assertIn(line, lines)
        self.assertNotIn("quit", text)  # q hides the sidebar: its pane closes
        self.assertIsNone(re.search(r"\brigs?\b", text))
        self.assertTrue(all(hcgui.text_width(line) <= 29 for line in lines))
        with mock.patch.object(hcgui, "utf8_screen", return_value=False):  # as Screen.put draws them
            ascii_lines = [hcgui.glyph(line) for line in hcgui.help_lines(29, 40)]
            self.assertTrue(all(len(line) <= 29 and line.isascii() for line in ascii_lines))
            self.assertIn(" < back  click: zoom ends", ascii_lines)

    def test_the_list_of_keys_ends_with_the_status_dots(self):
        rows = hcgui.help_rows(29, 60)
        tail = [(r.text, r.dim, r.status, r.spans) for r in rows[-7:]]
        self.assertEqual(tail, [(" status dots", True, None, ()),
                                (" ●       red: blocked, error", False, "blocked", ((1, 1), (9, 3))),
                                (" ●       yellow: working", False, "working", ((1, 1), (9, 6))),
                                (" ●       green: done, to read", False, "done", ((1, 1), (9, 5))),
                                (" ●       blue: idle, no news", False, "idle", ((1, 1), (9, 4))),
                                (" ○       grey: no status", False, "", ((1, 1), (9, 4))),
                                (" spaces, servers: most urgent", True, None, ())])
        self.assertEqual([r.text for r in rows], hcgui.help_lines(29, 60))
        self.assertEqual((rows[0].dim, [r for r in rows[1:-7] if r.dim or r.status is not None]), (True, []))
        # each colour as dot_attr draws that status (STATUS_COLOR: 1 red, 3 yellow, 2 green, 4 blue; none dim)
        colours = {"red": 1, "yellow": 3, "green": 2, "blue": 4, "grey": 0}
        for status, _, word, _ in hcgui.DOT_HELP:
            self.assertEqual(hcgui.STATUS_COLOR.get(status, 0), colours[word], status)
        self.assertEqual(hcgui.STATUS_COLOR["error"], colours["red"])
        # the order of the list is the order summary_status takes the most urgent in
        self.assertEqual([s for s, *_ in hcgui.DOT_HELP[:-1]], [s for s in hcgui.STATUS_ORDER if s != "error"])
        self.assertTrue(all(hcgui.text_width(r.text) <= 29 for r in rows))  # every line fits 30 columns

    def test_the_status_dots_cut_on_a_narrow_pane(self):
        for width in range(0, 30):
            for row in hcgui.help_rows(width, 60):
                self.assertLessEqual(hcgui.text_width(row.text), width)
                for x, n in row.spans:
                    self.assertGreater(n, 0)
                    self.assertNotIn("…", row.text[x:x + n])  # the cut mark stays plain
                    self.assertLessEqual(x + n, len(row.text))
        red = next(r for r in hcgui.help_rows(11, 60) if r.status == "blocked")
        self.assertEqual((red.text, red.spans), (" ●       r…", ((1, 1), (9, 1))))
        self.assertEqual(next(r for r in hcgui.help_rows(9, 60) if r.status == "blocked").spans, ((1, 1),))
        short = hcgui.help_rows(29, 5)
        self.assertEqual([r.text for r in short][-1], " …")  # a short pane: the dots go first
        self.assertTrue(all(r.status is None for r in short))

    def test_the_list_of_keys_on_a_short_or_narrow_pane(self):
        self.assertEqual(hcgui.help_lines(29, 0), [])
        self.assertEqual(hcgui.help_lines(0, 10), [])
        short = hcgui.help_lines(29, 5)
        self.assertEqual(len(short), 5)
        self.assertEqual(short[-1], " …")
        self.assertTrue(all(hcgui.text_width(line) <= 10 for line in hcgui.help_lines(10, 40)))
        dots = len(hcgui.DOT_HELP) + 2  # their title, a line per colour, the note
        self.assertEqual(len(hcgui.help_lines(29, 60)), 1 + len(hcgui.help_entries()) + dots)
        self.assertEqual(len(hcgui.help_entries()), len(hcgui.KEY_HELP) + 3)  # the marks of the tests: ¹ ² ³

    def test_servers_section_is_always_there_for_add_server_while_shown(self):
        plan = hcgui.plan_sidebar(self.spaces, [], 40)
        rows = [(r.kind, r.text) for _, r in plan]
        at = rows.index(("header", "servers"))
        self.assertEqual(rows[at - 2:at + 2], [("plus", "new_space"), ("blank", ""), ("header", "servers"),
                                               ("plus", "add_rig")])
        hidden = [(r.kind, r.text) for _, r in hcgui.plan_sidebar(self.spaces, self.rigs, 40, servers=False)]
        self.assertNotIn(("header", "servers"), hidden)
        self.assertNotIn(("plus", "add_rig"), hidden)
        self.assertEqual(sum(1 for k, _ in hidden if k == "group"), len(self.spaces))
        self.assertEqual(hidden[:len(self.spaces) + 2][-1], ("plus", "new_space"))

    def test_no_hint_block_more_agent_rows_instead(self):
        spaces, rigs = many_agents(6)
        top = top_rows(spaces, rigs)
        # before: 4 hint lines took the bottom; now the rule, the header, a heading and all 6 agents fit in top + 9
        plan = hcgui.plan_sidebar(spaces, rigs, top + 9, 0)
        self.assertEqual(sum(1 for _, r in plan if r.kind == "agent"), 6)
        self.assertNotIn("more", [r.kind for _, r in plan])

    def test_small_height_keeps_all_groups(self):
        for h in range(top_rows(self.spaces, self.rigs), 18):
            plan = hcgui.plan_sidebar(self.spaces, self.rigs, h)
            self.assertEqual(sum(1 for _, r in plan if r.kind == "group"), 6, h)
            self.assertTrue(all(0 <= y < h for y, _ in plan), h)
            ys = [y for y, _ in plan]
            self.assertEqual(len(ys), len(set(ys)), h)

    def test_more_line_when_agents_cut(self):
        # each of the three agents is alone in its group (no headings): 2 lines below the top part hold one and "+2"
        plan = hcgui.plan_sidebar(self.spaces, self.rigs, 13)
        more = [r for _, r in plan if r.kind == "more"]
        shown = sum(1 for _, r in plan if r.kind == "agent")
        self.assertEqual(len(more), 1)
        self.assertEqual(more[0].count + shown, 3)
        self.assertTrue(more[0].text.startswith("+"))

    def test_cursor_agent_always_placed_when_one_group_has_many(self):
        spaces, rigs = many_agents(6)
        items = hcgui.selectable_items(spaces, rigs)
        top = top_rows(spaces, rigs)
        for h in range(top + 1, 24):  # from one free line below the spaces and rigs
            for cursor, item in enumerate(items):
                plan = hcgui.plan_sidebar(spaces, rigs, h, cursor)
                ys = [y for y, _ in plan]
                self.assertEqual(len(ys), len(set(ys)), (h, cursor))
                self.assertTrue(all(0 <= y < h for y in ys), (h, cursor))
                self.assertIn(cursor, [r.item for _, r in plan if r.kind in ("group", "plus", "agent")], (h, cursor))
                self.assertEqual(sum(1 for _, r in plan if r.kind == "group"), len(spaces) + len(rigs), (h, cursor))

    def test_window_keeps_its_group_heading(self):
        spaces, rigs = many_agents(6)
        plan = hcgui.plan_sidebar(spaces, rigs, 11, 2 + 4)  # cursor on the 5th agent
        kinds = [r.kind for _, r in plan]
        first_agent = kinds.index("agent")
        self.assertEqual(kinds[first_agent - 1], "agent_group")
        self.assertEqual(kinds[-1], "more")
        shown = sum(1 for k in kinds if k == "agent")
        self.assertEqual([r.count for _, r in plan if r.kind == "more"][0], 6 - shown)

    def test_short_screen_gives_up_the_rule_before_agents(self):
        spaces, rigs = many_agents(6)
        top = top_rows(spaces, rigs)
        plan = hcgui.plan_sidebar(spaces, rigs, top + 4, 0)  # the top lines + 4
        kinds = [r.kind for _, r in plan]
        self.assertNotIn("rule", kinds)
        self.assertIn("agent", kinds)
        plan = hcgui.plan_sidebar(spaces, rigs, top + 5, 0)
        self.assertEqual([r.kind for _, r in plan].count("rule"), 1)

    def test_no_line_for_agents_means_none_placed(self):
        spaces, rigs = many_agents(6)
        first_agent = [i.kind for i in hcgui.selectable_items(spaces, rigs)].index("agent")
        plan = hcgui.plan_sidebar(spaces, rigs, 3, first_agent)
        self.assertNotIn(first_agent, [r.item for _, r in plan])  # the sidebar then keeps the cursor off that row

    def test_tiny_heights_do_not_crash(self):
        for h in range(0, 8):
            for cursor in range(0, 8):
                plan = hcgui.plan_sidebar(self.spaces, self.rigs, h, cursor)
                self.assertTrue(all(0 <= y < h for y, _ in plan))

    def test_many_spaces_scroll_to_cursor(self):
        raw = ls(*[term(f"t{i}", f"/Users/x/dev/s{i:02d}") for i in range(30)])
        spaces, rigs = hcgui.build_groups(hcgui.parse(raw), "mini")
        plan = hcgui.plan_sidebar(spaces, rigs, 10, 25)
        self.assertIn(25, [r.item for _, r in plan if r.kind == "group"])

    def test_compact_plan_has_no_hints_and_keeps_the_cursor(self):
        spaces, rigs = many_agents(6)
        items = hcgui.selectable_items(spaces, rigs)
        for h in range(0, 30):
            for cursor in range(len(items)):
                plan = hcgui.plan_sidebar(spaces, rigs, h, cursor, compact=True)
                self.assertNotIn("hint", [r.kind for _, r in plan], (h, cursor))
                ys = [y for y, _ in plan]
                self.assertEqual(len(ys), len(set(ys)), (h, cursor))
                self.assertTrue(all(0 <= y < h for y in ys), (h, cursor))
                if h >= top_rows(spaces, rigs):  # the top part fits: every group is there, the cursor's agent too
                    self.assertEqual(sum(1 for _, r in plan if r.kind == "group"), len(spaces) + len(rigs),
                                     (h, cursor))
                    if h >= 1 + top_rows(spaces, rigs):
                        self.assertIn(cursor, [r.item for _, r in plan], (h, cursor))
        tall = hcgui.plan_sidebar(spaces, rigs, 40, 0, compact=True)
        self.assertEqual(sum(1 for _, r in tall if r.kind == "agent"), 6)


class SidebarFrameTests(unittest.TestCase):
    """The arrow lines ("‹" last, "›" above it in the strip), and the lines left for the list and a message."""

    def test_arrow_lines_at_every_height(self):
        for height in range(0, 61):
            for message in (False, True):
                for prompt in (False, True):
                    for strip in (False, True):
                        body, arrow_y, open_y, extra = hcgui.sidebar_frame(height, message, prompt, strip)
                        case = (height, message, prompt, strip)
                        # every line has one use
                        self.assertEqual(body + extra + (arrow_y >= 0) + (open_y >= 0), height, case)
                        self.assertEqual(arrow_y, height - 1 if height >= 2 else -1, case)
                        self.assertEqual(open_y, height - 2 if strip and height >= 3 else -1, case)
                        if height >= 1:
                            self.assertGreaterEqual(body, 1, case)  # never over the cursor's line
                        self.assertLessEqual(extra, 2 if prompt else 1 if message else 0, case)

    def test_message_and_prompt_lines(self):
        self.assertEqual(hcgui.sidebar_frame(0, True, True), (0, -1, -1, 0))
        self.assertEqual(hcgui.sidebar_frame(1, True, True), (1, -1, -1, 0))  # one line: the cursor's
        self.assertEqual(hcgui.sidebar_frame(2, True, False), (1, 1, -1, 0))  # the arrow wins over the message
        self.assertEqual(hcgui.sidebar_frame(3, True, False), (1, 2, -1, 1))
        self.assertEqual(hcgui.sidebar_frame(3, False, True), (1, 2, -1, 1))  # the typed line, no title
        self.assertEqual(hcgui.sidebar_frame(5, False, True), (2, 4, -1, 2))
        self.assertEqual(hcgui.sidebar_frame(24, False, False), (23, 23, -1, 0))
        self.assertEqual(hcgui.sidebar_frame(24, True, False), (22, 23, -1, 1))

    def test_strip_order_at_tiny_heights_cursor_then_hide_then_open(self):
        f = hcgui.sidebar_frame
        self.assertEqual(f(1, True, False, True), (1, -1, -1, 0))  # the cursor's line only
        self.assertEqual(f(2, True, False, True), (1, 1, -1, 0))  # then "‹"
        self.assertEqual(f(3, True, False, True), (1, 2, 1, 0))  # then "›"; no room for the message
        self.assertEqual(f(4, True, False, True), (1, 3, 2, 1))  # the message just above "›"
        self.assertEqual(f(24, False, False, True), (22, 23, 22, 0))

    def test_arrow_labels(self):
        self.assertEqual(hcgui.fold_label("open", 29), " ‹ fold")
        self.assertEqual(hcgui.fold_label("strip", 29), " ‹ hide")
        self.assertEqual(hcgui.open_label(29), " › open")
        self.assertEqual(hcgui.fold_label("strip", 7), " ‹ hide")
        self.assertEqual(hcgui.open_label(6), " ›")
        self.assertEqual(hcgui.fold_label("open", 2), " ‹")
        self.assertEqual(hcgui.open_label(1), "›")
        self.assertEqual(hcgui.fold_label("strip", 0), "‹")
        with mock.patch.object(hcgui, "utf8_screen", return_value=False):
            self.assertEqual(hcgui.glyph(hcgui.fold_label("open", 29)), " < fold")
            self.assertEqual(hcgui.glyph(hcgui.fold_label("strip", 29)), " < hide")
            self.assertEqual(hcgui.glyph(hcgui.open_label(29)), " > open")
            self.assertEqual(hcgui.glyph(hcgui.open_label(2)), " >")

    def test_sidebar_hit(self):
        item = hcgui.Item("group", "space:a", "")
        rows = {1: item, 3: hcgui.Item("agent", "space:a", "t1")}
        self.assertEqual(hcgui.sidebar_hit(9, 9, -1, rows), ("step", None))
        self.assertEqual(hcgui.sidebar_hit(9, 9, 8, rows), ("step", None))
        self.assertEqual(hcgui.sidebar_hit(8, 9, 8, rows), ("open", None))
        self.assertEqual(hcgui.sidebar_hit(8, 9, -1, rows), ("", None))  # no "›" line in the open sidebar
        self.assertEqual(hcgui.sidebar_hit(1, 9, 8, rows), ("item", item))
        self.assertEqual(hcgui.sidebar_hit(3, 9, 8, rows)[1].address, "t1")
        self.assertEqual(hcgui.sidebar_hit(2, 9, 8, rows), ("", None))
        self.assertEqual(hcgui.sidebar_hit(0, -1, -1, {}), ("", None))  # no arrows on a one-line screen
        self.assertEqual(hcgui.sidebar_hit(1, 1, -1, rows), ("step", None))  # an arrow's line is never a row
        self.assertEqual(hcgui.sidebar_hit(3, 4, 3, rows), ("open", None))
        # the usage lines (usage_ys): no rows, but told apart (a right click opens their menu)
        self.assertEqual(hcgui.sidebar_hit(6, 9, -1, rows, usage_ys=[5, 6, 7]), ("usage", None))
        self.assertEqual(hcgui.sidebar_hit(4, 9, -1, rows, usage_ys=[5, 6, 7]), ("", None))
        self.assertEqual(hcgui.sidebar_hit(9, 9, -1, rows, usage_ys=[5, 6, 7]), ("step", None))

    def test_c_steps_open_strip_hidden(self):
        self.assertEqual(hcgui.SIDEBAR_STATES, ("open", "strip", "hidden"))
        n = hcgui.next_sidebar_state
        self.assertEqual((n("open"), n("strip"), n("hidden")), ("strip", "hidden", "open"))
        self.assertEqual(n("junk"), "strip")  # junk counts as open


class TabLayoutTests(unittest.TestCase):
    def lines(self, layout, width):
        rows = [[" "] * width for _ in range(layout.rows)]
        for s in layout.segs:
            for i, c in enumerate(s.text):
                if 0 <= s.x + i < width and 0 <= s.y < layout.rows:
                    rows[s.y][s.x + i] = c
        return ["".join(r).rstrip() for r in rows]

    def test_all_fit_on_one_row(self):
        lay = hcgui.layout_tabs(["a", "bb"], 0, 40, 4)
        self.assertEqual(self.lines(lay, 40), [" ● a │ ● bb │ +"])
        self.assertEqual(lay.rows, 1)
        self.assertFalse(lay.left_cut or lay.right_cut)

    def test_wide_names_are_measured_in_columns(self):
        lay = hcgui.layout_tabs(["🚀 deploy", "api", "日本語"], 0, 40, 4)
        tabs = [s for s in lay.segs if s.kind in ("tab", "sep", "plus")]
        for a, b in zip(tabs, tabs[1:]):
            if a.y == b.y:
                self.assertEqual(a.x + hcgui.text_width(a.text), b.x, (a, b))
        third = next(s for s in lay.segs if s.kind == "tab" and s.index == 2)
        last = third.x + hcgui.text_width(third.text) - 1
        self.assertEqual(hcgui.hit_test(lay, last, third.y), ("tab", 2))

    def test_menu_after_a_wide_title(self):
        entries = hcgui.tab_menu_entries("space")
        segs = hcgui.tab_menu_segs("🚀🚀🚀🚀🚀🚀🚀", entries, 80)
        self.assertEqual(segs[0].kind, "title")
        self.assertGreater(segs[1].x, segs[0].x + hcgui.text_width(segs[0].text))

    def test_no_tabs(self):
        lay = hcgui.layout_tabs([], -1, 20, 3)
        self.assertEqual(self.lines(lay, 20), [" +"])
        self.assertEqual(hcgui.hit_test(lay, 1, 0), ("plus", -1))

    def test_hit_test_one_row(self):
        lay = hcgui.layout_tabs(["a", "bb"], 0, 40)
        self.assertEqual(hcgui.hit_test(lay, 0), ("tab", 0))
        self.assertEqual(hcgui.hit_test(lay, 4), ("tab", 0))
        self.assertIsNone(hcgui.hit_test(lay, 5))  # separator
        self.assertEqual(hcgui.hit_test(lay, 6), ("tab", 1))
        self.assertEqual(hcgui.hit_test(lay, 6 + 6 + 1 + 1), ("plus", -1))
        self.assertIsNone(hcgui.hit_test(lay, 39))
        self.assertIsNone(hcgui.hit_test(lay, 0, 1))  # no such row

    def test_dot_position(self):
        lay = hcgui.layout_tabs(["a", "bb"], 0, 40)
        tab = [s for s in lay.segs if s.kind == "tab"]
        self.assertEqual((tab[0].dot_x, tab[1].dot_x), (1, 7))
        self.assertEqual(tab[0].text[1], "●")

    def test_tabs_wrap_onto_further_rows(self):
        labels = ["alpha", "beta", "gamma", "delta", "eps"]
        lay = hcgui.layout_tabs(labels, 3, 22, 4)
        self.assertEqual(self.lines(lay, 22), [" ● alpha │ ● beta", " ● gamma │ ● delta", " ● eps │ +"])
        self.assertFalse(lay.left_cut or lay.right_cut)
        self.assertEqual(lay.rows, 3)
        self.assertTrue(all(s.end <= 22 for s in lay.segs))
        self.assertEqual(sorted(s.index for s in lay.segs if s.kind == "tab"), [0, 1, 2, 3, 4])

    def test_hit_test_wrapped_rows(self):
        lay = hcgui.layout_tabs(["alpha", "beta", "gamma", "delta", "eps"], 3, 22, 4)
        self.assertEqual(hcgui.hit_test(lay, 2, 0), ("tab", 0))
        self.assertEqual(hcgui.hit_test(lay, 12, 0), ("tab", 1))
        self.assertEqual(hcgui.hit_test(lay, 2, 1), ("tab", 2))
        self.assertEqual(hcgui.hit_test(lay, 12, 1), ("tab", 3))
        self.assertIsNone(hcgui.hit_test(lay, 9, 1))  # separator
        self.assertEqual(hcgui.hit_test(lay, 2, 2), ("tab", 4))
        self.assertEqual(hcgui.hit_test(lay, 9, 2), ("plus", -1))
        self.assertIsNone(hcgui.hit_test(lay, 2, 3))
        self.assertIsNone(hcgui.hit_test(lay, 20, 2))

    def test_plus_wraps_alone_when_the_row_is_full(self):
        lay = hcgui.layout_tabs(["abcdef", "ghijkl"], 0, 21, 3)
        self.assertEqual(self.lines(lay, 21), [" ● abcdef │ ● ghijkl", " +"])
        self.assertEqual(hcgui.hit_test(lay, 1, 1), ("plus", -1))

    def test_one_long_label_is_shortened_to_the_row(self):
        lay = hcgui.layout_tabs(["a-very-long-terminal-name", "b"], 0, 16, 3)
        first = [s for s in lay.segs if s.kind == "tab"][0]
        self.assertEqual(len(first.text), 16)
        self.assertTrue(first.text.rstrip().endswith("…"))

    def test_scrolls_only_when_all_rows_are_not_enough(self):
        labels = [f"terminal{i}" for i in range(8)]  # 13 columns each
        fits = hcgui.layout_tabs(labels, 7, 30, 5)   # 2 per row -> 4 rows + the "+"
        self.assertFalse(fits.left_cut or fits.right_cut)
        self.assertEqual(len([s for s in fits.segs if s.kind == "tab"]), 8)
        for rows in (1, 2, 3):
            for active in range(8):
                lay = hcgui.layout_tabs(labels, active, 30, rows)
                self.assertEqual(lay.rows, rows)
                self.assertTrue(any(s.kind == "tab" and s.index == active for s in lay.segs), (rows, active))
                plus = [s for s in lay.segs if s.kind == "plus"][0]
                self.assertEqual((plus.y, plus.end), (0, 30))
                self.assertEqual(hcgui.hit_test(lay, 28, 0), ("plus", -1))
                self.assertTrue(all(0 <= s.x and s.end <= 30 and 0 <= s.y < rows for s in lay.segs))
                for s in lay.segs:  # every visible tab is whole and clickable where it is drawn
                    if s.kind == "tab":
                        self.assertEqual(hcgui.hit_test(lay, s.x + 2, s.y), ("tab", s.index))
            first = hcgui.layout_tabs(labels, 0, 30, rows)
            last = hcgui.layout_tabs(labels, 7, 30, rows)
            self.assertEqual((first.left_cut, first.right_cut), (False, True))
            self.assertEqual((last.left_cut, last.right_cut), (True, False))
            self.assertEqual([s.text for s in first.segs if s.kind == "cut"], ["›"])
            self.assertEqual([s.text for s in last.segs if s.kind == "cut"], ["‹"])

    def test_tiny_widths(self):
        for w in range(0, 12):
            for rows in (1, 2, 5):
                lay = hcgui.layout_tabs(["alpha", "beta"], 1, w, rows)
                self.assertIsInstance(lay.segs, list)
                self.assertLessEqual(lay.rows, rows)

    def test_tab_hint_shortens_step_by_step(self):
        hints = hcgui.TAB_HINTS
        self.assertEqual(hcgui.tab_hint(200), hints[0])
        for i in range(len(hints) - 1):
            self.assertEqual(hcgui.tab_hint(len(hints[i]) - 1), hints[i + 1])
        self.assertEqual(hcgui.tab_hint(len(hints[-1]) - 1), "")
        self.assertEqual(hcgui.tab_hint(-5), "")
        self.assertTrue(all("z zoom" in h and "⌘" not in h for h in hints))

    def test_tab_hint_without_a_sidebar_names_its_key(self):
        alone = hcgui.TAB_HINTS_ALONE
        self.assertEqual(hcgui.tab_hint(200, True), alone[0])
        self.assertTrue(all(h.startswith("c sidebar") for h in alone[:-1]))
        self.assertEqual(alone[-1], hcgui.TAB_HINTS[-1])  # the way back from a zoom still goes last
        for i in range(len(alone) - 1):
            self.assertEqual(hcgui.tab_hint(len(alone[i]) - 1, True), alone[i + 1])
        self.assertEqual(hcgui.tab_hint(len(alone[-1]) - 1, True), "")

    def test_opener_shifts_the_tabs_and_is_hit_first(self):
        plain = hcgui.layout_tabs(["alpha", "beta"], 0, 30, 2)
        lay = hcgui.with_opener(hcgui.layout_tabs(["alpha", "beta"], 0, 29, 2))
        self.assertEqual(self.lines(lay, 31), ["›" + line for line in self.lines(plain, 30)])
        self.assertEqual(hcgui.hit_test(lay, 0, 0), ("open", -1))
        self.assertEqual(hcgui.hit_test(lay, 1, 0), ("tab", 0))
        self.assertEqual(hcgui.hit_test(plain, 0, 0), ("tab", 0))  # with a sidebar the first cell is a tab's
        self.assertIsNone(hcgui.hit_test(lay, 0, 1))  # "›" is on the first row only
        wrapped = hcgui.with_opener(hcgui.layout_tabs(["alpha", "beta", "gamma"], 2, 20, 3))
        self.assertEqual(self.lines(wrapped, 21), ["› ● alpha │ ● beta", "  ● gamma │ +"])
        self.assertEqual(hcgui.hit_test(wrapped, 1, 1), ("tab", 2))
        self.assertEqual(hcgui.with_opener(hcgui.TabLayout([], 0)).rows, 1)

    def test_tab_bar_rows(self):
        self.assertEqual(hcgui.tab_bar_rows(0), (0, -1))
        self.assertEqual(hcgui.tab_bar_rows(1), (1, -1))   # one row: tabs only
        self.assertEqual(hcgui.tab_bar_rows(2), (1, 1))    # tabs + hints
        self.assertEqual(hcgui.tab_bar_rows(5), (4, 4))    # a tenth of a 50-row window

    def test_tab_info(self):
        tab = {"address": "mini/t5", "cwd": "/Users/r/dev/atlas", "agent": "claude-code", "status": "idle"}
        self.assertEqual(hcgui.tab_info(tab), "Claude Code · ~/dev/atlas · idle")  # no hc id; the product's name
        self.assertEqual(hcgui.tab_info({"address": "t1", "cwd": "/Users/r", "agent": "zsh"}), "zsh · ~")
        self.assertEqual(hcgui.tab_info({"address": "t1", "cwd": "/tmp", "agent": "node"}), "node · /tmp")
        long = dict(tab, cwd="/private/tmp/some/very/long/folder/name/that/does/not/fit/work")
        self.assertEqual(hcgui.tab_info(long, 40), "Claude Code · …/does/not/fit/work · idle")
        self.assertLessEqual(len(hcgui.tab_info(long, 40)), 40)
        self.assertEqual(hcgui.tab_info(long, 25), "Claude Code · idle")  # no room for a folder
        self.assertEqual(hcgui.tab_info(tab, with_id=True), "Claude Code · ~/dev/atlas · idle · mini/t5")
        self.assertEqual(hcgui.tab_info(long, 36, True), "Claude Code · idle · mini/t5")  # the folder goes first
        # narrower still: the part before the id is cut, never the id (the one thing the click adds; review)
        working = dict(tab, status="working")
        self.assertEqual(hcgui.tab_info(working, 33, True), "Claude Code · working · mini/t5")
        self.assertEqual(hcgui.tab_info(working, 30, True), "Claude Code · worki… · mini/t5")
        self.assertEqual(hcgui.tab_info(working, 20, True), "Claude Co… · mini/t5")
        self.assertEqual(hcgui.tab_info(working, 11, True), "mini/t5")
        self.assertEqual(hcgui.tab_info(working, 5, True), "mini…")
        for room in range(1, 60):
            line = hcgui.tab_info(working, room, True)
            self.assertLessEqual(hcgui.text_width(line), room, room)
            if room >= 8:
                self.assertTrue(line.endswith("mini/t5"), (room, line))
        self.assertEqual(hcgui.tab_info(working, 20), "Claude Code · working")  # no id: the caller cuts the end
        self.assertEqual(hcgui.short_folder("/home/u"), "~")

    def test_info_row(self):
        tab = {"address": "mini/t5", "cwd": "/Users/r/dev/atlas", "agent": "claude-code", "status": "idle"}
        row = hcgui.info_row
        self.assertEqual(row("atlas", tab, 60, False), ("Claude Code · ~/dev/atlas · idle", ""))  # no name, no id
        self.assertEqual(row("atlas", None, 60, False), ("", ""))  # nothing shown: an empty row
        left, hint = row("atlas", tab, 120, True)  # after a click: the name first, the id, and the widest hint
        self.assertEqual((left, hint), ("atlas · Claude Code · ~/dev/atlas · idle · mini/t5", hcgui.TAB_HINTS[0]))
        left, hint = row("atlas", tab, 70, True)  # the whole line kept, a shorter hint beside it
        self.assertEqual((left, hint), ("atlas · Claude Code · ~/dev/atlas · idle · mini/t5", "←→ switch  z zoom"))
        left, hint = row("atlas", tab, 45, True)  # no hint beside the whole line: the folder gives way for one
        self.assertEqual((left, hint), ("atlas · Claude Code · idle · mini/t5", "z zoom"))
        self.assertLessEqual(len(left) + 2 + len(hint), 45)
        self.assertEqual(row("atlas", None, 40, True), ("atlas", hcgui.TAB_HINTS[1]))  # nothing shown: name, hint
        left, hint = row("atlas", tab, 20, True)  # too narrow for anything else: cut, no hint
        self.assertEqual(hint, "")
        self.assertLessEqual(hcgui.text_width(left), 20)
        self.assertEqual(row("", tab, 120, True)[0], "Claude Code · ~/dev/atlas · idle · mini/t5")  # no name
        paid = dict(tab, account="Team plan", mark="²")  # the subscription it runs on, at the end, after a click
        self.assertEqual(row("atlas", paid, 120, True)[0],
                         "atlas · Claude Code · ~/dev/atlas · idle · mini/t5 · Team plan ²")
        self.assertEqual(row("atlas", paid, 60, False)[0], "Claude Code · ~/dev/atlas · idle")  # not without one
        left, hint = row("atlas", paid, 50, True)  # narrow: the folder goes, the subscription stays
        self.assertTrue(left.endswith("· Team plan ²"), left)
        self.assertLessEqual(hcgui.text_width(left) + (len(hint) + 2 if hint else 0), 50)

    def test_snapshot_names_the_subscription_of_claude_code_tabs(self):
        terms = [hcgui.Term("mini/t1", "mini", "", "claude-code", "idle", "/x"),
                 hcgui.Term("mini/t2", "mini", "", "zsh", "", "/x")]
        group = hcgui.Group("space:x", "x", "space", "mini", "", terms=terms)
        infos = {"mini/t1": hcgui.Info(account="work"), "mini/t2": hcgui.Info(account="work"),
                 "mini/t9": hcgui.Info(account="personal")}
        other = hcgui.Term("mini/t9", "mini", "", "claude-code", "idle", "/y")  # in another space
        everything = [*terms, other]
        with mock.patch.object(hcgui, "ACCOUNT_MARKS", {}):
            snap = hcgui.make_snapshot(group, 0.0, infos=infos, names={"account:work": "Team plan"},
                                       everything=everything)
            self.assertEqual([tb["account"] for tb in snap["tabs"]], ["Team plan", ""])  # a shell has none
            self.assertEqual(hcgui.make_snapshot(group, 0.0, infos=infos, everything=everything)["tabs"][0]["account"],
                             "work")
            # one subscription in sight: no name (owner, 24 Nov: too much to say it everywhere)
            self.assertEqual(hcgui.make_snapshot(group, 0.0, infos=infos, everything=terms)["tabs"][0]["account"], "")
            # the shared server's unlabelled session (its ³ mark) is another login: the name shows
            shared = hcgui.Term("box/t1", "box", "", "claude-code", "idle", "/z", mark="³")
            self.assertEqual(hcgui.make_snapshot(group, 0.0, infos=infos, everything=[*terms, shared])["tabs"][0]
                             ["account"], "work")
        with mock.patch.object(hcgui, "ACCOUNT_MARKS", {"work": "¹", "personal": "²"}):  # marks name two
            self.assertEqual(hcgui.make_snapshot(group, 0.0, infos=infos, everything=terms)["tabs"][0]["account"],
                             "work")

    def test_hc_claude_counts_as_claude_code(self):
        term = hcgui.Term("mini/t3", "mini", "", "claude", "", "/x")  # `hc run claude` before its first report
        self.assertEqual(hcgui.with_foreground([term], {})[0].agent, hcgui.CLAUDE_AGENT)


class StateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = Path(self._tmp.name) / "state"
        self.addCleanup(self._tmp.cleanup)

    def test_atomic_write_and_read(self):
        hcgui.write_atomic(self.state / "target", "t5\n")
        self.assertEqual(hcgui.current_target(self.state), "t5")
        self.assertEqual([p.name for p in self.state.iterdir()], ["target"])
        self.assertEqual(hcgui.read_text(self.state / "missing"), "")

    def test_a_failed_atomic_write_leaves_no_temp_file(self):
        (self.state / "taken").mkdir(parents=True)  # a folder where the file should go: os.replace fails
        with self.assertRaises(OSError):
            hcgui.write_atomic(self.state / "taken", "hidden\n")
        self.assertEqual([p.name for p in self.state.iterdir()], ["taken"])  # no .taken.<pid>.<tid>.tmp left
        self.assertTrue((self.state / "taken").is_dir())

    def test_last_round_trip(self):
        self.assertEqual(hcgui.read_last(self.state), {})
        hcgui.write_last({"space:a": "mini/t5"}, self.state)
        self.assertEqual(hcgui.read_last(self.state), {"space:a": "mini/t5"})
        (self.state / "last.json").write_text("garbage")
        self.assertEqual(hcgui.read_last(self.state), {})

    def test_remember_keeps_other_windows_entries(self):
        hcgui.write_last({"space:a": "t1"}, self.state)
        self.assertEqual(hcgui.remember("space:b", "t2", self.state), {"space:a": "t1", "space:b": "t2"})
        self.assertEqual(hcgui.read_last(self.state), {"space:a": "t1", "space:b": "t2"})

    def test_panes(self):
        hcgui.write_atomic(self.state / "panes", "side=A-1\ntabs=B-2\nview=C-3\n")
        self.assertEqual(hcgui.read_panes(self.state), {"side": "A-1", "tabs": "B-2", "view": "C-3"})
        self.assertEqual(hcgui.read_panes(self.state / "nope"), {})

    def test_sidebar_state_file_and_the_old_collapsed_file(self):
        read = hcgui.read_sidebar_state
        self.assertEqual(read(self.state), "open")  # nothing yet
        hcgui.write_atomic(self.state / "collapsed", "1\n")  # an older install, folded
        self.assertEqual(read(self.state), "strip")
        hcgui.write_atomic(self.state / "collapsed", "0\n")
        self.assertEqual(read(self.state), "open")
        hcgui.write_atomic(self.state / "collapsed", "1\n")
        for value in ("open", "strip", "hidden"):
            hcgui.write_sidebar_state(value, self.state)
            self.assertEqual(read(self.state), value)  # once "sidebar" exists, "collapsed" is not read
        self.assertEqual((self.state / "sidebar").read_text(), "hidden\n")
        self.assertEqual((self.state / "collapsed").read_text(), "1\n")  # left as it was
        for junk in ("junk\n", "", "Hidden\n"):
            hcgui.write_atomic(self.state / "sidebar", junk)
            self.assertEqual(read(self.state), "open", junk)  # junk is open, not the old file's strip

    def test_parse_sidebar_state(self):
        p = hcgui.parse_sidebar_state
        self.assertEqual([p(None, "1"), p(None, "0"), p(None, ""), p(None, "x")], ["strip", "open", "open", "open"])
        self.assertEqual([p("hidden", "1"), p("strip", ""), p("open", "1"), p("", "1")],
                         ["hidden", "strip", "open", "open"])

    def test_sidebar_alive_and_only_its_own_pid_file_removed(self):
        self.state.mkdir(parents=True)
        self.assertFalse(hcgui.sidebar_alive(self.state))  # no file
        for junk in ("", "junk", "0", "-1"):  # 0 and -1 would address process groups
            hcgui.write_atomic(self.state / "sidebar.pid", junk + "\n")
            self.assertFalse(hcgui.sidebar_alive(self.state), junk)
        hcgui.write_atomic(self.state / "sidebar.pid", f"{os.getpid()}\n")
        self.assertTrue(hcgui.sidebar_alive(self.state))
        dead = dead_pid()
        hcgui.write_atomic(self.state / "sidebar.pid", f"{dead}\n")  # ended by a hangup: the file stayed
        self.assertFalse(hcgui.sidebar_alive(self.state))
        hcgui.remove_own_pid(self.state)
        self.assertTrue((self.state / "sidebar.pid").exists())  # another sidebar's file is never touched
        hcgui.write_atomic(self.state / "sidebar.pid", f"{os.getpid()}\n")
        hcgui.remove_own_pid(self.state)
        self.assertFalse((self.state / "sidebar.pid").exists())
        hcgui.remove_own_pid(self.state)  # twice is fine

    def test_tab_engine_wanted(self):
        w = hcgui.tab_engine_wanted
        self.assertFalse(w(True, 100.0, True))  # a live sidebar: never
        self.assertFalse(w(False, 0.0, False))  # a normal start: the sidebar is on its way
        self.assertFalse(w(False, hcgui.ENGINE_GRACE - 0.1, False))
        self.assertTrue(w(False, hcgui.ENGINE_GRACE, False))
        self.assertTrue(w(False, 0.0, True))  # hidden on purpose: at once
        self.assertEqual(hcgui.ENGINE_GRACE, 3.0)

    def test_snapshot_format_and_round_trip(self):
        spaces, _ = hcgui.build_groups(hcgui.parse(SAMPLE), "mini")
        hcgui.write_snapshot(spaces[2], self.state, now=1000.0)
        snap = hcgui.read_snapshot(self.state, now=1001.0)
        self.assertEqual(sorted(snap), ["cwd", "group", "kind", "machine", "name", "names", "ordered", "panes", "server",
                                        "shown", "shown_title", "tabs", "title", "ts"])
        self.assertEqual((snap["server"], snap["shown"], snap["shown_title"]), ("mini", "", "hcGUI"))
        self.assertEqual(snap["group"], "space:atlas")
        self.assertEqual((snap["name"], snap["title"]), ("atlas", "atlas"))  # no display name: the name
        self.assertEqual(snap["kind"], "space")
        self.assertEqual(snap["machine"], "mini")
        self.assertEqual(snap["cwd"], "/Users/x/dev/atlas")
        self.assertEqual(snap["tabs"][0], {"address": "mini/t5", "label": "atlas", "status": "idle",
                                           "agent": "claude-code", "cwd": "/Users/x/dev/atlas", "server": "mini",
                                           "mark": "", "own": "atlas", "ends": [], "account": ""})
        self.assertEqual(snap["names"], {})  # no terminal list given
        self.assertEqual([t["label"] for t in snap["tabs"]], ["atlas", "zz"])

    def test_snapshot_stale_missing_broken(self):
        self.assertIsNone(hcgui.read_snapshot(self.state))
        hcgui.write_snapshot(None, self.state, now=1000.0)
        self.assertIsNotNone(hcgui.read_snapshot(self.state, now=1000.0 + 1))
        self.assertIsNone(hcgui.read_snapshot(self.state, now=1000.0 + hcgui.SNAPSHOT_MAX_AGE + 1))
        (self.state / "tabs.json").write_text("{broken")
        self.assertIsNone(hcgui.read_snapshot(self.state, now=1000.0))
        (self.state / "tabs.json").write_text(json.dumps({"ts": "x", "tabs": []}))
        self.assertIsNone(hcgui.read_snapshot(self.state, now=1000.0))
        (self.state / "tabs.json").write_text(json.dumps({"ts": 1000.0, "tabs": [1, {"address": "t1"}, {}]}))
        self.assertEqual(hcgui.read_snapshot(self.state, now=1000.0)["tabs"], [{"address": "t1"}])

    def test_show_writes_target_and_bumps_gen(self):
        hcgui.show("mini/t5", self.state)
        first = (self.state / "gen").read_text()
        self.assertEqual(hcgui.current_target(self.state), "mini/t5")
        time.sleep(0.001)
        hcgui.show("mini/t6", self.state)
        self.assertNotEqual((self.state / "gen").read_text(), first)

    def test_show_again_bumps_when_nothing_is_attached(self):
        hcgui.show("t5", self.state)
        first = (self.state / "gen").read_text()
        time.sleep(0.001)
        hcgui.show("t5", self.state)  # the view is waiting (detached): it must attach again
        self.assertNotEqual((self.state / "gen").read_text(), first)

    def test_attach_pid_needs_pid_file_loop_and_command(self):
        # our own pid is a python process, not an attach: it must never be signalled
        hcgui.write_atomic(self.state / "view.pid", f"{os.getpid()}\n")
        hcgui.write_atomic(self.state / "view.loop", f"{os.getppid()}\n")
        self.assertEqual(hcgui.attach_pid(self.state), 0)
        hcgui.end_current_attach(self.state)  # would kill the test run if the check failed
        hcgui.write_atomic(self.state / "view.pid", "garbage\n")
        self.assertEqual(hcgui.attach_pid(self.state), 0)
        (self.state / "view.loop").unlink()
        self.assertEqual(hcgui.attach_pid(self.state), 0)

    def test_attach_pid_only_for_a_child_of_this_views_loop(self):
        folder = Path(self._tmp.name) / "bin"
        folder.mkdir()
        stub = folder / "hc"
        stub.write_text("#!/bin/sh\nwhile :; do sleep 0.1; done\n")
        stub.chmod(0o755)
        proc = subprocess.Popen([str(stub), "attach", "t1"])  # an attach, but this test is its parent
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        time.sleep(0.2)
        hcgui.write_atomic(self.state / "view.pid", f"{proc.pid}\n")
        hcgui.write_atomic(self.state / "view.loop", "1\n")  # another loop's attach: hands off
        self.assertEqual(hcgui.attach_pid(self.state), 0)
        hcgui.end_current_attach(self.state)
        self.assertIsNone(proc.poll())
        hcgui.write_atomic(self.state / "view.loop", f"{os.getpid()}\n")
        self.assertEqual(hcgui.attach_pid(self.state), proc.pid)
        hcgui.write_atomic(self.state / "target", "t1\n")
        before = mtime_ns(self.state / "gen")
        hcgui.show("t1", self.state)  # already attached to it: nothing is restarted
        self.assertEqual(mtime_ns(self.state / "gen"), before)
        self.assertIsNone(proc.poll())
        hcgui.show("t2", self.state)
        self.assertEqual(proc.wait(timeout=5), -signal.SIGTERM)

    def test_attach_regex(self):
        for command in ("/Users/x/.local/bin/hc attach t5", "hc attach mini/t5", "herdr-core attach t1",
                        "/bin/sh /tmp/x/hc attach t1"):
            self.assertTrue(hcgui.ATTACH_RE.search(command), command)
        for command in ("/usr/bin/python3 hcgui.py sidebar", "hc ls --json", "vim hcattach", "xhc attach t1",
                        "hc attachments"):
            self.assertFalse(hcgui.ATTACH_RE.search(command), command)

    def test_new_shell_args_label_and_prefix(self):
        calls = []

        def fake(*args, **kw):
            calls.append(args)
            return json.dumps({"address": "t9"})

        self.assertEqual(hcgui.new_shell("mini", "/Users/x/dev/a", self.state, "a", fake), "mini/t9")
        self.assertEqual(calls[-1], ("run", "--bg", "--json", "--no-parent", "--on", "mini", "--cwd",
                                     "/Users/x/dev/a", "--label", "space=a"))
        self.assertEqual(hcgui.new_shell(hcgui.LOCAL, "", self.state, runner=fake), "t9")
        self.assertEqual(calls[-1], ("run", "--bg", "--json", "--no-parent"))
        self.assertEqual(hcgui.new_shell("rig", "", self.state, runner=lambda *a, **k: '{"address": "rig/t3"}'),
                         "rig/t3")
        self.assertTrue((self.state / "poke").exists())
        for junk in ("{}", "[]", "null"):
            with self.assertRaises(ValueError):
                hcgui.new_shell("mini", "", self.state, runner=lambda *a, **k: junk)

    def test_fetch_infos_never_raises(self):
        def fake(*args, **kw):
            address = args[1]
            if address == "t2":
                raise subprocess.CalledProcessError(3, "hc", stderr="gone")
            if address == "t3":
                return "junk"
            if address == "t4":
                raise RuntimeError("anything")
            return json.dumps({"labels": {"space": "s"}, "parent": "t0"})

        got = hcgui.fetch_infos(["t1", "t2", "t3", "t4", "mini/t5"], fake)
        self.assertEqual(got, {"t1": hcgui.Info("s", "t0"), "t2": None, "t3": None, "t4": None,
                               "mini/t5": hcgui.Info("s", "mini/t0")})
        self.assertEqual(hcgui.fetch_infos([], fake), {})


def mtime_ns(path):
    return path.stat().st_mtime_ns if path.exists() else 0


def dead_pid():
    """The pid of a process that has ended (and been reaped): a stand-in for a sidebar that is gone."""
    proc = subprocess.Popen(["/usr/bin/true"])
    proc.wait()
    return proc.pid


def wait_for(condition, timeout=6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


class MiscTests(unittest.TestCase):
    def test_wide_characters_count_two_columns(self):
        self.assertEqual([hcgui.cell_width(c) for c in "a日🚀é́…●"], [1, 2, 2, 1, 0, 1, 1])
        self.assertEqual(hcgui.text_width("日本語ab"), 8)
        self.assertEqual(hcgui.fit_columns("日本語ab", 5), "日本")  # a wide character is never cut in half
        self.assertEqual(hcgui.fit_columns("日本語ab", 7), "日本語a")
        self.assertEqual(hcgui.fit_columns("🚀rocket", 3), "🚀r")
        self.assertEqual(hcgui.fit_columns("abc", 2), "ab")
        self.assertEqual(hcgui.fit_columns("日本", 0), "")
        self.assertEqual(hcgui.fit_columns("日本", -1), "")
        self.assertEqual(hcgui.clip("日本語プロジェクト", 7), "日本語…")
        self.assertEqual(hcgui.clip("日本語", 6), "日本語")
        self.assertEqual(hcgui.clip("日本語", 1), "")

    def test_glyph_and_clip(self):
        self.assertEqual(hcgui.clip("abcdef", 4), "abc…")
        self.assertEqual(hcgui.clip("abc", 4), "abc")
        self.assertEqual(hcgui.clip("abc", 0), "")
        self.assertEqual(hcgui.clip("abc", 1), "a")
        self.assertEqual(hcgui.glyph("abc"), "abc")
        with mock.patch.object(hcgui, "utf8_screen", return_value=False):
            self.assertEqual(hcgui.glyph("› ● a │ é"), "> * a | ?")
        with mock.patch.object(hcgui, "utf8_screen", return_value=True):
            self.assertEqual(hcgui.glyph("› ●"), "› ●")

    def test_setup_locale_survives_an_unknown_locale(self):
        code = ("import hcgui, locale; hcgui.setup_locale(); "
                "print(locale.nl_langinfo(locale.CODESET), hcgui.glyph('›') == '›')")
        for value in ("xx_YY.UTF-8", "C", "nonsense"):
            env = dict(os.environ, LANG=value, LC_ALL=value, PYTHONDONTWRITEBYTECODE="1")
            out = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stdout.split(), ["UTF-8", "True"], value)

    def test_describe_error(self):
        exc = subprocess.CalledProcessError(1, "hc", stderr="boom\nmore")
        self.assertEqual(hcgui.describe_error(exc), "boom")
        real = ('{"error":{"hint":"check the program name and cwd","kind":"spawn_failed",'
                '"message":"cannot start \\"/bin/zsh\\": No such file or directory"}}\n')
        exc = subprocess.CalledProcessError(1, "hc", stderr=real)
        self.assertEqual(hcgui.describe_error(exc), 'cannot start "/bin/zsh": No such file or directory')
        exc = subprocess.CalledProcessError(1, "hc", stderr='{"error":{"kind":"not_found"}}')
        self.assertEqual(hcgui.describe_error(exc), "not_found")
        self.assertEqual(hcgui.describe_error(subprocess.CalledProcessError(3, "hc", stderr="")), "hc exit 3")
        self.assertEqual(hcgui.describe_error(subprocess.CalledProcessError(3, "hc", stderr="[1]")), "[1]")
        self.assertEqual(hcgui.describe_error(subprocess.TimeoutExpired("hc", 5)), "hc did not answer")
        self.assertEqual(hcgui.describe_error(FileNotFoundError()), "hc not found")
        self.assertEqual(hcgui.describe_error(ValueError()), "ValueError")
        self.assertEqual(hcgui.describe_error(ValueError("unexpected hc ls output")), "unexpected hc ls output")

    def test_env_int(self):
        with mock.patch.dict(os.environ, {"X_HCGUI": "junk"}):
            self.assertEqual(hcgui.env_int("X_HCGUI", 30, 10, 200), 30)
        with mock.patch.dict(os.environ, {"X_HCGUI": "500"}):
            self.assertEqual(hcgui.env_int("X_HCGUI", 30, 10, 200), 200)


class FakeScr:
    """Stands in for a curses window: records what is drawn where."""

    def __init__(self, height, width):
        self.height, self.width = height, width
        self.cells = {}
        self.typed = []  # keys typed ahead, read by getch in nodelay mode (drain_keys, read_paste)

    def getmaxyx(self):
        return (self.height, self.width)

    def nodelay(self, flag):
        pass

    def timeout(self, ms):
        pass

    def getch(self):
        return self.typed.pop(0) if self.typed else -1

    def unget(self, key):
        self.typed.insert(0, key)

    def erase(self):
        self.cells = {}

    def refresh(self):
        pass

    def addnstr(self, y, x, text, n, attr=0):
        for i, c in enumerate(text[:n]):
            self.cells[(y, x + i)] = (c, attr)

    def line(self, y):
        return "".join(self.cells.get((y, x), (" ", 0))[0] for x in range(self.width)).rstrip()

    def lines(self):
        return [self.line(y) for y in range(self.height)]

    def reversed_rows(self):
        return sorted({y for (y, _), (_, attr) in self.cells.items() if attr & hcgui.curses.A_REVERSE})


def columns(text):
    """Screen columns of text as a terminal draws it, worked out apart from hcgui: a wide character takes two."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


class WideScr(FakeScr):
    """A FakeScr that lays text out as a terminal does: a wide character (CJK, emoji) takes two cells, and curses'
    n counts characters, not columns, so text that runs past the right edge wraps onto the next line. Every cell
    drawn in the last column or past it is kept in `spilled` (Screen promises the last column stays empty)."""

    def __init__(self, height, width):
        super().__init__(height, width)
        self.spilled = []

    def addnstr(self, y, x, text, n, attr=0):
        for c in text[:n]:
            w = columns(c)
            if x + w > self.width:
                y, x = y + 1, 0
            if x + w > self.width - 1:
                self.spilled.append((y, x, c))
            self.cells[(y, x)] = (c, attr)
            if w == 2:
                self.cells[(y, x + 1)] = ("", attr)
            x += w


def exec_json(code, stderr="", stdout="", timed_out=False):
    """What `hc exec --json` prints (herdr-core 0.1.21's ExecResult, the output base64)."""
    import base64
    return json.dumps({"code": code, "ms": 9, "signal": None, "stderr": base64.b64encode(stderr.encode()).decode(),
                       "stdout": base64.b64encode(stdout.encode()).decode(), "timed_out": timed_out,
                       "truncated": False})


def hc_error(kind, message="x", code=1):
    return subprocess.CalledProcessError(code, "hc", stderr=json.dumps({"error": {"kind": kind, "message": message}}))


class FakeHc:
    """Answers `hc ls --json`, `hc get`, `hc run`, `hc label`, `hc exec`, `hc keep/kill/wait/rm`, `hc machine
    ls/rm` and `hc put --json` from a small table, the way herdr-core 0.1.21 answered them in an isolated core: keep
    on a finished terminal is "invalid_params", rm of a live one is "live", anything about a removed one
    "not_found", a kill ends the children that die with their parent, and a put over 8 MB is "invalid_params"
    (exit 6); a put lands beside the terminal with spaces made "_"."""

    def __init__(self, terms, infos=None, machines=()):
        self.terms = list(terms)
        self.infos = dict(infos or {})
        self.machines = list(machines)
        self.finished = {}  # address -> the terminal, ended but not removed (hc ls leaves it out)
        self.calls = []
        self.fail = ""
        self.dirs = set()
        # `hc exec --json` of the keychain check and of the dev servers: (exit code, stderr) and DEV_SCRIPT's output;
        # of the 5-hour usage: USAGE_SCRIPT's output (no files: nothing), or None for an exec that fails
        self.keychain = (0, 'Keychain "/Users/x/Library/Keychains/login.keychain-db" no-timeout\n')
        self.lsof = ""
        self.usage = ""
        self.puts = []  # (address, local path, its size, its first bytes) of each `hc put`
        self.put_answer = None  # a put's stdout instead of the JSON it would print (junk, for the tests)
        self.put_error = None  # (kind, message, exit code) a put fails with

    def find(self, address):
        return next((t for t in self.terms if t["address"] == address), None)

    def end(self, address):
        t = self.find(address)
        if t is None:
            return
        self.terms.remove(t)
        self.finished[address] = t
        for child, info in list(self.infos.items()):
            if info.get("parent") == address and info.get("dies", True):
                self.end(child)

    def __call__(self, *args, **kw):
        self.calls.append(args)
        if self.fail:
            raise subprocess.CalledProcessError(1, "hc", stderr=self.fail)
        if args[:2] == ("ls", "--json"):
            return json.dumps({"terminals": self.terms})
        if args[:3] == ("machine", "ls", "--json"):  # a machine: its name, or (name, ssh target)
            pairs = [(m, m) if isinstance(m, str) else m for m in self.machines]
            return json.dumps({"machines": [{"name": n, "target": t, "id": "x", "host": n, "version": "0.1.21",
                                             "state": "connected"} for n, t in pairs]})
        if args[:2] == ("machine", "rm"):
            names = [m if isinstance(m, str) else m[0] for m in self.machines]
            if args[2] not in names:
                raise hc_error("not_found", f"no machine {args[2]}", 3)
            del self.machines[names.index(args[2])]
            self.terms = [t for t in self.terms if not t["address"].startswith(args[2] + "/")]
            return json.dumps({"removed": args[2]})
        if args[0] == "get":
            info = self.infos.get(args[1], {})
            # "foreground": the leader of its foreground process group ({"pid", "name", "argv", "cwd"}), when given
            return json.dumps({"labels": info.get("labels", {}), "parent": info.get("parent"),
                               "die_with_parent": info.get("dies", True), "foreground": info.get("foreground"),
                               "reported": info.get("reported", False)})
        if args[0] == "run":
            address = f"t{50 + len(self.terms) + len(self.finished)}"
            if "--on" in args:  # a terminal on another machine: listed with its machine in front
                address = args[args.index("--on") + 1] + "/" + address
            cwd = args[args.index("--cwd") + 1] if "--cwd" in args else "/Users/x"
            name = args[args.index("--name") + 1] if "--name" in args else None
            self.terms.append(term(address, cwd, "sh" if "/bin/sh" in args else "zsh", name))
            if "--label" in args:
                self.infos[address] = {"labels": {"space": args[args.index("--label") + 1].split("=", 1)[1]}}
            return json.dumps({"address": address})
        if args[0] == "label":
            self.infos.setdefault(args[1], {})["labels"] = {"space": args[2].split("=", 1)[1]}
            return "{}"
        if args[0] == "exec" and hcgui.KEYCHAIN_SCRIPT in args:
            return exec_json(*self.keychain)
        if args[0] == "exec" and hcgui.DEV_SCRIPT in args:
            return exec_json(0, "", self.lsof)
        if args[0] == "exec" and hcgui.USAGE_SCRIPT in args:
            if self.usage is None:
                raise hc_error("machine_unreachable", "mini: not connected")
            return exec_json(0, "", self.usage)
        if args[0] == "exec":
            return "/Users/x\n" + ("dir" if args[-1] in self.dirs else "none") + "\n"
        if args[0] == "put":
            assert args[1] == "--json" and kw.get("timeout") == hcgui.PUT_TIMEOUT, (args, kw)
            address, path = args[2], args[3]
            size = os.path.getsize(path)
            with open(path, "rb") as f:
                self.puts.append((address, path, size, f.read(4)))
            if self.put_error:
                raise hc_error(*self.put_error)
            if size > 8_000_000:
                raise hc_error("invalid_params", "at most 8 MB per put", 6)
            if self.put_answer is not None:
                return self.put_answer
            return json.dumps({"bytes": size, "path": "/Users/x/dev/app/" + os.path.basename(path).replace(" ", "_")})
        if args[0] in ("keep", "kill", "wait", "rm"):
            address = args[1]
            if self.find(address) is None and address not in self.finished:
                raise hc_error("not_found", f'no terminal "{address}"', 3)
            if args[0] == "keep" and address in self.finished:
                raise hc_error("invalid_params", "only live terminals can be kept", 6)
            if args[0] == "kill":
                self.end(address)
            if args[0] == "rm":
                if address not in self.finished:
                    raise hc_error("live", f"{address} is still running")
                del self.finished[address]
            return "{}"
        raise AssertionError(args)


class FakeTmux:
    """Stands in for hcgui.tmux in an hcGUI window: records each tmux run (its arguments) and answers as tmux 3.8
    did in the spike. `scr`: the fake screen of the pane that sizes itself; a resize-pane changes it, as tmux would.
    `zoomed`, `width`, `height`: the window's zoom flag and size; `active`: this pane has the keyboard."""

    def __init__(self, scr=None, pane="%1", zoomed=False, width=120, height=40, lag=False):
        self.scr, self.pane, self.zoomed, self.width, self.height = scr, pane, zoomed, width, height
        self.pane_w, self.pane_h = (scr.width, scr.height) if scr is not None else (30, 3)
        self.lag = lag  # curses learns a resize later (tmux holds the size signal): scr changes only at settle()
        self.active = True
        self.calls = []
        self.inputs = []  # what tmux read on stdin (load-buffer -)
        self.split_id = "%7"

    def settle(self):
        """The held size signal arrives: curses sees tmux's size."""
        self.scr.width, self.scr.height = self.pane_w, self.pane_h

    def drag(self, width):
        """The divider dragged: tmux and (after its signal) curses see the new width; the window keeps its own."""
        self.pane_w = self.scr.width = width

    def resize(self, width, window):
        """The window resized: tmux spread it over the panes."""
        self.pane_w = self.scr.width = width
        self.width = window

    def install(self, test):
        """hcgui.tmux is this, resizing is on, and this program's pane is `pane`, until the test ends."""
        for patcher in (mock.patch.multiple(hcgui, tmux=self, autosize_enabled=lambda: True),
                        mock.patch.dict(os.environ, {"TMUX_PANE": self.pane})):
            patcher.start()
            test.addCleanup(patcher.stop)
        return self

    def __call__(self, *args, input=None):
        self.calls.append(args)
        if input is not None:
            self.inputs.append(input)
        out = ""
        cmd = []
        for word in list(args) + [";"]:
            if word != ";":
                cmd.append(word)
                continue
            if cmd[0] == "display":
                fmt = cmd[-1]
                if "window_zoomed_flag" in fmt:
                    out = f"{int(self.zoomed)} {self.width} {self.height} {self.pane_w} {self.pane_h}\n"
                elif fmt == "#{pane_active}":
                    out = f"{int(self.active)}\n"
                elif fmt == "#{pane_width}":
                    out = f"{self.scr.width}\n"
                elif fmt == "#{pane_height}":
                    out = f"{self.scr.height}\n"
            elif cmd[0] == "resize-pane":
                if "-Z" in cmd:
                    self.zoomed = not self.zoomed
                elif "-x" in cmd:
                    self.pane_w = int(cmd[cmd.index("-x") + 1])
                elif "-y" in cmd:
                    self.pane_h = int(cmd[cmd.index("-y") + 1])
                if self.scr is not None and not self.lag:
                    self.settle()
            elif cmd[0] == "split-window":
                out = self.split_id + "\n" if self.split_id else ""
            cmd = []
        return out if self.split_id or "split-window" not in args else None

    def sizes(self, flag="-x"):
        """The sizes asked for, in order (-x: widths, -y: heights)."""
        return [int(c[c.index(flag) + 1]) for c in self.calls if c[0] == "resize-pane" and flag in c]

    def commands(self):
        """Every tmux command run, one list each (a call may hold several, joined by ";")."""
        out = []
        for call in self.calls:
            cmd = []
            for word in list(call) + [";"]:
                if word == ";":
                    if cmd:
                        out.append(cmd)
                    cmd = []
                else:
                    cmd.append(word)
        return out

    def selected(self):
        """The panes given the keyboard, in order."""
        return [c[c.index("-t") + 1] for c in self.commands() if c[0] == "select-pane"]

    def typed(self, pane="%0"):
        """What send-keys typed into `pane`: text, and named keys as <Name>."""
        out = ""
        for c in self.commands():
            if c[0] == "send-keys" and c[c.index("-t") + 1] == pane:
                if "-H" in c:
                    out += bytes.fromhex("".join(c[c.index("-H") + 1:])).decode("latin1")
                else:
                    out += f"<{c[-1]}>"
        return out

    def looks(self):
        return sum(1 for c in self.calls if c[0] == "display" and "window_zoomed_flag" in c[-1])


PANES = "side=%1\ntabs=%2\nview=%0\n"  # the panes file start.sh writes in a new tmux server


class SidebarLogicTests(unittest.TestCase):
    """The Sidebar class against a fake screen and a fake hc."""

    TERMS = [term("t1", "/Users/x/dev", "claude-code", "atlas", "idle"),
             term("t2", "/Users/x/dev", "claude-code", "tracker", "working"),
             term("t3", "/Users/x/dev/other", "claude-code", "o1", "done"),
             term("t4", "/Users/x/dev/other", "zsh", "sh")]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"
        self.hc = FakeHc(self.TERMS)
        for target, value in ((hcgui, {"run_hc": self.hc}), (hcgui.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scr = FakeScr(24, 30)
        seen_done(self.state, self.hc.terms)
        self.side = hcgui.Sidebar(self.scr, self.state, self.win)
        self.side.refresh_once()
        self.side.sync()
        self.side.draw()

    def key(self, *keys):
        for k in keys:
            self.side.on_key(ord(k) if isinstance(k, str) else k)  # what the loop does with a key
            self.side.sync()
            self.side.draw()

    def type(self, text):
        self.key(*text)
        self.key(10)

    def test_cursor_on_the_current_group_after_the_first_draw(self):
        side = hcgui.Sidebar(self.scr, self.state, self.win)
        side.first_draw()  # before any listing
        side.refresh_once()
        side.begin(False)
        side.sync()
        side.draw()
        self.assertEqual(side.cursor_item(), hcgui.Item("group", side.cur, ""))

    def test_snapshot_rewritten_after_the_laptop_slept(self):
        woke = time.time() + 3600  # an hour of sleep: the wall clock moved, time.monotonic() on macOS did not
        with mock.patch.object(hcgui.time, "time", return_value=woke):
            self.side.sync()
            self.assertIsNotNone(hcgui.read_snapshot(self.win, now=woke))

    def test_first_group_becomes_current_and_snapshot_is_written(self):
        self.assertEqual(self.side.cur, "space:dev")
        self.assertEqual(hcgui.read_text(self.state / "group"), "space:dev")
        snap = hcgui.read_snapshot(self.win)
        self.assertEqual([t["label"] for t in snap["tabs"]], ["atlas", "tracker"])
        self.assertFalse((self.state / "target").exists())  # window files live in the window folder

    def test_draw_sections_markers_and_cursor(self):
        self.side.draw()
        lines = self.scr.lines()
        self.assertEqual(lines[0], " spaces")
        self.assertEqual(lines[1], hcgui.glyph("›● dev"))
        self.assertEqual(lines[2], hcgui.glyph(" ● other"))
        self.assertEqual(lines[3:7], [" + new space", "", "", ""])  # the servers section is hidden by default
        self.assertEqual(self.scr.reversed_rows(), [1])
        self.assertEqual(lines[-7], " agents")  # the heading alone: no "grouped" after it (owner, 24 Nov)
        self.assertEqual(lines[-6], hcgui.glyph(" dev"))
        # no status word on agent rows: the dot's colour says it (owner, 24 Nov)
        self.assertEqual(lines[-5], hcgui.glyph("  ● atlas"))
        self.assertEqual(lines[-4], hcgui.glyph("  ● tracker"))
        self.assertEqual(lines[-3], "")  # one blank row after a group with a heading (owner, 25 Nov)
        # o1 is the only agent of "other": no "other · 1" heading, the space's name after its own (owner, 24 Nov)
        self.assertEqual(lines[-2], hcgui.glyph("  ● o1 · other"))
        self.assertFalse(any(line.endswith(("idle", "working", "done", "blocked")) for line in lines))
        self.assertNotIn(hcgui.glyph(" other · 1"), lines)
        self.assertEqual(lines[-1], fold_line("open"))  # the arrow on the last line, a dim "?" at its end
        self.assertEqual(lines[-9:-7], ["", "─" * 29])  # no key hints above the rule
        self.assertNotIn("rig", " ".join(lines))
        self.assertNotIn("grouped", " ".join(lines))
        self.side.mode = "strip"  # the strip draws the heading too, cut at its edge
        self.scr.width = 6
        self.side.draw()
        self.assertNotIn("grouped", " ".join(self.scr.lines()))

    def test_a_lone_agent_names_its_group_dim_and_cut_to_fit_the_row(self):
        row = lambda: next(y for y, item in self.side.rows.items() if item.address == "t3")  # noqa: E731
        y = row()
        self.assertEqual(self.scr.line(y), hcgui.glyph("  ● o1 · other"))  # no status word: the dot says it
        self.assertEqual(self.scr.cells[(y, 4)][1] & hcgui.curses.A_DIM, 0)  # the name as any agent's
        self.assertTrue(self.scr.cells[(y, 7)][1] & hcgui.curses.A_DIM)  # "other" dim
        hcgui.change_names({"space:other": "a-very-long-space-name"}, self.state)
        self.side.draw()
        y = row()  # the renamed space sorts first
        # no status column: the place is cut to the row's own room (width - 5), short of the last column
        self.assertEqual(self.scr.line(y), hcgui.glyph("  ● o1 · a-very-long-space-n…"))
        self.assertEqual(columns(self.scr.line(y)), self.scr.width - 1)
        hcgui.change_names({"space:other": "", "term:t3": "Other"}, self.state)  # the space's own name, any case
        self.side.draw()
        y = row()
        self.assertEqual(self.scr.line(y), hcgui.glyph("  ● Other"))
        self.key("j", "j", "j", "j", "j")  # the cursor reaches it and a click shows it, as any agent's row
        self.assertEqual(self.side.cursor_item(), hcgui.Item("agent", "space:other", "t3"))
        with pressed(5, y):
            self.key(hcgui.curses.KEY_MOUSE)
        self.assertEqual(hcgui.current_target(self.win), "t3")

    def test_enter_on_group_shows_first_then_remembered(self):
        self.key("j", 10)
        self.assertEqual(self.side.cur, "space:other")
        self.assertEqual(hcgui.current_target(self.win), "t3")
        hcgui.show("t4", self.win)  # the tab bar picks another tab
        self.side.sync()
        self.assertEqual(hcgui.read_last(self.state)["space:other"], "t4")
        self.key("k", 10)
        self.assertEqual(hcgui.current_target(self.win), "t1")
        self.key("j", 10)
        self.assertEqual(hcgui.current_target(self.win), "t4")  # remembered

    def test_enter_on_agent_shows_it_and_marks_it(self):
        self.key(*"jjjj", 10)  # dev, other, + new space, atlas, tracker (servers hidden: the default)
        self.assertEqual(hcgui.current_target(self.win), "t2")
        self.assertEqual(self.side.cur, "space:dev")
        marked = [line for line in self.scr.lines() if line.startswith(hcgui.glyph("›"))]
        self.assertEqual(len(marked), 2)  # the current group and the shown agent
        self.assertTrue(any("tracker" in line for line in marked))

    def test_start_up_auto_open_does_not_touch_the_focus(self):
        with mock.patch.object(hcgui, "focus_view") as focus:
            self.side.open_group(self.side.cur, focus=False)
            focus.assert_not_called()
            self.assertEqual(hcgui.current_target(self.win), "t1")
            self.side.open_group(self.side.cur)
            focus.assert_called_once()

    def test_click_uses_the_item_that_was_drawn(self):
        self.side.draw()
        row = next(y for y, item in self.side.rows.items() if item.address == "t3")
        self.hc.terms = [t for t in self.hc.terms if t["address"] != "t1"]  # the list changes after the draw
        self.side.refresh_once()
        with pressed(5, row, 1):
            self.side.handle_key(hcgui.curses.KEY_MOUSE)
        self.assertEqual(hcgui.current_target(self.win), "t3")

    def test_click_on_an_agent_that_ended_shows_nothing(self):
        self.side.draw()
        row = next(y for y, item in self.side.rows.items() if item.address == "t3")
        self.hc.terms = [t for t in self.hc.terms if t["address"] != "t3"]
        self.side.refresh_once()
        with pressed(5, row, 1):
            self.side.handle_key(hcgui.curses.KEY_MOUSE)
        self.assertEqual(hcgui.current_target(self.win), "")
        self.assertTrue(self.side.notice.current())

    def test_n_starts_a_labelled_shell_in_the_cursor_space(self):
        self.key("j", "n")
        run = [c for c in self.hc.calls if c[0] == "run"][-1]
        self.assertEqual(run, ("run", "--bg", "--json", "--no-parent", "--cwd", "/Users/x/dev/other",
                               "--label", "space=other"))
        self.assertEqual(self.side.cur, "space:other")
        self.assertEqual(hcgui.current_target(self.win), "t54")

    def test_s_with_a_name_without_folder_labels_a_shell_in_home(self):
        self.key("s")
        self.assertIn("name or folder", self.scr.line(21))  # the prompt sits above the arrow line
        self.assertEqual(self.scr.line(22), "> _")
        self.type("fresh")
        probe = [c for c in self.hc.calls if c[0] == "exec"][-1]
        self.assertEqual(probe[-1], "dev/fresh")
        run = [c for c in self.hc.calls if c[0] == "run"][-1]
        self.assertEqual(run[4:], ("--cwd", "/Users/x", "--label", "space=fresh"))
        self.assertEqual(self.side.cur, "space:fresh")
        self.assertEqual(self.side.cursor, hcgui.Item("group", "space:fresh", ""))

    def test_s_with_a_name_whose_folder_exists_starts_there(self):
        self.hc.dirs.add("dev/repo")
        self.key("s")
        self.type("repo")
        run = [c for c in self.hc.calls if c[0] == "run"][-1]
        self.assertEqual(run[4:], ("--cwd", "/Users/x/dev/repo"))
        self.assertEqual(self.side.cur, "space:repo")

    def test_s_with_a_tilde_folder_never_reaches_hc_unexpanded(self):
        self.hc.dirs.add("dev/repo/sub")
        self.key("s")
        self.type("~/dev/repo/sub")
        run = [c for c in self.hc.calls if c[0] == "run"][-1]
        self.assertEqual(run[4:], ("--cwd", "/Users/x/dev/repo/sub"))
        self.assertFalse(any("~" in a for c in self.hc.calls for a in c))

    def test_s_missing_folder_and_bad_input_only_say_so(self):
        runs = len([c for c in self.hc.calls if c[0] == "run"])
        self.key("s")
        self.type("~/nope")
        self.assertEqual(self.side.notice.current(), "no folder ~/nope")
        self.key("s")
        self.type("rel/path")
        self.assertEqual(self.side.notice.current(), "start a folder with / or ~/")
        self.key("s", 27)
        self.assertIsNone(self.side.prompt)
        self.assertEqual(len([c for c in self.hc.calls if c[0] == "run"]), runs)

    def test_m_moves_the_agent_under_the_cursor(self):
        self.key("m")
        self.assertIsNone(self.side.prompt)  # the cursor is on a group
        self.assertTrue(self.side.notice.current())
        self.key(*"jjj", "m")  # atlas
        self.assertIn("move atlas to space:", self.scr.line(21))
        self.type("other")
        self.assertEqual([c for c in self.hc.calls if c[0] == "label"][-1], ("label", "t1", "space=other"))
        spaces, _ = self.side.groups()
        self.assertEqual({g.name: [t.label for t in g.terms] for g in spaces},
                         {"dev": ["tracker"], "other": ["atlas", "o1", "sh"]})
        self.assertEqual(self.side.cursor_item(), hcgui.Item("agent", "space:other", "t1"))  # the cursor follows it
        self.key("m", 10)  # empty input cancels
        self.assertEqual(len([c for c in self.hc.calls if c[0] == "label"]), 1)

    def test_tabs_follow_the_shown_terminal_into_its_new_space(self):
        self.key(*"jjj", 10)  # show atlas (space dev)
        self.assertEqual(self.side.cur, "space:dev")
        self.key("m")
        self.type("other")
        self.assertEqual(self.side.cur, "space:other")
        self.assertIn("atlas", [t["label"] for t in hcgui.read_snapshot(self.win)["tabs"]])

    def test_spawned_child_joins_its_parents_space_in_one_refresh(self):
        self.hc.infos["t1"] = {"labels": {"space": "atlas"}}
        self.hc.terms.append(term("t9", "/Users/x/dev", "zsh", "kid"))
        self.hc.infos["t9"] = {"parent": "t1"}
        self.side.refresh_once(full=True)
        spaces, _ = self.side.groups()
        self.assertEqual([t.label for t in next(g for g in spaces if g.name == "atlas").terms], ["atlas", "kid"])

    def test_new_terminals_are_fetched_once_and_all_again_on_a_full_round(self):
        gets = lambda: [c[1] for c in self.hc.calls if c[0] == "get"]  # noqa: E731
        self.assertEqual(sorted(gets()), ["t1", "t2", "t3", "t4"])
        self.side.refresh_once()
        self.assertEqual(len(gets()), 4)
        self.hc.terms.append(term("t9"))
        self.side.refresh_once()
        self.assertEqual(gets()[4:], ["t9"])
        self.side.refresh_once(full=True)
        self.assertEqual(len(gets()), 10)

    def test_a_failed_get_keeps_the_terminal_on_the_folder_rules(self):
        def flaky(*args, **kw):
            if args[0] == "get":
                raise subprocess.CalledProcessError(3, "hc", stderr="nope")
            return self.hc(*args, **kw)

        with mock.patch.object(hcgui, "run_hc", flaky):
            self.side.refresh_once(full=True)
        spaces, _ = self.side.groups()
        self.assertEqual([g.name for g in spaces], ["dev", "other"])
        self.assertEqual(self.side.error, "")

    def test_hc_errors_and_junk_become_one_red_line(self):
        self.hc.fail = '{"error":{"kind":"x","message":"core is not running"}}'
        self.side.refresh_once()
        self.side.draw()
        self.assertEqual(self.scr.line(22), "hc: core is not running")
        self.assertEqual(self.scr.line(23), fold_line("open"))
        self.assertEqual(len(self.side.groups()[0]), 2)  # the last good list stays
        self.hc.fail = ""
        for junk in ("[]", "null", '{"terminals": null}', '{"terminals": [1]}', "garbage"):
            with mock.patch.object(hcgui, "run_hc", lambda *a, **k: junk):
                self.side.refresh_once()
            self.side.draw()
        self.side.refresh_once()
        self.side.draw()
        self.assertEqual(self.side.error, "")

    def test_action_notice_survives_the_refresh_and_goes_with_a_key(self):
        self.hc.fail = '{"error":{"message":"cannot start"}}'
        self.side.new_in_cursor_group()
        self.hc.fail = ""
        self.side.refresh_once()
        self.side.draw()
        self.assertEqual(self.scr.line(22), "new: cannot start")
        self.key("k")
        self.assertEqual(self.side.notice.current(), "")

    def test_a_new_space_name_shows_on_its_plus_row_in_orange(self):
        # owner, 26 Nov: the question opens at the bottom and is hard to see
        self.side.ask_new_space()
        for c in "web":
            self.key(c)
        y = next(y for y, item in self.side.rows.items() if item.kind == "new_space")
        self.assertEqual(self.scr.line(y).rstrip(), " + web_")
        self.assertEqual(self.scr.cells[(y, 3)][1], hcgui.ask_attr())
        self.key(27)  # esc: the row says "new space" again
        self.assertIn("new space", self.scr.line(y))

    def test_cursor_never_rests_on_a_row_without_a_line(self):
        self.scr.height = 6  # the 4 top lines (servers hidden) + 1 line + the arrow: one agent row at most
        self.side.draw()
        for _ in range(10):
            self.key("j")
            index = self.side.cursor_index()
            self.assertIn(self.side.cursor, self.side.rows.values(), index)
        self.scr.height = 5  # no line for agents at all
        self.side.draw()
        self.assertEqual(self.side.cursor.kind, "group")  # back to the agent's group
        self.key(*"jjjjj")
        self.assertEqual(self.side.cursor.kind, "new_space")  # the last row with a line (servers hidden)
        for height in (3, 4, 5):  # the top part scrolls: every row the cursor reaches has its line, "+" rows too
            self.scr.height = height
            self.key(*"kkkkkk")
            for _ in range(5):
                self.assertIn(self.side.cursor, self.side.rows.values(), height)
                self.key("j")

    def test_sidebar_sizes_itself_again_after_a_resize(self):
        self.scr.width = 75
        with mock.patch.object(hcgui, "tmux") as run:
            self.side.refit()  # outside tmux: never
        run.assert_not_called()
        tm = self.fake_tmux()
        self.side.refit()
        self.assertEqual((tm.sizes(), self.scr.width), ([hcgui.WIDTH], hcgui.WIDTH))  # the first round sizes it
        calls = len(tm.calls)
        self.side.refit()
        self.assertEqual(len(tm.calls), calls)  # on its width: no tmux call at all
        self.scr.width, tm.width = 60, 180  # the window grew: tmux spread it over the panes
        self.side.refit()
        self.assertEqual(tm.sizes(), [hcgui.WIDTH, hcgui.WIDTH])

    def test_small_screens_do_not_crash(self):
        for mode in ("open", "strip"):
            for height in range(0, 12):
                for width in (1, 2, 3, 5, 20, 30):
                    self.scr.height, self.scr.width = height, width
                    self.side.prompt = None
                    self.side.mode = mode
                    self.side.draw()
                    self.key("j", "s", "x")
                    self.side.prompt = None
                    self.side.notice.say("something went wrong")
                    self.side.draw()

    # the collapse arrow and the folded strip -------------------------------------------------------------------
    def fake_tmux(self, **kw):
        return FakeTmux(self.scr, **kw).install(self)

    def group_line(self, key):
        return next(y for y, item in self.side.rows.items() if item == hcgui.Item("group", key, ""))

    def test_arrow_lines_at_every_height_in_both_modes(self):
        for mode in ("open", "strip"):
            self.side.mode = mode
            for height in range(1, 31):
                for notice in ("", "something went wrong"):
                    self.scr.height = height
                    self.side.notice.say(notice) if notice else self.side.notice.clear()
                    self.side.draw()
                    lines = self.scr.lines()
                    case = (mode, height, notice)
                    if height >= 2:
                        self.assertEqual(self.side.arrow_y, height - 1, case)
                        self.assertEqual(lines[-1], fold_line(mode), case)
                        self.assertNotIn(height - 1, self.side.rows, case)
                    else:
                        self.assertEqual(self.side.arrow_y, -1, case)
                    opener = mode == "strip" and height >= 3
                    self.assertEqual(self.side.open_y, height - 2 if opener else -1, case)
                    if opener:
                        self.assertEqual(lines[-2], hcgui.glyph(hcgui.open_label(29)), case)
                        self.assertNotIn(height - 2, self.side.rows, case)
                    cursor_rows = self.scr.reversed_rows()
                    self.assertEqual(len(cursor_rows), 1, case)  # the cursor always has its line
                    self.assertIn(cursor_rows[0], self.side.rows, case)
                    self.assertFalse(any("zoom" in line for line in lines), case)  # no key hints: "?" lists them
                    if notice and height >= (4 if opener else 3):
                        # the message sits just above the arrow lines
                        self.assertEqual(lines[-3 if opener else -2], notice, case)

    def test_compact_strip_draws_at_3_to_12_columns(self):
        self.key("c")
        self.key(*"jjj", 10)  # show atlas: the agent's line gets the marker too
        for width in range(3, 13):
            for height in (5, 9, 24):
                self.scr.width, self.scr.height = width, height
                self.side.draw()
                lines = self.scr.lines()
                case = (width, height, lines)
                self.assertTrue(all(len(line) <= width - 1 for line in lines), case)
                self.assertEqual(lines[-1], hcgui.glyph(hcgui.fold_label("strip", width - 1)), case)
                self.assertEqual(lines[-2], hcgui.glyph(hcgui.open_label(width - 1)), case)
                self.assertEqual(lines[0], "spaces"[:width - 1], case)  # the title, cut at the edge
                dev = lines[self.group_line("space:dev")]
                self.assertEqual(dev, hcgui.glyph("›●dev")[:width - 1], case)  # marker, dot, the name as it fits
                other = lines[self.group_line("space:other")]
                self.assertEqual(other, hcgui.glyph(" ●other")[:width - 1], case)
                self.assertTrue(self.scr.reversed_rows(), case)
                if height == 24:
                    atlas = next(y for y, item in self.side.rows.items() if item.address == "t1")
                    self.assertEqual(lines[atlas], hcgui.glyph("›●atlas")[:width - 1], case)  # no status word
                    self.assertNotIn("idle", "".join(lines), case)

    def test_wide_names_stay_inside_the_pane(self):
        """CJK and emoji names (a wide character takes two columns, curses counts characters): folded at 3 to 12
        columns and open, nothing reaches the last column or wraps onto the next line, blank lines included."""
        self.hc.terms = [term("t1", "/Users/x/dev/app", "claude-code", "a1", "idle"),
                         term("t2", "/Users/x/dev/日本語プロジェクト", "claude-code", "日本語のエージェント", "working"),
                         term("t3", "/Users/x/dev/🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀", "claude-code", "🚀rocket", "idle"),
                         term("rig/t1", "/home/r", "claude-code", "r1", "idle")]
        self.side.refresh_once()
        self.side.sync()
        hcgui.write_atomic(self.win / "target", "t2\n")  # the wide agent carries the marker
        for (mode, widths), servers in itertools.product((("strip", range(3, 13)), ("open", (12, 20, 30))),
                                                         (False, True)):
            self.side.mode = mode
            hcgui.write_servers_shown(servers, self.state)
            for width in widths:
                for height in (9, 12, 24):
                    scr = WideScr(height, width)
                    self.side.s = hcgui.Screen(scr)
                    self.side.draw()
                    lines = scr.lines()
                    case = (mode, servers, width, height, lines)
                    self.assertEqual(scr.spilled, [], case)
                    self.assertTrue(all(columns(line) <= width - 1 for line in lines), case)
                    plan = hcgui.plan_sidebar(*self.side.groups(), self.side.body_height, self.side.cursor_pos,
                                              mode == "strip", self.side.servers_shown())
                    for y, row in plan:
                        if row.kind == "blank":
                            self.assertEqual(lines[y], "", case)  # the line before "servers" stays empty
        self.side.mode = "open"
        scr = WideScr(24, 30)
        self.side.s = hcgui.Screen(scr)
        self.side.draw()
        agent = scr.lines()[next(y for y, item in self.side.rows.items() if item.address == "t2")]
        self.assertIn("…", agent)  # cut by columns, with the mark of the cut
        self.assertNotIn("working", agent)  # no status word: the dot says it
        self.assertEqual(columns(agent), 30 - 1, agent)  # the name gets the row up to the last column

    def test_compact_strip_keeps_the_cursor_enter_and_clicks(self):
        self.key("c")
        self.scr.width = 8
        self.side.draw()
        self.key("j", 10)
        self.assertEqual(self.side.cur, "space:other")
        self.assertEqual(hcgui.current_target(self.win), "t3")
        row = next(y for y, item in self.side.rows.items() if item.address == "t2")
        with pressed(1, row, 1):
            self.key(hcgui.curses.KEY_MOUSE)
        self.assertEqual(hcgui.current_target(self.win), "t2")
        self.assertEqual(self.side.cur, "space:dev")
        self.key("n")  # n works folded too
        self.assertEqual([c for c in self.hc.calls if c[0] == "run"][-1][-2:], ("--label", "space=dev"))

    def test_c_steps_open_strip_hidden_and_the_state_is_kept(self):
        hcgui.write_atomic(self.win / "sidebar.pid", f"{os.getpid()}\n")  # as run() writes it
        hcgui.write_atomic(self.win / "panes", PANES)
        self.assertEqual(self.side.mode, "open")
        self.assertEqual(self.scr.line(23), fold_line("open"))
        with mock.patch.object(hcgui, "tmux") as run:
            self.assertTrue(self.side.on_key(ord("c")))
            self.assertEqual(self.side.mode, "strip")
            self.assertEqual(hcgui.read_text(self.state / "sidebar"), "strip")  # shared by all windows
            self.assertFalse((self.win / "sidebar").exists())
            again = hcgui.Sidebar(FakeScr(24, 30), self.state, self.win)  # the next start opens folded
            self.assertEqual((again.mode, again.width_goal()), ("strip", hcgui.NARROW))
            self.side.draw()
            self.assertEqual(self.scr.line(23), hcgui.glyph(" ‹ hide"))
            self.assertEqual(self.scr.line(22), hcgui.glyph(" › open"))
            run.assert_not_called()  # outside tmux nothing is sized
            self.assertFalse(self.side.on_key(ord("C")))  # hidden: the loop ends, so does the program
        self.assertEqual(hcgui.read_sidebar_state(self.state), "hidden")
        self.assertFalse((self.win / "sidebar.pid").exists())
        self.assertTrue((self.win / "tabs.json").exists())  # the tab bar draws it until its own engine writes
        run.assert_called_once_with("select-pane", "-t", "%0")

    def test_q_hides_the_sidebar_from_either_state(self):
        hcgui.write_atomic(self.win / "panes", PANES)
        for before in ("open", "strip"):
            self.side.mode = before
            hcgui.write_sidebar_state(before, self.state)
            hcgui.write_atomic(self.win / "sidebar.pid", f"{os.getpid()}\n")
            with mock.patch.object(hcgui, "tmux") as run:
                self.assertFalse(self.side.on_key(ord("q")), before)
            self.assertEqual(hcgui.read_sidebar_state(self.state), "hidden", before)
            self.assertFalse((self.win / "sidebar.pid").exists(), before)
            run.assert_called_once_with("select-pane", "-t", "%0")  # the keyboard to the view; tmux closes the pane

    def test_hide_never_removes_another_sidebars_pid_file(self):
        hcgui.write_atomic(self.win / "sidebar.pid", "1\n")
        self.assertFalse(self.side.on_key(ord("q")))
        self.assertEqual(hcgui.read_text(self.win / "sidebar.pid"), "1")

    def test_clicks_on_the_two_arrow_lines(self):
        self.side.draw()
        self.assertEqual((self.side.arrow_y, self.side.open_y), (23, -1))
        with pressed(5, 23, 1):
            self.assertTrue(self.side.on_key(hcgui.curses.KEY_MOUSE))  # "‹ fold"
        self.assertEqual(self.side.mode, "strip")
        self.side.draw()
        self.assertEqual((self.side.arrow_y, self.side.open_y), (23, 22))
        self.side.mouse_quiet = 0.0  # past the double-click guard
        with pressed(0, 22, 1):
            self.assertTrue(self.side.on_key(hcgui.curses.KEY_MOUSE))  # "› open"
        self.assertEqual((self.side.mode, hcgui.read_sidebar_state(self.state)), ("open", "open"))
        self.side.draw()
        self.assertEqual(self.side.open_y, -1)  # no "›" line in the open sidebar: line 22 is a row again
        self.assertIn(22, self.side.rows)
        self.side.mouse_quiet = 0.0
        with pressed(9, 23, 1):
            self.side.on_key(hcgui.curses.KEY_MOUSE)
        self.side.draw()
        self.side.mouse_quiet = 0.0
        with pressed(9, 23, 1), mock.patch.object(hcgui, "tmux"):
            self.assertFalse(self.side.on_key(hcgui.curses.KEY_MOUSE))  # "‹ hide"
        self.assertEqual(hcgui.read_sidebar_state(self.state), "hidden")
        self.assertEqual(hcgui.current_target(self.win), "")  # a click on an arrow line opens nothing

    def test_o_opens_the_strip_and_does_nothing_when_open(self):
        self.key("o")
        self.assertEqual(self.side.mode, "open")
        self.assertFalse((self.state / "sidebar").exists())  # nothing changed, nothing written
        self.key("c", "O")
        self.assertEqual((self.side.mode, hcgui.read_sidebar_state(self.state)), ("open", "open"))

    def test_strip_keeps_both_arrow_lines_and_the_cursor_at_every_size(self):
        self.key("c")
        self.key(*"jjj")  # the cursor on an agent: the row that goes first on a short screen
        for height in range(1, 31):
            for width in range(3, 13):
                for notice in ("", "something went wrong"):
                    self.scr.height, self.scr.width = height, width
                    self.side.notice.say(notice) if notice else self.side.notice.clear()
                    self.side.draw()
                    lines = self.scr.lines()
                    case = (height, width, notice, lines)
                    self.assertTrue(all(len(line) <= width - 1 for line in lines), case)
                    cursor_rows = self.scr.reversed_rows()
                    self.assertEqual(len(cursor_rows), 1, case)  # the cursor's line wins
                    self.assertIn(cursor_rows[0], self.side.rows, case)
                    if height >= 2:  # then "‹ hide"
                        self.assertEqual(self.side.arrow_y, height - 1, case)
                        self.assertEqual(lines[-1], hcgui.glyph(hcgui.fold_label("strip", width - 1)), case)
                        self.assertEqual(hcgui.sidebar_hit(height - 1, self.side.arrow_y, self.side.open_y,
                                                           self.side.rows), ("step", None), case)
                    else:
                        self.assertEqual(self.side.arrow_y, -1, case)
                    if height >= 3:  # then "› open"
                        self.assertEqual(self.side.open_y, height - 2, case)
                        self.assertEqual(lines[-2], hcgui.glyph(hcgui.open_label(width - 1)), case)
                        self.assertEqual(hcgui.sidebar_hit(height - 2, self.side.arrow_y, self.side.open_y,
                                                           self.side.rows), ("open", None), case)
                    else:
                        self.assertEqual(self.side.open_y, -1, case)
                    self.assertFalse({self.side.arrow_y, self.side.open_y} & set(self.side.rows), case)

    def test_folding_outside_tmux_changes_only_the_layout(self):
        with mock.patch.object(hcgui, "tmux") as run:
            self.key("c", "o", "c")
            self.side.refit()
        run.assert_not_called()
        self.assertEqual(self.side.mode, "strip")

    def test_toggle_sizes_the_pane_for_the_new_mode(self):
        tm = self.fake_tmux()
        self.side.refit()
        self.key("c")
        self.assertEqual(tm.sizes(), [hcgui.WIDTH, hcgui.NARROW])  # exact: no tenth-of-the-window limit
        self.assertEqual(self.scr.width, hcgui.NARROW)
        self.key("o")
        self.assertEqual(tm.sizes(), [hcgui.WIDTH, hcgui.NARROW, hcgui.WIDTH])
        self.assertEqual((self.side.sized_at, self.side.aimed), (hcgui.WIDTH, hcgui.WIDTH))
        self.side.refit()
        self.assertEqual(len(tm.sizes()), 3)  # nothing new to do

    def test_the_strip_keeps_its_width_when_the_window_changes(self):
        tm = self.fake_tmux()
        self.key("c")
        self.assertEqual(self.scr.width, hcgui.NARROW)
        self.scr.width, tm.width = 20, 200  # the window grew: the strip grew with it
        self.side.refit()
        self.assertEqual(tm.sizes()[-1], hcgui.NARROW)  # back to the strip's width, not HCGUI_WIDTH
        self.key("o")
        self.assertEqual(tm.sizes()[-1], hcgui.WIDTH)

    def test_s_and_m_open_the_strip_before_they_ask(self):
        self.key("c")
        self.key("s")
        self.assertEqual(self.side.mode, "open")
        self.assertEqual(self.side.prompt.kind, "space")
        self.assertIn("name or folder", self.scr.line(21))
        self.key(27, "c", *"jjj", "m")  # cursor on atlas
        self.assertEqual(self.side.mode, "open")
        self.assertEqual(self.side.prompt.kind, "move")
        self.key(27, "c", *"kkkk", "m")  # m on a group: open, then say why not
        self.assertEqual(self.side.mode, "open")
        self.assertEqual(self.side.notice.current(), "m: cursor on an agent first")
        self.assertEqual(hcgui.read_sidebar_state(self.state), "open")

    def test_a_size_change_is_no_key(self):
        self.side.notice.say("new: cannot start")
        self.side.on_key(hcgui.curses.KEY_RESIZE)
        self.assertEqual(self.side.notice.current(), "new: cannot start")

    # zoom ------------------------------------------------------------------------------------------------------
    def test_z_without_a_shown_terminal_only_says_so(self):
        hcgui.write_atomic(self.win / "panes", PANES)
        with mock.patch.object(hcgui, "tmux") as run:
            self.key("z")
            self.assertEqual(self.side.notice.current(), "z: nothing shown")
            hcgui.write_atomic(self.win / "target", "t1\n")  # a target, but the view is not attached
            self.key("z")
            self.assertEqual(self.side.notice.current(), "z: nothing shown")
        run.assert_not_called()

    def test_z_zooms_the_view_and_sets_no_size_while_zoomed(self):
        tm = self.fake_tmux()
        self.side.refit()
        hcgui.write_atomic(self.win / "panes", PANES)
        self.key(*"jjj", 10)
        with mock.patch.object(hcgui, "attach_pid", return_value=4242):
            self.key("z")
        self.assertIn(("select-pane", "-t", "%0", ";", "resize-pane", "-Z", "-t", "%0"), tm.calls)
        self.assertEqual(self.side.notice.current(), "")
        self.assertTrue(tm.zoomed)
        # the window changed while zoomed; the "‹ back" line on top takes a row from every pane meanwhile
        self.scr.width, tm.width, self.scr.height = 75, 200, self.scr.height - 1
        tm.pane_w, tm.pane_h = self.scr.width, self.scr.height
        looks = tm.looks()
        self.side.refit()
        self.assertEqual((tm.sizes(), tm.looks()), ([hcgui.WIDTH], looks + 1))  # a resize would end the zoom
        for _ in range(3):
            self.side.zoom_look -= hcgui.ZOOM_LOOK
            self.side.refit()
        self.assertEqual(tm.looks(), looks + 1)  # no more looks while curses shows the same size
        tm.zoomed = False  # "‹ back" clicked: the row comes back
        self.scr.height += 1
        tm.pane_h = self.scr.height
        self.side.zoom_look -= hcgui.ZOOM_LOOK
        self.side.refit()
        self.assertEqual(tm.sizes(), [hcgui.WIDTH, hcgui.WIDTH])
        self.assertFalse((self.state / "width").exists())  # the width tmux rebuilt is no drag

    # start -----------------------------------------------------------------------------------------------------
    def start_with(self, terms, saved=""):
        self.hc.terms = list(terms)
        state = Path(tempfile.mkdtemp(dir=self._tmp.name))  # an empty state folder for each start
        if saved:
            hcgui.write_atomic(state / "group", saved + "\n")
        side = hcgui.Sidebar(FakeScr(24, 30), state, state / "w-2")
        side.refresh_once()
        side.sync()
        return side

    def test_first_start_opens_a_space_with_agents(self):
        terms = [term("t1", "/Users/x", "zsh"), term("t2", "/Users/x/dev/app", "zsh"),
                 term("t3", "/Users/x/dev/zeta", "claude-code", "z1", "idle")]
        self.assertEqual(self.start_with(terms).cur, "space:zeta")  # not the empty "home" at the top
        self.assertEqual(self.start_with(terms, "space:app").cur, "space:app")  # the last used one stays
        self.assertEqual(self.start_with(terms, "space:gone").cur, "space:zeta")
        self.assertEqual(self.start_with(terms[:2]).cur, "space:home")  # no agent anywhere: the first space

    def test_a_start_keeps_the_terminal_the_view_already_shows(self):
        """The sidebar coming back (or the tab bar taking over) never switches the view: the shown terminal's group
        becomes the current one, also when the shared group file names another (set in another window)."""
        terms = [term("t1", "/Users/x", "zsh"), term("t2", "/Users/x/dev/app", "zsh"),
                 term("t3", "/Users/x/dev/zeta", "claude-code", "z1", "idle")]
        for attached, cur, shown in ((True, "space:app", []), (False, "space:zeta", [("t3",)])):
            side = self.start_with(terms, "space:zeta")
            hcgui.write_atomic(side.win / "target", "t2\n")
            calls = []
            with mock.patch.object(hcgui, "attach_pid", return_value=4242 if attached else 0), \
                    mock.patch.object(hcgui, "show", lambda address, win, title=None: calls.append((address,))):
                side.begin(True)
            self.assertEqual((side.cur, calls), (cur, shown), attached)
            self.assertEqual(hcgui.read_text(side.state / "group"), cur)

    def test_poke_during_the_listing_is_not_lost(self):
        order = []
        real = self.side.refresh_once

        def slow(full=False, also=()):
            order.append("refresh")
            if len(order) == 1:
                hcgui.write_atomic(self.win / "poke", "x\n")  # a terminal is created while hc ls runs
            if len(order) == 2:
                raise SystemExit  # end the endless loop of this test
            real(full, also)

        self.side.refresh_once = slow
        started = time.monotonic()
        with self.assertRaises(SystemExit):
            self.side.refresh_forever()
        self.assertLess(time.monotonic() - started, hcgui.REFRESH_SECONDS / 2)


class TabBarLogicTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.win = Path(self._tmp.name)
        self.state = self.win / "shared"
        patcher = mock.patch.object(hcgui.curses, "color_pair", lambda n: n << 8)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.scr = FakeScr(5, 40)
        self.bar = hcgui.TabBar(self.scr, self.win, self.state)
        self.addCleanup(self.bar.stop_engine)
        spaces, _ = hcgui.build_groups(hcgui.parse(ls(
            term("t1", "/Users/x/dev/app", "claude-code", "alpha", "idle"), term("t2", name="beta"),
            term("t3", name="gamma"), term("t4", name="delta"), term("t5", name="omega"))), "mini")
        hcgui.write_snapshot(spaces[0], self.win)
        self.snap = hcgui.read_snapshot(self.win)

    def test_waiting_without_a_sidebar(self):
        self.bar.draw(None, "")
        self.assertIn("waiting for the sidebar", self.scr.line(0))
        self.bar.alone = True  # no sidebar: its own engine is still loading
        self.bar.draw(None, "")
        self.assertEqual(self.scr.line(0), hcgui.glyph("› loading…"))
        self.assertEqual(hcgui.hit_test(self.bar.layout, 0, 0), ("open", -1))  # "›" works before the tabs come

    # without a sidebar -----------------------------------------------------------------------------------------
    def test_no_opener_while_a_sidebar_runs(self):
        hcgui.write_atomic(self.win / "sidebar.pid", f"{os.getpid()}\n")
        hcgui.write_atomic(self.win / "panes", PANES)
        self.bar.watch_sidebar(100.0)
        self.assertFalse(self.bar.alone)
        self.assertIsNone(self.bar.engine)
        self.bar.draw(self.snap, "t1")
        self.assertEqual(self.scr.line(0), hcgui.glyph(" ● alpha │ ○ beta │ ○ delta │ ○ gamma"))
        self.assertEqual(hcgui.hit_test(self.bar.layout, 0, 0), ("tab", 0))
        self.assertNotIn("switch", self.scr.line(4))  # no hints until a click on the bar
        with mock.patch.object(hcgui, "tmux") as run:
            for key in (ord("c"), ord("o")):
                self.bar.on_key(key, self.snap, "t1")  # the sidebar's keys: nothing here
        run.assert_not_called()
        self.assertFalse((self.state / "sidebar").exists())
        self.assertIsNone(self.bar.opening)

    def test_opener_without_a_sidebar(self):
        self.bar.alone = True
        self.bar.draw(self.snap, "t1")
        lines = self.scr.lines()
        self.assertEqual(lines[0], hcgui.glyph("› ● alpha │ ○ beta │ ○ delta │ ○ gamma"))
        self.assertEqual(lines[1], hcgui.glyph("  ○ omega │ +"))
        self.assertEqual(lines[2:4], ["", ""])
        self.assertEqual(lines[4], hcgui.glyph("  Claude Code · ~/dev/app · idle"))  # the last row: the info row
        self.assertEqual(self.scr.cells[(0, 0)], ("›", hcgui.curses.A_BOLD))
        hit = hcgui.hit_test
        self.assertEqual(hit(self.bar.layout, 0, 0), ("open", -1))
        self.assertEqual(hit(self.bar.layout, 1, 0), ("tab", 0))
        self.assertEqual(hit(self.bar.layout, 2, 1), ("tab", 4))
        self.assertIsNone(hit(self.bar.layout, 0, 1))
        with mock.patch.object(hcgui, "read_mouse", return_value=(3, 1, 1)):  # the tabs still switch
            self.bar.on_key(hcgui.curses.KEY_MOUSE, self.snap, "t1")
        self.assertEqual(hcgui.current_target(self.win), "t5")

    def test_a_click_on_the_opener_brings_the_sidebar_back_once(self):
        hcgui.write_atomic(self.win / "panes", "tabs=%2\nview=%0\n")
        hcgui.write_sidebar_state("hidden", self.state)
        self.bar.alone = True
        self.bar.draw(self.snap, "t1")
        tm = FakeTmux().install(self)
        with mock.patch.object(hcgui, "read_mouse", return_value=(0, 0, 1)):
            self.bar.on_key(hcgui.curses.KEY_MOUSE, self.snap, "t1")
            self.assertEqual(hcgui.read_sidebar_state(self.state), "open")  # the new sidebar starts open
            self.bar.on_key(hcgui.curses.KEY_MOUSE, self.snap, "t1")  # a double click: one sidebar
        splits = [c for c in tm.calls if c[0] == "split-window"]
        self.assertEqual(len(splits), 1)
        self.assertEqual(splits[0][:8], ("split-window", "-f", "-hb", "-d", "-l", str(hcgui.WIDTH), "-t", "%0"))
        self.assertTrue(splits[0][-1].endswith("hcgui.py sidebar"))
        self.assertEqual(hcgui.pane_id("side", self.win), "%7")
        start = self.bar.opening
        self.bar.check_opening(start + 1)
        self.assertEqual(self.bar.opening, start)  # not running yet
        hcgui.write_atomic(self.win / "sidebar.pid", f"{os.getpid()}\n")
        self.bar.check_opening(start + 2)
        self.assertIsNone(self.bar.opening)  # it runs: this tab bar stays, its engine stops (watch_sidebar)
        self.assertEqual(hcgui.read_sidebar_state(self.state), "open")

    def test_c_opens_too_and_a_sidebar_that_never_runs_is_reported_after_ten_seconds(self):
        hcgui.write_atomic(self.win / "panes", PANES)
        hcgui.write_sidebar_state("hidden", self.state)
        self.bar.alone = True
        FakeTmux().install(self)
        self.bar.on_key(ord("c"), self.snap, "t1")
        start = self.bar.opening
        self.assertEqual(hcgui.read_sidebar_state(self.state), "open")
        self.bar.check_opening(start + hcgui.OPEN_TIMEOUT - 0.1)
        self.assertEqual(hcgui.read_sidebar_state(self.state), "open")
        # (+0.01: start + 10 - start can come out a hair under 10 for a large clock value)
        self.bar.check_opening(start + hcgui.OPEN_TIMEOUT + 0.01)
        self.assertEqual(hcgui.read_sidebar_state(self.state), "hidden")
        self.assertEqual(self.bar.notice.current(), "could not open the sidebar")
        self.assertTrue(self.bar.notice.bad)
        self.assertIsNone(self.bar.opening)

    def test_a_split_that_fails_says_so_at_once(self):
        hcgui.write_atomic(self.win / "panes", PANES)
        hcgui.write_sidebar_state("hidden", self.state)
        self.bar.alone = True
        with mock.patch.object(hcgui, "tmux", return_value=None):  # also outside tmux
            self.bar.on_key(ord("o"), self.snap, "t1")
        self.assertEqual(self.bar.notice.current(), "could not open the sidebar")
        self.assertEqual(hcgui.read_sidebar_state(self.state), "hidden")
        self.assertIsNone(self.bar.opening)

    def test_without_the_views_id_the_split_is_made_from_this_pane(self):
        self.bar.alone = True
        hcgui.write_sidebar_state("hidden", self.state)
        tm = FakeTmux(pane="%2").install(self)
        hcgui.write_atomic(self.win / "panes", "side=%1\ntabs=%2\nview=\"; \n")  # no usable view id
        self.bar.on_key(ord("c"), self.snap, "t1")
        self.assertEqual(tm.calls[-1][:8], ("split-window", "-f", "-hb", "-d", "-l", str(hcgui.WIDTH), "-t", "%2"))
        self.bar.opening = None
        tm.calls.clear()
        with mock.patch.dict(os.environ, {"TMUX_PANE": ""}):  # not even this pane's id: nothing to split
            self.bar.on_key(ord("c"), self.snap, "t1")
        self.assertEqual(tm.calls, [])
        self.assertEqual(self.bar.notice.current(), "could not open the sidebar")
        self.assertEqual(hcgui.read_sidebar_state(self.state), "hidden")

    def test_keys_without_a_snapshot(self):
        self.bar.alone = True
        hcgui.write_atomic(self.win / "panes", PANES)
        for key in (ord("h"), ord("l"), 10):
            self.bar.on_key(key, None, "")  # still loading: nothing to switch, nothing breaks
        self.assertEqual(hcgui.current_target(self.win), "")
        tm = FakeTmux().install(self)
        self.bar.on_key(ord("c"), None, "")
        self.assertEqual(tm.calls[-1][:3], ("split-window", "-f", "-hb"))

    def test_rows_wrap_info_and_hints(self):
        self.bar.draw(self.snap, "t1")
        lines = self.scr.lines()
        self.assertEqual(lines[0], hcgui.glyph(" ● alpha │ ○ beta │ ○ delta │ ○ gamma"))
        self.assertEqual(lines[1], hcgui.glyph(" ○ omega │ +"))
        self.assertEqual(lines[2:4], ["", ""])
        self.assertEqual(lines[4], hcgui.glyph(" Claude Code · ~/dev/app · idle"))  # the last row: no space name
        self.bar.handle_key(hcgui.curses.KEY_MOUSE, self.snap, "t1", click=(20, 4, 1))  # a click on the bar
        self.bar.draw(self.snap, "t1")
        # the space's name first, the line with the hc id, and the longest hint that fits (the folder gave way for it)
        self.assertEqual(self.scr.line(4), hcgui.glyph(" app · Claude Code · idle · t1") + "  " + "z zoom")
        self.scr.width = 80
        self.bar.handle_key(hcgui.curses.KEY_MOUSE, self.snap, "t1", click=(20, 2, 1))  # any row of the bar
        self.bar.draw(self.snap, "t1")
        line = self.scr.line(4)
        self.assertTrue(line.startswith(hcgui.glyph(" app · Claude Code · ~/dev/app · idle · t1")), line)  # whole
        self.assertTrue(line.endswith(hcgui.glyph("←→ switch  a menu  z zoom")), line)  # the longest beside it
        self.bar.hints_until = time.monotonic() - 0.1  # NOTICE_SECONDS later: the name, the id and the hints go
        self.bar.draw(self.snap, "t1")
        self.assertEqual(self.scr.line(4), hcgui.glyph(" Claude Code · ~/dev/app · idle"))
        reversed_cells = [x for (y, x), (_, attr) in self.scr.cells.items() if attr & hcgui.curses.A_REVERSE]
        self.assertEqual((min(reversed_cells), max(reversed_cells)), (0, 8))  # the shown tab only

    def test_a_newly_shown_terminal_gets_all_its_info_then_the_short_line(self):
        """Owner, 24 Nov: the row below the tabs gives all the info once a terminal is shown, then hides it."""
        now = time.monotonic()
        self.bar.note_shown("t1", now)  # the window's first terminal
        self.bar.draw(self.snap, "t1")
        self.assertTrue(self.scr.line(4).startswith(hcgui.glyph(" app · Claude Code")), self.scr.line(4))
        self.assertIn("· t1", self.scr.line(4))
        self.bar.hints_until = now - 0.1  # NOTICE_SECONDS later
        self.bar.note_shown("t1", now)  # the same terminal at the next round: nothing new
        self.bar.draw(self.snap, "t1")
        self.assertEqual(self.scr.line(4), hcgui.glyph(" Claude Code · ~/dev/app · idle"))
        self.bar.note_shown("t2", now)  # a switch: all the info again
        self.assertEqual(self.bar.hints_until, now + hcgui.NOTICE_SECONDS)
        self.bar.hints_until = 0.0
        self.bar.note_shown("", now)  # nothing shown: no info
        self.bar.note_shown("t2", now)  # shown again after nothing: it is new again
        self.assertEqual(self.bar.hints_until, now + hcgui.NOTICE_SECONDS)

    def test_the_row_below_the_tabs_carries_the_id_in_any_pane(self):
        """TAB_ROWS (two) rows: one row of tabs (scrolled when they do not fit), then the info row; a click shows the
        space's name, the line with its id and a hint there (review finding of the three-row bar: the id never
        showed when the tabs wrapped)."""
        self.scr.height = hcgui.TAB_ROWS
        self.bar.draw(self.snap, "t1")
        self.assertIn("alpha", self.scr.line(0))
        self.assertEqual(self.scr.line(1), hcgui.glyph(" Claude Code · ~/dev/app · idle"))
        self.bar.handle_key(hcgui.curses.KEY_MOUSE, self.snap, "t1", click=(30, 1, 1))  # a click on the bar
        self.bar.draw(self.snap, "t1")
        line = self.scr.line(1)
        self.assertTrue(line.startswith(" app · ") and "· t1" in line, line)
        self.scr.height = 3  # a taller pane: the tabs wrap, the info row is still the last one
        self.bar.draw(self.snap, "t1")
        self.assertTrue(self.scr.line(2).startswith(" app · ") and "· t1" in self.scr.line(2), self.scr.line(2))
        self.bar.hints_until = time.monotonic() - 0.1
        self.bar.draw(self.snap, "t1")
        self.assertEqual(self.scr.line(2), hcgui.glyph(" Claude Code · ~/dev/app · idle"))

    def test_one_and_two_row_panes(self):
        self.scr.height = 1
        self.bar.draw(self.snap, "t3")
        self.assertIn("gamma", self.scr.line(0))  # scrolled to the shown tab
        self.scr.height = 2
        self.bar.draw(self.snap, "t1")
        self.assertIn("alpha", self.scr.line(0))
        self.assertEqual(self.scr.line(1), hcgui.glyph(" Claude Code · ~/dev/app · idle"))  # TAB_ROWS: the tab bar
        self.scr.height = 0
        self.bar.draw(self.snap, "t1")

    def test_click_on_a_wrapped_tab_and_on_plus(self):
        self.bar.draw(self.snap, "t1")
        with mock.patch.object(hcgui, "read_mouse", return_value=(3, 1, 1)):
            self.bar.handle_key(hcgui.curses.KEY_MOUSE, self.snap, "t1")
        self.assertEqual(hcgui.current_target(self.win), "t5")  # omega, first tab of the second row
        calls = []

        def fake(*args, **kw):
            calls.append(args)
            return '{"address": "t77"}'

        with mock.patch.object(hcgui, "read_mouse", return_value=(12, 1, 1)), mock.patch.object(hcgui, "run_hc", fake):
            self.bar.handle_key(hcgui.curses.KEY_MOUSE, self.snap, "t5")
            self.bar.handle_key(hcgui.curses.KEY_MOUSE, self.snap, "t5")  # a double click
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][-4:], ("--cwd", "/Users/x/dev/app", "--label", "space=app"))
        self.assertEqual(hcgui.current_target(self.win), "t77")

    def test_left_right_switch_and_stop_at_the_ends(self):
        self.bar.step(self.snap, "t1", 1)
        self.assertEqual(hcgui.current_target(self.win), "t2")
        gen = (self.win / "gen").read_text()
        self.bar.step(self.snap, "t1", -1)  # already on the first tab: nothing is restarted
        self.bar.step(self.snap, "t5", 1)   # tab order is alpha beta delta gamma omega: omega is the last
        self.assertEqual((self.win / "gen").read_text(), gen)
        self.bar.step(self.snap, "t4", 1)   # delta -> gamma
        self.assertEqual(hcgui.current_target(self.win), "t3")
        self.bar.step(self.snap, "gone", 1)  # nothing of this group is shown: first tab
        self.assertEqual(hcgui.current_target(self.win), "t1")
        self.bar.step(self.snap, "gone", -1)
        self.assertEqual(hcgui.current_target(self.win), "t5")

    def test_failed_plus_shows_a_notice_that_goes_away(self):
        def fail(*args, **kw):
            raise subprocess.CalledProcessError(1, "hc", stderr='{"error":{"message":"no such machine"}}')

        with mock.patch.object(hcgui, "run_hc", fail):
            self.bar.plus(self.snap)
        self.bar.draw(self.snap, "t1")
        self.assertEqual(self.scr.line(4), " new: no such machine")
        self.bar.notice.until = 0
        self.bar.draw(self.snap, "t1")
        self.assertTrue(self.scr.line(4).startswith(" Claude Code"))  # the row below the tabs again

    def test_z_zooms_the_shown_terminal_or_says_nothing_is_shown(self):
        hcgui.write_atomic(self.win / "panes", PANES)
        tm = FakeTmux().install(self)
        self.bar.handle_key(ord("z"), self.snap, "")
        self.assertEqual(self.bar.notice.current(), "z: nothing shown")
        self.assertEqual(tm.calls, [])
        hcgui.show("t1", self.win)
        with mock.patch.object(hcgui, "attach_pid", return_value=4242):
            self.bar.notice.clear()
            self.bar.handle_key(ord("z"), self.snap, "t1")
        self.assertEqual(self.bar.notice.current(), "")
        self.assertEqual(tm.calls[-1], ("select-pane", "-t", "%0", ";", "resize-pane", "-Z", "-t", "%0"))

    def test_u_is_no_key_here(self):
        # u shows or hides the usage lines in the sidebar only: the tab bar has none, and the key is free here too
        hcgui.show("t1", self.win)
        for key in ("u", "U"):
            self.bar.handle_key(ord(key), self.snap, "t1")
            self.assertEqual((self.bar.notice.current(), self.bar.menu, self.bar.prompt), ("", None, None))
        self.assertEqual(hcgui.current_target(self.win), "t1")
        self.assertFalse((self.state / "usagelines").exists())
        self.assertIsNone(re.search(r"\bu\b", hcgui.tab_keys(True) + hcgui.tab_keys(False)))
        letters = [k for k, _ in hcgui.KEY_HELP if len(k) == 1]
        self.assertEqual(len(letters), len(set(letters)))  # no key of the sidebar twice

class TabEngineTests(unittest.TestCase):
    """The tab bar runs the engine (a thread of its own) only while its window has no live sidebar."""

    TERMS = [term("t1", "/Users/x/dev", "claude-code", "alpha", "idle"),
             term("t2", "/Users/x/dev", "zsh", "beta"),
             term("t3", "/Users/x/dev/other", "claude-code", "o1", "done")]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"
        self.hc = FakeHc(self.TERMS)
        for target, value in ((hcgui, {"run_hc": self.hc}), (hcgui.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scr = FakeScr(5, 60)
        self.bar = hcgui.TabBar(self.scr, self.win, self.state)
        self.addCleanup(self.bar.stop_engine)  # runs before the patches end

    def snap(self):
        return hcgui.read_snapshot(self.win)

    def test_engine_only_without_a_live_sidebar_and_it_stops_when_one_appears(self):
        hcgui.write_atomic(self.win / "sidebar.pid", f"{os.getpid()}\n")  # stand-in for a live sidebar
        for now in (100.0, 200.0):
            self.bar.watch_sidebar(now)
            self.assertIsNone(self.bar.engine)
            self.assertFalse(self.bar.alone)
        hcgui.write_atomic(self.win / "sidebar.pid", f"{dead_pid()}\n")  # it died; a hangup leaves the file
        self.bar.watch_sidebar(300.0)
        self.bar.watch_sidebar(300.0 + hcgui.ENGINE_GRACE - 0.1)
        self.assertIsNone(self.bar.engine)  # the grace of a normal start
        self.assertEqual(self.hc.calls, [])
        self.bar.watch_sidebar(300.0 + hcgui.ENGINE_GRACE)
        engine = self.bar.engine
        self.assertIsNotNone(engine)
        self.assertTrue(self.bar.alone)
        self.assertTrue(wait_for(lambda: self.snap() is not None))  # its own snapshot, from its own hc ls
        self.assertEqual([t["label"] for t in self.snap()["tabs"]], ["alpha", "beta"])
        self.bar.watch_sidebar(310.0)
        self.assertIs(self.bar.engine, engine)  # one engine, not one per round
        hcgui.write_atomic(self.win / "sidebar.pid", f"{os.getpid()}\n")  # a sidebar is back
        self.bar.watch_sidebar(311.0)
        self.assertIsNone(self.bar.engine)
        self.assertFalse(self.bar.alone)
        self.assertTrue(engine.stopped.is_set())
        time.sleep(0.3)  # a listing it was in finishes
        calls = len(self.hc.calls)
        hcgui.write_atomic(self.win / "poke", "x\n")  # would start a listing at once if it still ran
        time.sleep(0.6)
        self.assertEqual(len(self.hc.calls), calls)

    def test_hidden_starts_the_engine_at_once(self):
        hcgui.write_sidebar_state("hidden", self.state)  # the sidebar wrote it before it ended
        self.bar.watch_sidebar(100.0)
        self.assertIsNotNone(self.bar.engine)
        self.assertTrue(self.bar.alone)

    def test_a_normal_start_runs_no_second_engine(self):
        self.bar.watch_sidebar(100.0)  # both panes start; the sidebar has not written its pid yet
        hcgui.write_atomic(self.win / "sidebar.pid", f"{os.getpid()}\n")
        for now in (101.0, 100.0 + hcgui.ENGINE_GRACE, 200.0):
            self.bar.watch_sidebar(now)
            self.assertIsNone(self.bar.engine, now)

    def test_everything_works_with_the_sidebar_hidden(self):
        """Tabs of the current space, switching, +, the info line, and the tabs following the shown terminal into
        another space: all from the tab bar's own engine."""
        hcgui.write_sidebar_state("hidden", self.state)
        self.bar.watch_sidebar(100.0)
        self.assertTrue(wait_for(lambda: hcgui.current_target(self.win) == "t1"))  # the start opens the space
        self.assertTrue(wait_for(lambda: (self.snap() or {}).get("name") == "dev"))
        self.bar.draw(self.snap(), "t1")
        self.assertEqual(self.scr.line(0), hcgui.glyph("› ● alpha │ ○ beta │ +"))
        self.assertEqual(self.scr.line(self.scr.height - 1), hcgui.glyph("  Claude Code · ~/dev · idle"))
        self.bar.on_key(ord("l"), self.snap(), "t1")  # switch
        self.assertEqual(hcgui.current_target(self.win), "t2")
        self.assertTrue(wait_for(lambda: hcgui.read_last(self.state).get("space:dev") == "t2"))  # remembered
        self.bar.plus(self.snap())  # a new shell in this space: the engine lists it at once (poke)
        new = hcgui.current_target(self.win)
        self.assertNotIn(new, ("t1", "t2"))
        self.assertTrue(wait_for(lambda: new in [t["address"] for t in (self.snap() or {}).get("tabs", [])]))
        hcgui.show("t2", self.win)
        self.assertTrue(wait_for(lambda: self.bar.engine.seen == ("t2", "space:dev")))
        self.hc.terms[1]["cwd"] = "/Users/x/dev/other"  # the shown terminal moves to another space
        hcgui.write_atomic(self.win / "poke", "x\n")
        self.assertTrue(wait_for(lambda: (self.snap() or {}).get("name") == "other"))
        self.assertEqual(hcgui.read_text(self.state / "group"), "space:other")
        self.assertIn("t2", [t["address"] for t in self.snap()["tabs"]])


class UnlistedShownTests(unittest.TestCase):
    """The tabs stay with the shown terminal when a listing misses it (a rename meant for the shown terminal t3q went
    to another account's session rig/t5, whose tab the tab bar showed above t3q). Two accounts on one Mac mini: its
    own (mini, me@mini) and a shared one (rig, guest@mini); the view on mini/t3q in the space beta."""

    TERMS = [dict(term("rig/t5", "/Users/guest", "claude-code", None, "done"), turn=10),
             term("mini/t3p", "/Users/me", "zsh"), term("mini/t3q", "/Users/me", "zsh")]
    INFOS = {"mini/t3p": {"labels": {"space": "alpha"}}, "mini/t3q": {"labels": {"space": "beta"}}}
    MACHINES = [("rig", "guest@mini"), ("mini", "me@mini")]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"
        self.hc = FakeHc(self.TERMS, self.INFOS, machines=self.MACHINES)
        self.down = False  # `hc ls` fails (the cores not reached yet); `hc machine ls` still answers

        def run(*args, **kw):
            if self.down and args[:2] == ("ls", "--json"):
                raise subprocess.TimeoutExpired("hc", 10)
            return self.hc(*args, **kw)

        self.shows = []  # every show(): a pick, never wanted from a listing
        real_show = hcgui.show

        def show(address, win=hcgui.WINDOW, title=None):
            self.shows.append(address)
            real_show(address, win, title)

        for target, value in ((hcgui, {"run_hc": run, "show": show, "attach_pid": lambda win=None: 4242}),
                              (hcgui.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        hcgui.write_servers_shown(True, self.state)
        hcgui.write_atomic(self.state / "group", "space:beta\n")  # the group shown last
        hcgui.write_atomic(self.win / "target", "mini/t3q\n")  # the view is attached to it (attach_pid)

    def tabs(self):
        return [t["address"] for t in hcgui.read_snapshot(self.win)["tabs"]]

    def start(self, engine):
        """A start whose first `hc ls` fails: the sidebar brought back, or the tab bar taking over the engine."""
        self.down = True
        engine.refresh_once()
        self.assertTrue(engine.loaded.is_set())
        engine.begin(True)
        self.down = False
        engine.refresh_once()
        engine.sync()
        return engine

    def test_a_start_without_a_listing_keeps_the_shown_terminals_space(self):
        """The reproduction: with no terminal listed, the saved space looked gone and the fallback took the first
        server, guest@mini; its tab "t5" then stayed above t3q after the listing came back."""
        for engine in (hcgui.Sidebar(FakeScr(40, 30), self.state, self.win), hcgui.Engine(self.state, self.win)):
            self.start(engine)
            self.assertEqual(engine.cur, "space:beta", type(engine).__name__)
            self.assertEqual(hcgui.read_text(self.state / "group"), "space:beta")
            self.assertEqual(self.tabs(), ["mini/t3q"])
            self.assertEqual(self.shows, [])  # the view was never switched

    def test_a_start_without_a_listing_follows_the_shown_terminal_once_it_is_listed(self):
        """The saved group names another space (set in another window): once listed, the shown terminal's space
        becomes the current one, as a start with a listing does (begin)."""
        hcgui.write_atomic(self.state / "group", "space:alpha\n")
        engine = self.start(hcgui.Engine(self.state, self.win))
        self.assertEqual((engine.cur, self.tabs(), self.shows), ("space:beta", ["mini/t3q"], []))

    def test_the_tab_bars_own_engine_keeps_the_space_too(self):
        """The sidebar hidden: the tab bar's engine (its own threads) starts while `hc ls` fails."""
        hcgui.write_sidebar_state("hidden", self.state)
        self.down = True
        bar = hcgui.TabBar(FakeScr(5, 60), self.win, self.state)
        self.addCleanup(bar.stop_engine)
        bar.watch_sidebar(100.0)
        self.assertTrue(wait_for(lambda: (self.win / "tabs.json").exists()))  # begin() has run, with no listing
        self.assertEqual(bar.engine.cur, "space:beta")
        self.down = False
        hcgui.write_atomic(self.win / "poke", "x\n")
        self.assertTrue(wait_for(lambda: (hcgui.read_snapshot(self.win) or {}).get("tabs")))
        self.assertEqual((bar.engine.cur, self.tabs(), self.shows), ("space:beta", ["mini/t3q"], []))

    def test_a_start_whose_listing_misses_the_shown_terminal_keeps_the_view(self):
        """The sidebar comes back while the Mac mini's own core is away for a moment: the view keeps t3q (it was
        switched to rig/t5, the fall-back group's terminal), and t3q's space comes back once it is listed."""
        mini = self.hc.terms
        self.hc.terms = [t for t in mini if t["address"].startswith("rig/")]
        engine = hcgui.Engine(self.state, self.win)
        engine.refresh_once()
        engine.begin(True)
        self.assertEqual((hcgui.current_target(self.win), self.shows), ("mini/t3q", []))
        self.hc.terms = mini
        engine.refresh_once()
        engine.sync()
        self.assertEqual((engine.cur, self.tabs(), self.shows), ("space:beta", ["mini/t3q"], []))

    def test_the_tabs_come_back_when_the_shown_terminal_is_listed_again(self):
        """A listing without the Mac mini's own terminals (its core away for a moment): the space has gone, so the
        fallback picks a group; once t3q is listed again, the tabs go back to its space, the view never moves."""
        side = hcgui.Sidebar(FakeScr(40, 30), self.state, self.win)
        side.refresh_once()
        side.sync()
        self.assertEqual(side.cur, "space:beta")
        mini = self.hc.terms
        self.hc.terms = [t for t in mini if t["address"].startswith("rig/")]
        side.refresh_once()
        side.sync()
        self.assertEqual(side.cur, "rig:rig")  # nothing else is listed
        self.hc.terms = mini
        side.refresh_once()
        side.sync()
        self.assertEqual((side.cur, self.tabs(), self.shows), ("space:beta", ["mini/t3q"], []))
        side.set_current("rig:rig")  # a later choice is not undone: the follow happens once
        side.sync()
        self.assertEqual(side.cur, "rig:rig")

    def test_a_shown_terminal_that_ended_still_falls_back(self):
        """No listing yet: nothing is decided. A listing without the shown terminal (it ended, its space with it):
        the fallback as before, and it stays."""
        side = hcgui.Sidebar(FakeScr(40, 30), self.state, self.win)
        self.down = True
        side.refresh_once()
        side.sync()
        self.assertEqual(side.cur, "space:beta")  # hc has not answered: the saved space is kept
        self.down = False
        self.hc.terms = [t for t in self.hc.terms if t["address"] != "mini/t3q"]
        side.refresh_once()
        side.sync()
        self.assertEqual(side.cur, "space:alpha")  # fallback_group: the first space (no space has an agent)
        side.refresh_once()
        side.sync()
        self.assertEqual((side.cur, self.shows), ("space:alpha", []))

    def test_a_terminal_of_a_hidden_server_keeps_the_tabs_where_they_are(self):
        """Listed, but in no group while the servers are hidden (shown alone from "needs you"): not missing, so the
        tabs stay with their space when the servers are shown again."""
        hcgui.write_servers_shown(False, self.state)
        side = hcgui.Sidebar(FakeScr(40, 30), self.state, self.win)
        side.refresh_once()
        side.sync()
        side.show_alone("rig/t5")
        self.assertEqual(side.cur, "space:beta")
        hcgui.write_servers_shown(True, self.state)
        side.sync()
        side.sync()
        self.assertEqual(side.cur, "space:beta")


STUB_HC = """#!/bin/sh
# stands in for hc: "attach <t>" stays until it is ended, like the real one
[ "$1" = attach ] || exit 0
case "$2" in fail*) echo "no terminal $2" >&2; exit 3 ;; esac
echo "start $2" >>"$STUB_LOG"
trap 'echo "end $2" >>"$STUB_LOG"; exit 143' TERM
while :; do sleep 0.02; done
"""


class ViewLoopTests(unittest.TestCase):
    """view.sh with a stand-in hc: what it attaches, in which order, and what it leaves behind."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.win = tmp / "state"
        self.log = tmp / "log"
        self.log.write_text("")
        (tmp / "bin").mkdir()
        self.hc = tmp / "bin" / "hc"
        self.hc.write_text(STUB_HC)
        self.hc.chmod(0o755)
        self.procs = []

    def start_view(self, **extra):
        env = dict(os.environ, HCGUI_HC=str(self.hc), HCGUI_STATE=str(self.win), STUB_LOG=str(self.log), **extra)
        env.pop("HCGUI_WINDOW", None)
        proc = subprocess.Popen(["/bin/sh", str(ROOT / "view.sh")], env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        self.procs.append(proc)
        self.addCleanup(self.stop_view, proc)
        self.wait_for(lambda: (self.win / "view.loop").exists())
        return proc

    def stop_view(self, proc):
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=5)
        proc.stdout.close()

    def wait_for(self, condition, timeout=6.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(0.02)
        return False

    def attached(self):
        """The targets with a start and no end yet."""
        live = []
        for line in self.log.read_text().split("\n"):
            word, _, target = line.partition(" ")
            if word == "start":
                live.append(target)
            elif word == "end" and target in live:
                live.remove(target)
        return live

    def test_pick_switch_and_fast_path(self):
        self.start_view()
        hcgui.show("a", self.win)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["a"]))
        self.assertTrue(self.wait_for(lambda: hcgui.attach_pid(self.win) != 0))
        started = time.monotonic()
        hcgui.show("b", self.win)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["b"]))
        self.assertLess(time.monotonic() - started, 2.0)

    def test_two_quick_picks_end_on_the_last_one(self):
        self.start_view()
        hcgui.show("a", self.win)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["a"]))
        for round_, gap in enumerate((0.0, 0.005, 0.010, 0.012, 0.015, 0.020, 0.030, 0.010, 0.015, 0.012)):
            first, last = f"b{round_}", f"c{round_}"
            hcgui.show(first, self.win)
            time.sleep(gap)
            hcgui.show(last, self.win)
            self.assertTrue(self.wait_for(lambda: self.attached() == [last]), (gap, self.attached()))
            time.sleep(0.5)  # and it stays there
            self.assertEqual(self.attached(), [last], gap)
            self.assertEqual(hcgui.current_target(self.win), last)

    def test_the_watcher_alone_switches_when_the_fast_path_finds_nothing(self):
        self.start_view()
        hcgui.show("a", self.win)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["a"]))
        with mock.patch.object(hcgui, "attach_pid", return_value=0):  # as if the pick came before view.pid existed
            hcgui.show("b", self.win)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["b"]))

    def test_burst_of_picks(self):
        self.start_view()
        for i in range(12):
            hcgui.show(f"t{i}", self.win)
            time.sleep(0.004 * (i % 4))
        self.assertTrue(self.wait_for(lambda: self.attached() == ["t11"]), self.attached())
        time.sleep(0.6)
        self.assertEqual(self.attached(), ["t11"])

    def test_saved_target_is_attached_at_start_unless_autoopen_is_off(self):
        hcgui.write_atomic(self.win / "target", "old\n")
        self.start_view(HCGUI_AUTOOPEN="0")
        time.sleep(0.6)
        self.assertEqual(self.attached(), [])
        hcgui.show("new", self.win)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["new"]))

    def test_saved_target_is_attached_at_start_by_default(self):
        hcgui.write_atomic(self.win / "target", "old\n")
        self.start_view()
        self.assertTrue(self.wait_for(lambda: self.attached() == ["old"]))

    def test_closing_the_pane_leaves_no_pid_file_and_no_attach(self):
        proc = self.start_view()
        hcgui.show("a", self.win)
        self.assertTrue(self.wait_for(lambda: (self.win / "view.pid").exists() and self.attached() == ["a"]))
        os.killpg(proc.pid, signal.SIGHUP)  # what closing the pane does
        proc.wait(timeout=5)
        self.assertTrue(self.wait_for(lambda: not (self.win / "view.pid").exists()))
        self.assertFalse((self.win / "view.loop").exists())
        self.assertEqual(hcgui.attach_pid(self.win), 0)

    def test_stale_pid_file_from_a_dead_view_is_removed_at_start(self):
        hcgui.write_atomic(self.win / "view.pid", "999999\n")
        self.start_view()
        self.assertFalse((self.win / "view.pid").exists())

    def test_failed_attach_keeps_its_message_and_names_the_exit_code(self):
        proc = self.start_view()
        hcgui.show("fail-x", self.win)
        time.sleep(1.0)
        os.killpg(proc.pid, signal.SIGTERM)
        out = proc.stdout.read().decode()
        self.assertIn("no terminal fail-x", out)
        self.assertIn("could not show fail-x (hc exit 3)", out)
        tail = out[out.index("no terminal fail-x"):out.index("could not show")]
        self.assertNotIn("\033[2J", tail)  # the screen is not wiped between hc's message and ours

    def test_ctrl_c_and_ctrl_z_do_not_end_the_loop(self):
        proc = self.start_view()
        for sig in (signal.SIGINT, signal.SIGTSTP, signal.SIGQUIT):
            os.kill(proc.pid, sig)
        time.sleep(0.3)
        self.assertIsNone(proc.poll())
        hcgui.show("a", self.win)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["a"]))

    def test_missing_hc_is_said_plainly(self):
        env = dict(os.environ, HCGUI_HC="/nonexistent/hc", HCGUI_STATE=str(self.win))
        out = subprocess.run(["/bin/sh", str(ROOT / "view.sh")], env=env, capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, timeout=10)
        self.assertEqual(out.returncode, 1)
        self.assertIn("hc not found at /nonexistent/hc", out.stdout)

    def test_windows_have_their_own_folder_and_old_ones_are_swept(self):
        shared = self.win
        mine, live, dead, fresh, other, view, gone = (shared / n for n in (
            "w-mine", "w-live", "w-dead", "w-fresh", "notes", "w-view", "w-gone"))
        old = time.time() - 3 * 86400
        for folder in (live, dead, fresh, other, view, gone):
            folder.mkdir(parents=True)
            (folder / "panes").write_text("side=1\n")
        (live / "sidebar.pid").write_text(f"{os.getpid()}\n")
        (dead / "sidebar.pid").write_text("999999\n")
        (view / "view.loop").write_text(f"{os.getpid()}\n")  # sidebar quit, the view still runs
        (gone / "view.loop").write_text("999999\n")
        (gone / "sidebar.pid").write_text("junk\n")
        for folder in (live, dead, other, view, gone):
            os.utime(folder, (old, old))
        env = dict(os.environ, HCGUI_HC=str(self.hc), HCGUI_STATE=str(shared), HCGUI_WINDOW=str(mine),
                   STUB_LOG=str(self.log))
        proc = subprocess.Popen(["/bin/sh", str(ROOT / "view.sh")], env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        self.addCleanup(self.stop_view, proc)
        self.assertTrue(self.wait_for(lambda: (mine / "view.loop").exists()))
        self.assertFalse(dead.exists())  # old, sidebar gone
        self.assertFalse(gone.exists())  # old, sidebar and view gone
        self.assertTrue(live.exists() and fresh.exists() and other.exists())
        self.assertTrue(view.exists())  # old, but its view loop is alive: it keeps its folder (and its attach)
        hcgui.show("a", mine)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["a"]))
        self.assertFalse((shared / "target").exists())

    def test_two_windows_do_not_disturb_each_other(self):
        shared = self.win
        views = []
        for name in ("w-one", "w-two"):
            env = dict(os.environ, HCGUI_HC=str(self.hc), HCGUI_STATE=str(shared), HCGUI_WINDOW=str(shared / name),
                       STUB_LOG=str(self.log))
            proc = subprocess.Popen(["/bin/sh", str(ROOT / "view.sh")], env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
            self.addCleanup(self.stop_view, proc)
            views.append(shared / name)
        self.assertTrue(self.wait_for(lambda: all((v / "view.loop").exists() for v in views)))
        hcgui.show("one-a", views[0])
        hcgui.show("two-a", views[1])
        self.assertTrue(self.wait_for(lambda: sorted(self.attached()) == ["one-a", "two-a"]))
        pid_two = hcgui.attach_pid(views[1])
        hcgui.show("one-b", views[0])  # a pick in window one
        self.assertTrue(self.wait_for(lambda: sorted(self.attached()) == ["one-b", "two-a"]))
        time.sleep(0.5)
        self.assertEqual(hcgui.attach_pid(views[1]), pid_two)  # window two's attach was never touched
        self.assertNotIn("end two-a", self.log.read_text())


class ClosedPaneTests(unittest.TestCase):
    """A pane that is closed while the hangup signal is switched off (started under nohup): nothing may stay behind."""

    def closed_pane(self, argv, env):
        import pty
        master, slave = pty.openpty()
        proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, env=env, cwd=str(ROOT),
                                start_new_session=True,
                                preexec_fn=lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN))
        os.close(slave)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        time.sleep(1.5)
        self.assertIsNone(proc.poll(), "it must be running before the pane is closed")
        os.close(master)  # the pane is closed
        try:
            proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            self.fail(f"{argv} still runs beside a terminal that is gone")

    def env(self, tmp):
        return dict(os.environ, HCGUI_STATE=tmp, HCGUI_GHOSTTY="0", HCGUI_AUTOOPEN="0", TERM="xterm-256color",
                    HCGUI_HC="/nonexistent/hc", PYTHONDONTWRITEBYTECODE="1")

    def test_tab_bar_and_sidebar_end(self):
        for mode in ("tabs", "sidebar"):
            with tempfile.TemporaryDirectory() as tmp:
                env = self.env(tmp)
                env.pop("HCGUI_WINDOW", None)
                self.closed_pane([sys.executable, str(ROOT / "hcgui.py"), mode], env)

    def test_view_ends(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "hc"
            stub.write_text(STUB_HC)
            stub.chmod(0o755)
            env = dict(self.env(tmp), HCGUI_HC=str(stub), STUB_LOG=os.path.join(tmp, "log"),
                       HCGUI_STATE=os.path.join(tmp, "state"))
            env.pop("HCGUI_WINDOW", None)
            self.closed_pane(["/bin/sh", str(ROOT / "view.sh")], env)
            self.assertFalse(os.path.exists(os.path.join(tmp, "state", "view.loop")))

    def test_view_relay_ends_and_view_sh_with_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "hc"
            stub.write_text(STUB_HC)
            stub.chmod(0o755)
            env = dict(self.env(tmp), HCGUI_HC=str(stub), STUB_LOG=os.path.join(tmp, "log"),
                       HCGUI_STATE=os.path.join(tmp, "state"))
            env.pop("HCGUI_WINDOW", None)
            self.closed_pane([sys.executable, str(ROOT / "hcgui.py"), "view"], env)
            self.assertTrue(wait_for(lambda: not os.path.exists(os.path.join(tmp, "state", "view.loop"))))


def applescript_literals(line):
    """The contents of every AppleScript string literal on a line, unescaped (\\\\ and \\")."""
    return [re.sub(r"\\(.)", r"\1", m) for m in re.findall(r'"((?:[^"\\]|\\.)*)"', line)]


class PaneCommandTests(unittest.TestCase):
    """The command of a sidebar brought back ("›"), and the tmux split that runs it."""

    def test_env_pairs(self):
        environ = {"HCGUI_STATE": "/s", "HCGUI_WINDOW": "/elsewhere", "HCGUI_HC": "/my bin/hc", "PATH": "/bin",
                   "HCGUI_bad": "x", "XHCGUI_A": "1", "HCGUI_TMUX": "1"}
        pairs = hcgui.hcgui_env(environ)
        self.assertEqual(pairs, [("HCGUI_HC", "/my bin/hc"), ("HCGUI_STATE", "/s"), ("HCGUI_TMUX", "1")])
        line = hcgui.pane_command("tabs", Path("/w"), Path("/b"), pairs + [("HCGUI_WINDOW", "/x"), ("BAD NAME", "1")])
        self.assertEqual(line, "exec env HCGUI_WINDOW=/w HCGUI_HC='/my bin/hc' HCGUI_STATE=/s HCGUI_TMUX=1 "
                               "python3 /b/hcgui.py tabs")  # the window folder given wins over one in the pairs

    def test_hcgui_s_own_terminal_type_goes_along(self):
        environ = {"HCGUI_HC": "/h", "TERM": "xterm-hcgui", "TERMINFO": "/w/terminfo"}
        pairs = hcgui.hcgui_env(environ)
        self.assertEqual(pairs, [("HCGUI_HC", "/h"), ("TERM", "xterm-hcgui"), ("TERMINFO", "/w/terminfo")])
        self.assertEqual(hcgui.pane_command("sidebar", Path("/w"), Path("/b"), pairs),
                         "exec env HCGUI_WINDOW=/w HCGUI_HC=/h TERM=xterm-hcgui TERMINFO=/w/terminfo "
                         "python3 /b/hcgui.py sidebar")
        other = hcgui.hcgui_env({"HCGUI_HC": "/h", "TERM": "screen-256color", "TERMINFO": "/x"})
        self.assertEqual(other, [("HCGUI_HC", "/h")])  # tmux's own type: the new pane gets it from tmux
        self.assertEqual(hcgui.pane_command("tabs", Path("/w"), Path("/b"), [("TERM", "vt100"), ("TERMINFO", "/x")]),
                         "exec env HCGUI_WINDOW=/w python3 /b/hcgui.py tabs")

    def test_quoting_survives_spaces_and_quotes_in_the_window_folder(self):
        line = hcgui.pane_command("sidebar", Path("/Users/a b/it's"), Path("/opt/m m"), [("HCGUI_HC", 'x"y')])
        self.assertEqual(subprocess.run(["/bin/sh", "-c", "set -- " + line[len("exec "):] + '; printf "%s|" "$@"'],
                                        capture_output=True, text=True).stdout,
                         "env|HCGUI_WINDOW=/Users/a b/it's|HCGUI_HC=x\"y|python3|/opt/m m/hcgui.py|sidebar|")

    def test_the_tab_bar_passes_its_settings_and_its_own_folder(self):
        with mock.patch.dict(os.environ, {"HCGUI_WIDTH": "28", "HCGUI_HC": "/h"}):
            pairs = hcgui.hcgui_env(os.environ)
        self.assertIn(("HCGUI_WIDTH", "28"), pairs)
        self.assertIn(("HCGUI_STATE", _DEFAULT_STATE), pairs)
        self.assertEqual(hcgui.BASE.resolve(), ROOT)

    def test_split_sidebar_makes_a_full_height_pane_and_writes_its_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            win = Path(tmp)
            tm = FakeTmux().install(self)
            with mock.patch.dict(os.environ, {"TMUX_PANE": ""}):
                self.assertEqual(hcgui.split_sidebar(win, Path("/b"), [], 33), "")  # no pane to split from
            self.assertEqual(tm.calls, [])
            self.assertEqual(hcgui.split_sidebar(win, Path("/b"), [], 33), "%7")  # no view id: from this pane
            self.assertEqual(tm.calls[-1][7], "%1")
            tm.calls.clear()
            hcgui.write_atomic(win / "panes", "tabs=%2\nview=%0\n")
            self.assertEqual(hcgui.split_sidebar(win, Path("/b"), [("HCGUI_HC", "/h")], 33), "%7")
            self.assertEqual(tm.calls[-1][:12], ("split-window", "-f", "-hb", "-d", "-l", "33", "-t", "%0", "-P", "-F",
                                                 "#{pane_id}", f"exec env HCGUI_WINDOW={win} HCGUI_HC=/h python3 "
                                                 "/b/hcgui.py sidebar"))
            self.assertEqual(hcgui.read_panes(win), {"tabs": "%2", "view": "%0", "side": "%7"})
            tm.split_id = ""  # tmux failed
            self.assertEqual(hcgui.split_sidebar(win, Path("/b"), [], 33), "")
            hcgui.write_atomic(win / "panes", 'view="; rm -rf x\n')
            with mock.patch.dict(os.environ, {"TMUX_PANE": ""}):
                self.assertEqual(hcgui.split_sidebar(win, Path("/b"), [], 33), "")  # not a pane id: nothing is run
            self.assertEqual(len(tm.calls), 2)


class TmuxTests(unittest.TestCase):
    def test_off_outside_tmux_and_in_the_tests(self):
        with mock.patch.object(hcgui.subprocess, "run") as run:
            self.assertIsNone(hcgui.tmux("select-pane", "-t", "%0"))  # no $TMUX
            with mock.patch.dict(os.environ, {"TMUX": "/tmp/x,1,0", "HCGUI_TMUX": "0"}):
                self.assertIsNone(hcgui.tmux("select-pane", "-t", "%0"))
        run.assert_not_called()

    def test_never_raises_and_returns_the_output(self):
        with mock.patch.dict(os.environ, {"TMUX": "/tmp/x,1,0", "HCGUI_TMUX": "1"}):
            with mock.patch.object(hcgui.subprocess, "run", side_effect=OSError("gone")):
                self.assertIsNone(hcgui.tmux("display", "-p", "x"))
            done = subprocess.CompletedProcess([], 0, stdout="1 \n", stderr="")
            with mock.patch.object(hcgui.subprocess, "run", return_value=done) as run:
                self.assertEqual(hcgui.tmux("display", "-p", "x"), "1 \n")
            self.assertEqual(run.call_args[0][0][1:], ["display", "-p", "x"])
            failed = subprocess.CompletedProcess([], 1, stdout="", stderr="no pane")
            with mock.patch.object(hcgui.subprocess, "run", return_value=failed):
                self.assertIsNone(hcgui.tmux("display", "-p", "x"))

    def test_pane_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            win = Path(tmp)
            hcgui.write_atomic(win / "panes", 'side=%1\ntabs=T-1\nview=%0"\n')
            self.assertEqual([hcgui.pane_id(k, win) for k in ("side", "tabs", "view", "none")], ["%1", "", "", ""])
        for value, want in (("%3", "%3"), ("", ""), ("3", ""), ("%3;x", "")):
            with mock.patch.dict(os.environ, {"TMUX_PANE": value}):
                self.assertEqual(hcgui.own_pane(), want)

    def test_focus_and_zoom(self):
        with tempfile.TemporaryDirectory() as tmp:
            win = Path(tmp)
            tm = FakeTmux().install(self)
            hcgui.focus_view(win)  # no panes file: nothing
            self.assertEqual(tm.calls, [])
            hcgui.write_atomic(win / "panes", PANES)
            hcgui.focus_view(win)
            hcgui.focus_pane("tabs", win)
            self.assertEqual(tm.selected(), ["%0", "%2"])
            self.assertEqual(hcgui.zoom_view(win), "z: nothing shown")
            hcgui.show("t1", win)
            self.assertEqual(tm.calls[-1], ("if-shell", "-F", "-t", "%0", "#{pane_in_mode}",
                                            "send-keys -X -t %0 cancel"))  # a pick leaves a scrolled-back view
            with mock.patch.object(hcgui, "attach_pid", return_value=4242):
                self.assertEqual(hcgui.zoom_view(win), "")
            self.assertEqual(tm.calls[-1], ("select-pane", "-t", "%0", ";", "resize-pane", "-Z", "-t", "%0"))

    def test_window_look_and_size_pane(self):
        p = hcgui.parse_window_look
        self.assertEqual(p("0 120 40 30 40\n"), hcgui.WindowLook(False, 120, 40, 30, 40))
        self.assertEqual(p("1 200 50 30 3\n"), hcgui.WindowLook(True, 200, 50, 30, 3))
        self.assertEqual(p("junk\n0 120 40 30 40\n"), hcgui.WindowLook(False, 120, 40, 30, 40))  # the last line
        for junk in (None, "", "x 1 2 3 4", "2 1 1 1 1", "0 1", "0 a 40 1 1", "0 120 40 9"):
            self.assertIsNone(p(junk))
        scr = FakeScr(10, 50)
        tm = FakeTmux(scr).install(self)
        self.assertEqual(hcgui.size_pane("%1", cols=30).pane_width, 30)
        self.assertEqual(hcgui.size_pane("%1", rows=3).pane_height, 3)
        self.assertEqual(tm.calls[0], ("resize-pane", "-t", "%1", "-x", "30", ";", "display", "-p", "-t", "%1",
                                       hcgui.LOOK_FORMAT))  # the window's width from the same call
        with mock.patch.object(hcgui, "tmux", return_value=None):
            self.assertIsNone(hcgui.size_pane("%1", cols=30))


class ProgramTests(unittest.TestCase):
    """hcgui.py itself in a pseudo terminal: hiding ends the sidebar with exit status 0, and a sidebar started while
    the state is hidden ends before it draws anything. With HCGUI_GHOSTTY=0 the program ends all the same; only the
    focus script is skipped."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"
        self.win.mkdir(parents=True)

    def start(self, mode="sidebar", **extra):
        import pty
        master, slave = pty.openpty()
        env = dict(os.environ, HCGUI_STATE=str(self.state), HCGUI_WINDOW=str(self.win), HCGUI_GHOSTTY="0",
                   HCGUI_AUTOOPEN="0", HCGUI_HC="/nonexistent/hc", TERM="xterm-256color",
                   PYTHONDONTWRITEBYTECODE="1")
        env.update(extra)
        proc = subprocess.Popen([sys.executable, str(ROOT / "hcgui.py"), mode], stdin=slave, stdout=slave,
                                stderr=slave, env=env, cwd=str(ROOT), start_new_session=True)
        os.close(slave)
        output = bytearray()

        def drain():
            while True:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    return
                if not chunk:
                    return
                output.extend(chunk)

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()

        def stop():
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            os.close(master)
            reader.join(2)

        self.addCleanup(stop)
        return proc, master, output

    def test_a_sidebar_started_hidden_ends_without_drawing(self):
        hcgui.write_sidebar_state("hidden", self.state)
        proc, _, output = self.start()
        self.assertEqual(proc.wait(timeout=10), 0)
        time.sleep(0.2)
        self.assertEqual(bytes(output), b"")  # not even curses' screen switch
        self.assertFalse((self.win / "sidebar.pid").exists())
        self.assertEqual(hcgui.read_sidebar_state(self.state), "hidden")

    def test_q_and_c_c_end_the_sidebar_and_leave_hidden(self):
        for keys in (b"q", b"cc"):
            hcgui.write_sidebar_state("open", self.state)
            proc, master, output = self.start()
            self.assertTrue(wait_for(lambda: (self.win / "sidebar.pid").exists(), 10), keys)
            self.assertTrue(wait_for(lambda: b"fold" in output, 10), keys)  # drawn: the loop reads keys now
            os.write(master, keys)
            self.assertEqual(proc.wait(timeout=10), 0, keys)
            self.assertEqual(hcgui.read_sidebar_state(self.state), "hidden", keys)
            self.assertFalse((self.win / "sidebar.pid").exists(), keys)

    def test_both_panes_set_their_title_and_clear_their_folder_first(self):
        hcgui.write_sidebar_state("open", self.state)
        for mode, drawn in (("sidebar", b"fold"), ("tabs", b" + ")):  # the tab bar: its "+" (no hints until a click)
            proc, _, output = self.start(mode)
            self.assertTrue(wait_for(lambda: drawn in output, 10), (mode, bytes(output)))  # noqa: B023
            self.assertTrue(bytes(output).startswith(b"\x1b]2;hcGUI\x07\x1b]7;\x07"), (mode, bytes(output[:40])))
            proc.kill()
            proc.wait(timeout=5)

    def test_the_tab_bar_alone_draws_the_opener_and_its_own_tabs(self):
        stub = Path(self._tmp.name) / "hc"
        stub.write_text('#!/bin/sh\ncase "$1" in\n'
                        'ls) echo \'{"terminals":[{"address":"t1","agent":"claude-code","cwd":"/Users/x/dev/app",'
                        '"name":"alpha","status":"idle"},{"address":"t2","agent":"zsh","cwd":"/Users/x/dev/app",'
                        '"name":"beta"}]}\' ;;\nget) echo \'{"labels":{}}\' ;;\n*) exit 3 ;;\nesac\n')
        stub.chmod(0o755)
        hcgui.write_sidebar_state("hidden", self.state)
        proc, master, output = self.start("tabs", HCGUI_HC=str(stub))
        self.assertTrue(wait_for(lambda: hcgui.read_snapshot(self.win) is not None, 10))  # its engine wrote it
        self.assertEqual([t["label"] for t in hcgui.read_snapshot(self.win)["tabs"]], ["alpha", "beta"])
        self.assertTrue(wait_for(lambda: b"beta" in output and "›".encode() in output, 10), bytes(output))
        self.assertIsNone(proc.poll())


    def test_the_separator_dragged_in_the_real_program_both_encodings(self):
        """hcgui.py sidebar in a 24x30 pseudo terminal with a stand-in hc: a press on the separator, moves with
        the button held, the release: the file "split". X10 codes (xterm-256color) and SGR codes (a copy of
        Ghostty's terminfo, which asks for 1006)."""
        import fcntl
        import termios
        stub = Path(self._tmp.name) / "hc"
        stub.write_text('#!/bin/sh\ncase "$1" in\n'
                        'ls) echo \'{"terminals":[{"address":"t1","agent":"claude-code","cwd":"/Users/x/dev/app",'
                        '"name":"alpha","status":"idle"},{"address":"t2","agent":"zsh","cwd":"/Users/x/dev/app",'
                        '"name":"beta"}]}\' ;;\nget) echo \'{"labels":{}}\' ;;\n'
                        'machine) echo \'{"machines":[]}\' ;;\n*) exit 3 ;;\nesac\n')
        stub.chmod(0o755)
        x10 = lambda code, x, y: b"\x1b[M" + bytes([32 + code, 33 + x, 33 + y])
        sgr = lambda code, x, y, end="M": f"\x1b[<{code};{x + 1};{y + 1}{end}".encode()
        reports = DragReportTests("test_report_drags_writes_after_a_refresh")
        reports.addCleanup = self.addCleanup
        for term, extra, codes in (("xterm-256color", {}, (x10(0, 2, 20), x10(32, 2, 12), x10(3, 2, 8))),
                                   ("xterm-ghostty", {"TERMINFO": reports.terminfo()},
                                    (sgr(0, 2, 20), sgr(32, 2, 12), sgr(0, 2, 8, "m")))):
            hcgui.clear_split(self.state)
            hcgui.write_sidebar_state("open", self.state)
            proc, master, output = self.start(HCGUI_HC=str(stub), TERM=term, LINES="24", COLUMNS="30", **extra)
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct_winsize(24, 30))
            # drawn with the agent: rule on line 20 (23 lines of list: the line, "agents", alpha; alone in its
            # space app, so no "app · 1" heading)
            self.assertTrue(wait_for(lambda: b"alpha" in output and b"fold" in output, 10), term)  # noqa: B023
            time.sleep(0.3)
            for code in codes:
                os.write(master, code)
                time.sleep(0.1)
            self.assertTrue(wait_for(lambda: hcgui.read_text(self.state / "split") == "8/24", 5),
                            (term, hcgui.read_text(self.state / "split")))
            raw = bytes(output)
            self.assertLess(raw.index(b"\x1b[?1000h" if term == "xterm-256color" else b"\x1b[?1006;1000h"),
                            raw.index(b"\x1b[?1002h"), term)
            os.write(master, b"q")
            self.assertEqual(proc.wait(timeout=10), 0, term)
            self.assertEqual(hcgui.read_text(self.state / "split"), "8/24", term)
            self.assertTrue(wait_for(lambda: b"\x1b[?1002l" in output, 5), term)  # noqa: B023


def struct_winsize(rows, cols):
    import struct
    return struct.pack("HHHH", rows, cols, 0, 0)


class TabMenuTests(unittest.TestCase):
    """A right click on a tab: its menu, the rename, move and close questions, and what they do."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.win = Path(self._tmp.name)
        self.state = self.win / "shared"
        patcher = mock.patch.object(hcgui.curses, "color_pair", lambda n: n << 8)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.scr = FakeScr(5, 70)
        self.bar = hcgui.TabBar(self.scr, self.win, self.state)
        self.addCleanup(self.bar.stop_engine)
        self.hc = FakeHc([term("mini/t1", "/Users/x/dev/app", "claude-code", "alpha", "idle"),
                          term("mini/t2", "/Users/x/dev/app", "zsh", "beta"),
                          term("mini/t3", "/Users/x/dev/app", "zsh", "gamma"),
                          term("mini/t9", "/Users/x/dev/web", "zsh", "web")],
                         infos={"mini/t3": {"parent": "mini/t1", "dies": True}})
        self.snap = self.snapshot()
        hcgui.write_atomic(self.win / "panes", PANES)
        self.tm = FakeTmux().install(self)

    def snapshot(self):
        terms = hcgui.parse(self.hc("ls", "--json"))
        infos = {a: hcgui.parse_info(self.hc("get", a), a) for a in [t.address for t in terms]}
        spaces, _ = hcgui.build_groups(terms, "mini", infos)
        app = next(g for g in spaces if g.name == "app")
        hcgui.write_snapshot(app, self.win, everything=terms, infos=infos)
        return hcgui.read_snapshot(self.win)

    def press(self, x, y, button=1, shown="mini/t1"):
        with mock.patch.object(hcgui, "read_mouse", return_value=(x, y, button)):
            self.bar.on_key(hcgui.curses.KEY_MOUSE, self.snap, shown)
        self.bar.draw(self.snap, shown)

    def key(self, k, shown="mini/t1"):
        self.bar.on_key(ord(k) if isinstance(k, str) else k, self.snap, shown)
        self.bar.draw(self.snap, shown)

    def tab_x(self, label):
        return next(s.x for s in self.bar.layout.segs if s.kind == "tab" and label in s.text)

    def entry_x(self, word):
        return next(s.x for s in self.bar.menu_segs if s.kind == "entry" and s.text.lower().startswith(word))

    # pure parts ------------------------------------------------------------------------------------------------
    def test_entries_move_only_in_a_space(self):
        self.assertEqual([e.label for e in hcgui.tab_menu_entries("space")],
                         ["New terminal", "Rename", "Move to space", "Close"])
        self.assertEqual([e.label for e in hcgui.tab_menu_entries("server")], ["New terminal", "Rename", "Close"])
        self.assertEqual([e.key for e in hcgui.tab_menu_entries("space")], ["n", "e", "m", "d"])  # the sidebar's

    def test_menu_line_shortens_before_it_cuts(self):
        entries = hcgui.tab_menu_entries("space")

        def text(width):
            return " ".join(s.text for s in hcgui.tab_menu_segs("alpha", entries, width))

        self.assertEqual(text(80), "alpha: New terminal · Rename · Move to space · Close")
        self.assertEqual(text(46), "New terminal · Rename · Move to space · Close")
        self.assertEqual(text(30), "new · rename · move · close")
        self.assertEqual(text(20), "new · rename · move")  # no separator left hanging
        segs = hcgui.tab_menu_segs("alpha", entries, 80)
        self.assertEqual(hcgui.menu_entry_at(segs, segs[1].x), 0)
        self.assertEqual(hcgui.menu_entry_at(segs, segs[-1].end - 1), 3)
        self.assertIsNone(hcgui.menu_entry_at(segs, segs[2].x))  # a separator
        self.assertTrue(all(s.end <= 20 for s in hcgui.tab_menu_segs("alpha", entries, 20)))

    def test_tab_after_close(self):
        order = ["a", "b", "c", "d"]
        self.assertEqual(hcgui.tab_after_close(order, {"b"}, "b"), "c")
        self.assertEqual(hcgui.tab_after_close(order, {"b", "c"}, "b"), "d")
        self.assertEqual(hcgui.tab_after_close(order, {"d"}, "d"), "c")
        self.assertEqual(hcgui.tab_after_close(order, set(order), "a"), "")
        self.assertEqual(hcgui.tab_after_close(order, {"b"}, "a"), "a")  # the shown one stays

    def test_snapshot_lists_what_ends_and_every_name(self):
        tab = hcgui.tab_of(self.snap, "mini/t1")
        self.assertEqual(hcgui.tab_ends(tab), [("mini/t3", "gamma", "zsh")])
        self.assertEqual(tab["own"], "alpha")
        self.assertEqual(hcgui.snapshot_names(self.snap)["mini/t9"], "web")  # also outside this space
        self.assertEqual(hcgui.tab_ends({"ends": [["x", 1, "zsh"], "junk", ["y", "n", "zsh"]]}), [("y", "n", "zsh")])
        self.assertEqual(hcgui.snapshot_names({"names": ["junk"]}), {})
        self.assertIsNone(hcgui.tab_of(self.snap, "mini/t77"))

    # the menu --------------------------------------------------------------------------------------------------
    def test_right_click_opens_the_menu_below_the_tabs(self):
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("beta"), 0, button=3)
        self.assertEqual(self.bar.menu.address, "mini/t2")
        self.assertEqual(hcgui.current_target(self.win), "")  # a right click shows nothing
        lines = self.scr.lines()
        self.assertEqual(lines[1], " beta: New terminal · Split right · Rename · Move to space · Close")
        self.assertEqual(lines[4], " " + hcgui.TAB_MENU_HINT)
        beta = [attr for (y, x), (c, attr) in self.scr.cells.items() if y == 0 and x == self.tab_x("beta") + 3]
        self.assertTrue(beta[0] & hcgui.curses.A_UNDERLINE)  # the tab the menu belongs to
        self.press(self.tab_x("gamma"), 0, button=3)  # another tab's right click: its menu
        self.assertEqual(self.bar.menu.address, "mini/t3")
        self.key(27)
        self.assertIsNone(self.bar.menu)
        self.assertTrue(self.scr.line(4).startswith(" Claude Code"))  # the info row again, on the last row

    def test_a_left_click_outside_only_closes(self):
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("beta"), 0, button=3)
        self.press(self.tab_x("gamma"), 0)
        self.assertIsNone(self.bar.menu)
        self.assertEqual(hcgui.current_target(self.win), "")  # the click closed the menu, nothing else

    def test_keys_never_pick_an_entry_they_go_on_to_the_terminal(self):
        """Keys typed after a right click were meant for the terminal: "git status", "dyld", an arrow, enter."""
        self.bar.draw(self.snap, "mini/t1")
        gen = hcgui.read_text(self.win / "gen")
        with mock.patch.object(hcgui, "run_hc", self.hc):
            for key, typed in (("d", "d"), ("n", "n"), ("e", "e"), ("m", "m"), ("y", "y"), (10, "<Enter>"),
                               (hcgui.curses.KEY_RIGHT, "<Right>"), (27, "")):
                self.tm.calls.clear()
                self.press(self.tab_x("beta"), 0, button=3)
                self.key(key)
                self.assertIsNone(self.bar.menu, key)
                self.assertIsNone(self.bar.prompt, key)
                self.assertEqual(self.tm.typed(), typed, key)  # esc only closes
                self.assertEqual(self.tm.selected()[-1], "%0", key)  # the keyboard back to the view
                self.assertEqual(self.bar.notice.current(), "", key)
        self.assertFalse(any(c[0] in ("run", "kill", "label") for c in self.hc.calls))
        self.assertEqual(hcgui.read_names(self.state), {})
        self.assertEqual((hcgui.current_target(self.win), hcgui.read_text(self.win / "gen")), ("", gen))

    def test_keys_typed_ahead_go_with_it(self):
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("beta"), 0, button=3)
        self.scr.typed = [ord(c) for c in "it status"] + [10]
        self.key("g")
        self.assertEqual(self.tm.typed(), "git status<Enter>")
        self.assertEqual(self.scr.typed, [])

    def test_keys_go_on_byte_for_byte(self):
        """";", ctrl+C, esc sequences reach the terminal unchanged (review: a trailing ";" was eaten by tmux)."""
        args = hcgui.view_key_args([ord("l"), ord("s"), ord(";"), 10, 3, 27, ord("["), ord("1"), ord(";"), ord("5"),
                                    ord("D"), hcgui.curses.KEY_LEFT, hcgui.curses.KEY_F0 + 2, 0xC3, 0xA9], "%0")
        self.assertEqual(args, ["send-keys", "-t", "%0", "-H", "6c", "73", "3b", ";",
                                "send-keys", "-t", "%0", "Enter", ";",
                                "send-keys", "-t", "%0", "-H", "03", "1b", "5b", "31", "3b", "35", "44", ";",
                                "send-keys", "-t", "%0", "Left", ";", "send-keys", "-t", "%0", "F2", ";",
                                "send-keys", "-t", "%0", "-H", "c3", "a9", ";"])
        self.assertEqual(hcgui.view_key_args([hcgui.curses.KEY_F0 + 15], "%0"), ["send-keys", "-t", "%0", "S-F3", ";"])
        self.assertEqual(hcgui.view_key_args([99999], "%0"), [])  # no name: left out

    def test_keys_right_after_the_closing_key_go_on_too(self):
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("beta"), 0, button=3)
        with mock.patch.object(hcgui, "run_hc", self.hc):
            self.key("l")  # closes the menu, goes on
            self.key("n")  # arrived before tmux moved the keyboard: goes on too, no new terminal, no tab switch
        self.assertEqual(self.tm.typed(), "ln")
        self.assertFalse(any(c[0] == "run" for c in self.hc.calls))
        self.assertEqual(hcgui.current_target(self.win), "")
        self.bar.forward_until = 0.0
        self.key("l")  # later: the tab bar's own key again
        self.assertEqual(self.tm.typed(), "ln")

    def test_a_paste_that_cannot_be_passed_on_says_so_and_gives_the_view_the_keyboard(self):
        self.bar.draw(self.snap, "mini/t1")
        failing = FakeTmux()
        calls = []

        def tmux(*args, input=None):
            calls.append(args)
            return None if args[0] == "load-buffer" else ""

        with mock.patch.object(hcgui, "tmux", tmux):
            self.scr.typed = [ord(c) for c in "[200~" + "x" * 20000] + list(hcgui.PASTE_END)
            self.key(27)
        self.assertEqual(self.bar.notice.current(), "the paste could not be passed on to the terminal")
        self.assertEqual(calls[-1], ("select-pane", "-t", "%0"))
        del failing

    def test_a_double_click_on_an_entry_keeps_its_question(self):
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("beta"), 0, button=3)
        x = self.entry_x("rename")
        self.press(x, 1)
        self.press(x, 1)  # the double click's second press
        self.assertEqual(self.bar.prompt.kind, "rename")

    def test_a_double_clicks_second_press_after_the_menu_went_shows_no_hints(self):
        """tmux sends a double click's second press to the tab bar without taking the keyboard back: once the
        first press ran an entry, closed the menu or cancelled a question, that press must not show the key hints
        and the id (review finding). A later click does."""
        self.bar.draw(self.snap, "mini/t1")
        with mock.patch.object(hcgui, "run_hc", self.hc):
            self.press(self.tab_x("beta"), 0, button=3)
            x = self.entry_x("new")
            self.press(x, 1)  # New terminal: the menu goes, the keyboard to the view
            self.press(x, 1)  # the second press: no menu, nothing hit on that row
        self.assertIsNone(self.bar.menu)
        self.assertEqual(self.bar.hints_until, 0.0)
        self.bar.mouse_quiet = 0.0
        self.press(self.tab_x("beta"), 0, button=3)
        self.press(1, 1)  # on the menu's "beta:", off its entries: closes it
        self.press(1, 1)
        self.assertIsNone(self.bar.menu)
        self.assertEqual(self.bar.hints_until, 0.0)
        for cancel in ("rename", "close"):
            self.bar.mouse_quiet = 0.0
            self.press(self.tab_x("beta"), 0, button=3)
            self.press(self.entry_x(cancel), 1)
            self.bar.mouse_quiet = 0.0  # past the double click that opened the question
            self.press(60, 1)  # cancels it
            self.press(60, 1)
            self.assertIsNone(self.bar.prompt, cancel)
            self.assertEqual(self.bar.hints_until, 0.0, cancel)
        self.bar.mouse_quiet = 0.0  # later: a click shows them
        self.press(60, 1)
        self.assertGreater(self.bar.hints_until, time.monotonic())
        self.assertIn("· mini/t1", self.scr.line(self.scr.height - 1))  # the info row: the id after the line

    def test_the_tabs_keep_their_rows_while_close_asks(self):
        """Wrapped tabs must not take the rows the bar grew by for the question (review finding)."""
        many = [term(f"mini/t{n}", "/Users/x/dev/app", "zsh", f"tab-number-{n}") for n in range(40, 52)]
        self.hc.terms += many
        kids = [term(f"mini/t{n}", "/Users/x/dev/kids", "zsh", f"child-{n}") for n in range(20, 26)]
        self.hc.terms += kids
        for t in kids:
            self.hc.infos[t["address"]] = {"parent": "mini/t2", "dies": True, "labels": {"space": "kids"}}
        self.snap = self.snapshot()
        self.bar.draw(self.snap, "mini/t1")
        menu_row = next(s.y for s in self.bar.layout.segs if s.kind == "tab") if self.bar.layout else 0
        x = next(s.x for s in self.bar.layout.segs if s.kind == "tab" and "beta" in s.text)
        self.press(x + 1, menu_row, button=3)
        y = next(g.y for g in self.bar.menu_segs)
        self.press(next(g.x for g in self.bar.menu_segs if g.kind == "entry" and g.text.lower().startswith("close")), y)
        self.assertEqual(self.bar.prompt.kind, "close")
        self.scr.height = self.bar.rows_goal()
        self.bar.draw(self.snap, "mini/t1")
        self.assertFalse(self.bar.close_cut)  # the grown rows went to the question
        self.assertLessEqual(self.bar.layout.rows, hcgui.TAB_ROWS - 1)

    def test_a_right_click_in_the_view_opens_the_shown_terminals_menu_here(self):
        self.bar.draw(self.snap, "mini/t2")
        hcgui.write_atomic(self.win / "ask", "menu\n")  # what hcgui.tmux.conf writes
        self.bar.check_ask(self.snap, "mini/t2")
        self.assertEqual(self.bar.menu.address, "mini/t2")
        self.assertEqual(self.tm.selected(), ["%2"])  # the tab bar takes the keyboard, as for a tab's right click
        self.assertFalse((self.win / "ask").exists())
        self.bar.check_ask(self.snap, "mini/t2")  # read once
        self.assertEqual(self.tm.selected(), ["%2"])
        self.bar.menu = None
        hcgui.write_atomic(self.win / "ask", "menu\n")
        self.bar.check_ask(self.snap, "")  # nothing shown
        self.assertIsNone(self.bar.menu)
        self.assertEqual(self.bar.notice.current(), "nothing shown")

    def test_a_paste_goes_on_to_the_view_or_into_the_question(self):
        self.bar.draw(self.snap, "mini/t1")
        drop = [ord(c) for c in "[200~/Users/me/Desktop/shot one.png"] + list(hcgui.PASTE_END)
        self.scr.typed = list(drop)
        self.key(27)
        self.assertIn(["load-buffer", "-b", "hcgui-paste", "-"], self.tm.commands())
        self.assertEqual(self.tm.inputs, ["/Users/me/Desktop/shot one.png"])  # on stdin: no 16 KB limit
        self.assertIn(["paste-buffer", "-p", "-d", "-b", "hcgui-paste", "-t", "%0"], self.tm.commands())
        self.assertEqual(self.tm.selected()[-1], "%0")
        self.press(self.tab_x("beta"), 0, button=3)
        self.press(self.entry_x("rename"), 1)
        self.key(21)
        self.scr.typed = [ord(c) for c in "[200~web\nside"] + list(hcgui.PASTE_END)
        self.key(27)
        self.assertEqual(self.bar.prompt.text, "web side")  # one line, into the question
        self.scr.typed = [ord(c) for c in "[A"]  # esc of its own: the keys read to tell are given back
        self.assertIsNone(hcgui.read_paste(self.scr))
        self.assertEqual(self.scr.typed, [ord("["), ord("A")])

    def test_a_click_in_another_pane_closes_the_menu(self):
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("beta"), 0, button=3)
        with mock.patch.dict(os.environ, {"TMUX_PANE": "%2"}):
            self.bar.watch_menu()
            self.assertIsNotNone(self.bar.menu)  # still the tab bar's keyboard
            self.tm.active = False  # a click in the view
            self.bar.watch_menu()
        self.assertIsNone(self.bar.menu)

    def test_menu_on_a_one_row_pane_takes_the_row(self):
        self.scr.height = 1
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("beta"), 0, button=3)
        self.assertTrue(self.scr.line(0).startswith(" beta: New terminal"))

    # the actions -----------------------------------------------------------------------------------------------
    def test_rename_from_the_menu(self):
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("beta"), 0, button=3)
        self.press(self.entry_x("rename"), 1)
        self.assertEqual(self.bar.prompt.text, "beta")  # the current name filled in
        self.assertEqual(self.tm.selected(), ["%2"])  # the answer is typed here
        self.assertEqual(self.scr.line(1), " rename beta to: beta_")
        self.assertEqual(self.scr.line(4), " " + hcgui.TAB_ASK["rename"])
        self.key(21)
        for c in "web":
            self.key(c)
        self.key(10)
        self.assertEqual(self.bar.notice.current(), "rename: web is taken")  # t9 in another space shows it
        self.assertNotIn("term:mini/t2", hcgui.read_names(self.state))
        self.press(self.tab_x("beta"), 0, button=3)
        self.press(self.entry_x("rename"), 1)
        for c in "-two":
            self.key(c)
        self.key(10)
        self.assertEqual(hcgui.read_names(self.state), {"term:mini/t2": "beta-two"})
        self.assertEqual(self.tm.selected()[-1], "%0")  # the keyboard back to the view
        self.assertIsNone(self.bar.prompt)

    def test_rename_cancelled_by_esc_or_a_click(self):
        self.bar.draw(self.snap, "mini/t1")
        for cancel in (27, None):
            self.press(self.tab_x("beta"), 0, button=3)
            self.press(self.entry_x("rename"), 1)
            self.key("x")
            self.bar.mouse_quiet = 0.0  # past a double click's second press (that one keeps the question)
            if cancel is None:
                self.press(self.tab_x("gamma"), 0)
            else:
                self.key(cancel)
            self.assertIsNone(self.bar.prompt)
        self.assertEqual(hcgui.read_names(self.state), {})
        self.assertEqual(hcgui.current_target(self.win), "")

    def test_move_labels_and_asks_for_a_full_listing(self):
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("beta"), 0, button=3)
        self.press(self.entry_x("move"), 1)
        self.assertEqual(self.scr.line(1), " move beta to space: _")
        with mock.patch.object(hcgui, "run_hc", self.hc):
            for c in "web":
                self.key(c)
            self.key(10)
        self.assertIn(("label", "mini/t2", "space=web"), self.hc.calls)
        self.assertTrue((self.win / "poke.full").exists())  # the engine asks every label again

    def test_new_terminal_from_the_menu(self):
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("beta"), 0, button=3)
        with mock.patch.object(hcgui, "run_hc", self.hc):
            self.press(self.entry_x("new"), 1)
        run = next(c for c in self.hc.calls if c[0] == "run")
        self.assertEqual(run[-2:], ("--label", "space=app"))
        self.assertEqual(hcgui.current_target(self.win), "mini/t54")  # the new shell is shown
        self.assertIsNone(self.bar.menu)

    def test_close_asks_for_y_and_lists_what_ends(self):
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("alpha"), 0, button=3)
        self.press(self.entry_x("close"), 1)
        self.assertEqual(self.scr.line(1), " close alpha? ends 2: alpha (claude-code), gamma (zsh)")
        self.assertEqual(self.scr.line(4), " " + hcgui.TAB_ASK["close"])
        with mock.patch.object(hcgui, "run_hc", self.hc):
            self.key("n")  # any other key: nothing ends
        self.assertEqual(self.bar.notice.current(), "not closed")
        self.assertFalse(any(c[0] == "kill" for c in self.hc.calls))
        hcgui.show("mini/t1", self.win)
        hcgui.change_names({"term:mini/t3": "kid"}, self.state)
        self.press(self.tab_x("alpha"), 0, button=3)
        self.press(self.entry_x("close"), 1)
        with mock.patch.object(hcgui, "run_hc", self.hc):
            self.key("y")
        self.assertEqual([c[1] for c in self.hc.calls if c[0] == "kill"], ["mini/t1", "mini/t3"])
        self.assertEqual([t["address"] for t in self.hc.terms], ["mini/t2", "mini/t9"])
        self.assertEqual(hcgui.current_target(self.win), "mini/t2")  # the next tab that stays
        self.assertEqual(hcgui.read_names(self.state), {})  # the names of what ended went
        self.assertEqual(self.bar.notice.current(), "")
        self.assertIsNone(self.bar.prompt)

    def test_close_of_a_tab_not_shown_keeps_the_view(self):
        hcgui.show("mini/t1", self.win)
        gen = (self.win / "gen").read_text()
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("beta"), 0, button=3)
        self.press(self.entry_x("close"), 1)
        with mock.patch.object(hcgui, "run_hc", self.hc):
            self.key("Y")
        self.assertEqual((self.win / "gen").read_text(), gen)
        self.assertNotIn("mini/t2", [t["address"] for t in self.hc.terms])

    def test_close_asks_again_when_what_ends_has_changed(self):
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("beta"), 0, button=3)
        self.press(self.entry_x("close"), 1)
        self.assertEqual(self.bar.prompt.data, ("mini/t2",))
        self.hc.infos["mini/t9"] = {"parent": "mini/t2", "dies": True}  # t9 now ends with beta
        self.snap = self.snapshot()
        with mock.patch.object(hcgui, "run_hc", self.hc):
            self.key("y")
        self.assertFalse(any(c[0] == "kill" for c in self.hc.calls))
        self.assertEqual(self.bar.prompt.data, ("mini/t2", "mini/t9"))
        self.assertTrue(self.scr.line(1).startswith(" changed: close beta? ends 2:"))  # said where it is read
        with mock.patch.object(hcgui, "run_hc", self.hc):
            self.key("y")  # at once: not taken
        self.assertFalse(any(c[0] == "kill" for c in self.hc.calls))
        self.bar.asked_again -= hcgui.CLOSE_AGAIN
        with mock.patch.object(hcgui, "run_hc", self.hc):
            self.key("y")
        self.assertEqual([c[1] for c in self.hc.calls if c[0] == "kill"], ["mini/t2", "mini/t9"])

    def test_a_close_list_that_does_not_fit_refuses_y_and_the_bar_grows_for_it(self):
        many = [term(f"mini/t{n}", "/Users/x/dev/kids", "zsh", f"child-number-{n}") for n in range(20, 32)]
        self.hc.terms += many
        for t in many:  # in a space of their own: not tabs here
            self.hc.infos[t["address"]] = {"parent": "mini/t2", "dies": True, "labels": {"space": "kids"}}
        self.snap = self.snapshot()
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("beta"), 0, button=3)
        self.press(self.entry_x("close"), 1)
        self.assertTrue(self.bar.close_cut)  # 5 rows of 70 columns: the 13 names do not fit
        self.assertIn("the list is cut", self.scr.line(4))
        with mock.patch.object(hcgui, "run_hc", self.hc):
            self.key("y")
        self.assertFalse(any(c[0] == "kill" for c in self.hc.calls))
        self.assertIsNotNone(self.bar.prompt)  # still asking
        goal = self.bar.rows_goal()
        self.assertGreater(goal, hcgui.TAB_ROWS)  # in tmux the bar grows to show it all
        self.scr.height = goal
        self.bar.draw(self.snap, "mini/t1")
        self.assertFalse(self.bar.close_cut)
        self.assertEqual(self.scr.line(goal - 1), " " + hcgui.TAB_ASK["close"])
        with mock.patch.object(hcgui, "run_hc", self.hc):
            self.key("y")
        self.assertEqual(len([c for c in self.hc.calls if c[0] == "kill"]), 13)
        self.assertEqual(self.bar.rows_goal(), hcgui.TAB_ROWS)  # and back to its rows

    def test_a_failed_close_says_so(self):
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("beta"), 0, button=3)
        self.press(self.entry_x("close"), 1)
        self.hc.fail = '{"error": {"kind": "io", "message": "core gone"}}'
        with mock.patch.object(hcgui, "run_hc", self.hc):
            self.key("y")
        self.assertEqual(self.bar.notice.current(), "close: 1 of 1 failed, mini/t2: core gone")

    def test_a_tab_that_ended_meanwhile(self):
        self.bar.draw(self.snap, "mini/t1")
        self.press(self.tab_x("beta"), 0, button=3)
        x = self.entry_x("rename")
        self.snap = dict(self.snap, tabs=[t for t in self.snap["tabs"] if t["address"] != "mini/t2"])
        self.press(x, 1)
        self.assertIsNone(self.bar.prompt)
        self.assertEqual(self.bar.notice.current(), "that terminal has ended")


class PointerMenuTests(unittest.TestCase):
    """Owner, 26 Nov: the menu at the pointer ("Popup and the row", tabs and the view only); a key for it ("an extra
    button for right-click ... select the options on the top with <->"): a in the tab bar, Shift+F10 anywhere."""

    setUp = TabMenuTests.setUp
    snapshot = TabMenuTests.snapshot
    press = TabMenuTests.press
    key = TabMenuTests.key
    tab_x = TabMenuTests.tab_x

    def menus(self):
        return [c for c in self.tm.calls if c and c[0] == "display-menu"]

    def test_popup_args(self):
        menu = hcgui.TabMenu("rig/t2", "we#b", hcgui.tab_menu_entries("space", right=True))
        args = hcgui.menu_popup_args(menu, 40, 3, True)
        self.assertEqual(args[:9], ["display-menu", "-O", "-M", "-x", "40", "-y", "10", "-T", " we##b "])
        self.assertEqual(args[9:13], ["-s", "bg=themedarkgrey,fg=default", "-S", "bg=themedarkgrey,fg=colour244"])
        items = args[13:]
        self.assertEqual(items[0::3], ["New terminal", "Split right", "Rename", "Move to space", "Close"])
        self.assertEqual(set(items[1::3]), {""})  # no keys: typing never picks an entry
        self.assertEqual(items[2], "run-shell -b 'printf \"pick new rig/t2\\n\" >> \"$HCGUI_WINDOW/ask\"'")
        self.assertNotIn("-s", hcgui.menu_popup_args(menu, 40, 3, False))  # tmux without theme colours: its own look
        for bad in ("t1;rm", "t1'", 'a"b', "t 1", "$x"):  # an address that cannot go into the command: no popup
            self.assertIsNone(hcgui.menu_popup_args(hcgui.TabMenu(bad, "x", menu.entries), 0, 0, True))

    def test_parse_ask_lines(self):
        self.assertEqual(hcgui.parse_menu_ask(["menu 20 11"]), ("mouse", (20, 11)))
        self.assertEqual(hcgui.parse_menu_ask(["menu"]), ("mouse", None))
        self.assertEqual(hcgui.parse_menu_ask(["menu 3 4", "info x", "menu key"]), ("key", None))  # the last one
        self.assertIsNone(hcgui.parse_menu_ask(["info menu", "notice x"]))
        self.assertEqual(hcgui.parse_pick(["pick close mini/t2"]), ("close", "mini/t2"))
        self.assertIsNone(hcgui.parse_pick(["pick close", "menu"]))

    def test_a_right_click_on_a_tab_also_opens_the_popup_below_the_bar(self):
        self.bar.draw(self.snap, "mini/t1")
        with mock.patch.object(hcgui, "pane_box", return_value=(31, 0, 3)):
            self.press(self.tab_x("beta"), 0, button=3)
        self.assertEqual(self.bar.menu.address, "mini/t2")
        self.assertEqual(self.scr.lines()[1], " beta: New terminal · Split right · Rename · Move to space · Close")
        (menu,) = self.menus()
        self.assertEqual(menu[3:7], ("-x", str(31 + self.tab_x("beta")), "-y", str(3 + 7)))  # top: below the bar
        with mock.patch.object(hcgui, "pane_box", return_value=None):  # tmux cannot tell: the row only
            self.press(self.tab_x("gamma"), 0, button=3)
        self.assertEqual((self.bar.menu.address, len(self.menus())), ("mini/t3", 1))

    def test_a_right_click_in_the_view_opens_both_at_the_pointer(self):
        hcgui.write_atomic(self.win / "ask", "menu 50 20\n")
        self.bar.check_ask(self.snap, "mini/t1")
        self.assertEqual((self.bar.menu.address, self.bar.menu.selected), ("mini/t1", -1))  # clicks only
        (menu,) = self.menus()
        self.assertEqual(menu[3:7], ("-x", "50", "-y", str(21 + 7)))  # just below the pointer (alpha: 5 entries)
        self.assertIn(("select-pane", "-t", "%2"), self.tm.calls)  # the tab bar takes the keyboard

    def test_a_pick_in_the_popup_runs_that_entry(self):
        hcgui.write_atomic(self.win / "ask", "pick close mini/t2\n")
        self.bar.check_ask(self.snap, "mini/t1")
        self.assertEqual((self.bar.prompt.kind, self.bar.prompt.address), ("close", "mini/t2"))  # Close asks first
        self.bar.prompt = None
        hcgui.write_atomic(self.win / "ask", "pick rename mini/t2\n")
        self.bar.check_ask(self.snap, "mini/t1")
        self.assertEqual(self.bar.prompt.kind, "rename")
        self.bar.prompt = None
        hcgui.write_atomic(self.win / "ask", "pick close mini/t77\n")  # ended meanwhile
        self.bar.check_ask(self.snap, "mini/t1")
        self.assertIsNone(self.bar.prompt)
        self.assertEqual(self.bar.notice.current(), "that terminal has ended")
        hcgui.write_atomic(self.win / "ask", "pick right mini/t1\n")  # an entry it no longer has: nothing
        self.bar.check_ask(self.snap, "mini/t1")
        self.assertIsNone(self.bar.prompt)
        self.assertIsNone(self.bar.menu)

    def test_a_opens_the_shown_tabs_menu_picked_with_the_arrows(self):
        self.bar.draw(self.snap, "mini/t1")
        self.key("a")
        menu = self.bar.menu
        self.assertEqual((menu.address, menu.selected), ("mini/t1", 0))
        self.assertEqual(self.menus(), [])  # no pointer: no popup
        self.assertEqual(self.scr.lines()[4], " " + hcgui.TAB_MENU_KEYS_HINT)
        selected = [s for s in self.bar.menu_segs if s.kind == "entry" and s.index == 0][0]
        self.assertTrue(self.scr.cells[(selected.y, selected.x)][1] & hcgui.curses.A_REVERSE)
        self.key(hcgui.curses.KEY_LEFT)  # wraps round
        self.assertEqual(menu.entries[menu.selected].action, "close")
        self.key("l")
        self.key(hcgui.curses.KEY_RIGHT)
        self.assertEqual(menu.entries[menu.selected].action, "right")
        self.key(hcgui.curses.KEY_RIGHT)
        self.assertEqual(menu.entries[menu.selected].action, "rename")
        self.key(10)
        self.assertEqual(self.bar.prompt.kind, "rename")
        self.bar.prompt = None
        self.key("a")
        self.key("x")  # any other key: nothing, the menu stays (opened by a key, keys drive it)
        self.assertIsNotNone(self.bar.menu)
        self.key("d")  # an entry's letter, as in the sidebar
        self.assertEqual(self.bar.prompt.kind, "close")
        self.bar.prompt = None
        self.key("a")
        with mock.patch.object(hcgui, "focus_view") as view:
            self.key(27)
        self.assertIsNone(self.bar.menu)
        view.assert_called_once_with(self.win)
        self.key("a", shown="")  # nothing shown
        self.assertIsNone(self.bar.menu)

    def test_f12_is_the_tab_bars_menu_key_too(self):
        """Shift+F10 reaches the tab bar as F12 (hcgui.tmux.conf): it opens the shown tab's menu and closes it."""
        self.bar.draw(self.snap, "mini/t1")
        self.key(hcgui.MENU_FKEY)
        self.assertEqual(self.bar.menu.selected, 0)
        with mock.patch.object(hcgui, "focus_view"):
            self.key(hcgui.MENU_FKEY)
        self.assertIsNone(self.bar.menu)

    def test_split_right_twice_starts_one_shell(self):
        """python-pro review, 26 Nov: a second "Split right" before the engine lists the first shell made two."""
        tab = hcgui.tab_of(self.snap, "mini/t2")
        with mock.patch.object(hcgui, "new_right_shell", return_value="mini/t8") as new, \
                mock.patch.object(hcgui, "focus_view"), mock.patch.object(hcgui, "show"):
            self.bar.open_right(self.snap, "mini/t2", tab)
            self.bar.open_right(self.snap, "mini/t2", tab)  # the first not listed yet
            self.assertEqual(new.call_count, 1)
            self.assertEqual(self.bar.notice.current(), "a right pane is there or starting")
            self.bar.right_since -= hcgui.RIGHT_WAIT  # given up on: a new one may start
            self.bar.open_right(self.snap, "mini/t2", tab)
            self.assertEqual(new.call_count, 2)

    def test_shift_f10_in_the_view_asks_for_the_keyboard_menu(self):
        hcgui.write_atomic(self.win / "ask", "menu key\n")
        self.bar.check_ask(self.snap, "mini/t1")
        self.assertEqual(self.bar.menu.selected, 0)
        self.assertEqual(self.menus(), [])

    def test_the_tmux_bindings_and_the_lists_name_the_key(self):
        conf = (ROOT / "hcgui.tmux.conf").read_text()
        line = next(x for x in conf.splitlines() if x.startswith("bind -n S-F10 "))
        for part in ('printf "menu key\\n" >> "$HCGUI_WINDOW/ask"', 'printf "close\\n" >> "$HCGUI_WINDOW/right/ask"',
                     "send-keys F12", "send-keys S-F10", "#{window_zoomed_flag}"):
            self.assertIn(part, line)
        self.assertIn('printf "menu #{e|+:#{mouse_x},#{pane_left}} #{e|+:#{mouse_y},#{pane_top}}\\n"', conf)
        self.assertIn((hcgui.MENU_ANYWHERE, "menu anywhere"), hcgui.KEY_HELP)
        self.assertIn("⇧F10", hcgui.tab_keys())
        self.assertIn("a menu", hcgui.TAB_HINTS[0])


class PokeTests(unittest.TestCase):
    def test_a_full_poke_asks_for_every_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            win = Path(tmp)
            engine = hcgui.Engine(win / "shared", win)
            calls = []
            done = threading.Event()

            def refresh(full=False, also=()):
                calls.append(full)
                if len(calls) >= 3:
                    done.set()

            with mock.patch.object(engine, "refresh_once", refresh):
                thread = threading.Thread(target=engine.refresh_forever, daemon=True)
                thread.start()
                self.assertTrue(wait_for(lambda: len(calls) == 1))
                time.sleep(0.05)
                hcgui.poke_engine(win)
                self.assertTrue(wait_for(lambda: len(calls) == 2))
                time.sleep(0.05)
                hcgui.poke_engine(win, full=True)
                hcgui.poke_engine(win)  # a plain poke right after does not hide it
                self.assertTrue(done.wait(6))
                engine.stop()
                thread.join(3)
        self.assertEqual(calls[:3], [False, False, True])


class NamesTests(unittest.TestCase):
    """Display names: names.json, what a rename does, and where the names are drawn."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name)

    def test_valid_display_names(self):
        for good in ("Main", "Harry's rig", "a", "x" * 32, "Größe", "web-2 (old)"):
            self.assertTrue(hcgui.valid_display_name(good), good)
        for bad in ("", " Main", "Main ", "x" * 33, "a\nb", "a\tb", "a\x1b[31mb", "a\x00", " "):
            self.assertFalse(hcgui.valid_display_name(bad), repr(bad))

    def test_read_change_and_remove_keep_other_entries(self):
        self.assertEqual(hcgui.read_names(self.state), {})
        hcgui.change_names({"space:dev": "Main"}, self.state)
        hcgui.change_names({"rig:guest": "Harry"}, self.state)  # another window's rename stays
        self.assertEqual(hcgui.read_names(self.state), {"space:dev": "Main", "rig:guest": "Harry"})
        self.assertEqual(json.loads((self.state / "names.json").read_text()),
                         {"rig:guest": "Harry", "space:dev": "Main"})
        hcgui.change_names({"space:dev": ""}, self.state)  # "" removes
        self.assertEqual(hcgui.read_names(self.state), {"rig:guest": "Harry"})

    def test_junk_in_the_file_is_left_out(self):
        (self.state / "names.json").write_text(json.dumps({
            "space:dev": "Main", "rig:x": "a\nb", "term:t1": 7, "other:x": "y", "space:": "z", "rig:y": " pad"}))
        self.assertEqual(hcgui.read_names(self.state), {"space:dev": "Main"})
        (self.state / "names.json").write_text("not json")
        self.assertEqual(hcgui.read_names(self.state), {})

    def test_a_change_keeps_the_keys_of_kinds_it_does_not_know(self):
        """A window of an older version must not drop a later version's names when it saves one (review finding:
        the subscriptions' "account:" names went with a rename in a window started before the update). Junk of the
        kinds it knows still goes."""
        (self.state / "names.json").write_text(json.dumps({
            "space:dev": "Main", "rig:x": "a\nb", "later:thing": "Kept", "later:list": [1, 2]}))
        self.assertEqual(hcgui.change_names({"term:mini/t5": "web"}, self.state),
                         {"space:dev": "Main", "term:mini/t5": "web"})
        self.assertEqual(json.loads((self.state / "names.json").read_text()),
                         {"space:dev": "Main", "term:mini/t5": "web", "later:thing": "Kept", "later:list": [1, 2]})
        hcgui.change_names({hcgui.usage_key("work"): "Team"}, self.state)
        with mock.patch.object(hcgui, "NAME_KEY", re.compile(r"(?:space|rig|term):.+")):  # the kinds before 24 Nov
            hcgui.change_names({"term:mini/t5": ""}, self.state)  # so a later version's window keeps "account:work"
        self.assertEqual(hcgui.read_names(self.state), {"space:dev": "Main", "account:work": "Team"})
        (self.state / "names.json").write_text("[1, 2]")  # not an object: nothing to keep
        self.assertEqual(hcgui.change_names({"space:dev": "Main"}, self.state), {"space:dev": "Main"})
        self.assertEqual(json.loads((self.state / "names.json").read_text()), {"space:dev": "Main"})

    def test_a_subscriptions_name_is_kept_by_its_usage_files_name(self):
        # "account:<name>", <name> a usage file's name (USAGE_NAME), next to the other display names
        hcgui.change_names({"space:dev": "Main"}, self.state)
        hcgui.change_names({hcgui.usage_key("work"): "Team plan"}, self.state)
        self.assertEqual(hcgui.read_names(self.state), {"space:dev": "Main", "account:work": "Team plan"})
        hcgui.change_names({"account:work": ""}, self.state)  # "" removes it, the others stay
        self.assertEqual(hcgui.read_names(self.state), {"space:dev": "Main"})
        names = {"account:work": "Team plan"}
        self.assertEqual(hcgui.usage_shown("work", names), "Team plan")
        self.assertEqual(hcgui.usage_shown("solo", names), "solo")  # no display name: the file's name
        self.assertEqual(hcgui.usage_shown("work", {}), "work")

    def test_junk_subscription_names_are_left_out(self):
        (self.state / "names.json").write_text(json.dumps({
            "account:work": "Team", "account:": "x", "account:two words": "x", "account:caf\u00e9": "x",
            "account:" + "a" * 33: "x", "account:solo": 7, "account:spare": " pad", "account:side": "a\nb",
            "accounts:work": "x", "Account:work": "x"}))
        self.assertEqual(hcgui.read_names(self.state), {"account:work": "Team"})
        (self.state / "names.json").write_text(json.dumps(["account:work", "Team"]))
        self.assertEqual(hcgui.read_names(self.state), {})

    def test_a_name_another_subscription_shows_is_taken(self):
        drawn = ["work", "solo", "spare", "solo"]  # the usage files' names; a repeat counts once
        names = {"account:solo": "Side", "account:gone": "Old"}  # "gone": no line drawn now
        # what the others show, then their own names behind a display name (removing it brings them back)
        self.assertEqual(hcgui.usage_taken("work", drawn, names), ["Side", "spare", "solo"])
        self.assertEqual(hcgui.usage_taken("solo", drawn, names), ["work", "spare"])
        self.assertEqual(hcgui.usage_taken("work", [], names), [])
        p = hcgui.plan_rename
        self.assertEqual(p("SIDE", "work", hcgui.usage_taken("work", drawn, names)), ("bad", "SIDE is taken"))
        self.assertEqual(p("Spare", "work", hcgui.usage_taken("work", drawn, names)), ("bad", "Spare is taken"))
        self.assertEqual(p("solo", "work", hcgui.usage_taken("work", drawn, names)), ("bad", "solo is taken"))
        self.assertEqual(p("SOLO", "work", hcgui.usage_taken("work", drawn, names)), ("bad", "SOLO is taken"))
        self.assertEqual(p("Old", "work", hcgui.usage_taken("work", drawn, names)), ("set", "Old"))
        self.assertEqual(p("work", "work", hcgui.usage_taken("work", drawn, names)), ("remove", ""))  # its own
        self.assertEqual(p("Side", "solo", hcgui.usage_taken("solo", drawn, names)), ("set", "Side"))  # its own

    def test_removing_a_display_name_never_leaves_two_lines_one_name(self):
        # solo is renamed Side; work may not take "solo" meanwhile, or solo's own name, back once its display name
        # goes, would be drawn on two lines
        drawn, names = ["claude", "solo", "work"], {}
        for own, text in (("solo", "Side"), ("work", "solo"), ("solo", "")):
            what, value = hcgui.plan_rename(text, own, hcgui.usage_taken(own, drawn, names))
            if what != "bad":
                names = hcgui.renamed(names, hcgui.usage_key(own), value)
        self.assertEqual(names, {})
        shown = [hcgui.usage_shown(n, names) for n in drawn]
        self.assertEqual(len({s.casefold() for s in shown}), len(shown), shown)

    def test_plan_rename(self):
        p = hcgui.plan_rename
        self.assertEqual(p("Main", "dev", ["other", "rig"]), ("set", "Main"))
        self.assertEqual(p("  Main  ", "dev", []), ("set", "Main"))
        self.assertEqual(p("", "dev", []), ("remove", ""))  # an empty name removes the rename
        self.assertEqual(p("   ", "dev", []), ("remove", ""))
        self.assertEqual(p("dev", "dev", []), ("remove", ""))  # the own name too
        self.assertEqual(p("Other", "dev", ["other"]), ("bad", "Other is taken"))  # refused, ignoring case
        self.assertEqual(p("x" * 33, "dev", [])[0], "bad")
        self.assertEqual(p("a\x1bb", "dev", [])[0], "bad")

    def test_names_change_what_is_drawn_and_the_order_only(self):
        terms = hcgui.parse(SAMPLE)
        names = {"space:atlas": "Zeta", "rig:rig": "Harry", "term:mini/t5": "web", "rig:this Mac": "Laptop"}
        spaces, rigs = hcgui.build_groups(terms, "mini", names=names)
        rigs = [g for g in rigs if not g.home]  # the home machine's row: ServerTests
        self.assertEqual([(g.key, g.name, g.shown) for g in spaces],
                         [("space:home", "home", "home"), ("space:appshop", "appshop", "appshop"),
                          ("space:atlas", "atlas", "Zeta")])  # sorted by what is shown, "home" first
        self.assertEqual([(g.key, g.shown) for g in rigs], [("rig:rig", "Harry"), ("rig:this Mac", "Laptop")])
        atlas = spaces[2]
        self.assertEqual(atlas.cwd, "/Users/x/dev/atlas")  # the folder rules use the space's own name
        self.assertEqual([(t.label, t.shown) for t in atlas.terms], [("atlas", "web"), ("zz", "zz")])
        self.assertEqual(hcgui.make_snapshot(atlas, 1.0)["name"], "atlas")  # a new shell's label: the own name
        self.assertEqual(hcgui.make_snapshot(atlas, 1.0)["title"], "Zeta")
        self.assertEqual(hcgui.make_snapshot(atlas, 1.0)["tabs"][0]["label"], "web")


class MenuTests(unittest.TestCase):
    """The action menu: entries per row, its box at 30 columns and at small heights, clicks."""

    def setUp(self):
        self.space = hcgui.Group("space:dev", "dev", "space", "mini", "")
        self.rig = hcgui.Group("rig:vps", "vps", "rig", "vps", "")
        self.local = hcgui.Group("rig:this Mac", hcgui.LOCAL, "rig", hcgui.LOCAL, "")
        self.home = hcgui.Group("rig:mini", "mini", "rig", "mini", "")  # the home machine without terminals

    def actions(self, item, group):
        """The row's own entries (menu_actions), without the section switches (test_switches_...)."""
        return [e.action for e in hcgui.menu_actions(item, group, "mini")]

    def test_entries_per_row(self):
        g = hcgui.Item("group", "", "")
        self.assertEqual(self.actions(g, self.space), ["open", "new", "rename", "delete"])
        self.assertEqual(self.actions(g, self.rig), ["open", "new", "rename", "forget"])
        self.assertEqual(self.actions(g, self.local), ["open", "new", "rename"])  # never removed
        self.assertEqual(self.actions(g, self.home), ["open", "new", "rename"])
        home = hcgui.Group("rig:box", "box", "rig", "box", "", home=True)  # a home machine of another name
        self.assertEqual(self.actions(g, home), ["open", "new", "rename"])
        self.assertEqual(self.actions(hcgui.Item("agent", "space:dev", "t1"), self.space),
                         ["open", "rename", "move", "end"])
        self.assertEqual(self.actions(hcgui.Item("agent", "rig:vps", "vps/t1"), self.rig),
                         ["open", "rename", "end"])  # servers have no spaces to move to
        self.assertEqual(self.actions(hcgui.NEW_SPACE, None), ["new_space"])
        self.assertEqual(self.actions(hcgui.ADD_RIG, None), ["add_rig"])
        self.assertEqual(self.actions(hcgui.Item("needs", "", "t3"), None), ["open"])
        self.assertEqual(self.actions(hcgui.Item("dev", "", "3917"), None), ["browse"])

    def test_switches_hide_only_their_own_section_and_show_every_hidden_one(self):
        """Owner, 26 Nov: "be more specific": a row's menu hides only its own section; a hidden section's "Show"
        is in every menu (no row of it is left to right-click)."""
        g = hcgui.Item("group", "", "")
        rows = {"servers": ((g, self.rig), (g, self.local), (hcgui.ADD_RIG, None)),
                "agents": ((hcgui.Item("agent", "space:dev", "t1"), self.space),),
                "devs": ((hcgui.Item("dev", "", "3917"), None),),
                "": ((g, self.space), (hcgui.NEW_SPACE, None), (hcgui.Item("needs", "", "t3"), None))}
        hide = {"servers": "Hide servers", "agents": "Hide agents", "devs": "Hide dev servers"}
        for section, pairs in rows.items():
            for item, group in pairs:
                self.assertEqual(hcgui.menu_section(item, group), section)
                own = hcgui.menu_actions(item, group, "mini")
                labels = [e.label for e in hcgui.menu_entries(item, group, "mini", True, True, True)[len(own):]]
                self.assertEqual(labels, [hide[section]] if section else [])  # everything shown
                hidden = hcgui.menu_entries(item, group, "mini", False, False, False, False)
                labels = [e.label for e in hidden[len(own):]]
                self.assertEqual(labels, ["Show servers", "Show agents", "Show dev servers", "Show usage"])
        self.assertEqual([e.label for e in hcgui.menu_entries(g, self.rig, "mini", servers=True, devs=False)],
                         ["Open", "New terminal here", "Rename", "Forget server", "Hide servers", "Show dev servers"])
        self.assertEqual(hcgui.menu_entries(hcgui.ADD_RIG, None, "mini", servers=True)[-1],
                         hcgui.Entry("servers", "Hide servers", "v"))

    def test_the_usage_lines_menu_and_show_usage_once_hidden(self):
        rows = ((hcgui.Item("group", "", ""), self.space), (hcgui.Item("group", "", ""), self.rig),
                (hcgui.Item("agent", "space:dev", "t1"), self.space), (hcgui.NEW_SPACE, None), (hcgui.ADD_RIG, None),
                (hcgui.Item("needs", "", "t3"), None), (hcgui.Item("dev", "", "3917"), None))
        for item, group in rows:
            shown = hcgui.menu_entries(item, group, "mini")
            self.assertEqual(hcgui.menu_entries(item, group, "mini", usage=True), shown)  # the default: shown
            self.assertNotIn("usage", [e.action for e in shown])  # no usage entry while they are shown
            hidden = hcgui.menu_entries(item, group, "mini", usage=False)
            self.assertEqual(hidden, shown + [hcgui.Entry("usage", "Show usage", "u")])  # last, like a switch
        # a line's own menu (a right click on a usage line): Rename, Refresh, Hide usage only (owner, 26 Nov:
        # "subscriptions do not need 'hide servers' and all that"); Rename has no direct key (no cursor there)
        for name, usage in itertools.product(("work", "solo"), (True, False)):
            entries = hcgui.menu_entries(hcgui.usage_item(name), None, "mini", True, False, True, usage)
            self.assertEqual(entries, [hcgui.Entry("rename", "Rename", ""), hcgui.Entry("refresh", "Refresh", "r"),
                                       hcgui.Entry("usage", "Hide usage", "u")])

    def test_every_entry_names_its_direct_key(self):
        keys = {}
        for item, group in ((hcgui.Item("group", "", ""), self.space), (hcgui.Item("group", "", ""), self.rig),
                            (hcgui.Item("agent", "space:dev", "t1"), self.space), (hcgui.Item("dev", "", "1"), None)):
            for e in hcgui.menu_entries(item, group, "mini"):
                keys[e.action] = e.key
        self.assertEqual(keys, {"open": "↵", "new": "n", "rename": "e", "delete": "d", "forget": "d", "move": "m",
                                "end": "d", "servers": "v", "agents": "g", "devs": "w", "browse": "↵"})
        labels = [e.label for e in hcgui.menu_entries(hcgui.Item("group", "", ""), self.space, "mini")]
        self.assertEqual(labels, ["Open", "New terminal here", "Rename", "Delete space", "Show servers"])

    def test_box_at_30_columns_fits_and_reads(self):
        entries = hcgui.menu_entries(hcgui.Item("group", "", ""), self.space, "mini", False, False, False)
        for ascii_only in (False, True):
            with mock.patch.object(hcgui, "utf8_screen", return_value=not ascii_only):
                want = hcgui.menu_width(entries)
                self.assertLessEqual(want, 29, ascii_only)
                box = hcgui.menu_box(1, len(entries), 0, 24, 30, want)
                self.assertEqual((box.top, box.left, box.width, box.bordered, box.offset, box.shown),
                                 (2, min(2, 29 - want), want, True, 0, 7))  # just below the row, two columns in
                self.assertLessEqual(box.left + box.width, 29)  # the last column stays empty
                lines = hcgui.menu_lines("dev", entries, box, 2)
                self.assertEqual([y for y, _, _ in lines], list(range(2, 11)))
                self.assertTrue(all(len(hcgui.glyph(t)) == want for _, t, _ in lines), lines)
                self.assertEqual([s for _, _, s in lines], [False, False, False, True] + [False] * 5)
                texts = [hcgui.glyph(t) for _, t, _ in lines]
                self.assertIn("dev", texts[0])
                self.assertTrue(texts[1].startswith(hcgui.glyph("│ Open")))
                self.assertTrue(texts[1].rstrip(hcgui.glyph("│")).rstrip().endswith(hcgui.glyph("↵")))
                self.assertRegex(texts[2], r"New terminal here +n ")
                self.assertRegex(texts[5], r"Show servers +v ")
                self.assertRegex(texts[6], r"Show agents +g ")
                self.assertRegex(texts[7], r"Show dev servers +w ")

    def test_box_goes_above_the_row_when_below_has_no_room(self):
        box = hcgui.menu_box(20, 4, 0, 24, 30, 24)
        self.assertEqual((box.top, box.height), (14, 6))  # lines 14-19, the row on 20 stays visible
        box = hcgui.menu_box(3, 4, 0, 8, 30, 24)  # neither below nor above: as low as the screen allows
        self.assertEqual((box.top, box.height), (2, 6))

    def test_small_heights_drop_the_border_and_scroll(self):
        for height in range(1, 13):
            for row in range(height):
                for selected in range(4):
                    box = hcgui.menu_box(row, 4, selected, height, 30, 24)
                    case = (height, row, selected, box)
                    self.assertGreaterEqual(box.top, 0, case)
                    self.assertLessEqual(box.top + box.height, height, case)
                    self.assertEqual(box.bordered, height >= 6, case)
                    self.assertTrue(box.offset <= selected < box.offset + box.shown, case)  # the selection shows
        self.assertIsNone(hcgui.menu_box(0, 4, 0, 0, 30, 24))
        narrow = hcgui.menu_box(0, 4, 0, 24, 12, 24)  # a narrow pane: as wide as it can, from column 0
        self.assertEqual((narrow.left, narrow.width), (0, 11))
        lines = hcgui.menu_lines("dev", hcgui.menu_entries(hcgui.Item("group", "", ""), self.space), narrow, 0)
        self.assertTrue(all(hcgui.text_width(t) == 11 for _, t, _ in lines), lines)

    def test_menu_hit(self):
        box = hcgui.menu_box(1, 4, 0, 24, 30, 24)  # lines 2-7, columns 2-25
        self.assertEqual(hcgui.menu_hit(box, 5, 3), ("entry", 0))
        self.assertEqual(hcgui.menu_hit(box, 25, 6), ("entry", 3))
        self.assertEqual(hcgui.menu_hit(box, 5, 2), ("box", -1))  # the border
        self.assertEqual(hcgui.menu_hit(box, 5, 7), ("box", -1))
        for x, y in ((1, 3), (26, 3), (5, 1), (5, 8)):
            self.assertEqual(hcgui.menu_hit(box, x, y), ("outside", -1), (x, y))
        flat = hcgui.menu_box(0, 4, 3, 3, 30, 24)  # no border, scrolled to the last entry
        self.assertEqual((flat.offset, flat.shown, flat.bordered), (1, 3, False))
        self.assertEqual(hcgui.menu_hit(flat, 5, flat.top), ("entry", 1))


class AddRigTests(unittest.TestCase):
    """What may be typed at "+ add server", and the exact command built from it."""

    GOOD = ("me@host", "host", "me@10.0.0.7:2222", "my-vps.example.com", "vps_2", "a.b@c-d.e:22", "_x")
    BAD = ("", "x;rm -rf ~", "me@host; rm -rf ~", "a b", "host\n", "\nhost", "hоst", "mе@host",
           "-oProxyCommand=x", "me@-oProxyCommand=x", "a@b@c", "@host", "host:", "host:123456", "$(id)", "`id`",
           "host|cat", "a/b", "~/x", "x" * 256, "host\x00", "ｈost")

    def test_targets(self):
        for target in self.GOOD:
            self.assertTrue(hcgui.valid_rig_target(target), target)
        for target in self.BAD:
            self.assertFalse(hcgui.valid_rig_target(target), repr(target))

    def test_names(self):
        for name in ("harry", "rig-2", "a_b", "a" * 32):
            self.assertTrue(hcgui.valid_rig_name(name), name)
        for name in ("", "Harry", "2rig", "-x", "_x", "a" * 33, "a b", "a\n", "x;y", "ｈakan"):
            self.assertFalse(hcgui.valid_rig_name(name), repr(name))

    def test_args_are_separate_items_after_a_fixed_script(self):
        args = hcgui.add_rig_args("/Users/me/.local/bin/hc", "me@host:2222", "harry", "/Users/me")
        self.assertEqual(args, ["run", "--bg", "--json", "--no-parent", "--rm", "--name", "add-server", "--cwd",
                                "/Users/me", "/bin/sh", "-c", hcgui.ADD_RIG_SCRIPT, "add-server",
                                "/Users/me/.local/bin/hc", "me@host:2222", "harry"])
        self.assertNotIn("--on", args)  # this Mac's own core: the questions come up where they can be answered
        self.assertEqual(hcgui.add_rig_args("hc", "vps", "", "/Users/me")[-2:], ["hc", "vps"])  # no name: the host
        self.assertNotIn("--cwd", hcgui.add_rig_args("hc", "vps", "", ""))
        for target in self.BAD:
            with self.assertRaises(ValueError, msg=repr(target)):
                hcgui.add_rig_args("hc", target, "", "/Users/me")
        for name in ("Harry", "x;y", "a b"):
            with self.assertRaises(ValueError, msg=name):
                hcgui.add_rig_args("hc", "vps", name, "/Users/me")

    def test_the_script_passes_what_was_typed_as_arguments_only(self):
        """The fixed script run as the new terminal would run it, with a stand-in hc that prints its arguments:
        the target and name arrive whole, after "--", and nothing in them is run."""
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "hc"
            stub.write_text('#!/bin/sh\nfor a in "$@"; do printf "[%s]" "$a"; done; echo\nexit 3\n')
            stub.chmod(0o755)
            for name, expect in (("harry", "[machine][add][--name][harry][--][me@host]"),
                                 ("", "[machine][add][--][me@host]")):
                argv = hcgui.add_rig_args(str(stub), "me@host", name, tmp)[9:]
                out = subprocess.run(argv, input="\n", capture_output=True, text=True, timeout=10)
                self.assertEqual(out.stdout.splitlines()[0], expect)
                self.assertIn("add server: hc ended with exit 3.", out.stdout)
                self.assertIn("This terminal can be closed: press enter.", out.stdout)
            # not reachable through the checks, but even so the script would run nothing of it
            marker = Path(tmp) / "ran"
            out = subprocess.run(["/bin/sh", "-c", hcgui.ADD_RIG_SCRIPT, "add-server", str(stub), f"x; touch {marker}",
                                  f"$(touch {marker})"], input="\n", capture_output=True, text=True, timeout=10)
            self.assertIn(f"[--name][$(touch {marker})][--][x; touch {marker}]", out.stdout)
            self.assertFalse(marker.exists())


class EndTests(unittest.TestCase):
    """Ending terminals and forgetting rigs: the hc calls, in their order."""

    def test_end_steps_and_forget_args(self):
        self.assertEqual(hcgui.end_steps("mini/t5"), [("keep", "mini/t5", "--off"), ("kill", "mini/t5"),
                                                       ("wait", "mini/t5", "--timeout", "15"), ("rm", "mini/t5")])
        self.assertEqual(hcgui.forget_args("vps"), ("machine", "rm", "vps"))

    def test_end_terminal_on_live_finished_and_gone_terminals(self):
        hc = FakeHc([term("t1"), term("t2")])
        hcgui.end_terminal("t1", runner=hc)
        self.assertEqual(hc.calls, [("keep", "t1", "--off"), ("kill", "t1"), ("wait", "t1", "--timeout", "15"),
                                    ("rm", "t1")])
        self.assertEqual(([t["address"] for t in hc.terms], hc.finished), (["t2"], {}))
        hc.end("t2")  # finished already (it ended with its parent): keep refuses, the rest goes on
        hc.calls = []
        hcgui.end_terminal("t2", runner=hc)
        self.assertEqual([c[0] for c in hc.calls], ["keep", "kill", "wait", "rm"])
        self.assertEqual(hc.finished, {})
        hc.calls = []
        hcgui.end_terminal("t9", runner=hc)  # gone: nothing more to do
        self.assertEqual(hc.calls, [("keep", "t9", "--off")])

    def test_other_errors_reach_the_caller(self):
        def fail(*args, **kw):
            raise hc_error("unreachable", "cannot reach vps")

        with self.assertRaises(subprocess.CalledProcessError):
            hcgui.end_terminal("vps/t1", runner=fail)
        self.assertEqual(hcgui.error_kind(hc_error("live")), "live")
        self.assertEqual(hcgui.error_kind(subprocess.CalledProcessError(1, "hc", stderr="junk")), "")
        self.assertEqual(hcgui.error_kind(ValueError()), "")

    def test_ending_lists_the_children_that_end_too(self):
        terms = hcgui.parse(ls(term("t1", name="web"), term("t2", name="kid"), term("t3", name="grandkid"),
                               term("t4", name="free"), term("t5", name="other")))
        infos = {"t2": hcgui.Info("", "t1"), "t3": hcgui.Info("", "t2"), "t4": hcgui.Info("", "t1", False)}
        ends = hcgui.ending([terms[0]], terms, infos)
        self.assertEqual([t.label for t in ends], ["web", "kid", "grandkid"])  # not the one with --outlive-parent
        self.assertEqual(hcgui.ends_text(ends), "ends 3: web (zsh), kid (zsh), grandkid (zsh)")

    def test_confirm_matches(self):
        self.assertTrue(hcgui.confirm_matches("dev", ("dev",)))
        self.assertTrue(hcgui.confirm_matches(" dev ", ("Main", "dev")))
        for typed in ("", "de", "Dev", "dev2", "devx"):
            self.assertFalse(hcgui.confirm_matches(typed, ("dev",)), typed)

    def test_neighbour(self):
        g = lambda k: hcgui.Item("group", k, "")  # noqa: E731
        a = lambda k, t: hcgui.Item("agent", k, t)  # noqa: E731
        sa, sb, sc, rr, rs = g("space:a"), g("space:b"), g("space:c"), g("rig:r"), g("rig:s")
        before = [sa, sb, sc, hcgui.NEW_SPACE, rr, rs, hcgui.ADD_RIG, a("space:a", "t1"), a("space:b", "t2"),
                  a("space:b", "t3"), a("space:b", "t4")]
        without = lambda *gone: [i for i in before if i not in gone]  # noqa: E731
        b_agents = [a("space:b", t) for t in ("t2", "t3", "t4")]
        self.assertEqual(hcgui.neighbour(before, 1, without(sb, *b_agents)), sc)  # the next group
        self.assertEqual(hcgui.neighbour(before, 2, without(sc)), sb)  # the last space: the space before, no rig
        self.assertEqual(hcgui.neighbour(before, 4, without(rr)), rs)  # a rig: the next rig
        self.assertEqual(hcgui.neighbour(before, 5, without(rs)), rr)
        self.assertEqual(hcgui.neighbour(before, 4, without(rr, rs)), sc)  # no rig left: any group
        self.assertEqual(hcgui.neighbour(before, 9, without(b_agents[1])), b_agents[2])  # the next agent of its group
        self.assertEqual(hcgui.neighbour(before, 10, without(b_agents[2])), b_agents[1])  # the last: the one before
        self.assertEqual(hcgui.neighbour(before, 7, without(a("space:a", "t1"))), sa)  # alone: its group
        self.assertEqual(hcgui.neighbour(before, 7, without(sa, a("space:a", "t1"))), sb)  # group gone: next space
        self.assertIsNone(hcgui.neighbour(before, 0, [hcgui.NEW_SPACE, hcgui.ADD_RIG]))
        self.assertIsNone(hcgui.neighbour(before, 99, before))


class PromptLayoutTests(unittest.TestCase):
    def test_wrap_and_keep_what_to_type(self):
        title = "delete space dev? ends 3: tracker (claude-code), atlas (claude-code), t1f (zsh)."
        ask = "type dev to confirm:"
        full = hcgui.prompt_lines(title, ask, 29, 8)
        self.assertEqual(full, ["delete space dev? ends 3:", "tracker (claude-code), atlas",
                                "(claude-code), t1f (zsh).", "type dev to confirm:"])
        cut = hcgui.prompt_lines(title, ask, 29, 2)
        self.assertEqual(cut, [hcgui.clip("delete space dev? ends 3: …", 29), ask])  # the cut is marked
        self.assertEqual(hcgui.prompt_lines(title, ask, 29, 1), [ask])
        self.assertEqual(hcgui.prompt_lines(title, ask, 29, 0), [])
        self.assertTrue(all(len(line) <= 10 for line in hcgui.prompt_lines(title, ask, 10, 20)))

    def test_one_key_question_whole_or_cut(self):
        title = "delete space dev? ends 3: tracker (claude-code), atlas (claude-code), t1f (zsh)."
        ask = hcgui.DELETE_ASK["space"]
        self.assertEqual(hcgui.yes_height(title, ask, 29), 5)  # 3 lines of what ends, 2 of keys
        whole, cut = hcgui.yes_lines(title, ask, 29, 5)
        self.assertEqual((whole, cut), (["delete space dev? ends 3:", "tracker (claude-code), atlas",
                                         "(claude-code), t1f (zsh).", "y deletes · any other key", "cancels"], False))
        self.assertEqual(hcgui.yes_lines(title, ask, 29, 9), (whole, False))  # more room: the same lines
        lines, cut = hcgui.yes_lines(title, ask, 29, 5)
        self.assertEqual((lines, cut), (whole, False))  # just enough room
        lines, cut = hcgui.yes_lines(title, ask, 29, 4)
        self.assertTrue(cut)  # one line short: cut, marked, and the keys say so
        self.assertEqual(lines, [hcgui.clip("delete space dev? ends 3: …", 29), "the list is cut: widen the",
                                 "sidebar · any other key", "cancels"])
        self.assertEqual(hcgui.yes_lines(title, ask, 29, 0), ([], True))  # no room at all: nothing on screen, cut

    def test_one_key_answers(self):
        self.assertTrue(hcgui.is_yes(ord("y")) and hcgui.is_yes(ord("Y")))
        for key in ("n", "d", "\n", " "):
            self.assertFalse(hcgui.is_yes(ord(key)), key)
        self.assertFalse(hcgui.is_yes(hcgui.curses.KEY_MOUSE))
        self.assertTrue(hcgui.yes_waits(True, float("-inf"), 100.0))  # cut: never
        self.assertTrue(hcgui.yes_waits(False, 99.5, 100.0))  # asked again half a second ago
        self.assertFalse(hcgui.yes_waits(False, 100.0 - hcgui.CLOSE_AGAIN, 100.0))
        self.assertFalse(hcgui.yes_waits(False, float("-inf"), 0.2))  # a clock that starts near 0
        self.assertTrue(hcgui.yes_waits(False, 99.6, 100.0, hcgui.DELETE_HOLD))  # d asked a moment ago
        self.assertFalse(hcgui.yes_waits(False, 100.0 - hcgui.DELETE_HOLD, 100.0, hcgui.DELETE_HOLD))
        self.assertLess(hcgui.DELETE_HOLD, hcgui.CLOSE_AGAIN)
        # a cut list does not take y: its hint says any *other* key cancels (review of 24 Nov)
        for cut in (hcgui.DELETE_CUT, hcgui.CLOSE_CUT):
            self.assertTrue(cut.startswith("the list is cut: ") and cut.endswith(" · any other key cancels"), cut)
        asked = hcgui.Prompt("delete", "end a? ends 1: a (zsh).", data=("t1", "t1"), by_mouse=True)
        same = hcgui.Prompt("delete", "end b? ends 1: b (zsh).", data=("t1", "t1"))  # renamed only
        self.assertIsNone(hcgui.changed_question(asked, same))
        more = hcgui.Prompt("delete", "end a? ends 2: a (zsh), k (zsh).", data=("t1", "t1", "t3"))
        again = hcgui.changed_question(asked, more)
        self.assertEqual((again.title, again.data, again.by_mouse),
                         ("changed: end a? ends 2: a (zsh), k (zsh).", ("t1", "t1", "t3"), True))
        self.assertEqual(more.title, "end a? ends 2: a (zsh), k (zsh).")  # a copy: the new question stays as built

    def test_frame_gives_the_question_its_lines_and_the_list_two(self):
        f = hcgui.sidebar_frame
        self.assertEqual(f(24, False, True, False, 4), (18, 23, -1, 5))
        self.assertEqual(f(24, False, True, False, 20), (2, 23, -1, 21))  # the list keeps two lines
        self.assertEqual(f(24, False, True), f(24, False, True, False, 1))  # one line: as before
        for height in range(0, 30):
            for lines in range(1, 9):
                body, arrow_y, open_y, extra = f(height, False, True, False, lines)
                self.assertEqual(body + extra + (arrow_y >= 0), height, (height, lines))
                if height >= 1:
                    self.assertGreaterEqual(body, 1, (height, lines))


class ActionTests(unittest.TestCase):
    """Menu, rename, create and delete in the Sidebar, against a fake screen and a fake hc."""

    TERMS = [term("t1", "/Users/x/dev", "claude-code", "tracker", "idle"),
             term("t2", "/Users/x/dev", "claude-code", "atlas", "working"),
             term("t3", "/Users/x/dev", "zsh", "t1f"),
             term("t4", "/Users/x/dev/other", "claude-code", "o1", "done"),
             term("vps/t1", "/home/v", "claude-code", "v1", "idle"),
             term("t9", "/Users/x", "zsh")]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"
        # the home machine is this Mac here (no terminal on "mini"): "mini" is in hc's machine list, without terminals
        self.hc = FakeHc(self.TERMS, machines=["vps", "mini", "spare"])
        for target, value in ((hcgui, {"run_hc": self.hc}), (hcgui.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        hcgui.write_servers_shown(True, self.state)  # these tests act on servers: the section is shown
        self.scr = FakeScr(30, 30)
        seen_done(self.state, self.hc.terms)
        self.side = hcgui.Sidebar(self.scr, self.state, self.win)
        self.side.refresh_once()
        self.side.sync()
        self.side.draw()

    def key(self, *keys):
        for k in keys:
            self.side.on_key(ord(k) if isinstance(k, str) else k)
            self.side.sync()
            self.side.draw()

    def type(self, text):
        self.key(*text)
        self.key(10)

    def go(self, item):
        self.side.cursor = item
        self.side.draw()

    def line_of(self, item):
        return next(y for y, i in self.side.rows.items() if i == item)

    def click(self, x, y, button=1):
        self.side.mouse_quiet = 0.0
        with pressed(x, y, button):
            self.key(hcgui.curses.KEY_MOUSE)

    def ends(self):
        return [c for c in self.hc.calls if c[0] in ("keep", "kill", "wait", "rm")]

    def held(self):
        """As if d's question had been on screen long enough for y: DELETE_HOLD after d asked, CLOSE_AGAIN after it
        asked again (yes_waits). These tests press keys far faster than anyone types."""
        self.side.asked_at -= self.side.yes_hold

    # rows ------------------------------------------------------------------------------------------------------
    def test_servers_from_hc_machine_ls_show_without_terminals(self):
        spaces, rigs = self.side.groups()
        self.assertEqual([g.key for g in spaces], ["space:home", "space:dev", "space:other"])
        self.assertEqual([(g.key, len(g.terms)) for g in rigs],  # this Mac is home: its row first, all its terminals
                         [("rig:this Mac", 5), ("rig:mini", 0), ("rig:spare", 0), ("rig:vps", 1)])
        self.go(hcgui.Item("group", "rig:spare", ""))
        self.key(10)
        self.assertEqual(self.side.notice.current(), "no terminals on spare: n starts one")
        self.key("n")
        self.assertEqual([c for c in self.hc.calls if c[0] == "run"][-1][:6],
                         ("run", "--bg", "--json", "--no-parent", "--on", "spare"))
        self.hc.terms = [t for t in self.hc.terms if not t["address"].startswith("spare/")]  # n's shell ended
        self.hc.machines = ["vps"]  # forgotten elsewhere: the empty server goes
        self.side.refresh_once()
        self.assertEqual([g.key for g in self.side.groups()[1]], ["rig:this Mac", "rig:vps"])
        real = self.hc.__call__

        def no_machine_list(*args, **kw):
            if args[0] == "machine":
                raise hc_error("unknown", "no such command")
            return real(*args, **kw)

        with mock.patch.object(hcgui, "run_hc", no_machine_list):
            self.side.refresh_once()
        self.assertEqual([g.key for g in self.side.groups()[1]], ["rig:this Mac", "rig:vps"])  # the last list stays
        self.assertEqual(self.side.error, "")  # without a red line: the terminals are what matters

    def test_plus_rows_are_rows_the_cursor_reaches_and_clicks_hit(self):
        lines = self.scr.lines()
        self.assertEqual(lines[4], " + new space")
        self.assertEqual(lines[5:8], ["", " servers", hcgui.glyph(" ● this Mac")])  # the home machine first
        self.assertEqual(lines[11], " + add server")
        self.assertEqual((self.side.rows[4], self.side.rows[11]), (hcgui.NEW_SPACE, hcgui.ADD_RIG))
        self.go(hcgui.Item("group", "space:other", ""))
        self.key("j")
        self.assertEqual(self.side.cursor, hcgui.NEW_SPACE)
        self.assertEqual(self.scr.reversed_rows(), [4])
        self.key(10)
        self.assertEqual((self.side.prompt.kind, self.side.prompt.title), ("space", "new space: name or folder"))
        self.key(27)
        self.click(3, 11)
        self.assertEqual(self.side.prompt.kind, "rig_target")
        self.assertEqual(self.side.prompt.title, "add server: ssh target (me@host, or a Host of ~/.ssh/config)")
        self.key(27)
        self.key("c")  # the strip: "+" only, still a row
        self.side.draw()
        self.assertEqual(self.scr.line(self.line_of(hcgui.ADD_RIG)), " +")
        self.assertEqual(self.scr.line(self.line_of(hcgui.NEW_SPACE)), " +")
        self.click(1, self.line_of(hcgui.NEW_SPACE))
        self.assertEqual((self.side.mode, self.side.prompt.kind), ("open", "space"))  # opened, then asked

    # menu ------------------------------------------------------------------------------------------------------
    def test_a_opens_the_menu_of_the_cursor_row_and_keys_drive_it(self):
        self.go(hcgui.Item("group", "space:dev", ""))
        self.key("a")
        menu = self.side.menu
        self.assertEqual([e.label for e in menu.entries],
                         ["Open", "New terminal here", "Rename", "Delete space"])  # spaces: no switch
        box = self.side.menu_at
        lines = self.scr.lines()
        self.assertTrue(all(len(line) <= 29 for line in lines), lines)
        self.assertIn("dev", lines[box.top])
        self.assertIn("Open", lines[box.top + 1])
        self.assertEqual(self.scr.reversed_rows()[-1], box.top + 1)  # the selected entry
        self.key("j", "j", "k")
        self.assertEqual(menu.selected, 1)
        self.key(27)
        self.assertIsNone(self.side.menu)
        self.key("a", "j", "j", 10)  # Rename
        self.assertEqual((self.side.prompt.kind, self.side.prompt.text), ("rename", "dev"))
        self.key(27, "a", "e")  # a direct key inside the menu does the same
        self.assertEqual(self.side.prompt.kind, "rename")
        self.key(27, "a", "a")  # a again closes
        self.assertIsNone(self.side.menu)
        self.key("a", 10)  # Open
        self.assertEqual((self.side.cur, hcgui.current_target(self.win)), ("space:dev", "t2"))

    def test_f12_opens_the_rows_menu_and_never_goes_into_a_typed_name(self):
        """Shift+F10 reaches the sidebar as F12 (hcgui.tmux.conf): the row's menu, as a; F12 again closes it; while a
        name is typed it adds nothing (python-pro review, 26 Nov: an "a" went into the name)."""
        self.go(hcgui.Item("group", "space:dev", ""))
        self.key(hcgui.MENU_FKEY)
        self.assertEqual(self.side.menu.item, hcgui.Item("group", "space:dev", ""))
        self.key(hcgui.MENU_FKEY)
        self.assertIsNone(self.side.menu)
        self.key("s", *"web", hcgui.MENU_FKEY)
        self.assertEqual(self.side.prompt.text, "web")

    def test_menu_in_the_strip_opens_the_sidebar_first(self):
        self.key("c")
        self.go(hcgui.Item("agent", "space:dev", "t1"))
        self.key("a")
        self.assertEqual(self.side.mode, "open")
        self.assertEqual([e.action for e in self.side.menu.entries], ["open", "rename", "move", "end", "agents"])

    def test_right_click_opens_the_rows_menu_and_clicks_inside_and_outside(self):
        row = self.line_of(hcgui.Item("group", "rig:vps", ""))
        self.click(5, row, 3)
        self.assertEqual(self.side.menu.item, hcgui.Item("group", "rig:vps", ""))
        self.assertEqual(self.side.cursor, hcgui.Item("group", "rig:vps", ""))
        self.assertEqual([e.label for e in self.side.menu.entries],
                         ["Open", "New terminal here", "Rename", "Forget server", "Hide servers"])
        with pressed(5, row, 3):  # a double click's second press
            self.key(hcgui.curses.KEY_MOUSE)
        self.assertIsNotNone(self.side.menu)  # dropped: it came within MOUSE_QUIET
        box = self.side.menu_at
        self.click(box.left + 3, box.entry_y(2))  # Rename
        self.assertIsNone(self.side.menu)
        self.assertEqual(self.side.prompt.title, "rename vps to:")
        self.key(27)
        self.click(5, row, 3)
        self.click(0, 0)  # outside: closes, opens nothing
        self.assertIsNone(self.side.menu)
        self.assertNotEqual(self.side.cur, "rig:vps")
        self.click(5, self.line_of(hcgui.Item("group", "space:other", "")), 3)
        self.click(5, self.side.menu_at.top)  # its border: nothing
        self.assertIsNotNone(self.side.menu)

    def test_a_right_click_menu_takes_clicks_only(self):
        """Keys typed after a right click were meant for the terminal: they close the menu and go on to it."""
        hcgui.write_atomic(self.win / "panes", PANES)
        row = self.line_of(hcgui.Item("group", "rig:vps", ""))
        tm = FakeTmux().install(self)
        for key, typed in (("e", "e"), ("n", "n"), ("d", "d"), ("s", "s"), ("j", "j"), (10, "<Enter>"), (27, "")):
            self.side.mouse_quiet = 0.0
            tm.calls.clear()
            self.click(5, row, 3)
            self.assertTrue(self.side.menu.by_mouse)
            self.key(key)
            self.assertIsNone(self.side.menu, key)
            self.assertIsNone(self.side.prompt, key)
            self.assertEqual(tm.typed(), typed, key)
            self.assertEqual(tm.selected()[-1], "%0", key)  # the keyboard back to the view
            self.assertEqual(hcgui.current_target(self.win), "", key)  # enter did not open the row
        self.assertFalse(any(c[0] in ("run", "kill", "rm") or c[:2] in (("machine", "add"), ("machine", "rm"))
                             for c in self.hc.calls))
        self.side.forward_until = 0.0
        self.key("a", "e")  # opened with a, the menu keeps its keys
        self.assertEqual(self.side.prompt.kind, "rename")

    def test_a_right_click_menu_shows_no_keys_and_nothing_selected(self):
        row = self.line_of(hcgui.Item("group", "rig:vps", ""))
        self.click(5, row, 3)
        box = self.side.menu_at
        lines = [self.scr.line(box.entry_y(i)) for i in range(box.offset, box.offset + box.shown)]
        self.assertFalse(any(re.search(r" [a-z↵] │$", line) for line in lines), lines)
        reversed_rows = [y for (y, x), (_, attr) in self.scr.cells.items() if attr & hcgui.curses.A_REVERSE]
        self.assertFalse(set(reversed_rows) & {box.entry_y(i) for i in range(box.offset, box.offset + box.shown)})
        self.key(27)
        self.side.forward_until = 0.0  # past the moment keys still go on to the terminal
        self.key("a")  # with a: the keys and the selected entry
        box = self.side.menu_at
        self.assertTrue(self.scr.line(box.entry_y(0)).rstrip("│").rstrip().endswith("↵") or
                        re.search(r" [a-z↵] │$", self.scr.line(box.entry_y(1))))

    def test_a_question_from_a_right_click_menu_goes_with_a_click_elsewhere(self):
        row = self.line_of(hcgui.Item("group", "rig:vps", ""))
        tm = FakeTmux().install(self)
        self.click(5, row, 3)
        box = self.side.menu_at
        self.click(box.left + 3, box.entry_y(2))  # Rename
        self.assertTrue(self.side.prompt.by_mouse)
        tm.active = False  # a click in the view
        self.side.watch_menu()
        self.assertIsNone(self.side.prompt)
        self.assertEqual(self.side.notice.current(), "cancelled")
        self.side.mouse_quiet = 0.0
        self.key("e")  # a question opened with a key: a press in the sidebar ends it and acts
        self.assertIsNotNone(self.side.prompt)
        self.click(5, self.line_of(hcgui.Item("group", "space:other", "")))
        self.assertIsNone(self.side.prompt)
        self.assertEqual(self.side.cur, "space:other")

    def test_a_paste_in_the_sidebar_goes_on_to_the_view_or_into_the_question(self):
        hcgui.write_atomic(self.win / "panes", PANES)
        tm = FakeTmux().install(self)
        self.scr.typed = [ord(c) for c in "[200~/Users/me/a.png"] + list(hcgui.PASTE_END)
        self.key(27)
        self.assertEqual(tm.inputs, ["/Users/me/a.png"])
        self.assertEqual(tm.selected()[-1], "%0")
        self.assertIsNone(self.side.prompt)  # no key of it acted: no "s" question, no "e"
        self.key("s")
        self.scr.typed = [ord(c) for c in "[200~~/dev/web"] + list(hcgui.PASTE_END)
        self.key(27)
        self.assertEqual(self.side.prompt.text, "~/dev/web")

    def test_a_right_click_menu_goes_when_another_pane_gets_the_keyboard(self):
        row = self.line_of(hcgui.Item("group", "rig:vps", ""))
        tm = FakeTmux().install(self)
        self.click(5, row, 3)
        self.side.watch_menu()
        self.assertIsNotNone(self.side.menu)
        tm.active = False  # a click in the view
        self.side.watch_menu()
        self.assertIsNone(self.side.menu)
        self.key("a")  # a menu opened with a is not watched: the keyboard is here
        tm.active = False
        self.side.watch_menu()
        self.assertIsNotNone(self.side.menu)

    def test_a_menu_whose_row_has_gone_closes(self):
        self.go(hcgui.Item("agent", "space:other", "t4"))
        self.key("a")
        self.hc.terms = [t for t in self.hc.terms if t["address"] != "t4"]
        self.side.refresh_once()
        self.side.draw()
        self.assertIsNone(self.side.menu)

    def test_menu_at_small_heights_and_narrow_widths(self):
        for item in (hcgui.Item("group", "space:dev", ""), hcgui.Item("agent", "space:dev", "t2"), hcgui.ADD_RIG):
            for height in range(1, 16):
                for width in (12, 20, 30):
                    self.scr.height, self.scr.width = height, width
                    self.side.menu = None
                    self.go(item)
                    self.key("a")
                    lines = self.scr.lines()
                    case = (item, height, width, lines)
                    self.assertTrue(all(len(line) <= width - 1 for line in lines), case)
                    if self.side.menu is not None and self.side.menu_at is not None:
                        box = self.side.menu_at
                        self.assertLessEqual(box.top + box.height, height, case)
                    self.key(27)

    # direct keys -----------------------------------------------------------------------------------------------
    def test_direct_keys_without_the_menu(self):
        self.go(hcgui.ADD_RIG)
        self.key("e")
        self.assertEqual(self.side.notice.current(), "e: cursor on a space, server or agent first")
        self.key("d")
        self.assertEqual(self.side.notice.current(), "d: cursor on a space, server or agent first")
        self.key("n")  # on a "+" row: its own question
        self.assertEqual(self.side.prompt.kind, "rig_target")
        self.key(27)
        self.go(hcgui.Item("group", "rig:mini", ""))
        self.key("d")
        self.assertEqual(self.side.notice.current(), "d: mini cannot be removed")
        self.assertIsNone(self.side.prompt)
        self.go(hcgui.Item("agent", "space:dev", "t1"))
        self.key("d")
        self.assertEqual(self.side.prompt.kind, "delete")
        self.key(27, "e")
        self.assertEqual(self.side.prompt.title, "rename tracker to:")
        self.key(27, "m")
        self.assertEqual(self.side.prompt.kind, "move")

    # rename ----------------------------------------------------------------------------------------------------
    def test_rename_a_space_and_see_it_everywhere(self):
        self.go(hcgui.Item("group", "space:dev", ""))
        self.key("e")
        self.assertEqual(self.scr.line(28), "> dev_")  # filled in: enter alone changes nothing
        self.key(21)  # ctrl+U
        self.type("Main")
        self.assertEqual(hcgui.read_names(self.state), {"space:dev": "Main"})
        self.side.draw()
        lines = self.scr.lines()
        dev = lines[self.line_of(hcgui.Item("group", "space:dev", ""))]
        self.assertEqual(dev, hcgui.glyph("›● Main"))  # the sidebar row
        self.assertIn(hcgui.glyph(" Main"), lines)  # the agents heading
        self.key(10)  # open it: the tab bar's snapshot carries the display name
        snap = hcgui.read_snapshot(self.win)
        self.assertEqual((snap["name"], snap["title"]), ("dev", "Main"))
        bar = hcgui.TabBar(FakeScr(3, 60), self.win, self.state)
        bar.show_hints()  # the space's name shows after a click on the bar, at the start of the row below the tabs
        bar.draw(snap, hcgui.current_target(self.win))
        self.assertTrue(bar.s.scr.line(2).startswith(" Main · "))
        self.key("n")  # a new shell still gets the space's own label
        self.assertEqual([c for c in self.hc.calls if c[0] == "run"][-1][-2:], ("--label", "space=dev"))
        self.key("c")  # the strip
        self.assertTrue(any(line.endswith("Main") for line in self.scr.lines()))
        self.key("o")
        self.go(hcgui.Item("group", "space:dev", ""))
        self.key("e", 21, 10)  # an empty name removes the rename
        self.assertEqual(hcgui.read_names(self.state), {})

    def test_rename_refuses_a_name_another_group_shows(self):
        self.go(hcgui.Item("group", "space:dev", ""))
        self.key("e", 21)
        self.type("Other")
        self.assertEqual(self.side.notice.current(), "rename: Other is taken")
        self.assertEqual(hcgui.read_names(self.state), {})
        self.key("e", 21)
        self.type("vps")  # a rig's shown name counts too
        self.assertEqual(self.side.notice.current(), "rename: vps is taken")

    def test_rename_a_rig_and_a_terminal(self):
        self.go(hcgui.Item("group", "rig:vps", ""))
        self.key("e", 21)
        self.type("Harry")
        self.go(hcgui.Item("agent", "space:dev", "t2"))
        self.key("e", 21)
        self.type("web")
        self.assertEqual(hcgui.read_names(self.state), {"rig:vps": "Harry", "term:t2": "web"})
        lines = self.scr.lines()
        self.assertTrue(any(line.startswith(hcgui.glyph(" ● Harry")) for line in lines), lines)
        self.assertTrue(any(line.startswith(hcgui.glyph("  ● web")) for line in lines), lines)
        # the server's only agent: no "Harry · 1" heading, and no server name on its row (owner, 24 Nov)
        self.assertIn(hcgui.glyph("  ● v1"), lines)  # no status word: the dot says it
        self.assertNotIn(hcgui.glyph(" Harry · 1"), lines)
        self.go(hcgui.Item("agent", "space:dev", "t1"))
        self.key("e", 21)
        self.type("WEB")
        self.assertEqual(self.side.notice.current(), "rename: WEB is taken")
        self.assertFalse(any(c[0] == "label" for c in self.hc.calls))  # nothing of hc changes

    def test_a_rename_in_another_window_shows_here(self):
        hcgui.change_names({"space:other": "Side"}, self.state)
        self.side.draw()
        self.assertIn(hcgui.glyph(" ● Side"), [line[:7] for line in self.scr.lines()])

    # add a rig -------------------------------------------------------------------------------------------------
    def test_add_rig_asks_twice_then_starts_a_terminal_on_this_mac_and_shows_it(self):
        self.go(hcgui.ADD_RIG)
        with mock.patch.object(hcgui, "focus_view") as focus:
            self.key(10)
            self.type("me@host:2222")
            self.assertEqual(self.side.prompt.kind, "rig_name")
            self.assertEqual(self.side.prompt.title, "name for me@host:2222 (empty = host)")
            self.type("harry")
        run = [c for c in self.hc.calls if c[0] == "run"][-1]
        self.assertEqual(list(run), hcgui.add_rig_args(hcgui.HC, "me@host:2222", "harry", str(Path.home())))
        address = hcgui.current_target(self.win)
        self.assertEqual(self.side.group_of(address).key, "space:home")  # this Mac is the home machine here
        focus.assert_called_once()  # the keyboard goes there: the questions are answered in that terminal
        self.assertIn(self.side.cursor, (hcgui.Item("agent", "space:home", address),
                                         hcgui.Item("group", "space:home", "")))

    def test_add_rig_refuses_bad_input_before_hc(self):
        for target in ("x;rm -rf ~", "-oProxyCommand=x", "a b", "hоst"):
            self.go(hcgui.ADD_RIG)
            self.key(10)
            self.side.prompt.text = target  # as if typed (the prompt itself takes ASCII only)
            self.key(10)
            self.assertEqual(self.side.notice.current(), "not a usable ssh target", target)
            self.assertIsNone(self.side.prompt)
        self.go(hcgui.ADD_RIG)
        self.key(10)
        self.type("vps2")
        self.type("Bad Name")
        self.assertEqual(self.side.notice.current(), "name: a-z 0-9 _ -, a letter first, 32 at most")
        self.assertFalse(any(c[0] == "run" for c in self.hc.calls))

    # delete ----------------------------------------------------------------------------------------------------
    def test_delete_space_lists_what_ends_and_another_key_cancels(self):
        self.go(hcgui.Item("group", "space:dev", ""))
        self.key("d")
        p = self.side.prompt
        self.assertEqual(p.title, "delete space dev? ends 3: atlas (claude-code), t1f (zsh), tracker (claude-code).")
        self.assertEqual(p.ask, hcgui.DELETE_ASK["space"])
        lines = self.scr.lines()  # the whole question, then its keys (no typed line); the list keeps the rest
        self.assertEqual(lines[-6:-1], ["delete space dev? ends 3:", "atlas (claude-code), t1f",
                                        "(zsh), tracker (claude-code).", "y deletes · any other key", "cancels"])
        self.assertEqual(self.scr.cells[(len(lines) - 2, 0)][1], hcgui.ask_attr())  # the keys orange and bold
        self.assertEqual(self.scr.cells[(len(lines) - 6, 0)][1], 0)  # what ends: plain, not dim (owner, 26 Nov)
        self.key("n")  # any other key: nothing ends
        self.assertIsNone(self.side.prompt)
        self.assertEqual(self.side.notice.current(), hcgui.DELETE_NO)
        for key in (27, 10, "d", "x", hcgui.curses.KEY_DOWN):  # esc, enter, d again, a letter, an arrow: all cancel
            self.go(hcgui.Item("group", "space:dev", ""))
            self.key("d", key)
            self.assertIsNone(self.side.prompt, key)
        self.assertEqual(self.ends(), [])
        self.assertEqual(len(self.side.groups()[0]), 3)

    def test_delete_space_ends_every_terminal_in_order_on_y_and_moves_on(self):
        hcgui.change_names({"space:dev": "Main", "term:t1": "tr", "space:other": "Side"}, self.state)
        self.go(hcgui.Item("group", "space:dev", ""))
        self.key(10)  # dev is the current group and its terminal is shown
        self.assertEqual(hcgui.current_target(self.win), "t2")
        self.key("d")
        self.assertTrue(self.side.prompt.title.startswith("delete space Main? ends 3:"))
        self.held()
        self.key("y")  # one key: no name typed
        addresses = ["t2", "t3", "t1"]  # as listed: atlas, t1f, tr (shown names)
        self.assertEqual(self.ends(), [step for a in addresses for step in hcgui.end_steps(a)])
        self.assertIsNone(self.side.prompt)
        spaces, _ = self.side.groups()
        self.assertEqual([g.key for g in spaces], ["space:home", "space:other"])
        self.assertEqual(self.side.cursor, hcgui.Item("group", "space:other", ""))  # the next group
        self.assertEqual(self.side.cur, "space:other")  # the current group went: its neighbour
        self.assertEqual(hcgui.current_target(self.win), "t4")  # the view shows a terminal that still exists
        self.assertEqual(hcgui.read_names(self.state), {"space:other": "Side"})  # its names went with it
        self.assertEqual(self.side.notice.current(), "")

    def test_delete_space_takes_capital_y_too_and_the_last_space_moves_back(self):
        hcgui.change_names({"space:other": "Side"}, self.state)
        self.go(hcgui.Item("group", "space:other", ""))
        self.key("d")
        self.held()
        self.key("Y")
        self.assertEqual(self.ends(), hcgui.end_steps("t4"))
        self.assertEqual(self.side.cursor, hcgui.Item("group", "space:dev", ""))  # the last space: the one before

    def test_a_click_cancels_the_delete_and_acts(self):
        self.go(hcgui.Item("group", "space:dev", ""))
        self.key("d")
        other = hcgui.Item("group", "space:other", "")
        self.click(5, self.line_of(other))
        self.assertIsNone(self.side.prompt)
        self.assertEqual(self.side.notice.current(), hcgui.DELETE_NO)
        self.assertEqual(self.ends(), [])
        self.assertEqual(self.side.cursor, other)  # the press acted
        self.key("d")
        self.side.mouse_quiet = time.monotonic() + 5  # the second press of the double click that opened it
        with pressed(5, 1):
            self.key(hcgui.curses.KEY_MOUSE)
        self.assertEqual(self.side.prompt.kind, "delete")  # dropped: still asking
        self.held()
        self.key("y")
        self.assertEqual(self.ends(), hcgui.end_steps("t4"))

    def test_delete_from_the_right_click_menu_takes_y(self):
        self.click(5, self.line_of(hcgui.Item("group", "space:other", "")), button=3)
        self.assertTrue(self.side.menu.by_mouse)
        entry = next(i for i, e in enumerate(self.side.menu.entries) if e.action == "delete")
        box = self.side.menu_at
        self.click(box.left + 3, box.entry_y(entry))
        self.assertEqual((self.side.prompt.kind, self.side.prompt.by_mouse), ("delete", True))
        self.held()
        self.key("y")
        self.assertEqual(self.ends(), hcgui.end_steps("t4"))

    def test_d_and_y_typed_in_one_go_end_nothing(self):
        # review of 24 Nov: a word typed while the sidebar kept the keyboard (after j/k, or a click on a heading)
        # ended a whole space: d asked, and the word's y answered at once. The clock stands still here: every key
        # of the word comes in the same instant, as typed keys come a few tenths of a second apart.
        clock = [1000.0]
        dev = hcgui.Item("group", "space:dev", "")
        with mock.patch.object(hcgui.time, "monotonic", lambda: clock[0]):
            for word in ("tidy", "lady"):  # d asks (in "lady": a opens the menu, d is its Delete space); y waits
                self.go(dev)
                self.key(*word)
                self.assertEqual((self.side.prompt.kind, self.ends()), ("delete", []), word)
                self.key("x")  # the next key typed cancels it
                self.assertEqual((self.side.prompt, self.side.notice.current()), (None, hcgui.DELETE_NO), word)
            self.go(dev)
            self.key(*"dynamic")  # n, right after the y, cancels
            self.assertEqual(self.ends(), [])
            self.assertNotEqual(getattr(self.side.prompt, "kind", None), "delete")
            self.key(27)
            self.go(dev)
            self.key("d")
            clock[0] += hcgui.DELETE_HOLD - 0.01
            self.key("y")  # still too soon
            self.assertEqual(self.ends(), [])
            clock[0] += 0.01  # the list read: y is taken
            self.key("y")
        self.assertEqual(sorted({c[1] for c in self.ends()}), ["t1", "t2", "t3"])
        self.assertIsNone(self.side.prompt)

    def test_a_question_from_a_right_click_menu_gives_the_keyboard_back(self):
        # the right click gave the sidebar the keyboard (hcgui.tmux.conf); once its question is answered or
        # cancelled with a key, typing goes to the terminal again, as after the tab bar's Close
        def ask_by_menu(row, action):
            self.click(5, self.line_of(row), button=3)
            entry = next(i for i, e in enumerate(self.side.menu.entries) if e.action == action)
            box = self.side.menu_at
            self.click(box.left + 3, box.entry_y(entry))
            self.assertTrue(self.side.prompt.by_mouse)

        dev, other = hcgui.Item("group", "space:dev", ""), hcgui.Item("group", "space:other", "")
        with mock.patch.object(hcgui, "focus_view") as focus:
            ask_by_menu(other, "delete")
            focus.assert_not_called()  # the question has the keyboard
            self.key("n")
            self.assertEqual(self.side.notice.current(), hcgui.DELETE_NO)
            focus.assert_called_once_with(self.win)
            focus.reset_mock()
            ask_by_menu(dev, "delete")
            self.hc.terms.append(term("t30", "/Users/x/dev", "zsh", "late"))  # what ends changes meanwhile
            self.side.refresh_once()
            self.held()
            self.key("y")
            self.assertTrue(self.side.prompt.title.startswith("changed: "))
            focus.assert_not_called()  # asked again: the keyboard stays for the answer
            self.held()
            self.key("y")
            self.assertEqual(sorted({c[1] for c in self.ends()}), ["t1", "t2", "t3", "t30"])
            focus.assert_called_once_with(self.win)
            focus.reset_mock()
            ask_by_menu(other, "delete")
            self.hc.terms = [t for t in self.hc.terms if t["address"] != "t4"]  # gone meanwhile
            self.side.refresh_once()
            self.held()
            self.key("y")
            self.assertEqual(self.side.notice.current(), "that space has gone")
            focus.assert_called_once_with(self.win)
            focus.reset_mock()
            ask_by_menu(hcgui.Item("group", "rig:vps", ""), "rename")  # a typed question too
            self.key(27)
            focus.assert_called_once_with(self.win)
            focus.reset_mock()
            self.go(hcgui.Item("group", "space:home", ""))
            self.key("d", "n")  # d typed: the sidebar had the keyboard on purpose, and keeps it
            self.assertEqual(self.side.notice.current(), hcgui.DELETE_NO)
            focus.assert_not_called()

    def test_delete_asks_again_when_what_ends_has_changed(self):
        self.go(hcgui.Item("group", "space:dev", ""))
        self.key("d")
        self.assertEqual(self.side.prompt.data, ("space:dev", "t2", "t3", "t1"))
        self.hc.terms.append(term("t30", "/Users/x/dev", "zsh", "late"))  # started meanwhile, in that space
        self.side.refresh_once()
        self.held()
        self.key("y")
        self.assertEqual(self.ends(), [])
        self.assertEqual(set(self.side.prompt.data), {"space:dev", "t1", "t2", "t3", "t30"})
        self.assertTrue(self.side.prompt.title.startswith("changed: delete space dev? ends 4:"))
        self.assertTrue(any(line.startswith("changed: delete space") for line in self.scr.lines()))  # on screen
        self.key("y")  # at once: not taken
        self.assertEqual(self.ends(), [])
        self.assertIsNotNone(self.side.prompt)
        self.held()
        self.key("y")
        self.assertEqual(sorted({c[1] for c in self.ends()}), ["t1", "t2", "t3", "t30"])
        self.assertIsNone(self.side.prompt)

    def test_end_asks_again_when_a_child_now_ends_with_it(self):
        self.go(hcgui.Item("agent", "space:dev", "t1"))
        self.key("d")
        self.assertEqual(self.side.prompt.title, "end tracker? ends 1: tracker (claude-code).")
        self.hc.infos["t3"] = {"parent": "t1"}  # t1f now ends with tracker
        self.side.refresh_once(full=True)
        self.held()
        self.key("y")
        self.assertEqual(self.ends(), [])
        self.assertEqual(self.side.prompt.title, "changed: end tracker? ends 2: tracker (claude-code), t1f (zsh).")
        self.held()
        self.key("y")
        self.assertEqual(self.ends(), hcgui.end_steps("t1") + hcgui.end_steps("t3"))

    def test_y_ends_nothing_once_the_terminal_or_space_has_gone(self):
        self.go(hcgui.Item("agent", "space:dev", "t2"))
        self.key("d")
        self.hc.terms = [t for t in self.hc.terms if t["address"] != "t2"]  # ended elsewhere meanwhile
        self.side.refresh_once()
        self.held()
        self.key("y")
        self.assertEqual(self.side.notice.current(), "that terminal has ended")
        self.assertIsNone(self.side.prompt)
        self.go(hcgui.Item("group", "space:other", ""))
        self.key("d")
        self.hc.terms = [t for t in self.hc.terms if t["address"] != "t4"]
        self.side.refresh_once()
        self.held()
        self.key("y")
        self.assertEqual(self.side.notice.current(), "that space has gone")
        self.assertEqual(self.ends(), [])

    def test_a_cut_list_does_not_take_y_until_it_all_shows(self):
        kids = [term(f"t{n}", "/Users/x/dev", "zsh", f"child-number-{n}") for n in range(20, 32)]
        self.hc.terms += kids
        self.side.refresh_once()
        self.scr.height = 12  # 12 lines: the list keeps two, the question gets the rest
        self.go(hcgui.Item("group", "space:dev", ""))
        self.key("d")
        self.assertTrue(self.side.yes_cut)
        lines = self.scr.lines()
        self.assertIn("the list is cut: widen the", lines)
        self.assertTrue(any(line.endswith("…") for line in lines))  # the cut is marked
        self.held()  # long enough: only the cut keeps y from being taken
        self.key("y")
        self.assertEqual(self.ends(), [])
        self.assertIsNotNone(self.side.prompt)  # still asking
        self.scr.height = 30  # taller: the question takes every line it needs
        self.side.draw()
        self.assertFalse(self.side.yes_cut)
        self.assertEqual(self.scr.lines()[-3:-1], ["y deletes · any other key", "cancels"])
        self.held()
        self.key("y")
        self.assertEqual(len([c for c in self.ends() if c[0] == "kill"]), 15)

    def test_the_delete_question_at_every_size(self):
        self.go(hcgui.Item("group", "space:dev", ""))
        self.key("d")
        p = self.side.prompt
        for height in range(1, 31):
            for width in (8, 30, 80):
                case = (height, width)
                self.scr.height, self.scr.width = height, width
                self.side.draw()
                lines = self.scr.lines()
                if height >= 2:
                    self.assertTrue(lines[-1].lstrip().startswith(hcgui.glyph("‹")), case)  # never drawn over
                keys = hcgui.wrap_words(hcgui.DELETE_CUT if self.side.yes_cut else p.ask, width - 1)
                if height >= 6:  # room for the keys: the line above "‹" ends them
                    self.assertEqual(lines[-2], keys[-1], case)
                # whole when the list of rows keeps two lines: y is taken then, else not
                self.assertEqual(self.side.yes_cut, hcgui.yes_height(p.title, p.ask, width - 1) > height - 3, case)
        self.assertIsNotNone(self.side.prompt)

    def test_a_paste_cancels_the_delete_and_goes_to_the_view(self):
        self.go(hcgui.Item("group", "space:dev", ""))
        self.key("d")
        with mock.patch.object(hcgui, "paste_to_view", return_value=True) as paste:
            self.side.pasted("y")
        paste.assert_called_once_with("y", self.win)
        self.assertIsNone(self.side.prompt)
        self.assertEqual(self.side.notice.current(), hcgui.DELETE_NO)
        self.assertEqual(self.ends(), [])

    def test_end_terminal_lists_children_and_shows_a_sibling(self):
        self.hc.infos["t3"] = {"parent": "t1"}  # t1f was started from tracker: it ends with it
        self.side.refresh_once(full=True)
        self.go(hcgui.Item("agent", "space:dev", "t1"))
        self.key(10)
        self.assertEqual(hcgui.current_target(self.win), "t1")
        self.key("d")
        p = self.side.prompt
        self.assertEqual((p.title, p.ask), ("end tracker? ends 2: tracker (claude-code), t1f (zsh).",
                                            hcgui.DELETE_ASK["end"]))
        self.held()
        self.key("y")
        self.assertEqual(self.ends(), hcgui.end_steps("t1") + hcgui.end_steps("t3"))
        self.assertEqual(self.hc.finished, {})  # removed, not left as finished terminals
        self.assertEqual(self.side.cursor, hcgui.Item("agent", "space:dev", "t2"))  # the agent before it
        self.assertEqual(hcgui.current_target(self.win), "t2")  # dev still has a terminal: shown

    def test_end_an_unnamed_terminal_and_the_last_one_leaves_nothing(self):
        self.hc.terms.append(term("t20", "/Users/x/dev/solo", "python3"))
        self.side.refresh_once()
        self.go(hcgui.Item("agent", "space:solo", "t20"))
        self.key(10)
        self.key("d")
        self.assertEqual(self.side.prompt.title, "end t20? ends 1: t20 (python3).")
        self.held()
        self.key("y")
        self.assertEqual(self.ends(), hcgui.end_steps("t20"))
        self.assertNotIn("space:solo", [g.key for g in self.side.everything()])
        self.assertEqual(self.side.cursor, hcgui.Item("group", "space:other", ""))  # no group left of it: neighbour
        self.assertEqual(self.side.cur, "space:other")
        self.assertEqual(hcgui.current_target(self.win), "t4")

    def test_ending_the_shown_terminal_of_a_group_with_nothing_left_shows_nothing(self):
        self.hc.terms = [term("t1", "/Users/x/dev", "claude-code", "only", "idle")]
        self.hc.machines = []
        self.side.refresh_once()
        self.go(hcgui.Item("agent", "space:dev", "t1"))
        self.key(10, "d")
        self.held()
        self.key("y")
        self.assertEqual(hcgui.current_target(self.win), "")  # the view says to pick a terminal
        self.assertEqual(self.side.everything(), [])

    def test_a_failed_end_says_so_and_the_others_still_end(self):
        real = self.hc.__call__

        def flaky(*args, **kw):
            if args[:2] == ("kill", "t3"):
                raise hc_error("unreachable", "core went away")
            return real(*args, **kw)

        self.go(hcgui.Item("group", "space:dev", ""))
        self.key("d")
        self.held()
        with mock.patch.object(hcgui, "run_hc", flaky):
            self.key("y")
        self.assertEqual(self.side.notice.current(), "end: 1 of 3 failed, t3: core went away")
        self.assertTrue(self.side.notice.bad)
        self.assertIn(("rm", "t1"), self.hc.calls)

    def test_forget_server(self):
        hcgui.change_names({"rig:vps": "Harry", "space:dev": "Main"}, self.state)
        self.go(hcgui.Item("group", "rig:vps", ""))
        self.key("d")
        p = self.side.prompt
        self.assertEqual((p.title, p.ask), ("forget server Harry? its terminals keep running there.",
                                            "type Harry to confirm:"))
        self.type("vps")  # its hc name works too
        self.assertIn(("machine", "rm", "vps"), self.hc.calls)
        self.assertEqual(self.ends(), [])  # its terminals are not ended
        self.assertNotIn("rig:vps", [g.key for g in self.side.everything()])
        self.assertEqual(hcgui.read_names(self.state), {"space:dev": "Main"})
        self.assertEqual(self.side.cursor, hcgui.Item("group", "rig:mini", ""))  # the next server

    def test_forget_needs_the_name_and_never_offers_this_mac_or_home(self):
        self.go(hcgui.Item("group", "rig:vps", ""))
        self.key("d", "y")  # not d's one-key question: y is typed, nothing happens yet
        self.assertEqual((self.side.prompt.kind, self.side.prompt.text), ("forget", "y"))
        self.assertEqual(self.scr.lines()[-2], "> y_")
        self.key(10)
        self.assertNotIn(("machine", "rm", "vps"), self.hc.calls)
        self.assertEqual(self.side.notice.current(), "cancelled: the name did not match")
        self.key("d")
        self.type("vp")
        self.assertNotIn(("machine", "rm", "vps"), self.hc.calls)
        self.assertEqual(self.side.notice.current(), "cancelled: the name did not match")
        self.hc.terms.append(term("mini/t1", "/Users/x/dev"))  # now mini is home; this Mac another server
        self.side.refresh_once()
        for key in ("rig:this Mac", "rig:mini"):
            self.go(hcgui.Item("group", key, ""))
            self.key("a")
            self.assertEqual([e.action for e in self.side.menu.entries], ["open", "new", "rename", "servers"])
            self.key(27, "d")
            self.assertEqual(self.side.notice.current(), f"d: {key[4:]} cannot be removed")
            self.assertIsNone(self.side.prompt)


class ScriptTests(unittest.TestCase):
    def test_shell_syntax(self):
        for name in ("view.sh", "build.sh", "start.sh", "usage.sh"):
            out = subprocess.run(["/bin/sh", "-n", str(ROOT / name)], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)

    def test_build_keeps_the_install_line_and_never_edits_the_ghostty_config(self):
        text = (ROOT / "build.sh").read_text()
        self.assertIn("git clone https://github.com/PerIPan/herdr-core-GUI ~/.local/share/hcgui && "
                      "sh ~/.local/share/hcgui/build.sh", text)
        self.assertIn("git -C ~/.local/share/hcgui pull && sh ~/.local/share/hcgui/build.sh", text)
        self.assertNotIn("focus-follows-mouse", text)  # one click is enough without it now
        self.assertNotIn("Application Support/com.mitchellh.ghostty", text)  # the config is not even read
        self.assertNotRegex(text, r"ghostty/config")

    def test_start_runs_the_view_relay_with_tmuxs_terminal_type(self):
        text = (ROOT / "start.sh").read_text()
        line = next(x for x in text.splitlines() if "hcgui.py\") view" in x)
        self.assertEqual(line.strip(), '"exec python3 $(q "$here/hcgui.py") view" 2>&1)')  # no ${term}: no xterm-hcgui
        self.assertNotIn("view.sh\")", text)  # nothing starts view.sh itself any more
        self.assertIn('"$py sidebar"', text)
        self.assertIn('"$py tabs"', text)

    def setup_report(self, machines=(), zshrc="", **env):
        """The last part of build.sh (its setup report), run alone with a stand-in hc and HOME."""
        text = (ROOT / "build.sh").read_text()
        part = text[text.index("# What is set up and what is left"):]
        with tempfile.TemporaryDirectory() as home:
            hc = Path(home) / ".local/bin/hc"
            hc.parent.mkdir(parents=True)
            listing = json.dumps({"machines": [{"name": m, "target": f"me@{m}"} for m in machines]})
            hc.write_text(f"#!/bin/sh\necho '{listing}'\n")
            hc.chmod(0o755)
            (Path(home) / ".zshrc").write_text(zshrc)
            environ = {"PATH": "/usr/bin:/bin", "HOME": home, **env}
            out = subprocess.run(["/bin/sh", "-c", part], env=environ, capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def test_build_ends_with_what_is_set_and_what_is_left(self):
        out = self.setup_report()
        self.assertIn("setup (README: Setup; AI agents: AGENTS.md):", out)
        self.assertIn("home:   this Mac (no servers", out)
        self.assertIn("usage:  off (optional)", out)
        self.assertIn("marks:  none; only for two or more subscriptions", out)
        self.assertIn("start hcGUI.app", out)
        self.assertIn("home:   box, the only server", self.setup_report(["box"]))
        several = self.setup_report(["a", "b"])
        self.assertIn("servers: a b. If one of them is home: export HCGUI_FIRST=<name>", several)
        # from ~/.zshrc when the shell has none (an agent's shell may not read it), or from the shell
        out = self.setup_report(["a", "b"], 'export HCGUI_FIRST="b"\nexport HCGUI_MARKS="x=¹,y=²"\n')
        self.assertIn("home:   b (HCGUI_FIRST)", out)
        self.assertIn("usage:  optional, set up on b", out)
        self.assertNotIn("marks:", out)
        self.assertIn("home:   a (HCGUI_FIRST)", self.setup_report(["a", "b"], "export HCGUI_FIRST=b\n",
                                                               HCGUI_FIRST="a"))

    def test_ai_agents_get_their_notes(self):
        """Owner, 24 Nov: an AI agent installing gets notice of the setup: AGENTS.md (CLAUDE.md loads it), linked
        from the README's install and named by build.sh's last lines; it ships in the public copy."""
        agents = (ROOT / "AGENTS.md").read_text()
        self.assertIn("git clone https://github.com/PerIPan/herdr-core-GUI ~/.local/share/hcgui && "
                      "sh ~/.local/share/hcgui/build.sh", agents)
        for words in ("Ask before setting anything", "never replace it", "HCGUI_FIRST", "HCGUI_MARKS",
                      "Back up each `settings.json`", "CLAUDE_CODE_DISABLE_TERMINAL_TITLE"):
            self.assertIn(words, agents)
        self.assertEqual((ROOT / "CLAUDE.md").read_text().strip(), "@AGENTS.md")
        readme = (ROOT / "README.md").read_text()
        self.assertIn("[AGENTS.md](AGENTS.md)", readme)
        self.assertIn("## Setup", readme)
        gitattributes = ROOT / ".gitattributes"  # not in the public copy (export-ignore itself)
        attributes = gitattributes.read_text() if gitattributes.exists() else ""
        self.assertNotIn("AGENTS.md", attributes)
        self.assertNotIn("CLAUDE.md", attributes)

    def test_build_needs_tmux_and_the_new_files(self):
        text = (ROOT / "build.sh").read_text()
        self.assertIn('echo "hcGUI: tmux not found (brew install tmux)" >&2; exit 1', text)
        self.assertIn("for f in hcgui.py view.sh start.sh hcgui.tmux.conf usage.sh; do", text)

    def test_launcher_types_start_sh_into_one_window(self):
        text = (ROOT / "build.sh").read_text()
        script = text[text.index("osacompile"):text.index("\nEOF\n", text.index("osacompile"))]
        lines = [line.strip() for line in script.splitlines()]
        self.assertIn('set initial input of cfg to "exec env HCGUI_WINDOW=" & (quoted form of winDir) & " sh " & '
                      '(quoted form of (base & "start.sh")) & linefeed', lines)
        self.assertNotIn(" split ", script)  # tmux makes the panes, not Ghostty
        self.assertEqual(lines[-1], "end tell")  # the heredoc ends right after it
        self.assertTrue(text[text.index(script) + len(script):].startswith("\nEOF\nrm -rf \"$app\"\n"))
        self.assertEqual(sum(line.startswith("set win to new window") for line in lines), 1)

    def test_build_header_says_what_to_expect_of_the_three_states(self):
        text = (ROOT / "build.sh").read_text()
        header = " ".join(text[:text.index("set -eu")].lower().replace("#", " ").split())
        for words in ("open, strip", "hidden (its pane closes", "\"›\", whose click", "untested", "brings the sidebar back at full",
                      "one click acts, in any pane", "‹ back"):
            self.assertIn(words, header)

    def test_build_header_says_what_to_expect_of_the_menu(self):
        text = (ROOT / "build.sh").read_text()
        header = " ".join(text[:text.index("set -eu")].lower().replace("#", " ").split())
        for words in ("a right click on a sidebar row or a tab, or in the shown terminal, opens its menu",
                      "keys typed then go on to the terminal", "a file dropped on the window lands in the terminal",
                      "adding and forgetting a real machine"):
            self.assertIn(words, header)
        readme = " ".join((ROOT / "README.md").read_text().split())
        for words in ("Delete space and End terminal list everything that ends and end it on `y`",
                      "Forget server asks for the server's name to be typed first", "names.json",
                      "A right click on a tab, or in the shown terminal, opens its menu", "brew install tmux",
                      "A file dropped on the window reaches the shown terminal"):
            self.assertIn(words, readme)


class TmuxWindowCase(unittest.TestCase):
    """start.sh with the real tmux, in a pseudo terminal, against a stand-in hc (HC: a shell script). Skipped where
    tmux is not installed. No tests of its own."""

    HC = ('#!/bin/sh\ncase "$1 $2" in "ls --json") echo \'{"terminals": [{"address": "t1", '
          '"agent": "zsh", "cwd": "/tmp/work", "state": "live", "name": "one"}]}\' ;; '
          '"machine ls") echo \'{"machines": []}\' ;; "get t1") echo "{}" ;; '
          '"attach t1") trap "exit 0" TERM; while :; do sleep 1; done ;; esac\nexit 0\n')

    def extra_env(self, tmp):
        """Settings for start.sh besides the fixtures' own."""
        return {}

    def setUp(self):
        self.tmux = shutil.which("tmux") or next((p for p in ("/opt/homebrew/bin/tmux", "/usr/local/bin/tmux")
                                                  if os.access(p, os.X_OK)), None)
        if self.tmux is None:
            self.skipTest("tmux not installed")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.tmp = tmp
        self.win = tmp / "state" / "w-test01"
        self.win.mkdir(parents=True)
        hc = tmp / "hc"
        hc.write_text(self.HC)
        hc.chmod(0o755)
        self.sock = "hcgui-" + self.win.name
        env = {k: v for k, v in os.environ.items() if not k.startswith(("HCGUI_", "TMUX"))}
        env.update(TERM="xterm-256color", HCGUI_HC=str(hc), HCGUI_STATE=str(tmp / "state"),
                   HCGUI_WINDOW=str(self.win), HCGUI_KEYCHAIN="0", HCGUI_BROWSER="0",
                   PYTHONDONTWRITEBYTECODE="1")
        env.update(self.extra_env(tmp))
        import pty
        pid, fd = pty.fork()
        if pid == 0:
            os.execve("/bin/sh", ["/bin/sh", str(ROOT / "start.sh")], env)
        self.pid, self.fd = pid, fd
        self.size(120, 40)
        threading.Thread(target=self.drain, daemon=True).start()
        self.addCleanup(self.close)
        # runs before close (last added, first run): with the server gone the drain thread's read() ends, else
        # closing the pty under that read blocks on macOS and the suite hangs
        self.addCleanup(lambda: subprocess.run([self.tmux, "-L", self.sock, "kill-server"], capture_output=True))

    def size(self, cols, rows):
        import fcntl
        import struct
        import termios
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        os.kill(self.pid, signal.SIGWINCH)

    def drain(self):
        while True:
            try:
                if not os.read(self.fd, 65536):
                    return
            except OSError:
                return

    def close(self):
        """The window closes as a terminal app closes one: a hangup to its processes, then the pty goes. A bare close
        of the pty can block on macOS while tmux's client lives (seen after a popup menu)."""
        try:
            os.killpg(self.pid, signal.SIGHUP)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass

    def t(self, *args):
        return subprocess.run([self.tmux, "-L", self.sock, *args], capture_output=True, text=True).stdout

    def panes(self):
        """{pane id: (left, top, width, height)} and the active pane."""
        out, active = {}, ""
        for line in self.t("list-panes", "-F", "#{pane_id} #{pane_left} #{pane_top} #{pane_width} #{pane_height} "
                                                "#{pane_active}").splitlines():
            parts = line.split()
            out[parts[0]] = tuple(int(v) for v in parts[1:5])
            if parts[5] == "1":
                active = parts[0]
        return out, active


class StartScriptTests(TmuxWindowCase):
    """start.sh with the real tmux, in a pseudo terminal, against a stand-in hc with one terminal of this Mac."""

    def test_layout_sizes_click_and_close(self):
        self.assertTrue(wait_for(lambda: len(hcgui.read_panes(self.win)) == 3, 10))
        ids = hcgui.read_panes(self.win)
        side, tabs, view = ids["side"], ids["tabs"], ids["view"]
        # the view pane runs the relay (tmux's terminal type, not xterm-hcgui), and view.sh runs under it: the attach
        # hcgui.py may end is still a child of view.loop
        relay = int(self.t("display", "-p", "-t", view, "#{pane_pid}").strip())
        self.assertTrue(wait_for(lambda: (self.win / "view.loop").exists(), 10))
        loop = int(hcgui.read_text(self.win / "view.loop"))
        self.assertEqual(hcgui.proc_info(loop)[0], relay)
        self.assertTrue(hcgui.proc_info(relay)[1].endswith("hcgui.py view"), hcgui.proc_info(relay))
        self.assertTrue(wait_for(lambda: hcgui.attach_pid(self.win) != 0, 10))
        environ = subprocess.run(["/bin/ps", "-E", "-o", "command=", "-p", str(relay)], capture_output=True,
                                 text=True).stdout
        self.assertIn("TERM=screen-256color", environ)
        self.assertNotIn("TERMINFO=", environ)

        def laid_out(cols, rows):
            panes, active = self.panes()
            return (len(panes) == 3 and panes[side] == (0, 0, hcgui.WIDTH, rows)
                    and panes[tabs][2:] == (cols - hcgui.WIDTH - 1, hcgui.TAB_ROWS)
                    and panes[view][1] == hcgui.TAB_ROWS + 1 and active == view)

        self.assertTrue(wait_for(lambda: laid_out(120, 40), 10), self.panes())
        self.size(160, 50)  # a bigger window: tmux spreads it, the panes set their sizes again
        self.assertTrue(wait_for(lambda: laid_out(160, 50), 10), self.panes())
        self.assertEqual(self.t("show", "-gv", "prefix").strip(), "None")
        sgr = {p: self.t("display", "-p", "-t", p, "#{mouse_sgr_flag}").strip() for p in (side, tabs)}
        self.assertEqual(sgr, {side: "1", tabs: "1"})  # xterm-hcgui: a click far right keeps its column
        self.assertTrue((self.win / "terminfo").is_dir())
        # one click on "‹ fold" (the sidebar's last line), while the view has the keyboard: it acts at once
        os.write(self.fd, b"\x1b[<0;3;50M")
        time.sleep(0.05)
        os.write(self.fd, b"\x1b[<0;3;50m")
        self.assertTrue(wait_for(lambda: self.panes()[0][side][2] == hcgui.NARROW, 10), self.panes())
        self.assertEqual(hcgui.read_text(self.win.parent / "sidebar"), "strip")
        # q in the sidebar: its pane closes, the tab bar takes the width and shows "›"; one click on it brings a
        # full-height sidebar back
        self.t("send-keys", "-t", side, "q")
        self.assertTrue(wait_for(lambda: side not in self.panes()[0] and self.panes()[0][tabs][0] == 0, 10),
                        self.panes())
        self.assertTrue(wait_for(lambda: "›" in self.t("capture-pane", "-p", "-t", tabs).splitlines()[0], 10))
        os.write(self.fd, b"\x1b[<0;1;1M")
        time.sleep(0.05)
        os.write(self.fd, b"\x1b[<0;1;1m")
        self.assertTrue(wait_for(lambda: len(self.panes()[0]) == 3, 10), self.panes())
        new = hcgui.read_panes(self.win)["side"]
        self.assertNotEqual(new, side)
        self.assertTrue(wait_for(lambda: self.panes()[0][new] == (0, 0, hcgui.WIDTH, 50), 10), self.panes())
        self.assertEqual(hcgui.read_text(self.win.parent / "sidebar"), "open")
        # a slow drag of the divider, one column at a time: every step stays, the width is kept for later windows
        x = hcgui.WIDTH + 1  # the border column (1-based): right of the 30-column sidebar
        os.write(self.fd, f"\x1b[<0;{x};20M".encode())
        for step in range(1, 9):
            time.sleep(0.12)
            os.write(self.fd, f"\x1b[<32;{x + step};20M".encode())
        time.sleep(0.12)
        os.write(self.fd, f"\x1b[<0;{x + 8};20m".encode())
        self.assertTrue(wait_for(lambda: self.panes()[0][new][2] == hcgui.WIDTH + 8, 10), self.panes())
        self.assertTrue(wait_for(lambda: hcgui.read_text(self.win.parent / "width") == str(hcgui.WIDTH + 8), 10))
        self.size(170, 50)  # a wider window: the dragged width stays
        time.sleep(0.5)
        self.assertTrue(wait_for(lambda: self.panes()[0][new][2] == hcgui.WIDTH + 8, 10), self.panes())
        # a right click in the view: the shown terminal's menu, in the tab bar, which takes the keyboard; a key closes it
        tabs = hcgui.read_panes(self.win)["tabs"]
        view = hcgui.read_panes(self.win)["view"]
        self.assertTrue(wait_for(lambda: hcgui.current_target(self.win) == "t1", 10))
        os.write(self.fd, b"\x1b[<2;120;30M")
        time.sleep(0.05)
        os.write(self.fd, b"\x1b[<2;120;30m")
        self.assertTrue(wait_for(lambda: "New terminal" in self.t("capture-pane", "-p", "-t", tabs), 10),
                        self.t("capture-pane", "-p", "-t", tabs))
        self.assertTrue(wait_for(lambda: self.panes()[1] == tabs, 10))
        # the popup at the pointer (tmux's menu) takes the keys while it is open, as a context menu does: esc
        # closes it, the row stays; a key then closes the row and goes on to the terminal
        time.sleep(0.5)  # the popup opens before the row is drawn (open_tab_menu)
        os.write(self.fd, b"q")  # closes the popup, as esc does (a lone esc from this pty may wait)
        time.sleep(0.5)
        os.write(self.fd, b"x")
        self.assertTrue(wait_for(lambda: self.panes()[1] == view, 10))
        self.assertTrue(wait_for(lambda: "New terminal" not in self.t("capture-pane", "-p", "-t", tabs), 10))
        # a double click on a sidebar row: the pick gives the view the keyboard, and the double click leaves it there
        side_lines = self.t("capture-pane", "-p", "-t", new).splitlines()
        row = next(i for i, line in enumerate(side_lines) if " work" in line) + 1
        for _ in range(2):
            os.write(self.fd, f"\x1b[<0;6;{row}M".encode())
            time.sleep(0.03)
            os.write(self.fd, f"\x1b[<0;6;{row}m".encode())
            time.sleep(0.08)
        time.sleep(0.8)  # tmux reports the double click about 300 ms later
        self.assertEqual(self.panes()[1], view)
        # ctrl+C typed after a right click in the view goes on to the terminal; the tab bar lives on (raw mode)
        os.write(self.fd, b"\x1b[<2;120;30M")
        time.sleep(0.05)
        os.write(self.fd, b"\x1b[<2;120;30m")
        self.assertTrue(wait_for(lambda: self.panes()[1] == tabs, 10))
        time.sleep(0.5)
        os.write(self.fd, b"q")  # the popup first (q closes it as esc does; a lone esc may wait here)
        time.sleep(0.5)
        os.write(self.fd, b"\x03")
        self.assertTrue(wait_for(lambda: self.panes()[1] == view, 10))
        time.sleep(0.5)
        self.assertIn(tabs, self.panes()[0])
        # zoomed: a right click in the view leaves the zoom (the tab bar is hidden then)
        self.t("resize-pane", "-Z", "-t", view)
        self.assertTrue(wait_for(lambda: self.t("display", "-p", "#{window_zoomed_flag}").strip() == "1", 10))
        os.write(self.fd, b"\x1b[<2;120;30M")
        time.sleep(0.05)
        os.write(self.fd, b"\x1b[<2;120;30m")
        time.sleep(0.8)
        self.assertEqual(self.t("display", "-p", "#{window_zoomed_flag}").strip(), "1")
        self.assertFalse((self.win / "ask").exists())
        self.close()  # the window closed: its tmux ends
        self.assertTrue(wait_for(lambda: subprocess.run([self.tmux, "-L", self.sock, "ls"],
                                                        capture_output=True).returncode != 0, 10))

class StartFailureTests(unittest.TestCase):
    def run_start(self, tmux_script, width="abc"):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bad = tmp / "bin"
            bad.mkdir()
            log = tmp / "tmux.log"
            (bad / "tmux").write_text("#!/bin/sh\necho \"$*\" >> " + str(log) + "\n" + tmux_script)
            (bad / "tmux").chmod(0o755)
            env = {"HOME": str(tmp), "PATH": f"{bad}:/usr/bin:/bin", "HCGUI_STATE": str(tmp / "state"),
                   "HCGUI_WIDTH": width}
            out = subprocess.run(["/bin/sh", str(ROOT / "start.sh")], env=env, input="\n", capture_output=True,
                                 text=True, timeout=20)
            return out, log.read_text().splitlines() if log.exists() else []

    def test_a_tmux_that_fails_is_said_and_leaves_nothing_behind(self):
        out, calls = self.run_start("echo 'no server: broken' >&2\nexit 1\n")
        self.assertEqual(out.returncode, 1)
        self.assertIn("hcGUI: tmux could not start: no server: broken", out.stdout)
        self.assertIn("(enter closes this window)", out.stdout)
        self.assertTrue(calls[-1].startswith("-L hcgui-w-") and calls[-1].endswith(" kill-server"), calls)

    def test_a_split_that_fails_ends_the_server_and_a_junk_width_is_30(self):
        script = 'case "$*" in *new-session*) echo %0 ;; *split-window*) echo "no space" >&2; exit 1 ;; esac\n'
        out, calls = self.run_start(script)
        self.assertIn("hcGUI: tmux could not make the sidebar: no space", out.stdout)
        split = next(c for c in calls if "split-window" in c)
        self.assertIn(" -l 30 ", split)  # HCGUI_WIDTH=abc
        self.assertTrue(calls[-1].endswith(" kill-server"))
        out, calls = self.run_start(script, width="7")
        self.assertIn(" -l 30 ", next(c for c in calls if "split-window" in c))  # out of 10-200

class ServerTests(unittest.TestCase):
    """The servers section: user@host names, the home machine's row, hidden by default, v and the menu switch. The
    terminals and machines are a laptop's: the home machine "mini" and the machine "rig" (a guest account on the
    same machine)."""

    TERMS = [term("mini/t1", "/Users/x/dev/atlas", "claude-code", "atlas", "idle"),
             term("mini/t2", "/Users/x/dev/tracker", "claude-code", "tracker", "working"),
             term("mini/t3", "/Users/x/dev/tracker", "zsh", "sh"),
             term("rig/t1", "/Users/guest", "claude-code", "harry", "idle")]
    MACHINES = [("mini", "me@mini"), ("rig", "guest@mini")]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"
        self.hc = FakeHc(self.TERMS, machines=self.MACHINES)
        for target, value in ((hcgui, {"run_hc": self.hc, "FIRST": "mini"}),
                              (hcgui.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scr = FakeScr(24, 30)
        seen_done(self.state, self.hc.terms)
        self.side = hcgui.Sidebar(self.scr, self.state, self.win)
        self.side.refresh_once()
        self.side.sync()
        self.side.draw()

    def key(self, *keys):
        for k in keys:
            self.side.on_key(ord(k) if isinstance(k, str) else k)
            self.side.sync()
            self.side.draw()

    def type(self, text):
        self.key(*text)
        self.key(10)

    def go(self, item):
        self.side.cursor = item
        self.side.draw()

    # names -----------------------------------------------------------------------------------------------------
    def test_user_at_host_from_the_ssh_target(self):
        label = hcgui.server_label
        M = hcgui.Machine
        self.assertEqual(label(M("mini", "me@mini")), "me@mini")
        self.assertEqual(label(M("rig", "guest@mini")), "guest@mini")
        self.assertEqual(label(M("vps", "me@10.0.0.7:2222")), "me@10.0.0.7")  # the port is left out
        self.assertEqual(label(M("v6", "me@[fe80::1]:22")), "me@[fe80::1]")
        self.assertEqual(label(M("vps", "vps")), "vps")  # no user: as hc gives it
        self.assertEqual(label(M("box", "box.example.com:2222")), "box.example.com:2222")
        self.assertEqual(label(M("fly", "fly ssh console -a app -C", via=True)), "fly")  # a command: the name
        for odd in ("", "   ", "a b@c", "me@host\x1b[2J", "@host", "me@"):
            self.assertIn(label(M("x", odd)), ("x", odd.strip()), repr(odd))
        self.assertEqual(label(M("x", "me@host\x1b[2J")), "x")  # never a control character on screen

    def test_the_laptops_servers_and_the_home_row(self):
        terms = hcgui.parse(ls(*self.TERMS))
        machines = hcgui.parse_machines(self.hc("machine", "ls", "--json"))
        spaces, rigs = hcgui.build_groups(terms, "mini", {}, machines)
        self.assertEqual([(g.key, g.shown, g.home, len(g.terms)) for g in rigs],
                         [("rig:mini", "me@mini", True, 3), ("rig:rig", "guest@mini", False, 1)])
        self.assertEqual([g.name for g in spaces], ["atlas", "tracker"])
        _, rigs = hcgui.build_groups(terms, "mini", {}, machines, {"rig:rig": "Harry"})
        self.assertEqual([g.shown for g in rigs], ["me@mini", "Harry"])  # names.json wins
        self.assertEqual([g.own for g in rigs], ["me@mini", "guest@mini"])
        _, rigs = hcgui.build_groups(terms, "mini", {}, [hcgui.Machine("mini", "mini"), "rig"])
        self.assertEqual([g.shown for g in rigs], ["mini", "rig"])  # a bare Host, or no target known: the name
        # this Mac only while it runs terminals; the home machine's agents are listed once, under their spaces
        self.assertNotIn("rig:" + hcgui.LOCAL, [g.key for g in rigs])
        items = hcgui.selectable_items(spaces, rigs)
        self.assertEqual([i.address for i in items if i.kind == "agent"], ["mini/t1", "mini/t2", "rig/t1"])

    # hidden by default -----------------------------------------------------------------------------------------
    def test_hidden_by_default_then_v_shows_them(self):
        lines = self.scr.lines()
        self.assertFalse((self.state / "servers").exists())
        self.assertFalse(self.side.servers_shown())
        self.assertEqual(lines[:5], [" spaces", hcgui.glyph("›● atlas"), hcgui.glyph(" ● tracker"), " + new space", ""])
        text = "\n".join(lines)
        for gone in ("servers", "me@mini", "guest@mini", "add server", "harry"):
            self.assertNotIn(gone, text)
        self.assertEqual(self.side.groups()[1], [])
        self.key("v")
        lines = self.scr.lines()
        self.assertEqual(hcgui.read_text(self.state / "servers"), "shown")
        self.assertEqual(lines[4:10], ["", " servers", hcgui.glyph(" ● me@mini"),
                                       hcgui.glyph(" ● guest@mini"), " + add server", ""])
        # the server's agents come back: its only one on its row alone (no "guest@mini · 1", no server name)
        self.assertIn(hcgui.glyph("  ● harry³"), lines)  # no status word: the dot says it
        self.assertEqual(self.side.cursor, hcgui.Item("group", "rig:mini", ""))
        self.assertEqual(self.side.notice.current(), "servers shown (v hides them)")
        self.key("V")
        self.assertEqual(hcgui.read_text(self.state / "servers"), "hidden")
        self.assertNotIn("servers", "\n".join(self.scr.lines()[:-2]))

    def test_the_switch_in_every_menu_and_for_every_window(self):
        for item in (hcgui.Item("group", "space:atlas", ""), hcgui.Item("agent", "space:atlas", "mini/t1"),
                     hcgui.NEW_SPACE):
            self.go(item)
            self.key("a")
            self.assertEqual(self.side.menu.entries[-1].label, "Show servers", item)  # hidden: in every menu
            self.key(27)
        self.key("a", "v")  # its letter in the menu
        self.assertTrue(self.side.servers_shown())
        other = hcgui.Sidebar(FakeScr(24, 30), self.state, self.state / "w-2")  # another window
        other.refresh_once()
        self.assertEqual([g.key for g in other.groups()[1]], ["rig:mini", "rig:rig"])
        self.go(hcgui.ADD_RIG)
        self.key("a")
        self.assertEqual([e.label for e in self.side.menu.entries],
                         ["Add server", "Hide servers"])
        self.key("j", 10)
        self.assertFalse(self.side.servers_shown())
        self.assertEqual(other.groups()[1], [])  # the other window follows the shared file

    def test_hiding_while_a_server_is_current_falls_back(self):
        self.key("v")
        self.go(hcgui.Item("group", "rig:rig", ""))
        with mock.patch.object(hcgui, "focus_view"):
            self.key(10)
        self.assertEqual((self.side.cur, hcgui.current_target(self.win)), ("rig:rig", "rig/t1"))
        self.key("v")
        # the first space with an agent, and its terminal: nothing on screen could reach rig/t1 any more
        self.assertEqual((self.side.cur, hcgui.current_target(self.win)), ("space:atlas", "mini/t1"))
        self.assertEqual(hcgui.read_snapshot(self.win)["group"], "space:atlas")
        self.assertEqual(self.side.cursor_item(), hcgui.Item("group", "space:atlas", ""))

    def test_hiding_keeps_a_space_terminal_shown_from_the_home_row(self):
        self.key("v")
        self.go(hcgui.Item("group", "rig:mini", ""))
        with mock.patch.object(hcgui, "focus_view"):
            self.key(10)
        snap = hcgui.read_snapshot(self.win)
        self.assertEqual(snap["title"], "me@mini")
        self.assertEqual([t["label"] for t in snap["tabs"]], ["atlas", "sh", "tracker"])  # the whole machine
        hcgui.show("mini/t3", self.win)  # the tab bar picks "sh" (space tracker)
        self.side.sync()
        self.assertEqual(self.side.cur, "rig:mini")  # the row stays current
        self.assertEqual(hcgui.read_last(self.state)["rig:mini"], "mini/t3")  # and remembers it
        self.key("v")
        self.assertEqual((self.side.cur, hcgui.current_target(self.win)), ("space:tracker", "mini/t3"))

    def test_hidden_in_another_window_falls_back_at_the_next_sync(self):
        self.key("v")
        self.go(hcgui.Item("group", "rig:rig", ""))
        with mock.patch.object(hcgui, "focus_view"):
            self.key(10)
        hcgui.write_servers_shown(False, self.state)  # another window's v
        self.side.sync()
        self.assertEqual(self.side.cur, "space:atlas")  # the usual fall-back rule; that window's view is its own

    def test_the_home_row_menu_and_keys(self):
        self.key("v")
        home = hcgui.Item("group", "rig:mini", "")
        self.go(home)
        self.key("a")
        self.assertEqual([e.label for e in self.side.menu.entries],
                         ["Open", "New terminal here", "Rename", "Hide servers"])  # never Forget
        self.key(27, "d")
        self.assertEqual(self.side.notice.current(), "d: me@mini cannot be removed")
        self.assertIsNone(self.side.prompt)
        self.key("e")
        self.assertEqual((self.side.prompt.title, self.side.prompt.text), ("rename me@mini to:", "me@mini"))
        self.key(21)
        self.type("Mini")
        self.assertEqual(hcgui.read_names(self.state), {"rig:mini": "Mini"})
        self.assertIn(hcgui.glyph(" ● Mini"), self.scr.lines())
        self.go(home)
        self.key("e", 21)
        self.type("me@mini")  # its own user@host removes the rename
        self.assertEqual(hcgui.read_names(self.state), {})
        agents = [line for line in self.scr.lines() if line[1:].startswith(hcgui.glyph(" ● atlas"))]  # agent rows
        self.assertEqual(len(agents), 1)  # listed once, under its space
        self.go(home)
        self.key("n")
        self.assertEqual([c for c in self.hc.calls if c[0] == "run"][-1][:6],
                         ("run", "--bg", "--json", "--no-parent", "--on", "mini"))
        self.assertEqual(self.side.cur, "rig:mini")  # the new shell is shown in the row it was started from

    def test_forget_a_server_by_its_user_at_host(self):
        self.key("v")
        self.go(hcgui.Item("group", "rig:rig", ""))
        self.key("d")
        p = self.side.prompt
        self.assertEqual((p.title, p.ask), ("forget server guest@mini? its terminals keep running there.",
                                            "type guest@mini to confirm:"))
        self.type("guest@mini")
        self.assertIn(("machine", "rm", "rig"), self.hc.calls)
        self.assertEqual([g.key for g in self.side.groups()[1]], ["rig:mini"])

    def test_no_user_facing_rig_word(self):
        self.key("v")
        drawn = []
        for item in self.side.items():
            self.go(item)
            self.key("a")
            drawn += self.scr.lines()
            self.key(27)
        for item in (hcgui.ADD_RIG, hcgui.Item("group", "space:atlas", ""), hcgui.Item("group", "rig:rig", "")):
            self.go(item)
            self.key("e", 27, "d", 27, "m", 27)
            drawn += self.scr.lines() + [self.side.notice.current()]
        self.assertIsNone(re.search(r"\brigs?\b", "\n".join(drawn)), "\n".join(drawn))
        # every text hcgui.py says (notices, prompts, menu labels, the add terminal's lines), from its source
        said = re.findall(r'(?:say|Prompt|Entry|echo)\(?[^\n]*?"([^"\n]*)"', (ROOT / "hcgui.py").read_text())
        self.assertTrue(said)
        self.assertEqual([t for t in said if re.search(r"\brigs?\b", t) and not t.startswith(("rig_", "rig:"))], [])


class PublicCopyTests(unittest.TestCase):
    """The public copy (`git archive`) ships tests/ but not INTERNAL.md: its suite must pass all the same."""

    def test_only_tests_skipped_without_the_notes_read_them(self):
        tree = ast.parse(Path(__file__).read_text())

        def skipped(node: ast.AST) -> bool:
            return any(isinstance(d, ast.Name) and d.id == "skip_without_notes"
                       for d in getattr(node, "decorator_list", []))

        def check(node: ast.AST, inside: bool) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.ClassDef, ast.FunctionDef)):
                    reads = any(isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "NOTES"
                                and n.attr in ("read_text", "read_bytes", "open") for n in ast.walk(child))
                    if isinstance(child, ast.FunctionDef) and reads:
                        self.assertTrue(inside or skipped(child), child.name)
                    check(child, inside or skipped(child))

        check(tree, False)
        named = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == NOTES.name]
        self.assertEqual(len(named), 1)  # only in NOTES: no test reaches the notes another way


class HelpTests(unittest.TestCase):
    """"?": the list of keys over the sidebar, closed by any key or click; the dim "?" on the last line."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"
        self.hc = FakeHc(SidebarLogicTests.TERMS)
        for target, value in ((hcgui, {"run_hc": self.hc}), (hcgui.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scr = FakeScr(24, 30)
        seen_done(self.state, self.hc.terms)
        self.side = hcgui.Sidebar(self.scr, self.state, self.win)
        self.side.refresh_once()
        self.side.sync()
        self.side.draw()

    def key(self, *keys):
        for k in keys:
            self.side.on_key(ord(k) if isinstance(k, str) else k)
            self.side.sync()
            self.side.draw()

    def click(self, x, y, button=1):
        self.side.mouse_quiet = 0.0
        with pressed(x, y, button):
            self.key(hcgui.curses.KEY_MOUSE)

    def test_the_status_dots_are_drawn_in_their_colours(self):
        self.scr.height = 60  # tall enough for the whole list
        self.key("?")
        lines = self.scr.lines()
        self.assertEqual(lines[:len(hcgui.help_lines(29, 60))], hcgui.help_lines(29, 60))
        at = lines.index(" status dots")
        self.assertEqual(self.scr.cells[(at, 1)][1], hcgui.curses.A_DIM)
        dim = hcgui.curses.A_DIM
        for i, (pair, word) in enumerate(((1, "red"), (3, "yellow"), (2, "green"), (4, "blue"), (0, "grey"))):
            y = at + 1 + i
            attr = pair << 8 if pair else dim  # as dot_attr: the colour pair, or dim for no status
            self.assertEqual(self.scr.cells[(y, 1)][1], attr, word)  # the dot
            self.assertEqual({self.scr.cells[(y, x)][1] for x in range(9, 9 + len(word))}, {attr}, word)
            self.assertEqual(self.scr.cells[(y, 9 + len(word))], (":", 0), word)  # the rest plain
            self.assertEqual(self.scr.cells[(y, 9 + len(word) + 2)][1], 0, word)
        self.assertEqual(lines[at + 6], " spaces, servers: most urgent")
        self.assertEqual(self.scr.cells[(at + 6, 1)][1], dim)
        self.assertEqual(self.scr.cells[(1, 1)][1], 0)  # a key line: plain
        self.key("j")
        self.assertFalse(self.side.help)

    def test_the_readme_says_the_same_as_the_list(self):
        # README's table names every colour, every status and the most urgent rule; its keys table has u (the public
        # copy has README, so this runs there too)
        readme = (ROOT / "README.md").read_text()
        dots = readme[readme.index("## Status dots"):]
        dots = dots[:dots.index("\n## ")]
        for status, _, word, _ in hcgui.DOT_HELP:
            self.assertIn(f"| {word}", dots)
            if status:
                self.assertIn(f"`{status}`", dots)
        self.assertIn("`error`", dots)
        self.assertIn("most urgent", dots)
        # a plain shell with no status is no agent row (Term.is_agent): its dot shows on its tab only
        self.assertNotIn("Every terminal has a dot", dots)
        self.assertIn("every agent in the sidebar", dots)
        keys = readme[readme.index("## Keys"):readme.index("## Status dots")]
        self.assertIn("| u, right click on a usage line | Show or hide the 5-hour usage lines", keys)
        self.assertIn("then what the status dots mean", keys)

    @skip_without_notes
    def test_the_notes_say_the_same_as_the_list(self):
        # INTERNAL.md's block is what the list draws at the default width
        notes = NOTES.read_text()
        section = notes[notes.index("## Status dots"):]
        block = next(b for b in section.split("\n\n") if all(line.startswith("    ") for line in b.splitlines()))
        self.assertEqual([" " + line[4:] for line in block.splitlines()], hcgui.help_lines(29, 60)[-7:])

    def test_question_mark_shows_the_list_and_any_key_closes_it_without_acting(self):
        self.assertEqual(self.scr.line(23), fold_line("open"))
        self.assertEqual(self.side.help_x, 28)
        self.key("?")
        lines = self.scr.lines()
        self.assertEqual(lines[:len(hcgui.help_lines(29, 24))], hcgui.help_lines(29, 24))
        self.assertEqual(self.side.rows, {})  # nothing under it can be clicked
        cursor = self.side.cursor
        self.key("j")  # closes, does not move
        self.assertFalse(self.side.help)
        self.assertEqual(self.side.cursor, cursor)
        self.assertEqual(self.scr.line(0), " spaces")
        self.key("?", "q")  # q closes the list, it does not hide the sidebar
        self.assertFalse(self.side.help)
        self.assertEqual(hcgui.read_sidebar_state(self.state), "open")
        self.key("?", hcgui.curses.KEY_RESIZE)  # a size change is no key
        self.assertTrue(self.side.help)

    def test_a_click_on_the_dim_question_mark_opens_it_and_a_click_closes_it(self):
        self.click(27, 23)  # the "‹" line beside the "?": c's step, as before
        self.assertEqual(self.side.mode, "strip")
        self.key("o")
        self.click(self.side.help_x, 23)
        self.assertTrue(self.side.help)
        self.assertEqual(self.side.mode, "open")
        with pressed(self.side.help_x, 23, 1):
            self.key(hcgui.curses.KEY_MOUSE)  # a double click's second press: it stays open
        self.assertTrue(self.side.help)
        with mouse_at(0, 0, RELEASE1):
            self.side.mouse_quiet = 0.0
            self.key(hcgui.curses.KEY_MOUSE)  # a button let go: no click
        self.assertTrue(self.side.help)
        target = hcgui.current_target(self.win)
        self.click(5, 2)  # on a row under the list: closes it, opens nothing
        self.assertFalse(self.side.help)
        self.assertEqual(hcgui.current_target(self.win), target)

    def test_in_the_strip_it_opens_the_sidebar_first_and_draws_no_question_mark(self):
        self.key("c")
        self.assertEqual(self.side.help_x, -1)
        self.assertNotIn("?", self.scr.line(23))
        self.key("?")
        self.assertEqual((self.side.mode, self.side.help), ("open", True))

    def test_the_question_mark_needs_room_beside_the_label(self):
        self.assertEqual(hcgui.help_column(" ‹ fold", 30), 28)
        self.assertEqual(hcgui.help_column(" ‹ fold", 10), 8)
        self.assertEqual(hcgui.help_column(" ‹ fold", 9), -1)  # it would touch the word
        self.assertEqual(hcgui.sidebar_hit(23, 23, -1, {}, 28, 28), ("help", None))
        self.assertEqual(hcgui.sidebar_hit(23, 23, -1, {}, 27, 28), ("step", None))
        self.assertEqual(hcgui.sidebar_hit(23, 23, -1, {}, 28, -1), ("step", None))

    def test_small_panes_do_not_crash(self):
        for height in range(0, 8):
            for width in (1, 2, 5, 12, 30):
                self.scr.height, self.scr.width = height, width
                self.side.help = True
                self.side.draw()
                self.assertTrue(all(len(line) <= max(0, width - 1) for line in self.scr.lines()))

    def test_tab_bar_question_mark_says_its_keys(self):
        bar = hcgui.TabBar(FakeScr(5, 120), self.win, self.state)
        bar.handle_key(ord("?"), None, "")
        keys = ("←→ h l switch · enter ↓ focus · a, ⇧F10 or right click: menu (←→ enter) · z zoom (a click on the top "
                "line ends it)")
        self.assertEqual(bar.notice.current(), "keys: " + keys)
        bar.alone = True
        bar.handle_key(ord("?"), None, "")
        self.assertEqual(bar.notice.current(), "keys: c o sidebar · " + keys)
        self.assertEqual(hcgui.TAB_HINTS_ALONE[0], "c sidebar  ←→ switch  enter focus  a menu  z zoom")


class DragTests(unittest.TestCase):
    """A dragged divider is kept; a resized window is not (the sidebar sizes itself again)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"
        self.hc = FakeHc(SidebarLogicTests.TERMS)
        for target, value in ((hcgui, {"run_hc": self.hc}), (hcgui.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scr = FakeScr(24, 60)
        self.tm = FakeTmux(self.scr).install(self)
        seen_done(self.state, self.hc.terms)
        self.side = hcgui.Sidebar(self.scr, self.state, self.win)
        self.side.refresh_once()
        self.side.refit()  # as run()'s first round does

    def drag(self, *widths):
        """The divider dragged through `widths`: tmux resized the pane at each step, the window kept its width."""
        for width in widths:
            self.tm.drag(width)
            self.side.refit()

    def resize(self, width, window):
        """The window resized to `window` columns: tmux spread it over the panes, the sidebar first."""
        self.tm.resize(width, window)
        self.side.refit()

    def test_a_drag_is_kept_at_every_step_and_remembered_a_window_change_is_not(self):
        self.assertEqual(self.tm.sizes(), [30])
        self.drag(31, 33, 38, 45)  # a slow drag: every step seen, none snapped back (the drag would die)
        self.assertEqual(self.tm.sizes(), [30])
        self.assertEqual((self.side.open_width, self.side.width_goal()), (45, 45))
        self.assertEqual(hcgui.read_text(self.state / "width"), "45")
        self.side.refit()
        self.assertEqual(self.tm.sizes(), [30])  # and not later either
        self.resize(90, 200)  # the window grew: back to the dragged width
        self.assertEqual(self.tm.sizes(), [30, 45])
        again = hcgui.Sidebar(FakeScr(24, 30), self.state, self.state / "w-2")  # the next window
        self.assertEqual(again.width_goal(), 45)

    def test_a_late_curses_width_is_no_drag(self):
        """tmux holds a pane's next size signal up to 250 ms: curses may still show the old width (review finding)."""
        self.tm.lag = True
        self.side.on_key(ord("c"))
        self.side.on_key(ord("o"))  # quickly: curses still shows 30, tmux has 6, then 30
        for _ in range(3):
            self.side.refit()
        self.tm.settle()
        self.side.refit()
        self.assertEqual((self.side.mode, self.tm.pane_w, self.scr.width), ("open", 30, 30))
        self.assertFalse((self.state / "width").exists())  # nobody dragged
        self.tm.lag = False
        self.resize(38, 160)  # a live resize: a step of it seen late by curses
        self.tm.lag = True
        self.tm.width, self.scr.width = 170, 44
        self.side.refit()
        self.tm.settle()
        self.side.refit()
        self.assertEqual(self.tm.pane_w, 30)
        self.assertFalse((self.state / "width").exists())

    def test_the_view_keeps_room_in_a_narrow_window(self):
        self.drag(90)
        self.resize(60, 70)  # a narrow window: the dragged 90 would leave the view nothing
        self.assertEqual(self.tm.sizes()[-1], 70 - 1 - hcgui.MIN_VIEW)
        self.assertEqual(hcgui.read_text(self.state / "width"), "90")  # kept for wide windows
        self.resize(100, 200)
        self.assertEqual(self.tm.sizes()[-1], 90)

    def test_a_drag_past_the_limits_is_set_to_the_limit_at_once(self):
        self.drag(5)
        self.side.refit()
        self.assertEqual((self.tm.sizes()[-1], self.side.open_width), (10, 10))

    def test_a_width_only_window_change_after_a_drag_is_no_drag(self):
        self.drag(40)
        self.resize(70, 160)  # maximised: wider only
        self.assertEqual(self.tm.sizes(), [30, 40])
        self.assertEqual(hcgui.read_text(self.state / "width"), "40")

    def test_a_dragged_strip_lasts_until_the_next_state_change(self):
        self.side.on_key(ord("c"))
        self.assertEqual(self.tm.sizes()[-1], hcgui.NARROW)
        self.drag(20)
        self.assertEqual((self.side.width_goal(), self.tm.sizes()[-1]), (20, hcgui.NARROW))
        self.assertFalse((self.state / "width").exists())  # only an open width is kept for later
        self.side.on_key(ord("o"))
        self.assertEqual((self.side.strip_width, self.tm.sizes()[-1]), (0, 30))
        self.side.on_key(ord("c"))
        self.assertEqual(self.tm.sizes()[-1], hcgui.NARROW)

    def test_the_open_width_file(self):
        self.assertEqual(hcgui.read_open_width(self.state), hcgui.WIDTH)
        for junk in ("", "x", "9", "201", "-5", "3.5"):
            hcgui.write_atomic(self.state / "width", junk + "\n")
            self.assertEqual(hcgui.read_open_width(self.state), hcgui.WIDTH, junk)
        self.assertEqual(hcgui.write_open_width(5, self.state), 10)
        self.assertEqual(hcgui.read_open_width(self.state), 10)
        self.assertEqual(hcgui.write_open_width(44, self.state), 44)
        self.assertEqual(hcgui.read_open_width(self.state), 44)
        self.side.on_key(ord("c"))
        self.side.on_key(ord("o"))  # dragged in another window meanwhile: the next open takes it
        self.assertEqual(self.tm.sizes()[-1], 44)

    def test_the_tab_bar_keeps_its_rows(self):
        scr = FakeScr(9, 90)
        tm = FakeTmux(scr, pane="%2").install(self)
        bar = hcgui.TabBar(scr, self.win, self.state)
        bar.refit()
        self.assertEqual((tm.sizes("-y"), scr.height), ([hcgui.TAB_ROWS], hcgui.TAB_ROWS))
        bar.refit()
        self.assertEqual(tm.sizes("-y"), [hcgui.TAB_ROWS])  # on its rows: no tmux call
        scr.height = tm.pane_h = 6  # its line dragged, or the window resized: back to its rows
        bar.refit()
        self.assertEqual(tm.sizes("-y"), [hcgui.TAB_ROWS, hcgui.TAB_ROWS])
        scr.height, tm.pane_h, tm.zoomed = 8, 8, True
        bar.refit()
        self.assertEqual(len(tm.sizes("-y")), 2)  # never while zoomed


class PaneTitleTests(unittest.TestCase):
    """The title "mini" and no folder icon: OSC 2, then an empty OSC 7, from all three panes."""

    def test_the_sequence(self):
        self.assertEqual(hcgui.PANE_TITLE, "\x1b]2;hcGUI\x07\x1b]7;\x07")

    def test_claim_pane_writes_only_to_a_terminal(self):
        import pty
        master, slave = pty.openpty()
        try:
            hcgui.claim_pane(slave)
            self.assertEqual(os.read(master, 100), hcgui.PANE_TITLE.encode())
        finally:
            os.close(master)
            os.close(slave)
        r, w = os.pipe()
        try:
            hcgui.claim_pane(w)  # not a terminal: nothing
            os.close(w)
            self.assertEqual(os.read(r, 100), b"")
        finally:
            os.close(r)
        hcgui.claim_pane(9999)  # a closed descriptor: no error

    def test_view_sh_sends_it_at_start_and_before_and_after_each_attach(self):
        text = (ROOT / "view.sh").read_text()
        own = text[text.index("own_title() {"):text.index("}", text.index("own_title() {"))]
        self.assertEqual(own.split("\n")[1:3], ['  set_title "$1"', "  printf '\\033]7;\\007'"])  # OSC 2 first
        self.assertIn("tt=hcGUI", text)  # nothing shown: "hcGUI"
        body = text[text.index("clean_screen() {"):text.index("}", text.index("clean_screen() {"))]
        self.assertIn('own_title "$target"', body)
        self.assertIn('[ "$on_tty" = 1 ] && own_title "$target"', text)
        loop = text[text.index("while :; do\n  read_gen"):]
        self.assertLess(loop.index('own_title "$target"'), loop.index('"$hc" attach'))


OSC_RE = re.compile(rb"\x1b\](\d+);(.*?)\x07", re.DOTALL)


def ghostty_title(stream, title=b"", seen=False, pwd=b""):
    """The title Ghostty 1.3 shows after `stream` (bytes), per its stream_handler: windowTitle ignores a title of
    256 bytes or more; an empty title means "no title seen" (the pwd is shown); an empty OSC 7 forgets the pwd and,
    only while no title was seen, clears the title; a pwd is the title while no title was seen."""
    for code, value in OSC_RE.findall(stream):
        if code == b"2":
            if len(value) >= 256:
                continue
            title, seen = (value, True) if value else (pwd, False)
        elif code == b"7":
            if not value:
                pwd = b""
                if not seen:
                    title = b""
            else:
                pwd = value
                if not seen:
                    title = value
    return title.decode("utf-8"), seen


TITLE_STUB = STUB_HC.replace('echo "start $2" >>"$STUB_LOG"', 'echo "start $2" >>"$STUB_LOG"; echo "ATTACH $2"')


class WindowTitleTests(unittest.TestCase):
    """The window title "<shown terminal> · <server>": the text, the file view.sh reads, the snapshot, sending only
    on a change, and the order of the escapes."""

    TERMS = ServerTests.TERMS + [term("t9", "/Users/me", "zsh", None)]  # an unnamed terminal of this Mac
    MACHINES = ServerTests.MACHINES

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"
        self.hc = FakeHc(self.TERMS, machines=self.MACHINES)
        for target, value in ((hcgui, {"run_hc": self.hc, "FIRST": "mini"}),
                              (hcgui.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def sidebar(self):
        side = hcgui.Sidebar(FakeScr(24, 30), self.state, self.win)
        side.refresh_once()
        side.sync()
        return side

    def title_file(self):
        return (self.win / "title").read_text(encoding="utf-8").split("\n")[:2]

    # the text ----------------------------------------------------------------------------------------------------
    def test_three_examples(self):
        parsed = hcgui.parse(json.dumps({"terminals": self.TERMS}))
        machines = [hcgui.Machine(n, t) for n, t in self.MACHINES]
        title = hcgui.shown_title
        self.assertEqual(title("mini/t2", parsed, machines), "tracker · me@mini")
        self.assertEqual(title("rig/t1", parsed, machines), "harry · guest@mini")
        self.assertEqual(title("t9", parsed, machines), "t9 · this Mac")  # no hc name: its id
        self.assertEqual(title("", parsed, machines), "hcGUI")  # nothing shown

    def test_display_names_win(self):
        parsed = hcgui.parse(json.dumps({"terminals": self.TERMS}))
        machines = [hcgui.Machine(n, t) for n, t in self.MACHINES]
        names = {"term:mini/t2": "Bot", "rig:rig": "Harry", "rig:mini": "Mini", "rig:this Mac": "Laptop"}
        self.assertEqual(hcgui.shown_title("mini/t2", parsed, machines, names), "Bot · Mini")
        self.assertEqual(hcgui.shown_title("rig/t1", parsed, machines, names), "harry · Harry")
        self.assertEqual(hcgui.shown_title("t9", parsed, machines, names), "t9 · Laptop")
        # the same server names as the server rows draw them
        _, rigs = hcgui.build_groups(parsed, "mini", None, machines, names)
        for g in rigs:
            self.assertEqual(hcgui.server_name(g.machine, machines, names), g.shown)
        _, rigs = hcgui.build_groups(parsed, "mini", None, machines)
        for g in rigs:
            self.assertEqual(hcgui.server_name(g.machine, machines), g.shown)

    def test_servers_without_ssh_user_via_or_unknown(self):
        M = hcgui.Machine
        self.assertEqual(hcgui.server_name("vps", [M("vps", "vps")]), "vps")  # a Host of ~/.ssh/config
        self.assertEqual(hcgui.server_name("box", [M("box", "ssh -J x box", True)]), "box")  # via: the hc name
        self.assertEqual(hcgui.server_name("gone", []), "gone")  # not in hc machine ls: the hc name
        self.assertEqual(hcgui.server_name(hcgui.LOCAL, []), "this Mac")
        self.assertEqual(hcgui.shown_title("box/t3", [], [M("box", "me@box.lan:2222")]), "t3 · me@box.lan")

    def test_unprintable_and_long_names(self):
        wt = hcgui.window_title
        for evil in ("a\x1b]2;owned\x07b", "a\nb", "a\x9bb", "a\u202eb", "a\u00a0b", "a\tb", "a\x00b", "a\rb"):
            text = wt(evil, "srv\x1b\x07")
            self.assertTrue(text.isprintable(), repr(text))
            self.assertNotIn("\x1b", text)
            self.assertTrue(text.startswith("a "), repr(text))
            self.assertTrue(text.endswith(" · srv"), repr(text))
        self.assertEqual(wt("\x1b\x07", "\n"), "hcGUI")  # nothing printable left: as when nothing is shown
        self.assertEqual(wt("  web  ", ""), "web")
        self.assertEqual(wt("", "me@mini"), "me@mini")
        long = wt("x" * 200, "me@mini")
        self.assertLessEqual(len(long), hcgui.TITLE_MAX)
        self.assertTrue(long.endswith("x… · me@mini"))  # the server stays whole
        both = wt("x" * 200, "y" * 200)
        self.assertEqual(len(both), hcgui.TITLE_MAX)
        self.assertIn("… · y", both)
        self.assertTrue(both.endswith("y…"))
        short = wt("web", "y" * 200)
        self.assertTrue(short.startswith("web · y") and len(short) == hcgui.TITLE_MAX)  # a short name leaves room
        wide = wt("\U0001d4d0" * 100, "\U0001d4d1" * 100)  # 4 bytes each in UTF-8
        self.assertLess(len(wide.encode()), 256)  # Ghostty ignores a title of 256 bytes or more
        self.assertLessEqual(len(wide.encode()), hcgui.TITLE_BYTES)
        self.assertIn(" · ", wide)

    def test_the_escape_is_osc_2_with_a_clean_title(self):
        self.assertEqual(hcgui.title_escape("tracker · me@mini"),
                         "\x1b]2;tracker · me@mini\x07".encode())
        self.assertEqual(hcgui.title_escape("a\x07\x1b]7;b"), b"\x1b]2;a ]7;b\x07")
        self.assertEqual(hcgui.title_escape(""), b"\x1b]2;hcGUI\x07")

    # sending -----------------------------------------------------------------------------------------------------
    def test_sent_only_when_it_changes_and_never_followed_by_osc_7(self):
        import pty
        master, slave = pty.openpty()
        try:
            hcgui.claim_pane(slave)
            pane = hcgui.PaneTitle(slave)
            self.assertFalse(pane.send("hcGUI"))  # what claim_pane sent: nothing again
            self.assertTrue(pane.send("tracker · me@mini"))
            self.assertFalse(pane.send("tracker · me@mini"))  # every frame: once only
            self.assertFalse(pane.send(None))  # not known: the title stays
            self.assertTrue(pane.send("harry · guest@mini"))
            out = os.read(master, 1000)
        finally:
            os.close(master)
            os.close(slave)
        self.assertEqual(out, (hcgui.PANE_TITLE + "\x1b]2;tracker · me@mini\x07"
                               "\x1b]2;harry · guest@mini\x07").encode())
        codes = [c for c, _ in OSC_RE.findall(out)]
        self.assertEqual(codes, [b"2", b"7", b"2", b"2"])  # the one OSC 7 only at the start, after a title
        # Ghostty, starting from the login shell's folder as the title (no title seen): the last title wins
        self.assertEqual(ghostty_title(out, b"/Users/me", False, b"/Users/me"), ("harry · guest@mini", True))
        r, w = os.pipe()
        try:
            self.assertFalse(hcgui.PaneTitle(w).send("x"))  # not a terminal: nothing written
            os.close(w)
            self.assertEqual(os.read(r, 100), b"")
        finally:
            os.close(r)
        self.assertFalse(hcgui.PaneTitle(9999).send("x"))  # a closed descriptor: no error

    def test_the_ghostty_model_shows_why_the_title_goes_first(self):
        self.assertEqual(ghostty_title(b"\x1b]7;\x07\x1b]2;web\x07", b"/home", False, b"/home")[0], "web")
        self.assertEqual(ghostty_title(b"\x1b]2;web\x07\x1b]7;\x07", b"/home", False, b"/home")[0], "web")
        self.assertEqual(ghostty_title(b"\x1b]2;" + b"x" * 256 + b"\x07\x1b]7;\x07", b"/home", False, b"/home")[0],
                         "")  # an ignored (too long) title, then an empty OSC 7: no title at all

    # the engine: file, snapshot, hidden servers ------------------------------------------------------------------
    def test_the_engine_writes_the_title_file_and_the_snapshot(self):
        side = self.sidebar()
        self.assertEqual(self.title_file(), ["", "hcGUI"])
        hcgui.write_servers_shown(False, self.state)  # hidden: changes nothing about the title
        for address, title in (("mini/t2", "tracker · me@mini"), ("rig/t1", "harry · guest@mini"),
                               ("t9", "t9 · this Mac")):
            hcgui.write_atomic(self.win / "target", address + "\n")
            side.sync()
            self.assertEqual(side.title, title)
            self.assertEqual(self.title_file(), [address, title])
            snap = hcgui.read_snapshot(self.win)
            self.assertEqual((snap["shown"], snap["shown_title"]), (address, title))
            self.assertEqual(hcgui.tabs_title(snap, address), title)
        hcgui.write_servers_shown(True, self.state)
        side.sync()
        self.assertEqual(side.title, "t9 · this Mac")
        hcgui.write_atomic(self.state / "names.json", json.dumps({"term:t9": "Notes", "rig:this Mac": "Laptop"}))
        side.sync()
        self.assertEqual(self.title_file(), ["t9", "Notes · Laptop"])  # a rename counts at once

    def test_the_title_file_is_written_only_on_a_change(self):
        side = self.sidebar()
        hcgui.write_atomic(self.win / "target", "mini/t2\n")
        with mock.patch.object(hcgui, "write_title", wraps=hcgui.write_title) as wrote:
            for _ in range(5):
                side.sync()
            self.assertEqual(wrote.call_count, 1)
            hcgui.write_atomic(self.win / "target", "mini/t1\n")
            side.sync()
            side.sync()
            self.assertEqual(wrote.call_count, 2)

    def test_show_group_writes_the_title_before_the_target(self):
        side = self.sidebar()
        hcgui.write_servers_shown(True, self.state)
        order = []
        real = hcgui.write_atomic

        def spy(path, text, encoding=None):
            order.append(path.name)
            real(path, text, encoding)

        with mock.patch.object(hcgui, "write_atomic", spy):
            side.show_group("rig:rig")
        self.assertLess(order.index("title"), order.index("target"))
        self.assertEqual(self.title_file(), ["rig/t1", "harry · guest@mini"])

    def test_tab_bar_titles_from_the_snapshot_alone(self):
        side = self.sidebar()
        hcgui.write_servers_shown(True, self.state)
        side.show_group("space:tracker", "mini/t2")
        snap = hcgui.read_snapshot(self.win)
        self.assertEqual(snap["server"], "me@mini")
        self.assertEqual([t["server"] for t in snap["tabs"]], ["me@mini", "me@mini"])
        self.assertEqual(hcgui.tabs_title(snap, "mini/t3"), "sh · me@mini")  # a tab: from its label
        self.assertEqual(hcgui.tabs_title(snap, ""), "hcGUI")
        self.assertIsNone(hcgui.tabs_title(None, "mini/t2"))  # no snapshot yet: the title stays
        self.assertIsNone(hcgui.tabs_title(snap, "rig/t1"))  # neither shown when written nor a tab: stays
        # the tab bar's picks write the title before the target, like the sidebar's
        bar = hcgui.TabBar(FakeScr(5, 60), self.win, self.state)
        bar.step(snap, "mini/t2", -1)  # tabs: sh, tracker
        self.assertEqual(self.title_file(), ["mini/t3", "sh · me@mini"])
        new = json.dumps({"address": "t44"})
        bar.last_plus = -10.0  # time.monotonic() starts near 0 in a new process
        with mock.patch.object(hcgui, "run_hc", lambda *a, **k: new):
            bar.plus({**snap, "server": "this Mac", "machine": hcgui.LOCAL})
        self.assertEqual(self.title_file(), ["t44", "t44 · this Mac"])

    def test_the_tab_bars_own_engine_gives_the_same_title(self):
        """Sidebar hidden: the tab bar's engine writes the file and the snapshot; servers stay hidden."""
        hcgui.write_atomic(self.state / "group", "space:tracker\n")
        hcgui.write_last({"space:tracker": "mini/t2"}, self.state)
        hcgui.write_sidebar_state("hidden", self.state)
        bar = hcgui.TabBar(FakeScr(5, 60), self.win, self.state)
        self.addCleanup(bar.stop_engine)
        bar.watch_sidebar(100.0)
        self.assertTrue(bar.alone)
        self.assertTrue(wait_for(lambda: (self.win / "title").exists() and self.title_file()[0] == "mini/t2"))
        self.assertEqual(self.title_file(), ["mini/t2", "tracker · me@mini"])
        self.assertTrue(wait_for(lambda: (hcgui.read_snapshot(self.win) or {}).get("shown") == "mini/t2"))
        snap = hcgui.read_snapshot(self.win)
        self.assertFalse(hcgui.read_servers_shown(self.state))
        self.assertEqual(hcgui.tabs_title(snap, "mini/t2"), "tracker · me@mini")
        hcgui.show("rig/t1", self.win)  # a terminal of a hidden server: still named by its server
        self.assertTrue(wait_for(lambda: self.title_file() == ["rig/t1", "harry · guest@mini"]))

    def test_tab_bar_sends_it_from_its_run_loop(self):
        text = (ROOT / "hcgui.py").read_text()
        tabs_loop = text[text.index("class TabBar:"):text.index("def start_hidden(")]
        self.assertIn("self.pane_title.send(tabs_title(snap, shown))", tabs_loop)
        side_run = text[text.index("    def run(self) -> None:\n        setup_curses(self.s.scr, right=True, "
                                   "motion=True)"):]
        self.assertIn("self.pane_title.send(self.title)", side_run[:side_run.index("class TabBar:")])

    # view.sh -----------------------------------------------------------------------------------------------------
    def start_view(self, stub=TITLE_STUB):
        tmp = Path(self._tmp.name)
        (tmp / "bin").mkdir(exist_ok=True)
        hc = tmp / "bin" / "hc"
        hc.write_text(stub)
        hc.chmod(0o755)
        log = tmp / "log"
        log.write_text("")
        out = tmp / "out"
        env = dict(os.environ, HCGUI_HC=str(hc), HCGUI_STATE=str(self.state), HCGUI_WINDOW=str(self.win),
                   STUB_LOG=str(log), LC_ALL="en_US.UTF-8")
        self.win.mkdir(parents=True, exist_ok=True)
        with open(out, "wb") as sink:
            proc = subprocess.Popen(["/bin/sh", str(ROOT / "view.sh")], env=env, stdin=subprocess.DEVNULL,
                                    stdout=sink, stderr=subprocess.STDOUT, start_new_session=True)

        def stop():
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)

        self.addCleanup(stop)
        self.assertTrue(wait_for(lambda: (self.win / "view.loop").exists()))
        return out

    def test_view_sets_the_title_before_each_attach_and_hcgui_after(self):
        out = self.start_view()
        hcgui.show("mini/t2", self.win, "tracker · me@mini")
        self.assertTrue(wait_for(lambda: b"ATTACH mini/t2" in out.read_bytes()))
        hcgui.show("rig/t1", self.win, "harry · guest@mini")
        self.assertTrue(wait_for(lambda: b"ATTACH rig/t1" in out.read_bytes()))
        hcgui.show("", self.win, hcgui.NO_TITLE)
        self.assertTrue(wait_for(lambda: out.read_bytes().count(b"Pick a terminal") >= 2))
        data = out.read_bytes()
        one, two = data.index(b"ATTACH mini/t2"), data.index(b"ATTACH rig/t1")
        first = "\x1b]2;tracker · me@mini\x07".encode()
        second = "\x1b]2;harry · guest@mini\x07".encode()
        self.assertIn(first, data[:one])
        self.assertIn(second, data[one:two])
        self.assertEqual(ghostty_title(data[:one])[0], "tracker · me@mini")
        self.assertEqual(ghostty_title(data[:two])[0], "harry · guest@mini")
        self.assertEqual(ghostty_title(data)[0], "hcGUI")  # nothing shown any more
        # every OSC 7 comes right after a title: never one that could clear it
        osc = OSC_RE.findall(data)
        for i, (code, _) in enumerate(osc):
            if code == b"7":
                self.assertEqual(osc[i - 1][0], b"2")

    def test_view_after_an_attach_ends_goes_back_to_the_mini_title(self):
        stub = TITLE_STUB.replace("while :; do sleep 0.02; done", 'printf "\\033]2;Claude Code\\007"; exit 0')
        out = self.start_view(stub)
        hcgui.show("mini/t2", self.win, "tracker · me@mini")
        self.assertTrue(wait_for(lambda: b"is not shown any more" in out.read_bytes()))
        data = out.read_bytes()
        attach = data.index(b"ATTACH mini/t2")
        self.assertEqual(ghostty_title(data[:data.index(b"Claude Code") + 12])[0], "Claude Code")  # its own title
        self.assertEqual(ghostty_title(data)[0], "tracker · me@mini")  # clean_screen: the mini title again
        self.assertIn("\x1b]2;tracker · me@mini\x07".encode(), data[:attach])

    def test_view_with_a_title_for_another_terminal_waits_then_says_hcgui(self):
        out = self.start_view()
        hcgui.write_title("other", "other · x", self.win)
        started = time.monotonic()
        hcgui.show("mini/t2", self.win)  # no title given: the file still names "other"
        self.assertTrue(wait_for(lambda: b"ATTACH mini/t2" in out.read_bytes()))
        self.assertGreaterEqual(time.monotonic() - started, 0.4)  # it waited for the right one
        data = out.read_bytes()
        self.assertEqual(ghostty_title(data[:data.index(b"ATTACH")])[0], "hcGUI")
        hcgui.write_title("mini/t3", "sh · me@mini", self.win)  # the engine, a moment late
        hcgui.show("mini/t3", self.win)
        self.assertTrue(wait_for(lambda: b"ATTACH mini/t3" in out.read_bytes()))
        data = out.read_bytes()
        self.assertEqual(ghostty_title(data[:data.index(b"ATTACH mini/t3")])[0], "sh · me@mini")

    def test_view_drops_control_characters_from_the_file(self):
        out = self.start_view()
        self.win.mkdir(parents=True, exist_ok=True)
        (self.win / "title").write_bytes(b"t1\nweb\x1b]7;file://x/\x07 \xc2\xb7 x\n")  # not from hcgui.py
        hcgui.show("t1", self.win)
        self.assertTrue(wait_for(lambda: b"ATTACH t1" in out.read_bytes()))
        data = out.read_bytes()
        before = data[:data.index(b"ATTACH t1")]
        self.assertIn("\x1b]2;web]7;file://x/ · x\x07".encode(), before)
        self.assertEqual(ghostty_title(before)[0], "web]7;file://x/ · x")


PRESS1, RELEASE1 = hcgui.curses.BUTTON1_PRESSED, hcgui.curses.BUTTON1_RELEASED
PRESS3, RELEASE3 = hcgui.curses.BUTTON3_PRESSED, hcgui.curses.BUTTON3_RELEASED


class MouseSetupTests(unittest.TestCase):
    """Presses act the moment they arrive: no mouse interval, no CLICKED in the mask, releases dropped."""

    def setup(self, right):
        calls = []
        patches = {"curs_set": lambda n: None, "use_default_colors": lambda: None, "init_pair": lambda *a: None,
                   "mouseinterval": lambda ms: calls.append(("interval", ms)),
                   "mousemask": lambda mask: calls.append(("mask", mask)) or (mask, 0)}
        scr = mock.Mock()
        with mock.patch.multiple(hcgui.curses, **patches):
            hcgui.setup_curses(scr, right=right)
        return calls, scr

    def test_interval_zero_before_the_mask_and_only_presses_and_releases(self):
        calls, scr = self.setup(right=True)
        self.assertEqual(calls, [("interval", 0), ("mask", PRESS1 | RELEASE1 | PRESS3 | RELEASE3)])
        clicked = (hcgui.curses.BUTTON1_CLICKED | hcgui.curses.BUTTON3_CLICKED | hcgui.curses.BUTTON1_DOUBLE_CLICKED
                   | hcgui.curses.BUTTON3_DOUBLE_CLICKED)
        self.assertEqual(calls[1][1] & clicked, 0)  # a CLICKED in the mask makes ncurses hold every press back
        scr.timeout.assert_called_once_with(hcgui.LOOP_WAIT_MS)
        calls, _ = self.setup(right=False)  # the tab bar leaves the right button to Ghostty
        self.assertEqual(calls, [("interval", 0), ("mask", PRESS1 | RELEASE1)])

    def test_read_mouse_reports_presses_only(self):
        for bstate, mouse, click in ((PRESS1, (4, 2, 1), (4, 2)), (PRESS3, (4, 2, 3), None), (RELEASE1, None, None),
                                     (RELEASE3, None, None), (hcgui.curses.BUTTON1_CLICKED, None, None), (0, None, None)):
            with mock.patch.object(hcgui.curses, "getmouse", return_value=(0, 4, 2, 0, bstate)):
                self.assertEqual(hcgui.read_mouse(), mouse, bstate)
                self.assertEqual(hcgui.read_click(), click, bstate)
        with mock.patch.object(hcgui.curses, "getmouse", side_effect=hcgui.curses.error):
            self.assertIsNone(hcgui.read_mouse())

    def test_in_a_pseudo_terminal_the_press_comes_at_once(self):
        """The real ncurses of this Mac: a press, then its release 150 ms later (X10 mouse, as xterm-256color
        has it). The press must be read within a few ms of its arrival, the release apart."""
        import pty
        child = (
            "import curses, os, sys, time\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "import hcgui\n"
            "def main(scr):\n"
            "    hcgui.setup_curses(scr, right=True)\n"
            "    os.write(3, b'ready\\n')\n"
            "    end = time.time() + 2\n"
            "    while time.time() < end:\n"
            "        k = scr.getch()\n"
            "        if k == curses.KEY_MOUSE:\n"
            "            os.write(3, f'{time.time()} {hcgui.read_mouse()}\\n'.encode())\n"
            "curses.wrapper(main)\n")
        r, w = os.pipe()
        pid, fd = pty.fork()
        if pid == 0:  # pragma: no cover - the child
            os.dup2(w, 3)
            env = dict(os.environ, TERM="xterm-256color", PYTHONDONTWRITEBYTECODE="1")
            os.execve(sys.executable, [sys.executable, "-c", child], env)
        os.close(w)
        drain = threading.Thread(target=lambda: [None for _ in iter(lambda: _read(fd), b"")], daemon=True)
        drain.start()
        log = os.fdopen(r)
        try:
            self.assertEqual(log.readline().strip(), "ready")
            sent = time.time()
            os.write(fd, b"\x1b[M" + bytes([32, 33 + 5, 33 + 2]))  # left press at column 5, line 2
            time.sleep(0.15)
            os.write(fd, b"\x1b[M" + bytes([35, 33 + 5, 33 + 2]))  # its release
            press, release = log.readline().split(" ", 1), log.readline().split(" ", 1)
        finally:
            os.waitpid(pid, 0)
            log.close()
            os.close(fd)
        self.assertEqual(press[1].strip(), "(5, 2, 1)")
        self.assertLess(float(press[0]) - sent, 0.08)  # before: at the release plus 166 ms, here about 0.3 s
        self.assertEqual(release[1].strip(), "None")


def _read(fd):
    try:
        return os.read(fd, 4096)
    except OSError:
        return b""


class PressTests(unittest.TestCase):
    """Sidebar and tab bar on presses: the press acts, the release that follows changes nothing."""

    TERMS = ActionTests.TERMS
    setUp = ActionTests.setUp
    key = ActionTests.key
    line_of = ActionTests.line_of

    def mouse(self, x, y, bstate):
        with mock.patch.object(hcgui.curses, "getmouse", return_value=(0, x, y, 0, bstate)):
            self.key(hcgui.curses.KEY_MOUSE)

    def test_a_press_on_a_row_shows_it_and_its_release_does_nothing(self):
        row = self.line_of(hcgui.Item("agent", "space:other", "t4"))
        self.mouse(5, row, PRESS1)
        self.assertEqual(hcgui.current_target(self.win), "t4")
        gen = mtime_ns(self.win / "gen")
        self.side.notice.say("kept")
        self.side.mouse_quiet = 0.0
        self.mouse(5, row, RELEASE1)
        self.assertEqual(mtime_ns(self.win / "gen"), gen)  # no second pick
        self.assertEqual(self.side.notice.current(), "kept")  # a release is no key: the notice stays

    def test_the_notice_a_press_set_survives_its_release(self):
        row = self.line_of(hcgui.Item("agent", "space:other", "t4"))
        self.hc.terms = [t for t in self.hc.terms if t["address"] != "t4"]
        self.side.refresh_once()
        self.mouse(5, row, PRESS1)
        self.assertEqual(self.side.notice.current(), "that terminal has ended")
        self.mouse(5, row, RELEASE1)
        self.assertEqual(self.side.notice.current(), "that terminal has ended")

    def test_a_right_press_opens_the_menu_and_its_release_keeps_it(self):
        row = self.line_of(hcgui.Item("group", "rig:vps", ""))
        self.mouse(5, row, PRESS3)
        self.assertEqual(self.side.menu.item, hcgui.Item("group", "rig:vps", ""))
        self.side.mouse_quiet = 0.0  # not the double-click guard: the release itself is dropped
        self.mouse(5, row, RELEASE3)
        self.assertIsNotNone(self.side.menu)
        self.mouse(0, 0, PRESS1)  # a press outside closes it, and opens nothing
        self.assertIsNone(self.side.menu)
        self.side.mouse_quiet = 0.0
        target = hcgui.current_target(self.win)
        self.mouse(0, 0, RELEASE1)
        self.assertIsNone(self.side.menu)
        self.assertEqual(hcgui.current_target(self.win), target)

    def test_a_press_on_an_entry_runs_it_and_its_release_does_not_close_the_prompt(self):
        row = self.line_of(hcgui.Item("group", "rig:vps", ""))
        self.mouse(5, row, PRESS3)
        box = self.side.menu_at
        self.side.mouse_quiet = 0.0
        self.mouse(box.left + 3, box.entry_y(2), PRESS1)  # Rename
        self.assertEqual(self.side.prompt.title, "rename vps to:")
        self.mouse(box.left + 3, box.entry_y(2), RELEASE1)
        self.assertEqual(self.side.prompt.title, "rename vps to:")

    def test_the_key_list_opened_by_a_press_stays_on_its_release(self):
        self.mouse(self.side.help_x, self.side.arrow_y, PRESS1)
        self.assertTrue(self.side.help)
        self.side.mouse_quiet = 0.0
        self.mouse(self.side.help_x, self.side.arrow_y, RELEASE1)
        self.assertTrue(self.side.help)
        self.mouse(5, 2, PRESS1)  # the next press closes it, and does nothing else
        self.assertFalse(self.side.help)

    def test_a_double_click_on_fold_folds_once(self):
        self.mouse(5, self.side.arrow_y, PRESS1)
        self.assertEqual(self.side.mode, "strip")
        self.mouse(5, self.side.arrow_y, RELEASE1)
        with mock.patch.object(hcgui, "tmux"):
            self.mouse(5, self.side.arrow_y, PRESS1)  # the second press, within MOUSE_QUIET: no hide
        self.assertEqual(hcgui.read_sidebar_state(self.state), "strip")

    def test_tab_bar_press_shows_at_once_and_its_release_keeps_the_notice(self):
        bar_tests = TabBarLogicTests("test_waiting_without_a_sidebar")  # only for its fixture
        bar_tests.addCleanup = self.addCleanup
        bar_tests.setUp()
        bar, snap = bar_tests.bar, bar_tests.snap
        bar.draw(snap, "t1")
        with mock.patch.object(hcgui.curses, "getmouse", return_value=(0, 3, 1, 0, PRESS1)):
            bar.on_key(hcgui.curses.KEY_MOUSE, snap, "t1")
        self.assertEqual(hcgui.current_target(bar_tests.win), "t5")
        gen = mtime_ns(bar_tests.win / "gen")
        bar.notice.say("kept")
        with mock.patch.object(hcgui.curses, "getmouse", return_value=(0, 3, 1, 0, RELEASE1)):
            bar.on_key(hcgui.curses.KEY_MOUSE, snap, "t5")
        self.assertEqual(mtime_ns(bar_tests.win / "gen"), gen)
        self.assertEqual(bar.notice.current(), "kept")


class LoopWakeTests(unittest.TestCase):
    """A pick in one pane shows in the other within LOOP_WAIT_MS, not at the next 0.25 s round."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.win = Path(self._tmp.name)

    def test_round_due(self):
        stamp = (1, 2)
        self.assertFalse(hcgui.round_due(stamp, stamp, 10.1, 10.0))
        self.assertTrue(hcgui.round_due((3, 2), stamp, 10.1, 10.0))  # a pick
        self.assertTrue(hcgui.round_due((1, 4), stamp, 10.1, 10.0))  # new tabs
        self.assertTrue(hcgui.round_due(stamp, stamp, 10.0 + hcgui.ROUND_SECONDS, 10.0))

    def test_pick_stamp_moves_on_a_pick_and_on_new_tabs(self):
        first = hcgui.pick_stamp(self.win)
        self.assertEqual(first, (0, 0, 0))
        hcgui.show("t1", self.win)
        second = hcgui.pick_stamp(self.win)
        self.assertNotEqual(second[0], 0)
        time.sleep(0.002)
        hcgui.write_snapshot(None, self.win)
        self.assertNotEqual(hcgui.pick_stamp(self.win)[1], second[1])
        hcgui.write_atomic(self.win / "ask", "menu\n")  # a right click in the view
        self.assertNotEqual(hcgui.pick_stamp(self.win)[2], 0)

    def test_wait_key(self):
        keys = iter([-1, -1, ord("j")])
        scr = mock.Mock(getch=lambda: next(keys))
        with mock.patch.object(hcgui, "terminal_gone", return_value=False):
            now = time.monotonic()
            self.assertEqual(hcgui.wait_key(scr, self.win, hcgui.pick_stamp(self.win), now), ord("j"))
            seen = hcgui.pick_stamp(self.win)
            calls = []

            def getch():
                calls.append(1)
                if len(calls) == 3:
                    hcgui.show("t2", self.win)  # the other pane picks
                return -1

            scr = mock.Mock(getch=getch)
            self.assertEqual(hcgui.wait_key(scr, self.win, seen, time.monotonic()), -1)
            self.assertEqual(len(calls), 3)  # at once after the pick, not at the end of the round
            calls.clear()
            self.assertEqual(hcgui.wait_key(scr, self.win, hcgui.pick_stamp(self.win), now - 1), -1)  # round due
            self.assertEqual(len(calls), 1)
        with mock.patch.object(hcgui, "terminal_gone", return_value=True):
            self.assertIsNone(hcgui.wait_key(mock.Mock(getch=lambda: -1), self.win, (0, 0), time.monotonic()))

    def test_both_loops_wait_with_it(self):
        text = (ROOT / "hcgui.py").read_text()
        side = text[text.index("    def run(self) -> None:\n        setup_curses(self.s.scr, right=True, motion=True)"):
                    text.index("class TabBar:")]
        tabs = text[text.index("class TabBar:"):text.index("def start_hidden(")]
        for loop in (side, tabs):
            self.assertIn("wait_key(self.s.scr, self.win, seen,", loop)
            self.assertNotIn(".getch()", loop)


class ProcInfoTests(unittest.TestCase):
    """attach_pid asks the kernel, not ps (5-10 ms less on every pick), and still falls back to ps."""

    def test_own_process_and_a_dead_one(self):
        if sys.platform != "darwin":
            self.skipTest("macOS only")
        ppid, command = hcgui.proc_info(os.getpid())
        self.assertEqual(ppid, os.getppid())
        self.assertIn("unittest", command)
        proc = subprocess.Popen(["/bin/sleep", "5"])
        self.assertEqual(hcgui.proc_info(proc.pid), (os.getpid(), "/bin/sleep 5"))
        proc.kill()
        proc.wait()
        self.assertEqual(hcgui.proc_info(proc.pid), (0, ""))

    def test_attach_pid_falls_back_to_ps(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        win = Path(tmp.name)
        stub = win / "hc"
        stub.write_text("#!/bin/sh\nwhile :; do sleep 0.1; done\n")
        stub.chmod(0o755)
        proc = subprocess.Popen([str(stub), "attach", "t1"])
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        time.sleep(0.2)
        hcgui.write_atomic(win / "view.pid", f"{proc.pid}\n")
        hcgui.write_atomic(win / "view.loop", f"{os.getpid()}\n")
        self.assertEqual(hcgui.attach_pid(win), proc.pid)
        with mock.patch.object(hcgui, "proc_info", return_value=None), \
                mock.patch.object(hcgui.subprocess, "run", wraps=subprocess.run) as run:
            self.assertEqual(hcgui.attach_pid(win), proc.pid)
        self.assertEqual(run.call_args[0][0][0], "/bin/ps")
        with mock.patch.object(hcgui.subprocess, "run") as run:
            self.assertEqual(hcgui.attach_pid(win), proc.pid)  # the kernel answered: no ps
        run.assert_not_called()


class ViewSwitchTests(unittest.TestCase):
    """view.sh between two attaches: no wipe of the pane when the next attach follows at once (hc attach clears and
    draws the whole pane itself), the wipe kept when nothing follows, and nothing slow on the way."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.win = self.tmp / "state"
        self.log = self.tmp / "log"
        self.log.write_text("")

    def start_view(self, stub=TITLE_STUB, **extra):
        (self.tmp / "bin").mkdir(exist_ok=True)
        hc = self.tmp / "bin" / "hc"
        hc.write_text(stub)
        hc.chmod(0o755)
        out = self.tmp / "out"
        env = dict(os.environ, HCGUI_HC=str(hc), HCGUI_STATE=str(self.win), STUB_LOG=str(self.log), **extra)
        env.pop("HCGUI_WINDOW", None)
        with open(out, "wb") as sink:
            proc = subprocess.Popen(["/bin/sh", str(ROOT / "view.sh")], env=env, stdin=subprocess.DEVNULL,
                                    stdout=sink, stderr=subprocess.STDOUT, start_new_session=True)

        def stop():
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)

        self.addCleanup(stop)
        self.assertTrue(wait_for(lambda: (self.win / "view.loop").exists()))
        return out

    def test_no_wipe_between_two_attaches(self):
        out = self.start_view()
        hcgui.show("a", self.win)
        self.assertTrue(wait_for(lambda: b"ATTACH a" in out.read_bytes()))
        hcgui.show("b", self.win)
        self.assertTrue(wait_for(lambda: b"ATTACH b" in out.read_bytes()))
        data = out.read_bytes()
        between = data[data.index(b"ATTACH a"):data.index(b"ATTACH b")]
        self.assertNotIn(b"\x1b[2J", between)
        # the modes are still reset: main screen, mouse off, cursor on, plain colours
        for mode in (b"\x1b[?1049l", b"\x1b[?1000l", b"\x1b[?1006l", b"\x1b[?25h", b"\x1b[0m"):
            self.assertIn(mode, between)
        self.assertNotIn(b"Pick a terminal", between)

    def test_wipe_kept_when_nothing_follows(self):
        out = self.start_view()
        hcgui.show("a", self.win)
        self.assertTrue(wait_for(lambda: b"ATTACH a" in out.read_bytes()))
        hcgui.show("", self.win)  # nothing shown any more
        self.assertTrue(wait_for(lambda: b"Pick a terminal" in out.read_bytes().partition(b"ATTACH a")[2]))
        data = out.read_bytes()
        attach = data.index(b"ATTACH a")
        self.assertIn(b"\x1b[2J", data[attach:data.index(b"Pick a terminal", attach)])
        ended = TITLE_STUB.replace("while :; do sleep 0.02; done", "exit 0")  # detached, or its program ended
        self.log.write_text("")
        (self.tmp / "out").unlink()
        out = self.start_view(ended)
        hcgui.show("c", self.win)
        self.assertTrue(wait_for(lambda: b"is not shown any more" in out.read_bytes()))
        data = out.read_bytes()
        self.assertIn(b"\x1b[2J", data[data.index(b"ATTACH c"):data.index(b"is not shown any more")])

    def test_idle_view_attaches_a_pick_within_a_few_polls(self):
        self.start_view(HCGUI_AUTOOPEN="0")
        delays = []
        for name in ("a", "b", "c", "d", "e"):
            time.sleep(0.3)  # idle: nothing attached
            started = time.monotonic()
            hcgui.show(name, self.win)
            self.assertTrue(wait_for(lambda: f"start {name}" in self.log.read_text()))
            delays.append(time.monotonic() - started)
            hcgui.show("", self.win)
            self.assertTrue(wait_for(lambda: f"end {name}" in self.log.read_text()))
        # the median: one slow start on a busy machine is no failure. The shell loop that polled every 0.2 s (with
        # a cat and a sleep each time) took 160 ms in the median, here it is 35 ms.
        self.assertLess(sorted(delays)[2], 0.12, delays)

    def test_a_signal_while_idle_ends_the_view_and_its_wait_at_once(self):
        self.start_view(HCGUI_AUTOOPEN="0")
        time.sleep(0.3)  # idle: the perl wait runs
        loop = int(hcgui.read_text(self.win / "view.loop"))
        waiters = subprocess.run(["/usr/bin/pgrep", "-P", str(loop)], capture_output=True, text=True).stdout.split()
        self.assertEqual(len(waiters), 1, waiters)
        started = time.monotonic()
        os.kill(loop, signal.SIGTERM)  # the script alone, not its process group
        self.assertTrue(wait_for(lambda: not (self.win / "view.loop").exists()))
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertTrue(wait_for(lambda: subprocess.run(["/bin/kill", "-0", waiters[0]],
                                                        capture_output=True).returncode != 0))

    def test_switch_path_starts_no_needless_process(self):
        text = (ROOT / "view.sh").read_text()
        loop = text[text.index("while :; do\n  read_gen"):]
        substitution = re.compile(r"\$\((?!\()")  # $( but not $(( (arithmetic, no process)
        self.assertIsNone(substitution.search(loop))  # no command substitution: each costs a process
        for name in ("read_gen", "read_target", "wait_title", "set_title", "own_title", "reset_modes"):
            body = text[text.index(f"{name}() {{"):text.index("\n}", text.index(f"{name}() {{"))]
            self.assertIsNone(substitution.search(body), name)
            for tool in ("cat ", "head ", "stty ", "perl", "tr "):
                self.assertNotIn(tool, body, (name, tool))
        switch = loop[loop.index('if [ "$now_gen" != "$gen" ]; then'):loop.index("continue", loop.index(
            'if [ "$now_gen" != "$gen" ]; then'))]
        switch = "\n".join(x for x in switch.split("\n") if not x.strip().startswith("#"))
        self.assertIn("reset_modes", switch)
        for slow in ("clean_screen", "rm ", "stty", "gone"):
            self.assertNotIn(slow, switch, slow)

    def test_flush_drops_pending_input(self):
        import fcntl
        import pty
        import termios
        text = (ROOT / "view.sh").read_text()
        line = next(x for x in text.split("\n") if "0x80047410" in x)
        command = re.search(r"'(.*)'", line).group(1)
        import tty
        master, slave = pty.openpty()
        try:
            tty.setraw(slave)  # as an attach leaves it: every byte counts, not only whole lines
            os.write(master, b"keys typed meanwhile")
            time.sleep(0.05)
            pending = lambda: int.from_bytes(fcntl.ioctl(slave, termios.FIONREAD, b"\0\0\0\0"), sys.byteorder)
            self.assertGreater(pending(), 0)
            self.assertEqual(subprocess.run(["/usr/bin/perl", "-e", command], stdin=slave).returncode, 0)
            self.assertEqual(pending(), 0)
        finally:
            os.close(master)
            os.close(slave)


MOTION = hcgui.curses.REPORT_MOUSE_POSITION


class TabDragTests(unittest.TestCase):
    """Owner, 25 Nov: "is it possible to drag the Tabs, left and right?" A held tab follows the pointer; its release
    keeps the order (order.json, every window); "Sort by name" in the tab menu gives the names' order back."""

    setUp = TabBarLogicTests.setUp

    def x_of(self, label):
        seg = next(s for s in self.bar.layout.segs if s.kind == "tab" and label in s.text)
        return seg.x + 2, seg.y

    def mouse(self, x, y, bstate):
        with mouse_at(x, y, bstate), mock.patch.object(hcgui, "focus_view"):
            self.bar.on_key(hcgui.curses.KEY_MOUSE, self.snap, hcgui.current_target(self.win))
        self.bar.draw(self.snap, hcgui.current_target(self.win))

    def labels(self):
        return [str(t["label"]) for t in self.bar.drawn]

    def test_drag_a_tab_to_another_place_and_keep_it(self):
        self.bar.draw(self.snap, "t1")
        self.assertEqual(self.labels(), ["alpha", "beta", "delta", "gamma", "omega"])  # by name
        self.mouse(*self.x_of("delta"), PRESS1)
        self.assertEqual(hcgui.current_target(self.win), "t4")  # the press picks it, as a click does
        self.mouse(*self.x_of("alpha"), MOTION)  # held over alpha: delta takes its place
        self.assertEqual(self.labels(), ["delta", "alpha", "beta", "gamma", "omega"])
        self.assertFalse((self.state / "order.json").exists())  # nothing kept before the release
        with mock.patch.object(hcgui, "poke_engine") as poke:
            self.mouse(*self.x_of("delta"), RELEASE1)
        poke.assert_called_once_with(self.win)  # a snapshot in the new order, now
        self.assertEqual(hcgui.read_order(self.state), {"space:app": ["t4", "t1", "t2", "t3", "t5"]})
        self.assertEqual(self.labels(), ["delta", "alpha", "beta", "gamma", "omega"])  # until the snapshot shows it
        self.assertIsNone(self.bar.tab_drag)

    def test_the_saved_order_is_the_groups_order(self):
        hcgui.write_order("space:app", ["t4", "t1", "t9"], self.state)  # t9 ended: skipped
        terms = hcgui.parse(ls(term("t1", "/Users/x/dev/app", "claude-code", "alpha", "idle"), term("t2", name="beta"),
                               term("t3", name="gamma"), term("t4", name="delta"), term("t5", name="omega")))
        spaces, _ = hcgui.build_groups(terms, "mini", order=hcgui.read_order(self.state))
        group = spaces[0]
        # dragged ones first in their order, the rest (new since) after them by name
        self.assertEqual([t.shown for t in group.terms], ["delta", "alpha", "beta", "gamma", "omega"])
        self.assertTrue(group.ordered)
        snap = hcgui.make_snapshot(group, 0.0)
        self.assertTrue(snap["ordered"])
        self.assertFalse(hcgui.make_snapshot(hcgui.build_groups(terms, "mini")[0][0], 0.0)["ordered"])

    def test_a_click_writes_nothing_and_a_key_or_a_lost_release_drops_the_drag(self):
        self.bar.draw(self.snap, "t1")
        self.mouse(*self.x_of("beta"), PRESS1)
        self.mouse(*self.x_of("beta"), RELEASE1)  # a plain click: no order
        self.assertFalse((self.state / "order.json").exists())
        self.mouse(*self.x_of("beta"), PRESS1)
        self.mouse(*self.x_of("alpha"), MOTION)
        with mock.patch.object(hcgui, "focus_view"):
            self.bar.on_key(27, self.snap, "t2")  # esc: the drag ends, the order as it was
        self.bar.draw(self.snap, "t2")
        self.assertIsNone(self.bar.tab_drag)
        self.assertEqual(self.labels(), ["alpha", "beta", "delta", "gamma", "omega"])
        self.mouse(*self.x_of("beta"), PRESS1)
        self.bar.tab_drag.seen -= hcgui.DRAG_IDLE  # no event for a while: the release got lost
        self.mouse(*self.x_of("alpha"), MOTION)  # most likely a new click: dropped, the order as it was
        self.assertIsNone(self.bar.tab_drag)
        self.assertEqual(self.labels(), ["alpha", "beta", "delta", "gamma", "omega"])
        self.assertFalse((self.state / "order.json").exists())

    def test_over_plus_is_the_last_place(self):
        self.bar.draw(self.snap, "t1")
        self.mouse(*self.x_of("alpha"), PRESS1)
        plus = next(s for s in self.bar.layout.segs if s.kind == "plus")
        self.mouse(plus.x, plus.y, MOTION)
        self.assertEqual(self.labels()[-1], "alpha")

    def test_sort_by_name_only_while_ordered_and_it_removes_the_order(self):
        self.assertNotIn("sort", [e.action for e in hcgui.tab_menu_entries("space")])
        self.assertEqual(hcgui.tab_menu_entries("space", True)[-1], hcgui.Entry("sort", "Sort by name", ""))
        hcgui.write_order("space:app", ["t4", "t1"], self.state)
        hcgui.write_order("rig:box", ["box/t2", "box/t1"], self.state)
        self.bar.menu = hcgui.TabMenu("t1", "alpha", hcgui.tab_menu_entries("space", True))
        with mock.patch.object(hcgui, "poke_engine"), mock.patch.object(hcgui, "focus_view"):
            self.bar.run_tab_entry(hcgui.Entry("sort", "Sort by name", ""), self.snap)
        self.assertEqual(hcgui.read_order(self.state), {"rig:box": ["box/t2", "box/t1"]})  # other groups stay

    def test_order_file_junk_and_moved(self):
        hcgui.write_atomic(self.state / "order.json", json.dumps(
            {"space:a": ["t1", "t1", "t2"], "space:b": "t1", "space:c": [1, 2], "": ["t1"], "space:d": []}))
        self.assertEqual(hcgui.read_order(self.state), {"space:a": ["t1", "t2"], "space:d": []})
        hcgui.write_atomic(self.state / "order.json", "not json")
        self.assertEqual(hcgui.read_order(self.state), {})
        self.assertEqual(hcgui.moved(["a", "b", "c", "d"], "d", 0), ["d", "a", "b", "c"])
        self.assertEqual(hcgui.moved(["a", "b", "c", "d"], "a", 2), ["b", "c", "a", "d"])
        self.assertEqual(hcgui.moved(["a", "b"], "a", 9), ["b", "a"])


class AgentGapTests(unittest.TestCase):
    """Owner, 25 Nov: one blank row after a group with a heading, before the next agent ("keep it simple"); 26 Nov:
    after an agent alone in its group too."""

    def plan(self, height=30, needs=()):
        terms = hcgui.parse(ls(term("t1", "/Users/x/dev", "claude-code", "atlas", "idle"),
                               term("t2", "/Users/x/dev", "claude-code", "gecko", "idle"),
                               term("t3", "/Users/x/dev/other", "claude-code", "o1", "idle"),
                               term("t4", "/Users/x/dev/zz", "claude-code", "z1", "idle")))
        spaces, rigs = hcgui.build_groups(terms, "mini")
        return [r.kind for _, r in hcgui.plan_sidebar(spaces, rigs, height, servers=False, needs=needs)]

    def test_one_blank_row_after_every_group(self):
        kinds = self.plan()
        agents = kinds[kinds.index("agents") + 1:]
        # dev (two agents, a heading), a blank row, o1 alone, a blank row, z1 alone; none at the end
        self.assertEqual(agents, ["agent_group", "agent", "agent", "blank", "agent", "blank", "agent"])

    def test_no_blank_row_when_the_agents_do_not_all_fit(self):
        kinds = self.plan(height=9)
        self.assertNotIn("blank", kinds[kinds.index("agents") + 1:] if "agents" in kinds else kinds)


class SeparatorPlanTests(unittest.TestCase):
    """The separator between the upper part and the agents, moved: its line from the file and the pane height."""

    def setUp(self):
        self.spaces, self.rigs = many_agents(6)
        self.items = hcgui.selectable_items(self.spaces, self.rigs)

    def test_limits_keep_a_heading_and_a_row_on_each_side(self):
        self.assertIsNone(hcgui.rule_limits(4))  # "spaces" + a row, then the line, "agents" + a row: 5 lines
        self.assertEqual(hcgui.rule_limits(5), (2, 2))
        self.assertEqual(hcgui.rule_limits(23), (2, 20))
        for height in range(-2, 5):
            self.assertIsNone(hcgui.clamp_rule(3, height), height)
        self.assertEqual([hcgui.clamp_rule(y, 23) for y in (-5, 0, 2, 11, 20, 21, 99)], [2, 2, 2, 11, 20, 20, 20])

    def test_keys_step_one_line_and_stop_at_the_limits(self):
        step = hcgui.rule_step
        self.assertEqual((step(10, -1, 23), step(10, 1, 23)), (9, 11))
        self.assertEqual((step(2, -1, 23), step(20, 1, 23)), (2, 20))
        self.assertEqual(step(21, -1, 23), 20)  # drawn below the limit (no agents): up goes to the limit
        self.assertEqual(step(21, 1, 23), 21)  # ] never moves it up
        self.assertEqual(step(23, -1, 23), 20)  # none drawn (the upper part took every line): from the bottom
        self.assertEqual(step(23, 1, 23), 23)
        self.assertIsNone(step(2, 1, 4))

    def test_the_file_split_parses_or_counts_as_none(self):
        self.assertEqual(hcgui.parse_split("12/40"), (12, 40))
        self.assertEqual(hcgui.parse_split(" 0/1\n"), (0, 1))
        for junk in ("", "12", "x/40", "40/40", "41/40", "-1/40", "3/0", "3/1001", "12 / 40", "+3/40", "1e3/40",
                     "١٢/40", "12/40/2", "12/40\n7/9", "99999/99999"):
            self.assertIsNone(hcgui.parse_split(junk), junk)

    def test_its_line_keeps_its_share_of_the_pane(self):
        self.assertIsNone(hcgui.split_row(None, 40))
        self.assertIsNone(hcgui.split_row((12, 40), 0))
        for height in range(1, 200):  # the height it was set at: exactly that line
            for row in range(height):
                self.assertEqual(hcgui.split_row((row, height), height), row, (row, height))
        self.assertEqual(hcgui.split_row((12, 40), 60), 18)  # a taller window: the same share
        self.assertEqual(hcgui.split_row((12, 40), 20), 6)
        self.assertEqual(hcgui.split_row((12, 40), 41), 12)  # 12.3

    def test_moved_rule_splits_the_list_there(self):
        plan = hcgui.plan_sidebar(self.spaces, self.rigs, 23, 0, rule=8)
        rule = next(y for y, r in plan if r.kind == "rule")
        self.assertEqual(rule, 8)
        self.assertTrue(all(y < 8 for y, r in plan if r.kind in ("header", "group", "plus", "blank")))
        below = [(y, r.kind) for y, r in plan if y >= 8]
        self.assertEqual(below[:3], [(8, "rule"), (9, "agents"), (10, "agent_group")])
        self.assertEqual(sum(1 for _, k in below if k == "agent"), 6)  # 13 lines below: all 6 agents
        self.assertEqual(max(y for y, _ in plan), 16)  # top-aligned under the line; the rest stays empty
        auto = hcgui.plan_sidebar(self.spaces, self.rigs, 23, 0)
        self.assertEqual([(y, r.kind) for y, r in hcgui.plan_sidebar(self.spaces, self.rigs, 23, 0, rule=None)],
                         [(y, r.kind) for y, r in auto])

    def test_every_height_line_and_cursor_keeps_the_cursor_row_and_both_parts(self):
        for height in range(0, 26):
            for rule in range(-2, height + 3):
                for cursor in range(len(self.items)):
                    case = (height, rule, cursor)
                    plan = hcgui.plan_sidebar(self.spaces, self.rigs, height, cursor, rule=rule)
                    ys = [y for y, _ in plan]
                    self.assertEqual(len(ys), len(set(ys)), case)
                    self.assertTrue(all(0 <= y < height for y in ys), case)
                    at = hcgui.clamp_rule(rule, height)
                    if at is None:  # too short: the automatic layout
                        self.assertEqual([(y, r.kind) for y, r in plan],
                                         [(y, r.kind) for y, r in hcgui.plan_sidebar(self.spaces, self.rigs, height,
                                                                                     cursor)], case)
                        continue
                    self.assertEqual([y for y, r in plan if r.kind == "rule"], [at], case)
                    self.assertEqual(dict(plan)[at + 1].kind, "agents", case)
                    self.assertIn(cursor, [r.item for _, r in plan], case)  # a "+" row and an agent too
                    tops = [y for y, r in plan if r.kind in ("header", "group", "plus", "blank")]
                    self.assertTrue(all(y < at for y in tops), case)
                    self.assertGreaterEqual(len(tops), 2, case)

    def test_a_small_upper_part_scrolls_to_the_plus_row(self):
        plus = self.items.index(hcgui.Item("new_space", "", ""))
        plan = hcgui.plan_sidebar(self.spaces, self.rigs, 23, plus, rule=2)
        self.assertEqual([r.kind for y, r in plan if y < 2], ["group", "plus"])

    def test_the_strip_has_the_same_lines(self):
        for rule in (2, 8, 20):
            wide = hcgui.plan_sidebar(self.spaces, self.rigs, 23, 0, rule=rule)
            strip = hcgui.plan_sidebar(self.spaces, self.rigs, 23, 0, compact=True, rule=rule)
            self.assertEqual([(y, r.kind) for y, r in wide], [(y, r.kind) for y, r in strip])

    def test_a_click_on_its_line_hits_the_separator_only(self):
        rows = {3: hcgui.Item("group", "space:dev", "")}
        self.assertEqual(hcgui.sidebar_hit(8, 23, -1, rows, 0, 28, 8), ("rule", None))
        self.assertEqual(hcgui.sidebar_hit(8, 23, -1, rows, 27, 28, 8), ("rule", None))
        self.assertEqual(hcgui.sidebar_hit(3, 23, -1, rows, 0, 28, 8)[0], "item")
        self.assertEqual(hcgui.sidebar_hit(8, 23, -1, rows, 0, 28), ("", None))  # not drawn: nothing there
        self.assertEqual(hcgui.sidebar_hit(23, 23, -1, rows, 0, 28, 23), ("step", None))  # the arrow line wins

    def test_mouse_events_and_their_route(self):
        for bstate, event in ((PRESS1, "press"), (PRESS3, "right"), (RELEASE1, "release"), (RELEASE3, "release"),
                              (MOTION, "motion"), (MOTION | PRESS1, "motion"), (0, None),
                              (hcgui.curses.BUTTON1_CLICKED, None)):
            with mouse_at(4, 2, bstate):
                self.assertEqual(hcgui.read_mouse_event(), (4, 2, event) if event else None, bstate)
                if event not in ("press", "right"):
                    self.assertIsNone(hcgui.read_mouse(), bstate)  # only presses are clicks
        route = hcgui.mouse_route
        for what in ("release", "motion", ""):  # without a drag: dropped, as before
            self.assertEqual(route(what, False), "drop", what)
        self.assertEqual((route("motion", True), route("release", True), route("", True)), ("follow", "end", "drop"))
        for dragging in (False, True):
            self.assertEqual((route("press", dragging), route("right", dragging)), ("press", "press"))

    def test_a_move_after_a_quiet_drag_is_a_lost_release(self):
        route = hcgui.mouse_route
        # ncurses 6.0 reads the press after a lost release as a move: a drag quiet for DRAG_IDLE is not followed
        self.assertEqual(route("motion", True, True), "lost")
        self.assertEqual((route("release", True, True), route("press", True, True)), ("end", "press"))
        self.assertEqual((route("motion", False, True), route("release", False, True)), ("drop", "drop"))

    def test_the_line_where_the_automatic_layout_dropped_it(self):
        def crowded(n):
            terms = [term(f"s{i}", f"/Users/x/dev/s{i:02d}") for i in range(n)]
            terms += [term(f"a{i}", "/Users/x/dev/s00", "claude-code", f"a{i}", "idle") for i in range(6)]
            return hcgui.build_groups(hcgui.parse(ls(*terms)), "mini")

        def agent_lines(plan):
            return sum(1 for _, r in plan if r.kind in ("agent_group", "agent", "more"))

        for n, auto_rows in ((17, [(19, "agents"), (20, "agent_group")]), (18, [(20, "agent_group")])):
            spaces, rigs = crowded(n)
            plan = hcgui.plan_sidebar(spaces, rigs, 23, 0, servers=False)
            self.assertNotIn("rule", [r.kind for _, r in plan], n)  # the automatic layout dropped it
            self.assertEqual([(y, r.kind) for y, r in plan if y >= auto_rows[0][0]][:len(auto_rows)], auto_rows, n)
            line = hcgui.rule_line(plan, 23)
            self.assertEqual(line, 18, n)  # where it would be above the same agent rows
            up = hcgui.plan_sidebar(spaces, rigs, 23, 0, servers=False, rule=hcgui.rule_step(line, -1, 23))
            down = hcgui.plan_sidebar(spaces, rigs, 23, 0, servers=False, rule=hcgui.rule_step(line, 1, 23))
            self.assertEqual((agent_lines(up), agent_lines(down)), (agent_lines(plan) + 1, agent_lines(plan) - 1), n)
        plan = hcgui.plan_sidebar(self.spaces, self.rigs, 23, 0)
        self.assertEqual(hcgui.rule_line(plan, 23), next(y for y, r in plan if r.kind == "rule"))  # drawn: there
        self.assertEqual(hcgui.rule_line([], 23), 23)  # no agents part at all: the bottom

    def test_the_file_is_read_written_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            self.assertIsNone(hcgui.read_split(state))
            hcgui.clear_split(state)  # no file: fine
            hcgui.write_split(8, 24, state)
            self.assertEqual((state / "split").read_text(), "8/24\n")
            self.assertEqual(hcgui.read_split(state), (8, 24))
            (state / "split").write_text("junk\n")
            self.assertIsNone(hcgui.read_split(state))
            hcgui.clear_split(state)
            self.assertFalse((state / "split").exists())


class ShellClaudeTests(unittest.TestCase):
    """The Sidebar with Claude Code typed in a terminal's shell: hc ls names the shell (no status), hc get's
    foreground shows Claude Code. Listed as Claude Code until the shell is in front again."""

    TERMS = SidebarLogicTests.TERMS
    setUp = SidebarLogicTests.setUp
    key = SidebarLogicTests.key

    def front(self, address, *argv, account=""):
        self.hc.infos[address] = {"labels": {"account": account} if account else {},
                                  "foreground": foreground(*argv, name="2.1.331" if argv[0].endswith("claude")
                                                           else "zsh")}
        self.side.refresh_once(full=True)
        self.side.sync()
        self.side.draw()

    def test_listed_as_claude_code_with_its_mark_and_no_status(self):
        self.front("t4", "/Users/x/.local/bin/claude", account="work")
        lines = self.scr.lines()
        self.assertIn(hcgui.glyph(" other"), lines)  # two agents now: the heading is back
        self.assertIn(hcgui.glyph("  ○ sh²"), lines)  # hollow dot, its account mark, no status word
        items = self.side.sections().items()
        self.assertIn(hcgui.Item("agent", "space:other", "t4"), items)
        found = self.side.term_of("t4")
        self.assertEqual((found.agent, found.status, found.mark), ("claude-code", "", "²"))
        self.assertNotIn("t4", [t.address for t in self.side.needs("")])  # no status: never "needs you"
        prompt = self.side.delete_question(hcgui.Item("agent", "space:other", "t4"))
        self.assertIn("sh (claude-code)", prompt.title)  # the list of what ends names its program
        self.side.set_current("space:other")  # the tab bar's line names the program
        hcgui.show("t4", self.win)
        self.side.sync()
        tab = next(t for t in hcgui.read_snapshot(self.win)["tabs"] if t["address"] == "t4")
        self.assertEqual((tab["agent"], tab["mark"]), ("claude-code", "²"))
        self.assertTrue(hcgui.tab_info(tab).startswith("Claude Code · "), hcgui.tab_info(tab))

    def test_a_shell_again_once_claude_code_ended(self):
        self.front("t4", "/Users/x/.local/bin/claude")
        self.assertIn(hcgui.Item("agent", "space:other", "t4"), self.side.sections().items())
        self.front("t4", "-zsh")
        self.assertNotIn(hcgui.Item("agent", "space:other", "t4"), self.side.sections().items())
        self.assertEqual(self.side.term_of("t4").agent, "zsh")
        self.assertIn(hcgui.glyph("  ● o1 · other"), self.scr.lines())  # o1 alone again
        self.front("t4", "/Users/x/.local/bin/claude-foo")  # another program of a like name: still a shell
        self.assertEqual(self.side.term_of("t4").agent, "zsh")

    def test_a_shell_of_another_machine_is_asked_too(self):
        self.hc.terms.append(term("rig/t9", "/home/x", "zsh", "remote"))
        self.hc.terms.append(term("rig/t8", "/home/x", "python3", "job"))  # neither Claude Code nor a shell
        self.front("rig/t9", "claude", account="work")
        gets = [c[1] for c in self.hc.calls if c[0] == "get"]
        self.assertIn("rig/t9", gets)
        self.assertNotIn("rig/t8", gets)
        self.assertEqual(self.side.infos["rig/t9"], hcgui.Info(account="work", foreground="claude-code"))
        found = self.side.term_of("rig/t9")
        self.assertEqual((found.agent, found.mark), ("claude-code", "²"))


class SeparatorDragTests(unittest.TestCase):
    """The Sidebar: the separator dragged with the mouse (press, moves, release) and moved with [ ] - =."""

    # dev's four agents under "dev · 4" (o1 moved there: one group, so no blank row after it): the rule, "agents" and
    # 5 lines, the 7 lines these tests' rows are counted with; "other" keeps its shell
    TERMS = [term("t3", "/Users/x/dev", "claude-code", "o1", "done") if t["address"] == "t3" else t
             for t in SidebarLogicTests.TERMS] + [term("t5", "/Users/x/dev", "claude-code", "zed", "idle")]
    setUp = SidebarLogicTests.setUp
    key = SidebarLogicTests.key

    def mouse(self, x, y, bstate):
        with mouse_at(x, y, bstate):
            self.key(hcgui.curses.KEY_MOUSE)

    def rule_line(self):
        return next(y for y in range(self.scr.height) if self.scr.line(y) == "─" * 29)

    def split(self):
        return hcgui.read_text(self.state / "split")

    def test_auto_layout_first(self):
        self.assertEqual((self.side.rule_y, self.rule_line()), (16, 16))  # 23 lines of list, the agents at the end
        self.assertIsNone(self.side.rule_plan)

    def test_press_on_the_line_then_release_elsewhere_moves_it_and_keeps_it(self):
        target, gen = hcgui.current_target(self.win), mtime_ns(self.win / "gen")
        self.mouse(20, 16, PRESS1)  # any column of the line
        self.assertEqual(self.side.drag_y, 16)
        self.assertEqual(self.scr.cells[(16, 0)][1], hcgui.curses.A_BOLD)  # held: drawn bold
        self.assertIsNone(self.side.menu)
        self.assertEqual((hcgui.current_target(self.win), mtime_ns(self.win / "gen")), (target, gen))  # no pick
        self.mouse(3, 12, MOTION)  # the pointer moves with the button held: the line goes along
        self.assertEqual((self.side.drag_y, self.rule_line()), (12, 12))
        self.assertEqual(self.split(), "")  # written only at the release
        self.mouse(3, 8, RELEASE1)
        self.assertIsNone(self.side.drag_y)
        self.assertEqual(self.split(), "8/24")
        lines = self.scr.lines()
        self.assertEqual(lines[8], "─" * 29)
        self.assertEqual(self.scr.cells[(8, 0)][1], hcgui.curses.A_DIM)
        self.assertTrue(lines[9].startswith(" agents"))
        self.assertEqual(lines[10], hcgui.glyph(" dev"))
        # other holds only a shell here (o1 moved to dev in this class's TERMS): its dot is hollow
        self.assertEqual(lines[0:4], [" spaces", hcgui.glyph("›● dev"), hcgui.glyph(" ○ other"), " + new space"])
        self.assertEqual(lines[-1], fold_line("open"))

    def test_without_moves_the_release_alone_moves_it(self):
        self.mouse(0, 16, PRESS1)
        self.mouse(0, 5, RELEASE1)
        self.assertEqual((self.split(), self.rule_line()), ("5/24", 5))

    def test_press_elsewhere_and_release_on_the_line_does_nothing(self):
        row = next(y for y, item in self.side.rows.items() if item.address == "t3")
        self.mouse(5, row, PRESS1)
        self.assertIsNone(self.side.drag_y)
        self.mouse(5, row - 3, MOTION)
        self.mouse(5, 16, RELEASE1)
        self.assertEqual((self.split(), self.rule_line()), ("", 16))

    def test_a_release_outside_the_pane_lands_at_the_limit(self):
        self.mouse(0, 16, PRESS1)
        self.mouse(0, 60, MOTION)
        self.assertEqual(self.side.drag_y, 20)  # the line, "agents" and one row stay
        self.mouse(0, 60, RELEASE1)
        self.assertEqual((self.split(), self.rule_line()), ("20/24", 20))
        self.mouse(0, 20, PRESS1)
        self.mouse(0, 0, RELEASE1)  # up: "spaces" and one row stay
        self.assertEqual((self.split(), self.rule_line()), ("2/24", 2))
        self.assertEqual(self.scr.lines()[:2], [" spaces", hcgui.glyph("›● dev")])

    def test_a_click_on_the_line_writes_nothing_and_a_double_press_resets(self):
        self.mouse(0, 16, PRESS1)
        self.mouse(0, 16, RELEASE1)
        self.assertEqual(self.split(), "")  # a click moves nothing
        hcgui.write_split(6, 24, self.state)
        self.side.rule_pressed = None
        self.side.draw()
        self.assertEqual(self.rule_line(), 6)
        self.mouse(0, 6, PRESS1)
        self.mouse(0, 6, RELEASE1)
        self.mouse(0, 6, PRESS1)  # the second press, within MOUSE_QUIET
        self.assertFalse((self.state / "split").exists())
        self.assertIsNone(self.side.drag_y)
        self.assertEqual(self.rule_line(), 15)  # the automatic layout (one line less: the notice says so)
        self.assertEqual(self.side.notice.current(), "separator: automatic again")
        self.mouse(0, 6, RELEASE1)  # its release: no drag, nothing
        self.assertFalse((self.state / "split").exists())

    def test_a_slow_second_press_starts_a_new_drag(self):
        self.mouse(0, 16, PRESS1)
        self.mouse(0, 16, RELEASE1)
        self.side.rule_pressed -= hcgui.MOUSE_QUIET + 0.01
        self.mouse(0, 16, PRESS1)
        self.assertEqual(self.side.drag_y, 16)

    def test_a_right_press_on_the_line_does_nothing(self):
        target = hcgui.current_target(self.win)
        self.mouse(5, 16, PRESS3)
        self.assertIsNone(self.side.menu)
        self.assertIsNone(self.side.drag_y)
        self.assertEqual(hcgui.current_target(self.win), target)

    def test_releases_and_moves_without_a_drag_change_nothing(self):
        self.side.notice.say("kept")
        self.mouse(5, 8, MOTION)
        self.mouse(5, 8, RELEASE1)
        self.assertEqual(self.side.notice.current(), "kept")
        self.assertEqual(self.split(), "")

    def test_esc_ends_a_drag_and_another_key_ends_it_and_acts(self):
        self.mouse(0, 16, PRESS1)
        self.mouse(0, 10, MOTION)
        self.key(27)
        self.assertIsNone(self.side.drag_y)
        self.assertEqual(self.rule_line(), 16)
        self.mouse(0, 10, RELEASE1)  # its release comes later: no drag, nothing
        self.assertEqual(self.split(), "")
        self.mouse(0, 16, PRESS1)
        self.side.rule_pressed = None
        self.key("j")
        self.assertIsNone(self.side.drag_y)
        self.assertEqual(self.side.cursor, hcgui.Item("group", "space:other", ""))

    def test_a_press_while_a_drag_lost_its_release_acts_normally(self):
        self.mouse(0, 16, PRESS1)
        row = next(y for y, item in self.side.rows.items() if item.address == "t3")
        self.mouse(5, row, PRESS1)
        self.assertIsNone(self.side.drag_y)
        self.assertEqual(hcgui.current_target(self.win), "t3")
        self.assertEqual(self.split(), "")

    def test_a_click_after_a_lost_release_does_not_move_it(self):
        self.mouse(0, 16, PRESS1)
        self.mouse(0, 12, MOTION)
        self.side.drag_seen -= hcgui.DRAG_IDLE + 0.01  # the release got lost; a while later, a click on row 3:
        self.mouse(3, 3, MOTION)  # ncurses 6.0 reads its press as a move (it still thinks the button is held)
        self.assertIsNone(self.side.drag_y)
        self.assertEqual(self.rule_line(), 16)  # back where it was
        self.mouse(3, 3, RELEASE1)
        self.assertEqual((self.split(), self.rule_line()), ("", 16))
        self.assertIsNone(self.side.prompt)  # that click is dropped, as one after a lost release always was
        self.mouse(3, 3, PRESS1)  # the next click acts
        self.assertIsNotNone(self.side.prompt)

    def test_a_quiet_drag_still_ends_at_its_release(self):
        self.mouse(0, 16, PRESS1)
        self.mouse(0, 12, MOTION)
        self.side.drag_seen -= hcgui.DRAG_IDLE + 0.01  # held still a while, then let go
        self.mouse(0, 12, RELEASE1)
        self.assertEqual((self.split(), self.rule_line()), ("12/24", 12))

    def test_keys_from_a_dropped_line_move_the_boundary_the_right_way(self):
        self.hc.terms = [term(f"s{i}", f"/Users/x/dev/s{i:02d}") for i in range(17)]
        self.hc.terms += [term(f"a{i}", "/Users/x/dev/s00", "claude-code", f"a{i}", "idle") for i in range(6)]
        self.side.refresh_once()
        self.key("r")
        self.assertEqual(self.side.rule_y, -1)  # crowded: the automatic layout dropped the line
        agents = lambda: sum(1 for item in self.side.rows.values() if item.kind == "agent")
        self.assertTrue(self.scr.line(19).startswith(" agents"))
        self.assertEqual(agents(), 1)
        self.key("[")  # up: the agents get a row
        self.assertEqual((self.split(), self.rule_line()), ("17/24", 17))
        self.assertEqual(agents(), 2)
        (self.state / "split").unlink()
        self.side.draw()  # the automatic layout again
        self.key("]")  # down: the agents give one
        self.assertEqual((self.split(), self.rule_line()), ("19/24", 19))
        self.assertEqual(agents(), 0)

    def test_a_low_automatic_line_is_held_where_drawn_and_moves_one_row_up(self):
        self.hc.terms = [t for t in self.hc.terms if t["agent"] == "zsh"]  # no agents: the line sits lower
        self.side.refresh_once()
        self.key("r")
        self.assertEqual(self.rule_line(), 21)
        self.mouse(0, 21, PRESS1)
        self.assertEqual(self.rule_line(), 21)  # held: it does not jump up
        self.mouse(0, 20, MOTION)
        self.mouse(0, 21, MOTION)  # and back: where it was drawn
        self.assertEqual(self.rule_line(), 21)
        self.mouse(0, 21, RELEASE1)
        self.assertEqual(self.split(), "")  # let go where it was: nothing written
        self.side.rule_pressed = None
        self.mouse(0, 21, PRESS1)
        self.mouse(0, 20, RELEASE1)  # one row up: it stays there
        self.assertEqual((self.split(), self.rule_line()), ("20/24", 20))

    def test_at_its_lower_limit_a_notice_or_the_strip_moves_it_up_as_far_as_needed(self):
        hcgui.write_split(20, 24, self.state)
        self.side.draw()
        self.assertEqual(self.rule_line(), 20)
        self.side.notice.say("something")  # one line less for the list: "agents" and a row still fit
        self.side.draw()
        self.assertEqual(self.rule_line(), 19)
        self.side.notice.clear()
        self.side.draw()
        self.assertEqual(self.rule_line(), 20)
        hcgui.write_split(12, 24, self.state)
        self.side.prompt = hcgui.Prompt("forget", " ".join(["word"] * 60), ask="type yes:")  # a long typed question
        self.side.draw()
        self.assertEqual(self.rule_line(), 11)

    def test_keys_move_it_one_line(self):
        self.key("[")
        self.assertEqual((self.split(), self.rule_line()), ("15/24", 15))
        self.key("-", "-")
        self.assertEqual(self.rule_line(), 13)
        self.key("]", "=")
        self.assertEqual((self.split(), self.rule_line()), ("15/24", 15))
        self.key(*"]" * 10)
        self.assertEqual((self.split(), self.rule_line()), ("20/24", 20))
        self.key("[")
        self.assertEqual(self.rule_line(), 19)

    def test_keys_never_push_a_low_line_up(self):
        self.hc.terms = [t for t in self.hc.terms if t["agent"] == "zsh"]  # no agents: the line sits lower
        self.side.refresh_once()
        self.key("r")
        self.assertEqual(self.rule_line(), 21)
        self.key("]")
        self.assertEqual((self.split(), self.rule_line()), ("", 21))
        self.key("[")
        self.assertEqual((self.split(), self.rule_line()), ("20/24", 20))

    def test_kept_for_the_next_window_and_removing_the_file_goes_back(self):
        self.key("[", "[")
        other = hcgui.Sidebar(FakeScr(24, 30), self.state, self.state / "w-2")
        other.refresh_once()
        other.sync()
        other.draw()
        self.assertEqual(other.rule_y, 14)
        (self.state / "split").unlink()
        self.side.draw()
        self.assertEqual(self.rule_line(), 16)
        (self.state / "split").write_text("nonsense\n")
        self.side.draw()
        self.assertEqual(self.rule_line(), 16)

    def test_moved_in_another_window_shows_here_at_the_next_draw(self):
        hcgui.write_split(9, 24, self.state)
        self.side.draw()
        self.assertEqual(self.rule_line(), 9)

    def test_a_taller_or_shorter_pane_keeps_the_share(self):
        self.mouse(0, 16, PRESS1)
        self.mouse(0, 8, RELEASE1)
        self.scr.height = 36
        self.side.draw()
        self.assertEqual(self.rule_line(), 12)
        self.scr.height = 12
        self.side.draw()
        self.assertEqual(self.rule_line(), 4)
        self.scr.height = 5  # too short for a moved line: the automatic layout
        self.side.draw()
        self.assertIsNone(hcgui.rule_limits(self.side.body_height))
        self.scr.height = 24
        self.side.draw()
        self.assertEqual(self.rule_line(), 8)

    def test_a_notice_or_a_prompt_does_not_move_it(self):
        hcgui.write_split(12, 24, self.state)
        self.side.notice.say("something")
        self.side.draw()
        self.assertEqual(self.rule_line(), 12)
        self.key("s")  # the new space prompt: lines at the bottom
        self.assertIsNotNone(self.side.prompt)
        self.assertEqual(self.rule_line(), 12)

    def test_the_strip_has_it_too(self):
        self.key("c")
        self.assertEqual(self.side.mode, "strip")
        self.scr.width = 8
        self.side.draw()
        self.assertEqual(self.side.rule_y, 15)  # "› open" takes a line
        self.mouse(0, 15, PRESS1)
        self.mouse(0, 7, RELEASE1)
        self.assertEqual(self.split(), "7/24")
        self.assertEqual(self.scr.line(7), "─" * 7)
        self.key("c")  # hide: no sidebar at all; the file stays for the next one
        self.assertEqual(self.split(), "7/24")

    def test_a_small_upper_part_keeps_the_cursor_row(self):
        hcgui.write_split(2, 24, self.state)
        self.side.draw()
        self.key("j", "j")  # down to "+ new space": the upper part scrolls
        self.assertEqual(self.side.cursor, hcgui.Item("new_space", "", ""))
        self.assertEqual(self.scr.reversed_rows(), [1])
        self.assertEqual(self.scr.line(1), " + new space")
        self.key("j")  # on to the agents below the line
        self.assertEqual(self.side.cursor.kind, "agent")

    def test_the_list_of_keys_names_them(self):
        self.assertIn(" [ ] - = separator up/down", hcgui.help_lines(29, 40))


class DragReportTests(unittest.TestCase):
    """Mode 1002 (moves with a button held) asked of the terminal after ncurses' own mouse mode, and the moves read
    by this Mac's ncurses in both encodings: X10 (xterm-256color) and SGR (Ghostty's terminfo asks for 1006)."""

    def test_report_drags_writes_after_a_refresh(self):
        r, w = os.pipe()
        order = []
        scr = mock.Mock(refresh=lambda: order.append("refresh"))
        try:
            hcgui.report_drags(scr, True, w)
            order.append(os.read(r, 100))
            hcgui.report_drags(scr, False, w)
            order.append(os.read(r, 100))
        finally:
            os.close(r)
            os.close(w)
        self.assertEqual(order, ["refresh", b"\x1b[?1002h", "refresh", b"\x1b[?1002l"])
        hcgui.report_drags(scr, True, 999)  # a closed pane: no error

    def test_the_sidebar_and_the_tab_bar_ask_for_moves(self):
        calls = []
        raw = []
        patches = {"curs_set": lambda n: None, "use_default_colors": lambda: None, "init_pair": lambda *a: None,
                   "mouseinterval": lambda ms: None, "mousemask": lambda mask: calls.append(mask) or (mask, 0),
                   "raw": lambda: raw.append(1)}
        with mock.patch.multiple(hcgui.curses, **patches):
            hcgui.setup_curses(mock.Mock(), right=True, motion=True)
            hcgui.setup_curses(mock.Mock())
        self.assertEqual(calls, [PRESS1 | RELEASE1 | PRESS3 | RELEASE3 | MOTION, PRESS1 | RELEASE1])
        self.assertEqual(raw, [1, 1])  # ctrl+C is a key in the panes, never a signal that ends one
        text = (ROOT / "hcgui.py").read_text()
        side = text[text.index("class Sidebar(Engine):"):text.index("class TabBar:")]
        run = side[side.index("    def run(self) -> None:"):]
        self.assertIn("setup_curses(self.s.scr, right=True, motion=True)\n        report_drags(self.s.scr, True)", run)
        self.assertIn("finally:\n            report_drags(self.s.scr, False)", run)
        # the tab bar too since 25 Nov: a dragged tab follows the pointer (owner: "drag the tabs left and right")
        bar = text[text.index("class TabBar:"):text.index("def start_hidden(")]
        bar_run = bar[bar.index("    def run(self) -> None:"):]
        self.assertIn("setup_curses(self.s.scr, right=True, motion=True)", bar_run)
        self.assertIn("report_drags(self.s.scr, True)", bar_run)
        self.assertIn("finally:\n            report_drags(self.s.scr, False)", bar_run)

    def terminfo(self):
        """A copy of Ghostty 1.3's mouse capabilities (src/terminfo/ghostty.zig) on top of xterm-256color."""
        tic = shutil.which("tic") or "/usr/bin/tic"
        if not os.path.exists(tic):
            self.skipTest("no tic")
        folder = tempfile.mkdtemp(prefix="hcgui-ti-")
        self.addCleanup(shutil.rmtree, folder, True)
        source = Path(folder) / "ghostty.src"
        source.write_text("xterm-ghostty|test copy of the mouse capabilities of Ghostty 1.3,\n"
                          "\tXM=\\E[?1006;1000%?%p1%{1}%=%th%el%;,\n"
                          "\txm=\\E[<%i%p3%d;%p1%d;%p2%d;%?%p4%tM%em%;,\n"
                          "\tkmous=\\E[<, use=xterm-256color,\n")
        subprocess.run([tic, "-x", "-o", folder, str(source)], check=True, capture_output=True)
        return folder

    def run_child(self, term, terminfo, events):
        """The sidebar's mouse setup in a pseudo terminal: what it writes, and what it reads for `events`."""
        import pty
        child = (
            "import curses, os, sys\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "import hcgui\n"
            "def main(scr):\n"
            "    hcgui.setup_curses(scr, right=True, motion=True)\n"
            "    hcgui.report_drags(scr, True)\n"
            "    os.write(3, b'ready\\n')\n"
            f"    for _ in range({len(events)}):\n"
            "        k = -1\n"
            "        while k == -1:\n"
            "            k = scr.getch()\n"
            "        e = hcgui.read_mouse_event() if k == curses.KEY_MOUSE else ('key', k)\n"
            "        os.write(3, (repr(e) + '\\n').encode())\n"
            "    hcgui.report_drags(scr, False)\n"
            "curses.wrapper(main)\n")
        r, w = os.pipe()
        pid, fd = pty.fork()
        if pid == 0:  # pragma: no cover - the child
            os.dup2(w, 3)
            env = dict(os.environ, TERM=term, PYTHONDONTWRITEBYTECODE="1")
            if terminfo:
                env["TERMINFO"] = terminfo
            os.execve(sys.executable, [sys.executable, "-c", child], env)
        os.close(w)
        out = []
        drain = threading.Thread(target=lambda: [out.append(b) for b in iter(lambda: _read(fd), b"")], daemon=True)
        drain.start()
        log = os.fdopen(r)
        try:
            self.assertEqual(log.readline().strip(), "ready")
            got = []
            for event in events:
                os.write(fd, event)
                got.append(log.readline().strip())
        finally:
            os.waitpid(pid, 0)
            log.close()
            drain.join(2)
            os.close(fd)
        modes = re.findall(rb"\x1b\[\?(1006;1000|1000|1002)([hl])", b"".join(out))
        return got, modes

    def test_x10_moves_and_release_in_a_pseudo_terminal(self):
        x10 = lambda code, x, y: b"\x1b[M" + bytes([32 + code, 33 + x, 33 + y])
        got, modes = self.run_child("xterm-256color", "", [x10(0, 5, 16), x10(32, 5, 12), x10(32, 5, 9),
                                                            x10(3, 5, 8), x10(2, 4, 3), x10(3, 4, 3)])
        self.assertEqual(got, ["(5, 16, 'press')", "(5, 12, 'motion')", "(5, 9, 'motion')", "(5, 8, 'release')",
                               "(4, 3, 'right')", "(4, 3, 'release')"])
        # ncurses' 1000 first, then 1002 (a 1000 after it would end the moves), 1002 off, ncurses' 1000 off
        self.assertEqual(modes, [(b"1000", b"h"), (b"1002", b"h"), (b"1002", b"l"), (b"1000", b"l")])

    def test_sgr_moves_and_release_with_ghosttys_terminfo(self):
        sgr = lambda code, x, y, end="M": f"\x1b[<{code};{x + 1};{y + 1}{end}".encode()
        got, modes = self.run_child("xterm-ghostty", self.terminfo(),
                                    [sgr(0, 5, 16), sgr(32, 5, 12), sgr(32, 300, 0), sgr(0, 5, 49, "m"),
                                     sgr(2, 4, 3), sgr(2, 4, 3, "m")])
        self.assertEqual(got, ["(5, 16, 'press')", "(5, 12, 'motion')", "(300, 0, 'motion')", "(5, 49, 'release')",
                               "(4, 3, 'right')", "(4, 3, 'release')"])
        self.assertEqual(modes, [(b"1006;1000", b"h"), (b"1002", b"h"), (b"1002", b"l"), (b"1006;1000", b"l")])

    def test_a_press_after_a_lost_release_reads_as_a_move_in_both_codes(self):
        # why mouse_route has "lost": ncurses 6.0 still thinks the button is held and gives no press to tell apart
        x10 = lambda code, x, y: b"\x1b[M" + bytes([32 + code, 33 + x, 33 + y])
        sgr = lambda code, x, y, end="M": f"\x1b[<{code};{x + 1};{y + 1}{end}".encode()
        want = ["(5, 16, 'press')", "(5, 12, 'motion')", "(2, 3, 'motion')", "(2, 3, 'release')", "(2, 3, 'press')"]
        got, _ = self.run_child("xterm-256color", "", [x10(0, 5, 16), x10(32, 5, 12), x10(0, 2, 3), x10(3, 2, 3),
                                                       x10(0, 2, 3)])
        self.assertEqual(got, want)
        got, _ = self.run_child("xterm-ghostty", self.terminfo(), [sgr(0, 5, 16), sgr(32, 5, 12), sgr(0, 2, 3),
                                                                   sgr(0, 2, 3, "m"), sgr(0, 2, 3)])
        self.assertEqual(got, want)


# ---------------------------------------------------------------------------------------------------------------
# needs you, account marks, the keychain warning, dev servers, hiding the agents
# ---------------------------------------------------------------------------------------------------------------
LSOF = "\n".join([
    "p88581", "cnode", "f12", "n*:3917", "f13", "n127.0.0.1:3918",  # the loopback one only the machine itself reaches
    "p90001", "cnode", "f20", "n[::]:5173", "f21", "n0.0.0.0:5173",  # IPv6 and IPv4 of one port: one row
    "p90002", "cnode-exporter", "f5", "n*:9100",  # lsof -c matches the start of a name: not node
    "p90003", "cnode", "f7", "n[::1]:9229", "f8", "n192.168.1.20:8080",  # loopback IPv6; a LAN address counts
    "p90004", "cnode", "f9", "n*:3917",  # the same port again (another program): the first one stays
    "--cwd",
    "p88581", "fcwd", "n/Users/x/dev/.wt/site/feature",
    "p90001", "fcwd", "n/Users/x/dev/docs-site",
    "p90003", "fcwd", "n/Users/x",
]) + "\n"


def tterm(address, cwd, agent, name, status=None, turn=0):
    t = term(address, cwd, agent, name, status)
    t["turn"] = turn
    return t


class NeedsYouTests(unittest.TestCase):
    """needs_you and mark_seen (pure)."""

    def terms(self):
        return hcgui.parse(ls(tterm("mini/t1", "/Users/x/dev", "claude-code", "zeta", "done", 2),
                              tterm("mini/t2", "/Users/x/dev", "claude-code", "alpha", "blocked", 1),
                              tterm("mini/t3", "/Users/x/dev", "claude-code", "beta", "idle", 4),
                              tterm("mini/t4", "/Users/x/dev", "claude-code", "gamma", "error", 3),
                              tterm("mini/t5", "/Users/x/dev", "claude-code", "delta", "working", 1),
                              tterm("mini/t6", "/Users/x/dev", "zsh", "sh", None, 0),
                              tterm("rig/t1", "/home/r", "claude-code", "remote", "done", 1)))

    def test_parse_reads_the_turn(self):
        self.assertEqual([t.turn for t in self.terms()], [2, 1, 4, 3, 1, 0, 1])
        junk = hcgui.parse(ls(dict(term("t1"), turn="7"), dict(term("t2"), turn=-1), dict(term("t3"), turn=True)))
        self.assertEqual([t.turn for t in junk], [0, 0, 0])

    def test_blocked_and_error_first_then_unseen_done(self):
        names = [t.name for t in hcgui.needs_you(self.terms(), {})]
        self.assertEqual(names, ["alpha", "gamma", "remote", "zeta"])

    def test_a_done_once_looked_at_goes_and_a_newer_done_comes_back(self):
        terms = self.terms()
        self.assertEqual([t.name for t in hcgui.needs_you(terms, {"mini/t1": 2, "rig/t1": 1})], ["alpha", "gamma"])
        self.assertIn("zeta", [t.name for t in hcgui.needs_you(terms, {"mini/t1": 1})])  # an older look

    def test_the_shown_terminal_is_left_out(self):
        names = [t.name for t in hcgui.needs_you(self.terms(), {}, "mini/t2")]
        self.assertNotIn("alpha", names)

    def test_mark_seen_records_the_turn_of_the_shown_done_terminal(self):
        terms = self.terms()
        self.assertEqual(hcgui.mark_seen({}, terms, "mini/t1"), {"mini/t1": 2})
        self.assertEqual(hcgui.mark_seen({}, terms, "mini/t2"), {})  # blocked: nothing to remember
        self.assertEqual(hcgui.mark_seen({}, terms, ""), {})
        cleared = hcgui.needs_you(terms, hcgui.mark_seen({}, terms, "mini/t1"))
        self.assertNotIn("zeta", [t.name for t in cleared])

    def test_mark_seen_drops_ended_terminals_but_keeps_an_unlisted_machine(self):
        seen = {"mini/t99": 3, "rig/t1": 1, "away/t4": 2}
        after = hcgui.mark_seen(seen, self.terms(), "")
        self.assertEqual(after, {"rig/t1": 1, "away/t4": 2})  # mini/t99 ended; "away" is not listed now

    def test_mark_seen_keeps_at_most_the_newest(self):
        seen = {f"away/t{i}": i for i in range(hcgui.SEEN_MAX + 20)}
        after = hcgui.mark_seen(seen, self.terms(), "mini/t1")
        self.assertEqual(len(after), hcgui.SEEN_MAX)
        self.assertEqual(list(after)[-1], "mini/t1")

    def test_seen_file_round_trip_and_junk(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            self.assertEqual(hcgui.read_seen(state), {})
            hcgui.write_seen({"mini/t1": 2}, state)
            self.assertEqual(hcgui.read_seen(state), {"mini/t1": 2})
            (state / "seen.json").write_text('{"a": 1, "b": "2", "c": -1, "d": true, "": 3}')
            self.assertEqual(hcgui.read_seen(state), {"a": 1})
            (state / "seen.json").write_text("junk")
            self.assertEqual(hcgui.read_seen(state), {})

    def test_needs_text_keeps_the_mark_and_cuts_the_server(self):
        self.assertEqual(hcgui.needs_text("tracker", "²", "", 25), "tracker²")
        self.assertEqual(hcgui.needs_text("harry", "³", "guest@mini", 27), "harry³ · guest@mini")
        self.assertEqual(hcgui.needs_text("harry", "³", "guest@mini", 16), "harry³ · guest@…")
        self.assertEqual(hcgui.needs_text("averyveryverylongname", "¹", "srv", 12), "aver…¹ · srv")  # half each
        self.assertEqual(hcgui.needs_text("averyveryverylongname", "¹", "guest", 12), "aver…¹ · gu…")
        self.assertEqual(hcgui.needs_text("averyveryverylongname", "¹", "srv", 10), "averyver…¹")  # no room: no server
        for room in range(1, 30):
            self.assertLessEqual(hcgui.text_width(hcgui.needs_text("averyveryverylongname", "¹", "guest", room)),
                                 room, room)


class AccountMarkTests(unittest.TestCase):
    """account_mark, account_marks and the width of a marked name (pure)."""

    def test_the_rule(self):
        mark = hcgui.account_mark
        # HCGUI_MARKS of the tests: claude and main = ¹, work = ²; HCGUI_SHARED_USER guest
        self.assertEqual(mark("claude-code", "main"), "¹")
        self.assertEqual(mark("claude-code", "claude"), "¹")
        self.assertEqual(mark("claude-code", "work"), "²")
        self.assertEqual(mark("claude-code", "team"), "³")  # any other account
        self.assertEqual(mark("claude-code", ""), "")  # no label: no mark
        self.assertEqual(mark("claude-code", "", "me"), "")
        self.assertEqual(mark("claude-code", "", "guest"), "³")  # the shared account's own plan
        self.assertEqual(mark("claude-code", "main", "guest"), "¹")  # a label wins
        self.assertEqual(mark("zsh", "main"), "")  # only Claude Code
        self.assertEqual(mark("codex", "", "guest"), "")

    def test_ssh_user(self):
        self.assertEqual(hcgui.ssh_user(hcgui.Machine("rig", "guest@mini")), "guest")
        self.assertEqual(hcgui.ssh_user(hcgui.Machine("rig", "guest@mini:2222")), "guest")
        self.assertEqual(hcgui.ssh_user(hcgui.Machine("rig", "vps")), "")
        self.assertEqual(hcgui.ssh_user(hcgui.Machine("rig", "guest@x", via=True)), "")
        self.assertEqual(hcgui.ssh_user(None), "")

    def test_marks_from_labels_and_machines(self):
        terms = hcgui.parse(ls(term("mini/t1", agent="claude-code"), term("mini/t2", agent="claude-code"),
                               term("mini/t3", agent="claude-code"), term("mini/t4", agent="claude-code"),
                               term("guest/t1", agent="claude-code"), term("guest/t2", agent="zsh")))
        infos = {"mini/t1": hcgui.Info(account="main"), "mini/t2": hcgui.Info(account="work"),
                 "mini/t3": hcgui.Info(account="other"), "mini/t4": hcgui.Info(account="claude")}
        machines = [hcgui.Machine("mini", "me@mini"), hcgui.Machine("guest", "guest@mini")]
        self.assertEqual(hcgui.account_marks(terms, infos, machines),
                         {"mini/t1": "¹", "mini/t2": "²", "mini/t3": "³", "mini/t4": "¹", "guest/t1": "³"})

    def test_parse_info_reads_the_account(self):
        raw = json.dumps({"labels": {"account": " main ", "space": "dev"}, "parent": None})
        self.assertEqual(hcgui.parse_info(raw, "t1"), hcgui.Info("dev", "", True, "main"))
        self.assertEqual(hcgui.parse_info('{"labels": {"account": 3}}', "t1").account, "")

    def test_with_mark_never_loses_the_mark_and_fits(self):
        self.assertEqual(hcgui.with_mark("tracker", "²", 30), "tracker²")
        self.assertEqual(hcgui.with_mark("tracker", "²", 6), "trac…²")
        self.assertEqual(hcgui.with_mark("tracker", "", 6), "track…")
        self.assertEqual(hcgui.with_mark("t", "¹", 2), "t¹")
        for room in range(0, 12):
            for name in ("tracker", "a", "日本語の名前"):
                text = hcgui.with_mark(name, "³", room)
                self.assertLessEqual(hcgui.text_width(text), room, (name, room))
                if room >= 2:
                    self.assertTrue(text.endswith("³"), (name, room, text))

    def test_tab_labels_carry_the_mark(self):
        self.assertEqual(hcgui.tab_label({"label": "tracker", "mark": "²"}), "tracker²")
        self.assertEqual(hcgui.tab_label({"label": "tracker", "mark": "x"}), "tracker")  # only a known mark
        self.assertEqual(hcgui.tab_label({"label": "tracker"}), "tracker")
        segs, _, _ = hcgui.flow_tabs(["averyveryverylongname¹"], 12)
        self.assertEqual(segs[0].text, " ● averyv…¹ ")  # 8 columns for the label: the mark stays

    def test_ascii_screen_stand_ins(self):
        with mock.patch.object(hcgui, "utf8_screen", return_value=False):
            self.assertEqual(hcgui.glyph("a¹ b² c³"), "a1 b2 c3")


class KeychainTests(unittest.TestCase):
    """The keychain check: its call, its answer, its schedule, its line (pure)."""

    def test_the_call_is_an_argument_list_on_the_home_machine(self):
        args = hcgui.exec_args("mini", hcgui.KEYCHAIN_SCRIPT)
        self.assertEqual(args, ["exec", "--json", "--timeout", "20", "--on", "mini", "/bin/sh", "-c",
                                hcgui.KEYCHAIN_SCRIPT])
        self.assertNotIn("--on", hcgui.exec_args(hcgui.LOCAL, hcgui.KEYCHAIN_SCRIPT))
        self.assertIn("show-keychain-info", hcgui.KEYCHAIN_SCRIPT)
        self.assertNotIn("unlock", hcgui.KEYCHAIN_SCRIPT)  # it never unlocks, never asks for a password

    def test_parse(self):
        parse = hcgui.parse_keychain
        self.assertEqual(parse(exec_json(0, 'Keychain "/Users/x/Library/Keychains/login.keychain-db" no-timeout\n')),
                         "unlocked")
        self.assertEqual(parse(exec_json(36, "security: SecKeychainCopySettings /Users/x/Library/Keychains/login."
                                             "keychain-db: User interaction is not allowed.\n")), "locked")
        self.assertEqual(parse(exec_json(1, "")), "locked")  # any other exit of security
        self.assertEqual(parse(exec_json(50, "security: SecKeychainCopySettings x: The specified keychain could not "
                                             "be found.\n")), "failed")
        self.assertEqual(parse(exec_json(None)), "failed")  # ended by a signal
        self.assertEqual(parse(exec_json(0, timed_out=True)), "failed")
        self.assertEqual(parse("junk"), "failed")
        self.assertEqual(parse('{"code": 0, "stderr": 5}'), "failed")
        self.assertEqual(parse('{"code": 0, "stderr": "%%%"}'), "failed")

    def test_check_keychain_reports_hc_failures_as_failed(self):
        hc = FakeHc([])
        self.assertEqual(hcgui.check_keychain("mini", hc), "unlocked")
        self.assertEqual(hc.calls[-1], tuple(hcgui.exec_args("mini", hcgui.KEYCHAIN_SCRIPT)))
        hc.keychain = (36, "User interaction is not allowed.")
        self.assertEqual(hcgui.check_keychain("mini", hc), "locked")
        hc.fail = '{"error":{"kind":"machine_unknown","message":"unknown machine"}}'
        self.assertEqual(hcgui.check_keychain("mini", hc), "failed")

    def test_the_schedule_start_then_every_four_hours(self):
        due = hcgui.keychain_due
        self.assertTrue(due(None, "unknown", 0.0))  # at the start
        self.assertFalse(due(100.0, "unlocked", 100.0 + 4 * 3600 - 1))
        self.assertTrue(due(100.0, "unlocked", 100.0 + 4 * 3600))
        self.assertFalse(due(100.0, "locked", 159.0))  # locked: again a minute later, so the line goes soon
        self.assertTrue(due(100.0, "locked", 160.0))
        self.assertFalse(due(100.0, "failed", 399.0))
        self.assertTrue(due(100.0, "failed", 400.0))

    def test_failed_checks_back_off_to_the_four_hours(self):
        due = hcgui.keychain_due
        waits = []
        for fails in range(1, 12):
            wait = next(w for w in range(60, 5 * 3600, 60) if due(0.0, "failed", float(w), fails))
            waits.append(wait)
        self.assertEqual(waits[:7], [300, 600, 1200, 2400, 4800, 9600, 14400])  # 5 min, doubled, then 4 hours
        self.assertEqual(set(waits[6:]), {14400})
        self.assertTrue(due(0.0, "failed", 4 * 3600.0, 10 ** 6))  # never longer than 4 hours, no overflow
        self.assertFalse(due(0.0, "unlocked", 4 * 3600.0 - 1, 9))  # the count only matters after a failure

    def test_the_line_fits(self):
        self.assertEqual(hcgui.keychain_text(29), " keychain locked: API billing")
        self.assertEqual(hcgui.keychain_text(60), " keychain locked: sessions bill the API")
        self.assertEqual(hcgui.keychain_text(11), " keychain")
        self.assertEqual(hcgui.keychain_text(5), "! key")
        self.assertEqual(hcgui.keychain_text(1), "!")
        self.assertEqual(hcgui.keychain_text(0), "")
        for room in range(0, 40):
            self.assertLessEqual(hcgui.text_width(hcgui.keychain_text(room)), room)

    def test_frame_and_line(self):
        self.assertEqual(hcgui.sidebar_frame(24, False, False, keychain=True), (22, 23, -1, 0))
        self.assertEqual(hcgui.keychain_line(24, False, True), 22)
        self.assertEqual(hcgui.keychain_line(24, True, True), 21)  # the strip's "› open" below it
        self.assertEqual(hcgui.keychain_line(24, False, False), -1)
        self.assertEqual(hcgui.sidebar_frame(24, True, False, keychain=True), (21, 23, -1, 1))
        for height in range(0, 12):
            for strip in (False, True):
                body, arrow, opener, extra = hcgui.sidebar_frame(height, True, False, strip, keychain=True)
                y = hcgui.keychain_line(height, strip, True)
                if y >= 0:
                    self.assertEqual(y, body + extra, (height, strip))  # right below the list and the message
                    self.assertNotIn(y, (arrow, opener))
                self.assertGreaterEqual(body, 1 if height >= 2 else 0, (height, strip))
        self.assertEqual(hcgui.sidebar_frame(20, True, False, message_lines=3), (16, 19, -1, 3))
        self.assertEqual(hcgui.sidebar_frame(4, True, False, message_lines=3), (2, 3, -1, 1))

    def test_a_click_on_the_line(self):
        self.assertEqual(hcgui.sidebar_hit(22, 23, -1, {22: hcgui.NEW_SPACE}, 3, keychain_y=22), ("keychain", None))


class DevServerTests(unittest.TestCase):
    """The dev servers: lsof's answer, the rows, the URL (pure)."""

    def test_parse_lsof(self):
        devs = hcgui.parse_dev_servers(LSOF)
        self.assertEqual([(d.port, d.folder, d.pid) for d in devs],
                         [(3917, "/Users/x/dev/.wt/site/feature", 88581),
                          (5173, "/Users/x/dev/docs-site", 90001), (8080, "/Users/x", 90003)])
        self.assertEqual([d.label for d in devs], [":3917 feature", ":5173 docs-site", ":8080 x"])
        self.assertEqual(hcgui.DevServer(3000).label, ":3000")

    def test_parse_empty_and_junk(self):
        self.assertEqual(hcgui.parse_dev_servers(""), [])
        self.assertEqual(hcgui.parse_dev_servers("\n--cwd\n"), [])  # lsof found nothing
        self.assertEqual(hcgui.parse_dev_servers("pX\ncnode\nf1\nn*:http\nf2\nn*:0\nf3\nn*:70000\nf4\nnjunk\n"), [])

    def test_listen_port(self):
        self.assertEqual(hcgui.listen_port("*:3917"), 3917)
        self.assertEqual(hcgui.listen_port("[::]:3000"), 3000)
        self.assertEqual(hcgui.listen_port("0.0.0.0:80"), 80)
        self.assertEqual(hcgui.listen_port("100.64.1.2:3000"), 3000)
        for name in ("127.0.0.1:3000", "[::1]:3000", "localhost:3000", "[::ffff:127.0.0.1]:3000", "*:", "*:65536"):
            self.assertIsNone(hcgui.listen_port(name), name)

    def test_the_script_is_fixed_and_lists_node_only(self):
        self.assertIn("-sTCP:LISTEN -a -c node", hcgui.DEV_SCRIPT)
        self.assertEqual(hcgui.exec_args("mini", hcgui.DEV_SCRIPT)[-3:], ["/bin/sh", "-c", hcgui.DEV_SCRIPT])

    def test_fetch(self):
        hc = FakeHc([])
        hc.lsof = LSOF
        self.assertEqual([d.port for d in hcgui.fetch_dev_servers("mini", hc)], [3917, 5173, 8080])
        hc.fail = '{"error":{"kind":"x","message":"down"}}'
        self.assertIsNone(hcgui.fetch_dev_servers("mini", hc))

    def test_the_schedule(self):
        self.assertTrue(hcgui.dev_due(None, 5.0))
        self.assertFalse(hcgui.dev_due(10.0, 69.0))
        self.assertTrue(hcgui.dev_due(10.0, 70.0))

    def test_home_host(self):
        machines = [hcgui.Machine("mini", "me@mini"), hcgui.Machine("v6", "me@[fd00::1]:22"),
                    hcgui.Machine("port", "me@box.lan:2222"), hcgui.Machine("alias", "minihost"),
                    hcgui.Machine("via", "wsl.exe -e sh -c", via=True), hcgui.Machine("bad", "me@-oProxy")]
        self.assertEqual(hcgui.home_host(machines, "mini"), "mini")
        self.assertEqual(hcgui.home_host(machines, "v6"), "[fd00::1]")
        self.assertEqual(hcgui.home_host(machines, "port"), "box.lan")
        self.assertEqual(hcgui.home_host(machines, "alias"), "minihost")
        self.assertEqual(hcgui.home_host(machines, "via"), "via")  # its hc name
        self.assertEqual(hcgui.home_host(machines, "bad"), "")
        self.assertEqual(hcgui.home_host([], "mini"), "mini")
        self.assertEqual(hcgui.home_host(machines, hcgui.LOCAL), "localhost")

    def test_open_url_args_are_a_list_and_checked(self):
        self.assertEqual(hcgui.open_url_args("mini", 3917), ["/usr/bin/open", "http://mini:3917/"])
        self.assertEqual(hcgui.open_url_args("[fd00::1]", 1), ["/usr/bin/open", "http://[fd00::1]:1/"])
        self.assertEqual(hcgui.open_url_args("mini", 65535)[1], "http://mini:65535/")
        for port in (0, 65536, -1, "3917", 3917.0, True, None):
            with self.assertRaises(ValueError, msg=port):
                hcgui.open_url_args("mini", port)
        for host in ("", "-oProxy", "a b", "mini;rm -rf ~", "mini/x", "$(id)", "mini\n"):
            with self.assertRaises(ValueError, msg=host):
                hcgui.open_url_args(host, 3917)

    def test_open_url_never_runs_in_tests(self):
        with mock.patch.object(hcgui.subprocess, "Popen") as popen:
            self.assertFalse(hcgui.open_url("mini", 3917))  # HCGUI_GHOSTTY=0 (set for all tests)
            with mock.patch.dict(os.environ, {"HCGUI_GHOSTTY": "1", "HCGUI_BROWSER": "0"}):
                self.assertFalse(hcgui.open_url("mini", 3917))
            popen.assert_not_called()
            with mock.patch.dict(os.environ, {"HCGUI_GHOSTTY": "1", "HCGUI_BROWSER": "1"}):
                self.assertTrue(hcgui.open_url("mini", 3917))
            popen.assert_called_once()
            self.assertEqual(popen.call_args[0][0], ["/usr/bin/open", "http://mini:3917/"])  # a list: no shell
            self.assertNotIn("shell", popen.call_args[1])


class SwitchFileTests(unittest.TestCase):
    """The shared files "agents" and "devservers" (shown by default) next to "servers" (hidden by default)."""

    def test_defaults_and_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            self.assertTrue(hcgui.read_agents_shown(state))
            self.assertTrue(hcgui.read_devs_shown(state))
            hcgui.write_agents_shown(False, state)
            hcgui.write_devs_shown(False, state)
            self.assertEqual(hcgui.read_text(state / "agents"), "hidden")
            self.assertEqual(hcgui.read_text(state / "devservers"), "hidden")
            self.assertFalse(hcgui.read_agents_shown(state))
            self.assertFalse(hcgui.read_devs_shown(state))
            hcgui.write_agents_shown(True, state)
            self.assertTrue(hcgui.read_agents_shown(state))
            (state / "devservers").write_text("junk\n")
            self.assertTrue(hcgui.read_devs_shown(state))  # junk: the default

    def test_the_usage_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            self.assertTrue(hcgui.read_usage_shown(state))  # no file: shown
            hcgui.write_usage_shown(False, state)
            self.assertEqual((state / "usagelines").read_text(), "hidden\n")  # the same words as the others
            self.assertFalse(hcgui.read_usage_shown(state))
            hcgui.write_usage_shown(True, state)
            self.assertEqual((state / "usagelines").read_text(), "shown\n")
            self.assertTrue(hcgui.read_usage_shown(state))
            (state / "usagelines").write_text("junk\n")
            self.assertTrue(hcgui.read_usage_shown(state))  # junk: the default
            self.assertFalse((state / "usage").exists())  # usage.sh's folder: never this switch

    def test_the_usage_switch_leaves_usage_sh_folder_alone(self):
        # on a one-Mac setup the sidebar's state folder is the one usage.sh saves into (usage/<name>.json): the
        # switch must neither fail on that folder nor take its place
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            folder = state / "usage"
            folder.mkdir()
            (folder / "claude.json").write_text("saved\n")
            for shown in (False, True, False):
                hcgui.write_usage_shown(shown, state)
                self.assertEqual(hcgui.read_usage_shown(state), shown)
            self.assertEqual(sorted(p.name for p in state.iterdir()), ["usage", "usagelines"])  # no temp file
            self.assertEqual([p.name for p in folder.iterdir()], ["claude.json"])
            self.assertEqual((folder / "claude.json").read_text(), "saved\n")


def sections_sample(needs=2, devs=2, agents=True, servers=True):
    spaces, rigs = hcgui.build_groups(hcgui.parse(SAMPLE), "mini", machines=["mini", "rig"])
    terms = [t for g in spaces + rigs for t in g.terms if t.is_agent][:needs]
    return hcgui.Sections(spaces, rigs, servers, terms, [hcgui.DevServer(3917 + i, "/Users/x/dev/w") for i in
                                                          range(devs)], agents)


class SectionsLayoutTests(unittest.TestCase):
    """plan_sidebar and selectable_items with "needs you", dev servers and the agents hidden (pure)."""

    def test_order_top_to_bottom(self):
        sec = sections_sample()
        plan = sec.plan(40)
        kinds = [r.kind for _, r in plan]
        heads = [r.text for _, r in plan if r.kind == "header"]
        # "needs you" last of the top part (owner, 26 Nov: at the top it moved every row as it came and went)
        self.assertEqual(heads, ["spaces", "servers", "dev servers", "needs you"])
        self.assertLess(kinds.index("dev"), kinds.index("needs"))
        self.assertLess(kinds.index("needs"), kinds.index("rule"))
        self.assertEqual(kinds[:2], ["header", "group"])
        items = sec.items()
        self.assertEqual([i.kind for i in items if i.kind in ("dev", "needs")], ["dev", "dev", "needs", "needs"])
        self.assertEqual([i for i in items if i.kind == "dev"], [hcgui.Item("dev", "", "3917"),
                                                                  hcgui.Item("dev", "", "3918")])
        for _, row in plan:  # every row's item index names its own item
            if row.item >= 0:
                item = items[row.item]
                if row.kind == "needs":
                    self.assertEqual(item, hcgui.Item("needs", "", row.term.address))
                elif row.kind == "dev":
                    self.assertEqual(item, hcgui.Item("dev", "", str(row.dev.port)))
                elif row.kind == "agent":
                    self.assertEqual(item.address, row.term.address)

    def test_empty_sections_are_not_drawn(self):
        plan = sections_sample(needs=0, devs=0).plan(40)
        heads = [r.text for _, r in plan if r.kind == "header"]
        self.assertEqual(heads, ["spaces", "servers"])
        self.assertEqual(plan[0][1].text, "spaces")

    def test_agents_hidden_no_rule_no_heading_no_rows_and_no_items(self):
        sec = sections_sample(agents=False)
        for rule in (None, 10, 3):
            plan = sec.plan(40, rule=rule)
            kinds = {r.kind for _, r in plan}
            self.assertFalse(kinds & {"rule", "agents", "agent_group", "agent", "more"}, rule)
            self.assertEqual(hcgui.rule_line(plan, 40), 40)
        self.assertFalse([i for i in sec.items() if i.kind == "agent"])
        crowded = sections_sample(agents=False, devs=30)  # the upper part gets every line and scrolls
        last = len(crowded.items()) - 1
        plan = crowded.plan(20, cursor=last)
        self.assertTrue(any(r.item == last for _, r in plan))
        self.assertEqual(max(y for y, _ in plan), 19)

    def test_small_heights_with_every_section(self):
        for agents in (True, False):
            sec = sections_sample(needs=3, devs=3, agents=agents)
            items = sec.items()
            for height in range(0, 30):
                for rule in (None, 2, height // 2, height):
                    for cursor in range(len(items)):
                        plan = sec.plan(height, cursor, rule=rule)
                        ys = [y for y, _ in plan]
                        case = (agents, height, rule, cursor)
                        self.assertEqual(len(ys), len(set(ys)), case)  # one row per line
                        self.assertTrue(all(0 <= y < height for y in ys), case)
                        if height >= 4 and items[cursor].kind != "agent":
                            self.assertTrue(any(r.item == cursor for _, r in plan), case)  # the cursor's row shows

    def test_agents_hidden_a_stored_split_gives_the_upper_part_every_line(self):
        crowded = sections_sample(agents=False, devs=30)
        for rule in (3, 5, 10):
            self.assertEqual([y for y, _ in crowded.plan(20, rule=rule)], list(range(20)), rule)  # no blank lines

    def test_the_strip_has_the_same_rows(self):
        sec = sections_sample()
        self.assertEqual([(y, r.kind, r.item) for y, r in sec.plan(30, compact=True)],
                         [(y, r.kind, r.item) for y, r in sec.plan(30)])


class ExtrasSidebarTests(unittest.TestCase):
    """The Sidebar with "needs you", account marks, the keychain warning, dev servers, the agents hidden."""

    MACHINES = [("mini", "me@mini"), ("guest", "guest@mini")]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"
        terms = [tterm("mini/t1", "/Users/x/dev", "claude-code", "atlas", "idle", 3),
                 tterm("mini/t2", "/Users/x/dev", "claude-code", "tracker", "done", 2),
                 tterm("mini/t3", "/Users/x/dev/other", "claude-code", "o1", "blocked", 1),
                 tterm("mini/t4", "/Users/x/dev/other", "zsh", "sh"),
                 tterm("mini/t5", "/Users/x/dev", "claude-code", "gecko", "working", 0),
                 tterm("guest/t1", "/Users/guest", "claude-code", "harry", "done", 1)]
        infos = {"mini/t1": {"labels": {"account": "main"}}, "mini/t2": {"labels": {"account": "work"}},
                 "mini/t3": {"labels": {"account": "team"}}}
        self.hc = FakeHc(terms, infos, machines=self.MACHINES)
        self.hc.lsof = LSOF
        for target, value in ((hcgui, {"run_hc": self.hc, "FIRST": "mini"}),
                              (hcgui.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scr = FakeScr(40, 30)
        self.side = hcgui.Sidebar(self.scr, self.state, self.win)
        self.side.refresh_once()
        self.now = 1000.0
        self.side.refresh_extras(self.now)
        self.side.sync()
        self.side.draw()

    key = SidebarLogicTests.key

    def mouse(self, x, y, bstate=None):
        with pressed(x, y) if bstate is None else mouse_at(x, y, bstate):
            self.key(hcgui.curses.KEY_MOUSE)

    def lines(self):
        return [hcgui.glyph(line) for line in self.scr.lines()]

    def lock(self):
        self.hc.keychain = (36, "security: SecKeychainCopySettings x: User interaction is not allowed.\n")
        self.now += hcgui.KEYCHAIN_SECONDS
        self.side.refresh_extras(self.now)
        self.side.draw()

    def needs_lines(self):
        """The "needs you" section's lines, its heading first ([] when it is not drawn)."""
        lines = self.lines()
        if " needs you" not in lines:
            return []
        at = lines.index(" needs you")
        end = next((i for i in range(at + 1, len(lines)) if not lines[i].strip()), len(lines))
        return lines[at:end]

    def test_needs_you_below_the_dev_servers(self):
        # owner, 26 Nov: at the top it moved every row below it as it came and went
        lines = self.lines()
        self.assertEqual(lines[0], " spaces")
        at = lines.index(" needs you")
        self.assertLess(lines.index(" dev servers"), at)
        self.assertEqual(lines[at - 1], "")
        self.assertTrue(lines[at + 1].startswith(hcgui.glyph(" ● o1³")) and lines[at + 1].endswith("blocked"),
                        lines[at + 1])
        self.assertTrue(lines[at + 2].startswith(hcgui.glyph(" ● harry³ · guest@mini")) and
                        lines[at + 2].endswith("done"), lines[at + 2])  # not on the home machine: its server too
        self.assertTrue(lines[at + 3].startswith(hcgui.glyph(" ● tracker²")) and lines[at + 3].endswith("done"),
                        lines[at + 3])

    def test_enter_on_a_needs_row_shows_it_and_clears_a_done(self):
        self.key("j")  # the cursor starts on the current group: down to the needs rows
        while self.side.cursor_item().kind != "needs" or self.side.cursor_item().address != "mini/t2":
            self.key("j")
        self.key(10)
        self.assertEqual(hcgui.current_target(self.win), "mini/t2")
        self.assertEqual(hcgui.read_seen(self.state), {"mini/t2": 2})
        self.assertNotIn("tracker", " ".join(self.needs_lines()))  # looked at: gone from "needs you"
        hcgui.show("mini/t1", self.win)  # another terminal shown: tracker stays seen until its next done
        self.key(-1)
        self.assertNotIn("tracker", " ".join(self.needs_lines()))
        self.hc.find("mini/t2")["turn"] = 3  # it worked again and is done again
        self.side.refresh_once()
        self.key(-1)
        self.assertIn("tracker", " ".join(self.needs_lines()))

    def test_a_click_on_a_needs_row_of_a_hidden_server_shows_it(self):
        self.assertFalse(self.side.servers_shown())
        y = next(i for i, line in enumerate(self.lines()) if "harry" in line)
        self.mouse(5, y)
        self.assertEqual(hcgui.current_target(self.win), "guest/t1")
        self.assertEqual(hcgui.read_seen(self.state), {"guest/t1": 1})
        self.assertNotIn("harry", " ".join(self.needs_lines()))

    def test_blocked_stays_until_it_is_no_longer_blocked(self):
        y = next(i for i, line in enumerate(self.lines()) if " o1" in line and "blocked" in line)
        self.mouse(5, y)
        self.assertEqual(hcgui.current_target(self.win), "mini/t3")
        self.assertNotIn("o1", " ".join(self.needs_lines()))  # shown here: left out
        hcgui.show("mini/t1", self.win)
        self.key(-1)
        self.assertIn("o1", " ".join(self.needs_lines()))

    def test_marks_on_agent_rows_and_tabs(self):
        lines = self.lines()
        agents = lines[next(i for i, line in enumerate(lines) if line.startswith(" agents")):]
        text = "\n".join(agents)
        self.assertIn(hcgui.glyph("atlas¹"), text)
        self.assertIn(hcgui.glyph("  ● gecko"), agents)  # no label: no mark (and no status word after it)
        # tracker and o1 need you: listed only there, at the top, with their marks (owner, 24 Nov: "only top")
        top = "\n".join(lines[:lines.index(agents[0])])
        for name in ("tracker²", "o1³"):
            self.assertIn(hcgui.glyph(name), top)
            self.assertNotIn(hcgui.glyph(name), text)
        snap = hcgui.read_snapshot(self.win)
        self.assertEqual({t["label"]: t["mark"] for t in snap["tabs"]},
                         {"atlas": "¹", "tracker": "²", "gecko": ""})
        self.assertEqual(hcgui.tabs_title(snap, "mini/t2"), "tracker · me@mini")  # never in the title

    def test_marks_in_the_strip(self):
        self.key("c")
        for width in (6, 8, 12):
            self.scr.width = width
            self.side.draw()
            atlas = [line for line in self.scr.lines() if "¹" in line or "1" in hcgui.glyph(line)]
            self.assertTrue(atlas, width)
            self.assertTrue(all(hcgui.text_width(line) <= width - 1 for line in self.scr.lines()), width)

    def test_labels_of_other_machines_are_fetched_once_not_every_round(self):
        gets = [c for c in self.hc.calls if c[0] == "get"]
        self.assertIn(("get", "guest/t1", "--json"), gets)
        self.hc.calls.clear()
        self.side.refresh_once()
        self.assertFalse([c for c in self.hc.calls if c[0] == "get"])  # known: no hc get until the next full round
        self.side.refresh_once(full=True)
        self.assertIn(("get", "guest/t1", "--json"), self.hc.calls)
        self.assertEqual(self.side.infos["guest/t1"], hcgui.Info())  # no space, no parent off the home machine

    def test_keychain_line_only_while_locked(self):
        self.assertNotIn("keychain", " ".join(self.lines()))
        self.lock()
        lines = self.lines()
        self.assertEqual(lines[38], " keychain locked: API billing")
        self.assertEqual(self.side.keychain_y, 38)
        self.assertEqual(self.scr.cells[(38, 1)][1], (1 << 8) | hcgui.curses.A_BOLD)  # red
        self.assertEqual(lines[39], hcgui.glyph(fold_line("open")))
        self.hc.keychain = (0, "")
        self.now += hcgui.KEYCHAIN_LOCKED_SECONDS  # locked: checked again a minute later
        self.side.refresh_extras(self.now)
        self.side.draw()
        self.assertNotIn("keychain", " ".join(self.lines()))
        self.hc.fail = '{"error":{"kind":"x","message":"down"}}'
        self.now += hcgui.KEYCHAIN_SECONDS
        self.side.refresh_extras(self.now)
        self.side.draw()
        self.assertEqual(self.side.keychain, "failed")
        self.assertNotIn("keychain", " ".join(self.lines()))  # unknown: nothing

    def test_keychain_checked_at_start_then_every_four_hours(self):
        calls = lambda: sum(1 for c in self.hc.calls if hcgui.KEYCHAIN_SCRIPT in c)
        self.assertEqual(calls(), 1)  # at the start
        for step in (60.0, 3600.0, 4 * 3600.0 - 1):
            self.side.refresh_extras(self.now + step)
        self.assertEqual(calls(), 1)
        self.side.refresh_extras(self.now + 4 * 3600.0)
        self.assertEqual(calls(), 2)
        self.key("r")  # r: now
        self.side.refresh_extras(self.now + 4 * 3600.0 + 1)
        self.assertEqual(calls(), 3)

    def test_keychain_click_shows_the_unlock_terminal_or_opens_one(self):
        self.lock()
        self.mouse(3, self.side.keychain_y)
        run = [c for c in self.hc.calls if c[0] == "run"]
        self.assertEqual(len(run), 1)
        self.assertEqual(run[0][:7], ("run", "--bg", "--json", "--no-parent", "--on", "mini", "--name"))
        self.assertEqual(run[0][7], "unlock")
        self.assertNotIn("security", " ".join(run[0]))  # nothing is run or typed in it
        address = hcgui.current_target(self.win)
        self.assertEqual(self.hc.find(address)["name"], "unlock")
        notice = " ".join(self.lines())
        self.assertIn("Claude sessions bill the API", notice)  # the whole text, wrapped
        time.sleep(hcgui.MOUSE_QUIET)
        hcgui.show("mini/t1", self.win)
        self.mouse(3, self.side.keychain_y)  # it exists now: shown, not made again
        self.assertEqual(len([c for c in self.hc.calls if c[0] == "run"]), 1)
        self.assertEqual(hcgui.current_target(self.win), address)
        self.assertFalse([c for c in self.hc.calls if c[0] in ("send", "keys", "put")])

    def test_dev_servers_section_and_open(self):
        lines = self.lines()
        at = lines.index(" dev servers")
        self.assertEqual(lines[at + 1:at + 4], [" :3917 feature", " :5173 docs-site", " :8080 x"])  # col 1
        self.assertLess(at, next(i for i, line in enumerate(lines) if line.startswith("─")))
        with mock.patch.object(hcgui, "open_url", return_value=False) as opened:
            self.mouse(5, at + 1)
        opened.assert_called_once_with("mini", 3917)
        self.assertIn("http://mini:3917/", "".join(self.lines()))  # the notice wraps: the whole address

    def test_dev_servers_hidden_and_shown_with_w_and_polled_only_while_shown(self):
        self.key("w")
        self.assertFalse(hcgui.read_devs_shown(self.state))
        self.assertNotIn(" dev servers", self.lines())
        self.hc.calls.clear()
        self.side.refresh_extras(self.now + 600)
        self.assertFalse([c for c in self.hc.calls if hcgui.DEV_SCRIPT in c])
        self.key("w")
        self.side.refresh_extras(self.now + 601)
        self.assertTrue([c for c in self.hc.calls if hcgui.DEV_SCRIPT in c])  # asked at once when shown
        self.assertIn(" dev servers", self.lines())

    def test_no_dev_servers_no_section(self):
        self.hc.lsof = "\n--cwd\n"
        self.side.refresh_extras(self.now + hcgui.DEV_SECONDS)
        self.side.draw()
        self.assertNotIn(" dev servers", self.lines())

    def test_agents_hidden_with_g_and_back(self):
        while self.side.cursor_item().kind != "agent":
            self.key("j")
        self.key("g")
        self.assertFalse(hcgui.read_agents_shown(self.state))
        lines = self.lines()
        self.assertFalse(any(line.startswith(" agents") or line.startswith("─") for line in lines))
        self.assertEqual(self.side.rule_y, -1)
        self.assertNotEqual(self.side.cursor_item().kind, "agent")  # back to a row that is drawn
        self.key("]")
        self.assertIsNone(hcgui.read_split(self.state))  # [ and ] do nothing while hidden
        self.assertIn("agents hidden", " ".join(self.lines()))
        self.key("g")
        self.assertTrue(any(line.startswith(" agents") for line in self.lines()))

    def test_agents_hidden_from_the_menu_keeps_needs_you(self):
        for _ in range(20):  # an agent's menu: the agents' switch is in its own section's menus only
            if self.side.cursor_item().kind == "agent":
                break
            self.key("j")
        self.key("a")
        entry = next(e for e in self.side.menu.entries if e.action == "agents")
        self.assertEqual(entry.label, "Hide agents")
        self.key("g")  # the entry's letter
        self.assertIsNone(self.side.menu)
        self.assertFalse(hcgui.read_agents_shown(self.state))
        self.assertIn(" needs you", self.lines())

    def test_agents_hidden_drops_a_drag(self):
        y = self.side.rule_y
        self.mouse(3, y, PRESS1)
        self.assertIsNotNone(self.side.drag_y)
        self.side.toggle_agents()
        self.assertIsNone(self.side.drag_y)

    def keychain_calls(self):
        return [c for c in self.hc.calls if c[0] == "exec" and hcgui.KEYCHAIN_SCRIPT in c]

    def test_extras_wait_for_a_listing_and_start_over_when_the_mini_turns_up(self):
        engine = hcgui.Engine(self.state, self.win)
        self.hc.fail = '{"error":{"kind":"x","message":"down"}}'  # the first hc ls fails (the network not up yet)
        engine.refresh_once()
        self.assertTrue(engine.loaded.is_set())
        self.hc.calls.clear()
        engine.refresh_extras(self.now)
        self.assertFalse([c for c in self.hc.calls if c[0] == "exec"])  # no home machine known: nothing asked
        self.hc.fail = ""
        mini = self.hc.terms
        self.hc.terms = []  # listed, but no terminal of the mini yet: this Mac is home for now
        engine.refresh_once()
        engine.refresh_extras(self.now)
        self.assertEqual([("--on" in c) for c in self.keychain_calls()], [False])
        self.assertEqual((engine.keychain, len(engine.devs)), ("unlocked", 3))
        self.hc.terms = mini  # the mini turns up: its keychain is asked at once, not 4 hours later
        engine.refresh_once()
        self.hc.calls.clear()
        self.hc.keychain = (36, "User interaction is not allowed.")
        engine.refresh_extras(self.now + 60)
        self.assertEqual([c[4:6] for c in self.keychain_calls()], [("--on", "mini")])
        self.assertEqual(engine.keychain, "locked")
        dev = [c for c in self.hc.calls if c[0] == "exec" and hcgui.DEV_SCRIPT in c]
        self.assertEqual([c[4:6] for c in dev], [("--on", "mini")])
        hcgui.write_devs_shown(False, self.state)
        self.hc.terms = []  # home moves again while the dev servers are hidden: this Mac's are not kept for it
        engine.refresh_once()
        engine.refresh_extras(self.now + 120)
        self.assertEqual(engine.devs, [])

    def test_showing_the_dev_servers_does_not_check_the_keychain(self):
        before = len(self.keychain_calls())
        self.key("w")
        self.key("w")
        self.side.refresh_extras(self.now + 1)
        self.assertEqual(len(self.keychain_calls()), before)
        self.assertTrue([c for c in self.hc.calls if hcgui.DEV_SCRIPT in c])

    def test_failed_checks_back_off(self):
        self.hc.fail = '{"error":{"kind":"x","message":"down"}}'
        start = self.now + hcgui.KEYCHAIN_SECONDS
        at = []
        for minute in range(0, 4 * 60, 1):
            before = len(self.keychain_calls())
            self.side.refresh_extras(start + minute * 60.0)
            if len(self.keychain_calls()) > before:
                at.append(minute)
        self.assertEqual(at, [0, 5, 15, 35, 75, 155])  # 5, 10, 20, 40, 80 minutes apart: not every 5 minutes
        self.assertEqual((self.side.keychain, self.side.keychain_fails), ("failed", 6))
        self.hc.fail = ""
        self.side.refresh_extras(start + 155 * 60.0 + hcgui.KEYCHAIN_SECONDS)
        self.assertEqual((self.side.keychain, self.side.keychain_fails), ("unlocked", 0))

    def test_hiding_the_agents_puts_the_cursor_on_the_current_group(self):
        while self.side.cursor_item().kind != "agent":
            self.key("j")
        self.key("g")
        self.assertEqual(self.side.cursor_item(), hcgui.Item("group", self.side.cur, ""))

    def test_hiding_the_dev_servers_puts_the_cursor_on_the_current_group(self):
        while self.side.cursor_item().kind != "dev":
            self.key("j")
        self.key("w")
        self.assertEqual(self.side.cursor_item(), hcgui.Item("group", self.side.cur, ""))

    def test_agents_hidden_in_another_window_drops_a_drag(self):
        y = self.side.rule_y
        self.mouse(3, y, PRESS1)
        self.assertIsNotNone(self.side.drag_y)
        hcgui.write_agents_shown(False, self.state)  # another window hides them
        self.side.draw()
        self.assertIsNone(self.side.drag_y)
        hcgui.write_agents_shown(True, self.state)  # and shows them again before the release
        self.side.draw()
        self.mouse(3, y - 4, RELEASE1)
        self.assertIsNone(hcgui.read_split(self.state))  # the old drag never lands

    def test_a_menu_never_covers_the_keychain_line(self):
        self.lock()
        ends = set()
        for _ in range(12):  # the separator up a line at a time: the agents' menus end on every line once
            self.key("[")
            for y, item in sorted(self.side.rows.items()):  # a menu on every row drawn
                items = self.side.items()
                self.side.cursor, self.side.cursor_pos = item, items.index(item)
                self.side.draw()
                self.key("a")
                if self.side.menu is None:
                    continue
                box = self.side.menu_at
                ends.add(box.top + box.shown + 1)  # its lower border's line
                self.assertEqual(self.lines()[self.side.keychain_y], " keychain locked: API billing", (y, item))
                self.side.menu = None
                self.side.draw()
        self.assertIn(self.side.keychain_y - 1, ends)  # one menu ended right above the line

    def test_the_whole_sidebar_at_30x40(self):
        self.lock()
        lines = self.lines()
        self.assertEqual(lines[0], " spaces")
        self.assertIn(" needs you", lines)
        self.assertIn(" dev servers", lines)
        self.assertTrue(any(line.startswith(" agents") for line in lines))
        self.assertEqual(lines[38], " keychain locked: API billing")
        self.assertTrue(all(hcgui.text_width(line) <= 29 for line in self.scr.lines()))

    def test_help_lists_the_new_keys_and_the_marks(self):
        lines = hcgui.help_lines(29, 40)
        self.assertIn(" g       show/hide agents", lines)
        self.assertIn(" w       dev servers on/off", lines)
        at = lines.index(" u       show/hide usage")
        self.assertEqual(lines[at + 1], "         (or right click it)")  # the right click on a usage line
        self.assertIn(" ¹       claude, main", lines)
        self.assertIn(" ²       work", lines)
        self.assertIn(" ³       other, guest", lines)


class SettingsTests(unittest.TestCase):
    """HCGUI_FIRST, HCGUI_MARKS, HCGUI_SHARED_USER, HCGUI_SHARED_MARK, HCGUI_DEV_PROGRAM and HCGUI_KEYCHAIN."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"

    def engine(self, hc, first=""):
        for target, value in ((hcgui, {"run_hc": hc, "FIRST": first}),):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        engine = hcgui.Engine(self.state, self.win)
        engine.refresh_once()
        return engine

    def test_first_machine(self):
        M = hcgui.Machine
        self.assertEqual(hcgui.first_machine([M("box", "me@box")], "mini"), "mini")  # the setting wins
        self.assertEqual(hcgui.first_machine([M("box", "me@box")], ""), "box")  # the only machine
        self.assertEqual(hcgui.first_machine(["box", "box"], ""), "box")
        self.assertEqual(hcgui.first_machine(["api", "web"], ""), hcgui.LOCAL)  # two: this Mac
        self.assertEqual(hcgui.first_machine([], ""), hcgui.LOCAL)
        self.assertEqual(hcgui.first_machine([], " "), hcgui.LOCAL)
        self.assertEqual(hcgui.first_machine([]), "mini")  # HCGUI_FIRST of the tests
        with mock.patch.object(hcgui, "FIRST", ""):
            self.assertEqual(hcgui.first_machine([M("box")]), "box")

    def test_without_mini_first_the_only_machine_is_home(self):
        hc = FakeHc([term("box/t1", "/Users/me/dev/api", "claude-code", "api", "idle"),
                     term("box/t2", "/Users/me/dev/web", "zsh", "sh"), term("t1", "/Users/x", "zsh")],
                    machines=[("box", "me@box")])
        engine = self.engine(hc)
        self.assertEqual(engine.home(), "box")
        spaces, _ = engine.groups()
        self.assertEqual([g.name for g in spaces], ["api", "web"])
        self.assertEqual([(g.machine, g.home) for g in engine.rigs_all], [("box", True), (hcgui.LOCAL, False)])

    def test_without_mini_first_and_two_machines_this_mac_is_home(self):
        hc = FakeHc([term("api/t1", "/Users/me/dev/api", "zsh"), term("t1", "/Users/x/dev/docs", "zsh")],
                    machines=[("api", "me@api"), ("web", "me@web")])
        engine = self.engine(hc)
        self.assertEqual(engine.home(), hcgui.LOCAL)
        spaces, _ = engine.groups()
        self.assertEqual([g.name for g in spaces], ["docs"])

    def test_parse_marks(self):
        self.assertEqual(hcgui.parse_marks("claude=¹, main = ¹ ,work=²"), {"claude": "¹", "main": "¹", "work": "²"})
        self.assertEqual(hcgui.parse_marks("a=¹,a=²"), {"a": "²"})
        for junk in ("", "x", "=¹", "a=", "a=¹²", "a=x", "a=7", "a= ", "a=\u0301", "a=\u4e00"):
            self.assertEqual(hcgui.parse_marks(junk), {}, junk)

    def test_no_settings_no_marks_and_no_legend(self):
        mark = hcgui.account_mark
        none = {"marks": {}, "shared_user": "", "shared_mark": "³"}
        for account, user in (("claude", ""), ("team", ""), ("", "guest"), ("", "")):
            self.assertEqual(mark("claude-code", account, user, **none), "")
        self.assertEqual(hcgui.mark_legend(**none), [])
        with mock.patch.multiple(hcgui, ACCOUNT_MARKS={}, SHARED_USER=""):
            self.assertEqual(hcgui.help_entries(), list(hcgui.KEY_HELP))
            self.assertEqual(len(hcgui.help_lines(29, 60)), 1 + len(hcgui.KEY_HELP) + len(hcgui.DOT_HELP) + 2)

    def test_shared_user_alone_and_its_mark(self):
        mark = hcgui.account_mark
        self.assertEqual(mark("claude-code", "", "guest", marks={}, shared_user="guest", shared_mark="⁴"), "⁴")
        self.assertEqual(mark("claude-code", "", "me", marks={}, shared_user="guest", shared_mark="⁴"), "")
        self.assertEqual(mark("claude-code", "x", "guest", marks={}, shared_user="guest", shared_mark="⁴"), "")
        self.assertEqual(mark("zsh", "", "guest", marks={}, shared_user="guest", shared_mark="⁴"), "")
        self.assertEqual(hcgui.mark_legend({}, "guest", "⁴"), [("⁴", "guest")])
        self.assertEqual(hcgui.mark_legend({"a": "¹", "b": "³"}, "guest", "³"), [("¹", "a"), ("³", "b, other, guest")])

    def test_the_legend_names_a_subscription_by_its_display_name(self):
        # an HCGUI_MARKS label is a subscription's name (its usage file's name): its display name is drawn, as on
        # its usage line; "other" and the shared ssh user are no subscriptions and stay as they are
        names = {"account:a": "Alpha", "account:guest": "G", "account:other": "O", "space:b": "B"}
        self.assertEqual(hcgui.mark_legend({"a": "¹", "b": "³", "c": "¹"}, "guest", "³", names),
                         [("¹", "Alpha, c"), ("³", "b, other, guest")])
        self.assertEqual(hcgui.mark_legend({"a": "¹"}, "", "³", {}), [("¹", "a"), ("³", "other")])
        with mock.patch.multiple(hcgui, ACCOUNT_MARKS={"work": "²"}, SHARED_USER=""):
            self.assertEqual(hcgui.help_entries({"account:work": "Team"})[-2:], [("²", "Team"), ("³", "other")])
            self.assertEqual(hcgui.help_entries()[-2:], [("²", "work"), ("³", "other")])
            self.assertIn(" ²       Team", hcgui.help_lines(29, 60, {"account:work": "Team"}))

    def test_settings_read_at_start(self):
        code = ("import json, hcgui; print(json.dumps([hcgui.FIRST, hcgui.ACCOUNT_MARKS, hcgui.SHARED_USER, "
                "hcgui.SHARED_MARK, hcgui.DEV_PROGRAM, hcgui.mark_legend()]))")

        def read(**settings):
            env = {k: v for k, v in os.environ.items() if not k.startswith("HCGUI_")}
            env.update(HCGUI_GHOSTTY="0", HCGUI_STATE=str(self.state), PYTHONDONTWRITEBYTECODE="1", **settings)
            out = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, env=env, capture_output=True,
                                 text=True, timeout=30, check=False)
            self.assertEqual(out.returncode, 0, out.stderr)
            return json.loads(out.stdout)

        self.assertEqual(read(), ["", {}, "", "³", "node", []])
        self.assertEqual(read(HCGUI_FIRST=" box ", HCGUI_MARKS="a=¹,b=²", HCGUI_SHARED_USER="guest",
                              HCGUI_SHARED_MARK="⁴", HCGUI_DEV_PROGRAM="bun"),
                         ["box", {"a": "¹", "b": "²"}, "guest", "⁴", "bun",
                          [["¹", "a"], ["²", "b"], ["³", "other"], ["⁴", "guest"]]])
        self.assertEqual(read(HCGUI_SHARED_MARK="xy", HCGUI_DEV_PROGRAM="a b")[3:5], ["³", "node"])
        self.assertFalse(self.state.exists())  # importing creates no folder

    def test_dev_program(self):
        for value, want in (("bun", "bun"), (" deno ", "deno"), ("", "node"), ("-x", "node"), ("a b", "node"),
                            ("a;b", "node"), ("x" * 16, "node"), ("x" * 15, "x" * 15)):
            self.assertEqual(hcgui.dev_program(value), want, value)
        self.assertEqual(hcgui.DEV_SCRIPT, hcgui.dev_script("node"))
        self.assertIn("-sTCP:LISTEN -a -c bun -F pcn", hcgui.dev_script("bun"))
        self.assertEqual(hcgui.parse_dev_servers(LSOF, "bun"), [])
        bun = LSOF.replace("cnode\n", "cbun\n")
        self.assertEqual([d.port for d in hcgui.parse_dev_servers(bun, "bun")], [3917, 5173, 8080])
        self.assertEqual(hcgui.parse_dev_servers(bun), [])  # DEV_PROGRAM: node

    def test_keychain_off(self):
        hc = FakeHc([term("mini/t1", "/Users/x/dev/api", "zsh")], machines=[("mini", "me@mini")])
        engine = self.engine(hc, "mini")
        keychain = lambda: [c for c in hc.calls if c[0] == "exec" and hcgui.KEYCHAIN_SCRIPT in c]
        with mock.patch.dict(os.environ, {"HCGUI_KEYCHAIN": "0"}):
            self.assertFalse(hcgui.keychain_enabled())
            engine.refresh_extras(1000.0)
            engine.keychain_asked = True  # r
            engine.refresh_extras(1001.0)
        self.assertEqual(keychain(), [])
        self.assertEqual(engine.keychain, "unknown")
        self.assertTrue(hcgui.keychain_enabled())
        engine.refresh_extras(1002.0)
        self.assertEqual(len(keychain()), 1)
        self.assertEqual(engine.keychain, "unlocked")


# ---------------------------------------------------------------------------------------------------------------
# The 5-hour usage: usage.sh, the check, the lines at the bottom of the open sidebar
# ---------------------------------------------------------------------------------------------------------------
JQ = next((j for j in ("/usr/bin/jq", shutil.which("jq") or "", "/opt/homebrew/bin/jq") if j and os.access(j, os.X_OK)),
          "")


def status_input(five=None, seven=None, **extra):
    """What Claude Code hands its status line command (the fields usage.sh reads, and a few it does not)."""
    data = {"model": {"display_name": "Opus"}, "workspace": {"current_dir": "/Users/x/dev"}, **extra}
    limits = {}
    if five is not None:
        limits["five_hour"] = {"used_percentage": five[0], "resets_at": five[1]}
    if seven is not None:
        limits["seven_day"] = {"used_percentage": seven[0], "resets_at": seven[1]}
    if limits:
        data["rate_limits"] = limits
    return json.dumps(data)


def usage_line(name, used, resets, at=0):
    """One line of a file usage.sh writes."""
    return json.dumps({"name": name, "five_hour": {"used_percentage": used, "resets_at": resets}, "at": at})


@unittest.skipUnless(JQ, "no jq on this Mac")
class UsageScriptTests(unittest.TestCase):
    """usage.sh, run as Claude Code runs it: `sh usage.sh <name>`, the JSON on stdin."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.folder = self.state / "usage"
        self.now = int(time.time())

    def run_usage(self, stdin, *args, script=None, **env):
        """usage.sh with `stdin`; the result, after checking it printed nothing and ended with 0."""
        environ = {"PATH": "/usr/bin:/bin", "HOME": self._tmp.name, "HCGUI_STATE": str(self.state), **env}
        environ = {k: v for k, v in environ.items() if v is not None}
        out = subprocess.run(["/bin/sh", str(script or ROOT / "usage.sh"), *args], input=stdin, env=environ,
                             capture_output=True, text=True, timeout=30)
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, "", ""))
        return out

    def saved(self, name="claude"):
        return json.loads((self.folder / f"{name}.json").read_text())

    def files(self):
        return sorted(p.name for p in self.folder.iterdir()) if self.folder.exists() else []

    def test_writes_one_line_of_json(self):
        self.run_usage(status_input((42.4, self.now + 3600.0), (7, self.now + 86400)), "claude")
        text = (self.folder / "claude.json").read_text()
        self.assertEqual(text.count("\n"), 1)
        data = json.loads(text)
        self.assertEqual(data["name"], "claude")
        self.assertEqual(data["five_hour"], {"used_percentage": 42.4, "resets_at": self.now + 3600})  # whole seconds
        self.assertEqual(data["seven_day"], {"used_percentage": 7, "resets_at": self.now + 86400})
        self.assertLessEqual(abs(data["at"] - time.time()), 5)
        self.assertEqual(list(data), ["name", "five_hour", "seven_day", "at"])
        self.assertEqual(hcgui.parse_usage(text), [hcgui.Usage("claude", 42.4, self.now + 3600)])  # mini reads it

    def test_hidden_usage_lines_do_not_stop_the_saving(self):
        # one Mac: the sidebar's switch (u) sits in this same state folder; usage.sh still saves (a switch file named
        # "usage" took the folder's place, and mkdir failed without a word on every answer)
        hcgui.write_usage_shown(False, self.state)
        self.run_usage(status_input((42, self.now + 3600)), "claude")
        self.assertEqual(self.saved()["five_hour"]["used_percentage"], 42)
        self.assertFalse(hcgui.read_usage_shown(self.state))

    def test_seven_day_only_when_present(self):
        self.run_usage(status_input((10, self.now + 3600)), "claude-2")
        self.assertNotIn("seven_day", self.saved("claude-2"))
        self.run_usage(status_input((11, self.now + 3600), ("x", 5)), "claude-2")
        self.assertNotIn("seven_day", self.saved("claude-2"))

    def test_no_rate_limits_no_file(self):
        for stdin in (status_input(), status_input(seven=(7, self.now + 86400)),  # an API key, the first prompt
                      status_input(rate_limits={"five_hour": None}), status_input(rate_limits="x"),
                      status_input(rate_limits={"five_hour": {"used_percentage": "42", "resets_at": self.now}}),
                      status_input(rate_limits={"five_hour": {"used_percentage": 42}}),  # no resets_at
                      status_input(rate_limits={"five_hour": {"used_percentage": True, "resets_at": self.now}}),
                      "", "junk", "[1, 2]", "null"):
            self.run_usage(stdin, "claude")
            self.assertEqual([f for f in self.files() if not f.startswith(".")], [], stdin)
        self.assertEqual(self.files(), [])  # no temporary file left behind either

    def test_a_name_that_is_not_allowed_writes_nothing(self):
        stdin = status_input((42, self.now + 3600))
        for args in ((), ("",), ("a/b",), ("../x",), ("a b",), ("x" * 33,), ("é",), ("$(touch pwned)",), ("a\nb",)):
            self.run_usage(stdin, *args)
        self.assertEqual(self.files(), [])
        self.assertFalse((Path(self._tmp.name) / "pwned").exists())
        self.assertFalse((self.state / "x.json").exists())
        self.run_usage(stdin, "x" * 32)
        self.run_usage(stdin, "Work_1.b-2")
        self.assertEqual(self.files(), ["Work_1.b-2.json", "x" * 32 + ".json"])

    def fake_hc(self, fails=False, labels=None):
        """A stand-in hc in a folder of its own: it logs its arguments, one call per line; `hc get` prints a
        terminal with `labels`; `hc label` fails when asked."""
        bin_dir = Path(self._tmp.name) / "bin"
        bin_dir.mkdir(exist_ok=True)
        log = Path(self._tmp.name) / "hc.log"
        got = Path(self._tmp.name) / "get.json"
        got.write_text(json.dumps({"address": "t1", "labels": labels or {}}))
        hc = bin_dir / "hc"
        hc.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n'
                      f'if [ "$1" = get ]; then cat "{got}"; exit 0; fi\nexit {1 if fails else 0}\n')
        hc.chmod(0o755)
        return f"{bin_dir}:/usr/bin:/bin", log

    def hc_calls(self, log, verb="label"):
        return [c for c in log.read_text().splitlines() if c.startswith(verb + " ")] if log.exists() else []

    def test_a_label_already_there_is_kept(self):
        """Review, 24 Nov: a hand-set label, or one another tool resumes sessions by, is never changed."""
        for labels in ({"account": "claude-2"}, {"account": 3}):
            path, log = self.fake_hc(labels=labels)
            log.unlink(missing_ok=True)
            for _ in range(2):
                self.run_usage(status_input(), "claude", PATH=path, HC_TERMINAL_ID="t7", HC_SCOPE=str(labels))
            self.assertEqual(self.hc_calls(log), [], labels)
            self.assertEqual(len(self.hc_calls(log, "get")), 1, labels)  # looked once, then remembered

    def test_labels_its_terminal_with_the_name_once(self):
        path, log = self.fake_hc()
        stdin = status_input()  # before the first answer too: no numbers needed for the label
        self.run_usage(stdin, "claude", PATH=path, HC_TERMINAL_ID="t49", HC_SCOPE="s1")
        self.assertEqual(self.hc_calls(log), ["label t49 account=claude"])
        self.run_usage(stdin, "claude", PATH=path, HC_TERMINAL_ID="t49", HC_SCOPE="s1")  # after each answer
        self.assertEqual(len(self.hc_calls(log)), 1)  # once per terminal
        self.run_usage(stdin, "work", PATH=path, HC_TERMINAL_ID="t49", HC_SCOPE="s1")  # another name
        self.run_usage(stdin, "work", PATH=path, HC_TERMINAL_ID="t50", HC_SCOPE="s1")  # another terminal
        self.run_usage(stdin, "work", PATH=path, HC_TERMINAL_ID="t50", HC_SCOPE="s2")  # another core
        self.assertEqual(self.hc_calls(log)[1:], ["label t49 account=work", "label t50 account=work",
                                                  "label t50 account=work"])
        self.assertEqual(self.files(), [])  # no numbers: no usage file; the labels' notes live beside, not in it

    def test_no_label_outside_hc_or_when_turned_off(self):
        path, log = self.fake_hc()
        stdin = status_input((42, self.now + 3600))
        for env in ({}, {"HC_TERMINAL_ID": ""}, {"HC_TERMINAL_ID": "../x"}, {"HC_TERMINAL_ID": "a b"},
                    {"HC_TERMINAL_ID": "t$(touch pwned)"}, {"HC_TERMINAL_ID": "x" * 65},
                    {"HC_TERMINAL_ID": "t1", "HCGUI_ACCOUNT_LABEL": "0"}):
            self.run_usage(stdin, "claude", PATH=path, **env)
        self.assertEqual(self.hc_calls(log), [])
        self.assertFalse((Path(self._tmp.name) / "pwned").exists())
        self.assertEqual(self.saved()["five_hour"]["used_percentage"], 42)  # the numbers are still saved

    def test_a_failed_label_is_tried_again_and_no_hc_is_no_error(self):
        path, log = self.fake_hc(fails=True)
        for _ in range(2):
            self.run_usage(status_input(), "claude", PATH=path, HC_TERMINAL_ID="t1")
        self.assertEqual(len(self.hc_calls(log)), 2)  # no note kept after a failure
        self.run_usage(status_input((5, self.now + 3600)), "claude", HC_TERMINAL_ID="t1")  # no hc anywhere
        self.assertEqual(self.saved()["five_hour"]["used_percentage"], 5)

    def test_the_name_check_is_the_same_in_a_utf_8_locale(self):
        # Claude Code runs it with the session's locale (LANG=en_US.UTF-8 on most Macs); there sh's [A-Za-z] can
        # match letters such as é, and ${#name} counts characters, not bytes. mini reads ASCII names only.
        stdin = status_input((42, self.now + 3600))
        for locale in ({"LC_ALL": "en_US.UTF-8"}, {"LANG": "en_US.UTF-8"}, {"LC_CTYPE": "en_US.UTF-8"}):
            for name in ("é", "ß", "Ä", "ı", "ü", "ñ", "x" * 31 + "é", "claudé"):
                self.run_usage(stdin, name, **locale)
            self.assertEqual(self.files(), [], locale)
        self.run_usage(stdin, "claude-2", LC_ALL="en_US.UTF-8")
        self.run_usage(stdin, "x" * 32, LC_ALL="en_US.UTF-8")
        self.run_usage(stdin, "y" * 33, LC_ALL="en_US.UTF-8")
        self.assertEqual(self.files(), ["claude-2.json", "x" * 32 + ".json"])
        self.assertEqual(self.saved("claude-2")["five_hour"], {"used_percentage": 42, "resets_at": self.now + 3600})

    def test_atomic_a_new_file_replaces_the_old_one(self):
        self.run_usage(status_input((10, self.now + 3600)), "claude")
        with open(self.folder / "claude.json") as old:  # a reader that has the old file open keeps the old file
            self.run_usage(status_input((20, self.now + 3600)), "claude")
            self.assertEqual(json.loads(old.read())["five_hour"]["used_percentage"], 10)
        self.assertEqual(self.saved()["five_hour"]["used_percentage"], 20)
        self.assertEqual(self.files(), ["claude.json"])  # the temporary file was renamed, none left over
        self.assertIn('tmp=$(mktemp "$dir/.$name.XXXXXX"', (ROOT / "usage.sh").read_text())  # in the same folder
        self.assertIn('mv -f "$tmp" "$file"', (ROOT / "usage.sh").read_text())

    def test_a_newer_number_is_never_replaced_by_an_older_one(self):
        reset = self.now + 3600
        self.run_usage(status_input((40, reset)), "claude")
        self.run_usage(status_input((30, reset)), "claude")  # an idle session's last answer: same window, lower
        self.assertEqual(self.saved()["five_hour"]["used_percentage"], 40)
        self.run_usage(status_input((35, reset + 1)), "claude")  # resets_at a second off: still the same window
        self.assertEqual(self.saved()["five_hour"]["used_percentage"], 40)
        self.run_usage(status_input((40, reset)), "claude")  # the same number: written again (a fresh "at")
        self.run_usage(status_input((55.5, reset)), "claude")
        self.assertEqual(self.saved()["five_hour"], {"used_percentage": 55.5, "resets_at": reset})
        self.run_usage(status_input((90, reset - 5 * 3600)), "claude")  # an earlier window: never
        self.assertEqual(self.saved()["five_hour"]["used_percentage"], 55.5)
        self.run_usage(status_input((2, reset + 5 * 3600)), "claude")  # the next window: lower, but newer
        self.assertEqual(self.saved()["five_hour"], {"used_percentage": 2, "resets_at": reset + 5 * 3600})

    def test_a_higher_number_is_kept_for_ten_minutes_only(self):
        reset = self.now + 3600
        self.folder.mkdir(parents=True, exist_ok=True)
        line = json.loads(usage_line("claude", 80, reset))
        line["at"] = self.now - 11 * 60  # written 11 minutes ago (a session on another login, say)
        (self.folder / "claude.json").write_text(json.dumps(line) + "\n")
        self.run_usage(status_input((44, reset)), "claude")  # a right session's answer: lower, but the 80 is old
        self.assertEqual(self.saved()["five_hour"]["used_percentage"], 44)
        line["at"] = self.now - 5 * 60  # 5 minutes old: still kept
        (self.folder / "claude.json").write_text(json.dumps(line) + "\n")
        self.run_usage(status_input((44, reset)), "claude")
        self.assertEqual(self.saved()["five_hour"]["used_percentage"], 80)

    def test_a_saved_window_that_has_passed_or_is_junk_is_replaced(self):
        for saved in (usage_line("claude", 90, self.now - 60), usage_line("claude", 90, self.now + 10 ** 6),
                      "junk", "", '{"five_hour": {"used_percentage": "x", "resets_at": 1}}'):
            self.folder.mkdir(parents=True, exist_ok=True)
            (self.folder / "claude.json").write_text(saved + "\n")
            self.run_usage(status_input((5, self.now - 120)), "claude")  # a passed window is still written over
            self.run_usage(status_input((5, self.now + 3000)), "claude")
            self.assertEqual(self.saved()["five_hour"], {"used_percentage": 5, "resets_at": self.now + 3000}, saved)

    def test_default_folder_and_the_folder_made(self):
        self.run_usage(status_input((42, self.now + 3600)), "claude", HCGUI_STATE=None)
        self.assertTrue((Path(self._tmp.name) / ".local/state/hcgui/usage/claude.json").is_file())

    def test_no_jq_nothing(self):
        script = Path(self._tmp.name) / "usage.sh"
        text = (ROOT / "usage.sh").read_text()
        where = 'for j in /usr/bin/jq "$(command -v jq 2>/dev/null)" /opt/homebrew/bin/jq; do'
        self.assertEqual(text.count(where), 1)
        script.write_text(text.replace(where, 'for j in /nonexistent/jq "$(command -v jq 2>/dev/null)"; do'))
        self.run_usage(status_input((42, self.now + 3600)), "claude", script=script, PATH="/bin")
        self.assertEqual(self.files(), [])

    def test_fast(self):
        start = time.monotonic()
        for i in range(5):
            self.run_usage(status_input((i, self.now + 3600)), "claude")
        self.assertLess((time.monotonic() - start) / 5, 1.0)  # about 10 ms on the Mac mini


class UsageParseTests(unittest.TestCase):
    """The usage check: its script, its answer, its schedule (pure, and the script run with sh)."""

    def test_parse(self):
        lines = [usage_line("work", 87.5, 2000), "", "junk", "[1]", "null", '"x"',
                 usage_line("claude", 42, 1000), usage_line("claude", 99, 1001),  # a name twice: the first
                 usage_line("bad name", 1, 1), usage_line("", 1, 1), usage_line("x" * 33, 1, 1),
                 usage_line("t1", True, 1), usage_line("t2", "4", 1), usage_line("t3", None, 1),
                 usage_line("t4", 1, 1.5), usage_line("t5", 1, "1"), usage_line("t6", 1, -1),
                 usage_line("t7", 1, 10 ** 10 + 1), usage_line("t8", 1, False),
                 '{"name": "t9", "five_hour": [42, 1]}', '{"name": "t10"}', '{"name": 5, "five_hour": {}}',
                 '{"name": "t11", "five_hour": {"used_percentage": NaN, "resets_at": 1}}',
                 '{"name": "t12", "five_hour": {"used_percentage": 1e999, "resets_at": 1}}']
        self.assertEqual(hcgui.parse_usage("\n".join(lines)), [hcgui.Usage("claude", 42.0, 1000),
                                                              hcgui.Usage("work", 87.5, 2000)])
        self.assertEqual(hcgui.parse_usage(""), [])

    def test_junk_that_json_reads_is_left_out_never_raised(self):
        # a hand-written or broken file: a whole number too large for a float (jq keeps such a literal as it is;
        # float() raises OverflowError), and nesting deeper than Python 3.9's json can follow (RecursionError)
        lines = ['{"name": "huge", "five_hour": {"used_percentage": 1' + "0" * 400 + ', "resets_at": 1}}',
                 "[" * 4000, '{"a":' * 3000, "{" * 4000,
                 '{"name": "deep", "five_hour": {"used_percentage": ' + "[" * 4000 + ', "resets_at": 1}}',
                 usage_line("big", 10 ** 300, 2000),  # large but a float: kept, drawn as 100 %
                 usage_line("claude", 42, 1000)]
        self.assertEqual(hcgui.parse_usage("\n".join(lines)), [hcgui.Usage("big", 1e300, 2000),
                                                              hcgui.Usage("claude", 42.0, 1000)])

    def test_a_check_whose_answer_cannot_be_read_failed(self):
        hc = FakeHc([])
        hc.usage = usage_line("claude", 42, 1000)
        with mock.patch.object(hcgui, "parse_usage", side_effect=RuntimeError("surprise")):
            self.assertIsNone(hcgui.fetch_usage("mini", hc))  # a failure (backs off), never an exception

    def test_at_most_six_by_name(self):
        names = ["c10", "c2", "b", "a-2", "a", "c1", "d", "e"]
        out = "\n".join(usage_line(n, 1, 1) for n in names)
        self.assertEqual([u.name for u in hcgui.parse_usage(out)], ["a", "a-2", "b", "c1", "c2", "c10"])

    def test_percent_shown(self):
        U = hcgui.Usage
        self.assertEqual(U("a", 42.4, 100).percent(50), 42)
        self.assertEqual(U("a", 42.5, 100).percent(50), 43)  # half up, not to even
        self.assertEqual(U("a", 0.4, 100).percent(50), 0)
        self.assertEqual(U("a", 150, 100).percent(50), 100)
        self.assertEqual(U("a", -3, 100).percent(50), 0)
        self.assertEqual(U("a", 95, 100).percent(100), 0)  # the window has passed: a new one starts
        self.assertEqual(U("a", 95, 100).percent(101), 0)

    def test_the_call_is_an_argument_list_on_the_home_machine(self):
        args = hcgui.exec_args("mini", hcgui.USAGE_SCRIPT)
        self.assertEqual(args, ["exec", "--json", "--timeout", "20", "--on", "mini", "/bin/sh", "-c",
                                hcgui.USAGE_SCRIPT])
        self.assertIn('"$HOME"/.local/state/hcgui/usage/*.json', hcgui.USAGE_SCRIPT)

    def run_script(self, home):
        out = subprocess.run(["/bin/sh", "-c", hcgui.USAGE_SCRIPT], env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
                             capture_output=True, text=True, timeout=30)
        self.assertEqual((out.returncode, out.stderr), (0, ""))
        return out.stdout

    def test_the_script_prints_every_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_script(tmp), "")  # no folder: nothing, and still exit 0
            folder = Path(tmp) / ".local/state/hcgui/usage"
            folder.mkdir(parents=True)
            self.assertEqual(self.run_script(tmp), "")
            (folder / "claude.json").write_text(usage_line("claude", 42, 1000) + "\n")
            (folder / "work.json").write_text(usage_line("work", 7, 2000))  # no newline at its end
            (folder / ".claude.AbC123").write_text("half")  # usage.sh's temporary file: not read
            (folder / "notes.txt").write_text("x")
            (folder / "dir.json").mkdir()
            (folder / "big.json").write_text("x" * 10000)
            out = self.run_script(tmp)
            self.assertNotIn("half", out)
            self.assertIn("x" * hcgui.USAGE_BYTES + "\n", out)
            self.assertNotIn("x" * (hcgui.USAGE_BYTES + 1), out)
            self.assertEqual(hcgui.parse_usage(out), [hcgui.Usage("claude", 42, 1000), hcgui.Usage("work", 7, 2000)])
            for i in range(80):
                (folder / f"z{i:02}.json").write_text(usage_line(f"z{i:02}", 1, 1) + "\n")
            self.assertEqual(self.run_script(tmp).count('"five_hour"'), hcgui.USAGE_FILES - 1)  # big.json counts

    def test_fetch(self):
        hc = FakeHc([])
        hc.usage = usage_line("claude", 42, 1000) + "\n"
        self.assertEqual(hcgui.fetch_usage("mini", hc), [hcgui.Usage("claude", 42, 1000)])
        self.assertEqual(hc.calls[-1], tuple(hcgui.exec_args("mini", hcgui.USAGE_SCRIPT)))
        hc.usage = ""
        self.assertEqual(hcgui.fetch_usage("mini", hc), [])  # not set up: no lines, but not a failure
        hc.usage = None
        self.assertIsNone(hcgui.fetch_usage("mini", hc))
        for answer in (exec_json(1, "", usage_line("claude", 1, 1)), exec_json(0, "", "", timed_out=True),
                       exec_json(None), "junk"):
            self.assertIsNone(hcgui.fetch_usage("mini", lambda *a, **k: answer), answer)

    def test_the_schedule_start_then_every_ten_minutes(self):
        due = hcgui.usage_due
        self.assertTrue(due(None, 0.0))
        self.assertFalse(due(100.0, 699.0))
        self.assertTrue(due(100.0, 700.0))

    def test_failed_checks_back_off_to_an_hour(self):
        due = hcgui.usage_due
        waits = [next(w for w in range(60, 3 * 3600, 60) if due(0.0, float(w), fails)) for fails in range(1, 9)]
        self.assertEqual(waits, [600, 1200, 2400, 3600, 3600, 3600, 3600, 3600])
        self.assertTrue(due(0.0, 3600.0, 10 ** 6))  # no overflow
        self.assertFalse(due(0.0, 3599.0, 10 ** 6))


class UsageTextTests(unittest.TestCase):
    """The usage lines' text and look (pure)."""

    NOW = 1_800_000_000  # 2027-01-15 08:00 UTC

    def texts(self, entries, room, marks=None):
        marks = {"claude": "¹", "claude-2": "²"} if marks is None else marks
        return hcgui.usage_texts(entries, self.NOW, room, marks)

    def test_the_widest_form_that_fits(self):
        one = [hcgui.Usage("claude", 42.2, self.NOW + 6 * 60 + 3600)]
        # the mark right after the name, no space before it (owner, 24 Nov)
        self.assertEqual(self.texts(one, 40), [" claude¹  42%"])
        self.assertEqual(self.texts(one, 13), [" claude¹  42%"])
        self.assertEqual(self.texts(one, 12), [" claude¹ 42%"])
        self.assertEqual(self.texts(one, 11), [" ¹ 42%"])
        self.assertEqual(self.texts(one, 6), [" ¹ 42%"])
        self.assertEqual(self.texts(one, 5), [" 42%"])
        self.assertEqual(self.texts(one, 4), [" 42%"])
        self.assertEqual(self.texts(one, 3), [""])
        self.assertEqual(self.texts(one, 0), [""])

    def test_no_reset_time_at_any_width(self):
        # owner, 24 Nov: "no need for the 'resets xx:xx'": the name, its mark and the share, nothing after it
        entries = [hcgui.Usage("claude", 42, self.NOW + 3600), hcgui.Usage("claude-2", 87, self.NOW + 7200)]
        for room in range(0, 80):
            for line in self.texts(entries, room):
                self.assertTrue(line == "" or line.endswith("%"), (room, line))
                self.assertNotIn("·", line)
                self.assertNotIn("resets", line)
                self.assertIsNone(re.search(r"\d:\d\d", line), (room, line))

    @skip_without_notes
    def test_the_design_notes_show_what_the_default_width_draws(self):
        # INTERNAL.md's example, the owner's two subscriptions, is compared with the screen: it must be the form
        # drawn at HCGUI_WIDTH's default (the room is a column less), not a wider one
        notes = NOTES.read_text()
        section = notes[notes.index("## 5-hour usage"):]
        block = next(b for b in section.split("\n\n") if all(line.startswith("    ") for line in b.splitlines()))
        shown = [line[4:] for line in block.splitlines()]
        U = hcgui.Usage
        entries = [U("claude", 42, self.NOW + 6 * 3600 + 300), U("claude-2", 87, self.NOW + 7 * 3600 + 1800)]
        self.assertIn('WIDTH = env_int("HCGUI_WIDTH", 30,', (ROOT / "hcgui.py").read_text())  # the default: 30
        self.assertEqual([" " + line for line in shown], self.texts(entries, 30 - 1))

    def test_without_a_mark_the_name_alone(self):
        one = [hcgui.Usage("solo", 9, self.NOW + 3600)]
        self.assertEqual(self.texts(one, 29, {}), [" solo   9%"])
        self.assertEqual(self.texts(one, 10, {}), [" solo   9%"])
        self.assertEqual(self.texts(one, 9, {}), [" solo 9%"])
        self.assertEqual(self.texts(one, 7, {}), [" so… 9%"])
        self.assertEqual(self.texts(one, 3, {}), [" 9%"])

    def test_every_line_in_one_form_the_shares_lined_up(self):
        two = [hcgui.Usage("claude", 5, self.NOW + 3600), hcgui.Usage("claude-2", 100, self.NOW + 2 * 3600)]
        self.assertEqual(self.texts(two, 40), [" claude¹     5%", " claude-2² 100%"])
        self.assertEqual(self.texts(two, 15), [" claude¹     5%", " claude-2² 100%"])
        # " claude-2² 100%" needs 15 in both forms: below that the names are cut (the marks stay, the shares lined
        # up) while each keeps USAGE_CLIP_MIN columns before its "…", then the marks alone
        self.assertEqual(self.texts(two, 14), [" claude¹    5%", " claude…² 100%"])
        self.assertEqual(self.texts(two, 13), [" claude¹   5%", " claud…² 100%"])
        self.assertEqual(self.texts(two, 12), [" clau…¹   5%", " clau…² 100%"])
        self.assertEqual(self.texts(two, 11), [" ¹ 5%", " ² 100%"])
        self.assertEqual(self.texts(two, 8), [" ¹ 5%", " ² 100%"])

    def test_a_window_that_has_passed_shows_0(self):
        # its resets_at is still read: a window that has reset was not used yet (the next message starts it)
        entries = [hcgui.Usage("claude", 97, self.NOW), hcgui.Usage("claude-2", 50, self.NOW + 60)]
        self.assertEqual(self.texts(entries, 40), [" claude¹     0%", " claude-2²  50%"])
        self.assertEqual(self.texts(entries[:1], 40), [" claude¹   0%"])
        self.assertEqual(self.texts([hcgui.Usage("claude", 97, self.NOW + 1)], 40), [" claude¹  97%"])

    def test_every_width_fits(self):
        entries = [hcgui.Usage("claude", 42, self.NOW + 3600), hcgui.Usage("claude-2", 87, self.NOW + 60),
                   hcgui.Usage("a-very-long-subscription-name", 3, self.NOW + 99)]
        for marks in ({"claude": "¹", "claude-2": "²"}, {}):
            for room in range(0, 60):
                lines = self.texts(entries, room, marks)
                self.assertEqual(len(lines), 3)
                for line in lines:
                    self.assertLessEqual(hcgui.text_width(line), room, (room, line))
                if room >= 6:
                    self.assertTrue(all(line.endswith("%") for line in lines), (room, lines))
        self.assertEqual(self.texts([], 29), [])

    def test_display_names_drawn_the_mark_by_the_files_name(self):
        two = [hcgui.Usage("claude", 42, self.NOW + 3600), hcgui.Usage("work", 87, self.NOW + 7200)]
        marks = {"claude": "¹", "work": "²"}
        names = {"account:work": "Team plan", "account:Team plan": "x", "space:claude": "x"}
        self.assertEqual(hcgui.usage_texts(two, self.NOW, 29, marks, names), [" claude¹     42%", " Team plan²  87%"])
        self.assertEqual(hcgui.usage_texts(two, self.NOW, 14, marks, names), [" claude¹   42%", " Team p…²  87%"])
        self.assertEqual(hcgui.usage_texts(two, self.NOW, 12, marks, names), [" clau…¹  42%", " Team…²  87%"])
        self.assertEqual(hcgui.usage_texts(two, self.NOW, 11, marks, names), [" ¹ 42%", " ² 87%"])
        self.assertEqual(hcgui.usage_texts(two, self.NOW, 29, {}, names), [" claude     42%", " Team plan  87%"])
        self.assertEqual(hcgui.usage_texts(two[1:], self.NOW, 9, {}, names), [" Tea… 87%"])  # no mark: cut
        self.assertEqual(hcgui.usage_texts(two, self.NOW, 29, marks), [" claude¹  42%", " work²    87%"])

    def test_long_display_names_are_cut_not_dropped(self):
        # one long display name must not leave every line with its mark alone at the default width: the names are
        # cut as a row's name is (the mark stays), the shares lined up
        two = [hcgui.Usage("claude", 42, self.NOW + 3600), hcgui.Usage("work", 87, self.NOW + 7200)]
        marks = {"claude": "¹", "work": "²"}
        names = {"account:work": "Team subscription paid by Studio"}  # 32: the longest allowed
        self.assertEqual(hcgui.usage_texts(two, self.NOW, 29, marks, names),
                         [" claude¹                  42%", " Team subscription pai…²  87%"])
        self.assertEqual(hcgui.usage_texts(two, self.NOW, 29, {}, names),
                         [" claude                   42%", " Team subscription paid…  87%"])

    def test_every_allowed_display_name_fits_every_width(self):
        entries = [hcgui.Usage("claude", 42, self.NOW + 3600), hcgui.Usage("work", 7, self.NOW + 60),
                   hcgui.Usage("solo", 100, self.NOW + 99)]
        for long in ("x" * 32, "漢" * 32, "a" * 31 + "漢", "Team", "T", "é" * 32):
            self.assertTrue(hcgui.valid_display_name(long), long)
            names = {"account:work": long, "account:solo": long[:1] + "!"}
            for marks in ({"claude": "¹", "work": "²"}, {}):
                for room in range(0, 70):
                    lines = hcgui.usage_texts(entries, self.NOW, room, marks, names)
                    self.assertEqual(len(lines), 3)
                    for line in lines:
                        self.assertLessEqual(hcgui.text_width(line), room, (long, room, line))
                    if room >= 6:
                        self.assertTrue(all(line.endswith("%") for line in lines), (long, room, lines))
                    if room >= 13 and any("…" in line for line in lines):  # the cut form (no mark alone yet)
                        widths = {hcgui.text_width(line) for line in lines}
                        self.assertEqual(len(widths), 1, (long, room, lines))  # the shares lined up
                    if room >= 29:  # the default width and wider: the name is never dropped
                        self.assertTrue(lines[1].startswith(" " + long[:4]), (long, room, lines))

    def test_the_cut_form_keeps_at_least_four_columns_of_each_name(self):
        one = [hcgui.Usage("work", 87, self.NOW + 60)]
        names = {"account:work": "Alpha Beta"}
        texts = [hcgui.usage_texts(one, self.NOW, room, {"work": "²"}, names) for room in range(10, 20)]
        self.assertEqual(texts, [[" ² 87%"]] * 2 + [[" Alph…²  87%"], [" Alpha…²  87%"],
                                                    [" Alpha …²  87%"],  # cut as clip() cuts any name
                                                    [" Alpha B…²  87%"], [" Alpha Beta² 87%"],
                                                    [" Alpha Beta²  87%"], [" Alpha Beta²  87%"],
                                                    [" Alpha Beta²  87%"]])
        self.assertEqual(hcgui.USAGE_CLIP_MIN, 4)

    def test_tone(self):
        tone = hcgui.usage_tone
        self.assertEqual([tone(p) for p in (0, 49, 50, 80, 94, 95, 100)], ["", "", "", "", "", "high", "high"])
        with mock.patch.object(hcgui.curses, "color_pair", lambda n: n << 8):
            for share in (0, 49, 50, 80, 94):  # always dim (owner, 24 Nov), never bold
                self.assertEqual(hcgui.usage_attr(share), hcgui.curses.A_DIM)
            self.assertEqual(hcgui.usage_attr(95), (1 << 8) | hcgui.curses.A_DIM)  # the keychain warning's red, dim


class UsageFrameTests(unittest.TestCase):
    """Where the usage lines go: above the keychain warning and "‹", below the list and a message (pure)."""

    def test_open_sidebar(self):
        f, rows = hcgui.sidebar_frame, hcgui.usage_rows
        # a blank line between the list and them (owner, 24 Nov: the agents sat right on the subscriptions) and one
        # between them and "‹ fold" (owner, 24 Nov)
        self.assertEqual(f(40, False, False, usage=2), (35, 39, -1, 0))
        self.assertEqual(rows(40, False, False, 35, 0, 2), [36, 37])  # 35 and 38 stay blank
        self.assertEqual(rows(40, False, False, 35, 0), [35, 36, 37, 38])  # no count: every line between
        self.assertEqual(f(40, False, False, keychain=True, usage=2), (34, 39, -1, 0))
        self.assertEqual(rows(40, False, True, 34, 0, 2), [35, 36])  # 34 and 37 blank, the keychain warning on 38
        self.assertEqual(f(40, True, False, keychain=True, usage=2), (33, 39, -1, 1))
        # 33 and 34: the message and the blank line above them (the Sidebar draws the message right above them, on
        # 34); 37 blank, the keychain warning on 38
        self.assertEqual(rows(40, False, True, 33, 1, 2), [35, 36])
        # room for one blank line only: the one above them; none: the list keeps its USAGE_LIST_MIN lines, the
        # usage lines right below it and right above "‹ fold"
        least = hcgui.USAGE_LIST_MIN
        for tight, below in ((least + 2 + 1, least), (least + 2 + 2, least + 1), (least + 2 + 3, least + 1)):
            self.assertEqual(f(tight, False, False, usage=2), (least, tight - 1, -1, 0), tight)
            self.assertEqual(rows(tight, False, False, least, 0, 2), [below, below + 1], tight)
        self.assertEqual(rows(40, False, False, 35, 0, 0), [])
        self.assertEqual(f(40, False, False), f(40, False, False, usage=0))  # none: as before
        self.assertEqual(rows(40, False, False, *[f(40, False, False)[i] for i in (0, 3)]), [])

    def test_every_line_has_one_use_and_the_list_keeps_its_lines(self):
        for height in range(0, 30):
            for keychain in (False, True):
                for message, prompt in ((False, False), (True, False), (False, True)):
                    for strip in (False, True):
                        for usage in (0, 1, 2, 6):
                            case = (height, keychain, message, prompt, strip, usage)
                            body, arrow, opener, extra = hcgui.sidebar_frame(height, message, prompt, strip, 8,
                                                                             keychain, 3, usage)
                            ys = hcgui.usage_rows(height, strip, keychain, body, extra, usage)
                            kc = hcgui.keychain_line(height, strip, keychain)
                            self.assertIn(len(ys), (0, usage), case)  # all of them or none
                            # the blank lines above them and below them, when room: the one above first
                            end = next((y for y in (kc, opener, arrow) if y >= 0), height)
                            above = ys[0] - (body + extra) if ys else 0
                            below = end - (ys[-1] + 1) if ys else 0
                            self.assertIn(above, (0, 1), case)
                            self.assertIn(below, (0, 1), case)
                            self.assertLessEqual(below, above, case)
                            self.assertEqual(body + extra + above + below + len(ys) + (kc >= 0) + (arrow >= 0)
                                             + (opener >= 0), height, case)
                            if ys:
                                self.assertGreaterEqual(body, hcgui.USAGE_LIST_MIN, case)
                                self.assertEqual(ys, list(range(ys[0], ys[0] + usage)), case)
                                if above + below < 2:  # a blank line is left out only for the list's lines
                                    self.assertEqual(body, hcgui.USAGE_LIST_MIN, case)
                            without = hcgui.sidebar_frame(height, message, prompt, strip, 8, keychain, 3)
                            self.assertEqual((body + above + below + len(ys), arrow, opener, extra), without, case)
                            if height >= 1:
                                self.assertGreaterEqual(body, 1, case)
                            if usage and height >= 2 + keychain + hcgui.USAGE_LIST_MIN + usage + 9 + strip:
                                self.assertTrue(ys, case)  # a prompt of 9 lines never pushes them out of a tall pane

    def test_short_sidebars_drop_them_first(self):
        f = hcgui.sidebar_frame
        self.assertEqual(f(8, False, False, usage=2), (5, 7, -1, 0))  # the list keeps 5 lines
        self.assertEqual(f(7, False, False, usage=2), (6, 6, -1, 0))  # one short: none of the two
        self.assertEqual(f(9, True, False, keychain=True, usage=2), (6, 8, -1, 1))  # the message wins
        self.assertEqual(f(10, True, False, keychain=True, usage=2), (5, 9, -1, 1))


class UsageSidebarTests(unittest.TestCase):
    """The Sidebar with usage lines: the check's schedule (FakeHc's exec, a fake clock) and the drawing (FakeScr)."""

    MACHINES = [("mini", "me@mini"), ("guest", "guest@mini")]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"
        terms = [tterm("mini/t1", "/Users/x/dev", "claude-code", "atlas", "idle", 3),
                 tterm("mini/t2", "/Users/x/dev", "claude-code", "tracker", "working", 2),
                 tterm("mini/t4", "/Users/x/dev/other", "zsh", "sh")]
        self.hc = FakeHc(terms, {"mini/t1": {"labels": {"account": "claude"}}}, machines=self.MACHINES)
        self.reset = int(time.time()) + 2 * 3600
        self.hc.usage = "\n".join([usage_line("work", 87.4, self.reset + 600), usage_line("claude", 42, self.reset),
                                   usage_line("solo", 55, self.reset)]) + "\n"
        for target, value in ((hcgui, {"run_hc": self.hc, "FIRST": "mini"}),
                              (hcgui.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scr = FakeScr(40, 30)
        self.side = hcgui.Sidebar(self.scr, self.state, self.win)
        self.side.refresh_once()
        self.now = 1000.0
        self.side.refresh_extras(self.now)
        self.side.sync()
        self.side.draw()

    key = SidebarLogicTests.key
    mouse = ExtrasSidebarTests.mouse
    lines = ExtrasSidebarTests.lines

    def calls(self):
        return [c for c in self.hc.calls if c[0] == "exec" and hcgui.USAGE_SCRIPT in c]

    def test_lines_at_the_bottom_above_fold(self):
        lines = self.lines()
        want = [" claude¹  42%", " solo     55%", " work²    87%"]  # no reset time
        self.assertEqual(lines[35:38], [hcgui.glyph(w) for w in want])
        self.assertEqual(lines[39], hcgui.glyph(fold_line("open")))
        self.assertEqual(self.side.usage_ys, [35, 36, 37])
        self.assertEqual(self.side.body_height, 34)  # line 34: the blank line above them
        self.assertEqual((lines[34], lines[38]), ("", ""))  # and line 38: the one below them, off "‹ fold"
        for y in (35, 36, 37):  # 42, 55, 87: dim, never bold (owner, 24 Nov: red only from 95 %, dim too)
            self.assertEqual(self.scr.cells[(y, 1)][1], hcgui.curses.A_DIM)
        self.assertTrue(all(hcgui.text_width(line) <= 29 for line in self.scr.lines()))

    def test_above_the_keychain_warning(self):
        self.hc.keychain = (36, "User interaction is not allowed.")
        self.side.keychain_asked = True
        self.side.refresh_extras(self.now + 1)
        self.side.draw()
        lines = self.lines()
        self.assertEqual(self.side.usage_ys, [34, 35, 36])
        self.assertTrue(lines[34].startswith(" claude"))
        self.assertEqual((lines[33], lines[37]), ("", ""))  # a blank line above them and one below them
        self.assertEqual(lines[38], " keychain locked: API billing")
        self.assertEqual(lines[39], hcgui.glyph(fold_line("open")))

    def test_the_rest_of_the_sidebar_is_unchanged(self):
        with_usage = self.lines()
        with mock.patch.dict(os.environ, {"HCGUI_USAGE": "0"}):
            self.side.draw()
        without = self.lines()
        self.assertNotIn("%", "".join(without))
        # the same rows in the same order, the agents (anchored to the list's last line) 5 lines higher: 3 usage
        # lines and the blank lines above and below them
        self.assertEqual([line for line in with_usage[:34] if line], [line for line in without[:39] if line])
        self.assertEqual(with_usage[29:34], without[34:39])
        self.assertEqual((with_usage[34], with_usage[38]), ("", ""))
        self.assertEqual(with_usage[39], without[39])

    def test_none_in_the_strip(self):
        self.key("c")
        self.assertEqual(self.side.mode, "strip")
        self.assertEqual(self.side.usage_ys, [])
        self.assertNotIn("%", "".join(self.scr.lines()))
        self.key("o")
        self.assertEqual(len(self.side.usage_ys), 3)

    def test_nothing_without_data_or_after_a_failed_check(self):
        self.hc.usage = ""  # usage.sh not set up
        self.side.refresh_extras(self.now + hcgui.USAGE_SECONDS)
        self.side.draw()
        self.assertEqual(self.side.usage_ys, [])
        self.assertNotIn("%", "".join(self.scr.lines()))
        self.hc.usage = usage_line("claude", 1, self.reset)
        self.side.refresh_extras(self.now + 2 * hcgui.USAGE_SECONDS)
        self.side.draw()
        self.assertEqual(len(self.side.usage_ys), 1)
        self.hc.usage = None  # the home machine does not answer
        self.side.refresh_extras(self.now + 3 * hcgui.USAGE_SECONDS)
        self.side.draw()
        self.assertEqual(self.side.usage_ys, [])
        self.assertEqual(self.side.usage_fails, 1)

    def test_a_junk_file_neither_hides_the_others_nor_asks_every_second(self):
        self.hc.usage = "\n".join(['{"name": "x", "five_hour": {"used_percentage": 1' + "0" * 400 +
                                   ', "resets_at": 1}}', "[" * 4000, usage_line("claude", 7, self.reset)]) + "\n"
        before = len(self.calls())
        for step in range(1, 11):
            self.side.refresh_extras(self.now + hcgui.USAGE_SECONDS + step)
        self.assertEqual(len(self.calls()), before + 1)  # once, then not again before the next minute
        self.assertEqual((self.side.usage_at, self.side.usage_fails), (self.now + hcgui.USAGE_SECONDS + 1, 0))
        self.side.draw()
        self.assertEqual([u.name for u in self.side.usage], ["claude"])
        self.assertEqual(len(self.side.usage_ys), 1)

    def test_asked_at_the_start_then_every_ten_minutes_and_at_once_on_r(self):
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.calls()[0][4:6], ("--on", "mini"))
        for step in (1.0, 60.0, 300.0, 599.0):
            self.side.refresh_extras(self.now + step)
        self.assertEqual(len(self.calls()), 1)
        self.side.refresh_extras(self.now + 600.0)
        self.assertEqual(len(self.calls()), 2)
        self.key("r")
        self.side.refresh_extras(self.now + 601.0)
        self.assertEqual(len(self.calls()), 3)

    def test_failed_checks_back_off(self):
        self.hc.usage = None
        start = self.now + 600.0
        at = []
        for minute in range(0, 4 * 60):
            before = len(self.calls())
            self.side.refresh_extras(start + minute * 60.0)
            if len(self.calls()) > before:
                at.append(minute)
        self.assertEqual(at, [0, 10, 30, 70, 130, 190])  # 10, 20, 40, then every 60 minutes
        self.hc.usage = usage_line("claude", 1, self.reset)
        self.key("r")  # r asks at once, also while backing off
        self.side.refresh_extras(start + 196 * 60.0)
        self.assertEqual((len(self.side.usage), self.side.usage_fails), (1, 0))

    def test_off_with_mini_usage_0(self):
        self.hc.calls.clear()
        with mock.patch.dict(os.environ, {"HCGUI_USAGE": "0"}):
            self.assertFalse(hcgui.usage_enabled())
            self.side.usage_asked = True
            self.side.refresh_extras(self.now + 600)
            self.side.draw()
            self.assertEqual(self.calls(), [])
            self.assertEqual(self.side.usage_ys, [])
        self.assertTrue(hcgui.usage_enabled())

    def test_a_new_home_machine_drops_them_and_asks_at_once(self):
        engine = hcgui.Engine(self.state, self.win)
        mini = self.hc.terms
        self.hc.terms = []  # no terminal of the mini yet: this Mac is home
        engine.refresh_once()
        engine.refresh_extras(self.now)
        self.assertEqual([("--on" in c) for c in self.calls()][-1:], [False])
        self.assertEqual(len(engine.usage), 3)
        self.hc.terms = mini
        self.hc.usage = ""
        engine.refresh_once()
        engine.refresh_extras(self.now + 1)  # not a minute later: at once, and this Mac's lines are gone
        self.assertEqual(self.calls()[-1][4:6], ("--on", "mini"))
        self.assertEqual(engine.usage, [])

    def right_click(self, y):
        self.side.mouse_quiet = 0.0
        with pressed(3, y, 3):
            self.key(hcgui.curses.KEY_MOUSE)

    def test_a_left_click_does_nothing(self):
        target, cursor = hcgui.current_target(self.win), self.side.cursor
        for y in self.side.usage_ys:
            self.side.mouse_quiet = 0.0
            with pressed(3, y, 1):
                self.key(hcgui.curses.KEY_MOUSE)
        self.assertNotIn(36, self.side.rows)
        self.assertIsNone(self.side.menu)
        self.assertEqual((hcgui.current_target(self.win), self.side.cursor), (target, cursor))
        self.assertEqual(self.side.notice.current(), "")
        self.assertFalse([c for c in self.hc.calls if c[0] == "run"])
        self.assertEqual(len(self.side.usage_ys), 3)

    def test_a_right_click_opens_that_lines_menu_above_them(self):
        cursor = self.side.cursor
        before = self.lines()[35:38]
        self.assertEqual(self.side.usage_names, ["claude", "solo", "work"])  # as drawn, by name
        for y, name in zip(self.side.usage_ys, ("claude", "solo", "work")):
            self.right_click(y)
            menu = self.side.menu
            self.assertEqual((menu.item, menu.title, menu.by_mouse), (hcgui.usage_item(name), name, True))
            self.assertEqual([e.label for e in menu.entries],
                             ["Rename", "Refresh", "Hide usage"])
            self.assertEqual(self.side.cursor, cursor)  # a usage line is no row: the cursor stays
            box = self.side.menu_at
            self.assertEqual(box.top + box.height, 35, y)  # just above the first of them, whichever was clicked
            self.assertEqual(self.lines()[35:38], before)  # none of them covered
            self.assertIn("Rename", self.lines()[box.entry_y(0)])
            self.assertIn("Refresh", self.lines()[box.entry_y(1)])
            self.assertIn("Hide usage", self.lines()[box.entry_y(2)])
            self.assertIn(name, self.lines()[box.top])  # titled with the subscription's name
            self.side.mouse_quiet = 0.0
            with pressed(20, 2):  # a click outside closes it, and does nothing else
                self.key(hcgui.curses.KEY_MOUSE)
            self.assertIsNone(self.side.menu)
        self.assertFalse((self.state / "usagelines").exists())  # nothing written yet

    def test_refresh_in_their_menu_checks_now(self):
        """Owner, 24 Nov: "Refresh" in a usage line's menu, the same as r."""
        self.right_click(36)
        box = self.side.menu_at
        self.side.mouse_quiet = 0.0
        self.side.usage_asked = self.side.keychain_asked = False
        with mock.patch.object(hcgui, "focus_view"), pressed(box.left + 2, box.entry_y(1)):
            self.key(hcgui.curses.KEY_MOUSE)
        self.assertIsNone(self.side.menu)
        self.assertTrue(self.side.usage_asked and self.side.keychain_asked and self.side.full_due)
        self.assertFalse((self.state / "usagelines").exists())  # still shown

    def test_hide_usage_in_their_menu_hides_them_and_stops_the_check(self):
        self.right_click(36)
        box = self.side.menu_at
        self.side.mouse_quiet = 0.0
        with mock.patch.object(hcgui, "focus_view") as focus, pressed(box.left + 2, box.entry_y(2)):
            self.key(hcgui.curses.KEY_MOUSE)
        focus.assert_called_once_with(self.win)  # a right-click menu: the keyboard back to the view
        self.assertIsNone(self.side.menu)
        self.assertEqual(hcgui.read_text(self.state / "usagelines"), "hidden")
        self.assertEqual(self.side.notice.current(), "usage hidden (u shows it)")
        self.assertEqual(self.side.usage_ys, [])
        self.assertNotIn("%", "".join(self.scr.lines()))
        self.assertEqual(self.side.body_height, 39 - 1)  # the list gets their lines (one is the notice's)
        before = len(self.calls())
        for minute in range(1, 30):
            self.side.refresh_extras(self.now + minute * 60.0)
        self.key("r")  # r neither
        self.side.refresh_extras(self.now + 31 * 60.0)
        self.assertEqual(len(self.calls()), before)  # no hc exec while hidden
        self.assertEqual(self.side.usage, [])  # and the last lines are dropped

    def test_hidden_every_row_menu_offers_show_usage(self):
        for item in list(self.side.rows.values())[:3]:  # shown: no usage entry in a row's menu
            self.side.cursor, self.side.cursor_pos = item, self.side.items().index(item)
            self.key("a")
            self.assertNotIn("usage", [e.action for e in self.side.menu.entries])
            self.key(27)
        self.key("u")
        self.assertEqual(self.side.usage_ys, [])
        for y, item in sorted(self.side.rows.items()):
            self.side.cursor, self.side.cursor_pos = item, self.side.items().index(item)
            self.key("a")
            self.assertEqual(self.side.menu.entries[-1], hcgui.Entry("usage", "Show usage", "u"), item)
            self.key(27)
        row = min(self.side.rows)
        self.right_click(row)  # a right click on a row: the same entry, picked with a click
        menu, box = self.side.menu, self.side.menu_at
        self.assertEqual(menu.entries[-1].label, "Show usage")
        before = len(self.calls())
        self.side.mouse_quiet = 0.0
        with pressed(box.left + 2, box.entry_y(len(menu.entries) - 1)):
            self.key(hcgui.curses.KEY_MOUSE)
        self.assertTrue(hcgui.read_usage_shown(self.state))
        self.assertEqual(hcgui.read_text(self.state / "usagelines"), "shown")
        self.assertEqual(self.side.notice.current(), "usage shown (u hides it)")
        self.side.refresh_extras(self.now + 1)  # asked at once, not a minute later
        self.assertEqual(len(self.calls()), before + 1)
        self.side.draw()
        self.assertEqual(len(self.side.usage_ys), 3)

    def test_u_shows_and_hides_them_for_every_window(self):
        other = hcgui.Sidebar(FakeScr(40, 30), self.state, self.state / "w-2")  # another window
        other.refresh_once()
        other.refresh_extras(self.now)
        other.sync()
        other.draw()
        self.assertEqual(len(other.usage_ys), 3)
        self.key("u")
        self.assertEqual(self.side.notice.current(), "usage hidden (u shows it)")
        self.assertEqual(self.side.usage_ys, [])
        other.draw()
        self.assertEqual(other.usage_ys, [])  # the other window follows the shared file at its next draw
        before = len(self.calls())
        other.refresh_extras(self.now + 600)
        self.assertEqual(len(self.calls()), before)
        self.key("U")  # shown again
        self.assertEqual(self.side.notice.current(), "usage shown (u hides it)")
        self.side.refresh_extras(self.now + 1)
        other.refresh_extras(self.now + 601)  # its lines were dropped while hidden: asked at once there too
        self.assertEqual(len(self.calls()), before + 2)
        for side in (self.side, other):
            side.draw()
            self.assertEqual(len(side.usage_ys), 3)

    def test_u_works_beside_usage_sh_folder(self):
        # one Mac: usage.sh saves into this same state folder (usage/<name>.json); u hides and shows the lines all
        # the same and never touches that folder
        folder = self.state / "usage"
        folder.mkdir(parents=True)
        (folder / "claude.json").write_text(usage_line("claude", 42, self.reset) + "\n")
        before = (folder / "claude.json").read_text()
        self.key("u")
        self.assertEqual(self.side.notice.current(), "usage hidden (u shows it)")
        self.assertEqual(self.side.usage_ys, [])
        self.assertFalse(hcgui.read_usage_shown(self.state))
        self.key("u")
        self.assertEqual(self.side.notice.current(), "usage shown (u hides it)")
        self.assertTrue(hcgui.read_usage_shown(self.state))
        self.assertTrue(folder.is_dir())
        self.assertEqual([p.name for p in folder.iterdir()], ["claude.json"])
        self.assertEqual((folder / "claude.json").read_text(), before)
        self.assertEqual([p.name for p in self.state.iterdir() if p.name.endswith(".tmp")], [])

    def test_u_in_the_strip_and_in_the_menu(self):
        self.key("c", "u")  # works in the strip too (no lines there): the file changes
        self.assertEqual(self.side.mode, "strip")
        self.assertFalse(hcgui.read_usage_shown(self.state))
        self.key("o", "a")
        self.key("u")  # its letter in a row's menu: Show usage
        self.assertIsNone(self.side.menu)
        self.assertTrue(hcgui.read_usage_shown(self.state))

    def test_their_menu_closes_when_they_go(self):
        self.right_click(35)
        self.assertIsNotNone(self.side.menu)
        hcgui.write_usage_shown(False, self.state)  # another window hides them
        self.side.draw()
        self.assertIsNone(self.side.menu)
        self.assertIsNone(self.side.menu_at)
        hcgui.write_usage_shown(True, self.state)
        self.side.draw()  # back at the next draw
        self.right_click(35)
        self.assertEqual(self.side.menu.item, hcgui.usage_item("claude"))
        self.hc.usage = None  # a failed check: the lines go, and their menu with them
        self.side.refresh_extras(self.now + hcgui.USAGE_SECONDS)
        self.side.draw()
        self.assertIsNone(self.side.menu)

    def pick(self, y, entry):
        """A right click on the usage line at `y`, then a click on its menu's entry `entry` (its label)."""
        self.right_click(y)
        box, menu = self.side.menu_at, self.side.menu
        self.side.mouse_quiet = 0.0
        with pressed(box.left + 2, box.entry_y([e.label for e in menu.entries].index(entry))):
            self.key(hcgui.curses.KEY_MOUSE)

    def rename(self, y, text):
        """Rename in the menu of the usage line at `y`, the name filled in cleared (ctrl+U), `text` typed, enter."""
        self.pick(y, "Rename")
        self.key(21, *text, 10)

    def test_rename_a_subscription_from_its_lines_menu(self):
        with mock.patch.object(hcgui, "focus_view") as focus:
            self.pick(37, "Rename")
        focus.assert_not_called()  # a question: the sidebar keeps the keyboard until it is answered
        prompt = self.side.prompt
        self.assertEqual((prompt.kind, prompt.title, prompt.text), ("rename", "rename work to:", "work"))
        self.assertEqual((prompt.key, prompt.own, prompt.by_mouse), ("account:work", "work", True))
        self.assertIsNone(self.side.menu)
        self.assertIn("> work_", self.lines())  # the usual rename prompt, the shown name filled in
        with mock.patch.object(hcgui, "focus_view") as focus:
            self.key(21, *"Team plan", 10)
        focus.assert_called_once_with(self.win)  # answered: the keyboard back to the view
        self.assertEqual(hcgui.read_names(self.state), {"account:work": "Team plan"})
        self.assertIsNone(self.side.prompt)
        self.assertEqual(self.lines()[35:38], [hcgui.glyph(w) for w in
                                               (" claude¹     42%", " solo        55%", " Team plan²  87%")])
        self.assertEqual(self.side.usage_names, ["claude", "solo", "work"])  # still by the file's name
        self.assertEqual(self.scr.cells[(37, 1)][1], hcgui.curses.A_DIM)  # its look as before: dim (87 % is under 95)
        self.pick(37, "Rename")  # again: the display name filled in, and in the menu's title
        self.assertEqual((self.side.prompt.title, self.side.prompt.text), ("rename Team plan to:", "Team plan"))
        self.key(27)
        self.right_click(37)
        self.assertEqual(self.side.menu.title, "Team plan")
        self.assertEqual(self.side.menu.item, hcgui.usage_item("work"))
        self.assertIn("Team plan", self.lines()[self.side.menu_at.top])
        self.side.mouse_quiet = 0.0
        with pressed(20, 2):
            self.key(hcgui.curses.KEY_MOUSE)
        self.assertFalse([c for c in self.hc.calls if c[0] == "label"])  # nothing of hc changes

    def test_an_empty_name_or_the_plain_name_removes_it(self):
        for answer in ("", "work", "  "):
            self.rename(37, "Team")
            self.assertEqual(hcgui.read_names(self.state), {"account:work": "Team"})
            self.rename(37, answer)
            self.assertEqual(hcgui.read_names(self.state), {}, repr(answer))
            self.assertTrue(self.lines()[37].startswith(hcgui.glyph(" work²")), answer)
        hcgui.change_names({"space:dev": "Main", "account:solo": "Side"}, self.state)
        self.rename(37, "Team")
        self.rename(37, "")  # the other display names stay
        self.assertEqual(hcgui.read_names(self.state), {"space:dev": "Main", "account:solo": "Side"})

    def test_a_name_another_subscription_shows_is_refused(self):
        self.rename(36, "Side")
        for answer, why in (("SIDE", "SIDE is taken"), ("claude", "claude is taken"), ("Claude", "Claude is taken"),
                            ("x" * 33, "a name is 1-32 printable characters")):
            self.rename(37, answer)
            self.assertEqual(self.side.notice.current(), "rename: " + why, answer)
            self.assertEqual(hcgui.read_names(self.state), {"account:solo": "Side"}, answer)
        self.rename(37, "solo")  # solo shows Side, but its own name comes back once that goes
        self.assertEqual(self.side.notice.current(), "rename: solo is taken")
        self.assertEqual(hcgui.read_names(self.state), {"account:solo": "Side"})
        self.rename(36, "")
        self.assertEqual(hcgui.read_names(self.state), {})
        self.assertEqual(self.lines()[35:38], [hcgui.glyph(w) for w in (" claude¹  42%", " solo     55%",
                                                                        " work²    87%")])
        hcgui.change_names({"space:dev": "Desk"}, self.state)
        self.rename(36, "Desk")  # a space's or a terminal's name is no subscription's: allowed
        self.assertEqual(hcgui.read_names(self.state)["account:solo"], "Desk")

    def test_a_name_the_marks_stand_for_is_refused_with_or_without_a_line(self):
        """The "?" list names every HCGUI_MARKS label (a subscription, with a line or not yet), "other" and
        HCGUI_SHARED_USER: none may come twice there, or on two lines once a label's line shows (review finding).
        The tests' HCGUI_MARKS: claude and main ¹, work ²; HCGUI_SHARED_USER guest. "main" has no usage file."""
        for answer in ("main", "Main", "other", "Guest"):
            self.rename(37, answer)
            self.assertEqual(self.side.notice.current(), f"rename: {answer} is taken", answer)
            self.assertEqual(hcgui.read_names(self.state), {}, answer)
        self.hc.usage = "\n".join([usage_line("work", 87.4, self.reset + 600),
                                   usage_line("solo", 55, self.reset)]) + "\n"  # claude's line not there yet
        self.now += hcgui.USAGE_SECONDS
        self.side.refresh_extras(self.now)
        self.side.draw()
        self.assertEqual(self.side.usage_names, ["solo", "work"])
        self.rename(self.side.usage_ys[0], "claude")
        self.assertEqual(self.side.notice.current(), "rename: claude is taken")
        self.assertEqual(hcgui.read_names(self.state), {})
        hcgui.change_names({"account:main": "Home"}, self.state)  # a label's display name is taken too
        self.rename(self.side.usage_ys[0], "home")
        self.assertEqual(self.side.notice.current(), "rename: home is taken")
        self.rename(self.side.usage_ys[0], "Team")
        self.assertEqual(hcgui.read_names(self.state), {"account:main": "Home", "account:solo": "Team"})

    def test_lines_gone_while_asked_still_refuse_their_names(self):
        # the lines drop while the question is open (a failed check, or hidden in another window: refresh_extras
        # empties them): the names they showed when it was asked are still taken
        for drop in ("failed", "hidden"):
            hcgui.change_names({"account:solo": "Side", "account:work": ""}, self.state)
            hcgui.write_usage_shown(True, self.state)
            self.hc.usage = "\n".join([usage_line("work", 87.4, self.reset + 600),
                                       usage_line("claude", 42, self.reset), usage_line("solo", 55, self.reset)]) + "\n"
            self.now += hcgui.USAGE_SECONDS
            self.side.refresh_extras(self.now)
            self.side.draw()
            self.pick(37, "Rename")
            self.assertEqual(self.side.prompt.title, "rename work to:", drop)
            if drop == "failed":
                self.hc.usage = None
            else:
                hcgui.write_usage_shown(False, self.state)
            self.now += hcgui.USAGE_SECONDS
            self.side.refresh_extras(self.now)
            self.assertEqual(self.side.usage, [], drop)
            self.assertIsNotNone(self.side.prompt, drop)  # the question stays
            self.key(21, *"side", 10)
            self.assertEqual(self.side.notice.current(), "rename: side is taken", drop)
            self.assertEqual(hcgui.read_names(self.state), {"account:solo": "Side"}, drop)

    def test_a_rename_is_seen_in_every_window(self):
        other = hcgui.Sidebar(FakeScr(40, 30), self.state, self.state / "w-2")  # another window
        other.refresh_once()
        other.refresh_extras(self.now)
        other.sync()
        other.draw()
        self.rename(37, "Team")
        other.draw()  # names.json is read again at its next draw
        self.assertEqual(other.s.scr.line(37), hcgui.glyph(" Team²    87%"))
        hcgui.change_names({"account:claude": "Max"}, self.state)  # renamed in the other window: seen here
        self.side.draw()
        self.assertEqual(self.lines()[35], hcgui.glyph(" Max¹   42%"))
        other.on_key(ord("?"))
        other.draw()
        self.assertIn(hcgui.glyph(" ¹       Max, main"), other.s.scr.lines())  # the "?" list's marks too
        self.assertIn(hcgui.glyph(" ²       Team"), other.s.scr.lines())
        self.assertIn(hcgui.glyph(" ³       other, guest"), other.s.scr.lines())  # not subscriptions: as they are

    def test_the_marks_in_the_question_mark_list_name_the_display_names(self):
        self.scr.height = 60
        self.key("?")
        self.assertIn(hcgui.glyph(" ²       work"), self.lines())
        self.key("?")  # closes it
        self.rename(self.side.usage_ys[2], "Team plan")
        self.key("?")
        lines = self.lines()
        self.assertIn(hcgui.glyph(" ²       Team plan"), lines)
        self.assertNotIn(hcgui.glyph(" ²       work"), lines)
        self.assertEqual(hcgui.help_lines(29, 60, hcgui.read_names(self.state)), lines[:len(hcgui.help_lines(29, 60))])

    def test_junk_in_names_json_draws_the_files_names(self):
        (self.state / "names.json").write_text(json.dumps({
            "account:work": "a\nb", "account:solo": 7, "account:claude": " pad", "account:": "x",
            "account:two words": "x"}))
        self.side.draw()
        self.assertEqual(self.lines()[35:38], [hcgui.glyph(w) for w in (" claude¹  42%", " solo     55%",
                                                                        " work²    87%")])
        self.right_click(37)
        self.assertEqual(self.side.menu.title, "work")
        self.side.mouse_quiet = 0.0
        with pressed(20, 2):  # a press outside closes it
            self.key(hcgui.curses.KEY_MOUSE)
        (self.state / "names.json").write_text("{not json")
        self.side.draw()
        self.assertEqual(self.lines()[37], hcgui.glyph(" work²    87%"))
        self.pick(37, "Rename")
        self.key(21, *"Team", 10)  # a broken file is replaced by a good one
        self.assertEqual(hcgui.read_names(self.state), {"account:work": "Team"})

    def test_a_lines_menu_closes_when_its_subscription_goes(self):
        self.right_click(37)
        self.assertEqual(self.side.menu.item, hcgui.usage_item("work"))
        self.hc.usage = "\n".join([usage_line("claude", 42, self.reset), usage_line("solo", 55, self.reset)]) + "\n"
        self.side.usage_asked = True
        self.side.refresh_extras(self.now + 1)
        self.side.draw()
        self.assertEqual(self.side.usage_names, ["claude", "solo"])
        self.assertIsNone(self.side.menu)  # its file has gone: the menu goes, though the other lines stay
        self.right_click(self.side.usage_ys[1])
        self.assertEqual(self.side.menu.item, hcgui.usage_item("solo"))
        self.side.draw()
        self.assertIsNotNone(self.side.menu)

    def test_keys_typed_after_the_right_click_go_to_the_view(self):
        self.right_click(35)
        with mock.patch.object(hcgui, "send_keys_to_view") as send:
            self.key("u")  # meant for the terminal, as after any right click: nothing hidden
        send.assert_called_once()
        self.assertEqual(send.call_args[0][0][0], ord("u"))
        self.assertIsNone(self.side.menu)
        self.assertTrue(hcgui.read_usage_shown(self.state))

    def test_off_with_mini_usage_0_no_switch(self):
        hcgui.write_usage_shown(False, self.state)
        with mock.patch.dict(os.environ, {"HCGUI_USAGE": "0"}):
            self.key("u")
            self.assertEqual(self.side.notice.current(), "usage is off (HCGUI_USAGE=0)")
            self.assertEqual(hcgui.read_text(self.state / "usagelines"), "hidden")  # left as it is
            self.key("a")
            self.assertNotIn("usage", [e.action for e in self.side.menu.entries])  # nothing to show

    def test_a_notice_and_a_prompt_go_above_them(self):
        self.side.notice.say("hello there", bad=False)
        self.side.draw()
        lines = self.lines()
        self.assertEqual(lines[34], "hello there")  # right above them; the blank line above it
        self.assertEqual(lines[33], "")
        self.assertTrue(lines[35].startswith(" claude"))
        self.key("s")  # the new-space prompt
        lines = self.lines()
        typed = next(i for i, line in enumerate(lines) if line.startswith("> "))
        self.assertEqual(typed, 34)
        self.assertTrue(lines[35].startswith(" claude"))

    def test_short_sidebars_drop_them_before_the_list(self):
        for height in range(3, 16):
            self.scr.height = height
            self.side.draw()
            lines = self.lines()
            if self.side.usage_ys:
                self.assertGreaterEqual(self.side.body_height, hcgui.USAGE_LIST_MIN, height)
                self.assertEqual(len(self.side.usage_ys), 3, height)
            else:
                self.assertNotIn("%", "".join(lines), height)
            self.assertEqual(self.side.usage_ys != [], height >= 1 + 3 + hcgui.USAGE_LIST_MIN, height)
            cursor = self.side.cursor_pos
            plan = self.side.sections().plan(self.side.body_height, cursor)
            self.assertTrue(any(row.item == cursor for _, row in plan), height)  # the cursor's line stays

    def test_a_menu_never_covers_them(self):
        for y, item in sorted(self.side.rows.items()):
            items = self.side.items()
            self.side.cursor, self.side.cursor_pos = item, items.index(item)
            self.side.draw()
            before = self.lines()[35:38]
            self.key("a")
            if self.side.menu is None:
                continue
            self.assertEqual(self.lines()[35:38], before, (y, item))
            self.side.menu = None
            self.side.draw()

    def test_the_readme_says_how_to_set_it_up(self):
        readme = " ".join((ROOT / "README.md").read_text().split())
        for words in ("HCGUI_USAGE=0", "5-hour usage", "The status line stays empty",
                      '{"statusLine": {"type": "command", "command": "sh \\"$HOME/.local/share/hcgui/usage.sh\\" '
                      'claude"}}',
                      # one Mac (home is this Mac): the install folder is there, and a clone into it would fail
                      "Skip this step when the home machine is this Mac"):
            self.assertTrue(words in readme, words)

    def test_the_shipped_notes_name_no_reset_time(self):
        # owner, 24 Nov: "no need for the 'resets xx:xx'": README, build.sh's header and the code's module
        # docstring say the share only, and that the lines can be hidden
        build = " ".join((ROOT / "build.sh").read_text().replace("#", " ").split())
        code = " ".join((ROOT / "hcgui.py").read_text()[:2000].split())
        readme = " ".join((ROOT / "README.md").read_text().split())
        for name, text in (("build.sh", build), ("hcgui.py", code), ("README.md", readme)):
            self.assertIsNone(re.search(r"when (the window|it) resets|resets \d\d:\d\d", text), name)
        self.assertIn("how much of its 5-hour window is used (u or a right click on a line hides them)", build)



# The view relay: drops to a terminal of another machine ------------------------------------------------------------
OPEN, CLOSE = hcgui.PASTE_OPEN, hcgui.PASTE_CLOSE


def parse_all(chunks, cap=hcgui.PASTE_CAP):
    """Feed `chunks` one read each; the plain bytes (joined, with what was held at the end) and the pastes."""
    parser = hcgui.PasteParser(cap)
    plain, pastes = b"", []
    for chunk in chunks:
        for kind, payload in parser.feed(chunk, 0.0):
            if kind == "data":
                plain += payload
            else:
                pastes.append(payload)
    return plain + parser.take(), pastes


def stored_png(path, width, height):
    """A PNG of a colour ramp, stored without compression: width * height * 3 bytes on disk (over 8 MB when
    asked), and small as a JPEG."""
    import struct
    import zlib

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    row = b"\0" + bytes(i * 255 // (width * 3) for i in range(width * 3))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(row * height, 0)) + chunk(b"IEND", b""))


def big_file(path, size=9_000_000):
    """A file of `size` bytes without writing them (sparse)."""
    with open(path, "wb") as f:
        f.truncate(size)


class PasteParserTests(unittest.TestCase):
    """PasteParser: plain bytes at once, pastes whole, markers split anywhere."""

    STREAM = b"ab\x1b[A" + OPEN + b"/Users/me/Desktop/shot\\ one.png" + CLOSE + b"cd\x1b[B"

    def test_plain_keys_go_on_at_once(self):
        parser = hcgui.PasteParser()
        for keys in (b"abc", b"\x1b[A", b"\x03", b"\x1b[<0;3;50M", b"\x1b[20~", b"\x1b[2004h", b"\r"):
            self.assertEqual(parser.feed(keys, 1.0), [("data", keys)], keys)
            self.assertIsNone(parser.deadline())

    def test_a_possible_marker_start_is_held_at_most_marker_hold(self):
        for tail in (b"\x1b", b"\x1b[", b"\x1b[2", b"\x1b[20", b"\x1b[200"):
            parser = hcgui.PasteParser()
            self.assertEqual(parser.feed(b"x" + tail, 5.0), [("data", b"x")], tail)
            self.assertEqual(parser.deadline(), 5.0 + hcgui.MARKER_HOLD)
            self.assertEqual(parser.due(5.0 + hcgui.MARKER_HOLD / 2), b"")
            self.assertEqual(parser.due(5.0 + hcgui.MARKER_HOLD), tail)  # then it goes on, unchanged
            self.assertIsNone(parser.deadline())
        parser = hcgui.PasteParser()
        parser.feed(b"\x1b", 1.0)
        parser.feed(b"[", 1.015)  # grown, not new: the first byte's time counts
        self.assertEqual(parser.deadline(), 1.0 + hcgui.MARKER_HOLD)
        self.assertEqual(parser.feed(b"A", 1.016), [("data", b"\x1b[A")])  # an arrow key after all
        parser.feed(b"\x1b", 2.0)
        self.assertEqual(parser.feed(b"q\x1b", 2.01), [("data", b"\x1bq")])  # a new hold: its own time
        self.assertEqual(parser.deadline(), 2.01 + hcgui.MARKER_HOLD)

    def test_markers_split_at_every_byte_position(self):
        whole = self.STREAM
        want = (b"ab\x1b[Acd\x1b[B", [b"/Users/me/Desktop/shot\\ one.png"])
        self.assertEqual(parse_all([whole]), want)
        for i in range(len(whole) + 1):
            for j in range(i, len(whole) + 1):
                self.assertEqual(parse_all([whole[:i], whole[i:j], whole[j:]]), want, (i, j))
        self.assertEqual(parse_all([bytes([b]) for b in whole]), want)  # a byte per read

    def test_two_pastes_and_keys_in_one_read(self):
        plain, pastes = parse_all([OPEN + b"one" + CLOSE + b"k" + OPEN + CLOSE + b"\x1b"])
        self.assertEqual((plain, pastes), (b"k\x1b", [b"one", b""]))

    def test_a_paste_over_the_cap_passes_through_unchanged(self):
        stream = b"a" + OPEN + b"x" * 30 + CLOSE + b"b" + OPEN + b"short" + CLOSE
        for size in (1, 7, len(stream)):
            chunks = [stream[i:i + size] for i in range(0, len(stream), size)]
            self.assertEqual(parse_all(chunks, cap=20), (b"a" + OPEN + b"x" * 30 + CLOSE + b"b", [b"short"]), size)

    def test_a_paste_without_its_end_goes_on_unchanged_after_a_quiet_while(self):
        parser = hcgui.PasteParser()
        self.assertEqual(parser.feed(b"k" + OPEN + b"/a", 10.0), [("data", b"k")])
        self.assertEqual(parser.feed(b"/b", 10.5), [])
        self.assertEqual(parser.deadline(), 10.5 + hcgui.PASTE_IDLE)
        self.assertEqual(parser.due(10.5 + hcgui.PASTE_IDLE / 2), b"")
        self.assertEqual(parser.due(10.5 + hcgui.PASTE_IDLE), OPEN + b"/a/b")
        self.assertEqual(parser.feed(b"x" + CLOSE, 12.0), [("data", b"x" + CLOSE)])  # no paste any more

    def test_take_gives_back_what_is_held_as_typed(self):
        parser = hcgui.PasteParser()
        parser.feed(OPEN + b"/a" + CLOSE[:3], 1.0)
        self.assertEqual(parser.take(), OPEN + b"/a" + CLOSE[:3])
        self.assertEqual(parser.feed(b"z", 1.0), [("data", b"z")])  # afresh
        parser.feed(b"\x1b[", 1.0)
        self.assertEqual(parser.take(), b"\x1b[")
        self.assertEqual(hcgui.raw_event(("paste", b"p")), OPEN + b"p" + CLOSE)
        self.assertEqual(hcgui.raw_event(("data", b"d")), b"d")


class DropDecisionTests(unittest.TestCase):
    """drop_files: which pastes are drops to send; shell_escape and drop_paste: what is pasted instead."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.shot = self.dir / "Screen Shot (1).png"
        self.shot.write_bytes(b"png")
        self.note = self.dir / "note.txt"
        self.note.write_text("x")

    def test_only_existing_local_files_shown_on_another_machine(self):
        shot, note = str(self.shot), str(self.note)
        text = hcgui.shell_escape(shot) + " " + hcgui.shell_escape(note)
        self.assertEqual(hcgui.drop_files(text, "rig/t1"), [shot, note])
        self.assertEqual(hcgui.drop_files("\n " + text + " \n", "mini/t7"), [shot, note])  # white space at the ends
        self.assertEqual(hcgui.drop_files(f"'{shot}'", "rig/t1"), [shot])  # quoted
        self.assertIsNone(hcgui.drop_files(text, "t1"))  # a terminal of this Mac opens the path itself
        self.assertIsNone(hcgui.drop_files(text, ""))  # nothing shown
        for paste in ("", "   ", "hello world", str(self.dir), shot + "x", "note.txt", "~/note.txt",
                      hcgui.shell_escape(shot) + " hello", f"'{shot}", shot.replace(" ", "  ")):
            self.assertIsNone(hcgui.drop_files(paste, "rig/t1"), paste)

    def test_at_most_twenty_files(self):
        word = hcgui.shell_escape(str(self.note))
        self.assertEqual(len(hcgui.drop_files(" ".join([word] * 20), "rig/t1")), 20)
        self.assertIsNone(hcgui.drop_files(" ".join([word] * 21), "rig/t1"))
        self.assertEqual(hcgui.drop_files(word + " " * hcgui.DROP_TEXT, "rig/t1"), [str(self.note)])  # trimmed
        self.assertIsNone(hcgui.drop_files("/x" * hcgui.DROP_TEXT, "rig/t1"))  # never split: too long for a drop

    def test_escape_as_ghostty_does_and_back(self):
        self.assertEqual(hcgui.shell_escape("/a b/c(1)&$x.png"), "/a\\ b/c\\(1\\)\\&\\$x.png")
        nasty = "/tmp/a b\\c\"d'e`f!g#h$i&j;k|l*m?n(o)p[q]r{s}t<u>v\tw~x=y%z.png"
        self.assertEqual(shlex.split(hcgui.shell_escape(nasty)), [nasty])
        self.assertEqual(hcgui.shell_escape("/Users/x/dev/app/shot_one.png"), "/Users/x/dev/app/shot_one.png")

    def test_the_new_paste_keeps_the_white_space_at_its_ends(self):
        self.assertEqual(hcgui.drop_paste(" /a\\ b.png ", ["/r/a_b.png"]), OPEN + b" /r/a_b.png " + CLOSE)
        self.assertEqual(hcgui.drop_paste("/a /b", ["/r/a", "/r/my b"]), OPEN + b"/r/a /r/my\\ b" + CLOSE)

    def test_landed_path(self):
        self.assertEqual(hcgui.landed_path('{"bytes": 3, "path": "/Users/x/dev/app/a.png"}'),
                         "/Users/x/dev/app/a.png")
        for junk in ("", "nope", "[]", '{"path": 3}', '{"bytes": 3}', '{"path": ""}',
                     '{"path": "/x\\u001b[201~rm"}', '{"path": "/x\\ny"}', '{"path": "/x\\ud800.png"}'):
            self.assertEqual(hcgui.landed_path(junk), "", junk)

    def test_hidden_files_and_the_library_folder_are_never_sent(self):
        """A program on another machine can put a path on this Mac's clipboard (OSC 52): a paste of
        ~/.ssh/id_ed25519 must not send the key there."""
        home = "/Users/me"
        for path in ("/Users/me/Desktop/Screen Shot.png", "/Users/me/Documents/a.pdf", "/Volumes/USB/Library/a.png",
                     "/Users/me/Library/Mobile Documents/com~apple~CloudDocs/a.png",  # iCloud Drive
                     "/Users/me/Library/CloudStorage/Dropbox/a.png", "/Users/me/library/cloudstorage/GoogleDrive/b",
                     "/var/folders/xy/T/TemporaryItems/NSIRD_screencaptureui_1/Screenshot.png",  # a screenshot's
                     "/Users/me/Libraryx/a.png", "/Users/first.last/a.png", "/Library/Desktop Pictures/a.heic"):
            self.assertEqual(hcgui.drop_refusal([path], home), "", path)
        for path, why in (("/Users/me/.ssh/id_ed25519", "in a hidden folder"),
                          ("/Users/me/.netrc", "a hidden file"),
                          ("/Users/me/dev/.git/config", "in a hidden folder"),
                          ("/Users/me/Desktop/../.aws/credentials", "in a hidden folder"),
                          ("/Users/me/Desktop/./a.png", "in a hidden folder"),
                          ("/Users/me/Library/Keychains/login.keychain-db", "in the Library folder"),
                          ("/Users/me/Library/a.plist", "in the Library folder"),
                          ("/users/ME/LIBRARY/Cookies/Cookies.binarycookies", "in the Library folder"),  # no case
                          ("//Users//me/Library/Mail/V10/a.emlx", "in the Library folder"),
                          ("/Users/me/Library/Mobile Documents", "in the Library folder")):
            self.assertEqual(hcgui.drop_refusal([path], home), f"drop: {os.path.basename(path)} not sent: {why}", path)
        accented = unicodedata.normalize("NFD", "/Users/josé/Library/Keychains/k")  # as a file URL may spell it
        self.assertEqual(hcgui.drop_refusal([accented], "/Users/josé"), "drop: k not sent: in the Library folder")
        self.assertEqual(hcgui.drop_refusal(["/Users/me/a.png", "/Users/me/.zshrc", "/Users/me/.ssh/k"], home),
                         "drop: .zshrc not sent: a hidden file")  # the first such file
        self.assertEqual(hcgui.drop_refusal([str(self.shot)]), "")  # this test's files, with the real home


class DropSendTests(unittest.TestCase):
    """send_drop and put_file with a stand-in hc: what is sent, the 8 MB path, and the notice on a failure."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.hc = FakeHc([])
        self.shot = self.dir / "shot one.png"
        self.shot.write_bytes(b"\x89PNG small")

    def test_small_files_are_put_as_they_are(self):
        note = self.dir / "note.txt"
        note.write_text("x")
        landed, why = hcgui.send_drop([str(self.shot), str(note)], "rig/t1", self.hc)
        self.assertEqual((landed, why), (["/Users/x/dev/app/shot_one.png", "/Users/x/dev/app/note.txt"], ""))
        self.assertEqual([c[:3] for c in self.hc.calls], [("put", "--json", "rig/t1")] * 2)
        self.assertEqual([p[:2] for p in self.hc.puts], [("rig/t1", str(self.shot)), ("rig/t1", str(note))])

    def test_a_failure_names_the_file_and_why(self):
        note = self.dir / "note.txt"
        note.write_text("x")
        self.hc.put_error = ("not_found", 'no terminal "rig/t1"', 3)
        self.assertEqual(hcgui.send_drop([str(note), str(self.shot)], "rig/t1", self.hc),
                         (None, 'drop: note.txt not sent: no terminal "rig/t1"'))
        self.assertEqual(len(self.hc.puts), 1)  # the first failure ends the drop
        self.hc.put_error = None
        self.hc.put_answer = "Saved."
        self.assertEqual(hcgui.send_drop([str(note)], "rig/t1", self.hc),
                         (None, "drop: note.txt not sent: hc's answer was not understood"))

        def slow(*args, **kw):
            raise subprocess.TimeoutExpired("hc", hcgui.PUT_TIMEOUT)

        self.assertEqual(hcgui.send_drop([str(note)], "rig/t1", slow),
                         (None, "drop: note.txt not sent: hc did not answer"))

        def broken(*args, **kw):
            raise RuntimeError("boom")

        self.assertEqual(hcgui.send_drop([str(note)], "rig/t1", broken), (None, "drop: note.txt not sent: boom"))

        def stdout_only(*args, **kw):  # hc's own 8 MB check, its error JSON on stdout only
            raise subprocess.CalledProcessError(6, "hc", stderr="", output=json.dumps(
                {"error": {"kind": "invalid_params", "message": "at most 8 MB per put"}}))

        self.assertEqual(hcgui.send_drop([str(note)], "rig/t1", stdout_only),
                         (None, "drop: note.txt not sent: at most 8 MB per put"))
        gone = str(self.dir / "gone.png")
        self.assertEqual(hcgui.send_drop([gone], "rig/t1", self.hc),
                         (None, "drop: gone.png not sent: could not be read"))

    def test_over_8_mb_another_kind_is_not_sent(self):
        big = self.dir / "movie.mov"
        big_file(big)
        self.assertEqual(hcgui.send_drop([str(big)], "rig/t1", self.hc), (None, "drop: movie.mov not sent: over 8 MB"))
        self.assertEqual(self.hc.puts, [])
        edge = self.dir / "edge.bin"
        big_file(edge, hcgui.PUT_MAX)  # exactly the limit: sent as it is
        self.assertEqual(hcgui.send_drop([str(edge)], "rig/t1", self.hc)[0], ["/Users/x/dev/app/edge.bin"])

    def test_over_8_mb_an_image_goes_as_a_smaller_jpeg_copy_deleted_after(self):
        big = self.dir / "Big Shot.PNG"
        big_file(big)
        made = []

        def shrink(source, copy):
            made.append((source, copy))
            Path(copy).write_bytes(b"\xff\xd8\xff small")
            return True

        landed, why = hcgui.send_drop([str(big)], "rig/t1", self.hc, shrink)
        self.assertEqual((landed, why), (["/Users/x/dev/app/Big_Shot.jpg"], ""))
        source, copy = made[0]
        self.assertEqual((source, Path(copy).name), (str(big), "Big Shot.jpg"))  # the same stem
        self.assertTrue(Path(copy).parent.name.startswith("hcgui-drop-"))
        self.assertEqual(self.hc.puts[0][1:], (copy, 9, b"\xff\xd8\xff "))
        self.assertFalse(Path(copy).parent.exists())  # the copy and its folder are gone

        def fails(source, copy):
            made.append((source, copy))
            return False

        self.assertEqual(hcgui.send_drop([str(big)], "rig/t1", self.hc, fails),
                         (None, "drop: Big Shot.PNG not sent: over 8 MB, could not be made smaller"))
        self.assertFalse(Path(made[-1][1]).parent.exists())

        def still_big(source, copy):
            made.append((source, copy))
            big_file(copy)
            return True

        self.assertEqual(hcgui.send_drop([str(big)], "rig/t1", self.hc, still_big),
                         (None, "drop: Big Shot.PNG not sent: over 8 MB, also when made smaller"))
        self.assertFalse(Path(made[-1][1]).parent.exists())
        self.assertEqual(len(self.hc.puts), 1)
        scratch = self.dir / "relay"  # the view relay's folder, which it removes when it ends
        scratch.mkdir()
        self.assertEqual(hcgui.send_drop([str(big)], "rig/t1", self.hc, shrink, str(scratch))[1], "")
        self.assertEqual(Path(made[-1][1]).parent.parent, scratch)
        self.assertEqual(list(scratch.iterdir()), [])
        scratch.rmdir()  # gone: the relay ended meanwhile
        self.assertEqual(hcgui.send_drop([str(big)], "rig/t1", self.hc, shrink, str(scratch)),
                         (None, "drop: Big Shot.PNG not sent: over 8 MB, could not be made smaller"))
        self.assertFalse(scratch.exists())
        self.assertTrue(hcgui.needs_copy(str(big)))
        self.assertFalse(hcgui.needs_copy(str(self.shot)))
        self.assertFalse(hcgui.needs_copy(str(self.dir / "gone.png")))

    def test_a_drop_given_up_sends_no_more_files(self):
        note = self.dir / "note.txt"
        note.write_text("x")
        landed, why = hcgui.send_drop([str(self.shot), str(note)], "rig/t1", self.hc,
                                      cancelled=lambda: len(self.hc.puts) > 0)
        self.assertEqual((landed, why), (None, "drop: note.txt not sent: given up"))
        self.assertEqual([p[1] for p in self.hc.puts], [str(self.shot)])

    def test_sips_makes_a_real_jpeg_under_8_mb(self):
        if not os.access(hcgui.SIPS, os.X_OK):
            self.skipTest("no sips")
        sides = []

        def shrink(source, copy):  # the real one, and the size it made
            done = hcgui.shrink_image(source, copy)
            sides.append(hcgui.image_side(copy))
            return done

        for name, width, height, side in (("screen shot.png", 1700, 1700, 1700), ("wide.png", 3000, 1000, 2576)):
            big = self.dir / name
            stored_png(big, width, height)  # 8.7 and 9 MB on disk
            self.assertGreater(big.stat().st_size, hcgui.PUT_MAX)
            self.assertEqual(hcgui.image_side(str(big)), width)
            landed, why = hcgui.send_drop([str(big)], "rig/t1", self.hc, shrink)
            self.assertEqual((landed, why), (["/Users/x/dev/app/" + Path(name).stem.replace(" ", "_") + ".jpg"], ""))
            _, copy, size, head = self.hc.puts[-1]
            self.assertEqual(head[:3], b"\xff\xd8\xff")  # a JPEG
            self.assertLess(size, hcgui.PUT_MAX)
            self.assertFalse(Path(copy).exists())
            self.assertEqual(sides[-1], side)  # made smaller to 2576 pixels a side, never larger
        self.assertEqual(hcgui.image_side(str(self.dir / "none.png")), 0)


class DropNoticeTests(unittest.TestCase):
    """The request file "ask": the relay's notice line beside "menu", and the tab bar reading both once."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.win = Path(self._tmp.name)
        patcher = mock.patch.object(hcgui.curses, "color_pair", lambda n: n << 8)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bar = hcgui.TabBar(FakeScr(5, 70), self.win, self.win / "shared")
        self.addCleanup(self.bar.stop_engine)
        self.hc = FakeHc([term("mini/t1", "/Users/x/dev/app", "claude-code", "alpha", "idle")])
        terms = hcgui.parse(self.hc("ls", "--json"))
        spaces, _ = hcgui.build_groups(terms, "mini", {})
        hcgui.write_snapshot(spaces[0], self.win, everything=terms, infos={})
        self.snap = hcgui.read_snapshot(self.win)
        hcgui.write_atomic(self.win / "panes", PANES)
        self.tm = FakeTmux().install(self)

    def test_a_notice_is_shown_once(self):
        hcgui.ask_notice("drop: x.png not sent: over 8 MB", self.win)
        self.assertEqual(hcgui.read_text(self.win / "ask"), "notice drop: x.png not sent: over 8 MB")
        self.assertNotEqual(hcgui.pick_stamp(self.win)[2], 0)  # the tab bar's loop wakes up for it
        self.bar.check_ask(self.snap, "mini/t1")
        self.assertEqual(self.bar.notice.current(), "drop: x.png not sent: over 8 MB")
        self.assertIsNone(self.bar.menu)
        self.assertEqual(self.tm.selected(), [])  # a notice takes no keyboard
        self.assertFalse((self.win / "ask").exists())
        self.bar.notice.clear()
        self.bar.check_ask(self.snap, "mini/t1")
        self.assertEqual(self.bar.notice.current(), "")
        self.bar.draw(self.snap, "mini/t1")
        hcgui.ask_notice("drop: y.png not sent: hc did not answer", self.win)
        self.bar.check_ask(self.snap, "mini/t1")
        self.bar.draw(self.snap, "mini/t1")
        self.assertIn("drop: y.png not sent: hc did not answer", "\n".join(self.bar.s.scr.lines()))

    def test_a_menu_waiting_beside_it_still_opens(self):
        hcgui.write_atomic(self.win / "ask", "menu\n")  # a right click in the view, not read yet
        hcgui.ask_notice("drop: x.png not sent: over 8 MB", self.win)
        self.assertEqual(hcgui.read_text(self.win / "ask").splitlines(),
                         ["menu", "notice drop: x.png not sent: over 8 MB"])
        self.bar.check_ask(self.snap, "mini/t1")
        self.assertEqual(self.bar.menu.address, "mini/t1")
        self.assertEqual(self.tm.selected(), ["%2"])
        self.assertEqual(self.bar.notice.current(), "drop: x.png not sent: over 8 MB")  # kept for after the menu

    def test_info_is_a_notice_that_is_no_error_and_the_last_line_wins(self):
        hcgui.ask_notice("drop: sending shot.png to mini; keys wait", self.win, bad=False)
        self.assertEqual(hcgui.read_text(self.win / "ask"), "info drop: sending shot.png to mini; keys wait")
        self.bar.check_ask(self.snap, "mini/t1")
        self.assertEqual((self.bar.notice.current(), self.bar.notice.bad),
                         ("drop: sending shot.png to mini; keys wait", False))
        hcgui.ask_notice("drop: sending shot.png to mini; keys wait", self.win, bad=False)
        hcgui.ask_notice("drop: shot.png not sent: hc did not answer", self.win)
        self.bar.check_ask(self.snap, "mini/t1")
        self.assertEqual((self.bar.notice.current(), self.bar.notice.bad),
                         ("drop: shot.png not sent: hc did not answer", True))
        hcgui.ask_notice("drop: x not sent: y", self.win)
        hcgui.ask_notice("drop: 2 files sent to mini", self.win, bad=False)
        self.bar.check_ask(self.snap, "mini/t1")
        self.assertEqual((self.bar.notice.current(), self.bar.notice.bad), ("drop: 2 files sent to mini", False))

    def test_errors_go_to_error_log_once_in_a_row(self):
        for _ in range(3):
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                hcgui.log_error("extras", self.win)
        text = (self.win / "error.log").read_text()
        self.assertEqual(text.count("RuntimeError: boom"), 1)
        self.assertIn("extras (pid", text)

    def test_the_line_holds_no_control_character(self):
        hcgui.ask_notice("drop: a\nb\x1b[2J\udcff.png not sent: x", self.win)
        lines = (self.win / "ask").read_text().splitlines()
        self.assertEqual(lines, ["notice drop: a b [2J?.png not sent: x"])
        for _ in range(12):
            hcgui.ask_notice("n", self.win)
        self.assertEqual(len(hcgui.take_ask(self.win)), hcgui.ASK_LINES)
        self.assertEqual(hcgui.take_ask(self.win), [])


RELAY_CHILD = r"""
import os, signal, struct, sys, termios, fcntl, tty
rec = sys.argv[1]
def put(name, text):
    with open(os.path.join(rec, name), "a") as f:
        f.write(text)
lflag = termios.tcgetattr(0)[3]
put("start", f"{bool(lflag & termios.ICANON)} {bool(lflag & termios.ECHO)}\n")
def winch(*_):
    rows, cols = struct.unpack("hhhh", fcntl.ioctl(0, termios.TIOCGWINSZ, b"\0" * 8))[:2]
    put("size", f"{rows} {cols}\n")
signal.signal(signal.SIGWINCH, winch)
winch()
put("pid", f"{os.getpid()}\n")
tty.setraw(0)
os.write(1, b"READY\r\n")
got = b""
while True:
    try:
        data = os.read(0, 4096)
    except InterruptedError:
        continue
    if not data:
        break
    with open(os.path.join(rec, "in.bin"), "ab") as f:
        f.write(data)
    os.write(1, data.replace(b"\x1b", b"^"))
    got += data
    if b"@@exit7@@" in got:
        os._exit(7)
"""

RELAY_HC = """#!/bin/sh
# stands in for hc put: logs, waits a little (keys typed meanwhile must follow the paste), lands the file in /remote
printf '%s\\n' "$*" >>"$HC_LOG"
[ "$1 $2" = "put --json" ] || exit 1
case "$4" in
  *fail*) echo '{"error":{"kind":"invalid_params","message":"at most 8 MB per put"}}' >&2; exit 6 ;;
esac
sleep 0.3
printf '{"bytes":%s,"path":"/remote/in/%s"}\\n' "$(wc -c <"$4" | tr -d ' ')" "$(basename "$4" | tr ' ' '_')"
"""


class RelayTests(unittest.TestCase):
    """The real relay (hcgui.relay_view) in a pseudo terminal, around a stand-in child that records what it reads,
    with a stand-in hc (HCGUI_HC)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.win = self.tmp / "w-1"
        self.win.mkdir()
        self.rec = self.tmp / "rec"
        self.rec.mkdir()
        (self.tmp / "child.py").write_text(RELAY_CHILD)
        hc = self.tmp / "hc"
        hc.write_text(RELAY_HC)
        hc.chmod(0o755)
        self.hc_log = self.tmp / "hc.log"
        self.env = dict(os.environ, HCGUI_HC=str(hc), HCGUI_WINDOW=str(self.win), HCGUI_STATE=str(self.tmp),
                        HC_LOG=str(self.hc_log), PYTHONDONTWRITEBYTECODE="1")
        self.out = b""
        self.pid, self.fd, self.status = 0, -1, None
        self.addCleanup(self.stop)

    def start(self, target="rig/t1", cols=100, rows=30):
        import fcntl
        import pty
        import struct
        import termios
        if target is not None:
            hcgui.write_atomic(self.win / "target", target + "\n")
        code = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); import hcgui; "
                f"sys.exit(hcgui.relay_view([sys.executable, {str(self.tmp / 'child.py')!r}, {str(self.rec)!r}]))")
        pid, fd = pty.fork()
        if pid == 0:
            try:
                fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
                os.execve(sys.executable, [sys.executable, "-c", code], self.env)
            finally:
                os._exit(127)
        self.pid, self.fd, self.status, self.out = pid, fd, None, b""
        self.assertTrue(self.wait_out(b"READY"), self.out)

    def stop(self):
        """End this test's relay (its child ends with the pseudo terminal) and close its side; once only."""
        if self.pid and self.status is None:
            try:
                os.kill(self.pid, signal.SIGKILL)
            except OSError:
                pass
            self.reap()
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = -1

    def reap(self, timeout=5.0):
        """The relay's wait status once it ended. Its output is read meanwhile, as tmux does: a process that ends
        waits for its terminal's output to be read first."""
        deadline = time.monotonic() + timeout
        while self.status is None and time.monotonic() < deadline:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.status = status
                break
            if self.fd >= 0:
                self.read_some(0.02)
            else:
                time.sleep(0.02)
        return self.status

    def read_some(self, wait=0.05):
        import select
        ready, _, _ = select.select([self.fd], [], [], wait)
        if ready:
            try:
                self.out += os.read(self.fd, 65536)
            except OSError:
                pass

    def wait_out(self, want, timeout=6.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if want in self.out:
                return True
            self.read_some()
        return False

    def got(self):
        path = self.rec / "in.bin"
        return path.read_bytes() if path.exists() else b""

    def wait_got(self, want, timeout=6.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.read_some()
            if self.got() == want:
                return True
        return False

    def child_pid(self):
        text = hcgui.read_text(self.rec / "pid")
        return int(text) if text.isdigit() else 0

    def test_keys_a_drop_resize_and_exit_code(self):
        self.start(cols=100, rows=30)
        self.assertEqual(hcgui.read_text(self.rec / "start"), "True True")  # the pane's settings, not raw
        self.assertEqual(hcgui.read_text(self.rec / "size").splitlines()[0], "30 100")
        keys = b"ls -la\r\x03\x1b[A\x1bOP\x1b[<0;3;50M\x7f\x1b"
        os.write(self.fd, keys)
        self.assertTrue(self.wait_got(keys), self.got())  # unchanged, the lone esc a moment later
        self.assertIn(b"ls -la\r\x03^[A", self.out)  # and the child's output comes back as it wrote it
        # a drop: Ghostty's escaped path in a bracketed paste, keys typed while it is sent
        shot = self.tmp / "shot one.png"
        shot.write_bytes(b"\x89PNG")
        os.write(self.fd, OPEN + hcgui.shell_escape(str(shot)).encode() + CLOSE[:2])
        time.sleep(0.03)
        os.write(self.fd, CLOSE[2:] + b"after")  # the end marker split over two reads
        time.sleep(0.1)
        os.write(self.fd, b" more")  # hc put takes 0.3 s: these wait, then follow the new paste
        want = keys + OPEN + b"/remote/in/shot_one.png" + CLOSE + b"after more"
        self.assertTrue(self.wait_got(want), self.got())
        self.assertEqual(self.hc_log.read_text(), f"put --json rig/t1 {shot}\n")
        # a resize of the pane reaches the child
        import fcntl
        import struct
        import termios
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 41, 133, 0, 0))
        self.assertTrue(wait_for(lambda: hcgui.read_text(self.rec / "size").splitlines()[-1] == "41 133"),
                        hcgui.read_text(self.rec / "size"))
        os.write(self.fd, b"@@exit7@@")
        self.assertIsNotNone(self.reap())
        self.assertEqual(os.waitstatus_to_exitcode(self.status), 7)  # the child's exit code is the relay's

    def test_a_failed_drop_pastes_the_original_and_tells_the_tab_bar(self):
        self.start()
        bad = self.tmp / "fail shot.png"
        bad.write_bytes(b"\x89PNG")
        paste = OPEN + hcgui.shell_escape(str(bad)).encode() + CLOSE
        os.write(self.fd, paste + b"k")
        self.assertTrue(self.wait_got(paste + b"k"), self.got())
        self.assertEqual(hcgui.read_text(self.win / "ask").splitlines()[-1],  # after "sending", on a slow machine
                         "notice drop: fail shot.png not sent: at most 8 MB per put")

    def test_a_terminal_of_this_mac_no_target_or_other_text_pass_unchanged(self):
        shot = self.tmp / "shot.png"
        shot.write_bytes(b"\x89PNG")
        paste = OPEN + str(shot).encode() + CLOSE
        for target in ("t1", ""):
            with self.subTest(target=target):
                self.start(target=target)
                os.write(self.fd, paste + b"x" + OPEN + b"hello" + CLOSE)
                self.assertTrue(self.wait_got(paste + b"x" + OPEN + b"hello" + CLOSE), self.got())
                self.assertFalse(self.hc_log.exists())  # no hc call
                os.write(self.fd, b"@@exit7@@")
                self.reap()
                self.stop()
                (self.rec / "in.bin").unlink()
        self.start(target="rig/t1")
        os.write(self.fd, OPEN + b"some text, not a path" + CLOSE)
        self.assertTrue(self.wait_got(OPEN + b"some text, not a path" + CLOSE), self.got())
        self.assertFalse(self.hc_log.exists())

    def test_a_pick_while_a_drop_is_sent_pastes_nothing(self):
        self.start()
        shot = self.tmp / "shot.png"
        shot.write_bytes(b"\x89PNG")
        os.write(self.fd, OPEN + str(shot).encode() + CLOSE)
        self.assertTrue(wait_for(self.hc_log.exists))  # the put has started; it takes 0.3 s
        hcgui.write_atomic(self.win / "target", "rig/t2\n")  # a pick: another terminal of the same machine
        os.write(self.fd, b"k")
        self.assertTrue(self.wait_got(b"k"), self.got())  # the key that waited goes on, and no paste
        time.sleep(0.2)
        self.assertEqual(self.got(), b"k")
        self.assertEqual(hcgui.read_text(self.win / "ask").splitlines()[-1],
                         "notice drop: not pasted: another terminal is shown now")

    def test_closing_the_pane_ends_the_child(self):
        self.start()
        child = self.child_pid()
        self.assertTrue(child)
        os.close(self.fd)  # the pane is closed
        self.fd = -1
        self.assertIsNotNone(self.reap())
        self.assertTrue(wait_for(lambda: subprocess.run(["/bin/kill", "-0", str(child)],
                                                        capture_output=True).returncode != 0))

    def test_sighup_and_sigterm_end_the_relay_and_the_child(self):
        for sig in (signal.SIGHUP, signal.SIGTERM):
            with self.subTest(sig=sig):
                for name in ("pid", "start", "size"):
                    (self.rec / name).unlink(missing_ok=True)
                self.start()
                child = self.child_pid()
                os.kill(self.pid, sig)
                self.assertIsNotNone(self.reap())
                self.assertTrue(wait_for(lambda: subprocess.run(["/bin/kill", "-0", str(child)],
                                                                capture_output=True).returncode != 0))
                self.stop()

    def test_stray_interrupts_do_not_end_the_relay(self):
        self.start()
        for sig in (signal.SIGINT, signal.SIGQUIT, signal.SIGTSTP):
            os.kill(self.pid, sig)
        time.sleep(0.3)
        self.assertEqual(os.waitpid(self.pid, os.WNOHANG), (0, 0))
        os.write(self.fd, b"z")
        self.assertTrue(self.wait_got(b"z"))

    def test_no_terminal_runs_the_child_in_its_place(self):
        proc = subprocess.Popen([sys.executable, "-c", f"import sys; sys.path.insert(0, {str(ROOT)!r}); "
                                 "import hcgui; hcgui.relay_view(['/bin/sh', '-c', 'echo $$; exit 4'])"],
                                env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
        out, _ = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 4)
        self.assertEqual(out.split(), [str(proc.pid)])  # exec'd in its place: no relay, no pseudo terminal


class RelayDropTests(unittest.TestCase):
    """ViewRelay's drops driven step by step, on pipes (no pseudo terminal; a socket pair stands in for view.sh's
    terminal) with a stand-in `hc put` that can wait or change the shown terminal while it runs: a pick meanwhile,
    the tab bar told about a slow drop, a drop given up at DROP_TIMEOUT, a file that is never sent, and the smaller
    copy removed when the relay ends during a send."""

    def setUp(self):
        import socket
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.win = self.tmp / "w-1"
        self.win.mkdir()
        hcgui.write_atomic(self.win / "target", "mini/t7\n")
        self.shot = self.tmp / "shot one.png"
        self.shot.write_bytes(b"\x89PNG")
        self.note = self.tmp / "note.txt"
        self.note.write_text("x")
        ours, self.peer = socket.socketpair()  # what the relay types for view.sh arrives at self.peer
        self.peer.setblocking(False)
        self.addCleanup(self.peer.close)
        master = ours.detach()
        os.set_blocking(master, False)
        self.fds = dict(zip(("in_r", "in_w"), os.pipe()))
        self.fds.update(zip(("out_r", "out_w"), os.pipe()))
        self.during = lambda args: None  # runs inside each put
        self.fail = False
        self.puts = []
        self.threads = set()
        self.go = threading.Event()  # a put that waits, waits for this
        self.relay = hcgui.ViewRelay(master, 0, self.win, self.fds["in_r"], self.fds["out_w"], runner=self.put)
        self.addCleanup(self.finish)

    def finish(self):
        self.relay.close()
        self.go.set()
        for thread in list(self.threads):
            thread.join(5)
        for fd in self.fds.values():
            try:
                os.close(fd)
            except OSError:
                pass

    def put(self, *args, **kw):
        self.threads.add(threading.current_thread())
        self.puts.append(args[3])
        self.during(args)
        if self.fail:
            raise subprocess.CalledProcessError(6, "hc", stderr=json.dumps(
                {"error": {"kind": "invalid_params", "message": "at most 8 MB per put"}}))
        return json.dumps({"bytes": 1, "path": "/remote/" + os.path.basename(args[3]).replace(" ", "_")})

    def type(self, data):
        os.write(self.fds["in_w"], data)
        self.assertTrue(self.relay.from_outer())

    def sent(self):
        """The sending thread's answer, taken as the relay's loop takes it."""
        import select
        self.assertTrue(select.select([self.relay.done_r], [], [], 5)[0])
        self.relay.drain(self.relay.done_r)
        self.relay.drop_sent()

    def got(self):
        data = b""
        while True:
            try:
                chunk = self.peer.recv(65536)
            except BlockingIOError:
                return data
            if not chunk:
                return data
            data += chunk

    def paste_of(self, *paths):
        return OPEN + " ".join(hcgui.shell_escape(str(p)) for p in paths).encode() + CLOSE

    def test_a_pick_while_it_is_sent_pastes_nothing_into_the_terminal_shown_then(self):
        paste = self.paste_of(self.shot)
        for shown in ("mini/t8", "rig/t1", "t3"):  # the same machine, another one, this Mac
            with self.subTest(shown=shown):
                hcgui.write_atomic(self.win / "target", "mini/t7\n")
                self.during = lambda args, shown=shown: hcgui.write_atomic(self.win / "target", shown + "\n")
                self.type(paste)
                self.assertTrue(self.relay.busy)
                self.type(b"k")  # typed meanwhile: it waits
                self.assertEqual(self.got(), b"")
                self.sent()
                self.assertFalse(self.relay.busy)
                self.assertEqual(self.got(), b"k")  # no paste, neither the new one nor the original; the key goes on
                self.assertEqual(hcgui.take_ask(self.win), ["notice drop: not pasted: another terminal is shown now"])
        hcgui.write_atomic(self.win / "target", "mini/t7\n")
        self.fail = True
        self.during = lambda args: hcgui.write_atomic(self.win / "target", "mini/t8\n")
        self.type(paste)
        self.sent()
        self.assertEqual(self.got(), b"")
        self.assertEqual(hcgui.take_ask(self.win), ["notice drop: shot one.png not sent: at most 8 MB per put; "
                                                    "not pasted: another terminal is shown now"])
        hcgui.write_atomic(self.win / "target", "mini/t7\n")
        self.fail = False

        def away_and_back(args):
            hcgui.write_atomic(self.win / "target", "mini/t8\n")
            hcgui.write_atomic(self.win / "target", "mini/t7\n")

        self.during = away_and_back
        self.type(paste)
        self.sent()
        self.assertEqual(self.got(), OPEN + b"/remote/shot_one.png" + CLOSE)  # the terminal it was dropped on
        self.assertEqual(hcgui.take_ask(self.win), [])

    def test_a_slow_drop_says_so_and_then_that_it_was_sent(self):
        self.during = lambda args: self.go.wait(5)
        self.type(self.paste_of(self.shot, self.note))
        start = self.relay.drop.started
        self.assertEqual(self.relay.next_time(), start + hcgui.DROP_TELL)
        self.relay.on_time(start + hcgui.DROP_TELL / 2)
        self.assertFalse((self.win / "ask").exists())  # a quick drop says nothing
        self.relay.on_time(start + hcgui.DROP_TELL)
        self.assertEqual(hcgui.take_ask(self.win), ["info drop: sending 2 files to mini; keys wait"])
        self.assertEqual(self.relay.next_time(), start + hcgui.DROP_TELL + hcgui.NOTICE_SECONDS - 1)  # said again
        self.relay.on_time(start + hcgui.DROP_TELL + hcgui.NOTICE_SECONDS - 1)  # before the notice runs out
        self.assertEqual(hcgui.take_ask(self.win), ["info drop: sending 2 files to mini; keys wait"])
        self.type(b"x\r")
        self.assertEqual(self.got(), b"")
        self.go.set()
        self.sent()
        self.assertEqual(self.got(), OPEN + b"/remote/shot_one.png /remote/note.txt" + CLOSE + b"x\r")
        self.assertEqual(hcgui.take_ask(self.win), ["info drop: 2 files sent to mini"])
        self.assertIsNone(self.relay.next_time())

    def test_a_drop_without_an_answer_goes_on_as_it_came_at_drop_timeout(self):
        self.during = lambda args: self.go.wait(5)
        paste = self.paste_of(self.shot, self.note)
        self.type(paste)
        drop = self.relay.drop
        self.type(b"x\x1c\r")  # ctrl+\ and enter wait too
        self.assertEqual(self.relay.next_time(), drop.started + hcgui.DROP_TELL)
        drop.tell_at = drop.started + hcgui.DROP_TIMEOUT + 1  # (the "sending" notices are tested above)
        self.assertEqual(self.relay.next_time(), drop.started + hcgui.DROP_TIMEOUT)
        self.relay.on_time(drop.started + hcgui.DROP_TIMEOUT)
        self.assertFalse(self.relay.busy)
        self.assertEqual(self.got(), paste + b"x\x1c\r")  # the original, then the keys that waited, in order
        self.assertEqual(hcgui.take_ask(self.win), ["notice drop: 2 files not sent: no answer within 60 s"])
        self.type(b"y")
        self.assertEqual(self.got(), b"y")  # no longer held
        self.go.set()
        drop.thread.join(5)
        self.sent()  # the answer comes too late: nothing more is pasted
        self.assertEqual(self.got(), b"")
        self.assertEqual(self.puts, [str(self.shot)])  # the second file is never sent
        self.type(self.paste_of(self.note))  # the next drop is its own
        self.sent()
        self.assertEqual(self.got(), OPEN + b"/remote/note.txt" + CLOSE)

    def test_a_hidden_file_is_never_sent(self):
        folder = self.tmp / ".ssh"
        folder.mkdir()
        key = folder / "id_ed25519"
        key.write_text("k")
        paste = self.paste_of(key)
        self.type(paste + b"z")
        self.assertFalse(self.relay.busy)
        self.assertEqual(self.got(), paste + b"z")  # as it came, at once
        self.assertEqual(self.puts, [])
        self.assertEqual(hcgui.take_ask(self.win), ["notice drop: id_ed25519 not sent: in a hidden folder"])

    def test_the_smaller_copy_goes_when_the_relay_ends_during_the_send(self):
        temp = self.tmp / "T"
        temp.mkdir()
        patcher = mock.patch.object(tempfile, "tempdir", str(temp))
        patcher.start()
        self.addCleanup(patcher.stop)
        big = self.tmp / "big.png"
        big_file(big)
        made, making = [], threading.Event()

        def shrink(source, copy):  # sips, slow: the window is closed meanwhile
            self.threads.add(threading.current_thread())
            Path(copy).write_bytes(b"\xff\xd8\xff small")
            made.append(Path(copy))
            making.set()
            self.go.wait(5)
            return True

        self.relay.shrink = shrink
        child = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)  # view.sh: hang_up's SIGHUP ends it
        self.addCleanup(lambda: (child.kill(), child.wait()))
        self.relay.child = child.pid
        os.write(self.fds["in_w"], self.paste_of(big))

        def close_pane():
            making.wait(5)
            os.close(self.fds.pop("in_w"))  # end of file: the pane has gone

        closer = threading.Thread(target=close_pane, daemon=True)
        closer.start()
        self.assertEqual(self.relay.run(), 0)
        closer.join(5)
        self.assertTrue(made)
        self.assertFalse(made[0].exists())
        self.assertEqual(list(temp.iterdir()), [])  # the copy and its folders are gone
        self.assertEqual(child.wait(5), -signal.SIGHUP)


class RelayViewTests(unittest.TestCase):
    """The relay around the real view.sh (python3 hcgui.py view) in a pseudo terminal, with the stand-in hc of the
    view tests: picks and switches work as before, and closing the pane leaves nothing behind."""

    def test_pick_switch_and_close(self):
        import pty
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            win = tmp / "state"
            log = tmp / "log"
            log.write_text("")
            hc = tmp / "hc"
            hc.write_text(STUB_HC)
            hc.chmod(0o755)
            env = dict(os.environ, HCGUI_HC=str(hc), HCGUI_STATE=str(win), STUB_LOG=str(log),
                       PYTHONDONTWRITEBYTECODE="1")
            env.pop("HCGUI_WINDOW", None)
            pid, fd = pty.fork()
            if pid == 0:
                try:
                    os.execve(sys.executable, [sys.executable, str(ROOT / "hcgui.py"), "view"], env)
                finally:
                    os._exit(127)
            stop = threading.Event()

            def drain():  # never blocked in a read when the fd is closed: select first
                import select
                while not stop.is_set():
                    if select.select([fd], [], [], 0.05)[0]:
                        try:
                            if not os.read(fd, 65536):
                                return
                        except OSError:
                            return

            drainer = threading.Thread(target=drain, daemon=True)
            drainer.start()
            try:
                self.assertTrue(wait_for(lambda: (win / "view.loop").exists()))
                self.assertEqual(hcgui.proc_info(int(hcgui.read_text(win / "view.loop")))[0], pid)
                hcgui.show("a", win)
                self.assertTrue(wait_for(lambda: "start a" in log.read_text()))
                self.assertTrue(wait_for(lambda: hcgui.attach_pid(win) != 0))  # the attach is view.loop's child
                hcgui.show("b", win)
                self.assertTrue(wait_for(lambda: "end a" in log.read_text() and "start b" in log.read_text()))
                self.assertTrue(wait_for(lambda: hcgui.attach_pid(win) != 0))
                attach = hcgui.attach_pid(win)
                stop.set()
                drainer.join()
                os.close(fd)  # the pane is closed
                fd = -1
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and os.waitpid(pid, os.WNOHANG) == (0, 0):
                    time.sleep(0.02)
                self.assertTrue(wait_for(lambda: hcgui.proc_info(attach) in ((0, ""), None)))  # the attach ended
                self.assertTrue(wait_for(lambda: not (win / "view.loop").exists()))
                self.assertFalse((win / "view.pid").exists())
            finally:
                stop.set()
                try:
                    os.kill(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)
                except (OSError, ChildProcessError):
                    pass
                if fd >= 0:
                    os.close(fd)


class StartDropTests(TmuxWindowCase):
    """A drop through the whole window: tmux pastes into the view pane (as Ghostty's drop reaches it), the relay
    sends the file to the terminal's machine and pastes the path there; a file that cannot be sent goes on as it
    came, and the tab bar says why. The terminal is on the machine "rig" (the home machine here)."""

    HC = """#!/bin/sh
case "$1 $2" in
  "ls --json") echo '{"terminals": [{"address": "rig/t1", "agent": "zsh", "cwd": "/tmp/work", "state": "live",
                  "name": "one"}]}' ;;
  "machine ls") echo '{"machines": [{"name": "rig", "target": "me@rig", "id": "x", "host": "rig",
                  "version": "0.1.21", "state": "connected"}]}' ;;
  "get rig/t1") echo "{}" ;;
  "attach rig/t1") printf '\\033[?2004h'; stty raw -echo; : >"$DROP_LOG.ready"; exec cat >>"$DROP_LOG" ;;
  "put --json")
    printf '%s %s\\n' "$3" "$4" >>"$PUT_LOG"
    printf '{"bytes": 3, "path": "/remote/%s"}\\n' "$(basename "$4" | tr ' ' '_')" ;;
esac
exit 0
"""

    def extra_env(self, tmp):
        return {"HCGUI_FIRST": "rig", "DROP_LOG": str(tmp / "drop.log"), "PUT_LOG": str(tmp / "put.log")}

    def test_a_drop_lands_on_the_terminals_machine(self):
        drop_log, put_log = self.tmp / "drop.log", self.tmp / "put.log"
        self.assertTrue(wait_for(lambda: (self.tmp / "drop.log.ready").exists(), 15))
        time.sleep(0.3)  # the attach's bracketed paste mode reaches tmux through the relay
        view = hcgui.read_panes(self.win)["view"]
        tabs = hcgui.read_panes(self.win)["tabs"]
        shot = self.tmp / "shot one.png"
        shot.write_bytes(b"png")
        self.t("set-buffer", "-b", "drop", hcgui.shell_escape(str(shot)))
        self.t("paste-buffer", "-p", "-d", "-b", "drop", "-t", view)
        want = OPEN + b"/remote/shot_one.png" + CLOSE
        self.assertTrue(wait_for(lambda: drop_log.exists() and drop_log.read_bytes() == want, 10),
                        drop_log.read_bytes() if drop_log.exists() else None)
        self.assertEqual(put_log.read_text(), f"rig/t1 {shot}\n")
        movie = self.tmp / "movie.mov"
        big_file(movie)
        self.t("set-buffer", "-b", "drop", str(movie))
        self.t("paste-buffer", "-p", "-d", "-b", "drop", "-t", view)
        want += OPEN + str(movie).encode() + CLOSE  # as it came
        self.assertTrue(wait_for(lambda: drop_log.read_bytes() == want, 10), drop_log.read_bytes())
        notice = "drop: movie.mov not sent: over 8 MB"
        self.assertTrue(wait_for(lambda: notice in self.t("capture-pane", "-p", "-t", tabs), 10),
                        self.t("capture-pane", "-p", "-t", tabs))
        self.assertEqual(put_log.read_text(), f"rig/t1 {shot}\n")  # never put: over 8 MB and no image


class RightPaneTests(unittest.TestCase):
    """Owner, 26 Nov: herdr's small pane on the right, a shell the session can see. "Split right" in a
    tab's menu starts a child shell of that tab's terminal (label pane=right); it shows right of the view while its
    parent is shown, is no tab of its own, and its pane's right click offers Close (y ends it)."""

    setUp = TabBarLogicTests.setUp

    def group(self):
        terms = [hcgui.Term("mini/t1", "mini", "alpha", "claude-code", "idle", "/x"),
                 hcgui.Term("mini/t2", "mini", "", "zsh", "", "/x"),
                 hcgui.Term("mini/t3", "mini", "beta", "zsh", "", "/x")]
        infos = {"mini/t2": hcgui.Info(parent="mini/t1", pane="right"),
                 "mini/t3": hcgui.Info(parent="mini/t9", pane="right")}  # its parent is not listed: a tab
        return hcgui.Group("space:x", "x", "space", "mini", "", terms=terms), terms, infos

    def snapshot(self):
        group, terms, infos = self.group()
        hcgui.write_snapshot(group, self.win, everything=terms, infos=infos)
        return hcgui.read_snapshot(self.win)

    def test_parse_info_reads_the_pane_label(self):
        raw = json.dumps({"labels": {"pane": "right"}, "parent": "t1"})
        self.assertEqual(hcgui.parse_info(raw, "rig/t2"), hcgui.Info(parent="rig/t1", pane="right"))
        self.assertEqual(hcgui.parse_info(json.dumps({"labels": {"pane": "left"}}), "t2").pane, "")

    def test_the_shell_is_no_tab_and_its_parent_names_it(self):
        snap = self.snapshot()
        self.assertEqual([t["address"] for t in snap["tabs"]], ["mini/t1", "mini/t3"])
        self.assertEqual([t["address"] for t in snap["panes"]], ["mini/t2"])
        self.assertEqual(hcgui.right_of(snap, "mini/t1"), "mini/t2")
        self.assertEqual(hcgui.right_of(snap, "mini/t3"), "")
        self.assertEqual(hcgui.tab_of(snap, "mini/t2")["address"], "mini/t2")  # its menu finds it
        self.assertEqual(hcgui.tab_title(snap, "mini/t2"), hcgui.window_title("t2", "mini"))
        # Close of the parent lists the shell: it ends with it
        self.assertIn("mini/t2", [a for a, _, _ in hcgui.tab_ends(hcgui.tab_of(snap, "mini/t1"))])

    def test_menu_entries(self):
        labels = [e.label for e in hcgui.tab_menu_entries("space", right=True)]
        self.assertEqual(labels, ["New terminal", "Split right", "Rename", "Move to space", "Close"])
        segs = hcgui.tab_menu_segs("x", hcgui.tab_menu_entries("space", right=True), 40)  # short: first words
        self.assertEqual([g.text for g in segs if g.kind == "entry"][:2], ["new", "split"])

    def test_menus_of_a_tab_and_of_the_right_pane(self):
        snap = self.snapshot()
        self.bar.open_tab_menu(snap, "mini/t3")
        self.assertIn("right", [e.action for e in self.bar.menu.entries])
        self.bar.open_tab_menu(snap, "mini/t1")  # it has one already
        self.assertNotIn("right", [e.action for e in self.bar.menu.entries])
        conf = (Path(hcgui.__file__).parent / "hcgui.tmux.conf").read_text()
        # a right click in the right pane: its header asks Close (the file "ask" of the right pane's folder)
        self.assertIn(f"printf \"{hcgui.HEAD_ASK_LINE}\\n\" >> \"$HCGUI_WINDOW/{hcgui.RIGHT_DIR}/ask\"", conf)

    def test_new_right_shell_asks_hc_for_a_child(self):
        calls = []

        def runner(*args, timeout=0.0):
            calls.append(args)
            return json.dumps({"address": "t8"})

        with mock.patch.object(hcgui, "poke_engine"):
            self.assertEqual(hcgui.new_right_shell("t1", "/x", self.win, runner), "t8")
            self.assertEqual(hcgui.new_right_shell("rig/t4", "", self.win, runner), "rig/t8")
        self.assertEqual(calls[0], ("run", "--bg", "--json", "--parent", "t1", "--no-notify", "--rm",
                                    "--label", "pane=right", "--cwd", "/x"))
        self.assertEqual(calls[1], ("run", "--bg", "--json", "--parent", "t4", "--no-notify", "--rm",
                                    "--label", "pane=right", "--on", "rig"))

    def test_view_pane_command(self):
        cmd = hcgui.view_pane_command(Path("/w/right"), Path("/w"), Path("/app"),
                                      [("HCGUI_HC", "/b/hc"), ("TERM", "xterm-hcgui"), ("HCGUI_WINDOW", "/x")])
        self.assertEqual(cmd, "exec env HCGUI_WINDOW=/w HCGUI_VIEW_DIR=/w/right HCGUI_HC=/b/hc python3 /app/hcgui.py view")
        self.assertTrue(hcgui.view_pane_command(Path("/w/right"), Path("/w"), Path("/app"), [], "head").endswith(
            "HCGUI_VIEW_DIR=/w/right python3 /app/hcgui.py head"))

    def sync(self, snap, shown, pane="", zoomed=False, head="", width=""):
        calls = []

        def tmux(*args, input=None):
            calls.append(args)
            return width if args[:2] == ("display", "-p") else None

        look = hcgui.WindowLook(zoomed, 100, 40, 70, 38)
        with mock.patch.object(hcgui, "tmux_enabled", return_value=True), \
                mock.patch.object(hcgui, "pane_id", return_value="%1"), \
                mock.patch.object(hcgui, "window_look", return_value=look), \
                mock.patch.object(hcgui, "right_panes", return_value=(pane, head)), \
                mock.patch.object(hcgui, "right_tint", return_value="themedarkgrey"), \
                mock.patch.object(hcgui, "open_right_pane", return_value="%7") as opened, \
                mock.patch.object(hcgui, "open_head_pane", return_value="%8") as headed, \
                mock.patch.object(hcgui, "tmux", tmux), mock.patch.object(hcgui, "end_current_attach"):
            self.bar.sync_right(snap, shown, 1000.0)
        self.opened_args, self.headed = opened.call_args, headed.called
        return calls, opened.called

    def test_sync_opens_switches_and_closes_the_pane(self):
        snap = self.snapshot()
        self.bar.right_focus, self.bar.right_since = "mini/t2", time.monotonic()
        calls, opened = self.sync(snap, "mini/t1")
        self.assertTrue(opened)
        self.assertTrue(self.headed)  # its header with it
        self.assertEqual(self.opened_args[0][3:], ("themedarkgrey", 0, 70))  # no width dragged yet: RIGHT_SHARE
        self.assertEqual(hcgui.current_target(self.win / hcgui.RIGHT_DIR), "mini/t2")
        self.assertIn(("select-pane", "-t", "%7"), calls)  # just started: it takes the keyboard
        self.assertEqual(self.bar.right_focus, "")
        calls, opened = self.sync(snap, "mini/t1", pane="%7", head="%8")  # nothing changed: no tmux call
        self.assertEqual((calls, opened), ([], False))
        # a tab without one: the pane and its header go; the pane's width is kept for the next one
        calls, opened = self.sync(snap, "mini/t3", pane="%7", head="%8", width="52\n")
        self.assertEqual(calls, [("kill-pane", "-t", "%8"), ("display", "-p", "-t", "%7", "#{pane_width}"),
                                 ("kill-pane", "-t", "%7")])
        self.assertEqual(self.bar.right_width, 52)
        calls, opened = self.sync(snap, "mini/t1")  # back: made again at that width
        self.assertEqual(self.opened_args[0][3:], ("themedarkgrey", 52, 70))
        self.bar.right_look = 0.0
        calls, opened = self.sync(snap, "mini/t1", pane="%7", head="")  # the header gone: made again alone
        self.assertEqual((opened, self.headed), (False, True))
        self.bar.right_look = 0.0
        calls, opened = self.sync(snap, "mini/t1", pane="", zoomed=True)  # zoomed: nothing until it is not
        self.assertEqual((calls, opened), ([], False))
        calls, opened = self.sync(None, "mini/t3", pane="%7")  # no snapshot: the pane stays
        self.assertEqual(calls, [])

    def test_a_header_without_its_pane_goes(self):
        snap = self.snapshot()
        calls, opened = self.sync(snap, "mini/t3", pane="", head="%8")
        self.assertEqual(calls, [("kill-pane", "-t", "%8")])
        self.assertFalse(opened)

    def test_open_right_pane_width(self):
        """A dragged width is kept while the view keeps RIGHT_ROOM columns, else RIGHT_SHARE; both panes get their
        role and the background."""
        for width, room, size in ((52, 100, "52"), (90, 100, hcgui.RIGHT_SHARE), (0, 100, hcgui.RIGHT_SHARE)):
            calls = []

            def tmux(*args, input=None):
                calls.append(args)
                return "%7\n" if args[0] == "split-window" else ""

            with mock.patch.object(hcgui, "tmux", tmux), mock.patch.object(hcgui, "pane_id", return_value="%1"):
                self.assertEqual(hcgui.open_right_pane(self.win, Path("/app"), [], "colour235", width, room), "%7")
            self.assertEqual(calls[0][:6], ("split-window", "-h", "-d", "-l", size, "-t"))
            self.assertEqual(calls[1], ("set", "-p", "-t", "%7", "@hcgui_role", "right", ";", "set", "-p", "-t", "%7",
                                        "window-style", "bg=colour235", ";", "set", "-p", "-t", "%7",
                                        "window-active-style", "bg=colour235"))
        calls = []

        def tmux(*args, input=None):
            calls.append(args)
            return "%8\n" if args[0] == "split-window" else ""

        with mock.patch.object(hcgui, "tmux", tmux):
            self.assertEqual(hcgui.open_head_pane("%7", self.win, Path("/app"), [], "themedarkgrey"), "%8")
        self.assertEqual(calls[0][:8], ("split-window", "-v", "-b", "-d", "-l", str(hcgui.HEAD_ROWS), "-t", "%7"))
        self.assertTrue(calls[0][-1].endswith("/app/hcgui.py head"))
        self.assertEqual(calls[1][4:6], ("@hcgui_role", hcgui.HEAD_ROLE))

    def test_right_tint_follows_what_tmux_knows(self):
        with mock.patch.object(hcgui, "tmux", return_value="") as tm:
            self.assertEqual(hcgui.right_tint(), hcgui.RIGHT_TINT)
        tm.assert_called_once_with("set", "-g", "light-theme-dark-grey", hcgui.RIGHT_TINT_LIGHT)
        with mock.patch.object(hcgui, "tmux", return_value=None):  # a tmux without theme colours
            self.assertEqual(hcgui.right_tint(), hcgui.RIGHT_TINT_OLD)

    def test_right_panes_reads_both_roles(self):
        out = "%1 view\n%7 right\n%8 rhead\n%2 tabs\n"
        with mock.patch.object(hcgui, "tmux", return_value=out), mock.patch.object(hcgui, "pane_id", return_value="%1"):
            self.assertEqual(hcgui.right_panes(self.win), ("%7", "%8"))
            self.assertEqual(hcgui.right_pane(self.win), "%7")
        with mock.patch.object(hcgui, "tmux", return_value=None), \
                mock.patch.object(hcgui, "pane_id", return_value="%1"):
            self.assertEqual(hcgui.right_panes(self.win), ("", ""))

    def test_header_text(self):
        snap = self.snapshot()
        self.assertEqual(hcgui.right_head_text(snap, "mini/t2", "/Users/me"), "t2 · /x · mini")  # another machine
        tab = hcgui.tab_of(snap, "mini/t2")
        local = {"tabs": [], "panes": [dict(tab, address="t2", cwd="/Users/me/dev/hcgui", label="zsh")]}
        self.assertEqual(hcgui.right_head_text(local, "t2", "/Users/me"), "zsh · ~/dev/hcgui")
        local["panes"][0]["cwd"] = "/Users/me"
        self.assertEqual(hcgui.right_head_text(local, "t2", "/Users/me"), "zsh · ~")
        local["panes"][0]["cwd"] = "/Users/meow"  # only the home folder itself becomes ~
        self.assertEqual(hcgui.right_head_text(local, "t2", "/Users/me"), "zsh · /Users/meow")
        local["panes"][0]["label"] = "a\x1b[31mb"  # nothing unprintable reaches the screen
        self.assertNotIn("\x1b", hcgui.right_head_text(local, "t2", "/Users/me"))
        self.assertEqual(hcgui.right_head_text(local, "t9", "/Users/me"), "")
        self.assertEqual(hcgui.right_head_text(None, "", "/Users/me"), "")

    def test_head_line(self):
        self.assertEqual(hcgui.head_line("zsh · ~/dev", 30), (" zsh · ~/dev", 27))
        line, x = hcgui.head_line("zsh · ~/dev/a-very-long-folder-name", 20)
        self.assertEqual((line, x), (" zsh · ~/dev/a-…", 17))
        self.assertLess(hcgui.text_width(line), x)  # never under the ×
        self.assertEqual(hcgui.head_line("zsh", 4), ("", -1))

    def test_write_head_only_on_a_change(self):
        snap = self.snapshot()
        path = self.win / hcgui.RIGHT_DIR / hcgui.HEAD_FILE
        self.bar.write_head(snap, "mini/t2")
        self.assertEqual(path.read_text(), "t2 · /x · mini\n")
        path.write_text("other\n")
        self.bar.write_head(snap, "mini/t2")  # the same text: not written again
        self.assertEqual(path.read_text(), "other\n")
        self.bar.write_head(snap, "")
        self.assertEqual(path.read_text(), "\n")

    def head(self, snap, height=2, width=40):
        """A RightHead on a fake screen, its shell mini/t2 shown below."""
        head = hcgui.RightHead.__new__(hcgui.RightHead)
        head.s = mock.Mock()
        head.s.size.return_value = (height, width)
        head.folder, head.win = self.win / hcgui.RIGHT_DIR, self.win
        head.text, head.close_x, head.prompt, head.asked_at, head.cut = "t2", width - 3, None, 0.0, False
        hcgui.show("mini/t2", head.folder)
        hcgui.write_snapshot(self.group()[0], self.win, everything=self.group()[1], infos=self.group()[2])
        return head

    def test_header_presses(self):
        snap = self.snapshot()
        head = self.head(snap)
        with mock.patch.object(hcgui, "send_keys_to_view") as keys, \
                mock.patch.object(hcgui, "right_pane", return_value="%7"), \
                mock.patch.object(hcgui, "own_pane", return_value="%8"), \
                mock.patch.object(hcgui, "tmux") as tm, mock.patch.object(hcgui, "size_pane") as size:
            head.press(5, 1, 1)  # beside the ×: the shell takes the keyboard
            keys.assert_called_once_with([], self.win, "%7")
            head.press(38, 1, 1)  # one column beside the × counts too: Close's question, here
            self.assertEqual((head.prompt.kind, head.prompt.data), ("close", ("mini/t2",)))
            tm.assert_called_with("select-pane", "-t", "%8")  # the header takes the keyboard for the answer
            size.assert_called_with("%8", rows=2)  # it fits in two rows: no taller
            head.press(5, 1, 1)  # a press cancels; the shell gets the keyboard back
            self.assertIsNone(head.prompt)
            self.assertEqual(keys.call_args[0], ([], self.win, "%7"))
            head.press(5, 0, 3)  # a right press asks too
            self.assertIsNotNone(head.prompt)

    def test_header_question_grows_and_waits(self):
        snap = self.snapshot()
        head = self.head(snap, width=20)
        with mock.patch.object(hcgui, "own_pane", return_value="%8"), mock.patch.object(hcgui, "tmux"), \
                mock.patch.object(hcgui, "size_pane") as size:
            head.ask_close()
        rows = len(head.question_lines(20))
        self.assertGreater(rows, 2)
        size.assert_called_with("%8", rows=min(rows, hcgui.HEAD_MAX_ROWS))
        self.assertEqual(head.question_lines(20)[-1], " y closes · any other key cancels")
        head.draw()  # still 2 rows high (tmux not resized here): cut, so y waits
        self.assertTrue(head.cut)
        with mock.patch.object(hcgui, "end_terminal") as end:
            head.asked_at = 0.0
            head.answer(ord("y"))
        end.assert_not_called()

    def test_header_y_closes_after_the_hold(self):
        snap = self.snapshot()
        head = self.head(snap, height=8, width=60)
        with mock.patch.object(hcgui, "own_pane", return_value=""), mock.patch.object(hcgui, "tmux"):
            head.ask_close()
            head.draw()
            with mock.patch.object(hcgui, "end_terminal") as end, mock.patch.object(hcgui, "poke_engine"), \
                    mock.patch.object(hcgui, "change_names") as names, \
                    mock.patch.object(hcgui, "focus_view") as focus:
                head.answer(ord("y"))  # at once: not taken (DELETE_HOLD)
                end.assert_not_called()
                head.asked_at -= hcgui.DELETE_HOLD
                head.answer(ord("Y"))
            end.assert_called_once_with("mini/t2")
            names.assert_called_once_with({"term:mini/t2": ""})
            focus.assert_called_once_with(self.win)
            self.assertIsNone(head.prompt)

    def test_a_right_click_in_the_shell_reaches_the_header(self):
        snap = self.snapshot()
        head = self.head(snap)
        hcgui.write_atomic(head.folder / "ask", hcgui.HEAD_ASK_LINE + "\n")
        head.s.scr.getch.side_effect = [-1, KeyboardInterrupt]
        with mock.patch.object(hcgui, "setup_curses"), mock.patch.object(hcgui, "own_pane", return_value=""), \
                mock.patch.object(hcgui, "tmux"), self.assertRaises(KeyboardInterrupt):
            head.run()
        self.assertEqual(head.prompt.kind, "close")
        self.assertFalse((head.folder / "ask").exists())

    def test_main_runs_the_header(self):
        with mock.patch.object(hcgui, "run_head", return_value=0) as run:
            self.assertEqual(hcgui.main(["hcgui.py", "head"]), 0)
        run.assert_called_once_with()

if __name__ == "__main__":
    unittest.main()
