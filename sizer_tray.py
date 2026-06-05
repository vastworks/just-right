#!/usr/bin/env python3
"""Window Sizer tray app.

Loads the KWin resize script on startup, then shows a system-tray menu listing
every saved preset. Clicking a preset resizes the currently active window.

Also hosts the org.justright.tray DBus service used by the KWin script to:
  - show the size overlay whenever any window is resized (showSize)
  - prompt the user to save the active window's current size (addCurrentSize)
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
from sizer_editor import PresetsEditor

TRAY_ICON_NAMES = ["transform-scale", "view-fullscreen", "zoom-fit-best", "preferences-system-windows"]
_INSTANCE_KEY = "just-right-window-sizer"
_DBUS_SERVICE  = "org.justright.tray"
_DBUS_PATH     = "/SizeOverlay"


# ---------------------------------------------------------------------------
# Geometry overlay — uses KDE's native OSD service (org.kde.plasmashell).
# Wayland doesn't let apps position their own windows freely, so a custom
# floating widget always ends up on the wrong screen. KDE's OSD handles
# Wayland output selection natively and looks like the volume/brightness HUD.
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


# ---------------------------------------------------------------------------
# Main tray class
# ---------------------------------------------------------------------------

class WindowSizerTray:
    def __init__(self, application):
        self.application = application
        self.presets = sizer_engine.reload_kwin_script()

        self._dbus_service = TrayDBusService(self)
        bus = QDBusConnection.sessionBus()
        bus.registerService(_DBUS_SERVICE)
        bus.registerObject(_DBUS_PATH, self._dbus_service,
                           QDBusConnection.RegisterOption.ExportAllSlots)

        self.tray_icon = QSystemTrayIcon(self._load_icon())
        self.tray_icon.setToolTip("Just Right")
        self.menu = QMenu()
        self.tray_icon.setContextMenu(self.menu)
        self.rebuild_menu()
        self.tray_icon.show()

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
            # 150 ms delay lets the tray menu fully close before the DBus trigger
            # fires — without it the active window would be the menu itself.
            action.triggered.connect(
                lambda _checked, chosen=preset: QTimer.singleShot(
                    150, lambda: sizer_engine.trigger_preset(chosen)
                )
            )

        self.menu.addSeparator()
        self.menu.addAction("Add current window size…", self._trigger_add_current_size)
        self.menu.addSeparator()
        self.menu.addAction("Edit presets…", self.open_editor)
        self.menu.addAction("Reload KWin script", self.reload_script)
        self.menu.addSeparator()
        self.menu.addAction("Quit", self.application.quit)

    def _trigger_add_current_size(self):
        """Ask the KWin script for the active window's current size.

        The 150 ms delay matches the preset-trigger delay — it gives the tray
        menu time to close so the original window regains focus before the
        KWin script reads workspace.activeWindow.
        """
        QTimer.singleShot(
            150,
            lambda: sizer_engine.run_qdbus(
                "/component/" + sizer_engine.KGLOBALACCEL_COMPONENT,
                "org.kde.kglobalaccel.Component.invokeShortcut",
                "WindowSizer_AddCurrentSize",
            ),
        )

    # -- callbacks from TrayDBusService --

    def show_size_overlay(self, x, y, width, height):
        _call_osd("showText", _OSD_ICON, f"{width} × {height}")

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
        self.presets = sizer_engine.reload_kwin_script()
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
