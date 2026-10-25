"""Синхронизация между ПК через закрытый канал Discord (#🔧・bot-sync), только REST, без запуска бота.

В канале:
  • «пульс» — одно сообщение, которое активная копия обновляет каждые 15 сек (кто сейчас главный);
  • «DB …»   — снимки базы bot.db (последние несколько);
  • «CODE …» — опубликованные обновления кода (zip).
Писать туда может только сам бот (наш токен), поэтому чужие файлы туда не попадут."""
import asyncio
import hashlib
import io
import json
import os
import socket
import time
import zipfile

import aiohttp
from dotenv import load_dotenv

APP = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(APP, ".env"))
API = "https://discord.com/api/v10"
TOKEN = os.getenv("DISCORD_TOKEN")
SYNC_CHANNEL_ID = os.getenv("SYNC_CHANNEL_ID")
SYNC_HEARTBEAT_ID = os.getenv("SYNC_HEARTBEAT_ID")
RUNTIME = os.path.join(APP, "runtime")
os.makedirs(RUNTIME, exist_ok=True)

# что НЕ входит в обновление кода (у каждого ПК своё)
LOCAL_FILES = {".env", "host.json", "bot.db", "bot.log", "version.txt", "bot.db-journal"}
LOCAL_DIRS = {".venv", "runtime", "__pycache__", ".git", "backups"}


def host_info() -> dict:
    """Кто я: имя ПК и приоритет (1 — основной, 2 — запасной…). Лежит в host.json, у каждого свой."""
    path = os.path.join(APP, "host.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    else:
        data = {"name": socket.gethostname(), "priority": 2}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    data.setdefault("id", socket.gethostname())
    return data


def local_version() -> int:
    try:
        with open(os.path.join(APP, "version.txt")) as f:
            return int(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def set_local_version(v: int):
    with open(os.path.join(APP, "version.txt"), "w") as f:
        f.write(str(v))


class Discord:
    """Мини-клиент Discord REST (без подключения к шлюзу — бот при этом не «включается»)."""

    def __init__(self):
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={"Authorization": f"Bot {TOKEN}",
                                                      "User-Agent": "RestBotSync (local, 1.0)"})
        return self

    async def __aexit__(self, *exc):
        await self.session.close()

    async def request(self, method: str, path: str, **kw):
        for _ in range(5):
            async with self.session.request(method, API + path, **kw) as r:
                if r.status == 429:
                    await asyncio.sleep(float((await r.json()).get("retry_after", 2)) + 0.5)
                    continue
                if r.status >= 400:
                    raise RuntimeError(f"Discord {r.status}: {await r.text()}")
                return await r.json() if r.content_type == "application/json" else await r.read()
        raise RuntimeError("Discord: слишком много запросов")

    # --- пульс ---
    async def read_heartbeat(self) -> dict:
        msg = await self.request("GET", f"/channels/{SYNC_CHANNEL_ID}/messages/{SYNC_HEARTBEAT_ID}")
        text = msg.get("content", "")
        try:
            return json.loads(text.split("\n", 1)[1]) if text.startswith("HEARTBEAT") else {}
        except (IndexError, json.JSONDecodeError):
            return {}

    async def write_heartbeat(self, data: dict):
        body = "HEARTBEAT\n" + json.dumps(data, ensure_ascii=False)
        await self.request("PATCH", f"/channels/{SYNC_CHANNEL_ID}/messages/{SYNC_HEARTBEAT_ID}",
                           json={"content": body[:2000]})

    # --- сообщения с файлами ---
    async def send_file(self, kind: str, meta: dict, filename: str, data: bytes) -> dict:
        form = aiohttp.FormData()
        form.add_field("payload_json", json.dumps({"content": f"{kind} " + json.dumps(meta, ensure_ascii=False)}),
                       content_type="application/json")
        form.add_field("files[0]", data, filename=filename, content_type="application/octet-stream")
        return await self.request("POST", f"/channels/{SYNC_CHANNEL_ID}/messages", data=form)

    async def latest(self, kind: str, limit: int = 50) -> list[dict]:
        """Последние сообщения вида «KIND {json}» с файлом, новые — первыми."""
        msgs = await self.request("GET", f"/channels/{SYNC_CHANNEL_ID}/messages?limit={limit}")
        out = []
        for m in msgs:
            c = m.get("content", "")
            if c.startswith(kind + " ") and m.get("attachments"):
                try:
                    meta = json.loads(c[len(kind) + 1:])
                except json.JSONDecodeError:
                    continue
                out.append({"id": m["id"], "meta": meta, "url": m["attachments"][0]["url"]})
        return out

    async def download(self, url: str) -> bytes:
        async with self.session.get(url) as r:
            r.raise_for_status()
            return await r.read()

    async def delete(self, message_id: str):
        try:
            await self.request("DELETE", f"/channels/{SYNC_CHANNEL_ID}/messages/{message_id}")
        except RuntimeError:
            pass


# ---------- код: упаковать / применить ----------
def pack_code() -> tuple[bytes, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(APP):
            dirs[:] = [d for d in dirs if d not in LOCAL_DIRS]
            for name in files:
                rel = os.path.relpath(os.path.join(root, name), APP)
                if name in LOCAL_FILES or name.endswith((".pyc", ".log")) or rel.startswith(os.path.join("tools", "backup")):
                    continue
                z.write(os.path.join(root, name), rel)
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest()


def apply_code(data: bytes):
    """Распаковать обновление поверх папки, не трогая локальные файлы (.env, host.json, базу)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            parts = info.filename.replace("\\", "/").split("/")
            if parts[0] in LOCAL_DIRS or parts[-1] in LOCAL_FILES or ".." in parts:
                continue
            target = os.path.join(APP, *parts)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())


async def publish(note: str = "") -> int:
    """Опубликовать текущий код как новое обновление. Возвращает номер версии."""
    data, sha = pack_code()
    version = int(time.time())
    async with Discord() as d:
        await d.send_file("CODE", {"version": version, "sha256": sha, "by": host_info()["name"], "note": note},
                          f"code-{version}.zip", data)
        for old in (await d.latest("CODE"))[3:]:  # храним 3 последних
            await d.delete(old["id"])
    set_local_version(version)
    return version
