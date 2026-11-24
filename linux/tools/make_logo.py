#!/usr/bin/env python3
"""Draw the recovery logo shown at the top of the menu.

The stock LineageOS logo is a bitmap, not a string: res/images/logo_image*.png
in the recovery ramdisk, 768x480, black ground, #7c4dff rounded frame and
#f891ff letter-spaced caption. This reproduces that layout with the project's
own name, so the branding change is a file swap rather than a runtime patch.

  tools/make_logo.py                       # writes assets/logo_sonofanton.png

The build does not run this: tools/make_launcher_ramdisk.py injects the
committed PNG, so a host without Pillow can still build.
"""
import argparse
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 768, 480
FRAME = (124, 77, 255)
CAPTION = (248, 145, 255)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

# Frame geometry measured from the stock logo_image_switch.png.
FRAME_BOX = (3, 129, 765, 350)
FRAME_RADIUS = 72
FRAME_WIDTH = 5

FONT_CANDIDATES = [
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
]


def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    raise SystemExit("no bold TrueType font found; tried:\n  " + "\n  ".join(FONT_CANDIDATES))


def draw_centered(draw, text, y, font, fill, tracking=0):
    """Draw text centred horizontally on y (top), with optional letter spacing."""
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = (W - total) / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill)
        x += w + tracking
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="SonOfAnton II")
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets", "logo_sonofanton.png"))
    args = ap.parse_args()

    im = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(FRAME_BOX, radius=FRAME_RADIUS, outline=FRAME, width=FRAME_WIDTH)

    # Name inside the frame: largest size that still fits with a margin.
    size = 76
    while size > 24:
        font = load_font(size)
        if d.textlength(args.name, font=font) <= (FRAME_BOX[2] - FRAME_BOX[0]) - 90:
            break
        size -= 2
    font = load_font(size)
    box = d.textbbox((0, 0), args.name, font=font)
    text_h = box[3] - box[1]
    centre = (FRAME_BOX[1] + FRAME_BOX[3]) / 2
    draw_centered(d, args.name, centre - text_h / 2 - box[1], font, WHITE)

    # Caption below the frame, letter-spaced, like the stock wordmark.
    draw_centered(d, "RECOVERY", 383, load_font(40), CAPTION, tracking=12)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    im.save(args.out, optimize=True)
    print(f"wrote {args.out} ({os.path.getsize(args.out)} bytes, {W}x{H}, name {size}px)")


if __name__ == "__main__":
    main()
