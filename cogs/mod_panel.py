"""Мод-панель в #🛡️・мод-панель: обычный модератор — предупреждения, тайм-аут до 1 дня,
выгнать из голосового, история нарушений. Администрацию, mini Admin и других модераторов трогать нельзя."""
import discord
from discord.ext import commands

import config
import perms
import punish
from cogs.admin_panel import as_member, hint, log_action

MOD_COLOUR = discord.Colour(0x2ECC71)
MOD_DURATIONS = [("10 минут", 600), ("1 час", 3600), ("6 часов", 21600), ("1 день", 86400), ("Снять тайм-аут", 0)]


def is_protected(member: discord.Member) -> bool:
    if member.guild_permissions.administrator or member == member.guild.owner:
        return True
    return any(r.name in config.MOD_ROLES or r.name.startswith("mini Admin") for r in member.roles)


async def allowed(interaction: discord.Interaction) -> bool:
    return not await perms.deny(interaction, "modpanel")


async def check(interaction: discord.Interaction, t: discord.Member) -> str | None:
    if t == interaction.user or is_protected(t):
        return "Администрацию, mini Admin и модераторов наказывает только Администрация"
    if t.top_role >= interaction.guild.me.top_role:
        return "Участник выше бота по ролям"
    return None


def mod_flow(action: str) -> punish.PunishFlow:
    return punish.PunishFlow(action, allowed, check, MOD_DURATIONS, dept="🛡️ Модератор")


class VoiceKickView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await allowed(interaction)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="👤 Кого выгнать из голосового?")
    async def pick(self, interaction: discord.Interaction, select):
        t = as_member(interaction.guild, select.values[0])
        if not t or not t.voice or not t.voice.channel:
            return await interaction.response.send_message("⚠️ Он не сидит в голосовом канале", ephemeral=True)
        if problem := await check(interaction, t):
            return await interaction.response.send_message(f"⚠️ {problem}", ephemeral=True)
        channel = t.voice.channel
        await t.move_to(None, reason=f"Модератор {interaction.user}")
        await interaction.response.send_message(f"🔇 {t.mention} выгнан из {channel.mention}", ephemeral=True)
        await log_action(interaction.guild, f"[🛡️ Модератор] {interaction.user.mention} выгнал {t.mention} "
                                            f"из голосового {channel.mention}")


class HistoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await allowed(interaction)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="👤 Чью историю показать?")
    async def pick(self, interaction: discord.Interaction, select):
        await interaction.response.send_message(embed=await punish.history_embed(interaction.guild, select.values[0]),
                                                ephemeral=True)


HINT = "Выбери человека и причину из правил — нарушитель получит ЛС, всё попадёт в #📋・логи."


class ModPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await allowed(interaction)

    async def open(self, interaction, title, text, view):
        await interaction.response.send_message(embed=hint(title, text), view=view, ephemeral=True)

    @discord.ui.button(label="Предупреждение", emoji="⚠️", style=discord.ButtonStyle.secondary, custom_id="mod:warn")
    async def warn(self, interaction, _):
        await self.open(interaction, "⚠️ Предупреждение",
                        HINT + f"\nКаждое {punish.WARN_LIMIT}-е — авто-тайм-аут на 1 день.", mod_flow("warn"))

    @discord.ui.button(label="Тайм-аут", emoji="⏳", style=discord.ButtonStyle.danger, custom_id="mod:timeout")
    async def timeout_btn(self, interaction, _):
        await self.open(interaction, "⏳ Тайм-аут", "Максимум на 1 день.\n" + HINT, mod_flow("timeout"))

    @discord.ui.button(label="Из голосового", emoji="🔇", style=discord.ButtonStyle.secondary, custom_id="mod:vkick")
    async def voice(self, interaction, _):
        await self.open(interaction, "🔇 Выгнать из голосового", "Отключит человека от голосового канала.",
                        VoiceKickView())

    @discord.ui.button(label="История", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="mod:history")
    async def history(self, interaction, _):
        await self.open(interaction, "📋 История нарушений", "Выбери человека.", HistoryView())


async def post_mod_panel(bot: commands.Bot, channel: discord.TextChannel):
    async for msg in channel.history(limit=30):
        if msg.author == bot.user:
            await msg.delete()
    embed = discord.Embed(
        title="🛡️ Панель модератора",
        description=(
            f"⚠️ **Предупреждение** — каждое {punish.WARN_LIMIT}-е даёт авто-тайм-аут на 1 день\n"
            "⏳ **Тайм-аут** — до 1 дня\n"
            "🔇 **Из голосового** — отключить человека от голосового\n"
            "📋 **История** — все наказания человека\n\n"
            "Причина выбирается из правил, нарушитель получает ЛС.\n"
            "Кик и бан — через Главного модератора или Администрацию.\n"
            "Администрацию, mini Admin и других модераторов модератор наказать не может.\n\n"
            f"Все действия записываются в #{config.CH_ADMIN_LOG}."
        ),
        colour=MOD_COLOUR,
    )
    await channel.send(embed=embed, view=ModPanelView())


class ModPanel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(ModPanelView())


async def setup(bot: commands.Bot):
    await bot.add_cog(ModPanel(bot))
