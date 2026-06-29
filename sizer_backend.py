"""Backend selection for Window Sizer.

The tray performs three window actions: set up on startup, resize the active
window to a preset, and read the active window's size to save it. How those
happen depends on the desktop:

  - KWinBackend  → KDE Plasma (Wayland or X11). Drives the generated KWin
                   script over DBus. This is the original Bazzite path.
  - X11Backend   → Cinnamon / Mint / any plain X11 desktop. Resizes windows
                   directly with `wmctrl`; no script injection needed.

Both expose the same three methods so the tray never has to branch:

    backend = select_backend()
    presets = backend.activate()
    backend.trigger_preset(preset)
    backend.add_current_size(tray)

Preset storage stays in sizer_engine for both backends — a single source of
truth for presets.json.
"""

import os
import re
import shutil
import subprocess

import sizer_engine


# ---------------------------------------------------------------------------
# KWin backend (KDE Plasma) — thin wrapper over the existing engine.
# ---------------------------------------------------------------------------

class KWinBackend:
    name = "kwin"

    def activate(self):
        """Generate + load the KWin script and return the current presets."""
        return sizer_engine.reload_kwin_script()

    def trigger_preset(self, preset):
        """Resize the active window by firing the preset's kglobalaccel action."""
        return sizer_engine.trigger_preset(preset)

    def add_current_size(self, tray):
        """Ask the KWin script for the active window's size.

        The script reads workspace.activeWindow and calls back into the tray's
        DBus service (addCurrentSize), which opens the save-preset dialog — so
        nothing to return here.
        """
        sizer_engine.run_qdbus(
            "/component/" + sizer_engine.KGLOBALACCEL_COMPONENT,
            "org.kde.kglobalaccel.Component.invokeShortcut",
            "WindowSizer_AddCurrentSize",
        )


# ---------------------------------------------------------------------------
# X11 backend (Cinnamon / Mint) — direct window manipulation via wmctrl.
# ---------------------------------------------------------------------------

class X11Backend:
    name = "x11"

    def activate(self):
        """No script to load on X11; just hand back the saved presets."""
        return sizer_engine.load_presets()

    def trigger_preset(self, preset):
        """Resize the active window to the preset, honoring its position mode."""
        width = int(preset["width"])
        height = int(preset["height"])
        position = preset.get("position", "keep")

        left, top = None, None
        if position == "center":
            left, top = self._centered_position(width, height)

        self._apply_size(width, height, left, top)

    def add_current_size(self, tray):
        """Read the active window's size and open the tray's save dialog."""
        geometry = self._active_window_geometry()
        if geometry is not None:
            tray.prompt_add_preset(geometry["width"], geometry["height"])

    # -- internals --

    def _apply_size(self, width, height, left=None, top=None):
        """Resize (and optionally move) the active window via wmctrl.

        wmctrl's -e argument is gravity,left,top,width,height. Passing -1 for
        left or top leaves that coordinate untouched ("keep" position). A window
        manager refuses to resize a maximized window, so clear that state first.
        """
        move_left = left if left is not None else -1
        move_top = top if top is not None else -1
        geometry = f"0,{move_left},{move_top},{width},{height}"

        _run(["wmctrl", "-r", ":ACTIVE:", "-b",
              "remove,maximized_vert,maximized_horz"])
        _run(["wmctrl", "-r", ":ACTIVE:", "-e", geometry])

    def _centered_position(self, width, height):
        """Top-left coords that center a width x height window on the monitor
        the active window currently sits on. Falls back to (None, None) — i.e.
        keep position — if we can't work out the monitor layout."""
        window = self._active_window_geometry()
        if window is None:
            return None, None

        window_center_x = window["left"] + window["width"] // 2
        window_center_y = window["top"] + window["height"] // 2

        monitor = self._monitor_containing(window_center_x, window_center_y)
        if monitor is None:
            return None, None

        left = monitor["x"] + (monitor["width"] - width) // 2
        top = monitor["y"] + (monitor["height"] - height) // 2
        return left, top

    def _monitor_containing(self, point_x, point_y):
        """Return the monitor rectangle containing the given point, or the
        first monitor as a fallback. Parsed from `xrandr --listmonitors`."""
        monitors = self._list_monitors()
        if not monitors:
            return None
        for monitor in monitors:
            within_x = monitor["x"] <= point_x < monitor["x"] + monitor["width"]
            within_y = monitor["y"] <= point_y < monitor["y"] + monitor["height"]
            if within_x and within_y:
                return monitor
        return monitors[0]

    def _list_monitors(self):
        """Parse monitor rectangles from xrandr. Each --listmonitors line looks
        like:  ' 0: +*HDMI-0 2560/598x1440/336+0+0  HDMI-0' — the token we want
        is the WIDTH/mmx HEIGHT/mm+X+Y geometry."""
        if shutil.which("xrandr") is None:
            return []
        raw = _run(["xrandr", "--listmonitors"])
        geometry_pattern = re.compile(r"(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)")
        monitors = []
        for line in raw.splitlines():
            match = geometry_pattern.search(line)
            if match:
                width, height, x, y = (int(value) for value in match.groups())
                monitors.append({"x": x, "y": y, "width": width, "height": height})
        return monitors

    def _active_window_geometry(self):
        """Active window geometry via xdotool, or None if unavailable."""
        if shutil.which("xdotool") is None:
            return None
        window_id = _run(["xdotool", "getactivewindow"]).strip()
        if not window_id:
            return None
        raw = _run(["xdotool", "getwindowgeometry", "--shell", window_id])
        values = {}
        for line in raw.splitlines():
            key, _, value = line.partition("=")
            if value.strip().lstrip("-").isdigit():
                values[key.strip().lower()] = int(value)
        if "width" in values and "height" in values:
            return {
                "left": values.get("x", 0),
                "top": values.get("y", 0),
                "width": values["width"],
                "height": values["height"],
            }
        return None


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def select_backend():
    """Pick the right backend for this desktop.

    KDE Plasma → KWin (keeps the rich live-overlay features). Anything else
    with wmctrl available → X11. Errors only if neither path is usable.
    """
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()

    if "KDE" in desktop and _qdbus_available():
        return KWinBackend()
    if shutil.which("wmctrl") is not None:
        return X11Backend()
    if _qdbus_available():
        return KWinBackend()

    raise RuntimeError(
        "No supported window backend found. Install wmctrl (X11 desktops): "
        "sudo apt install wmctrl xdotool"
    )


def _qdbus_available():
    return any(shutil.which(cmd) for cmd in ("qdbus6", "qdbus-qt6", "qdbus"))


def _run(command):
    """Run a command and return stdout. Raises on a non-zero exit."""
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout


if __name__ == "__main__":
    backend = select_backend()
    print(f"Selected backend: {backend.name}")
    if backend.name == "x11":
        x11 = backend
        print("Monitors:", x11._list_monitors())
        print("Active window:", x11._active_window_geometry())
