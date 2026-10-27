#!/usr/bin/env python3
"""Generate the plugin logo (SVG + PNG) from one shared geometry definition.

Kept in-repo so the icon can be regenerated instead of being an opaque binary.

Run:  python3 assets/build-logo.py
Check: python3 assets/build-logo.py --check   # ASCII + pixel self-test

Design: a bracketed "window" whose rows grow wider line by line — the model
list, with the true context capacity on the last row.

Brackets are closed polygons: 8 points, mitred corners, no stroke caps. A
previous revision drew them as thick strokes, which (a) produced rounded caps
that read as stray dots at the corners and (b) silently degenerated into solid
bars when the arm weight equalled the spine width, because the notch between
the two arms had zero depth. Both are prevented by asserting the geometry.
"""
from __future__ import annotations

import sys
import pathlib

from PIL import Image, ImageDraw

S = 512
SS = 4  # supersampling factor for anti-aliasing
MID = S // 2

# --- palette -------------------------------------------------------------
BG_TOP = (0x1B, 0x2A, 0x4A)
BG_BOTTOM = (0x0D, 0x16, 0x26)
RADIUS = 112
BORDER = (0x3B, 0x4D, 0x6B)

ACCENT_START = (0x22, 0xD3, 0xEE)
ACCENT_END = (0xA7, 0x8B, 0xFA)
BAR_GRAD_START = (0x38, 0xBD, 0xF8)
BAR_GRAD_END = (0x81, 0x8C, 0xF8)

BAR_DIM = (0x5B, 0x72, 0x90)
BAR_MID = (0x8E, 0xA6, 0xC4)

# --- bracket geometry ----------------------------------------------------
# A bracket = vertical spine + two horizontal arms reaching inward.
#   spine width (horizontal)  = SPINE_W
#   arm thickness (vertical)  = ARM_H
#   arm reach (horizontal)    = ARM_LEN, measured from the spine's inner edge
# ARM_LEN must be > 0 or the notch between the arms collapses and the bracket
# renders as a plain filled bar.
SPINE_W = 38
ARM_H = 38
ARM_LEN = 46
BR_Y0, BR_Y1 = 138, 374

L_SPINE_OUT = 72
L_SPINE_IN = L_SPINE_OUT + SPINE_W        # 110
L_ARM_TIP = L_SPINE_IN + ARM_LEN          # 156
# Mirror about MID so both brackets are exactly symmetric.
R_SPINE_OUT = 2 * MID - L_SPINE_OUT       # 440 -> see R_SPINE_OUT below
R_ARM_TIP = 2 * MID - L_ARM_TIP           # 356
R_SPINE_IN = 2 * MID - L_SPINE_IN         # 402

# Recompute the right spine outer edge from the spine width, not by mirroring
# the left outer edge, so the pair cannot drift apart if SPINE_W changes.
R_SPINE_OUT = R_SPINE_IN + SPINE_W        # 440

# --- bars ----------------------------------------------------------------
BAR_H = 30
BAR_R = BAR_H // 2
BAR_GAP = 24
BAR_X = 170
BAR_W = (92, 130, 172)                    # growing length, top to bottom

# Centre the bar stack inside the bracket's inner window with an even margin
# on all four sides, instead of relying on the numbers happening to line up.
_WIN_TOP = BR_Y0 + ARM_H
_WIN_BOTTOM = BR_Y1 - ARM_H
_STACK_H = 3 * BAR_H + 2 * BAR_GAP
_BAR_TOP = _WIN_TOP + (_WIN_BOTTOM - _WIN_TOP - _STACK_H) // 2


