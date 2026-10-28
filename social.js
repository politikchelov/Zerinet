"use strict";
/* ZERINET: профиль, друзья, чат, «Критика», топ. Работает вместе с server.py (/social/*). */
(function () {
  const S = { enabled: false, user: undefined, ranks: [], requests: 0 };
  const el = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const enc = encodeURIComponent;

  /* ---------- стили ---------- */
  document.head.append(el(`<style>
    .top{flex-wrap:wrap}
    #znav{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
    #znav a{padding:6px 10px;border-radius:8px;color:var(--muted);position:relative}
    #znav a:hover{background:var(--panel2);color:var(--text)}
    #znav .badge{background:var(--danger);color:#fff;border-radius:999px;font-size:11px;padding:0 6px;margin-left:4px}
    #znav .me{display:flex;gap:8px;align-items:center;color:var(--text)}
    .av{--s:40px;--ring:#3a3f4b;width:var(--s);height:var(--s);border-radius:50%;display:inline-block;flex:none;padding:calc(var(--s)*.07);background:var(--ring);vertical-align:middle;line-height:0}
    .av img,.av .ph{width:100%;height:100%;border-radius:50%;object-fit:cover;display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff;font-size:calc(var(--s)*.42);line-height:1}
    .frame-viewer{--ring:linear-gradient(135deg,#b4691f,#f3c08d)}
    .frame-expert{--ring:linear-gradient(135deg,#8892a0,#f1f4f8)}
    .frame-legend{--ring:linear-gradient(135deg,#f59e0b,#fde047,#f59e0b);animation:glowG 2s ease-in-out infinite}
    .frame-moderator{--ring:linear-gradient(135deg,#10b981,#6ee7b7);animation:glowM 2.4s ease-in-out infinite}
    .frame-admin{--ring:linear-gradient(135deg,#8b5cf6,#ec4899,#38bdf8);animation:glowA 1.8s ease-in-out infinite}
    @keyframes glowG{50%{box-shadow:0 0 14px #facc15aa}}
    @keyframes glowM{50%{box-shadow:0 0 14px #34d399aa}}
    @keyframes glowA{50%{box-shadow:0 0 16px #a78bfaee}}
    .rk{font-size:11px;padding:1px 8px;border-radius:999px;background:var(--panel2);color:var(--muted);white-space:nowrap}
    .rk-viewer{color:#f3c08d}.rk-expert{color:#d5dbe5}.rk-legend{color:#fde047}.rk-moderator{color:#6ee7b7}.rk-admin{color:#c4b5fd}
    .who{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
    .who a{font-weight:600}
    .muted{color:var(--muted);font-size:12px}
    .box{background:var(--panel);border-radius:var(--radius);padding:14px}
    .chatbox{height:min(60vh,520px);overflow:auto;display:flex;flex-direction:column;gap:10px;padding:12px}
    .msg-i{display:flex;gap:10px;align-items:flex-start}
    .msg-i .t{white-space:pre-wrap;word-break:break-word;margin-top:2px}
    .sys{align-self:center;background:var(--panel2);border-radius:8px;padding:6px 12px;font-size:13px;color:#fde68a;max-width:90%;white-space:pre-wrap}
    .x{margin-left:auto;background:none;border:0;color:var(--muted);cursor:pointer;padding:0 4px}
    .x:hover{color:var(--danger)}
    .composer{display:flex;gap:8px;margin-top:10px}
    .composer input,.composer textarea,.field{flex:1;min-width:0;background:var(--panel);border:1px solid var(--panel2);border-radius:10px;padding:9px 12px;outline:none;color:var(--text);font:inherit}
    .composer input:focus,.composer textarea:focus,.field:focus{border-color:var(--accent)}
    .notice{white-space:pre-wrap;background:var(--panel2);border-radius:8px;padding:8px 12px;font-size:13px;margin-top:8px}
    .prof{display:flex;gap:18px;align-items:center;flex-wrap:wrap}
    .prof h1{margin:0}
    .frow{display:flex;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--panel2)}
    .frow:last-child{border:0}
    .frow .sp{margin-left:auto;display:flex;gap:6px}
    .dot{width:9px;height:9px;border-radius:50%;background:#4b5563;display:inline-block}.dot.on{background:#22c55e}
    .tabs{display:flex;gap:6px;margin:10px 0;flex-wrap:wrap}
    .crit-wrap{margin-top:18px}
    .crit{margin-top:10px}
    .cmt{display:flex;gap:10px;padding:10px 0;border-bottom:1px solid var(--panel2)}
    .cmt .t{white-space:pre-wrap;word-break:break-word;margin-top:3px}
    dialog{background:var(--panel);color:var(--text);border:1px solid var(--panel2);border-radius:14px;padding:18px;width:min(92vw,360px)}
    dialog::backdrop{background:rgba(0,0,0,.6)}
    dialog form{display:flex;flex-direction:column;gap:10px}
    .toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--panel2);padding:10px 16px;border-radius:10px;z-index:50;box-shadow:0 6px 24px #000a;max-width:90vw}
    .err{color:var(--danger)}
    .room{margin-top:16px}
    .room .rhead{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px}
    .room .rmem{display:flex;gap:12px;flex-wrap:wrap;margin:8px 0}
    .room .rm{display:flex;gap:6px;align-items:center;font-size:13px}
    .room .rchat{max-height:180px;overflow:auto;display:flex;flex-direction:column;gap:6px;margin:8px 0;font-size:14px}
    .room .rchat div{word-break:break-word}
    .room .field{font-size:13px}
  </style>`));

  /* ---------- запросы ---------- */
  async function call(method, path, data) {
    const response = await fetch(path, {
      method, credentials: "same-origin",
      headers: method === "POST" ? { "Content-Type": "application/json", "X-Requested-With": "zerinet" } : {},
      body: method === "POST" ? JSON.stringify(data || {}) : undefined,
    });
    let json = {};
    try { json = await response.json(); } catch { /* не JSON */ }
    if (!response.ok) throw new Error(json.error || "Ошибка " + response.status);
    return json;
  }
  const get = (path) => call("GET", path);
  const post = (path, data) => call("POST", path, data);

  function toast(text) {
    const t = el(`<div class="toast">${esc(text)}</div>`);
    document.body.append(t);
    setTimeout(() => t.remove(), 3500);
  }

  const hue = (name) => [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
  function avatar(u, size = 40) {
    const inner = u.avatar ? `<img src="${esc(u.avatar)}" alt="">` : `<span class="ph" style="background:hsl(${hue(u.name)} 45% 38%)">${esc(u.name[0].toUpperCase())}</span>`;
    return `<span class="av frame-${esc(u.rank || "novice")}" style="--s:${size}px">${inner}</span>`;
  }
  const rankBadge = (u) => `<span class="rk rk-${esc(u.rank)}">${esc(u.rank_name || u.rank)}</span>`;
  const userLink = (u) => `<a href="#/user/${enc(u.name)}">${esc(u.name)}</a>`;
  const who = (u, size = 32) => `<span class="who">${avatar(u, size)}${userLink(u)}${rankBadge(u)}</span>`;
  function ago(ts) {
    const d = Math.max(0, Date.now() / 1000 - ts);
    if (d < 60) return "только что";
    if (d < 3600) return Math.floor(d / 60) + " мин назад";
    if (d < 86400) return Math.floor(d / 3600) + " ч назад";
    return new Date(ts * 1000).toLocaleDateString("ru-RU");
  }
  const isAdmin = () => S.user?.role === "admin";

  /* ---------- состояние и шапка ---------- */
  S.ready = get("/social/me").then((info) => {
    S.enabled = true; S.user = info.user; S.ranks = info.ranks; S.requests = info.requests;
  }).catch(() => { S.enabled = false; }).then(renderNav);

  function renderNav() {
    document.getElementById("znav")?.remove();
    if (!S.enabled) return;
    const u = S.user;
    const nav = el(`<nav id="znav">
      <a href="#/chat">Чат</a><a href="#/top">Топ</a>
      ${u ? `<a href="#/friends">Друзья${S.requests ? `<span class="badge">${S.requests}</span>` : ""}</a>
             <a class="me" href="#/user/${enc(u.name)}">${avatar(u, 28)}<span>${esc(u.name)}</span></a>`
          : `<a href="#" id="zlogin" class="primary">Войти</a>`}
    </nav>`);
    document.getElementById("logo").after(nav);
    nav.querySelector("#zlogin")?.addEventListener("click", (e) => { e.preventDefault(); openAuth(); });
  }

  async function refreshMe() {
    const info = await get("/social/me");
    S.user = info.user; S.requests = info.requests; renderNav();
  }

  /* ---------- вход / регистрация ---------- */
  function openAuth(afterLogin) {
    const dialog = el(`<dialog>
      <form method="dialog" id="zauth">
        <h2 style="margin:0" id="zt">Вход</h2>
        <input class="field" name="username" placeholder="Ник" autocomplete="username" maxlength="20" required>
        <input class="field" name="password" type="password" placeholder="Пароль (от 6 символов)" autocomplete="current-password" required>
        <div class="err" id="zerr"></div>
        <button class="btn primary" type="submit" id="zgo">Войти</button>
        <button class="btn" type="button" id="zsw">Нет аккаунта? Регистрация</button>
        <button class="btn" type="button" id="zcl">Отмена</button>
      </form></dialog>`);
    document.body.append(dialog);
    let register = false;
    const set = () => {
      dialog.querySelector("#zt").textContent = register ? "Регистрация" : "Вход";
      dialog.querySelector("#zgo").textContent = register ? "Создать аккаунт" : "Войти";
      dialog.querySelector("#zsw").textContent = register ? "Уже есть аккаунт? Войти" : "Нет аккаунта? Регистрация";
    };
    dialog.querySelector("#zsw").addEventListener("click", () => { register = !register; set(); });
    dialog.querySelector("#zcl").addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => dialog.remove());
    dialog.querySelector("#zauth").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(event.target);
      try {
        await post(register ? "/social/register" : "/social/login", { username: form.get("username"), password: form.get("password") });
        await refreshMe();
        dialog.close();
        toast(register ? "Аккаунт создан, добро пожаловать!" : "Вы вошли");
        (afterLogin || window.zApp.reroute)();
      } catch (error) {
        dialog.querySelector("#zerr").textContent = error.message;
      }
    });
    dialog.showModal();
  }

  const needLogin = (what) => `<div class="msg">${esc(what)} <button class="btn primary" data-login>Войти</button></div>`;
  function bindLogin(root) { root.querySelectorAll("[data-login]").forEach((b) => b.addEventListener("click", () => openAuth())); }

  /* ---------- чат ---------- */
  async function showChat() {
    const { app, newScreen, setCleanup } = window.zApp;
    newScreen();
    await S.ready;
    if (!S.enabled) { app.innerHTML = `<div class="msg err">Чат работает только с сервером (server.py)</div>`; return; }
    app.innerHTML = `<h2>Чат <span class="muted" id="zon"></span></h2>
      <div class="box chatbox" id="zlist"></div>
      <div id="znote"></div>
      ${S.user ? `<form class="composer" id="zform"><input id="ztext" maxlength="500" autocomplete="off" placeholder="${isAdmin() ? "Сообщение или команда (/help)" : "Напиши сообщение…"}"><button class="btn primary">Отправить</button></form>`
               : needLogin("Чтобы писать в чат,")}`;
    bindLogin(app);
    const list = document.getElementById("zlist");
    let signature = "";
    async function load() {
      let data;
      try { data = await get("/social/chat"); } catch { return; }
      document.getElementById("zon").textContent = "· онлайн: " + data.online;
      const sig = data.messages.map((m) => m.id).join(",");
      if (sig === signature) return;
      signature = sig;
      const stick = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
      list.innerHTML = data.messages.map((m) => m.kind === "system"
        ? `<div class="sys">📢 ${esc(m.text)}</div>`
        : `<div class="msg-i">${avatar(m.user, 34)}<div style="min-width:0;flex:1">
             <div class="who">${userLink(m.user)}${rankBadge(m.user)}<span class="muted">${ago(m.ts)}</span>${isAdmin() ? `<span class="muted">#${m.id}</span><button class="x" data-del="${m.id}" title="Удалить">✕</button>` : ""}</div>
             <div class="t">${esc(m.text)}</div></div></div>`).join("") || `<div class="msg">Пока тихо. Напиши первым!</div>`;
      if (stick) list.scrollTop = list.scrollHeight;
    }
    list.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-del]");
      if (!b) return;
      try { await post("/social/delete", { kind: "chat", id: Number(b.dataset.del) }); signature = ""; load(); } catch (error) { toast(error.message); }
    });
    document.getElementById("zform")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = document.getElementById("ztext");
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      try {
        const result = await post("/social/chat", { text });
        document.getElementById("znote").innerHTML = result.reply ? `<div class="notice">${esc(result.reply)}</div>` : "";
      } catch (error) { toast(error.message); input.value = text; }
      signature = ""; await load(); list.scrollTop = list.scrollHeight;
    });
    await load(); list.scrollTop = list.scrollHeight;
    const timer = setInterval(load, 3000);
    setCleanup(() => clearInterval(timer));
  }

  /* ---------- профиль ---------- */
  async function toJpeg(file) {
    const bitmap = await createImageBitmap(file);
    const side = Math.min(bitmap.width, bitmap.height);
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 256;
    canvas.getContext("2d").drawImage(bitmap, (bitmap.width - side) / 2, (bitmap.height - side) / 2, side, side, 0, 0, 256, 256);
    return canvas.toDataURL("image/jpeg", 0.85);
  }

  async function showUser(parts) {
    const { app, newScreen } = window.zApp;
    newScreen();
    await S.ready;
    if (!S.enabled) { app.innerHTML = `<div class="msg err">Профили работают только с сервером (server.py)</div>`; return; }
    app.innerHTML = `<div class="msg">Загружаем…</div>`;
    let u;
    try { u = await get("/social/user?name=" + enc(parts[1] || "")); } catch (error) { app.innerHTML = `<div class="msg err">${esc(error.message)}</div>`; return; }
    const self = u.relation === "self";
    const friendBtn = { none: ["add", "Добавить в друзья"], sent: ["remove", "Заявка отправлена (отменить)"], received: ["accept", "Принять заявку"], friends: ["remove", "Убрать из друзей"] }[u.relation];
    app.innerHTML = `
      <div class="box prof">
        ${avatar(u, 110)}
        <div style="flex:1;min-width:200px">
          <h1>${esc(u.name)} ${u.banned ? `<span class="err">(заблокирован)</span>` : ""}</h1>
          <div class="who">${rankBadge(u)}<span>⭐ ${u.points}</span><span class="muted"><span class="dot ${u.online ? "on" : ""}"></span> ${u.online ? "в сети" : "не в сети"}</span></div>
          <div class="muted" style="margin-top:4px">С нами с ${new Date(u.created * 1000).toLocaleDateString("ru-RU")} · комментариев: ${u.comments}</div>
          <div class="desc" style="margin-top:8px">${esc(u.bio) || `<span class="muted">О себе ничего не написано</span>`}</div>
          <div class="row">
            ${friendBtn && S.user ? `<button class="btn primary" id="zfr">${friendBtn[1]}</button>` : ""}
            ${!S.user && !self ? `<button class="btn primary" data-login>Войти, чтобы добавить в друзья</button>` : ""}
          </div>
        </div>
      </div>
      ${self ? `<div class="box" style="margin-top:14px">
        <h2 style="margin-top:0">Настройки профиля</h2>
        <div class="row"><input type="file" id="zfile" accept="image/*" hidden>
          <button class="btn" id="zpick">Сменить аватарку</button>
          <button class="btn" id="zrm" ${u.avatar ? "" : "disabled"}>Убрать аватарку</button></div>
        <textarea class="field" id="zbio" rows="3" maxlength="200" placeholder="О себе (до 200 символов)" style="width:100%">${esc(u.bio)}</textarea>
        <div class="row"><button class="btn primary" id="zsave">Сохранить</button>
          <button class="btn" id="zout">Выйти из аккаунта</button></div>
        <div class="muted">Очки и ранги (рамки у аватарки) выдают только админы.</div>
      </div>` : ""}
      <h2>Друзья (${u.friends.length})</h2>
      <div class="box">${u.friends.map((f) => `<div class="frow">${who(f, 34)}</div>`).join("") || `<span class="muted">Пока никого</span>`}</div>`;
    bindLogin(app);
    document.getElementById("zfr")?.addEventListener("click", async () => {
      try { await post("/social/friend", { name: u.name, action: friendBtn[0] }); await refreshMe(); showUser(parts); } catch (error) { toast(error.message); }
    });
    if (self) {
      const file = document.getElementById("zfile");
      document.getElementById("zpick").addEventListener("click", () => file.click());
      file.addEventListener("change", async () => {
        if (!file.files[0]) return;
        try { await post("/social/avatar", { data: await toJpeg(file.files[0]) }); await refreshMe(); toast("Аватарка обновлена"); showUser(parts); }
        catch (error) { toast(error.message || "Не удалось загрузить картинку"); }
      });
      document.getElementById("zrm").addEventListener("click", async () => { try { await post("/social/avatar", { data: null }); await refreshMe(); showUser(parts); } catch (error) { toast(error.message); } });
      document.getElementById("zsave").addEventListener("click", async () => { try { await post("/social/profile", { bio: document.getElementById("zbio").value }); toast("Сохранено"); } catch (error) { toast(error.message); } });
      document.getElementById("zout").addEventListener("click", async () => { await post("/social/logout"); await refreshMe(); location.hash = "#/"; });
    }
  }

  /* ---------- друзья ---------- */
  async function showFriends() {
    const { app, newScreen } = window.zApp;
    newScreen();
    await S.ready;
    if (!S.enabled) { app.innerHTML = `<div class="msg err">Друзья работают только с сервером (server.py)</div>`; return; }
    if (!S.user) { app.innerHTML = needLogin("Чтобы видеть друзей,"); bindLogin(app); return; }
    let tab = "friends", data;
    async function render() {
      data = await get("/social/friends");
      await refreshMe();
      const rows = (list, buttons) => list.map((f) => `<div class="frow">${who(f, 36)}${f.online !== undefined ? `<span class="dot ${f.online ? "on" : ""}" title="${f.online ? "в сети" : "не в сети"}"></span>` : ""}<span class="sp">${buttons(f)}</span></div>`).join("") || `<div class="muted">Здесь пусто</div>`;
      const tabs = [["friends", `Друзья (${data.friends.length})`], ["in", `Заявки (${data.incoming.length})`], ["out", `Исходящие (${data.outgoing.length})`], ["find", "Найти людей"]];
      app.innerHTML = `<h2>Друзья</h2><div class="tabs">${tabs.map(([k, t]) => `<button class="btn ${k === tab ? "on" : ""}" data-tab="${k}">${t}</button>`).join("")}</div>
        <div class="box" id="zbody">${
          tab === "friends" ? rows(data.friends, (f) => `<button class="btn" data-act="remove" data-n="${esc(f.name)}">Убрать</button>`)
          : tab === "in" ? rows(data.incoming, (f) => `<button class="btn primary" data-act="accept" data-n="${esc(f.name)}">Принять</button><button class="btn" data-act="decline" data-n="${esc(f.name)}">Отклонить</button>`)
          : tab === "out" ? rows(data.outgoing, (f) => `<button class="btn" data-act="remove" data-n="${esc(f.name)}">Отменить</button>`)
          : `<form class="composer" id="zsf"><input id="zq" placeholder="Ник (от 2 букв)" autocomplete="off"><button class="btn primary">Искать</button></form><div id="zres"></div>`}</div>`;
      app.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; render(); }));
      app.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", async () => {
        try { await post("/social/friend", { name: b.dataset.n, action: b.dataset.act }); render(); } catch (error) { toast(error.message); }
      }));
      document.getElementById("zsf")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const found = await get("/social/users?q=" + enc(document.getElementById("zq").value));
        const box = document.getElementById("zres");
        box.innerHTML = found.users.filter((x) => x.id !== S.user.id).map((f) => `<div class="frow">${who(f, 36)}<span class="sp"><button class="btn primary" data-add="${esc(f.name)}">В друзья</button></span></div>`).join("") || `<div class="muted" style="margin-top:8px">Никого не нашли</div>`;
        box.querySelectorAll("[data-add]").forEach((b) => b.addEventListener("click", async () => {
          try { await post("/social/friend", { name: b.dataset.add, action: "add" }); toast("Заявка отправлена"); b.disabled = true; } catch (error) { toast(error.message); }
        }));
      });
    }
    render().catch((error) => { app.innerHTML = `<div class="msg err">${esc(error.message)}</div>`; });
  }

  /* ---------- топ ---------- */
  async function showTop() {
    const { app, newScreen } = window.zApp;
    newScreen();
    await S.ready;
    if (!S.enabled) { app.innerHTML = `<div class="msg err">Топ работает только с сервером (server.py)</div>`; return; }
    const data = await get("/social/top");
    app.innerHTML = `<h2>Топ по очкам</h2><div class="box">${data.users.map((u, i) => `<div class="frow"><b style="width:26px">${i + 1}</b>${who(u, 38)}<span class="sp">⭐ ${u.points}</span></div>`).join("")}</div>
      <div class="muted" style="margin-top:8px">Очки и ранги выдают админы.</div>`;
  }

  /* ---------- «Критика» под аниме ---------- */
  async function mountCritic(root, alias) {
    await S.ready;
    if (!S.enabled || !root) return;
    root.innerHTML = `<div class="crit-wrap"><button class="btn primary" id="zct">Критика <span id="zcc"></span></button><div class="crit" id="zcp" hidden></div></div>`;
    const toggle = root.querySelector("#zct"), panel = root.querySelector("#zcp"), counter = root.querySelector("#zcc");
    let total = 0, oldest = 0, loaded = false;
    const item = (c) => `<div class="cmt" data-id="${c.id}">${avatar(c.user, 38)}<div style="min-width:0;flex:1">
      <div class="who">${userLink(c.user)}${rankBadge(c.user)}<span class="muted">${ago(c.ts)}</span>${isAdmin() || S.user?.id === c.user.id ? `<button class="x" data-del="${c.id}" title="Удалить">✕</button>` : ""}</div>
      <div class="t">${esc(c.text)}</div></div></div>`;
    async function page(first) {
      const data = await get(`/social/comments?alias=${enc(alias)}${first ? "" : "&before=" + oldest}`);
      total = data.total; counter.textContent = `(${total})`;
      if (data.comments.length) oldest = data.comments[data.comments.length - 1].id;
      return data;
    }
    function shell() {
      panel.innerHTML = `${S.user
        ? `<form class="composer" id="zcf"><textarea id="zct2" rows="3" maxlength="2000" placeholder="Что думаешь об этом аниме? Разбери сюжет, героев, режиссуру…"></textarea></form>
           <div class="row"><button class="btn primary" id="zcs">Отправить</button><span class="muted">до 2000 символов</span></div>`
        : needLogin("Чтобы писать критику,")}
        <div id="zcl"></div><div class="row"><button class="btn" id="zmore" hidden>Показать ещё</button></div>`;
      bindLogin(panel);
    }
    async function reload() {
      const data = await page(true);
      shell();
      panel.querySelector("#zcl").innerHTML = data.comments.map(item).join("") || `<div class="msg">Пока никто не высказался. Будь первым!</div>`;
      panel.querySelector("#zmore").hidden = !data.has_more;
      loaded = true;
    }
    panel.addEventListener("click", async (e) => {
      try {
        if (e.target.id === "zcs") {
          const box = panel.querySelector("#zct2");
          await post("/social/comments", { alias, text: box.value });
          await reload(); toast("Опубликовано");
        } else if (e.target.id === "zmore") {
          const data = await page(false);
          panel.querySelector("#zcl").insertAdjacentHTML("beforeend", data.comments.map(item).join(""));
          e.target.hidden = !data.has_more;
        } else if (e.target.dataset.del) {
          await post("/social/delete", { kind: "comment", id: Number(e.target.dataset.del) });
          await reload();
        }
      } catch (error) { toast(error.message); }
    });
    toggle.addEventListener("click", async () => {
      panel.hidden = !panel.hidden;
      if (!panel.hidden && !loaded) { try { await reload(); } catch (error) { toast(error.message); } }
    });
    try { await page(true); } catch { /* счётчик не критичен */ }
  }


  /* ---------- совместный просмотр ---------- */
  async function createRoom(alias, title, episode) {
    await S.ready;
    if (!S.user) { openAuth(); return; }
    try {
      const result = await post("/social/room/create", { alias, title, episode });
      location.hash = "#/room/" + result.code;
    } catch (error) { toast(error.message); }
  }

  async function showRoom(parts) {
    const { app, newScreen } = window.zApp;
    newScreen();
    await S.ready;
    if (!S.enabled) { app.innerHTML = `<div class="msg err">Совместный просмотр работает только с сервером (server.py)</div>`; return; }
    if (!S.user) { app.innerHTML = needLogin("Чтобы смотреть вместе,"); bindLogin(app); return; }
    const code = String(parts[1] || "").toUpperCase();
    let data;
    try { data = await get("/social/room?code=" + enc(code)); } catch (error) { app.innerHTML = `<div class="msg err">${esc(error.message)}</div>`; return; }
    window.zApp.showTitle(data.state.alias, data.state.episode, { room: code });
  }

  // ctx: { video, container, count, getIndex(), setEpisode(i), onEpisode, ready() } из страницы аниме
  function attachRoom(code, ctx) {
    const root = ctx.container, video = ctx.video;
    const link = location.origin + location.pathname + "#/room/" + code;
    root.innerHTML = `<div class="box room">
      <div class="rhead"><b>👥 Комната ${esc(code)}</b><span class="muted" id="rstat">подключаемся…</span></div>
      <div class="row"><input class="field" id="rlink" readonly value="${esc(link)}"><button class="btn" id="rcopy">Скопировать ссылку</button>
        <button class="btn" id="rshared" hidden></button><button class="btn primary" id="rjoin" hidden>▶ Присоединиться к просмотру</button></div>
      <div class="rmem" id="rmem"></div>
      <div class="rchat" id="rchat"></div>
      <form class="composer" id="rform"><input id="rtext" maxlength="300" autocomplete="off" placeholder="Сообщение комнате…"><button class="btn primary">→</button></form></div>`;
    const $ = (id) => root.querySelector("#" + id);
    let state, offset = 0, controller = false, ignoreUntil = 0, lastChat = 0, signature = "", closed = false;
    const serverNow = () => Date.now() / 1000 + offset;
    const expected = () => (state.playing ? state.pos + (serverNow() - state.ts) : state.pos);
    const mutate = (fn) => { ignoreUntil = Date.now() + 800; fn(); };
    const say = (text) => { $("rstat").textContent = text; };

    function apply() {
      if (!state || closed) return;
      if (ctx.getIndex() + 1 !== state.episode) { ctx.setEpisode(Math.min(state.episode, ctx.count) - 1); return; }
      if (!ctx.ready()) { say("загружаем видео…"); return; }
      const want = expected(), drift = Math.abs(video.currentTime - want);
      if (drift > 1.6 || (!state.playing && drift > 0.4)) mutate(() => { video.currentTime = want; });
      if (state.playing && video.paused) mutate(() => video.play().then(() => { $("rjoin").hidden = true; }).catch(() => { $("rjoin").hidden = false; }));
      else if (!state.playing && !video.paused) mutate(() => video.pause());
      say(controller ? (drift < 1.7 ? "синхронно ✓" : "подстраиваемся…") : `синхронно ✓ · управляет ${state.host?.name || "хост"}`);
    }

    function send(payload) {
      return post("/social/room/control", { code, ...payload }).then((r) => { state = r.state; }).catch((error) => toast(error.message));
    }
    const onUser = (action) => {
      if (Date.now() < ignoreUntil || !ctx.ready()) return;
      if (!controller) { apply(); return; }                // не управляющему возвращаем всё как было
      send({ action, position: video.currentTime });
    };
    video.addEventListener("play", () => onUser("play"));
    video.addEventListener("pause", () => { if (!video.ended) onUser("pause"); });
    video.addEventListener("seeked", () => onUser("seek"));
    ctx.onEpisode = (i) => {
      if (!controller) { toast("Серию выбирает " + (state?.host?.name || "хост")); apply(); return; }
      send({ action: "episode", episode: i + 1 });
    };

    function renderMembers(list) {
      $("rmem").innerHTML = list.map((m) => `<span class="rm">${avatar(m, 26)}<a href="#/user/${enc(m.name)}">${esc(m.name)}</a>${m.host ? "👑" : ""}</span>`).join("");
      const host = list.find((m) => m.host);
      const shared = $("rshared");
      shared.hidden = !(S.user && host && host.id === S.user.id);
      shared.textContent = state?.shared ? "Управление: все" : "Управление: только я";
    }
    function renderChat(messages) {
      if (!messages.length) return;
      const box = $("rchat"), stick = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
      box.insertAdjacentHTML("beforeend", messages.map((m) => `<div><b>${m.user ? esc(m.user.name) : "?"}:</b> ${esc(m.text)}</div>`).join(""));
      lastChat = messages[messages.length - 1].id;
      if (stick) box.scrollTop = box.scrollHeight;
    }

    async function poll() {
      if (closed) return;
      let data;
      try { data = await get(`/social/room?code=${enc(code)}&v=${state ? state.version : 0}&c=${lastChat}`); }
      catch (error) {
        if (/не найдена|закрыта/.test(error.message)) { closed = true; clearInterval(timer); say("комната закрыта"); }
        return;
      }
      offset = data.now - Date.now() / 1000;
      controller = data.controller;
      if (!data.same) state = data.state;
      renderMembers(data.members); renderChat(data.chat);
      apply();
    }

    $("rcopy").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(link); toast("Ссылка скопирована"); } catch { $("rlink").select(); document.execCommand("copy"); toast("Ссылка скопирована"); }
    });
    $("rjoin").addEventListener("click", () => { mutate(() => video.play().then(() => { $("rjoin").hidden = true; }).catch(() => {})); });
    $("rshared").addEventListener("click", async () => {
      try { const r = await post("/social/room/settings", { code, shared: !state?.shared }); state = r.state; renderMembers([]); poll(); } catch (error) { toast(error.message); }
    });
    $("rform").addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = $("rtext"), text = input.value.trim();
      if (!text) return;
      input.value = "";
      try { await post("/social/room/say", { code, text }); poll(); } catch (error) { toast(error.message); input.value = text; }
    });
    $("rlink").addEventListener("focus", (e) => e.target.select());

    const timer = setInterval(poll, 1000);
    window.zApp.addCleanup(() => { closed = true; clearInterval(timer); });
    poll();
  }

  /* ---------- экспорт ---------- */
  window.zSocial = S;
  S.mountCritic = mountCritic;
  S.openAuth = openAuth;
  S.createRoom = createRoom;
  S.attachRoom = attachRoom;
  window.zRoutes = {
    chat: showChat,
    user: showUser,
    friends: showFriends,
    top: showTop,
    room: showRoom,
    me: async () => { await S.ready; if (S.user) location.hash = "#/user/" + enc(S.user.name); else { location.hash = "#/"; openAuth(); } },
  };
})();
