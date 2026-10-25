"""Чтение плейлистов ВК через API. Нужен VK_TOKEN в .env (как получить — в README).
Отдаёт только названия треков, сами треки потом ищутся на YouTube/SoundCloud."""
import os
import re

import requests

API = "https://api.vk.com/method/"
# Доступ к музыке в API ВК есть только у токенов Kate Mobile, поэтому представляемся ею
UA = "KateMobileAndroid/56 lite-460 (Android 4.4.2; SDK 19; x86; unknown Android SDK built for x86; en)"

VK_URL_RE = re.compile(r"(?:^|//|\.)vk\.(?:com|ru)/", re.I)
PLAYLIST_RE = re.compile(r"(?:playlist|album)/?(-?\d+)_(\d+)(?:(?:_|/|%2F)([0-9a-f]+))?", re.I)
TRACK_RE = re.compile(r"vk\.(?:com|ru)/audio(-?\d+)_(\d+)", re.I)
AUDIOS_RE = re.compile(r"vk\.(?:com|ru)/audios(-?\d+)", re.I)


class VKError(Exception):
    pass


def is_vk(url: str) -> bool:
    return bool(VK_URL_RE.search(url))


def _call(method: str, **params):
    token = os.getenv("VK_TOKEN")
    if not token:
        raise VKError("Для ссылок ВК нужен VK_TOKEN в файле .env (инструкция в README)")
    resp = requests.get(API + method, params={**params, "access_token": token, "v": "5.131"},
                        headers={"User-Agent": UA}, timeout=15)
    data = resp.json()
    if "error" in data:
        raise VKError(data["error"].get("error_msg", "ошибка ВК"))
    return data["response"]


def get_tracks(url: str, limit: int = 100) -> tuple[str | None, list[dict]]:
    """Возвращает (название плейлиста или None, [{artist, title, duration, cover}])."""
    name = None
    if m := PLAYLIST_RE.search(url):
        owner, pid, key = m.groups()
        extra = {"access_key": key} if key else {}
        items = _call("audio.get", owner_id=owner, album_id=pid, count=limit, **extra)["items"]
        try:
            name = _call("audio.getPlaylistById", owner_id=owner, playlist_id=pid, **extra).get("title")
        except VKError:
            name = "Плейлист ВК"
    elif m := TRACK_RE.search(url):
        items = _call("audio.getById", audios=f"{m[1]}_{m[2]}")
    elif m := AUDIOS_RE.search(url):
        items = _call("audio.get", owner_id=m[1], count=limit)["items"]
        name = "Музыка пользователя ВК"
    else:
        raise VKError("Не понял ссылку ВК. Нужна ссылка на плейлист, альбом или трек")

    tracks = []
    for a in items:
        thumb = (a.get("album") or {}).get("thumb") or {}
        tracks.append({
            "artist": a.get("artist") or "",
            "title": a.get("title") or "",
            "duration": a.get("duration"),
            "cover": thumb.get("photo_600") or thumb.get("photo_300"),
        })
    return name, tracks
