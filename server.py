# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp"]
# ///
"""term-image — show images from an MCP client, as a scrollable chronicle.

A repainting TUI can't keep an inline image alive: it redraws its own region and
WezTerm stores images in the cell grid, so anything drawn inline gets shredded.
So instead of fighting it, this opens a viewer of its own and appends to it: a split
beside the client's WezTerm pane, or a WezTerm window of its own outside WezTerm.

Inside kitty it registers no tool at all: kitty draws images inline natively, so the
client there gets its pictures another way.

⭐⭐ The viewer is a CHRONICLE, not a slot. Every image is appended below the last with
its own caption and path, and the terminal's scrollback IS the history — scroll up to
find anything shown earlier in the session. It used to show one image at a time and
close the previous one, which made a series unreadable: *"it's just some image I can't
really tell what's it for, where it's from. And it overrides the previous pictures too."*
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time

from fastmcp import FastMCP

mcp = FastMCP("term-image")

WEZTERM = shutil.which("wezterm")
WINDOW_CLASS = "wezterm-image"
# The viewer's title, and how a split mode finds its viewer again
VIEWER_TITLE = "term-image"
# Share of the client's pane the split takes, in percent
SPLIT_PERCENT = 40

# The viewer's program. imgcat draws the image at whatever size the terminal is when it
# runs — and a window manager resizes the window *after* it has mapped, so a draw
# issued immediately is sized for the pty's 80x24 starting point and then sits in the corner
# of a much larger window. Waiting for the size to SETTLE is what makes the image fit the
# viewer it ends up in.
#
# ⛔⛔ AN APPENDED IMAGE CANNOT BE RESIZED AFTERWARDS, and that is the deliberate trade.
# The old viewer re-drew on every resize, which is why it had to clear the screen — and
# clearing is exactly what destroys a history. Each image is now committed to the scrollback
# at the size the viewer had when it arrived. Resizing later re-flows the text but leaves
# earlier pictures as they were; that is the cost of being able to scroll back at all.
VIEWER = r"""
stty -echo 2>/dev/null   # it is a viewer, not a shell: stray keystrokes shouldn't show
printf '\033[?25l'      # hide the cursor; it blinks in the middle of the picture otherwise
printf '\033]2;%s\007' "$IMG_TITLE"   # how a split mode finds this viewer again
drawn=0
epoch=''
prev=''
settle=0
while :; do
    cur=$(stty size 2>/dev/null)
    rows=${cur% *}
    cols=${cur#* }
    # ⛔ A DEGENERATE SIZE IS A REPORTED CRASH. Mid-resize `stty size` can answer `0 0` or
    # nothing at all, and `wezterm imgcat --width 0` fails with
    #   ERROR wezterm > no size information available; terminating
    # which kills the draw and leaves the window blank. Wait for a real size instead of
    # substituting a fake 24x80, which drew a tiny image and then had to redraw anyway.
    case "$rows$cols" in ''|*[!0-9]*) sleep 0.2; continue ;; esac
    [ "$rows" -ge 4 ] && [ "$cols" -ge 8 ] || { sleep 0.2; continue; }

    # ⛔ Draw only once the geometry has stopped moving. `stty size` is in CELLS and a window
    # can change PIXEL size without changing its cell count, so the counter is a settling
    # loop anchored to the LAST change, never a stopwatch from process start — a window
    # manager that resizes late used to get no settling pass at all.
    if [ "$cur" != "$prev" ]; then prev=$cur; settle=0; else settle=$((settle + 1)); fi
    [ "$settle" -ge 3 ] || { sleep 0.2; continue; }

    [ -f "$IMG_STATE" ] || { sleep 0.3; continue; }

    # Line 1 is the epoch. A new epoch means the caller cleared the history, which is the
    # ONLY thing that may wipe the scrollback — every other path only ever appends.
    e=$(head -n 1 "$IMG_STATE" 2>/dev/null)
    if [ "$e" != "$epoch" ]; then
        epoch=$e
        drawn=0
        printf '\033[H\033[2J\033[3J'
    fi

    total=$(wc -l < "$IMG_STATE" 2>/dev/null)
    case "$total" in ''|*[!0-9]*) sleep 0.3; continue ;; esac
    total=$((total - 1))

    while [ "$drawn" -lt "$total" ]; do
        drawn=$((drawn + 1))
        line=$(sed -n "$((drawn + 1))p" "$IMG_STATE" 2>/dev/null)
        [ -n "$line" ] || continue
        img=${line%%	*}
        title=${line#*	}
        [ -f "$img" ] || continue
        # ⭐⭐ The caption and the path are printed as TEXT, not burned into the picture, so
        # they can be SELECTED AND COPIED out of the terminal — *"can you just write it so
        # it's copy-pastable"*. They also survive scrolling, which a title inside the image
        # only does at the size it was drawn.
        printf '\n\033[38;5;240m%s\033[0m\n' "----------------------------------------------------------------"
        printf '\033[1;38;5;75m%s\033[0m\n' "$title"
        printf '\033[38;5;245m%s\033[0m\n\n' "$img"
        # ⛔⛔ ONE ROW SHORT IS NOT ENOUGH HERE. `imgcat` fits the image inside the box it
        # is given; a box the full height of the viewer leaves no room for the NEXT caption, so
        # a chronicle would show exactly one entry per screen with its header scrolled off. Six
        # rows of headroom keeps a caption and the top of its image together.
        h=$((rows - 6))
        [ "$h" -lt 4 ] && h=4
        # Size in cells, not `--width 100%`: a percentage is resolved against pixels, and on a
        # fractionally scaled display that overshoots the window and clips the image.
        # stderr is dropped: imgcat's own diagnostics would be drawn INTO the picture.
        wezterm imgcat --width "$cols" --height "$h" "$img" 2>/dev/null
        printf '\n'
    done
    sleep 0.3
done
"""

_proc: subprocess.Popen | None = None  # the separate window, if still open


def _log_path() -> str:
    """The chronicle for this client's viewer.

    One per split, so a second session's split does not replay the first one's images.
    Pane ids restart in every WezTerm mux, so the socket's name is part of the key.
    """
    pane = os.environ.get("WEZTERM_PANE")
    if pane:
        key = f"wezterm-{os.path.basename(os.environ.get('WEZTERM_UNIX_SOCKET', ''))}-{pane}"
    else:
        key = "window"
    key = re.sub(r"[^\w.-]", "_", key)
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir(), f"term-image-{key}.log")


def _viewer_env(log: str) -> dict[str, str]:
    return {"IMG_STATE": log, "IMG_TITLE": VIEWER_TITLE}


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    # ⛔ stdin is the MCP channel: a child that inherits it could eat protocol bytes
    return subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)


def _reset_log(log: str) -> None:
    """Start a fresh chronicle. The epoch is what tells the viewer to wipe its scrollback."""
    os.makedirs(os.path.dirname(log), exist_ok=True)
    tmp = f"{log}.{os.getpid()}"
    with open(tmp, "w") as fh:
        fh.write(f"epoch {time.time_ns()}\n")
    os.replace(tmp, log)


def _cli(*args: str) -> list[str]:
    return [WEZTERM, "cli", "--no-auto-start", *args]


def _open_split(log: str) -> str | None:
    """Open the viewer beside the client's WezTerm pane unless it is already there.

    Returns an error message, or None on success.
    """
    pane = int(os.environ["WEZTERM_PANE"])
    listed = _run(_cli("list", "--format", "json"))
    if listed.returncode != 0:
        return f"Error: wezterm cli list failed: {listed.stderr.strip()}"
    panes = json.loads(listed.stdout or "[]")
    tab = next((p["tab_id"] for p in panes if p["pane_id"] == pane), None)
    # ⚠️ Asks WezTerm, not a remembered flag: the user closes the split by hand
    if any(p["tab_id"] == tab and p["title"] == VIEWER_TITLE for p in panes):
        return None

    # Split-pane focuses the new pane; hand focus back only if the user was on the client's pane,
    # since activate-pane also switches to its tab
    clients = _run(_cli("list-clients", "--format", "json"))
    focused = {c.get("focused_pane_id") for c in json.loads(clients.stdout or "[]")} if clients.returncode == 0 else set()

    env = [f"{k}={v}" for k, v in _viewer_env(log).items()]
    made = _run(_cli(
        "split-pane", "--pane-id", str(pane), "--right", "--percent", str(SPLIT_PERCENT),
        "--cwd", os.path.expanduser("~"),
        "--", "env", *env, "sh", "-c", VIEWER, "sh",
    ))
    if made.returncode != 0:
        return f"Error: wezterm could not open the image split: {made.stderr.strip()}"
    if pane in focused:
        _run(_cli("activate-pane", "--pane-id", str(pane)))
    return None


def _window_is_open() -> bool:
    """True when a separate window we started is still running.

    ⚠️ Asks the PROCESS, not a remembered flag. The user closes this window by hand — that is the
    normal way it ends — so a cached "it is open" would leave every later image appended to a log
    nobody reads, and the tool would report success while showing nothing.
    """
    return _proc is not None and _proc.poll() is None


def _open_window(log: str, cols: int | None, rows: int | None) -> str | None:
    """Open the viewer as a WezTerm window of its own. Returns an error message, or None."""
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
                "--config", "scrollback_lines=20000",
                *(["--config", f"initial_cols={int(cols)}"] if cols else []),
                *(["--config", f"initial_rows={int(rows)}"] if rows else []),
                "start", "--always-new-process",
                "--class", WINDOW_CLASS,
                "--", "sh", "-c", VIEWER, "sh",
            ],
            env={**os.environ, "WEZTERM_IMAGE_MCP": "1", **_viewer_env(log)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # survives this server's own process group
        )
    except OSError as exc:
        return f"Error: could not start a wezterm window: {exc}"
    return None


async def show_image(
    file_path: str,
    title: str | None = None,
    cols: int | None = None,
    rows: int | None = None,
    clear: bool = False,
) -> str:
    """Append an image to the user's WezTerm image viewer (PNG/JPEG/GIF/WebP/...).

    Inside WezTerm the viewer is a split beside this session; elsewhere it is a WezTerm window
    of its own. Either way it is a scrollable CHRONICLE: each image is added below the previous
    one with its caption and path above it, and nothing is replaced. Scroll up in the viewer to
    see everything shown earlier. The user can close it on its own.

    ⭐ ALWAYS pass `title` — it is printed above the image as selectable terminal text and is
    the only thing that says what the picture is and where it came from. An untitled image in a
    long chronicle is unidentifiable.

    Args:
        file_path: Path to the image file.
        title: Short caption printed above the image. Say what it shows, not just its filename.
        cols: Optional window width in columns, used only when a separate window is first created.
        rows: Optional window height in rows. Same.
        clear: Start a fresh chronicle, wiping the viewer's scrollback, before appending this
            image. Use when beginning an unrelated batch — not between images of one batch.
    """
    if not WEZTERM:
        return "Error: wezterm not found on PATH"
    path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.exists(path):
        return f"Error: file not found: {path}"

    caption = (title or os.path.basename(path)).replace("\t", " ").replace("\n", " ")
    log = _log_path()

    if clear or not os.path.exists(log):
        _reset_log(log)

    # ⚠️ One `write` of one complete line, opened in append mode. A reader that catches a
    # half-written line would show a broken path — and worse, `wc -l` would already have
    # counted it, so the entry would be skipped and never retried.
    with open(log, "a") as fh:
        fh.write(f"{path}\t{caption}\n")

    name = os.path.basename(path)
    split = bool(os.environ.get("WEZTERM_PANE"))
    try:
        if split:
            err = _open_split(log)
        elif _window_is_open():
            return f"Appended {name} to the image window"
        else:
            err = _open_window(log, cols, rows)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as exc:
        err = f"Error: could not reach wezterm: {exc}"
    if err:
        return err
    return f"Showing {name} in the {'image split beside this session' if split else 'image window'}"


# kitty draws images inline itself, so a kitty session gets no tool from this server
if not os.environ.get("KITTY_WINDOW_ID"):
    mcp.tool()(show_image)


if __name__ == "__main__":
    mcp.run(transport="stdio")
