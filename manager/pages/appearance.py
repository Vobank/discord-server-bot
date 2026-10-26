"""Оформление: фон, цвета и надписи карточки нового участника (с живым предпросмотром) и карточек фильмов."""
import io
import os
import tkinter as tk
from tkinter import filedialog

from .. import state
from .. import widgets as W
from ..theme import C, px
from .base import Page

MISSING_BANNER = os.path.join(state.RUNTIME, "no-banner.png")  # несуществующий файл → стандартный фон


def rgb(hex_color: str) -> tuple:
    h = (hex_color or "#000000").lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else (0, 0, 0)


def sample_avatar() -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (256, 256))
    d = ImageDraw.Draw(img)
    for y in range(256):
        d.line([(0, y), (256, y)], fill=(90 + y // 4, 82, 200 - y // 3))
    d.ellipse((78, 50, 178, 150), fill=(236, 232, 255))
    d.ellipse((38, 160, 218, 330), fill=(236, 232, 255))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def render_cards(p: dict) -> tuple[bytes, bytes]:
    """Рисует обе карточки с черновыми значениями (в фоновом потоке)."""
    import config
    from cogs import film_card as fc
    from cogs import welcome_card as wc
    wc.ACCENT, wc.ACCENT2 = rgb(p["accent"]), rgb(p["accent2"])
    fc.ACCENT, fc.ACCENT2 = wc.ACCENT, wc.ACCENT2
    wc.BG_FILE = p["banner"]
    config.THEME["welcome_title"] = p["title"]
    config.THEME["welcome_subtitle"] = p["subtitle"]
    welcome = wc.render(sample_avatar(), "Новичок", 1, p["server"] or "Сервер")
    film = fc.render("Интерстеллар", ["Фантастика", "Драма"], "2014 · США, Великобритания · 2 ч 49 мин",
                     "ХОТЯТ ПОСМОТРЕТЬ ×3", None)
    return welcome, film


class View(Page):
    description = "Карточка нового участника и карточки фильмов."

    def build(self):
        self.job = None
        self.photos = []

        g = W.Group(self.body)
        blk = g.block(padding=(18, 18))
        self.preview = tk.Label(blk, bg=C("card"))
        self.preview.pack(anchor="w")
        self.film_preview = tk.Label(blk, bg=C("card"))
        self.film_preview.pack(anchor="w", pady=(px(12), 0))
        self.preview_note = W.label(blk, "Предпросмотр строится…", "caption", "text2")
        self.preview_note.pack(anchor="w", pady=(px(10), 0))

        W.section(self.body, "Фон")
        g = W.Group(self.body)
        row = g.row("Фоновое изображение", "PNG или JPG, лучше 1100 × 400. Без него рисуется фирменный ночной фон.",
                    "picture")
        self.banner_state = W.label(row.right, "", "caption", "text2")
        self.banner_state.pack(side="left", padx=(0, px(12)))
        W.button(row.right, "Выбрать…", self.pick, icon="folder").pack(side="left")
        self.b_remove = W.button(row.right, "Убрать", self.remove)
        self.b_remove.pack(side="left", padx=(px(8), 0))

        W.section(self.body, "Цвета", "Те же цвета используются в карточках фильмов.")
        g = W.Group(self.body)
        row = g.row("Основной цвет", "Рамка карточки и плашка с номером участника.", "color")
        self.bind_color(row.right, "s:theme.accent").pack(side="left")
        row = g.row("Второй цвет", "Свечение вокруг аватара и надпись над ником.", "color")
        self.bind_color(row.right, "s:theme.accent2").pack(side="left")

        W.section(self.body, "Надписи")
        g = W.Group(self.body)
        row = g.row("Надпись над ником", "Пишется заглавными буквами.", "font")
        self.bind_entry(row.right, "s:theme.welcome_title", 30).pack(side="left")
        row = g.row("Надпись под ником", "{server} заменяется названием сервера.", "font")
        self.bind_entry(row.right, "s:theme.welcome_subtitle", 30, strip=False).pack(side="left")

        W.spacer(self.body, 12)
        W.InfoBar(self.body, "info", "Когда применится",
                  "Новые карточки будут такими после сохранения и перезапуска бота.", closable=False).pack(fill="x")
        self._banner_state()
        self.schedule()

    def set(self, path, value):
        super().set(path, value)
        self._banner_state()
        self.schedule()

    def on_show(self):
        self.schedule()

    # ---------- фон ----------
    def _current_banner(self) -> str:
        return state.banner_path(self.app.store.draft["s"])

    def _banner_state(self):
        op = self.get("x:banner", "keep")
        if op == "remove":
            text, can_remove = "Будет стандартный фон", False
        elif op not in ("keep", "", None):
            text, can_remove = f"Новое: {os.path.basename(op)}", True
        elif os.path.exists(self._current_banner()):
            text, can_remove = "Своё изображение", True
        else:
            text, can_remove = "Стандартный фон", False
        self.banner_state.configure(text=text)
        self.b_remove.state(["!disabled"] if can_remove else ["disabled"])

    def pick(self):
        path = filedialog.askopenfilename(parent=self.winfo_toplevel(), title="Фоновое изображение",
                                          filetypes=[("Изображения", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if path:
            self.set("x:banner", path)

    def remove(self):
        if self.saved("x:banner", "keep") == "keep" and not os.path.exists(self._current_banner()):
            self.set("x:banner", "keep")
        else:
            self.set("x:banner", "remove")

    # ---------- предпросмотр ----------
    def schedule(self):
        if self.job:
            self.after_cancel(self.job)
        self.job = self.after(300, self.render)

    def render(self):
        self.job = None
        if not self.winfo_exists():
            return
        op = self.get("x:banner", "keep")
        if op == "remove":
            banner = MISSING_BANNER
        elif op not in ("keep", "", None):
            banner = op
        else:
            banner = self._current_banner()
        params = {"accent": self.get("s:theme.accent"), "accent2": self.get("s:theme.accent2"),
                  "title": self.get("s:theme.welcome_title") or "", "subtitle": self.get("s:theme.welcome_subtitle") or "",
                  "server": self.get("s:bot.server_name"), "banner": banner}
        self.app.background(lambda: render_cards(params), self._show)

    def _show(self, result, error):
        if not self.winfo_exists():
            return
        if error:
            self.preview.configure(image="")
            self.film_preview.configure(image="")
            self.preview_note.configure(text=f"Предпросмотр недоступен: {error}", fg=C("error"))
            return
        from PIL import Image, ImageTk
        width = max(px(360), min(px(760), self.preview.master.winfo_width() - px(4)))
        self.photos = []
        for data, target in zip(result, (self.preview, self.film_preview)):
            img = Image.open(io.BytesIO(data))
            h = int(img.height * width / img.width)
            photo = ImageTk.PhotoImage(img.resize((width, h), Image.LANCZOS))
            self.photos.append(photo)
            target.configure(image=photo)
        self.preview_note.configure(text="Так карточки будут выглядеть на сервере.", fg=C("text2"))
