# Changelog

All notable changes to Just Right are listed here. Versions follow
[semantic versioning](https://semver.org/): MINOR adds features without breaking
existing behavior, PATCH is fixes only.

## v1.2.0

### What's new

- **Beta support for X11 desktops (Linux Mint / Cinnamon).** The tray now runs
  outside KDE. It auto-detects your desktop at launch and uses the KWin backend
  on Plasma or a new `wmctrl`-based backend on X11. No change for existing KDE
  users; the KWin path is untouched.
- **Live drag-dimensions popup on X11.** A floating, outlined size readout
  follows the cursor while you resize any window. It is event-driven (python-xlib
  watching window geometry), not polled, and keys off the active window so it
  stays quiet for menus, tooltips, and the overlay itself.
- **Outlined popup text.** The size numbers are drawn with a black stroke over a
  white fill so they stay legible over any window or wallpaper.

### Details

- New `sizer_backend.py` selects the backend behind one interface, so the tray,
  editor, and presets file are shared across both desktops.
- New `sizer_overlay_x11.py` renders the X11 size popup.
- Presets, centering, and "Add current window size" all work on X11.

### Known limits on X11 (beta)

- No built-in global keyboard shortcuts yet; bind a `wmctrl` command in Cinnamon
  keyboard settings if you want hotkeys.
- The live popup assumes client-side decorations (true on Cinnamon); on window
  managers with server-side frames it may not appear. Presets still work.

## v1.1.1

- Notify when an app refuses a target size; track size per window.

## v1.1.0

- Geometry OSD and "Add current window size" preset capture.

## v1.0.0

- Initial release: KDE Plasma (Wayland) window resizer with tray presets,
  editable sizes, and optional global shortcuts.
