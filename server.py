# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp"]
# ///
"""wezterm-image-mcp — show an image from an MCP client.

A repainting TUI can't keep an inline image alive: it redraws its own region and
WezTerm stores images in the cell grid, so anything drawn inline gets shredded.
So instead of fighting it, this opens the image in its own WezTerm window.

`start --always-new-process` rather than `cli spawn --new-window`: the latter puts
the window inside the running multiplexer, where it shares the fate of every other
window attached to it. A standalone process can be closed on its own.

One image window at a time — opening a new one closes the previous. Each carries
`--class wezterm-image`, for window-manager rules.
"""

import os
import shlex
import shutil
import subprocess

from fastmcp import FastMCP

mcp = FastMCP("term-image")

WEZTERM = shutil.which("wezterm")
WINDOW_CLASS = "wezterm-image"

# ⚠️ No size is set unless asked for. A tiling compositor overrides `initial_cols` /
# `initial_rows` the moment the window maps, and WezTerm then logs a "cannot resize ...
# because window_state is MAXIMIZED" warning on every image. There, size the window with
# a rule on WINDOW_CLASS instead. The arguments still work under floating WMs.

_proc: subprocess.Popen | None = None  # the current image window, if still open


def _close_previous() -> None:
    """Close the last image window so they do not accumulate.

    Terminating the process is safe precisely because it IS its own process —
    the whole reason for `--always-new-process`.
    """
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
        cols: Optional window width in columns. Tiling window managers override it —
            size the window with a rule on the `wezterm-image` class instead.
        rows: Optional window height in rows. Same caveat.
    """
    if not WEZTERM:
        return "Error: wezterm not found on PATH"
    path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.exists(path):
        return f"Error: file not found: {path}"

    _close_previous()

    # imgcat runs inside the new window's own shell, where there is a real TTY to
    # query for size. `exec bash` keeps the window alive afterwards — including
    # when imgcat fails, so the error is visible rather than flashing past.
    inner = f"wezterm imgcat {shlex.quote(path)}; exec bash"
    global _proc
    try:
        _proc = subprocess.Popen(
            [
                WEZTERM,
                *(["--config", f"initial_cols={int(cols)}"] if cols else []),
                *(["--config", f"initial_rows={int(rows)}"] if rows else []),
                "start", "--always-new-process",
                "--class", WINDOW_CLASS,
                "--", "bash", "-lc", inner,
            ],
            start_new_session=True,  # survives this server's own process group
        )
    except OSError as exc:
        return f"Error: could not start a wezterm window: {exc}"

    return f"Showing {os.path.basename(path)} in its own wezterm window"


if __name__ == "__main__":
    mcp.run(transport="stdio")
