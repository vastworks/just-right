#!/usr/bin/env python3
"""Window Sizer tray app.

Picks a window backend for the current desktop (KWin on KDE, wmctrl on X11),
then shows a system-tray menu listing every saved preset. Clicking a preset
resizes the currently active window.

On KDE it also hosts the org.justright.tray DBus service used by the KWin
script to show the size overlay and the add-preset prompt. On X11 those
callbacks are handled directly (no DBus round-trip), so the live drag overlay
is simply absent there.
"""

import sys

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSlot
from PyQt6.QtDBus import QDBusConnection, QDBusMessage
from PyQt6.QtGui import QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
)

import sizer_engine
from sizer_backend import select_backend
from sizer_editor import PresetsEditor
from sizer_ratios import RATIOS, ratio_label, sizes_for_ratio

class StickyMenu(QMenu):
    """A QMenu that stays open when you trigger a size action, so you can apply
    several sizes in a row and compare them without reopening the menu.

    Only actions marked with the dynamic property "keepMenuOpen" stay open;
    everything else (Edit presets, Quit, submenu openers) behaves normally.
    """

    def mouseReleaseEvent(self, event):
        action = self.actionAt(event.position().toPoint())
        if (
            action is not None
            and action.isEnabled()
            and action.menu() is None
            and action.property("keepMenuOpen")
        ):
            action.trigger()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class RatioMenu(QMenu):
    """The 'Resize to ratio' submenu, with an Alt-to-flip trick.

    Normally it lists the landscape ratios. While the menu is open and Alt is
    held, it rebuilds itself showing each ratio's portrait inverse (16:9 -> 9:16),
    so a pivoted monitor is one keypress away without cluttering the menu. This
    mirrors the macOS pattern of holding a modifier to reveal alternate items.
    """

    def __init__(self, area, on_pick, parent=None):
        super().__init__("Resize to ratio", parent)
        self._area = area
        self._on_pick = on_pick
        self._inverted = False

        # QMenu swallows the Alt key (it is reserved for mnemonics), so we can't
        # rely on key events. Instead, while the menu is open, poll the real
        # keyboard state a few times a second and flip when Alt changes.
        self._alt_timer = QTimer(self)
        self._alt_timer.setInterval(60)
        self._alt_timer.timeout.connect(self._poll_alt)
        self.aboutToShow.connect(self._on_show)
        self.aboutToHide.connect(self._alt_timer.stop)

    def _on_show(self):
        self._inverted = self._alt_is_held()
        self._rebuild()
        self._alt_timer.start()

    def _alt_is_held(self):
        modifiers = QApplication.queryKeyboardModifiers()
        return bool(modifiers & Qt.KeyboardModifier.AltModifier)

    def _poll_alt(self):
        held = self._alt_is_held()
        if held != self._inverted:
            self._inverted = held
            self._rebuild()

    def _rebuild(self):
        self.clear()
        hint = self.addAction(
            "Portrait (release Alt)" if self._inverted else "Hold Alt for portrait"
        )
        hint.setEnabled(False)
        self.addSeparator()

        for ratio_width, ratio_height in RATIOS:
            if self._inverted:
                ratio_width, ratio_height = ratio_height, ratio_width
            submenu = StickyMenu(ratio_label(ratio_width, ratio_height), self)
            self.addMenu(submenu)
            for width, height in sizes_for_ratio(
                ratio_width, ratio_height, self._area.width(), self._area.height()
            ):
                action = submenu.addAction(f"{width} × {height}")
                # Keep the menu open so several sizes can be tried in a row.
                action.setProperty("keepMenuOpen", True)
                action.triggered.connect(
                    lambda _checked, w=width, h=height: self._on_pick(w, h)
                )


TRAY_ICON_NAMES = ["transform-scale", "view-fullscreen", "zoom-fit-best", "preferences-system-windows"]
_INSTANCE_KEY = "just-right-window-sizer"
_DBUS_SERVICE  = "org.justright.tray"
_DBUS_PATH     = "/SizeOverlay"


# ---------------------------------------------------------------------------
# Geometry overlay — uses KDE's native OSD service (org.kde.plasmashell).
# Wayland doesn't let apps position their own windows freely, so a custom
# floating widget always ends up on the wrong screen. KDE's OSD handles
# Wayland output selection natively and looks like the volume/brightness HUD.
# (KDE only; on X11 there is no KWin script firing these callbacks.)
# ---------------------------------------------------------------------------

