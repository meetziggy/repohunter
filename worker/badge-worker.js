/* RepoHunter badge + report-card Worker — Cloudflare Workers (free tier).
 *
 * Live, self-updating SVG for any PUBLIC repo. The owner embeds it but CANNOT edit the verdict —
 * that's the whole point: it's trustworthy because it reflects the current, transparent score.
 *
 *   /badge/:owner/:name.svg   → shields-style badge:  repohunter | GO 82
 *   /card/:owner/:name.svg    → shareable report card (facts + scores + verdict)
 *   /health                   → ok
 *
 * Scores are a transparent heuristic over live GitHub data — guidance, not a guarantee, and NOT a
 * safety/security claim (that layer ships only after validation). No fabricated numbers. No verdict
 * on people. Optional GITHUB_TOKEN secret raises the rate limit. MIT (c) 2026 Chris Gorzelic.
 */
const GREEN = "#34d399", AMBER = "#fbbf24", RED = "#fb7185", DARK = "#0b1220", LIME = "#b8ff3c",
      CYAN = "#38bdf8", LINE = "#22304a", TEXT = "#e6edf7", MUTED = "#8fa0bd";

const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function days(iso) {
  const t = Date.parse(iso || "");
  return isFinite(t) ? Math.max(0, Math.floor((Date.now() - t) / 86400000)) : 9999;
}

function score(m) {
  const stars = m.stargazers_count || 0;
  const pop = Math.min(100, Math.round(Math.log10(stars + 1) * 22));
  const fd = days(m.pushed_at);
  const fresh = fd < 30 ? 100 : fd < 90 ? 80 : fd < 365 ? 55 : 25;
  const spdx = (m.license && m.license.spdx_id) || "";
  let health = 70 + (spdx && spdx !== "NOASSERTION" ? 15 : 0) + (stars > 1000 ? 10 : 0) - (m.archived ? 40 : 0);
  health = Math.max(0, Math.min(100, health));
  const age = days(m.created_at);
  const mat = Math.min(100, (age > 365 ? 20 : 5) + Math.min(50, Math.round(Math.log10(stars + 1) * 12)));
  const overall = Math.round(pop * 0.3 + fresh * 0.25 + health * 0.25 + mat * 0.2);
  const verdict = m.archived ? "SKIP" : overall >= 68 ? "GO" : overall >= 45 ? "MAYBE" : "SKIP";
  return { pop, fresh, health, mat, overall, verdict };
}

const vColor = (v) => (v === "GO" ? GREEN : v === "MAYBE" ? AMBER : RED);

async function fetchRepo(slug, env) {
  const h = { "User-Agent": "RepoHunter-Badge", Accept: "application/vnd.github+json" };
  if (env && env.GITHUB_TOKEN) h.Authorization = "Bearer " + env.GITHUB_TOKEN;
  const r = await fetch("https://api.github.com/repos/" + slug, { headers: h, cf: { cacheTtl: 1800, cacheEverything: true } });
  if (!r.ok) return null;
  return r.json();
}

