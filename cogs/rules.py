"""Правила сервера в #📜・правила. Текст — в rules.json (свои) или rules.example.json (по умолчанию).
После правки — /rules или кнопка в Мастере настройки, бот перевыложит."""
import json
import os

import discord
from discord import app_commands
from discord.ext import commands

import config
import utils

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_rules() -> dict:
    for name in ("rules.json", "rules.example.json"):
        path = os.path.join(ROOT, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig") as f:
                return json.load(f)
    raise FileNotFoundError("Нет rules.json и rules.example.json")


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def build_embeds(guild: discord.Guild) -> list[discord.Embed]:
    data = load_rules()
    welcome = discord.utils.get(guild.text_channels, name=config.CH_WELCOME)
    girls = discord.utils.get(guild.text_channels, name=config.CH_GIRLS)
    boys = discord.utils.get(guild.text_channels, name=config.CH_BOYS)
    values = SafeDict(server=config.SERVER_NAME, games=", ".join(g["name"] for g in config.GAMES),
                      welcome=welcome.mention if welcome else config.CH_WELCOME,
                      girls=girls.mention if girls else config.CH_GIRLS, boys=boys.mention if boys else config.CH_BOYS)

    def fill(text: str) -> str:
        return text.format_map(values)

    embeds = [discord.Embed(title=fill(data["title"]), description=fill(data["intro"]), colour=discord.Colour.gold())]
    for section in data["sections"]:
        if section.get("adult") and not config.enabled("adult_channels"):
            continue
        title = fill(section["title"])
        num = title.split()[1].rstrip(".") if len(title.split()) > 1 else str(len(embeds))
        text = "\n".join(f"**{num}.{i}** {fill(item)}" for i, item in enumerate(section["items"], 1))
        embeds.append(discord.Embed(title=title, description=text[:4096], colour=config.colour(section["colour"])))
    last = discord.Embed(title="⚖️ Наказания", description=fill(data["punishments"]), colour=discord.Colour.dark_red())
    last.set_footer(text=fill(data["footer"]))
    embeds.append(last)
    return embeds[:10]  # Discord: не больше 10 карточек в сообщении


async def post_rules(bot: commands.Bot, channel: discord.TextChannel):
    async for msg in channel.history(limit=30):
        if msg.author == bot.user:
            await msg.delete()
    await channel.send(embeds=build_embeds(channel.guild))


class Rules(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="rules", description="Перевыложить правила в канал правил")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def rules(self, interaction: discord.Interaction):
        channel = utils.rules_channel(interaction.guild)
        if not channel:
            return await interaction.response.send_message("Канал правил не найден — запусти /setup", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await post_rules(self.bot, channel)
        await interaction.followup.send(f"✅ Правила опубликованы в {channel.mention}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Rules(bot))
