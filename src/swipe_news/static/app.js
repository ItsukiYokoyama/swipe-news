// Swipe News UI: the card stack, actions, charts, settings, news sources and Dopa mode.
// Animations use CSS transitions + setTimeout (requestAnimationFrame doesn't advance in headless test runs)
const CAT_STYLE = {
  "テクノロジー": { tag: "#7dd3fc", hue: 205, mark: "TECH" },
  "経済":       { tag: "#fcd34d", hue: 38,  mark: "ECONOMY" },
  "エンタメ":    { tag: "#f9a8d4", hue: 330, mark: "CULTURE" },
  "社会":       { tag: "#86efac", hue: 150, mark: "SOCIETY" },
};
const VISIBLE = 3;       // Cards kept in the DOM
const REFILL_BELOW = 5;  // Load more when fewer than this remain

const stack = document.getElementById("stack");
const chips = document.getElementById("chips");
const tpl = document.getElementById("card-tpl");
let category = "";      // Category filter
let genre = "";         // Sub-genre filter
let taxonomy = [];      // [{category, genres: [{name, short}]}] (/api/genres)
let queue = [];          // Unsorted articles (first = front card)
let loading = false;
let exhausted = false;
const seen = new Set();

function ago(iso) {
  const min = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
  if (min < 60) return `${min}分前`;
  if (min < 60 * 24) return `${Math.floor(min / 60)}時間前`;
  return `${Math.floor(min / 1440)}日前`;
}

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.remove("opacity-0", "translate-y-2");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.add("opacity-0", "translate-y-2"), 1600);
}

function link(href, text) {
  const a = document.createElement("a");
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.className = "underline underline-offset-2";
  a.textContent = text;
  return a;
}

