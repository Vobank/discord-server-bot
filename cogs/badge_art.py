"""Значки достижений: картинки в assets/badges/<stat>_<need>.png (прозрачный фон), админ может заменить
любой командой /badge (свой файл или новый от ИИ — тогда он хранится в базе, таблица badges).
Здесь только рисование: вырезать фон у картинки от ИИ и собрать сетку значков для /achievements."""
import io
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = os.path.join(ROOT, "assets", "badges")
FONTS = os.path.join(ROOT, "assets", "fonts")
SIZE = 512


def cut_out(data: bytes, tolerance: int = 48) -> bytes:
    """Картинка от ИИ (значок на однотонном фоне) → PNG без фона, обрезанный по краю значка.
    Фон — всё, что похоже по цвету на края картинки и соединено с ними."""
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    if img.getextrema()[3][0] < 250:  # уже с прозрачным фоном — только обрезаем
        alpha = img.getchannel("A")
    else:
        rgb = img.convert("RGB")
        w, h = rgb.size
        border = [rgb.getpixel((x, y)) for x in range(0, w, 8) for y in (0, h - 1)] + \
                 [rgb.getpixel((x, y)) for y in range(0, h, 8) for x in (0, w - 1)]
        bg = tuple(sorted(c[i] for c in border)[len(border) // 2] for i in range(3))
        diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, bg))
        far = ImageChops.lighter(ImageChops.lighter(*diff.split()[:2]), diff.split()[2])
        mask = far.point(lambda v: 255 if v > tolerance else 0)
        for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            if mask.getpixel(corner) == 0:
                ImageDraw.floodfill(mask, corner, 128)
        alpha = mask.point(lambda v: 0 if v == 128 else 255).filter(ImageFilter.MinFilter(3))
        alpha = alpha.filter(ImageFilter.GaussianBlur(1.2))
    img.putalpha(alpha)
    box = alpha.point(lambda v: 255 if v > 20 else 0).getbbox() or (0, 0, *img.size)
    img = img.crop(box)
    side = max(img.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.alpha_composite(img, ((side - img.width) // 2, (side - img.height) // 2))
    square = square.resize((SIZE, SIZE), Image.LANCZOS)
    out = io.BytesIO()
    square.save(out, "PNG", optimize=True)
    return out.getvalue()


def default_file(key: str) -> bytes | None:
    path = os.path.join(FILES, f"{key}.png")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None


def locked(img: Image.Image) -> Image.Image:
    """Ещё не получено: серый и полупрозрачный."""
    grey = ImageOps.grayscale(img).convert("RGBA")
    grey = Image.eval(grey, lambda v: int(v * 0.55))
    grey.putalpha(img.getchannel("A").point(lambda v: int(v * 0.6)))
    return grey


def font(size: int, weight: str = "Bold"):
    path = os.path.join(FONTS, f"Inter-{weight}.ttf")
    return ImageFont.truetype(path, size) if os.path.exists(path) else ImageFont.load_default(size)


def grid(items: list[tuple[bytes | None, str, bool]], cols: int = 3) -> bytes:
    """Сетка значков для /achievements: (картинка, подпись, получено)."""
    cell, pad, caption = 240, 18, 46
    rows = (len(items) + cols - 1) // cols
    img = Image.new("RGBA", (cols * cell + pad * 2, rows * (cell + caption) + pad * 2), (24, 14, 44, 255))
    d = ImageDraw.Draw(img)
    for i, (data, name, got) in enumerate(items):
        x, y = pad + (i % cols) * cell, pad + (i // cols) * (cell + caption)
        if data:
            badge = Image.open(io.BytesIO(data)).convert("RGBA").resize((cell - 30, cell - 30), Image.LANCZOS)
            if got:  # мягкое свечение за полученным значком
                glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
                glow.paste((255, 200, 90, 90), (x + 15, y + 15), badge.getchannel("A"))
                img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)))
            img.alpha_composite(badge if got else locked(badge), (x + 15, y + 15))
        text, f = name, font(22)
        while d.textlength(text, font=f) > cell - 12 and len(text) > 3:
            text = text[:-2] + "…"
        d.text((x + cell / 2, y + cell + caption / 2 - 6), text, font=f, anchor="mm",
               fill=(255, 225, 140, 255) if got else (140, 130, 160, 255))
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()