def bar_box(i: int) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) of bar i, top to bottom."""
    y = _BAR_TOP + i * (BAR_H + BAR_GAP)
    return BAR_X, y, BAR_X + BAR_W[i], y + BAR_H


def lerp(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(round(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def hexc(c):
    return "#%02x%02x%02x" % c


def bracket_polygon(left: bool) -> list[tuple[int, int]]:
    """Closed mitred bracket outline, traced clockwise.

    Left bracket arms point right; the right bracket is the mirror image.
    """
    if left:
        spine_out, spine_in, tip = L_SPINE_OUT, L_SPINE_IN, L_ARM_TIP
    else:
        spine_out, spine_in, tip = R_SPINE_OUT, R_SPINE_IN, R_ARM_TIP
    y0, y1 = BR_Y0, BR_Y1
    return [
        (tip, y0),                    # top arm, tip, top edge
        (spine_out, y0),              # top-outer corner
        (spine_out, y1),              # bottom-outer corner
        (tip, y1),                    # bottom arm, tip, bottom edge
        (tip, y1 - ARM_H),            # bottom arm, tip, inner edge
        (spine_in, y1 - ARM_H),       # bottom arm meets spine
        (spine_in, y0 + ARM_H),       # up the inner face of the spine
        (tip, y0 + ARM_H),            # top arm, tip, inner edge
    ]


def assert_geometry() -> None:
    """Fail loudly on the degenerate cases that broke earlier revisions."""
    notch_depth = ARM_LEN
    assert notch_depth > 8, f"bracket notch too shallow ({notch_depth}px): would read as a solid bar"
    assert ARM_H < (BR_Y1 - BR_Y0) - 2 * ARM_H, "bracket arms would overlap"
    for i, w in enumerate(BAR_W):
        assert w < BAR_W[-1] + 1 or i == len(BAR_W) - 1, "bars must grow"
        x0, y0, x1, y1 = bar_box(i)
        assert x0 > L_ARM_TIP, f"bar {i} overlaps the left bracket arm"
        assert x1 < R_ARM_TIP, f"bar {i} overlaps the right bracket arm"
    assert BAR_W == tuple(sorted(BAR_W)), "bar widths must increase top to bottom"
    # Symmetry of the bracket pair about the vertical centre line.
    assert L_SPINE_OUT + R_SPINE_OUT == 2 * MID
    assert L_SPINE_IN + R_SPINE_IN == 2 * MID
    # Bars centred horizontally.
    assert bar_box(2)[0] + bar_box(2)[2] == 2 * MID, "bars not centred"
    # Bars centred vertically inside the brackets.
    assert bar_box(0)[1] + bar_box(2)[3] == 2 * MID, "bars not vertically centred"


def svg() -> str:
    """SVG source.

    Gradients use userSpaceOnUse: fills here are flush against vertical and
    horizontal edges, and objectBoundingBox gradients on a near-zero-width
    axis render as flat colour or nothing at all in some engines.
    """
    left = " ".join(f"{x},{y}" for x, y in bracket_polygon(True))
    right = " ".join(f"{x},{y}" for x, y in bracket_polygon(False))
    bars = []
    for i, w in enumerate(BAR_W):
        x0, y0, _, _ = bar_box(i)
        paint = "url(#bar)" if i == len(BAR_W) - 1 else hexc(BAR_DIM if i == 0 else BAR_MID)
        bars.append(
            f'  <rect x="{x0}" y="{y0}" width="{w}" height="{BAR_H}" '
            f'rx="{BAR_R}" fill="{paint}"/>'
        )
    bars_svg = "\n".join(bars)
    bar_x1 = bar_box(len(BAR_W) - 1)[2]

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" width="{S}" height="{S}" role="img" aria-label="Model Context Windows">
  <title>Model Context Windows</title>
  <defs>
    <linearGradient id="bg" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="{S}">
      <stop offset="0" stop-color="{hexc(BG_TOP)}"/>
      <stop offset="1" stop-color="{hexc(BG_BOTTOM)}"/>
    </linearGradient>
    <linearGradient id="accent" gradientUnits="userSpaceOnUse" x1="0" y1="{BR_Y0}" x2="0" y2="{BR_Y1}">
      <stop offset="0" stop-color="{hexc(ACCENT_START)}"/>
      <stop offset="1" stop-color="{hexc(ACCENT_END)}"/>
    </linearGradient>
    <linearGradient id="bar" gradientUnits="userSpaceOnUse" x1="{BAR_X}" y1="0" x2="{bar_x1}" y2="0">
      <stop offset="0" stop-color="{hexc(BAR_GRAD_START)}"/>
      <stop offset="1" stop-color="{hexc(BAR_GRAD_END)}"/>
    </linearGradient>
  </defs>

  <rect x="0" y="0" width="{S}" height="{S}" rx="{RADIUS}" ry="{RADIUS}" fill="url(#bg)"/>
  <rect x="4" y="4" width="{S - 8}" height="{S - 8}" rx="{RADIUS - 4}" ry="{RADIUS - 4}"
        fill="none" stroke="{hexc(BORDER)}" stroke-width="4" opacity="0.55"/>

  <polygon points="{left}" fill="url(#accent)"/>
  <polygon points="{right}" fill="url(#accent)"/>

{bars_svg}
</svg>
"""


