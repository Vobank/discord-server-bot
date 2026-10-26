"""Компоненты интерфейса в стиле Windows 11: карточки, строки настроек, раскрывающиеся блоки, уведомления,
кнопки, переключатели, поля ввода, таблицы, диалоги.

Правила: цвета — только через theme.C(...), отступы — через px(...), шрифты — theme.font(...).
Контролы сами подбирают стиль под фон родителя (страница, карточка или вложенный блок).
"""
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import colorchooser, ttk

from . import state
from .theme import C, font, glyph, icon_font, icon_image, px

ICON_COLORS = {"info": "info", "success": "success", "warning": "warning", "error": "error"}
INFO_ICONS = {"info": "info", "success": "completed", "warning": "warning", "error": "error"}


def bg_of(widget) -> str:
    try:
        return widget.cget("bg")
    except tk.TclError:
        return C("bg")


def prefix_for(parent) -> str:
    """Префикс стиля ttk под фон родителя: '', 'Card.' или 'Card2.'."""
    bg = bg_of(parent)
    if bg == C("card"):
        return "Card."
    if bg == C("card2"):
        return "Card2."
    return ""


def label(parent, text="", role="body", color="text", wrap=None, anchor="w", justify="left", **kw):
    lb = tk.Label(parent, text=text, font=font(role), fg=C(color), bg=bg_of(parent), anchor=anchor,
                  justify=justify, **kw)
    if wrap:
        lb.configure(wraplength=px(wrap))
    return lb


def icon_label(parent, name, size=16, color="text", **kw):
    return tk.Label(parent, text=glyph(name), font=icon_font(size), fg=C(color), bg=bg_of(parent), **kw)


def autowrap(lb: tk.Label, margin: int = 0):
    """Перенос строк по ширине родителя (для описаний, которые растягиваются вместе с окном)."""
    def on_resize(e):
        width = max(px(120), e.width - margin)
        if abs(int(lb.cget("wraplength") or 0) - width) > 4:
            lb.configure(wraplength=width)
    lb.master.bind("<Configure>", on_resize, add="+")


class Tooltip:
    def __init__(self, widget, text: str):
        self.widget, self.text, self.tip, self.job = widget, text, None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _):
        self.job = self.widget.after(600, self._show)

    def _show(self):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + px(8)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + px(6)
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        frame = tk.Frame(self.tip, bg=C("border"))
        frame.pack()
        tk.Label(frame, text=self.text, font=font("caption"), fg=C("text"), bg=C("card"), justify="left",
                 wraplength=px(320), padx=px(8), pady=px(5)).pack(padx=1, pady=1)

    def _hide(self, _=None):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


