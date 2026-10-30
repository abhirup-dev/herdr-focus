"""Where each pane of the snapshot sits inside the cover, so every effect lines up with the real tab."""

from dataclasses import dataclass


@dataclass
class Pane:
    pane_id: str
    focused: bool
    x: int  # border corner, in cover cells (may be -1: under Herdr's frame)
    y: int
    width: int  # border included
    height: int
    content_width: int  # visible content columns inside the cover
    lines: list  # the pane's visible text, ANSI kept, one entry per content row


@dataclass
class Frame:
    """Everything an effect needs to draw one cover frame."""

    panes: list  # [Pane], unfocused first, focused last
    cols: int
    rows: int
    colors: dict  # host terminal colors: "fg", "bg", 0-15 -> (r, g, b); may be empty
    settings: dict  # this effect's settings from config.toml


def frame_rect(rect: dict, area: dict, gaps: bool) -> tuple:
    """The pane's border box in tab cells: (x, y, width, height), content one cell inside it.

    Measured on screenshots (Herdr 0.9.3):
      ui.pane_gaps = true   every pane draws its own full box inside its rect.
      ui.pane_gaps = false  neighbours share one divider, drawn in the right
                            (or lower) pane's first column (row); only panes on
                            the tab's right (bottom) edge draw that side. So the
                            box reaches one cell past the rect, except at an edge.
    """
    x, y, w, h = rect["x"], rect["y"], rect["width"], rect["height"]
    if not gaps:
        w += x + w < area["x"] + area["width"]
        h += y + h < area["y"] + area["height"]
    return x, y, w, h


def panes(layout: dict, cols: int, rows: int) -> list:
    # Herdr frames the overlay exactly where the tab's outer pane borders are,
    # so cover cell (0,0) is tab cell (ox,oy). Every cell is placed where it
    # really is: nothing shifts when the cover opens or closes.
    area = layout["area"]
    ox, oy = area["x"] + (area["width"] - cols) // 2, area["y"] + (area["height"] - rows) // 2
    out = []
    for p in layout["panes"]:
        fx, fy, w, h = frame_rect(p["rect"], area, layout.get("pane_gaps", True))
        x, y = fx - ox, fy - oy
        out.append(
            Pane(
                pane_id=p["pane_id"],
                focused=p["pane_id"] == layout["focused_pane_id"],
                x=x,
                y=y,
                width=w,
                height=h,
                content_width=min(w - 2, cols - (x + 1)),  # content sits one cell inside the border
                lines=p["text"].replace("\r", "").split("\n")[: h - 2],
            )
        )
    # Focused last: where boxes share a divider, its border is drawn on top.
    return sorted(out, key=lambda p: p.focused)


def at(row: int, col: int) -> str:
    """Cursor move to a 0-based cover cell."""
    return f"\x1b[{row + 1};{col + 1}H"


def box(pane: Pane, cols: int, rows: int, style: str) -> str:
    """The pane's border at its true position; cells outside the cover (under Herdr's frame) are skipped."""
    # Herdr's own thin glyphs: heavy ones sit differently in the cell and look shifted.
    h_, v, tl, tr, bl, br = "─│┌┐└┘"
    x, y, w, h = pane.x, pane.y, pane.width, pane.height
    cells = {}
    for col in range(x, x + w):
        cells[(y, col)] = cells[(y + h - 1, col)] = h_
    for row in range(y, y + h):
        cells[(row, x)] = cells[(row, x + w - 1)] = v
    cells.update({(y, x): tl, (y, x + w - 1): tr, (y + h - 1, x): bl, (y + h - 1, x + w - 1): br})
    return style + "".join(at(r, c) + ch for (r, c), ch in cells.items() if 0 <= r < rows and 0 <= c < cols)
