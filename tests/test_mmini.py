"""Offline tests for mmini.py and view.sh: no real hc, no Ghostty, no curses screen."""

import atexit
import itertools
import json
import os
import re
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
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
# Only the settings the fixtures are written for: none of the shell's MMINI_* settings reach mmini or view.sh. The
# home machine is "mmini"; the account marks and the shared account are fixtures too.
for _name in [k for k in os.environ if k.startswith("MMINI_")]:
    del os.environ[_name]
os.environ["MMINI_GHOSTTY"] = "0"
os.environ["MMINI_FIRST"] = "mmini"
os.environ["MMINI_MARKS"] = "claude=¹,main=¹,work=²"
os.environ["MMINI_SHARED_USER"] = "guest"
# mmini's default folders come from these at import: a test that forgets to pass its own folder writes into a
# throwaway one, never into ~/.local/state/mmini.
_DEFAULT_STATE = tempfile.mkdtemp(prefix="mmini-tests-")
atexit.register(shutil.rmtree, _DEFAULT_STATE, True)
os.environ["MMINI_STATE"] = _DEFAULT_STATE
os.environ.pop("MMINI_WINDOW", None)

import mmini  # noqa: E402

mmini.HC = "/nonexistent/hc-must-never-run-in-tests"  # a test that forgets its stand-in fails, it never reaches hc
mmini.setup_locale()


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
    term("mmini/t5", "/Users/x/dev/atlas", "claude-code", "atlas", "idle"),
    term("mmini/t6", "/Users/x/dev/atlas", "zsh", "zz"),
    term("mmini/t7", "/Users/x", "zsh", None),
    term("mmini/t8", "/Users/x/dev/appshop", "claude-code", "appshop", "working"),
    term("rig/t1", "/home/rig", "claude-code", "r1", "blocked"),
    term("t1", "/Users/me", "zsh", None),
)


def top_rows(spaces, rigs):
    """Lines of the sidebar's top part: "spaces", the spaces, "+ new space", a blank, "rigs", the rigs, "+ add rig"."""
    return len(spaces) + len(rigs) + 5


def fold_line(mode, width=30):
    """The sidebar's last line as drawn: "‹ fold" (or "‹ hide"), and in the open sidebar a dim "?" at its end."""
    label = mmini.fold_label(mode, width - 1)
    x = mmini.help_column(label, width)
    return mmini.glyph(label).ljust(x) + "?" if mode == "open" and x >= 0 else mmini.glyph(label)


def mouse_at(x, y, bstate):
    """What ncurses reports for one mouse event (read by read_mouse_event and read_mouse)."""
    return mock.patch.object(mmini.curses, "getmouse", return_value=(0, x, y, 0, bstate))


def pressed(x, y, button=1):
    """A press of the left (1) or right (3) button at column x, line y."""
    return mouse_at(x, y, mmini.curses.BUTTON1_PRESSED if button == 1 else mmini.curses.BUTTON3_PRESSED)


def seen_done(state, terms):
    """The user has looked at every "done" agent of `terms` (seen.json), so no "needs you" section is drawn for
    them: the tests written before that section keep their screens."""
    done = {t["address"]: t.get("turn", 0) for t in terms if t.get("status") == "done"}
    if done:
        mmini.write_seen(done, state)


def many_agents(n=6):
    """Two spaces, one of them with n agents (like the mini's real "dev" space)."""
    return mmini.build_groups(mmini.parse(ls(
        *[term(f"t{i}", "/Users/x/dev", "claude-code", f"a{i}", "idle") for i in range(n)],
        term("t90", "/Users/x/dev/other", "zsh", "sh"))), "mmini")


class ParseTests(unittest.TestCase):
    def test_parse_fields_and_missing(self):
        raw = ls({"address": "t5", "agent": "claude-code", "cwd": "/a/b", "name": None, "status": "done"},
                 {"address": "rig/t2"}, {"name": "no-address"})
        terms = mmini.parse(raw)
        self.assertEqual([t.address for t in terms], ["t5", "rig/t2"])
        self.assertEqual(terms[0].machine, mmini.LOCAL)
        self.assertEqual(terms[1].machine, "rig")
        self.assertEqual(terms[0].label, "t5")
        self.assertEqual(terms[1].name, "")

    def test_label_prefers_name(self):
        self.assertEqual(mmini.parse(ls(term("mmini/t9", name="atlas")))[0].label, "atlas")
        self.assertEqual(mmini.parse(ls(term("mmini/t9")))[0].label, "t9")

    def test_machine_of(self):
        self.assertEqual(mmini.machine_of("t1"), mmini.LOCAL)
        self.assertEqual(mmini.machine_of("mmini/t5"), "mmini")
        self.assertEqual(mmini.machine_of("a/b/t5"), "a/b")

    def test_junk_raises_value_error_only(self):
        for raw in ("not json", "[]", "null", "3", '{"terminals": null}', '{"terminals": {"a": 1}}', "{}"):
            with self.assertRaises(ValueError, msg=raw):
                mmini.parse(raw)

    def test_junk_entries_are_skipped(self):
        raw = json.dumps({"terminals": [1, None, "x", [], {"address": "t3", "name": 7, "cwd": None}]})
        terms = mmini.parse(raw)
        self.assertEqual([(t.address, t.name, t.cwd) for t in terms], [("t3", "7", "")])

    def test_parse_info(self):
        raw = json.dumps({"labels": {"space": " atlas "}, "parent": "t19"})
        self.assertEqual(mmini.parse_info(raw, "mmini/t20"), mmini.Info("atlas", "mmini/t19"))
        self.assertEqual(mmini.parse_info(raw, "t20"), mmini.Info("atlas", "t19"))
        self.assertEqual(mmini.parse_info('{"labels": {}, "parent": null}', "t1"), mmini.Info())
        self.assertEqual(mmini.parse_info('{"labels": null, "parent": 5}', "t1"), mmini.Info())
        self.assertEqual(mmini.parse_info('{"labels": {"space": 3}}', "t1"), mmini.Info())
        self.assertEqual(mmini.parse_info('{"parent": "rig/t2"}', "rig/t3"), mmini.Info("", "rig/t2"))
        for raw in ("junk", "[]", "null"):
            with self.assertRaises(ValueError):
                mmini.parse_info(raw, "t1")

    def test_parse_info_ends_with_parent(self):
        self.assertTrue(mmini.parse_info('{"parent": "t1", "die_with_parent": true}', "t2").dies)
        self.assertFalse(mmini.parse_info('{"parent": "t1", "die_with_parent": false}', "t2").dies)
        self.assertTrue(mmini.parse_info('{"parent": "t1"}', "t2").dies)  # unknown: listed as ending, to be safe

    def test_parse_machines(self):
        raw = json.dumps({"machines": [{"name": "vps", "target": "me@vps", "state": "connected"}, {"name": ""},
                                       {"target": "x"}, 3, {"name": 7}]})
        self.assertEqual(mmini.parse_machines(raw), [mmini.Machine("vps", "me@vps", False)])
        raw = json.dumps({"machines": [{"name": "rig", "target": "guest@mini", "via": False},
                                       {"name": "box", "target": "fly ssh console -C", "via": True},
                                       {"name": "odd", "target": 7}]})
        self.assertEqual(mmini.parse_machines(raw), [mmini.Machine("rig", "guest@mini"),
                                                     mmini.Machine("box", "fly ssh console -C", True),
                                                     mmini.Machine("odd", "")])
        self.assertEqual(mmini.parse_machines('{"machines": []}'), [])
        for raw in ("junk", "[]", "{}", '{"machines": null}'):
            with self.assertRaises(ValueError):
                mmini.parse_machines(raw)


class SpaceTests(unittest.TestCase):
    def test_cwd_space(self):
        self.assertEqual(mmini.cwd_space("/Users/x/dev/atlas"), "atlas")
        self.assertEqual(mmini.cwd_space("/Users/x/dev/atlas/src/deep/er"), "atlas")
        self.assertEqual(mmini.cwd_space("/home/u/dev/repo/x"), "repo")
        self.assertEqual(mmini.cwd_space("/Users/x/dev"), "dev")
        self.assertEqual(mmini.cwd_space("/Users/x/dev/"), "dev")
        self.assertEqual(mmini.cwd_space("/Users/x"), "home")
        self.assertEqual(mmini.cwd_space("/Users/x/"), "home")
        self.assertEqual(mmini.cwd_space("/home/rig"), "home")
        self.assertEqual(mmini.cwd_space(""), "home")
        self.assertEqual(mmini.cwd_space("/"), "home")
        self.assertEqual(mmini.cwd_space("/Users"), "Users")
        self.assertEqual(mmini.cwd_space("/Users/x/Documents/notes"), "notes")
        self.assertEqual(mmini.cwd_space("/opt/dev/thing"), "thing")
        self.assertEqual(mmini.cwd_space("/private/tmp/work"), "work")

    def test_own_label_wins(self):
        cwds = {"t1": "/Users/x/dev/a"}
        self.assertEqual(mmini.resolve_space("t1", cwds, {"t1": mmini.Info("mine", "")}), "mine")
        self.assertEqual(mmini.resolve_space("t1", cwds, {}), "a")
        self.assertEqual(mmini.resolve_space("t1", cwds, {"t1": mmini.Info()}), "a")

    def test_parent_chain(self):
        cwds = {"t1": "/Users/x/dev/a", "t2": "/Users/x/dev/b", "t3": "/Users/x/dev/c"}
        infos = {"t1": mmini.Info("top", ""), "t2": mmini.Info("", "t1"), "t3": mmini.Info("", "t2")}
        self.assertEqual(mmini.resolve_space("t3", cwds, infos), "top")  # label two levels up
        infos["t1"] = mmini.Info("", "")
        self.assertEqual(mmini.resolve_space("t3", cwds, infos), "a")  # no label anywhere: the top's folder
        infos["t2"] = mmini.Info("mid", "t1")
        self.assertEqual(mmini.resolve_space("t3", cwds, infos), "mid")  # the nearest label wins
        infos["t3"] = mmini.Info("own", "t2")
        self.assertEqual(mmini.resolve_space("t3", cwds, infos), "own")

    def test_missing_or_ended_parent_stops_the_chain(self):
        cwds = {"t2": "/Users/x/dev/b", "t3": "/Users/x/dev/c"}  # t1 is not live any more
        infos = {"t1": mmini.Info("gone", ""), "t2": mmini.Info("", "t1"), "t3": mmini.Info("", "t2")}
        self.assertEqual(mmini.resolve_space("t3", cwds, infos), "b")
        self.assertEqual(mmini.resolve_space("t2", cwds, infos), "b")
        self.assertEqual(mmini.resolve_space("t3", cwds, {"t3": mmini.Info("", "t99")}), "c")
        self.assertEqual(mmini.resolve_space("t3", cwds, {"t3": mmini.Info("", "t2")}), "b")  # parent without info

    def test_loops_end(self):
        cwds = {"t1": "/Users/x/dev/a", "t2": "/Users/x/dev/b"}
        infos = {"t1": mmini.Info("", "t2"), "t2": mmini.Info("", "t1")}
        self.assertEqual(mmini.resolve_space("t1", cwds, infos), "a")
        self.assertEqual(mmini.resolve_space("t2", cwds, infos), "b")
        self.assertEqual(mmini.resolve_space("t1", cwds, {"t1": mmini.Info("", "t1")}), "a")

    def test_unknown_terminal(self):
        self.assertEqual(mmini.resolve_space("t9", {}, {}), "home")

    def test_space_cwd(self):
        def t(address, cwd):
            return mmini.Term(address, "mmini", "", "zsh", "", cwd)
        self.assertEqual(mmini.space_cwd("atlas", [t("t1", "/Users/x/dev/atlas/src/a")]), "/Users/x/dev/atlas")
        self.assertEqual(mmini.space_cwd("home", [t("t1", "/Users/x")]), "/Users/x")
        self.assertEqual(mmini.space_cwd("dev", [t("t1", "/Users/x/dev")]), "/Users/x/dev")
        self.assertEqual(mmini.space_cwd("notes", [t("t1", "/Users/x/Documents/notes")]), "/Users/x/Documents/notes")
        # a labelled space whose terminals sit elsewhere: the first terminal's folder
        self.assertEqual(mmini.space_cwd("lab", [t("t1", ""), t("t2", "/Users/x/dev/other/sub")]),
                         "/Users/x/dev/other/sub")
        self.assertEqual(mmini.space_cwd("lab", [t("t1", "/tmp/a"), t("t2", "/Users/x/dev/lab/z")]),
                         "/Users/x/dev/lab")
        self.assertEqual(mmini.space_cwd("lab", []), "")


class GroupTests(unittest.TestCase):
    def test_home_machine(self):
        terms = mmini.parse(SAMPLE)
        self.assertEqual(mmini.home_machine(terms, "mmini"), "mmini")
        self.assertEqual(mmini.home_machine(terms, "nothere"), mmini.LOCAL)
        self.assertEqual(mmini.home_machine([], "mmini"), mmini.LOCAL)

    def test_groups_remote_home(self):
        spaces, rigs = mmini.build_groups(mmini.parse(SAMPLE), "mmini")
        self.assertEqual([g.name for g in spaces], ["home", "appshop", "atlas"])
        # servers: the home machine first (all its terminals, the spaces' ones), then the others, this Mac last
        self.assertEqual([g.name for g in rigs], ["mmini", "rig", mmini.LOCAL])
        self.assertEqual([g.home for g in rigs], [True, False, False])
        self.assertEqual([t.address for t in rigs[0].terms], ["mmini/t8", "mmini/t5", "mmini/t7", "mmini/t6"])
        self.assertEqual(spaces[2].key, "space:atlas")
        self.assertEqual(spaces[2].machine, "mmini")
        self.assertEqual(spaces[2].cwd, "/Users/x/dev/atlas")
        self.assertEqual(rigs[1].kind, "rig")
        self.assertEqual(rigs[1].cwd, "")
        self.assertEqual(rigs[2].key, "rig:" + mmini.LOCAL)

    def test_tabs_sorted_by_label(self):
        spaces, _ = mmini.build_groups(mmini.parse(SAMPLE), "mmini")
        self.assertEqual([t.label for t in spaces[2].terms], ["atlas", "zz"])
        raw = ls(term("t13"), term("t9"), term("t100"), term("t2", name="beta"), term("t3", name="Alpha"))
        spaces, _ = mmini.build_groups(mmini.parse(raw), "mmini")
        self.assertEqual([t.label for t in spaces[0].terms], ["Alpha", "beta", "t9", "t13", "t100"])

    def test_natural_key_takes_any_text(self):
        self.assertEqual(mmini.natural("t13"), [(1, 0, "t"), (0, 13, "")])
        self.assertLess(mmini.natural("t9"), mmini.natural("t13"))
        for odd in ("²", "1²", "v1²", "①", "٣", "x٣9", "½", ""):  # str.isdigit() is True for some, int() refuses
            self.assertIsInstance(mmini.natural(odd), list, odd)
        self.assertEqual(mmini.natural("v1²"), [(1, 0, "v"), (0, 1, ""), (1, 0, "²")])
        raw = ls(term("mmini/t5"), term("rig/t1", name="v1²"), term("rig/t2", name="①"), term("rig/t3", name="v1"))
        _, rigs = mmini.build_groups(mmini.parse(raw), "mmini")  # a server may report any name: no crash, an order
        self.assertEqual([t.label for t in rigs[1].terms], ["v1", "v1²", "①"])

    def test_groups_all_local(self):
        raw = ls(term("t5", "/Users/x/dev/b"), term("t6", "/Users/x/dev/a"))
        spaces, rigs = mmini.build_groups(mmini.parse(raw), "mmini")
        self.assertEqual([g.name for g in spaces], ["a", "b"])
        self.assertEqual(spaces[0].machine, mmini.LOCAL)
        self.assertEqual([(g.key, g.home, len(g.terms)) for g in rigs], [("rig:" + mmini.LOCAL, True, 2)])

    def test_labels_and_parents_make_the_spaces(self):
        raw = ls(term("mmini/t1", "/Users/x/dev", "claude-code", "atlas", "idle"),
                 term("mmini/t2", "/Users/x/dev", "claude-code", "tracker", "idle"),
                 term("mmini/t3", "/Users/x/dev", "zsh", "helper"),        # started by t1
                 term("mmini/t4", "/Users/x/dev/atlas-app/src", "zsh"),    # repo folder below dev
                 term("mmini/t5", "/tmp/elsewhere", "zsh", "moved"),       # labelled into "atlas"
                 term("rig/t1", "/home/rig/dev/x", "claude-code", "r1"))
        infos = {"mmini/t1": mmini.Info("atlas", ""), "mmini/t3": mmini.Info("", "mmini/t1"),
                 "mmini/t5": mmini.Info("atlas", ""), "rig/t1": mmini.Info("ignored", "")}
        spaces, rigs = mmini.build_groups(mmini.parse(raw), "mmini", infos)
        self.assertEqual([g.name for g in spaces], ["atlas", "atlas-app", "dev"])
        self.assertEqual([t.label for t in spaces[0].terms], ["atlas", "helper", "moved"])
        self.assertEqual([t.label for t in spaces[2].terms], ["tracker"])
        self.assertEqual(spaces[1].cwd, "/Users/x/dev/atlas-app")
        self.assertEqual(spaces[0].cwd, "/Users/x/dev")  # no terminal is in a folder called atlas: the first one's
        self.assertEqual([g.name for g in rigs], ["mmini", "rig"])  # one group per machine, labels play no part

    def test_empty(self):
        self.assertEqual(mmini.build_groups([], "mmini"), ([], []))

    def test_summary_status(self):
        def terms(*statuses):
            return [mmini.Term("t", mmini.LOCAL, "", "claude-code", s, "") for s in statuses]
        self.assertEqual(mmini.summary_status(terms("idle", "working")), "working")
        self.assertEqual(mmini.summary_status(terms("done", "idle")), "done")
        self.assertEqual(mmini.summary_status(terms("working", "blocked")), "blocked")
        self.assertEqual(mmini.summary_status(terms("idle", "error")), "error")
        self.assertEqual(mmini.summary_status(terms("")), "")
        self.assertEqual(mmini.summary_status([]), "")


class AgentTests(unittest.TestCase):
    def test_is_agent(self):
        def t(agent, status=""):
            return mmini.Term("t1", mmini.LOCAL, "", agent, status, "")
        for plain in ("zsh", "bash", "sh", "fish", "login"):
            self.assertFalse(t(plain).is_agent)
        self.assertTrue(t("claude-code").is_agent)
        self.assertTrue(t("zsh", "working").is_agent)
        self.assertTrue(t("python3").is_agent)

    def test_selectable_items_order(self):
        spaces, rigs = mmini.build_groups(mmini.parse(SAMPLE), "mmini")
        items = mmini.selectable_items(spaces, rigs)
        # as drawn: the spaces, "+ new space", the servers, "+ add server", then the agents (the home machine's
        # agents once, under their spaces)
        self.assertEqual([i.kind for i in items], ["group"] * 3 + ["new_space"] + ["group"] * 3 + ["add_rig"]
                         + ["agent"] * 3)
        self.assertEqual([i.address for i in items[8:]], ["mmini/t8", "mmini/t5", "rig/t1"])
        plan = mmini.plan_sidebar(spaces, rigs, 40)
        self.assertEqual([items[r.item] for _, r in plan if r.item >= 0], items)  # the drawn order is the cursor's
        # the servers section hidden: no server rows, no "+ add server", no agents of servers
        hidden = mmini.selectable_items(spaces, rigs, servers=False)
        self.assertEqual([i.kind for i in hidden], ["group"] * 3 + ["new_space"] + ["agent"] * 2)
        self.assertEqual([i.address for i in hidden[4:]], ["mmini/t8", "mmini/t5"])
        plan = mmini.plan_sidebar(spaces, rigs, 40, servers=False)
        self.assertEqual([hidden[r.item] for _, r in plan if r.item >= 0], hidden)
        self.assertNotIn("servers", [r.text for _, r in plan])


class FallbackGroupTests(unittest.TestCase):
    """Which group a start opens on when there is no usable saved group."""

    def test_first_space_with_an_agent_not_the_empty_home(self):
        spaces, rigs = mmini.build_groups(mmini.parse(SAMPLE), "mmini")
        self.assertEqual([g.name for g in spaces], ["home", "appshop", "atlas"])  # home holds a shell only
        self.assertEqual(mmini.fallback_group(spaces, rigs), "space:appshop")

    def test_the_shown_terminals_group_wins(self):
        spaces, rigs = mmini.build_groups(mmini.parse(SAMPLE), "mmini")
        self.assertEqual(mmini.fallback_group(spaces, rigs, "space:home"), "space:home")
        self.assertEqual(mmini.fallback_group(spaces, rigs, "rig:rig"), "rig:rig")
        self.assertEqual(mmini.fallback_group(spaces, rigs, "space:gone"), "space:appshop")  # not listed: ignored

    def test_no_agent_anywhere_first_space_then_first_rig(self):
        spaces, rigs = mmini.build_groups(mmini.parse(ls(term("mmini/t1", "/Users/x"), term("mmini/t2"),
                                                         term("rig/t1", agent="claude-code"))), "mmini")
        self.assertEqual(mmini.fallback_group(spaces, rigs), "space:home")  # an agent on a rig does not count
        _, rigs = mmini.build_groups(mmini.parse(ls(term("rig/t1"), term("box/t2"))), "mmini")
        self.assertEqual(mmini.fallback_group([], rigs), "rig:box")
        self.assertEqual(mmini.fallback_group([], []), "")

    def test_a_shell_with_a_status_counts_as_an_agent(self):
        spaces, rigs = mmini.build_groups(mmini.parse(ls(
            term("t1", "/Users/x"), term("t2", "/Users/x/dev/a"), term("t3", "/Users/x/dev/b", status="working"))),
            "mmini")
        self.assertEqual(mmini.fallback_group(spaces, rigs), "space:b")


class PromptInputTests(unittest.TestCase):
    def test_classify(self):
        c = mmini.classify_space_input
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
            self.assertTrue(mmini.valid_space_name(good), good)
        for bad in ("", "a/b", "~x", "-x", ".", "..", "tab\tname", "é"):
            self.assertFalse(mmini.valid_space_name(bad), bad)

    def test_probe_arg(self):
        self.assertEqual(mmini.probe_arg("name", "foo"), "dev/foo")
        self.assertEqual(mmini.probe_arg("folder", "~"), ".")
        self.assertEqual(mmini.probe_arg("folder", "~/"), ".")
        self.assertEqual(mmini.probe_arg("folder", "~/dev/foo"), "dev/foo")
        self.assertEqual(mmini.probe_arg("folder", "/opt/x"), "/opt/x")

    def test_plan_folder(self):
        p = mmini.plan_new_space
        self.assertEqual(p("folder", "~/dev/foo", "/Users/r", True), ("/Users/r/dev/foo", "", ""))
        self.assertEqual(p("folder", "~", "/Users/r", True), ("/Users/r", "", ""))
        self.assertEqual(p("folder", "/opt/x/", "/Users/r", True), ("/opt/x", "", ""))
        self.assertEqual(p("folder", "/opt/x", "", None), ("/opt/x", "", ""))  # could not ask: try it
        self.assertEqual(p("folder", "~/nope", "/Users/r", False), ("", "", "no folder ~/nope"))
        self.assertTrue(p("folder", "~/x", "", None)[2])  # ~ without a known home folder: say so, never guess

    def test_plan_name(self):
        p = mmini.plan_new_space
        self.assertEqual(p("name", "foo", "/Users/r", True), ("/Users/r/dev/foo", "", ""))
        self.assertEqual(p("name", "foo", "/Users/r", False), ("/Users/r", "foo", ""))
        self.assertEqual(p("name", "foo", "/Users/r", None), ("/Users/r", "foo", ""))
        self.assertEqual(p("name", "foo", "", None), ("", "foo", ""))  # hc starts it in that machine's home

    def test_parse_probe(self):
        self.assertEqual(mmini.parse_probe("/Users/r\ndir\n"), ("/Users/r", True))
        self.assertEqual(mmini.parse_probe("/home/u/\nnone\n"), ("/home/u", False))
        for junk in ("", "dir\n", "relative\ndir\n", "/Users/r\nmaybe\n"):
            with self.assertRaises(ValueError):
                mmini.parse_probe(junk)

    def test_probe_folder_calls_hc_exec(self):
        calls = []

        def fake(*args, **kw):
            calls.append(args)
            return "/Users/r\nnone\n"

        self.assertEqual(mmini.probe_folder("mmini", "dev/foo", fake), ("/Users/r", False))
        self.assertEqual(calls[-1][:5], ("exec", "--on", "mmini", "/bin/sh", "-c"))
        self.assertEqual(calls[-1][-1], "dev/foo")
        mmini.probe_folder(mmini.LOCAL, "/opt", fake)
        self.assertEqual(calls[-1][:3], ("exec", "/bin/sh", "-c"))

    def test_probe_script_runs_in_sh(self):
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "dev"))
            os.mkdir(os.path.join(d, "dev", "foo"))
            for arg, want in (("dev/foo", True), ("dev/nope", False), (d, True), (".", True), ("/nonexistent", False)):
                out = subprocess.run(["/bin/sh", "-c", mmini.PROBE, "mmini", arg], capture_output=True, text=True,
                                     env={"HOME": d, "PATH": "/usr/bin:/bin"}).stdout
                self.assertEqual(mmini.parse_probe(out), (d, want), arg)

    def test_home_dir_from_cwds(self):
        self.assertEqual(mmini.home_dir_from_cwds(["/Users/r/dev/a", "/Users/r", "/tmp", "/home/o/x"]), "/Users/r")
        self.assertEqual(mmini.home_dir_from_cwds(["/tmp", ""]), "")


class SidebarPlanTests(unittest.TestCase):
    def setUp(self):
        self.spaces, self.rigs = mmini.build_groups(mmini.parse(SAMPLE), "mmini")

    def test_tall_layout_bottom_anchored(self):
        plan = mmini.plan_sidebar(self.spaces, self.rigs, 40)
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
        lines = mmini.help_lines(29, 40)
        text = "\n".join(lines)
        self.assertEqual(lines[0], " keys · any key closes")
        for line in (" ↑↓ j k  move", " enter   show it", " a       menu (right click)", " e       rename",
                     " d       delete, forget, end", " n       new terminal here", " s       new space",
                     " m       move to a space", " v       show/hide servers", " c       fold, then hide",
                     " o       open the strip", " q       hide", " z       zoom the view",
                     " ⌘⇧↵     back from the zoom", " [ ] - = separator up/down",
                     " r       refresh", " ?       this list"):
            self.assertIn(line, lines)
        self.assertNotIn("quit", text)  # q hides the sidebar: its pane closes
        self.assertIsNone(re.search(r"\brigs?\b", text))
        self.assertTrue(all(mmini.text_width(line) <= 29 for line in lines))
        with mock.patch.object(mmini, "utf8_screen", return_value=False):  # cmd+shift+enter is longer: cut, not wrapped
            ascii_lines = [mmini.glyph(line) for line in mmini.help_lines(29, 40)]  # as Screen.put draws them
            self.assertTrue(all(len(line) <= 29 and line.isascii() for line in ascii_lines))
            self.assertIn(" cmd+shift+enter back from t~", ascii_lines)

    def test_the_list_of_keys_on_a_short_or_narrow_pane(self):
        self.assertEqual(mmini.help_lines(29, 0), [])
        self.assertEqual(mmini.help_lines(0, 10), [])
        short = mmini.help_lines(29, 5)
        self.assertEqual(len(short), 5)
        self.assertEqual(short[-1], " …")
        self.assertTrue(all(mmini.text_width(line) <= 10 for line in mmini.help_lines(10, 40)))
        self.assertEqual(len(mmini.help_lines(29, 40)), 1 + len(mmini.help_entries()))
        self.assertEqual(len(mmini.help_entries()), len(mmini.KEY_HELP) + 3)  # the marks of the tests: ¹ ² ³

    def test_servers_section_is_always_there_for_add_server_while_shown(self):
        plan = mmini.plan_sidebar(self.spaces, [], 40)
        rows = [(r.kind, r.text) for _, r in plan]
        at = rows.index(("header", "servers"))
        self.assertEqual(rows[at - 2:at + 2], [("plus", "new_space"), ("blank", ""), ("header", "servers"),
                                               ("plus", "add_rig")])
        hidden = [(r.kind, r.text) for _, r in mmini.plan_sidebar(self.spaces, self.rigs, 40, servers=False)]
        self.assertNotIn(("header", "servers"), hidden)
        self.assertNotIn(("plus", "add_rig"), hidden)
        self.assertEqual(sum(1 for k, _ in hidden if k == "group"), len(self.spaces))
        self.assertEqual(hidden[:len(self.spaces) + 2][-1], ("plus", "new_space"))

    def test_no_hint_block_more_agent_rows_instead(self):
        spaces, rigs = many_agents(6)
        top = top_rows(spaces, rigs)
        # before: 4 hint lines took the bottom; now the rule, the header, a heading and all 6 agents fit in top + 9
        plan = mmini.plan_sidebar(spaces, rigs, top + 9, 0)
        self.assertEqual(sum(1 for _, r in plan if r.kind == "agent"), 6)
        self.assertNotIn("more", [r.kind for _, r in plan])

    def test_small_height_keeps_all_groups(self):
        for h in range(top_rows(self.spaces, self.rigs), 18):
            plan = mmini.plan_sidebar(self.spaces, self.rigs, h)
            self.assertEqual(sum(1 for _, r in plan if r.kind == "group"), 6, h)
            self.assertTrue(all(0 <= y < h for y, _ in plan), h)
            ys = [y for y, _ in plan]
            self.assertEqual(len(ys), len(set(ys)), h)

    def test_more_line_when_agents_cut(self):
        plan = mmini.plan_sidebar(self.spaces, self.rigs, 14)
        more = [r for _, r in plan if r.kind == "more"]
        shown = sum(1 for _, r in plan if r.kind == "agent")
        self.assertEqual(len(more), 1)
        self.assertEqual(more[0].count + shown, 3)
        self.assertTrue(more[0].text.startswith("+"))

    def test_cursor_agent_always_placed_when_one_group_has_many(self):
        spaces, rigs = many_agents(6)
        items = mmini.selectable_items(spaces, rigs)
        top = top_rows(spaces, rigs)
        for h in range(top + 1, 24):  # from one free line below the spaces and rigs
            for cursor, item in enumerate(items):
                plan = mmini.plan_sidebar(spaces, rigs, h, cursor)
                ys = [y for y, _ in plan]
                self.assertEqual(len(ys), len(set(ys)), (h, cursor))
                self.assertTrue(all(0 <= y < h for y in ys), (h, cursor))
                self.assertIn(cursor, [r.item for _, r in plan if r.kind in ("group", "plus", "agent")], (h, cursor))
                self.assertEqual(sum(1 for _, r in plan if r.kind == "group"), len(spaces) + len(rigs), (h, cursor))

    def test_window_keeps_its_group_heading(self):
        spaces, rigs = many_agents(6)
        plan = mmini.plan_sidebar(spaces, rigs, 11, 2 + 4)  # cursor on the 5th agent
        kinds = [r.kind for _, r in plan]
        first_agent = kinds.index("agent")
        self.assertEqual(kinds[first_agent - 1], "agent_group")
        self.assertEqual(kinds[-1], "more")
        shown = sum(1 for k in kinds if k == "agent")
        self.assertEqual([r.count for _, r in plan if r.kind == "more"][0], 6 - shown)

    def test_short_screen_gives_up_the_rule_before_agents(self):
        spaces, rigs = many_agents(6)
        top = top_rows(spaces, rigs)
        plan = mmini.plan_sidebar(spaces, rigs, top + 4, 0)  # the top lines + 4
        kinds = [r.kind for _, r in plan]
        self.assertNotIn("rule", kinds)
        self.assertIn("agent", kinds)
        plan = mmini.plan_sidebar(spaces, rigs, top + 5, 0)
        self.assertEqual([r.kind for _, r in plan].count("rule"), 1)

    def test_no_line_for_agents_means_none_placed(self):
        spaces, rigs = many_agents(6)
        first_agent = [i.kind for i in mmini.selectable_items(spaces, rigs)].index("agent")
        plan = mmini.plan_sidebar(spaces, rigs, 3, first_agent)
        self.assertNotIn(first_agent, [r.item for _, r in plan])  # the sidebar then keeps the cursor off that row

    def test_tiny_heights_do_not_crash(self):
        for h in range(0, 8):
            for cursor in range(0, 8):
                plan = mmini.plan_sidebar(self.spaces, self.rigs, h, cursor)
                self.assertTrue(all(0 <= y < h for y, _ in plan))

    def test_many_spaces_scroll_to_cursor(self):
        raw = ls(*[term(f"t{i}", f"/Users/x/dev/s{i:02d}") for i in range(30)])
        spaces, rigs = mmini.build_groups(mmini.parse(raw), "mmini")
        plan = mmini.plan_sidebar(spaces, rigs, 10, 25)
        self.assertIn(25, [r.item for _, r in plan if r.kind == "group"])

    def test_compact_plan_has_no_hints_and_keeps_the_cursor(self):
        spaces, rigs = many_agents(6)
        items = mmini.selectable_items(spaces, rigs)
        for h in range(0, 30):
            for cursor in range(len(items)):
                plan = mmini.plan_sidebar(spaces, rigs, h, cursor, compact=True)
                self.assertNotIn("hint", [r.kind for _, r in plan], (h, cursor))
                ys = [y for y, _ in plan]
                self.assertEqual(len(ys), len(set(ys)), (h, cursor))
                self.assertTrue(all(0 <= y < h for y in ys), (h, cursor))
                if h >= top_rows(spaces, rigs):  # the top part fits: every group is there, the cursor's agent too
                    self.assertEqual(sum(1 for _, r in plan if r.kind == "group"), len(spaces) + len(rigs),
                                     (h, cursor))
                    if h >= 1 + top_rows(spaces, rigs):
                        self.assertIn(cursor, [r.item for _, r in plan], (h, cursor))
        tall = mmini.plan_sidebar(spaces, rigs, 40, 0, compact=True)
        self.assertEqual(sum(1 for _, r in tall if r.kind == "agent"), 6)


