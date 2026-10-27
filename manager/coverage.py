"""Проверка, что каждая настройка редактируется в программе, причём ровно в одном разделе.

  python -m manager.coverage

Ожидаемые пути: все ключи settings.example.json (записи раскрываются до полей, списки и словари-соответствия —
целиком), ключи .env, поля host.json, правила и баннер. Найденные пути — строки вида "s:…" в manager/pages/*.py.
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# словари, которые редактируются целиком (ключи — данные пользователя, а не имена настроек)
MAPS = {"levels.roles", "custom_role_owners", "role_descriptions"}
ENV = {"DISCORD_TOKEN", "GUILD_ID", "NEWS_FORWARDS", "FFMPEG_PATH", "VK_TOKEN", "KINOZAL_URL", "KINOZAL_SECRET"}
HOST = {"name", "priority", "mode"}
RULES = {"title", "intro", "sections", "punishments", "footer"}
# служебное: путь к баннеру меняется через x:banner, а не напрямую
SKIP = {"s:theme.welcome_banner"}


def expected() -> set[str]:
    with open(os.path.join(ROOT, "settings.example.json"), encoding="utf-8-sig") as f:
        data = json.load(f)
    out = set()

    def walk(node, prefix):
        for k, v in node.items():
            if k.startswith("_"):
                continue
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict) and path not in MAPS:
                walk(v, path)
            else:
                out.add("s:" + path)
    walk(data, "")
    out |= {f"e:{k}" for k in ENV} | {f"h:{k}" for k in HOST} | {f"r:{k}" for k in RULES} | {"x:banner"}
    return out - SKIP


PATH_RE = re.compile(r"""["']([sehrx]):([A-Za-z_][A-Za-z0-9_.]*)["']""")


def found() -> dict[str, set[str]]:
    """путь → в каких файлах встречается (как привязка или запись)."""
    out: dict[str, set[str]] = {}
    for file in glob.glob(os.path.join(ROOT, "manager", "pages", "*.py")):
        name = os.path.basename(file)
        if name in ("__init__.py", "base.py"):
            continue
        text = open(file, encoding="utf-8").read()
        for m in PATH_RE.finditer(text):
            out.setdefault(f"{m[1]}:{m[2]}", set()).add(name)
    return out


def main() -> int:
    exp, got = expected(), found()
    writes = {p: files for p, files in got.items()}
    missing = sorted(exp - set(writes))
    unknown = sorted(p for p in writes if p not in exp and not any(p.startswith(e + ".") for e in exp)
                     and p not in SKIP)
    shared = sorted((p, sorted(files)) for p, files in writes.items() if len(files) > 1)
    print(f"Настроек всего: {len(exp)}, найдено в разделах: {len(exp & set(writes))}")
    if missing:
        print("\nНе редактируются нигде:")
        for p in missing:
            print("  ", p)
    if unknown:
        print("\nНеизвестные пути (опечатка или нет в settings.example.json):")
        for p in unknown:
            print("  ", p, "←", ", ".join(sorted(writes[p])))
    if shared:
        print("\nВстречаются в нескольких разделах (проверьте, что привязка одна, а остальное — только чтение):")
        for p, files in shared:
            print("  ", p, "←", ", ".join(files))
    return 1 if missing or unknown else 0


if __name__ == "__main__":
    sys.exit(main())