def render_png() -> Image.Image:
    size = S * SS
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    grad = Image.new("RGB", (size, size))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        gd.line([(0, y), (size, y)], fill=lerp(BG_TOP, BG_BOTTOM, y / (size - 1)))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=RADIUS * SS, fill=255
    )
    canvas.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle(
        [4 * SS, 4 * SS, (S - 4) * SS, (S - 4) * SS],
        radius=(RADIUS - 4) * SS,
        outline=BORDER, width=4 * SS,
    )

    # Accent gradient restricted to the bracket band, applied through the
    # polygon masks so mitred corners stay sharp.
    accent = Image.new("RGB", (size, size), ACCENT_END)
    ad = ImageDraw.Draw(accent)
    top, bottom = BR_Y0 * SS, BR_Y1 * SS
    span = max(1, bottom - top)
    for y in range(size):
        ad.line([(0, y), (size, y)],
                fill=lerp(ACCENT_START, ACCENT_END, (y - top) / span))
    for left in (True, False):
        pmask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(pmask).polygon(
            [(x * SS, y * SS) for x, y in bracket_polygon(left)], fill=255
        )
        canvas.paste(accent, (0, 0), pmask)

    for i, w in enumerate(BAR_W):
        x0, y0, x1, y1 = (v * SS for v in bar_box(i))
        if i == len(BAR_W) - 1:
            bar = Image.new("RGB", (x1 - x0, y1 - y0))
            bd = ImageDraw.Draw(bar)
            for x in range(bar.size[0]):
                bd.line([(x, 0), (x, bar.size[1])],
                        fill=lerp(BAR_GRAD_START, BAR_GRAD_END, x / max(1, bar.size[0] - 1)))
            bmask = Image.new("L", bar.size, 0)
            ImageDraw.Draw(bmask).rounded_rectangle(
                [0, 0, bar.size[0] - 1, bar.size[1] - 1], radius=BAR_R * SS, fill=255
            )
            canvas.paste(bar, (x0, y0), bmask)
        else:
            d.rounded_rectangle([x0, y0, x1, y1], radius=BAR_R * SS,
                                fill=BAR_DIM if i == 0 else BAR_MID)

    return canvas.resize((S, S), Image.Resampling.LANCZOS)


