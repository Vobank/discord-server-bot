"""Базовый класс страницы и привязка контролов к черновику настроек.

Страница наследует Page, задаёт key/title/icon/description и реализует build(). Всё, что меняет настройки,
идёт через self.set(путь, значение) или готовые bind_*: так работают «Сохранить / Отменить» внизу окна.

Пути: «s:bot.name» — settings.json, «e:DISCORD_TOKEN» — .env, «h:priority» — этот ПК (host.json),
«r:intro» — правила (rules.json), «x:banner» — баннер. Один путь — ровно в одном месте программы.
"""
import tkinter as tk

from .. import widgets as W
from ..theme import C, px


class Page(tk.Frame):
    key = ""
    title = ""
    icon = ""
    description = ""
    scroll = True  # False — страница сама управляет размером (журнал и т.п.)

    def __init__(self, app, parent):
        super().__init__(parent, bg=C("bg"))
        self.app = app
        if self.scroll:
            self.scroller = W.Scroll(self)
            self.scroller.pack(fill="both", expand=True)
            self.body = self.scroller.body
        else:
            self.scroller = None
            self.body = tk.Frame(self, bg=C("bg"))
            self.body.pack(fill="both", expand=True, padx=px(36))
        W.page_header(self.body, self.title, self.description)
        self.build()
        if self.scroll:
            W.spacer(self.body, 36)

    # --- переопределяется на страницах ---
    def build(self):
        raise NotImplementedError

    def on_show(self):
        """Страницу открыли (каждый раз)."""

    def on_status(self, status: dict | None):
        """Раз в 2 секунды: статус диспетчера (runtime/status.json) или None, если бот на этом ПК не запущен."""

    # --- черновик ---
    def get(self, path: str, default=None):
        return self.app.store.get(path, default)

    def saved(self, path: str, default=None):
        return self.app.store.get(path, default, saved=True)

    def set(self, path: str, value):
        if self.app.store.get(path) != value:
            self.app.store.set(path, value)
            self.app.changed()

    # --- готовые привязки (контрол сразу пишет в черновик) ---
    def bind_entry(self, parent, path: str, width: int = 30, kind: str = "str", placeholder: str = "",
                   secret: bool = False, strip: bool = True, minimum=None, maximum=None) -> W.Entry:
        """kind: str, int, float, id (ID Discord: цифры или пусто → None), list (через запятую)."""
        value = self.get(path)
        if kind == "list":
            text = ", ".join(str(x) for x in (value or []))
        elif value is None:
            text = ""
        else:
            text = str(value)

        def convert(raw: str):
            raw = raw.strip() if strip or kind != "str" else raw
            if kind == "str":
                return raw
            if kind == "list":
                return [x.strip() for x in raw.split(",") if x.strip()]
            if kind == "id":
                if not raw:
                    return None
                if not raw.isdigit() or not 15 <= len(raw) <= 21:
                    raise ValueError
                return int(raw)
            v = float(raw.replace(",", ".")) if kind == "float" else int(raw)
            if (minimum is not None and v < minimum) or (maximum is not None and v > maximum):
                raise ValueError
            return v

        def validate(raw: str) -> bool:
            try:
                convert(raw)
                return True
            except ValueError:
                return False

        e = W.Entry(parent, text, width, placeholder, secret, command=lambda raw: self.set(path, convert(raw)),
                    validate=validate)
        return e

    def bind_switch(self, parent, path: str, on_toggle=None, labels=("Вкл.", "Откл.")) -> W.Switch:
        def changed(v):
            self.set(path, bool(v))
            if on_toggle:
                on_toggle(bool(v))
        return W.Switch(parent, bool(self.get(path)), changed, labels)

    def bind_combo(self, parent, path: str, options, width: int = 26, on_change=None) -> W.Combo:
        def changed(v):
            self.set(path, v)
            if on_change:
                on_change(v)
        return W.Combo(parent, options, self.get(path), changed, width)

    def bind_spin(self, parent, path: str, frm=0, to=100, step=1, width: int = 7, is_float=False) -> W.Spin:
        value = self.get(path)
        return W.Spin(parent, value if value is not None else frm, frm, to, step, lambda v: self.set(path, v), width,
                      is_float)

    def bind_text(self, parent, path: str, height: int = 4, width: int = 60, lines: bool = False) -> tk.Text:
        """Многострочный текст. lines=True — значение хранится списком строк (пустые строки отбрасываются)."""
        value = self.get(path)
        text = "\n".join(value or []) if lines else (value or "")
        box = tk.Text(parent, height=height, width=width, font=W.font("body"), bg=C("card2") if W.bg_of(parent) ==
                      C("card") else C("card"), fg=C("text"), insertbackground=C("text"), relief="flat", wrap="word",
                      highlightthickness=1, highlightbackground=C("border"), highlightcolor=C("accent"),
                      padx=px(10), pady=px(8), undo=True)
        box.insert("1.0", text)
        box.edit_modified(False)

        def changed(_=None):
            if not box.edit_modified():
                return
            raw = box.get("1.0", "end-1c")
            self.set(path, [x.strip() for x in raw.splitlines() if x.strip()] if lines else raw)
            box.edit_modified(False)
        box.bind("<<Modified>>", changed)
        return box

    def bind_color(self, parent, path: str) -> W.ColorButton:
        return W.ColorButton(parent, self.get(path) or "#5865F2", lambda v: self.set(path, v))