// Send an action. The response includes the updated preferences, so redraw with them (404 = article gone; ignore)
function post(id, action) {
  return fetch(`/api/news/${id}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  }).then(r => (r.ok ? r.json() : null))
    .then(j => { if (j?.prefs) renderPrefs(j.prefs, { self: true }); })
    .catch(() => {});
}

// ---- Background art, drawn in the browser instead of photos (no rights issues). Hue from the category, pattern and jitter from the article id
const MOTIFS = ["circles", "waves", "grid", "rays", "blobs", "stripes"];

function seedOf(str) {
  let h = 2166136261;
  for (const ch of str) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return h >>> 0;
}
function rng(seed) {  // mulberry32
  return () => {
    seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const DRAW = {
  circles(r, c, uid) {
    let s = "";
    for (let i = 0; i < 3; i++) {
      const x = 60 + r() * 280, y = 140 + r() * 260, rad = 70 + r() * 110;
      s += i === 0
        ? `<circle cx="${x}" cy="${y}" r="${rad}" fill="${c[0]}" opacity=".55"/>`
        : `<circle cx="${x}" cy="${y}" r="${rad}" fill="none" stroke="${c[i]}" stroke-width="1.5" opacity=".7"/>`;
    }
    return s + `<circle cx="${80 + r() * 240}" cy="${120 + r() * 300}" r="6" fill="#fff" opacity=".85"/>`;
  },
  waves(r, c) {
    let s = "";
    const amp = 14 + r() * 18, len = 120 + r() * 120, ph = r() * 6;
    for (let i = 0; i < 10; i++) {
      const y0 = 130 + i * 34;
      let d = `M -20 ${y0}`;
      for (let x = -20; x <= 420; x += 10) d += ` L ${x} ${(y0 + Math.sin(x / len * 6.283 + ph + i * .45) * amp).toFixed(1)}`;
      s += `<path d="${d}" fill="none" stroke="${c[i % 2]}" stroke-width="1.6" opacity="${(.85 - i * .07).toFixed(2)}"/>`;
    }
    return s;
  },
  grid(r, c) {
    let s = "";
    for (let x = 14; x < 400; x += 26) for (let y = 90; y < 500; y += 26)
      s += `<circle cx="${x}" cy="${y}" r="1.3" fill="#fff" opacity=".22"/>`;
    for (let i = 0; i < 7; i++)
      s += `<circle cx="${14 + Math.floor(r() * 15) * 26}" cy="${90 + Math.floor(r() * 16) * 26}" r="4.5" fill="${c[i % 3]}"/>`;
    const x = 80 + r() * 200, y = 160 + r() * 200, w = 90 + r() * 80;
    return s + `<rect x="${x}" y="${y}" width="${w}" height="${w}" fill="none" stroke="${c[0]}" stroke-width="1.5" transform="rotate(${(r() * 30 - 15).toFixed(1)} ${x + w / 2} ${y + w / 2})" opacity=".8"/>`;
  },
  rays(r, c) {
    const ox = r() < .5 ? -30 + r() * 80 : 350 + r() * 80, oy = 70 + r() * 90;
    let s = "";
    for (let i = 0; i < 16; i++) {
      const a = (ox < 200 ? 0.05 : Math.PI - 1.35) + i * 0.085;
      s += `<line x1="${ox}" y1="${oy}" x2="${(ox + Math.cos(a) * 700).toFixed(1)}" y2="${(oy + Math.sin(a) * 700).toFixed(1)}" stroke="${c[i % 2]}" stroke-width="${i % 4 ? 1 : 2.5}" opacity="${i % 4 ? .45 : .8}"/>`;
    }
    return s + `<circle cx="${ox}" cy="${oy}" r="34" fill="${c[0]}" opacity=".9"/>`;
  },
  blobs(r, c, uid) {
    let s = `<defs><filter id="b${uid}" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="38"/></filter></defs><g filter="url(#b${uid})">`;
    for (let i = 0; i < 3; i++)
      s += `<circle cx="${40 + r() * 320}" cy="${120 + r() * 300}" r="${100 + r() * 90}" fill="${c[i]}" opacity=".75"/>`;
    return s + "</g>";
  },
  stripes(r, c) {
    let s = `<g transform="rotate(${-25 - r() * 20} 200 300)">`;
    let x = -300;
    while (x < 700) {
      const w = 10 + r() * 34;
      if (r() < .55) s += `<rect x="${x}" y="-200" width="${w}" height="900" fill="${c[Math.floor(r() * 3)]}" opacity="${(.25 + r() * .5).toFixed(2)}"/>`;
      x += w + 6 + r() * 20;
    }
    return s + "</g>";
  },
};

function paintArt(el, n) {
  const seed = seedOf(n.id);
  const r = rng(seed);
  const base = CAT_STYLE[n.category]?.hue ?? 150;
  const h = (base + (seed % 31) - 15 + 360) % 360;
  const motif = MOTIFS[(seed >>> 8) % MOTIFS.length];
  const c = [`hsl(${h} 75% 62%)`, `hsl(${(h + 35) % 360} 70% 56%)`, `hsl(${(h + 330) % 360} 60% 70%)`];
  el.querySelector(".bg").style.background =
    `radial-gradient(120% 70% at 30% 20%, hsl(${h} 45% 24%), transparent 70%), linear-gradient(170deg, hsl(${h} 40% 14%), hsl(${(h + 30) % 360} 45% 5%))`;
  el.querySelector(".art").innerHTML = DRAW[motif](r, c, seed.toString(36));
}

function renderCard(n) {
  const el = tpl.content.firstElementChild.cloneNode(true);
  const style = CAT_STYLE[n.category] || CAT_STYLE["社会"];
  el.dataset.id = n.id;
  paintArt(el, n);
  el.querySelector(".mark").textContent = style.mark;
  const img = el.querySelector("img");
  if (n.image_url) {
    img.src = n.image_url;
    img.onerror = () => img.remove();
  } else {
    img.remove();
  }
  const cat = el.querySelector(".cat");
  cat.textContent = n.genre || n.category;  // Color from the category, text is the sub-genre
  if (n.genre_by === "ai") {
    cat.dataset.tip = `AI が判定（メディアのジャンル: ${n.feed_genre}）`;
    cat.prepend(Object.assign(document.createElement("span"), { className: "mr-0.5 opacity-60", textContent: "✦" }));
  }
  cat.style.background = style.tag;
  const media = el.querySelector(".media");
  media.textContent = n.media_name;
  if (n.explore) {
    // A card mixed in regardless of preferences
    const tag = Object.assign(document.createElement("span"), {
      className: "rounded-full bg-white/15 px-2 py-0.5 font-bold text-white/80", textContent: "たまにはこれも",
    });
    tag.dataset.tip = "普段は後ろに回るジャンルから。→ で開けばこのジャンルが戻ってきます";
    media.before(tag);
  }
  const time = el.querySelector(".ago");
  time.textContent = ago(n.published_at);
  time.dateTime = n.published_at;

  // Show the RSS text as published, without editing or excerpting
  el.querySelector(".headline").textContent = n.title;
  el.querySelector(".headline").classList.add("text-2xl");
  const desc = el.querySelector(".desc");
  if (n.description && n.description !== n.title) desc.textContent = n.description;
  else desc.remove();
  const credit = el.querySelector(".credit");
  credit.textContent = `出典：${n.media_name}（RSS で配信された文面をそのまま表示）`;
  if (n.image_url) credit.append(`　画像：${n.media_name}（記事のプレビュー画像）`);
  return el;
}

// ---- Card stack
function cardEls() {
  return [...stack.querySelectorAll(".card:not(.leaving)")];
}

// Cards 0, 1, 2 from the front. Cards behind are lower, smaller and darker. lift (0-1) brings one forward
function depthTransform(i, lift = 0) {
  const d = Math.max(0, i - lift);
  return `translateY(${d * 14}px) scale(${1 - d * 0.045})`;
}

function layout() {
  // Sync the DOM with the first VISIBLE items of the queue
  const want = queue.slice(0, VISIBLE);
  cardEls().forEach(el => { if (!want.some(n => n.id === el.dataset.id)) el.remove(); });
  want.forEach((n, i) => {
    if (stack.querySelector(`.card[data-id="${n.id}"]:not(.leaving)`)) return;
    const el = renderCard(n);
    el.style.transform = depthTransform(i + 1);
    stack.prepend(el);
    void el.offsetWidth;  // Commit the position one step back first, so the settle below animates it forward
  });
  cardEls().forEach(el => {
    const i = want.findIndex(n => n.id === el.dataset.id);
    el.style.zIndex = String(10 - i);
    el.classList.add("settle");
    el.style.transform = depthTransform(i);
    el.style.filter = i ? `brightness(${1 - i * 0.18})` : "";
    el.inert = i > 0;
    el.classList.toggle("top", i === 0);
    if (i === 0 && !el.dataset.bound) bindDrag(el);
  });
  showEmpty(!queue.length);
}

// p is progress toward committing (0-1). Stamps reach full opacity at about 40%
const STAMP_FULL_AT = 0.4;
function setStamps(el, kind, p) {
  for (const k of ["skip", "enough", "open"])
    el.querySelector(`.stamp-${k}`).style.opacity = k === kind ? String(Math.min(1, p / STAMP_FULL_AT)) : "0";
}

// Commit when moved far enough or flicked fast
function decide(dx, dy, vx, vy, w, h) {
  if (Math.abs(dx) > Math.abs(dy)) {
    if (Math.abs(dx) > w * 0.28 || Math.abs(vx) > 0.6) return dx > 0 ? "open" : "skip";
  } else if (dy < 0 && (-dy > h * 0.2 || -vy > 0.6)) {  // Flicking down does nothing (undo is the ↓ key and button)
    return "enough";
  }
  return null;
}

function bindDrag(el) {
  el.dataset.bound = "1";
  let sx = 0, sy = 0, dx = 0, dy = 0, lastX = 0, lastY = 0, lastT = 0, vx = 0, vy = 0;
  let pointer = null, dragging = false, justDragged = false;

  el.addEventListener("pointerdown", e => {
    if (pointer !== null) return;
    pointer = e.pointerId;
    el.dataset.touching = "1";  // Pause the Dopa mode countdown while touched
    sx = lastX = e.clientX; sy = lastY = e.clientY; lastT = e.timeStamp;
    dx = dy = vx = vy = 0;
    dragging = false;
  });
  el.addEventListener("pointermove", e => {
    if (e.pointerId !== pointer) return;
    dx = e.clientX - sx; dy = e.clientY - sy;
    if (!dragging) {
      if (Math.hypot(dx, dy) < 6) return;  // Below this it's a tap (so the source link stays clickable)
      dragging = true;
      try { el.setPointerCapture(pointer); } catch { /* Keep going if this fails (e.g. synthetic events) */ }
      el.classList.remove("settle");
    }
    const dt = Math.max(1, e.timeStamp - lastT);
    vx = (e.clientX - lastX) / dt; vy = (e.clientY - lastY) / dt;
    lastX = e.clientX; lastY = e.clientY; lastT = e.timeStamp;
    el.style.transform = `translate(${dx}px, ${dy}px) rotate(${dx / 18}deg)`;
    const horiz = Math.abs(dx) > Math.abs(dy);
    const kind = horiz ? (dx > 0 ? "open" : "skip") : (dy < 0 ? "enough" : null);
    const p = horiz ? Math.abs(dx) / (el.clientWidth * 0.28) : Math.abs(dy) / (el.clientHeight * 0.2);
    setStamps(el, kind, p);
    // The next card moves forward
    const next = cardEls().find(c => c.dataset.id === queue[1]?.id);
    if (next) {
      next.classList.remove("settle");
      next.style.transform = depthTransform(1, kind ? Math.min(1, p) : 0);
    }
  });
  const end = e => {
    if (e.pointerId !== pointer) return;
    pointer = null;
    delete el.dataset.touching;
    if (!dragging) return;
    dragging = false;
    justDragged = true;
    setTimeout(() => { justDragged = false; }, 0);
    const action = decide(dx, dy, vx, vy, el.clientWidth, el.clientHeight);
    if (action) {
      commit(action, { dx, dy });
    } else {
      setStamps(el, null, 0);
      layout();  // Snap back
    }
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
  // Don't let the end of a drag click a link
  el.addEventListener("click", e => { if (justDragged) { e.preventDefault(); e.stopPropagation(); } }, true);
}

const genreOf = n => n.genre || n.category;
const MESSAGES = {
  skip: n => `「${genreOf(n)}」を少なめにします`,
  enough: () => "",
  open: () => "",
};

const undoStack = [];  // For undo (articles sorted in this page)

function commit(action, { dx = 0, dy = 0, auto = false } = {}) {
  if (action === "undo") return undo();
  const n = queue[0];
  const el = cardEls().find(c => c.dataset.id === n?.id);
  if (!n || !el) return;
  if (dopa.on) dopaBurst(action, el, auto);
  // Open synchronously within the user gesture to avoid the popup blocker
  if (action === "open") window.open(n.url, "_blank", "noopener");
  post(n.id, action);
  undoStack.push(n);
  if (action === "open") { opened = [n, ...opened.filter(k => k.id !== n.id)]; renderOpened(); }
  const msg = MESSAGES[action](n);
  if (msg) toast(msg);

  el.classList.add("leaving");
  el.classList.remove("settle");
  el.classList.add("fly");
  el.inert = true;
  setStamps(el, action, 1);
  const W = window.innerWidth, H = window.innerHeight;
  const spin = dopa.on ? 3 : 1;  // In Dopa mode the card spins away
  el.style.transform = action === "enough"
    ? `translate(${dx}px, ${-H}px) rotate(${dopa.on ? 540 : dx / 18}deg) scale(${dopa.on ? 0.4 : 1})`
    : `translate(${action === "open" ? W * 1.3 : -W * 1.3}px, ${dy + 60}px) rotate(${(action === "open" ? 28 : -28) * spin}deg)`;
  el.style.opacity = "0";
  setTimeout(() => el.remove(), 400);

  queue.shift();
  layout();
  if (queue.length < REFILL_BELOW) fill();
}

// ↓ / undo: put the last sorted article back on top and drop that action from learning
async function undo() {
  const n = undoStack.pop();
  if (!n) { toast("戻せるカードがありません"); return; }
  const res = await fetch(`/api/news/${n.id}/undo`, { method: "POST" }).then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (!res) { toast("戻せませんでした"); return; }
  if (res.prefs) renderPrefs(res.prefs, { self: true });
  queue = [n, ...queue.filter(q => q.id !== n.id)];
  opened = opened.filter(k => k.id !== n.id);
  renderOpened();
  layout();
  toast("1枚戻しました");
}

async function fill() {
  if (loading || exhausted) return;
  loading = true;
  try {
    // The server excludes sorted articles, so always fetch from the top and skip ones we already have.
    // Opening or skipping changes the weights, and so the order of what comes next
    const q = new URLSearchParams({ limit: Math.min(50, queue.length + 15) });
    if (category) q.set("category", category);
    if (genre) q.set("genre", genre);
    const items = await fetch(`/api/news/feed?${q}`).then(r => r.json());
    const fresh = items.filter(n => !seen.has(n.id));
    fresh.forEach(n => seen.add(n.id));
    if (!fresh.length) exhausted = true;
    queue.push(...fresh);
  } catch {
    toast("読み込みに失敗しました");
  } finally {
    loading = false;
    layout();
  }
}

// No cards: prompt to add sources if there are none, otherwise "all caught up" with a crawl-now button
function showEmpty(show) {
  let div = stack.querySelector(".empty");
  const kind = feedsState.list.length ? "done" : "nofeeds";
  if (!show || loading || !feedsState.loaded) { div?.remove(); return; }
  if (div?.dataset.kind === kind) return;
  div?.remove();
  div = document.createElement("div");
  div.dataset.kind = kind;
  div.className = "empty absolute inset-0 flex flex-col items-center justify-center gap-4 rounded-[28px] bg-white/5 px-8 text-center ring-1 ring-white/10";
  if (kind === "nofeeds") {
    div.innerHTML = `
      <p class="text-lg font-bold">読むメディアを追加しましょう</p>
      <p class="text-sm leading-relaxed text-white/60">おすすめの一覧から選ぶか、RSS の URL を入れて追加します。<br>
        個人で読む目的に限り、各メディアの利用規約を読んでから追加してください。</p>
      <button class="rounded-full bg-white px-6 py-3 text-sm font-bold text-black active:scale-95">メディアを追加する</button>`;
    div.querySelector("button").addEventListener("click", () => openFeeds("catalog"));
  } else {
    div.innerHTML = `
      <p class="text-lg font-bold">全部見ました</p>
      <p class="text-sm text-white/60">新しい記事は 30 分おきに届きます。いま巡回することもできます (1〜2 分)。</p>
      <button class="rounded-full bg-white px-6 py-3 text-sm font-bold text-black active:scale-95">いま巡回する</button>`;
    div.querySelector("button").addEventListener("click", async e => {
      e.target.disabled = true;
      e.target.textContent = "巡回中…";
      const r = await fetch("/api/crawl", { method: "POST" }).then(r => r.json()).catch(() => null);
      if (r?.status === "already_running") toast("巡回中です。しばらくしてからもう一度どうぞ");
      reset();
    });
  }
  stack.append(div);
}

function reset() {
  queue = [];
  seen.clear();
  exhausted = false;
  stack.innerHTML = "";
  fill();
}

// ---- Actions: buttons and keyboard
document.querySelectorAll("nav button[data-act]").forEach(b =>
  b.addEventListener("click", () => commit(b.dataset.act)));

document.addEventListener("keydown", e => {
  // Enter on a focused button is handled by its click (don't handle it twice)
  if (document.querySelector("dialog[open]") || (e.key === "Enter" && e.target.closest("button, a, [role=button]"))) return;
  const action = { ArrowLeft: "skip", ArrowRight: "open", ArrowUp: "enough", ArrowDown: "undo", Enter: "open" }[e.key];
  if (!action) return;
  e.preventDefault();
  if (e.repeat) return;  // Ignore key auto-repeat (one press = one card)
  if (e.key === "ArrowLeft" || e.key === "ArrowRight") startHold(e.key, action);
  else commit(action);
});
document.addEventListener("keyup", e => { if (hold && e.key === hold.key) cancelHold(); });
window.addEventListener("blur", () => { if (hold) cancelHold(); });

// ← → commit after holding 0.5 s (0.25 s in Dopa mode). While held the card slides that way and the stamp fades in; releasing early snaps back
const HOLD_MS = 500;
const holdMs = () => (dopa.on ? HOLD_MS / 2 : HOLD_MS);
let hold = null;  // { key, el, next, timer }

function topCard() {
  return cardEls().find(c => c.dataset.id === queue[0]?.id);
}

function startHold(key, action) {
  const el = topCard();
  if (hold || !el) return;
  const dir = action === "open" ? 1 : -1;
  const dx = dir * el.clientWidth * 0.28;  // Up to the drag commit distance
  const next = cardEls().find(c => c.dataset.id === queue[1]?.id);
  // Let a CSS transition do the motion (GPU-accelerated, smoother than stepping with timers)
  const ms = holdMs();
  const motion = `transform ${ms}ms cubic-bezier(.2,.7,.3,1)`;
  for (const c of [el, next].filter(Boolean)) {
    c.classList.remove("settle");
    c.style.transition = motion;
  }
  void el.offsetWidth;
  el.style.transform = `translate(${dx}px, 0) rotate(${dx / 18}deg)`;
  if (next) next.style.transform = depthTransform(1, 1);
  setStamps(el, action, 1);  // With keys, show the stamp immediately
  hold = {
    key, el, next,
    timer: setTimeout(() => {
      hold = null;
      for (const c of [el, next].filter(Boolean)) c.style.transition = "";
      commit(action, { dx, dy: 0 });
    }, ms),
  };
}

function cancelHold() {
  clearTimeout(hold.timer);
  for (const c of [hold.el, hold.next].filter(Boolean)) c.style.transition = "";
  hold = null;
  const el = topCard();
  if (el) setStamps(el, null, 0);
  layout();  // Snap back
}

// ---- Dopa mode: flashy effects, and the front card becomes ↑ (headline is enough; not learned) after 5 seconds.
// Paused while touching a card, holding a key, with a dialog open, or while another tab or window is active.
// On/off is remembered in this browser. Time is counted with setInterval (requestAnimationFrame doesn't run headless)
const DOPA_MS = 5000;  // The combo lasts as long as you keep sorting before time runs out (the automatic ↑)
const DOPA_FX = {
  skip: { color: "#f43f5e", word: "NOPE!", fill: "linear-gradient(180deg, #fecdd3, #f43f5e 55%, #9f1239)" },
  open: { color: "#38bdf8", word: "OPEN!!", fill: "linear-gradient(180deg, #e0f2fe, #38bdf8 55%, #6366f1)" },
  enough: { color: "#a855f7", word: "NEXT!", fill: "linear-gradient(180deg, #f5d0fe, #a855f7 55%, #6d28d9)" },
  timeup: { color: "#facc15", word: "TIME UP!", fill: "linear-gradient(180deg, #fef9c3, #facc15 50%, #ea580c)" },
};
// Combo tiers: [reached at, word, confetti multiplier]
const COMBO_TIERS = [[20, "GODLIKE", 3], [10, "FEVER!!", 2.5], [5, "GREAT!", 2], [3, "GOOD", 1.3]];
const CONFETTI = ["★", "💥", "✦", "🔥"];
const dopa = { on: false, id: null, left: DOPA_MS, last: 0, num: 0, away: false, combo: 0, timer: null, comboTimer: null };
const dopaBtn = document.getElementById("dopa-btn");
const dopaMute = document.getElementById("dopa-mute");
const dopaCount = document.getElementById("dopa-count");
const dopaCombo = document.getElementById("dopa-combo");
const comboTier = n => COMBO_TIERS.find(([at]) => n >= at);

// ---- Sound effects, synthesized with Web Audio (no audio files). The AudioContext is created inside a key/click (autoplay policy)
const SFX_VOLUME = 0.6;      // Master volume (1 = original)
const FANFARE_VOLUME = 0.5;  // The → (open) fanfare is quieter still (many layered sounds make it loud)
const sfx = {
  ctx: null,
  out: null,  // Route through a compressor so layered sounds don't clip
  muted: false,
  init() {
    try {
      if (!this.ctx) {
        this.ctx = new (window.AudioContext || window.webkitAudioContext)();
        this.out = this.ctx.createDynamicsCompressor();
        this.out.threshold.value = -14;
        this.out.ratio.value = 6;
        const volume = this.ctx.createGain();
        volume.gain.value = SFX_VOLUME;
        this.out.connect(volume).connect(this.ctx.destination);
      }
      if (this.ctx.state === "suspended") this.ctx.resume();
    } catch { this.ctx = null; }
  },
  // A tone sweeping f0 → f1. vol is the peak volume, wait is the delay in seconds
  tone(f0, f1, dur, type = "sine", vol = 0.15, wait = 0) {
    const c = this.ctx, t = c.currentTime + wait;
    const osc = c.createOscillator(), gain = c.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(f0, t);
    osc.frequency.exponentialRampToValueAtTime(f1, t + dur);
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(vol, t + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    osc.connect(gain).connect(this.out);
    osc.start(t);
    osc.stop(t + dur + 0.02);
  },
  noise(dur, vol = 0.12, wait = 0) {
    const c = this.ctx, len = Math.floor(c.sampleRate * dur);
    const buf = c.createBuffer(1, len, c.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < len; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / len);
    const src = c.createBufferSource(), gain = c.createGain(), hp = c.createBiquadFilter();
    hp.type = "highpass";
    hp.frequency.value = 900;
    gain.gain.value = vol;
    src.buffer = buf;
    src.connect(hp).connect(gain).connect(this.out);
    src.start(c.currentTime + wait);
  },
  // → (open): thump + whoosh + rising sweep + fanfare chord + sparkles. k raises the pitch with the combo
  fanfare(k) {
    const v = FANFARE_VOLUME;
    this.tone(160, 45, 0.35, "sine", 0.45 * v);
    this.noise(0.32, 0.14 * v);
    this.tone(260 * k, 1300 * k, 0.2, "sawtooth", 0.07 * v);
    [0, 4, 7, 12, 16].forEach((s, i) => {
      const f = 523 * k * 2 ** (s / 12);
      this.tone(f, f, 0.22, "square", 0.05 * v, 0.08 + i * 0.05);
      this.tone(f * 2, f * 2, 0.18, "triangle", 0.05 * v, 0.08 + i * 0.05);
    });
    const top = 523 * k * 2 ** (19 / 12);  // Hold the final chord
    for (const s of [0, 4, 7]) this.tone(top * 2 ** (s / 12) / 2, top * 2 ** (s / 12) / 2, 0.5, "triangle", 0.06 * v, 0.34);
    for (let i = 0; i < 6; i++) {
      const f = 2400 + Math.random() * 2400;
      this.tone(f, f * 1.02, 0.08, "sine", 0.05 * v, 0.36 + i * 0.06);
    }
  },
  // Raise the pitch as the combo grows (one semitone per step, up to two octaves)
  play(name, combo = 0) {
    if (this.muted || !this.ctx || !dopa.on) return;
    const k = 2 ** (Math.min(combo, 24) / 12);
    if (name === "skip") { this.tone(420 * k, 90 * k, 0.28, "sawtooth", 0.09); this.noise(0.18, 0.08); }
    if (name === "open") this.fanfare(k);
    if (name === "enough") this.tone(660 * k, 990 * k, 0.12, "triangle", 0.2);
    if (name === "timeup") { this.tone(190, 120, 0.45, "square", 0.08); this.tone(196, 124, 0.45, "sawtooth", 0.06); }
    if (name === "tick") this.tone(1200, 1200, 0.05, "square", 0.05);
    if (name === "tick-last") this.tone(1760, 1760, 0.07, "square", 0.07);
    if (name === "tier") [0, 4, 7, 12].forEach((s, i) => this.tone(523 * 2 ** (s / 12), 523 * 2 ** (s / 12), 0.22, "triangle", 0.12, i * 0.07));
    if (name === "break") this.tone(330, 110, 0.35, "triangle", 0.12);
  },
};

function setMuted(muted) {
  sfx.muted = muted;
  dopaMute.textContent = muted ? "🔇" : "🔊";
  dopaMute.setAttribute("aria-pressed", String(muted));
  dopaMute.setAttribute("aria-label", muted ? "ドパモードの効果音を鳴らす" : "ドパモードの効果音を消す");
}
setMuted(true);  // Sound starts muted on every page load (not remembered). Press 🔇 to turn it on

function setDopa(on, { quiet = false } = {}) {
  dopa.on = on;
  dopa.id = null;
  endCombo();
  document.body.classList.toggle("dopa", on);
  document.body.classList.remove("danger");
  dopaBtn.setAttribute("aria-checked", String(on));
  dopaBtn.querySelector(".dopa-icon").textContent = on ? "🔥" : "⚡";
  topCard()?.classList.remove("jitter", "jitter-hard");
  try { localStorage.setItem("swipe-news:dopa", on ? "1" : "0"); } catch { /* Works without storage */ }
  clearInterval(dopa.timer);
  if (on) {
    dopa.last = performance.now();
    dopa.timer = setInterval(dopaTick, 100);
    if (!quiet) toast("ドパモード ON！ 5 秒で次のカードへ");
  } else {
    dopaCount.classList.add("hidden", "opacity-0");
    if (!quiet) toast("ドパモード OFF");
  }
}

function dopaTick() {
  const now = performance.now();
  const dt = now - dopa.last;
  dopa.last = now;
  const el = topCard();
  if (!el) { dopaCount.classList.add("opacity-0"); document.body.classList.remove("danger"); return; }
  if (el.dataset.id !== dopa.id) {  // Restart at 5 seconds when a new card comes to the front
    dopa.id = el.dataset.id;
    dopa.left = DOPA_MS;
    dopa.num = 0;
  }
  const paused = hold || el.dataset.touching || dopa.away || document.visibilityState !== "visible"
    || document.querySelector("dialog[open]");
  if (!paused) dopa.left -= dt;
  const num = Math.max(1, Math.ceil(dopa.left / 1000));
  const hurry = num <= 2;
  dopaCount.classList.remove("hidden", "opacity-0");
  dopaCount.style.opacity = paused ? ".45" : "";
  dopaCount.classList.toggle("hurry", hurry);
  // The gauge around the card edge (sized to the edge in style.css)
  const rect = el.querySelector(".gauge rect");
  rect.style.strokeDashoffset = String(100 * (1 - Math.max(0, dopa.left) / DOPA_MS));
  rect.style.stroke = rect.style.color = hurry ? "#fb7185" : "#facc15";
  // Shake at 2 seconds left; at 1 second shake harder and pulse the screen edge red
  el.classList.toggle("jitter", hurry && num === 2 && !paused);
  el.classList.toggle("jitter-hard", num === 1 && !paused);
  document.body.classList.toggle("danger", num === 1 && !paused);
  if (num !== dopa.num) {  // The number bounces every second; ticking starts at 3 seconds left
    const first = dopa.num === 0;
    dopa.num = num;
    dopaCount.querySelector(".num").textContent = String(num);
    dopaCount.classList.remove("tick");
    void dopaCount.offsetWidth;
    dopaCount.classList.add("tick");
    if (!first && num <= 3 && !paused) sfx.play(num === 1 ? "tick-last" : "tick");
  }
  if (dopa.left <= 0) {
    dopa.id = null;
    document.body.classList.remove("danger");
    commit("enough", { auto: true });
  }
}

// Add a short-lived effect element, animate it with a CSS transition, then remove it (no requestAnimationFrame)
function fxElement(cls, from, to, ms) {
  const e = make("div", cls);
  Object.assign(e.style, from);
  document.body.append(e);
  void e.offsetWidth;
  Object.assign(e.style, to);
  setTimeout(() => e.remove(), ms);
  return e;
}

function fxWord(text, fill, cls = "dopa-word") {
  const word = fxElement(cls, { backgroundImage: fill, opacity: "1", transform: "translate(-50%, -50%) scale(.2) rotate(-14deg)" },
                         { transform: "translate(-50%, -50%) scale(1) rotate(-6deg)" }, 1300);
  word.textContent = text;
  setTimeout(() => Object.assign(word.style, { opacity: "0", transform: "translate(-50%, -90%) scale(1.25) rotate(-6deg)" }), 600);
}

function restartAnim(el, cls) {
  el.classList.remove("dopa-shake", "dopa-shake-big");
  void el.offsetWidth;
  el.classList.add(cls);
}

function endCombo() {
  dopa.combo = 0;
  document.body.classList.remove("fever");
  clearTimeout(dopa.comboTimer);
  dopaCombo.classList.add("hidden", "opacity-0");
  dopaCombo.classList.remove("broken", "big");
}

function showCombo(text, { big = false, broken = false } = {}) {
  dopaCombo.textContent = text;
  dopaCombo.classList.remove("hidden", "opacity-0");
  dopaCombo.classList.toggle("big", big);
  dopaCombo.classList.toggle("broken", broken);
  dopaCombo.style.transform = "rotate(-6deg) scale(1.6)";
  setTimeout(() => { dopaCombo.style.transform = ""; }, 120);
}

function dopaBurst(action, el, auto) {
  if (!auto) sfx.init();  // We're inside a key/click, so audio can be enabled here
  const broke = auto && dopa.combo >= 2;
  const prev = dopa.combo;
  dopa.combo = auto ? 0 : dopa.combo + 1;
  const tier = comboTier(dopa.combo);
  const fx = DOPA_FX[auto ? "timeup" : action];
  const r = el.getBoundingClientRect();
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;

  // Light: a flash from the action color to white, a brief brighter rainbow, and shockwave rings
  fxElement("dopa-flash", { background: `radial-gradient(circle at ${cx}px ${cy}px, #fff, ${fx.color} 25%, transparent 70%)`, opacity: "1" },
            { opacity: "0" }, 600);
  document.body.classList.add("boom");
  setTimeout(() => document.body.classList.remove("boom"), 180);
  for (const [delay, scale] of [[0, 14], [90, 9]]) setTimeout(() =>
    fxElement("dopa-wave", { left: `${cx - 30}px`, top: `${cy - 30}px`, borderColor: fx.color, opacity: "1", transform: "scale(.2)" },
              { transform: `scale(${scale})`, opacity: "0" }, 650), delay);

  // Big word and confetti; show the tier word when a combo tier is reached
  fxWord(fx.word, fx.fill);
  const reached = tier && tier[0] === dopa.combo;
  if (reached) setTimeout(() => fxWord(tier[1], "linear-gradient(90deg, #facc15, #f472b6, #38bdf8, #4ade80)", "dopa-word tier"), 120);
  const colors = [fx.color, "#facc15", "#22c55e", "#f472b6", "#ffffff", "#06b6d4"];
  const count = Math.round(80 * (tier?.[2] ?? 1));
  for (let i = 0; i < count; i++) {
    const a = Math.random() * Math.PI * 2, dist = 140 + Math.random() * 420;
    const emoji = i % 5 === 0 ? CONFETTI[i % CONFETTI.length] : "";
    const size = emoji ? 22 + Math.random() * 18 : 10 + Math.random() * 8;
    const bit = fxElement("dopa-bit", {
      left: `${cx}px`, top: `${cy}px`, width: `${size}px`, height: `${emoji ? size : size * 1.4}px`, fontSize: `${size}px`,
      background: emoji ? "none" : colors[i % colors.length], opacity: "1",
    }, { transform: `translate(${Math.cos(a) * dist}px, ${Math.sin(a) * dist + 100}px) rotate(${Math.random() * 900 - 450}deg)`, opacity: "0" },
    1100);
    bit.textContent = emoji;
  }
  restartAnim(document.getElementById("layout"), (tier?.[0] ?? 0) >= 5 || auto ? "dopa-shake-big" : "dopa-shake");
  el.classList.remove("jitter", "jitter-hard");

  // Sound and combo display
  sfx.play(auto ? "timeup" : action, dopa.combo);
  if (reached) setTimeout(() => sfx.play("tier"), 120);
  document.body.classList.toggle("fever", dopa.combo >= 10);
  clearTimeout(dopa.comboTimer);
  if (broke) {
    showCombo(`COMBO BREAK… ${prev}`, { broken: true });
    setTimeout(() => sfx.play("break"), 200);
    dopa.comboTimer = setTimeout(endCombo, 1500);
  } else if (dopa.combo >= 2) {
    showCombo(`${dopa.combo} COMBO!${tier ? ` ${tier[1]}` : ""}`, { big: dopa.combo >= 5 });
  }
}

dopaBtn.addEventListener("click", () => {
  setDopa(!dopa.on);
  if (dopa.on) { sfx.init(); sfx.play("tier"); }
});
dopaMute.addEventListener("click", () => {
  setMuted(!sfx.muted);
  if (!sfx.muted) { sfx.init(); sfx.play("enough"); }
});
window.addEventListener("blur", () => { dopa.away = true; });
window.addEventListener("focus", () => { dopa.away = false; });

// ---- Recently opened: right column on wide screens, a dialog in narrow windows. Both render from `opened`
let opened = [];  // Most recently opened first

function openedItem(n) {
  const style = CAT_STYLE[n.category] || CAT_STYLE["社会"];
  const li = document.createElement("li");
  li.className = "flex items-start gap-3 rounded-xl bg-white/5 p-3";
  const a = document.createElement("a");
  a.href = n.url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.className = "min-w-0 flex-1";
  a.innerHTML = `<div class="mb-1 flex min-w-0 items-center gap-2 whitespace-nowrap text-[11px] text-white/60">
      <span class="shrink-0 rounded-full px-2 py-0.5 font-bold text-black"></span><span class="min-w-0 truncate"></span><span class="shrink-0">·</span><span class="shrink-0"></span></div>
    <div class="text-sm font-bold leading-snug"></div>`;
  const [tag, media, , when] = a.firstElementChild.children;
  tag.textContent = n.genre || n.category;
  tag.style.background = style.tag;
  media.textContent = n.media_name;
  when.textContent = ago(n.published_at);
  a.lastElementChild.textContent = n.title;
  li.append(a);
  return li;
}

function renderOpened() {
  document.getElementById("opened-count").textContent = String(opened.length);
  document.querySelectorAll(".opened-num").forEach(el => { el.textContent = String(opened.length); });
  for (const ul of document.querySelectorAll(".opened-list")) {
    ul.innerHTML = "";
    if (!opened.length) {
      ul.innerHTML = '<li class="px-2 py-8 text-center text-sm text-white/40">→ で開いた記事がここに入ります</li>';
      continue;
    }
    for (const n of opened) ul.append(openedItem(n));
  }
}

async function loadOpened() {
  const items = await fetch("/api/news/opened").then(r => r.json()).catch(() => null);
  if (!items) return;
  const same = items.length === opened.length && items.every((n, i) => n.id === opened[i].id);
  opened = items;
  if (!same) renderOpened();  // Don't redraw if unchanged (keeps the list's scroll position)
}

document.getElementById("opened-btn").addEventListener("click", async () => {
  await loadOpened();
  document.getElementById("opened").showModal();
});

// ---- About
document.getElementById("about-btn").addEventListener("click", () => document.getElementById("about").showModal());

// ---- News sources: added sources / add from the recommended list (ditsuki.com) / add by URL.
// Adding always requires ticking "personal use / read the terms" (unticked again after each addition)
const feedsState = { list: [], loaded: false, catalog: null, found: null };
const feedsDialog = document.getElementById("feeds");
const feedsAgree = document.getElementById("feeds-agree");

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options, headers: options.body ? { "Content-Type": "application/json" } : undefined,
  }).catch(() => null);
  if (!res) throw new Error("アプリに接続できませんでした");
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new Error(body?.detail || `エラー (${res.status})`);
  return body;
}

