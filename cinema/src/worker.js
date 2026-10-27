// Кинозал: сервер на Cloudflare Workers.
//  /api/config            — ID приложения для Discord SDK
//  /api/now?channel=ID    — какой фильм сейчас в голосовом канале (бот пишет POST с секретом, плеер читает GET)
//  /api/ws?room=ID        — синхронизация просмотра (одна комната = один запуск кинозала в канале)
//  /api/video?room=ID     — видео текущего фильма комнаты (с перемоткой: заголовок Range передаётся дальше)
// Остальное — страница плеера из public/.
import { DurableObject } from "cloudflare:workers";

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

function apiPath(url) {
  // Запросы из Discord приходят через его прокси с приставкой /.proxy
  const p = url.pathname;
  return p.startsWith("/.proxy/") ? p.slice(7) : p;
}

const resolved = new Map(); // ссылка Яндекс Диска → прямая ссылка (живёт недолго)

async function directLink(u) {
  if (/^https?:\/\/(disk\.yandex\.(ru|com|by|kz)|yadi\.sk)\//i.test(u)) {
    const hit = resolved.get(u);
    if (hit && hit.until > Date.now()) return hit.href;
    const r = await fetch(
      "https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key=" + encodeURIComponent(u),
    );
    if (!r.ok) throw new Error("Яндекс Диск не отдал файл: проверьте, что ссылка публичная");
    const href = (await r.json()).href;
    resolved.set(u, { href, until: Date.now() + 10 * 60 * 1000 });
    return href;
  }
  return u;
}

async function proxyVideo(req, source) {
  let target;
  try {
    target = new URL(await directLink(source));
  } catch (e) {
    return json({ error: String(e.message || e) }, 400);
  }
  if (!/^https?:$/.test(target.protocol)) return json({ error: "Нужна ссылка http или https" }, 400);
  const headers = new Headers();
  const range = req.headers.get("range");
  if (range) headers.set("range", range);
  const upstream = await fetch(target.toString(), { headers, redirect: "follow" });
  const out = new Headers();
  for (const h of ["content-type", "content-length", "content-range", "accept-ranges", "last-modified", "etag"]) {
    const v = upstream.headers.get(h);
    if (v) out.set(h, v);
  }
  const type = out.get("content-type") || "";
  if (!type || type.startsWith("application/octet-stream") || type.startsWith("binary/")) out.set("content-type", "video/mp4");
  if (!out.has("accept-ranges")) out.set("accept-ranges", "bytes");
  out.set("cache-control", "no-store");
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const path = apiPath(url);
    if (!path.startsWith("/api/")) {
      if (path !== url.pathname) {
        const clean = new URL(url);
        clean.pathname = path;
        return env.ASSETS.fetch(new Request(clean, req));
      }
      return env.ASSETS.fetch(req);
    }
    if (path === "/api/config") return json({ clientId: env.CLIENT_ID || "" });

    if (path === "/api/now") {
      const channel = url.searchParams.get("channel") || "";
      if (!/^\d{5,25}$/.test(channel)) return json({ error: "channel" }, 400);
      const stub = env.ROOMS.get(env.ROOMS.idFromName("channel:" + channel));
      return stub.fetch(new Request(new URL("https://room/now"), req));
    }

    const room = url.searchParams.get("room") || "";
    if (!/^[\w.:-]{1,100}$/.test(room)) return json({ error: "room" }, 400);
    const stub = env.ROOMS.get(env.ROOMS.idFromName("room:" + room));
    if (path === "/api/ws") return stub.fetch(new Request(new URL("https://room/ws"), req));
    if (path === "/api/video") {
      const state = await (await stub.fetch("https://room/state")).json();
      if (!state.url) return json({ error: "Фильм ещё не выбран" }, 404);
      return proxyVideo(req, state.url);
    }
    return json({ error: "not found" }, 404);
  },
};

export class Room extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.env = env;
    this.state = null;
  }

  async loadState() {
    if (!this.state) {
      this.state = (await this.ctx.storage.get("state")) || { url: "", title: "", playing: false, pos: 0, at: Date.now() };
    }
    return this.state;
  }

  position(s) {
    return s.playing ? s.pos + (Date.now() - s.at) / 1000 : s.pos;
  }

  snapshot() {
    return { t: "state", ...this.state, now: Date.now(), viewers: this.ctx.getWebSockets().length };
  }

  broadcast() {
    const msg = JSON.stringify(this.snapshot());
    for (const ws of this.ctx.getWebSockets()) {
      try {
        ws.send(msg);
      } catch (e) {
        // соединение уже закрыто
      }
    }
  }

  async fetch(req) {
    const path = new URL(req.url).pathname;
    if (path === "/now") {
      if (req.method === "POST") {
        const auth = req.headers.get("authorization") || "";
        if (!this.env.KINOZAL_SECRET || auth !== "Bearer " + this.env.KINOZAL_SECRET) return json({ error: "forbidden" }, 403);
        const body = await req.json();
        const now = { url: String(body.url || ""), title: String(body.title || "").slice(0, 200), at: Date.now() };
        await this.ctx.storage.put("now", now);
        return json({ ok: true });
      }
      return json((await this.ctx.storage.get("now")) || { url: "", title: "" });
    }
    await this.loadState();
    if (path === "/state") return json(this.state);
    if (path === "/ws") {
      if (req.headers.get("upgrade") !== "websocket") return json({ error: "websocket" }, 426);
      const pair = new WebSocketPair();
      this.ctx.acceptWebSocket(pair[1]);
      pair[1].send(JSON.stringify(this.snapshot()));
      this.broadcast();
      return new Response(null, { status: 101, webSocket: pair[0] });
    }
    return json({ error: "not found" }, 404);
  }

  async webSocketMessage(ws, raw) {
    let msg;
    try {
      msg = JSON.parse(raw);
    } catch (e) {
      return;
    }
    const s = await this.loadState();
    const pos = Math.max(0, Number(msg.pos) || 0);
    if (msg.t === "load" && typeof msg.url === "string" && /^https?:\/\//.test(msg.url)) {
      Object.assign(s, { url: msg.url.slice(0, 2000), title: String(msg.title || "").slice(0, 200), playing: false, pos: 0 });
    } else if (msg.t === "play") {
      Object.assign(s, { playing: true, pos });
    } else if (msg.t === "pause") {
      Object.assign(s, { playing: false, pos });
    } else if (msg.t === "seek") {
      Object.assign(s, { pos });
    } else if (msg.t === "sync") {
      ws.send(JSON.stringify(this.snapshot()));
      return;
    } else {
      return;
    }
    s.at = Date.now();
    await this.ctx.storage.put("state", s);
    this.broadcast();
  }

  async webSocketClose() {
    this.broadcast();
  }

  async webSocketError() {
    this.broadcast();
  }
}
