# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp"]
# ///
"""wezterm-image-mcp — let Claude Code show you an image.

Claude can't paint pixels into its own TUI pane (it redraws that region and
WezTerm stores images in the cell grid, so anything drawn inline gets shredded).
So instead of fighting it, this opens the image in a *separate* WezTerm pane via
`wezterm cli`, where it renders cleanly and stays put. One pane is reused across
calls so images don't pile up into new panes.
"""

import json
import os
import shlex
import shutil
import subprocess

from fastmcp import FastMCP

mcp = FastMCP("term-image")

WEZTERM = shutil.which("wezterm")
_pane_id = None  # the reused image pane, remembered across calls


def _cli(args, **kw):
    return subprocess.run([WEZTERM, "cli", *args], capture_output=True, text=True, **kw)


def _pane_alive(pane_id):
    r = _cli(["list", "--format", "json"])
    if r.returncode != 0:
        return False
    try:
        return any(str(p.get("pane_id")) == str(pane_id) for p in json.loads(r.stdout))
    except (ValueError, TypeError):
        return False


def _open_pane(width):
    """Split a pane to the right running a shell; return its id, or None."""
    r = _cli(["split-pane", "--right", "--percent", str(width), "--", "bash"])
    return r.stdout.strip() or None if r.returncode == 0 else None


@mcp.tool()
async def show_image(file_path: str, width: int = 40) -> str:
    """Show an image to the user in a side WezTerm pane (PNG/JPEG/GIF/WebP/...).

    Use whenever the user asks to see an image, or to show them a file you're
    working with. The image opens beside the chat and persists.

    Args:
        file_path: Path to the image file.
        width: Pane width as a percent of the window (10-80). Default 40.
    """
    if not WEZTERM:
        return "Error: wezterm not found on PATH"
    path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.exists(path):
        return f"Error: file not found: {path}"
    width = max(10, min(80, width))

    global _pane_id
    if _pane_id is None or not _pane_alive(_pane_id):
        _pane_id = _open_pane(width)
        if _pane_id is None:
            return "Error: could not open a wezterm pane (is this running inside WezTerm?)"

    # Type the imgcat command into the reused pane's shell.
    cmd = f"wezterm imgcat {shlex.quote(path)}\n"
    _cli(["send-text", "--no-paste", "--pane-id", str(_pane_id)], input=cmd)
    return f"Showing {os.path.basename(path)} in wezterm pane {_pane_id}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