async function loadFeeds() {
  feedsState.list = await api("/api/feeds").catch(() => feedsState.list);
  feedsState.loaded = true;
  document.getElementById("feeds-count").textContent = `(${feedsState.list.length})`;
  if (!queue.length) showEmpty(true);
  return feedsState.list;
}

function genreOptions(select, value) {
  select.innerHTML = "";
  for (const t of taxonomy) {
    const group = document.createElement("optgroup");
    group.label = t.category;
    for (const g of t.genres) group.append(new Option(g.name, g.name, false, g.name === value));
    select.append(group);
  }
}

function openFeeds(tab = "added") {
  showFeedsTab(tab);
  feedsDialog.showModal();
}

function showFeedsTab(tab) {
  document.querySelectorAll(".feeds-tab").forEach(b => {
    const on = b.dataset.tab === tab;
    b.setAttribute("aria-selected", String(on));
    b.classList.toggle("bg-white/10", on);
    b.classList.toggle("text-white/50", !on);
  });
  document.querySelectorAll(".feeds-panel").forEach(p => p.classList.toggle("hidden", p.dataset.panel !== tab));
  document.getElementById("feeds-agree-box").classList.toggle("hidden", tab === "added");
  document.getElementById("feeds-agree-box").classList.toggle("flex", tab !== "added");
  if (tab === "added") renderFeedList();
  if (tab === "catalog") loadCatalog();
}

