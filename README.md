# wezterm-image-mcp

**Show an image from an MCP client** — in a WezTerm window of its own.

Terminal-based clients repaint their own region continuously, and WezTerm keeps images
in the cell grid, so anything drawn inline gets shredded within a second. This MCP
server sidesteps that: the image opens in its own WezTerm window, where it renders
cleanly and stays put. Opening a new image closes the previous one, so they don't
pile up.

```
you:   show me ~/pictures/catpp_mushhill.jpg
agent: → a terminal window opens with the picture
```

## Requirements

- [WezTerm](https://wezterm.org), with `wezterm` on `PATH`
- [`uv`](https://docs.astral.sh/uv/) and Python 3.10+

That's all. `server.py` is a self-contained [PEP 723](https://peps.python.org/pep-0723/)
script — `uv` reads its inline dependency (`fastmcp`) and runs it; nothing to install
by hand. The server does not need to run inside a WezTerm pane.

## Install

```bash
git clone https://github.com/rupel190/wezterm-image-mcp ~/projects/wezterm-image-mcp
```

Register it with your MCP client as a `stdio` server:

```json
{
  "mcpServers": {
    "term-image": {
      "command": "uv",
      "args": ["run", "--python", "python3", "~/projects/wezterm-image-mcp/server.py"]
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

**Tool:** `show_image(file_path, cols=None, rows=None)`. Formats: whatever
`wezterm imgcat` supports (PNG, JPEG, GIF, WebP, BMP, …).

`cols`/`rows` set the window size where the window manager allows it. Tiling
compositors override them, so there size and placement are a WM concern — the window
carries the class `wezterm-image` if you want to target it with a rule.

## How it works

1. Closes the previous image window, if one is still open.
2. Starts a WezTerm process — `wezterm start --always-new-process --class wezterm-image`
   — running `wezterm imgcat <path>; exec bash`.
3. `imgcat` runs inside that window's own shell, where there is a real TTY to query for
   size. `exec bash` keeps the window alive afterwards, so a failure stays readable
   instead of flashing past.

Nothing repaints that window, so the image stays clean and permanent — unlike drawing
into the conversation itself.

## Credits

Inspired by [jrmeyer/ghostty-image-mcp](https://github.com/jrmeyer/ghostty-image-mcp),
which renders inline [Kitty graphics](https://sw.kovidgoyal.net/kitty/graphics-protocol/)
in Ghostty. This project takes a different tack — a separate window — because WezTerm's
cell-grid image storage can't keep an inline image alive under a repainting TUI.

## License

[MIT](LICENSE)
