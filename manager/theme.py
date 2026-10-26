"""Оформление панели: палитры светлой и тёмной темы, шрифты, иконки, стили ttk.

Шрифт интерфейса — Inter (лежит в assets/fonts, подключается только для этой программы), иконки — системный
шрифт Segoe Fluent Icons (Windows 11) или Segoe MDL2 Assets (Windows 10). Контролы — тема sv_ttk (Windows 11).
"""
import ctypes
import glob
import os
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import sv_ttk

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_DIR = os.path.join(APP, "assets", "fonts")

PALETTES = {
    "dark": {
        "bg": "#1c1c1c", "nav": "#1c1c1c", "card": "#262626", "card2": "#212121", "hover": "#2d2d2d",
        "border": "#303030", "divider": "#2f2f2f", "nav_sel": "#2b2b2b", "nav_hover": "#252525",
        "text": "#fafafa", "text2": "#b2b2b2", "text3": "#7f7f7f", "accent": "#57c8ff", "on_accent": "#000000",
        "link": "#7fd4ff", "success": "#6ccb5f", "warning": "#fce100", "error": "#ff99a4", "info": "#57c8ff",
        "success_bg": "#2a3527", "warning_bg": "#3b3520", "error_bg": "#3d2627", "info_bg": "#232f38",
        "idle": "#8a8a8a", "track": "#3a3a3a", "code_bg": "#181818",
    },
    "light": {
        "bg": "#fafafa", "nav": "#fafafa", "card": "#ffffff", "card2": "#f6f6f6", "hover": "#f2f2f2",
        "border": "#e3e3e3", "divider": "#ececec", "nav_sel": "#ececec", "nav_hover": "#f2f2f2",
        "text": "#1b1b1b", "text2": "#5c5c5c", "text3": "#8a8a8a", "accent": "#005fb8", "on_accent": "#ffffff",
        "link": "#005fb8", "success": "#0f7b0f", "warning": "#9d5d00", "error": "#c42b1c", "info": "#005fb8",
        "success_bg": "#dff6dd", "warning_bg": "#fff4ce", "error_bg": "#fde7e9", "info_bg": "#e8f2fc",
        "idle": "#8a8a8a", "track": "#e0e0e0", "code_bg": "#f3f3f3",
    },
}

# Имена иконок → символы шрифта Segoe Fluent Icons / MDL2 (проверены на глаз).
ICONS = {
    "home": "\uE80F", "link": "\uE71B", "globe": "\uE774", "puzzle": "\uEA86", "game": "\uE7FC", "people": "\uE716",
    "group": "\uE902", "chat": "\uE8BD", "document": "\uE8A5", "brush": "\uE771", "monitor": "\uE7F4",
    "repair": "\uE90F", "log": "\uE7BC", "info": "\uE946", "settings": "\uE713", "play": "\uE768", "stop": "\uE71A",
    "pause": "\uE769", "refresh": "\uE72C", "sync": "\uE895", "save": "\uE74E", "upload": "\uE898",
    "download": "\uE896", "pin": "\uE718", "unpin": "\uE77A", "folder": "\uE8B7", "open": "\uE8A7", "copy": "\uE8C8",
    "add": "\uE710", "edit": "\uE70F", "delete": "\uE74D", "up": "\uE70E", "down": "\uE70D", "right": "\uE76C",
    "left": "\uE76B", "close": "\uE711", "more": "\uE712", "check": "\uE73E", "completed": "\uE930",
    "warning": "\uE7BA", "error": "\uE783", "help": "\uE897", "shield": "\uEA18", "robot": "\uE99A",
    "music": "\uEC4F", "video": "\uE714", "calendar": "\uE787", "heart": "\uEB51", "camera": "\uE722",
    "star": "\uE734", "lightbulb": "\uEA80", "volume": "\uE767", "megaphone": "\uE789", "lock": "\uE72E",
    "key": "\uE8D7", "mail": "\uE715", "picture": "\uE8B9", "search": "\uE721", "filter": "\uE71C", "tag": "\uE8EC",
    "clock": "\uE823", "history": "\uE81C", "code": "\uE943", "power": "\uE7E8", "cloud": "\uE753",
    "contact": "\uE77B", "contactinfo": "\uE779", "trend": "\uEAFC", "comment": "\uE90A", "laptop": "\uE7F8",
    "cpu": "\uEEA1", "memory": "\uEEA0", "admin": "\uE83D", "permissions": "\uE8D7", "font": "\uE8D2",
    "color": "\uE790", "theme": "\uE793", "export": "\uEDE1", "import": "\uE8B5", "flag": "\uE7C1",
    "world": "\uE909", "switch": "\uE8AB", "devices": "\uE772", "clear": "\uE894", "ticket": "\uE8EC",
    "eye": "\uE7B3", "hide": "\uED1A", "back": "\uE72B", "sort": "\uE8CB", "speed": "\uEC4A",
}

