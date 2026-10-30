"""herdr-focus: after a break, show which pane your keys will go to.

Subcommands (run by Herdr, see herdr-plugin.toml):
  startup      spawn this session's watcher once
  daemon       watch for a break: machine idle, or this session's terminal not frontmost
  tab-focused  open the cover when re-entering a tab unseen for tab_away_seconds
  show         snapshot the tab, then open the cover overlay
  ui           the cover itself, drawn by the configured effect; any key, click or scroll exits

Settings: $HERDR_PLUGIN_CONFIG_DIR/config.toml, documented in config.example.toml.
"""

import sys

from herdr_focus.cover import ui
from herdr_focus.herdr import log
from herdr_focus.triggers import daemon, show, startup, tab_focused

HANDLERS = {"startup": startup, "daemon": daemon, "tab-focused": tab_focused, "show": show, "ui": ui}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in HANDLERS:
        sys.exit(__doc__)
    try:
        HANDLERS[cmd]()
    except Exception as e:
        log(f"{cmd} failed: {e}")
        raise
