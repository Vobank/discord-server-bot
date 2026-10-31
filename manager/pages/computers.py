"""Компьютеры: синхронизация, список компьютеров с ботом, управление, очередь и установщики.

Несколько компьютеров подменяют друг друга через закрытый канал bot-sync (supervisor.py): работает всегда одна
копия бота. Здесь — включение синхронизации, живой список компьютеров из runtime/status.json, команды
«забрать сюда / вернуть по приоритету / перезапустить», параметры этого ПК (host.json) и сборка установщика
для другого ПК или хостинга.
"""
import re
import time
import tkinter as tk

from .. import state
from .. import widgets as W
from ..theme import C, font, glyph, px
from .base import Page

ONLINE = 150           # компьютер на связи, если отмечался не позже (как в supervisor.py)
FRESH = 90             # пульс бота свежий — значит, бот работает на этом компьютере
RESTART_WAIT = 20000   # мс: столько ждём остановки диспетчера, прежде чем запустить его снова
RESTART_LIMIT = 120    # с: дольше старый процесс не ждём

PRIORITIES = [(1, "1 — главный")] + [(n, f"{n} — запасной") for n in range(2, 6)]
MODES = [("auto", "Автоматически, по очереди"), ("manual", "Только по кнопке «Забрать бота сюда»")]
KINDS = [("pc", "Компьютер с Windows"), ("server", "Хостинг или сервер (Linux, Docker)")]
KIND_HINTS = {
    "pc": "На том компьютере достаточно распаковать архив и запустить УСТАНОВИТЬ.bat.",
    "server": "Внутри архива будет инструкция для VPS, Docker и хостинга с панелью для ботов.",
}
SYNC_KEYS = ("SYNC_CHANNEL_ID", "SYNC_HEARTBEAT_ID")
STEPS = (
    "Включите синхронизацию: бот создаст на сервере закрытый канал bot-sync.",
    "Соберите установщик для другого компьютера или хостинга внизу этой страницы.",
    "Распакуйте архив на том компьютере и запустите УСТАНОВИТЬ.bat.",
)
BALANCE_ON = ("Если компьютер с ботом сильно загружен, например игрой, бот переедет на более свободный — "
              "не чаще раза в 10 минут и не во время музыки.")
BALANCE_OFF = "Бот выбирает компьютер строго по номеру в очереди: №1 всегда забирает его себе."
TAKE_DESC = "Бот переедет сюда и останется здесь, пока вы не вернёте его по приоритету."
UNPIN_DESC = "Снимает закрепление: бот вернётся на компьютер, который положен по очереди."
RESTART_DESC = "Перезапуск на том компьютере, где бот сейчас работает."
RESTART_NOTE = "Он запустится снова примерно через 30 секунд. Не закрывайте программу до этого."
SAME_NAME = "компьютеры с одинаковыми именами будут мешать друг другу."


def ago(ts: float) -> str:
    """Сколько прошло: «5 мин», «3 ч», «2 дн.»."""
    s = max(0, int(time.time() - ts))
    if s < 3600:
        return f"{max(1, s // 60)} мин"
    if s < 86400:
        return f"{s // 3600} ч"
    return f"{s // 86400} дн."


def host_id(name: str) -> str:
    """ID компьютера из имени — так же, как его получает tools/make_package.py."""
    return re.sub(r"\W+", "-", name.lower()).strip("-") or "second-pc"


def priority_options(current) -> list:
    options = list(PRIORITIES)
    if isinstance(current, int) and current > len(PRIORITIES):
        options.append((current, f"{current} — запасной"))
    return options


def pid_alive(pid) -> bool:
    """Процесс ещё работает? Без psutil считаем, что уже нет."""
    try:
        import psutil
        return bool(pid) and psutil.pid_exists(int(pid))
    except Exception:
        return False


