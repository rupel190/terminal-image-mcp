# wezterm-image-mcp

Let Claude Code (or any MCP client) **show you an image** — in a WezTerm pane beside your chat.

Claude Code can't render images inline in its terminal UI: it constantly repaints
its own region, and WezTerm keeps images in the cell grid, so anything drawn into
the conversation gets shredded within a second. This MCP server sidesteps that
entirely — it opens the image in a **separate WezTerm pane** via `wezterm cli`,
where it renders cleanly and stays put. One pane is reused, so images don't pile up.

```
you:    show me ~/pictures/wallpaper/catpp_mushhill.jpg
claude: → a pane splits off to the right with the picture
```

## Requirements

- [WezTerm](https://wezterm.org) with `wezterm cli` reachable (the default when running inside WezTerm)
- [`uv`](https://docs.astral.sh/uv/) and Python 3.10+
- Must run from inside a WezTerm pane (needs `WEZTERM_PANE`)

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

Claude calls the `show_image` tool and the picture opens in a side pane.

**Tool:** `show_image(file_path, width=40)` — `width` is the pane width as a percent
of the window (10–80). Formats: whatever `wezterm imgcat` supports (PNG, JPEG, GIF,
WebP, BMP, …).

Remove it with: `claude mcp remove term-image -s user`.

## How it works

1. On the first call it splits a pane to the right running a shell (`wezterm cli split-pane`).
2. It types `wezterm imgcat <path>` into that pane (`wezterm cli send-text`).
3. It remembers the pane id and reuses it for later images (splitting a fresh one only if you closed it).

Claude never repaints that pane, so the image stays clean and permanent — unlike
drawing into the conversation itself.

## Credits

Inspired by [jrmeyer/ghostty-image-mcp](https://github.com/jrmeyer/ghostty-image-mcp),
which renders inline [Kitty graphics](https://sw.kovidgoyal.net/kitty/graphics-protocol/)
in Ghostty. This project takes a different tack — a side pane driven by `wezterm cli` —
because WezTerm's cell-grid image storage can't keep an inline image alive under
Claude Code's ~1 Hz repaint.

## License

[MIT](LICENSE)
