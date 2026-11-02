"""🚗 Автопарк и контракты семьи (Секта): один канал, два раздела.
Автопарк: транспорт по типам (машины, вертолёты, мотоциклы, лодки — типы можно добавлять свои). У каждой единицы
видно, свободна ли она и кто взял. «Взять» — за тобой, «вернуть» — снова свободна. Ведётся история: кто, когда взял
и когда вернул.
Контракты: взять, отметить выполненным, открыть заново — тоже с историей.
Добавляют, берут и возвращают все из семьи. Кнопки работают после перезапуска; выбор типа/машины — личное окошко."""
import json
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

import config
import db

log = logging.getLogger(__name__)
CHANNELS = {"transport": "🚗・автопарк", "contracts": "🎯・контракты"}
COLOUR = discord.Colour.from_rgb(*config.ACCENT)
DEFAULT_TYPES = [{"name": "Машины", "emoji": "🚗"}, {"name": "Вертолёты", "emoji": "🚁"},
                 {"name": "Мотоциклы", "emoji": "🏍️"}, {"name": "Лодки", "emoji": "🚤"}]


def in_family(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    names = {config.ROLE_FAMILY_MEMBER, config.ROLE_FAMILY_PROBATION, *(n for n, *_ in config.FAMILY_ROLES)}
    return any(r.name in names for r in member.roles)


async def get_types(guild_id: int) -> list[dict]:
    raw = await db.get_setting(guild_id, "garage_types")
    try:
        types = json.loads(raw) if raw else None
    except ValueError:
        types = None
    return types or DEFAULT_TYPES


async def add_type(guild_id: int, name: str, emoji: str = "🚗"):
    types = await get_types(guild_id)
    if not any(t["name"].lower() == name.lower() for t in types):
        types.append({"name": name[:30], "emoji": emoji})
        await db.set_setting(guild_id, "garage_types", json.dumps(types, ensure_ascii=False))


def type_emoji(types: list[dict], name: str) -> str:
    return next((t["emoji"] for t in types if t["name"] == name), "🚗")


async def transport(guild_id: int, vtype: str | None = None) -> list[dict]:
    q = "SELECT id, vtype, name, note, taken_by, taken_at FROM fleet WHERE guild_id=? AND kind='transport'"
    args = [guild_id]
    if vtype:
        q += " AND vtype=?"
        args.append(vtype)
    rows = await db.fetchall(q + " ORDER BY vtype, id", args)
    keys = ("id", "vtype", "name", "note", "taken_by", "taken_at")
    return [dict(zip(keys, r)) for r in rows]


async def contracts(guild_id: int) -> list[dict]:
    rows = await db.fetchall("SELECT id, name, note, taken_by, taken_at, done FROM fleet "
                             "WHERE guild_id=? AND kind='contract' ORDER BY done, id", (guild_id,))
    return [dict(zip(("id", "name", "note", "taken_by", "taken_at", "done"), r)) for r in rows]


# ---------- история ----------
async def log_take(guild_id: int, item: dict, kind: str, user_id: int):
    await db.execute("INSERT INTO fleet_log (guild_id, item_id, item_name, vtype, kind, user_id, took_at) "
                     "VALUES (?,?,?,?,?,?,?)",
                     (guild_id, item["id"], item["name"], item.get("vtype"), kind, user_id, int(time.time())))


async def log_return(guild_id: int, item_id: int):
    await db.execute("UPDATE fleet_log SET returned_at=? WHERE item_id=? AND returned_at IS NULL",
                     (int(time.time()), item_id))


async def history(guild_id: int, kind: str, limit: int = 15) -> list[dict]:
    rows = await db.fetchall("SELECT item_name, vtype, user_id, took_at, returned_at FROM fleet_log "
                             "WHERE guild_id=? AND kind=? ORDER BY id DESC LIMIT ?", (guild_id, kind, limit))
    return [dict(zip(("name", "vtype", "user_id", "took_at", "returned_at"), r)) for r in rows]


# ---------- панель автопарка ----------
async def transport_embed(guild: discord.Guild) -> discord.Embed:
    types = await get_types(guild.id)
    rows = await transport(guild.id)
    e = discord.Embed(title="🚗 Автопарк семьи", colour=COLOUR,
                      description="Жми **🚗 Взять / вернуть** — выбери тип и единицу. **➕ Добавить** — новый транспорт.")
    by = {}
    for r in rows:
        by.setdefault(r["vtype"] or "Другое", []).append(r)
    present = {t["name"] for t in types} | set(by)
    lines = []
    for name in [t["name"] for t in types] + [n for n in by if n not in {t["name"] for t in types}]:
        if name not in present:
            continue
        group = by.get(name, [])
        free = sum(1 for r in group if not r["taken_by"])
        lines.append(f"{type_emoji(types, name)} **{name}** — {len(group)} (свободно {free})")
    e.add_field(name="По типам", value="\n".join(lines) or "Пока пусто", inline=False)
    taken = [r for r in rows if r["taken_by"]]
    if taken:
        e.add_field(name="🔴 Сейчас на руках",
                    value="\n".join(f"{type_emoji(types, r['vtype'])} {r['name']} — <@{r['taken_by']}> "
                                    f"<t:{r['taken_at']}:R>" for r in taken[:15])[:1024], inline=False)
    e.set_footer(text=f"Всего единиц: {len(rows)}")
    return e


class TransportPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if in_family(interaction.user):
            return True
        await interaction.response.send_message("Это для участников семьи 🙂", ephemeral=True, delete_after=15)
        return False

    @discord.ui.button(label="Взять / вернуть", emoji="🚗", style=discord.ButtonStyle.success, custom_id="g2:take")
    async def take(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("Выбери тип транспорта:", view=await TakeFlow.start(interaction.guild),
                                                ephemeral=True, delete_after=180)

    @discord.ui.button(label="Добавить", emoji="➕", custom_id="g2:add")
    async def add(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(AddTransportModal(await get_types(interaction.guild.id)))

    @discord.ui.button(label="Убрать", emoji="🗑️", custom_id="g2:del")
    async def remove(self, interaction: discord.Interaction, _):
        rows = await transport(interaction.guild.id)
        if not rows:
            return await interaction.response.send_message("Список пуст", ephemeral=True, delete_after=15)
        await interaction.response.send_message("Что убрать?", view=RemoveView(rows), ephemeral=True, delete_after=120)

    @discord.ui.button(label="История", emoji="📜", custom_id="g2:hist")
    async def hist(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(embed=await history_embed(interaction.guild, "transport"),
                                                ephemeral=True, delete_after=120)


class TakeFlow(discord.ui.View):
    """Личное окошко: выбор типа → выбор единицы → взять/вернуть."""

    def __init__(self):
        super().__init__(timeout=180)

    @classmethod
    async def start(cls, guild: discord.Guild) -> "TakeFlow":
        v = cls()
        types = await get_types(guild.id)
        rows = await transport(guild.id)
        have = {r["vtype"] for r in rows}
        opts = [discord.SelectOption(label=t["name"], emoji=t["emoji"]) for t in types if t["name"] in have]
        v.vtype.options = opts or [discord.SelectOption(label="Пока нет транспорта — сначала «➕ Добавить»", value="-")]
        v.vtype.disabled = not opts
        v.remove_item(v.item)
        return v

    @discord.ui.select(placeholder="Тип транспорта", options=[discord.SelectOption(label="-")], row=0)
    async def vtype(self, interaction: discord.Interaction, select):
        if select.values[0] == "-":
            return await interaction.response.defer()
        rows = await transport(interaction.guild.id, select.values[0])
        types = await get_types(interaction.guild.id)
        self.item.options = [discord.SelectOption(
            label=r["name"][:100], value=str(r["id"]),
            description=("свободна" if not r["taken_by"] else "занята")[:100],
            emoji="🟢" if not r["taken_by"] else "🔴") for r in rows[:25]]
        self.item.placeholder = f"{type_emoji(types, select.values[0])} Выбери единицу"
        if self.item not in self.children:
            self.add_item(self.item)
        await interaction.response.edit_message(content=f"Тип: **{select.values[0]}**. Теперь выбери единицу:", view=self)

    @discord.ui.select(placeholder="Выбери единицу", options=[discord.SelectOption(label="-")], row=1)
    async def item(self, interaction: discord.Interaction, select):
        row = await db.fetchone("SELECT id, vtype, name, taken_by FROM fleet WHERE id=? AND kind='transport'",
                                (int(select.values[0]),))
        if not row:
            return await interaction.response.edit_message(content="Эта единица удалена", view=None)
        fid, vtype, name, taken_by = row
        if taken_by and taken_by != interaction.user.id:
            return await interaction.response.edit_message(content=f"🚗 **{name}** сейчас у <@{taken_by}>", view=None)
        if taken_by == interaction.user.id:
            await db.execute("UPDATE fleet SET taken_by=NULL, taken_at=NULL WHERE id=?", (fid,))
            await log_return(interaction.guild.id, fid)
            text = f"↩️ Ты вернул **{name}** — снова свободна"
        else:
            await db.execute("UPDATE fleet SET taken_by=?, taken_at=? WHERE id=?",
                             (interaction.user.id, int(time.time()), fid))
            await log_take(interaction.guild.id, {"id": fid, "name": name, "vtype": vtype}, "transport",
                           interaction.user.id)
            text = f"🚗 Ты взял **{name}**"
        await interaction.response.edit_message(content=text, view=None)
        await update_panels(interaction.guild)


class AddTransportModal(discord.ui.Modal, title="➕ Добавить транспорт"):
    def __init__(self, types: list[dict]):
        super().__init__()
        self.vtype = discord.ui.Select(options=[discord.SelectOption(label=t["name"], emoji=t["emoji"]) for t in types]
                                       + [discord.SelectOption(label="➕ Новый тип (впиши ниже)", value="__new__",
                                                               emoji="✨")])
        self.add_item(discord.ui.Label(text="Тип", component=self.vtype))
        self.name = discord.ui.TextInput(label="Название", placeholder="Например: BMW M5", max_length=100)
        self.add_item(self.name)
        self.note = discord.ui.TextInput(label="Номер / заметка", required=False, max_length=100,
                                         placeholder="Номер, цвет — необязательно")
        self.add_item(self.note)
        self.newtype = discord.ui.TextInput(label="Новый тип (если выбрал «Новый тип»)", required=False, max_length=30,
                                            placeholder="Например: Самолёты")
        self.add_item(self.newtype)

    async def on_submit(self, interaction: discord.Interaction):
        chosen = (self.vtype.values or ["Машины"])[0]
        if chosen == "__new__":
            chosen = self.newtype.value.strip() or "Другое"
            await add_type(interaction.guild.id, chosen)
        await db.execute("INSERT INTO fleet (guild_id, kind, vtype, name, note, created_at) VALUES (?,?,?,?,?,?)",
                         (interaction.guild.id, "transport", chosen[:30], self.name.value.strip()[:100],
                          self.note.value.strip()[:100] or None, int(time.time())))
        await interaction.response.send_message(f"✅ Добавил: **{self.name.value.strip()}** ({chosen})", ephemeral=True,
                                                delete_after=15)
        await update_panels(interaction.guild)


# ---------- панель контрактов ----------
async def contracts_embed(guild: discord.Guild) -> discord.Embed:
    rows = await contracts(guild.id)
    e = discord.Embed(title="🎯 Контракты семьи", colour=COLOUR,
                      description="Жми **🎯 Взять / выполнить** — выбери контракт. **➕ Добавить** — новый.")
    for r in rows[:20]:
        note = f" · {r['note']}" if r["note"] else ""
        if r["done"]:
            status = f"✅ выполнил <@{r['taken_by']}>" if r["taken_by"] else "✅ выполнен"
        elif r["taken_by"]:
            status = f"🔴 взял <@{r['taken_by']}> <t:{r['taken_at']}:R>"
        else:
            status = "🟢 свободен"
        e.add_field(name=f"🎯 {r['name']}{note}", value=status, inline=False)
    free = sum(1 for r in rows if not r["taken_by"] and not r["done"])
    done = sum(1 for r in rows if r["done"])
    e.set_footer(text=f"Всего: {len(rows)} · свободно: {free} · выполнено: {done}")
    return e


class ContractsPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if in_family(interaction.user):
            return True
        await interaction.response.send_message("Это для участников семьи 🙂", ephemeral=True, delete_after=15)
        return False

    @discord.ui.select(placeholder="🎯 Взять, выполнить или открыть контракт", custom_id="g2:contract",
                       options=[discord.SelectOption(label="-")])
    async def toggle(self, interaction: discord.Interaction, select):
        if select.values[0] == "none":
            return await interaction.response.defer()
        row = await db.fetchone("SELECT id, name, taken_by, done FROM fleet WHERE id=? AND kind='contract'",
                                (int(select.values[0]),))
        if not row:
            return await interaction.response.send_message("Контракт удалён", ephemeral=True, delete_after=15)
        fid, name, taken_by, done = row
        uid = interaction.user.id
        if done:
            await db.execute("UPDATE fleet SET done=0, taken_by=NULL, taken_at=NULL WHERE id=?", (fid,))
            msg = f"🔄 Контракт **{name}** снова открыт"
        elif not taken_by:
            await db.execute("UPDATE fleet SET taken_by=?, taken_at=? WHERE id=?", (uid, int(time.time()), fid))
            await log_take(interaction.guild.id, {"id": fid, "name": name}, "contract", uid)
            msg = f"🎯 Ты взял контракт **{name}**"
        elif taken_by == uid:
            await db.execute("UPDATE fleet SET done=1 WHERE id=?", (fid,))
            await log_return(interaction.guild.id, fid)
            msg = f"✅ Контракт **{name}** выполнен!"
        else:
            return await interaction.response.send_message(f"🎯 **{name}** взял <@{taken_by}>", ephemeral=True,
                                                           delete_after=20)
        await interaction.response.send_message(msg, ephemeral=True, delete_after=20)
        await update_panels(interaction.guild)

    @discord.ui.button(label="Добавить контракт", emoji="➕", style=discord.ButtonStyle.success, custom_id="g2:c:add")
    async def add(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(AddContractModal())

    @discord.ui.button(label="Убрать", emoji="🗑️", custom_id="g2:c:del")
    async def remove(self, interaction: discord.Interaction, _):
        rows = await contracts(interaction.guild.id)
        if not rows:
            return await interaction.response.send_message("Список пуст", ephemeral=True, delete_after=15)
        await interaction.response.send_message("Что убрать?", view=RemoveView(rows), ephemeral=True, delete_after=120)

    @discord.ui.button(label="История", emoji="📜", custom_id="g2:c:hist")
    async def hist(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(embed=await history_embed(interaction.guild, "contract"),
                                                ephemeral=True, delete_after=120)


class AddContractModal(discord.ui.Modal, title="➕ Добавить контракт"):
    name = discord.ui.TextInput(label="Контракт", placeholder="Например: Перевозка груза в порт", max_length=100)
    note = discord.ui.TextInput(label="Награда / заметка", required=False, max_length=100,
                                placeholder="Например: 50 000$")

    async def on_submit(self, interaction: discord.Interaction):
        await db.execute("INSERT INTO fleet (guild_id, kind, name, note, created_at) VALUES (?,?,?,?,?)",
                         (interaction.guild.id, "contract", self.name.value.strip()[:100],
                          self.note.value.strip()[:100] or None, int(time.time())))
        await interaction.response.send_message(f"✅ Добавил контракт: **{self.name.value.strip()}**", ephemeral=True,
                                                delete_after=15)
        await update_panels(interaction.guild)


# ---------- убрать и история (общее) ----------
class RemoveView(discord.ui.View):
    def __init__(self, rows: list[dict]):
        super().__init__(timeout=120)
        self.pick.options = [discord.SelectOption(label=r["name"][:100], value=str(r["id"]),
                                                  description=(r.get("vtype") or "")[:100] or None) for r in rows[:25]]
        self.pick.max_values = min(25, len(rows))

    @discord.ui.select(placeholder="Выбери, что убрать (можно несколько)")
    async def pick(self, interaction: discord.Interaction, select):
        for v in select.values:
            await db.execute("DELETE FROM fleet WHERE id=? AND guild_id=?", (int(v), interaction.guild.id))
        await interaction.response.edit_message(content=f"🗑️ Убрал: {len(select.values)} шт.", view=None)
        await update_panels(interaction.guild)


async def history_embed(guild: discord.Guild, kind: str) -> discord.Embed:
    types = await get_types(guild.id)
    rows = await history(guild.id, kind)
    title = "📜 История автопарка" if kind == "transport" else "📜 История контрактов"
    e = discord.Embed(title=title, colour=COLOUR)
    lines = []
    for r in rows:
        emoji = type_emoji(types, r["vtype"]) if kind == "transport" else "🎯"
        took = f"<t:{r['took_at']}:f>"
        if r["returned_at"]:
            tail = f"вернул <t:{r['returned_at']}:f>" if kind == "transport" else f"выполнил <t:{r['returned_at']}:f>"
        else:
            tail = "ещё у него" if kind == "transport" else "в работе"
        lines.append(f"{emoji} **{r['name']}** — <@{r['user_id']}>\n　взял {took} · {tail}")
    e.description = "\n".join(lines) or "Пока пусто."
    return e


# ---------- канал и панели ----------
async def channel_for(guild: discord.Guild, which: str) -> discord.TextChannel | None:
    """which: 'transport' — канал автопарка, 'contracts' — канал контрактов (каждый свой)."""
    name = CHANNELS[which]
    key = f"garage_{which}_channel"
    cid = await db.get_setting(guild.id, key)
    ch = guild.get_channel(int(cid)) if cid else None
    ch = ch or discord.utils.get(guild.text_channels, name=name)
    if ch is None:
        category = (discord.utils.find(lambda c: "Секта" in c.name, guild.categories)
                    or discord.utils.find(lambda c: config.CAT_FAMILY in c.name, guild.categories))
        if category is None:
            return None
        topic = ("Транспорт семьи — бери, возвращай, веди историю" if which == "transport"
                 else "Контракты семьи — бери, отмечай выполненными, веди историю")
        ch = await category.create_text_channel(name, reason="Автопарк/контракты семьи", topic=topic)
    if str(ch.id) != cid:
        await db.set_setting(guild.id, key, str(ch.id))
    return ch


def contracts_panel_view(rows: list[dict]) -> "ContractsPanel":
    cv = ContractsPanel()
    cv.toggle.options = [discord.SelectOption(
        label=r["name"][:100], value=str(r["id"]),
        description=("выполнен" if r["done"] else "занят" if r["taken_by"] else "свободен"),
        emoji="✅" if r["done"] else ("🔴" if r["taken_by"] else "🟢")) for r in rows[:25]] \
        or [discord.SelectOption(label="Пока нет контрактов — добавь первый", value="none")]
    cv.toggle.disabled = not rows
    return cv


async def update_panels(guild: discord.Guild):
    tch = await channel_for(guild, "transport")
    cch = await channel_for(guild, "contracts")
    plan = [(tch, "garage_transport_msg", await transport_embed(guild), TransportPanel()),
            (cch, "garage_contracts_msg", await contracts_embed(guild),
             contracts_panel_view(await contracts(guild.id)))]
    for ch, key, embed, view in plan:
        if not ch:
            continue
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
        bot.add_view(TransportPanel())
        bot.add_view(ContractsPanel())

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                if discord.utils.find(lambda c: "Секта" in c.name or config.CAT_FAMILY in c.name, guild.categories):
                    await update_panels(guild)
            except discord.HTTPException:
                log.exception("Автопарк: не получилось выложить панели")

    @app_commands.command(name="garage", description="Открыть/обновить панели автопарка и контрактов")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def garage(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await update_panels(interaction.guild)
        tch = await channel_for(interaction.guild, "transport")
        await interaction.followup.send(f"✅ Готово: {tch.mention} и канал контрактов" if tch
                                        else "⚠️ Нет категории семьи/секты", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Garage(bot))
