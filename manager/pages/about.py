"""О программе: сведения о версии, тема оформления программы, ссылки и лицензии."""
import os
import platform
import time
import tkinter as tk
from tkinter import ttk

from .. import state, theme
from .. import widgets as W
from ..theme import C, font, px
from .base import Page

REPO = "https://github.com/Vobank/discord-server-bot"
PORTAL = "https://discord.com/developers/applications"
THEMES = [("system", "Как в Windows"), ("light", "Светлая"), ("dark", "Тёмная")]


def version_text() -> str:
    version = state.local_version()
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(version)) if version else ""


def os_name() -> str:
    return f"{platform.system()} {platform.release()}".strip()


class TextDialog(W.Modal):
    """Текст только для чтения (лицензии) — внутри программы, без внешнего редактора."""

    def __init__(self, app, title: str, text: str):
        super().__init__(app, title, 640)
        box = tk.Frame(self.content, bg=C("border"))
        box.pack(fill="both", expand=True)
        inner = tk.Frame(box, bg=C("card"))
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        view = tk.Text(inner, height=20, width=80, font=font("small"), bg=C("card"), fg=C("text"), relief="flat",
                       wrap="word", padx=px(14), pady=px(12), highlightthickness=0, insertbackground=C("text"),
                       spacing2=px(2))
        bar = ttk.Scrollbar(inner, orient="vertical", command=view.yview)
        view.configure(yscrollcommand=bar.set)
        view.insert("1.0", text.strip())
        view.configure(state="disabled")
        view.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.add_buttons("Закрыть", None)


class View(Page):
    description = "Версия, оформление программы и ссылки."

    def build(self):
        self._build_header()
        self._build_theme()
        self._build_links()
        self._build_licenses()

    # ---------- разметка ----------
    def _build_header(self):
        card = W.Card(self.body, padding=(20, 18))
        card.pack(fill="x")
        c = card.content
        c.columnconfigure(1, weight=1)
        img = theme.app_icon_image(56)
        if img:
            pic = tk.Label(c, image=img, bg=W.bg_of(c))
            pic.image = img
            pic.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, px(16)))
        W.label(c, f"{self.app.bot_name()} — панель управления", "subtitle").grid(row=0, column=1, sticky="sw")
        W.label(c, self._details(), "caption", "text2").grid(row=1, column=1, sticky="nw", pady=(px(4), 0))
        self.b_copy = W.button(c, "Копировать сведения", self.copy_info, icon="copy")
        self.b_copy.grid(row=0, column=2, rowspan=2, sticky="e", padx=(px(12), 0))

    @staticmethod
    def _details() -> str:
        version = version_text()
        parts = [f"Версия кода от {version}" if version else "Локальная сборка",
                 f"Python {platform.python_version()}", os_name()]
        return " · ".join(p for p in parts if p)

    def _build_theme(self):
        W.section(self.body, "Оформление программы")
        g = W.Group(self.body)
        row = g.row("Тема", "Меняется сразу и только для этой программы на этом компьютере.", "theme")
        W.Combo(row.right, THEMES, self.app.prefs.get("theme", "system"), self._theme_changed, 20).pack(side="left")

    def _build_links(self):
        W.section(self.body, "Ссылки")
        g = W.Group(self.body)
        row = g.row("Исходный код", "Репозиторий проекта на GitHub.", "code")
        W.button(row.right, "Открыть", lambda: state.open_url(REPO), icon="open").pack(side="left")
        row = g.row("Инструкция", "Подробное описание функций и настройки бота.", "help")
        W.button(row.right, "Открыть", self.open_readme, icon="open").pack(side="left")
        row = g.row("Портал разработчика Discord", "Здесь меняются имя, аватар и ключ бота.", "globe")
        W.button(row.right, "Открыть", lambda: state.open_url(PORTAL), icon="open").pack(side="left")

    def _build_licenses(self):
        W.section(self.body, "Лицензии")
        g = W.Group(self.body)
        row = g.row("Программа", "Лицензия MIT", "document")
        W.button(row.right, "Показать", lambda: self.show_license("Лицензия MIT", "LICENSE")).pack(side="left")
        row = g.row("Шрифт Inter", "SIL Open Font License 1.1", "font")
        W.button(row.right, "Показать", lambda: self.show_license("SIL Open Font License 1.1", "assets", "fonts",
                                                                  "Inter-OFL.txt")).pack(side="left")
        g.row("Значки Segoe Fluent Icons", "Входят в состав Windows", "picture")

    # ---------- действия ----------
    def _theme_changed(self, mode):
        if not mode or mode == self.app.prefs.get("theme", "system"):
            return
        app = self.app

        def apply():  # после обработки выбора: смена темы пересобирает окно вместе с этим разделом
            app.set_theme(mode)
            try:
                state.save_prefs(app.prefs)
            except OSError:
                pass
        app.after_idle(apply)

    def copy_info(self):
        version = state.local_version()
        lines = [f"{self.app.bot_name()} — панель управления",
                 f"Версия кода: {version_text()} ({version})" if version else "Версия кода: локальная сборка",
                 f"Python {platform.python_version()}", f"{os_name()} ({platform.version()})"]
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self.b_copy.configure(text=" Скопировано")
        self.after(2000, lambda: self.b_copy.winfo_exists() and self.b_copy.configure(text=" Копировать сведения"))

    def open_readme(self):
        path = os.path.join(state.APP, "README.md")
        if not os.path.exists(path):
            self.app.notify("info", "Инструкции нет на этом компьютере", "Её можно прочитать на GitHub.",
                            actions=[("Открыть GitHub", lambda: state.open_url(REPO))], timeout=8000)
            return
        try:
            state.open_path(path)
        except OSError as e:
            self.app.notify("error", "Не удалось открыть инструкцию", f"{e}")

    def show_license(self, title: str, *parts: str):
        try:
            with open(os.path.join(state.APP, *parts), encoding="utf-8-sig") as f:
                text = f.read()
        except OSError:
            self.app.notify("warning", "Файл лицензии не найден", "Текст лицензии есть в репозитории на GitHub.",
                            actions=[("Открыть GitHub", lambda: state.open_url(REPO))], timeout=8000)
            return
        TextDialog(self.app, title, text).show()
