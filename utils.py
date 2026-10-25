import discord

import config
import db

GENDER_NAMES = {role for role, *_ in config.GENDERS}
DEPT_ROLE_NAMES = {name for g in config.GAMES for name in config.dept_roles(g)}


def find_channel(guild: discord.Guild, name: str, channel_id: int | None = None, kind: str = "text"):
    """Канал по id из настроек (если задан и найден), иначе по названию. kind: text / voice / category."""
    if channel_id and (ch := guild.get_channel(channel_id)):
        return ch
    pool = {"text": guild.text_channels, "voice": guild.voice_channels, "category": guild.categories}[kind]
    return discord.utils.get(pool, name=name)


def main_category(guild: discord.Guild) -> discord.CategoryChannel | None:
    return find_channel(guild, config.CAT_MAIN, config.CAT_MAIN_ID, "category")


def rules_channel(guild: discord.Guild) -> discord.TextChannel | None:
    return find_channel(guild, config.CH_RULES, config.CH_RULES_ID)


def general_channel(guild: discord.Guild) -> discord.TextChannel | None:
    return find_channel(guild, config.CH_GENERAL, config.CH_GENERAL_ID)


def rooms_panel_channel(guild: discord.Guild) -> discord.TextChannel | None:
    return find_channel(guild, config.CH_ROOMS_PANEL, config.CH_ROOMS_PANEL_ID)


def is_pending(member: discord.Member) -> bool:
    return any(r.name == config.ROLE_PENDING for r in member.roles)


async def stashed_roles(member: discord.Member) -> list[discord.Role]:
    """Игровые роли, которые придержаны до конца анкеты."""
    rows = await db.fetchall("SELECT role_id FROM pending_roles WHERE guild_id=? AND user_id=?",
                             (member.guild.id, member.id))
    return [r for (rid,) in rows if (r := member.guild.get_role(rid))]


async def set_stash(member: discord.Member, roles: list[discord.Role]):
    await db.execute("DELETE FROM pending_roles WHERE guild_id=? AND user_id=?", (member.guild.id, member.id))
    for r in roles:
        await db.execute("INSERT OR IGNORE INTO pending_roles (guild_id, user_id, role_id) VALUES (?,?,?)",
                         (member.guild.id, member.id, r.id))


async def has_birthday(member: discord.Member) -> bool:
    row = await db.fetchone(  # год обязателен — без него анкета не засчитывается
        "SELECT 1 FROM birthdays WHERE guild_id=? AND user_id=? AND year IS NOT NULL", (member.guild.id, member.id)
    )
    return row is not None


async def onboarding_status(member: discord.Member) -> str:
    """Что ещё осталось сделать в анкете (пустая строка — всё готово)."""
    todo = []
    if not any(r.name in GENDER_NAMES for r in member.roles):
        todo.append("выбрать пол")
    if not await has_birthday(member) or (
            is_pending(member) and not await db.get_setting(member.guild.id, f"bday_ok:{member.id}")):
        todo.append("указать день рождения")  # новичок вводит дату заново, даже если она осталась с прошлого раза
    # игры засчитываются только после «✅ Подтвердить» в выборе игр (роли от других ботов — не в счёт)
    if is_pending(member) and not await db.get_setting(member.guild.id, f"games_ok:{member.id}"):
        todo.append("выбрать игры (🎮 Выбрать игры → ✅ Подтвердить)")
    elif not is_pending(member) and not any(r.name in {g["role"] for g in config.GAMES} for r in member.roles):
        todo.append("выбрать игры")
    return ", ".join(todo)


async def finish_if_complete(member: discord.Member) -> str:
    """Если анкета заполнена — снимаем 🔒 и выдаём 👻. Возвращает текст для ответа человеку."""
    member = await member.guild.fetch_member(member.id)
    todo = await onboarding_status(member)
    if todo:
        return f"\nОсталось: **{todo}** — после этого откроется весь сервер."
    pending = discord.utils.get(member.guild.roles, name=config.ROLE_PENDING)
    base = discord.utils.get(member.guild.roles, name=config.ROLE_BASE)
    if pending and pending in member.roles:
        try:
            # сначала снимаем 🔒, потом выдаём 👻 и придержанные игры — иначе их снова придержит
            await member.remove_roles(pending, reason="Анкета заполнена")
            give = [r for r in [base, *await stashed_roles(member)] if r and r not in member.roles]
            if give:
                await member.add_roles(*give, reason="Анкета заполнена")
            await set_stash(member, [])
        except discord.Forbidden:
            return "\n⚠️ Анкета заполнена, но боту не хватает прав открыть сервер — сообщи администрации."
        return "\n🎉 **Анкета заполнена — сервер открыт!** Добро пожаловать!"
    return "\n✅ Анкета заполнена."


def fmt_duration(seconds) -> str:
    if not seconds:
        return "🔴 live"
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"
