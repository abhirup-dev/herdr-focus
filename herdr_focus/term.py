"""Terminal text helpers shared by effects: ANSI parsing, colors, the host palette."""

import os
import re
import select
import sys
import time

ANSI = re.compile(r"\x1b\[[0-9;:?<=>]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
RESET = "\x1b[0m"
NAMED = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]
LEVELS = (0, 95, 135, 175, 215, 255)


def sgr_fg(color: str) -> str:
    """A foreground escape for a color name (`red`, `bright-black`), palette index (`208`) or `#RRGGBB`."""
    c = str(color).strip().lower()
    if c.removeprefix("bright-") in NAMED:
        base = 90 if c.startswith("bright-") else 30
        return f"\x1b[0;{base + NAMED.index(c.removeprefix('bright-'))}m"
    if c.isdigit() and int(c) < 256:
        return f"\x1b[0;38;5;{c}m"
    if re.fullmatch(r"#[0-9a-f]{6}", c):
        return "\x1b[0;38;2;{};{};{}m".format(*(int(c[i : i + 2], 16) for i in (1, 3, 5)))
    raise ValueError(f"unknown color {color!r}")


def clip_ansi(line: str, width: int) -> str:
    """Keep the first `width` printable characters; escape sequences pass through."""
    out, left, pos = [], width, 0
    for m in [*ANSI.finditer(line), None]:
        text = line[pos : m.start() if m else len(line)]
        out.append(text[: max(left, 0)])
        left -= len(text)
        if m:
            out.append(m.group())
            pos = m.end()
    return "".join(out)


def palette(n: int, colors: dict) -> tuple | None:
    """RGB of xterm palette entry n: 0-15 as the terminal reported them, 16-255 by the standard formula."""
    if n < 16:
        return colors.get(n)
    if n < 232:
        n -= 16
        return LEVELS[n // 36], LEVELS[n // 6 % 6], LEVELS[n % 6]
    v = 8 + 10 * (n - 232)
    return v, v, v


def apply_sgr(params: str, fg, bg, colors: dict) -> tuple:
    """Track foreground/background through one SGR sequence (None = terminal default)."""
    ps = [int(p) if p.isdigit() else 0 for p in re.split("[;:]", params)]
    i = 0
    while i < len(ps):
        p = ps[i]
        if p == 0:
            fg = bg = None
        elif 30 <= p <= 37 or 90 <= p <= 97:
            fg = palette(p - 30 if p < 90 else p - 82, colors)
        elif 40 <= p <= 47 or 100 <= p <= 107:
            bg = palette(p - 40 if p < 100 else p - 92, colors)
        elif p == 39:
            fg = None
        elif p == 49:
            bg = None
        elif p in (38, 48) and i + 2 < len(ps):
            if ps[i + 1] == 5:
                c, i = palette(ps[i + 2], colors), i + 2
            elif ps[i + 1] == 2 and i + 4 < len(ps):
                c, i = tuple(ps[i + 2 : i + 5]), i + 4
            else:
                c = None
            fg, bg = (c, bg) if p == 38 else (fg, c)
        i += 1
    return fg, bg


def recolor(line: str, colors: dict, transform) -> str:
    """Rewrite every color in the line through transform(rgb) -> rgb, the terminal default included.
    Without the terminal's colors there is nothing to transform: returns None."""
    if "fg" not in colors or "bg" not in colors:
        return None
    fg = bg = None

    def override() -> str:
        s = "\x1b[38;2;{};{};{}m".format(*transform(fg or colors["fg"]))
        return s + ("\x1b[48;2;{};{};{}m".format(*transform(bg)) if bg else "")

    out, pos = [override()], 0
    for m in ANSI.finditer(line):
        out += [line[pos : m.start()], m.group()]
        pos = m.end()
        if m.group().startswith("\x1b[") and m.group().endswith("m"):
            fg, bg = apply_sgr(m.group()[2:-1], fg, bg, colors)
            out.append(override())
    out.append(line[pos:])
    return "".join(out)


def faint(line: str) -> str:
    """The faint attribute on every run of the line, surviving its own SGR resets."""
    return "\x1b[2m" + re.sub(r"(\x1b\[[0-9;:]*m)", "\\1\x1b[2m", line)


def query_colors(fd: int, timeout: float = 0.3) -> dict:
    """Ask the terminal (Herdr relays the host's) for its fg, bg and 16 palette colors."""
    sys.stdout.write("\x1b]10;?\x07\x1b]11;?\x07" + "".join(f"\x1b]4;{i};?\x07" for i in range(16)))
    sys.stdout.flush()
    buf, end = b"", time.monotonic() + timeout
    colors: dict = {}
    while len(colors) < 18 and time.monotonic() < end:
        if select.select([fd], [], [], 0.02)[0]:
            buf += os.read(fd, 4096)
            for m in re.finditer(rb"\x1b\](10|11|4;(\d+));rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)", buf):
                key = {b"10": "fg", b"11": "bg"}.get(m.group(1)) or int(m.group(2))
                colors[key] = tuple(int(c[:2], 16) for c in m.groups()[2:])
    return colors
