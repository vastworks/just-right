"""Modifier + scroll-wheel resize for X11 desktops.

Hold the modifier (Super by default) and scroll the wheel over a window to step
it through the size ladder for its current aspect ratio: scroll up grows it to
the next size, scroll down shrinks it. The window keeps its ratio family, so a
roughly 16:9 window steps through 16:9 sizes.

How it works: a passive X grab on the root window for buttons 4/5 (wheel up and
down) combined with the modifier. The grab delivers ButtonPress events to us
whenever Super+wheel happens over any window, without disturbing plain
scrolling. Events arrive on the display socket and are pumped by a
QSocketNotifier, the same event-driven pattern the overlay uses.

Requires python3-xlib. The tray imports this lazily and skips it if unavailable.
"""

from PyQt6.QtCore import QObject, QSocketNotifier

from Xlib import X, display

from sizer_ratios import nearest_ratio, sizes_for_ratio, stepped_size


# Modifier that must be held with the scroll wheel. Mod4 is the Super/Meta key.
# Change to e.g. X.ControlMask | X.Mod1Mask for Ctrl+Alt if Super conflicts.
_MODIFIER = X.Mod4Mask

# Wheel buttons: 4 is scroll up, 5 is scroll down.
_WHEEL_UP = 4
_WHEEL_DOWN = 5

# Re-grab the combo with each on/off state of Lock (Caps) and Mod2 (Num Lock)
# so it still fires when those happen to be on.
_LOCK_COMBOS = (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask)


class ScrollResizer(QObject):
    """Grabs modifier+wheel and steps the active window along its ratio ladder.

    Construct with the active backend (used to read the window geometry and
    apply the new size) and keep a reference alive for the app's lifetime.
    """

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self._backend = backend

        self._display = display.Display()
        self._root = self._display.screen().root
        self._grab_failed = False
        self._display.set_error_handler(self._on_x_error)

        for button in (_WHEEL_UP, _WHEEL_DOWN):
            for extra in _LOCK_COMBOS:
                self._root.grab_button(
                    button,
                    _MODIFIER | extra,
                    True,
                    X.ButtonPressMask,
                    X.GrabModeAsync,
                    X.GrabModeAsync,
                    X.NONE,
                    X.NONE,
                )
        # Force the grab requests out so any BadAccess (another client already
        # owns this combo) surfaces now via the error handler.
        self._display.sync()

        self._notifier = QSocketNotifier(
            self._display.fileno(), QSocketNotifier.Type.Read, self
        )
        self._notifier.activated.connect(self._drain)

    @property
    def grab_failed(self):
        """True if the modifier+wheel combo was already taken by another client."""
        return self._grab_failed

    def _on_x_error(self, error, request):
        # A BadAccess here means something else grabbed Super+wheel first.
        self._grab_failed = True

    def _drain(self):
        for _ in range(self._display.pending_events()):
            event = self._display.next_event()
            if event.type == X.ButtonPress:
                if event.detail == _WHEEL_UP:
                    self._step(+1)
                elif event.detail == _WHEEL_DOWN:
                    self._step(-1)

    def _step(self, direction):
        geometry = self._backend.active_window_geometry()
        if geometry is None:
            return
        monitor = self._backend.active_window_monitor_size()
        if monitor is None:
            return

        ratio_width, ratio_height = nearest_ratio(geometry["width"], geometry["height"])
        ladder = sizes_for_ratio(ratio_width, ratio_height, monitor[0], monitor[1])
        if not ladder:
            return

        target_width, target_height = stepped_size(ladder, geometry["width"], direction)
        # Keep the window where it is so repeated scrolls feel like scaling in
        # place rather than the window jumping around.
        self._backend.apply_size(target_width, target_height, "keep")
