"""Картинка-карточка фильма в стиле приветствия новичков: обложка вместо аватарки, название вместо ника,
жанры вместо «Добро пожаловать», год · страна · длительность ниже, плашка «хотят посмотреть ×N»."""
import io
import random

from PIL import Image, ImageDraw, ImageFilter

from cogs.welcome_card import ACCENT, ACCENT2, FONT_BOLD, FONT_REG, background, font

W, H = 1100, 420
GOLD = (245, 197, 24)


def shrink_poster(data: bytes) -> bytes:
    """Обложку храним в базе компактно: 400 px по высоте, JPEG."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((600, 400))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, width: int, max_lines: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        test = (line + " " + w).strip()
        if draw.textlength(test, font=fnt) <= width:
            line = test
        else:
            lines.append(line)
            line = w
            if len(lines) == max_lines:
                break
    if line and len(lines) < max_lines:
        lines.append(line)
    if len(lines) == max_lines and " ".join(lines) != text:
        while draw.textlength(lines[-1] + "…", font=fnt) > width and lines[-1]:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def render(title: str, genres: list[str], meta: str, badge: str, poster: bytes | None, watched: bool = False) -> bytes:
    # фон: размытая обложка (если есть) или фирменный ночной фон
    if poster:
        p = Image.open(io.BytesIO(poster)).convert("RGB")
        scale = max(W / p.width, H / p.height)
        bg = p.resize((int(p.width * scale) + 1, int(p.height * scale) + 1)).filter(ImageFilter.GaussianBlur(28))
        left, top = (bg.width - W) // 2, (bg.height - H) // 2
        img = bg.crop((left, top, left + W, top + H)).convert("RGBA")
        img.alpha_composite(Image.new("RGBA", (W, H), (8, 6, 20, 150)))
    else:
        img = background(random.randint(0, 9999)).resize((W, H)).convert("RGBA")

    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle((30, 30, W - 30, H - 30), radius=32, fill=(10, 8, 25, 120),
                                            outline=(*(GOLD if not watched else (61, 220, 132)), 220), width=3)
    img.alpha_composite(panel)

    # обложка слева (или «плёнка», если обложки нет)
    pw, ph, px, py = 230, 340, 70, 40
    if poster:
        cover = Image.open(io.BytesIO(poster)).convert("RGB")
        scale = max(pw / cover.width, ph / cover.height)
        cover = cover.resize((int(cover.width * scale) + 1, int(cover.height * scale) + 1))
        l, t = (cover.width - pw) // 2, (cover.height - ph) // 2
        cover = cover.crop((l, t, l + pw, t + ph)).convert("RGBA")
    else:
        cover = Image.new("RGBA", (pw, ph), (35, 30, 60, 255))
        cd = ImageDraw.Draw(cover)
        for y in range(10, ph, 34):
            cd.rounded_rectangle((10, y, 26, y + 18), 3, fill=(15, 12, 30))
            cd.rounded_rectangle((pw - 26, y, pw - 10, y + 18), 3, fill=(15, 12, 30))
        cd.text((pw // 2, ph // 2), "КИНО", font=font(FONT_BOLD, 40), fill=(*GOLD, 255), anchor="mm")
    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw, ph), radius=18, fill=255)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle((px - 6, py - 6, px + pw + 6, py + ph + 6), radius=22,
                                           outline=(*ACCENT2, 255), width=5)
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3)))
    img.paste(cover, (px, py), mask)

    d = ImageDraw.Draw(img)
    x, maxw = px + pw + 50, W - (px + pw + 50) - 60
    gline = "  ·  ".join(g.upper() for g in genres) or "ФИЛЬМ"
    size = 26
    while size > 16 and d.textlength(gline, font=font(FONT_BOLD, size)) > maxw:  # много жанров — шрифт меньше
        size -= 2
    d.text((x, 62), gline, font=font(FONT_BOLD, size), fill=(*ACCENT2, 255))
    big = font(FONT_BOLD, 58)
    lines = wrap(d, title, big, maxw, 2)
    y = 100
    for line in lines:
        d.text((x + 2, y + 3), line, font=big, fill=(0, 0, 0, 170))
        d.text((x, y), line, font=big, fill=(255, 255, 255, 255))
        y += 66
    d.text((x, y + 8), meta, font=font(FONT_REG, 28), fill=(215, 210, 240, 255))
    bf = font(FONT_BOLD, 26)
    bw = d.textlength(badge, font=bf)
    colour = (61, 220, 132) if watched else ACCENT
    d.rounded_rectangle((x, H - 110, x + bw + 36, H - 64), radius=23, fill=(*colour, 235))
    d.text((x + 18, H - 104), badge, font=bf, fill=(255, 255, 255, 255))

    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()