def restart_supervisor(app, pid=None):
    """Остановить диспетчер этого ПК и запустить снова. Второй диспетчер, пока жив первый, сразу выходит,
    поэтому запускаем не раньше чем через 20 с и только когда старый процесс завершился."""
    state.send_command("stop")
    deadline = time.time() + RESTART_LIMIT

    def start():
        if pid and pid_alive(pid) and time.time() < deadline:
            app.after(2000, start)
        else:
            state.start_supervisor()
    app.after(RESTART_WAIT, start)


class View(Page):
    description = "Бот может работать на нескольких компьютерах: если один выключится, бот продолжит на другом."

    def build(self):
        self.synced = state.sync_enabled(self.app.store.saved["e"])
        self.hosts_sig = None
        self.host_rows: list = []
        self.notice = None
        self._texts: dict = {}
        self._build_sync()
        self.notice_box = tk.Frame(self.body, bg=W.bg_of(self.body))
        self.notice_box.pack(fill="x")
        self._build_hosts()
        self._build_actions()
        self._build_choice()
        self._build_this_pc()
        self._build_installer()

    # ---------- разметка ----------
    def _build_sync(self):
        W.section(self.body, "Синхронизация")
        if self.synced:
            W.InfoBar(self.body, "success", "Синхронизация включена",
                      "Работает всегда одна копия бота. База, настройки и обновления переезжают между "
                      "компьютерами через закрытый канал bot-sync.", closable=False).pack(fill="x")
            return
        g = W.Group(self.body)
        row = g.row("Несколько компьютеров",
                    "Работает всегда одна копия бота, а база, настройки и обновления сами переезжают между "
                    "компьютерами через закрытый канал bot-sync.", "sync")
        W.button(row.right, "Включить синхронизацию", self.enable_sync, "accent").pack(side="left")
        box = g.block((54, 14))
        for i, text in enumerate(STEPS, 1):
            line = tk.Frame(box, bg=W.bg_of(box))
            line.pack(fill="x", pady=(px(8) if i > 1 else 0, 0))
            self._step_number(line, i).pack(side="left", anchor="n")
            lb = W.label(line, text, "body", "text2")
            lb.pack(side="left", fill="x", expand=True, padx=(px(12), 0))
            W.autowrap(lb, px(40))

    @staticmethod
    def _step_number(parent, n: int) -> tk.Canvas:
        s = px(22)
        cv = tk.Canvas(parent, width=s, height=s, bg=W.bg_of(parent), highlightthickness=0, bd=0)
        cv.create_oval(1, 1, s - 1, s - 1, fill=C("hover"), outline=C("border"))
        cv.create_text(s / 2, s / 2, text=str(n), font=font("caption_strong"), fill=C("text2"))
        return cv

    def _build_hosts(self):
        W.section(self.body, "Компьютеры с ботом", "Компьютеры отмечаются раз в минуту, поэтому изменения "
                                                   "видны не сразу.")
        self.hosts_box = tk.Frame(self.body, bg=W.bg_of(self.body))
        self.hosts_box.pack(fill="x")

    def _build_actions(self):
        box = W.section(self.body, "Управление", " ")
        self.actions_hint = box.winfo_children()[-1]
        g = W.Group(self.body)
        self.take_row = g.row("Забрать бота на этот компьютер", TAKE_DESC, "pin")
        self.b_take = W.button(self.take_row.right, "Забрать бота сюда", self.take_here)
        self.b_take.pack(side="left")
        self.unpin_row = g.row("Вернуть по приоритету", UNPIN_DESC, "unpin")
        self.b_unpin = W.button(self.unpin_row.right, "Вернуть", self.unpin)
        self.b_unpin.pack(side="left")
        self.restart_row = g.row("Перезапустить бота", RESTART_DESC, "refresh")
        self.b_restart = W.button(self.restart_row.right, "Перезапустить", self.restart_bot)
        self.b_restart.pack(side="left")

    def _build_choice(self):
        W.section(self.body, "Выбор компьютера")
        g = W.Group(self.body)
        on = bool(self.get("s:multi_pc.balance"))
        row = g.row("Выбирать самый свободный компьютер", BALANCE_ON if on else BALANCE_OFF, "speed")
        self.bind_switch(row.right, "s:multi_pc.balance",
                         on_toggle=lambda v: row.set_description(BALANCE_ON if v else BALANCE_OFF)).pack(side="left")

    def _build_this_pc(self):
        W.section(self.body, "Этот компьютер", "Параметры хранятся только на этом компьютере и вступают в силу "
                                               "после перезапуска бота.")
        g = W.Group(self.body)
        row = g.row("Имя компьютера", "Так компьютер называется в списке и в команде /status.", "tag")
        W.Entry(row.right, self.get("h:name") or "", 30, command=lambda v: self.set("h:name", v.strip()),
                validate=lambda v: bool(v.strip())).pack(side="left")
        row = g.row("Номер в очереди", "№1 — главный компьютер, остальные подменяют его по порядку.", "sort")
        self.bind_combo(row.right, "h:priority", priority_options(self.get("h:priority")), 28).pack(side="left")
        row = g.row("Когда брать бота", "В режиме «только по кнопке» компьютер не забирает бота сам, даже если "
                                        "остальные выключены.", "switch")
        self.bind_combo(row.right, "h:mode", MODES, 28).pack(side="left")

    def _build_installer(self):
        W.section(self.body, "Установщик для другого компьютера или хостинга",
                  "Архив с ботом, настройками и ключом: на другом компьютере бот установится в один шаг.")
        g = W.Group(self.body)
        row = g.row("Имя", "Так компьютер будет называться в списке.", "tag")
        self.pkg_name = W.Entry(row.right, "ПК друга", 30, validate=lambda v: bool(v.strip()))
        self.pkg_name.pack(side="left")
        self.kind_row = g.row("Куда устанавливать", KIND_HINTS["pc"], "monitor")
        self.pkg_kind = W.Combo(self.kind_row.right, KINDS, "pc", self._kind_changed, 28)
        self.pkg_kind.pack(side="left")
        row = g.row("Номер в очереди", "Чем меньше номер, тем раньше компьютер забирает бота.", "sort")
        self.pkg_priority = W.Combo(row.right, PRIORITIES, 2, width=28)
        self.pkg_priority.pack(side="left")
        row = g.row("Когда брать бота", "«Только по кнопке» удобно для компьютера, на котором часто играют.",
                    "switch")
        self.pkg_mode = W.Combo(row.right, MODES, "auto", width=28)
        self.pkg_mode.pack(side="left")
        row = g.row("Собрать установщик", "Архив появится на рабочем столе этого компьютера.", "download")
        W.button(row.right, "Собрать на рабочий стол", self.make_package, "accent").pack(side="left")
        W.spacer(self.body, 8)
        W.InfoBar(self.body, "warning", "В архиве лежит ключ бота",
                  "Передайте архив лично, например на флешке или в личных сообщениях, и не выкладывайте его "
                  "в открытый доступ.", closable=False).pack(fill="x")

    def _kind_changed(self, kind):
        self.kind_row.icon.configure(text=glyph("cloud" if kind == "server" else "monitor"))
        self.kind_row.set_description(KIND_HINTS.get(kind, KIND_HINTS["pc"]))

    # ---------- живое состояние ----------
    def on_show(self):
        # синхронизацию могли включить, пока окно задачи было закрыто раньше времени
        if not self.synced and state.sync_enabled(state.read_env()):
            self._merge_sync_env()
            self.app.after_idle(self.app.rebuild)

    def on_status(self, status):
        self._render_hosts(status)
        self._update_actions(status)
        self._update_notice(status)

    @staticmethod
    def _hosts(st) -> list:
        hosts = [h for h in (st.get("hosts") or []) if isinstance(h, dict)]
        return sorted(hosts, key=lambda h: (h.get("priority") or 99, str(h.get("name") or "")))

    def _signature(self, st) -> tuple:
        if st is None:
            return ("none",)
        if st.get("solo"):
            return ("solo", self.synced)
        hosts = self._hosts(st)
        if not hosts:
            return ("empty",)
        me = (st.get("me") or {}).get("id")
        return ("list", me) + tuple((h.get("id"), h.get("name"), h.get("kind"), h.get("priority"), h.get("mode"),
                                     h.get("os")) for h in hosts)

    def _render_hosts(self, st):
        sig = self._signature(st)
        if sig != self.hosts_sig:
            self.hosts_sig = sig
            for child in self.hosts_box.winfo_children():
                child.destroy()
            self.host_rows = []
            kind = sig[0]
            if kind == "none":
                self._empty("Бот не запущен", "Запустите бота на этом компьютере, чтобы увидеть список.",
                            ("Открыть обзор", lambda: self.app.goto("overview")))
            elif kind == "solo" and self.synced:
                self._empty("Список появится после перезапуска бота",
                            "Синхронизация уже включена, но бот пока работает в режиме одного компьютера.")
            elif kind == "solo":
                self._empty("Один компьютер", "Синхронизация не включена — бот работает на одном компьютере.")
            elif kind == "empty":
                self._empty("Список пока пуст", "Компьютеры отмечаются раз в минуту, скоро они появятся здесь.")
            else:
                g = W.Group(self.hosts_box)
                for h in self._hosts(st):
                    self._add_host(g, h, sig[1])
        if sig[0] == "list":
            for w, h in zip(self.host_rows, self._hosts(st)):
                self._update_host(w, h, st)

    def _empty(self, title: str, text: str, action=None):
        g = W.Group(self.hosts_box)
        row = g.row(title, text, "monitor")
        row.icon.configure(fg=C("text3"))
        if action:
            W.button(row.right, action[0], action[1]).pack(side="left")

    def _add_host(self, g, h: dict, me_id):
        title = str(h.get("name") or h.get("id") or "Компьютер")
        if me_id and h.get("id") == me_id:
            title += " · этот компьютер"
        desc = f"№{h.get('priority') or '?'} в очереди"
        if h.get("os"):
            desc += f" · {h['os']}"
        if h.get("mode") == "manual":
            desc += " · только по кнопке"
        row = g.row(title, desc, "cloud" if h.get("kind") == "server" else "monitor")
        r = row.right
        r.columnconfigure(0, minsize=px(96))    # «Закреплён» (место держим, чтобы колонки не прыгали)
        r.columnconfigure(1, minsize=px(140))   # нагрузка
        r.columnconfigure(2, minsize=px(140))   # состояние
        pin = W.Pill(r, "Закреплён", "info")
        pin.grid(row=0, column=0, sticky="e", padx=(0, px(14)))
        load = tk.Frame(r, bg=W.bg_of(r))
        load.grid(row=0, column=1, sticky="w")
        meter = W.Meter(load, 88)
        meter.pack(side="left")
        pct = W.label(load, "", "caption", "text2", width=5, anchor="e")
        pct.pack(side="left", padx=(px(6), 0))
        status = W.Pill(r, "", "neutral")
        status.grid(row=0, column=2, sticky="w", padx=(px(16), 0))
        r.columnconfigure(3, minsize=px(150))   # «Перенести сюда»
        give = W.button(r, "Перенести сюда", lambda h=h: self.give(h), tooltip="Перенести бота на этот компьютер "
                        "и закрепить его там")
        give.grid(row=0, column=3, sticky="e", padx=(px(12), 0))
        self.host_rows.append({"row": row, "pin": pin, "load": load, "meter": meter, "pct": pct, "status": status,
                               "give": give, "tips": [W.Tooltip(meter, ""), W.Tooltip(pct, "")], "online": None})

    def _update_host(self, w: dict, h: dict, st: dict):
        now = time.time()
        ts = h.get("ts") or 0
        running = (bool(h.get("name")) and h.get("name") == st.get("active_host")
                   and now - (st.get("active_ts") or 0) < FRESH)
        online = running or now - ts < ONLINE
        if running:
            w["status"].set("Работает бот", "success")
        elif online:
            w["status"].set("В резерве", "neutral")
        else:
            w["status"].set(f"Не в сети {ago(ts)}" if ts else "Не в сети", "neutral")
        if st.get("pinned") and st.get("pinned") == h.get("id"):
            w["pin"].grid()
        else:
            w["pin"].grid_remove()
        if online and not running and not st.get("solo"):
            w["give"].grid()
        else:
            w["give"].grid_remove()
        load = h.get("load")
        if online and isinstance(load, (int, float)):
            w["meter"].set(load)
            w["pct"].configure(text=f"{round(load)} %")
            parts = [f"{name} {h[key]} %" for key, name in (("cpu", "процессор"), ("ram", "память"))
                     if h.get(key) is not None]
            tip = "Нагрузка без учёта самого бота" + (": " + ", ".join(parts) if parts else "")
            for t in w["tips"]:
                t.text = tip
            w["load"].grid()
        else:
            w["load"].grid_remove()
        if w["online"] != online:
            w["online"] = online
            w["row"].icon.configure(fg=C("text" if online else "text3"))
            w["row"].title.configure(fg=C("text" if online else "text2"))

    def _update_actions(self, st):
        take = unpin = restart = False
        take_desc, unpin_desc = TAKE_DESC, UNPIN_DESC
        if not self.synced:
            hint = "Станет доступно, когда вы включите синхронизацию."
        elif st is None:
            hint = "Запустите бота на этом компьютере, чтобы управлять им отсюда."
        elif st.get("solo"):
            hint = "Станет доступно после перезапуска бота."
        else:
            hint = "Команды выполняются там, где сейчас работает бот, даже если это другой компьютер."
            me = (st.get("me") or {}).get("id")
            here = st.get("state") == "active"
            pinned = st.get("pinned")
            running = bool(st.get("active_host")) and time.time() - (st.get("active_ts") or 0) < FRESH
            take = not (here and pinned == me)
            unpin = bool(pinned)
            restart = running or here
            if here and pinned == me:
                take_desc = "Бот уже работает здесь и закреплён за этим компьютером."
            elif here:
                take_desc = "Бот уже работает здесь, кнопка закрепит его за этим компьютером."
            if not pinned:
                unpin_desc = "Сейчас бот ни за кем не закреплён и выбирает компьютер сам."
        self._set_text(self.actions_hint, hint)
        self._set_desc(self.take_row, take_desc)
        self._set_desc(self.unpin_row, unpin_desc)
        for b, on in ((self.b_take, take), (self.b_unpin, unpin), (self.b_restart, restart)):
            b.state(["!disabled"] if on else ["disabled"])

    def _set_text(self, lb: tk.Label, text: str):
        if lb.cget("text") != text:
            lb.configure(text=text)

    def _set_desc(self, row: W.Row, text: str):
        if self._texts.get(id(row)) != text:
            self._texts[id(row)] = text
            row.set_description(text)

    def _needs_restart(self, st: dict) -> bool:
        """Диспетчер читает host.json и выбор по нагрузке при запуске: сохранённое ещё не применилось?"""
        me = st.get("me") or {}
        host = self.app.store.saved["h"]
        if not me or me.get("id") != host.get("id"):
            return False
        if me.get("name") != host.get("name") or me.get("priority") != host.get("priority"):
            return True
        if st.get("mode") and st.get("mode") != host.get("mode", "auto"):
            return True
        if st.get("load") is not None and "balance" in st:  # без psutil выбор по нагрузке выключен всегда
            return bool(st["balance"]) != bool(self.saved("s:multi_pc.balance", True))
        return False

    def _update_notice(self, st):
        kind = None
        if st and self.synced:
            if st.get("solo"):
                kind = "solo"
            elif self._needs_restart(st):
                kind = "changed"
        if kind == self.notice:
            return
        self.notice = kind
        for child in self.notice_box.winfo_children():
            child.destroy()
        if kind == "solo":
            title, message = ("Синхронизация включится после перезапуска бота",
                              "Сейчас бот работает в режиме одного компьютера.")
        elif kind == "changed":
            title, message = ("Изменения применятся после перезапуска бота",
                              "Выбор компьютера и параметры этого компьютера бот читает только при запуске.")
        else:
            return
        W.InfoBar(self.notice_box, "info", title, message, actions=[("Перезапустить", self.restart_here)],
                  closable=False).pack(fill="x", pady=(px(12), 0))

    # ---------- действия ----------
    def take_here(self):
        st = self.app.status
        if not st:
            return
        if st.get("state") == "active":
            state.send_command("take_here")
            self.app.notify("success", "Бот закреплён за этим компьютером",
                            "Очередь и нагрузка не перенесут его, пока вы не вернёте его по приоритету.",
                            timeout=8000)
            return
        other = st.get("active_host")
        where = f"на «{other}»" if other else "на другом компьютере"
        if not self.app.confirm("Забрать бота на этот компьютер?",
                                f"Бот остановится {where} и примерно через 30 секунд запустится здесь. Он останется "
                                "на этом компьютере, пока вы не вернёте его по приоритету.", ok="Забрать"):
            return
        state.send_command("take_here")
        self.app.notify("info", "Бот переезжает на этот компьютер", "Это займёт около 30 секунд.", timeout=10000)

    def give(self, h: dict):
        """Перенести бота на выбранный компьютер (сервер) и закрепить там."""
        st = self.app.status or {}
        name = h.get("name") or h.get("id")
        where = f"на «{st['active_host']}»" if st.get("active_host") else "там, где он сейчас"
        if not self.app.confirm(f"Перенести бота на «{name}»?",
                                f"Бот остановится {where} и примерно через 30 секунд запустится на «{name}». "
                                "Он останется там, пока вы не вернёте его по приоритету.", ok="Перенести"):
            return
        state.send_command(f"give:{h.get('id')}")
        self.app.notify("info", f"Бот переезжает на «{name}»", "Это займёт около 30 секунд.", timeout=10000)

    def unpin(self):
        state.send_command("unpin")
        self.app.notify("success", "Закрепление снято", "Бот вернётся на компьютер, который положен по очереди.",
                        timeout=8000)

    def restart_bot(self):
        st = self.app.status or {}
        state.send_command("restart_bot")
        if st.get("state") == "active":
            self.app.notify("info", "Бот перезапускается", "Это займёт около 10 секунд.", timeout=8000)
        else:
            where = f"«{st['active_host']}»" if st.get("active_host") else "другой компьютер"
            self.app.notify("info", "Бот перезапускается",
                            f"Команда уйдёт на {where}, бот перезапустится в течение 30 секунд.", timeout=10000)

    def restart_here(self):
        """Перезапуск диспетчера этого ПК, чтобы он перечитал host.json, .env и выбор компьютера."""
        st = self.app.status
        if st is None:
            return
        if st.get("state") == "active":
            message = "Бот остановится и запустится снова примерно через 30 секунд."
            if not st.get("solo"):
                message += " Пока он перезапускается, его может подхватить другой компьютер."
            if not self.app.confirm("Перезапустить бота?", message, ok="Перезапустить"):
                self.notice = None  # вернуть полосу с кнопкой
                self.after_idle(lambda: self.winfo_exists() and self._update_notice(self.app.status))
                return
        restart_supervisor(self.app, st.get("pid"))
        self.app.notify("info", "Бот перезапускается", RESTART_NOTE, timeout=30000)

    def enable_sync(self):
        if not self.app.ensure_saved("Синхронизация использует сохранённые ключ бота и сервер. "
                                     "Сохранить изменения и продолжить?"):
            return
        env = self.app.store.saved["e"]
        if not state.token_looks_valid(env.get("DISCORD_TOKEN", "")) or not env.get("GUILD_ID"):
            if self.app.confirm("Сначала подключите бота", "Для синхронизации нужны ключ бота и сервер. "
                                "Укажите их в разделе «Подключение».", ok="Открыть «Подключение»"):
                self.app.goto("connection")
            return
        if not self.app.confirm("Включить синхронизацию?",
                                "Бот создаст на сервере закрытый канал bot-sync, который видит только он. Через этот "
                                "канал компьютеры передают друг другу базу, настройки и обновления.", ok="Включить"):
            return
        self.app.run_task("Синхронизация", state.tool_args("setup_sync.py"),
                          "Бот подключится к серверу и создаст канал bot-sync. Обычно это занимает до минуты.",
                          on_done=lambda ok, _log: ok and self._merge_sync_env(),
                          success="Синхронизация включена", failure="Не удалось включить синхронизацию")
        if not state.sync_enabled(self.app.store.saved["e"]):
            self._merge_sync_env()  # окно закрыли раньше, чем пришёл ответ, или синхронизация уже была
        if state.sync_enabled(self.app.store.saved["e"]):
            self._finish_sync()

    def _merge_sync_env(self):
        """Новые ключи синхронизации из .env — в сохранённое и в черновик, не трогая несохранённые правки."""
        new_env = state.read_env()
        for key in SYNC_KEYS:
            self.app.store.saved["e"][key] = new_env.get(key, "")
            self.app.store.draft["e"][key] = new_env.get(key, "")

    def _finish_sync(self):
        app = self.app
        st = app.status
        restarted = False
        if st is not None and app.confirm("Перезапустить бота?", "Режим нескольких компьютеров включится после "
                                          "перезапуска. Бот будет недоступен около 30 секунд.", ok="Перезапустить"):
            restart_supervisor(app, st.get("pid"))
            restarted = True
        app.rebuild()  # раздел пересоберётся уже с включённой синхронизацией; self после этого не трогаем
        if restarted:
            app.notify("info", "Бот перезапускается", RESTART_NOTE, timeout=30000)
        else:
            app.notify("success", "Синхронизация включена", "Теперь можно собрать установщик для другого "
                                                             "компьютера.", timeout=8000)

    def make_package(self):
        name = self.pkg_name.get().strip()
        if not name:
            self.pkg_name.entry.focus_set()
            self.app.notify("warning", "Укажите имя компьютера", "Так он будет называться в списке.", timeout=6000)
            return
        kind = self.pkg_kind.get_value() or "pc"
        priority = self.pkg_priority.get_value() or 2
        mode = self.pkg_mode.get_value() or "auto"
        synced = state.sync_enabled(self.app.store.saved["e"])
        if not synced and kind == "pc":
            self.app.message("Сначала включите синхронизацию",
                             "Компьютеры подменяют друг друга через закрытый канал bot-sync. Включите синхронизацию "
                             "в начале этой страницы, а затем соберите установщик.")
            return
        if not synced and not self.app.confirm(
                "Бот будет работать только на хостинге",
                "Синхронизация не включена, поэтому хостинг и этот компьютер не смогут подменять друг друга. После "
                "запуска на хостинге остановите бота здесь, иначе на сервере будут работать два бота. Чтобы они "
                "подменяли друг друга, сначала включите синхронизацию.", ok="Собрать архив"):
            return
        me = self.app.store.saved["h"]
        if host_id(name) == me.get("id") or name.casefold() == str(me.get("name") or "").casefold():
            self.app.message("Так называется этот компьютер", "Выберите другое имя: " + SAME_NAME)
            return
        known = [h for h in ((self.app.status or {}).get("hosts") or []) if isinstance(h, dict)]
        if any(h.get("id") == host_id(name) or str(h.get("name") or "").casefold() == name.casefold()
               for h in known):
            if not self.app.confirm(f"«{name}» уже есть в списке",
                                    "Собрать для него новый установщик? Если это другой компьютер, выберите другое "
                                    "имя: " + SAME_NAME, ok="Собрать"):
                return
        if not self.app.ensure_saved("Установщик собирается из сохранённых настроек. "
                                     "Сохранить изменения и продолжить?"):
            return
        self.app.run_task("Сборка установщика",
                          state.tool_args("make_package.py", "--name", name, "--priority", str(priority),
                                          "--mode", mode, "--kind", kind),
                          "Архив с ботом, настройками и ключом появится на рабочем столе.",
                          success="Установщик собран", failure="Не удалось собрать установщик")
