"""Кто может пользоваться какой функцией. Настраивается кнопкой «🔐 Доступ» в админ-панели.
Если для функции роли не выбраны — действует правило по умолчанию (default)."""
import discord

import config
import db

STAFF, MOD, EVERYONE = "staff", "mod", "everyone"

# ключ: (название, эмодзи, по умолчанию, админская ли функция — нужен доступ к #админ-панель)
FEATURES = {
    "roles":    ("Выдача/снятие ролей", "🎭", STAFF, True),
    "dept":     ("Назначение mini Admin", "🛡️", STAFF, True),
    "warn":     ("Предупреждение", "⚠️", STAFF, True),
    "timeout":  ("Тайм-аут", "⏳", STAFF, True),
    "kick":     ("Кик", "👢", STAFF, True),
    "ban":      ("Бан", "🔨", STAFF, True),
    "announce": ("Объявления", "📢", STAFF, True),
    "bday":     ("ДР за участника", "🎂", STAFF, True),
    "stats":    ("Статистика", "📊", STAFF, True),
    "history":  ("История нарушений", "📋", STAFF, True),
    "cinema":   ("Настройка кинотеатра", "🎬", STAFF, True),
    "panels":   ("Обновление панелей", "🔄", STAFF, True),
    "modpanel": ("Мод-панель (предупреждения, тайм-ауты)", "🛡️", MOD, False),
    "music":    ("Музыка (/play, /genre, кнопки)", "🎵", EVERYONE, False),
    "rooms":    ("Личные голосовые комнаты", "🔊", EVERYONE, False),
}


def label(feature: str) -> str:
    name, emoji, *_ = FEATURES[feature]
    return f"{emoji} {name}"


def default_text(feature: str) -> str:
    level = FEATURES[feature][2]
    if level == STAFF:
        return f"«{config.ROLE_STAFF}» и главные"
    if level == MOD:
        return f"«{config.ROLE_MOD}», «{config.ROLE_STAFF}» и главные"
    return "все"


async def get_roles(guild_id: int, feature: str) -> list[int]:
    rows = await db.fetchall("SELECT role_id FROM feature_roles WHERE guild_id=? AND feature=?", (guild_id, feature))
    return [r[0] for r in rows]


async def set_roles(guild_id: int, feature: str, role_ids: list[int]):
    await db.execute("DELETE FROM feature_roles WHERE guild_id=? AND feature=?", (guild_id, feature))
    for rid in role_ids:
        await db.execute("INSERT INTO feature_roles (guild_id, feature, role_id) VALUES (?,?,?)",
                         (guild_id, feature, rid))


async def allowed(member: discord.Member, feature: str) -> bool:
    if member.guild_permissions.administrator:
        return True
    role_ids = await get_roles(member.guild.id, feature)
    if role_ids:
        return any(r.id in role_ids for r in member.roles)
    level = FEATURES[feature][2]
    if level == EVERYONE:
        return True
    names = config.MOD_ROLES if level == MOD else config.STAFF_ROLES
    return any(r.name in names for r in member.roles)


async def deny(interaction: discord.Interaction, feature: str) -> bool:
    """True и сообщение об отказе, если нельзя. Использование: if await perms.deny(i, 'kick'): return"""
    if await allowed(interaction.user, feature):
        return False
    await interaction.response.send_message(f"⛔ У тебя нет доступа: **{label(feature)}**", ephemeral=True)
    return True


async def sync_panel_access(guild: discord.Guild):
    """Даёт видеть #админ-панель всем ролям, которым выдана хоть одна админская функция."""
    panel = discord.utils.get(guild.text_channels, name=config.CH_ADMIN_PANEL)
    if not panel:
        return
    wanted = set()
    for key, (*_, is_admin) in FEATURES.items():
        if is_admin:
            wanted.update(await get_roles(guild.id, key))
    staff_ids = {r.id for r in guild.roles if r.name in config.STAFF_ROLES}
    for target, ow in panel.overwrites.items():
        if isinstance(target, discord.Role) and target.id not in staff_ids and not target.is_default() and target.id not in wanted:
            await panel.set_permissions(target, overwrite=None)
    for rid in wanted:
        if (role := guild.get_role(rid)) and not panel.overwrites_for(role).view_channel:
            await panel.set_permissions(role, view_channel=True, send_messages=False, add_reactions=False)