# ---------- раскладка страницы ----------
class Scroll(tk.Frame):
    """Прокручиваемая область. Содержимое — в .body; ширина содержимого ограничена, как в «Параметрах» Windows."""

    def __init__(self, parent, max_width: int = 1040, pad_x: int = 36):
        super().__init__(parent, bg=C("bg"))
        self.canvas = tk.Canvas(self, bg=C("bg"), highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=C("bg"))
        self.win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.max_width, self.pad_x = px(max_width), px(pad_x)
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_resize)
        # колесо мыши обрабатывает окно программы (App._on_wheel) и передаёт сюда — см. _wheel

    def _on_resize(self, e):
        width = min(e.width - 2 * self.pad_x, self.max_width)
        x = max(self.pad_x, (e.width - width) // 2)
        self.canvas.coords(self.win, x, 0)
        self.canvas.itemconfigure(self.win, width=width)

    def _on_scroll(self, first, last):
        self.bar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self.bar.pack_forget()
        elif not self.bar.winfo_ismapped():
            self.bar.pack(side="right", fill="y")

    def _wheel(self, e):
        w = e.widget
        while w is not None:  # у таблиц и текстовых полей своя прокрутка
            if isinstance(w, (ttk.Treeview, tk.Text, tk.Listbox)):
                return
            if w is self:
                break
            w = getattr(w, "master", None)
        if self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(int(-e.delta / 120) * 3, "units")

    def to_top(self):
        self.canvas.yview_moveto(0)


def page_header(parent, title: str, description: str = ""):
    box = tk.Frame(parent, bg=bg_of(parent))
    box.pack(fill="x", pady=(px(28), px(18)))
    label(box, title, "title").pack(anchor="w")
    if description:
        d = label(box, description, "body", "text2")
        d.pack(anchor="w", fill="x", pady=(px(6), 0))
        autowrap(d)
    return box


def section(parent, title: str, description: str = ""):
    """Подзаголовок группы настроек."""
    box = tk.Frame(parent, bg=bg_of(parent))
    box.pack(fill="x", pady=(px(22), px(8)))
    label(box, title, "strong").pack(anchor="w")
    if description:
        d = label(box, description, "caption", "text2")
        d.pack(anchor="w", fill="x", pady=(px(2), 0))
        autowrap(d)
    return box


def spacer(parent, height: int = 8):
    tk.Frame(parent, bg=bg_of(parent), height=px(height)).pack(fill="x")


class Card(tk.Frame):
    """Карточка с рамкой. Содержимое — в .inner (отступы внутри уже есть)."""

    def __init__(self, parent, padding=(18, 16), bg="card"):
        super().__init__(parent, bg=C("border"))
        self.inner = tk.Frame(self, bg=C(bg))
        self.inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.content = tk.Frame(self.inner, bg=C(bg))
        self.content.pack(fill="both", expand=True, padx=px(padding[0]), pady=px(padding[1]))


class Row(tk.Frame):
    """Строка настройки: иконка, название и описание слева, контролы справа (в .right).
    Если места мало, контролы сами переезжают под текст — как в «Параметрах» Windows."""

    TEXT_MIN = 300  # уже этого (при 100 %) текст не сжимаем — контролы уходят вниз

    def __init__(self, parent, title: str, description: str = "", icon: str | None = None, bg="card",
                 indent: int = 0):
        super().__init__(parent, bg=C(bg))
        self.columnconfigure(1, weight=1)
        self.icon_pad = px(18 + indent)
        if icon:
            self.icon = icon_label(self, icon, 18)
            self.icon.grid(row=0, column=0, padx=(self.icon_pad, 0), sticky="w")
            self.text_pad = px(16)
        else:
            self.icon = None
            self.text_pad = self.icon_pad
        self.text = tk.Frame(self, bg=C(bg))
        self.text.grid(row=0, column=1, sticky="we", padx=(self.text_pad, px(16)), pady=px(13))
        self.title = label(self.text, title, "body")
        self.title.pack(anchor="w")
        self.desc = None
        if description:
            self.set_description(description)
        self.right = tk.Frame(self, bg=C(bg))
        self.right.grid(row=0, column=2, sticky="e", padx=(0, px(18)))
        self.bg_key = bg
        self.stacked = False
        self.bind("<Configure>", self._relayout, add="+")
        self.right.bind("<Configure>", self._relayout, add="+")

    def _left_width(self) -> int:
        return (self.icon_pad + self.icon.winfo_reqwidth() if self.icon else 0) + self.text_pad + px(16)

    def _relayout(self, _=None):
        width = self.winfo_width()
        if width <= 1:
            return
        right_w = self.right.winfo_reqwidth() if self.right.winfo_children() else 0
        text_space = width - self._left_width() - right_w - px(18)
        stack = bool(right_w) and text_space < px(self.TEXT_MIN)
        if stack != self.stacked:
            self.stacked = stack
            if stack:
                self.text.grid_configure(pady=(px(13), px(8)))
                self.right.grid_configure(row=1, column=1, columnspan=2, sticky="w",
                                          padx=(self.text_pad, px(18)), pady=(0, px(14)))
            else:
                self.text.grid_configure(pady=px(13))
                self.right.grid_configure(row=0, column=2, columnspan=1, sticky="e", padx=(0, px(18)), pady=0)
        if self.desc is not None:
            avail = width - self._left_width() - px(18) if stack else max(px(140), text_space)
            if abs(int(self.desc.cget("wraplength") or 0) - avail) > 3:
                self.desc.configure(wraplength=avail)

    def set_description(self, text: str):
        if self.desc is None:
            self.desc = label(self.text, "", "caption", "text2")
            self.desc.pack(anchor="w", fill="x", pady=(px(2), 0))
        self.desc.configure(text=text)
        self.after_idle(self._relayout)


class Group(tk.Frame):
    """Карточка из нескольких строк с разделителями."""

    def __init__(self, parent, bg="card"):
        super().__init__(parent, bg=C("border"))
        self.inner = tk.Frame(self, bg=C(bg))
        self.inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.bg_key, self.count = bg, 0
        self.pack(fill="x", pady=(0, px(4)))

    def _divider(self):
        if self.count:
            tk.Frame(self.inner, height=1, bg=C("divider")).pack(fill="x")
        self.count += 1

    def row(self, title: str, description: str = "", icon: str | None = None, indent: int = 0) -> Row:
        self._divider()
        r = Row(self.inner, title, description, icon, self.bg_key, indent)
        r.pack(fill="x")
        return r

    def block(self, padding=(18, 14)) -> tk.Frame:
        """Произвольное содержимое внутри группы (таблица, текст, список)."""
        self._divider()
        outer = tk.Frame(self.inner, bg=C(self.bg_key))
        outer.pack(fill="x")
        f = tk.Frame(outer, bg=C(self.bg_key))
        f.pack(fill="both", expand=True, padx=px(padding[0]), pady=px(padding[1]))
        return f


class Expander(tk.Frame):
    """Раскрывающийся блок: заголовок как у строки настройки (в .right можно положить переключатель),
    вложенные строки — через .row(...)."""

    def __init__(self, parent, title: str, description: str = "", icon: str | None = None, expanded=False,
                 on_toggle=None):
        super().__init__(parent, bg=C("border"))
        self.inner = tk.Frame(self, bg=C("card"))
        self.inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.header = Row(self.inner, title, description, icon, "card")
        self.header.pack(fill="x")
        self.right = tk.Frame(self.header.right, bg=C("card"))
        self.right.pack(side="left")
        self.chevron = tk.Label(self.header.right, text=glyph("down"), font=icon_font(12), fg=C("text2"),
                                bg=C("card"), cursor="hand2", padx=px(6))
        self.chevron.pack(side="left", padx=(px(10), 0))
        self.body = tk.Frame(self.inner, bg=C("card2"))
        self.count = 0
        self.expanded = False
        self.on_toggle = on_toggle
        for w in (self.header, self.header.text, self.header.title, self.chevron, self.header.icon, self.header.desc):
            if w is not None:
                w.bind("<Button-1>", lambda e: self.toggle(), add="+")
        self.header.configure(cursor="hand2")
        self.pack(fill="x", pady=(0, px(4)))
        if expanded:
            self.toggle()

    def toggle(self, value: bool | None = None):
        self.expanded = (not self.expanded) if value is None else value
        if self.expanded:
            self.body.pack(fill="x")
            self.chevron.configure(text=glyph("up"))
        else:
            self.body.pack_forget()
            self.chevron.configure(text=glyph("down"))
        if self.on_toggle:
            self.on_toggle(self.expanded)

    def row(self, title: str, description: str = "", icon: str | None = None) -> Row:
        tk.Frame(self.body, height=1, bg=C("divider")).pack(fill="x")
        r = Row(self.body, title, description, icon, "card2", indent=36 if not icon else 0)
        r.pack(fill="x")
        self.count += 1
        return r

    def block(self, padding=(54, 14)) -> tk.Frame:
        tk.Frame(self.body, height=1, bg=C("divider")).pack(fill="x")
        f = tk.Frame(self.body, bg=C("card2"))
        f.pack(fill="x", padx=(px(padding[0]), px(18)), pady=px(padding[1]))
        self.count += 1
        return f


# ---------- кнопки и мелочи ----------
def button(parent, text: str, command=None, kind: str = "default", icon: str | None = None, width=None,
           tooltip: str | None = None) -> ttk.Button:
    """kind: default, accent. Иконка — имя из theme.ICONS."""
    style = prefix_for(parent) + ("Accent.TButton" if kind == "accent" else "TButton")
    img = icon_image(icon, 16, C("on_accent") if kind == "accent" else C("text")) if icon else None
    b = ttk.Button(parent, text=(" " + text) if img and text else text, command=command, style=style,
                   takefocus=True)
    if img:
        b.configure(image=img, compound="left")
        b.image = img
    if width:
        b.configure(width=width)
    if tooltip:
        Tooltip(b, tooltip)
    return b


class IconButton(tk.Label):
    """Маленькая кнопка-иконка без рамки (как в панели инструментов)."""

    def __init__(self, parent, icon: str, command=None, tooltip: str = "", size: int = 14, color="text"):
        self.base = bg_of(parent)
        super().__init__(parent, text=glyph(icon), font=icon_font(size), fg=C(color), bg=self.base,
                         padx=px(8), pady=px(6), cursor="hand2")
        self.command = command
        self.enabled = True
        self.bind("<Enter>", lambda e: self.enabled and self.configure(bg=C("hover")))
        self.bind("<Leave>", lambda e: self.configure(bg=self.base))
        self.bind("<Button-1>", lambda e: self.enabled and self.command and self.command())
        if tooltip:
            Tooltip(self, tooltip)

    def set_enabled(self, on: bool):
        self.enabled = on
        self.configure(fg=C("text") if on else C("text3"), cursor="hand2" if on else "arrow")


class LinkButton(tk.Label):
    def __init__(self, parent, text: str, command=None, role="body"):
        super().__init__(parent, text=text, font=font(role), fg=C("link"), bg=bg_of(parent), cursor="hand2")
        self.bind("<Button-1>", lambda e: command and command())
        self.bind("<Enter>", lambda e: self.configure(font=self._underlined(role)))
        self.bind("<Leave>", lambda e: self.configure(font=font(role)))

    @staticmethod
    def _underlined(role):
        f = font(role).copy()
        f.configure(underline=True)
        LinkButton._fonts = getattr(LinkButton, "_fonts", []) + [f]
        return f


class Dot(tk.Canvas):
    """Цветной индикатор состояния."""

    def __init__(self, parent, color="idle", size: int = 10):
        s = px(size)
        super().__init__(parent, width=s, height=s, bg=bg_of(parent), highlightthickness=0, bd=0)
        self.oval = self.create_oval(1, 1, s - 1, s - 1, fill=C(color), outline="")

    def set(self, color: str):
        self.itemconfigure(self.oval, fill=C(color) if not color.startswith("#") else color)


class Pill(tk.Label):
    """Короткая метка-статус: «Работает», «Резерв», «Вручную»."""

    def __init__(self, parent, text: str, kind: str = "info"):
        super().__init__(parent, text=text, font=font("caption_strong"), padx=px(8), pady=px(1))
        self.set(text, kind)

    def set(self, text: str, kind: str = "info"):
        if kind == "neutral":
            self.configure(text=text, fg=C("text2"), bg=C("hover"))
        else:
            self.configure(text=text, fg=C(kind), bg=C(kind + "_bg"))


class Meter(tk.Canvas):
    """Полоска заполнения (нагрузка ПК и т.п.)."""

    def __init__(self, parent, width: int = 120, height: int = 6):
        self.w, self.h = px(width), px(height)
        super().__init__(parent, width=self.w, height=self.h, bg=bg_of(parent), highlightthickness=0, bd=0)
        r = self.h
        self.create_rectangle(0, 0, self.w, self.h, fill=C("track"), outline="")
        self.fill = self.create_rectangle(0, 0, 0, self.h, fill=C("accent"), outline="")
        self.r = r

    def set(self, value: float | None, color: str | None = None):
        value = 0 if value is None else max(0.0, min(100.0, float(value)))
        self.coords(self.fill, 0, 0, self.w * value / 100, self.h)
        if color is None:
            color = "success" if value < 60 else ("warning" if value < 85 else "error")
        self.itemconfigure(self.fill, fill=C(color))


def divider(parent, pady: int = 0):
    tk.Frame(parent, height=1, bg=C("divider")).pack(fill="x", pady=px(pady))


# ---------- поля ввода ----------
class Switch(tk.Frame):
    """Переключатель «Вкл./Откл.» как в «Параметрах» Windows."""

    def __init__(self, parent, value: bool = False, command=None, labels=("Вкл.", "Откл.")):
        super().__init__(parent, bg=bg_of(parent))
        self.var = tk.BooleanVar(value=bool(value))
        self.labels = labels
        self.text = label(self, "", "body", "text")
        self.text.pack(side="left", padx=(0, px(10)))
        self.check = ttk.Checkbutton(self, variable=self.var, style=prefix_for(parent) + "Switch.TCheckbutton",
                                     command=self._changed, takefocus=True)
        self.check.pack(side="left")
        self.command = command
        self._update_text()

    def _update_text(self):
        self.text.configure(text=self.labels[0] if self.var.get() else self.labels[1])

    def _changed(self):
        self._update_text()
        if self.command:
            self.command(self.var.get())

    def get(self) -> bool:
        return bool(self.var.get())

    def set(self, value: bool):
        self.var.set(bool(value))
        self._update_text()

    def set_enabled(self, on: bool):
        self.check.state(["!disabled"] if on else ["disabled"])


class Entry(tk.Frame):
    """Поле ввода с подсказкой (placeholder), режимом пароля и проверкой значения."""

    def __init__(self, parent, value: str = "", width: int = 28, placeholder: str = "", secret: bool = False,
                 command=None, validate=None, justify="left"):
        super().__init__(parent, bg=bg_of(parent))
        self.placeholder, self.secret, self.command, self.validate = placeholder, secret, command, validate
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=width, style=prefix_for(parent) + "TEntry",
                               font=font("body"), justify=justify)
        self.entry.pack(side="left", fill="x", expand=True)
        self.showing_placeholder = False
        self.revealed = False
        if secret:
            self.eye = IconButton(self, "eye", self.toggle_reveal, "Показать / скрыть", 13, "text2")
            self.eye.pack(side="left", padx=(px(2), 0))
        self.entry.bind("<FocusIn>", self._focus_in)
        self.entry.bind("<FocusOut>", self._focus_out)
        self._set_text(value or "")
        self.var.trace_add("write", self._on_write)

    def _apply_show(self):
        if self.secret and not self.revealed and not self.showing_placeholder:
            self.entry.configure(show="•")
        else:
            self.entry.configure(show="")

    def _set_text(self, value: str):
        self._muted = True
        self.var.set(value)
        self._muted = False
        if not value and self.placeholder and self.focus_get() is not self.entry:
            self._show_placeholder()
        else:
            self.showing_placeholder = False
            self.entry.configure(foreground=C("text"))
            self._apply_show()

    def _show_placeholder(self):
        self._muted = True
        self.showing_placeholder = True
        self.var.set(self.placeholder)
        self.entry.configure(foreground=C("text3"))
        self._apply_show()
        self._muted = False

    def _focus_in(self, _):
        if self.showing_placeholder:
            self._muted = True
            self.var.set("")
            self._muted = False
            self.showing_placeholder = False
            self.entry.configure(foreground=C("text"))
            self._apply_show()

    def _focus_out(self, _):
        if not self.var.get() and self.placeholder:
            self._show_placeholder()

    def _on_write(self, *_):
        if getattr(self, "_muted", False) or self.showing_placeholder:
            return
        value = self.var.get()
        ok = True
        if self.validate:
            ok = self.validate(value)
            self.entry.state(["!invalid"] if ok else ["invalid"])
        if ok and self.command:
            self.command(value)

    def toggle_reveal(self):
        self.revealed = not self.revealed
        self._apply_show()
        self.eye.configure(text=glyph("hide" if self.revealed else "eye"))

    def get(self) -> str:
        return "" if self.showing_placeholder else self.var.get()

    def set(self, value: str):
        self._set_text(value or "")

    def set_enabled(self, on: bool):
        self.entry.state(["!disabled"] if on else ["disabled"])


