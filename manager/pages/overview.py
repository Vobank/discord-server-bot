"""Обзор: состояние бота, быстрые действия, первые шаги, компьютеры и последние события."""
import datetime
import time
import tkinter as tk

from .. import state
from .. import widgets as W
from ..theme import C, px
from .base import Page

ONLINE = 150


def uptime(ts: float) -> str:
    if not ts:
        return "—"
    s = max(0, int(time.time() - ts))
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    return f"{d} дн. {h} ч" if d else f"{h} ч {s // 60} мин"


def ago(ts: float) -> str:
    if not ts:
        return "—"
    s = max(0, int(time.time() - ts))
    if s < 60:
        return "только что"
    if s < 3600:
        return f"{s // 60} мин назад"
    if s < 86400:
        return f"{s // 3600} ч назад"
    return f"{s // 86400} дн. назад"


def version_text(v) -> str:
    try:
        v = int(v or 0)
    except (TypeError, ValueError):
        return "—"
    return datetime.datetime.fromtimestamp(v).strftime("%d.%m.%Y %H:%M") if v > 10 ** 9 else "Локальная сборка"


class View(Page):
    description = "Состояние бота и быстрые действия."

    def build(self):
        self.mode = None
        self.steps_sig = None
        self.hosts_sig = None
        self.events_sig = None

        hero = W.Card(self.body, padding=(22, 20))
        hero.pack(fill="x")
        top = tk.Frame(hero.content, bg=C("card"))
        top.pack(fill="x")
        self.dot = W.Dot(top, "idle", 14)
        self.dot.pack(side="left", padx=(0, px(16)))
        text = tk.Frame(top, bg=C("card"))
        text.pack(side="left", fill="x", expand=True)
        self.h_title = W.label(text, "", "subtitle")
        self.h_title.pack(anchor="w")
        self.h_sub = W.label(text, "", "body", "text2")
        self.h_sub.pack(anchor="w", fill="x", pady=(px(4), 0))
        W.autowrap(self.h_sub)
        self.h_buttons = tk.Frame(top, bg=C("card"))
        self.h_buttons.pack(side="right", padx=(px(16), 0))

        grid = tk.Frame(self.body, bg=C("bg"))
        grid.pack(fill="x", pady=(px(8), 0))
        self.metrics = {}
        for i, (key, title) in enumerate((("uptime", "Без перерыва"), ("version", "Версия кода"),
                                           ("backup", "Копия базы"), ("pcs", "Компьютеры"))):
            card = W.Card(grid, padding=(16, 14))
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else px(4), 0))
            grid.columnconfigure(i, weight=1, uniform="metrics")
            W.label(card.content, title, "caption", "text2").pack(anchor="w")
            value = W.label(card.content, "—", "body_large")
            value.pack(anchor="w", pady=(px(4), 0))
            self.metrics[key] = value

        self.steps_box = tk.Frame(self.body, bg=C("bg"))
        self.steps_box.pack(fill="x")
        self.hosts_box = tk.Frame(self.body, bg=C("bg"))
        self.hosts_box.pack(fill="x")

        W.section(self.body, "Последние события")
        g = W.Group(self.body)
        self.events = g.block()
        foot = g.block(padding=(18, 10))
        W.LinkButton(foot, "Открыть журнал", lambda: self.app.goto("logs")).pack(side="left")

        W.section(self.body, "Быстрые действия")
        g = W.Group(self.body)
        row = g.row("Сохранить копию базы", "Внеочередная копия уровней, дней рождения и фильмов.", "save")
        W.button(row.right, "Сохранить", self.backup).pack(side="left")
        row = g.row("Проверить обновления", "Если на другом компьютере опубликовали новую версию, бот поставит её.",
                    "download")
        W.button(row.right, "Проверить", self.check_updates).pack(side="left")
        if state.sync_enabled(self.app.store.saved["e"]):
            row = g.row("Опубликовать обновление", "Отправить текущий код и настройки на остальные компьютеры.",
                        "upload")
            W.button(row.right, "Опубликовать", self.publish).pack(side="left")
        row = g.row("Папка бота", "Файлы бота, настройки и журналы.", "folder")
        W.button(row.right, "Открыть", lambda: state.open_path(state.APP), icon="open").pack(side="left")
        self.on_status(self.app.status)

    # ---------- обновление по статусу ----------
    def on_status(self, st):
        if not self.winfo_exists():
            return
        self._hero(st)
        self._metrics(st)
        self._steps(st)
        self._hosts(st)
        self._events()

    def _hero(self, st):
        if st is None:
            mode, color = "stopped", "idle"
            title, sub = "Бот остановлен", "На этом компьютере бот не запущен."
        elif st.get("state") == "active":
            running = st.get("bot_running")
            mode, color = ("running", "success") if running else ("starting", "warning")
            title = "Бот работает" if running else "Бот запускается"
            sub = "На этом компьютере"
            if running:
                sub += f" · без перерыва {uptime(st.get('bot_started'))}"
            if st.get("pinned") and st.get("pinned") == (st.get("me") or {}).get("id"):
                sub += " · закреплён за этим компьютером"
        else:
            mode, color = "standby", "info"
            title = "Бот работает на другом компьютере"
            other = st.get("active_host")
            sub = (f"Сейчас: «{other}». " if other else "") + "Этот компьютер в резерве."
        self.dot.set(color)
        self.h_title.configure(text=title)
        self.h_sub.configure(text=sub)
        if mode == self.mode:
            return
        self.mode = mode
        for w in self.h_buttons.winfo_children():
            w.destroy()
        if mode == "stopped":
            W.button(self.h_buttons, "Запустить", self.start, "accent", "play").pack(side="left")
        elif mode == "standby":
            W.button(self.h_buttons, "Перезапустить", self.restart, icon="refresh").pack(side="left")
            W.button(self.h_buttons, "Забрать бота сюда", self.take_here, "accent", "pin").pack(
                side="left", padx=(px(8), 0))
        else:
            W.button(self.h_buttons, "Перезапустить", self.restart, icon="refresh").pack(side="left")
            W.button(self.h_buttons, "Остановить", self.stop, icon="stop").pack(side="left", padx=(px(8), 0))

    def _metrics(self, st):
        st = st or {}
        solo = st.get("solo") or not state.sync_enabled(self.app.store.saved["e"])
        running = st.get("state") == "active" and st.get("bot_running")
        self.metrics["uptime"].configure(text=uptime(st.get("bot_started")) if running else "—")
        self.metrics["version"].configure(text=version_text(st.get("version") or state.local_version()))
        if not st:
            backup = "—"
        elif solo:
            backup = "Раз в день на диске"
        else:
            backup = ago(st.get("last_db_upload") or 0)
        self.metrics["backup"].configure(text=backup)
        hosts = st.get("hosts") or []
        if solo or not hosts:
            pcs = "Один компьютер"
        else:
            online = sum(1 for h in hosts if time.time() - h.get("ts", 0) < ONLINE)
            pcs = f"{online} в сети из {len(hosts)}"
        self.metrics["pcs"].configure(text=pcs)

    def _steps(self, st):
        done = {
            "token": state.token_looks_valid(self.saved("e:DISCORD_TOKEN") or ""),
            "guild": bool(self.saved("e:GUILD_ID")),
            "built": bool(self.app.prefs.get("server_built")),
            "running": st is not None,
        }
        sig = tuple(done.values())
        if sig == self.steps_sig:
            return
        self.steps_sig = sig
        for w in self.steps_box.winfo_children():
            w.destroy()
        if all(done.values()):
            return
        W.section(self.steps_box, "Первые шаги", "Осталось несколько действий, чтобы бот заработал.")
        g = W.Group(self.steps_box)
        steps = [
            ("token", "Ключ бота", "Вставьте ключ из Developer Portal и проверьте его.", "Указать",
             lambda: self.app.goto("connection")),
            ("guild", "Сервер", "Пригласите бота на свой сервер и выберите его.", "Выбрать",
             lambda: self.app.goto("connection")),
            ("built", "Построение сервера", "Бот создаст недостающие роли, каналы и панели.", "Построить",
             self.build_server),
            ("running", "Запуск", "Бот начнёт работать и будет запускаться вместе с Windows.", "Запустить",
             self.start),
        ]
        first_open = next((k for k, *_ in steps if not done[k]), None)
        for key, title, desc, action, fn in steps:
            row = g.row(title, desc, "completed" if done[key] else "right")
            if done[key]:
                W.Pill(row.right, "Готово", "success").pack(side="left")
            else:
                W.button(row.right, action, fn, "accent" if key == first_open else "default").pack(side="left")

    def _hosts(self, st):
        hosts = (st or {}).get("hosts") or []
        if (st or {}).get("solo") or not hosts:
            sig = None
        else:
            now = time.time()
            sig = tuple((h.get("id"), h.get("name"), h.get("state"), now - h.get("ts", 0) < ONLINE, h.get("load"))
                        for h in hosts)
        if sig == self.hosts_sig:
            return
        self.hosts_sig = sig
        for w in self.hosts_box.winfo_children():
            w.destroy()
        if sig is None:
            return
        W.section(self.hosts_box, "Компьютеры")
        g = W.Group(self.hosts_box)
        me = ((st or {}).get("me") or {}).get("id")
        active = st.get("active_host")
        for h in hosts:
            online = time.time() - h.get("ts", 0) < ONLINE
            running = online and h.get("name") == active
            name = h.get("name", "?") + (" · этот компьютер" if h.get("id") == me else "")
            desc = f"№{h.get('priority')} · {h.get('os') or 'Windows'}"
            if h.get("mode") == "manual":
                desc += " · только по кнопке"
            row = g.row(name, desc, "cloud" if h.get("kind") == "server" else "monitor")
            if online and h.get("load") is not None:
                meter = W.Meter(row.right, 90)
                meter.set(h["load"])
                meter.pack(side="left")
                W.label(row.right, f"{h['load']} %", "caption", "text2", width=5, anchor="e").pack(
                    side="left", padx=(px(6), px(12)))
            if running:
                W.Pill(row.right, "Работает бот", "success").pack(side="left")
            elif online:
                W.Pill(row.right, "В резерве", "neutral").pack(side="left")
            else:
                W.Pill(row.right, "Не в сети", "neutral").pack(side="left")
        foot = g.block(padding=(18, 10))
        W.LinkButton(foot, "Все компьютеры", lambda: self.app.goto("computers")).pack(side="left")

    def _events(self):
        lines = state.tail(state.LOGS["supervisor"], 8)
        sig = tuple(lines)
        if sig == self.events_sig:
            return
        self.events_sig = sig
        for w in self.events.winfo_children():
            w.destroy()
        if not lines:
            W.label(self.events, "Событий пока нет. Они появятся после первого запуска бота.", "body",
                    "text2").pack(anchor="w")
            return
        for line in lines:
            if line.startswith("[") and len(line) > 21 and line[11] == " ":
                line = line[12:]  # «[2026-10-25 19:22:34] …» → «19:22:34] …»
                line = line.replace("]", "", 1)
            W.label(self.events, line[:140], "mono", "text2").pack(anchor="w")

    # ---------- действия ----------
    def start(self):
        state.start_supervisor()
        self.app.notify("info", "Бот запускается", "Это займёт до 20 секунд.", timeout=8000)

    def restart(self):
        state.send_command("restart_bot")
        self.app.notify("info", "Бот перезапускается", "Это займёт около 10 секунд.", timeout=8000)

    def stop(self):
        if state.sync_enabled(self.app.store.saved["e"]):
            text = "Если включены другие компьютеры, бот продолжит работу на одном из них."
        else:
            text = "Бот перестанет отвечать на сервере, пока вы не запустите его снова."
        if self.app.confirm("Остановить бота?", text, ok="Остановить", danger=True):
            state.send_command("stop")
            self.app.notify("info", "Бот останавливается", timeout=6000)

    def take_here(self):
        if self.app.confirm("Забрать бота на этот компьютер?",
                            "Бот переедет сюда и закрепится здесь, пока вы не вернёте его по приоритету.",
                            ok="Забрать"):
            state.send_command("take_here")
            self.app.notify("info", "Бот переезжает", "Это займёт около 30 секунд.", timeout=8000)

    def backup(self):
        if self.app.status is None:
            return self.app.message("Бот не запущен", "Копию базы делает работающий бот. Сначала запустите его.")
        state.send_command("backup")
        self.app.notify("success", "Копия базы сохраняется", timeout=5000)

    def check_updates(self):
        if self.app.status is None:
            return self.app.message("Бот не запущен", "Обновления проверяет работающий бот. Сначала запустите его.")
        state.send_command("check_update")
        self.app.notify("info", "Проверяю обновления", timeout=5000)

    def publish(self):
        note = self.app.prompt("Опубликовать обновление", "Что изменилось (коротко, для истории)")
        if note is None:
            return
        self.app.background(lambda: state.publish_update(note or "Обновление из панели управления"),
                            lambda v, e: self.app.notify("error", "Не удалось опубликовать", str(e)) if e else
                            self.app.notify("success", "Обновление опубликовано",
                                            "Остальные компьютеры поставят его в течение минуты.", timeout=8000))

    def build_server(self):
        if not self.app.ensure_saved("Бот строит сервер по сохранённым настройкам."):
            return

        def done(ok, _out):
            if ok:
                self.app.prefs["server_built"] = time.time()
                state.save_prefs(self.app.prefs)
                self.steps_sig = None
                self._steps(self.app.status)
        self.app.run_task("Построение сервера", state.tool_args("build_server.py"),
                          "Бот создаст недостающие роли, категории и каналы. Ничего не удаляется.", done)
