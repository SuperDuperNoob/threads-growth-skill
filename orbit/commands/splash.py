from __future__ import annotations
import time
import math
from rich.console import Console
from rich.text import Text

console = Console()

LOGO = [
    "   ██████╗ ██████╗ ██████╗ ██╗████████╗",
    "  ██╔═══██╗██╔══██╗██╔══██╗██║╚══██╔══╝",
    "  ██║   ██║██████╔╝██████╔╝██║   ██║   ",
    "  ██║   ██║██╔══██╗██╔══██╗██║   ██║   ",
    "  ╚██████╔╝██║  ██║██████╔╝██║   ██║   ",
    "   ╚═════╝ ╚═╝  ╚═╝╚═════╝ ╚═╝   ╚═╝   ",
]

SUBTITLE = "content flywheel  ·  create · publish · analyze · grow"

# Orbital ring frames — a dot travelling around an ellipse
_RING = "·"
_PLANET = "●"
_ORBIT_WIDTH = 42
_ORBIT_HEIGHT = 5

def _orbit_frame(t: float) -> list[str]:
    """Render one frame of an orbiting dot around an ellipse."""
    cx = _ORBIT_WIDTH // 2
    cy = _ORBIT_HEIGHT // 2
    rx = cx - 1
    ry = cy - 1

    # Build empty grid
    grid = [[" "] * _ORBIT_WIDTH for _ in range(_ORBIT_HEIGHT)]

    # Draw ellipse outline
    for step in range(360):
        angle = math.radians(step)
        x = int(cx + rx * math.cos(angle))
        y = int(cy + ry * math.sin(angle) * 0.5)
        if 0 <= x < _ORBIT_WIDTH and 0 <= y < _ORBIT_HEIGHT:
            grid[y][x] = "·"

    # Draw orbiting planet
    angle = math.radians(t * 4 % 360)
    px = int(cx + rx * math.cos(angle))
    py = int(cy + ry * math.sin(angle) * 0.5)
    if 0 <= px < _ORBIT_WIDTH and 0 <= py < _ORBIT_HEIGHT:
        grid[py][px] = "●"

    # Center star
    grid[cy][cx] = "✦"

    return ["".join(row) for row in grid]


# Gradient colors for logo animation
_COLORS = [
    "#FF6B35", "#FF8C42", "#FFA94D",
    "#FFB347", "#FFC05C", "#FFD166",
]


def show_splash() -> None:
    """Display animated orbit splash screen, then clear and show static version."""
    import sys
    if not sys.stdout.isatty():
        _show_static()
        return

    frames = 60
    console.print()

    # Animate for ~1.5 seconds
    with console:
        for i in range(frames):
            t = i / frames * 360

            lines: list[str] = []

            # Logo with cycling color
            color = _COLORS[i % len(_COLORS)]
            for line in LOGO:
                lines.append(f"[bold {color}]{line}[/]")

            lines.append("")

            # Orbit animation
            for ring_line in _orbit_frame(t):
                # Color the planet brighter
                colored = ring_line.replace("●", f"[bold {color}]●[/]")
                colored = colored.replace("✦", f"[bold white]✦[/]")
                colored = colored.replace("·", "[dim white]·[/]")
                lines.append("  " + colored)

            lines.append("")
            lines.append(f"  [dim]{SUBTITLE}[/dim]")

            # Move cursor up to overwrite previous frame (after first frame)
            if i > 0:
                total_lines = len(LOGO) + 1 + _ORBIT_HEIGHT + 2
                console.print(f"\033[{total_lines}A", end="")

            for line in lines:
                console.print(line)

            time.sleep(0.025)

    console.print()


def _show_static() -> None:
    """Non-TTY fallback — plain logo, no animation."""
    console.print()
    for line in LOGO:
        console.print(f"[bold #FF6B35]{line}[/]")
    console.print()
    console.print(f"  [dim]{SUBTITLE}[/dim]")
    console.print()
