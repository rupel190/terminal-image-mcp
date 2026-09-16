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
import tempfile

from fastmcp import FastMCP

mcp = FastMCP("term-image")

WEZTERM = shutil.which("wezterm")
WINDOW_CLASS = "wezterm-image"

# The window's program. imgcat draws the image at whatever size the terminal is when it
# runs — and a window manager resizes the window *after* it has mapped, so a single draw
# is sized for the pty's 80x24 starting point and then sits in the corner of a much
# larger window. Redrawing is what makes the image track the window it ends up in.
#
# It watches the size rather than trapping SIGWINCH: a signal that arrives while imgcat
# is still drawing the previous frame is not queued, and that lost frame is exactly the
# last one — the window's final size. Comparing `stty size` cannot miss it.
VIEWER = r"""
stty -echo 2>/dev/null   # it is a viewer, not a shell: stray keystrokes shouldn't show
printf '\033[?25l'      # hide the cursor; it blinks in the middle of the picture otherwise
prev=''
shown=''
n=0
while :; do
    cur=$(stty size 2>/dev/null)
    rows=${cur% *}
    cols=${cur#* }
    # ⛔ A DEGENERATE SIZE IS THE REPORTED CRASH. Mid-resize `stty size` can answer `0 0` or
    # nothing at all, and `wezterm imgcat --width 0` fails with
    #   ERROR wezterm > no size information available: no size information available; terminating
    # which kills the draw and leaves the window blank. Wait for a real size instead of
    # substituting a fake 24x80, which drew a tiny image and then had to redraw anyway.
    case "$rows$cols" in ''|*[!0-9]*) sleep 0.2; continue ;; esac
    [ "$rows" -ge 4 ] && [ "$cols" -ge 8 ] || { sleep 0.2; continue; }
    # ⛔⛔ ONE ROW SHORT, ALWAYS. `imgcat` fits the image inside the box it is given, but a box
    # exactly `rows` tall ends on the last line and the terminal SCROLLS — and once it has
    # scrolled, `\033[2J` clears only what is still on screen. Every redraw then leaves its own
    # strip behind in the scrollback, which is the repeated-caption glitch on a tall image: not
    # a tiling artefact, ten honest redraws stacked up.
    h=$((rows - 1))
    # `stty size` is in CELLS, and a window can change PIXEL size without changing its
    # cell count — a frame the size check cannot see, and the one that clips the image.
    # So redraw a few more times after the geometry stops moving.
    # ⛔ The counter RESETS on every change. It used to count from process start, so the ten
    # settling redraws were spent in the first four seconds — and a window manager that resizes
    # later than that got no settling pass at all, leaving the image sized for a window that no
    # longer exists. Counting from the LAST change is what makes it a settling loop rather than a
    # stopwatch. Four is enough once it is anchored to the right moment; ten was compensating for
    # being anchored to the wrong one, at the cost of re-decoding a multi-megabyte PNG nine times.
    # ⭐⭐ The image to show is READ EACH TICK from a state file, not baked in as "$1". Showing a
    # second image used to close the window and open a new one, which makes a tiling window
    # manager re-lay the whole workspace — *"reuse the MCP window when it's already there, so I
    # can keep working in the 50:50 terminal split"*. A window that never closes cannot disturb a
    # layout, so a new image is a redraw rather than a new window.
    img=$(cat "$IMG_STATE" 2>/dev/null)
    [ -n "$img" ] && [ -f "$img" ] || { sleep 0.2; continue; }
    if [ "$img" != "$shown" ]; then shown=$img; n=0; fi
    if [ "$cur" != "$prev" ]; then prev=$cur; n=0; fi
    if [ "$n" -lt 4 ]; then
        n=$((n + 1))
        # \033[3J clears the SCROLLBACK as well. Without it a strip that scrolled off before
        # the fix above landed is still sitting above the viewport, one scroll-wheel away.
        printf '\033[H\033[2J\033[3J'
        # Size in cells, not `--width 100%`: a percentage is resolved against pixels, and
        # on a fractionally scaled display that overshoots the window and clips the image.
        # stderr is dropped: imgcat's own diagnostics would be drawn INTO the picture.
        wezterm imgcat --width "$cols" --height "$h" "$img" 2>/dev/null
    fi
    sleep 0.4
done
"""

_proc: subprocess.Popen | None = None  # the current image window, if still open

#: Which image the open window should be showing. ⭐ The window watches this file, so a second
#: `show_image` is a REDRAW in the window that is already there rather than a new window — which
#: is what keeps a tiling layout intact. One path, overwritten; nothing accumulates.
IMG_STATE = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir(), "wezterm-image-mcp.current"
)


def _window_is_open() -> bool:
    """True when a viewer we started is still running.

    ⚠️ Asks the PROCESS, not a remembered flag. The user closes this window by hand — that is the
    normal way it ends — so a cached "it is open" would leave every later image written to a state
    file nobody reads, and the tool would report success while showing nothing.
    """
    return _proc is not None and _proc.poll() is None


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

    # ⭐⭐ POINT THE EXISTING WINDOW AT THE NEW IMAGE. Writing the path is the whole handoff: the
    # viewer re-reads this file every tick and redraws when it changes. Closing and reopening
    # instead makes a tiling window manager re-lay the entire workspace, which is disruptive
    # precisely when the window is most useful — beside the work, in a split.
    # ⚠️ Written atomically. A reader that catches a half-written path would fail its `-f` test
    # and, worse, could stick on the old image with no sign anything went wrong.
    os.makedirs(os.path.dirname(IMG_STATE), exist_ok=True)
    tmp = f"{IMG_STATE}.{os.getpid()}"
    with open(tmp, "w") as fh:
        fh.write(path)
    os.replace(tmp, IMG_STATE)

    if _window_is_open():
        return f"Showing {os.path.basename(path)} in the existing wezterm window"

    # The window runs the user's own wezterm.lua, so it looks like their terminal. It
    # carries WEZTERM_IMAGE_MCP=1 in its environment, which a config can test to skip
    # anything that shouldn't happen in a throwaway viewer — a `mux-startup` handler
    # that spawns a workspace layout will otherwise open a stray shell tab beside the
    # image, since this window has a mux of its own.
    #
    # stdio goes to DEVNULL: the window outlives this call, and an inherited pipe
    # would both keep the caller's output open and let the child write into an
    # MCP server's stdio channel.
    global _proc
    try:
        _proc = subprocess.Popen(
            [
                WEZTERM,
                "--config", "hide_tab_bar_if_only_one_tab=true",
                *(["--config", f"initial_cols={int(cols)}"] if cols else []),
                *(["--config", f"initial_rows={int(rows)}"] if rows else []),
                "start", "--always-new-process",
                "--class", WINDOW_CLASS,
                "--", "sh", "-c", VIEWER, "sh",
            ],
            env={**os.environ, "WEZTERM_IMAGE_MCP": "1", "IMG_STATE": IMG_STATE},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # survives this server's own process group
        )
    except OSError as exc:
        return f"Error: could not start a wezterm window: {exc}"

    return f"Showing {os.path.basename(path)} in a new wezterm window"


if __name__ == "__main__":
    mcp.run(transport="stdio")