STATE = {"mode": "dark", "palette": PALETTES["dark"], "k": 1.0, "icon_family": "Segoe MDL2 Assets",
         "ui_family": "Segoe UI", "strong_family": "Segoe UI Semibold", "display_family": "Segoe UI Semibold",
         "mono_family": "Consolas", "fonts": {}}


def palette() -> dict:
    return STATE["palette"]


def C(name: str) -> str:
    """Цвет текущей темы по имени (bg, card, text, text2, accent…)."""
    return STATE["palette"][name]


def px(n: float) -> int:
    """Размер в пикселях с учётом масштаба экрана (125 %, 150 %…)."""
    return int(round(n * STATE["k"]))


def dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def set_app_id(app_id: str = "DiscordBot.Manager"):
    """Своя иконка на панели задач вместо значка Python."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def system_mode() -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return "light" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else "dark"
    except Exception:
        return "dark"


def load_fonts():
    """Inter — только для этого процесса (в систему не устанавливается)."""
    loaded = 0
    if sys.platform == "win32":
        for path in glob.glob(os.path.join(FONTS_DIR, "*.ttf")):
            try:
                loaded += ctypes.windll.gdi32.AddFontResourceExW(path, 0x10, 0)
            except Exception:
                pass
    return loaded


def _pick(families: set, *names: str) -> str:
    return next((n for n in names if n in families), names[-1])


def init_fonts(root: tk.Misc):
    fams = set(tkfont.families(root))
    STATE["ui_family"] = _pick(fams, "Inter", "Segoe UI Variable Text", "Segoe UI")
    STATE["strong_family"] = _pick(fams, "Inter SemiBold", "Segoe UI Variable Text Semibold", "Segoe UI Semibold")
    STATE["display_family"] = _pick(fams, "Inter Display SemiBold", "Inter SemiBold", "Segoe UI Semibold")
    STATE["icon_family"] = _pick(fams, "Segoe Fluent Icons", "Segoe MDL2 Assets")
    STATE["mono_family"] = _pick(fams, "Cascadia Mono", "Consolas", "Courier New")
    k = STATE["k"]
    spec = {  # имя → (семейство, размер в px при 100 %)
        "caption": (STATE["ui_family"], 12), "body": (STATE["ui_family"], 14), "small": (STATE["ui_family"], 13),
        "strong": (STATE["strong_family"], 14), "body_large": (STATE["ui_family"], 16),
        "subtitle": (STATE["strong_family"], 18), "title": (STATE["display_family"], 26),
        "title_large": (STATE["display_family"], 32), "mono": (STATE["mono_family"], 13),
        "caption_strong": (STATE["strong_family"], 12),
    }
    fonts = STATE["fonts"]
    if STATE.get("root") is not root:  # шрифты привязаны к окну: для нового окна — новые
        fonts.clear()
        _IMAGES.clear()
        STATE["root"] = root
    for name, (family, size) in spec.items():
        if name in fonts:
            fonts[name].configure(family=family, size=-int(round(size * k)))
        else:
            fonts[name] = tkfont.Font(root, family=family, size=-int(round(size * k)))
    # шрифты самой темы sv_ttk и стандартные — тоже на Inter, иначе кнопки и поля будут другим шрифтом
    remap = {"SunValleyCaptionFont": ("caption",), "SunValleyBodyFont": ("body",),
             "SunValleyBodyStrongFont": ("strong",), "SunValleyBodyLargeFont": ("body_large",),
             "SunValleySubtitleFont": ("subtitle",), "SunValleyTitleFont": ("title",),
             "SunValleyTitleLargeFont": ("title_large",), "SunValleyDisplayFont": ("title_large",),
             "TkDefaultFont": ("body",), "TkTextFont": ("body",), "TkMenuFont": ("body",),
             "TkHeadingFont": ("caption_strong",), "TkCaptionFont": ("body",), "TkSmallCaptionFont": ("caption",),
             "TkIconFont": ("body",), "TkTooltipFont": ("caption",), "TkFixedFont": ("mono",)}
    for named, (ours,) in remap.items():
        try:
            f = tkfont.nametofont(named, root)
        except tk.TclError:
            continue
        src = fonts[ours]
        f.configure(family=src.cget("family"), size=src.cget("size"), weight="normal", slant="roman")


def font(name: str) -> tkfont.Font:
    """Шрифт по роли: caption, small, body, strong, body_large, subtitle, title, title_large, mono."""
    return STATE["fonts"][name]


def icon_font(size: int = 16) -> tkfont.Font:
    key = f"icon{size}"
    fonts = STATE["fonts"]
    if key not in fonts:
        fonts[key] = tkfont.Font(family=STATE["icon_family"], size=-px(size))
    return fonts[key]


def glyph(name: str) -> str:
    return ICONS.get(name, name)


_IMAGES: dict = {}


def icon_image(name: str, size: int = 16, color: str | None = None):
    """Иконка картинкой (для кнопок ttk). Без Pillow — None, кнопка будет просто с текстом."""
    color = color or C("text")
    key = (name, size, color, STATE["k"])
    if key in _IMAGES:
        return _IMAGES[key]
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageTk
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts",
                            "SegoeIcons.ttf" if STATE["icon_family"] == "Segoe Fluent Icons" else "segmdl2.ttf")
        s = px(size)
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        f = ImageFont.truetype(path, s)
        d = ImageDraw.Draw(img)
        d.text((s / 2, s / 2), glyph(name), font=f, fill=color, anchor="mm")
        photo = ImageTk.PhotoImage(img)
    except Exception:
        photo = None
    _IMAGES[key] = photo
    return photo


def app_icon_image(size: int = 32):
    """Значок программы: скруглённый квадрат цвета акцента с роботом."""
    key = ("__app__", size, STATE["mode"], STATE["k"])
    if key in _IMAGES:
        return _IMAGES[key]
    try:
        from PIL import ImageTk
        photo = ImageTk.PhotoImage(render_app_icon(px(size)))
    except Exception:
        photo = None
    _IMAGES[key] = photo
    return photo


def render_app_icon(s: int):
    from PIL import Image, ImageDraw, ImageFont
    big = s * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    top, bottom = (88, 101, 242), (54, 66, 196)
    for y in range(big):  # вертикальный градиент
        t = y / big
        d.line([(0, y), (big, y)], fill=tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)) + (255,))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.22), fill=255)
    img.putalpha(mask)
    path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "SegoeIcons.ttf")
    if not os.path.exists(path):
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segmdl2.ttf")
    try:
        f = ImageFont.truetype(path, int(big * 0.58))
        d = ImageDraw.Draw(img)
        d.text((big / 2, big / 2 + big * 0.02), ICONS["robot"], font=f, fill=(255, 255, 255, 255), anchor="mm")
    except Exception:
        pass
    return img.resize((s, s), Image.LANCZOS)


def write_ico(path: str):
    img = render_app_icon(256)
    img.save(path, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])


def dark_title_bar(window: tk.Misc, dark: bool):
    """Полоса заголовка окна в цвет программы (Windows 11), на Windows 10 — хотя бы тёмная/светлая."""
    try:
        window.update_idletasks()
        hwnd = int(window.wm_frame(), 16)
        dwm = ctypes.windll.dwmapi

        def set_attr(attr, value):
            v = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0

        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (новые и старые сборки Windows 10)
            if set_attr(attr, 1 if dark else 0):
                break

        def colorref(hex_color):
            h = hex_color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return r | (g << 8) | (b << 16)
        set_attr(35, colorref(C("nav")))     # DWMWA_CAPTION_COLOR — фон заголовка как у программы
        set_attr(36, colorref(C("text")))    # DWMWA_TEXT_COLOR
        set_attr(34, colorref(C("nav")))     # DWMWA_BORDER_COLOR — без светлой рамки
        # перерисовать рамку окна сразу, а не после переключения фокуса
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
    except Exception:
        pass


CARD_STYLES = ("TButton", "Accent.TButton", "TEntry", "TCombobox", "Switch.TCheckbutton", "TCheckbutton",
               "TRadiobutton", "TSpinbox", "Toolbutton", "TLabel", "TFrame", "Horizontal.TProgressbar", "TScale")


def apply(root: tk.Tk, mode: str):
    """Включить тему: light, dark или system."""
    if mode == "system":
        mode = system_mode()
    STATE["mode"] = mode
    STATE["palette"] = PALETTES[mode]
    sv_ttk.set_theme(mode, root)
    init_fonts(root)
    p = PALETTES[mode]
    s = ttk.Style(root)
    s.configure(".", background=p["bg"], font=font("body"))
    root.configure(bg=p["bg"])
    # стили для контролов на карточках: тот же вид, но фон углов — цвета карточки
    for base in CARD_STYLES:
        s.configure("Card." + base, background=p["card"])
        s.configure("Card2." + base, background=p["card2"])
    for prefix in ("", "Card.", "Card2."):
        s.configure(prefix + "TButton", font=font("body"), padding=(px(11), px(5), px(11), px(6)))
        s.configure(prefix + "Accent.TButton", font=font("body"), padding=(px(11), px(5), px(11), px(6)),
                    foreground=p["on_accent"])
    s.configure("Treeview", font=font("body"), rowheight=px(32), background=p["card"], fieldbackground=p["card"])
    s.configure("Heading", font=font("caption_strong"))
    s.configure("Treeview.Heading", font=font("caption_strong"))
    s.configure("TCombobox", font=font("body"))
    root.option_add("*TCombobox*Listbox.font", font("body"))
    root.option_add("*TCombobox*Listbox.background", p["card"])
    root.option_add("*TCombobox*Listbox.foreground", p["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["on_accent"])
    dark_title_bar(root, mode == "dark")
    _IMAGES.clear()
    return mode
