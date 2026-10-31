"""Уровни за сообщения + роли (100 сообщений -> «Писатель» и т.д.)."""
import time

import discord
from discord import app_commands
from discord.ext import commands

import config
import db


def level_of(messages: int) -> int:
    return messages // config.LEVEL_STEP


class Levels(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_counted: dict[tuple[int, int], float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member) \
                or config.is_ghost(message.author):
            return
        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        if now - self.last_counted.get(key, 0) < config.MESSAGE_COOLDOWN:
            return
        self.last_counted[key] = now

        await db.execute(
            "INSERT INTO levels (guild_id, user_id, messages) VALUES (?,?,1) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET messages = messages + 1", key)
        (count,) = await db.fetchone("SELECT messages FROM levels WHERE guild_id=? AND user_id=?", key)

        channel = discord.utils.get(message.guild.text_channels, name=config.CH_LEVELS)
        member = message.author

        if count % config.LEVEL_STEP == 0 and channel:
            await channel.send(f"⬆️ {member.mention} достиг **{level_of(count)} уровня**! ({count} сообщений)")

        for need, role_name in sorted(config.LEVEL_ROLES.items()):
            if count < need:
                break
            role = discord.utils.get(message.guild.roles, name=role_name)
            if role and role not in member.roles:
                await member.add_roles(role, reason=f"{need} сообщений")
                if channel:
                    await channel.send(f"🏅 {member.mention} написал **{need}** сообщений и получил роль **{role_name}**!")

    @app_commands.command(name="rank", description="Твой уровень и количество сообщений")
    @app_commands.guild_only()
    async def rank(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        row = await db.fetchone("SELECT messages FROM levels WHERE guild_id=? AND user_id=?",
                                (interaction.guild.id, member.id))
        count = row[0] if row else 0
        next_role = next(((n, r) for n, r in sorted(config.LEVEL_ROLES.items()) if count < n), None)
        embed = discord.Embed(title=f"📊 {member.display_name}", colour=discord.Colour.gold())
        embed.add_field(name="Уровень", value=str(level_of(count)))
        embed.add_field(name="Сообщений", value=str(count))
        if next_role:
            embed.add_field(name="До следующей роли", value=f"{next_role[0] - count} → **{next_role[1]}**", inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="top", description="Топ-10 по сообщениям")
    @app_commands.guild_only()
    async def top(self, interaction: discord.Interaction):
        rows = await db.fetchall(
            "SELECT user_id, messages FROM levels WHERE guild_id=? ORDER BY messages DESC LIMIT 10",
            (interaction.guild.id,))
        medals = ["🥇", "🥈", "🥉"]
        lines = [f"{medals[i] if i < 3 else f'`{i + 1}.`'} <@{uid}> — {msgs} сообщ. (ур. {level_of(msgs)})"
                 for i, (uid, msgs) in enumerate(rows)]
        embed = discord.Embed(title="🏆 Топ болтунов", description="\n".join(lines) or "Пока пусто",
                              colour=discord.Colour.gold())
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
