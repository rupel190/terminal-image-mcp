# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp"]
# ///
"""wezterm-image-mcp — show an image from an MCP client.

A repainting TUI can't keep an inline image alive: it redraws its own region and
WezTerm stores images in the cell grid, so anything drawn inline gets shredded.
So instead of fighting it, this opens the image in its own WezTerm window.

The window is a standalone process, so closing it closes only it. One image at a
time — opening a new one closes the previous.
"""

import os
import shutil
import subprocess

from fastmcp import FastMCP

mcp = FastMCP("term-image")

WEZTERM = shutil.which("wezterm")
WINDOW_CLASS = "wezterm-image"

# The window's program. imgcat draws the image at whatever size the terminal is when
# it runs — and a window manager resizes the window *after* it has mapped, so a single
# draw is sized for the pty's 80x24 starting point and then sits in the corner of a
# much larger window (or, if the resize lands mid-draw, is clipped). Redrawing on
# SIGWINCH is what makes the image track the window it ends up in.
VIEWER = r"""
draw() { printf '\033[2J\033[H'; wezterm imgcat --width 100% --height 100% "$1"; }
trap 'draw "$1"' WINCH
draw "$1"
while :; do sleep 86400; done
"""

_proc: subprocess.Popen | None = None  # the current image window, if still open


def _close_previous() -> None:
    """Close the last image window so they do not accumulate."""
    global _proc
    if _proc is not None and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None


@mcp.tool()
async def show_image(file_path: str, cols: int | None = None, rows: int | None = None) -> str:
    """Show an image to the user in its own WezTerm window (PNG/JPEG/GIF/WebP/...).

    Use whenever the user asks to see an image, or to show them a file you're
    working with. The window is a standalone process the user can close on its own.
    Opening a new image closes the previous one.

    Args:
        file_path: Path to the image file.
        cols: Optional window width in columns. A window manager may override it.
        rows: Optional window height in rows. Same.
    """
    if not WEZTERM:
        return "Error: wezterm not found on PATH"
    path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.exists(path):
        return f"Error: file not found: {path}"

    _close_previous()

    # `--skip-config` because a personal wezterm.lua can carry startup hooks and
    # default startup arguments, which would run here too and open stray tabs in
    # what should be a window showing one image.
    #
    # stdio goes to DEVNULL: the window outlives this call, and an inherited pipe
    # would both keep the caller's output open and let the child write into an
    # MCP server's stdio channel.
    global _proc
    try:
        _proc = subprocess.Popen(
            [
                WEZTERM,
                "--skip-config",
                "--config", "hide_tab_bar_if_only_one_tab=true",
                *(["--config", f"initial_cols={int(cols)}"] if cols else []),
                *(["--config", f"initial_rows={int(rows)}"] if rows else []),
                "start", "--always-new-process",
                "--class", WINDOW_CLASS,
                "--", "sh", "-c", VIEWER, "sh", path,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # survives this server's own process group
        )
    except OSError as exc:
        return f"Error: could not start a wezterm window: {exc}"

    return f"Showing {os.path.basename(path)} in its own wezterm window"


if __name__ == "__main__":
    mcp.run(transport="stdio")
