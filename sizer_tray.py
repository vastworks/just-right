#!/usr/bin/env python3
"""Window Sizer tray app.

Loads the KWin resize script on startup, then shows a system-tray menu listing
every saved preset. Clicking a preset resizes the currently active window.
"""

import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import sizer_engine
from sizer_editor import PresetsEditor

TRAY_ICON_NAMES = ["transform-scale", "view-fullscreen", "zoom-fit-best", "preferences-system-windows"]


class WindowSizerTray:
    def __init__(self, application):
        self.application = application
        self.presets = sizer_engine.reload_kwin_script()

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
            action.triggered.connect(
                lambda _checked, chosen=preset: QTimer.singleShot(150, lambda: sizer_engine.trigger_preset(chosen))
            )

        self.menu.addSeparator()
        self.menu.addAction("Edit presets…", self.open_editor)
        self.menu.addAction("Reload KWin script", self.reload_script)
        self.menu.addSeparator()
        self.menu.addAction("Quit", self.application.quit)

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

    tray_instance = WindowSizerTray(application)
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
