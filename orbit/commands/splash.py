from __future__ import annotations
import time
import math
import sys
from rich.console import Console
from rich.live import Live
from rich.text import Text
from rich.align import Align

console = Console()

LOGO = """\
  ██████╗ ██████╗ ██████╗ ██╗████████╗
 ██╔═══██╗██╔══██╗██╔══██╗██║╚══██╔══╝
 ██║   ██║██████╔╝██████╔╝██║   ██║
 ██║   ██║██╔══██╗██╔══██╗██║   ██║
 ╚██████╔╝██║  ██║██████╔╝██║   ██║
  ╚═════╝ ╚═╝  ╚═╝╚═════╝ ╚═╝   ╚═╝  """

SUBTITLE = "content flywheel  ·  create · publish · analyze · grow"

_COLORS = ["#FF6B35", "#FF8450", "#FFA070", "#FFB347", "#FFD166", "#FFB347", "#FFA070", "#FF8450"]

# Orbit ring: 36 positions around an ellipse, rendered as a single line
_STEPS = 36
_RX = 18   # horizontal radius (chars)
_RY = 3    # vertical radius (lines)
_W = _RX * 2 + 3
_H = _RY * 2 + 1


def _render_frame(step: int) -> Text:
    color = _COLORS[step % len(_COLORS)]

    # Build logo
    out = Text()
    for line in LOGO.splitlines():
        out.append(line + "\n", style=f"bold {color}")
    out.append("\n")

    # Build orbit grid
    cx = _W // 2
    cy = _H // 2
    grid = [[" "] * _W for _ in range(_H)]

    # Draw ellipse
    for i in range(360):
        a = math.radians(i)
        x = int(round(cx + _RX * math.cos(a)))
        y = int(round(cy + _RY * math.sin(a)))
        if 0 <= x < _W and 0 <= y < _H:
            grid[y][x] = "·"

    # Center star
    grid[cy][cx] = "✦"

    # Moving planet
    planet_angle = math.radians((step / _STEPS) * 360)
    px = int(round(cx + _RX * math.cos(planet_angle)))
    py = int(round(cy + _RY * math.sin(planet_angle)))
    if 0 <= px < _W and 0 <= py < _H:
        grid[py][px] = "●"

    for row in grid:
        row_str = "".join(row)
        # color each character separately
        for ch in row_str:
            if ch == "●":
                out.append(ch, style=f"bold {color}")
            elif ch == "✦":
                out.append(ch, style="bold white")
            elif ch == "·":
                out.append(ch, style="dim white")
            else:
                out.append(ch)
        out.append("\n")

    out.append("\n")
    out.append(f"  {SUBTITLE}", style="dim")
    return out


def show_splash() -> None:
    if not sys.stdout.isatty():
        _show_static()
        return

    console.print()
    with Live(
        _render_frame(0),
        console=console,
        refresh_per_second=30,
        transient=False,
    ) as live:
        for step in range(_STEPS * 2):  # two full orbits
            live.update(_render_frame(step))
            time.sleep(0.05)

    console.print()


def _show_static() -> None:
    # Non-TTY means stdout is piped/redirected (e.g. `orbit draft --json`
    # consumed by Hermes). The splash is decoration — keep it off stdout so the
    # JSON payload stays the only thing there. Print to stderr instead.
    err = Console(stderr=True)
    err.print()
    err.print(LOGO, style="bold #FF6B35")
    err.print()
    err.print(f"  {SUBTITLE}", style="dim")
    err.print()
