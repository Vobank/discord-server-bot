"""Наказания для админ-панели и mini-панели: причины по пунктам правил, ЛС нарушителю,
история в базе, авто-тайм-аут за каждые 3 предупреждения."""
import datetime
import time

import discord

import db

REASONS = [
    ("1.1", "Оскорбления, травля, провокации"),
    ("1.2", "Дискриминация"),
    ("1.3", "Политика / религиозные споры"),
    ("1.4", "Выдаёт себя за другого"),
    ("2.1", "Не по теме канала"),
    ("2.2", "Спам, флуд, капс"),
    ("2.3", "Пинги без причины"),
    ("2.4", "Реклама без разрешения"),
    ("2.5", "Вредоносные / фишинговые ссылки"),
    ("3.1", "NSFW / шок-контент"),
    ("3.2", "Слив личных данных"),
    ("3.3", "Читы, взломы"),
    ("4.1", "Шум / саундпад в голосовом"),
    ("6.1", "Недопустимый ник или аватар"),
    ("6.2", "Обход наказания (твинк)"),
]
OTHER = "other"
ACTIONS = {"warn": ("⚠️", "Предупреждение"), "timeout": ("⏳", "Тайм-аут"), "kick": ("👢", "Кик"), "ban": ("🔨", "Бан")}
WARN_LIMIT = 3          # каждые 3 предупреждения -> авто-тайм-аут
WARN_TIMEOUT = 86400    # на 1 день
COLOURS = {"warn": discord.Colour.yellow(), "timeout": discord.Colour.orange(),
           "kick": discord.Colour.red(), "ban": discord.Colour.dark_red()}


def reason_options() -> list[discord.SelectOption]:
    opts = [discord.SelectOption(label=f"п. {num} — {text}"[:100], value=num) for num, text in REASONS]
    opts.append(discord.SelectOption(label="Другое — написать самому", value=OTHER, emoji="✍️"))
    return opts


def reason_text(value: str) -> str:
    return next((f"п. {num} правил — {text}" for num, text in REASONS if num == value), value)


async def count_warns(guild_id: int, user_id: int) -> int:
    (n,) = await db.fetchone("SELECT COUNT(*) FROM punishments WHERE guild_id=? AND user_id=? AND action='warn'",
                             (guild_id, user_id))
    return n


async def notify(target: discord.Member, action: str, reason: str, extra: str = ""):
    emoji, name = ACTIONS[action]
    embed = discord.Embed(title=f"{emoji} {name} на сервере {target.guild.name}",
                          description=f"**Причина:** {reason}{extra}\n\nПравила: перечитай канал 📜・правила.",
                          colour=COLOURS[action])
    try:
        await target.send(embed=embed)
    except discord.HTTPException:
        pass  # ЛС закрыты


async def apply(interaction: discord.Interaction, action: str, target: discord.Member, reason: str,
                seconds: int = 0, duration_name: str = "", dept: str | None = None) -> str:
    """Выполнить наказание. Возвращает текст для модератора."""
    from cogs.admin_panel import log_action
    g, mod = interaction.guild, interaction.user
    full = f"{reason} | {mod}"
    extra = ""
    try:
        if action == "warn":
            await db.execute("INSERT INTO punishments (guild_id, user_id, moderator_id, action, reason, dept, "
                             "created_at) VALUES (?,?,?,?,?,?,?)", (g.id, target.id, mod.id, action, reason, dept,
                                                                     int(time.time())))
            n = await count_warns(g.id, target.id)
            what = f"⚠️ предупреждение (**{n}-е**)"
            if n % WARN_LIMIT == 0:
                await target.timeout(datetime.timedelta(seconds=WARN_TIMEOUT), reason=f"{WARN_LIMIT} предупреждения")
                what += f" → ⏳ авто-тайм-аут на 1 день за {WARN_LIMIT} предупреждения"
                extra = f"\n\nЭто твоё {n}-е предупреждение — выдан тайм-аут на 1 день."
            else:
                extra = f"\n\nЭто твоё {n}-е предупреждение. Каждое {WARN_LIMIT}-е — тайм-аут на 1 день."
            await notify(target, action, reason, extra)
            return await _done(g, mod, target, what, reason, dept, log_action)

        if action == "timeout":
            if seconds:
                await notify(target, action, reason, f"\n**Срок:** {duration_name}")
                await target.timeout(datetime.timedelta(seconds=seconds), reason=full)
                what = f"⏳ тайм-аут на **{duration_name}**"
            else:
                await target.timeout(None, reason=full)
                return await _done(g, mod, target, "✅ снят тайм-аут", reason, dept, log_action, record=False)
        elif action == "kick":
            await notify(target, action, reason)
            await target.kick(reason=full)
            what = "👢 кикнут"
        else:
            await notify(target, action, reason)
            await target.ban(reason=full, delete_message_seconds=0)
            what = "🔨 забанен"
    except discord.Forbidden:
        return "⚠️ Боту не хватает прав (его роль ниже роли этого человека)"
    except discord.HTTPException as e:
        return f"⚠️ Не получилось: `{e}`"

    await db.execute("INSERT INTO punishments (guild_id, user_id, moderator_id, action, reason, dept, created_at) "
                     "VALUES (?,?,?,?,?,?,?)", (g.id, target.id, mod.id, action, reason, dept, int(time.time())))
    return await _done(g, mod, target, what, reason, dept, log_action, record=False)


