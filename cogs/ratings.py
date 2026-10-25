"""#🏆・рейтинги (админка): как получить достижения, у кого какие достижения, топ уровней.
Сообщения бот редактирует раз в 30 минут (и по кнопке «Обновить»)."""
import discord
from discord.ext import commands, tasks

import config
import db
from cogs.levels import level_of

MAX_LINES = 40


def ach_icon(role_name: str) -> str:
    return role_name.split(" ")[0]


def requirements_embed() -> discord.Embed:
    lines = [f"{a['role']} — {a['desc']}" for a in config.ACHIEVEMENTS]
    lines.append(f"{config.ROLE_BIRTHDAY} — в свой день рождения (на 1 день)")
    lvl = [f"**{role}** — {need} сообщений" for need, role in sorted(config.LEVEL_ROLES.items())]
    e = discord.Embed(title="📖 Как получить достижения", description="\n".join(lines), colour=discord.Colour.gold())
    e.add_field(name="💬 Роли за сообщения", value="\n".join(lvl) + f"\nНовый уровень — каждые {config.LEVEL_STEP} "
                                                                     "сообщений (не чаще 1 раза в 3 сек.)",
                inline=False)
    e.set_footer(text="Игроки смотрят свой прогресс командой /achievements")
    return e


def achievements_embed(guild: discord.Guild) -> discord.Embed:
    roles = [r for a in config.ACHIEVEMENTS if (r := discord.utils.get(guild.roles, name=a["role"]))]
    rows = []
    for m in guild.members:
        if m.bot:
            continue
        got = [r for r in roles if r in m.roles]
        if got:
            rows.append((len(got), m, got))
    rows.sort(key=lambda x: (-x[0], x[1].display_name.lower()))
    lines = [f"`{i:>2}.` {m.mention} — **{n}** {' '.join(ach_icon(r.name) for r in got)}"
             for i, (n, m, got) in enumerate(rows[:MAX_LINES], 1)]
    if len(rows) > MAX_LINES:
        lines.append(f"…и ещё {len(rows) - MAX_LINES} чел.")
    counts = " · ".join(f"{ach_icon(r.name)} {len([m for m in r.members if not m.bot])}" for r in roles)
    e = discord.Embed(title="🏆 Достижения — у кого сколько", description="\n".join(lines) or "Пока ни у кого нет",
                      colour=discord.Colour.orange())
    e.add_field(name="Сколько людей с каждым достижением", value=counts or "—", inline=False)
    return e


async def levels_embed(guild: discord.Guild) -> discord.Embed:
    rows = await db.fetchall("SELECT user_id, messages FROM levels WHERE guild_id=? ORDER BY messages DESC LIMIT ?",
                             (guild.id, MAX_LINES))
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [f"{medals.get(i, f'`{i:>2}.`')} <@{uid}> — ур. **{level_of(msgs)}** · {msgs} сообщ."
             for i, (uid, msgs) in enumerate(rows, 1)]
    return discord.Embed(title="📊 Уровни — топ", description="\n".join(lines) or "Пока пусто",
                         colour=discord.Colour.blurple())


class RefreshView(discord.ui.View):
    def __init__(self, cog: "Ratings"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Обновить сейчас", emoji="🔄", custom_id="ratings:refresh")
    async def refresh(self, interaction: discord.Interaction, _):
        await interaction.response.defer(ephemeral=True)
        await self.cog.update(interaction.guild)
        await interaction.followup.send("✅ Обновлено", ephemeral=True)


class Ratings(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(RefreshView(self))
        self.loop.start()

    def cog_unload(self):
        self.loop.cancel()

    async def update(self, guild: discord.Guild):
        channel = discord.utils.get(guild.text_channels, name=config.CH_RATINGS)
        if not channel:
            return
        embeds = [requirements_embed(), achievements_embed(guild), await levels_embed(guild)]
        ids = (await db.get_setting(guild.id, "ratings_msgs") or "").split(",")
        msgs = []
        for mid in ids:
            if mid:
                try:
                    msgs.append(await channel.fetch_message(int(mid)))
                except discord.HTTPException:
                    pass
        if len(msgs) == len(embeds):
            for msg, emb in zip(msgs, embeds):
                await msg.edit(embed=emb, view=RefreshView(self) if msg == msgs[-1] else None)
            return
        async for old in channel.history(limit=30):
            if old.author == self.bot.user:
                await old.delete()
        new = []
        for i, emb in enumerate(embeds):
            new.append(await channel.send(embed=emb, view=RefreshView(self) if i == len(embeds) - 1 else None))
        await db.set_setting(guild.id, "ratings_msgs", ",".join(str(m.id) for m in new))

    @tasks.loop(minutes=30)
    async def loop(self):
        for g in self.bot.guilds:
            await self.update(g)

    @loop.before_loop
    async def before(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Ratings(bot))
