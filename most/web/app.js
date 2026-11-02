"use strict";

const $ = (s) => document.querySelector(s);
const queue = [];        // файлы, ждущие отправки
let current = null;      // отправляется сейчас
let wakeLock = null;
let events = null;       // поток новостей с ПК (SSE)
let me = null;
const shown = new Map(); // id элемента ленты -> <li>
const unseen = new Set();
const downloads = new Map(); // id файла с ПК -> состояние скачивания
const DL_WAIT_MS = 15000;    // столько ждём, что браузер начнёт скачивать
const IOS = /iPhone|iPad/.test(navigator.userAgent);
const IS_PHONE = IOS || /Android/.test(navigator.userAgent);
const SAVED_TO = IOS ? "в «Файлы» → «Загрузки»" : "в «Загрузки» телефона";
const FOLDER_HINT = "Открыть: приложение «Файлы» → «Загрузки»";

// ---------- вход ----------

async function init() {
  try {
    const r = await fetch("/api/me");
    if (r.ok) return showApp(await r.json());
  } catch (_) { /* сервер недоступен — покажем вход */ }
  showLogin();
}

function showLogin() {
  if (events) events.close();
  $("#app").hidden = true;
  $("#login").hidden = false;
  $("#pin").focus();
}

function showApp(info) {
  me = info;
  $("#login").hidden = true;
  $("#app").hidden = false;
  $("#pc-name").textContent = info.pc || "Компьютер";
  listen();
}

$("#pin-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button");
  btn.disabled = true;
  $("#pin-error").textContent = "";
  try {
    const r = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: $("#pin").value.trim() }),
    });
    if (r.ok) return init();
    $("#pin-error").textContent = (await r.json()).error || "Не получилось войти";
    $("#pin").select();
  } catch (_) {
    $("#pin-error").textContent = "Нет связи с компьютером";
  } finally {
    btn.disabled = false;
  }
});

// ---------- связь с ПК ----------

function listen() {
  if (events) events.close();
  events = new EventSource("/api/events");
  events.onopen = () => { setOnline(true); loadFeed(); };
  events.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "item" && !shown.has(msg.item.id)) {
      addItem(msg.item);
      if (msg.item.who !== "me") beep("in");
    } else if (msg.type === "dl") {
      onDownload(msg);
    } else if (msg.type === "clear") {
      clearFeed();
    }
  };
  events.onerror = () => {
    setOnline(false);
    // EventSource сам переподключается; закрывается насовсем только при ошибке входа
    if (events.readyState === EventSource.CLOSED) setTimeout(init, 3000);
  };
}

function setOnline(on) {
  $(".dot").classList.toggle("off", !on);
  $("#status").textContent = on ? "На связи · " + me.device : "Нет связи — переподключаюсь…";
  $("#reconnect").hidden = on;
}

// Свёрнутый браузер Android/iPhone рвёт SSE или «замораживает» его, а сам EventSource
// переподключается не сразу — при возврате на страницу подключаемся заново немедленно.
function reconnect() {
  if (!me || $("#app").hidden) return;
  $("#status").textContent = "Подключаюсь…";
  listen();
  loadFeed();
}

$("#reconnect").addEventListener("click", reconnect);
document.addEventListener("visibilitychange", () => { if (!document.hidden) reconnect(); });
// возврат из кэша «назад/вперёд»: страница не перезагружалась, соединения мертвы
window.addEventListener("pageshow", (e) => { if (e.persisted) reconnect(); });

async function loadFeed() {
  try {
    const r = await fetch("/api/feed");
    if (r.status === 401) return showLogin();
    if (!r.ok) return;
    for (const item of (await r.json()).items) {
      if (!shown.has(item.id)) addItem(item);
      // пока не было связи, скачивание могло закончиться — сообщение о нём потерялось
      const d = downloads.get(item.id);
      if (d && item.delivered && (d.state === "wait" || d.state === "run")) dlDone(d, true);
    }
  } catch (_) {}
}

// ---------- лента ----------

