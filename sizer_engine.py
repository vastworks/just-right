"""Shared logic for Window Sizer.

Owns the presets file, generates the KWin script from those presets, loads the
script into KWin, and triggers a preset's resize action over DBus. Both the tray
app and the presets editor import from here so there is a single source of truth.
"""

import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

CONFIG_DIRECTORY = Path.home() / ".config" / "window-sizer"
PRESETS_PATH = CONFIG_DIRECTORY / "presets.json"
APP_PRESETS_PATH = CONFIG_DIRECTORY / "app-presets.json"
GENERATED_SCRIPT_PATH = CONFIG_DIRECTORY / "window-sizer.js"

# Name KWin/kglobalaccel uses to identify this loaded script.
KWIN_PLUGIN_NAME = "window_sizer"
# kglobalaccel groups every KWin-script shortcut under this component.
KGLOBALACCEL_COMPONENT = "kwin"

VALID_POSITIONS = ("keep", "center")
VALID_SIZE_MODES = ("outer", "client")

DEFAULT_PRESETS = [
    {"name": "720p", "width": 1280, "height": 720, "position": "keep"},
    {"name": "720p centered", "width": 1280, "height": 720, "position": "center"},
    {"name": "1080p", "width": 1920, "height": 1080, "position": "keep"},
    {"name": "Half HD", "width": 960, "height": 1080, "position": "keep"},
    {"name": "Compact", "width": 800, "height": 600, "position": "center"},
]

# Prefer the Qt6 qdbus binary; fall back to the Qt5 one if needed.
_QDBUS = next(
    (cmd for cmd in ("qdbus6", "qdbus-qt6", "qdbus") if shutil.which(cmd)),
    "qdbus",
)