_OSD_SERVICE   = "org.kde.plasmashell"
_OSD_PATH      = "/org/kde/osdService"
_OSD_INTERFACE = "org.kde.osdService"
_OSD_ICON      = "zoom-fit-best"


def _call_osd(method, *args):
    msg = QDBusMessage.createMethodCall(_OSD_SERVICE, _OSD_PATH, _OSD_INTERFACE, method)
    msg.setArguments(list(args))
    QDBusConnection.sessionBus().call(msg)


# ---------------------------------------------------------------------------
# DBus service — receives callbacks from the KWin script
# ---------------------------------------------------------------------------

class TrayDBusService(QObject):
    """Exported on org.justright.tray /SizeOverlay so the KWin script can
    trigger the overlay and the add-preset dialog."""

    def __init__(self, tray, parent=None):
        super().__init__(parent)
        self._tray = tray

    @pyqtSlot(int, int, int, int)
    def showSize(self, x, y, width, height):   # noqa: N802
        self._tray.show_size_overlay(x, y, width, height)

    @pyqtSlot(int, int)
    def addCurrentSize(self, width, height):   # noqa: N802
        self._tray.prompt_add_preset(width, height)

    @pyqtSlot(int, int, int, int)
    def showClamped(self, requested_width, requested_height,   # noqa: N802
                    actual_width, actual_height):
        self._tray.show_clamped_overlay(
            requested_width, requested_height, actual_width, actual_height
        )


# ---------------------------------------------------------------------------
# Main tray class
# ---------------------------------------------------------------------------

