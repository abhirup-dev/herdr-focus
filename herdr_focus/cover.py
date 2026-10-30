"""The cover: the overlay pane's process. Sizes itself, asks for the host colors, draws the chosen
effect, redraws panes that change behind it, and exits on the first key, click or scroll."""

import json
import os
import re
import select
import sys
import termios
import time
import tty
from pathlib import Path

from .config import config
from .effects import EFFECTS
from .geometry import Frame, panes
from .herdr import STATE_DIR, call, log
from .term import query_colors

OSC_REPLY = re.compile(rb"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def should_dismiss(data: bytes) -> bool:
    """Any key, click or scroll dismisses; late replies to our color queries do not."""
    return bool(OSC_REPLY.sub(b"", data))


def refresh(layout: dict) -> bool:
    """Re-read the panes so agents working behind the cover show their progress. True if any changed.
    The focused pane keeps its snapshot: under the overlay Herdr squeezes it, so a live read is narrow."""
    changed = False
    for p in layout["panes"]:
        if p.get("focused"):
            continue
        try:
            text = call("pane.read", {"pane_id": p["pane_id"], "source": "visible", "format": "ansi"})["read"]["text"]
        except Exception:
            continue  # pane closed or server busy: keep what we have
        if text != p["text"]:
            p["text"], changed = text, True
    return changed


def ui() -> None:
    (STATE_DIR / "cover.pid").write_text(str(os.getpid()))
    layout = json.loads(Path(os.environ["FOCUS_SNAPSHOT"]).read_text())
    cfg = config()
    effect = EFFECTS[cfg["effect"]]
    # Herdr opens the overlay at the displaced pane's size and resizes it to the
    # tab (minus its frame) on its next redraw. Output first: a silent pane gets none.
    want = (layout["area"]["width"] - 2, layout["area"]["height"] - 2)
    t0 = time.monotonic()
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[2J")
    sys.stdout.flush()
    deadline = t0 + cfg["resize_timeout_seconds"]
    while tuple(os.get_terminal_size()) != want and time.monotonic() < deadline:
        time.sleep(0.02)
    if cfg["debug"]:
        spawn = time.time() - float(os.environ.get("FOCUS_T0", "0")) - (time.monotonic() - t0)
        log(f"debug ui: spawned {spawn:.2f}s after show, sized in {time.monotonic() - t0:.2f}s")

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    # Ask for mouse reports (clicks and wheel, SGR encoding) so they reach us instead of Herdr.
    sys.stdout.write("\x1b[?1000h\x1b[?1006h")
    drawn = None
    next_refresh = time.monotonic() + cfg["refresh_seconds"]
    try:
        tty.setraw(fd)
        colors = query_colors(fd)
        if cfg["debug"]:
            log(f"debug ui: effect={cfg['effect']}, terminal reported {len(colors)}/18 colors")
        while True:
            size = tuple(os.get_terminal_size())
            if cfg["refresh_seconds"] > 0 and time.monotonic() >= next_refresh:
                next_refresh = time.monotonic() + cfg["refresh_seconds"]
                if refresh(layout):
                    drawn = None
            if size != drawn:  # redraw on resize, or when a refresh brought new pane text
                frame = Frame(panes(layout, *size), *size, colors, cfg["effect_settings"])
                # Synchronized output: the terminal shows the cleared and redrawn frame at once.
                sys.stdout.write("\x1b[?2026h\x1b[2J" + effect.render(frame) + "\x1b[?2026l")
                sys.stdout.flush()
                drawn = size
            if select.select([fd], [], [], 0.05)[0]:
                # The input that dismisses is swallowed: it never reaches a pane.
                if should_dismiss(os.read(fd, 1024)):
                    return
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        (STATE_DIR / "cover.pid").unlink(missing_ok=True)