class SidebarFrameTests(unittest.TestCase):
    """The arrow lines ("‹" last, "›" above it in the strip), and the lines left for the list and a message."""

    def test_arrow_lines_at_every_height(self):
        for height in range(0, 61):
            for message in (False, True):
                for prompt in (False, True):
                    for strip in (False, True):
                        body, arrow_y, open_y, extra = mmini.sidebar_frame(height, message, prompt, strip)
                        case = (height, message, prompt, strip)
                        # every line has one use
                        self.assertEqual(body + extra + (arrow_y >= 0) + (open_y >= 0), height, case)
                        self.assertEqual(arrow_y, height - 1 if height >= 2 else -1, case)
                        self.assertEqual(open_y, height - 2 if strip and height >= 3 else -1, case)
                        if height >= 1:
                            self.assertGreaterEqual(body, 1, case)  # never over the cursor's line
                        self.assertLessEqual(extra, 2 if prompt else 1 if message else 0, case)

    def test_message_and_prompt_lines(self):
        self.assertEqual(mmini.sidebar_frame(0, True, True), (0, -1, -1, 0))
        self.assertEqual(mmini.sidebar_frame(1, True, True), (1, -1, -1, 0))  # one line: the cursor's
        self.assertEqual(mmini.sidebar_frame(2, True, False), (1, 1, -1, 0))  # the arrow wins over the message
        self.assertEqual(mmini.sidebar_frame(3, True, False), (1, 2, -1, 1))
        self.assertEqual(mmini.sidebar_frame(3, False, True), (1, 2, -1, 1))  # the typed line, no title
        self.assertEqual(mmini.sidebar_frame(5, False, True), (2, 4, -1, 2))
        self.assertEqual(mmini.sidebar_frame(24, False, False), (23, 23, -1, 0))
        self.assertEqual(mmini.sidebar_frame(24, True, False), (22, 23, -1, 1))

    def test_strip_order_at_tiny_heights_cursor_then_hide_then_open(self):
        f = mmini.sidebar_frame
        self.assertEqual(f(1, True, False, True), (1, -1, -1, 0))  # the cursor's line only
        self.assertEqual(f(2, True, False, True), (1, 1, -1, 0))  # then "‹"
        self.assertEqual(f(3, True, False, True), (1, 2, 1, 0))  # then "›"; no room for the message
        self.assertEqual(f(4, True, False, True), (1, 3, 2, 1))  # the message just above "›"
        self.assertEqual(f(24, False, False, True), (22, 23, 22, 0))

    def test_arrow_labels(self):
        self.assertEqual(mmini.fold_label("open", 29), " ‹ fold")
        self.assertEqual(mmini.fold_label("strip", 29), " ‹ hide")
        self.assertEqual(mmini.open_label(29), " › open")
        self.assertEqual(mmini.fold_label("strip", 7), " ‹ hide")
        self.assertEqual(mmini.open_label(6), " ›")
        self.assertEqual(mmini.fold_label("open", 2), " ‹")
        self.assertEqual(mmini.open_label(1), "›")
        self.assertEqual(mmini.fold_label("strip", 0), "‹")
        with mock.patch.object(mmini, "utf8_screen", return_value=False):
            self.assertEqual(mmini.glyph(mmini.fold_label("open", 29)), " < fold")
            self.assertEqual(mmini.glyph(mmini.fold_label("strip", 29)), " < hide")
            self.assertEqual(mmini.glyph(mmini.open_label(29)), " > open")
            self.assertEqual(mmini.glyph(mmini.open_label(2)), " >")

    def test_sidebar_hit(self):
        item = mmini.Item("group", "space:a", "")
        rows = {1: item, 3: mmini.Item("agent", "space:a", "t1")}
        self.assertEqual(mmini.sidebar_hit(9, 9, -1, rows), ("step", None))
        self.assertEqual(mmini.sidebar_hit(9, 9, 8, rows), ("step", None))
        self.assertEqual(mmini.sidebar_hit(8, 9, 8, rows), ("open", None))
        self.assertEqual(mmini.sidebar_hit(8, 9, -1, rows), ("", None))  # no "›" line in the open sidebar
        self.assertEqual(mmini.sidebar_hit(1, 9, 8, rows), ("item", item))
        self.assertEqual(mmini.sidebar_hit(3, 9, 8, rows)[1].address, "t1")
        self.assertEqual(mmini.sidebar_hit(2, 9, 8, rows), ("", None))
        self.assertEqual(mmini.sidebar_hit(0, -1, -1, {}), ("", None))  # no arrows on a one-line screen
        self.assertEqual(mmini.sidebar_hit(1, 1, -1, rows), ("step", None))  # an arrow's line is never a row
        self.assertEqual(mmini.sidebar_hit(3, 4, 3, rows), ("open", None))

    def test_c_steps_open_strip_hidden(self):
        self.assertEqual(mmini.SIDEBAR_STATES, ("open", "strip", "hidden"))
        n = mmini.next_sidebar_state
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
        lay = mmini.layout_tabs(["a", "bb"], 0, 40, 4)
        self.assertEqual(self.lines(lay, 40), [" ● a │ ● bb │ +"])
        self.assertEqual(lay.rows, 1)
        self.assertFalse(lay.left_cut or lay.right_cut)

    def test_no_tabs(self):
        lay = mmini.layout_tabs([], -1, 20, 3)
        self.assertEqual(self.lines(lay, 20), [" +"])
        self.assertEqual(mmini.hit_test(lay, 1, 0), ("plus", -1))

    def test_hit_test_one_row(self):
        lay = mmini.layout_tabs(["a", "bb"], 0, 40)
        self.assertEqual(mmini.hit_test(lay, 0), ("tab", 0))
        self.assertEqual(mmini.hit_test(lay, 4), ("tab", 0))
        self.assertIsNone(mmini.hit_test(lay, 5))  # separator
        self.assertEqual(mmini.hit_test(lay, 6), ("tab", 1))
        self.assertEqual(mmini.hit_test(lay, 6 + 6 + 1 + 1), ("plus", -1))
        self.assertIsNone(mmini.hit_test(lay, 39))
        self.assertIsNone(mmini.hit_test(lay, 0, 1))  # no such row

    def test_dot_position(self):
        lay = mmini.layout_tabs(["a", "bb"], 0, 40)
        tab = [s for s in lay.segs if s.kind == "tab"]
        self.assertEqual((tab[0].dot_x, tab[1].dot_x), (1, 7))
        self.assertEqual(tab[0].text[1], "●")

    def test_tabs_wrap_onto_further_rows(self):
        labels = ["alpha", "beta", "gamma", "delta", "eps"]
        lay = mmini.layout_tabs(labels, 3, 22, 4)
        self.assertEqual(self.lines(lay, 22), [" ● alpha │ ● beta", " ● gamma │ ● delta", " ● eps │ +"])
        self.assertFalse(lay.left_cut or lay.right_cut)
        self.assertEqual(lay.rows, 3)
        self.assertTrue(all(s.end <= 22 for s in lay.segs))
        self.assertEqual(sorted(s.index for s in lay.segs if s.kind == "tab"), [0, 1, 2, 3, 4])

    def test_hit_test_wrapped_rows(self):
        lay = mmini.layout_tabs(["alpha", "beta", "gamma", "delta", "eps"], 3, 22, 4)
        self.assertEqual(mmini.hit_test(lay, 2, 0), ("tab", 0))
        self.assertEqual(mmini.hit_test(lay, 12, 0), ("tab", 1))
        self.assertEqual(mmini.hit_test(lay, 2, 1), ("tab", 2))
        self.assertEqual(mmini.hit_test(lay, 12, 1), ("tab", 3))
        self.assertIsNone(mmini.hit_test(lay, 9, 1))  # separator
        self.assertEqual(mmini.hit_test(lay, 2, 2), ("tab", 4))
        self.assertEqual(mmini.hit_test(lay, 9, 2), ("plus", -1))
        self.assertIsNone(mmini.hit_test(lay, 2, 3))
        self.assertIsNone(mmini.hit_test(lay, 20, 2))

    def test_plus_wraps_alone_when_the_row_is_full(self):
        lay = mmini.layout_tabs(["abcdef", "ghijkl"], 0, 21, 3)
        self.assertEqual(self.lines(lay, 21), [" ● abcdef │ ● ghijkl", " +"])
        self.assertEqual(mmini.hit_test(lay, 1, 1), ("plus", -1))

    def test_one_long_label_is_shortened_to_the_row(self):
        lay = mmini.layout_tabs(["a-very-long-terminal-name", "b"], 0, 16, 3)
        first = [s for s in lay.segs if s.kind == "tab"][0]
        self.assertEqual(len(first.text), 16)
        self.assertTrue(first.text.rstrip().endswith("…"))

    def test_scrolls_only_when_all_rows_are_not_enough(self):
        labels = [f"terminal{i}" for i in range(8)]  # 13 columns each
        fits = mmini.layout_tabs(labels, 7, 30, 5)   # 2 per row -> 4 rows + the "+"
        self.assertFalse(fits.left_cut or fits.right_cut)
        self.assertEqual(len([s for s in fits.segs if s.kind == "tab"]), 8)
        for rows in (1, 2, 3):
            for active in range(8):
                lay = mmini.layout_tabs(labels, active, 30, rows)
                self.assertEqual(lay.rows, rows)
                self.assertTrue(any(s.kind == "tab" and s.index == active for s in lay.segs), (rows, active))
                plus = [s for s in lay.segs if s.kind == "plus"][0]
                self.assertEqual((plus.y, plus.end), (0, 30))
                self.assertEqual(mmini.hit_test(lay, 28, 0), ("plus", -1))
                self.assertTrue(all(0 <= s.x and s.end <= 30 and 0 <= s.y < rows for s in lay.segs))
                for s in lay.segs:  # every visible tab is whole and clickable where it is drawn
                    if s.kind == "tab":
                        self.assertEqual(mmini.hit_test(lay, s.x + 2, s.y), ("tab", s.index))
            first = mmini.layout_tabs(labels, 0, 30, rows)
            last = mmini.layout_tabs(labels, 7, 30, rows)
            self.assertEqual((first.left_cut, first.right_cut), (False, True))
            self.assertEqual((last.left_cut, last.right_cut), (True, False))
            self.assertEqual([s.text for s in first.segs if s.kind == "cut"], ["›"])
            self.assertEqual([s.text for s in last.segs if s.kind == "cut"], ["‹"])

    def test_tiny_widths(self):
        for w in range(0, 12):
            for rows in (1, 2, 5):
                lay = mmini.layout_tabs(["alpha", "beta"], 1, w, rows)
                self.assertIsInstance(lay.segs, list)
                self.assertLessEqual(lay.rows, rows)

    def test_tab_hint_keeps_the_way_back_from_a_zoom_longest(self):
        self.assertEqual(mmini.tab_hint(200), mmini.TAB_HINTS[0])
        self.assertEqual(mmini.tab_hint(len(mmini.TAB_HINTS[0]) - 1), mmini.TAB_HINTS[1])
        self.assertEqual(mmini.tab_hint(len(mmini.TAB_HINTS[2])), "z zoom  ⌘⇧↵ back")
        self.assertEqual(mmini.tab_hint(len(mmini.TAB_HINTS[2]) - 1), "")
        self.assertEqual(mmini.tab_hint(-5), "")
        self.assertTrue(all("⌘⇧↵ back" in h for h in mmini.TAB_HINTS))
        with mock.patch.object(mmini, "utf8_screen", return_value=False):  # measured as drawn
            self.assertEqual(mmini.tab_hint(len(mmini.TAB_HINTS[2])), "")
            self.assertEqual(mmini.tab_hint(len("z zoom  cmd+shift+enter back")), mmini.TAB_HINTS[2])

    def test_tab_hint_without_a_sidebar_names_its_key(self):
        alone = mmini.TAB_HINTS_ALONE
        self.assertEqual(mmini.tab_hint(200, True), alone[0])
        self.assertTrue(all(h.startswith("c sidebar") for h in alone[:-1]))
        self.assertEqual(alone[-1], mmini.TAB_HINTS[-1])  # the way back from a zoom still goes last
        for i in range(len(alone) - 1):
            self.assertEqual(mmini.tab_hint(len(alone[i]) - 1, True), alone[i + 1])
        self.assertEqual(mmini.tab_hint(len(alone[-1]) - 1, True), "")

    def test_opener_shifts_the_tabs_and_is_hit_first(self):
        plain = mmini.layout_tabs(["alpha", "beta"], 0, 30, 2)
        lay = mmini.with_opener(mmini.layout_tabs(["alpha", "beta"], 0, 29, 2))
        self.assertEqual(self.lines(lay, 31), ["›" + line for line in self.lines(plain, 30)])
        self.assertEqual(mmini.hit_test(lay, 0, 0), ("open", -1))
        self.assertEqual(mmini.hit_test(lay, 1, 0), ("tab", 0))
        self.assertEqual(mmini.hit_test(plain, 0, 0), ("tab", 0))  # with a sidebar the first cell is a tab's
        self.assertIsNone(mmini.hit_test(lay, 0, 1))  # "›" is on the first row only
        wrapped = mmini.with_opener(mmini.layout_tabs(["alpha", "beta", "gamma"], 2, 20, 3))
        self.assertEqual(self.lines(wrapped, 21), ["› ● alpha │ ● beta", "  ● gamma │ +"])
        self.assertEqual(mmini.hit_test(wrapped, 1, 1), ("tab", 2))
        self.assertEqual(mmini.with_opener(mmini.TabLayout([], 0)).rows, 1)

    def test_tab_bar_rows(self):
        self.assertEqual(mmini.tab_bar_rows(0), (0, -1))
        self.assertEqual(mmini.tab_bar_rows(1), (1, -1))   # one row: tabs only
        self.assertEqual(mmini.tab_bar_rows(2), (1, 1))    # tabs + hints
        self.assertEqual(mmini.tab_bar_rows(5), (4, 4))    # a tenth of a 50-row window

    def test_tab_info(self):
        tab = {"address": "mmini/t5", "cwd": "/Users/r/dev/atlas", "agent": "claude-code", "status": "idle"}
        self.assertEqual(mmini.tab_info(tab), "mmini/t5 · ~/dev/atlas · claude-code · idle")
        self.assertEqual(mmini.tab_info({"address": "t1", "cwd": "/tmp", "agent": "zsh"}), "t1 · /tmp · zsh")
        long = dict(tab, cwd="/private/tmp/some/very/long/folder/name/that/does/not/fit/work")
        self.assertEqual(mmini.tab_info(long, 44), "mmini/t5 · …ot/fit/work · claude-code · idle")
        self.assertLessEqual(len(mmini.tab_info(long, 44)), 44)
        self.assertEqual(mmini.tab_info(long, 30), "mmini/t5 · claude-code · idle")  # no room for a folder
        self.assertEqual(mmini.short_folder("/home/u"), "~")


class GhosttyModel:
    """Ghostty's split as its source describes it: the divider moves `gain` times the cells asked for (the amount
    is in points, the reported size in device pixels) and the pane stays between 10% and 90% of the window."""

    def __init__(self, window, size, gain=2.0, shrink="left", late=0):
        self.window, self.size, self.gain, self.shrink, self.late = window, float(size), gain, shrink, late
        self.sent = []

    def apply(self, action):
        direction, cells = action
        self.sent.append(action)
        if self.late:  # this step never arrives in time
            self.late -= 1
            return
        delta = cells * self.gain * (-1 if direction == self.shrink else 1)
        self.size = max(0.1 * self.window, min(0.9 * self.window, self.size + delta))

    def run(self, target, dirs, tolerance=1):
        state = mmini.ResizeState()
        while True:
            action, state = mmini.next_resize(int(self.size), target, state, dirs, tolerance)
            if action is None:
                return int(self.size)
            self.apply(action)


