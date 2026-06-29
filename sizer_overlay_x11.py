"""Live drag-dimensions overlay for X11 desktops.

On X11, unlike Wayland, an app may freely position its own top-level
windows, so we can show a small floating "W x H" box right next to the
window being resized, exactly like Sizer on Windows.

How it works:
  - We ask the X server to notify us about geometry changes of every
    top-level window (SubstructureNotifyMask on the root window).
  - Those notifications arrive as ConfigureNotify events on the display's
    socket. A QSocketNotifier wakes us whenever that socket is readable, so
    this is fully event-driven, with no polling loop and no extra thread.
  - When a window's *size* (not just position) changes, we show the overlay
    near the cursor and arm a short timer to hide it once dragging stops.

Requires python3-xlib (the `Xlib` module). The tray imports this lazily and
degrades gracefully if it isn't installed.
"""

from PyQt6.QtCore import QObject, QPointF, QSocketNotifier, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import QWidget

from Xlib import X, display


# How long the box lingers after the last resize event, in milliseconds.
_HIDE_AFTER_MS = 600
# Offset from the cursor so the box doesn't sit directly under the pointer.
_CURSOR_OFFSET = (18, 18)

# Text appearance.
_FONT_POINT_SIZE = 17
_STROKE_WIDTH = 4               # black outline thickness, in pixels
_TEXT_FILL = QColor("#ffffff")
_TEXT_STROKE = QColor("#000000")
_PADDING_X = 12
_PADDING_Y = 7
# Subtle dark plate behind the text so it reads over any wallpaper.
_PLATE_COLOR = QColor(20, 20, 20, 150)
_PLATE_BORDER = QColor(255, 255, 255, 30)
_PLATE_RADIUS = 6


class DimensionsOverlay(QWidget):
    """A small frameless box that shows the current window size.

    The text is drawn as an outlined glyph path (a thick black stroke with a
    white fill) so the numbers stay legible against any window or wallpaper.
    """

    def __init__(self):
        super().__init__()
        # Tool + bypass-WM so it pops instantly, never steals focus, and the
        # window manager doesn't decorate or try to manage it.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._font = QFont()
        self._font.setPointSize(_FONT_POINT_SIZE)
        self._font.setBold(True)
        self._text = ""

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_dimensions(self, width, height):
        """Show "W x H" near the cursor and (re)arm the auto-hide timer."""
        self._text = f"{width} × {height}"

        metrics = QFontMetricsF(self._font)
        text_width = metrics.horizontalAdvance(self._text)
        text_height = metrics.height()
        # Pad for the box and the stroke that bleeds outside the glyph edges.
        self.setFixedSize(
            int(text_width + 2 * _PADDING_X + _STROKE_WIDTH),
            int(text_height + 2 * _PADDING_Y + _STROKE_WIDTH),
        )

        cursor = QCursor.pos()
        self.move(cursor.x() + _CURSOR_OFFSET[0], cursor.y() + _CURSOR_OFFSET[1])

        if not self.isVisible():
            self.show()
        self.update()
        self._hide_timer.start(_HIDE_AFTER_MS)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Dark plate behind the text.
        plate = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(_PLATE_BORDER, 1))
        painter.setBrush(_PLATE_COLOR)
        painter.drawRoundedRect(plate, _PLATE_RADIUS, _PLATE_RADIUS)

        # Build the glyph outline as a path so we can stroke and fill it.
        metrics = QFontMetricsF(self._font)
        half_stroke = _STROKE_WIDTH / 2
        baseline = QPointF(_PADDING_X + half_stroke, _PADDING_Y + half_stroke + metrics.ascent())
        glyphs = QPainterPath()
        glyphs.addText(baseline, self._font, self._text)

        # Draw the black outline first (centered on the path edge), then lay the
        # white fill on top so only the outer half of the stroke remains visible.
        outline_pen = QPen(_TEXT_STROKE, _STROKE_WIDTH)
        outline_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        outline_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(outline_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(glyphs)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_TEXT_FILL)
        painter.drawPath(glyphs)


class ResizeWatcher(QObject):
    """Watches top-level windows for size changes and drives the overlay.

    Hook it into the Qt event loop by simply constructing it; the
    QSocketNotifier does the rest. Keep a reference alive for the life of the
    app (the tray stores it on itself).

    We react only to size changes of the window currently under the mouse
    pointer, i.e. the one you are dragging. That filter does a lot of work: it
    ignores our own overlay window, tooltips, menus, and background windows,
    all of which produce ConfigureNotify noise (the overlay could even feed
    back on itself). Note we deliberately do NOT key off _NET_ACTIVE_WINDOW:
    on Cinnamon, grabbing a window's resize border does not make it the active
    window, so that test wrongly rejected the very window being resized.
    """

    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self._overlay = overlay
        self._last_size = {}

        self._display = display.Display()
        self._root = self._display.screen().root

        # SubstructureNotify: geometry changes of root's children (the windows).
        self._root.change_attributes(event_mask=X.SubstructureNotifyMask)
        self._display.flush()

        # The overlay's own X window, so we never react to it resizing itself.
        self._overlay_window_id = int(overlay.winId())

        # Wake _drain() whenever the X connection has events waiting.
        self._notifier = QSocketNotifier(
            self._display.fileno(), QSocketNotifier.Type.Read, self
        )
        self._notifier.activated.connect(self._drain)

    def _drain(self):
        # Read every event currently buffered, then return to the Qt loop.
        for _ in range(self._display.pending_events()):
            event = self._display.next_event()
            if event.type == X.ConfigureNotify:
                self._on_configure(event)
            elif event.type == X.DestroyNotify:
                self._last_size.pop(event.window.id, None)

    def _window_under_pointer(self):
        """Id of the root-level window the mouse is currently over, or None.

        query_pointer reports the child of root containing the pointer; with
        client-side decorations (Cinnamon) that is the window itself, which is
        what ConfigureNotify reports too.
        """
        try:
            child = self._root.query_pointer().child
        except Exception:
            return None
        if child is None or child == 0:
            return None
        return child.id

    def _on_configure(self, event):
        window_id = event.window.id
        if window_id == self._overlay_window_id:
            return

        size = (event.width, event.height)
        previous = self._last_size.get(window_id)
        self._last_size[window_id] = size

        # Only the size (not a plain move), and skip the first sighting so we
        # don't pop when a window first appears.
        if previous is None or previous == size:
            return

        # Only the window being dragged, i.e. the one under the pointer.
        if window_id != self._window_under_pointer():
            return

        self._overlay.show_dimensions(width=size[0], height=size[1])
