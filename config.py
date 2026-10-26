"""Настройки бота. Сами значения — в settings.json (свои) поверх settings.example.json (по умолчанию).
Меняются в панели управления (Запуск.bat) или прямо в settings.json, потом /setup или «Построить сервер».
/setup ничего не удаляет и не меняет существующие каналы — только добавляет недостающее."""
import json
import os
from zoneinfo import ZoneInfo

APP = os.path.dirname(os.path.abspath(__file__))
EXAMPLE_PATH = os.path.join(APP, "settings.example.json")
SETTINGS_PATH = os.getenv("BOT_SETTINGS") or os.path.join(APP, "settings.json")  # BOT_SETTINGS — для тестов


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load() -> dict:
    with open(EXAMPLE_PATH, encoding="utf-8-sig") as f:
        data = json.load(f)
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, encoding="utf-8-sig") as f:
            data = _merge(data, json.load(f))
    return data


def colour(value) -> int:
    return int(str(value).lstrip("#"), 16) if isinstance(value, str) else int(value)


def tz(text: str = "") -> str:
    """«20:30» → «20:30 (МСК)» — подпись часового пояса из настроек."""
    return f"{text} ({TZ_LABEL})".strip() if TZ_LABEL else text


S = load()
_ch, _r, _adm = S["channels"], S["roles"], S["admin"]


def _name(item):
    return item["name"] if isinstance(item, dict) else item


def _id(item):
    return item.get("id") if isinstance(item, dict) else None


# --- Основное ---
BOT_NAME = S["bot"]["name"]
SERVER_NAME = S["bot"]["server_name"]
BOT_NICKNAME = S["bot"].get("nickname_on_server") or ""
TIMEZONE = ZoneInfo(S["bot"]["timezone"])
TZ_LABEL = S["bot"].get("tz_label") or ""    # подпись времени в текстах: «20:30 (МСК)»
MODULES: dict[str, bool] = S["modules"]
THEME = S["theme"]
ACCENT = tuple(colour(THEME["accent"]).to_bytes(3, "big"))     # основной цвет карточек
ACCENT2 = tuple(colour(THEME["accent2"]).to_bytes(3, "big"))   # второй цвет (свечение, подписи)


def enabled(module: str) -> bool:
    return bool(MODULES.get(module, False))


# --- Роли ---
ROLE_BASE = _r["base"]                 # выдаётся, когда анкета заполнена
ROLE_PENDING = _r["pending"]           # новичок до анкеты: видит только старт и правила
ROLE_STAFF = _r["staff"]               # пользуется админ-панелью (плюс все с правом «Администратор»)
ROLE_HEAD_ADMIN = _r["head_admin"]     # полные права
ROLE_HEAD_MOD = _r["head_mod"]         # модерация всего сервера + все панели
ROLE_MOD = _r["mod"]                   # обычный модератор: своя мод-панель
STAFF_ROLES = {ROLE_STAFF, ROLE_HEAD_MOD, ROLE_HEAD_ADMIN}
MOD_ROLES = STAFF_ROLES | {ROLE_MOD}
ROLE_BIRTHDAY = _r["birthday"]
ROLE_CINEMA = _r["cinema"]
MINI_PREFIX = _r["mini_admin_prefix"]

GENDERS = [tuple(g) for g in S["genders"]]  # (роль, эмодзи кнопки, подпись)

# Отделы/игры: role — открывает категорию; extra_roles — доп. роли отдела (выдаёт его mini Admin);
# category_id — уже существующая категория (её каналы бот не меняет); иначе category — создаётся /setup.
GAMES = []
for _g in S["games"]:
    _g = dict(_g)
    if not _g.get("category_id"):
        _g.pop("category_id", None)
        _g.setdefault("category", f"━━❘│{_g['emoji']}・{_g['name']}")
    GAMES.append(_g)
GAME_BY_NAME = {g["name"]: g for g in GAMES}


def admin_role_name(game: str) -> str:
    return f"{MINI_PREFIX}{game}"


def dept_roles(game: dict) -> list[str]:
    """Роли, которыми управляет mini Admin этого отдела."""
    return [game["role"], *game.get("extra_roles", [])]


# --- Уровни и достижения ---
LEVEL_STEP = S["levels"]["step"]
MESSAGE_COOLDOWN = S["levels"]["cooldown"]
LEVEL_ROLES = {int(k): v for k, v in S["levels"]["roles"].items()}
ACHIEVEMENTS = [dict(a, colour=colour(a["colour"])) for a in S["achievements"]]

# --- Именные роли ---
CUSTOM_ROLES = [(n, colour(c)) for n, c in S["custom_roles"]]
CUSTOM_ROLE_OWNERS = S["custom_role_owners"]