class ResizeTests(unittest.TestCase):
    D = ("left", "right")

    def test_done_within_tolerance(self):
        for size in (29, 30, 31):
            self.assertIsNone(mmini.next_resize(size, 30, mmini.ResizeState(), self.D)[0])
        self.assertIsNotNone(mmini.next_resize(3, 2, mmini.ResizeState(), ("up", "down"), 0)[0])
        self.assertIsNone(mmini.next_resize(2, 2, mmini.ResizeState(), ("up", "down"), 0)[0])

    def test_first_step_uses_the_layouts_direction_and_the_first_gain(self):
        action, state = mmini.next_resize(60, 30, mmini.ResizeState(), self.D)
        self.assertEqual(action, ("left", 30 / mmini.FIRST_GAIN))
        self.assertEqual((state.steps, state.before, state.grow), (1, 60, False))
        action, _ = mmini.next_resize(10, 30, mmini.ResizeState(), self.D)
        self.assertEqual(action, ("right", 20 / mmini.FIRST_GAIN))
        action, _ = mmini.next_resize(20, 2, mmini.ResizeState(), ("up", "down"), 0)
        self.assertEqual(action[0], "up")

    def test_a_move_the_other_way_stops_and_teaches_nothing(self):
        # asked to shrink by 4 at the 10% limit, the pane grew from 12 to 14: the window grew meanwhile
        sent = mmini.ResizeState(steps=2, gain=1.5, before=12, asked=4.0, grow=False)
        action, state = mmini.next_resize(14, 6, sent, self.D)
        self.assertIsNone(action)  # no step "right" (the old swap of directions), no gain of 2/4
        self.assertTrue(state.stray)
        self.assertEqual((state.gain, state.steps), (1.5, 2))
        sent = mmini.ResizeState(steps=1, gain=2.0, before=12, asked=9.0, grow=True)  # meant to grow, it shrank
        self.assertTrue(mmini.next_resize(10, 30, sent, self.D)[1].stray)
        self.assertFalse(mmini.next_resize(30, 30, sent, self.D)[1].stray)  # moved the way asked: no stray

    def test_gain_is_learnt_from_the_last_step(self):
        sent = mmini.ResizeState(steps=1, gain=1.0, before=100, asked=20.0)  # asked for 20, moved 40: a 2x display
        action, state = mmini.next_resize(60, 30, sent, self.D)
        self.assertEqual(state.gain, 2.0)
        self.assertEqual(action, ("left", 15.0))

    def test_overshoot_comes_back_with_the_corrected_amount(self):
        sent = mmini.ResizeState(steps=1, gain=1.0, before=60, asked=30.0)  # asked for 30, moved 48 (past the goal)
        action, state = mmini.next_resize(12, 30, sent, self.D)
        self.assertEqual(action[0], "right")
        self.assertAlmostEqual(action[1], 18 / 1.6)
        self.assertFalse(state.stray)  # an overshoot moved the way asked

    def test_gain_stays_within_limits(self):
        sent = mmini.ResizeState(steps=1, gain=1.0, before=100, asked=2.0)
        self.assertEqual(mmini.next_resize(40, 30, sent, self.D)[1].gain, mmini.GAIN_LIMITS[1])
        sent = mmini.ResizeState(steps=1, gain=1.0, before=100, asked=50.0)
        self.assertEqual(mmini.next_resize(99, 30, sent, self.D)[1].gain, mmini.GAIN_LIMITS[0])

    def test_no_movement_stops_instead_of_sending_again(self):
        sent = mmini.ResizeState(steps=1, gain=2.0, before=60, asked=15.0)
        action, state = mmini.next_resize(60, 30, sent, self.D)
        self.assertIsNone(action)
        self.assertEqual(state.steps, 1)
        self.assertFalse(state.stray)

    def test_step_limit(self):
        self.assertIsNone(mmini.next_resize(90, 30, mmini.ResizeState(mmini.MAX_RESIZE_STEPS), self.D)[0])
        self.assertIsNotNone(mmini.next_resize(90, 30, mmini.ResizeState(mmini.MAX_RESIZE_STEPS - 1), self.D)[0])

    def test_sidebar_converges_on_retina_and_plain_displays(self):
        for window in (100, 120, 160, 200, 250, 300):
            for gain in (1.0, 2.0, 3.0):
                model = GhosttyModel(window, window // 2, gain)
                end = model.run(30, self.D)
                self.assertLessEqual(abs(end - 30), 1, (window, gain, model.sent))
                self.assertLessEqual(len(model.sent), mmini.MAX_RESIZE_STEPS, (window, gain))
        self.assertEqual(len(GhosttyModel(200, 100, 2.0).sent), 0)
        model = GhosttyModel(160, 80, 2.0)  # a MacBook: the first amount already allows for 2x
        model.run(30, self.D)
        self.assertEqual(len(model.sent), 1)

    def test_a_window_resize_during_the_step_at_the_limit_sends_nothing_the_other_way(self):
        """Folded: the step at the 10% limit moves nothing, so the loop waits its full time; the window changes size
        meanwhile and the strip (a share of the window) with it. That change is not the step's: no step the other way,
        no jump past the strip's width, and the loop ends on it with 0 (no limit found), so the sidebar's refit looks
        again once the size is quiet."""
        for window, new, gain in ((120, 140, 2.0), (160, 200, 2.0), (120, 200, 1.0), (320, 360, 2.0),
                                  (200, 120, 2.0)):
            model = GhosttyModel(window, max(30, int(0.1 * window) + 8), gain)  # open, above the 10% limit
            seen = []

            def wait(before, moved_on):
                if int(model.size) == before and model.window == window:  # the step at the limit: the window changes
                    model.size, model.window = model.size * new / window, new
                seen.append(int(model.size))
                return int(model.size)

            size, aimed = mmini.resize_loop(lambda: (int(model.size), 1.0),
                                            lambda d, amount: model.apply((d, float(amount))),
                                            lambda: mmini.NARROW, wait, self.D, 1)
            case = (window, new, gain, model.sent, seen)
            self.assertEqual({d for d, _ in model.sent}, {"left"}, case)
            self.assertLessEqual(max(seen), max(int(0.1 * window), int(0.1 * new)) + 1, case)
            self.assertEqual(aimed, mmini.NARROW, case)
            if new > window:
                self.assertEqual(size, 0, case)  # stopped by the outside change: not taken as the limit

    def test_sidebar_stops_at_the_ten_percent_limit_of_a_very_wide_window(self):
        model = GhosttyModel(400, 200, 2.0)  # 10% of 400 columns is 40: 30 cannot be reached
        self.assertEqual(model.run(30, self.D), 40)
        self.assertLessEqual(len(model.sent), 3)

    def test_tab_bar_stops_cleanly_at_the_ten_percent_limit(self):
        for rows, gain in ((50, 1.0), (50, 2.0), (70, 2.0), (45, 1.0)):
            model = GhosttyModel(rows, rows // 2, gain, shrink="up")
            end = model.run(2, ("up", "down"), 0)
            self.assertEqual(end, int(0.1 * rows), (rows, gain))
            self.assertLessEqual(len(model.sent), 3, (rows, gain, model.sent))  # the last one shows the limit
        model = GhosttyModel(20, 10, 2.0, shrink="up")  # a small window: 10% is 2 rows
        self.assertEqual(model.run(2, ("up", "down"), 0), 2)

    def test_a_step_that_never_arrives_is_not_sent_twice(self):
        model = GhosttyModel(120, 60, 2.0, late=1)
        self.assertEqual(model.run(30, self.D), 60)
        self.assertEqual(len(model.sent), 1)

    def test_folding_ends_at_the_ten_percent_limit(self):
        for window, gain in ((120, 2.0), (200, 2.0), (300, 1.0), (60, 2.0)):
            model = GhosttyModel(window, 30, gain)  # open at MMINI_WIDTH, then folded toward 6 columns
            self.assertEqual(model.run(mmini.NARROW, self.D), max(mmini.NARROW, int(0.1 * window)), (window, gain))
            self.assertLessEqual(len(model.sent), 3, (window, gain, model.sent))  # the last step shows the limit
            back = len(model.sent)
            self.assertLessEqual(abs(model.run(mmini.WIDTH, self.D) - mmini.WIDTH), 1, (window, gain))
            self.assertLessEqual(len(model.sent) - back, mmini.MAX_RESIZE_STEPS)

    def loop(self, model, goal):
        """resize_loop against the model: 1 pixel per cell, every step's effect seen at once (or never)."""
        return mmini.resize_loop(lambda: (int(model.size), 1.0), lambda d, amount: model.apply((d, float(amount))),
                                 goal, lambda before, moved_on: int(model.size), self.D, 1)

    def test_resize_loop_ends_where_next_resize_does(self):
        model = GhosttyModel(160, 80, 2.0)
        self.assertEqual(self.loop(model, lambda: 30), (30, 30))
        self.assertEqual(self.loop(GhosttyModel(120, 30, 2.0), lambda: 6), (12, 6))  # at the limit

    def test_resize_loop_turns_to_a_new_goal_even_at_the_limit(self):
        for window, gain in ((120, 2.0), (160, 2.0), (120, 1.0), (160, 1.0)):
            model = GhosttyModel(window, 30, gain)
            stuck = []  # the step that ran into the 10% limit: c is pressed again during its wait
            seen = []

            def wait(before, moved_on):
                if int(model.size) == before:
                    stuck.append(len(model.sent))
                seen.append((bool(stuck), int(model.size)))
                return int(model.size)

            size, aimed = mmini.resize_loop(lambda: (int(model.size), 1.0),
                                            lambda d, amount: model.apply((d, float(amount))),
                                            lambda: mmini.WIDTH if stuck else mmini.NARROW, wait, self.D, 1)
            case = (window, gain, model.sent, seen)
            self.assertEqual(aimed, mmini.WIDTH, case)
            self.assertLessEqual(abs(size - mmini.WIDTH), 1, case)
            self.assertEqual(model.sent[stuck[0] - 1][0], "left", case)  # the step at the limit, which moved nothing
            self.assertEqual(model.sent[stuck[0]][0], "right", case)  # not taken as the end: on to the new goal
            # the gain of the step cut short by the limit is not kept: no jump past MMINI_WIDTH on the way back
            self.assertLessEqual(max(n for after, n in seen if after), mmini.WIDTH + 1, case)

    def test_resize_loop_stops_at_once_for_a_zoom(self):
        model = GhosttyModel(160, 80, 2.0)
        size, aimed = self.loop(model, lambda: None if model.sent else 30)
        self.assertIsNone(aimed)
        self.assertEqual(len(model.sent), 1)  # nothing more after the zoom
        self.assertEqual(size, int(model.size))
        model = GhosttyModel(160, 80, 2.0)
        self.assertEqual(self.loop(model, lambda: None), (80, None))
        self.assertEqual(model.sent, [])

    def test_resize_loop_without_a_size(self):
        sent = []
        self.assertEqual(mmini.resize_loop(lambda: (0, 0.0), lambda *a: sent.append(a), lambda: 30,
                                           lambda b, m: 0), (0, 30))
        self.assertEqual(sent, [])

    def test_refit_after_the_window_changed_size(self):
        due = mmini.refit_due
        quiet = mmini.REFIT_QUIET
        self.assertTrue(due(75, 30, quiet, False, 30))        # maximised: the sidebar grew with the window
        self.assertTrue(due(12, 30, quiet, False, 30))        # window made narrow
        self.assertFalse(due(75, 30, quiet - 0.1, False, 30))  # still changing
        self.assertFalse(due(75, 30, quiet, True, 30))         # a resize loop is running
        for width in (29, 30, 31):
            self.assertFalse(due(width, 30, quiet, False, 0))  # on target
        self.assertFalse(due(40, 30, quiet, False, 40))        # where the last loop ended (10% limit): not again
        self.assertTrue(due(41, 30, quiet, False, 40))

    def test_wait_for_change(self):
        values = iter([60, 60, 45, 30, 30, 30])
        self.assertEqual(mmini.wait_for_change(lambda: next(values), 60, 2.0, settle=0.0), 30)
        started = time.monotonic()
        self.assertEqual(mmini.wait_for_change(lambda: 60, 60, 0.25), 60)
        self.assertLess(time.monotonic() - started, 1.0)

    def test_wait_for_change_gives_up_early_only_when_the_goal_moved_on(self):
        started = time.monotonic()
        self.assertEqual(mmini.wait_for_change(lambda: 60, 60, 5.0, stop=lambda: True, grace=0.3), 60)
        took = time.monotonic() - started
        self.assertGreaterEqual(took, 0.3)  # a step still on its way gets its grace
        self.assertLess(took, 1.5)
        started = time.monotonic()
        self.assertEqual(mmini.wait_for_change(lambda: 60, 60, 0.6, stop=lambda: False, grace=0.1), 60)
        self.assertGreaterEqual(time.monotonic() - started, 0.6)  # same goal: the full wait
        values = iter([45, 45])
        self.assertEqual(mmini.wait_for_change(lambda: next(values), 60, 5.0, settle=0.0, stop=lambda: True,
                                               grace=0.0), 45)  # a change is looked at first


class StateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = Path(self._tmp.name) / "state"
        self.addCleanup(self._tmp.cleanup)

    def test_atomic_write_and_read(self):
        mmini.write_atomic(self.state / "target", "t5\n")
        self.assertEqual(mmini.current_target(self.state), "t5")
        self.assertEqual([p.name for p in self.state.iterdir()], ["target"])
        self.assertEqual(mmini.read_text(self.state / "missing"), "")

    def test_last_round_trip(self):
        self.assertEqual(mmini.read_last(self.state), {})
        mmini.write_last({"space:a": "mmini/t5"}, self.state)
        self.assertEqual(mmini.read_last(self.state), {"space:a": "mmini/t5"})
        (self.state / "last.json").write_text("garbage")
        self.assertEqual(mmini.read_last(self.state), {})

    def test_remember_keeps_other_windows_entries(self):
        mmini.write_last({"space:a": "t1"}, self.state)
        self.assertEqual(mmini.remember("space:b", "t2", self.state), {"space:a": "t1", "space:b": "t2"})
        self.assertEqual(mmini.read_last(self.state), {"space:a": "t1", "space:b": "t2"})

    def test_panes(self):
        mmini.write_atomic(self.state / "panes", "side=A-1\ntabs=B-2\nview=C-3\n")
        self.assertEqual(mmini.read_panes(self.state), {"side": "A-1", "tabs": "B-2", "view": "C-3"})
        self.assertEqual(mmini.read_panes(self.state / "nope"), {})

    def test_sidebar_state_file_and_the_old_collapsed_file(self):
        read = mmini.read_sidebar_state
        self.assertEqual(read(self.state), "open")  # nothing yet
        mmini.write_atomic(self.state / "collapsed", "1\n")  # an older install, folded
        self.assertEqual(read(self.state), "strip")
        mmini.write_atomic(self.state / "collapsed", "0\n")
        self.assertEqual(read(self.state), "open")
        mmini.write_atomic(self.state / "collapsed", "1\n")
        for value in ("open", "strip", "hidden"):
            mmini.write_sidebar_state(value, self.state)
            self.assertEqual(read(self.state), value)  # once "sidebar" exists, "collapsed" is not read
        self.assertEqual((self.state / "sidebar").read_text(), "hidden\n")
        self.assertEqual((self.state / "collapsed").read_text(), "1\n")  # left as it was
        for junk in ("junk\n", "", "Hidden\n"):
            mmini.write_atomic(self.state / "sidebar", junk)
            self.assertEqual(read(self.state), "open", junk)  # junk is open, not the old file's strip

    def test_parse_sidebar_state(self):
        p = mmini.parse_sidebar_state
        self.assertEqual([p(None, "1"), p(None, "0"), p(None, ""), p(None, "x")], ["strip", "open", "open", "open"])
        self.assertEqual([p("hidden", "1"), p("strip", ""), p("open", "1"), p("", "1")],
                         ["hidden", "strip", "open", "open"])

    def test_sidebar_alive_and_only_its_own_pid_file_removed(self):
        self.state.mkdir(parents=True)
        self.assertFalse(mmini.sidebar_alive(self.state))  # no file
        for junk in ("", "junk", "0", "-1"):  # 0 and -1 would address process groups
            mmini.write_atomic(self.state / "sidebar.pid", junk + "\n")
            self.assertFalse(mmini.sidebar_alive(self.state), junk)
        mmini.write_atomic(self.state / "sidebar.pid", f"{os.getpid()}\n")
        self.assertTrue(mmini.sidebar_alive(self.state))
        dead = dead_pid()
        mmini.write_atomic(self.state / "sidebar.pid", f"{dead}\n")  # ended by a hangup: the file stayed
        self.assertFalse(mmini.sidebar_alive(self.state))
        mmini.remove_own_pid(self.state)
        self.assertTrue((self.state / "sidebar.pid").exists())  # another sidebar's file is never touched
        mmini.write_atomic(self.state / "sidebar.pid", f"{os.getpid()}\n")
        mmini.remove_own_pid(self.state)
        self.assertFalse((self.state / "sidebar.pid").exists())
        mmini.remove_own_pid(self.state)  # twice is fine

    def test_tab_engine_wanted(self):
        w = mmini.tab_engine_wanted
        self.assertFalse(w(True, 100.0, True))  # a live sidebar: never
        self.assertFalse(w(False, 0.0, False))  # a normal start: the sidebar is on its way
        self.assertFalse(w(False, mmini.ENGINE_GRACE - 0.1, False))
        self.assertTrue(w(False, mmini.ENGINE_GRACE, False))
        self.assertTrue(w(False, 0.0, True))  # hidden on purpose: at once
        self.assertEqual(mmini.ENGINE_GRACE, 3.0)

    def test_opening_verdict(self):
        v = mmini.opening_verdict
        self.assertEqual(v("T-1", "T-1", 1.0), "wait")
        self.assertEqual(v("T-1", "", 1.0), "wait")  # a panes file that went missing names no new tab bar
        self.assertEqual(v("T-1", "T-2", 1.0), "done")
        self.assertEqual(v("", "T-2", 0.0), "done")
        self.assertEqual(v("T-1", "T-1", mmini.OPEN_TIMEOUT - 0.01), "wait")
        self.assertEqual(v("T-1", "T-1", mmini.OPEN_TIMEOUT), "failed")
        self.assertEqual(v("T-1", "T-2", 99.0), "done")  # the new ids count even when they come late
        self.assertEqual(mmini.OPEN_TIMEOUT, 10.0)

    def test_snapshot_format_and_round_trip(self):
        spaces, _ = mmini.build_groups(mmini.parse(SAMPLE), "mmini")
        mmini.write_snapshot(spaces[2], self.state, now=1000.0)
        snap = mmini.read_snapshot(self.state, now=1001.0)
        self.assertEqual(sorted(snap), ["cwd", "group", "kind", "machine", "name", "server", "shown", "shown_title",
                                        "tabs", "title", "ts"])
        self.assertEqual((snap["server"], snap["shown"], snap["shown_title"]), ("mmini", "", "mmini"))
        self.assertEqual(snap["group"], "space:atlas")
        self.assertEqual((snap["name"], snap["title"]), ("atlas", "atlas"))  # no display name: the name
        self.assertEqual(snap["kind"], "space")
        self.assertEqual(snap["machine"], "mmini")
        self.assertEqual(snap["cwd"], "/Users/x/dev/atlas")
        self.assertEqual(snap["tabs"][0], {"address": "mmini/t5", "label": "atlas", "status": "idle",
                                           "agent": "claude-code", "cwd": "/Users/x/dev/atlas", "server": "mmini",
                                           "mark": ""})
        self.assertEqual([t["label"] for t in snap["tabs"]], ["atlas", "zz"])

    def test_snapshot_stale_missing_broken(self):
        self.assertIsNone(mmini.read_snapshot(self.state))
        mmini.write_snapshot(None, self.state, now=1000.0)
        self.assertIsNotNone(mmini.read_snapshot(self.state, now=1000.0 + 1))
        self.assertIsNone(mmini.read_snapshot(self.state, now=1000.0 + mmini.SNAPSHOT_MAX_AGE + 1))
        (self.state / "tabs.json").write_text("{broken")
        self.assertIsNone(mmini.read_snapshot(self.state, now=1000.0))
        (self.state / "tabs.json").write_text(json.dumps({"ts": "x", "tabs": []}))
        self.assertIsNone(mmini.read_snapshot(self.state, now=1000.0))
        (self.state / "tabs.json").write_text(json.dumps({"ts": 1000.0, "tabs": [1, {"address": "t1"}, {}]}))
        self.assertEqual(mmini.read_snapshot(self.state, now=1000.0)["tabs"], [{"address": "t1"}])

    def test_show_writes_target_and_bumps_gen(self):
        mmini.show("mmini/t5", self.state)
        first = (self.state / "gen").read_text()
        self.assertEqual(mmini.current_target(self.state), "mmini/t5")
        time.sleep(0.001)
        mmini.show("mmini/t6", self.state)
        self.assertNotEqual((self.state / "gen").read_text(), first)

    def test_show_again_bumps_when_nothing_is_attached(self):
        mmini.show("t5", self.state)
        first = (self.state / "gen").read_text()
        time.sleep(0.001)
        mmini.show("t5", self.state)  # the view is waiting (detached): it must attach again
        self.assertNotEqual((self.state / "gen").read_text(), first)

    def test_attach_pid_needs_pid_file_loop_and_command(self):
        # our own pid is a python process, not an attach: it must never be signalled
        mmini.write_atomic(self.state / "view.pid", f"{os.getpid()}\n")
        mmini.write_atomic(self.state / "view.loop", f"{os.getppid()}\n")
        self.assertEqual(mmini.attach_pid(self.state), 0)
        mmini.end_current_attach(self.state)  # would kill the test run if the check failed
        mmini.write_atomic(self.state / "view.pid", "garbage\n")
        self.assertEqual(mmini.attach_pid(self.state), 0)
        (self.state / "view.loop").unlink()
        self.assertEqual(mmini.attach_pid(self.state), 0)

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
        mmini.write_atomic(self.state / "view.pid", f"{proc.pid}\n")
        mmini.write_atomic(self.state / "view.loop", "1\n")  # another loop's attach: hands off
        self.assertEqual(mmini.attach_pid(self.state), 0)
        mmini.end_current_attach(self.state)
        self.assertIsNone(proc.poll())
        mmini.write_atomic(self.state / "view.loop", f"{os.getpid()}\n")
        self.assertEqual(mmini.attach_pid(self.state), proc.pid)
        mmini.write_atomic(self.state / "target", "t1\n")
        before = mtime_ns(self.state / "gen")
        mmini.show("t1", self.state)  # already attached to it: nothing is restarted
        self.assertEqual(mtime_ns(self.state / "gen"), before)
        self.assertIsNone(proc.poll())
        mmini.show("t2", self.state)
        self.assertEqual(proc.wait(timeout=5), -signal.SIGTERM)

    def test_attach_regex(self):
        for command in ("/Users/x/.local/bin/hc attach t5", "hc attach mmini/t5", "herdr-core attach t1",
                        "/bin/sh /tmp/x/hc attach t1"):
            self.assertTrue(mmini.ATTACH_RE.search(command), command)
        for command in ("/usr/bin/python3 mmini.py sidebar", "hc ls --json", "vim hcattach", "xhc attach t1",
                        "hc attachments"):
            self.assertFalse(mmini.ATTACH_RE.search(command), command)

    def test_new_shell_args_label_and_prefix(self):
        calls = []

        def fake(*args, **kw):
            calls.append(args)
            return json.dumps({"address": "t9"})

        self.assertEqual(mmini.new_shell("mmini", "/Users/x/dev/a", self.state, "a", fake), "mmini/t9")
        self.assertEqual(calls[-1], ("run", "--bg", "--json", "--no-parent", "--on", "mmini", "--cwd",
                                     "/Users/x/dev/a", "--label", "space=a"))
        self.assertEqual(mmini.new_shell(mmini.LOCAL, "", self.state, runner=fake), "t9")
        self.assertEqual(calls[-1], ("run", "--bg", "--json", "--no-parent"))
        self.assertEqual(mmini.new_shell("rig", "", self.state, runner=lambda *a, **k: '{"address": "rig/t3"}'),
                         "rig/t3")
        self.assertTrue((self.state / "poke").exists())
        for junk in ("{}", "[]", "null"):
            with self.assertRaises(ValueError):
                mmini.new_shell("mmini", "", self.state, runner=lambda *a, **k: junk)

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

        got = mmini.fetch_infos(["t1", "t2", "t3", "t4", "mmini/t5"], fake)
        self.assertEqual(got, {"t1": mmini.Info("s", "t0"), "t2": None, "t3": None, "t4": None,
                               "mmini/t5": mmini.Info("s", "mmini/t0")})
        self.assertEqual(mmini.fetch_infos([], fake), {})


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
    def test_ghostty_disabled_never_runs(self):
        os.environ["MMINI_GHOSTTY"] = "0"
        with mock.patch.object(mmini.subprocess, "Popen") as popen:
            mmini.ghostty('tell application "Ghostty" to quit')
            mmini.focus_view(True)
            mmini.autosize("sidebar")
            mmini.autosize("tabs")
        popen.assert_not_called()

    def test_ghostty_helper_never_raises(self):
        with mock.patch.dict(os.environ, {"MMINI_GHOSTTY": "1"}), \
                mock.patch.object(mmini.subprocess, "Popen", side_effect=OSError("no osascript")):
            mmini.ghostty("anything")

    def test_safe_id(self):
        self.assertEqual(mmini.safe_id('A-1"; do shell script "x'), "A-1doshellscriptx")

    def test_action_script_uses_panes_with_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            self.assertNotIn("whose id", mmini.action_script("goto_split:right", "view", state))
            mmini.write_atomic(state / "panes", "view=ID-9\n")
            script = mmini.action_script('resize_split:left,40"; quit', "view", state)
            self.assertIn('whose id is "ID-9"', script)
            self.assertIn("focused terminal", script)
            self.assertIn('"resize_split:left,40quit"', script)

    def test_focus_script(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            side = mmini.focus_script(True, state)
            self.assertLess(side.index("goto_split:right"), side.index("goto_split:down"))  # tab bar, then view
            tabs = mmini.focus_script(False, state)
            self.assertIn("goto_split:down", tabs)
            self.assertNotIn("goto_split:right", tabs)
            mmini.write_atomic(state / "panes", "view=V-1\n")
            script = mmini.focus_script(True, state)
            self.assertIn('focus (first terminal whose id is "V-1")', script)
            self.assertIn("on error", script)
            self.assertIn("goto_split:right", script)

    def test_zoom_script_focuses_the_view_then_zooms_it(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            mmini.write_atomic(state / "panes", "side=S-1\ntabs=T-1\nview=V-1\n")
            for from_side in (True, False):
                script = mmini.zoom_script(from_side, state)
                focus = script.index('focus (first terminal whose id is "V-1")')
                zoom = script.index('perform action "toggle_split_zoom" on (first terminal whose id is "V-1")')
                self.assertLess(focus, zoom)
                self.assertNotIn("S-1", script)
                self.assertNotIn("T-1", script)
                self.assertEqual(script.count("toggle_split_zoom"), 2)  # by id, else on the focused terminal
                self.assertEqual(script.count('tell application "Ghostty"'), script.count("end tell"))
            (state / "panes").unlink()
            script = mmini.zoom_script(True, state)  # no ids: by direction, then the focused terminal
            self.assertLess(script.index("goto_split:down"), script.index("toggle_split_zoom"))
            self.assertIn("delay 0.1", script)

    def test_zoom_without_ghostty_runs_nothing(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(mmini.subprocess, "Popen") as popen, \
                mock.patch.object(mmini, "attach_pid", return_value=4242):
            state = Path(d)
            mmini.write_atomic(state / "target", "t5\n")
            self.assertEqual(mmini.zoom_view(True, state), "")
            self.assertTrue((state / "zoom").exists())
        popen.assert_not_called()

    def test_wide_characters_count_two_columns(self):
        self.assertEqual([mmini.cell_width(c) for c in "a日🚀é́…●"], [1, 2, 2, 1, 0, 1, 1])
        self.assertEqual(mmini.text_width("日本語ab"), 8)
        self.assertEqual(mmini.fit_columns("日本語ab", 5), "日本")  # a wide character is never cut in half
        self.assertEqual(mmini.fit_columns("日本語ab", 7), "日本語a")
        self.assertEqual(mmini.fit_columns("🚀rocket", 3), "🚀r")
        self.assertEqual(mmini.fit_columns("abc", 2), "ab")
        self.assertEqual(mmini.fit_columns("日本", 0), "")
        self.assertEqual(mmini.fit_columns("日本", -1), "")
        self.assertEqual(mmini.clip("日本語プロジェクト", 7), "日本語…")
        self.assertEqual(mmini.clip("日本語", 6), "日本語")
        self.assertEqual(mmini.clip("日本語", 1), "")

    def test_glyph_and_clip(self):
        self.assertEqual(mmini.clip("abcdef", 4), "abc…")
        self.assertEqual(mmini.clip("abc", 4), "abc")
        self.assertEqual(mmini.clip("abc", 0), "")
        self.assertEqual(mmini.clip("abc", 1), "a")
        self.assertEqual(mmini.glyph("abc"), "abc")
        with mock.patch.object(mmini, "utf8_screen", return_value=False):
            self.assertEqual(mmini.glyph("› ● a │ é"), "> * a | ?")
        with mock.patch.object(mmini, "utf8_screen", return_value=True):
            self.assertEqual(mmini.glyph("› ●"), "› ●")

    def test_setup_locale_survives_an_unknown_locale(self):
        code = ("import mmini, locale; mmini.setup_locale(); "
                "print(locale.nl_langinfo(locale.CODESET), mmini.glyph('›') == '›')")
        for value in ("xx_YY.UTF-8", "C", "nonsense"):
            env = dict(os.environ, LANG=value, LC_ALL=value, PYTHONDONTWRITEBYTECODE="1")
            out = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stdout.split(), ["UTF-8", "True"], value)

    def test_describe_error(self):
        exc = subprocess.CalledProcessError(1, "hc", stderr="boom\nmore")
        self.assertEqual(mmini.describe_error(exc), "boom")
        real = ('{"error":{"hint":"check the program name and cwd","kind":"spawn_failed",'
                '"message":"cannot start \\"/bin/zsh\\": No such file or directory"}}\n')
        exc = subprocess.CalledProcessError(1, "hc", stderr=real)
        self.assertEqual(mmini.describe_error(exc), 'cannot start "/bin/zsh": No such file or directory')
        exc = subprocess.CalledProcessError(1, "hc", stderr='{"error":{"kind":"not_found"}}')
        self.assertEqual(mmini.describe_error(exc), "not_found")
        self.assertEqual(mmini.describe_error(subprocess.CalledProcessError(3, "hc", stderr="")), "hc exit 3")
        self.assertEqual(mmini.describe_error(subprocess.CalledProcessError(3, "hc", stderr="[1]")), "[1]")
        self.assertEqual(mmini.describe_error(subprocess.TimeoutExpired("hc", 5)), "hc did not answer")
        self.assertEqual(mmini.describe_error(FileNotFoundError()), "hc not found")
        self.assertEqual(mmini.describe_error(ValueError()), "ValueError")
        self.assertEqual(mmini.describe_error(ValueError("unexpected hc ls output")), "unexpected hc ls output")

    def test_env_int(self):
        with mock.patch.dict(os.environ, {"X_MMINI": "junk"}):
            self.assertEqual(mmini.env_int("X_MMINI", 30, 10, 200), 30)
        with mock.patch.dict(os.environ, {"X_MMINI": "500"}):
            self.assertEqual(mmini.env_int("X_MMINI", 30, 10, 200), 200)


class FakeScr:
    """Stands in for a curses window: records what is drawn where."""

    def __init__(self, height, width):
        self.height, self.width = height, width
        self.cells = {}

    def getmaxyx(self):
        return (self.height, self.width)

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
        return sorted({y for (y, _), (_, attr) in self.cells.items() if attr & mmini.curses.A_REVERSE})


def columns(text):
    """Screen columns of text as a terminal draws it, worked out apart from mmini: a wide character takes two."""
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
    """Answers `hc ls --json`, `hc get`, `hc run`, `hc label`, `hc exec`, `hc keep/kill/wait/rm` and `hc machine
    ls/rm` from a small table, the way herdr-core 0.1.21 answered them in an isolated core: keep on a finished
    terminal is "invalid_params", rm of a live one is "live", anything about a removed one "not_found", and a kill
    ends the children that die with their parent."""

    def __init__(self, terms, infos=None, machines=()):
        self.terms = list(terms)
        self.infos = dict(infos or {})
        self.machines = list(machines)
        self.finished = {}  # address -> the terminal, ended but not removed (hc ls leaves it out)
        self.calls = []
        self.fail = ""
        self.dirs = set()
        # `hc exec --json` of the keychain check and of the dev servers: (exit code, stderr) and DEV_SCRIPT's output
        self.keychain = (0, 'Keychain "/Users/x/Library/Keychains/login.keychain-db" no-timeout\n')
        self.lsof = ""

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
            return json.dumps({"labels": info.get("labels", {}), "parent": info.get("parent"),
                               "die_with_parent": info.get("dies", True)})
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
        if args[0] == "exec" and mmini.KEYCHAIN_SCRIPT in args:
            return exec_json(*self.keychain)
        if args[0] == "exec" and mmini.DEV_SCRIPT in args:
            return exec_json(0, "", self.lsof)
        if args[0] == "exec":
            return "/Users/x\n" + ("dir" if args[-1] in self.dirs else "none") + "\n"
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
        for target, value in ((mmini, {"run_hc": self.hc}), (mmini.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scr = FakeScr(24, 30)
        seen_done(self.state, self.hc.terms)
        self.side = mmini.Sidebar(self.scr, self.state, self.win)
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

    def test_first_group_becomes_current_and_snapshot_is_written(self):
        self.assertEqual(self.side.cur, "space:dev")
        self.assertEqual(mmini.read_text(self.state / "group"), "space:dev")
        snap = mmini.read_snapshot(self.win)
        self.assertEqual([t["label"] for t in snap["tabs"]], ["atlas", "tracker"])
        self.assertFalse((self.state / "target").exists())  # window files live in the window folder

    def test_draw_sections_markers_and_cursor(self):
        self.side.draw()
        lines = self.scr.lines()
        self.assertEqual(lines[0], " spaces")
        self.assertEqual(lines[1], mmini.glyph("›● dev"))
        self.assertEqual(lines[2], mmini.glyph(" ● other"))
        self.assertEqual(lines[3:7], [" + new space", "", "", ""])  # the servers section is hidden by default
        self.assertEqual(self.scr.reversed_rows(), [1])
        self.assertIn(" agents", lines[-7][:8])
        self.assertEqual(lines[-6], mmini.glyph(" dev · 2"))
        self.assertTrue(lines[-5].startswith(mmini.glyph("  ● atlas")) and lines[-5].endswith("idle"))
        self.assertEqual(lines[-3], mmini.glyph(" other · 1"))
        self.assertEqual(lines[-1], fold_line("open"))  # the arrow on the last line, a dim "?" at its end
        self.assertEqual(lines[-9:-7], ["", "─" * 29])  # no key hints above the rule
        self.assertNotIn("rig", " ".join(lines))

    def test_enter_on_group_shows_first_then_remembered(self):
        self.key("j", 10)
        self.assertEqual(self.side.cur, "space:other")
        self.assertEqual(mmini.current_target(self.win), "t3")
        mmini.show("t4", self.win)  # the tab bar picks another tab
        self.side.sync()
        self.assertEqual(mmini.read_last(self.state)["space:other"], "t4")
        self.key("k", 10)
        self.assertEqual(mmini.current_target(self.win), "t1")
        self.key("j", 10)
        self.assertEqual(mmini.current_target(self.win), "t4")  # remembered

    def test_enter_on_agent_shows_it_and_marks_it(self):
        self.key(*"jjjj", 10)  # dev, other, + new space, atlas, tracker (servers hidden: the default)
        self.assertEqual(mmini.current_target(self.win), "t2")
        self.assertEqual(self.side.cur, "space:dev")
        marked = [line for line in self.scr.lines() if line.startswith(mmini.glyph("›"))]
        self.assertEqual(len(marked), 2)  # the current group and the shown agent
        self.assertTrue(any("tracker" in line for line in marked))

    def test_start_up_auto_open_does_not_touch_the_focus(self):
        with mock.patch.object(mmini, "focus_view") as focus:
            self.side.open_group(self.side.cur, focus=False)
            focus.assert_not_called()
            self.assertEqual(mmini.current_target(self.win), "t1")
            self.side.open_group(self.side.cur)
            focus.assert_called_once()

    def test_click_uses_the_item_that_was_drawn(self):
        self.side.draw()
        row = next(y for y, item in self.side.rows.items() if item.address == "t3")
        self.hc.terms = [t for t in self.hc.terms if t["address"] != "t1"]  # the list changes after the draw
        self.side.refresh_once()
        with pressed(5, row, 1):
            self.side.handle_key(mmini.curses.KEY_MOUSE)
        self.assertEqual(mmini.current_target(self.win), "t3")

    def test_click_on_an_agent_that_ended_shows_nothing(self):
        self.side.draw()
        row = next(y for y, item in self.side.rows.items() if item.address == "t3")
        self.hc.terms = [t for t in self.hc.terms if t["address"] != "t3"]
        self.side.refresh_once()
        with pressed(5, row, 1):
            self.side.handle_key(mmini.curses.KEY_MOUSE)
        self.assertEqual(mmini.current_target(self.win), "")
        self.assertTrue(self.side.notice.current())

    def test_n_starts_a_labelled_shell_in_the_cursor_space(self):
        self.key("j", "n")
        run = [c for c in self.hc.calls if c[0] == "run"][-1]
        self.assertEqual(run, ("run", "--bg", "--json", "--no-parent", "--cwd", "/Users/x/dev/other",
                               "--label", "space=other"))
        self.assertEqual(self.side.cur, "space:other")
        self.assertEqual(mmini.current_target(self.win), "t54")

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
        self.assertEqual(self.side.cursor, mmini.Item("group", "space:fresh", ""))

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
        self.assertEqual(self.side.cursor_item(), mmini.Item("agent", "space:other", "t1"))  # the cursor follows it
        self.key("m", 10)  # empty input cancels
        self.assertEqual(len([c for c in self.hc.calls if c[0] == "label"]), 1)

    def test_tabs_follow_the_shown_terminal_into_its_new_space(self):
        self.key(*"jjj", 10)  # show atlas (space dev)
        self.assertEqual(self.side.cur, "space:dev")
        self.key("m")
        self.type("other")
        self.assertEqual(self.side.cur, "space:other")
        self.assertIn("atlas", [t["label"] for t in mmini.read_snapshot(self.win)["tabs"]])

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

        with mock.patch.object(mmini, "run_hc", flaky):
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
            with mock.patch.object(mmini, "run_hc", lambda *a, **k: junk):
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
        runs = []

        def fake(mode, win, goal):
            runs.append(mode)
            return 40, goal()  # as if Ghostty's 10% limit stopped the loop at 40 columns

        def settle():
            self.side.resized = time.monotonic() - 2 * mmini.REFIT_QUIET  # a resize, quiet since
            self.side.refit()
            if self.side.sizer is not None:
                self.side.sizer.join(5)

        self.scr.width = 75
        settle()
        self.assertEqual(runs, [])  # MMINI_GHOSTTY=0: never
        with mock.patch.object(mmini, "autosize", fake), mock.patch.object(mmini, "autosize_enabled", lambda: True):
            self.side.resized = 0.0
            self.side.refit()
            self.assertEqual(runs, [])  # no resize seen
            self.side.resized = time.monotonic()
            self.side.refit()
            self.assertEqual(runs, [])  # the size is still changing
            self.assertTrue(self.side.resized)
            settle()
            self.assertEqual(runs, ["sidebar"])
            self.assertEqual((self.side.resized, self.side.sized_at), (0.0, 40))
            self.scr.width = 40  # the loop's own steps resized the pane: no second loop from where it ended
            settle()
            self.scr.width = mmini.WIDTH + 1  # on target
            settle()
            self.assertEqual(len(runs), 1)
            self.scr.width = 60  # the window changed again
            settle()
            self.assertEqual(len(runs), 2)

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
    def fake_sizing(self, ends_at):
        """autosize stand-in with resizing switched on: records each loop's goal, ends at ends_at(goal)."""
        goals = []

        def fake(mode, win, goal):
            goals.append(goal())
            return ends_at(goals[-1]), goal()

        for target, value in ((mmini, {"autosize": fake, "autosize_enabled": lambda: True}),):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return goals

    def settle(self):
        """A size change some time ago, then the loop's refit; waits for a loop it started."""
        self.side.resized = time.monotonic() - 2 * mmini.REFIT_QUIET
        self.side.refit()
        self.join()

    def join(self):
        if self.side.sizer is not None:
            self.side.sizer.join(5)

    def group_line(self, key):
        return next(y for y, item in self.side.rows.items() if item == mmini.Item("group", key, ""))

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
                        self.assertEqual(lines[-2], mmini.glyph(mmini.open_label(29)), case)
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
                self.assertEqual(lines[-1], mmini.glyph(mmini.fold_label("strip", width - 1)), case)
                self.assertEqual(lines[-2], mmini.glyph(mmini.open_label(width - 1)), case)
                self.assertEqual(lines[0], "spaces"[:width - 1], case)  # the title, cut at the edge
                dev = lines[self.group_line("space:dev")]
                self.assertEqual(dev, mmini.glyph("›●dev")[:width - 1], case)  # marker, dot, the name as it fits
                other = lines[self.group_line("space:other")]
                self.assertEqual(other, mmini.glyph(" ●other")[:width - 1], case)
                self.assertTrue(self.scr.reversed_rows(), case)
                if height == 24:
                    atlas = next(y for y, item in self.side.rows.items() if item.address == "t1")
                    self.assertEqual(lines[atlas], mmini.glyph("›●atlas")[:width - 1], case)  # no status word
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
        mmini.write_atomic(self.win / "target", "t2\n")  # the wide agent carries the marker
        for (mode, widths), servers in itertools.product((("strip", range(3, 13)), ("open", (12, 20, 30))),
                                                         (False, True)):
            self.side.mode = mode
            mmini.write_servers_shown(servers, self.state)
            for width in widths:
                for height in (9, 12, 24):
                    scr = WideScr(height, width)
                    self.side.s = mmini.Screen(scr)
                    self.side.draw()
                    lines = scr.lines()
                    case = (mode, servers, width, height, lines)
                    self.assertEqual(scr.spilled, [], case)
                    self.assertTrue(all(columns(line) <= width - 1 for line in lines), case)
                    plan = mmini.plan_sidebar(*self.side.groups(), self.side.body_height, self.side.cursor_pos,
                                              mode == "strip", self.side.servers_shown())
                    for y, row in plan:
                        if row.kind == "blank":
                            self.assertEqual(lines[y], "", case)  # the line before "servers" stays empty
        self.side.mode = "open"
        scr = WideScr(24, 30)
        self.side.s = mmini.Screen(scr)
        self.side.draw()
        agent = next(line for line in scr.lines() if "working" in line)
        self.assertIn("…", agent)  # cut by columns, before the status word, with the mark of the cut
        self.assertTrue(agent.endswith(" working"), agent)

    def test_compact_strip_keeps_the_cursor_enter_and_clicks(self):
        self.key("c")
        self.scr.width = 8
        self.side.draw()
        self.key("j", 10)
        self.assertEqual(self.side.cur, "space:other")
        self.assertEqual(mmini.current_target(self.win), "t3")
        row = next(y for y, item in self.side.rows.items() if item.address == "t2")
        with pressed(1, row, 1):
            self.key(mmini.curses.KEY_MOUSE)
        self.assertEqual(mmini.current_target(self.win), "t2")
        self.assertEqual(self.side.cur, "space:dev")
        self.key("n")  # n works folded too
        self.assertEqual([c for c in self.hc.calls if c[0] == "run"][-1][-2:], ("--label", "space=dev"))

    def test_c_steps_open_strip_hidden_and_the_state_is_kept(self):
        mmini.write_atomic(self.win / "sidebar.pid", f"{os.getpid()}\n")  # as run() writes it
        mmini.write_atomic(self.win / "panes", "side=S-1\ntabs=T-1\nview=V-1\n")
        self.assertEqual(self.side.mode, "open")
        self.assertEqual(self.scr.line(23), fold_line("open"))
        with mock.patch.object(mmini, "ghostty") as run:
            self.assertTrue(self.side.on_key(ord("c")))
            self.assertEqual(self.side.mode, "strip")
            self.assertEqual(mmini.read_text(self.state / "sidebar"), "strip")  # shared by all windows
            self.assertFalse((self.win / "sidebar").exists())
            again = mmini.Sidebar(FakeScr(24, 30), self.state, self.win)  # the next start opens folded
            self.assertEqual((again.mode, again.width_goal()), ("strip", mmini.NARROW))
            self.side.draw()
            self.assertEqual(self.scr.line(23), mmini.glyph(" ‹ hide"))
            self.assertEqual(self.scr.line(22), mmini.glyph(" › open"))
            run.assert_not_called()
            self.assertFalse(self.side.on_key(ord("C")))  # hidden: the loop ends, so does the program
        self.assertEqual(mmini.read_sidebar_state(self.state), "hidden")
        self.assertFalse((self.win / "sidebar.pid").exists())
        self.assertTrue((self.win / "tabs.json").exists())  # the tab bar draws it until its own engine writes
        script = run.call_args[0][0]
        self.assertEqual(run.call_args[1], {"detach": True})  # it outlives the pane that is about to close
        self.assertIn('focus (first terminal whose id is "V-1")', script)
        self.assertNotIn("S-1", script)

    def test_q_hides_the_sidebar_from_either_state(self):
        for before in ("open", "strip"):
            self.side.mode = before
            mmini.write_sidebar_state(before, self.state)
            mmini.write_atomic(self.win / "sidebar.pid", f"{os.getpid()}\n")
            with mock.patch.object(mmini, "ghostty") as run:
                self.assertFalse(self.side.on_key(ord("q")), before)
            self.assertEqual(mmini.read_sidebar_state(self.state), "hidden", before)
            self.assertFalse((self.win / "sidebar.pid").exists(), before)
            run.assert_called_once()

    def test_hide_never_removes_another_sidebars_pid_file(self):
        mmini.write_atomic(self.win / "sidebar.pid", "1\n")
        self.assertFalse(self.side.on_key(ord("q")))
        self.assertEqual(mmini.read_text(self.win / "sidebar.pid"), "1")

    def test_clicks_on_the_two_arrow_lines(self):
        self.side.draw()
        self.assertEqual((self.side.arrow_y, self.side.open_y), (23, -1))
        with pressed(5, 23, 1):
            self.assertTrue(self.side.on_key(mmini.curses.KEY_MOUSE))  # "‹ fold"
        self.assertEqual(self.side.mode, "strip")
        self.side.draw()
        self.assertEqual((self.side.arrow_y, self.side.open_y), (23, 22))
        self.side.mouse_quiet = 0.0  # past the double-click guard
        with pressed(0, 22, 1):
            self.assertTrue(self.side.on_key(mmini.curses.KEY_MOUSE))  # "› open"
        self.assertEqual((self.side.mode, mmini.read_sidebar_state(self.state)), ("open", "open"))
        self.side.draw()
        self.assertEqual(self.side.open_y, -1)  # no "›" line in the open sidebar: line 22 is a row again
        self.assertIn(22, self.side.rows)
        self.side.mouse_quiet = 0.0
        with pressed(9, 23, 1):
            self.side.on_key(mmini.curses.KEY_MOUSE)
        self.side.draw()
        self.side.mouse_quiet = 0.0
        with pressed(9, 23, 1), mock.patch.object(mmini, "ghostty"):
            self.assertFalse(self.side.on_key(mmini.curses.KEY_MOUSE))  # "‹ hide"
        self.assertEqual(mmini.read_sidebar_state(self.state), "hidden")
        self.assertEqual(mmini.current_target(self.win), "")  # a click on an arrow line opens nothing

    def test_o_opens_the_strip_and_does_nothing_when_open(self):
        self.key("o")
        self.assertEqual(self.side.mode, "open")
        self.assertFalse((self.state / "sidebar").exists())  # nothing changed, nothing written
        self.key("c", "O")
        self.assertEqual((self.side.mode, mmini.read_sidebar_state(self.state)), ("open", "open"))

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
                        self.assertEqual(lines[-1], mmini.glyph(mmini.fold_label("strip", width - 1)), case)
                        self.assertEqual(mmini.sidebar_hit(height - 1, self.side.arrow_y, self.side.open_y,
                                                           self.side.rows), ("step", None), case)
                    else:
                        self.assertEqual(self.side.arrow_y, -1, case)
                    if height >= 3:  # then "› open"
                        self.assertEqual(self.side.open_y, height - 2, case)
                        self.assertEqual(lines[-2], mmini.glyph(mmini.open_label(width - 1)), case)
                        self.assertEqual(mmini.sidebar_hit(height - 2, self.side.arrow_y, self.side.open_y,
                                                           self.side.rows), ("open", None), case)
                    else:
                        self.assertEqual(self.side.open_y, -1, case)
                    self.assertFalse({self.side.arrow_y, self.side.open_y} & set(self.side.rows), case)

    def test_folding_without_ghostty_changes_only_the_layout(self):
        with mock.patch.object(mmini, "autosize") as sizing:
            self.key("c", "o", "c")
            self.side.refit()
        sizing.assert_not_called()
        self.assertEqual(self.side.mode, "strip")

    def test_toggle_sizes_the_pane_for_the_new_mode(self):
        goals = self.fake_sizing(lambda goal: goal)
        self.key("c")
        self.join()
        self.assertEqual(goals, [mmini.NARROW])
        self.key("o")
        self.join()
        self.assertEqual(goals, [mmini.NARROW, mmini.WIDTH])
        self.assertEqual((self.side.sized_at, self.side.aimed), (mmini.WIDTH, mmini.WIDTH))
        self.side.refit()
        self.join()
        self.assertEqual(len(goals), 2)  # nothing new to do

    def test_toggle_while_a_loop_runs_reaches_the_new_mode(self):
        goals = self.fake_sizing(lambda goal: goal)
        busy = threading.Event()
        self.side.sizer = threading.Thread(target=busy.wait, daemon=True)  # a loop that is still running
        self.side.sizer.start()
        self.key("c")
        self.assertEqual(goals, [])  # not a second loop beside the first
        self.assertNotEqual(self.side.aimed, self.side.width_goal())
        busy.set()
        self.join()
        self.side.refit()  # the loop ended on the old goal: the next round starts one for the folded strip
        self.join()
        self.assertEqual(goals, [mmini.NARROW])

    def test_refit_in_the_folded_strip_stops_at_the_limit(self):
        limit = {"cols": 12}  # a tenth of a 120-column window
        goals = self.fake_sizing(lambda goal: max(goal, limit["cols"]))
        self.key("c")
        self.join()
        self.assertEqual((goals, self.side.sized_at), ([mmini.NARROW], 12))
        self.scr.width = 12  # where the loop ended: its own steps changed the size, nothing new
        self.settle()
        self.settle()
        self.assertEqual(len(goals), 1)
        self.scr.width, limit["cols"] = 20, 20  # the window grew: the strip grew with it
        self.settle()
        self.assertEqual(goals, [mmini.NARROW, mmini.NARROW])  # aims at the strip, not MMINI_WIDTH
        self.settle()  # ended at 20, the new limit: no chain
        self.assertEqual(len(goals), 2)
        self.scr.width = mmini.NARROW + 1  # a small window: the strip is on its goal (far from MMINI_WIDTH)
        self.settle()
        self.assertEqual(len(goals), 2)
        self.key("o")  # open: back to MMINI_WIDTH
        self.join()
        self.assertEqual(goals[-1], mmini.WIDTH)

    def test_a_loop_stopped_by_a_size_change_from_outside_is_looked_at_again(self):
        ends = [0, 14]  # the window grew during the step at the limit (no limit found); the next loop finds it
        goals = self.fake_sizing(lambda goal: ends.pop(0) if ends else 14)
        self.key("c")
        self.join()
        self.assertEqual((goals, self.side.sized_at), ([mmini.NARROW], 0))
        self.scr.width = 14  # the strip grew with the window
        self.settle()
        self.assertEqual((goals, self.side.sized_at), ([mmini.NARROW, mmini.NARROW], 14))
        self.settle()
        self.settle()
        self.assertEqual(len(goals), 2)  # at the new limit: no chain

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
        self.assertEqual(mmini.read_sidebar_state(self.state), "open")

    def test_a_size_change_is_no_key(self):
        self.side.notice.say("new: cannot start")
        self.side.on_key(mmini.curses.KEY_RESIZE)
        self.assertEqual(self.side.notice.current(), "new: cannot start")
        self.assertTrue(self.side.resized)

    # zoom ------------------------------------------------------------------------------------------------------
    def test_z_without_a_shown_terminal_only_says_so(self):
        with mock.patch.object(mmini, "ghostty") as run:
            self.key("z")
            self.assertEqual(self.side.notice.current(), "z: nothing shown")
            mmini.write_atomic(self.win / "target", "t1\n")  # a target, but the view is not attached
            self.key("z")
            self.assertEqual(self.side.notice.current(), "z: nothing shown")
        run.assert_not_called()
        self.assertFalse((self.win / "zoom").exists())

    def test_z_zooms_the_view_and_holds_the_refit_until_the_next_key(self):
        goals = self.fake_sizing(lambda goal: goal)
        mmini.write_atomic(self.win / "panes", "side=S-1\ntabs=T-1\nview=V-1\n")
        self.key(*"jjj", 10)
        with mock.patch.object(mmini, "ghostty") as run, mock.patch.object(mmini, "attach_pid", return_value=4242):
            self.key("z")
        script = run.call_args[0][0]
        self.assertEqual(run.call_count, 1)
        self.assertLess(script.index('focus (first terminal whose id is "V-1")'),
                        script.index('perform action "toggle_split_zoom" on (first terminal whose id is "V-1")'))
        self.assertEqual(self.side.notice.current(), "")
        self.assertTrue(self.side.zoom_held())
        self.scr.width = 75  # the window changed while zoomed
        self.side.on_key(mmini.curses.KEY_RESIZE)  # a size change does not show the zoom is over
        self.settle()
        self.side.aimed = None  # also a loop the zoom stopped is not started again
        self.side.refit()
        self.join()
        self.assertEqual(goals, [])
        self.key("k")  # a key in the sidebar: it can be seen again
        self.assertFalse(self.side.zoom_held())
        self.settle()
        self.assertEqual(goals, [mmini.WIDTH])

    def test_a_zoom_from_the_tab_bar_holds_the_refit_too(self):
        goals = self.fake_sizing(lambda goal: goal)
        mmini.mark_zoom(self.win)
        self.scr.width = 75
        self.settle()
        self.assertEqual(goals, [])
        self.key("j")
        self.settle()
        self.assertEqual(goals, [mmini.WIDTH])

    # start -----------------------------------------------------------------------------------------------------
    def start_with(self, terms, saved=""):
        self.hc.terms = list(terms)
        state = Path(tempfile.mkdtemp(dir=self._tmp.name))  # an empty state folder for each start
        if saved:
            mmini.write_atomic(state / "group", saved + "\n")
        side = mmini.Sidebar(FakeScr(24, 30), state, state / "w-2")
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
            mmini.write_atomic(side.win / "target", "t2\n")
            calls = []
            with mock.patch.object(mmini, "attach_pid", return_value=4242 if attached else 0), \
                    mock.patch.object(mmini, "show", lambda address, win, title=None: calls.append((address,))):
                side.begin(True)
            self.assertEqual((side.cur, calls), (cur, shown), attached)
            self.assertEqual(mmini.read_text(side.state / "group"), cur)

    def test_poke_during_the_listing_is_not_lost(self):
        order = []
        real = self.side.refresh_once

        def slow(full=False, also=()):
            order.append("refresh")
            if len(order) == 1:
                mmini.write_atomic(self.win / "poke", "x\n")  # a terminal is created while hc ls runs
            if len(order) == 2:
                raise SystemExit  # end the endless loop of this test
            real(full, also)

        self.side.refresh_once = slow
        started = time.monotonic()
        with self.assertRaises(SystemExit):
            self.side.refresh_forever()
        self.assertLess(time.monotonic() - started, mmini.REFRESH_SECONDS / 2)


class TabBarLogicTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.win = Path(self._tmp.name)
        self.state = self.win / "shared"
        patcher = mock.patch.object(mmini.curses, "color_pair", lambda n: n << 8)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.scr = FakeScr(5, 40)
        self.bar = mmini.TabBar(self.scr, self.win, self.state)
        self.addCleanup(self.bar.stop_engine)
        spaces, _ = mmini.build_groups(mmini.parse(ls(
            term("t1", "/Users/x/dev/app", "claude-code", "alpha", "idle"), term("t2", name="beta"),
            term("t3", name="gamma"), term("t4", name="delta"), term("t5", name="omega"))), "mmini")
        mmini.write_snapshot(spaces[0], self.win)
        self.snap = mmini.read_snapshot(self.win)

    def test_waiting_without_a_sidebar(self):
        self.bar.draw(None, "")
        self.assertIn("waiting for the sidebar", self.scr.line(0))
        self.bar.alone = True  # no sidebar: its own engine is still loading
        self.bar.draw(None, "")
        self.assertEqual(self.scr.line(0), mmini.glyph("› loading…"))
        self.assertEqual(mmini.hit_test(self.bar.layout, 0, 0), ("open", -1))  # "›" works before the tabs come

    # without a sidebar -----------------------------------------------------------------------------------------
    def test_no_opener_while_a_sidebar_runs(self):
        mmini.write_atomic(self.win / "sidebar.pid", f"{os.getpid()}\n")
        mmini.write_atomic(self.win / "panes", "side=S-1\ntabs=T-1\nview=V-1\n")
        self.bar.watch_sidebar(100.0)
        self.assertFalse(self.bar.alone)
        self.assertIsNone(self.bar.engine)
        self.bar.draw(self.snap, "t1")
        self.assertEqual(self.scr.line(0), mmini.glyph(" ● alpha │ ○ beta │ ○ delta │ ○ gamma"))
        self.assertEqual(mmini.hit_test(self.bar.layout, 0, 0), ("tab", 0))
        self.assertTrue(self.scr.line(4).endswith(mmini.glyph("←→ switch  z zoom  ⌘⇧↵ back")))
        with mock.patch.object(mmini, "ghostty") as run:
            for key in (ord("c"), ord("o")):
                self.bar.on_key(key, self.snap, "t1")  # the sidebar's keys: nothing here
        run.assert_not_called()
        self.assertFalse((self.state / "sidebar").exists())
        self.assertIsNone(self.bar.opening)

    def test_opener_without_a_sidebar(self):
        self.bar.alone = True
        self.bar.draw(self.snap, "t1")
        lines = self.scr.lines()
        self.assertEqual(lines[0], mmini.glyph("› ● alpha │ ○ beta │ ○ delta │ ○ gamma"))
        self.assertEqual(lines[1], mmini.glyph("  ○ omega │ +"))
        self.assertEqual(lines[2], mmini.glyph("  t1 · ~/dev/app · claude-code · idle"))  # the info line
        self.assertTrue(lines[4].startswith("  app"))
        self.assertTrue(lines[4].endswith(mmini.glyph("c sidebar  z zoom  ⌘⇧↵ back")))
        self.assertEqual(self.scr.cells[(0, 0)], ("›", mmini.curses.A_BOLD))
        hit = mmini.hit_test
        self.assertEqual(hit(self.bar.layout, 0, 0), ("open", -1))
        self.assertEqual(hit(self.bar.layout, 1, 0), ("tab", 0))
        self.assertEqual(hit(self.bar.layout, 2, 1), ("tab", 4))
        self.assertIsNone(hit(self.bar.layout, 0, 1))
        with mock.patch.object(mmini, "read_click", return_value=(3, 1)):  # the tabs still switch
            self.bar.on_key(mmini.curses.KEY_MOUSE, self.snap, "t1")
        self.assertEqual(mmini.current_target(self.win), "t5")

    def test_a_click_on_the_opener_rebuilds_and_the_old_bar_ends_on_the_new_ids(self):
        mmini.write_atomic(self.win / "panes", "side=S-1\ntabs=T-1\nview=V-1\n")
        mmini.write_sidebar_state("hidden", self.state)
        self.bar.alone = True
        self.bar.draw(self.snap, "t1")
        with mock.patch.object(mmini, "ghostty") as run, mock.patch.object(mmini, "read_click", return_value=(0, 0)):
            self.bar.on_key(mmini.curses.KEY_MOUSE, self.snap, "t1")
            self.assertEqual(mmini.read_sidebar_state(self.state), "open")  # the new sidebar starts open
            self.bar.on_key(mmini.curses.KEY_MOUSE, self.snap, "t1")  # a double click: one rebuild
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args[0][0],
                         mmini.rebuild_script("V-1", self.win, mmini.BASE, mmini.mmini_env(os.environ)))
        self.assertEqual(run.call_args[1], {"detach": True})  # it outlives this tab bar
        self.bar.on_key(ord("h"), self.snap, "t1")  # any key clears a notice; this line stays while it waits
        self.bar.draw(self.snap, "t1")
        self.assertEqual(self.scr.line(4), mmini.glyph("  opening the sidebar…"))
        self.assertEqual(self.scr.cells[(4, 2)][1], mmini.curses.A_DIM)  # not red: nothing went wrong
        start = self.bar.opening[0]
        self.assertFalse(self.bar.check_opening(start + 1))  # no new ids yet: this tab bar stays
        mmini.write_atomic(self.win / "panes", "side=S-2\ntabs=T-1\nview=V-1\n")
        self.assertFalse(self.bar.check_opening(start + 2))  # only a new tab bar counts
        mmini.write_atomic(self.win / "panes", "side=S-2\ntabs=T-2\nview=V-1\n")
        self.assertTrue(self.bar.check_opening(start + 3))  # the new one is there: this one ends
        self.assertEqual(mmini.read_sidebar_state(self.state), "open")

    def test_c_opens_too_and_a_rebuild_that_never_arrives_gives_up_after_ten_seconds(self):
        """With MMINI_GHOSTTY=0 nothing runs, as when the script fails: the state goes back to hidden."""
        mmini.write_atomic(self.win / "panes", "side=S-1\ntabs=T-1\nview=V-1\n")
        mmini.write_sidebar_state("hidden", self.state)
        self.bar.alone = True
        with mock.patch.object(mmini.subprocess, "Popen") as popen:
            self.bar.on_key(ord("c"), self.snap, "t1")
        popen.assert_not_called()
        start = self.bar.opening[0]
        self.assertEqual(mmini.read_sidebar_state(self.state), "open")
        self.assertFalse(self.bar.check_opening(start + mmini.OPEN_TIMEOUT - 0.1))
        self.assertEqual(mmini.read_sidebar_state(self.state), "open")
        # (+0.01: start + 10 - start can come out a hair under 10 for a large clock value)
        self.assertFalse(self.bar.check_opening(start + mmini.OPEN_TIMEOUT + 0.01))  # it stays
        self.assertEqual(mmini.read_sidebar_state(self.state), "hidden")
        self.assertEqual(self.bar.notice.current(), "could not open the sidebar")
        self.assertTrue(self.bar.notice.bad)
        self.assertIsNone(self.bar.opening)
        with mock.patch.object(mmini, "ghostty") as run:
            self.bar.on_key(ord("o"), self.snap, "t1")  # a new try
        run.assert_called_once()

    def test_a_sidebar_that_did_start_keeps_the_state_open_when_the_rebuild_gives_up(self):
        mmini.write_atomic(self.win / "panes", "side=S-1\ntabs=T-1\nview=V-1\n")
        self.bar.alone = True
        with mock.patch.object(mmini, "ghostty"):
            self.bar.on_key(ord("c"), self.snap, "t1")
        mmini.write_atomic(self.win / "sidebar.pid", f"{os.getpid()}\n")  # the first split worked, the second not
        self.assertFalse(self.bar.check_opening(self.bar.opening[0] + mmini.OPEN_TIMEOUT + 0.01))
        self.assertEqual(mmini.read_sidebar_state(self.state), "open")  # it is on screen
        self.assertEqual(self.bar.notice.current(), "could not open the sidebar")

    def test_without_the_views_id_nothing_is_split(self):
        self.bar.alone = True
        mmini.write_sidebar_state("hidden", self.state)
        with mock.patch.object(mmini, "ghostty") as run:
            self.bar.on_key(ord("c"), self.snap, "t1")
            mmini.write_atomic(self.win / "panes", "side=S-1\ntabs=T-1\nview=\"; \n")  # nothing usable left
            self.bar.on_key(ord("c"), self.snap, "t1")
        run.assert_not_called()
        self.assertEqual(self.bar.notice.current(), "could not open the sidebar")
        self.assertEqual(mmini.read_sidebar_state(self.state), "hidden")
        self.assertIsNone(self.bar.opening)

    def test_keys_without_a_snapshot(self):
        self.bar.alone = True
        mmini.write_atomic(self.win / "panes", "side=S-1\ntabs=T-1\nview=V-1\n")
        for key in (ord("h"), ord("l"), 10):
            self.bar.on_key(key, None, "")  # still loading: nothing to switch, nothing breaks
        self.assertEqual(mmini.current_target(self.win), "")
        with mock.patch.object(mmini, "ghostty") as run:
            self.bar.on_key(ord("c"), None, "")
        self.assertIn("direction left", run.call_args[0][0])

    def test_rows_wrap_info_and_hints(self):
        self.bar.draw(self.snap, "t1")
        lines = self.scr.lines()
        self.assertEqual(lines[0], mmini.glyph(" ● alpha │ ○ beta │ ○ delta │ ○ gamma"))
        self.assertEqual(lines[1], mmini.glyph(" ○ omega │ +"))
        self.assertEqual(lines[2], mmini.glyph(" t1 · ~/dev/app · claude-code · idle"))
        self.assertTrue(lines[4].startswith(" app"))
        self.assertTrue(lines[4].endswith(mmini.glyph("←→ switch  z zoom  ⌘⇧↵ back")))  # the longest that fits
        self.scr.width = 80
        self.bar.draw(self.snap, "t1")
        self.assertTrue(self.scr.line(4).endswith(mmini.glyph(mmini.TAB_HINTS[0])))
        reversed_cells = [x for (y, x), (_, attr) in self.scr.cells.items() if attr & mmini.curses.A_REVERSE]
        self.assertEqual((min(reversed_cells), max(reversed_cells)), (0, 8))  # the shown tab only

    def test_one_and_two_row_panes(self):
        self.scr.height = 1
        self.bar.draw(self.snap, "t3")
        self.assertIn("gamma", self.scr.line(0))  # scrolled to the shown tab
        self.scr.height = 2
        self.bar.draw(self.snap, "t1")
        self.assertIn("alpha", self.scr.line(0))
        self.assertTrue(self.scr.line(1).startswith(" app"))
        self.scr.height = 0
        self.bar.draw(self.snap, "t1")

    def test_click_on_a_wrapped_tab_and_on_plus(self):
        self.bar.draw(self.snap, "t1")
        with mock.patch.object(mmini, "read_click", return_value=(3, 1)):
            self.bar.handle_key(mmini.curses.KEY_MOUSE, self.snap, "t1")
        self.assertEqual(mmini.current_target(self.win), "t5")  # omega, first tab of the second row
        calls = []

        def fake(*args, **kw):
            calls.append(args)
            return '{"address": "t77"}'

        with mock.patch.object(mmini, "read_click", return_value=(12, 1)), mock.patch.object(mmini, "run_hc", fake):
            self.bar.handle_key(mmini.curses.KEY_MOUSE, self.snap, "t5")
            self.bar.handle_key(mmini.curses.KEY_MOUSE, self.snap, "t5")  # a double click
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][-4:], ("--cwd", "/Users/x/dev/app", "--label", "space=app"))
        self.assertEqual(mmini.current_target(self.win), "t77")

    def test_left_right_switch_and_stop_at_the_ends(self):
        self.bar.step(self.snap, "t1", 1)
        self.assertEqual(mmini.current_target(self.win), "t2")
        gen = (self.win / "gen").read_text()
        self.bar.step(self.snap, "t1", -1)  # already on the first tab: nothing is restarted
        self.bar.step(self.snap, "t5", 1)   # tab order is alpha beta delta gamma omega: omega is the last
        self.assertEqual((self.win / "gen").read_text(), gen)
        self.bar.step(self.snap, "t4", 1)   # delta -> gamma
        self.assertEqual(mmini.current_target(self.win), "t3")
        self.bar.step(self.snap, "gone", 1)  # nothing of this group is shown: first tab
        self.assertEqual(mmini.current_target(self.win), "t1")
        self.bar.step(self.snap, "gone", -1)
        self.assertEqual(mmini.current_target(self.win), "t5")

    def test_failed_plus_shows_a_notice_that_goes_away(self):
        def fail(*args, **kw):
            raise subprocess.CalledProcessError(1, "hc", stderr='{"error":{"message":"no such machine"}}')

        with mock.patch.object(mmini, "run_hc", fail):
            self.bar.plus(self.snap)
        self.bar.draw(self.snap, "t1")
        self.assertEqual(self.scr.line(4), " new: no such machine")
        self.bar.notice.until = 0
        self.bar.draw(self.snap, "t1")
        self.assertTrue(self.scr.line(4).startswith(" app"))

    def test_z_zooms_the_shown_terminal_or_says_nothing_is_shown(self):
        mmini.write_atomic(self.win / "panes", "side=S-1\ntabs=T-1\nview=V-1\n")
        with mock.patch.object(mmini, "ghostty") as run:
            self.bar.handle_key(ord("z"), self.snap, "")
            self.assertEqual(self.bar.notice.current(), "z: nothing shown")
            run.assert_not_called()
            mmini.show("t1", self.win)
            with mock.patch.object(mmini, "attach_pid", return_value=4242):
                self.bar.notice.clear()
                self.bar.handle_key(ord("z"), self.snap, "t1")
            self.assertEqual(self.bar.notice.current(), "")
        script = run.call_args[0][0]
        self.assertLess(script.index('focus (first terminal whose id is "V-1")'),
                        script.index('perform action "toggle_split_zoom" on (first terminal whose id is "V-1")'))
        self.assertNotIn("goto_split:right", script)  # from the tab bar the view is below, not to the right
        self.assertTrue(mmini.zoom_mark(self.win))  # the sidebar and the loops see it

    def test_a_resize_loop_cut_short_runs_again_at_the_next_key_only(self):
        ends = [(12, None), (5, 2), (12, None), (5, 2), (0, 2), (5, 2)]  # how each loop ends (resize_loop's result)
        runs = []

        def fake(mode, win, goal=None):
            runs.append(mode)
            return ends.pop(0)

        def join():
            if self.bar.sizer is not None:
                self.bar.sizer.join(5)

        with mock.patch.multiple(mmini, autosize=fake, autosize_enabled=lambda: True):
            self.bar.start_autosize()  # what run() does first
            mmini.mark_zoom(self.win)  # z in the sidebar in the first seconds: the loop stops (12, None)
            join()
            self.bar.resize_again()
            self.bar.on_key(mmini.curses.KEY_RESIZE, self.snap, "t1")  # a size change is no key
            join()
            self.assertEqual(runs, ["tabs"])  # hidden behind the zoom: nothing
            self.bar.on_key(ord("h"), self.snap, "t1")  # a key in the tab bar: it can be seen again
            join()
            self.assertEqual((runs, self.bar.sized), (["tabs", "tabs"], (5, 2)))
            self.bar.on_key(ord("h"), self.snap, "t1")
            join()
            self.assertEqual(len(runs), 2)  # sized: nothing more
            self.bar.start_autosize()  # (12, None) once more, then a z in the tab bar itself
            join()
            mmini.write_atomic(self.win / "target", "t1\n")
            with mock.patch.object(mmini, "ghostty") as run, \
                    mock.patch.object(mmini, "attach_pid", return_value=4242):
                self.bar.on_key(ord("z"), self.snap, "t1")
            self.assertIn("toggle_split_zoom", run.call_args[0][0])
            join()
            self.assertEqual(len(runs), 3)  # the z holds it
            self.bar.on_key(ord("h"), self.snap, "t1")
            join()
            self.assertEqual(len(runs), 4)
            self.bar.start_autosize()  # a size change from outside stopped it: no limit found (0)
            join()
            self.bar.on_key(ord("h"), self.snap, "t1")
            join()
            self.assertEqual(len(runs), 6)
        with mock.patch.object(mmini, "autosize") as sizing:  # MMINI_GHOSTTY=0: never
            self.bar.sized = (0, None)
            self.bar.on_key(ord("h"), self.snap, "t1")
        sizing.assert_not_called()


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
        for target, value in ((mmini, {"run_hc": self.hc}), (mmini.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scr = FakeScr(5, 60)
        self.bar = mmini.TabBar(self.scr, self.win, self.state)
        self.addCleanup(self.bar.stop_engine)  # runs before the patches end

    def snap(self):
        return mmini.read_snapshot(self.win)

    def test_engine_only_without_a_live_sidebar_and_it_stops_when_one_appears(self):
        mmini.write_atomic(self.win / "sidebar.pid", f"{os.getpid()}\n")  # stand-in for a live sidebar
        for now in (100.0, 200.0):
            self.bar.watch_sidebar(now)
            self.assertIsNone(self.bar.engine)
            self.assertFalse(self.bar.alone)
        mmini.write_atomic(self.win / "sidebar.pid", f"{dead_pid()}\n")  # it died; a hangup leaves the file
        self.bar.watch_sidebar(300.0)
        self.bar.watch_sidebar(300.0 + mmini.ENGINE_GRACE - 0.1)
        self.assertIsNone(self.bar.engine)  # the grace of a normal start
        self.assertEqual(self.hc.calls, [])
        self.bar.watch_sidebar(300.0 + mmini.ENGINE_GRACE)
        engine = self.bar.engine
        self.assertIsNotNone(engine)
        self.assertTrue(self.bar.alone)
        self.assertTrue(wait_for(lambda: self.snap() is not None))  # its own snapshot, from its own hc ls
        self.assertEqual([t["label"] for t in self.snap()["tabs"]], ["alpha", "beta"])
        self.bar.watch_sidebar(310.0)
        self.assertIs(self.bar.engine, engine)  # one engine, not one per round
        mmini.write_atomic(self.win / "sidebar.pid", f"{os.getpid()}\n")  # a sidebar is back
        self.bar.watch_sidebar(311.0)
        self.assertIsNone(self.bar.engine)
        self.assertFalse(self.bar.alone)
        self.assertTrue(engine.stopped.is_set())
        time.sleep(0.3)  # a listing it was in finishes
        calls = len(self.hc.calls)
        mmini.write_atomic(self.win / "poke", "x\n")  # would start a listing at once if it still ran
        time.sleep(0.6)
        self.assertEqual(len(self.hc.calls), calls)

    def test_hidden_starts_the_engine_at_once(self):
        mmini.write_sidebar_state("hidden", self.state)  # the sidebar wrote it before it ended
        self.bar.watch_sidebar(100.0)
        self.assertIsNotNone(self.bar.engine)
        self.assertTrue(self.bar.alone)

    def test_a_normal_start_runs_no_second_engine(self):
        self.bar.watch_sidebar(100.0)  # both panes start; the sidebar has not written its pid yet
        mmini.write_atomic(self.win / "sidebar.pid", f"{os.getpid()}\n")
        for now in (101.0, 100.0 + mmini.ENGINE_GRACE, 200.0):
            self.bar.watch_sidebar(now)
            self.assertIsNone(self.bar.engine, now)

    def test_everything_works_with_the_sidebar_hidden(self):
        """Tabs of the current space, switching, +, the info line, and the tabs following the shown terminal into
        another space: all from the tab bar's own engine."""
        mmini.write_sidebar_state("hidden", self.state)
        self.bar.watch_sidebar(100.0)
        self.assertTrue(wait_for(lambda: mmini.current_target(self.win) == "t1"))  # the start opens the space
        self.assertTrue(wait_for(lambda: (self.snap() or {}).get("name") == "dev"))
        self.bar.draw(self.snap(), "t1")
        self.assertEqual(self.scr.line(0), mmini.glyph("› ● alpha │ ○ beta │ +"))
        self.assertEqual(self.scr.line(1), mmini.glyph("  t1 · ~/dev · claude-code · idle"))
        self.bar.on_key(ord("l"), self.snap(), "t1")  # switch
        self.assertEqual(mmini.current_target(self.win), "t2")
        self.assertTrue(wait_for(lambda: mmini.read_last(self.state).get("space:dev") == "t2"))  # remembered
        self.bar.plus(self.snap())  # a new shell in this space: the engine lists it at once (poke)
        new = mmini.current_target(self.win)
        self.assertNotIn(new, ("t1", "t2"))
        self.assertTrue(wait_for(lambda: new in [t["address"] for t in (self.snap() or {}).get("tabs", [])]))
        mmini.show("t2", self.win)
        self.assertTrue(wait_for(lambda: self.bar.engine.seen == ("t2", "space:dev")))
        self.hc.terms[1]["cwd"] = "/Users/x/dev/other"  # the shown terminal moves to another space
        mmini.write_atomic(self.win / "poke", "x\n")
        self.assertTrue(wait_for(lambda: (self.snap() or {}).get("name") == "other"))
        self.assertEqual(mmini.read_text(self.state / "group"), "space:other")
        self.assertIn("t2", [t["address"] for t in self.snap()["tabs"]])


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
        env = dict(os.environ, MMINI_HC=str(self.hc), MMINI_STATE=str(self.win), STUB_LOG=str(self.log), **extra)
        env.pop("MMINI_WINDOW", None)
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
        mmini.show("a", self.win)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["a"]))
        self.assertTrue(self.wait_for(lambda: mmini.attach_pid(self.win) != 0))
        started = time.monotonic()
        mmini.show("b", self.win)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["b"]))
        self.assertLess(time.monotonic() - started, 2.0)

    def test_two_quick_picks_end_on_the_last_one(self):
        self.start_view()
        mmini.show("a", self.win)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["a"]))
        for round_, gap in enumerate((0.0, 0.005, 0.010, 0.012, 0.015, 0.020, 0.030, 0.010, 0.015, 0.012)):
            first, last = f"b{round_}", f"c{round_}"
            mmini.show(first, self.win)
            time.sleep(gap)
            mmini.show(last, self.win)
            self.assertTrue(self.wait_for(lambda: self.attached() == [last]), (gap, self.attached()))
            time.sleep(0.5)  # and it stays there
            self.assertEqual(self.attached(), [last], gap)
            self.assertEqual(mmini.current_target(self.win), last)

    def test_the_watcher_alone_switches_when_the_fast_path_finds_nothing(self):
        self.start_view()
        mmini.show("a", self.win)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["a"]))
        with mock.patch.object(mmini, "attach_pid", return_value=0):  # as if the pick came before view.pid existed
            mmini.show("b", self.win)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["b"]))

    def test_burst_of_picks(self):
        self.start_view()
        for i in range(12):
            mmini.show(f"t{i}", self.win)
            time.sleep(0.004 * (i % 4))
        self.assertTrue(self.wait_for(lambda: self.attached() == ["t11"]), self.attached())
        time.sleep(0.6)
        self.assertEqual(self.attached(), ["t11"])

    def test_saved_target_is_attached_at_start_unless_autoopen_is_off(self):
        mmini.write_atomic(self.win / "target", "old\n")
        self.start_view(MMINI_AUTOOPEN="0")
        time.sleep(0.6)
        self.assertEqual(self.attached(), [])
        mmini.show("new", self.win)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["new"]))

    def test_saved_target_is_attached_at_start_by_default(self):
        mmini.write_atomic(self.win / "target", "old\n")
        self.start_view()
        self.assertTrue(self.wait_for(lambda: self.attached() == ["old"]))

    def test_closing_the_pane_leaves_no_pid_file_and_no_attach(self):
        proc = self.start_view()
        mmini.show("a", self.win)
        self.assertTrue(self.wait_for(lambda: (self.win / "view.pid").exists() and self.attached() == ["a"]))
        os.killpg(proc.pid, signal.SIGHUP)  # what closing the pane does
        proc.wait(timeout=5)
        self.assertTrue(self.wait_for(lambda: not (self.win / "view.pid").exists()))
        self.assertFalse((self.win / "view.loop").exists())
        self.assertEqual(mmini.attach_pid(self.win), 0)

    def test_stale_pid_file_from_a_dead_view_is_removed_at_start(self):
        mmini.write_atomic(self.win / "view.pid", "999999\n")
        self.start_view()
        self.assertFalse((self.win / "view.pid").exists())

    def test_failed_attach_keeps_its_message_and_names_the_exit_code(self):
        proc = self.start_view()
        mmini.show("fail-x", self.win)
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
        mmini.show("a", self.win)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["a"]))

    def test_missing_hc_is_said_plainly(self):
        env = dict(os.environ, MMINI_HC="/nonexistent/hc", MMINI_STATE=str(self.win))
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
        env = dict(os.environ, MMINI_HC=str(self.hc), MMINI_STATE=str(shared), MMINI_WINDOW=str(mine),
                   STUB_LOG=str(self.log))
        proc = subprocess.Popen(["/bin/sh", str(ROOT / "view.sh")], env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        self.addCleanup(self.stop_view, proc)
        self.assertTrue(self.wait_for(lambda: (mine / "view.loop").exists()))
        self.assertFalse(dead.exists())  # old, sidebar gone
        self.assertFalse(gone.exists())  # old, sidebar and view gone
        self.assertTrue(live.exists() and fresh.exists() and other.exists())
        self.assertTrue(view.exists())  # old, but its view loop is alive: it keeps its folder (and its attach)
        mmini.show("a", mine)
        self.assertTrue(self.wait_for(lambda: self.attached() == ["a"]))
        self.assertFalse((shared / "target").exists())

    def test_two_windows_do_not_disturb_each_other(self):
        shared = self.win
        views = []
        for name in ("w-one", "w-two"):
            env = dict(os.environ, MMINI_HC=str(self.hc), MMINI_STATE=str(shared), MMINI_WINDOW=str(shared / name),
                       STUB_LOG=str(self.log))
            proc = subprocess.Popen(["/bin/sh", str(ROOT / "view.sh")], env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
            self.addCleanup(self.stop_view, proc)
            views.append(shared / name)
        self.assertTrue(self.wait_for(lambda: all((v / "view.loop").exists() for v in views)))
        mmini.show("one-a", views[0])
        mmini.show("two-a", views[1])
        self.assertTrue(self.wait_for(lambda: sorted(self.attached()) == ["one-a", "two-a"]))
        pid_two = mmini.attach_pid(views[1])
        mmini.show("one-b", views[0])  # a pick in window one
        self.assertTrue(self.wait_for(lambda: sorted(self.attached()) == ["one-b", "two-a"]))
        time.sleep(0.5)
        self.assertEqual(mmini.attach_pid(views[1]), pid_two)  # window two's attach was never touched
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
        return dict(os.environ, MMINI_STATE=tmp, MMINI_GHOSTTY="0", MMINI_AUTOOPEN="0", TERM="xterm-256color",
                    MMINI_HC="/nonexistent/hc", PYTHONDONTWRITEBYTECODE="1")

    def test_tab_bar_and_sidebar_end(self):
        for mode in ("tabs", "sidebar"):
            with tempfile.TemporaryDirectory() as tmp:
                env = self.env(tmp)
                env.pop("MMINI_WINDOW", None)
                self.closed_pane([sys.executable, str(ROOT / "mmini.py"), mode], env)

    def test_view_ends(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "hc"
            stub.write_text(STUB_HC)
            stub.chmod(0o755)
            env = dict(self.env(tmp), MMINI_HC=str(stub), STUB_LOG=os.path.join(tmp, "log"),
                       MMINI_STATE=os.path.join(tmp, "state"))
            env.pop("MMINI_WINDOW", None)
            self.closed_pane(["/bin/sh", str(ROOT / "view.sh")], env)
            self.assertFalse(os.path.exists(os.path.join(tmp, "state", "view.loop")))


def applescript_literals(line):
    """The contents of every AppleScript string literal on a line, unescaped (\\\\ and \\")."""
    return [re.sub(r"\\(.)", r"\1", m) for m in re.findall(r'"((?:[^"\\]|\\.)*)"', line)]


class RebuildScriptTests(unittest.TestCase):
    """The AppleScript the tab bar runs to bring the sidebar back at full height."""

    VID = "6C1D0F2A-3B4E-4F5A-9C8D-7E6F5A4B3C2D"
    WIN = Path("/Users/x/.local/state/mmini/w-AbC123")
    BASE = Path("/Users/x/.local/share/mmini")

    def test_exact_text(self):
        script = mmini.rebuild_script(self.VID, self.WIN, self.BASE, [("MMINI_WIDTH", "28")])
        line = ("exec env MMINI_WINDOW=/Users/x/.local/state/mmini/w-AbC123 MMINI_WIDTH=28 "
                "python3 /Users/x/.local/share/mmini/mmini.py ")
        win = "/Users/x/.local/state/mmini/w-AbC123"
        self.assertEqual(script.split("\n"), [
            'tell application "Ghostty"',
            "    set sideCfg to new surface configuration",
            f'    set initial input of sideCfg to "{line}sidebar" & linefeed',
            f'    set sideTerm to split (first terminal whose id is "{self.VID}") direction left with configuration '
            "sideCfg",
            "    set tabsCfg to new surface configuration",
            f'    set initial input of tabsCfg to "{line}tabs" & linefeed',
            f'    set tabsTerm to split (first terminal whose id is "{self.VID}") direction up with configuration '
            "tabsCfg",
            f'    set ids to "side=" & (id of sideTerm) & linefeed & "tabs=" & (id of tabsTerm) & linefeed & '
            f'"view={self.VID}" & linefeed',
            f'    tell current application to do shell script "printf %s " & quoted form of ids & '
            f'" > {win}/panes.tmp && mv {win}/panes.tmp {win}/panes"',
            "    tell current application to delay 0.8",
            "    focus sideTerm",
            "end tell",
        ])

    def test_order_splits_first_ids_then_the_delay_then_the_focus(self):
        script = mmini.rebuild_script(self.VID, self.WIN, self.BASE, [])
        steps = ["direction left", "direction up", "set ids to", "do shell script", "delay 0.8", "focus sideTerm"]
        at = [script.index(s) for s in steps]
        self.assertEqual(at, sorted(at), steps)
        self.assertEqual(script.count("split "), 2)  # both from the view: a split is made from a leaf
        self.assertNotIn("close", script)  # no close command, no close_surface action (it can ask first)
        self.assertNotIn("perform action", script)
        self.assertEqual(script.count('tell application "Ghostty"'), 1)

    def test_ids_go_through_safe_id(self):
        script = mmini.rebuild_script('V-1"; do shell script "rm -rf ~', self.WIN, self.BASE, [])
        self.assertIn('(first terminal whose id is "V-1doshellscriptrm-rf")', script)
        self.assertNotIn("rm -rf", script)

    def test_env_pairs(self):
        environ = {"MMINI_STATE": "/s", "MMINI_WINDOW": "/elsewhere", "MMINI_HC": "/my bin/hc", "PATH": "/bin",
                   "MMINI_bad": "x", "XMMINI_A": "1", "MMINI_GHOSTTY": "1"}
        pairs = mmini.mmini_env(environ)
        self.assertEqual(pairs, [("MMINI_GHOSTTY", "1"), ("MMINI_HC", "/my bin/hc"), ("MMINI_STATE", "/s")])
        line = mmini.pane_command("tabs", Path("/w"), Path("/b"), pairs + [("MMINI_WINDOW", "/x"), ("BAD NAME", "1")])
        self.assertEqual(line, "exec env MMINI_WINDOW=/w MMINI_GHOSTTY=1 MMINI_HC='/my bin/hc' MMINI_STATE=/s "
                               "python3 /b/mmini.py tabs")  # the window folder given wins over one in the pairs

    def test_quoting_survives_spaces_and_quotes_in_the_window_folder(self):
        """The literals are unescaped as AppleScript reads them and handed to /bin/sh, as Ghostty types the line
        and `do shell script` runs the write: python3 is a stand-in that records what it got."""
        with tempfile.TemporaryDirectory() as tmp:
            win = Path(tmp) / "my win" / 'it\'s "x" \\ $HOME `id`'
            win.mkdir(parents=True)
            base = Path(tmp) / "app dir"
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            record = Path(tmp) / "record"
            stub = bin_dir / "python3"
            stub.write_text('#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done >"$RECORD"\n'
                            'printf "%s\\n" "$MMINI_WINDOW" "$MMINI_STATE" >>"$RECORD"\n')
            stub.chmod(0o755)
            env_pairs = [("MMINI_STATE", "/st ate/'q'")]
            script = mmini.rebuild_script(self.VID, win, base, env_pairs)
            lines = script.split("\n")
            for mode, line in (("sidebar", lines[2]), ("tabs", lines[5])):
                typed = applescript_literals(line)
                self.assertEqual(len(typed), 1, line)
                out = subprocess.run(["/bin/sh", "-c", typed[0]], capture_output=True, text=True,
                                     env={"PATH": f"{bin_dir}:/usr/bin:/bin", "RECORD": str(record)})
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual(record.read_text().split("\n")[:-1],
                                 [str(base / "mmini.py"), mode, str(win), "/st ate/'q'"])
            write = lines[8]
            prefix, rest = applescript_literals(write)  # "printf %s " & quoted form of ids & " > ... && mv ..."
            self.assertEqual(prefix, "printf %s ")
            ids = f"side=S-9\ntabs=T-9\nview={self.VID}\n"
            # AppleScript's quoted form of a text without single quotes is that text in single quotes
            out = subprocess.run(["/bin/sh", "-c", prefix + "'" + ids + "'" + rest], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(mmini.read_panes(win), {"side": "S-9", "tabs": "T-9", "view": self.VID})
            self.assertFalse((win / "panes.tmp").exists())

    def test_the_tab_bar_passes_its_settings_and_its_own_folder(self):
        with mock.patch.dict(os.environ, {"MMINI_WIDTH": "28", "MMINI_HC": "/h"}):
            pairs = mmini.mmini_env(os.environ)
        self.assertIn(("MMINI_WIDTH", "28"), pairs)
        self.assertIn(("MMINI_STATE", _DEFAULT_STATE), pairs)
        self.assertEqual(mmini.BASE.resolve(), ROOT)


class ProgramTests(unittest.TestCase):
    """mmini.py itself in a pseudo terminal: hiding ends the sidebar with exit status 0, and a sidebar started while
    the state is hidden ends before it draws anything. With MMINI_GHOSTTY=0 the program ends all the same; only the
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
        env = dict(os.environ, MMINI_STATE=str(self.state), MMINI_WINDOW=str(self.win), MMINI_GHOSTTY="0",
                   MMINI_AUTOOPEN="0", MMINI_HC="/nonexistent/hc", TERM="xterm-256color",
                   PYTHONDONTWRITEBYTECODE="1")
        env.update(extra)
        proc = subprocess.Popen([sys.executable, str(ROOT / "mmini.py"), mode], stdin=slave, stdout=slave,
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
        mmini.write_sidebar_state("hidden", self.state)
        proc, _, output = self.start()
        self.assertEqual(proc.wait(timeout=10), 0)
        time.sleep(0.2)
        self.assertEqual(bytes(output), b"")  # not even curses' screen switch
        self.assertFalse((self.win / "sidebar.pid").exists())
        self.assertEqual(mmini.read_sidebar_state(self.state), "hidden")

    def test_q_and_c_c_end_the_sidebar_and_leave_hidden(self):
        for keys in (b"q", b"cc"):
            mmini.write_sidebar_state("open", self.state)
            proc, master, output = self.start()
            self.assertTrue(wait_for(lambda: (self.win / "sidebar.pid").exists(), 10), keys)
            self.assertTrue(wait_for(lambda: b"fold" in output, 10), keys)  # drawn: the loop reads keys now
            os.write(master, keys)
            self.assertEqual(proc.wait(timeout=10), 0, keys)
            self.assertEqual(mmini.read_sidebar_state(self.state), "hidden", keys)
            self.assertFalse((self.win / "sidebar.pid").exists(), keys)

    def test_both_panes_set_their_title_and_clear_their_folder_first(self):
        mmini.write_sidebar_state("open", self.state)
        for mode, drawn in (("sidebar", b"fold"), ("tabs", b"switch")):
            proc, _, output = self.start(mode)
            self.assertTrue(wait_for(lambda: drawn in output, 10), (mode, bytes(output)))  # noqa: B023
            self.assertTrue(bytes(output).startswith(b"\x1b]2;mmini\x07\x1b]7;\x07"), (mode, bytes(output[:40])))
            proc.kill()
            proc.wait(timeout=5)

    def test_the_tab_bar_alone_draws_the_opener_and_its_own_tabs(self):
        stub = Path(self._tmp.name) / "hc"
        stub.write_text('#!/bin/sh\ncase "$1" in\n'
                        'ls) echo \'{"terminals":[{"address":"t1","agent":"claude-code","cwd":"/Users/x/dev/app",'
                        '"name":"alpha","status":"idle"},{"address":"t2","agent":"zsh","cwd":"/Users/x/dev/app",'
                        '"name":"beta"}]}\' ;;\nget) echo \'{"labels":{}}\' ;;\n*) exit 3 ;;\nesac\n')
        stub.chmod(0o755)
        mmini.write_sidebar_state("hidden", self.state)
        proc, master, output = self.start("tabs", MMINI_HC=str(stub))
        self.assertTrue(wait_for(lambda: mmini.read_snapshot(self.win) is not None, 10))  # its engine wrote it
        self.assertEqual([t["label"] for t in mmini.read_snapshot(self.win)["tabs"]], ["alpha", "beta"])
        self.assertTrue(wait_for(lambda: b"beta" in output and "›".encode() in output, 10), bytes(output))
        self.assertIsNone(proc.poll())


    def test_the_separator_dragged_in_the_real_program_both_encodings(self):
        """mmini.py sidebar in a 24x30 pseudo terminal with a stand-in hc: a press on the separator, moves with
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
        for term, extra, codes in (("xterm-256color", {}, (x10(0, 2, 19), x10(32, 2, 12), x10(3, 2, 8))),
                                   ("xterm-ghostty", {"TERMINFO": reports.terminfo()},
                                    (sgr(0, 2, 19), sgr(32, 2, 12), sgr(0, 2, 8, "m")))):
            mmini.clear_split(self.state)
            mmini.write_sidebar_state("open", self.state)
            proc, master, output = self.start(MMINI_HC=str(stub), TERM=term, LINES="24", COLUMNS="30", **extra)
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct_winsize(24, 30))
            # drawn with the agent: rule on line 19 (23 lines of list: the line, "agents", "app · 1", alpha)
            self.assertTrue(wait_for(lambda: b"alpha" in output and b"fold" in output, 10), term)  # noqa: B023
            time.sleep(0.3)
            for code in codes:
                os.write(master, code)
                time.sleep(0.1)
            self.assertTrue(wait_for(lambda: mmini.read_text(self.state / "split") == "8/24", 5),
                            (term, mmini.read_text(self.state / "split")))
            raw = bytes(output)
            self.assertLess(raw.index(b"\x1b[?1000h" if term == "xterm-256color" else b"\x1b[?1006;1000h"),
                            raw.index(b"\x1b[?1002h"), term)
            os.write(master, b"q")
            self.assertEqual(proc.wait(timeout=10), 0, term)
            self.assertEqual(mmini.read_text(self.state / "split"), "8/24", term)
            self.assertTrue(wait_for(lambda: b"\x1b[?1002l" in output, 5), term)  # noqa: B023


def struct_winsize(rows, cols):
    import struct
    return struct.pack("HHHH", rows, cols, 0, 0)


class NamesTests(unittest.TestCase):
    """Display names: names.json, what a rename does, and where the names are drawn."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name)

    def test_valid_display_names(self):
        for good in ("Main", "Harry's rig", "a", "x" * 32, "Größe", "web-2 (old)"):
            self.assertTrue(mmini.valid_display_name(good), good)
        for bad in ("", " Main", "Main ", "x" * 33, "a\nb", "a\tb", "a\x1b[31mb", "a\x00", " "):
            self.assertFalse(mmini.valid_display_name(bad), repr(bad))

    def test_read_change_and_remove_keep_other_entries(self):
        self.assertEqual(mmini.read_names(self.state), {})
        mmini.change_names({"space:dev": "Main"}, self.state)
        mmini.change_names({"rig:guest": "Harry"}, self.state)  # another window's rename stays
        self.assertEqual(mmini.read_names(self.state), {"space:dev": "Main", "rig:guest": "Harry"})
        self.assertEqual(json.loads((self.state / "names.json").read_text()),
                         {"rig:guest": "Harry", "space:dev": "Main"})
        mmini.change_names({"space:dev": ""}, self.state)  # "" removes
        self.assertEqual(mmini.read_names(self.state), {"rig:guest": "Harry"})

    def test_junk_in_the_file_is_left_out(self):
        (self.state / "names.json").write_text(json.dumps({
            "space:dev": "Main", "rig:x": "a\nb", "term:t1": 7, "other:x": "y", "space:": "z", "rig:y": " pad"}))
        self.assertEqual(mmini.read_names(self.state), {"space:dev": "Main"})
        (self.state / "names.json").write_text("not json")
        self.assertEqual(mmini.read_names(self.state), {})

    def test_plan_rename(self):
        p = mmini.plan_rename
        self.assertEqual(p("Main", "dev", ["other", "rig"]), ("set", "Main"))
        self.assertEqual(p("  Main  ", "dev", []), ("set", "Main"))
        self.assertEqual(p("", "dev", []), ("remove", ""))  # an empty name removes the rename
        self.assertEqual(p("   ", "dev", []), ("remove", ""))
        self.assertEqual(p("dev", "dev", []), ("remove", ""))  # the own name too
        self.assertEqual(p("Other", "dev", ["other"]), ("bad", "Other is taken"))  # refused, ignoring case
        self.assertEqual(p("x" * 33, "dev", [])[0], "bad")
        self.assertEqual(p("a\x1bb", "dev", [])[0], "bad")

    def test_names_change_what_is_drawn_and_the_order_only(self):
        terms = mmini.parse(SAMPLE)
        names = {"space:atlas": "Zeta", "rig:rig": "Harry", "term:mmini/t5": "web", "rig:this Mac": "Laptop"}
        spaces, rigs = mmini.build_groups(terms, "mmini", names=names)
        rigs = [g for g in rigs if not g.home]  # the home machine's row: ServerTests
        self.assertEqual([(g.key, g.name, g.shown) for g in spaces],
                         [("space:home", "home", "home"), ("space:appshop", "appshop", "appshop"),
                          ("space:atlas", "atlas", "Zeta")])  # sorted by what is shown, "home" first
        self.assertEqual([(g.key, g.shown) for g in rigs], [("rig:rig", "Harry"), ("rig:this Mac", "Laptop")])
        atlas = spaces[2]
        self.assertEqual(atlas.cwd, "/Users/x/dev/atlas")  # the folder rules use the space's own name
        self.assertEqual([(t.label, t.shown) for t in atlas.terms], [("atlas", "web"), ("zz", "zz")])
        self.assertEqual(mmini.make_snapshot(atlas, 1.0)["name"], "atlas")  # a new shell's label: the own name
        self.assertEqual(mmini.make_snapshot(atlas, 1.0)["title"], "Zeta")
        self.assertEqual(mmini.make_snapshot(atlas, 1.0)["tabs"][0]["label"], "web")


class MenuTests(unittest.TestCase):
    """The action menu: entries per row, its box at 30 columns and at small heights, clicks."""

    def setUp(self):
        self.space = mmini.Group("space:dev", "dev", "space", "mmini", "")
        self.rig = mmini.Group("rig:vps", "vps", "rig", "vps", "")
        self.local = mmini.Group("rig:this Mac", mmini.LOCAL, "rig", mmini.LOCAL, "")
        self.home = mmini.Group("rig:mmini", "mmini", "rig", "mmini", "")  # the home machine without terminals

    def actions(self, item, group):
        """The row's own entries: every menu ends with the three switches (test_every_menu_ends_with_...)."""
        entries = mmini.menu_entries(item, group, "mmini")
        self.assertEqual([e.action for e in entries[-3:]], ["servers", "agents", "devs"])
        return [e.action for e in entries[:-3]]

    def test_entries_per_row(self):
        g = mmini.Item("group", "", "")
        self.assertEqual(self.actions(g, self.space), ["open", "new", "rename", "delete"])
        self.assertEqual(self.actions(g, self.rig), ["open", "new", "rename", "forget"])
        self.assertEqual(self.actions(g, self.local), ["open", "new", "rename"])  # never removed
        self.assertEqual(self.actions(g, self.home), ["open", "new", "rename"])
        home = mmini.Group("rig:box", "box", "rig", "box", "", home=True)  # a home machine of another name
        self.assertEqual(self.actions(g, home), ["open", "new", "rename"])
        self.assertEqual(self.actions(mmini.Item("agent", "space:dev", "t1"), self.space),
                         ["open", "rename", "move", "end"])
        self.assertEqual(self.actions(mmini.Item("agent", "rig:vps", "vps/t1"), self.rig),
                         ["open", "rename", "end"])  # servers have no spaces to move to
        self.assertEqual(self.actions(mmini.NEW_SPACE, None), ["new_space"])
        self.assertEqual(self.actions(mmini.ADD_RIG, None), ["add_rig"])
        self.assertEqual(self.actions(mmini.Item("needs", "", "t3"), None), ["open"])
        self.assertEqual(self.actions(mmini.Item("dev", "", "3917"), None), ["browse"])

    def test_every_menu_ends_with_the_servers_switch(self):
        for item, group in ((mmini.Item("group", "", ""), self.space), (mmini.Item("group", "", ""), self.rig),
                            (mmini.Item("agent", "space:dev", "t1"), self.space), (mmini.NEW_SPACE, None),
                            (mmini.ADD_RIG, None), (mmini.Item("needs", "", "t3"), None),
                            (mmini.Item("dev", "", "3917"), None)):
            self.assertEqual(mmini.menu_entries(item, group, "mmini")[-3], mmini.Entry("servers", "Show servers", "v"))
            self.assertEqual(mmini.menu_entries(item, group, "mmini", servers=True)[-3],
                             mmini.Entry("servers", "Hide servers", "v"))
        labels = [e.label for e in mmini.menu_entries(mmini.Item("group", "", ""), self.rig, "mmini")]
        self.assertEqual(labels, ["Open", "New terminal here", "Rename", "Forget server", "Show servers",
                                  "Hide agents", "Hide dev servers"])
        self.assertEqual([e.label for e in mmini.menu_entries(mmini.ADD_RIG, None)],
                         ["Add server", "Show servers", "Hide agents", "Hide dev servers"])

    def test_every_menu_has_the_agents_and_dev_servers_switches(self):
        for item, group in ((mmini.Item("group", "", ""), self.space), (mmini.Item("group", "", ""), self.rig),
                            (mmini.Item("agent", "space:dev", "t1"), self.space), (mmini.NEW_SPACE, None),
                            (mmini.ADD_RIG, None), (mmini.Item("needs", "", "t3"), None),
                            (mmini.Item("dev", "", "3917"), None)):
            for agents, devs in itertools.product((True, False), repeat=2):
                tail = mmini.menu_entries(item, group, "mmini", True, agents, devs)[-2:]
                self.assertEqual(tail, [mmini.Entry("agents", "Hide agents" if agents else "Show agents", "g"),
                                        mmini.Entry("devs", "Hide dev servers" if devs else "Show dev servers", "w")])

    def test_every_entry_names_its_direct_key(self):
        keys = {}
        for item, group in ((mmini.Item("group", "", ""), self.space), (mmini.Item("group", "", ""), self.rig),
                            (mmini.Item("agent", "space:dev", "t1"), self.space)):
            for e in mmini.menu_entries(item, group, "mmini"):
                keys[e.action] = e.key
        self.assertEqual(keys, {"open": "↵", "new": "n", "rename": "e", "delete": "d", "forget": "d", "move": "m",
                                "end": "d", "servers": "v", "agents": "g", "devs": "w"})
        labels = [e.label for e in mmini.menu_entries(mmini.Item("group", "", ""), self.space, "mmini")]
        self.assertEqual(labels, ["Open", "New terminal here", "Rename", "Delete space", "Show servers",
                                  "Hide agents", "Hide dev servers"])

    def test_box_at_30_columns_fits_and_reads(self):
        entries = mmini.menu_entries(mmini.Item("group", "", ""), self.space, "mmini")
        for ascii_only in (False, True):
            with mock.patch.object(mmini, "utf8_screen", return_value=not ascii_only):
                want = mmini.menu_width(entries)
                self.assertLessEqual(want, 29, ascii_only)
                box = mmini.menu_box(1, len(entries), 0, 24, 30, want)
                self.assertEqual((box.top, box.left, box.width, box.bordered, box.offset, box.shown),
                                 (2, min(2, 29 - want), want, True, 0, 7))  # just below the row, two columns in
                self.assertLessEqual(box.left + box.width, 29)  # the last column stays empty
                lines = mmini.menu_lines("dev", entries, box, 2)
                self.assertEqual([y for y, _, _ in lines], list(range(2, 11)))
                self.assertTrue(all(len(mmini.glyph(t)) == want for _, t, _ in lines), lines)
                self.assertEqual([s for _, _, s in lines], [False, False, False, True] + [False] * 5)
                texts = [mmini.glyph(t) for _, t, _ in lines]
                self.assertIn("dev", texts[0])
                self.assertTrue(texts[1].startswith(mmini.glyph("│ Open")))
                self.assertTrue(texts[1].rstrip(mmini.glyph("│")).rstrip().endswith(mmini.glyph("↵")))
                self.assertRegex(texts[2], r"New terminal here +n ")
                self.assertRegex(texts[5], r"Show servers +v ")
                self.assertRegex(texts[6], r"Hide agents +g ")
                self.assertRegex(texts[7], r"Hide dev servers +w ")

    def test_box_goes_above_the_row_when_below_has_no_room(self):
        box = mmini.menu_box(20, 4, 0, 24, 30, 24)
        self.assertEqual((box.top, box.height), (14, 6))  # lines 14-19, the row on 20 stays visible
        box = mmini.menu_box(3, 4, 0, 8, 30, 24)  # neither below nor above: as low as the screen allows
        self.assertEqual((box.top, box.height), (2, 6))

    def test_small_heights_drop_the_border_and_scroll(self):
        for height in range(1, 13):
            for row in range(height):
                for selected in range(4):
                    box = mmini.menu_box(row, 4, selected, height, 30, 24)
                    case = (height, row, selected, box)
                    self.assertGreaterEqual(box.top, 0, case)
                    self.assertLessEqual(box.top + box.height, height, case)
                    self.assertEqual(box.bordered, height >= 6, case)
                    self.assertTrue(box.offset <= selected < box.offset + box.shown, case)  # the selection shows
        self.assertIsNone(mmini.menu_box(0, 4, 0, 0, 30, 24))
        narrow = mmini.menu_box(0, 4, 0, 24, 12, 24)  # a narrow pane: as wide as it can, from column 0
        self.assertEqual((narrow.left, narrow.width), (0, 11))
        lines = mmini.menu_lines("dev", mmini.menu_entries(mmini.Item("group", "", ""), self.space), narrow, 0)
        self.assertTrue(all(mmini.text_width(t) == 11 for _, t, _ in lines), lines)

    def test_menu_hit(self):
        box = mmini.menu_box(1, 4, 0, 24, 30, 24)  # lines 2-7, columns 2-25
        self.assertEqual(mmini.menu_hit(box, 5, 3), ("entry", 0))
        self.assertEqual(mmini.menu_hit(box, 25, 6), ("entry", 3))
        self.assertEqual(mmini.menu_hit(box, 5, 2), ("box", -1))  # the border
        self.assertEqual(mmini.menu_hit(box, 5, 7), ("box", -1))
        for x, y in ((1, 3), (26, 3), (5, 1), (5, 8)):
            self.assertEqual(mmini.menu_hit(box, x, y), ("outside", -1), (x, y))
        flat = mmini.menu_box(0, 4, 3, 3, 30, 24)  # no border, scrolled to the last entry
        self.assertEqual((flat.offset, flat.shown, flat.bordered), (1, 3, False))
        self.assertEqual(mmini.menu_hit(flat, 5, flat.top), ("entry", 1))


class AddRigTests(unittest.TestCase):
    """What may be typed at "+ add server", and the exact command built from it."""

    GOOD = ("me@host", "host", "me@10.0.0.7:2222", "my-vps.example.com", "vps_2", "a.b@c-d.e:22", "_x")
    BAD = ("", "x;rm -rf ~", "me@host; rm -rf ~", "a b", "host\n", "\nhost", "hоst", "mе@host",
           "-oProxyCommand=x", "me@-oProxyCommand=x", "a@b@c", "@host", "host:", "host:123456", "$(id)", "`id`",
           "host|cat", "a/b", "~/x", "x" * 256, "host\x00", "ｈost")

    def test_targets(self):
        for target in self.GOOD:
            self.assertTrue(mmini.valid_rig_target(target), target)
        for target in self.BAD:
            self.assertFalse(mmini.valid_rig_target(target), repr(target))

    def test_names(self):
        for name in ("harry", "rig-2", "a_b", "a" * 32):
            self.assertTrue(mmini.valid_rig_name(name), name)
        for name in ("", "Harry", "2rig", "-x", "_x", "a" * 33, "a b", "a\n", "x;y", "ｈakan"):
            self.assertFalse(mmini.valid_rig_name(name), repr(name))

    def test_args_are_separate_items_after_a_fixed_script(self):
        args = mmini.add_rig_args("/Users/me/.local/bin/hc", "me@host:2222", "harry", "/Users/me")
        self.assertEqual(args, ["run", "--bg", "--json", "--no-parent", "--rm", "--name", "add-server", "--cwd",
                                "/Users/me", "/bin/sh", "-c", mmini.ADD_RIG_SCRIPT, "add-server",
                                "/Users/me/.local/bin/hc", "me@host:2222", "harry"])
        self.assertNotIn("--on", args)  # this Mac's own core: the questions come up where they can be answered
        self.assertEqual(mmini.add_rig_args("hc", "vps", "", "/Users/me")[-2:], ["hc", "vps"])  # no name: the host
        self.assertNotIn("--cwd", mmini.add_rig_args("hc", "vps", "", ""))
        for target in self.BAD:
            with self.assertRaises(ValueError, msg=repr(target)):
                mmini.add_rig_args("hc", target, "", "/Users/me")
        for name in ("Harry", "x;y", "a b"):
            with self.assertRaises(ValueError, msg=name):
                mmini.add_rig_args("hc", "vps", name, "/Users/me")

    def test_the_script_passes_what_was_typed_as_arguments_only(self):
        """The fixed script run as the new terminal would run it, with a stand-in hc that prints its arguments:
        the target and name arrive whole, after "--", and nothing in them is run."""
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "hc"
            stub.write_text('#!/bin/sh\nfor a in "$@"; do printf "[%s]" "$a"; done; echo\nexit 3\n')
            stub.chmod(0o755)
            for name, expect in (("harry", "[machine][add][--name][harry][--][me@host]"),
                                 ("", "[machine][add][--][me@host]")):
                argv = mmini.add_rig_args(str(stub), "me@host", name, tmp)[9:]
                out = subprocess.run(argv, input="\n", capture_output=True, text=True, timeout=10)
                self.assertEqual(out.stdout.splitlines()[0], expect)
                self.assertIn("add server: hc ended with exit 3.", out.stdout)
                self.assertIn("This terminal can be closed: press enter.", out.stdout)
            # not reachable through the checks, but even so the script would run nothing of it
            marker = Path(tmp) / "ran"
            out = subprocess.run(["/bin/sh", "-c", mmini.ADD_RIG_SCRIPT, "add-server", str(stub), f"x; touch {marker}",
                                  f"$(touch {marker})"], input="\n", capture_output=True, text=True, timeout=10)
            self.assertIn(f"[--name][$(touch {marker})][--][x; touch {marker}]", out.stdout)
            self.assertFalse(marker.exists())


class EndTests(unittest.TestCase):
    """Ending terminals and forgetting rigs: the hc calls, in their order."""

    def test_end_steps_and_forget_args(self):
        self.assertEqual(mmini.end_steps("mmini/t5"), [("keep", "mmini/t5", "--off"), ("kill", "mmini/t5"),
                                                       ("wait", "mmini/t5", "--timeout", "15"), ("rm", "mmini/t5")])
        self.assertEqual(mmini.forget_args("vps"), ("machine", "rm", "vps"))

    def test_end_terminal_on_live_finished_and_gone_terminals(self):
        hc = FakeHc([term("t1"), term("t2")])
        mmini.end_terminal("t1", runner=hc)
        self.assertEqual(hc.calls, [("keep", "t1", "--off"), ("kill", "t1"), ("wait", "t1", "--timeout", "15"),
                                    ("rm", "t1")])
        self.assertEqual(([t["address"] for t in hc.terms], hc.finished), (["t2"], {}))
        hc.end("t2")  # finished already (it ended with its parent): keep refuses, the rest goes on
        hc.calls = []
        mmini.end_terminal("t2", runner=hc)
        self.assertEqual([c[0] for c in hc.calls], ["keep", "kill", "wait", "rm"])
        self.assertEqual(hc.finished, {})
        hc.calls = []
        mmini.end_terminal("t9", runner=hc)  # gone: nothing more to do
        self.assertEqual(hc.calls, [("keep", "t9", "--off")])

    def test_other_errors_reach_the_caller(self):
        def fail(*args, **kw):
            raise hc_error("unreachable", "cannot reach vps")

        with self.assertRaises(subprocess.CalledProcessError):
            mmini.end_terminal("vps/t1", runner=fail)
        self.assertEqual(mmini.error_kind(hc_error("live")), "live")
        self.assertEqual(mmini.error_kind(subprocess.CalledProcessError(1, "hc", stderr="junk")), "")
        self.assertEqual(mmini.error_kind(ValueError()), "")

    def test_ending_lists_the_children_that_end_too(self):
        terms = mmini.parse(ls(term("t1", name="web"), term("t2", name="kid"), term("t3", name="grandkid"),
                               term("t4", name="free"), term("t5", name="other")))
        infos = {"t2": mmini.Info("", "t1"), "t3": mmini.Info("", "t2"), "t4": mmini.Info("", "t1", False)}
        ends = mmini.ending([terms[0]], terms, infos)
        self.assertEqual([t.label for t in ends], ["web", "kid", "grandkid"])  # not the one with --outlive-parent
        self.assertEqual(mmini.ends_text(ends), "ends 3: web (zsh), kid (zsh), grandkid (zsh)")

    def test_confirm_matches(self):
        self.assertTrue(mmini.confirm_matches("dev", ("dev",)))
        self.assertTrue(mmini.confirm_matches(" dev ", ("Main", "dev")))
        for typed in ("", "de", "Dev", "dev2", "devx"):
            self.assertFalse(mmini.confirm_matches(typed, ("dev",)), typed)

    def test_neighbour(self):
        g = lambda k: mmini.Item("group", k, "")  # noqa: E731
        a = lambda k, t: mmini.Item("agent", k, t)  # noqa: E731
        sa, sb, sc, rr, rs = g("space:a"), g("space:b"), g("space:c"), g("rig:r"), g("rig:s")
        before = [sa, sb, sc, mmini.NEW_SPACE, rr, rs, mmini.ADD_RIG, a("space:a", "t1"), a("space:b", "t2"),
                  a("space:b", "t3"), a("space:b", "t4")]
        without = lambda *gone: [i for i in before if i not in gone]  # noqa: E731
        b_agents = [a("space:b", t) for t in ("t2", "t3", "t4")]
        self.assertEqual(mmini.neighbour(before, 1, without(sb, *b_agents)), sc)  # the next group
        self.assertEqual(mmini.neighbour(before, 2, without(sc)), sb)  # the last space: the space before, no rig
        self.assertEqual(mmini.neighbour(before, 4, without(rr)), rs)  # a rig: the next rig
        self.assertEqual(mmini.neighbour(before, 5, without(rs)), rr)
        self.assertEqual(mmini.neighbour(before, 4, without(rr, rs)), sc)  # no rig left: any group
        self.assertEqual(mmini.neighbour(before, 9, without(b_agents[1])), b_agents[2])  # the next agent of its group
        self.assertEqual(mmini.neighbour(before, 10, without(b_agents[2])), b_agents[1])  # the last: the one before
        self.assertEqual(mmini.neighbour(before, 7, without(a("space:a", "t1"))), sa)  # alone: its group
        self.assertEqual(mmini.neighbour(before, 7, without(sa, a("space:a", "t1"))), sb)  # group gone: next space
        self.assertIsNone(mmini.neighbour(before, 0, [mmini.NEW_SPACE, mmini.ADD_RIG]))
        self.assertIsNone(mmini.neighbour(before, 99, before))


class PromptLayoutTests(unittest.TestCase):
    def test_wrap_and_keep_what_to_type(self):
        title = "delete space dev? ends 3: tracker (claude-code), atlas (claude-code), t1f (zsh)."
        ask = "type dev to confirm:"
        full = mmini.prompt_lines(title, ask, 29, 8)
        self.assertEqual(full, ["delete space dev? ends 3:", "tracker (claude-code), atlas",
                                "(claude-code), t1f (zsh).", "type dev to confirm:"])
        cut = mmini.prompt_lines(title, ask, 29, 2)
        self.assertEqual(cut, [mmini.clip("delete space dev? ends 3: …", 29), ask])  # the cut is marked
        self.assertEqual(mmini.prompt_lines(title, ask, 29, 1), [ask])
        self.assertEqual(mmini.prompt_lines(title, ask, 29, 0), [])
        self.assertTrue(all(len(line) <= 10 for line in mmini.prompt_lines(title, ask, 10, 20)))

    def test_frame_gives_the_question_its_lines_and_the_list_two(self):
        f = mmini.sidebar_frame
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
        # the home machine is this Mac here (no terminal on "mmini"): "mmini" is in hc's machine list, without terminals
        self.hc = FakeHc(self.TERMS, machines=["vps", "mmini", "spare"])
        for target, value in ((mmini, {"run_hc": self.hc}), (mmini.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        mmini.write_servers_shown(True, self.state)  # these tests act on servers: the section is shown
        self.scr = FakeScr(30, 30)
        seen_done(self.state, self.hc.terms)
        self.side = mmini.Sidebar(self.scr, self.state, self.win)
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
            self.key(mmini.curses.KEY_MOUSE)

    def ends(self):
        return [c for c in self.hc.calls if c[0] in ("keep", "kill", "wait", "rm")]

    # rows ------------------------------------------------------------------------------------------------------
    def test_servers_from_hc_machine_ls_show_without_terminals(self):
        spaces, rigs = self.side.groups()
        self.assertEqual([g.key for g in spaces], ["space:home", "space:dev", "space:other"])
        self.assertEqual([(g.key, len(g.terms)) for g in rigs],  # this Mac is home: its row first, all its terminals
                         [("rig:this Mac", 5), ("rig:mmini", 0), ("rig:spare", 0), ("rig:vps", 1)])
        self.go(mmini.Item("group", "rig:spare", ""))
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

        with mock.patch.object(mmini, "run_hc", no_machine_list):
            self.side.refresh_once()
        self.assertEqual([g.key for g in self.side.groups()[1]], ["rig:this Mac", "rig:vps"])  # the last list stays
        self.assertEqual(self.side.error, "")  # without a red line: the terminals are what matters

    def test_plus_rows_are_rows_the_cursor_reaches_and_clicks_hit(self):
        lines = self.scr.lines()
        self.assertEqual(lines[4], " + new space")
        self.assertEqual(lines[5:8], ["", " servers", mmini.glyph(" ● this Mac")])  # the home machine first
        self.assertEqual(lines[11], " + add server")
        self.assertEqual((self.side.rows[4], self.side.rows[11]), (mmini.NEW_SPACE, mmini.ADD_RIG))
        self.go(mmini.Item("group", "space:other", ""))
        self.key("j")
        self.assertEqual(self.side.cursor, mmini.NEW_SPACE)
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
        self.assertEqual(self.scr.line(self.line_of(mmini.ADD_RIG)), " +")
        self.assertEqual(self.scr.line(self.line_of(mmini.NEW_SPACE)), " +")
        self.click(1, self.line_of(mmini.NEW_SPACE))
        self.assertEqual((self.side.mode, self.side.prompt.kind), ("open", "space"))  # opened, then asked

    # menu ------------------------------------------------------------------------------------------------------
    def test_a_opens_the_menu_of_the_cursor_row_and_keys_drive_it(self):
        self.go(mmini.Item("group", "space:dev", ""))
        self.key("a")
        menu = self.side.menu
        self.assertEqual([e.label for e in menu.entries],
                         ["Open", "New terminal here", "Rename", "Delete space", "Hide servers", "Hide agents",
                          "Hide dev servers"])
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
        self.assertEqual((self.side.cur, mmini.current_target(self.win)), ("space:dev", "t2"))

    def test_menu_in_the_strip_opens_the_sidebar_first(self):
        self.key("c")
        self.go(mmini.Item("agent", "space:dev", "t1"))
        self.key("a")
        self.assertEqual(self.side.mode, "open")
        self.assertEqual([e.action for e in self.side.menu.entries], ["open", "rename", "move", "end", "servers", "agents",
                                                                      "devs"])

    def test_right_click_opens_the_rows_menu_and_clicks_inside_and_outside(self):
        row = self.line_of(mmini.Item("group", "rig:vps", ""))
        self.click(5, row, 3)
        self.assertEqual(self.side.menu.item, mmini.Item("group", "rig:vps", ""))
        self.assertEqual(self.side.cursor, mmini.Item("group", "rig:vps", ""))
        self.assertEqual([e.label for e in self.side.menu.entries],
                         ["Open", "New terminal here", "Rename", "Forget server", "Hide servers", "Hide agents",
                          "Hide dev servers"])
        with pressed(5, row, 3):  # a double click's second press
            self.key(mmini.curses.KEY_MOUSE)
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
        self.click(5, self.line_of(mmini.Item("group", "space:other", "")), 3)
        self.click(5, self.side.menu_at.top)  # its border: nothing
        self.assertIsNotNone(self.side.menu)

    def test_a_menu_whose_row_has_gone_closes(self):
        self.go(mmini.Item("agent", "space:other", "t4"))
        self.key("a")
        self.hc.terms = [t for t in self.hc.terms if t["address"] != "t4"]
        self.side.refresh_once()
        self.side.draw()
        self.assertIsNone(self.side.menu)

    def test_menu_at_small_heights_and_narrow_widths(self):
        for item in (mmini.Item("group", "space:dev", ""), mmini.Item("agent", "space:dev", "t2"), mmini.ADD_RIG):
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
        self.go(mmini.ADD_RIG)
        self.key("e")
        self.assertEqual(self.side.notice.current(), "e: cursor on a space, server or agent first")
        self.key("d")
        self.assertEqual(self.side.notice.current(), "d: cursor on a space, server or agent first")
        self.key("n")  # on a "+" row: its own question
        self.assertEqual(self.side.prompt.kind, "rig_target")
        self.key(27)
        self.go(mmini.Item("group", "rig:mmini", ""))
        self.key("d")
        self.assertEqual(self.side.notice.current(), "d: mmini cannot be removed")
        self.assertIsNone(self.side.prompt)
        self.go(mmini.Item("agent", "space:dev", "t1"))
        self.key("d")
        self.assertEqual(self.side.prompt.kind, "delete")
        self.key(27, "e")
        self.assertEqual(self.side.prompt.title, "rename tracker to:")
        self.key(27, "m")
        self.assertEqual(self.side.prompt.kind, "move")

    # rename ----------------------------------------------------------------------------------------------------
    def test_rename_a_space_and_see_it_everywhere(self):
        self.go(mmini.Item("group", "space:dev", ""))
        self.key("e")
        self.assertEqual(self.scr.line(28), "> dev_")  # filled in: enter alone changes nothing
        self.key(21)  # ctrl+U
        self.type("Main")
        self.assertEqual(mmini.read_names(self.state), {"space:dev": "Main"})
        self.side.draw()
        lines = self.scr.lines()
        dev = lines[self.line_of(mmini.Item("group", "space:dev", ""))]
        self.assertEqual(dev, mmini.glyph("›● Main"))  # the sidebar row
        self.assertIn(mmini.glyph(" Main · 2"), lines)  # the agents heading
        self.key(10)  # open it: the tab bar's snapshot carries the display name
        snap = mmini.read_snapshot(self.win)
        self.assertEqual((snap["name"], snap["title"]), ("dev", "Main"))
        bar = mmini.TabBar(FakeScr(3, 60), self.win, self.state)
        bar.draw(snap, mmini.current_target(self.win))
        self.assertTrue(bar.s.scr.line(2).startswith(" Main"))
        self.key("n")  # a new shell still gets the space's own label
        self.assertEqual([c for c in self.hc.calls if c[0] == "run"][-1][-2:], ("--label", "space=dev"))
        self.key("c")  # the strip
        self.assertTrue(any(line.endswith("Main") for line in self.scr.lines()))
        self.key("o")
        self.go(mmini.Item("group", "space:dev", ""))
        self.key("e", 21, 10)  # an empty name removes the rename
        self.assertEqual(mmini.read_names(self.state), {})

    def test_rename_refuses_a_name_another_group_shows(self):
        self.go(mmini.Item("group", "space:dev", ""))
        self.key("e", 21)
        self.type("Other")
        self.assertEqual(self.side.notice.current(), "rename: Other is taken")
        self.assertEqual(mmini.read_names(self.state), {})
        self.key("e", 21)
        self.type("vps")  # a rig's shown name counts too
        self.assertEqual(self.side.notice.current(), "rename: vps is taken")

    def test_rename_a_rig_and_a_terminal(self):
        self.go(mmini.Item("group", "rig:vps", ""))
        self.key("e", 21)
        self.type("Harry")
        self.go(mmini.Item("agent", "space:dev", "t2"))
        self.key("e", 21)
        self.type("web")
        self.assertEqual(mmini.read_names(self.state), {"rig:vps": "Harry", "term:t2": "web"})
        lines = self.scr.lines()
        self.assertTrue(any(line.startswith(mmini.glyph(" ● Harry")) for line in lines), lines)
        self.assertTrue(any(line.startswith(mmini.glyph("  ● web")) for line in lines), lines)
        self.assertIn(mmini.glyph(" Harry · 1"), lines)
        self.go(mmini.Item("agent", "space:dev", "t1"))
        self.key("e", 21)
        self.type("WEB")
        self.assertEqual(self.side.notice.current(), "rename: WEB is taken")
        self.assertFalse(any(c[0] == "label" for c in self.hc.calls))  # nothing of hc changes

    def test_a_rename_in_another_window_shows_here(self):
        mmini.change_names({"space:other": "Side"}, self.state)
        self.side.draw()
        self.assertIn(mmini.glyph(" ● Side"), [line[:7] for line in self.scr.lines()])

    # add a rig -------------------------------------------------------------------------------------------------
    def test_add_rig_asks_twice_then_starts_a_terminal_on_this_mac_and_shows_it(self):
        self.go(mmini.ADD_RIG)
        with mock.patch.object(mmini, "focus_view") as focus:
            self.key(10)
            self.type("me@host:2222")
            self.assertEqual(self.side.prompt.kind, "rig_name")
            self.assertEqual(self.side.prompt.title, "name for me@host:2222 (empty = host)")
            self.type("harry")
        run = [c for c in self.hc.calls if c[0] == "run"][-1]
        self.assertEqual(list(run), mmini.add_rig_args(mmini.HC, "me@host:2222", "harry", str(Path.home())))
        address = mmini.current_target(self.win)
        self.assertEqual(self.side.group_of(address).key, "space:home")  # this Mac is the home machine here
        focus.assert_called_once()  # the keyboard goes there: the questions are answered in that terminal
        self.assertIn(self.side.cursor, (mmini.Item("agent", "space:home", address),
                                         mmini.Item("group", "space:home", "")))

    def test_add_rig_refuses_bad_input_before_hc(self):
        for target in ("x;rm -rf ~", "-oProxyCommand=x", "a b", "hоst"):
            self.go(mmini.ADD_RIG)
            self.key(10)
            self.side.prompt.text = target  # as if typed (the prompt itself takes ASCII only)
            self.key(10)
            self.assertEqual(self.side.notice.current(), "not a usable ssh target", target)
            self.assertIsNone(self.side.prompt)
        self.go(mmini.ADD_RIG)
        self.key(10)
        self.type("vps2")
        self.type("Bad Name")
        self.assertEqual(self.side.notice.current(), "name: a-z 0-9 _ -, a letter first, 32 at most")
        self.assertFalse(any(c[0] == "run" for c in self.hc.calls))

    # delete ----------------------------------------------------------------------------------------------------
    def test_delete_space_confirmation_text_and_a_wrong_name_cancels(self):
        self.go(mmini.Item("group", "space:dev", ""))
        self.key("d")
        p = self.side.prompt
        self.assertEqual(p.title, "delete space dev? ends 3: atlas (claude-code), t1f (zsh), tracker (claude-code).")
        self.assertEqual(p.ask, "type dev to confirm:")
        lines = self.scr.lines()  # the whole question above the typed line, the list keeps the rest
        self.assertEqual(lines[-6:-1], ["delete space dev? ends 3:", "atlas (claude-code), t1f",
                                        "(zsh), tracker (claude-code).", "type dev to confirm:", "> _"])
        self.type("de")
        self.assertEqual(self.side.notice.current(), "cancelled: the name did not match")
        self.assertEqual(self.ends(), [])
        self.assertEqual(len(self.side.groups()[0]), 3)

    def test_delete_space_ends_every_terminal_in_order_and_moves_on(self):
        mmini.change_names({"space:dev": "Main", "term:t1": "tr", "space:other": "Side"}, self.state)
        self.go(mmini.Item("group", "space:dev", ""))
        self.key(10)  # dev is the current group and its terminal is shown
        self.assertEqual(mmini.current_target(self.win), "t2")
        self.key("d")
        self.assertEqual(self.side.prompt.ask, "type Main to confirm:")
        self.type("Main")
        addresses = ["t2", "t3", "t1"]  # as listed: atlas, t1f, tr (shown names)
        self.assertEqual(self.ends(), [step for a in addresses for step in mmini.end_steps(a)])
        spaces, _ = self.side.groups()
        self.assertEqual([g.key for g in spaces], ["space:home", "space:other"])
        self.assertEqual(self.side.cursor, mmini.Item("group", "space:other", ""))  # the next group
        self.assertEqual(self.side.cur, "space:other")  # the current group went: its neighbour
        self.assertEqual(mmini.current_target(self.win), "t4")  # the view shows a terminal that still exists
        self.assertEqual(mmini.read_names(self.state), {"space:other": "Side"})  # its names went with it
        self.assertEqual(self.side.notice.current(), "")

    def test_delete_space_typing_its_own_name_works_too(self):
        mmini.change_names({"space:other": "Side"}, self.state)
        self.go(mmini.Item("group", "space:other", ""))
        self.key("d")
        self.type("other")
        self.assertEqual(self.ends(), mmini.end_steps("t4"))
        self.assertEqual(self.side.cursor, mmini.Item("group", "space:dev", ""))  # the last space: the one before

    def test_end_terminal_lists_children_and_shows_a_sibling(self):
        self.hc.infos["t3"] = {"parent": "t1"}  # t1f was started from tracker: it ends with it
        self.side.refresh_once(full=True)
        self.go(mmini.Item("agent", "space:dev", "t1"))
        self.key(10)
        self.assertEqual(mmini.current_target(self.win), "t1")
        self.key("d")
        p = self.side.prompt
        self.assertEqual((p.title, p.ask), ("end tracker? ends 2: tracker (claude-code), t1f (zsh).",
                                            "type tracker to confirm:"))
        self.type("tracker")
        self.assertEqual(self.ends(), mmini.end_steps("t1") + mmini.end_steps("t3"))
        self.assertEqual(self.hc.finished, {})  # removed, not left as finished terminals
        self.assertEqual(self.side.cursor, mmini.Item("agent", "space:dev", "t2"))  # the agent before it
        self.assertEqual(mmini.current_target(self.win), "t2")  # dev still has a terminal: shown

    def test_end_an_unnamed_terminal_by_its_address_and_the_last_one_leaves_nothing(self):
        self.hc.terms.append(term("t20", "/Users/x/dev/solo", "python3"))
        self.side.refresh_once()
        self.go(mmini.Item("agent", "space:solo", "t20"))
        self.key(10)
        self.key("d")
        self.assertEqual(self.side.prompt.ask, "type t20 to confirm:")
        self.type("t20")
        self.assertEqual(self.ends(), mmini.end_steps("t20"))
        self.assertNotIn("space:solo", [g.key for g in self.side.everything()])
        self.assertEqual(self.side.cursor, mmini.Item("group", "space:other", ""))  # no group left of it: neighbour
        self.assertEqual(self.side.cur, "space:other")
        self.assertEqual(mmini.current_target(self.win), "t4")

    def test_ending_the_shown_terminal_of_a_group_with_nothing_left_shows_nothing(self):
        self.hc.terms = [term("t1", "/Users/x/dev", "claude-code", "only", "idle")]
        self.hc.machines = []
        self.side.refresh_once()
        self.go(mmini.Item("agent", "space:dev", "t1"))
        self.key(10, "d")
        self.type("only")
        self.assertEqual(mmini.current_target(self.win), "")  # the view says to pick a terminal
        self.assertEqual(self.side.everything(), [])

    def test_a_failed_end_says_so_and_the_others_still_end(self):
        real = self.hc.__call__

        def flaky(*args, **kw):
            if args[:2] == ("kill", "t3"):
                raise hc_error("unreachable", "core went away")
            return real(*args, **kw)

        self.go(mmini.Item("group", "space:dev", ""))
        self.key("d")
        with mock.patch.object(mmini, "run_hc", flaky):
            self.type("dev")
        self.assertEqual(self.side.notice.current(), "end: 1 of 3 failed, t3: core went away")
        self.assertTrue(self.side.notice.bad)
        self.assertIn(("rm", "t1"), self.hc.calls)

    def test_forget_server(self):
        mmini.change_names({"rig:vps": "Harry", "space:dev": "Main"}, self.state)
        self.go(mmini.Item("group", "rig:vps", ""))
        self.key("d")
        p = self.side.prompt
        self.assertEqual((p.title, p.ask), ("forget server Harry? its terminals keep running there.",
                                            "type Harry to confirm:"))
        self.type("vps")  # its hc name works too
        self.assertIn(("machine", "rm", "vps"), self.hc.calls)
        self.assertEqual(self.ends(), [])  # its terminals are not ended
        self.assertNotIn("rig:vps", [g.key for g in self.side.everything()])
        self.assertEqual(mmini.read_names(self.state), {"space:dev": "Main"})
        self.assertEqual(self.side.cursor, mmini.Item("group", "rig:mmini", ""))  # the next server

    def test_forget_needs_the_name_and_never_offers_this_mac_or_home(self):
        self.go(mmini.Item("group", "rig:vps", ""))
        self.key("d")
        self.type("vp")
        self.assertNotIn(("machine", "rm", "vps"), self.hc.calls)
        self.assertEqual(self.side.notice.current(), "cancelled: the name did not match")
        self.hc.terms.append(term("mmini/t1", "/Users/x/dev"))  # now mmini is home; this Mac another server
        self.side.refresh_once()
        for key in ("rig:this Mac", "rig:mmini"):
            self.go(mmini.Item("group", key, ""))
            self.key("a")
            self.assertEqual([e.action for e in self.side.menu.entries], ["open", "new", "rename", "servers", "agents",
                                                                          "devs"])
            self.key(27, "d")
            self.assertEqual(self.side.notice.current(), f"d: {key[4:]} cannot be removed")
            self.assertIsNone(self.side.prompt)


class ScriptTests(unittest.TestCase):
    def test_shell_syntax(self):
        for name in ("view.sh", "build.sh"):
            out = subprocess.run(["/bin/sh", "-n", str(ROOT / name)], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)

    def test_build_keeps_the_install_line_and_never_edits_the_ghostty_config(self):
        text = (ROOT / "build.sh").read_text()
        self.assertIn("git clone https://github.com/PerIPan/herdr-core-ghostty-UI ~/.local/share/mmini && "
                      "sh ~/.local/share/mmini/build.sh", text)
        self.assertIn("git -C ~/.local/share/mmini pull && sh ~/.local/share/mmini/build.sh", text)
        self.assertIn("focus-follows-mouse", text)
        for line in text.splitlines():
            if "ghostty/config" in line or "com.mitchellh.ghostty" in line or '"$c"' in line:
                self.assertNotRegex(line, r">>|>\s*\"?\$c|tee|sed -i")

    def test_build_reads_all_four_config_files_and_the_hint_names_its_limit(self):
        text = (ROOT / "build.sh").read_text()
        loop = next(line for line in text.splitlines() if line.startswith("for c in "))
        self.assertEqual(loop.rstrip("; do").split()[3:],
                         ['"$xdg/config"', '"$xdg/config.ghostty"', '"$mac/config"', '"$mac/config.ghostty"'])
        hint = text[text.index("mmini: hint:"):]
        self.assertIn('echo "    focus-follows-mouse = true"', hint)
        self.assertIn("keyboard then follows the pointer", hint)

    def test_config_check_finds_the_setting_in_either_file_name(self):
        text = (ROOT / "build.sh").read_text()
        check = text[text.index("# --- Ghostty settings"):]  # the last part: reads the config files, prints hints
        cases = (({}, True), ({"config": "focus-follows-mouse = true\n"}, False),
                 ({"config.ghostty": ' focus-follows-mouse="true"\n'}, False),
                 ({"config": "focus-follows-mouse = true\n", "config.ghostty": "focus-follows-mouse = false\n"}, True),
                 ({"config.ghostty": "# focus-follows-mouse = true\nfont-size = 12\n"}, True))
        for files, hinted in cases:
            with tempfile.TemporaryDirectory() as home:
                folder = Path(home) / ".config" / "ghostty"
                folder.mkdir(parents=True)
                for name, body in files.items():
                    (folder / name).write_text(body)
                before = {f.name: f.read_text() for f in folder.iterdir()}
                out = subprocess.run(["/bin/sh", "-euc", check], capture_output=True, text=True,
                                     env={"HOME": home, "PATH": "/usr/bin:/bin"})
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual("    focus-follows-mouse = true" in out.stdout, hinted, files)
                self.assertEqual({f.name: f.read_text() for f in folder.iterdir()}, before)  # read only

    def test_launcher_waits_for_ghosttys_own_split_focus_before_focusing_the_sidebar(self):
        lines = [line.strip() for line in (ROOT / "build.sh").read_text().splitlines()]
        focus = lines.index("focus sideTerm")
        delay = lines.index("tell current application to delay 0.8")
        self.assertLess(delay, focus)
        self.assertTrue(all(line.startswith("--") or line == "try" for line in lines[delay + 1:focus]))
        self.assertLess(max(i for i, line in enumerate(lines) if line.startswith("set tabsTerm to split")), focus)

    def test_launcher_focus_falls_back_to_the_view_when_the_sidebar_is_gone(self):
        lines = [line.strip() for line in (ROOT / "build.sh").read_text().splitlines()]
        focus = lines.index("focus sideTerm")
        self.assertEqual(lines[focus - 1], "try")  # a sidebar started hidden has ended: its pane is gone
        self.assertEqual(lines[focus + 1:focus + 4], ["on error", "focus viewTerm", "end try"])

    def test_launcher_panes_close_when_their_program_ends(self):
        lines = [line.strip() for line in (ROOT / "build.sh").read_text().splitlines()]

        def typed(name):
            return next(line for line in lines if line.startswith(f"set initial input of {name} to"))

        for name, mode in (("sideCfg", "sidebar"), ("tabsCfg", "tabs")):
            self.assertIn('to "exec " & pre & "python3 " & (quoted form of (base & "mmini.py"))', typed(name))
            self.assertTrue(typed(name).endswith(f'& " {mode}" & linefeed'), typed(name))
        self.assertNotIn("exec", typed("viewCfg"))  # the view's command stays as it was
        self.assertIn('set pre to "env MMINI_WINDOW=" & (quoted form of winDir) & " "', lines)

    def test_build_header_says_what_to_expect_of_the_three_states(self):
        text = (ROOT / "build.sh").read_text()
        header = text[:text.index("set -eu")].lower()
        for words in ("open, strip and hidden", "q now closes the sidebar's pane", "a click on \"›\"", "untested",
                      "bringing the sidebar back at full height"):
            self.assertIn(words, header)

    def test_build_header_says_what_to_expect_of_the_menu(self):
        text = (ROOT / "build.sh").read_text()
        header = " ".join(text[:text.index("set -eu")].lower().replace("#", " ").split())
        for words in ("the key a, or a right click on the row", "ghostty may show its own context menu instead",
                      "the key a always works", "a delete asks for the name first", "runs `hc machine add`",
                      "a right click in ghostty", "adding and forgetting a real machine"):
            self.assertIn(words, header)
        readme = " ".join((ROOT / "README.md").read_text().split())
        for words in ("A delete asks for the name to be typed first", "names.json",
                      "A right click may open Ghostty's own menu instead of mmini's"):
            self.assertIn(words, readme)


class ServerTests(unittest.TestCase):
    """The servers section: user@host names, the home machine's row, hidden by default, v and the menu switch. The
    terminals and machines are a laptop's: the home machine "mmini" and the machine "rig" (a guest account on the
    same machine)."""

    TERMS = [term("mmini/t1", "/Users/x/dev/atlas", "claude-code", "atlas", "idle"),
             term("mmini/t2", "/Users/x/dev/tracker", "claude-code", "tracker", "working"),
             term("mmini/t3", "/Users/x/dev/tracker", "zsh", "sh"),
             term("rig/t1", "/Users/guest", "claude-code", "harry", "idle")]
    MACHINES = [("mmini", "me@mini"), ("rig", "guest@mini")]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"
        self.hc = FakeHc(self.TERMS, machines=self.MACHINES)
        for target, value in ((mmini, {"run_hc": self.hc, "FIRST": "mmini"}),
                              (mmini.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scr = FakeScr(24, 30)
        seen_done(self.state, self.hc.terms)
        self.side = mmini.Sidebar(self.scr, self.state, self.win)
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
        label = mmini.server_label
        M = mmini.Machine
        self.assertEqual(label(M("mmini", "me@mini")), "me@mini")
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
        terms = mmini.parse(ls(*self.TERMS))
        machines = mmini.parse_machines(self.hc("machine", "ls", "--json"))
        spaces, rigs = mmini.build_groups(terms, "mmini", {}, machines)
        self.assertEqual([(g.key, g.shown, g.home, len(g.terms)) for g in rigs],
                         [("rig:mmini", "me@mini", True, 3), ("rig:rig", "guest@mini", False, 1)])
        self.assertEqual([g.name for g in spaces], ["atlas", "tracker"])
        _, rigs = mmini.build_groups(terms, "mmini", {}, machines, {"rig:rig": "Harry"})
        self.assertEqual([g.shown for g in rigs], ["me@mini", "Harry"])  # names.json wins
        self.assertEqual([g.own for g in rigs], ["me@mini", "guest@mini"])
        _, rigs = mmini.build_groups(terms, "mmini", {}, [mmini.Machine("mmini", "mmini"), "rig"])
        self.assertEqual([g.shown for g in rigs], ["mmini", "rig"])  # a bare Host, or no target known: the name
        # this Mac only while it runs terminals; the home machine's agents are listed once, under their spaces
        self.assertNotIn("rig:" + mmini.LOCAL, [g.key for g in rigs])
        items = mmini.selectable_items(spaces, rigs)
        self.assertEqual([i.address for i in items if i.kind == "agent"], ["mmini/t1", "mmini/t2", "rig/t1"])

    # hidden by default -----------------------------------------------------------------------------------------
    def test_hidden_by_default_then_v_shows_them(self):
        lines = self.scr.lines()
        self.assertFalse((self.state / "servers").exists())
        self.assertFalse(self.side.servers_shown())
        self.assertEqual(lines[:5], [" spaces", mmini.glyph("›● atlas"), mmini.glyph(" ● tracker"), " + new space", ""])
        text = "\n".join(lines)
        for gone in ("servers", "me@mini", "guest@mini", "add server", "harry"):
            self.assertNotIn(gone, text)
        self.assertEqual(self.side.groups()[1], [])
        self.key("v")
        lines = self.scr.lines()
        self.assertEqual(mmini.read_text(self.state / "servers"), "shown")
        self.assertEqual(lines[4:10], ["", " servers", mmini.glyph(" ● me@mini"),
                                       mmini.glyph(" ● guest@mini"), " + add server", ""])
        self.assertIn(mmini.glyph(" guest@mini · 1"), lines)  # the server's agents come back
        self.assertEqual(self.side.cursor, mmini.Item("group", "rig:mmini", ""))
        self.assertEqual(self.side.notice.current(), "servers shown (v hides them)")
        self.key("V")
        self.assertEqual(mmini.read_text(self.state / "servers"), "hidden")
        self.assertNotIn("servers", "\n".join(self.scr.lines()[:-2]))

    def test_the_switch_in_every_menu_and_for_every_window(self):
        for item in (mmini.Item("group", "space:atlas", ""), mmini.Item("agent", "space:atlas", "mmini/t1"),
                     mmini.NEW_SPACE):
            self.go(item)
            self.key("a")
            self.assertEqual(self.side.menu.entries[-3].label, "Show servers", item)
            self.key(27)
        self.key("a", "v")  # its letter in the menu
        self.assertTrue(self.side.servers_shown())
        other = mmini.Sidebar(FakeScr(24, 30), self.state, self.state / "w-2")  # another window
        other.refresh_once()
        self.assertEqual([g.key for g in other.groups()[1]], ["rig:mmini", "rig:rig"])
        self.go(mmini.ADD_RIG)
        self.key("a")
        self.assertEqual([e.label for e in self.side.menu.entries],
                         ["Add server", "Hide servers", "Hide agents", "Hide dev servers"])
        self.key("j", 10)
        self.assertFalse(self.side.servers_shown())
        self.assertEqual(other.groups()[1], [])  # the other window follows the shared file

    def test_hiding_while_a_server_is_current_falls_back(self):
        self.key("v")
        self.go(mmini.Item("group", "rig:rig", ""))
        with mock.patch.object(mmini, "focus_view"):
            self.key(10)
        self.assertEqual((self.side.cur, mmini.current_target(self.win)), ("rig:rig", "rig/t1"))
        self.key("v")
        # the first space with an agent, and its terminal: nothing on screen could reach rig/t1 any more
        self.assertEqual((self.side.cur, mmini.current_target(self.win)), ("space:atlas", "mmini/t1"))
        self.assertEqual(mmini.read_snapshot(self.win)["group"], "space:atlas")
        self.assertEqual(self.side.cursor_item(), mmini.Item("group", "space:atlas", ""))

    def test_hiding_keeps_a_space_terminal_shown_from_the_home_row(self):
        self.key("v")
        self.go(mmini.Item("group", "rig:mmini", ""))
        with mock.patch.object(mmini, "focus_view"):
            self.key(10)
        snap = mmini.read_snapshot(self.win)
        self.assertEqual(snap["title"], "me@mini")
        self.assertEqual([t["label"] for t in snap["tabs"]], ["atlas", "sh", "tracker"])  # the whole machine
        mmini.show("mmini/t3", self.win)  # the tab bar picks "sh" (space tracker)
        self.side.sync()
        self.assertEqual(self.side.cur, "rig:mmini")  # the row stays current
        self.assertEqual(mmini.read_last(self.state)["rig:mmini"], "mmini/t3")  # and remembers it
        self.key("v")
        self.assertEqual((self.side.cur, mmini.current_target(self.win)), ("space:tracker", "mmini/t3"))

    def test_hidden_in_another_window_falls_back_at_the_next_sync(self):
        self.key("v")
        self.go(mmini.Item("group", "rig:rig", ""))
        with mock.patch.object(mmini, "focus_view"):
            self.key(10)
        mmini.write_servers_shown(False, self.state)  # another window's v
        self.side.sync()
        self.assertEqual(self.side.cur, "space:atlas")  # the usual fall-back rule; that window's view is its own

    def test_the_home_row_menu_and_keys(self):
        self.key("v")
        home = mmini.Item("group", "rig:mmini", "")
        self.go(home)
        self.key("a")
        self.assertEqual([e.label for e in self.side.menu.entries],
                         ["Open", "New terminal here", "Rename", "Hide servers", "Hide agents",
                          "Hide dev servers"])  # never Forget
        self.key(27, "d")
        self.assertEqual(self.side.notice.current(), "d: me@mini cannot be removed")
        self.assertIsNone(self.side.prompt)
        self.key("e")
        self.assertEqual((self.side.prompt.title, self.side.prompt.text), ("rename me@mini to:", "me@mini"))
        self.key(21)
        self.type("Mini")
        self.assertEqual(mmini.read_names(self.state), {"rig:mmini": "Mini"})
        self.assertIn(mmini.glyph(" ● Mini"), self.scr.lines())
        self.go(home)
        self.key("e", 21)
        self.type("me@mini")  # its own user@host removes the rename
        self.assertEqual(mmini.read_names(self.state), {})
        agents = [line for line in self.scr.lines() if "atlas" in line and "idle" in line]
        self.assertEqual(len(agents), 1)  # listed once, under its space
        self.go(home)
        self.key("n")
        self.assertEqual([c for c in self.hc.calls if c[0] == "run"][-1][:6],
                         ("run", "--bg", "--json", "--no-parent", "--on", "mmini"))
        self.assertEqual(self.side.cur, "rig:mmini")  # the new shell is shown in the row it was started from

    def test_forget_a_server_by_its_user_at_host(self):
        self.key("v")
        self.go(mmini.Item("group", "rig:rig", ""))
        self.key("d")
        p = self.side.prompt
        self.assertEqual((p.title, p.ask), ("forget server guest@mini? its terminals keep running there.",
                                            "type guest@mini to confirm:"))
        self.type("guest@mini")
        self.assertIn(("machine", "rm", "rig"), self.hc.calls)
        self.assertEqual([g.key for g in self.side.groups()[1]], ["rig:mmini"])

    def test_no_user_facing_rig_word(self):
        self.key("v")
        drawn = []
        for item in self.side.items():
            self.go(item)
            self.key("a")
            drawn += self.scr.lines()
            self.key(27)
        for item in (mmini.ADD_RIG, mmini.Item("group", "space:atlas", ""), mmini.Item("group", "rig:rig", "")):
            self.go(item)
            self.key("e", 27, "d", 27, "m", 27)
            drawn += self.scr.lines() + [self.side.notice.current()]
        self.assertIsNone(re.search(r"\brigs?\b", "\n".join(drawn)), "\n".join(drawn))
        # every text mmini.py says (notices, prompts, menu labels, the add terminal's lines), from its source
        said = re.findall(r'(?:say|Prompt|Entry|echo)\(?[^\n]*?"([^"\n]*)"', (ROOT / "mmini.py").read_text())
        self.assertTrue(said)
        self.assertEqual([t for t in said if re.search(r"\brigs?\b", t) and not t.startswith(("rig_", "rig:"))], [])


class HelpTests(unittest.TestCase):
    """"?": the list of keys over the sidebar, closed by any key or click; the dim "?" on the last line."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"
        self.hc = FakeHc(SidebarLogicTests.TERMS)
        for target, value in ((mmini, {"run_hc": self.hc}), (mmini.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scr = FakeScr(24, 30)
        seen_done(self.state, self.hc.terms)
        self.side = mmini.Sidebar(self.scr, self.state, self.win)
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
            self.key(mmini.curses.KEY_MOUSE)

    def test_question_mark_shows_the_list_and_any_key_closes_it_without_acting(self):
        self.assertEqual(self.scr.line(23), fold_line("open"))
        self.assertEqual(self.side.help_x, 28)
        self.key("?")
        lines = self.scr.lines()
        self.assertEqual(lines[:len(mmini.help_lines(29, 24))], mmini.help_lines(29, 24))
        self.assertEqual(self.side.rows, {})  # nothing under it can be clicked
        cursor = self.side.cursor
        self.key("j")  # closes, does not move
        self.assertFalse(self.side.help)
        self.assertEqual(self.side.cursor, cursor)
        self.assertEqual(self.scr.line(0), " spaces")
        self.key("?", "q")  # q closes the list, it does not hide the sidebar
        self.assertFalse(self.side.help)
        self.assertEqual(mmini.read_sidebar_state(self.state), "open")
        self.key("?", mmini.curses.KEY_RESIZE)  # a size change is no key
        self.assertTrue(self.side.help)

    def test_a_click_on_the_dim_question_mark_opens_it_and_a_click_closes_it(self):
        self.click(27, 23)  # the "‹" line beside the "?": c's step, as before
        self.assertEqual(self.side.mode, "strip")
        self.key("o")
        self.click(self.side.help_x, 23)
        self.assertTrue(self.side.help)
        self.assertEqual(self.side.mode, "open")
        with pressed(self.side.help_x, 23, 1):
            self.key(mmini.curses.KEY_MOUSE)  # a double click's second press: it stays open
        self.assertTrue(self.side.help)
        with mouse_at(0, 0, RELEASE1):
            self.side.mouse_quiet = 0.0
            self.key(mmini.curses.KEY_MOUSE)  # a button let go: no click
        self.assertTrue(self.side.help)
        target = mmini.current_target(self.win)
        self.click(5, 2)  # on a row under the list: closes it, opens nothing
        self.assertFalse(self.side.help)
        self.assertEqual(mmini.current_target(self.win), target)

    def test_in_the_strip_it_opens_the_sidebar_first_and_draws_no_question_mark(self):
        self.key("c")
        self.assertEqual(self.side.help_x, -1)
        self.assertNotIn("?", self.scr.line(23))
        self.key("?")
        self.assertEqual((self.side.mode, self.side.help), ("open", True))

    def test_the_question_mark_needs_room_beside_the_label(self):
        self.assertEqual(mmini.help_column(" ‹ fold", 30), 28)
        self.assertEqual(mmini.help_column(" ‹ fold", 10), 8)
        self.assertEqual(mmini.help_column(" ‹ fold", 9), -1)  # it would touch the word
        self.assertEqual(mmini.sidebar_hit(23, 23, -1, {}, 28, 28), ("help", None))
        self.assertEqual(mmini.sidebar_hit(23, 23, -1, {}, 27, 28), ("step", None))
        self.assertEqual(mmini.sidebar_hit(23, 23, -1, {}, 28, -1), ("step", None))

    def test_small_panes_do_not_crash(self):
        for height in range(0, 8):
            for width in (1, 2, 5, 12, 30):
                self.scr.height, self.scr.width = height, width
                self.side.help = True
                self.side.draw()
                self.assertTrue(all(len(line) <= max(0, width - 1) for line in self.scr.lines()))

    def test_tab_bar_question_mark_says_its_keys(self):
        bar = mmini.TabBar(FakeScr(5, 120), self.win, self.state)
        bar.handle_key(ord("?"), None, "")
        self.assertEqual(bar.notice.current(), "keys: ←→ h l switch · enter ↓ focus · z zoom · ⌘⇧↵ back")
        bar.alone = True
        bar.handle_key(ord("?"), None, "")
        self.assertEqual(bar.notice.current(), "keys: c o sidebar · ←→ h l switch · enter ↓ focus · z zoom · ⌘⇧↵ back")
        self.assertEqual(mmini.TAB_HINTS_ALONE[0], "c sidebar  ←→ switch  enter focus  z zoom  ⌘⇧↵ back")  # stays


class DragTests(unittest.TestCase):
    """A dragged divider is kept; a resized window is not (the sidebar sizes itself again)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"
        self.hc = FakeHc(SidebarLogicTests.TERMS)
        self.goals = []

        def fake(mode, win, goal):  # the loop reaches its goal; the pane is that wide then
            self.goals.append(goal())
            self.scr.width = goal()
            return goal(), goal()

        for target, value in ((mmini, {"run_hc": self.hc, "autosize": fake, "autosize_enabled": lambda: True}),
                              (mmini.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scr = FakeScr(24, 60)
        seen_done(self.state, self.hc.terms)
        self.side = mmini.Sidebar(self.scr, self.state, self.win)
        self.side.refresh_once()
        self.side.start_autosize()  # as run() does
        self.join()

    def join(self):
        if self.side.sizer is not None:
            self.side.sizer.join(5)

    def tabs(self, cols):
        mmini.write_atomic(self.win / "tabs.cols", f"{cols}\n")

    def quiet(self):
        """The size has been quiet for a while since the last loop or change: the sidebar takes its measure."""
        self.side.sized_when = time.monotonic() - 2 * mmini.REFIT_QUIET
        self.side.refit()

    def resize(self, side, tabs):
        """Ghostty resized both panes; quiet since then."""
        self.scr.width = side
        self.tabs(tabs)
        self.side.resized = time.monotonic() - 2 * mmini.REFIT_QUIET
        self.side.refit()
        self.join()

    def test_resize_kind(self):
        k = mmini.resize_kind
        self.assertEqual(k((30, 90), (45, 75)), "drag")  # opposite directions, the sum stays
        self.assertEqual(k((30, 90), (20, 101)), "drag")  # within a column of rounding
        self.assertEqual(k((30, 90), (31, 89)), "none")
        self.assertEqual(k((30, 90), (60, 150)), "window")  # both grew
        self.assertEqual(k((30, 90), (30, 60)), "window")
        self.assertEqual(k(None, (45, 75)), "window")  # nothing known to compare with: as before
        self.assertEqual(k((30, 0), (45, 75)), "window")
        self.assertEqual(k((30, 90), (45, 0)), "window")

    def test_a_drag_is_kept_and_remembered_a_window_change_is_not(self):
        self.assertEqual(self.goals, [30])
        self.tabs(90)
        self.quiet()
        self.assertEqual(self.side.layout_seen, (30, 90))
        self.resize(45, 75)  # the divider dragged to 45 columns
        self.assertEqual(self.goals, [30])  # not snapped back
        self.assertEqual((self.side.open_width, self.side.width_goal()), (45, 45))
        self.assertEqual(mmini.read_text(self.state / "width"), "45")
        self.side.refit()
        self.assertEqual(self.goals, [30])  # and not later either
        self.resize(90, 150)  # the window grew: back to the dragged width
        self.assertEqual(self.goals, [30, 45])
        self.assertIsNone(self.side.layout_seen)  # the loop moved the divider: measured again once quiet
        self.quiet()
        self.assertEqual(self.side.layout_seen, (45, 150))
        again = mmini.Sidebar(FakeScr(24, 30), self.state, self.state / "w-2")  # the next window
        self.assertEqual(again.width_goal(), 45)

    def test_without_the_tab_bars_width_every_change_is_a_window_change(self):
        self.quiet()  # no tabs.cols: a tab bar that never wrote it
        self.resize(45, 0)
        self.assertEqual(self.goals, [30, 30])
        self.assertFalse((self.state / "width").exists())

    def test_a_change_before_the_first_quiet_moment_counts_as_a_window_change(self):
        self.tabs(90)
        self.resize(45, 75)  # no quiet moment since the loop: nothing to compare with
        self.assertEqual(self.goals, [30, 30])

    def test_a_dragged_strip_lasts_until_the_next_state_change(self):
        self.tabs(90)
        self.key_c()
        self.assertEqual(self.goals[-1], mmini.NARROW)
        self.tabs(114)
        self.quiet()
        self.resize(20, 100)  # dragged
        self.assertEqual((self.side.width_goal(), self.goals[-1]), (20, mmini.NARROW))
        self.assertFalse((self.state / "width").exists())  # only an open width is kept for later
        self.side.on_key(ord("o"))
        self.join()
        self.assertEqual((self.side.strip_width, self.goals[-1]), (0, 30))
        self.side.on_key(ord("c"))
        self.join()
        self.assertEqual(self.goals[-1], mmini.NARROW)

    def key_c(self):
        self.side.on_key(ord("c"))
        self.join()

    def test_the_open_width_file(self):
        self.assertEqual(mmini.read_open_width(self.state), mmini.WIDTH)
        for junk in ("", "x", "9", "201", "-5", "3.5"):
            mmini.write_atomic(self.state / "width", junk + "\n")
            self.assertEqual(mmini.read_open_width(self.state), mmini.WIDTH, junk)
        self.assertEqual(mmini.write_open_width(5, self.state), 10)
        self.assertEqual(mmini.read_open_width(self.state), 10)
        self.assertEqual(mmini.write_open_width(44, self.state), 44)
        self.assertEqual(mmini.read_open_width(self.state), 44)
        self.side.on_key(ord("c"))
        self.join()
        self.side.on_key(ord("o"))  # dragged in another window meanwhile: the next open takes it
        self.join()
        self.assertEqual(self.goals[-1], 44)

    def test_the_tab_bar_writes_its_width_when_it_changes(self):
        scr = FakeScr(5, 90)
        bar = mmini.TabBar(scr, self.win, self.state)
        with mock.patch.object(mmini, "write_atomic", wraps=mmini.write_atomic) as write:
            bar.note_width()
            bar.note_width()
            scr.width = 75
            bar.note_width()
        self.assertEqual(write.call_count, 2)
        self.assertEqual(mmini.read_tabs_cols(self.win), 75)
        mmini.write_atomic(self.win / "tabs.cols", "junk\n")
        self.assertEqual(mmini.read_tabs_cols(self.win), 0)


class PaneTitleTests(unittest.TestCase):
    """The title "mmini" and no folder icon: OSC 2, then an empty OSC 7, from all three panes."""

    def test_the_sequence(self):
        self.assertEqual(mmini.PANE_TITLE, "\x1b]2;mmini\x07\x1b]7;\x07")

    def test_claim_pane_writes_only_to_a_terminal(self):
        import pty
        master, slave = pty.openpty()
        try:
            mmini.claim_pane(slave)
            self.assertEqual(os.read(master, 100), mmini.PANE_TITLE.encode())
        finally:
            os.close(master)
            os.close(slave)
        r, w = os.pipe()
        try:
            mmini.claim_pane(w)  # not a terminal: nothing
            os.close(w)
            self.assertEqual(os.read(r, 100), b"")
        finally:
            os.close(r)
        mmini.claim_pane(9999)  # a closed descriptor: no error

    def test_view_sh_sends_it_at_start_and_before_and_after_each_attach(self):
        text = (ROOT / "view.sh").read_text()
        own = text[text.index("own_title() {"):text.index("}", text.index("own_title() {"))]
        self.assertEqual(own.split("\n")[1:3], ['  set_title "$1"', "  printf '\\033]7;\\007'"])  # OSC 2 first
        self.assertIn("tt=mmini", text)  # nothing shown: "mmini"
        body = text[text.index("clean_screen() {"):text.index("}", text.index("clean_screen() {"))]
        self.assertIn('own_title "$target"', body)
        self.assertIn('[ "$on_tty" = 1 ] && own_title "$target"', text)
        loop = text[text.index("while :; do\n  read_gen"):]
        self.assertLess(loop.index('own_title "$target"'), loop.index('"$hc" attach'))


class GhosttyHintTests(unittest.TestCase):
    """build.sh's last words: the two Ghostty settings mmini cannot set per window, with the exact lines."""

    def run_check(self, files, folder=".config/ghostty"):
        text = (ROOT / "build.sh").read_text()
        check = text[text.index("# --- Ghostty settings"):]
        with tempfile.TemporaryDirectory() as home:
            where = Path(home) / folder
            where.mkdir(parents=True)
            for name, body in files.items():
                (where / name).write_text(body)
            before = {f.name: f.read_text() for f in where.iterdir()}
            out = subprocess.run(["/bin/sh", "-euc", check], capture_output=True, text=True,
                                 env={"HOME": home, "PATH": "/usr/bin:/bin"})
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual({f.name: f.read_text() for f in where.iterdir()}, before)  # read only
            return out.stdout.replace(home, "~")

    def test_both_lines_when_neither_is_set(self):
        out = self.run_check({})
        self.assertIn("mmini: hint: add these lines to the Ghostty config (~/.config/ghostty/config.ghostty), then "
                      "reload it in Ghostty (cmd+shift+,):", out)
        self.assertIn("\n    focus-follows-mouse = true\n    macos-titlebar-proxy-icon = hidden\n", out)
        self.assertTrue(out.rstrip().endswith("never edits the config."))

    def test_only_what_is_missing_in_the_file_that_counts(self):
        out = self.run_check({"config": "focus-follows-mouse = true\n"})
        self.assertNotIn("focus-follows-mouse = true", out)
        self.assertIn("    macos-titlebar-proxy-icon = hidden", out)
        self.assertIn("(~/.config/ghostty/config)", out)
        out = self.run_check({"config": "macos-titlebar-proxy-icon = hidden\nfocus-follows-mouse = true\n"})
        self.assertEqual(out, "")
        out = self.run_check({"config.ghostty": 'macos-titlebar-proxy-icon = "hidden"\n'},
                             "Library/Application Support/com.mitchellh.ghostty")
        self.assertIn("    focus-follows-mouse = true", out)
        self.assertNotIn("proxy-icon = hidden", out)
        self.assertIn("(~/Library/Application Support/com.mitchellh.ghostty/config.ghostty)", out)

    def test_the_hints_are_the_last_thing_build_sh_prints(self):
        text = (ROOT / "build.sh").read_text()
        after = text[text.index("# --- Ghostty settings"):]
        before = text[:text.index("# --- Ghostty settings")]
        self.assertIn('echo "built $app', before)
        self.assertNotIn("osacompile", after)
        self.assertIn("focus-follows-mouse = true", after)
        self.assertIn("macos-titlebar-proxy-icon = hidden", after)


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
        for target, value in ((mmini, {"run_hc": self.hc, "FIRST": "mmini"}),
                              (mmini.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def sidebar(self):
        side = mmini.Sidebar(FakeScr(24, 30), self.state, self.win)
        side.refresh_once()
        side.sync()
        return side

    def title_file(self):
        return (self.win / "title").read_text(encoding="utf-8").split("\n")[:2]

    # the text ----------------------------------------------------------------------------------------------------
    def test_three_examples(self):
        parsed = mmini.parse(json.dumps({"terminals": self.TERMS}))
        machines = [mmini.Machine(n, t) for n, t in self.MACHINES]
        title = mmini.shown_title
        self.assertEqual(title("mmini/t2", parsed, machines), "tracker · me@mini")
        self.assertEqual(title("rig/t1", parsed, machines), "harry · guest@mini")
        self.assertEqual(title("t9", parsed, machines), "t9 · this Mac")  # no hc name: its id
        self.assertEqual(title("", parsed, machines), "mmini")  # nothing shown

    def test_display_names_win(self):
        parsed = mmini.parse(json.dumps({"terminals": self.TERMS}))
        machines = [mmini.Machine(n, t) for n, t in self.MACHINES]
        names = {"term:mmini/t2": "Bot", "rig:rig": "Harry", "rig:mmini": "Mini", "rig:this Mac": "Laptop"}
        self.assertEqual(mmini.shown_title("mmini/t2", parsed, machines, names), "Bot · Mini")
        self.assertEqual(mmini.shown_title("rig/t1", parsed, machines, names), "harry · Harry")
        self.assertEqual(mmini.shown_title("t9", parsed, machines, names), "t9 · Laptop")
        # the same server names as the server rows draw them
        _, rigs = mmini.build_groups(parsed, "mmini", None, machines, names)
        for g in rigs:
            self.assertEqual(mmini.server_name(g.machine, machines, names), g.shown)
        _, rigs = mmini.build_groups(parsed, "mmini", None, machines)
        for g in rigs:
            self.assertEqual(mmini.server_name(g.machine, machines), g.shown)

    def test_servers_without_ssh_user_via_or_unknown(self):
        M = mmini.Machine
        self.assertEqual(mmini.server_name("vps", [M("vps", "vps")]), "vps")  # a Host of ~/.ssh/config
        self.assertEqual(mmini.server_name("box", [M("box", "ssh -J x box", True)]), "box")  # via: the hc name
        self.assertEqual(mmini.server_name("gone", []), "gone")  # not in hc machine ls: the hc name
        self.assertEqual(mmini.server_name(mmini.LOCAL, []), "this Mac")
        self.assertEqual(mmini.shown_title("box/t3", [], [M("box", "me@box.lan:2222")]), "t3 · me@box.lan")

    def test_unprintable_and_long_names(self):
        wt = mmini.window_title
        for evil in ("a\x1b]2;owned\x07b", "a\nb", "a\x9bb", "a\u202eb", "a\u00a0b", "a\tb", "a\x00b", "a\rb"):
            text = wt(evil, "srv\x1b\x07")
            self.assertTrue(text.isprintable(), repr(text))
            self.assertNotIn("\x1b", text)
            self.assertTrue(text.startswith("a "), repr(text))
            self.assertTrue(text.endswith(" · srv"), repr(text))
        self.assertEqual(wt("\x1b\x07", "\n"), "mmini")  # nothing printable left: as when nothing is shown
        self.assertEqual(wt("  web  ", ""), "web")
        self.assertEqual(wt("", "me@mini"), "me@mini")
        long = wt("x" * 200, "me@mini")
        self.assertLessEqual(len(long), mmini.TITLE_MAX)
        self.assertTrue(long.endswith("x… · me@mini"))  # the server stays whole
        both = wt("x" * 200, "y" * 200)
        self.assertEqual(len(both), mmini.TITLE_MAX)
        self.assertIn("… · y", both)
        self.assertTrue(both.endswith("y…"))
        short = wt("web", "y" * 200)
        self.assertTrue(short.startswith("web · y") and len(short) == mmini.TITLE_MAX)  # a short name leaves room
        wide = wt("\U0001d4d0" * 100, "\U0001d4d1" * 100)  # 4 bytes each in UTF-8
        self.assertLess(len(wide.encode()), 256)  # Ghostty ignores a title of 256 bytes or more
        self.assertLessEqual(len(wide.encode()), mmini.TITLE_BYTES)
        self.assertIn(" · ", wide)

    def test_the_escape_is_osc_2_with_a_clean_title(self):
        self.assertEqual(mmini.title_escape("tracker · me@mini"),
                         "\x1b]2;tracker · me@mini\x07".encode())
        self.assertEqual(mmini.title_escape("a\x07\x1b]7;b"), b"\x1b]2;a ]7;b\x07")
        self.assertEqual(mmini.title_escape(""), b"\x1b]2;mmini\x07")

    # sending -----------------------------------------------------------------------------------------------------
    def test_sent_only_when_it_changes_and_never_followed_by_osc_7(self):
        import pty
        master, slave = pty.openpty()
        try:
            mmini.claim_pane(slave)
            pane = mmini.PaneTitle(slave)
            self.assertFalse(pane.send("mmini"))  # what claim_pane sent: nothing again
            self.assertTrue(pane.send("tracker · me@mini"))
            self.assertFalse(pane.send("tracker · me@mini"))  # every frame: once only
            self.assertFalse(pane.send(None))  # not known: the title stays
            self.assertTrue(pane.send("harry · guest@mini"))
            out = os.read(master, 1000)
        finally:
            os.close(master)
            os.close(slave)
        self.assertEqual(out, (mmini.PANE_TITLE + "\x1b]2;tracker · me@mini\x07"
                               "\x1b]2;harry · guest@mini\x07").encode())
        codes = [c for c, _ in OSC_RE.findall(out)]
        self.assertEqual(codes, [b"2", b"7", b"2", b"2"])  # the one OSC 7 only at the start, after a title
        # Ghostty, starting from the login shell's folder as the title (no title seen): the last title wins
        self.assertEqual(ghostty_title(out, b"/Users/me", False, b"/Users/me"), ("harry · guest@mini", True))
        r, w = os.pipe()
        try:
            self.assertFalse(mmini.PaneTitle(w).send("x"))  # not a terminal: nothing written
            os.close(w)
            self.assertEqual(os.read(r, 100), b"")
        finally:
            os.close(r)
        self.assertFalse(mmini.PaneTitle(9999).send("x"))  # a closed descriptor: no error

    def test_the_ghostty_model_shows_why_the_title_goes_first(self):
        self.assertEqual(ghostty_title(b"\x1b]7;\x07\x1b]2;web\x07", b"/home", False, b"/home")[0], "web")
        self.assertEqual(ghostty_title(b"\x1b]2;web\x07\x1b]7;\x07", b"/home", False, b"/home")[0], "web")
        self.assertEqual(ghostty_title(b"\x1b]2;" + b"x" * 256 + b"\x07\x1b]7;\x07", b"/home", False, b"/home")[0],
                         "")  # an ignored (too long) title, then an empty OSC 7: no title at all

    # the engine: file, snapshot, hidden servers ------------------------------------------------------------------
    def test_the_engine_writes_the_title_file_and_the_snapshot(self):
        side = self.sidebar()
        self.assertEqual(self.title_file(), ["", "mmini"])
        mmini.write_servers_shown(False, self.state)  # hidden: changes nothing about the title
        for address, title in (("mmini/t2", "tracker · me@mini"), ("rig/t1", "harry · guest@mini"),
                               ("t9", "t9 · this Mac")):
            mmini.write_atomic(self.win / "target", address + "\n")
            side.sync()
            self.assertEqual(side.title, title)
            self.assertEqual(self.title_file(), [address, title])
            snap = mmini.read_snapshot(self.win)
            self.assertEqual((snap["shown"], snap["shown_title"]), (address, title))
            self.assertEqual(mmini.tabs_title(snap, address), title)
        mmini.write_servers_shown(True, self.state)
        side.sync()
        self.assertEqual(side.title, "t9 · this Mac")
        mmini.write_atomic(self.state / "names.json", json.dumps({"term:t9": "Notes", "rig:this Mac": "Laptop"}))
        side.sync()
        self.assertEqual(self.title_file(), ["t9", "Notes · Laptop"])  # a rename counts at once

    def test_the_title_file_is_written_only_on_a_change(self):
        side = self.sidebar()
        mmini.write_atomic(self.win / "target", "mmini/t2\n")
        with mock.patch.object(mmini, "write_title", wraps=mmini.write_title) as wrote:
            for _ in range(5):
                side.sync()
            self.assertEqual(wrote.call_count, 1)
            mmini.write_atomic(self.win / "target", "mmini/t1\n")
            side.sync()
            side.sync()
            self.assertEqual(wrote.call_count, 2)

    def test_show_group_writes_the_title_before_the_target(self):
        side = self.sidebar()
        mmini.write_servers_shown(True, self.state)
        order = []
        real = mmini.write_atomic

        def spy(path, text, encoding=None):
            order.append(path.name)
            real(path, text, encoding)

        with mock.patch.object(mmini, "write_atomic", spy):
            side.show_group("rig:rig")
        self.assertLess(order.index("title"), order.index("target"))
        self.assertEqual(self.title_file(), ["rig/t1", "harry · guest@mini"])

    def test_tab_bar_titles_from_the_snapshot_alone(self):
        side = self.sidebar()
        mmini.write_servers_shown(True, self.state)
        side.show_group("space:tracker", "mmini/t2")
        snap = mmini.read_snapshot(self.win)
        self.assertEqual(snap["server"], "me@mini")
        self.assertEqual([t["server"] for t in snap["tabs"]], ["me@mini", "me@mini"])
        self.assertEqual(mmini.tabs_title(snap, "mmini/t3"), "sh · me@mini")  # a tab: from its label
        self.assertEqual(mmini.tabs_title(snap, ""), "mmini")
        self.assertIsNone(mmini.tabs_title(None, "mmini/t2"))  # no snapshot yet: the title stays
        self.assertIsNone(mmini.tabs_title(snap, "rig/t1"))  # neither shown when written nor a tab: stays
        # the tab bar's picks write the title before the target, like the sidebar's
        bar = mmini.TabBar(FakeScr(5, 60), self.win, self.state)
        bar.step(snap, "mmini/t2", -1)  # tabs: sh, tracker
        self.assertEqual(self.title_file(), ["mmini/t3", "sh · me@mini"])
        new = json.dumps({"address": "t44"})
        bar.last_plus = -10.0  # time.monotonic() starts near 0 in a new process
        with mock.patch.object(mmini, "run_hc", lambda *a, **k: new):
            bar.plus({**snap, "server": "this Mac", "machine": mmini.LOCAL})
        self.assertEqual(self.title_file(), ["t44", "t44 · this Mac"])

    def test_the_tab_bars_own_engine_gives_the_same_title(self):
        """Sidebar hidden: the tab bar's engine writes the file and the snapshot; servers stay hidden."""
        mmini.write_atomic(self.state / "group", "space:tracker\n")
        mmini.write_last({"space:tracker": "mmini/t2"}, self.state)
        mmini.write_sidebar_state("hidden", self.state)
        bar = mmini.TabBar(FakeScr(5, 60), self.win, self.state)
        self.addCleanup(bar.stop_engine)
        bar.watch_sidebar(100.0)
        self.assertTrue(bar.alone)
        self.assertTrue(wait_for(lambda: (self.win / "title").exists() and self.title_file()[0] == "mmini/t2"))
        self.assertEqual(self.title_file(), ["mmini/t2", "tracker · me@mini"])
        self.assertTrue(wait_for(lambda: (mmini.read_snapshot(self.win) or {}).get("shown") == "mmini/t2"))
        snap = mmini.read_snapshot(self.win)
        self.assertFalse(mmini.read_servers_shown(self.state))
        self.assertEqual(mmini.tabs_title(snap, "mmini/t2"), "tracker · me@mini")
        mmini.show("rig/t1", self.win)  # a terminal of a hidden server: still named by its server
        self.assertTrue(wait_for(lambda: self.title_file() == ["rig/t1", "harry · guest@mini"]))

    def test_tab_bar_sends_it_from_its_run_loop(self):
        text = (ROOT / "mmini.py").read_text()
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
        env = dict(os.environ, MMINI_HC=str(hc), MMINI_STATE=str(self.state), MMINI_WINDOW=str(self.win),
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

    def test_view_sets_the_title_before_each_attach_and_mmini_after(self):
        out = self.start_view()
        mmini.show("mmini/t2", self.win, "tracker · me@mini")
        self.assertTrue(wait_for(lambda: b"ATTACH mmini/t2" in out.read_bytes()))
        mmini.show("rig/t1", self.win, "harry · guest@mini")
        self.assertTrue(wait_for(lambda: b"ATTACH rig/t1" in out.read_bytes()))
        mmini.show("", self.win, mmini.NO_TITLE)
        self.assertTrue(wait_for(lambda: out.read_bytes().count(b"Pick a terminal") >= 2))
        data = out.read_bytes()
        one, two = data.index(b"ATTACH mmini/t2"), data.index(b"ATTACH rig/t1")
        first = "\x1b]2;tracker · me@mini\x07".encode()
        second = "\x1b]2;harry · guest@mini\x07".encode()
        self.assertIn(first, data[:one])
        self.assertIn(second, data[one:two])
        self.assertEqual(ghostty_title(data[:one])[0], "tracker · me@mini")
        self.assertEqual(ghostty_title(data[:two])[0], "harry · guest@mini")
        self.assertEqual(ghostty_title(data)[0], "mmini")  # nothing shown any more
        # every OSC 7 comes right after a title: never one that could clear it
        osc = OSC_RE.findall(data)
        for i, (code, _) in enumerate(osc):
            if code == b"7":
                self.assertEqual(osc[i - 1][0], b"2")

    def test_view_after_an_attach_ends_goes_back_to_the_mmini_title(self):
        stub = TITLE_STUB.replace("while :; do sleep 0.02; done", 'printf "\\033]2;Claude Code\\007"; exit 0')
        out = self.start_view(stub)
        mmini.show("mmini/t2", self.win, "tracker · me@mini")
        self.assertTrue(wait_for(lambda: b"is not shown any more" in out.read_bytes()))
        data = out.read_bytes()
        attach = data.index(b"ATTACH mmini/t2")
        self.assertEqual(ghostty_title(data[:data.index(b"Claude Code") + 12])[0], "Claude Code")  # its own title
        self.assertEqual(ghostty_title(data)[0], "tracker · me@mini")  # clean_screen: the mmini title again
        self.assertIn("\x1b]2;tracker · me@mini\x07".encode(), data[:attach])

    def test_view_with_a_title_for_another_terminal_waits_then_says_mmini(self):
        out = self.start_view()
        mmini.write_title("other", "other · x", self.win)
        started = time.monotonic()
        mmini.show("mmini/t2", self.win)  # no title given: the file still names "other"
        self.assertTrue(wait_for(lambda: b"ATTACH mmini/t2" in out.read_bytes()))
        self.assertGreaterEqual(time.monotonic() - started, 0.4)  # it waited for the right one
        data = out.read_bytes()
        self.assertEqual(ghostty_title(data[:data.index(b"ATTACH")])[0], "mmini")
        mmini.write_title("mmini/t3", "sh · me@mini", self.win)  # the engine, a moment late
        mmini.show("mmini/t3", self.win)
        self.assertTrue(wait_for(lambda: b"ATTACH mmini/t3" in out.read_bytes()))
        data = out.read_bytes()
        self.assertEqual(ghostty_title(data[:data.index(b"ATTACH mmini/t3")])[0], "sh · me@mini")

    def test_view_drops_control_characters_from_the_file(self):
        out = self.start_view()
        self.win.mkdir(parents=True, exist_ok=True)
        (self.win / "title").write_bytes(b"t1\nweb\x1b]7;file://x/\x07 \xc2\xb7 x\n")  # not from mmini.py
        mmini.show("t1", self.win)
        self.assertTrue(wait_for(lambda: b"ATTACH t1" in out.read_bytes()))
        data = out.read_bytes()
        before = data[:data.index(b"ATTACH t1")]
        self.assertIn("\x1b]2;web]7;file://x/ · x\x07".encode(), before)
        self.assertEqual(ghostty_title(before)[0], "web]7;file://x/ · x")


PRESS1, RELEASE1 = mmini.curses.BUTTON1_PRESSED, mmini.curses.BUTTON1_RELEASED
PRESS3, RELEASE3 = mmini.curses.BUTTON3_PRESSED, mmini.curses.BUTTON3_RELEASED


class MouseSetupTests(unittest.TestCase):
    """Presses act the moment they arrive: no mouse interval, no CLICKED in the mask, releases dropped."""

    def setup(self, right):
        calls = []
        patches = {"curs_set": lambda n: None, "use_default_colors": lambda: None, "init_pair": lambda *a: None,
                   "mouseinterval": lambda ms: calls.append(("interval", ms)),
                   "mousemask": lambda mask: calls.append(("mask", mask)) or (mask, 0)}
        scr = mock.Mock()
        with mock.patch.multiple(mmini.curses, **patches):
            mmini.setup_curses(scr, right=right)
        return calls, scr

    def test_interval_zero_before_the_mask_and_only_presses_and_releases(self):
        calls, scr = self.setup(right=True)
        self.assertEqual(calls, [("interval", 0), ("mask", PRESS1 | RELEASE1 | PRESS3 | RELEASE3)])
        clicked = (mmini.curses.BUTTON1_CLICKED | mmini.curses.BUTTON3_CLICKED | mmini.curses.BUTTON1_DOUBLE_CLICKED
                   | mmini.curses.BUTTON3_DOUBLE_CLICKED)
        self.assertEqual(calls[1][1] & clicked, 0)  # a CLICKED in the mask makes ncurses hold every press back
        scr.timeout.assert_called_once_with(mmini.LOOP_WAIT_MS)
        calls, _ = self.setup(right=False)  # the tab bar leaves the right button to Ghostty
        self.assertEqual(calls, [("interval", 0), ("mask", PRESS1 | RELEASE1)])

    def test_read_mouse_reports_presses_only(self):
        for bstate, mouse, click in ((PRESS1, (4, 2, 1), (4, 2)), (PRESS3, (4, 2, 3), None), (RELEASE1, None, None),
                                     (RELEASE3, None, None), (mmini.curses.BUTTON1_CLICKED, None, None), (0, None, None)):
            with mock.patch.object(mmini.curses, "getmouse", return_value=(0, 4, 2, 0, bstate)):
                self.assertEqual(mmini.read_mouse(), mouse, bstate)
                self.assertEqual(mmini.read_click(), click, bstate)
        with mock.patch.object(mmini.curses, "getmouse", side_effect=mmini.curses.error):
            self.assertIsNone(mmini.read_mouse())

    def test_in_a_pseudo_terminal_the_press_comes_at_once(self):
        """The real ncurses of this Mac: a press, then its release 150 ms later (X10 mouse, as xterm-256color
        has it). The press must be read within a few ms of its arrival, the release apart."""
        import pty
        child = (
            "import curses, os, sys, time\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "import mmini\n"
            "def main(scr):\n"
            "    mmini.setup_curses(scr, right=True)\n"
            "    os.write(3, b'ready\\n')\n"
            "    end = time.time() + 2\n"
            "    while time.time() < end:\n"
            "        k = scr.getch()\n"
            "        if k == curses.KEY_MOUSE:\n"
            "            os.write(3, f'{time.time()} {mmini.read_mouse()}\\n'.encode())\n"
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
        with mock.patch.object(mmini.curses, "getmouse", return_value=(0, x, y, 0, bstate)):
            self.key(mmini.curses.KEY_MOUSE)

    def test_a_press_on_a_row_shows_it_and_its_release_does_nothing(self):
        row = self.line_of(mmini.Item("agent", "space:other", "t4"))
        self.mouse(5, row, PRESS1)
        self.assertEqual(mmini.current_target(self.win), "t4")
        gen = mtime_ns(self.win / "gen")
        self.side.notice.say("kept")
        self.side.mouse_quiet = 0.0
        self.mouse(5, row, RELEASE1)
        self.assertEqual(mtime_ns(self.win / "gen"), gen)  # no second pick
        self.assertEqual(self.side.notice.current(), "kept")  # a release is no key: the notice stays

    def test_the_notice_a_press_set_survives_its_release(self):
        row = self.line_of(mmini.Item("agent", "space:other", "t4"))
        self.hc.terms = [t for t in self.hc.terms if t["address"] != "t4"]
        self.side.refresh_once()
        self.mouse(5, row, PRESS1)
        self.assertEqual(self.side.notice.current(), "that terminal has ended")
        self.mouse(5, row, RELEASE1)
        self.assertEqual(self.side.notice.current(), "that terminal has ended")

    def test_a_right_press_opens_the_menu_and_its_release_keeps_it(self):
        row = self.line_of(mmini.Item("group", "rig:vps", ""))
        self.mouse(5, row, PRESS3)
        self.assertEqual(self.side.menu.item, mmini.Item("group", "rig:vps", ""))
        self.side.mouse_quiet = 0.0  # not the double-click guard: the release itself is dropped
        self.mouse(5, row, RELEASE3)
        self.assertIsNotNone(self.side.menu)
        self.mouse(0, 0, PRESS1)  # a press outside closes it, and opens nothing
        self.assertIsNone(self.side.menu)
        self.side.mouse_quiet = 0.0
        target = mmini.current_target(self.win)
        self.mouse(0, 0, RELEASE1)
        self.assertIsNone(self.side.menu)
        self.assertEqual(mmini.current_target(self.win), target)

    def test_a_press_on_an_entry_runs_it_and_its_release_does_not_close_the_prompt(self):
        row = self.line_of(mmini.Item("group", "rig:vps", ""))
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
        with mock.patch.object(mmini, "ghostty"):
            self.mouse(5, self.side.arrow_y, PRESS1)  # the second press, within MOUSE_QUIET: no hide
        self.assertEqual(mmini.read_sidebar_state(self.state), "strip")

    def test_tab_bar_press_shows_at_once_and_its_release_keeps_the_notice(self):
        bar_tests = TabBarLogicTests("test_waiting_without_a_sidebar")  # only for its fixture
        bar_tests.addCleanup = self.addCleanup
        bar_tests.setUp()
        bar, snap = bar_tests.bar, bar_tests.snap
        bar.draw(snap, "t1")
        with mock.patch.object(mmini.curses, "getmouse", return_value=(0, 3, 1, 0, PRESS1)):
            bar.on_key(mmini.curses.KEY_MOUSE, snap, "t1")
        self.assertEqual(mmini.current_target(bar_tests.win), "t5")
        gen = mtime_ns(bar_tests.win / "gen")
        bar.notice.say("kept")
        with mock.patch.object(mmini.curses, "getmouse", return_value=(0, 3, 1, 0, RELEASE1)):
            bar.on_key(mmini.curses.KEY_MOUSE, snap, "t5")
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
        self.assertFalse(mmini.round_due(stamp, stamp, 10.1, 10.0))
        self.assertTrue(mmini.round_due((3, 2), stamp, 10.1, 10.0))  # a pick
        self.assertTrue(mmini.round_due((1, 4), stamp, 10.1, 10.0))  # new tabs
        self.assertTrue(mmini.round_due(stamp, stamp, 10.0 + mmini.ROUND_SECONDS, 10.0))

    def test_pick_stamp_moves_on_a_pick_and_on_new_tabs(self):
        first = mmini.pick_stamp(self.win)
        self.assertEqual(first, (0, 0))
        mmini.show("t1", self.win)
        second = mmini.pick_stamp(self.win)
        self.assertNotEqual(second[0], 0)
        time.sleep(0.002)
        mmini.write_snapshot(None, self.win)
        self.assertNotEqual(mmini.pick_stamp(self.win)[1], second[1])

    def test_wait_key(self):
        keys = iter([-1, -1, ord("j")])
        scr = mock.Mock(getch=lambda: next(keys))
        with mock.patch.object(mmini, "terminal_gone", return_value=False):
            now = time.monotonic()
            self.assertEqual(mmini.wait_key(scr, self.win, mmini.pick_stamp(self.win), now), ord("j"))
            seen = mmini.pick_stamp(self.win)
            calls = []

            def getch():
                calls.append(1)
                if len(calls) == 3:
                    mmini.show("t2", self.win)  # the other pane picks
                return -1

            scr = mock.Mock(getch=getch)
            self.assertEqual(mmini.wait_key(scr, self.win, seen, time.monotonic()), -1)
            self.assertEqual(len(calls), 3)  # at once after the pick, not at the end of the round
            calls.clear()
            self.assertEqual(mmini.wait_key(scr, self.win, mmini.pick_stamp(self.win), now - 1), -1)  # round due
            self.assertEqual(len(calls), 1)
        with mock.patch.object(mmini, "terminal_gone", return_value=True):
            self.assertIsNone(mmini.wait_key(mock.Mock(getch=lambda: -1), self.win, (0, 0), time.monotonic()))

    def test_both_loops_wait_with_it(self):
        text = (ROOT / "mmini.py").read_text()
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
        ppid, command = mmini.proc_info(os.getpid())
        self.assertEqual(ppid, os.getppid())
        self.assertIn("unittest", command)
        proc = subprocess.Popen(["/bin/sleep", "5"])
        self.assertEqual(mmini.proc_info(proc.pid), (os.getpid(), "/bin/sleep 5"))
        proc.kill()
        proc.wait()
        self.assertEqual(mmini.proc_info(proc.pid), (0, ""))

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
        mmini.write_atomic(win / "view.pid", f"{proc.pid}\n")
        mmini.write_atomic(win / "view.loop", f"{os.getpid()}\n")
        self.assertEqual(mmini.attach_pid(win), proc.pid)
        with mock.patch.object(mmini, "proc_info", return_value=None), \
                mock.patch.object(mmini.subprocess, "run", wraps=subprocess.run) as run:
            self.assertEqual(mmini.attach_pid(win), proc.pid)
        self.assertEqual(run.call_args[0][0][0], "/bin/ps")
        with mock.patch.object(mmini.subprocess, "run") as run:
            self.assertEqual(mmini.attach_pid(win), proc.pid)  # the kernel answered: no ps
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
        env = dict(os.environ, MMINI_HC=str(hc), MMINI_STATE=str(self.win), STUB_LOG=str(self.log), **extra)
        env.pop("MMINI_WINDOW", None)
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
        mmini.show("a", self.win)
        self.assertTrue(wait_for(lambda: b"ATTACH a" in out.read_bytes()))
        mmini.show("b", self.win)
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
        mmini.show("a", self.win)
        self.assertTrue(wait_for(lambda: b"ATTACH a" in out.read_bytes()))
        mmini.show("", self.win)  # nothing shown any more
        self.assertTrue(wait_for(lambda: b"Pick a terminal" in out.read_bytes().partition(b"ATTACH a")[2]))
        data = out.read_bytes()
        attach = data.index(b"ATTACH a")
        self.assertIn(b"\x1b[2J", data[attach:data.index(b"Pick a terminal", attach)])
        ended = TITLE_STUB.replace("while :; do sleep 0.02; done", "exit 0")  # detached, or its program ended
        self.log.write_text("")
        (self.tmp / "out").unlink()
        out = self.start_view(ended)
        mmini.show("c", self.win)
        self.assertTrue(wait_for(lambda: b"is not shown any more" in out.read_bytes()))
        data = out.read_bytes()
        self.assertIn(b"\x1b[2J", data[data.index(b"ATTACH c"):data.index(b"is not shown any more")])

    def test_idle_view_attaches_a_pick_within_a_few_polls(self):
        self.start_view(MMINI_AUTOOPEN="0")
        delays = []
        for name in ("a", "b", "c", "d", "e"):
            time.sleep(0.3)  # idle: nothing attached
            started = time.monotonic()
            mmini.show(name, self.win)
            self.assertTrue(wait_for(lambda: f"start {name}" in self.log.read_text()))
            delays.append(time.monotonic() - started)
            mmini.show("", self.win)
            self.assertTrue(wait_for(lambda: f"end {name}" in self.log.read_text()))
        # the median: one slow start on a busy machine is no failure. The shell loop that polled every 0.2 s (with
        # a cat and a sleep each time) took 160 ms in the median, here it is 35 ms.
        self.assertLess(sorted(delays)[2], 0.12, delays)

    def test_a_signal_while_idle_ends_the_view_and_its_wait_at_once(self):
        self.start_view(MMINI_AUTOOPEN="0")
        time.sleep(0.3)  # idle: the perl wait runs
        loop = int(mmini.read_text(self.win / "view.loop"))
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


MOTION = mmini.curses.REPORT_MOUSE_POSITION


class SeparatorPlanTests(unittest.TestCase):
    """The separator between the upper part and the agents, moved: its line from the file and the pane height."""

    def setUp(self):
        self.spaces, self.rigs = many_agents(6)
        self.items = mmini.selectable_items(self.spaces, self.rigs)

    def test_limits_keep_a_heading_and_a_row_on_each_side(self):
        self.assertIsNone(mmini.rule_limits(4))  # "spaces" + a row, then the line, "agents" + a row: 5 lines
        self.assertEqual(mmini.rule_limits(5), (2, 2))
        self.assertEqual(mmini.rule_limits(23), (2, 20))
        for height in range(-2, 5):
            self.assertIsNone(mmini.clamp_rule(3, height), height)
        self.assertEqual([mmini.clamp_rule(y, 23) for y in (-5, 0, 2, 11, 20, 21, 99)], [2, 2, 2, 11, 20, 20, 20])

    def test_keys_step_one_line_and_stop_at_the_limits(self):
        step = mmini.rule_step
        self.assertEqual((step(10, -1, 23), step(10, 1, 23)), (9, 11))
        self.assertEqual((step(2, -1, 23), step(20, 1, 23)), (2, 20))
        self.assertEqual(step(21, -1, 23), 20)  # drawn below the limit (no agents): up goes to the limit
        self.assertEqual(step(21, 1, 23), 21)  # ] never moves it up
        self.assertEqual(step(23, -1, 23), 20)  # none drawn (the upper part took every line): from the bottom
        self.assertEqual(step(23, 1, 23), 23)
        self.assertIsNone(step(2, 1, 4))

    def test_the_file_split_parses_or_counts_as_none(self):
        self.assertEqual(mmini.parse_split("12/40"), (12, 40))
        self.assertEqual(mmini.parse_split(" 0/1\n"), (0, 1))
        for junk in ("", "12", "x/40", "40/40", "41/40", "-1/40", "3/0", "3/1001", "12 / 40", "+3/40", "1e3/40",
                     "١٢/40", "12/40/2", "12/40\n7/9", "99999/99999"):
            self.assertIsNone(mmini.parse_split(junk), junk)

    def test_its_line_keeps_its_share_of_the_pane(self):
        self.assertIsNone(mmini.split_row(None, 40))
        self.assertIsNone(mmini.split_row((12, 40), 0))
        for height in range(1, 200):  # the height it was set at: exactly that line
            for row in range(height):
                self.assertEqual(mmini.split_row((row, height), height), row, (row, height))
        self.assertEqual(mmini.split_row((12, 40), 60), 18)  # a taller window: the same share
        self.assertEqual(mmini.split_row((12, 40), 20), 6)
        self.assertEqual(mmini.split_row((12, 40), 41), 12)  # 12.3

    def test_moved_rule_splits_the_list_there(self):
        plan = mmini.plan_sidebar(self.spaces, self.rigs, 23, 0, rule=8)
        rule = next(y for y, r in plan if r.kind == "rule")
        self.assertEqual(rule, 8)
        self.assertTrue(all(y < 8 for y, r in plan if r.kind in ("header", "group", "plus", "blank")))
        below = [(y, r.kind) for y, r in plan if y >= 8]
        self.assertEqual(below[:3], [(8, "rule"), (9, "agents"), (10, "agent_group")])
        self.assertEqual(sum(1 for _, k in below if k == "agent"), 6)  # 13 lines below: all 6 agents
        self.assertEqual(max(y for y, _ in plan), 16)  # top-aligned under the line; the rest stays empty
        auto = mmini.plan_sidebar(self.spaces, self.rigs, 23, 0)
        self.assertEqual([(y, r.kind) for y, r in mmini.plan_sidebar(self.spaces, self.rigs, 23, 0, rule=None)],
                         [(y, r.kind) for y, r in auto])

    def test_every_height_line_and_cursor_keeps_the_cursor_row_and_both_parts(self):
        for height in range(0, 26):
            for rule in range(-2, height + 3):
                for cursor in range(len(self.items)):
                    case = (height, rule, cursor)
                    plan = mmini.plan_sidebar(self.spaces, self.rigs, height, cursor, rule=rule)
                    ys = [y for y, _ in plan]
                    self.assertEqual(len(ys), len(set(ys)), case)
                    self.assertTrue(all(0 <= y < height for y in ys), case)
                    at = mmini.clamp_rule(rule, height)
                    if at is None:  # too short: the automatic layout
                        self.assertEqual([(y, r.kind) for y, r in plan],
                                         [(y, r.kind) for y, r in mmini.plan_sidebar(self.spaces, self.rigs, height,
                                                                                     cursor)], case)
                        continue
                    self.assertEqual([y for y, r in plan if r.kind == "rule"], [at], case)
                    self.assertEqual(dict(plan)[at + 1].kind, "agents", case)
                    self.assertIn(cursor, [r.item for _, r in plan], case)  # a "+" row and an agent too
                    tops = [y for y, r in plan if r.kind in ("header", "group", "plus", "blank")]
                    self.assertTrue(all(y < at for y in tops), case)
                    self.assertGreaterEqual(len(tops), 2, case)

    def test_a_small_upper_part_scrolls_to_the_plus_row(self):
        plus = self.items.index(mmini.Item("new_space", "", ""))
        plan = mmini.plan_sidebar(self.spaces, self.rigs, 23, plus, rule=2)
        self.assertEqual([r.kind for y, r in plan if y < 2], ["group", "plus"])

    def test_the_strip_has_the_same_lines(self):
        for rule in (2, 8, 20):
            wide = mmini.plan_sidebar(self.spaces, self.rigs, 23, 0, rule=rule)
            strip = mmini.plan_sidebar(self.spaces, self.rigs, 23, 0, compact=True, rule=rule)
            self.assertEqual([(y, r.kind) for y, r in wide], [(y, r.kind) for y, r in strip])

    def test_a_click_on_its_line_hits_the_separator_only(self):
        rows = {3: mmini.Item("group", "space:dev", "")}
        self.assertEqual(mmini.sidebar_hit(8, 23, -1, rows, 0, 28, 8), ("rule", None))
        self.assertEqual(mmini.sidebar_hit(8, 23, -1, rows, 27, 28, 8), ("rule", None))
        self.assertEqual(mmini.sidebar_hit(3, 23, -1, rows, 0, 28, 8)[0], "item")
        self.assertEqual(mmini.sidebar_hit(8, 23, -1, rows, 0, 28), ("", None))  # not drawn: nothing there
        self.assertEqual(mmini.sidebar_hit(23, 23, -1, rows, 0, 28, 23), ("step", None))  # the arrow line wins

    def test_mouse_events_and_their_route(self):
        for bstate, event in ((PRESS1, "press"), (PRESS3, "right"), (RELEASE1, "release"), (RELEASE3, "release"),
                              (MOTION, "motion"), (MOTION | PRESS1, "motion"), (0, None),
                              (mmini.curses.BUTTON1_CLICKED, None)):
            with mouse_at(4, 2, bstate):
                self.assertEqual(mmini.read_mouse_event(), (4, 2, event) if event else None, bstate)
                if event not in ("press", "right"):
                    self.assertIsNone(mmini.read_mouse(), bstate)  # only presses are clicks
        route = mmini.mouse_route
        for what in ("release", "motion", ""):  # without a drag: dropped, as before
            self.assertEqual(route(what, False), "drop", what)
        self.assertEqual((route("motion", True), route("release", True), route("", True)), ("follow", "end", "drop"))
        for dragging in (False, True):
            self.assertEqual((route("press", dragging), route("right", dragging)), ("press", "press"))

    def test_a_move_after_a_quiet_drag_is_a_lost_release(self):
        route = mmini.mouse_route
        # ncurses 6.0 reads the press after a lost release as a move: a drag quiet for DRAG_IDLE is not followed
        self.assertEqual(route("motion", True, True), "lost")
        self.assertEqual((route("release", True, True), route("press", True, True)), ("end", "press"))
        self.assertEqual((route("motion", False, True), route("release", False, True)), ("drop", "drop"))

    def test_the_line_where_the_automatic_layout_dropped_it(self):
        def crowded(n):
            terms = [term(f"s{i}", f"/Users/x/dev/s{i:02d}") for i in range(n)]
            terms += [term(f"a{i}", "/Users/x/dev/s00", "claude-code", f"a{i}", "idle") for i in range(6)]
            return mmini.build_groups(mmini.parse(ls(*terms)), "mmini")

        def agent_lines(plan):
            return sum(1 for _, r in plan if r.kind in ("agent_group", "agent", "more"))

        for n, auto_rows in ((17, [(19, "agents"), (20, "agent_group")]), (18, [(20, "agent_group")])):
            spaces, rigs = crowded(n)
            plan = mmini.plan_sidebar(spaces, rigs, 23, 0, servers=False)
            self.assertNotIn("rule", [r.kind for _, r in plan], n)  # the automatic layout dropped it
            self.assertEqual([(y, r.kind) for y, r in plan if y >= auto_rows[0][0]][:len(auto_rows)], auto_rows, n)
            line = mmini.rule_line(plan, 23)
            self.assertEqual(line, 18, n)  # where it would be above the same agent rows
            up = mmini.plan_sidebar(spaces, rigs, 23, 0, servers=False, rule=mmini.rule_step(line, -1, 23))
            down = mmini.plan_sidebar(spaces, rigs, 23, 0, servers=False, rule=mmini.rule_step(line, 1, 23))
            self.assertEqual((agent_lines(up), agent_lines(down)), (agent_lines(plan) + 1, agent_lines(plan) - 1), n)
        plan = mmini.plan_sidebar(self.spaces, self.rigs, 23, 0)
        self.assertEqual(mmini.rule_line(plan, 23), next(y for y, r in plan if r.kind == "rule"))  # drawn: there
        self.assertEqual(mmini.rule_line([], 23), 23)  # no agents part at all: the bottom

    def test_the_file_is_read_written_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            self.assertIsNone(mmini.read_split(state))
            mmini.clear_split(state)  # no file: fine
            mmini.write_split(8, 24, state)
            self.assertEqual((state / "split").read_text(), "8/24\n")
            self.assertEqual(mmini.read_split(state), (8, 24))
            (state / "split").write_text("junk\n")
            self.assertIsNone(mmini.read_split(state))
            mmini.clear_split(state)
            self.assertFalse((state / "split").exists())


class SeparatorDragTests(unittest.TestCase):
    """The Sidebar: the separator dragged with the mouse (press, moves, release) and moved with [ ] - =."""

    TERMS = SidebarLogicTests.TERMS
    setUp = SidebarLogicTests.setUp
    key = SidebarLogicTests.key

    def mouse(self, x, y, bstate):
        with mouse_at(x, y, bstate):
            self.key(mmini.curses.KEY_MOUSE)

    def rule_line(self):
        return next(y for y in range(self.scr.height) if self.scr.line(y) == "─" * 29)

    def split(self):
        return mmini.read_text(self.state / "split")

    def test_auto_layout_first(self):
        self.assertEqual((self.side.rule_y, self.rule_line()), (16, 16))  # 23 lines of list, the agents at the end
        self.assertIsNone(self.side.rule_plan)

    def test_press_on_the_line_then_release_elsewhere_moves_it_and_keeps_it(self):
        target, gen = mmini.current_target(self.win), mtime_ns(self.win / "gen")
        self.mouse(20, 16, PRESS1)  # any column of the line
        self.assertEqual(self.side.drag_y, 16)
        self.assertEqual(self.scr.cells[(16, 0)][1], mmini.curses.A_BOLD)  # held: drawn bold
        self.assertIsNone(self.side.menu)
        self.assertEqual((mmini.current_target(self.win), mtime_ns(self.win / "gen")), (target, gen))  # no pick
        self.mouse(3, 12, MOTION)  # the pointer moves with the button held: the line goes along
        self.assertEqual((self.side.drag_y, self.rule_line()), (12, 12))
        self.assertEqual(self.split(), "")  # written only at the release
        self.mouse(3, 8, RELEASE1)
        self.assertIsNone(self.side.drag_y)
        self.assertEqual(self.split(), "8/24")
        lines = self.scr.lines()
        self.assertEqual(lines[8], "─" * 29)
        self.assertEqual(self.scr.cells[(8, 0)][1], mmini.curses.A_DIM)
        self.assertTrue(lines[9].startswith(" agents"))
        self.assertEqual(lines[10], mmini.glyph(" dev · 2"))
        self.assertEqual(lines[0:4], [" spaces", mmini.glyph("›● dev"), mmini.glyph(" ● other"), " + new space"])
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
        self.assertEqual(self.scr.lines()[:2], [" spaces", mmini.glyph("›● dev")])

    def test_a_click_on_the_line_writes_nothing_and_a_double_press_resets(self):
        self.mouse(0, 16, PRESS1)
        self.mouse(0, 16, RELEASE1)
        self.assertEqual(self.split(), "")  # a click moves nothing
        mmini.write_split(6, 24, self.state)
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
        self.side.rule_pressed -= mmini.MOUSE_QUIET + 0.01
        self.mouse(0, 16, PRESS1)
        self.assertEqual(self.side.drag_y, 16)

    def test_a_right_press_on_the_line_does_nothing(self):
        target = mmini.current_target(self.win)
        self.mouse(5, 16, PRESS3)
        self.assertIsNone(self.side.menu)
        self.assertIsNone(self.side.drag_y)
        self.assertEqual(mmini.current_target(self.win), target)

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
        self.assertEqual(self.side.cursor, mmini.Item("group", "space:other", ""))

    def test_a_press_while_a_drag_lost_its_release_acts_normally(self):
        self.mouse(0, 16, PRESS1)
        row = next(y for y, item in self.side.rows.items() if item.address == "t3")
        self.mouse(5, row, PRESS1)
        self.assertIsNone(self.side.drag_y)
        self.assertEqual(mmini.current_target(self.win), "t3")
        self.assertEqual(self.split(), "")

    def test_a_click_after_a_lost_release_does_not_move_it(self):
        self.mouse(0, 16, PRESS1)
        self.mouse(0, 12, MOTION)
        self.side.drag_seen -= mmini.DRAG_IDLE + 0.01  # the release got lost; a while later, a click on row 3:
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
        self.side.drag_seen -= mmini.DRAG_IDLE + 0.01  # held still a while, then let go
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
        mmini.write_split(20, 24, self.state)
        self.side.draw()
        self.assertEqual(self.rule_line(), 20)
        self.side.notice.say("something")  # one line less for the list: "agents" and a row still fit
        self.side.draw()
        self.assertEqual(self.rule_line(), 19)
        self.side.notice.clear()
        self.side.draw()
        self.assertEqual(self.rule_line(), 20)
        mmini.write_split(12, 24, self.state)
        self.side.prompt = mmini.Prompt("delete", " ".join(["word"] * 60), ask="type yes:")  # a long question
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
        other = mmini.Sidebar(FakeScr(24, 30), self.state, self.state / "w-2")
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
        mmini.write_split(9, 24, self.state)
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
        self.assertIsNone(mmini.rule_limits(self.side.body_height))
        self.scr.height = 24
        self.side.draw()
        self.assertEqual(self.rule_line(), 8)

    def test_a_notice_or_a_prompt_does_not_move_it(self):
        mmini.write_split(12, 24, self.state)
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
        mmini.write_split(2, 24, self.state)
        self.side.draw()
        self.key("j", "j")  # down to "+ new space": the upper part scrolls
        self.assertEqual(self.side.cursor, mmini.Item("new_space", "", ""))
        self.assertEqual(self.scr.reversed_rows(), [1])
        self.assertEqual(self.scr.line(1), " + new space")
        self.key("j")  # on to the agents below the line
        self.assertEqual(self.side.cursor.kind, "agent")

    def test_the_list_of_keys_names_them(self):
        self.assertIn(" [ ] - = separator up/down", mmini.help_lines(29, 40))


class DragReportTests(unittest.TestCase):
    """Mode 1002 (moves with a button held) asked of the terminal after ncurses' own mouse mode, and the moves read
    by this Mac's ncurses in both encodings: X10 (xterm-256color) and SGR (Ghostty's terminfo asks for 1006)."""

    def test_report_drags_writes_after_a_refresh(self):
        r, w = os.pipe()
        order = []
        scr = mock.Mock(refresh=lambda: order.append("refresh"))
        try:
            mmini.report_drags(scr, True, w)
            order.append(os.read(r, 100))
            mmini.report_drags(scr, False, w)
            order.append(os.read(r, 100))
        finally:
            os.close(r)
            os.close(w)
        self.assertEqual(order, ["refresh", b"\x1b[?1002h", "refresh", b"\x1b[?1002l"])
        mmini.report_drags(scr, True, 999)  # a closed pane: no error

    def test_the_sidebar_asks_for_moves_and_the_tab_bar_does_not(self):
        calls = []
        patches = {"curs_set": lambda n: None, "use_default_colors": lambda: None, "init_pair": lambda *a: None,
                   "mouseinterval": lambda ms: None, "mousemask": lambda mask: calls.append(mask) or (mask, 0)}
        with mock.patch.multiple(mmini.curses, **patches):
            mmini.setup_curses(mock.Mock(), right=True, motion=True)
            mmini.setup_curses(mock.Mock())
        self.assertEqual(calls, [PRESS1 | RELEASE1 | PRESS3 | RELEASE3 | MOTION, PRESS1 | RELEASE1])
        text = (ROOT / "mmini.py").read_text()
        side = text[text.index("class Sidebar(Engine):"):text.index("class TabBar:")]
        run = side[side.index("    def run(self) -> None:"):]
        self.assertIn("setup_curses(self.s.scr, right=True, motion=True)\n        report_drags(self.s.scr, True)", run)
        self.assertIn("finally:\n            report_drags(self.s.scr, False)", run)
        self.assertNotIn("report_drags", text[text.index("class TabBar:"):text.index("def start_hidden(")])

    def terminfo(self):
        """A copy of Ghostty 1.3's mouse capabilities (src/terminfo/ghostty.zig) on top of xterm-256color."""
        tic = shutil.which("tic") or "/usr/bin/tic"
        if not os.path.exists(tic):
            self.skipTest("no tic")
        folder = tempfile.mkdtemp(prefix="mmini-ti-")
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
            "import mmini\n"
            "def main(scr):\n"
            "    mmini.setup_curses(scr, right=True, motion=True)\n"
            "    mmini.report_drags(scr, True)\n"
            "    os.write(3, b'ready\\n')\n"
            f"    for _ in range({len(events)}):\n"
            "        k = -1\n"
            "        while k == -1:\n"
            "            k = scr.getch()\n"
            "        e = mmini.read_mouse_event() if k == curses.KEY_MOUSE else ('key', k)\n"
            "        os.write(3, (repr(e) + '\\n').encode())\n"
            "    mmini.report_drags(scr, False)\n"
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
        return mmini.parse(ls(tterm("mmini/t1", "/Users/x/dev", "claude-code", "zeta", "done", 2),
                              tterm("mmini/t2", "/Users/x/dev", "claude-code", "alpha", "blocked", 1),
                              tterm("mmini/t3", "/Users/x/dev", "claude-code", "beta", "idle", 4),
                              tterm("mmini/t4", "/Users/x/dev", "claude-code", "gamma", "error", 3),
                              tterm("mmini/t5", "/Users/x/dev", "claude-code", "delta", "working", 1),
                              tterm("mmini/t6", "/Users/x/dev", "zsh", "sh", None, 0),
                              tterm("rig/t1", "/home/r", "claude-code", "remote", "done", 1)))

    def test_parse_reads_the_turn(self):
        self.assertEqual([t.turn for t in self.terms()], [2, 1, 4, 3, 1, 0, 1])
        junk = mmini.parse(ls(dict(term("t1"), turn="7"), dict(term("t2"), turn=-1), dict(term("t3"), turn=True)))
        self.assertEqual([t.turn for t in junk], [0, 0, 0])

    def test_blocked_and_error_first_then_unseen_done(self):
        names = [t.name for t in mmini.needs_you(self.terms(), {})]
        self.assertEqual(names, ["alpha", "gamma", "remote", "zeta"])

    def test_a_done_once_looked_at_goes_and_a_newer_done_comes_back(self):
        terms = self.terms()
        self.assertEqual([t.name for t in mmini.needs_you(terms, {"mmini/t1": 2, "rig/t1": 1})], ["alpha", "gamma"])
        self.assertIn("zeta", [t.name for t in mmini.needs_you(terms, {"mmini/t1": 1})])  # an older look

    def test_the_shown_terminal_is_left_out(self):
        names = [t.name for t in mmini.needs_you(self.terms(), {}, "mmini/t2")]
        self.assertNotIn("alpha", names)

    def test_mark_seen_records_the_turn_of_the_shown_done_terminal(self):
        terms = self.terms()
        self.assertEqual(mmini.mark_seen({}, terms, "mmini/t1"), {"mmini/t1": 2})
        self.assertEqual(mmini.mark_seen({}, terms, "mmini/t2"), {})  # blocked: nothing to remember
        self.assertEqual(mmini.mark_seen({}, terms, ""), {})
        cleared = mmini.needs_you(terms, mmini.mark_seen({}, terms, "mmini/t1"))
        self.assertNotIn("zeta", [t.name for t in cleared])

    def test_mark_seen_drops_ended_terminals_but_keeps_an_unlisted_machine(self):
        seen = {"mmini/t99": 3, "rig/t1": 1, "away/t4": 2}
        after = mmini.mark_seen(seen, self.terms(), "")
        self.assertEqual(after, {"rig/t1": 1, "away/t4": 2})  # mmini/t99 ended; "away" is not listed now

    def test_mark_seen_keeps_at_most_the_newest(self):
        seen = {f"away/t{i}": i for i in range(mmini.SEEN_MAX + 20)}
        after = mmini.mark_seen(seen, self.terms(), "mmini/t1")
        self.assertEqual(len(after), mmini.SEEN_MAX)
        self.assertEqual(list(after)[-1], "mmini/t1")

    def test_seen_file_round_trip_and_junk(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            self.assertEqual(mmini.read_seen(state), {})
            mmini.write_seen({"mmini/t1": 2}, state)
            self.assertEqual(mmini.read_seen(state), {"mmini/t1": 2})
            (state / "seen.json").write_text('{"a": 1, "b": "2", "c": -1, "d": true, "": 3}')
            self.assertEqual(mmini.read_seen(state), {"a": 1})
            (state / "seen.json").write_text("junk")
            self.assertEqual(mmini.read_seen(state), {})

    def test_needs_text_keeps_the_mark_and_cuts_the_server(self):
        self.assertEqual(mmini.needs_text("tracker", "²", "", 25), "tracker²")
        self.assertEqual(mmini.needs_text("harry", "³", "guest@mini", 27), "harry³ · guest@mini")
        self.assertEqual(mmini.needs_text("harry", "³", "guest@mini", 16), "harry³ · guest@…")
        self.assertEqual(mmini.needs_text("averyveryverylongname", "¹", "srv", 12), "aver…¹ · srv")  # half each
        self.assertEqual(mmini.needs_text("averyveryverylongname", "¹", "guest", 12), "aver…¹ · gu…")
        self.assertEqual(mmini.needs_text("averyveryverylongname", "¹", "srv", 10), "averyver…¹")  # no room: no server
        for room in range(1, 30):
            self.assertLessEqual(mmini.text_width(mmini.needs_text("averyveryverylongname", "¹", "guest", room)),
                                 room, room)


class AccountMarkTests(unittest.TestCase):
    """account_mark, account_marks and the width of a marked name (pure)."""

    def test_the_rule(self):
        mark = mmini.account_mark
        # MMINI_MARKS of the tests: claude and main = ¹, work = ²; MMINI_SHARED_USER guest
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
        self.assertEqual(mmini.ssh_user(mmini.Machine("rig", "guest@mini")), "guest")
        self.assertEqual(mmini.ssh_user(mmini.Machine("rig", "guest@mini:2222")), "guest")
        self.assertEqual(mmini.ssh_user(mmini.Machine("rig", "vps")), "")
        self.assertEqual(mmini.ssh_user(mmini.Machine("rig", "guest@x", via=True)), "")
        self.assertEqual(mmini.ssh_user(None), "")

    def test_marks_from_labels_and_machines(self):
        terms = mmini.parse(ls(term("mmini/t1", agent="claude-code"), term("mmini/t2", agent="claude-code"),
                               term("mmini/t3", agent="claude-code"), term("mmini/t4", agent="claude-code"),
                               term("guest/t1", agent="claude-code"), term("guest/t2", agent="zsh")))
        infos = {"mmini/t1": mmini.Info(account="main"), "mmini/t2": mmini.Info(account="work"),
                 "mmini/t3": mmini.Info(account="other"), "mmini/t4": mmini.Info(account="claude")}
        machines = [mmini.Machine("mmini", "me@mini"), mmini.Machine("guest", "guest@mini")]
        self.assertEqual(mmini.account_marks(terms, infos, machines),
                         {"mmini/t1": "¹", "mmini/t2": "²", "mmini/t3": "³", "mmini/t4": "¹", "guest/t1": "³"})

    def test_parse_info_reads_the_account(self):
        raw = json.dumps({"labels": {"account": " main ", "space": "dev"}, "parent": None})
        self.assertEqual(mmini.parse_info(raw, "t1"), mmini.Info("dev", "", True, "main"))
        self.assertEqual(mmini.parse_info('{"labels": {"account": 3}}', "t1").account, "")

    def test_with_mark_never_loses_the_mark_and_fits(self):
        self.assertEqual(mmini.with_mark("tracker", "²", 30), "tracker²")
        self.assertEqual(mmini.with_mark("tracker", "²", 6), "trac…²")
        self.assertEqual(mmini.with_mark("tracker", "", 6), "track…")
        self.assertEqual(mmini.with_mark("t", "¹", 2), "t¹")
        for room in range(0, 12):
            for name in ("tracker", "a", "日本語の名前"):
                text = mmini.with_mark(name, "³", room)
                self.assertLessEqual(mmini.text_width(text), room, (name, room))
                if room >= 2:
                    self.assertTrue(text.endswith("³"), (name, room, text))

    def test_tab_labels_carry_the_mark(self):
        self.assertEqual(mmini.tab_label({"label": "tracker", "mark": "²"}), "tracker²")
        self.assertEqual(mmini.tab_label({"label": "tracker", "mark": "x"}), "tracker")  # only a known mark
        self.assertEqual(mmini.tab_label({"label": "tracker"}), "tracker")
        segs, _, _ = mmini.flow_tabs(["averyveryverylongname¹"], 12)
        self.assertEqual(segs[0].text, " ● averyv…¹ ")  # 8 columns for the label: the mark stays

    def test_ascii_screen_stand_ins(self):
        with mock.patch.object(mmini, "utf8_screen", return_value=False):
            self.assertEqual(mmini.glyph("a¹ b² c³"), "a1 b2 c3")


class KeychainTests(unittest.TestCase):
    """The keychain check: its call, its answer, its schedule, its line (pure)."""

    def test_the_call_is_an_argument_list_on_the_home_machine(self):
        args = mmini.exec_args("mmini", mmini.KEYCHAIN_SCRIPT)
        self.assertEqual(args, ["exec", "--json", "--timeout", "20", "--on", "mmini", "/bin/sh", "-c",
                                mmini.KEYCHAIN_SCRIPT])
        self.assertNotIn("--on", mmini.exec_args(mmini.LOCAL, mmini.KEYCHAIN_SCRIPT))
        self.assertIn("show-keychain-info", mmini.KEYCHAIN_SCRIPT)
        self.assertNotIn("unlock", mmini.KEYCHAIN_SCRIPT)  # it never unlocks, never asks for a password

    def test_parse(self):
        parse = mmini.parse_keychain
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
        self.assertEqual(mmini.check_keychain("mmini", hc), "unlocked")
        self.assertEqual(hc.calls[-1], tuple(mmini.exec_args("mmini", mmini.KEYCHAIN_SCRIPT)))
        hc.keychain = (36, "User interaction is not allowed.")
        self.assertEqual(mmini.check_keychain("mmini", hc), "locked")
        hc.fail = '{"error":{"kind":"machine_unknown","message":"unknown machine"}}'
        self.assertEqual(mmini.check_keychain("mmini", hc), "failed")

    def test_the_schedule_start_then_every_four_hours(self):
        due = mmini.keychain_due
        self.assertTrue(due(None, "unknown", 0.0))  # at the start
        self.assertFalse(due(100.0, "unlocked", 100.0 + 4 * 3600 - 1))
        self.assertTrue(due(100.0, "unlocked", 100.0 + 4 * 3600))
        self.assertFalse(due(100.0, "locked", 159.0))  # locked: again a minute later, so the line goes soon
        self.assertTrue(due(100.0, "locked", 160.0))
        self.assertFalse(due(100.0, "failed", 399.0))
        self.assertTrue(due(100.0, "failed", 400.0))

    def test_failed_checks_back_off_to_the_four_hours(self):
        due = mmini.keychain_due
        waits = []
        for fails in range(1, 12):
            wait = next(w for w in range(60, 5 * 3600, 60) if due(0.0, "failed", float(w), fails))
            waits.append(wait)
        self.assertEqual(waits[:7], [300, 600, 1200, 2400, 4800, 9600, 14400])  # 5 min, doubled, then 4 hours
        self.assertEqual(set(waits[6:]), {14400})
        self.assertTrue(due(0.0, "failed", 4 * 3600.0, 10 ** 6))  # never longer than 4 hours, no overflow
        self.assertFalse(due(0.0, "unlocked", 4 * 3600.0 - 1, 9))  # the count only matters after a failure

    def test_the_line_fits(self):
        self.assertEqual(mmini.keychain_text(29), " keychain locked: API billing")
        self.assertEqual(mmini.keychain_text(60), " keychain locked: sessions bill the API")
        self.assertEqual(mmini.keychain_text(11), " keychain")
        self.assertEqual(mmini.keychain_text(5), "! key")
        self.assertEqual(mmini.keychain_text(1), "!")
        self.assertEqual(mmini.keychain_text(0), "")
        for room in range(0, 40):
            self.assertLessEqual(mmini.text_width(mmini.keychain_text(room)), room)

    def test_frame_and_line(self):
        self.assertEqual(mmini.sidebar_frame(24, False, False, keychain=True), (22, 23, -1, 0))
        self.assertEqual(mmini.keychain_line(24, False, True), 22)
        self.assertEqual(mmini.keychain_line(24, True, True), 21)  # the strip's "› open" below it
        self.assertEqual(mmini.keychain_line(24, False, False), -1)
        self.assertEqual(mmini.sidebar_frame(24, True, False, keychain=True), (21, 23, -1, 1))
        for height in range(0, 12):
            for strip in (False, True):
                body, arrow, opener, extra = mmini.sidebar_frame(height, True, False, strip, keychain=True)
                y = mmini.keychain_line(height, strip, True)
                if y >= 0:
                    self.assertEqual(y, body + extra, (height, strip))  # right below the list and the message
                    self.assertNotIn(y, (arrow, opener))
                self.assertGreaterEqual(body, 1 if height >= 2 else 0, (height, strip))
        self.assertEqual(mmini.sidebar_frame(20, True, False, message_lines=3), (16, 19, -1, 3))
        self.assertEqual(mmini.sidebar_frame(4, True, False, message_lines=3), (2, 3, -1, 1))

    def test_a_click_on_the_line(self):
        self.assertEqual(mmini.sidebar_hit(22, 23, -1, {22: mmini.NEW_SPACE}, 3, keychain_y=22), ("keychain", None))


class DevServerTests(unittest.TestCase):
    """The dev servers: lsof's answer, the rows, the URL (pure)."""

    def test_parse_lsof(self):
        devs = mmini.parse_dev_servers(LSOF)
        self.assertEqual([(d.port, d.folder, d.pid) for d in devs],
                         [(3917, "/Users/x/dev/.wt/site/feature", 88581),
                          (5173, "/Users/x/dev/docs-site", 90001), (8080, "/Users/x", 90003)])
        self.assertEqual([d.label for d in devs], [":3917 feature", ":5173 docs-site", ":8080 x"])
        self.assertEqual(mmini.DevServer(3000).label, ":3000")

    def test_parse_empty_and_junk(self):
        self.assertEqual(mmini.parse_dev_servers(""), [])
        self.assertEqual(mmini.parse_dev_servers("\n--cwd\n"), [])  # lsof found nothing
        self.assertEqual(mmini.parse_dev_servers("pX\ncnode\nf1\nn*:http\nf2\nn*:0\nf3\nn*:70000\nf4\nnjunk\n"), [])

    def test_listen_port(self):
        self.assertEqual(mmini.listen_port("*:3917"), 3917)
        self.assertEqual(mmini.listen_port("[::]:3000"), 3000)
        self.assertEqual(mmini.listen_port("0.0.0.0:80"), 80)
        self.assertEqual(mmini.listen_port("100.64.1.2:3000"), 3000)
        for name in ("127.0.0.1:3000", "[::1]:3000", "localhost:3000", "[::ffff:127.0.0.1]:3000", "*:", "*:65536"):
            self.assertIsNone(mmini.listen_port(name), name)

    def test_the_script_is_fixed_and_lists_node_only(self):
        self.assertIn("-sTCP:LISTEN -a -c node", mmini.DEV_SCRIPT)
        self.assertEqual(mmini.exec_args("mmini", mmini.DEV_SCRIPT)[-3:], ["/bin/sh", "-c", mmini.DEV_SCRIPT])

    def test_fetch(self):
        hc = FakeHc([])
        hc.lsof = LSOF
        self.assertEqual([d.port for d in mmini.fetch_dev_servers("mmini", hc)], [3917, 5173, 8080])
        hc.fail = '{"error":{"kind":"x","message":"down"}}'
        self.assertIsNone(mmini.fetch_dev_servers("mmini", hc))

    def test_the_schedule(self):
        self.assertTrue(mmini.dev_due(None, 5.0))
        self.assertFalse(mmini.dev_due(10.0, 69.0))
        self.assertTrue(mmini.dev_due(10.0, 70.0))

    def test_home_host(self):
        machines = [mmini.Machine("mmini", "me@mini"), mmini.Machine("v6", "me@[fd00::1]:22"),
                    mmini.Machine("port", "me@box.lan:2222"), mmini.Machine("alias", "minihost"),
                    mmini.Machine("via", "wsl.exe -e sh -c", via=True), mmini.Machine("bad", "me@-oProxy")]
        self.assertEqual(mmini.home_host(machines, "mmini"), "mini")
        self.assertEqual(mmini.home_host(machines, "v6"), "[fd00::1]")
        self.assertEqual(mmini.home_host(machines, "port"), "box.lan")
        self.assertEqual(mmini.home_host(machines, "alias"), "minihost")
        self.assertEqual(mmini.home_host(machines, "via"), "via")  # its hc name
        self.assertEqual(mmini.home_host(machines, "bad"), "")
        self.assertEqual(mmini.home_host([], "mmini"), "mmini")
        self.assertEqual(mmini.home_host(machines, mmini.LOCAL), "localhost")

    def test_open_url_args_are_a_list_and_checked(self):
        self.assertEqual(mmini.open_url_args("mmini", 3917), ["/usr/bin/open", "http://mmini:3917/"])
        self.assertEqual(mmini.open_url_args("[fd00::1]", 1), ["/usr/bin/open", "http://[fd00::1]:1/"])
        self.assertEqual(mmini.open_url_args("mmini", 65535)[1], "http://mmini:65535/")
        for port in (0, 65536, -1, "3917", 3917.0, True, None):
            with self.assertRaises(ValueError, msg=port):
                mmini.open_url_args("mmini", port)
        for host in ("", "-oProxy", "a b", "mmini;rm -rf ~", "mmini/x", "$(id)", "mmini\n"):
            with self.assertRaises(ValueError, msg=host):
                mmini.open_url_args(host, 3917)

    def test_open_url_never_runs_in_tests(self):
        with mock.patch.object(mmini.subprocess, "Popen") as popen:
            self.assertFalse(mmini.open_url("mmini", 3917))  # MMINI_GHOSTTY=0 (set for all tests)
            with mock.patch.dict(os.environ, {"MMINI_GHOSTTY": "1", "MMINI_BROWSER": "0"}):
                self.assertFalse(mmini.open_url("mmini", 3917))
            popen.assert_not_called()
            with mock.patch.dict(os.environ, {"MMINI_GHOSTTY": "1", "MMINI_BROWSER": "1"}):
                self.assertTrue(mmini.open_url("mmini", 3917))
            popen.assert_called_once()
            self.assertEqual(popen.call_args[0][0], ["/usr/bin/open", "http://mmini:3917/"])  # a list: no shell
            self.assertNotIn("shell", popen.call_args[1])


class SwitchFileTests(unittest.TestCase):
    """The shared files "agents" and "devservers" (shown by default) next to "servers" (hidden by default)."""

    def test_defaults_and_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            self.assertTrue(mmini.read_agents_shown(state))
            self.assertTrue(mmini.read_devs_shown(state))
            mmini.write_agents_shown(False, state)
            mmini.write_devs_shown(False, state)
            self.assertEqual(mmini.read_text(state / "agents"), "hidden")
            self.assertEqual(mmini.read_text(state / "devservers"), "hidden")
            self.assertFalse(mmini.read_agents_shown(state))
            self.assertFalse(mmini.read_devs_shown(state))
            mmini.write_agents_shown(True, state)
            self.assertTrue(mmini.read_agents_shown(state))
            (state / "devservers").write_text("junk\n")
            self.assertTrue(mmini.read_devs_shown(state))  # junk: the default


def sections_sample(needs=2, devs=2, agents=True, servers=True):
    spaces, rigs = mmini.build_groups(mmini.parse(SAMPLE), "mmini", machines=["mmini", "rig"])
    terms = [t for g in spaces + rigs for t in g.terms if t.is_agent][:needs]
    return mmini.Sections(spaces, rigs, servers, terms, [mmini.DevServer(3917 + i, "/Users/x/dev/w") for i in
                                                          range(devs)], agents)


class SectionsLayoutTests(unittest.TestCase):
    """plan_sidebar and selectable_items with "needs you", dev servers and the agents hidden (pure)."""

    def test_order_top_to_bottom(self):
        sec = sections_sample()
        plan = sec.plan(40)
        kinds = [r.kind for _, r in plan]
        heads = [r.text for _, r in plan if r.kind == "header"]
        self.assertEqual(heads, ["needs you", "spaces", "servers", "dev servers"])
        self.assertLess(kinds.index("dev"), kinds.index("rule"))
        self.assertEqual(kinds[:2], ["header", "needs"])
        items = sec.items()
        self.assertEqual([i.kind for i in items[:2]], ["needs", "needs"])
        self.assertEqual([i for i in items if i.kind == "dev"], [mmini.Item("dev", "", "3917"),
                                                                  mmini.Item("dev", "", "3918")])
        for _, row in plan:  # every row's item index names its own item
            if row.item >= 0:
                item = items[row.item]
                if row.kind == "needs":
                    self.assertEqual(item, mmini.Item("needs", "", row.term.address))
                elif row.kind == "dev":
                    self.assertEqual(item, mmini.Item("dev", "", str(row.dev.port)))
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
            self.assertEqual(mmini.rule_line(plan, 40), 40)
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

    MACHINES = [("mmini", "me@mini"), ("guest", "guest@mini")]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"
        terms = [tterm("mmini/t1", "/Users/x/dev", "claude-code", "atlas", "idle", 3),
                 tterm("mmini/t2", "/Users/x/dev", "claude-code", "tracker", "done", 2),
                 tterm("mmini/t3", "/Users/x/dev/other", "claude-code", "o1", "blocked", 1),
                 tterm("mmini/t4", "/Users/x/dev/other", "zsh", "sh"),
                 tterm("mmini/t5", "/Users/x/dev", "claude-code", "gecko", "working", 0),
                 tterm("guest/t1", "/Users/guest", "claude-code", "harry", "done", 1)]
        infos = {"mmini/t1": {"labels": {"account": "main"}}, "mmini/t2": {"labels": {"account": "work"}},
                 "mmini/t3": {"labels": {"account": "team"}}}
        self.hc = FakeHc(terms, infos, machines=self.MACHINES)
        self.hc.lsof = LSOF
        for target, value in ((mmini, {"run_hc": self.hc, "FIRST": "mmini"}),
                              (mmini.curses, {"color_pair": lambda n: n << 8})):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.scr = FakeScr(40, 30)
        self.side = mmini.Sidebar(self.scr, self.state, self.win)
        self.side.refresh_once()
        self.now = 1000.0
        self.side.refresh_extras(self.now)
        self.side.sync()
        self.side.draw()

    key = SidebarLogicTests.key

    def mouse(self, x, y, bstate=None):
        with pressed(x, y) if bstate is None else mouse_at(x, y, bstate):
            self.key(mmini.curses.KEY_MOUSE)

    def lines(self):
        return [mmini.glyph(line) for line in self.scr.lines()]

    def lock(self):
        self.hc.keychain = (36, "security: SecKeychainCopySettings x: User interaction is not allowed.\n")
        self.now += mmini.KEYCHAIN_SECONDS
        self.side.refresh_extras(self.now)
        self.side.draw()

    def test_needs_you_at_the_very_top(self):
        lines = self.lines()
        self.assertEqual(lines[0], " needs you")
        self.assertTrue(lines[1].startswith(mmini.glyph(" ● o1³")) and lines[1].endswith("blocked"), lines[1])
        self.assertTrue(lines[2].startswith(mmini.glyph(" ● harry³ · guest@mini")) and lines[2].endswith("done"),
                        lines[2])  # not on the home machine: its server too
        self.assertTrue(lines[3].startswith(mmini.glyph(" ● tracker²")) and lines[3].endswith("done"), lines[3])
        self.assertEqual(lines[4:6], ["", " spaces"])

    def test_enter_on_a_needs_row_shows_it_and_clears_a_done(self):
        self.key("k")  # the cursor starts on the current group: up to the needs rows
        while self.side.cursor_item().kind != "needs" or self.side.cursor_item().address != "mmini/t2":
            self.key("k")
        self.key(10)
        self.assertEqual(mmini.current_target(self.win), "mmini/t2")
        self.assertEqual(mmini.read_seen(self.state), {"mmini/t2": 2})
        self.assertNotIn("tracker", " ".join(self.lines()[:4]))  # looked at: gone from "needs you"
        mmini.show("mmini/t1", self.win)  # another terminal shown: tracker stays seen until its next done
        self.key(-1)
        self.assertNotIn("tracker", " ".join(self.lines()[:4]))
        self.hc.find("mmini/t2")["turn"] = 3  # it worked again and is done again
        self.side.refresh_once()
        self.key(-1)
        self.assertIn("tracker", " ".join(self.lines()[:5]))

    def test_a_click_on_a_needs_row_of_a_hidden_server_shows_it(self):
        self.assertFalse(self.side.servers_shown())
        y = next(i for i, line in enumerate(self.lines()) if "harry" in line)
        self.mouse(5, y)
        self.assertEqual(mmini.current_target(self.win), "guest/t1")
        self.assertEqual(mmini.read_seen(self.state), {"guest/t1": 1})
        self.assertNotIn("harry", " ".join(self.lines()[:4]))

    def test_blocked_stays_until_it_is_no_longer_blocked(self):
        y = next(i for i, line in enumerate(self.lines()) if " o1" in line and "blocked" in line)
        self.mouse(5, y)
        self.assertEqual(mmini.current_target(self.win), "mmini/t3")
        self.assertNotIn("o1", " ".join(self.lines()[:4]))  # shown here: left out
        mmini.show("mmini/t1", self.win)
        self.key(-1)
        self.assertIn("o1", " ".join(self.lines()[:4]))

    def test_marks_on_agent_rows_and_tabs(self):
        lines = self.lines()
        agents = lines[next(i for i, line in enumerate(lines) if line.startswith(" agents")):]
        text = "\n".join(agents)
        self.assertIn(mmini.glyph("atlas¹"), text)
        self.assertIn(mmini.glyph("tracker²"), text)
        self.assertIn(mmini.glyph("o1³"), text)
        self.assertIn(mmini.glyph(" gecko "), text)  # no label: no mark
        snap = mmini.read_snapshot(self.win)
        self.assertEqual({t["label"]: t["mark"] for t in snap["tabs"]},
                         {"atlas": "¹", "tracker": "²", "gecko": ""})
        self.assertEqual(mmini.tabs_title(snap, "mmini/t2"), "tracker · me@mini")  # never in the title

    def test_marks_in_the_strip(self):
        self.key("c")
        for width in (6, 8, 12):
            self.scr.width = width
            self.side.draw()
            atlas = [line for line in self.scr.lines() if "¹" in line or "1" in mmini.glyph(line)]
            self.assertTrue(atlas, width)
            self.assertTrue(all(mmini.text_width(line) <= width - 1 for line in self.scr.lines()), width)

    def test_labels_of_other_machines_are_fetched_once_not_every_round(self):
        gets = [c for c in self.hc.calls if c[0] == "get"]
        self.assertIn(("get", "guest/t1", "--json"), gets)
        self.hc.calls.clear()
        self.side.refresh_once()
        self.assertFalse([c for c in self.hc.calls if c[0] == "get"])  # known: no hc get until the next full round
        self.side.refresh_once(full=True)
        self.assertIn(("get", "guest/t1", "--json"), self.hc.calls)
        self.assertEqual(self.side.infos["guest/t1"], mmini.Info())  # no space, no parent off the home machine

    def test_keychain_line_only_while_locked(self):
        self.assertNotIn("keychain", " ".join(self.lines()))
        self.lock()
        lines = self.lines()
        self.assertEqual(lines[38], " keychain locked: API billing")
        self.assertEqual(self.side.keychain_y, 38)
        self.assertEqual(self.scr.cells[(38, 1)][1], (1 << 8) | mmini.curses.A_BOLD)  # red
        self.assertEqual(lines[39], mmini.glyph(fold_line("open")))
        self.hc.keychain = (0, "")
        self.now += mmini.KEYCHAIN_LOCKED_SECONDS  # locked: checked again a minute later
        self.side.refresh_extras(self.now)
        self.side.draw()
        self.assertNotIn("keychain", " ".join(self.lines()))
        self.hc.fail = '{"error":{"kind":"x","message":"down"}}'
        self.now += mmini.KEYCHAIN_SECONDS
        self.side.refresh_extras(self.now)
        self.side.draw()
        self.assertEqual(self.side.keychain, "failed")
        self.assertNotIn("keychain", " ".join(self.lines()))  # unknown: nothing

    def test_keychain_checked_at_start_then_every_four_hours(self):
        calls = lambda: sum(1 for c in self.hc.calls if mmini.KEYCHAIN_SCRIPT in c)
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
        self.assertEqual(run[0][:7], ("run", "--bg", "--json", "--no-parent", "--on", "mmini", "--name"))
        self.assertEqual(run[0][7], "unlock")
        self.assertNotIn("security", " ".join(run[0]))  # nothing is run or typed in it
        address = mmini.current_target(self.win)
        self.assertEqual(self.hc.find(address)["name"], "unlock")
        notice = " ".join(self.lines())
        self.assertIn("Claude sessions bill the API", notice)  # the whole text, wrapped
        time.sleep(mmini.MOUSE_QUIET)
        mmini.show("mmini/t1", self.win)
        self.mouse(3, self.side.keychain_y)  # it exists now: shown, not made again
        self.assertEqual(len([c for c in self.hc.calls if c[0] == "run"]), 1)
        self.assertEqual(mmini.current_target(self.win), address)
        self.assertFalse([c for c in self.hc.calls if c[0] in ("send", "keys", "put")])

    def test_dev_servers_section_and_open(self):
        lines = self.lines()
        at = lines.index(" dev servers")
        self.assertEqual(lines[at + 1:at + 4], ["   :3917 feature", "   :5173 docs-site", "   :8080 x"])
        self.assertLess(at, next(i for i, line in enumerate(lines) if line.startswith("─")))
        with mock.patch.object(mmini, "open_url", return_value=False) as opened:
            self.mouse(5, at + 1)
        opened.assert_called_once_with("mini", 3917)
        self.assertIn("http://mini:3917/", "".join(self.lines()))  # the notice wraps: the whole address

    def test_dev_servers_hidden_and_shown_with_w_and_polled_only_while_shown(self):
        self.key("w")
        self.assertFalse(mmini.read_devs_shown(self.state))
        self.assertNotIn(" dev servers", self.lines())
        self.hc.calls.clear()
        self.side.refresh_extras(self.now + 600)
        self.assertFalse([c for c in self.hc.calls if mmini.DEV_SCRIPT in c])
        self.key("w")
        self.side.refresh_extras(self.now + 601)
        self.assertTrue([c for c in self.hc.calls if mmini.DEV_SCRIPT in c])  # asked at once when shown
        self.assertIn(" dev servers", self.lines())

    def test_no_dev_servers_no_section(self):
        self.hc.lsof = "\n--cwd\n"
        self.side.refresh_extras(self.now + mmini.DEV_SECONDS)
        self.side.draw()
        self.assertNotIn(" dev servers", self.lines())

    def test_agents_hidden_with_g_and_back(self):
        while self.side.cursor_item().kind != "agent":
            self.key("j")
        self.key("g")
        self.assertFalse(mmini.read_agents_shown(self.state))
        lines = self.lines()
        self.assertFalse(any(line.startswith(" agents") or line.startswith("─") for line in lines))
        self.assertEqual(self.side.rule_y, -1)
        self.assertNotEqual(self.side.cursor_item().kind, "agent")  # back to a row that is drawn
        self.key("]")
        self.assertIsNone(mmini.read_split(self.state))  # [ and ] do nothing while hidden
        self.assertIn("agents hidden", " ".join(self.lines()))
        self.key("g")
        self.assertTrue(any(line.startswith(" agents") for line in self.lines()))

    def test_agents_hidden_from_the_menu_keeps_needs_you(self):
        self.key("a")
        entry = next(e for e in self.side.menu.entries if e.action == "agents")
        self.assertEqual(entry.label, "Hide agents")
        self.key("g")  # the entry's letter
        self.assertIsNone(self.side.menu)
        self.assertFalse(mmini.read_agents_shown(self.state))
        self.assertEqual(self.lines()[0], " needs you")

    def test_agents_hidden_drops_a_drag(self):
        y = self.side.rule_y
        self.mouse(3, y, PRESS1)
        self.assertIsNotNone(self.side.drag_y)
        self.side.toggle_agents()
        self.assertIsNone(self.side.drag_y)

    def keychain_calls(self):
        return [c for c in self.hc.calls if c[0] == "exec" and mmini.KEYCHAIN_SCRIPT in c]

    def test_extras_wait_for_a_listing_and_start_over_when_the_mini_turns_up(self):
        engine = mmini.Engine(self.state, self.win)
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
        self.assertEqual([c[4:6] for c in self.keychain_calls()], [("--on", "mmini")])
        self.assertEqual(engine.keychain, "locked")
        dev = [c for c in self.hc.calls if c[0] == "exec" and mmini.DEV_SCRIPT in c]
        self.assertEqual([c[4:6] for c in dev], [("--on", "mmini")])
        mmini.write_devs_shown(False, self.state)
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
        self.assertTrue([c for c in self.hc.calls if mmini.DEV_SCRIPT in c])

    def test_failed_checks_back_off(self):
        self.hc.fail = '{"error":{"kind":"x","message":"down"}}'
        start = self.now + mmini.KEYCHAIN_SECONDS
        at = []
        for minute in range(0, 4 * 60, 1):
            before = len(self.keychain_calls())
            self.side.refresh_extras(start + minute * 60.0)
            if len(self.keychain_calls()) > before:
                at.append(minute)
        self.assertEqual(at, [0, 5, 15, 35, 75, 155])  # 5, 10, 20, 40, 80 minutes apart: not every 5 minutes
        self.assertEqual((self.side.keychain, self.side.keychain_fails), ("failed", 6))
        self.hc.fail = ""
        self.side.refresh_extras(start + 155 * 60.0 + mmini.KEYCHAIN_SECONDS)
        self.assertEqual((self.side.keychain, self.side.keychain_fails), ("unlocked", 0))

    def test_hiding_the_agents_puts_the_cursor_on_the_current_group(self):
        while self.side.cursor_item().kind != "agent":
            self.key("j")
        self.key("g")
        self.assertEqual(self.side.cursor_item(), mmini.Item("group", self.side.cur, ""))

    def test_hiding_the_dev_servers_puts_the_cursor_on_the_current_group(self):
        while self.side.cursor_item().kind != "dev":
            self.key("j")
        self.key("w")
        self.assertEqual(self.side.cursor_item(), mmini.Item("group", self.side.cur, ""))

    def test_agents_hidden_in_another_window_drops_a_drag(self):
        y = self.side.rule_y
        self.mouse(3, y, PRESS1)
        self.assertIsNotNone(self.side.drag_y)
        mmini.write_agents_shown(False, self.state)  # another window hides them
        self.side.draw()
        self.assertIsNone(self.side.drag_y)
        mmini.write_agents_shown(True, self.state)  # and shows them again before the release
        self.side.draw()
        self.mouse(3, y - 4, RELEASE1)
        self.assertIsNone(mmini.read_split(self.state))  # the old drag never lands

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
        self.assertEqual(lines[0], " needs you")
        self.assertIn(" spaces", lines)
        self.assertIn(" dev servers", lines)
        self.assertTrue(any(line.startswith(" agents") for line in lines))
        self.assertEqual(lines[38], " keychain locked: API billing")
        self.assertTrue(all(mmini.text_width(line) <= 29 for line in self.scr.lines()))

    def test_help_lists_the_new_keys_and_the_marks(self):
        lines = mmini.help_lines(29, 40)
        self.assertIn(" g       show/hide agents", lines)
        self.assertIn(" w       dev servers on/off", lines)
        self.assertIn(" ¹       claude, main", lines)
        self.assertIn(" ²       work", lines)
        self.assertIn(" ³       other, guest", lines)


class SettingsTests(unittest.TestCase):
    """MMINI_FIRST, MMINI_MARKS, MMINI_SHARED_USER, MMINI_SHARED_MARK, MMINI_DEV_PROGRAM and MMINI_KEYCHAIN."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.win = self.state / "w-1"

    def engine(self, hc, first=""):
        for target, value in ((mmini, {"run_hc": hc, "FIRST": first}),):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        engine = mmini.Engine(self.state, self.win)
        engine.refresh_once()
        return engine

    def test_first_machine(self):
        M = mmini.Machine
        self.assertEqual(mmini.first_machine([M("box", "me@box")], "mini"), "mini")  # the setting wins
        self.assertEqual(mmini.first_machine([M("box", "me@box")], ""), "box")  # the only machine
        self.assertEqual(mmini.first_machine(["box", "box"], ""), "box")
        self.assertEqual(mmini.first_machine(["api", "web"], ""), mmini.LOCAL)  # two: this Mac
        self.assertEqual(mmini.first_machine([], ""), mmini.LOCAL)
        self.assertEqual(mmini.first_machine([], " "), mmini.LOCAL)
        self.assertEqual(mmini.first_machine([]), "mmini")  # MMINI_FIRST of the tests
        with mock.patch.object(mmini, "FIRST", ""):
            self.assertEqual(mmini.first_machine([M("box")]), "box")

    def test_without_mmini_first_the_only_machine_is_home(self):
        hc = FakeHc([term("box/t1", "/Users/me/dev/api", "claude-code", "api", "idle"),
                     term("box/t2", "/Users/me/dev/web", "zsh", "sh"), term("t1", "/Users/x", "zsh")],
                    machines=[("box", "me@box")])
        engine = self.engine(hc)
        self.assertEqual(engine.home(), "box")
        spaces, _ = engine.groups()
        self.assertEqual([g.name for g in spaces], ["api", "web"])
        self.assertEqual([(g.machine, g.home) for g in engine.rigs_all], [("box", True), (mmini.LOCAL, False)])

    def test_without_mmini_first_and_two_machines_this_mac_is_home(self):
        hc = FakeHc([term("api/t1", "/Users/me/dev/api", "zsh"), term("t1", "/Users/x/dev/docs", "zsh")],
                    machines=[("api", "me@api"), ("web", "me@web")])
        engine = self.engine(hc)
        self.assertEqual(engine.home(), mmini.LOCAL)
        spaces, _ = engine.groups()
        self.assertEqual([g.name for g in spaces], ["docs"])

    def test_parse_marks(self):
        self.assertEqual(mmini.parse_marks("claude=¹, main = ¹ ,work=²"), {"claude": "¹", "main": "¹", "work": "²"})
        self.assertEqual(mmini.parse_marks("a=¹,a=²"), {"a": "²"})
        for junk in ("", "x", "=¹", "a=", "a=¹²", "a=x", "a=7", "a= ", "a=\u0301", "a=\u4e00"):
            self.assertEqual(mmini.parse_marks(junk), {}, junk)

    def test_no_settings_no_marks_and_no_legend(self):
        mark = mmini.account_mark
        none = {"marks": {}, "shared_user": "", "shared_mark": "³"}
        for account, user in (("claude", ""), ("team", ""), ("", "guest"), ("", "")):
            self.assertEqual(mark("claude-code", account, user, **none), "")
        self.assertEqual(mmini.mark_legend(**none), [])
        with mock.patch.multiple(mmini, ACCOUNT_MARKS={}, SHARED_USER=""):
            self.assertEqual(mmini.help_entries(), list(mmini.KEY_HELP))
            self.assertEqual(len(mmini.help_lines(29, 40)), 1 + len(mmini.KEY_HELP))

    def test_shared_user_alone_and_its_mark(self):
        mark = mmini.account_mark
        self.assertEqual(mark("claude-code", "", "guest", marks={}, shared_user="guest", shared_mark="⁴"), "⁴")
        self.assertEqual(mark("claude-code", "", "me", marks={}, shared_user="guest", shared_mark="⁴"), "")
        self.assertEqual(mark("claude-code", "x", "guest", marks={}, shared_user="guest", shared_mark="⁴"), "")
        self.assertEqual(mark("zsh", "", "guest", marks={}, shared_user="guest", shared_mark="⁴"), "")
        self.assertEqual(mmini.mark_legend({}, "guest", "⁴"), [("⁴", "guest")])
        self.assertEqual(mmini.mark_legend({"a": "¹", "b": "³"}, "guest", "³"), [("¹", "a"), ("³", "b, other, guest")])

    def test_settings_read_at_start(self):
        code = ("import json, mmini; print(json.dumps([mmini.FIRST, mmini.ACCOUNT_MARKS, mmini.SHARED_USER, "
                "mmini.SHARED_MARK, mmini.DEV_PROGRAM, mmini.mark_legend()]))")

        def read(**settings):
            env = {k: v for k, v in os.environ.items() if not k.startswith("MMINI_")}
            env.update(MMINI_GHOSTTY="0", MMINI_STATE=str(self.state), PYTHONDONTWRITEBYTECODE="1", **settings)
            out = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, env=env, capture_output=True,
                                 text=True, timeout=30, check=False)
            self.assertEqual(out.returncode, 0, out.stderr)
            return json.loads(out.stdout)

        self.assertEqual(read(), ["", {}, "", "³", "node", []])
        self.assertEqual(read(MMINI_FIRST=" box ", MMINI_MARKS="a=¹,b=²", MMINI_SHARED_USER="guest",
                              MMINI_SHARED_MARK="⁴", MMINI_DEV_PROGRAM="bun"),
                         ["box", {"a": "¹", "b": "²"}, "guest", "⁴", "bun",
                          [["¹", "a"], ["²", "b"], ["³", "other"], ["⁴", "guest"]]])
        self.assertEqual(read(MMINI_SHARED_MARK="xy", MMINI_DEV_PROGRAM="a b")[3:5], ["³", "node"])
        self.assertFalse(self.state.exists())  # importing creates no folder

    def test_dev_program(self):
        for value, want in (("bun", "bun"), (" deno ", "deno"), ("", "node"), ("-x", "node"), ("a b", "node"),
                            ("a;b", "node"), ("x" * 16, "node"), ("x" * 15, "x" * 15)):
            self.assertEqual(mmini.dev_program(value), want, value)
        self.assertEqual(mmini.DEV_SCRIPT, mmini.dev_script("node"))
        self.assertIn("-sTCP:LISTEN -a -c bun -F pcn", mmini.dev_script("bun"))
        self.assertEqual(mmini.parse_dev_servers(LSOF, "bun"), [])
        bun = LSOF.replace("cnode\n", "cbun\n")
        self.assertEqual([d.port for d in mmini.parse_dev_servers(bun, "bun")], [3917, 5173, 8080])
        self.assertEqual(mmini.parse_dev_servers(bun), [])  # DEV_PROGRAM: node

    def test_keychain_off(self):
        hc = FakeHc([term("mmini/t1", "/Users/x/dev/api", "zsh")], machines=[("mmini", "me@mini")])
        engine = self.engine(hc, "mmini")
        keychain = lambda: [c for c in hc.calls if c[0] == "exec" and mmini.KEYCHAIN_SCRIPT in c]
        with mock.patch.dict(os.environ, {"MMINI_KEYCHAIN": "0"}):
            self.assertFalse(mmini.keychain_enabled())
            engine.refresh_extras(1000.0)
            engine.keychain_asked = True  # r
            engine.refresh_extras(1001.0)
        self.assertEqual(keychain(), [])
        self.assertEqual(engine.keychain, "unknown")
        self.assertTrue(mmini.keychain_enabled())
        engine.refresh_extras(1002.0)
        self.assertEqual(len(keychain()), 1)
        self.assertEqual(engine.keychain, "unlocked")


if __name__ == "__main__":
    unittest.main()