class Combo(ttk.Combobox):
    """Выпадающий список. options — [(значение, подпись), …]; хранит значение, показывает подпись."""

    def __init__(self, parent, options, value=None, command=None, width: int = 24):
        self.options = list(options)
        super().__init__(parent, values=[lbl for _, lbl in self.options], state="readonly", width=width,
                         style=prefix_for(parent) + "TCombobox", font=font("body"))
        self.command = command
        self.set_value(value)
        self.bind("<<ComboboxSelected>>", self._changed)

    def set_value(self, value):
        for v, lbl in self.options:
            if v == value:
                self.set(lbl)
                return
        if self.options and value is None:
            self.set(self.options[0][1])
        elif value is not None:  # значения нет в списке — показываем как есть
            self.options.append((value, str(value)))
            self.configure(values=[lbl for _, lbl in self.options])
            self.set(str(value))

    def get_value(self):
        text = self.get()
        return next((v for v, lbl in self.options if lbl == text), None)

    def _changed(self, _=None):
        self.selection_clear()
        if self.command:
            self.command(self.get_value())


class Spin(ttk.Spinbox):
    """Число в диапазоне."""

    def __init__(self, parent, value=0, frm: float = 0, to: float = 100, step: float = 1, command=None,
                 width: int = 7, is_float: bool = False):
        self.var = tk.StringVar(value=str(value))
        super().__init__(parent, from_=frm, to=to, increment=step, textvariable=self.var, width=width,
                         style=prefix_for(parent) + "TSpinbox", font=font("body"))
        self.frm, self.to, self.command, self.is_float = frm, to, command, is_float
        self.var.trace_add("write", self._changed)

    def parse(self):
        text = self.var.get().strip().replace(",", ".")
        try:
            v = float(text) if self.is_float else int(text)
        except ValueError:
            return None
        return v if self.frm <= v <= self.to else None

    def _changed(self, *_):
        v = self.parse()
        self.state(["!invalid"] if v is not None else ["invalid"])
        if v is not None and self.command:
            self.command(v)