function addItem(it) {
  const li = document.createElement("li");
  li.className = "item";
  const name = el("div", "item-name");
  const info = el("div", "item-info");
  const from = it.who === "me" ? "Вы" : it.sender;
  const parts = [from, when(it.ts)];
  li.append(name, info);

  if (it.kind === "text") {
    li.classList.add("text");
    name.remove();
    const body = el("div", "item-text");
    linkify(body, it.text);
    li.prepend(body);
    if (it.who !== "me") {
      const btn = button("Копировать", async () => {
        btn.textContent = (await copy(it.text)) ? "Скопировано" : "Не вышло";
        seen(it.id);
      });
      li.append(btn);
    }
  } else {
    name.textContent = it.name;
    parts.splice(1, 0, size(it.size));
    if (it.who !== "me") {
      if (it.available) {
        const acts = el("div", "acts");
        const bar = el("div", "bar");
        bar.append(el("i"));
        bar.hidden = true;
        li.append(acts, bar);
        const d = { it, li, info, acts, bar, state: "idle", base: parts.join(" · ") };
        downloads.set(it.id, d);
        if (it.delivered) dlDone(d, false);
        else dlButtons(d, [dlLink(d, "Скачать", true)]);
      } else {
        parts.push("файла больше нет");
      }
    }
  }
  if (it.who === "me") parts.push("отправлено");
  if (!info.textContent) info.textContent = parts.join(" · ");

  shown.set(it.id, li);
  $("#list").prepend(li);
  showEmpty();
  if (it.who !== "me" && !it.delivered && it.available) {
    li.classList.add("new");
    unseen.add(it.id);
    updateTitle();
  }
}

function showEmpty() {
  const empty = !$("#list").children.length;
  $("#empty").hidden = !empty;
  $("#clear").hidden = empty;
}

// Лента общая: очистка стирает её у всех (на ПК и телефонах), файлы остаются.
$("#clear").addEventListener("click", async () => {
  if (!confirm("Очистить ленту? Она очистится у всех: на компьютере и телефонах. Файлы останутся.")) return;
  try {
    const r = await fetch("/api/clear", { method: "POST" });
    if (r.status === 401) return showLogin();
    if (!r.ok) return toast("Не получилось очистить", true);
    clearFeed();
  } catch (_) {
    toast("Нет связи с компьютером", true);
  }
});

function clearFeed() {
  // то, что ещё отправляется, оставляем
  const keep = new Set([current, ...queue].filter(Boolean).map((i) => i.el));
  for (const li of [...$("#list").children]) if (!keep.has(li)) li.remove();
  for (const d of downloads.values()) clearTimeout(d.timer);
  shown.clear();
  downloads.clear();
  unseen.clear();
  updateTitle();
  showEmpty();
}

// ---------- скачивание с ПК ----------
// Скачивает сам браузер и странице ничего не сообщает. Ход знает сервер:
// он отдаёт файл кусками и шлёт сюда сообщения "dl" (start/progress/done/error).

function dlLink(d, text, primary) {
  const a = el("a", "btn small" + (primary ? " primary" : ""));
  a.href = "/api/file/" + d.it.id;
  a.setAttribute("download", d.it.name);
  a.textContent = text;
  a.onclick = () => dlStart(d);
  return a;
}

function dlButtons(d, buttons) {
  d.acts.replaceChildren(...buttons);
}

function dlInfo(d, text, cls) {
  d.li.classList.remove("ok", "err");
  if (cls) d.li.classList.add(cls);
  d.info.textContent = text;
}

function dlStart(d) {
  seen(d.it.id);
  d.state = "wait";
  d.bar.hidden = false;
  d.bar.firstChild.style.width = "0";
  dlInfo(d, "Запрашиваю файл у компьютера…");
  // кнопку убираем после клика: иначе браузер может не начать скачивание
  setTimeout(() => { if (d.state === "wait") dlButtons(d, []); }, 0);
  clearTimeout(d.timer);
  d.timer = setTimeout(() => {
    if (d.state === "wait") {
      dlFail(d, "Скачивание не началось. Если браузер спрашивает, скачать ли файл, — разрешите, или нажмите «Повторить».");
    }
  }, DL_WAIT_MS);
}

function onDownload(msg) {
  const d = downloads.get(msg.id);
  if (!d) return;
  if (msg.state === "done") return dlDone(d, true);
  if (msg.state === "error") return dlFail(d, msg.error + ". Нажмите «Повторить».");
  // start / progress
  clearTimeout(d.timer);
  if (d.state !== "run") {
    d.state = "run";
    d.t0 = performance.now();
    d.bar.hidden = false;
    dlButtons(d, []);
  }
  const sec = (performance.now() - d.t0) / 1000;
  const speed = sec > 0.5 && msg.done ? " · " + size(msg.done / sec) + "/с" : "";
  d.bar.firstChild.style.width = (msg.total ? msg.done / msg.total * 100 : 0) + "%";
  dlInfo(d, "Скачивается: " + size(msg.done) + " из " + size(msg.total) + speed);
}

