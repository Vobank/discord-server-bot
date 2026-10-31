"""👻 Невидимки (settings.json → "ghosts": ID через запятую): участники, которых на сервере как будто нет.

Бот для каждого невидимки:
  • запоминает его роли и ник (таблица ghost_backup) и заменяет их одной незаметной ролью с правами
    администратора (без цвета, не выделена в списке) и обычным ником вида «user1234»;
  • не даёт его тегнуть: правило AutoMod блокирует сообщения с его упоминанием
    (администраторов и владельца AutoMod не трогает — они упоминать могут);
  • не считает ему уровни, достижения, статистику и не показывает в топах, итогах недели,
    поздравлениях и счётчике участников (проверки config.is_ghost в других модулях), старые записи стирает.
Боты получают выделенную роль «🤖 Боты» — своя группа в списке участников, внизу, а невидимки
стоят среди людей в группе 👻.
Секретная фраза (settings.json → "ghost_phrase"): написал её Дворецкому в ЛС или в любой канал — этот
аккаунт сразу становится невидимкой. В канале сообщение не появляется (его блокирует то же правило AutoMod),
такие аккаунты хранятся в базе (ghosts_extra) — она общая для всех ПК и сервера.
Убрали ID из списка — на следующей проверке бот вернёт роли и ник как было.
Менять роли и ник бот может, только если его роль стоит выше ролей невидимки — иначе ждёт и пишет в журнал."""
import json
import logging
import re

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


def phrase_match(text: str) -> bool:
    words = re.sub(r"[^\w]+", " ", (text or "").lower()).split()
    return bool(config.GHOST_PHRASE) and " ".join(words) == " ".join(re.sub(r"[^\w]+", " ", config.GHOST_PHRASE).split())


def phrase_regex() -> str | None:
    """Секретная фраза для AutoMod: только она одна в сообщении, регистр и знаки между словами — любые."""
    words = re.sub(r"[^\w]+", " ", config.GHOST_PHRASE).split()
    return r"(?i)^\W*" + r"\W+".join(map(re.escape, words)) + r"\W*$" if words else None


async def extra_ghosts(guild_id: int) -> set[int]:
    """Аккаунты, ставшие невидимками по секретной фразе."""
    try:
        return {int(x) for x in json.loads(await db.get_setting(guild_id, "ghosts_extra", "[]") or "[]")}
    except ValueError:
        return set()


async def sync_automod(guild: discord.Guild):
    """Правило AutoMod: сообщения с упоминанием невидимок и с секретной фразой не отправляются."""
    rules = [r for r in await guild.fetch_automod_rules() if r.name == AUTOMOD_RULE]
    ghosts = sorted(uid for uid in config.GHOSTS if guild.get_member(uid))
    patterns = ([rf"<@!?({'|'.join(map(str, ghosts))})>"] if ghosts else []) + \
        ([p] if (p := phrase_regex()) else [])
    if not patterns:
        for r in rules:
            await r.delete(reason="Невидимок больше нет")
        return
    trigger = discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.keyword, regex_patterns=patterns)
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
    # роли бустера и т.п. снять нельзя; 18+ бот выдаёт сам по полу и возрасту — не спорим с ним по кругу
    keep = [r for r in member.roles if r.managed or r.name in (config.ROLE_GIRLS_18, config.ROLE_BOYS_18)]
    # маскировка: как у обычного участника после анкеты — 👻 и свой пол (♂️/♀️ из сохранённых ролей),
    # тогда в списке участников невидимка стоит среди людей своей группы, а не один
    (saved,) = await db.fetchone("SELECT roles FROM ghost_backup WHERE guild_id=? AND user_id=?", (guild.id, member.id))
    genders = {name for name, *_ in config.GENDERS}
    gender = next((r for rid in filter(None, saved.split(",")) if (r := guild.get_role(int(rid))) and r.name in genders),
                  None)
    camo = [r for r in (discord.utils.get(guild.roles, name=config.ROLE_BASE), gender) if r and r < guild.me.top_role]
    want = [role, *keep, *camo]
    if set(member.roles) - {guild.default_role} != set(want) or member.nick != fake_nick(member.id):
        await member.edit(roles=want, nick=fake_nick(member.id), reason="Невидимка")
    await forget_activity(guild, member.id)
    return ""


async def bots_group(guild: discord.Guild):
    """Все боты — в своей выделенной группе «🤖 Боты» (в самом низу списка, над «В сети»)."""
    role = discord.utils.get(guild.roles, name=config.ROLE_BOTS)
    if role is None:
        role = await guild.create_role(name=config.ROLE_BOTS, hoist=True, mentionable=False,
                                       colour=discord.Colour(0x99AAB5), reason="Группа ботов в списке участников")
        await role.edit(position=1, reason="Группа ботов — ниже всех")
    if role >= guild.me.top_role:
        return
    for member in guild.members:
        if member.bot and role not in member.roles:
            await member.add_roles(role, reason="Группа ботов")


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
        for guild in self.bot.guilds:  # невидимки по секретной фразе — из базы
            config.GHOSTS.update(await extra_ghosts(guild.id))

    async def make_ghost(self, guild: discord.Guild, user_id: int, where: str):
        if user_id not in config.GHOSTS:
            extra = await extra_ghosts(guild.id) | {user_id}
            await db.set_setting(guild.id, "ghosts_extra", json.dumps(sorted(extra)))
            config.GHOSTS.add(user_id)
            log.info("Невидимки: аккаунт %s добавлен по секретной фразе (%s)", user_id, where)
        await self.sync(guild)

    # секретная фраза в ЛС или в канале (у кого есть «Администратор», того AutoMod не останавливает)
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not phrase_match(message.content):
            return
        if message.guild:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            guilds = [message.guild]
        else:
            guilds = [g for g in self.bot.guilds if g.get_member(message.author.id)]
        for guild in guilds:
            await self.make_ghost(guild, message.author.id, "в канале" if message.guild else "в ЛС")
        if not message.guild:
            await message.channel.send("✅ Готово." if guilds else "Сначала зайди на сервер с этого аккаунта.")

    # в канале фразу блокирует AutoMod — сообщение никто не видит, а бот получает его здесь
    @commands.Cog.listener()
    async def on_automod_action(self, execution: discord.AutoModAction):
        if execution.action.type == discord.AutoModRuleActionType.block_message and phrase_match(execution.content):
            await self.make_ghost(execution.guild, execution.user_id, "в канале")

    async def sync(self, guild: discord.Guild):
        await sync_automod(guild)
        await bots_group(guild)
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

    # если невидимка перезашёл на сервер — сразу прячем снова; новый бот — сразу в группу ботов
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if config.is_ghost(member) or member.bot:
            await self.sync(member.guild)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ghosts(bot))