function toggle(label, checked, onChange) {
  const l = make("label", "flex items-center gap-1.5 text-xs text-white/70");
  const cb = Object.assign(document.createElement("input"), { type: "checkbox", checked, className: "h-3.5 w-3.5 accent-white" });
  cb.addEventListener("change", () => onChange(cb.checked, cb));
  l.append(cb, label);
  return l;
}

async function changeFeed(feed, change) {
  try {
    Object.assign(feed, await api(`/api/feeds/${feed.id}`, { method: "PATCH", body: JSON.stringify(change) }));
    toast("変更しました。次の巡回から反映します");
  } catch (e) {
    toast(e.message);
    renderFeedList();
  }
}

function renderFeedList() {
  const ul = document.getElementById("feeds-list");
  ul.innerHTML = "";
  document.getElementById("feeds-empty").classList.toggle("hidden", feedsState.list.length > 0);
  document.getElementById("feeds-bulk").classList.toggle("hidden", feedsState.list.length === 0);
  for (const f of feedsState.list) {
    const li = make("li", "rounded-xl bg-white/5 p-3 ring-1 ring-white/10" + (f.enabled ? "" : " opacity-50"));
    const head = make("div", "mb-2 flex flex-wrap items-center gap-2");
    head.append(make("span", "font-bold", f.name));
    if (f.site_url) head.append(link(f.site_url, "サイト"));
    if (f.terms_url) head.append(link(f.terms_url, "利用規約"));
    head.querySelectorAll("a").forEach(a => a.classList.add("text-xs", "text-white/60"));
    const del = make("button", "ml-auto rounded-full bg-white/10 px-3 py-1 text-xs", "外す");
    del.addEventListener("click", async () => {
      if (!confirm(`「${f.name}」を外しますか？ 未読の記事も消えます (開いた記事と操作の記録は残ります)。`)) return;
      try {
        await api(`/api/feeds/${f.id}`, { method: "DELETE" });
        await loadFeeds();
        renderFeedList();
        reset();
        toast(`「${f.name}」を外しました`);
      } catch (e) { toast(e.message); }
    });
    head.append(del);
    const row = make("div", "flex flex-wrap items-center gap-x-4 gap-y-2");
    const sel = make("select", "rounded-lg bg-white/5 px-2 py-1 text-xs ring-1 ring-white/15");
    genreOptions(sel, f.genre);
    sel.addEventListener("change", () => changeFeed(f, { genre: sel.value }));
    row.append(sel,
      toggle("総合系", f.mixed, v => changeFeed(f, { mixed: v })),
      toggle("記事の画像", f.og_image, v => changeFeed(f, { og_image: v })),
      toggle("取得する", f.enabled, v => changeFeed(f, { enabled: v }).then(renderFeedList)));
    row.append(make("span", "text-[11px] text-white/35", { catalog: "おすすめから", manual: "手入力", imported: "前の版から" }[f.source] ?? ""));
    li.append(head, row);
    ul.append(li);
  }
}