function dlDone(d, fresh) {
  clearTimeout(d.timer);
  d.state = "done";
  d.bar.hidden = true;
  const buttons = [];
  // папку «Загрузки» из браузера не открыть (intent'ы на телефонах не сработали) —
  // только подсказка; «Посмотреть» — открыть сам файл в браузере
  if (d.it.view) buttons.push(viewLink(d));
  buttons.push(dlLink(d, "Ещё раз", false));
  dlButtons(d, buttons);
  const saved = fresh ? "✓ Сохранено " + SAVED_TO : d.base + " · скачано " + SAVED_TO;
  dlInfo(d, IS_PHONE ? saved + ". " + FOLDER_HINT : saved, "ok");
  if (fresh) {
    toast("✓ Сохранено " + SAVED_TO + ": " + d.it.name);
    beep("done");
  }
}

function viewLink(d) {
  const a = el("a", "btn small");
  a.href = "/api/file/" + d.it.id + "?view=1";
  a.target = "_blank";
  a.rel = "noopener";
  a.textContent = "Посмотреть";
  return a;
}

function dlFail(d, text) {
  clearTimeout(d.timer);
  d.state = "error";
  d.bar.hidden = true;
  dlButtons(d, [dlLink(d, "Повторить", true)]);
  dlInfo(d, text, "err");
  toast("Не скачалось: " + d.it.name, true);
}

function seen(id) {
  const li = shown.get(id);
  if (li) li.classList.remove("new");
  unseen.delete(id);
  updateTitle();
}

function updateTitle() {
  document.title = unseen.size ? `(${unseen.size}) Тропка` : "Тропка";
}

// ---------- отправка текста ----------

$("#text").addEventListener("input", (e) => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight, 200) + "px";
});

$("#text-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const box = $("#text");
  const text = box.value;
  if (!text.trim()) return;
  try {
    const r = await fetch("/api/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await r.json();
    if (r.status === 401) return showLogin();
    if (!r.ok) return alert(data.error || "Не отправилось");
    addItem({ id: data.id, kind: "text", who: "me", text, ts: Date.now() / 1000 });
    box.value = "";
    box.style.height = "auto";
  } catch (_) {
    alert("Нет связи с компьютером");
  }
});

// ---------- отправка файлов ----------

$("#files").addEventListener("change", (e) => {
  for (const file of e.target.files) enqueue(file);
  e.target.value = "";
});

function enqueue(file) {
  const li = el("li", "item");
  li.innerHTML = '<div class="item-name"></div><button class="x" aria-label="Отменить">×</button>' +
    '<div class="item-info"></div><div class="bar"><i></i></div>';
  li.querySelector(".item-name").textContent = file.name;
  li.querySelector(".item-info").textContent = "В очереди · " + size(file.size);
  $("#list").prepend(li);
  showEmpty();
  const item = { file, el: li };
  li.querySelector(".x").onclick = () => cancel(item);
  queue.push(item);
  pump();
}

function cancel(item) {
  if (item === current) return item.xhr.abort();
  const i = queue.indexOf(item);
  if (i >= 0) queue.splice(i, 1);
  finish(item, false, "Отменено");
}

async function pump() {
  if (current) return;
  current = queue.shift();
  if (!current) return releaseWake();
  await holdWake();
  await send(current);
  current = null;
  pump();
}

function send(item) {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    item.xhr = xhr;
    xhr.open("PUT", "/api/upload");
    xhr.setRequestHeader("X-File-Name", encodeURIComponent(item.file.name));
    const t0 = performance.now();
    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const sec = (performance.now() - t0) / 1000;
      const speed = sec > 0.5 ? " · " + size(e.loaded / sec) + "/с" : "";
      item.el.querySelector(".bar > i").style.width = (e.loaded / e.total * 100) + "%";
      setInfo(item, size(e.loaded) + " из " + size(e.total) + speed);
    };
    xhr.onload = () => {
      if (xhr.status === 200) {
        const data = JSON.parse(xhr.responseText);
        shown.set(data.id, item.el);
        finish(item, true, "Вы · " + size(item.file.size) + " · доставлено");
        beep("done");
      } else {
        let msg = "Ошибка " + xhr.status;
        try { msg = JSON.parse(xhr.responseText).error || msg; } catch (_) {}
        finish(item, false, msg);
        if (xhr.status === 401) showLogin();
      }
      resolve();
    };
    xhr.onerror = () => { finish(item, false, "Нет связи с компьютером"); resolve(); };
    xhr.onabort = () => { finish(item, false, "Отменено"); resolve(); };
    xhr.send(item.file);
  });
}

