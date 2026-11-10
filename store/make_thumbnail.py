"""Render store/thumbnail.png (1000x360, the size the official plugins use).

    python3 store/make_thumbnail.py

Needs Pillow and the Open Sans font (Fedora: open-sans-fonts).
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1000, 360
FONTS = Path("/usr/share/fonts/open-sans")
OUT = Path(__file__).with_name("thumbnail.png")


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def background() -> Image.Image:
    """Dark horizontal gradient, darker in the middle like the official thumbnails."""
    img = Image.new("RGB", (W, H))
    px = img.load()
    for x in range(W):
        t = abs(x - W / 2) / (W / 2)
        c = (int(12 + 16 * t), int(13 + 17 * t), int(18 + 26 * t))
        for y in range(H):
            px[x, y] = c
    return img


def key(draw: ImageDraw.ImageDraw, x: int, y: int, size: int = 92) -> tuple[int, int]:
    draw.rounded_rectangle((x, y, x + size, y + size), radius=16,
                           fill=(34, 37, 48), outline=(70, 75, 92), width=2)
    return x + size // 2, y + size // 2


def main() -> None:
    img = background()
    d = ImageDraw.Draw(img)

    d.text((60, 92), "Werkbank", font=font("OpenSans-Semibold.ttf", 92), fill="white")
    d.text((64, 222), "Workflow keys for KDE Plasma", font=font("OpenSans-Regular.ttf", 34),
           fill=(205, 208, 218))

    gap, size = 16, 92
    x0, y0 = W - 60 - 3 * size - 2 * gap, (H - 2 * size - gap) // 2
    cells = [(x0 + c * (size + gap), y0 + r * (size + gap)) for r in range(2) for c in range(3)]

    # 1: status light (red / yellow / green)
    cx, cy = key(d, *cells[0])
    for i, col in enumerate([(230, 72, 72), (240, 190, 60), (80, 200, 110)]):
        oy = cy - 26 + i * 26
        d.ellipse((cx - 10, oy - 10, cx + 10, oy + 10), fill=col)

    # 2: countdown
    cx, cy = key(d, *cells[1])
    d.text((cx, cy), "25:00", font=font("OpenSans-Semibold.ttf", 26), fill="white", anchor="mm")

    # 3: terminal prompt
    cx, cy = key(d, *cells[2])
    d.text((cx, cy), ">_", font=font("OpenSans-Bold.ttf", 38), fill=(120, 200, 255), anchor="mm")

    # 4: guarded recording
    cx, cy = key(d, *cells[3])
    d.ellipse((cx - 20, cy - 20, cx + 20, cy + 20), fill=(225, 60, 60))

    # 5: note
    cx, cy = key(d, *cells[4])
    d.rectangle((cx - 18, cy - 24, cx + 18, cy + 24), outline=(220, 222, 230), width=3)
    for i in range(3):
        d.line((cx - 10, cy - 10 + i * 10, cx + 10, cy - 10 + i * 10), fill=(220, 222, 230), width=3)

    # 6: API value
    cx, cy = key(d, *cells[5])
    d.text((cx, cy), "3h12", font=font("OpenSans-Semibold.ttf", 28), fill=(80, 200, 110), anchor="mm")

    img.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
