"""Картинка-карточка фильма в стиле приветствия новичков: обложка вместо аватарки, название вместо ника,
жанры вместо «Добро пожаловать», год · страна · длительность ниже, плашка «хотят посмотреть ×N»."""
import io
import os
import random

from PIL import Image, ImageDraw, ImageFilter

from cogs.welcome_card import ACCENT, ACCENT2, FONT_BOLD, FONT_REG, ROOT, background, font

W, H = 1100, 420
GOLD = (245, 197, 24)
FRAME = os.path.join(ROOT, "assets", "cards", "film_frame.png")  # своя рамка; нет файла — рисуем как раньше


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


def cover_fit(data: bytes, w: int, h: int) -> Image.Image:
    """Картинка ровно w×h: увеличить и обрезать по центру."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    scale = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def render_frame(title: str, genres: list[str], badge: str, poster: bytes | None, watched: bool, info: dict) -> bytes:
    """Карточка в рамке assets/cards/film_frame.png. info: year, country, duration, description, count."""
    from cogs.welcome_card import centered, fit, inter
    frame = Image.open(FRAME).convert("RGBA")
    img = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    px0, py0, px1, py1 = 151, 32, 406, 365  # окно под постер
    d.rectangle((px0, py0, px1, py1), fill=(8, 12, 34, 255))
    if poster:
        img.paste(cover_fit(poster, px1 - px0 + 1, py1 - py0 + 1), (px0, py0))
    else:
        d.text(((px0 + px1) / 2, (py0 + py1) / 2), "КИНО", font=inter("Bold", 44), fill=(*GOLD, 255), anchor="mm")
    img.alpha_composite(frame)
    if poster:  # «кадры» справа внизу — увеличенные куски обложки, поверх тёмных окошек рамки
        big = cover_fit(poster, 600, 900)
        mask_cache = {}
        for i, (x0, x1) in enumerate([(1374, 1493), (1512, 1631), (1649, 1766), (1783, 1873)]):
            x0, x1, y0, y1 = x0 + 4, x1 - 4, 269, 350
            w, h = x1 - x0 + 1, y1 - y0 + 1
            part = big.crop((40 + i * 130, 140 + i * 160, 40 + i * 130 + w * 2, 140 + i * 160 + h * 2)).resize((w, h))
            if (w, h) not in mask_cache:
                mask_cache[w, h] = Image.new("L", (w, h), 0)
                ImageDraw.Draw(mask_cache[w, h]).rounded_rectangle((0, 0, w - 1, h - 1), radius=8, fill=255)
            img.paste(part, (x0, y0), mask_cache[w, h])
    d = ImageDraw.Draw(img)
    white, soft, blue = (255, 255, 255, 255), (205, 215, 240, 255), (120, 200, 255, 255)
    green = (61, 220, 132, 255)

    text, f = fit(d, title, "Bold", 34, 1020 - 554 - 24, smallest=18)
    d.text((566, 70), text, font=f, fill=white, anchor="lm")
    # «хотят ×N» и «в подборке» и так видны в нижней строке — в плашках только полезный статус
    status = "" if badge.startswith(("ХОТЯТ", "В ПОДБОРКЕ")) else badge
    pills = [*genres[:2], status][:3]
    for (x0, x1), label in zip([(500, 668), (683, 850), (866, 1035)], pills):
        if label:
            centered(d, (x0, 112, x1, 141), label.upper(), "Bold", 17, green if watched and label == badge else blue)
    for y0, y1, value in ((156, 185, info.get("year")), (200, 229, info.get("country")), (244, 273, info.get("duration"))):
        text, f = fit(d, value or "—", "Medium", 20, 785 - 566 - 20)
        d.text((578, (y0 + y1) / 2), text, font=f, fill=soft, anchor="lm")
    desc = info.get("description") or "Описания пока нет — его можно добавить кнопкой «Заполнить / исправить»."
    lines = wrap(d, desc, inter("Regular", 18), 1327 - 810 - 32, 4)
    for i, line in enumerate(lines):
        d.text((826, 166 + i * 24), line, font=inter("Regular", 18), fill=soft)
    label = "Уже посмотрели" if watched else "Хотят посмотреть"
    text, f = fit(d, label, "Bold", 24, 910 - 597 - 20)
    d.text((600, 327), text, font=f, fill=green if watched else white, anchor="lm")
    centered(d, (930, 301, 1094, 352), "✓" if watched else str(info.get("count") or 1), "Bold", 30,
             green if watched else blue)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def render(title: str, genres: list[str], meta: str, badge: str, poster: bytes | None, watched: bool = False,
           info: dict | None = None) -> bytes:
    if os.path.exists(FRAME):
        return render_frame(title, genres, badge, poster, watched, info or {})
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
