# herdr-focus

A [Herdr](https://herdr.dev) plugin for macOS. After a break, it covers the tab
and shows which pane your keys will go to: the focused pane as it is, every
other pane faded. Any key, click or scroll dismisses the cover; a key pressed to
dismiss it is not passed on.

## When the cover opens

| Trigger | Fires when |
|---|---|
| Idle | No keyboard or mouse input on the Mac for `idle_seconds` while this session is showing |
| Away | You come back to this session after `app_away_seconds` in another app or terminal tab |
| Stale tab | You switch to a Herdr tab you left `tab_away_seconds` ago |
| Manual | The `herdr-focus.show` action |

"Showing" means the frontmost terminal (Ghostty or iTerm) has a client of this
session in its selected tab. A session open in two terminals counts as showing
in either.

## Install

Requires macOS, Herdr 0.9 or newer and the system `python3` (standard library
only).

```sh
git clone https://github.com/abhirup-dev/herdr-focus
herdr plugin link herdr-focus
```

Bind the action in Herdr's `config.toml`:

```toml
[[keys.command]]
key = "prefix+ctrl+f"
type = "plugin_action"
command = "herdr-focus.show"
```

The first time the watcher reads the selected terminal tab, macOS asks whether
`python3` may control Ghostty (or iTerm). Allow it, or the session never counts
as showing.

## Configure

Copy [`config.example.toml`](config.example.toml) to
`$(herdr plugin config-dir herdr-focus)/config.toml`. Every key is optional and
documented there. Edits apply on the next watcher check; no restart needed.

The cover is drawn by an effect, chosen with `effect`. The only one so far is
`contrast`; effects live in [`herdr_focus/effects/`](herdr_focus/effects/).

## How it works

```
watcher (one per session, every poll_seconds)
  front app (lsappinfo) ─┐
  selected tab's tty  ───┼─▶ showing? ─▶ idle / away ─▶ show()
  this session's ttys ───┘                                 │
                                                           ▼
            snapshot every pane (pane.layout + pane.read), then open
            an overlay pane that redraws the snapshot through the effect
```

The snapshot is taken before the overlay opens because the overlay is a real
split: it halves the focused pane underneath. A check costs about 20 ms: native
`libproc` calls for the process scan, an in-process AppleScript for the
selected tab, and one `lsappinfo` call.

## Develop

```sh
python3 -m unittest discover tests
```

Logs go to `focus.log` under the plugin's state directory, one directory per
session. Set `debug = true` for frontmost-app changes and cover timings.
