"""contrast: the focused pane as it is with a colored border; every other pane faded toward the background."""

from ..geometry import Frame, at, box
from ..term import RESET, clip_ansi, faint, recolor, sgr_fg

DEFAULTS = {
    "dim_strength": 0.3,
    "focused_border": "208",
    "dimmed_border": "bright-black",
}


def validate(key: str, value):
    """Return the value to use, or raise ValueError with the reason."""
    if key == "dim_strength":
        if not (isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1):
            raise ValueError("must be a number between 0 and 1")
    else:
        sgr_fg(value)
    return value


def render(frame: Frame) -> str:
    s = frame.settings
    hot, dim_border = sgr_fg(s["focused_border"]), sgr_fg(s["dimmed_border"])
    strength = s["dim_strength"]
    bg = frame.colors.get("bg")
    fade = lambda rgb: tuple(round(a + (b - a) * strength) for a, b in zip(rgb, bg))
    out = []
    for pane in frame.panes:
        for i, line in enumerate(pane.lines):
            row = pane.y + 1 + i
            if not (0 <= row < frame.rows and pane.content_width > 0):
                continue
            text = clip_ansi(line, pane.content_width)
            if not pane.focused:
                text = recolor(text, frame.colors, fade) or faint(text)
            out.append(at(row, pane.x + 1) + RESET + text + RESET)
        out.append(box(pane, frame.cols, frame.rows, hot if pane.focused else dim_border) + RESET)
    return "".join(out)