class ColorButton(tk.Frame):
    """Образец цвета + HEX; по нажатию — выбор цвета."""

    def __init__(self, parent, value: str = "#5865F2", command=None, title="Выбор цвета"):
        super().__init__(parent, bg=bg_of(parent))
        self.value, self.command, self.title = value, command, title
        s = px(28)
        self.swatch = tk.Canvas(self, width=s, height=s, bg=bg_of(parent), highlightthickness=0, cursor="hand2")
        self.rect = self.swatch.create_rectangle(1, 1, s - 1, s - 1, outline=C("border"), width=1)
        self.swatch.pack(side="left")
        self.text = label(self, "", "body", "text2", cursor="hand2")
        self.text.pack(side="left", padx=(px(10), 0))
        for w in (self.swatch, self.text):
            w.bind("<Button-1>", lambda e: self.pick())
        self.set(value)

    def set(self, value: str):
        value = (value or "#000000").upper()
        if not value.startswith("#"):
            value = "#" + value
        self.value = value
        try:
            self.swatch.itemconfigure(self.rect, fill=value)
        except tk.TclError:
            pass
        self.text.configure(text=value)

    def pick(self):
        _, hx = colorchooser.askcolor(self.value, title=self.title, parent=self.winfo_toplevel())
        if hx:
            self.set(hx)
            if self.command:
                self.command(self.value)


