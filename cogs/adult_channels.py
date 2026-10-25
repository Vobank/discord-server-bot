"""Доступ к #🌸・девочки и #💪・мальчики: роль пола И 18+ по дате рождения.
Бот сам выдаёт/снимает служебные роли «🔞 Девочки 18+» / «🔞 Мальчики 18+» (при смене пола, вводе ДР,
дне рождения и раз в 30 минут). Без указанного года рождения доступа нет."""
import datetime

import discord
from discord.ext import commands, tasks

import config
import db

PAIRS = [("♀️", config.ROLE_GIRLS_18), ("♂️", config.ROLE_BOYS_18)]


async def age_of(member: discord.Member) -> int | None:
    row = await db.fetchone("SELECT day, month, year FROM birthdays WHERE guild_id=? AND user_id=?",
                            (member.guild.id, member.id))
    if not row or not row[2]:
        return None
    day, month, year = row
    today = datetime.datetime.now(config.TIMEZONE).date()
    return today.year - year - ((today.month, today.day) < (month, day))


async def sync_member(member: discord.Member):
    if member.bot or not config.enabled("adult_channels"):
        return
    pending = any(r.name == config.ROLE_PENDING for r in member.roles)
    adult = (await age_of(member) or 0) >= 18
    names = {r.name for r in member.roles}
    for gender, role_name in PAIRS:
        role = discord.utils.get(member.guild.roles, name=role_name)
        if not role or role >= member.guild.me.top_role:
            continue
        want = gender in names and adult and not pending
        try:
            if want and role not in member.roles:
                await member.add_roles(role, reason="Пол + 18 лет по дате рождения")
            elif not want and role in member.roles:
                await member.remove_roles(role, reason="Нет пола/18 лет")
        except discord.HTTPException:
            pass


class AdultChannels(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.loop.start()

    def cog_unload(self):
        self.loop.cancel()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        changed = {r.name for r in before.roles} ^ {r.name for r in after.roles}
        if changed & {"♀️", "♂️", config.ROLE_PENDING}:
            await sync_member(after)

    @tasks.loop(minutes=30)
    async def loop(self):
        for g in self.bot.guilds:
            for m in g.members:
                await sync_member(m)

    @loop.before_loop
    async def before(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(AdultChannels(bot))
