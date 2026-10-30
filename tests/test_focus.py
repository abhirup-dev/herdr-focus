"""Run with: python3 -m unittest discover tests"""

import os
import re
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp()
os.environ.update(HERDR_PLUGIN_CONFIG_DIR=TMP, HERDR_PLUGIN_STATE_DIR=TMP, HERDR_SOCKET_PATH="")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from herdr_focus import config as config_mod  # noqa: E402
from herdr_focus import cover  # noqa: E402
from herdr_focus.cover import should_dismiss  # noqa: E402
from herdr_focus.effects import EFFECTS, contrast  # noqa: E402
from herdr_focus.geometry import Frame, panes  # noqa: E402
from herdr_focus.term import apply_sgr, palette, recolor, sgr_fg  # noqa: E402
from herdr_focus import triggers  # noqa: E402
from herdr_focus.triggers import client_session  # noqa: E402

# The tab measured on screenshots: three side-by-side panes in a 205x50 tab.
AREA = {"x": 0, "y": 0, "width": 205, "height": 50}
RECTS = [(0, 97), (97, 59), (156, 49)]


def layout(gaps: bool) -> dict:
    return {
        "area": AREA,
        "focused_pane_id": "a",
        "pane_gaps": gaps,
        "panes": [
            {"pane_id": pid, "rect": {"x": x, "y": 0, "width": w, "height": 50}, "text": "x\r\n" * 48}
            for pid, (x, w) in zip("abc", RECTS)
        ],
    }


def vertical_borders(out: str, row: int) -> set:
    """Columns (tab cells) where a vertical border glyph is drawn on a cover row."""
    # Escape columns are 1-based cover cells; the cover starts at tab column 1, so they equal tab columns.
    return {int(c) for r, c, ch in re.findall(r"\x1b\[(\d+);(\d+)H(?:\x1b\[[0-9;]*m)*([│┌┐└┘])", out) if int(r) - 1 == row}


class Geometry(unittest.TestCase):
    def render(self, gaps: bool) -> str:
        frame = Frame(panes(layout(gaps), 203, 48), 203, 48, {}, dict(contrast.DEFAULTS))
        return contrast.render(frame)

    def test_gaps_on_every_pane_has_its_own_box(self):
        # Each rect's own edges; the outer ones (0, 204) are under Herdr's frame.
        self.assertEqual(vertical_borders(self.render(True), 10), {96, 97, 155, 156})

    def test_gaps_off_neighbours_share_one_divider(self):
        # Measured with pane_gaps = false: dividers at tab cols 97 and 156 only.
        self.assertEqual(vertical_borders(self.render(False), 10), {97, 156})

    def test_content_starts_after_the_left_border(self):
        # Pane b's rect starts at tab col 97; its content at tab col 98 (cover col 97) either way.
        for gaps in (True, False):
            b = {q.pane_id: q for q in panes(layout(gaps), 203, 48)}["b"]
            self.assertEqual(b.x + 1, 97, gaps)
            self.assertEqual(b.content_width, 57 if gaps else 58, gaps)

    def test_every_write_stays_inside_the_cover(self):
        for gaps in (True, False):
            out = self.render(gaps)
            for r, c in re.findall(r"\x1b\[(\d+);(\d+)H", out):
                self.assertTrue(1 <= int(r) <= 48 and 1 <= int(c) <= 203, (gaps, r, c))


class Colors(unittest.TestCase):
    def test_color_forms(self):
        self.assertEqual(sgr_fg("bright-black"), "\x1b[0;90m")
        self.assertEqual(sgr_fg("208"), "\x1b[0;38;5;208m")
        self.assertEqual(sgr_fg("#FE640B"), "\x1b[0;38;2;254;100;11m")
        for bad in ("nope", "300", "#12345"):
            self.assertRaises(ValueError, sgr_fg, bad)

    def test_sgr_tracking(self):
        self.assertEqual(palette(196, {}), (255, 0, 0))
        self.assertEqual(apply_sgr("38;2;1;2;3;48;5;21", None, None, {}), ((1, 2, 3), (0, 0, 255)))

    def test_fade_keeps_hue(self):
        colors = {"fg": (0, 0, 0), "bg": (200, 200, 200), 1: (200, 0, 0)}
        half = lambda c: tuple((a + b) // 2 for a, b in zip(c, colors["bg"]))
        self.assertIn("\x1b[38;2;100;100;100m", recolor("hi", colors, half))
        self.assertIn("\x1b[38;2;200;100;100m", recolor("\x1b[31mred", colors, half))
        self.assertIsNone(recolor("x", {}, half))


class Config(unittest.TestCase):
    def load(self, text: str) -> dict:
        path = Path(TMP) / "config.toml"
        path.write_text(text)
        return config_mod.load(path)

    def test_example_matches_defaults(self):
        example = tomllib.loads((ROOT / "config.example.toml").read_text())
        effects = example.pop("effects")
        self.assertEqual(example, config_mod.DEFAULTS)
        self.assertEqual(set(effects), set(EFFECTS))
        for name, settings in effects.items():
            self.assertEqual(settings, EFFECTS[name].DEFAULTS)

    def test_bad_values_fall_back(self):
        cfg = self.load(
            'idle_seconds = 5\nnope = 1\neffect = "sparkle"\npoll_seconds = "x"\n'
            '[effects.contrast]\ndim_strength = 2\nfocused_border = "red"\n'
        )
        self.assertEqual(cfg["idle_seconds"], 5)
        self.assertEqual(cfg["poll_seconds"], 2)
        self.assertEqual(cfg["effect"], "contrast")
        self.assertEqual(cfg["effect_settings"], dict(contrast.DEFAULTS, focused_border="red"))


class Processes(unittest.TestCase):
    def test_native_calls_see_this_process(self):
        self.assertTrue(Path(triggers._argv(os.getpid())[0]).name.startswith("python"))
        if sys.stdin.isatty():  # a pipe or CI has no controlling terminal
            self.assertEqual(triggers._tty(os.getpid()), os.ttyname(0))


class Refresh(unittest.TestCase):
    def test_other_panes_refresh_focused_keeps_snapshot(self):
        lay = {"panes": [{"pane_id": "a", "focused": True, "text": "old"}, {"pane_id": "b", "text": "old"}]}
        reads = []
        real = cover.call
        cover.call = lambda method, params: reads.append(params["pane_id"]) or {"read": {"text": "new"}}
        try:
            self.assertTrue(cover.refresh(lay))
            self.assertFalse(cover.refresh(lay))  # nothing new: no redraw
        finally:
            cover.call = real
        self.assertEqual(reads, ["b", "b"])
        self.assertEqual([p["text"] for p in lay["panes"]], ["old", "new"])


class Input(unittest.TestCase):
    def test_any_key_click_or_scroll_dismisses(self):
        for data in (b"a", b"\x1b[A", b"\x1b[<0;5;5M", b"\x1b[<64;5;5M"):
            self.assertTrue(should_dismiss(data), data)
        self.assertFalse(should_dismiss(b"\x1b]11;rgb:eeee/f1f1/f5f5\x07"))

    def test_client_command_lines(self):
        self.assertEqual(client_session(["herdr", "session", "attach", "work"]), "work")
        self.assertEqual(client_session(["/opt/homebrew/bin/herdr", "--session", "upt"]), "upt")
        self.assertEqual(client_session(["herdr"]), "default")
        self.assertIsNone(client_session(["herdr", "--session", "x", "server"]))


if __name__ == "__main__":
    unittest.main()
