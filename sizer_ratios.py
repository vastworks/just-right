"""Aspect-ratio scaler: turn a ratio into a ladder of sizes that fit the screen.

The tray shows a "Resize to ratio" menu. Under each ratio it lists several
sizes at that exact ratio, scaled to the user's display: the largest that fits,
then progressively smaller steps. Picking one resizes (and centers) the active
window through the normal backend, so it works on KDE and X11 alike.

This module is pure arithmetic so it can be unit-tested without a display.
"""

# Ratios offered in the menu, as (width, height). Editable.
RATIOS = [(16, 9), (16, 10), (4, 3), (21, 9)]

# Fractions of the largest fitting box to offer, biggest first.
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


def sizes_for_ratio(
    ratio_width, ratio_height, available_width, available_height, steps=SCALE_STEPS
):
    """Ladder of (width, height) sizes at this ratio, scaled to the screen.

    Heights are scaled by each step and widths recomputed from the height so
    every entry keeps the ratio. Duplicate and zero sizes are dropped.
    """
    base_width, base_height = largest_fitting_size(
        ratio_width, ratio_height, available_width, available_height
    )

    sizes = []
    seen = set()
    for step in steps:
        height = round(base_height * step)
        width = round(height * ratio_width / ratio_height)
        if width <= 0 or height <= 0:
            continue
        if (width, height) in seen:
            continue
        seen.add((width, height))
        sizes.append((width, height))
    return sizes