async def _done(g, mod, target, what, reason, dept, log_action, record=False) -> str:
    tag = f"[{dept}] " if dept else ""
    await log_action(g, f"{tag}{mod.mention}: {target.mention} — {what}\nПричина: {reason}")
    return f"Готово: {target.mention} — {what}\nПричина: {reason}"


async def history_embed(guild: discord.Guild, user: discord.abc.User) -> discord.Embed:
    rows = await db.fetchall("SELECT action, reason, moderator_id, dept, created_at FROM punishments "
                             "WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 15", (guild.id, user.id))
    lines = [f"{ACTIONS[a][0]} <t:{ts}:d> — {r}" + (f" [{d}]" if d else "") + f" · <@{m}>"
             for a, r, m, d, ts in rows]
    warns = await count_warns(guild.id, user.id)
    embed = discord.Embed(title=f"📋 Нарушения: {user.display_name}",
                          description="\n".join(lines) or "Чисто — нарушений нет ✅", colour=discord.Colour.dark_red())
    embed.set_footer(text=f"Предупреждений всего: {warns}")
    return embed


# ---------- Общее меню наказания ----------
class OtherReasonModal(discord.ui.Modal, title="✍️ Причина"):
    reason = discord.ui.TextInput(label="Опиши нарушение", placeholder="Например: оскорбил в голосовом",
                                  max_length=300)

    def __init__(self, flow: "PunishFlow"):
        super().__init__()
        self.flow = flow

    async def on_submit(self, interaction: discord.Interaction):
        await self.flow.execute(interaction, self.reason.value)


class PunishFlow(discord.ui.View):
    """Выбрать человека → срок (для тайм-аута) → причину из правил → применить.
    allowed(interaction) -> bool  — кто может пользоваться меню
    check(interaction, target) -> str|None — почему нельзя наказать этого человека"""

    def __init__(self, action: str, allowed, check, durations=None, dept: str | None = None):
        super().__init__(timeout=600)
        self.action, self.allowed, self.check, self.dept = action, allowed, check, dept
        self.target, self.reason = None, None
        self.durations = durations or []
        if action == "timeout" and self.durations:
            self.duration_name, self.seconds = self.durations[1]
            self.pick_duration.options = [discord.SelectOption(label=n, value=str(s), default=(s == self.seconds))
                                          for n, s in self.durations]
        else:
            self.duration_name, self.seconds = "", 0
            self.remove_item(self.pick_duration)
        emoji, name = ACTIONS[action]
        self.go.label = f"{emoji} {name}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.allowed(interaction)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="👤 Кого? Начни печатать ник для поиска", row=0)
    async def pick_user(self, interaction: discord.Interaction, select):
        u = select.values[0]
        self.target = u if isinstance(u, discord.Member) else interaction.guild.get_member(u.id)
        await interaction.response.defer()

    @discord.ui.select(placeholder="⏱️ На сколько?", options=[discord.SelectOption(label="-")], row=1)
    async def pick_duration(self, interaction: discord.Interaction, select):
        self.seconds = int(select.values[0])
        self.duration_name = next(n for n, s in self.durations if s == self.seconds)
        await interaction.response.defer()

    @discord.ui.select(placeholder="📜 Причина (пункт правил)", options=reason_options(), row=2)
    async def pick_reason(self, interaction: discord.Interaction, select):
        self.reason = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Применить", style=discord.ButtonStyle.danger, row=3)
    async def go(self, interaction: discord.Interaction, _):
        if not self.target:
            return await interaction.response.send_message("Выбери человека 👆", ephemeral=True)
        if not self.reason and not (self.action == "timeout" and self.seconds == 0):
            return await interaction.response.send_message("Выбери причину 👆", ephemeral=True)
        if problem := await self.check(interaction, self.target):
            return await interaction.response.send_message(f"⚠️ {problem}", ephemeral=True)
        if self.reason == OTHER:
            return await interaction.response.send_modal(OtherReasonModal(self))
        await self.execute(interaction, reason_text(self.reason) if self.reason else "снятие тайм-аута")

    async def execute(self, interaction: discord.Interaction, reason: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        text = await apply(interaction, self.action, self.target, reason, self.seconds, self.duration_name, self.dept)
        await interaction.followup.send(text, ephemeral=True)
