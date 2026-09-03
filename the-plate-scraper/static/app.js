/* The Plate Scraper — shared frontend */
(function () {
  "use strict";
  const TNS = {};
  window.TNS = TNS;

  TNS.me = null;

  /* ---------- api ---------- */
  TNS.api = async function (path, opts) {
    opts = opts || {};
    const res = await fetch("/api/" + path, {
      method: opts.method || (opts.body ? "POST" : "GET"),
      headers: { "Content-Type": "application/json" },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      credentials: "same-origin",
    });
    let data = {};
    try { data = await res.json(); } catch (e) { /* no body */ }
    if (!res.ok && !data.error) data.error = "Request failed (" + res.status + ")";
    if (!res.ok) { const e = new Error(data.error || "Request failed"); e.data = data; throw e; }
    return data;
  };

  /* ---------- toasts ---------- */
  TNS.toast = function (msg, type) {
    let box = document.getElementById("toasts");
    if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
    const t = document.createElement("div");
    t.className = "toast" + (type ? " " + type : "");
    t.textContent = msg;
    box.appendChild(t);
    setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .4s"; }, 3400);
    setTimeout(() => t.remove(), 3900);
  };

  /* ---------- auth ---------- */
  TNS.loadMe = async function () {
    try { const d = await TNS.api("me"); TNS.me = d.user; } catch (e) { TNS.me = null; }
    return TNS.me;
  };
  TNS.requireLogin = function (msg) {
    if (TNS.me) return true;
    TNS.toast(msg || "Sign in to do that.", "err");
    setTimeout(() => { if (confirm("Sign in first?")) location.href = "/members.html"; }, 60);
    return false;
  };
  TNS.signOut = async function () {
    try { await TNS.api("logout"); } catch (e) {}
    TNS.me = null;
    location.href = "/";
  };

  /* ---------- nav / footer ---------- */
  TNS.renderNav = async function (active) {
    const el = document.getElementById("nav");
    if (!el) return;
    const links = [
      ["recipes.html", "Recipes", "recipes"],
      ["scraper.html", "Scraper", "scraper"],
      ["feedroom.html", "Feed Room", "feedroom"],
      ["substitutions.html", "Substitutions", "subs"],
      ["shopping.html", "Shopping List", "shopping"],
      ["gear.html", "Kitchen Gear", "gear"],
    ];
    const me = await TNS.loadMe();
    const authHtml = me
      ? '<span class="who">Hi, <b>' + esc(me.name.split(" ")[0]) + "</b></span>" +
        (me.is_admin ? '<a class="btn btn-ghost btn-sm" href="/affiliate.html">Control Panel</a>' : "") +
        '<a class="btn btn-dark btn-sm" href="/dashboard.html">My Kitchen</a>'
      : '<a class="btn btn-ghost btn-sm" href="/members.html">Sign in</a>' +
        '<a class="btn btn-primary btn-sm" href="/members.html?tab=join">Join free</a>';
    el.innerHTML = '<div class="wrap navrow">' +
      '<a class="brand" href="/">' +
      '<span class="mark"><svg width="18" height="18" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="white" stroke-width="2"/><path d="M5 12h14M12 5v14" stroke="white" stroke-width="2" stroke-linecap="round"/></svg></span>' +
      '<span>The Plate Scraper<small>theplatescraper.com</small></span></a>' +
      '<nav class="navlinks">' +
      links.map(l => '<a href="/' + l[0] + '"' + (l[2] === active ? ' class="active"' : "") + ">" + l[1] + "</a>").join("") +
      "</nav>" +
      '<div class="navauth">' + authHtml + "</div></div>";
  };

  TNS.renderFooter = function () {
    const el = document.getElementById("footer");
    if (!el) return;
    el.innerHTML = '<div class="wrap"><div class="cols">' +
      "<div><h4>The Plate Scraper</h4><p style='font-size:14px;color:var(--ink-soft);margin:0 0 10px'>An independent home-cooking platform for theplatescraper.com. Scrape the web's best recipes, swap what you have, and cook like a legend.</p>" +
      '<div class="pillrow"><span class="pill">Est. 2026</span><span class="pill">Seattle, WA</span></div></div>' +
      "<div><h4>Tools</h4><ul>" +
      '<li><a href="/scraper.html">Recipe Scraper</a></li><li><a href="/feedroom.html">Feed Room (RSS)</a></li>' +
      '<li><a href="/substitutions.html">Substitution Guide</a></li><li><a href="/shopping.html">Shopping List</a></li></ul></div>' +
      "<div><h4>Explore</h4><ul>" +
      '<li><a href="/recipes.html">All Recipes</a></li><li><a href="/gear.html">Kitchen Gear</a></li>' +
      '<li><a href="/members.html">Membership</a></li><li><a href="/about.html">About</a></li></ul></div>' +
      "<div><h4>Site</h4><ul>" +
      '<li><a href="/affiliate.html">Affiliate Control Panel</a></li><li><a href="/dashboard.html">Members Area</a></li>' +
      '<li><a href="mailto:hello@theplatescraper.com">hello@theplatescraper.com</a></li></ul></div>' +
      '</div><div class="fine">© 2026 The Plate Scraper · Independent platform — not affiliated with any recipe site named elsewhere on the internet. Some gear links are affiliate links; we may earn a commission that keeps the pot on the stove. All recipes are original to our kitchen.</div></div>';
  };

  TNS.init = async function (active) {
    TNS.renderNav(active);
    TNS.renderFooter();
  };

  /* ---------- utils ---------- */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  TNS.esc = esc;

  TNS.timeAgo = function (ts) {
    const s = Math.max(1, Math.floor(Date.now() / 1000 - ts));
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    if (s < 86400 * 30) return Math.floor(s / 86400) + "d ago";
    return new Date(ts * 1000).toLocaleDateString();
  };
  TNS.fmtMoney = function (n) { return "$" + Number(n || 0).toFixed(2); };

  TNS.fmtQty = function (n) {
    if (n == null || n === "") return "";
    n = Number(n);
    if (isNaN(n)) return String(n);
    const whole = Math.floor(n);
    const frac = n - whole;
    const fr = [[0.25, "¼"], [0.33, "⅓"], [0.5, "½"], [0.66, "⅔"], [0.75, "¾"], [0.375, "⅜"], [0.125, "⅛"], [0.875, "⅞"]];
    for (const [v, sym] of fr) {
      if (Math.abs(frac - v) < 0.03) return (whole ? whole + " " : "") + sym;
    }
    if (Math.abs(frac) < 0.03) return String(whole);
    return (Math.round(n * 10) / 10).toString();
  };
  TNS.parseQty = function (q) {
    if (!q) return null;
    q = String(q).trim();
    if (q.includes("/")) { const [a, b] = q.split("/"); const x = parseFloat(a) / parseFloat(b); return isNaN(x) ? null : x; }
    const x = parseFloat(q);
    return isNaN(x) ? null : x;
  };
  TNS.scaleQty = function (orig, factor) {
    const v = TNS.parseQty(orig);
    if (v == null) return orig;
    return TNS.fmtQty(v * factor);
  };

  /* ---------- shopping list (guest: localStorage, member: server) ---------- */
  const LS = "tps_list_v1";
  TNS.getLocalList = function () { try { return JSON.parse(localStorage.getItem(LS) || "[]"); } catch (e) { return []; } };
  TNS.saveLocalList = function (items) { localStorage.setItem(LS, JSON.stringify(items)); };

  TNS.getList = async function () {
    if (TNS.me) { const d = await TNS.api("list"); return d.items; }
    return TNS.getLocalList();
  };

  TNS.addToList = async function (items, recipeTitle) {
    if (!Array.isArray(items) || !items.length) return 0;
    const payload = items.map(i => ({
      item: i.item || i.name, qty: i.qty, unit: i.unit || "", aisle: i.aisle || "pantry", recipe: recipeTitle || "",
    }));
    if (TNS.me) {
      const d = await TNS.api("list/add", { body: { items: payload } });
      return d.items.length;
    }
    const list = TNS.getLocalList();
    let n = 0;
    for (const it of payload) {
      const key = (it.item || "").toLowerCase() + "|" + (it.unit || "").toLowerCase();
      const ex = list.find(x => (x.name.toLowerCase() + "|" + (x.unit || "").toLowerCase()) === key);
      const q = TNS.parseQty(it.qty);
      if (ex) { if (q && ex.qty) ex.qty = Math.round((ex.qty + q) * 100) / 100; else if (q && !ex.qty) ex.qty = q; }
      else {
        list.push({ id: "g" + Date.now() + Math.random().toString(36).slice(2, 6), name: it.item, qty: q, unit: it.unit, aisle: it.aisle, recipe: it.recipe, purchased: false });
        n++;
      }
    }
    TNS.saveLocalList(list);
    return list.length;
  };

  /* ---------- affiliate tracking ---------- */
  TNS.trackAffiliate = async function (code) {
    if (!code) return;
    try {
      const d = await fetch("/api/track?code=" + encodeURIComponent(code)).then(r => r.json());
      if (d && d.url) window.open(d.url, "_blank", "noopener");
      else TNS.toast("Gear link is on its way to the store.", "ok");
    } catch (e) { TNS.toast("Couldn't track that link.", "err"); }
  };

  /* ---------- recipe cards ---------- */
  TNS.recipeCard = function (r) {
    const img = r.image
      ? '<img loading="lazy" src="' + r.image + '" alt="' + esc(r.title) + '">'
      : '<div class="noimg">🍲</div>';
    const stars = r.rating ? '★ ' + Number(r.rating).toFixed(1) + " (" + r.reviews + ")" : "new";
    return '<article class="recipe-card">' +
      (r.custom ? '<span class="scraped-badge">Scraped</span>' : "") +
      '<button class="heart' + (r.savedByMe ? " on" : "") + '" data-slug="' + r.slug + '" title="Save to my recipes">' + (r.savedByMe ? "❤️" : "🤍") + "</button>" +
      '<a class="thumb" href="/recipe/' + r.slug + '"><span class="cat">' + esc(r.category) + "</span>" + img + "</a>" +
      '<div class="body"><h3><a href="/recipe/' + r.slug + '">' + esc(r.title) + "</a></h3>" +
      '<p class="desc">' + esc(r.description || "") + "</p>" +
      '<div class="meta"><span class="star">' + stars + "</span><span>⏱ " + r.time + " min</span><span>🍽 serves " + r.servings + "</span></div></div></article>";
  };

  TNS.saveToggle = async function (slug, btn) {
    if (!TNS.requireLogin("Sign in to save recipes to your kitchen.")) return;
    try {
      const d = await TNS.api("recipes/" + slug + "/save");
      if (btn) { btn.classList.toggle("on", d.saved); btn.textContent = d.saved ? "❤️" : "🤍"; }
      TNS.toast(d.saved ? "Saved to your recipes." : "Removed from your recipes.", "ok");
      if (TNS.me) TNS.me.saved = d.saved ? [...(TNS.me.saved || []), slug] : (TNS.me.saved || []).filter(s => s !== slug);
    } catch (e) { TNS.toast(e.message, "err"); }
  };

  document.addEventListener("click", e => {
    const h = e.target.closest("[data-slug].heart");
    if (h) { e.preventDefault(); TNS.saveToggle(h.dataset.slug, h); }
    const g = e.target.closest("[data-affiliate]");
    if (g) { e.preventDefault(); TNS.trackAffiliate(g.dataset.affiliate); }
  });
})();