async function setAllImages(on) {
  const targets = feedsState.list.filter(f => f.og_image !== on);
  if (!targets.length) { toast(on ? "すべてオンになっています" : "すべてオフになっています"); return; }
  if (on && !confirm(`${targets.length} 件のメディアで記事の画像をオンにします。各メディアの利用規約を確かめましたか？`)) return;
  let failed = 0;
  for (const f of targets) {
    try {
      Object.assign(f, await api(`/api/feeds/${f.id}`, { method: "PATCH", body: JSON.stringify({ og_image: on }) }));
    } catch { failed++; }
  }
  renderFeedList();
  toast(failed ? `${failed} 件は変えられませんでした` : `記事の画像をすべて${on ? "オン" : "オフ"}にしました。次の巡回から反映します`);
}
document.getElementById("images-all-on").addEventListener("click", () => setAllImages(true));
document.getElementById("images-all-off").addEventListener("click", () => setAllImages(false));

// Check the box before every addition, then clear it (the next source needs its terms read too)
function agreed() {
  if (feedsAgree.checked) return true;
  toast("「個人で使う・利用規約を読んだ」にチェックを入れてください");
  document.getElementById("feeds-agree-box").classList.add("ring-amber-300");
  setTimeout(() => document.getElementById("feeds-agree-box").classList.remove("ring-amber-300"), 1500);
  return false;
}

async function addFeed(body) {
  const feed = await api("/api/feeds", { method: "POST", body: JSON.stringify({ ...body, agreed: true }) });
  feedsAgree.checked = false;
  await loadFeeds();
  toast(`「${feed.name}」を追加しました。記事を取っています…`);
  setTimeout(reset, 8000);  // Reload around when the crawl finishes
  return feed;
}

async function loadCatalog(refresh = false) {
  const status = document.getElementById("catalog-status");
  if (feedsState.catalog && !refresh) { renderCatalog(); return; }
  status.textContent = "読み込んでいます…";
  try {
    feedsState.catalog = await api(`/api/feeds/catalog${refresh ? "?refresh=true" : ""}`);
    status.textContent = feedsState.catalog.updated ? `一覧の更新: ${feedsState.catalog.updated}` : "";
  } catch (e) {
    feedsState.catalog = null;
    status.textContent = `${e.message}。「URL を入れて追加」からも追加できます`;
  }
  renderCatalog();
}

function renderCatalog() {
  const ul = document.getElementById("catalog-list");
  const filter = document.getElementById("catalog-filter");
  ul.innerHTML = "";
  if (!filter.options.length) {
    filter.append(new Option("すべてのジャンル", ""));
    for (const t of taxonomy) filter.append(new Option(t.category, t.category));
  }
  const cat = c => taxonomy.find(t => t.genres.some(g => g.name === c))?.category;
  const shown = (feedsState.catalog?.feeds ?? []).filter(f => !filter.value || cat(f.genre) === filter.value);
  const addAll = document.getElementById("catalog-add-all");
  const rest = shown.filter(f => !f.added).length;
  addAll.disabled = !rest;
  addAll.textContent = rest ? `すべて追加 (${rest})` : "すべて追加済み";
  addAll.classList.toggle("hidden", !feedsState.catalog);
  for (const f of shown) {
    const li = make("li", "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl bg-white/5 p-3 ring-1 ring-white/10");
    const info = make("div", "min-w-0 flex-1");
    const head = make("div", "flex flex-wrap items-center gap-2");
    const tag = make("span", "rounded-full px-2 py-0.5 text-[11px] font-bold text-black", f.genre);
    tag.style.background = (CAT_STYLE[cat(f.genre)] || CAT_STYLE["社会"]).tag;
    head.append(make("span", "font-bold", f.name), tag);
    if (f.mixed) head.append(make("span", "text-[11px] text-white/45", "総合系"));
    info.append(head);
    const links = make("div", "mt-1 flex flex-wrap gap-3 text-xs text-white/60");
    if (f.site_url) links.append(link(f.site_url, "サイト"));
    links.append(f.terms_url ? link(f.terms_url, "利用規約") : make("span", "text-white/40", "利用規約のページは未確認 (各自で確かめてください)"));
    info.append(links);
    if (f.note) info.append(make("p", "mt-1 text-xs text-amber-100/80", f.note));
    const btn = make("button", "shrink-0 rounded-full px-4 py-1.5 text-sm font-bold " + (f.added ? "bg-white/10 text-white/50" : "bg-white text-black"),
      f.added ? "追加済み" : "追加");
    btn.disabled = f.added;
    btn.addEventListener("click", async () => {
      if (!agreed()) return;
      btn.disabled = true;
      btn.textContent = "追加しています…";
      try {
        await addFeed({ url: f.url, name: f.name, genre: f.genre, mixed: f.mixed, terms_url: f.terms_url,
                        site_url: f.site_url, source: "catalog", catalog_id: f.catalog_id });
        f.added = true;
      } catch (e) { toast(e.message); }
      renderCatalog();
    });
    li.append(info, btn);
    ul.append(li);
  }
  if (feedsState.catalog && !ul.children.length) ul.append(make("li", "py-6 text-center text-sm text-white/45", "このジャンルのおすすめはありません"));
}

