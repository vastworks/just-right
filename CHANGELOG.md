# Changelog

All notable changes to Just Right are listed here. Versions follow
[semantic versioning](https://semver.org/): MINOR adds features without breaking
existing behavior, PATCH is fixes only.

## v1.4.0

### What's new

- **The menu stays open after picking a size.** Click size after size to preview
  them on the active window without reopening the menu each time. This applies to
  presets and ratio sizes; other items (Edit presets, Quit, ...) still close as
  before.

### Changed

- **Ratio menu now offers standard resolutions.** Instead of screen-scaled steps
  (which skipped familiar sizes), each ratio lists well-known resolutions that fit
  your display, so 16:9 includes 1920x1080, 1600x900, 1280x720, and so on. A ratio
  with no standard list, or a display too small for any standard size, falls back
  to the previous screen-scaled ladder.

## v1.3.1

### Fixed

- **Alt-to-flip portrait ratios not working.** The ratio menu tried to catch the
  Alt key with key events, but QMenu reserves Alt for mnemonics and never
  delivered them. It now polls the real keyboard state (queryKeyboardModifiers)
  while the menu is open, so holding Alt flips the ratios to portrait reliably.

## v1.3.0

### What's new

- **Aspect-ratio scaler.** A new "Resize to ratio" tray submenu offers, for each
  ratio (16:9, 16:10, 4:3, 21:9), a ladder of sizes scaled to fit the window's
  display. Pick one to resize and center the active window.
- **Portrait ratios for pivoted monitors.** Hold Alt while the ratio menu is open
  to flip every ratio to its inverse (16:9 becomes 9:16, and so on), without a
  separate cluttered submenu.
- **Super + scroll wheel to resize (X11).** Hold Super and scroll the wheel over a
  window to step it through the size ladder for its current aspect ratio: scroll
  up grows it, scroll down shrinks it. It keeps the window's ratio and
  orientation, so a portrait window steps through portrait sizes. The size popup
  shows each step. If Super+wheel is already taken by another app, the feature
  disables itself quietly; change the modifier in `sizer_scroll_x11.py`.

### Notes

- The ratio scaler works on KDE and X11. Super+scroll is X11 only, since the
  KWin/Wayland session cannot grab a modifier plus the wheel globally.
- New files: `sizer_ratios.py` (size-ladder math), `sizer_scroll_x11.py` (the
  scroll grab). KDE's ad-hoc resize uses a one-shot KWin script in
  `sizer_engine.py`.

## v1.2.1

### Fixed

- **X11 drag popup not appearing.** The live size popup filtered by the active
  window, but on Cinnamon grabbing a window's resize border does not make it the
  active window, so the popup never showed. It now keys off the window under the
  mouse pointer, which is the one actually being dragged. This also cleanly
  excludes the overlay itself, tooltips, and panels.

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
