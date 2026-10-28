// Vercel-функция: ходит в Kodik с токеном из переменной окружения KODIK_TOKEN (в браузер токен не попадает).
const ALLOWED = ["title", "shikimori_id", "with_material_data", "types", "limit", "strict", "year"];

module.exports = async (req, res) => {
  const token = process.env.KODIK_TOKEN || "";
  const url = new URL(req.url, "http://localhost");
  const action = url.searchParams.get("action");
  res.setHeader("Content-Type", "application/json");

  if (action === "status") return res.status(200).end(JSON.stringify({ enabled: Boolean(token) }));
  if (action !== "search" || !token) return res.status(404).end('{"error":"not_available"}');

  const query = new URLSearchParams();
  for (const key of ALLOWED) if (url.searchParams.has(key)) query.set(key, url.searchParams.get(key));
  query.set("token", token);

  try {
    const response = await fetch("https://kodik-api.com/search?" + query, { headers: { Accept: "application/json" } });
    res.status(response.status).end(await response.text());
  } catch {
    res.status(502).end('{"error":"kodik_unavailable"}');
  }
};
