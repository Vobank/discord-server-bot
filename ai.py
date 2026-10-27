"""ИИ для бота через свой сервер на Cloudflare (тот же, что у кинозала, cinema/):
текст — Gemini от Google (бесплатный ключ, сервер ходит к Google из Европы — из России Google не отвечает),
картинки — бесплатный Workers AI. Нужны KINOZAL_URL и KINOZAL_SECRET в .env, ключ Gemini хранится на сервере.

  ask / ask_json      — вопрос Gemini (search=True — с поиском Google, точнее для фактов)
  image               — нарисовать картинку по описанию
  guess_song          — «опиши песню или напиши строчку» → «Исполнитель - Название»
  film_info / poster  — данные фильма для карточки и обложка: постер из Википедии, нет — рисуем"""
import json
import logging
import os
import re

import aiohttp

log = logging.getLogger(__name__)
URL = (os.getenv("KINOZAL_URL") or "").rstrip("/")
SECRET = os.getenv("KINOZAL_SECRET") or ""
WIKI_UA = {"User-Agent": "DiscordServerBot/1.0 (https://github.com/Vobank/discord-server-bot)"}


class AIError(Exception):
    """Понятное человеку сообщение, почему ИИ не помог."""


def ready() -> bool:
    return bool(URL and SECRET)


