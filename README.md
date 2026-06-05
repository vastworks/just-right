# Just Right

[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/vastworks)

A Sizer-style window resizer for **KDE Plasma on Wayland**. (Project folder is
`window-sizer/`; the user-facing name is "Just Right".) Resize the active window to exact
dimensions from a system-tray menu or a keyboard shortcut.

On Wayland, ordinary apps can't move or resize other apps' windows — only the
compositor can. So the actual resizing is done by a tiny **KWin script**, and a
**PyQt6 tray app** drives it. The two talk over DBus.

## What it does

- **Tray menu of preset sizes.** Click a preset → the currently active window
  snaps to that size. Each preset can optionally re-center the window on its
  current monitor.
- **Keyboard shortcuts (optional).** Every preset is also a KDE global action.
  Open *System Settings → Shortcuts*, search **"Window Sizer"**, and bind keys.
- **Editable presets.** Add / edit / delete sizes in a small GUI.

## Install

```bash
cd window-sizer
bash install.sh
```

The installer:
- installs PyQt6 for the current user if it isn't already available,
- writes default presets and loads the KWin script,
- adds an autostart entry (tray starts at login) and a menu launcher for the editor.

Start the tray immediately, without logging out:

```bash
setsid python3 sizer_tray.py >/dev/null 2>&1 &
```

## Files

| File | Purpose |
|------|---------|
| `sizer_engine.py` | Shared logic: presets file, generates the KWin script, loads it, triggers presets over DBus |
| `sizer_tray.py` | System-tray app — the menu of presets |
| `sizer_editor.py` | PyQt6 dialog to add/edit/delete presets (also runs standalone) |
| `install.sh` | One-shot setup: deps, autostart, launcher |

## Config

- Presets: `~/.config/window-sizer/presets.json`
- Generated KWin script: `~/.config/window-sizer/window-sizer.js`

Each preset is `{ "name", "width", "height", "position", "identifier" }`, where
`position` is `"keep"` or `"center"`. The `identifier` is stable across renames
so any keyboard shortcut you assign stays bound.

## How it works

1. `sizer_engine.generate_script()` bakes the preset list into a KWin JavaScript
   file. For each preset it calls `registerShortcut()`, creating a named action
   that sets the active window's `frameGeometry`.
2. `reload_kwin_script()` loads that file into KWin via
   `org.kde.KWin /Scripting loadScript`.
3. The tray triggers a preset by calling
   `org.kde.kglobalaccel … invokeShortcut <action>`. The same action is what a
   keyboard shortcut would fire.

Sizes apply to the **window frame** (title bar + borders included), matching the
original Windows Sizer. Centering uses the available area of the window's current
monitor, so it works correctly across multiple displays.

## Notes / limits

- KWin/Wayland only. The X11 tools `wmctrl`/`xdotool` can't see native Wayland
  windows, which is why this exists.
- A window that declares itself non-resizable is left alone.
- If you change presets, the tray reloads the script automatically. If you edit
  `presets.json` by hand, pick **Reload KWin script** from the tray menu.
