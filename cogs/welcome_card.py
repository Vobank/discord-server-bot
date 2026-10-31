"""Карточка «только что присоединился» в #🎉・новички.
Свой фон: положи картинку в assets/welcome_bg.png (лучше 1100x400), иначе рисуется фирменный ночной фон.
Цвета и надписи — в настройках (theme)."""
import asyncio
import io
import os
import random

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config
import db

W, H = 1100, 400
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BG_FILE = os.path.join(ROOT, config.THEME.get("welcome_banner") or "assets/welcome_bg.png")
FONT_BOLD = next((p for p in (r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf",
                              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf") if os.path.exists(p)), None)
FONT_REG = next((p for p in (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf",
                             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf") if os.path.exists(p)), None)
ACCENT, ACCENT2 = config.ACCENT, config.ACCENT2  # цвета из настроек (theme)


def font(path, size):
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)


def background(seed: int) -> Image.Image:
    if os.path.exists(BG_FILE):
        bg = Image.open(BG_FILE).convert("RGB")
        scale = max(W / bg.width, H / bg.height)
        bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1))
        left, top = (bg.width - W) // 2, (bg.height - H) // 2
        return bg.crop((left, top, left + W, top + H))

    # Фирменный фон: ночной градиент + светящиеся пятна + звёзды + сетка
    rnd = random.Random(seed)
    img = Image.new("RGB", (W, H))
    top, bottom = (18, 10, 40), (8, 30, 60)
    px = img.load()
    for y in range(H):
        t = y / H
        for x in range(W):
            k = (t + x / W * 0.4) / 1.4
            px[x, y] = tuple(int(top[i] * (1 - k) + bottom[i] * k) for i in range(3))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for cx, cy, r, col in [(160, 60, 260, ACCENT), (980, 360, 300, ACCENT2), (720, 40, 180, (255, 90, 170))]:
        gd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=tuple(c // 2 for c in col))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    img = Image.blend(img, glow, 0.55)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 44):  # лёгкая перспективная сетка снизу
        d.line([(W / 2 + (x - W / 2) * 0.35, H * 0.62), (x, H)], fill=(60, 50, 110), width=1)
    for i in range(6):
        y = H * 0.62 + (H * 0.38) * (i / 6) ** 1.6
        d.line([(0, y), (W, y)], fill=(60, 50, 110), width=1)
    for _ in range(90):
        x, y, s = rnd.randint(0, W), rnd.randint(0, int(H * 0.6)), rnd.choice((1, 1, 2))
        d.ellipse((x, y, x + s, y + s), fill=(220, 220, 255))
    return img


def circle_avatar(data: bytes, size: int) -> Image.Image:
    av = Image.open(io.BytesIO(data)).convert("RGBA").resize((size, size))
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4, size * 4), fill=255)
    av.putalpha(mask.resize((size, size), Image.LANCZOS))
    return av


def render(avatar: bytes, name: str, number: int, server: str) -> bytes:
    img = background(number).convert("RGBA")
    d = ImageDraw.Draw(img)

    # затемнённая плашка
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle((30, 30, W - 30, H - 30), radius=32, fill=(10, 8, 25, 140),
                                            outline=(*ACCENT, 200), width=3)
    img.alpha_composite(panel)

    # аватар со светящимся кольцом
    size, ax, ay = 220, 80, (H - 220) // 2
    ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    for i, col in enumerate((ACCENT2, ACCENT)):
        pad = 14 - i * 6
        rd.ellipse((ax - pad, ay - pad, ax + size + pad, ay + size + pad), outline=(*col, 255), width=6)
    img.alpha_composite(ring.filter(ImageFilter.GaussianBlur(2)))
    img.alpha_composite(circle_avatar(avatar, size), (ax, ay))

    # водяной знак названия сервера справа (отдельным слоем, чтобы была прозрачность)
    wm_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    wd = ImageDraw.Draw(wm_layer)
    wm, text = font(FONT_BOLD, 150), server.upper()
    wd.text((W - 50 - wd.textlength(text, font=wm), H - 205), text, font=wm, fill=(255, 255, 255, 18))
    img.alpha_composite(wm_layer)
    d = ImageDraw.Draw(img)

    # текст
    x = ax + size + 60
    big = font(FONT_BOLD, 64)
    nm = name if d.textlength(name, font=big) < W - x - 60 else name[:16] + "…"
    d.text((x, 92), config.THEME["welcome_title"].upper(), font=font(FONT_BOLD, 30), fill=(*ACCENT2, 255))
    d.text((x + 2, 134), nm, font=big, fill=(0, 0, 0, 160))
    d.text((x, 130), nm, font=big, fill=(255, 255, 255, 255))
    d.text((x, 215), config.THEME["welcome_subtitle"].replace("{server}", server), font=font(FONT_REG, 30), fill=(210, 205, 240, 255))
    tag = f"УЧАСТНИК #{number}"
    tf = font(FONT_BOLD, 26)
    tw = d.textlength(tag, font=tf)
    d.rounded_rectangle((x, 272, x + tw + 36, 318), radius=23, fill=(*ACCENT, 230))
    d.text((x + 18, 278), tag, font=tf, fill=(255, 255, 255, 255))

    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()


async def next_number(guild: discord.Guild) -> int:
    """Номер новичка: 1, 2, 3… — только растёт, ушедшие не освобождают номер."""
    number = int(await db.get_setting(guild.id, "join_counter", "0")) + 1
    await db.set_setting(guild.id, "join_counter", str(number))
    return number


async def make_card(member: discord.Member, number: int) -> discord.File:
    avatar = await member.display_avatar.replace(size=256, format="png").read()
    data = await asyncio.to_thread(render, avatar, member.display_name, number, member.guild.name)
    return discord.File(io.BytesIO(data), filename="welcome.png")


class WelcomeCard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot or config.is_ghost(member):
            return
        channel = discord.utils.get(member.guild.text_channels, name=config.CH_JOINS)
        if not channel:
            return
        await channel.send(f"Привет, {member.mention}! Рады видеть тебя на сервере **{member.guild.name}** 🎉",
                           file=await make_card(member, await next_number(member.guild)))

    @app_commands.command(name="welcome-test", description="Показать карточку приветствия на себе")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def welcome_test(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        number = int(await db.get_setting(interaction.guild.id, "join_counter", "0")) + 1
        await interaction.followup.send(f"Так будет выглядеть приветствие (следующий номер — {number}):",
                                        file=await make_card(interaction.user, number), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCard(bot))
