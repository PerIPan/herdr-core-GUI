# Installing hcGUI: notes for AI agents

Read this before installing or setting up hcGUI for a person. README.md has the details; this file says what to
check, what to ask and what never to change on your own.

## 1. Install

```sh
git clone https://github.com/PerIPan/herdr-core-GUI ~/.local/share/hcgui && sh ~/.local/share/hcgui/build.sh
```

`build.sh` stops with a message when a requirement is missing (Ghostty 1.3.0+, tmux 3.5+, `python3` with curses,
`~/.local/bin/hc`). Report that message; install a missing tool only with the person's OK (`brew install tmux`).
Never use admin rights (sudo).

Read the last lines `build.sh` prints, under `setup (README: Setup; AI agents: AGENTS.md):`. They say which
machine is home, whether the usage lines are set up and what is left. Your shell may not read `~/.zshrc`; `build.sh`
reads its `export` lines for this report.

## 2. Ask before setting anything

Most setups need nothing more (README: Setup). Ask the person, and set only what they answer:

- **Several servers in `hc machine ls`:** which one is home (its terminals become spaces)? Then add
  `export HCGUI_FIRST=<name>` to `~/.zshrc`.
- **5-hour usage lines:** wanted? Which Claude config folders, and one short name per subscription
  (1 to 32 of `A-Z a-z 0-9 . _ -`)? One subscription needs one name; two need two.
- **Marks after agent names:** only with two or more subscriptions. `export HCGUI_MARKS="name1=¹,name2=²"`, the
  same names as the status line. One subscription: no marks, nothing to set.

## 3. Claude Code's status line (the usage lines)

On the home machine (README: 5-hour usage; a home machine that is not this Mac gets the clone too, `build.sh`
is not needed there, and needs `jq`):

- Back up each `settings.json` before changing it, change only the `statusLine` key, keep every other key.
- **A `statusLine` is already there:** never replace it. Run both, `usage.sh` first; the README gives the
  one-line command. Show the person the old and the new value.
- Config folders that share one `settings.json` pick the name by `CLAUDE_CONFIG_DIR` (README example).
- The same line labels each terminal with its subscription (`hc label <terminal> account=<name>`), once per
  terminal. Nothing to do by hand.

## 4. Never

- Edit Ghostty's config or `~/.tmux.conf` (hcGUI reads neither).
- Set `CLAUDE_CODE_DISABLE_TERMINAL_TITLE`: with it, Claude Code reports no status and the dots stay grey.
- Write a secret, token or password anywhere: hcGUI needs none.
- Remove `~/.local/state/hcgui` (display names and choices) unless the person asks.

## 5. Check, then hand over

- `sh ~/.local/share/hcgui/build.sh` again: its last lines show the new settings.
- Usage: after one answer in a session of each subscription, `~/.local/state/hcgui/usage/<name>.json` exists on
  the home machine.
- Status: `claude --version` is 2.1.295 or newer on every machine that runs agents, and
  `CLAUDE_CODE_DISABLE_TERMINAL_TITLE` is in no `env` block of Claude Code's `settings.json` nor in the shell.
  Agents run in herdr-core terminals (started there, `hc run` not needed); `hc get <terminal>` of a Claude Code
  terminal that answered shows `"reported": true` and a `status`. If not: tell the person, change nothing yourself.
- Labels: `hc get <terminal>` shows `"account": "<name>"` in `labels` for a Claude Code terminal that answered.
- Tell the person: close every hcGUI window, start hcGUI.app; settings are read when a window opens. You cannot
  see the window; ask them what it shows.

Update: `git -C ~/.local/share/hcgui pull && sh ~/.local/share/hcgui/build.sh`, then the same restart.
