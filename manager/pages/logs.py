"""Журнал: журналы бота, диспетчера и самой программы — поиск, фильтр ошибок, обновление на лету."""
import os
import re
import tkinter as tk
from tkinter import ttk

from .. import state
from .. import widgets as W
from ..theme import C, font, px
from .base import Page

SOURCES = [
    ("bot", "Бот", lambda: state.LOGS["bot"]),
    ("supervisor", "Диспетчер", lambda: state.LOGS["supervisor"]),
    ("manager", "Ошибки программы", lambda: os.path.join(state.RUNTIME, "manager-errors.log")),
]
ERROR_RE = re.compile(r"ERROR|CRITICAL|Traceback|Exception|ошибка|Ошибка|⚠|❌")
WARN_RE = re.compile(r"WARNING|WARN")
STAMP_RE = re.compile(r"^\[?\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\]?")
LINES = 1500


class View(Page):
    description = "Журналы бота, диспетчера и этой программы."
    scroll = False

    def build(self):
        self.source = tk.StringVar(value=self.app.prefs.get("log_source", "bot"))
        self.only_errors = tk.BooleanVar(value=False)
        self.stamp = None
        self.job = None

        bar = tk.Frame(self.body, bg=C("bg"))
        bar.pack(fill="x", pady=(0, px(10)))
        seg = tk.Frame(bar, bg=C("bg"))
        seg.pack(side="left")
        for key, title, _ in SOURCES:
            ttk.Radiobutton(seg, text=title, value=key, variable=self.source, style="Toggle.TButton",
                            command=self.reload).pack(side="left", padx=(0, px(4)))
        self.search = W.Entry(bar, "", 22, "Поиск", command=lambda v: self.reload(force=True))
        self.search.pack(side="left", padx=(px(16), 0))
        ttk.Checkbutton(bar, text="Только ошибки", variable=self.only_errors,
                        command=lambda: self.reload(force=True)).pack(side="left", padx=(px(12), 0))
        W.IconButton(bar, "folder", lambda: state.open_path(os.path.dirname(self.path())), "Открыть папку").pack(
            side="right")
        W.IconButton(bar, "open", self.open_file, "Открыть файл").pack(side="right")
        W.IconButton(bar, "copy", self.copy, "Копировать").pack(side="right")
        W.IconButton(bar, "refresh", lambda: self.reload(force=True), "Обновить").pack(side="right")

        box = tk.Frame(self.body, bg=C("border"))
        box.pack(fill="both", expand=True, pady=(0, px(24)))
        inner = tk.Frame(box, bg=C("code_bg"))
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.text = tk.Text(inner, font=font("mono"), bg=C("code_bg"), fg=C("text"), relief="flat", wrap="none",
                            padx=px(12), pady=px(10), insertbackground=C("text"), selectbackground=C("accent"),
                            selectforeground=C("on_accent"), state="disabled", cursor="arrow")
        ys = ttk.Scrollbar(inner, orient="vertical", command=self.text.yview)
        xs = ttk.Scrollbar(inner, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        xs.pack(side="bottom", fill="x")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("error", foreground=C("error"))
        self.text.tag_configure("warning", foreground=C("warning"))
        self.text.tag_configure("stamp", foreground=C("text3"))
        self.text.tag_configure("empty", foreground=C("text2"), font=font("body"))
        self.reload(force=True)
        self._tick()

    def path(self) -> str:
        return next(fn() for key, _, fn in SOURCES if key == self.source.get())

    def reload(self, force: bool = False):
        self.app.prefs["log_source"] = self.source.get()
        path = self.path()
        try:
            st = os.stat(path)
            stamp = (path, st.st_size, st.st_mtime)
        except OSError:
            stamp = (path, None, None)
        if not force and stamp == self.stamp:
            return
        changed_source = self.stamp is None or self.stamp[0] != path
        self.stamp = stamp
        at_bottom = self.text.yview()[1] >= 0.999 or changed_source or force
        lines = state.tail(path, LINES) if stamp[1] is not None else []
        query = self.search.get().strip().lower()
        if query:
            lines = [ln for ln in lines if query in ln.lower()]
        if self.only_errors.get():
            lines = [ln for ln in lines if ERROR_RE.search(ln) or WARN_RE.search(ln)]
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if not lines:
            msg = ("Журнал пока пуст. Он появится после первого запуска бота." if stamp[1] is None or not query
                   and not self.only_errors.get() else "Ничего не найдено.")
            self.text.insert("end", msg, "empty")
        for ln in lines:
            m = STAMP_RE.match(ln)
            tag = "error" if ERROR_RE.search(ln) else ("warning" if WARN_RE.search(ln) else None)
            if m:
                self.text.insert("end", m.group(0), "stamp")
                self.text.insert("end", ln[m.end():] + "\n", tag or ())
            else:
                self.text.insert("end", ln + "\n", tag or ())
        self.text.configure(state="disabled")
        if at_bottom:
            self.text.see("end")

    def _tick(self):
        if not self.winfo_exists():
            return
        if self.winfo_ismapped():
            self.reload()
        self.job = self.after(3000, self._tick)

    def on_show(self):
        self.reload()

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.text.get("1.0", "end").strip())
        self.app.notify("success", "Журнал скопирован", timeout=3000)

    def open_file(self):
        if os.path.exists(self.path()):
            state.open_path(self.path())
        else:
            self.app.message("Файла пока нет", "Журнал появится после первого запуска бота.")
