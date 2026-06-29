"""Aspect-ratio scaler: turn a ratio into a ladder of sizes that fit the screen.

The tray shows a "Resize to ratio" menu. Under each ratio it lists several
sizes at that exact ratio, scaled to the user's display: the largest that fits,
then progressively smaller steps. Picking one resizes (and centers) the active
window through the normal backend, so it works on KDE and X11 alike.

This module is pure arithmetic so it can be unit-tested without a display.
"""

# Ratios offered in the menu, as (width, height). Editable.
RATIOS = [(16, 9), (16, 10), (4, 3), (21, 9)]

# Well-known sizes per ratio, biggest first, each an exact match for its ratio.
# The menu shows the ones that fit the display, so common resolutions like
# 1920x1080 appear by name instead of odd screen-scaled values.
STANDARD_SIZES = {
    (16, 9): [(3840, 2160), (2560, 1440), (1920, 1080), (1600, 900),
              (1280, 720), (1024, 576)],
    (16, 10): [(2560, 1600), (1920, 1200), (1680, 1050), (1440, 900),
               (1280, 800)],
    (4, 3): [(2048, 1536), (1920, 1440), (1600, 1200), (1400, 1050),
             (1280, 960), (1024, 768), (800, 600)],
    (21, 9): [(3360, 1440), (2520, 1080), (1680, 720), (1260, 540)],
}

# Fallback fractions, used only for a ratio with no standard list (or a display
# too small for any standard size to fit).
SCALE_STEPS = (1.0, 0.85, 0.70, 0.60, 0.50)


def ratio_label(ratio_width, ratio_height):
    return f"{ratio_width}:{ratio_height}"


def portrait_ratios():
    """The RATIOS turned on their side (16:9 -> 9:16), for pivoted monitors."""
    return [(ratio_height, ratio_width) for ratio_width, ratio_height in RATIOS]


def oriented_ratios():
    """Every ratio in both orientations, landscape first, de-duplicated.

    Used to match a window's current proportions regardless of whether it is
    wider or taller than it is square."""
    result = []
    seen = set()
    for pair in list(RATIOS) + portrait_ratios():
        if pair not in seen:
            seen.add(pair)
            result.append(pair)
    return result


def largest_fitting_size(ratio_width, ratio_height, available_width, available_height):
    """The biggest width x height at the given ratio that fits the available
    area, preserving the ratio exactly (limited by whichever screen dimension
    runs out first)."""
    # Compare the screen's aspect to the target ratio by cross-multiplying
    # (avoids floating point). If the screen is wider than the ratio, height is
    # the limiting dimension; otherwise width is.
    if available_width * ratio_height > ratio_width * available_height:
        height = available_height
        width = round(height * ratio_width / ratio_height)
    else:
        width = available_width
        height = round(width * ratio_height / ratio_width)
    return width, height


def nearest_ratio(window_width, window_height):
    """The ratio in RATIOS closest to a window's current proportions.

    Lets the scroll-to-resize feature keep a window in its own ratio family and
    orientation: a roughly 16:9 window steps through 16:9 sizes, and a portrait
    window on a pivoted monitor steps through 9:16 sizes.
    """
    current = window_width / window_height
    return min(oriented_ratios(), key=lambda r: abs(current - r[0] / r[1]))


def stepped_size(ladder, current_width, direction):
    """Pick the next size up or down a ladder relative to the current width.

    ``direction`` is +1 to grow (next size wider than current) or -1 to shrink
    (next size narrower). At an end, clamps to the largest/smallest entry.
    Compares on width; since the ladder shares one ratio, height tracks along.
    """
    if direction > 0:
        bigger = [size for size in ladder if size[0] > current_width]
        if bigger:
            return min(bigger, key=lambda size: size[0])
        return max(ladder, key=lambda size: size[0])
    else:
        smaller = [size for size in ladder if size[0] < current_width]
        if smaller:
            return max(smaller, key=lambda size: size[0])
        return min(ladder, key=lambda size: size[0])


def _standard_sizes(ratio_width, ratio_height):
    """The curated standard sizes for a ratio, in either orientation, or None.

    Portrait ratios reuse their landscape list with width/height swapped, so
    9:16 offers 1080x1920 where 16:9 offers 1920x1080."""
    if (ratio_width, ratio_height) in STANDARD_SIZES:
        return STANDARD_SIZES[(ratio_width, ratio_height)]
    if (ratio_height, ratio_width) in STANDARD_SIZES:
        return [(h, w) for w, h in STANDARD_SIZES[(ratio_height, ratio_width)]]
    return None


def _scaled_ladder(ratio_width, ratio_height, available_width, available_height):
    """Fallback: scale the largest fitting box by SCALE_STEPS."""
    base_width, base_height = largest_fitting_size(
        ratio_width, ratio_height, available_width, available_height
    )
    sizes = []
    seen = set()
    for step in SCALE_STEPS:
        height = round(base_height * step)
        width = round(height * ratio_width / ratio_height)
        if width <= 0 or height <= 0 or (width, height) in seen:
            continue
        seen.add((width, height))
        sizes.append((width, height))
    return sizes


def sizes_for_ratio(ratio_width, ratio_height, available_width, available_height):
    """Sizes at this ratio to offer for the given display, biggest first.

    Uses the curated standard sizes that fit the screen (so 16:9 includes
    1920x1080). Falls back to a screen-scaled ladder for a ratio with no
    standard list, or when the display is too small for any standard size.
    """
    standard = _standard_sizes(ratio_width, ratio_height)
    if standard is not None:
        fitting = [
            (width, height)
            for width, height in standard
            if width <= available_width and height <= available_height
        ]
        if fitting:
            return fitting
    return _scaled_ladder(ratio_width, ratio_height, available_width, available_height)