# --- Каналы 18+ ---
CH_GIRLS, CH_BOYS = S["adult"]["girls_channel"], S["adult"]["boys_channel"]
ROLE_GIRLS_18, ROLE_BOYS_18 = S["adult"]["girls_role"], S["adult"]["boys_role"]

# --- Семья ---
_f = S["family"]
FAMILY_NAME = _f["name"]
FAMILY_GAME = _f.get("game") or ""     # в какой игре семья (для текста заявки)
CAT_FAMILY = _f["category"]
FAMILY_AFTER_CATEGORY_ID = _f.get("after_category_id")
CH_FAMILY_APPLY, CH_FAMILY_REQUESTS = _f["apply"], _f["requests"]
CH_FAMILY_PROBATION, CH_FAMILY_HR, CH_FAMILY_HR_REPORTS = _f["probation"], _f["hr"], _f["hr_reports"]
FAMILY_PROBATION_DAYS = _f["probation_days"]
FAMILY_ROLES = [(n, colour(c), ping) for n, c, ping in _f["roles"]]  # (роль, цвет, пинговать при заявке)
ROLE_FAMILY_PROBATION = _f["probation_role"]
ROLE_FAMILY_MEMBER = _f["member_role"]

# --- Заявки в состав ---
_a = S["applications"]
CAT_APPLY, CH_APPLY, CH_APPLY_REVIEW, VC_APPLY = _a["category"], _a["apply"], _a["review"], _a["voice"]
APPLY_REVIEWERS = {ROLE_HEAD_ADMIN, ROLE_HEAD_MOD, *_r["extra_reviewers"]}
APPLY_COOLDOWN_DAYS = _a["cooldown_days"]
APPLY_REVIEW_DAYS = _a["review_days"]

# --- Защита, «только фото», сообщество ---
ANTISPAM = S["protection"]
PHOTO_ONLY_KEYWORDS = S["photo_only"]["keywords"]
PHOTO_ONLY_DELAY = S["photo_only"]["delay"]
_c = S["community"]
CH_IDEAS, CH_STARBOARD = _c["ideas"], _c["starboard"]
STAR_EMOJI, STAR_COUNT = _c["star_emoji"], _c["star_count"]
DIGEST_WEEKDAY, DIGEST_HOUR = _c["digest_weekday"], _c["digest_hour"]
BIRTHDAY_HOUR = S["birthday_hour"]

# --- Каналы и категории (название; где указан id — ищем сначала по нему) ---
CAT_MAIN, CAT_MAIN_ID = _name(_ch["main"]), _id(_ch["main"])
CAT_INFO, CAT_ACTIVITY, CAT_VOICE = _ch["info"], _ch["activity"], _ch["voice"]
CH_JOINS, CH_WELCOME, CH_NEWS, CH_MEMES = _ch["joins"], _ch["welcome"], _ch["news"], _ch["memes"]
CH_RULES, CH_RULES_ID = _name(_ch["rules"]), _id(_ch["rules"])
CH_GENERAL, CH_GENERAL_ID = _name(_ch["general"]), _id(_ch["general"])
CH_ROOMS_PANEL, CH_ROOMS_PANEL_ID = _name(_ch["rooms_panel"]), _id(_ch["rooms_panel"])
VOICE_CREATOR = _ch["voice_creator"]
CH_BIRTHDAYS = _ch["birthdays"]
CH_LEVELS, CH_ACHIEVEMENTS = _ch["levels"], _ch["achievements"]
STATS_PREFIX = _ch["stats_prefix"]
LIMITED_BOT_ROLES = S["limited_bot_roles"]   # роли ботов, которым нельзя выдавать наши роли (всегда внизу)
SHOP_ROLES = S["shop_roles"]                 # роли для их магазина — ещё ниже
ROLE_DESCRIPTIONS = S.get("role_descriptions", {})  # подсказки «кому выдавать» для своих ролей

# --- Админка ---
CAT_ADMIN, CH_ADMIN_PANEL, CH_MINI_PANEL = _adm["category"], _adm["panel"], _adm["mini_panel"]
CH_ADMIN_CHAT, CH_ADMIN_LOG, CH_RATINGS = _adm["chat"], _adm["log"], _adm["ratings"]
CH_MOD_PANEL, CH_MOD_CHAT = _adm["mod_panel"], _adm["mod_chat"]

# --- Кинотеатр ---
_k = S["cinema"]
CAT_CINEMA, CH_CINEMA_AFISHA, VC_CINEMA = _k["category"], _k["afisha"], _k["hall"]
CH_CINEMA_WISHLIST, CH_CINEMA_TALK, CH_CINEMA_SETUP = _k["wishlist"], _k["talk"], _k["setup"]
WATCH_TOGETHER_APP_ID = 880218394199220334  # встроенная активность Discord «Смотрим вместе» (YouTube)