class WindowSizerTray:
    def __init__(self, application):
        self.application = application
        self.backend = select_backend()
        self.presets = self.backend.activate()

        # The DBus callback service is only meaningful for the KWin backend,
        # which calls back into it. It's harmless to register on X11, but the
        # KWin overlay/add-preset path only fires when a KWin script is loaded.
        self._dbus_service = TrayDBusService(self)
        bus = QDBusConnection.sessionBus()
        bus.registerService(_DBUS_SERVICE)
        bus.registerObject(_DBUS_PATH, self._dbus_service,
                           QDBusConnection.RegisterOption.ExportAllSlots)

        # On X11 we render our own live drag-dimensions overlay (KDE uses the
        # KWin script + Plasma OSD instead, driven via the DBus service above).
        self._overlay = None
        self._resize_watcher = None
        self._scroll_resizer = None
        if self.backend.name == "x11":
            self._start_x11_overlay()
            self._start_x11_scroll_resize()

        self.tray_icon = QSystemTrayIcon(self._load_icon())
        self.tray_icon.setToolTip("Just Right")
        self.menu = StickyMenu()
        self.tray_icon.setContextMenu(self.menu)
        self.rebuild_menu()
        self.tray_icon.show()

    def _start_x11_overlay(self):
        """Bring up the X11 live-resize overlay. Optional: if python-xlib is
        missing, the tray still works, just without the drag dimensions box."""
        try:
            from sizer_overlay_x11 import DimensionsOverlay, ResizeWatcher
        except ImportError as error:
            print(
                f"Live dimensions overlay disabled (install python3-xlib): {error}",
                file=sys.stderr,
            )
            return
        self._overlay = DimensionsOverlay()
        self._resize_watcher = ResizeWatcher(self._overlay)

    def _start_x11_scroll_resize(self):
        """Enable Super+scroll to step the active window through its ratio
        ladder. Optional: needs python-xlib, and skips quietly if the
        modifier+wheel combo is already claimed by another app."""
        try:
            from sizer_scroll_x11 import ScrollResizer
        except ImportError as error:
            print(f"Scroll-to-resize disabled (install python3-xlib): {error}",
                  file=sys.stderr)
            return
        resizer = ScrollResizer(self.backend)
        if resizer.grab_failed:
            print("Scroll-to-resize disabled: Super+wheel is already in use by "
                  "another app. Change the modifier in sizer_scroll_x11.py.",
                  file=sys.stderr)
            return
        self._scroll_resizer = resizer

    def _load_icon(self):
        for icon_name in TRAY_ICON_NAMES:
            icon = QIcon.fromTheme(icon_name)
            if not icon.isNull():
                return icon
        return QIcon.fromTheme("application-x-executable")

    def rebuild_menu(self):
        self.menu.clear()
        for preset in self.presets:
            action = self.menu.addAction(sizer_engine.preset_label(preset))
            # Keep the menu open so several presets can be tried in a row.
            action.setProperty("keepMenuOpen", True)
            # 150 ms delay lets the click settle before the resize fires; the
            # menu is a popup, so the window behind it stays the active one.
            action.triggered.connect(
                lambda _checked, chosen=preset: QTimer.singleShot(
                    150, lambda: self.backend.trigger_preset(chosen)
                )
            )

        self.menu.addSeparator()
        self._add_ratio_menu()
        self.menu.addSeparator()
        self.menu.addAction("Add current window size…", self._trigger_add_current_size)
        self.menu.addSeparator()
        self.menu.addAction("Edit presets…", self.open_editor)
        self.menu.addAction("Reload backend", self.reload_script)
        self.menu.addSeparator()
        self.menu.addAction("Quit", self.application.quit)

    def _add_ratio_menu(self):
        """Add the 'Resize to ratio' submenu. Holding Alt while it is open flips
        every ratio to its portrait inverse (16:9 -> 9:16) for pivoted monitors.
        Clicking a size resizes and centers the active window."""
        area = self.application.primaryScreen().availableGeometry()
        self.menu.addMenu(RatioMenu(area, self._apply_ratio_size, self.menu))

    def _apply_ratio_size(self, width, height):
        # 150 ms delay lets the menu close so the user's window, not the menu,
        # is the active window when the resize fires.
        QTimer.singleShot(150, lambda: self.backend.apply_size(width, height, "center"))

    def _trigger_add_current_size(self):
        """Read the active window's current size so it can be saved as a preset.

        The 150 ms delay gives the tray menu time to close so the original
        window regains focus before the backend reads the active window.
        """
        QTimer.singleShot(150, lambda: self.backend.add_current_size(self))

    # -- callbacks from TrayDBusService (KWin backend only) --

    def show_size_overlay(self, x, y, width, height):
        _call_osd("showText", _OSD_ICON, f"{width} × {height}")

    def show_clamped_overlay(self, requested_width, requested_height,
                             actual_width, actual_height):
        _call_osd(
            "showText",
            _OSD_ICON,
            f"App refused {requested_width} × {requested_height} "
            f"(min {actual_width} × {actual_height})",
        )

    def prompt_add_preset(self, width, height):
        """Show a small dialog so the user can name and save the current size."""
        dialog = QDialog()
        dialog.setWindowTitle("Add preset")
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        dialog.resize(300, 120)

        name_edit = QLineEdit(f"{width}×{height}")
        name_edit.selectAll()

        form = QFormLayout()
        form.addRow("Name:", name_edit)
        form.addRow("Size:", QLabel(f"{width} × {height}"))

        save_button = QPushButton("Save")
        save_button.setDefault(True)
        cancel_button = QPushButton("Cancel")
        save_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(cancel_button)
        button_row.addWidget(save_button)

        layout = QVBoxLayout(dialog)
        layout.addLayout(form)
        layout.addLayout(button_row)

        if dialog.exec():
            name = name_edit.text().strip()
            if name:
                new_preset = {"name": name, "width": width, "height": height, "position": "keep"}
                sizer_engine.save_presets(self.presets + [new_preset])
                self.reload_script()

    # -- editor / reload --

    def open_editor(self):
        editor = PresetsEditor(self.presets)
        if editor.exec() and editor.saved_presets is not None:
            sizer_engine.save_presets(editor.saved_presets)
            self.reload_script()

    def reload_script(self):
        self.presets = self.backend.activate()
        self.rebuild_menu()


def main():
    application = QApplication(sys.argv)
    application.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("No system tray is available on this session.", file=sys.stderr)
        return 1

    # Single-instance guard: if another copy is already running, exit cleanly.
    probe = QLocalSocket()
    probe.connectToServer(_INSTANCE_KEY)
    if probe.waitForConnected(200):
        probe.close()
        print("Just Right is already running.", file=sys.stderr)
        return 0

    instance_server = QLocalServer()
    QLocalServer.removeServer(_INSTANCE_KEY)  # clean up any stale socket file
    instance_server.listen(_INSTANCE_KEY)

    # Keep both the tray and the server alive for the life of the process.
    # Assigning to application attributes prevents Python's GC from collecting
    # them (QSystemTrayIcon has no parent widget to keep it alive otherwise).
    application._tray = WindowSizerTray(application)
    application._instance_server = instance_server

    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