# ---------- таблица и редактор списков ----------
class Table(tk.Frame):
    """Таблица: columns — [(ключ, заголовок, ширина), …]. Строки — кортежи значений."""

    def __init__(self, parent, columns, height: int = 6, on_double=None, on_select=None):
        super().__init__(parent, bg=C("border"))
        inner = tk.Frame(self, bg=C("card"))
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.columns = columns
        self.tree = ttk.Treeview(inner, columns=[c[0] for c in columns], show="headings", height=height,
                                 selectmode="browse")
        for key, title, width in columns:
            self.tree.heading(key, text=title, anchor="w")
            self.tree.column(key, width=px(width), minwidth=px(40), anchor="w", stretch=True)
        bar = ttk.Scrollbar(inner, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        if on_double:
            self.tree.bind("<Double-1>", lambda e: self.selected() is not None and on_double())
            self.tree.bind("<Return>", lambda e: self.selected() is not None and on_double())
        if on_select:
            self.tree.bind("<<TreeviewSelect>>", lambda e: on_select())

    def set_rows(self, rows, select: int | None = None):
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(rows):
            self.tree.insert("", "end", iid=str(i), values=["" if v is None else v for v in row])
        if select is not None and 0 <= select < len(rows):
            self.tree.selection_set(str(select))
            self.tree.see(str(select))

    def selected(self) -> int | None:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None


class ListEditor(tk.Frame):
    """Редактор списка (игры, роли за уровни, достижения…): таблица + «Добавить / Изменить / Удалить / ↑ / ↓».

    page — страница (для get/set черновика), path — путь в черновике («s:games»);
    columns — колонки таблицы; fields — поля формы (см. FormDialog);
    to_row(item) → кортеж для таблицы; to_form(item) → dict для формы; from_form(dict, old_item) → элемент;
    new() → значения формы для нового элемента."""

    def __init__(self, parent, page, path: str, columns, fields, to_row, to_form, from_form, new=None,
                 noun: str = "элемент", height: int = 6, reorder: bool = True, on_change=None, validate=None):
        super().__init__(parent, bg=bg_of(parent))
        self.page, self.path = page, path
        self.fields, self.to_row, self.to_form, self.from_form = fields, to_row, to_form, from_form
        self.new, self.noun, self.on_change, self.validate = new, noun, on_change, validate
        bar = tk.Frame(self, bg=bg_of(parent))
        bar.pack(fill="x", pady=(0, px(8)))
        button(bar, "Добавить", self.add, "default", "add").pack(side="left")
        self.b_edit = button(bar, "Изменить", self.edit, "default", "edit")
        self.b_edit.pack(side="left", padx=(px(6), 0))
        self.b_del = button(bar, "Удалить", self.delete, "default", "delete")
        self.b_del.pack(side="left", padx=(px(6), 0))
        if reorder:
            self.b_down = IconButton(bar, "down", lambda: self.move(1), "Ниже")
            self.b_down.pack(side="right")
            self.b_up = IconButton(bar, "up", lambda: self.move(-1), "Выше")
            self.b_up.pack(side="right")
        self.count_label = label(bar, "", "caption", "text3")
        self.count_label.pack(side="right", padx=px(10))
        self.table = Table(self, columns, height, on_double=self.edit, on_select=self._sync_buttons)
        self.table.pack(fill="both", expand=True)
        self.tree = self.table.tree
        self.tree.bind("<Delete>", lambda e: self.delete())
        self.refresh()

    def items(self) -> list:
        return self.page.get(self.path, []) or []

    def refresh(self, select: int | None = None):
        items = self.items()
        self.table.set_rows([self.to_row(x) for x in items], select)
        self.count_label.configure(text=f"Всего: {len(items)}")
        self._sync_buttons()

    def _sync_buttons(self):
        has = self.table.selected() is not None
        for b in (self.b_edit, self.b_del):
            b.state(["!disabled"] if has else ["disabled"])

    def _store(self, items, select=None):
        self.page.set(self.path, items)
        self.refresh(select)
        if self.on_change:
            self.on_change(items)

    def add(self):
        values = self.new() if self.new else {}
        data = FormDialog(self.page.app, f"Добавить: {self.noun}", self.fields, values, ok="Добавить",
                          validate=self.validate).show()
        if data is not None:
            items = self.items()
            items.append(self.from_form(data, None))
            self._store(items, len(items) - 1)

    def edit(self):
        i = self.table.selected()
        if i is None:
            return
        items = self.items()
        data = FormDialog(self.page.app, f"Изменить: {self.noun}", self.fields, self.to_form(items[i]),
                          ok="Сохранить", validate=self.validate).show()
        if data is not None:
            items[i] = self.from_form(data, items[i])
            self._store(items, i)

    def delete(self):
        i = self.table.selected()
        if i is None:
            return
        items = self.items()
        del items[i]
        self._store(items, min(i, len(items) - 1) if items else None)

    def move(self, step: int):
        i = self.table.selected()
        if i is None:
            return
        items = self.items()
        j = i + step
        if 0 <= j < len(items):
            items[i], items[j] = items[j], items[i]
            self._store(items, j)


# ---------- уведомления ----------
class InfoBar(tk.Frame):
    """Полоса-уведомление: kind — info, success, warning, error. actions — [(текст, функция), …]."""

    def __init__(self, parent, kind: str, title: str, message: str = "", actions=None, closable=True,
                 on_close=None):
        super().__init__(parent, bg=C("border"))
        self.kind = kind
        inner = tk.Frame(self, bg=C(kind + "_bg"))
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        inner.columnconfigure(1, weight=1)
        tk.Label(inner, text=glyph(INFO_ICONS[kind]), font=icon_font(16), fg=C(kind), bg=C(kind + "_bg")).grid(
            row=0, column=0, sticky="n", padx=(px(16), px(12)), pady=px(13))
        text = tk.Frame(inner, bg=C(kind + "_bg"))
        text.grid(row=0, column=1, sticky="we", pady=px(12))
        self.title_label = tk.Label(text, text=title, font=font("strong"), fg=C("text"), bg=C(kind + "_bg"),
                                    justify="left", anchor="w")
        self.title_label.pack(fill="x")
        self.message_label = None
        if message:
            msg = self.message_label = tk.Label(text, text=message, font=font("body"), fg=C("text"),
                                                bg=C(kind + "_bg"), justify="left", anchor="w")
            msg.pack(fill="x", pady=(px(2), 0))
        text.bind("<Configure>", lambda e: [w.configure(wraplength=max(px(160), e.width))
                                            for w in (self.title_label, self.message_label) if w], add="+")
        right = tk.Frame(inner, bg=C(kind + "_bg"))
        right.grid(row=0, column=2, sticky="e", padx=(px(8), px(8)))
        for text_, fn in actions or []:
            ttk.Button(right, text=text_, command=lambda f=fn: (f(), self.close())).pack(side="left", padx=px(4))
        if closable:
            close = tk.Label(right, text=glyph("close"), font=icon_font(11), fg=C("text2"), bg=C(kind + "_bg"),
                             cursor="hand2", padx=px(8), pady=px(6))
            close.pack(side="left")
            close.bind("<Button-1>", lambda e: self.close())
        self.on_close = on_close

    def close(self):
        if self.winfo_exists():
            self.destroy()
        if self.on_close:
            self.on_close(self)


# ---------- диалоги ----------
class Modal(tk.Toplevel):
    """Модальное окно в стиле Windows 11: заголовок, содержимое (.content), подвал с кнопками (.footer)."""

    def __init__(self, app, title: str, width: int = 520):
        super().__init__(app)
        self.app = app
        self.withdraw()
        self.title(title)
        self.configure(bg=C("bg"))
        self.resizable(False, False)
        self.transient(app)
        try:
            from . import theme
            theme.dark_title_bar(self, theme.STATE["mode"] == "dark")
            if getattr(app, "icon_photo", None):
                self.iconphoto(False, app.icon_photo)
        except Exception:
            pass
        self.result = None
        self.body = tk.Frame(self, bg=C("bg"))
        self.body.pack(fill="both", expand=True, padx=px(24), pady=(px(22), px(18)))
        label(self.body, title, "subtitle").pack(anchor="w", pady=(0, px(12)))
        self.content = tk.Frame(self.body, bg=C("bg"), width=px(width))
        self.content.pack(fill="both", expand=True)
        self.footer_wrap = tk.Frame(self, bg=C("card2"))
        self.footer_wrap.pack(fill="x", side="bottom")
        tk.Frame(self.footer_wrap, height=1, bg=C("divider")).pack(fill="x")
        self.footer = tk.Frame(self.footer_wrap, bg=C("card2"))
        self.footer.pack(fill="x", padx=px(24), pady=px(16))
        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.width = width

    def add_buttons(self, ok: str | None = "OK", cancel: str | None = "Отмена", danger=False):
        if cancel:
            self.b_cancel = button(self.footer, cancel, self.cancel)
            self.b_cancel.pack(side="right")
        if ok:
            self.b_ok = button(self.footer, ok, self.accept, "accent")
            self.b_ok.pack(side="right", padx=(0, px(8)))
            self.bind("<Return>", lambda e: self.accept() if not isinstance(e.widget, tk.Text) else None)

    def accept(self):
        self.result = True
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()

    def show(self):
        self.update_idletasks()
        w = max(self.winfo_reqwidth(), px(self.width) + px(48))
        h = self.winfo_reqheight()
        x = self.app.winfo_rootx() + (self.app.winfo_width() - w) // 2
        y = self.app.winfo_rooty() + max(px(40), (self.app.winfo_height() - h) // 3)
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        self.grab_set()
        self.focus_set()
        self.wait_window()
        return self.result


class MessageDialog(Modal):
    def __init__(self, app, title: str, message: str, ok: str = "OK", cancel: str | None = "Отмена",
                 danger: bool = False, extra: tuple | None = None):
        super().__init__(app, title, 460)
        m = label(self.content, message, "body", "text", wrap=460)
        m.pack(anchor="w", fill="x")
        if extra:  # третья кнопка: (текст, значение результата)
            b = button(self.footer, extra[0], lambda: self._finish(extra[1]))
            b.pack(side="right", padx=(px(8), 0))
        self.add_buttons(ok, cancel, danger)

    def _finish(self, value):
        self.result = value
        self.destroy()


class FormDialog(Modal):
    """Форма. fields — список dict: key, label, kind (text, int, float, secret, color, bool, choice, multiline),
    choices [(значение, подпись)], placeholder, required, min, max, hint, width."""

    def __init__(self, app, title: str, fields, values=None, ok="Сохранить", validate=None):
        super().__init__(app, title, 520)
        self.fields, self.widgets, self.validate_all = fields, {}, validate
        values = values or {}
        grid = tk.Frame(self.content, bg=C("bg"))
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1)
        r = 0
        for f in fields:
            kind = f.get("kind", "text")
            if kind != "bool":
                label(grid, f["label"], "body").grid(row=r, column=0, sticky="w", pady=(px(10) if r else 0, px(4)))
                r += 1
            v = values.get(f["key"], f.get("default"))
            if kind in ("text", "secret"):
                w = Entry(grid, "" if v is None else str(v), f.get("width", 44), f.get("placeholder", ""),
                          kind == "secret")
            elif kind in ("int", "float"):
                w = Spin(grid, v if v is not None else f.get("min", 0), f.get("min", 0), f.get("max", 10 ** 9),
                         f.get("step", 1), width=f.get("width", 10), is_float=kind == "float")
            elif kind == "color":
                w = ColorButton(grid, v or "#5865F2")
            elif kind == "bool":
                w = ttk.Checkbutton(grid, text=f["label"], style="TCheckbutton")
                w.var = tk.BooleanVar(value=bool(v))
                w.configure(variable=w.var)
            elif kind == "choice":
                w = Combo(grid, f["choices"], v, width=f.get("width", 42))
            elif kind == "multiline":
                w = tk.Text(grid, height=f.get("height", 4), width=f.get("width", 52), font=font("body"),
                            bg=C("card"), fg=C("text"), insertbackground=C("text"), relief="flat",
                            highlightthickness=1, highlightbackground=C("border"), highlightcolor=C("accent"),
                            wrap="word", padx=px(8), pady=px(6))
                w.insert("1.0", "" if v is None else str(v))
            else:
                raise ValueError(f"неизвестный тип поля {kind}")
            w.grid(row=r, column=0, sticky="w" if kind in ("int", "float", "color", "bool") else "we",
                   pady=(px(6) if kind == "bool" else 0, 0))
            r += 1
            if f.get("hint"):
                label(grid, f["hint"], "caption", "text2", wrap=470).grid(row=r, column=0, sticky="w",
                                                                          pady=(px(4), 0))
                r += 1
            self.widgets[f["key"]] = (f, w)
        self.error = label(self.content, "", "caption", "error", wrap=470)
        self.error.pack(anchor="w", pady=(px(10), 0))
        self.add_buttons(ok, "Отмена")
        first = next(iter(self.widgets.values()), None)
        if first and isinstance(first[1], Entry):
            self.after(50, first[1].entry.focus_set)

    def values(self) -> dict | None:
        out = {}
        for key, (f, w) in self.widgets.items():
            kind = f.get("kind", "text")
            if kind in ("text", "secret"):
                v = w.get().strip() if f.get("strip", True) else w.get()
            elif kind in ("int", "float"):
                v = w.parse()
                if v is None:
                    self.error.configure(text=f"«{f['label']}»: нужно число от {f.get('min', 0)} до {f.get('max')}")
                    return None
            elif kind == "color":
                v = w.value
            elif kind == "bool":
                v = bool(w.var.get())
            elif kind == "choice":
                v = w.get_value()
            else:
                v = w.get("1.0", "end").rstrip("\n")
            if f.get("required") and (v is None or (isinstance(v, str) and not v.strip())):
                self.error.configure(text=f"Заполните поле «{f['label']}»")
                return None
            out[key] = v
        if self.validate_all:
            problem = self.validate_all(out)
            if problem:
                self.error.configure(text=problem)
                return None
        return out

    def accept(self):
        data = self.values()
        if data is not None:
            self.result = data
            self.destroy()


class TaskDialog(Modal):
    """Запуск служебной команды с живым журналом вывода. В песочнице команда не запускается."""

    def __init__(self, app, title: str, args: list[str], description: str = "", on_done=None,
                 success: str = "Готово", failure: str = "Не получилось"):
        super().__init__(app, title, 640)
        self.args, self.on_done, self.success, self.failure = args, on_done, success, failure
        if description:
            label(self.content, description, "body", "text2", wrap=640).pack(anchor="w", pady=(0, px(10)))
        status = tk.Frame(self.content, bg=C("bg"))
        status.pack(fill="x")
        self.status_icon = tk.Label(status, text="", font=icon_font(16), bg=C("bg"), fg=C("accent"))
        self.status_icon.pack(side="left")
        self.status_text = label(status, "Выполняется…", "body")
        self.status_text.pack(side="left", padx=(px(8), 0))
        self.progress = ttk.Progressbar(self.content, mode="indeterminate", length=px(640))
        self.progress.pack(fill="x", pady=(px(10), px(10)))
        self.progress.start(12)
        box = tk.Frame(self.content, bg=C("border"))
        box.pack(fill="both", expand=True)
        self.text = tk.Text(box, height=14, width=80, font=font("mono"), bg=C("code_bg"), fg=C("text"),
                            relief="flat", wrap="word", padx=px(10), pady=px(8), state="disabled",
                            insertbackground=C("text"))
        self.text.pack(fill="both", expand=True, padx=1, pady=1)
        self.b_copy = button(self.footer, "Копировать журнал", self.copy_log, icon="copy")
        self.b_copy.pack(side="left")
        self.b_close = button(self.footer, "Закрыть", self.cancel, "accent")
        self.b_close.pack(side="right")
        self.lines: queue.Queue = queue.Queue()
        self.code = None
        threading.Thread(target=self._run, daemon=True).start()
        self.after(100, self._pump)

    def _run(self):
        if state.SANDBOX:
            state.sandbox_note("команда: " + " ".join(self.args))
            self.lines.put("Песочница: команда не запускалась.\n" + " ".join(self.args) + "\n")
            self.code = 0
            return
        try:
            p = subprocess.Popen(self.args, cwd=state.APP, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace", creationflags=state.NO_WINDOW)
            for line in p.stdout:
                self.lines.put(line)
            self.code = p.wait()
        except Exception as e:
            self.lines.put(f"Ошибка запуска: {e}\n")
            self.code = -1

    def _pump(self):
        if not self.winfo_exists():
            return
        chunk = []
        while not self.lines.empty():
            chunk.append(self.lines.get())
        if chunk:
            self.text.configure(state="normal")
            self.text.insert("end", "".join(chunk))
            self.text.see("end")
            self.text.configure(state="disabled")
        if self.code is None or not self.lines.empty():
            self.after(120, self._pump)
            return
        self.progress.stop()
        self.progress.pack_forget()
        ok = self.code == 0
        self.status_icon.configure(text=glyph("completed" if ok else "error"), fg=C("success" if ok else "error"))
        self.status_text.configure(text=self.success if ok else self.failure)
        if self.on_done:
            self.on_done(ok, self.text.get("1.0", "end"))

    def copy_log(self):
        self.clipboard_clear()
        self.clipboard_append(self.text.get("1.0", "end").strip())
        self.b_copy.configure(text="Скопировано")

    def show(self):
        Modal.show(self)
        return self.code == 0 if self.code is not None else None
