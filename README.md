# term-image

**Show an image from an MCP client in WezTerm** — in a viewer split beside it.

Terminal-based clients repaint their own region continuously, and WezTerm keeps images in
the cell grid, so anything drawn inline gets shredded within a second. This MCP server
sidesteps that: images go to a viewer of their own, where nothing repaints them. The viewer
is a chronicle — every image is appended below the last with its caption and path, and
scrolling up shows everything from earlier in the session.

```
you:   show me ~/pictures/catpp_mushhill.jpg
agent: → a split opens beside the session with the picture
```

Inside kitty (`KITTY_WINDOW_ID` set) the server registers no tool, since kitty can draw
images inline itself.

## Where the viewer opens

| Client runs in | Viewer | How |
|---|---|---|
| WezTerm | a split beside the client's pane | `wezterm cli split-pane`, then `wezterm imgcat` |
| anything else | a WezTerm window of its own | `wezterm start --always-new-process` |

Each split keeps its own chronicle, so two sessions never replay each other's images. The
split is opened once and reused; close it like any other pane and the next image opens a new
one. Focus stays on the client.

## Requirements

- [WezTerm](https://wezterm.org), with `wezterm` on `PATH`
- [`uv`](https://docs.astral.sh/uv/) and Python 3.10+

`server.py` is a self-contained [PEP 723](https://peps.python.org/pep-0723/) script — `uv`
reads its inline dependency (`fastmcp`) and runs it; nothing to install by hand. It invokes
WezTerm and a POSIX `sh` for the viewer loop, and does not need to run inside a terminal
itself.

## Install

```bash
git clone https://github.com/rupel190/terminal-image-mcp ~/projects/terminal-image-mcp
```

Register it with your MCP client as a `stdio` server:

```json
{
  "mcpServers": {
    "term-image": {
      "command": "uv",
      "args": ["run", "--python", "python3", "~/projects/terminal-image-mcp/server.py"]
    }
  }
}
```

Most clients load MCP servers at startup, so restart yours afterwards.

> **NixOS:** pass a concrete interpreter — `--python "$(command -v python3)"`. It makes
> `uv` use the Nix-provided CPython instead of downloading a generic manylinux build,
> which can't run on NixOS (no `/lib64/ld-linux-*`).

## Usage

Ask for an image:

```
show me ~/pics/cat.png
```

**Tool:** `show_image(file_path, title=None, cols=None, rows=None, clear=False)`.

- `title` is printed above the image as selectable text. Always worth passing.
- `clear` wipes the viewer's history before appending; use it between unrelated batches.
- `cols`/`rows` size the separate window only, where the window manager allows it.

Formats: whatever `wezterm imgcat` supports (PNG, JPEG, GIF, WebP, BMP, …).

## How it works

1. The server appends `<path>\t<caption>` to a per-viewer log in `$XDG_RUNTIME_DIR`. Line 1
   is an epoch; a new epoch (from `clear`) is the only thing that wipes the viewer.
2. If the viewer is not open, it opens one. The split titles itself `term-image`, which is
   how later calls find it in the client's tab; the separate window is tracked by its process.
3. The viewer is a small `sh` loop that draws every log line it has not drawn yet. It waits
   for the terminal size to settle before drawing — a window manager resizes a new window
   *after* it maps — and sizes each image in cells, leaving six rows so the next caption
   stays on screen. An image is drawn once, at the size the viewer had when it arrived;
   resizing later leaves earlier pictures as they were.

The separate window uses your own `wezterm.lua` and sets `WEZTERM_IMAGE_MCP=1`. Test that
variable to skip anything that shouldn't run in a throwaway viewer — a `mux-startup` handler
that spawns a workspace layout, for instance, would otherwise open a stray shell tab beside
the image:

```lua
wezterm.on('mux-startup', function()
  if os.getenv('WEZTERM_IMAGE_MCP') then return end
  -- your layout
end)
```

## Credits

Inspired by [jrmeyer/ghostty-image-mcp](https://github.com/jrmeyer/ghostty-image-mcp),
which renders inline [Kitty graphics](https://sw.kovidgoyal.net/kitty/graphics-protocol/)
in Ghostty. This project takes a different tack — a viewer of its own — because WezTerm's
cell-grid image storage can't keep an inline image alive under a repainting TUI.

## License

[MIT](LICENSE)
