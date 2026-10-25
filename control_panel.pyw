"""Панель управления ботом (окно на рабочем столе).
Показывает, где сейчас работает бот, и даёт кнопки: запустить, остановить, перезапустить,
сохранить базу, опубликовать обновление для второго ПК, настройки, логи."""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog

APP = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(APP, "runtime")
STATUS = os.path.join(RUNTIME, "status.json")
COMMAND = os.path.join(RUNTIME, "command.txt")
os.makedirs(RUNTIME, exist_ok=True)
sys.path.insert(0, APP)


def bot_name() -> str:
    try:
        import config
        return config.BOT_NAME
    except Exception:
        return "Discord Bot"


def two_pcs() -> bool:
    """Включена ли синхронизация двух ПК (канал bot-sync записан в .env)."""
    try:
        return "SYNC_CHANNEL_ID=" in open(os.path.join(APP, ".env"), encoding="utf-8").read()
    except OSError:
        return False


NAME = bot_name()


def dpi_aware():
    """Чёткий текст на экранах с масштабом 125–200% (иначе Windows растягивает окно и всё мыльное)."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

BG, CARD, FG, MUTED = "#15161c", "#1f2129", "#f2f2f7", "#9a9caa"
GREEN, YELLOW, RED, ACCENT = "#3ddc84", "#f5c518", "#ff5a5f", "#8b7bff"


def read_status() -> dict | None:
    try:
        with open(STATUS, encoding="utf-8") as f:
            data = json.load(f)
        return data if time.time() - data.get("ts", 0) < 40 else None
    except (OSError, json.JSONDecodeError):
        return None


def ago(ts: float) -> str:
    if not ts:
        return "—"
    s = int(time.time() - ts)
    if s < 60:
        return f"{s} сек назад"
    if s < 3600:
        return f"{s // 60} мин назад"
    return f"{s // 3600} ч {s % 3600 // 60} мин назад"


def uptime(ts: float) -> str:
    if not ts:
        return "—"
    s = int(time.time() - ts)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    return (f"{d} д " if d else "") + f"{h} ч {s // 60} мин"


def host_line(h: dict, st: dict) -> tuple[str, str]:
    """Строка списка ПК и её цвет: 🟢 работает бот, 🟡 на связи в резерве, ⚪ не в сети."""
    online = time.time() - h.get("ts", 0) < 150
    running = online and h.get("id") == (st.get("active_id") or "") or (online and h.get("state") == "active")
    kind = "🌐" if h.get("kind") == "server" else "🖥"
    pin = " 📌" if st.get("pinned") == h.get("id") else ""
    pin += " · вручную" if h.get("mode") == "manual" else ""
    pin += f" · нагрузка {h['load']}%" if online and h.get("load") is not None else ""
    me = " (этот)" if h.get("id") == st["me"].get("id") else ""
    if running:
        return f"● {kind} {h['name']}{me} · №{h.get('priority')} · работает бот{pin}", GREEN
    if online:
        return f"● {kind} {h['name']}{me} · №{h.get('priority')} · в резерве", YELLOW
    return f"● {kind} {h['name']}{me} · №{h.get('priority')} · не в сети ({ago(h.get('ts', 0))})", MUTED


def send(cmd: str):
    with open(COMMAND, "w", encoding="utf-8") as f:
        f.write(cmd)


class Panel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(NAME)
        self.configure(bg=BG)
        k = self.winfo_fpixels("1i") / 96  # масштаб экрана
        self.geometry(f"{int(480 * k)}x{int(800 * k)}")
        self.resizable(False, False)
        ico = os.path.join(APP, "assets", "icon.ico")
        if os.path.exists(ico):
            self.iconbitmap(ico)

        tk.Label(self, text=f"🤖  {NAME}", font=("Segoe UI", 20, "bold"), fg=FG, bg=BG).pack(pady=(18, 0))
        self.host = tk.Label(self, font=("Segoe UI", 10), fg=MUTED, bg=BG)
        self.host.pack()

        card = tk.Frame(self, bg=CARD, padx=18, pady=14)
        card.pack(fill="x", padx=18, pady=14)
        self.dot = tk.Label(card, text="●", font=("Segoe UI", 22), bg=CARD)
        self.dot.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        self.state = tk.Label(card, font=("Segoe UI", 13, "bold"), fg=FG, bg=CARD, anchor="w")
        self.state.grid(row=0, column=1, sticky="w")
        self.sub = tk.Label(card, font=("Segoe UI", 9), fg=MUTED, bg=CARD, anchor="w", wraplength=330, justify="left")
        self.sub.grid(row=1, column=1, sticky="w")

        self.info = tk.Label(self, font=("Consolas", 10), fg=FG, bg=BG, justify="left", anchor="w")
        self.info.pack(fill="x", padx=24)

        self.hosts_card = tk.Frame(self, bg=CARD, padx=14, pady=8)
        tk.Label(self.hosts_card, text="Компьютеры с ботом", font=("Segoe UI", 10, "bold"), fg=FG, bg=CARD,
                 anchor="w").pack(fill="x")
        self.host_rows = [tk.Label(self.hosts_card, font=("Segoe UI", 9), bg=CARD, anchor="w") for _ in range(8)]

        grid = self.grid_frame = tk.Frame(self, bg=BG)
        grid.pack(padx=18, pady=14, fill="x")
        buttons = [
            ("▶  Запустить", self.start, GREEN), ("⏹  Остановить", self.stop, RED),
            ("🔄  Перезапустить бота", lambda: self.cmd("restart_bot", "Бот перезапускается (где бы он ни работал)…"),
             ACCENT),
            ("💾  Сохранить базу", lambda: self.cmd("backup", "База будет сохранена"), ACCENT),
            ("📌  Забрать бота сюда", self.take_here, ACCENT),
            ("↩  Вернуть по приоритету", lambda: self.multi_cmd("unpin", "Бот вернётся на главный ПК по приоритету"),
             ACCENT),
            ("📤  Опубликовать обновление", self.publish, YELLOW),
            ("⬇  Проверить обновления", lambda: self.cmd("check_update", "Проверяю обновления…"), ACCENT),
            ("📜  Лог бота", lambda: self.open_file("bot.log"), MUTED),
            ("⚙️  Настройки", self.settings, MUTED),
            ("📂  Папка бота", lambda: os.startfile(APP), MUTED),
        ]
        for i, (text, fn, color) in enumerate(buttons):
            b = tk.Button(grid, text=text, command=fn, font=("Segoe UI", 10, "bold"), fg=BG, bg=color,
                          activebackground=FG, relief="flat", cursor="hand2", height=2)
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=5, pady=5)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        self.toast = tk.Label(self, font=("Segoe UI", 9), fg=MUTED, bg=BG)
        self.toast.pack()
        self.refresh()

    def refresh(self):
        st = read_status()
        if st is None:
            self.dot.config(fg=RED)
            self.state.config(text="Остановлен на этом ПК")
            self.sub.config(text="Диспетчер не запущен. Нажми «Запустить» — или перезагрузи ПК.")
            self.host.config(text="")
            self.info.config(text="")
        else:
            me = st["me"]
            solo = not two_pcs()
            self.host.config(text="Режим: один ПК" if solo else f"Этот ПК: {me['name']} · №{me['priority']} в очереди "
                                  f"({'главный' if me['priority'] == 1 else 'запасной'})")
            if st["state"] == "active" and solo:
                self.dot.config(fg=GREEN if st.get("bot_running") else YELLOW)
                self.state.config(text="Работает" if st.get("bot_running") else "Запускается…")
                self.sub.config(text="Бот онлайн. Хочешь ПК на подмену или хостинг — Настройки → «Несколько ПК».")
            elif st["state"] == "active":
                self.dot.config(fg=GREEN)
                self.state.config(text="Работает на этом ПК")
                self.sub.config(text=st.get("note") or "Бот онлайн. Запасные ПК подхватят, если этот выключится.")
            else:
                self.dot.config(fg=YELLOW)
                self.state.config(text="В резерве")
                self.sub.config(text=st.get("note") or "Бот работает на другом ПК.")
            self.info.config(text=(
                f"Сейчас главный:  {st.get('active_host') or '—'}\n"
                f"Пульс:           {ago(st.get('active_ts') or 0)}\n"
                f"Бот запущен:     {uptime(st.get('bot_started') or 0)}\n"
                f"База сохранена:  {'копия на диске раз в день' if solo else ago(st.get('last_db_upload') or 0)}\n"
                f"Версия кода:     {st.get('version') or '—'}"))
            self.show_hosts(st, solo)
        if st is None:
            self.hosts_card.pack_forget()
        self.after(2000, self.refresh)

    def show_hosts(self, st: dict, solo: bool):
        hosts = st.get("hosts") or []
        if solo or not hosts:
            self.hosts_card.pack_forget()
            return
        if not self.hosts_card.winfo_ismapped():
            self.hosts_card.pack(fill="x", padx=18, pady=(10, 0), before=self.grid_frame)
        active_name = st.get("active_host")
        for i, row in enumerate(self.host_rows):
            if i < len(hosts):
                h = dict(hosts[i])
                if h.get("name") == active_name and time.time() - (st.get("active_ts") or 0) < 90:
                    h["state"] = "active"
                elif h.get("state") == "active":
                    h["state"] = "standby"
                text, colour = host_line(h, st)
                row.config(text=text, fg=colour)
                row.pack(fill="x")
            else:
                row.pack_forget()

    def multi_cmd(self, c: str, text: str):
        if not two_pcs():
            return self.say("Это для нескольких ПК — включи их в Настройках")
        self.cmd(c, text)

    def take_here(self):
        st = read_status()
        if not two_pcs():
            return self.say("Это для нескольких ПК — включи их в Настройках")
        if st and st.get("state") == "active":
            send("take_here")
            return self.say("📌 Бот закреплён за этим ПК — другие не заберут его по приоритету")
        if messagebox.askyesno(NAME, "Забрать бота на этот ПК?\n\nОн закрепится здесь, пока не нажмёшь "
                                     "«↩ Вернуть по приоритету» или пока этот ПК не выключится."):
            self.cmd("take_here", "Прошу бота сюда — около 30 секунд…")

    def say(self, text: str):
        self.toast.config(text=text)
        self.after(6000, lambda: self.toast.config(text=""))

    def cmd(self, c: str, text: str):
        if read_status() is None:
            return self.say("Сначала нажми «Запустить»")
        send(c)
        self.say(text)

    def start(self):
        if read_status() is not None:
            return self.say("Уже запущен")
        subprocess.Popen(["wscript.exe", os.path.join(APP, "tools", "run_hidden.vbs")])
        self.say("Запускаю… через ~20 сек статус обновится")

    def stop(self):
        if read_status() is None:
            return self.say("И так остановлен")
        if messagebox.askyesno(NAME, "Остановить бота на этом ПК?\n\n"
                                           "Если включён другой ПК — бот сразу продолжит работать там."):
            send("stop")
            self.say("Останавливаю…")

    def settings(self):
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        subprocess.Popen([pyw if os.path.exists(pyw) else sys.executable, os.path.join(APP, "configure.pyw")], cwd=APP)

    def publish(self):
        if not two_pcs():
            return messagebox.showinfo(NAME, "Обновления рассылаются на другие ПК.\nСейчас бот работает на одном ПК — "
                                             "добавить ещё можно в Настройках, вкладка «Несколько ПК».")
        note = simpledialog.askstring("Опубликовать обновление",
                                      "Что изменилось? (коротко, для истории)", parent=self)
        if note is None:
            return
        self.say("Публикую…")

        def work():
            try:
                sys.path.insert(0, APP)
                import sync
                v = asyncio.run(sync.publish(note))
                self.after(0, lambda: messagebox.showinfo(
                    NAME, f"✅ Обновление {v} опубликовано.\nОстальные ПК поставят его сами в течение минуты."))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: messagebox.showerror(NAME, f"Не получилось: {err}"))
        threading.Thread(target=work, daemon=True).start()

    def open_file(self, name: str):
        path = os.path.join(APP, name)
        if os.path.exists(path):
            os.startfile(path)
        else:
            self.say("Файла пока нет")


if __name__ == "__main__":
    dpi_aware()
    Panel().mainloop()