// ── shields-style badge ────────────────────────────────────────────────────
function badgeSVG(label, message, color, msgDark) {
  const cw = 6.6;                                  // approx char width @ 11px
  const lw = Math.round(label.length * cw) + 22;   // + room for the lime dot
  const mw = Math.round(message.length * cw) + 16;
  const w = lw + mw, mtc = msgDark ? "#1a2233" : "#fff";
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="20" role="img" aria-label="${esc(label)}: ${esc(message)}">
<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#fff" stop-opacity=".08"/><stop offset="1" stop-opacity=".12"/></linearGradient>
<clipPath id="r"><rect width="${w}" height="20" rx="4" fill="#fff"/></clipPath>
<g clip-path="url(#r)">
  <rect width="${lw}" height="20" fill="${DARK}"/>
  <rect x="${lw}" width="${mw}" height="20" fill="${color}"/>
  <rect width="${w}" height="20" fill="url(#s)"/>
</g>
<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
  <circle cx="11" cy="10.5" r="3.1" fill="${LIME}"/>
  <text x="${(lw + 12) / 2 + 4}" y="15" fill="${TEXT}">${esc(label)}</text>
  <text x="${lw + mw / 2}" y="15" fill="${mtc}" font-weight="bold">${esc(message)}</text>
</g></svg>`;
}

// ── shareable report card ──────────────────────────────────────────────────
function bar(x, y, label, val) {
  const w = 150, fw = Math.round((Math.max(0, Math.min(100, val)) / 100) * w);
  return `<text x="${x}" y="${y - 5}" fill="${MUTED}" font-size="11" font-family="ui-monospace,monospace">${esc(label)}</text>
<rect x="${x}" y="${y}" width="${w}" height="7" rx="3.5" fill="#0b1424"/>
<rect x="${x}" y="${y}" width="${fw}" height="7" rx="3.5" fill="${LIME}"/>
<text x="${x + w + 8}" y="${y + 7}" fill="${TEXT}" font-size="11" font-family="ui-monospace,monospace">${val}</text>`;
}

function cardSVG(m, s) {
  const name = esc(m.full_name || "repo"), stars = (m.stargazers_count || 0).toLocaleString();
  const lic = (m.license && m.license.spdx_id && m.license.spdx_id !== "NOASSERTION") ? m.license.spdx_id : "no license";
  const lang = esc(m.language || "—"), pushed = (m.pushed_at || "").slice(0, 10), vc = vColor(s.verdict);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="560" height="300" viewBox="0 0 560 300" role="img" aria-label="RepoHunter report card for ${name}">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0b1220"/><stop offset="1" stop-color="#070b16"/></linearGradient>
  <linearGradient id="wg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${LIME}"/><stop offset="1" stop-color="${CYAN}"/></linearGradient>
</defs>
<rect width="560" height="300" rx="18" fill="url(#bg)" stroke="${LINE}"/>
<g transform="translate(28,22)">
  <g fill="url(#wg)" fill-opacity=".42" stroke="url(#wg)" stroke-width="1.3">
    <g transform="rotate(15 20 15)"><ellipse cx="6" cy="19" rx="14" ry="4.8"/></g>
    <g transform="rotate(-15 20 15)"><ellipse cx="34" cy="19" rx="14" ry="4.8"/></g>
    <g transform="rotate(-13 20 15)"><ellipse cx="6" cy="11" rx="14.5" ry="3.4"/></g>
    <g transform="rotate(13 20 15)"><ellipse cx="34" cy="11" rx="14.5" ry="3.4"/></g>
  </g>
  <rect x="18.7" y="17" width="2.6" height="16" rx="1.3" fill="url(#wg)"/>
  <ellipse cx="20" cy="14" rx="3.4" ry="5" fill="url(#wg)"/>
  <circle cx="16.9" cy="8.6" r="3" fill="url(#wg)"/><circle cx="23.1" cy="8.6" r="3" fill="url(#wg)"/>
  <circle cx="17.3" cy="9.3" r="1.35" fill="#0a1710"/><circle cx="22.7" cy="9.3" r="1.35" fill="#0a1710"/>
  <circle cx="16.4" cy="7.9" r=".55" fill="#f4ffe0"/><circle cx="21.8" cy="7.9" r=".55" fill="#f4ffe0"/>
</g>
<text x="72" y="40" fill="${TEXT}" font-size="15" font-weight="bold" font-family="ui-sans-serif,system-ui,sans-serif">RepoHunter</text>
<text x="72" y="57" fill="${MUTED}" font-size="11.5" font-family="ui-sans-serif,system-ui,sans-serif">reuse-decision report card</text>
<rect x="392" y="24" width="146" height="42" rx="10" fill="${vc}" fill-opacity=".16" stroke="${vc}" stroke-opacity=".5"/>
<text x="465" y="45" fill="${vc}" font-size="20" font-weight="800" text-anchor="middle" font-family="ui-sans-serif,system-ui,sans-serif">${s.verdict}</text>
<text x="465" y="60" fill="${MUTED}" font-size="10" text-anchor="middle" font-family="ui-monospace,monospace">score ${s.overall}/100</text>
<text x="26" y="104" fill="${TEXT}" font-size="21" font-weight="bold" font-family="ui-sans-serif,system-ui,sans-serif">${name}</text>
<text x="26" y="128" fill="${MUTED}" font-size="12.5" font-family="ui-monospace,monospace">★ ${stars}   ·   ${lang}   ·   ${esc(lic)}   ·   pushed ${esc(pushed)}</text>
<g transform="translate(26,150)">
  ${bar(0, 20, "popularity", s.pop)}
  ${bar(0, 48, "freshness", s.fresh)}
  ${bar(300, 20, "health", s.health)}
  ${bar(300, 48, "maturity", s.mat)}
</g>
<text x="26" y="270" fill="${MUTED}" font-size="10.5" font-family="ui-sans-serif,system-ui,sans-serif">Transparent heuristic over live GitHub data — guidance, not a guarantee. Verify before adopting.</text>
<text x="26" y="288" fill="${LIME}" font-size="11" font-weight="bold" font-family="ui-sans-serif,system-ui,sans-serif">repohunter.dev</text>
<text x="534" y="288" fill="${MUTED}" font-size="10" text-anchor="end" font-family="ui-monospace,monospace">not a safety/security rating</text>
</svg>`;
}

