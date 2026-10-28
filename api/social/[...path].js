"use strict";
// Vercel serverless replacement for the old SQLite-backed /social/* routes.
// Required server-only environment variables: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
const crypto = require("node:crypto");

const RANKS = {
  novice: "Новичок", viewer: "Зритель", expert: "Знаток",
  legend: "Легенда", moderator: "Модератор", admin: "Админ"
};
const USERNAME_RE = /^[A-Za-z0-9_\-А-Яа-яЁё]{3,20}$/;
const ALIAS_RE = /^[\w.\-]{1,120}$/;
const now = () => Math.floor(Date.now() / 1000);
const sha = (v) => crypto.createHash("sha256").update(v).digest("hex");
const passwordHash = (password, salt) =>
  crypto.scryptSync(password, Buffer.from(salt, "hex"), 32).toString("hex");
const clean = (v, n) => String(v ?? "").replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, "").trim().slice(0, n);
const json = (res, status, data, extra = {}) => {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");
  for (const [k,v] of Object.entries(extra)) res.setHeader(k, v);
  res.end(JSON.stringify(data));
};
function config() {
  const url = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
  // Prefer the Supabase integration-managed secret key; a manually added legacy key may be stale.
  const key = process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) throw new Error("Supabase server environment variables are not configured");
  return { url: url.replace(/\/$/, ""), key };
}
async function db(table, method = "GET", query = "", body, prefer) {
  const c = config();
  const headers = { apikey: c.key, Authorization: "Bearer " + c.key, Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (prefer) headers.Prefer = prefer;
  const r = await fetch(c.url + "/rest/v1/" + table + (query ? "?" + query : ""), {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body)
  });
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch {}
  if (!r.ok) {
    const e = new Error(data?.message || "Database request failed");
    e.status = r.status; throw e;
  }
  return data;
}
const cookie = (req) => {
  const raw = req.headers.cookie || "";
  const m = raw.match(/(?:^|;\s*)zsid=([^;]+)/);
  try { return m ? decodeURIComponent(m[1]) : ""; } catch { return ""; }
};
const sessionCookie = (token, age = 30 * 86400) =>
  "zsid=" + encodeURIComponent(token) + "; Path=/; HttpOnly; SameSite=Lax; Secure; Max-Age=" + age;
