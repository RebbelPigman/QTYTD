# QTYTD

Simple Qt YouTube downloader. UI is PyQt5. Downloads go through yt-dlp.

## Requirements

- **Nix** with `nix-shell` (uses `shell.nix` in this folder).
- **nixpkgs** on `NIX_PATH` (`<nixpkgs>`), so the shell can pull:
  - Python 3
  - PyQt5
  - yt-dlp
  - ffmpeg
  - Qt 5 base + Wayland plugins
- A working **display** (X11 or Wayland). The app does not set a Qt style; it uses the **system / desktop Qt theme**.
- Network access for video info, thumbnails, and downloads.
- Write access to the output folder (default: `~/Downloads`).

You do not need a system Python, pip, or a system PyQt install. Those come from the Nix shell.

A system Qt theme stack (KDE, GNOME + qt5ct, etc.) is optional but is what the window will follow.

## Run

From this directory:

```bash
nix-shell --run "python3 qtytd.py"
```
