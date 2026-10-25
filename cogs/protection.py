"""🛡️ Защита: антиспам (флуд, повторы, массовые пинги), антискам-ссылки, тревога при рейде,
предупреждение о свежих аккаунтах. Администрацию, модераторов и mini Admin не трогает.
Всё пишет в #📋・логи; при рейде пингует Главного админа и Главного модератора."""
import datetime
import re
import time
from collections import defaultdict, deque

import discord
from discord.ext import commands

import config

S = config.ANTISPAM
URL_HOST = re.compile(r"https?://([^/\s:?#]+)", re.I)
LEGIT = {"discord.com", "discord.gg", "discordapp.com", "discordapp.net", "discord.media", "discord.new",
         "steamcommunity.com", "steampowered.com", "steamstatic.com"}
LOOKALIKE = re.compile(r"d[il1]sc[o0]r[dt]|st[e3]a?(?:m|rn)c[o0](?:m|rn)m?un[il1]t[yi]|st[e3]amp[o0]wered|nitro|"
                       r"grabify|iplogger|^2no\.co$|^yip\.su$", re.I)


class _ScamDomains:
    """Ссылки на поддельные Discord/Steam (dlscord.gift, steamcommunlty.com…) и логгеры IP."""

    @staticmethod
    def search(text: str) -> bool:
        for host in URL_HOST.findall(text):
            host = host.lower().rstrip(".")
            base = ".".join(host.split(".")[-2:])
            if base not in LEGIT and LOOKALIKE.search(host):
                return True
        return False


SCAM_DOMAINS = _ScamDomains()
SCAM_PHRASES = re.compile(r"(free|бесплатн\w*)\s+(discord\s+)?nitro|nitro\s+(for\s+)?free|"
                          r"steam\s+gift.{0,20}https?://|@everyone.{0,40}https?://", re.I)


def is_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator or member.guild_permissions.manage_messages:
        return True
    return any(r.name in config.MOD_ROLES or r.name.startswith("mini Admin") for r in member.roles)


class Protection(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.recent: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=20))   # (guild, user) -> (time, msg)
        self.joins: dict[int, deque] = defaultdict(lambda: deque(maxlen=50))
        self.raid_alerted: dict[int, float] = {}

    async def log(self, guild: discord.Guild, text: str, ping: bool = False):
        from cogs.admin_panel import log_action
        if ping:
            ch = discord.utils.get(guild.text_channels, name=config.CH_ADMIN_LOG)
            roles = [r for r in guild.roles if r.name in (config.ROLE_HEAD_ADMIN, config.ROLE_HEAD_MOD)]
            if ch and roles:
                await ch.send(" ".join(r.mention for r in roles), allowed_mentions=discord.AllowedMentions(roles=True))
        await log_action(guild, text)

    async def punish(self, member: discord.Member, minutes: int, reason: str, messages: list[discord.Message]):
        for m in messages:
            try:
                await m.delete()
            except discord.HTTPException:
                pass
        try:
            await member.timeout(datetime.timedelta(minutes=minutes), reason=f"Защита: {reason}")
        except discord.HTTPException:
            pass
        try:
            await member.send(f"⏳ На сервере **{member.guild.name}** тебе выдан тайм-аут на {minutes} мин.\n"
                              f"**Причина:** {reason}. Если это ошибка — напиши администрации.")
        except discord.HTTPException:
            pass
        await self.log(member.guild, f"🛡️ {member.mention} — тайм-аут {minutes} мин: **{reason}** "
                                     f"(удалено сообщений: {len(messages)})")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        m = message.author
        if message.guild is None or m.bot or not isinstance(m, discord.Member) or is_staff(m):
            return
        text = message.content or ""

        if SCAM_DOMAINS.search(text) or SCAM_PHRASES.search(text):
            return await self.punish(m, S["scam_timeout_minutes"], "скам/фишинговая ссылка", [message])

        if len({u.id for u in message.mentions if not u.bot}) > S["max_mentions"]:
            return await self.punish(m, S["timeout_minutes"], "массовые упоминания", [message])

        now = time.monotonic()
        history = self.recent[(message.guild.id, m.id)]
        history.append((now, message))
        burst = [msg for t, msg in history if now - t <= S["flood_seconds"]]
        if len(burst) >= S["flood_messages"]:
            history.clear()
            return await self.punish(m, S["timeout_minutes"], "флуд", burst)
        if text.strip():
            same = [msg for t, msg in history
                    if now - t <= S["repeat_seconds"] and (msg.content or "").strip().lower() == text.strip().lower()]
            if len(same) >= S["repeat_messages"]:
                history.clear()
                return await self.punish(m, S["timeout_minutes"], "одинаковые сообщения подряд", same)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        g = member.guild
        age = discord.utils.utcnow() - member.created_at
        if age.days < S["new_account_days"]:
            await self.log(g, f"🆕 {member.mention} — **свежий аккаунт**: создан <t:{int(member.created_at.timestamp())}:R>. "
                              "Возможно, твинк — присмотрись.")
        now = time.monotonic()
        joins = self.joins[g.id]
        joins.append((now, member))
        wave = [mem for t, mem in joins if now - t <= S["raid_seconds"]]
        if len(wave) >= S["raid_joins"] and now - self.raid_alerted.get(g.id, 0) > 600:
            self.raid_alerted[g.id] = now
            names = ", ".join(mem.mention for mem in wave[-15:])
            await self.log(g, f"🚨 **Похоже на рейд:** {len(wave)} входов за {S['raid_seconds']} сек.\n{names}\n"
                              "Новички без анкеты писать не могут. Если это боты — забаньте их через админ-панель "
                              "или включите в настройках сервера повышенный уровень проверки.", ping=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Protection(bot))
