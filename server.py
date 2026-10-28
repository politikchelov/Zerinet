"""Локальный сервер ZERINET: сайт, прокси к AniLibria/Kodik, аккаунты, чат и «Критика».
Запуск:   py server.py        (потом открой http://localhost:8080)
Админ:    py server.py admin НИК     — сделать пользователя админом (он должен быть зарегистрирован)
          py server.py unadmin НИК   — забрать админку
          py server.py users         — список зарегистрированных
Ещё способ: впиши ник в файл admins.txt рядом с server.py (по одному в строке) — он станет админом.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import social

PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "127.0.0.1")           # для интернета на своём сервере: HOST=0.0.0.0
TRUST_PROXY = os.environ.get("TRUST_PROXY") == "1"   # за nginx/Caddy/Render: брать IP из X-Forwarded-For
UPSTREAMS = os.environ.get(
    "UPSTREAMS",
    "https://aniliberty.top/api/v1,https://anilibria.top/api/v1,https://api.anilibria.app/api/v1",
).split(",")
ROOT = os.path.dirname(os.path.abspath(__file__))
# отдаём наружу ТОЛЬКО эти файлы (токен, база данных и код сервера недоступны по адресу)
STATIC_FILES = {"/": "index.html", "/index.html": "index.html", "/social.js": "social.js"}
MAX_BODY = 400_000

# Токен Kodik: переменная окружения KODIK_TOKEN или файл kodik_token.txt рядом с server.py.
KODIK_API = os.environ.get("KODIK_API", "https://kodik-api.com").rstrip("/")
KODIK_ALLOWED = {"title", "shikimori_id", "with_material_data", "types", "limit", "strict", "year"}


def read_kodik_token():
    token = os.environ.get("KODIK_TOKEN", "").strip()
    if token:
        return token
    try:
        with open(os.path.join(ROOT, "kodik_token.txt"), encoding="utf-8-sig") as file:
            return file.read().strip()
    except OSError:
        return ""


KODIK_TOKEN = read_kodik_token()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        # файлы сайта не должны застревать в кеше браузера после обновления
        if not getattr(self, "_has_cache_header", False):
            self.send_header("Cache-Control", "no-cache")
        self._has_cache_header = False
        super().end_headers()

    def client_ip(self):
        if TRUST_PROXY:
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def is_https(self):
        return self.headers.get("X-Forwarded-Proto", "") == "https"

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            return self.proxy(self.path[len("/api"):])
        if path.startswith("/kodik/"):
            return self.kodik(parsed)
        if path.startswith("/social/"):
            return self.social("GET", parsed, b"")
        if path.startswith("/avatars/"):
            data = social.read_avatar(path[len("/avatars/"):])
            if data is None:
                return self.reply(404, "text/plain", b"not found")
            return self.reply(200, "image/jpeg", data, cache="public, max-age=604800")
        if path in STATIC_FILES:
            self.path = "/" + STATIC_FILES[path]
            return super().do_GET()
        return self.reply(404, "text/plain; charset=utf-8", b"Not found")

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/social/"):
            return self.reply(404, "text/plain", b"not found")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > MAX_BODY:
            return self.reply(413, "application/json", '{"error":"Слишком большой запрос"}'.encode())
        body = self.rfile.read(length) if length else b""
        return self.social("POST", parsed, body)

    def social(self, method, parsed, body):
        status, payload, cookie = social.handle(
            method, parsed.path, parsed.query, body, self.headers, self.client_ip(), self.is_https()
        )
        extra = {"Set-Cookie": cookie} if cookie is not None else None
        self.reply(status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode(), extra=extra)

    # ---------------------------------------------------------------- прокси
    def kodik(self, parsed):
        if parsed.path == "/kodik/status":
            return self.reply(200, "application/json", json.dumps({"enabled": bool(KODIK_TOKEN)}).encode())
        if parsed.path != "/kodik/search" or not KODIK_TOKEN:
            return self.reply(404, "application/json", b'{"error":"not_available"}')
        # из запроса берём только разрешённые параметры, свой токен браузера игнорируем
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items() if k in KODIK_ALLOWED}
        query["token"] = KODIK_TOKEN
        url = KODIK_API + "/search?" + urllib.parse.urlencode(query)
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 zerinet-local"})
            with urllib.request.urlopen(request, timeout=15) as response:
                return self.reply(response.status, "application/json", response.read())
        except urllib.error.HTTPError as error:
            body = error.read() or b'{"error":"kodik_error"}'
            print("Kodik ответил HTTP %d: %s" % (error.code, body[:200].decode("utf-8", "replace")), file=sys.stderr)
            return self.reply(error.code, "application/json", body)
        except Exception as error:
            print("kodik error:", error, file=sys.stderr)
            return self.reply(502, "application/json", b'{"error":"kodik_unavailable"}')

    def proxy(self, path):
        last_status = 502
        for base in UPSTREAMS:
            request = urllib.request.Request(base.strip() + path, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 zerinet-local"})
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    return self.reply(response.status, response.headers.get("Content-Type", "application/json"), response.read())
            except urllib.error.HTTPError as error:
                body = error.read()
                if error.code == 404 and "json" in (error.headers.get("Content-Type") or ""):
                    return self.reply(404, "application/json", body)
                last_status = error.code
            except Exception as error:  # сеть, таймаут и т.п. -> пробуем зеркало
                print("upstream error:", base, error, file=sys.stderr)
                last_status = 504
        self.reply(502, "application/json", ('{"error":"upstream_unavailable","status":%d}' % last_status).encode())

    def reply(self, status, content_type, body, extra=None, cache="no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self._has_cache_header = True
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "users":
        print(social.list_users())
        sys.exit(0)
    if len(sys.argv) >= 3 and sys.argv[1] in ("admin", "unadmin"):
        print(social.set_admin(sys.argv[2], sys.argv[1] == "admin"))
        sys.exit(0)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = "http://localhost:%d" % PORT
    print("Сайт запущен:", url, "(останови: Ctrl+C)")
    print("Kodik:", "включён (токен найден)" if KODIK_TOKEN else "выключен (нет токена)")
    print("Данные (база и аватарки):", social.DATA_DIR)
    if os.environ.get("NO_BROWSER") != "1" and HOST == "127.0.0.1":
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
