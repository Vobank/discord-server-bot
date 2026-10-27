// Кинозал: плеер внутри Discord. Все в одной комнате видят одно и то же место фильма.
import { DiscordSDK } from "./sdk.js";

const inDiscord = location.hostname.endsWith("discordsays.com");
const P = inDiscord ? "/.proxy" : "";
const $ = (id) => document.getElementById(id);
const video = $("video");

let room = new URLSearchParams(location.search).get("room") || "test";
let channel = new URLSearchParams(location.search).get("channel") || "";
let ws = null;
let st = null;          // состояние комнаты с сервера
let offset = 0;         // разница часов сервера и этого устройства
let applying = 0;       // до какого момента события плеера — наши, а не зрителя
let srcFor = "";

function showError(text) {
  const box = $("error");
  box.textContent = text;
  box.hidden = false;
  clearTimeout(showError.timer);
  showError.timer = setTimeout(() => (box.hidden = true), 7000);
}

function send(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

function target() {
  if (!st) return 0;
  return st.playing ? st.pos + (Date.now() + offset - st.at) / 1000 : st.pos;
}

function quiet(ms = 600) {
  applying = Date.now() + ms;
}

function render() {
  const hasFilm = st && st.url;
  $("empty").hidden = !!hasFilm;
  $("change").hidden = !hasFilm;
  $("title").textContent = (hasFilm && st.title) || "Кинозал";
  const n = st ? st.viewers || 0 : 0;
  $("viewers").textContent = n ? `${n} ${n % 10 === 1 && n % 100 !== 11 ? "зритель" : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? "зрителя" : "зрителей"}` : "";
  if (!hasFilm) {
    if (!video.paused) video.pause();
    return;
  }
  const src = `${P}/api/video?room=${encodeURIComponent(room)}&v=${encodeURIComponent(st.url)}`;
  if (srcFor !== src) {
    srcFor = src;
    quiet(1500);
    video.src = src;
  }
  const t = target();
  if (video.readyState > 0 && Math.abs(video.currentTime - t) > 1.5) {
    quiet();
    video.currentTime = t;
  }
  if (st.playing && video.paused) {
    quiet();
    video.play().then(() => ($("tap").hidden = true)).catch(() => ($("tap").hidden = false));
  } else if (!st.playing && !video.paused) {
    quiet();
    video.pause();
  }
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}${P}/api/ws?room=${encodeURIComponent(room)}`);
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.t !== "state") return;
    offset = msg.now - Date.now();
    const first = st === null;
    st = msg;
    render();
    if (first && !st.url && channel) loadNowPlaying();
  };
  ws.onclose = () => setTimeout(connect, 2000);
}

async function loadNowPlaying() {
  try {
    const now = await (await fetch(`${P}/api/now?channel=${encodeURIComponent(channel)}`)).json();
    if (now.url) send({ t: "load", url: now.url, title: now.title || "" });
  } catch (e) {
    // нет фильма от бота — зрители могут вставить ссылку сами
  }
}

// действия зрителя — всем
video.addEventListener("play", () => {
  if (Date.now() > applying) send({ t: "play", pos: video.currentTime });
});
video.addEventListener("pause", () => {
  if (Date.now() > applying && !video.seeking) send({ t: "pause", pos: video.currentTime });
});
video.addEventListener("seeked", () => {
  if (Date.now() > applying) send({ t: "seek", pos: video.currentTime });
});
video.addEventListener("loadedmetadata", () => render());
video.addEventListener("error", () => {
  showError("Видео не открылось. Нужен файл MP4 или WebM по прямой ссылке или публичная ссылка Яндекс Диска.");
});

$("tap").addEventListener("click", () => {
  $("tap").hidden = true;
  quiet();
  video.currentTime = target();
  video.play().catch(() => ($("tap").hidden = false));
});

$("load-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const url = $("url").value.trim();
  if (!/^https?:\/\//.test(url)) return showError("Нужна ссылка, которая начинается с http или https.");
  const name = decodeURIComponent(url.split("?")[0].split("/").pop() || "").replace(/\.[a-z0-9]{2,4}$/i, "");
  send({ t: "load", url, title: name });
  $("url").value = "";
});

$("change").addEventListener("click", () => {
  $("empty").hidden = false;
  $("empty-text").textContent = "Вставьте ссылку на другой фильм. Он включится у всех в этой комнате.";
});

// раз в 5 секунд сверяемся, чтобы у всех было одно и то же место
setInterval(() => {
  if (st && st.url && st.playing && !video.paused && Math.abs(video.currentTime - target()) > 2) {
    quiet();
    video.currentTime = target();
  }
}, 5000);

async function start() {
  if (inDiscord) {
    try {
      const cfg = await (await fetch(`${P}/api/config`)).json();
      const sdk = new DiscordSDK(cfg.clientId);
      await sdk.ready();
      channel = sdk.channelId || channel;
      // комната по голосовому каналу — та же, что у кнопки «Смотреть в браузере»
      room = channel ? `ch-${channel}` : sdk.instanceId || room;
    } catch (e) {
      showError("Не удалось подключиться к Discord. Закройте и откройте кинозал снова.");
    }
  }
  connect();
}

start();
