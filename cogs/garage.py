"""🚗 Автопарк и контракты семьи: в канале #🚗・автопарк-и-контракты два раздела.
Любой из семьи добавляет машины и контракты, берёт и возвращает их. Машина/контракт показывает, кто её взял.
Автопарк: «взять» — машина за тобой, «вернуть» — снова свободна.
Контракты: «взять» — за тобой, «выполнить» — отмечается ✅, можно открыть заново."""
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

import config
import db

log = logging.getLogger(__name__)
CHANNEL = "🚗・автопарк-и-контракты"
COLOUR = discord.Colour.from_rgb(*config.ACCENT)
FREE = "🟢 свободна"
FREE_C = "🟢 свободен"


def in_family(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    names = {config.ROLE_FAMILY_MEMBER, config.ROLE_FAMILY_PROBATION, *(n for n, *_ in config.FAMILY_ROLES)}
    return any(r.name in names for r in member.roles)


async def items(guild_id: int, kind: str) -> list[dict]:
    rows = await db.fetchall(
        "SELECT id, name, note, taken_by, taken_at, done FROM fleet WHERE guild_id=? AND kind=? ORDER BY id",
        (guild_id, kind))
    keys = ("id", "name", "note", "taken_by", "taken_at", "done")
    return [dict(zip(keys, r)) for r in rows]


def when(ts: int | None) -> str:
    return f"<t:{ts}:R>" if ts else ""


# ---------- автопарк ----------
def cars_embed(rows: list[dict]) -> discord.Embed:
    e = discord.Embed(title="🚗 Автопарк семьи", colour=COLOUR,
                      description="Нажми на машину в списке — **взять** (если свободна) или **вернуть** (если твоя)."
                      if rows else "Пока ни одной машины. Нажми **➕ Добавить машину**.")
    free = sum(1 for r in rows if not r["taken_by"])
    for r in rows[:25]:
        note = f" · {r['note']}" if r["note"] else ""
        status = FREE if not r["taken_by"] else f"🔴 у <@{r['taken_by']}> {when(r['taken_at'])}"
        e.add_field(name=f"🚗 {r['name']}{note}", value=status, inline=False)
    if len(rows) > 25:
        e.add_field(name="…", value=f"и ещё {len(rows) - 25}", inline=False)
    e.set_footer(text=f"Всего машин: {len(rows)} · свободно: {free}")
    return e


def cars_view(rows: list[dict]) -> "CarsView":
    v = CarsView()
    opts = [discord.SelectOption(
        label=r["name"][:100], value=str(r["id"]),
        description=("свободна" if not r["taken_by"] else "занята")[:100],
        emoji="🟢" if not r["taken_by"] else "🔴") for r in rows[:25]]
    v.toggle.options = opts or [discord.SelectOption(label="Пока нет машин — добавь первую", value="none")]
    v.toggle.disabled = not rows
    return v


class CarsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if in_family(interaction.user):
            return True
        await interaction.response.send_message("Это для участников семьи 🙂", ephemeral=True, delete_after=15)
        return False

    @discord.ui.select(placeholder="🚗 Взять или вернуть машину", custom_id="garage:car",
                       options=[discord.SelectOption(label="-")])
    async def toggle(self, interaction: discord.Interaction, select):
        if select.values[0] == "none":
            return await interaction.response.defer()
        row = await db.fetchone("SELECT name, taken_by FROM fleet WHERE id=? AND kind='car'", (int(select.values[0]),))
        if not row:
            return await interaction.response.send_message("Эта машина уже удалена", ephemeral=True, delete_after=15)
        name, taken_by = row
        if taken_by and taken_by != interaction.user.id:
            return await interaction.response.send_message(f"🚗 **{name}** сейчас у <@{taken_by}>", ephemeral=True,
                                                           delete_after=20)
        if taken_by == interaction.user.id:
            await db.execute("UPDATE fleet SET taken_by=NULL, taken_at=NULL WHERE id=?", (int(select.values[0]),))
            msg = f"↩️ Ты вернул **{name}** — снова свободна"
        else:
            await db.execute("UPDATE fleet SET taken_by=?, taken_at=? WHERE id=?",
                             (interaction.user.id, int(time.time()), int(select.values[0])))
            msg = f"🚗 Ты взял **{name}**"
        await interaction.response.send_message(msg, ephemeral=True, delete_after=20)
        await update_panels(interaction.guild)

    @discord.ui.button(label="Добавить машину", emoji="➕", style=discord.ButtonStyle.success, custom_id="garage:car:add")
    async def add(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(AddModal("car"))

    @discord.ui.button(label="Убрать машину", emoji="🗑️", custom_id="garage:car:del")
    async def remove(self, interaction: discord.Interaction, _):
        await open_remove(interaction, "car")


# ---------- контракты ----------
def contracts_embed(rows: list[dict]) -> discord.Embed:
    e = discord.Embed(title="🎯 Контракты семьи", colour=COLOUR,
                      description="Нажми на контракт — **взять** (если свободен), **выполнить** (если твой) "
                      "или **открыть заново** (если выполнен)." if rows else
                      "Пока нет контрактов. Нажми **➕ Добавить контракт**.")
    for r in rows[:25]:
        note = f" · {r['note']}" if r["note"] else ""
        if r["done"]:
            status = f"✅ выполнил <@{r['taken_by']}>" if r["taken_by"] else "✅ выполнен"
        elif r["taken_by"]:
            status = f"🔴 взял <@{r['taken_by']}> {when(r['taken_at'])}"
        else:
            status = FREE_C
        e.add_field(name=f"🎯 {r['name']}{note}", value=status, inline=False)
    if len(rows) > 25:
        e.add_field(name="…", value=f"и ещё {len(rows) - 25}", inline=False)
    free = sum(1 for r in rows if not r["taken_by"] and not r["done"])
    done = sum(1 for r in rows if r["done"])
    e.set_footer(text=f"Всего: {len(rows)} · свободно: {free} · выполнено: {done}")
    return e


def contracts_view(rows: list[dict]) -> "ContractsView":
    v = ContractsView()
    def mark(r):
        return "✅" if r["done"] else ("🔴" if r["taken_by"] else "🟢")
    opts = [discord.SelectOption(label=r["name"][:100], value=str(r["id"]),
                                 description=("выполнен" if r["done"] else "занят" if r["taken_by"] else "свободен"),
                                 emoji=mark(r)) for r in rows[:25]]
    v.toggle.options = opts or [discord.SelectOption(label="Пока нет контрактов — добавь первый", value="none")]
    v.toggle.disabled = not rows
    return v


class ContractsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if in_family(interaction.user):
            return True
        await interaction.response.send_message("Это для участников семьи 🙂", ephemeral=True, delete_after=15)
        return False

    @discord.ui.select(placeholder="🎯 Взять, выполнить или открыть контракт", custom_id="garage:contract",
                       options=[discord.SelectOption(label="-")])
    async def toggle(self, interaction: discord.Interaction, select):
        if select.values[0] == "none":
            return await interaction.response.defer()
        row = await db.fetchone("SELECT name, taken_by, done FROM fleet WHERE id=? AND kind='contract'",
                                (int(select.values[0]),))
        if not row:
            return await interaction.response.send_message("Этот контракт уже удалён", ephemeral=True, delete_after=15)
        name, taken_by, done = row
        fid = int(select.values[0])
        uid = interaction.user.id
        if done:
            await db.execute("UPDATE fleet SET done=0, taken_by=NULL, taken_at=NULL WHERE id=?", (fid,))
            msg = f"🔄 Контракт **{name}** снова открыт"
        elif not taken_by:
            await db.execute("UPDATE fleet SET taken_by=?, taken_at=? WHERE id=?", (uid, int(time.time()), fid))
            msg = f"🎯 Ты взял контракт **{name}**"
        elif taken_by == uid:
            await db.execute("UPDATE fleet SET done=1 WHERE id=?", (fid,))
            msg = f"✅ Контракт **{name}** выполнен!"
        else:
            return await interaction.response.send_message(f"🎯 Контракт **{name}** взял <@{taken_by}>", ephemeral=True,
                                                           delete_after=20)
        await interaction.response.send_message(msg, ephemeral=True, delete_after=20)
        await update_panels(interaction.guild)

    @discord.ui.button(label="Добавить контракт", emoji="➕", style=discord.ButtonStyle.success,
                       custom_id="garage:contract:add")
    async def add(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(AddModal("contract"))

    @discord.ui.button(label="Убрать контракт", emoji="🗑️", custom_id="garage:contract:del")
    async def remove(self, interaction: discord.Interaction, _):
        await open_remove(interaction, "contract")


# ---------- добавить / убрать ----------
LABELS = {"car": ("машину", "Марка и модель", "Например: BMW M5", "Номер, цвет — необязательно"),
          "contract": ("контракт", "Контракт", "Например: Перевозка груза в порт", "Награда, детали — необязательно")}


class AddModal(discord.ui.Modal):
    def __init__(self, kind: str):
        noun, name_label, name_ph, note_ph = LABELS[kind]
        super().__init__(title=f"➕ Добавить {noun}")
        self.kind = kind
        self.name = discord.ui.TextInput(label=name_label, placeholder=name_ph, max_length=100)
        self.note = discord.ui.TextInput(label="Заметка", placeholder=note_ph, required=False, max_length=100)
        self.add_item(self.name)
        self.add_item(self.note)

    async def on_submit(self, interaction: discord.Interaction):
        await db.execute("INSERT INTO fleet (guild_id, kind, name, note, created_at) VALUES (?,?,?,?,?)",
                         (interaction.guild.id, self.kind, self.name.value.strip()[:100],
                          self.note.value.strip()[:100] or None, int(time.time())))
        await interaction.response.send_message(f"✅ Добавил: **{self.name.value.strip()}**", ephemeral=True,
                                                delete_after=15)
        await update_panels(interaction.guild)


class RemoveView(discord.ui.View):
    def __init__(self, kind: str, rows: list[dict]):
        super().__init__(timeout=180)
        self.kind = kind
        self.pick.options = [discord.SelectOption(label=r["name"][:100], value=str(r["id"])) for r in rows[:25]]
        self.pick.max_values = min(25, len(rows))

    @discord.ui.select(placeholder="Выбери, что убрать (можно несколько)")
    async def pick(self, interaction: discord.Interaction, select):
        for v in select.values:
            await db.execute("DELETE FROM fleet WHERE id=? AND guild_id=?", (int(v), interaction.guild.id))
        await interaction.response.edit_message(content=f"🗑️ Убрал: {len(select.values)} шт.", view=None)
        await update_panels(interaction.guild)


async def open_remove(interaction: discord.Interaction, kind: str):
    rows = await items(interaction.guild.id, kind)
    if not rows:
        return await interaction.response.send_message("Список пуст — убирать нечего", ephemeral=True, delete_after=15)
    await interaction.response.send_message("Что убрать из списка?", view=RemoveView(kind, rows), ephemeral=True)


# ---------- канал и панели ----------
async def channel_of(guild: discord.Guild) -> discord.TextChannel | None:
    cid = await db.get_setting(guild.id, "garage_channel")
    ch = guild.get_channel(int(cid)) if cid else None
    ch = ch or discord.utils.get(guild.text_channels, name=CHANNEL)
    if ch is None:
        category = discord.utils.find(lambda c: config.CAT_FAMILY in c.name, guild.categories)
        if category is None:
            return None
        ch = await category.create_text_channel(CHANNEL, reason="Автопарк и контракты семьи",
                                                topic="Машины и контракты семьи — бери, возвращай, отмечай")
    if str(ch.id) != cid:
        await db.set_setting(guild.id, "garage_channel", str(ch.id))
    return ch


async def update_panels(guild: discord.Guild):
    """Обновить оба сообщения-панели (или создать, если их нет)."""
    ch = await channel_of(guild)
    if not ch:
        return
    cars, contracts = await items(guild.id, "car"), await items(guild.id, "contract")
    plan = [("garage_cars_msg", cars_embed(cars), cars_view(cars)),
            ("garage_contracts_msg", contracts_embed(contracts), contracts_view(contracts))]
    for key, embed, view in plan:
        mid = await db.get_setting(guild.id, key)
        if mid:
            try:
                await (await ch.fetch_message(int(mid))).edit(embed=embed, view=view)
                continue
            except discord.HTTPException:
                pass
        msg = await ch.send(embed=embed, view=view)
        await db.set_setting(guild.id, key, str(msg.id))


class Garage(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(CarsView())
        bot.add_view(ContractsView())

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                if await channel_of(guild):
                    await update_panels(guild)
            except discord.HTTPException:
                log.exception("Автопарк: не получилось выложить панели")

    @app_commands.command(name="garage", description="Открыть/обновить панели автопарка и контрактов")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def garage(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await update_panels(interaction.guild)
        ch = await channel_of(interaction.guild)
        await interaction.followup.send(f"✅ Готово: {ch.mention}" if ch else "⚠️ Нет категории семьи", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Garage(bot))