function setInfo(item, text) {
  item.el.querySelector(".item-info").textContent = text;
}

function finish(item, ok, text) {
  item.el.classList.add(ok ? "ok" : "err");
  setInfo(item, text);
}

// ---------- плашка и звуки ----------

let toastTimer = 0;

function toast(text, bad) {
  const t = $("#toast");
  t.textContent = text;
  t.classList.toggle("bad", !!bad);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 5000);
}

$("#toast").addEventListener("click", (e) => { e.currentTarget.hidden = true; });

// Браузер разрешает звук только после касания страницы: тогда и создаём AudioContext.
let audio = null;
let soundOn = true;
try { soundOn = localStorage.getItem("most-sound") !== "off"; } catch (_) {}

function unlockAudio() {
  try {
    if (!audio) audio = new (window.AudioContext || window.webkitAudioContext)();
    if (audio.state === "suspended") audio.resume().catch(() => {});
  } catch (_) {}
}

for (const t of ["pointerdown", "touchend", "keydown"]) {
  addEventListener(t, unlockAudio, { capture: true, passive: true });
}

const TUNES = {
  in: [[880, 0], [1319, 0.12]],     // новое с компьютера
  done: [[784, 0], [1047, 0.09]],   // отправлено или скачано
  test: [[988, 0]],
};

function beep(kind) {
  if (!soundOn || !audio) return;
  if (audio.state === "running") return play(kind);
  audio.resume().then(() => play(kind), () => {});
}

function play(kind) {
  const t = audio.currentTime + 0.02;
  for (const [freq, dt] of TUNES[kind]) {
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, t + dt);
    gain.gain.exponentialRampToValueAtTime(0.3, t + dt + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + dt + 0.4);
    osc.connect(gain).connect(audio.destination);
    osc.start(t + dt);
    osc.stop(t + dt + 0.45);
  }
}

function showSound() {
  const b = $("#sound");
  b.setAttribute("aria-pressed", String(soundOn));
  b.setAttribute("aria-label", soundOn ? "Звук включён" : "Звук выключен");
  b.title = b.getAttribute("aria-label");
  b.classList.toggle("off", !soundOn);
}

$("#sound").addEventListener("click", () => {
  soundOn = !soundOn;
  try { localStorage.setItem("most-sound", soundOn ? "on" : "off"); } catch (_) {}
  showSound();
  if (soundOn) beep("test");
});
showSound();

// ---------- мелочи ----------

function el(tag, cls) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  return e;
}

function button(text, onclick) {
  const b = el("button", "btn small");
  b.type = "button";
  b.textContent = text;
  b.onclick = onclick;
  return b;
}

function linkify(node, text) {
  for (const part of text.split(/(https?:\/\/[^\s]+)/g)) {
    if (/^https?:\/\//.test(part)) {
      const a = el("a");
      a.href = part;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = part;
      node.append(a);
    } else if (part) {
      node.append(part);
    }
  }
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (_) {
    const ta = el("textarea");
    ta.value = text;
    document.body.append(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

function when(ts) {
  const d = new Date(ts * 1000);
  const time = d.toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === new Date().toDateString()) return time;
  return d.toLocaleDateString("ru", { day: "numeric", month: "short" }) + ", " + time;
}

function size(n) {
  const u = ["Б", "КБ", "МБ", "ГБ"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i ? n.toFixed(n < 10 ? 1 : 0) : n) + " " + u[i];
}

// ---------- экран не гаснет во время передачи ----------

async function holdWake() {
  if (wakeLock || !("wakeLock" in navigator)) return;
  try { wakeLock = await navigator.wakeLock.request("screen"); } catch (_) {}
}

function releaseWake() {
  if (wakeLock) wakeLock.release().catch(() => {});
  wakeLock = null;
}

init();
