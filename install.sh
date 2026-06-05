#!/usr/bin/env bash
# Installer for Window Sizer (KDE Plasma / Wayland).
# - ensures PyQt6 is available
# - enables KWin's built-in "show geometry while resizing" tooltip
# - generates default presets and loads the KWin script
# - sets the tray app to start at login and adds a menu launcher for the editor
set -euo pipefail

PROJECT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$(command -v python3)"

echo "Using Python: $PYTHON_BIN"

if ! "$PYTHON_BIN" -c "import PyQt6" >/dev/null 2>&1; then
    echo "PyQt6 not found — installing for the current user..."
    "$PYTHON_BIN" -m pip install --user PyQt6
fi

echo "Enabling KWin's built-in geometry tooltip while resizing..."
kwriteconfig6 --file kwinrc --group Windows --key GeometryTip true
qdbus org.kde.KWin /KWin org.kde.KWin.reconfigure >/dev/null 2>&1 || true

echo "Generating default presets and loading the KWin script..."
( cd "$PROJECT_DIRECTORY" && "$PYTHON_BIN" -c "import sizer_engine; sizer_engine.reload_kwin_script()" )

AUTOSTART_DIRECTORY="$HOME/.config/autostart"
APPLICATIONS_DIRECTORY="$HOME/.local/share/applications"
mkdir -p "$AUTOSTART_DIRECTORY" "$APPLICATIONS_DIRECTORY"

echo "Installing autostart entry for the tray app..."
cat > "$AUTOSTART_DIRECTORY/window-sizer.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Just Right
Comment=Tray menu to resize windows to exact sizes
Exec=$PYTHON_BIN $PROJECT_DIRECTORY/sizer_tray.py
Icon=transform-scale
X-GNOME-Autostart-enabled=true
DESKTOP

echo "Installing menu launcher for the presets editor..."
cat > "$APPLICATIONS_DIRECTORY/window-sizer-editor.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Just Right — Edit Presets
Comment=Add, edit, and delete saved window sizes
Exec=$PYTHON_BIN $PROJECT_DIRECTORY/sizer_editor.py
Icon=transform-scale
Categories=Utility;Settings;
Terminal=false
DESKTOP

update-desktop-database "$APPLICATIONS_DIRECTORY" >/dev/null 2>&1 || true

echo
echo "Done. The tray app will start automatically at your next login."
echo "To start it now without logging out, run:"
echo "    setsid $PYTHON_BIN $PROJECT_DIRECTORY/sizer_tray.py >/dev/null 2>&1 &"
echo
echo "Look for the Window Sizer icon in your system tray once it is running."
echo "Optional: assign keyboard shortcuts in System Settings → Shortcuts → search 'Just Right'."