const publicUser = (u) => ({
  id:u.id, name:u.name, rank:u.rank, rank_name:RANKS[u.rank] || u.rank,
  role:u.role, avatar:u.avatar || "", points:u.points || 0, bio:u.bio || ""
});
async function currentUser(req) {
  const token = cookie(req);
  if (!token) return null;
  const sessions = await db("zerinet_sessions", "GET",
    "select=token_hash,user_id,expires&token_hash=eq." + encodeURIComponent(sha(token)) + "&expires=gt." + now() + "&limit=1");
  if (!sessions?.length) return null;
  const users = await db("zerinet_users", "GET",
    "select=*&id=eq." + sessions[0].user_id + "&limit=1");
  const u = users?.[0];
  if (!u || u.banned) return null;
  await db("zerinet_users", "PATCH", "id=eq." + u.id, {last_seen:now()});
  return u;
}
async function insertSession(userId) {
  const token = crypto.randomBytes(32).toString("base64url");
  await db("zerinet_sessions", "POST", "", {
    token_hash:sha(token), user_id:userId, expires:now()+30*86400
  }, "return=minimal");
  return token;
}
async function requireUser(req) {
  const u = await currentUser(req);
  if (!u) { const e = new Error("Нужно войти в аккаунт"); e.status = 401; throw e; }
  return u;
}
async function countIncoming(userId) {
  const a = await db("zerinet_friends","GET","select=user_id&other_id=eq."+userId+"&status=eq.pending");
  return a?.length || 0;
}
async function handle(req, res) {
  if (req.method !== "GET" && req.method !== "POST") return json(res,405,{error:"Метод не поддерживается"},{Allow:"GET, POST"});
  if (req.method === "POST") {
    if (req.headers["x-requested-with"] !== "zerinet") return json(res,403,{error:"Запрос отклонён"});
    const origin = req.headers.origin;
    if (origin && new URL(origin).host !== req.headers.host) return json(res,403,{error:"Запрос отклонён"});
  }
  let data = req.body || {};
  if (typeof data === "string") { try { data = JSON.parse(data || "{}"); } catch { return json(res,400,{error:"Плохой JSON"}); } }
  if (!data || typeof data !== "object" || Array.isArray(data)) data = {};
  const url = new URL(req.url, "https://zerinet.vercel.app");
  // Vercel rewrites can expose either the destination path or the original path.
  // Normalize both /api/social/* and /social/* so every endpoint reaches the same handler.
  const rawPath = url.searchParams.get("path") || url.pathname;
  const normalizedPath = rawPath.replace(/^\/(?:api\/social|social)\/?/, "").replace(/^\/+/, "");
  const path = "/" + normalizedPath;
  try {
    if (req.method === "GET" && path === "/me") {
      const u = await currentUser(req);
      return json(res,200,{enabled:true,user:u?publicUser(u):null,requests:u?await countIncoming(u.id):0,ranks:Object.entries(RANKS).map(([key,name])=>({key,name}))});
    }
    if (req.method === "POST" && path === "/register") {
      const name = clean(data.username,20), password = String(data.password || "");
      if (!USERNAME_RE.test(name)) return json(res,400,{error:"Ник: 3–20 символов, буквы, цифры, _ и -"});
      if (password.length < 6 || password.length > 100) return json(res,400,{error:"Пароль: от 6 символов"});
      const salt = crypto.randomBytes(16).toString("hex");
      const rows = await db("zerinet_users","POST","",{name,name_key:name.toLowerCase(),password_salt:salt,password_hash:passwordHash(password,salt),created:now(),last_seen:now()},"return=representation");
      const u = rows?.[0];
      if (!u) throw new Error("Не удалось создать аккаунт");
      const token = await insertSession(u.id);
      return json(res,200,{ok:true,user:publicUser(u)},{"Set-Cookie":sessionCookie(token)});
    }
    if (req.method === "POST" && path === "/login") {
      const name = clean(data.username,20).toLowerCase(), password = String(data.password || "");
      const rows = await db("zerinet_users","GET","select=*&name_key=eq."+encodeURIComponent(name)+"&limit=1");
      const u = rows?.[0];
      if (!u || !crypto.timingSafeEqual(Buffer.from(passwordHash(password,u.password_salt),"hex"),Buffer.from(u.password_hash,"hex")))
        return json(res,401,{error:"Неверный ник или пароль"});
      if (u.banned) return json(res,403,{error:"Аккаунт заблокирован. Причина: "+(u.ban_reason||"не указана")});
      const token = await insertSession(u.id);
      return json(res,200,{ok:true,user:publicUser(u)},{"Set-Cookie":sessionCookie(token)});
    }
    if (req.method === "POST" && path === "/logout") {
      const token = cookie(req);
      if (token) await db("zerinet_sessions","DELETE","token_hash=eq."+sha(token));
      return json(res,200,{ok:true},{"Set-Cookie":sessionCookie("",0)});
    }
    if (req.method === "GET" && path === "/chat") {
      const rows = await db("zerinet_chat","GET","select=id,user_id,kind,text,created&deleted=eq.false&order=id.desc&limit=80");
      const messages = [];
      for (const r of (rows||[]).reverse()) {
        const users = r.user_id ? await db("zerinet_users","GET","select=id,name,rank,role,avatar&id=eq."+r.user_id+"&limit=1") : [];
        messages.push({id:r.id,kind:r.kind,text:r.text,ts:r.created,user:users?.[0]?publicUser(users[0]):null});
      }
      const onlineRows = await db("zerinet_users","GET","select=id&last_seen=gt."+(now()-120));
      return json(res,200,{messages,online:onlineRows?.length||0});
    }
    if (req.method === "POST" && path === "/chat") {
      const u = await requireUser(req), text = clean(data.text,500);
      if (!text) return json(res,400,{error:"Пустое сообщение"});
      if (u.muted_until > now()) return json(res,403,{error:"Тебя заглушили"});
      if (text.startsWith("/")) return json(res,403,{error:"Команды доступны только администраторам"});
      const rows = await db("zerinet_chat","POST","",{user_id:u.id,kind:"msg",text,created:now()},"return=representation");
      return json(res,200,{ok:true,id:rows?.[0]?.id});
    }
    if (req.method === "GET" && path === "/comments") {
      const alias = url.searchParams.get("alias") || "";
      if (!ALIAS_RE.test(alias)) return json(res,400,{error:"Плохой адрес аниме"});
      const before = Number(url.searchParams.get("before")) || Number.MAX_SAFE_INTEGER;
      const rows = await db("zerinet_comments","GET","select=id,alias,user_id,text,created&alias=eq."+encodeURIComponent(alias)+"&deleted=eq.false&id=lt."+before+"&order=id.desc&limit=21");
      const comments=[];
      for (const r of (rows||[]).slice(0,20)) {
        const users=await db("zerinet_users","GET","select=id,name,rank,role,avatar&id=eq."+r.user_id+"&limit=1");
        if (users?.[0]) comments.push({id:r.id,text:r.text,ts:r.created,user:publicUser(users[0])});
      }
      const all = await db("zerinet_comments","GET","select=id&alias=eq."+encodeURIComponent(alias)+"&deleted=eq.false");
      return json(res,200,{comments,total:all?.length||0,has_more:(rows||[]).length>20});
    }
    if (req.method === "POST" && path === "/comments") {
      const u=await requireUser(req), alias=String(data.alias||""), text=clean(data.text,2000);
      if (!ALIAS_RE.test(alias)) return json(res,400,{error:"Плохой адрес аниме"});
      if (text.length<2) return json(res,400,{error:"Слишком короткий текст"});
      const rows=await db("zerinet_comments","POST","",{alias,user_id:u.id,text,created:now()},"return=representation");
      return json(res,200,{ok:true,id:rows?.[0]?.id});
    }
    if (req.method === "GET" && path === "/top") {
      const rows=await db("zerinet_users","GET","select=id,name,rank,role,avatar,points&banned=eq.false&order=points.desc&limit=20");
      return json(res,200,{users:(rows||[]).map(publicUser)});
    }
    if (req.method === "GET" && path === "/users") {
      const q=clean(url.searchParams.get("q"),20);
      if (q.length<2) return json(res,200,{users:[]});
      const rows=await db("zerinet_users","GET","select=id,name,rank,role,avatar&name=ilike.*"+encodeURIComponent(q)+"*&banned=eq.false&limit=20");
      return json(res,200,{users:(rows||[]).map(publicUser)});
    }
    if (req.method === "GET" && path === "/user") {
      const name=clean(url.searchParams.get("name"),20).toLowerCase();
      const rows=await db("zerinet_users","GET","select=id,name,rank,role,avatar,points,bio,created,last_seen,banned&name_key=eq."+encodeURIComponent(name)+"&limit=1");
      const u=rows?.[0]; if (!u) return json(res,404,{error:"Пользователь не найден"});
      const friends=await db("zerinet_friends","GET","select=user_id,other_id,status&status=eq.accepted&or=(user_id.eq."+u.id+",other_id.eq."+u.id+")&limit=60");
      const comments=await db("zerinet_comments","GET","select=id&user_id=eq."+u.id+"&deleted=eq.false");
      const me=await currentUser(req);
      let relation="none";
      if (me?.id===u.id) relation="self";
      else if(me) {
        const f=await db("zerinet_friends","GET","select=user_id,other_id,status&or=(and(user_id.eq."+me.id+",other_id.eq."+u.id+"),and(user_id.eq."+u.id+",other_id.eq."+me.id+"))&limit=1");
        if(f?.[0]) relation=f[0].status==="accepted"?"friends":(f[0].user_id===me.id?"sent":"received");
      }
      const friendsOut=[];
      for(const f of friends) { const id=f.user_id===u.id?f.other_id:f.user_id; const a=await db("zerinet_users","GET","select=id,name,rank,role,avatar&id=eq."+id+"&limit=1"); if(a?.[0]) friendsOut.push(publicUser(a[0]));}
      return json(res,200,{...publicUser(u),created:u.created,online:now()-u.last_seen<120,banned:u.banned,relation,friends:friendsOut,comments:comments?.length||0});
    }
    if (req.method === "POST" && path === "/profile") {
      const u=await requireUser(req), bio=clean(data.bio,200);
      await db("zerinet_users","PATCH","id=eq."+u.id,{bio});
      return json(res,200,{ok:true,bio});
    }
    if (req.method === "GET" && path === "/friends") {
      const u=await requireUser(req);
      const rows=await db("zerinet_friends","GET","select=user_id,other_id,status&or=(user_id.eq."+u.id+",other_id.eq."+u.id+")");
      const incoming=[],outgoing=[],friends=[];
      for(const f of rows||[]) {
        const otherId=f.user_id===u.id?f.other_id:f.user_id;
        const a=await db("zerinet_users","GET","select=id,name,rank,role,avatar,last_seen&id=eq."+otherId+"&limit=1");
        if(!a?.[0]) continue; const item={...publicUser(a[0]),online:now()-a[0].last_seen<120};
        if(f.status==="accepted") friends.push(item);
        else if(f.other_id===u.id) incoming.push(item); else outgoing.push(item);
      }
      return json(res,200,{friends,incoming,outgoing});
    }
    if (req.method === "POST" && path === "/friend") {
      const u=await requireUser(req), name=clean(data.name,20).toLowerCase(), action=data.action;
      const targets=await db("zerinet_users","GET","select=id,name&id=eq."+0+"&limit=1");
      const found=await db("zerinet_users","GET","select=id,name&name_key=eq."+encodeURIComponent(name)+"&limit=1");
      const other=found?.[0]; if(!other||other.id===u.id) return json(res,404,{error:"Пользователь не найден"});
      const rel=await db("zerinet_friends","GET","select=user_id,other_id,status&or=(and(user_id.eq."+u.id+",other_id.eq."+other.id+"),and(user_id.eq."+other.id+",other_id.eq."+u.id+"))&limit=1");
      const state=rel?.[0]?(rel[0].status==="accepted"?"friends":(rel[0].user_id===u.id?"sent":"received")):"none";
      if(action==="add"&&state==="received") {
        await db("zerinet_friends","PATCH","user_id=eq."+other.id+"&other_id=eq."+u.id,{status:"accepted"});
      } else if(action==="add"&&state==="none") {
        await db("zerinet_friends","POST","",{user_id:u.id,other_id:other.id,status:"pending",created:now()},"return=minimal");
      } else if(action==="accept"&&state==="received") {
        await db("zerinet_friends","PATCH","user_id=eq."+other.id+"&other_id=eq."+u.id,{status:"accepted"});
      } else if(["decline","remove"].includes(action)) {
        await db("zerinet_friends","DELETE","or=(and(user_id.eq."+u.id+",other_id.eq."+other.id+"),and(user_id.eq."+other.id+",other_id.eq."+u.id+"))");
      } else return json(res,409,{error:"Нельзя выполнить это действие"});
      return json(res,200,{ok:true});
    }
    if (req.method === "POST" && path === "/delete") {
      const u=await requireUser(req), id=Number(data.id), kind=data.kind;
      if(!Number.isSafeInteger(id)||id<1) return json(res,400,{error:"Неверный id"});
      if(kind==="comment") {
        const rows=await db("zerinet_comments","GET","select=id,user_id&id=eq."+id+"&limit=1");
        if(!rows?.[0]) return json(res,404,{error:"Не найдено"});
        if(rows[0].user_id!==u.id&&u.role!=="admin") return json(res,403,{error:"Нельзя"});
        await db("zerinet_comments","PATCH","id=eq."+id,{deleted:true});
      } else if(kind==="chat"&&u.role==="admin") await db("zerinet_chat","PATCH","id=eq."+id,{deleted:true});
      else return json(res,403,{error:"Нельзя"});
      return json(res,200,{ok:true});
    }
    return json(res,404,{error:"Не найдено"});
  } catch (e) {
    const status = e.status || (String(e.message).includes("Supabase server environment") ? 503 : 500);
    return json(res,status,{error:status===503?"Серверная база не настроена":status===500?"Ошибка сервера":e.message});
  }
}
module.exports = async (req, res) => handle(req, res);