document.getElementById("feeds-btn").addEventListener("click", async () => {
  await loadFeeds();
  openFeeds(feedsState.list.length ? "added" : "catalog");
});
document.querySelectorAll(".feeds-tab").forEach(b => b.addEventListener("click", () => showFeedsTab(b.dataset.tab)));
document.getElementById("catalog-filter").addEventListener("change", renderCatalog);
document.getElementById("catalog-reload").addEventListener("click", () => loadCatalog(true));

// "Add all": every source shown (in the selected genre) that isn't added yet, with one confirmation
document.getElementById("catalog-add-all").addEventListener("click", async e => {
  const filter = document.getElementById("catalog-filter").value;
  const cat = c => taxonomy.find(t => t.genres.some(g => g.name === c))?.category;
  const targets = (feedsState.catalog?.feeds ?? []).filter(f => !f.added && (!filter || cat(f.genre) === filter));
  if (!targets.length || !agreed()) return;
  if (!confirm(`${targets.length} 件のメディアを追加します。それぞれの利用規約を読みましたか？`)) return;
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = "追加しています…";
  try {
    const res = await api("/api/feeds/bulk", { method: "POST", body: JSON.stringify({
      agreed: true,
      feeds: targets.map(f => ({ url: f.url, name: f.name, genre: f.genre, mixed: f.mixed, terms_url: f.terms_url,
                                 site_url: f.site_url, source: "catalog", catalog_id: f.catalog_id })),
    }) });
    feedsAgree.checked = false;
    const done = new Set(res.added.map(f => f.catalog_id));
    for (const f of targets) if (done.has(f.catalog_id)) f.added = true;
    await loadFeeds();
    toast(`${res.added.length} 件を追加しました${res.errors.length ? ` (${res.errors.length} 件は追加できませんでした)` : ""}。記事を取っています…`);
    setTimeout(reset, 15000);  // Reload around when the crawl finishes
  } catch (err) { toast(err.message); }
  renderCatalog();
});

document.getElementById("manual-inspect").addEventListener("submit", async e => {
  e.preventDefault();
  const status = document.getElementById("manual-status");
  const form = document.getElementById("manual-form");
  form.classList.add("hidden");
  status.className = "mb-3 text-sm text-white/60";
  status.textContent = "確かめています… (robots.txt とフィードを確認します)";
  try {
    const found = await api("/api/feeds/inspect", { method: "POST", body: JSON.stringify({ url: document.getElementById("manual-url").value }) });
    feedsState.found = found;
    status.textContent = "";
    const box = document.getElementById("manual-found");
    box.innerHTML = "";
    box.append(make("p", "font-bold text-white", found.title), make("p", "break-all", found.url),
      make("p", "", `記事 ${found.entries} 件: ${found.sample.filter(Boolean).join(" / ")}`));
    const f = form.elements;  // form.name is the form's own name, so get the inputs from elements
    f.namedItem("name").value = found.title.slice(0, 60);
    genreOptions(f.namedItem("genre"), f.namedItem("genre").value);
    f.namedItem("terms_url").value = "";
    f.namedItem("mixed").checked = false;
    f.namedItem("og_image").checked = false;
    form.classList.remove("hidden");
  } catch (err) {
    status.className = "mb-3 text-sm text-rose-300";
    status.textContent = err.message;
  }
});

document.getElementById("manual-form").addEventListener("submit", async e => {
  e.preventDefault();
  if (!agreed()) return;
  const form = e.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const f = form.elements;
    await addFeed({ url: feedsState.found.url, name: f.namedItem("name").value, genre: f.namedItem("genre").value,
                    mixed: f.namedItem("mixed").checked, og_image: f.namedItem("og_image").checked,
                    terms_url: f.namedItem("terms_url").value || null, site_url: feedsState.found.site_url, source: "manual" });
    form.classList.add("hidden");
    document.getElementById("manual-url").value = "";
    showFeedsTab("added");
  } catch (err) {
    toast(err.message);
  } finally {
    button.disabled = false;
  }
});

