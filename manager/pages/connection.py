"""Подключение: ключ бота, сервер, приглашение, проверка разрешений (intents)."""
import tkinter as tk

from .. import state
from .. import widgets as W
from ..theme import px
from .base import Page

PORTAL = "https://discord.com/developers/applications"


class View(Page):
    description = "Ключ бота и сервер, на котором он работает."

    def build(self):
        W.section(self.body, "Бот")
        g = W.Group(self.body)
        row = g.row("Ключ бота", "Developer Portal → ваше приложение → Bot → Reset Token. "
                                 "Ключ даёт полный доступ к боту, никому его не показывайте.", "key")
        self.token = self.bind_entry(row.right, "e:DISCORD_TOKEN", 30, placeholder="Вставьте ключ", secret=True)
        self.token.pack(side="left")
        self.check_btn = W.button(row.right, "Проверить", self.check, "accent")
        self.check_btn.pack(side="left", padx=(px(8), 0))
        row = g.row("Портал разработчика Discord", "Здесь создаётся бот, меняются его имя, аватар и ключ.", "open")
        W.button(row.right, "Открыть", lambda: state.open_url(PORTAL), icon="open").pack(side="left")

        self.result_box = tk.Frame(self.body, bg=W.bg_of(self.body))
        self.result_box.pack(fill="x")

        W.section(self.body, "Сервер")
        g = W.Group(self.body)
        row = g.row("Сервер", "Бот обслуживает один сервер. Список появится после проверки ключа.", "globe")
        current = self.get("e:GUILD_ID") or ""
        options = [(current, f"ID {current}")] if current else [("", "Не выбран")]
        self.guild = self.bind_combo(row.right, "e:GUILD_ID", options, 30)
        self.guild.pack(side="left")
        row = g.row("Пригласить бота на сервер",
                    "Откроется Discord: выберите сервер и подтвердите. Права администратора нужны, чтобы бот "
                    "мог создавать каналы и роли.", "add")
        W.button(row.right, "Пригласить", self.invite, icon="open").pack(side="left")

        W.section(self.body, "Разрешения бота",
                  "Без них бот не видит участников и текст сообщений. Включаются на портале: Bot → "
                  "Privileged Gateway Intents.")
        g = W.Group(self.body)
        row = g.row("Участники сервера", "Server Members Intent", "people")
        self.pill_members = W.Pill(row.right, "Не проверено", "neutral")
        self.pill_members.pack(side="left")
        row = g.row("Содержимое сообщений", "Message Content Intent", "chat")
        self.pill_content = W.Pill(row.right, "Не проверено", "neutral")
        self.pill_content.pack(side="left")
        self.intents_row = g.row("Открыть настройки разрешений", "Откроется страница бота на портале.", "settings")
        W.button(self.intents_row.right, "Открыть", self.open_intents, icon="open").pack(side="left")

        if state.sync_enabled(self.app.store.saved["e"]):
            W.spacer(self.body, 12)
            W.InfoBar(self.body, "info", "Несколько компьютеров",
                      "Ключ и сервер хранятся на каждом ПК отдельно. Если меняете ключ, соберите для остальных ПК "
                      "новый установщик в разделе «Компьютеры».", closable=False).pack(fill="x")
        self.info = getattr(self.app, "discord_info", None)
        if self.info:
            self.show_result(self.info, None)

    def on_show(self):
        if not getattr(self.app, "discord_info", None) and state.token_looks_valid(self.token.get()):
            self.check(quiet=True)

    def check(self, quiet: bool = False):
        token = self.token.get().strip()
        if not state.token_looks_valid(token):
            self._result("error", "Ключ выглядит неполным", "Скопируйте его заново на портале: Bot → Reset Token.")
            return
        self.check_btn.state(["disabled"])
        self.check_btn.configure(text="Проверка…")
        self.app.background(lambda: state.check_token(token), self.show_result)

    def show_result(self, info, error):
        if not self.winfo_exists():
            return
        self.check_btn.state(["!disabled"])
        self.check_btn.configure(text="Проверить")
        if error:
            self._result("error", "Проверка не прошла", str(error))
            return
        self.app.discord_info = self.info = info
        guilds = info["guilds"]
        current = self.get("e:GUILD_ID") or ""
        options = [(g["id"], g["name"]) for g in guilds]
        if current and current not in {g["id"] for g in guilds}:
            options.insert(0, (current, f"ID {current} (бота там нет)"))
        if not options:
            options = [("", "Бот ещё не добавлен ни на один сервер")]
        self.guild.options = options
        self.guild.configure(values=[lbl for _, lbl in options])
        if not current and len(guilds) == 1:
            self.set("e:GUILD_ID", guilds[0]["id"])
            current = guilds[0]["id"]
        self.guild.set_value(current or options[0][0])
        for pill, ok in ((self.pill_members, info["members_intent"]), (self.pill_content, info["content_intent"])):
            pill.set("Включено" if ok else "Выключено", "success" if ok else "error")
        problems = [n for n, ok in (("Server Members Intent", info["members_intent"]),
                                    ("Message Content Intent", info["content_intent"])) if not ok]
        if problems:
            self._result("warning", f"Бот «{info['bot']}» найден, но не хватает разрешений",
                         "Включите на портале: " + ", ".join(problems) + ".")
        elif not guilds:
            self._result("warning", f"Бот «{info['bot']}» найден",
                         "Он ещё не добавлен на сервер. Нажмите «Пригласить», затем снова «Проверить».")
        elif current and current not in {g["id"] for g in guilds}:
            self._result("warning", f"Бот «{info['bot']}» найден", "Выбранного сервера нет в его списке.")
        else:
            self._result("success", "Бот подключён", f"Приложение «{info['bot']}», серверов: {len(guilds)}. "
                                                    "Разрешения в порядке.")

    def _result(self, kind, title, message):
        for child in self.result_box.winfo_children():
            child.destroy()
        W.InfoBar(self.result_box, kind, title, message, closable=False).pack(fill="x", pady=(px(8), 0))

    def invite(self):
        app_id = (self.info or {}).get("app_id") or state.app_id_from_token(self.token.get())
        if not app_id:
            self._result("warning", "Нужен ключ бота", "Вставьте ключ и нажмите «Проверить».")
            return
        state.open_url(state.invite_url(app_id))

    def open_intents(self):
        app_id = (self.info or {}).get("app_id") or state.app_id_from_token(self.token.get())
        state.open_url(f"{PORTAL}/{app_id}/bot" if app_id else PORTAL)