const CC = "public, max-age=1800, s-maxage=1800";   // 30-min cache → dedup + cheap
const SEC = { "x-content-type-options": "nosniff", "access-control-allow-origin": "*" };
const SLUG_RE = /^[\w.-]{1,39}\/[\w.-]{1,100}$/;     // reject junk before any GitHub call
const svgResp = (svg) => new Response(svg, {
  headers: { "content-type": "image/svg+xml; charset=utf-8", "cache-control": CC,
    "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'", ...SEC },
});
const jsonResp = (obj, status) => new Response(JSON.stringify(obj, null, 2), {
  status: status || 200,
  headers: { "content-type": "application/json; charset=utf-8", "cache-control": CC,
    "content-security-policy": "default-src 'none'", ...SEC },
});

// full facts + scores as JSON — the single source the report page and any agent read
function apiJSON(m, s) {
  return {
    repo: m.full_name, url: m.html_url, description: m.description || null, homepage: m.homepage || null,
    stars: m.stargazers_count || 0, forks: m.forks_count || 0, open_issues: m.open_issues_count || 0,
    language: m.language || null, license: (m.license && m.license.spdx_id && m.license.spdx_id !== "NOASSERTION") ? m.license.spdx_id : null,
    topics: m.topics || [], created: (m.created_at || "").slice(0, 10), last_push: (m.pushed_at || "").slice(0, 10),
    archived: !!m.archived, verdict: s.verdict,
    scores: { overall: s.overall, popularity: s.pop, freshness: s.fresh, health: s.health, maturity: s.mat },
    note: "Transparent heuristic over live GitHub data — guidance, not a guarantee, and NOT a safety/security rating.",
  };
}

function notFound(kind, slug) {
  if (kind === "badge") return svgResp(badgeSVG("repohunter", "repo not found", MUTED, false));
  if (kind === "card") return svgResp(cardSVG({ full_name: slug || "?/?" }, { verdict: "SKIP", overall: 0, pop: 0, fresh: 0, health: 0, mat: 0 }));
  return jsonResp({ error: "repo not found, private, or invalid", repo: slug || null }, 404);
}

async function route(request, env) {
  const url = new URL(request.url);
  if (url.pathname === "/health") return new Response("ok", { headers: { "cache-control": "no-store" } });
  const parts = url.pathname.replace(/\.svg$/, "").split("/").filter(Boolean);
  const kind = parts[0];                                    // badge | card | api

  if (kind === "badge" || kind === "card" || kind === "api") {
    // /api/repo/owner/name → [api, repo, owner, name] ; badge/card → [kind, owner, name]
    const off = kind === "api" ? 2 : 1;
    if (parts.length < off + 2 || (kind === "api" && parts[1] !== "repo")) return notFound(kind, "");
    const slug = parts[off] + "/" + parts[off + 1];
    if (!SLUG_RE.test(slug)) return notFound(kind, slug);   // cheap reject — no GitHub call for junk
    let m = null;
    try { m = await fetchRepo(slug, env); } catch (e) { m = null; }
    if (!m || !m.full_name) return notFound(kind, slug);
    const s = score(m);
    if (kind === "badge") return svgResp(badgeSVG("repohunter", s.verdict + " " + s.overall, vColor(s.verdict), s.verdict === "MAYBE"));
    if (kind === "card") return svgResp(cardSVG(m, s));
    return jsonResp(apiJSON(m, s));
  }
  return new Response(
    "RepoHunter badge service — /badge/:owner/:name.svg · /card/:owner/:name.svg · /api/repo/:owner/:name",
    { status: 404, headers: { "content-type": "text/plain", ...SEC } }
  );
}

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "GET" && request.method !== "HEAD")
      return new Response("method not allowed", { status: 405, headers: { "allow": "GET, HEAD", ...SEC } });
    // Edge cache = dedup: identical URLs are served from cache, so repeated asks don't re-hit GitHub.
    const cache = caches.default;
    const key = new Request(new URL(request.url).toString(), request);
    const hit = await cache.match(key);
    if (hit) return hit;
    const resp = await route(request, env);
    // cache both positive AND negative results (they carry max-age) so junk floods can't re-hit GitHub
    if ((resp.headers.get("cache-control") || "").includes("max-age")) ctx.waitUntil(cache.put(key, resp.clone()));
    return resp;
  },
};
