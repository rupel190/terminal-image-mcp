# wezterm-image-mcp

Let Claude Code (or any MCP client) **show you an image** — in a WezTerm window of its own.

Claude Code can't render images inline in its terminal UI: it constantly repaints
its own region, and WezTerm keeps images in the cell grid, so anything drawn into
the conversation gets shredded within a second. This MCP server sidesteps that
entirely — it opens the image in a WezTerm window of its own, where it renders cleanly
and stays put.

⛔ **It is a separate PROCESS, not just a separate window.** `wezterm cli spawn
--new-window` puts the window inside the *running multiplexer*, so a "close" binding
aimed at the mux takes every other WezTerm down with it. `wezterm start
--always-new-process` gets its own GUI and its own mux, so you can close the image
window on its own. Opening a new image closes the previous one, so they don't pile up.

```
you:    show me ~/pictures/wallpaper/catpp_mushhill.jpg
claude: → a new terminal window opens with the picture
```

## Requirements

- [WezTerm](https://wezterm.org) with `wezterm cli` reachable (the default when running inside WezTerm)
- [`uv`](https://docs.astral.sh/uv/) and Python 3.10+
- `wezterm` on `PATH` (the server does not need to run inside a WezTerm pane)

## Install

```bash
git clone https://github.com/rupel190/wezterm-image-mcp ~/projects/wezterm-image-mcp
claude mcp add term-image -s user -- \
  uv run --python "$(command -v python3)" ~/projects/wezterm-image-mcp/server.py
```

Then restart Claude Code (MCP tools load at startup).

`server.py` is a self-contained [PEP 723](https://peps.python.org/pep-0723/) script —
`uv` reads its inline dependency (`fastmcp`) and runs it; nothing to install by hand.

> **NixOS:** keep the `--python "$(command -v python3)"`. It makes `uv` use the
> Nix-provided interpreter instead of downloading a generic manylinux CPython,
> which can't run on NixOS (no `/lib64/ld-linux-*`).

## Usage

Just ask Claude:

```
show me ~/pics/cat.png
```

Claude calls the `show_image` tool and the picture opens in its own window.

**Tool:** `show_image(file_path)`. Formats: whatever `wezterm imgcat` supports
(PNG, JPEG, GIF, WebP, BMP, …). Size and placement belong to your window manager, and
under a tiling compositor they are the *only* thing that works — WezTerm's own
`initial_cols`/`initial_rows` are overridden the moment the window maps. Target the
window class:

```
# Hyprland
windowrulev2 = float,          class:^(wezterm-image)$
windowrulev2 = size 1600 900,  class:^(wezterm-image)$
```

The `cols`/`rows` arguments remain for floating window managers, where they do apply.

Remove it with: `claude mcp remove term-image -s user`.

## How it works

1. It closes the previous image window, if one is still open.
2. It starts an independent WezTerm process — `wezterm start --always-new-process
   --class wezterm-image` — running `wezterm imgcat <path>; exec bash`.
3. `imgcat` runs inside that window's own shell, where there is a real TTY to query for
   size; `exec bash` keeps the window alive afterwards, so a failure stays readable
   instead of flashing past.

Claude never repaints that window, so the image stays clean and permanent — unlike
drawing into the conversation itself.

### The workspace gotcha

`spawn --new-window` puts the new window in the workspace named `default`, *not*
the one you are in — and a WezTerm GUI only shows windows belonging to the
workspace it is currently displaying. If you use named workspaces, a naive spawn
creates a window that exists in the mux and never appears on screen (it shows up
in `wezterm cli list` with `dpi: 0`). So the server reads the workspace of its own
`WEZTERM_PANE` and passes it through as `--workspace`.

### Focus

Spawning the window takes focus once, when it is first created; later images are
sent into the existing window and don't move focus. `wezterm cli activate-pane`
cannot hand focus back — under a Wayland compositor the compositor owns focus, so
if the initial jump bothers you, that is a window-manager rule to write (e.g.
Hyprland's `noinitialfocus`), not something this server can do.

## Credits

Inspired by [jrmeyer/ghostty-image-mcp](https://github.com/jrmeyer/ghostty-image-mcp),
which renders inline [Kitty graphics](https://sw.kovidgoyal.net/kitty/graphics-protocol/)
in Ghostty. This project takes a different tack — a separate window driven by `wezterm cli` —
because WezTerm's cell-grid image storage can't keep an inline image alive under
Claude Code's ~1 Hz repaint.

## License

[MIT](LICENSE)