async def _post(path: str, payload: dict, timeout: int):
    if not ready():
        raise AIError("ИИ не подключён: нужен адрес и ключ кинозала в настройках бота")
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(URL + path, json=payload, headers={"Authorization": f"Bearer {SECRET}"},
                                 timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.content_type == "application/json":
                    data = await r.json()
                    if r.status != 200:
                        raise AIError(data.get("error") or f"ИИ ответил ошибкой {r.status}")
                    return data
                if r.status != 200:
                    raise AIError(f"ИИ ответил ошибкой {r.status}")
                return await r.read()
    except (aiohttp.ClientError, TimeoutError) as e:
        raise AIError("ИИ сейчас не отвечает, попробуй позже") from e


async def ask(prompt: str, system: str | None = None, search: bool = False) -> str:
    return (await _post("/api/ai/text", {"prompt": prompt, "system": system, "search": search}, 90))["text"]


async def ask_json(prompt: str, system: str | None = None, search: bool = False) -> dict:
    text = await ask(prompt + "\n\nОтветь только одним JSON-объектом, без пояснений и без ```.", system, search)
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        log.warning("ИИ ответил не JSON: %s", text[:300])
        raise AIError("ИИ ответил непонятно, попробуй ещё раз")


async def image(prompt: str) -> bytes:
    return await _post("/api/ai/image", {"prompt": prompt}, 120)


# ---------- песни ----------
async def guess_song(description: str) -> str | None:
    """Описание, строчка из песни или «та песня из тиктока про…» → «Исполнитель - Название» (или None)."""
    data = await ask_json(
        "Человек хочет включить песню, но не помнит точное название. Вот что он написал:\n"
        f"«{description[:500]}»\n\n"
        'Найди эту песню. Верни JSON: {"found": true/false, "artist": "исполнитель", "title": "название"}. '
        "Если вариантов несколько — самый известный.", search=True)
    if data.get("found") and data.get("title"):
        return f"{data.get('artist') or ''} - {data['title']}".strip(" -")
    return None


# ---------- фильмы ----------
# что искать в Википедии для каждого типа (так статья находится точнее)
WIKI_KIND = {"фильм": "фильм", "сериал": "телесериал", "мультфильм": "мультфильм", "мультсериал": "мультсериал",
             "аниме": "аниме", "аниме-фильм": "аниме фильм"}


async def _wiki_get(lang: str, params: dict) -> dict:
    async with aiohttp.ClientSession(headers=WIKI_UA) as http:
        async with http.get(f"https://{lang}.wikipedia.org/w/api.php", params={**params, "format": "json"},
                            timeout=aiohttp.ClientTimeout(total=20)) as r:
            return await r.json()


async def wiki_article(title: str, kind: str) -> tuple[str, str]:
    """Статья русской Википедии о фильме: (название статьи, начало в вики-разметке — карточка и вступление).
    Википедия свежее знаний ИИ: там есть число сезонов и серий, годы показа."""
    def norm(s: str) -> str:
        return re.sub(r"[^\w]+", " ", s.lower().replace("ё", "е")).strip()

    try:
        found = await _wiki_get("ru", {"action": "query", "list": "search", "srlimit": "5",
                                       "srsearch": f"{title} {WIKI_KIND.get(kind, kind)}"})
        # подходит только статья, название которой совпадает с фильмом: «Слово пацана», а не «Пацаны»
        hits = [h["title"] for h in found.get("query", {}).get("search", [])
                if "значения" not in h["title"] and norm(h["title"].split(" (")[0]).startswith(norm(title))]
        for name in hits[:2]:
            page = await _wiki_get("ru", {"action": "parse", "page": name, "prop": "wikitext",
                                          "section": "0", "redirects": "1"})
            text = page.get("parse", {}).get("wikitext", {}).get("*", "")
            if text:
                return page["parse"]["title"], text[:9000]
    except (aiohttp.ClientError, TimeoutError, ValueError, KeyError):
        pass
    return "", ""


async def film_info(title: str, kind: str = "фильм") -> dict:
    """Год, страна, длительность, число серий, описание. Сначала берём из Википедии, нет статьи — из знаний ИИ.
    found=False — не нашёлся."""
    article, text = await wiki_article(title, kind)
    source = (f"Вот начало статьи «{article}» из русской Википедии (вики-разметка):\n<<<\n{text}\n>>>\n"
              "Бери данные из статьи — она свежее твоих знаний. Если статья не про этот "
              f"{kind}, ответь found=false.\n\n") if text else ""
    data = await ask_json(
        f"{source}Нужны данные: {kind} «{title[:100]}». Верни JSON:\n"
        '{"found": true или false — нашёлся ли именно такой,\n'
        ' "title": официальное название на русском (если его нет — оригинальное),\n'
        ' "year": год выхода; у сериала — годы показа, например «2019–2022», а если ещё выходит — «2020 — н. в.»,\n'
        ' "country": страны через запятую, по-русски,\n'
        ' "duration": у фильма — «1 ч 33 мин», у сериала — сколько сезонов, например «5 сезонов»,\n'
        ' "episodes": у сериала — сколько всего серий (число), у фильма — null,\n'
        ' "description": 2–3 предложения на русском, о чём это, без спойлеров,\n'
        ' "wiki_en": точное название статьи в английской Википедии или "",\n'
        ' "poster_prompt": по-английски: атмосферный постер к нему — сцена, настроение, цвета; '
        "без текста, без надписей и без лиц реальных актёров}")
    info = {k: (str(v).strip() if v is not None and k not in ("found", "episodes") else v) for k, v in data.items()}
    info["wiki_ru"] = article
    try:
        info["episodes"] = int(info.get("episodes")) if info.get("episodes") else None
    except (TypeError, ValueError):
        info["episodes"] = None
    return info


async def wiki_image(article: str, lang: str) -> bytes | None:
    """Главная картинка статьи Википедии — у фильмов это обычно постер."""
    if not article:
        return None
    # pilicense=any: постеры фильмов в Википедии почти всегда несвободные, без этого их не отдают
    params = {"action": "query", "titles": article, "prop": "pageimages", "piprop": "original", "pilicense": "any",
              "format": "json", "redirects": "1"}
    try:
        async with aiohttp.ClientSession(headers=WIKI_UA) as http:
            async with http.get(f"https://{lang}.wikipedia.org/w/api.php", params=params,
                                timeout=aiohttp.ClientTimeout(total=20)) as r:
                pages = (await r.json()).get("query", {}).get("pages", {})
            src = next((p["original"]["source"] for p in pages.values() if p.get("original")), None)
            if not src or src.lower().endswith((".svg", ".gif")):
                return None
            async with http.get(src, timeout=aiohttp.ClientTimeout(total=30)) as r:
                return await r.read() if r.status == 200 else None
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return None


async def poster(title: str, info: dict | None = None) -> bytes | None:
    """Обложка: настоящий постер из Википедии, а если его нет — нарисованная ИИ."""
    info = info or {}
    for lang in ("ru", "en"):
        if data := await wiki_image(info.get(f"wiki_{lang}") or "", lang):
            return data
    prompt = info.get("poster_prompt") or f"atmospheric cinematic movie poster for the film \"{title}\""
    try:
        return await image(prompt + ", cinematic lighting, highly detailed, vertical movie poster, no text, no letters")
    except AIError:
        return None