def self_check(png: Image.Image) -> None:
    """Assert the rendered pixels actually contain the intended shapes."""
    px = png.convert("RGBA").load()

    def alpha(x, y):
        return px[x, y][3]

    def is_bg(x, y):
        """Background gradient is dark navy; shapes are much brighter."""
        r, g, b, a = px[x, y]
        return a > 200 and max(r, g, b) < 80

    def is_shape(x, y):
        """A rendered shape pixel: opaque and clearly brighter than the bg."""
        r, g, b, a = px[x, y]
        return a > 200 and max(r, g, b) >= 90

    # Outside the rounded corners must be fully transparent.
    assert alpha(2, 2) == 0, "corner should be transparent"

    # The notch between the two arms of a bracket must be BACKGROUND, not
    # accent — this is the exact check that catches a degenerate bracket.
    notch_x = (L_IN_REF + L_ARM_TIP) // 2 if False else (L_SPINE_IN + L_ARM_TIP) // 2
    notch_y = MID
    assert is_bg(notch_x, notch_y), \
        f"bracket notch filled with {px[notch_x, notch_y][:3]} (degenerate bracket)"

    # The spine itself must be accent-coloured at top and bottom.
    def close(a, b, tol=12):
        return all(abs(a[i] - b[i]) <= tol for i in range(3))

    spine_x = L_SPINE_OUT + SPINE_W // 2
    assert close(px[spine_x, BR_Y0 + 4][:3], ACCENT_START), \
        f"spine top not accent start: {px[spine_x, BR_Y0 + 4][:3]}"
    assert close(px[spine_x, BR_Y1 - 4][:3], ACCENT_END), \
        f"spine bottom not accent end: {px[spine_x, BR_Y1 - 4][:3]}"

    # Even breathing room: the bar stack must sit inside the bracket window
    # with a visible margin on all four sides.
    top_margin = bar_box(0)[1] - (BR_Y0 + ARM_H)
    bot_margin = (BR_Y1 - ARM_H) - bar_box(2)[3]
    left_margin = bar_box(0)[0] - L_ARM_TIP
    right_margin = R_ARM_TIP - bar_box(2)[2]
    assert min(top_margin, bot_margin, left_margin, right_margin) >= 8, \
        f"cramped layout: t={top_margin} b={bot_margin} l={left_margin} r={right_margin}"
    print(f"margins: top={top_margin} bottom={bot_margin} left={left_margin} right={right_margin}")

    # Arms must exist: sample just inside each arm tip.
    for tip, xsign in ((L_ARM_TIP, -1), (R_ARM_TIP, 1)):
        y_arm = BR_Y0 + ARM_H // 2
        assert is_shape(tip + xsign * 4, y_arm), f"missing top arm near x={tip}"
        assert is_shape(tip + xsign * 4, BR_Y1 - ARM_H // 2), f"missing bottom arm near x={tip}"

    # Bars: increasing length, all present, last one gradient.
    ends = []
    for i, w in enumerate(BAR_W):
        x0, y0, x1, y1 = bar_box(i)
        cy = (y0 + y1) // 2
        assert is_shape(x0 + 4, cy), f"bar {i} missing at left"
        assert is_shape(x1 - 4, cy), f"bar {i} missing at right"
        ends.append(x1)
    assert ends == sorted(ends), "bars are not left-aligned and growing"
    # Only the longest bar can be checked for overrun; shorter bars are
    # legitimately followed by a longer one below-turned-neighbour.
    last_x1 = bar_box(len(BAR_W) - 1)[2]
    gap_y = (bar_box(len(BAR_W) - 1)[1] + bar_box(len(BAR_W) - 1)[3]) // 2
    assert not is_shape(last_x1 + 8, gap_y), f"longest bar overruns to x={last_x1 + 8}"

    last = bar_box(len(BAR_W) - 1)
    left_rgb = px[last[0] + 6, (last[1] + last[3]) // 2][:3]
    right_rgb = px[last[2] - 6, (last[1] + last[3]) // 2][:3]
    assert left_rgb[2] > left_rgb[0] + 60, f"last bar left end not blue: {left_rgb}"
    assert right_rgb[0] > left_rgb[0], f"last bar gradient not progressing: {left_rgb}->{right_rgb}"

    # Left/right mirror symmetry of the bracket pair, sampled per row.
    for y in (BR_Y0 + 4, BR_Y0 + ARM_H + 10, MID, BR_Y1 - ARM_H - 10, BR_Y1 - 4):
        for x in range(L_SPINE_OUT, L_ARM_TIP + 1):
            assert is_shape(x, y) == is_shape(2 * MID - x, y), f"asymmetry at ({x},{y})"
    print("self-check: all assertions passed")


def ascii_map(png: Image.Image, cols=64) -> str:
    """Coarse text view so the shape can be inspected without an image viewer."""
    px = png.convert("RGBA").load()
    rows = cols // 2
    step = S // cols
    out = []
    for ry in range(rows * 2 if False else cols // 2 * 2):
        pass
    out = []
    for gy in range(0, S, step * 2):
        line = []
        for gx in range(0, S, step):
            r, g, b, a = px[min(gx, S - 1), min(gy, S - 1)]
            if a < 100:
                line.append(" ")
            elif r > 120 and b > 200:
                line.append("~")   # cyan
            elif b > 180 and r > 120:
                line.append("+")   # violet
            elif max(r, g, b) < 90:
                line.append(" ")   # background
            elif max(r, g, b) < 160:
                line.append(".")   # dim bar
            else:
                line.append("#")   # light bar
        out.append("".join(line))
    return "\n".join(out)


def main() -> None:
    assert_geometry()
    here = pathlib.Path(__file__).resolve().parent
    png = render_png()
    if "--check" in sys.argv:
        print(ascii_map(png))
        self_check(png)
        return
    (here / "logo.svg").write_text(svg(), encoding="utf-8")
    png.save(here / "logo.png", optimize=True)
    png.resize((64, 64), Image.Resampling.LANCZOS).save(here / "logo-64.png", optimize=True)
    print("wrote logo.svg, logo.png, logo-64.png to", here)


if __name__ == "__main__":
    main()