def run_qdbus(object_path, method, *arguments):
    """Call a method on the org.kde.KWin / kglobalaccel DBus service.

    Returns the trimmed stdout string, or None if the call failed.
    """
    command = [_QDBUS, _service_for(object_path), object_path, method, *map(str, arguments)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _service_for(object_path):
    if object_path.startswith("/component") or "kglobalaccel" in object_path:
        return "org.kde.kglobalaccel"
    return "org.kde.KWin"


def action_name_for(preset):
    """Stable kglobalaccel action id for a preset. Survives renames so any
    keyboard shortcut the user assigns in System Settings stays bound."""
    return "WindowSizer_" + preset["identifier"]


def preset_label(preset):
    suffix = " · centered" if preset.get("position") == "center" else ""
    if preset.get("sizeMode", "outer") == "client":
        suffix += " · client area"
    return f"{preset['name']} ({preset['width']}×{preset['height']}){suffix}"


def preset_category(preset):
    """User-facing optional grouping for a preset.

    An absent category deliberately means "keep this legacy preset flat" so
    existing configurations retain their menu layout after an upgrade.
    """
    return str(preset.get("category", "")).strip()


def grouped_presets(presets):
    """Return ungrouped presets and ordered category groups for menu builders."""
    ungrouped = []
    groups = {}
    for preset in presets:
        category = preset_category(preset)
        if category:
            groups.setdefault(category, []).append(preset)
        else:
            ungrouped.append(preset)
    return ungrouped, groups


def ensure_config_exists():
    CONFIG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    if not PRESETS_PATH.exists():
        save_presets([_with_identifier(preset) for preset in DEFAULT_PRESETS])


def _with_identifier(preset):
    copied = dict(preset)
    copied.setdefault("identifier", uuid.uuid4().hex[:8])
    copied.setdefault("position", "keep")
    copied.setdefault("sizeMode", "outer")
    if copied["sizeMode"] not in VALID_SIZE_MODES:
        copied["sizeMode"] = "outer"
    return copied


def load_presets():
    ensure_config_exists()
    try:
        with open(PRESETS_PATH, "r", encoding="utf-8") as presets_file:
            raw_presets = json.load(presets_file)
    except (json.JSONDecodeError, ValueError):
        print(
            f"Warning: {PRESETS_PATH} is corrupted — falling back to defaults.",
            file=sys.stderr,
        )
        raw_presets = list(DEFAULT_PRESETS)
    return [_with_identifier(preset) for preset in raw_presets]


def save_presets(presets):
    CONFIG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    normalized = [_with_identifier(preset) for preset in presets]
    # Write atomically: write to a temp file then rename (POSIX rename is atomic,
    # so a crash mid-write never leaves presets.json truncated or partial).
    tmp_path = PRESETS_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as presets_file:
        json.dump(normalized, presets_file, indent=2)
    tmp_path.replace(PRESETS_PATH)
    return normalized


def app_identity_key(identity_type, identity_value):
    """Stable, namespaced key for a KWin application identity."""
    return f"{identity_type}:{identity_value}"


def load_app_presets():
    """Load optional remembered preset IDs from their separate config file."""
    if not APP_PRESETS_PATH.exists():
        return {}
    try:
        with open(APP_PRESETS_PATH, "r", encoding="utf-8") as app_file:
            remembered = json.load(app_file)
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
    return remembered if isinstance(remembered, dict) else {}


def remember_app_preset(identity_type, identity_value, preset_identifier):
    """Record the last manually selected preset for one application identity."""
    if not identity_type or not identity_value or not preset_identifier:
        return
    remembered = load_app_presets()
    remembered[app_identity_key(identity_type, identity_value)] = {
        "presetIdentifier": str(preset_identifier),
        "updatedAt": int(time.time()),
    }
    CONFIG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    tmp_path = APP_PRESETS_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as app_file:
        json.dump(remembered, app_file, indent=2)
    tmp_path.replace(APP_PRESETS_PATH)


def remembered_preset_identifier(identity_type, identity_value):
    entry = load_app_presets().get(app_identity_key(identity_type, identity_value), {})
    return entry.get("presetIdentifier") if isinstance(entry, dict) else None


def generate_script(presets):
    """Bake the preset list into a KWin JavaScript file. Each preset becomes a
    named shortcut that resizes (and optionally re-centers) the active window."""
    script_presets = [
        {
            "actionName": action_name_for(preset),
            "label": "Just Right: " + preset_label(preset),
            "menuLabel": preset_label(preset),
            "width": int(preset["width"]),
            "height": int(preset["height"]),
            "position": preset.get("position", "keep"),
            "sizeMode": preset.get("sizeMode", "outer"),
            "category": preset_category(preset),
            "identifier": preset["identifier"],
        }
        for preset in presets
    ]
    presets_literal = json.dumps(script_presets)

    script_source = f"""// Generated by Window Sizer. Do not edit by hand.
var windowSizerPresets = {presets_literal};
var windowSizerFitRatios = [[16, 9], [16, 10], [4, 3], [3, 2], [21, 9]];

function applyToActiveWindow(targetWidth, targetHeight, position, sizeMode, windowOverride) {{
    var win = windowOverride || workspace.activeWindow;
    if (!win) {{
        return;
    }}

    // Cancel any in-flight resize on this window (rapid double-trigger safety).
    if (win._sizerHandler) {{
        try {{ win.frameGeometryChanged.disconnect(win._sizerHandler); }} catch (e) {{}}
        win._sizerHandler = null;
    }}

    function doResize() {{
        win._sizerHandler = null;
        var currentGeometry = win.frameGeometry;
        var requestedFrameWidth = targetWidth;
        var requestedFrameHeight = targetHeight;
        if (sizeMode === "client") {{
            // KWin's clientGeometry is the compositor-defined client rectangle,
            // not an application's semantic viewport. Use the current frame
            // extents for a one-shot conversion to a frameGeometry request.
            var client = win.clientGeometry;
            requestedFrameWidth = targetWidth + Math.max(0, currentGeometry.width - client.width);
            requestedFrameHeight = targetHeight + Math.max(0, currentGeometry.height - client.height);
        }}
        var newX = currentGeometry.x;
        var newY = currentGeometry.y;
        if (position === "center") {{
            var area = workspace.clientArea(KWin.MaximizeArea, win);
            newX = area.x + Math.round((area.width - requestedFrameWidth) / 2);
            newY = area.y + Math.round((area.height - requestedFrameHeight) / 2);
        }}
        // Qt.rect() is QML-only; plain JS objects are converted to QRectF
        // via KWin's registered QJSValue→QRectF meta-type converter.
        win.frameGeometry = {{ x: newX, y: newY, width: requestedFrameWidth, height: requestedFrameHeight }};
        // KWin clamps to the app's declared minSize before applying; if the
        // resulting size differs from what we asked, surface that to the user.
        var actual = sizeMode === "client" ? win.clientGeometry : win.frameGeometry;
        if (actual.width !== targetWidth || actual.height !== targetHeight) {{
            callDBus("org.justright.tray", "/SizeOverlay",
                     "", "showClamped",
                     targetWidth, targetHeight,
                     Math.round(actual.width), Math.round(actual.height));
        }}
    }}

    function deferResize() {{
        var handler = function () {{
            win.frameGeometryChanged.disconnect(handler);
            win._sizerHandler = null;
            doResize();
        }};
        win._sizerHandler = handler;
        win.frameGeometryChanged.connect(handler);
    }}

    // Fullscreen: attach the handler BEFORE changing state so we never miss the
    // signal if KWin fires it synchronously during the property assignment.
    if (win.fullScreen) {{
        deferResize();
        win.fullScreen = false;
        return;
    }}

    // maximizeMode returns a Qt flags object in KWin 6 scripting — plain == comparisons
    // are useless (always truthy), but bitwise & coerces it to a number correctly.
    // Bit 1 = vertically maximized, bit 2 = horizontally maximized.
    // Skip tiled windows: they are not maximized and setMaximize would break tiling.
    var isTiled = win.tile !== null && win.tile !== undefined;
    var isMaximized = !isTiled && (win.maximizeMode & 3) === 3;

    win.setMaximize(false, false);

    if (isMaximized) {{
        // setMaximize is async on Wayland: KWin restores the pre-maximize geometry
        // after our JS returns, overwriting a same-tick frameGeometry assignment.
        // Wait for frameGeometryChanged (fires once KWin has settled the restored
        // geometry), then stamp our target size on top.
        deferResize();
    }} else {{
        doResize();
    }}
}}

function applicationIdentity(win) {{
    if (win.desktopFileName) return {{ type: "desktopFileName", value: win.desktopFileName }};
    if (win.resourceClass) return {{ type: "resourceClass", value: win.resourceClass }};
    if (win.resourceName) return {{ type: "resourceName", value: win.resourceName }};
    return null;
}}

function publishActiveApplication(win) {{
    var identity = applicationIdentity(win);
    if (!identity) return;
    callDBus("org.justright.tray", "/SizeOverlay", "", "showActiveApplication",
             identity.type, identity.value);
}}

function applyPreset(preset, windowOverride) {{
    var win = windowOverride || workspace.activeWindow;
    if (!win) return;
    var identity = applicationIdentity(win);
    if (identity) {{
        callDBus("org.justright.tray", "/SizeOverlay", "", "rememberPreset",
                 identity.type, identity.value, preset.identifier);
    }}
    applyToActiveWindow(preset.width, preset.height, preset.position, preset.sizeMode, win);
}}

function fitRatioToWindow(ratioWidth, ratioHeight, windowOverride) {{
    var win = windowOverride || workspace.activeWindow;
    if (!win) return;
    var area = workspace.clientArea(KWin.MaximizeArea, win);
    var width;
    var height;
    if (area.width * ratioHeight > ratioWidth * area.height) {{
        height = area.height;
        width = Math.round(height * ratioWidth / ratioHeight);
    }} else {{
        width = area.width;
        height = Math.round(width * ratioHeight / ratioWidth);
    }}
    applyToActiveWindow(width, height, "center", "outer", win);
}}

for (var presetIndex = 0; presetIndex < windowSizerPresets.length; presetIndex++) {{
    (function (preset) {{
        registerShortcut(preset.actionName, preset.label, "", function () {{
            applyPreset(preset);
        }});
    }})(windowSizerPresets[presetIndex]);
}}

for (var ratioIndex = 0; ratioIndex < windowSizerFitRatios.length; ratioIndex++) {{
    (function (ratio) {{
        var label = ratio[0] + ":" + ratio[1];
        registerShortcut("WindowSizer_FitRatio_" + ratio[0] + "x" + ratio[1],
                         "Just Right: Fit " + label, "", function () {{
            fitRatioToWindow(ratio[0], ratio[1]);
        }});
    }})(windowSizerFitRatios[ratioIndex]);
}}

// Add a "Just Right" submenu to the window title-bar right-click context menu.
registerUserActionsMenu(function (win) {{
    function menuItem(preset) {{
        return {{
            text: preset.menuLabel,
            triggered: function () {{
                applyPreset(preset, win);
            }}
        }};
    }}
    var ungrouped = [];
    var groups = {{}};
    var categoryOrder = [];
    windowSizerPresets.forEach(function (preset) {{
        if (!preset.category) {{
            ungrouped.push(menuItem(preset));
        }} else {{
            if (!groups[preset.category]) {{
                groups[preset.category] = [];
                categoryOrder.push(preset.category);
            }}
            groups[preset.category].push(menuItem(preset));
        }}
    }});
    var items = ungrouped.slice();
    categoryOrder.forEach(function (category) {{
        items.push({{ text: category, items: groups[category] }});
    }});
    var fitItems = windowSizerFitRatios.map(function (ratio) {{
        return {{
            text: "Fit " + ratio[0] + ":" + ratio[1] + " to work area",
            triggered: function () {{ fitRatioToWindow(ratio[0], ratio[1], win); }}
        }};
    }});
    items.push({{ text: "Fit aspect ratio", items: fitItems }});
    return {{
        text: "Just Right",
        items: items
    }};
}});

// ---------------------------------------------------------------------------
// Geometry tooltip: show a size overlay whenever any window is resized.
// Calls back to the tray app over DBus; the tray renders the overlay widget.
// ---------------------------------------------------------------------------
var _wsTooltipLastT = 0;

function wsNotifySize(win) {{
    var geo = win.frameGeometry;
    // Only fire when *this window's* size changes, not on plain moves.
    if (geo.width === win._wsLastW && geo.height === win._wsLastH) return;
    // Throttle to ~15 fps so we don't hammer DBus on every pixel.
    var now = Date.now();
    if (now - _wsTooltipLastT < 66) return;
    win._wsLastW = geo.width;
    win._wsLastH = geo.height;
    _wsTooltipLastT = now;
    callDBus("org.justright.tray", "/SizeOverlay",
             "", "showSize",
             Math.round(geo.x), Math.round(geo.y),
             Math.round(geo.width), Math.round(geo.height));
}}

function wsConnectWindow(win) {{
    // Seed the per-window size so the first frameGeometryChanged only fires
    // if the size actually changes (not on the first plain move).
    var geo = win.frameGeometry;
    win._wsLastW = geo.width;
    win._wsLastH = geo.height;
    win.frameGeometryChanged.connect(function() {{ wsNotifySize(win); }});
}}

// Connect to all windows already open, then to any that open later.
var _wsAllWindows = (typeof workspace.windowList === "function")
    ? workspace.windowList()
    : (workspace.windows || []);
for (var _wsIdx = 0; _wsIdx < _wsAllWindows.length; _wsIdx++) {{
    wsConnectWindow(_wsAllWindows[_wsIdx]);
}}
workspace.windowAdded.connect(wsConnectWindow);

// ---------------------------------------------------------------------------
// "Add current window size" shortcut — reads the active window's geometry
// and sends it to the tray so the user can save it as a new preset.
// ---------------------------------------------------------------------------
registerShortcut("WindowSizer_AddCurrentSize", "Just Right: Add current window size", "", function() {{
    var win = workspace.activeWindow;
    if (!win) return;
    var geo = win.frameGeometry;
    callDBus("org.justright.tray", "/SizeOverlay",
             "", "addCurrentSize",
             Math.round(geo.width), Math.round(geo.height));
}});

// Ask KWin, rather than Qt, for the usable area of the active window's output.
// This is important on mixed-monitor setups: QApplication.primaryScreen() can
// describe a completely different monitor from the window being resized.
registerShortcut("WindowSizer_RequestRatioArea", "Just Right: Refresh ratio menu", "", function() {{
    var win = workspace.activeWindow;
    if (!win) return;
    var area = workspace.clientArea(KWin.MaximizeArea, win);
    callDBus("org.justright.tray", "/SizeOverlay",
             "", "showRatioArea",
             Math.round(area.width), Math.round(area.height));
}});

registerShortcut("WindowSizer_RequestActiveApplication", "Just Right: Refresh active application", "", function() {{
    var win = workspace.activeWindow;
    if (win) publishActiveApplication(win);
}});

workspace.windowActivated.connect(function (win) {{ publishActiveApplication(win); }});
"""
    CONFIG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with open(GENERATED_SCRIPT_PATH, "w", encoding="utf-8") as script_file:
        script_file.write(script_source)
    return GENERATED_SCRIPT_PATH


def reload_kwin_script():
    """Regenerate the script from the saved presets and (re)load it into KWin."""
    presets = load_presets()
    generate_script(presets)
    run_qdbus("/Scripting", "org.kde.kwin.Scripting.unloadScript", KWIN_PLUGIN_NAME)
    run_qdbus("/Scripting", "org.kde.kwin.Scripting.loadScript",
              str(GENERATED_SCRIPT_PATH), KWIN_PLUGIN_NAME)
    run_qdbus("/Scripting", "org.kde.kwin.Scripting.start")
    return presets


def trigger_preset(preset):
    """Fire a preset's action, resizing whatever window is currently active."""
    return run_qdbus("/component/" + KGLOBALACCEL_COMPONENT,
                     "org.kde.kglobalaccel.Component.invokeShortcut",
                     action_name_for(preset))


# Separate plugin name so the one-shot script never disturbs the persistent one.
KWIN_ONESHOT_NAME = "window_sizer_oneshot"
ONESHOT_SCRIPT_PATH = CONFIG_DIRECTORY / "window-sizer-oneshot.js"


def apply_size_kwin(width, height, position="center", ratio=None):
    """Resize the active window to an arbitrary size right now, without a saved
    preset or registered shortcut. Used by the aspect-ratio scaler.

    Saved presets resize via a pre-registered kglobalaccel action; ad-hoc sizes
    have no such action, so we load a tiny one-shot KWin script that resizes the
    active window once on load, under its own plugin name so it leaves the
    persistent preset script alone.
    """
    _generate_oneshot_script(int(width), int(height), position, ratio)
    run_qdbus("/Scripting", "org.kde.kwin.Scripting.unloadScript", KWIN_ONESHOT_NAME)
    run_qdbus("/Scripting", "org.kde.kwin.Scripting.loadScript",
              str(ONESHOT_SCRIPT_PATH), KWIN_ONESHOT_NAME)
    run_qdbus("/Scripting", "org.kde.kwin.Scripting.start")


def _generate_oneshot_script(width, height, position, ratio=None):
    """Generate one bounded ratio correction after KWin applies client hints.

    A client can quantize or clamp a requested rectangle (terminal cell grids are
    a common example). Ratio actions get one follow-up geometry assignment based
    on KWin's accepted size; exact preset actions deliberately retain their
    current one-shot semantics. This is not an interactive-resize event loop.
    """
    target = json.dumps({
        "width": width,
        "height": height,
        "position": position,
        "ratio": list(ratio) if ratio is not None else None,
    })
    # Mirrors the resize logic in generate_script(): clear maximize/fullscreen
    # first, and on Wayland wait for frameGeometryChanged before stamping the
    # target size (setMaximize/fullScreen settle asynchronously).
    source = f"""// Generated by Window Sizer (one-shot). Do not edit by hand.
var target = {target};
(function () {{
    var win = workspace.activeWindow;
    if (!win) {{ return; }}

    function doResize() {{
        var geometry = win.frameGeometry;
        var newX = geometry.x;
        var newY = geometry.y;
        if (target.position === "center") {{
            var area = workspace.clientArea(KWin.MaximizeArea, win);
            newX = area.x + Math.round((area.width - target.width) / 2);
            newY = area.y + Math.round((area.height - target.height) / 2);
        }}
        armRatioCorrection();
        win.frameGeometry = {{ x: newX, y: newY, width: target.width, height: target.height }};
    }}

    function constrainRatioOnce() {{
        if (!target.ratio) return;
        var ratioWidth = target.ratio[0];
        var ratioHeight = target.ratio[1];
        var actual = win.frameGeometry;
        if (actual.width * ratioHeight === actual.height * ratioWidth) return;

        // Respect the dimension KWin/client accepted, then derive the other.
        // If one requested dimension survived client quantisation, preserve it;
        // otherwise prefer changing the smaller amount. Never exceed the work
        // area.
        var fromHeight = {{
            width: Math.round(actual.height * ratioWidth / ratioHeight),
            height: actual.height
        }};
        var fromWidth = {{
            width: actual.width,
            height: Math.round(actual.width * ratioHeight / ratioWidth)
        }};
        var area = workspace.clientArea(KWin.MaximizeArea, win);
        var candidates = [fromHeight, fromWidth].filter(function (candidate) {{
            return candidate.width > 0 && candidate.height > 0 &&
                candidate.width <= area.width && candidate.height <= area.height;
        }});
        if (!candidates.length) return;
        var corrected;
        if (actual.width === target.width &&
                   fromHeight.width <= area.width && fromHeight.height <= area.height) {{
            corrected = fromHeight;
        }} else if (actual.height === target.height &&
                   fromWidth.width <= area.width && fromWidth.height <= area.height) {{
            corrected = fromWidth;
        }} else {{
            candidates.sort(function (left, right) {{
                var leftDelta = Math.abs(left.width - actual.width) + Math.abs(left.height - actual.height);
                var rightDelta = Math.abs(right.width - actual.width) + Math.abs(right.height - actual.height);
                return leftDelta - rightDelta;
            }});
            corrected = candidates[0];
        }}
        if (corrected.width > area.width || corrected.height > area.height) return;
        if (corrected.width === actual.width && corrected.height === actual.height) return;
        var x = actual.x;
        var y = actual.y;
        if (target.position === "center") {{
            x = area.x + Math.round((area.width - corrected.width) / 2);
            y = area.y + Math.round((area.height - corrected.height) / 2);
        }}
        win.frameGeometry = {{ x: x, y: y, width: corrected.width, height: corrected.height }};
    }}

    function armRatioCorrection() {{
        if (!target.ratio) return;

        // KWin can apply a geometry first and a client can then asynchronously
        // snap it to its size increments. Watch only the resize action's short
        // settling window, and disconnect *before* our one correction. This is
        // intentionally not a persistent geometry-change feedback loop and is
        // unrelated to interactive aspect-ratio locking.
        var startedAt = Date.now();
        var handler = function () {{
            if (Date.now() - startedAt > 1000) {{
                win.frameGeometryChanged.disconnect(handler);
                return;
            }}
            var actual = win.frameGeometry;
            if (actual.width * target.ratio[1] === actual.height * target.ratio[0]) {{
                return;
            }}
            win.frameGeometryChanged.disconnect(handler);
            constrainRatioOnce();
        }};
        win.frameGeometryChanged.connect(handler);
    }}

    function deferResize() {{
        var handler = function () {{
            win.frameGeometryChanged.disconnect(handler);
            doResize();
        }};
        win.frameGeometryChanged.connect(handler);
    }}

    if (win.fullScreen) {{
        deferResize();
        win.fullScreen = false;
        return;
    }}

    var isTiled = win.tile !== null && win.tile !== undefined;
    var isMaximized = !isTiled && (win.maximizeMode & 3) === 3;
    win.setMaximize(false, false);

    if (isMaximized) {{
        deferResize();
    }} else {{
        doResize();
    }}
}})();
"""
    CONFIG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with open(ONESHOT_SCRIPT_PATH, "w", encoding="utf-8") as script_file:
        script_file.write(source)
    return ONESHOT_SCRIPT_PATH