function renderChips() {
  chips.innerHTML = "";
  const chip = (label, pressed, onClick, sub) => {
    const b = document.createElement("button");
    b.className = "chip shrink-0 rounded-full font-bold ring-1 " +
      (sub ? "bg-white/5 px-3 py-1 text-xs ring-white/15" : "bg-white/10 px-4 py-1.5 text-sm ring-white/25");
    b.textContent = label;
    b.setAttribute("aria-pressed", String(pressed));
    b.addEventListener("click", onClick);
    chips.append(b);
    return b;
  };
  chip("すべて", !category, () => selectGenre("", ""));
  for (const t of taxonomy) {
    const shown = t.genres.filter(g => !hiddenGenres.has(g.name));
    if (!shown.length) continue;
    const b = chip(t.category, category === t.category && !genre, () => selectGenre(t.category, ""));
    if (category !== t.category || shown.length < 2) continue;
    for (const g of shown) chip(g.name, genre === g.name, () => selectGenre(t.category, g.name), true);
    b.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
}

function selectGenre(cat, gen) {
  category = cat;
  genre = gen;
  renderChips();
  reset();
}

// ---- Settings: hidden sub-genres / muted words / favorite words (stored on the server, shared across browsers)
let hiddenGenres = new Set();
let wordSettings = { mute_words: [], like_words: [] };
let updateCheck = true;  // Check for new versions (server-side setting)

async function putSettings(body) {
  const res = await fetch("/api/settings", {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }).then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (res) {
    hiddenGenres = new Set(res.hidden_genres);
    wordSettings = { mute_words: res.mute_words, like_words: res.like_words };
    updateCheck = res.update_check;
  }
  return res;
}

// Add one word from "words you reacted to"
async function addWord(kind, word) {
  const key = kind === "like" ? "like_words" : "mute_words";
  if (wordSettings[key].includes(word)) return;
  if (!await putSettings({ [key]: [...wordSettings[key], word] })) { toast("保存できませんでした"); return; }
  toast(kind === "like" ? `「${word}」を好きな言葉にしました` : `「${word}」をミュートしました（設定で外せます）`);
  reset();
}

function applyHidden() {
  // Dim them in the charts and hide them from the narrow-window strip
  document.querySelectorAll(".p-weight [data-genre]").forEach(r => r.classList.toggle("opacity-35", hiddenGenres.has(r.dataset.genre)));
  document.querySelectorAll("#pref-strip [data-genre]").forEach(r => r.classList.toggle("hidden", hiddenGenres.has(r.dataset.genre)));
}

function openSettings() {
  const box = document.getElementById("genre-settings");
  box.innerHTML = "";
  for (const t of taxonomy) {
    const sec = document.createElement("div");
    const h = document.createElement("p");
    h.className = "mb-1.5 flex items-center gap-1.5 text-xs font-bold text-white/50";
    h.append(catDot(t.category), t.category);
    const grid = document.createElement("div");
    grid.className = "grid grid-cols-2 gap-x-3 gap-y-1.5";
    for (const g of t.genres) {
      const label = document.createElement("label");
      label.className = "flex cursor-pointer items-center gap-2 rounded-lg bg-white/5 px-3 py-2";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = g.name;
      cb.checked = !hiddenGenres.has(g.name);
      cb.className = "h-4 w-4 accent-white";
      label.append(cb, g.name);
      grid.append(label);
    }
    sec.append(h, grid);
    box.append(sec);
  }
  document.getElementById("mute-words").value = wordSettings.mute_words.join("\n");
  document.getElementById("like-words").value = wordSettings.like_words.join("\n");
  document.getElementById("update-check").checked = updateCheck;
  document.getElementById("settings").showModal();
}

document.getElementById("settings-btn").addEventListener("click", openSettings);
document.getElementById("settings-all").addEventListener("click", () =>
  document.querySelectorAll("#genre-settings input").forEach(cb => { cb.checked = true; }));
document.getElementById("settings-save").addEventListener("click", async () => {
  const hidden = [...document.querySelectorAll("#genre-settings input")].filter(cb => !cb.checked).map(cb => cb.value);
  const lines = id => document.getElementById(id).value.split(/[\n、,]/).map(w => w.trim()).filter(Boolean);
  const res = await putSettings({ hidden_genres: hidden, mute_words: lines("mute-words"), like_words: lines("like-words"),
                                  update_check: document.getElementById("update-check").checked });
  if (!res) { toast("保存できませんでした"); return; }
  document.getElementById("settings").close();
  if (hiddenGenres.has(genre)) genre = "";
  if (category && taxonomy.find(t => t.category === category)?.genres.every(g => hiddenGenres.has(g.name))) category = "";
  applyHidden();
  renderChips();
  reset();
  toast("設定を保存しました");
  checkUpdate();  // Hide the "!" right away when the check was turned off
});

Promise.all([
  fetch("/api/genres").then(r => r.json()),
  fetch("/api/settings").then(r => r.json()).catch(() => ({ hidden_genres: [] })),
]).then(([t, st]) => {
  taxonomy = t;
  hiddenGenres = new Set(st.hidden_genres);
  wordSettings = { mute_words: st.mute_words || [], like_words: st.like_words || [] };
  updateCheck = st.update_check !== false;
  renderChips();
  applyHidden();
}).catch(() => {});

// ---- Charts: preferences (diverging bars) / action breakdown (stacked bars) / last 30 actions (dots)
// Colors were checked for contrast and distinguishability on the dark surfaces (#0d0d0d / #18181b)
const ACT_STYLE = {
  skip: { color: "#e11d48", sym: "←", label: "興味なし" },
  enough: { color: "#7c3aed", sym: "↑", label: "タイトルで十分" },  // Not used for learning
  open: { color: "#0284c7", sym: "→", label: "開く・興味あり" },  // keep / seen from 0.3 are counted here too (merged on the server)
};
const PREF_POS = "#3987e5", PREF_NEG = "#e66767", PREF_ZERO = "#383835";
const SHORT = { "テクノロジー": "テック", "経済": "経済", "エンタメ": "エンタメ", "社会": "社会" };
let prefsVersion = -1;
let lastActionId = 0;

function make(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
const actTotal = c => Object.keys(ACT_STYLE).reduce((sum, a) => sum + (c[a] || 0), 0);
function weightText(w) {
  const v = Math.round(w);
  return v > 0 ? `+${v} 多め` : v < 0 ? `−${-v} 少なめ` : "±0";
}
function placeWeightBar(bar, w, limit) {
  const pct = Math.min(1, Math.abs(w) / limit) * 50;
  bar.style.width = `${pct}%`;
  bar.style.left = w >= 0 ? "50%" : `${50 - pct}%`;
  bar.style.background = w >= 0 ? PREF_POS : PREF_NEG;
  bar.style.borderRadius = w >= 0 ? "0 4px 4px 0" : "4px 0 0 4px";  // Round only the end away from the zero line
}

function catDot(category) {
  const dot = make("i", "inline-block h-2 w-2 shrink-0 rounded-full");
  dot.style.background = (CAT_STYLE[category] || CAT_STYLE["社会"]).tag;
  return dot;
}

function buildPrefsPanel(root, p) {
  const row = cat => make("span", "whitespace-nowrap text-white/70", SHORT[cat]);
  root.innerHTML = "";
  const head = make("div", "mb-4");
  head.append(make("h2", "font-bold", "あなたの傾向"), make("p", "p-total mt-0.5 text-[11px] tabular-nums text-white/50"));

  const weight = make("div", "p-weight mb-5 space-y-1.5");
  weight.setAttribute("role", "img");
  weight.append(make("h3", "text-[11px] font-bold tracking-widest text-white/40", "好み（ほかのジャンルより開く割合が高いほど多め。↑ は数えない）"));
  for (const g of p.groups) {
    const label = make("p", "flex items-center gap-1.5 pt-1.5 text-[10px] font-bold text-white/45");
    label.append(catDot(g.category), g.category);
    weight.append(label);
    for (const x of g.genres) {
      const r = make("div", "grid grid-cols-[5.2em_1fr_4.6em] items-center gap-2 text-xs");
      r.dataset.genre = x.genre;
      const track = make("span", "relative h-2.5");
      track.append(make("span", "absolute inset-y-[-3px] left-1/2 w-0.5 -translate-x-1/2"), make("span", "w-bar absolute inset-y-0"));
      track.firstChild.style.background = PREF_ZERO;
      r.append(make("span", "truncate text-white/70", x.short), track,
               make("span", "w-val whitespace-nowrap text-right tabular-nums text-[11px] text-white/60"));
      weight.append(r);
    }
  }
  weight.append(make("p", "grid grid-cols-[5.2em_1fr_4.6em] gap-2 pt-1 text-[10px] text-white/35"));
  weight.lastChild.innerHTML = '<span></span><span class="flex justify-between"><span>← 少なめ</span><span>多め →</span></span><span></span>';

  const mix = make("div", "p-mix mb-5 space-y-2");
  mix.setAttribute("role", "img");
  mix.append(make("h3", "text-[11px] font-bold tracking-widest text-white/40", "操作の内訳"));
  const legend = make("div", "flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-white/60");
  for (const a of Object.values(ACT_STYLE)) {
    const item = make("span", "flex items-center gap-1");
    const sw = make("i", "inline-block h-2.5 w-2.5 rounded-sm");
    sw.style.background = a.color;
    item.append(sw, `${a.sym} ${a.label}`);
    legend.append(item);
  }
  mix.append(legend);
  for (const g of p.groups) {
    const r = make("div", "grid grid-cols-[3.6em_1fr_auto] items-center gap-2 text-xs");
    r.dataset.cat = g.category;
    const track = make("span", "relative h-3");
    const bar = make("span", "mix-bar absolute inset-y-0 left-0 flex gap-[2px] overflow-visible");
    for (const a of Object.keys(ACT_STYLE)) {
      const seg = make("span", "mix-seg h-full");
      seg.dataset.act = a;
      seg.style.background = ACT_STYLE[a].color;
      bar.append(seg);
    }
    track.append(bar);
    r.append(row(g.category), track, make("span", "m-val whitespace-nowrap text-right tabular-nums text-[11px] text-white/55"));
    mix.append(r);
  }

  const words = make("div", "p-words mb-5");
  words.append(make("h3", "mb-1.5 text-[11px] font-bold tracking-widest text-white/40", "反応した言葉（押すと 好きな言葉 / ミュート に追加）"),
               make("div", "w-like mb-1.5 flex flex-wrap gap-1.5"), make("div", "w-dislike flex flex-wrap gap-1.5"));

  const flow = make("div", "p-flow space-y-1.5");
  flow.setAttribute("role", "img");
  flow.append(make("h3", "mb-1 text-[11px] font-bold tracking-widest text-white/40", "直近 30 回の流れ"));
  for (const g of p.groups) {
    const r = make("div", "grid grid-cols-[3.6em_1fr] items-center gap-2 text-xs");
    r.dataset.cat = g.category;
    r.append(row(g.category), make("span", "f-row grid h-3 grid-cols-[repeat(30,minmax(0,1fr))] items-center"));
    flow.append(r);
  }
  flow.append(make("p", "grid grid-cols-[3.6em_1fr] gap-2 text-[10px] text-white/35"));
  flow.lastChild.innerHTML = '<span></span><span class="flex justify-between"><span>← 古い</span><span>新しい →</span></span>';

  root.append(head, weight, words, mix, flow);
}

function buildStrip(strip, p) {
  strip.innerHTML = "";
  for (const g of p.groups) for (const x of g.genres) {
    const item = make("span", "flex shrink-0 items-center gap-1.5 text-[10px] text-white/60");
    item.dataset.genre = x.genre;
    const track = make("span", "relative h-1.5 w-9 rounded-full bg-white/10");
    track.append(make("span", "absolute inset-y-[-2px] left-1/2 w-px"), make("span", "w-bar absolute inset-y-0"));
    track.firstChild.style.background = PREF_ZERO;
    item.append(catDot(g.category), make("span", "", x.short), track, make("span", "s-val w-[1.4em] text-right tabular-nums"));
    strip.append(item);
  }
}

function renderPanel(root, p, fresh) {
  const byCat = Object.fromEntries(p.groups.map(g => [g.category, g]));
  const genres = p.groups.flatMap(g => g.genres.map(x => ({ ...x, category: g.category })));
  const byGenre = Object.fromEntries(genres.map(x => [x.genre, x]));
  const t = p.total;
  root.querySelector(".p-total").textContent =
    `仕分け ${actTotal(t)} 件　` + Object.keys(ACT_STYLE).map(a => `${ACT_STYLE[a].sym}${t[a]}`).join(" ");

  root.querySelectorAll(".p-weight [data-genre]").forEach(r => {
    const x = byGenre[r.dataset.genre];
    if (!x) return;
    placeWeightBar(r.querySelector(".w-bar"), x.weight, p.weight_limit);
    r.querySelector(".w-val").textContent = weightText(x.weight);
    const counts = Object.keys(ACT_STYLE).map(a => `${ACT_STYLE[a].label}${x[a]}`).join(" ");
    r.children[1].dataset.tip = `${x.category} › ${x.genre}：${weightText(x.weight)}（範囲 ±${p.weight_limit}）${counts}`;
  });
  root.querySelector(".p-weight").setAttribute("aria-label",
    "好み: " + genres.map(x => `${x.genre} ${weightText(x.weight)}`).join("、"));

  const max = Math.max(1, ...p.groups.map(actTotal));
  root.querySelectorAll(".p-mix [data-cat]").forEach(r => {
    const c = byCat[r.dataset.cat];
    const total = actTotal(c);
    r.querySelector(".mix-bar").style.width = `${(total / max) * 100}%`;
    const segs = [...r.querySelectorAll(".mix-seg")];
    segs.forEach(seg => {
      const n = c[seg.dataset.act];
      seg.style.flex = `${n} 1 0px`;
      seg.style.display = n ? "" : "none";
      seg.style.borderRadius = "0";
      seg.dataset.tip = `${c.category}：${ACT_STYLE[seg.dataset.act].label} ${n} 回`;
    });
    const last = segs.filter(seg => c[seg.dataset.act]).pop();
    if (last) last.style.borderRadius = "0 4px 4px 0";  // Round only the end
    r.querySelector(".m-val").textContent =
      total ? Object.keys(ACT_STYLE).filter(a => c[a]).map(a => `${ACT_STYLE[a].sym}${c[a]}`).join(" ") : "—";
  });
  root.querySelector(".p-mix").setAttribute("aria-label", "操作の内訳: " + p.groups
    .map(c => `${c.category} ` + Object.keys(ACT_STYLE).map(a => `${ACT_STYLE[a].label}${c[a]}`).join(" ")).join("、"));

  for (const [kind, color, label] of [["like", PREF_POS, "興味あり"], ["dislike", PREF_NEG, "興味なし"]]) {
    const box = root.querySelector(`.w-${kind}`);
    box.innerHTML = "";
    const list = p.words?.[kind] || [];
    if (!list.length) box.append(make("span", "text-[11px] text-white/30", `${label}側: まだありません`));
    for (const [w, pos, neg] of list) {
      const b = make("button", "flex items-center gap-1 rounded-full bg-white/5 px-2 py-0.5 text-[11px] text-white/80 ring-1 hover:bg-white/10");
      b.style.setProperty("--tw-ring-color", color);
      b.append(make("i", "inline-block h-1.5 w-1.5 rounded-full"), w, make("span", "text-white/40 tabular-nums", String(kind === "like" ? pos : neg)));
      b.firstChild.style.background = color;
      b.dataset.tip = `${w}：興味あり ${pos} 回 / 興味なし ${neg} 回。押すと${kind === "like" ? "好きな言葉" : "ミュートする言葉"}に追加`;
      b.addEventListener("click", () => addWord(kind === "like" ? "like" : "mute", w));
      box.append(b);
    }
  }

  const rows = Object.fromEntries([...root.querySelectorAll(".p-flow [data-cat]")]
    .map(r => [r.dataset.cat, r.querySelector(".f-row")]));
  Object.values(rows).forEach(r => { r.innerHTML = ""; });
  const offset = 30 - p.recent.length;  // Newest on the right
  p.recent.forEach((a, i) => {
    const row = rows[a.category];
    if (!row) return;
    const dot = make("span", "dot" + (fresh.has(a.id) ? " new" : ""));
    dot.style.gridColumn = String(offset + i + 1);
    dot.style.background = ACT_STYLE[a.action]?.color ?? "#888";
    const time = new Date(a.at).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
    dot.dataset.tip = `${time} ${a.genre || a.category} ${ACT_STYLE[a.action]?.label ?? a.action}（${a.media_name ?? ""}）`;
    row.append(dot);
  });
  root.querySelector(".p-flow").setAttribute("aria-label", `直近 ${p.recent.length} 回の操作`);
}

function renderStrip(strip, p) {
  const byGenre = Object.fromEntries(p.groups.flatMap(g => g.genres).map(x => [x.genre, x]));
  strip.querySelectorAll("[data-genre]").forEach(item => {
    const x = byGenre[item.dataset.genre];
    if (!x) return;
    placeWeightBar(item.querySelector(".w-bar"), x.weight, p.weight_limit);
    const v = Math.round(x.weight);
    item.querySelector(".s-val").textContent = v > 0 ? `+${v}` : v < 0 ? `−${-v}` : "0";
  });
  strip.setAttribute("aria-label", "あなたの傾向を開く。" +
    p.groups.flatMap(g => g.genres).map(x => `${x.genre} ${weightText(x.weight)}`).join("、"));
}

// Draw only when version is newer than ours, so a late, older response can't roll the charts back
function renderPrefs(p, { self = false } = {}) {
  if (!p || p.version <= prefsVersion) return;
  const first = prefsVersion < 0;
  const fresh = new Set(first ? [] : p.recent.filter(a => a.id > lastActionId).map(a => a.id));
  prefsVersion = p.version;
  lastActionId = p.last_id ?? p.version;
  document.querySelectorAll(".prefs-panel").forEach(root => {
    if (!root.firstChild) buildPrefsPanel(root, p);
    renderPanel(root, p, fresh);
  });
  const strip = document.getElementById("pref-strip");
  if (!strip.firstChild) buildStrip(strip, p);
  renderStrip(strip, p);
  applyHidden();
  if (first || self) return;
  // Actions from another tab: drop those cards from our stack and reload the opened list
  const done = new Set(p.recent.filter(a => fresh.has(a.id)).map(a => a.article_id));
  const before = queue.length;
  queue = queue.filter(n => !done.has(n.id));
  if (queue.length !== before) layout();
  loadOpened();
}

async function pollPrefs() {
  if (document.visibilityState !== "visible") return;
  renderPrefs(await fetch("/api/prefs").then(r => r.json()).catch(() => null));
}
setInterval(pollPrefs, 5000);
document.addEventListener("visibilitychange", pollPrefs);
const prefStrip = document.getElementById("pref-strip");
prefStrip.addEventListener("click", () => document.getElementById("prefs-dialog").showModal());
prefStrip.addEventListener("keydown", e => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); prefStrip.click(); }
});

// Tooltips: hover an element with data-tip
const tip = document.getElementById("tip");
function showTip(target, x, y) {
  const host = target.closest("dialog") || document.body;
  if (tip.parentElement !== host) host.append(tip);
  tip.textContent = target.dataset.tip;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = `${Math.min(window.innerWidth - w - 8, x + 12)}px`;
  tip.style.top = `${Math.min(window.innerHeight - h - 8, y + 14)}px`;
  tip.style.opacity = "1";
}
document.addEventListener("pointerover", e => {
  const t = e.target.closest?.("[data-tip]");
  if (t) showTip(t, e.clientX, e.clientY); else tip.style.opacity = "0";
});
document.addEventListener("pointermove", e => {
  const t = e.target.closest?.("[data-tip]");
  if (t) showTip(t, e.clientX, e.clientY);
});

// ---- New-version check: a "!" on the i button and a notice in About when a newer release exists
async function checkUpdate() {
  const u = await fetch("/api/update").then(r => r.json()).catch(() => null);
  const newer = !!u?.newer;
  document.getElementById("update-badge").classList.toggle("hidden", !newer);
  document.getElementById("update-badge").classList.toggle("grid", newer);
  document.getElementById("about-update").classList.toggle("hidden", !newer);
  if (newer) {
    document.querySelector("#about-update .update-latest").textContent = u.latest;
    document.querySelector("#about-update .update-link").href = u.url;
  }
}

// ---- Bundled Chrome extension: suggest it until it's installed (its marker.js sets data-swipe-news-extension)
const EXT_HIDE_KEY = "swipe-news:ext-hint-hidden";
const extDialog = document.getElementById("ext-dialog");
const isChromium = () => navigator.userAgentData?.brands?.some(b => /Chrom|Edge/.test(b.brand)) ?? /Chrome\//.test(navigator.userAgent);

async function openExtGuide() {
  document.getElementById("about").close();
  const folder = await api("/api/extension").then(r => r.folder).catch(() => null);
  const open = document.getElementById("ext-open");
  open.disabled = !folder;
  open.classList.toggle("opacity-40", !folder);
  document.getElementById("ext-folder").textContent = folder ?? "このインストールには同梱されていません。GitHub のソースの extension フォルダを使ってください";
  extDialog.showModal();
}

document.getElementById("ext-btn").addEventListener("click", openExtGuide);
document.getElementById("about-ext").addEventListener("click", openExtGuide);
document.getElementById("ext-open").addEventListener("click", async () => {
  const res = await fetch("/api/extension/open", { method: "POST", headers: { "X-Swipe-News": "1" } }).catch(() => null);
  toast(res?.ok ? "エクスプローラーで extension フォルダの場所を開きました" : "フォルダを開けませんでした");
});
document.getElementById("ext-copy").addEventListener("click", () =>
  navigator.clipboard.writeText("chrome://extensions").then(() => toast("コピーしました。アドレスバーに貼り付けてください"), () => {}));
document.getElementById("ext-hide").addEventListener("click", () => {
  try { localStorage.setItem(EXT_HIDE_KEY, "1"); } catch { /* Hidden for this session only */ }
  document.getElementById("ext-btn").classList.add("hidden");
  extDialog.close();
  toast("ボタンを消しました。入れ方は「i」からも見られます");
});
// The content script runs at document_start, but give it a moment
setTimeout(() => {
  let hidden = false;
  try { hidden = localStorage.getItem(EXT_HIDE_KEY) === "1"; } catch { /* Show it */ }
  const installed = !!document.documentElement.dataset.swipeNewsExtension;
  const show = !installed && !hidden && isChromium();
  document.getElementById("ext-btn").classList.toggle("hidden", !show);
  document.getElementById("ext-btn").classList.toggle("flex", show);
}, 1500);

// ---- About: version, recommended-list URL and the on-device model
fetch("/api/config").then(r => r.json()).then(({ version, catalog_url, ai_genre }) => {
  document.getElementById("about-version").textContent = `${version}`;
  document.getElementById("catalog-source").textContent = catalog_url;
  if (ai_genre?.enabled) {
    document.getElementById("about-genre-ai").classList.remove("hidden");
    document.querySelector("#about-genre-ai .ai-model").textContent = ai_genre.model;
  }
}).catch(() => {});

renderOpened();
loadOpened();
loadFeeds();
checkUpdate();
setInterval(checkUpdate, 6 * 60 * 60 * 1000);  // The server asks ditsuki.com at most once a day; this just picks that up
pollPrefs();
try { if (localStorage.getItem("swipe-news:dopa") === "1") setDopa(true, { quiet: true }); } catch { /* Stay off if storage can't be read */ }
fill();
