/* M&M Item DB — static front end over window.MNM_ITEMS */
const WIKI = "https://monstersandmemories.miraheze.org/wiki/";
const ITEMS = (window.MNM_ITEMS || []);
const META = (window.MNM_META || {});

const SLOT_ORDER = [
  "HEAD","FACE","EAR","NECK","SHOULDERS","CHEST","ARMS","BACK","WRIST","HANDS",
  "FINGER","WAIST","LEGS","FEET","PRIMARY","SECONDARY","RANGED","AMMO",
];
const STAT_COLS = ["ac","dmg","delay","str","sta","agi","dex","int","wis","cha","hp","mana"];
const RESISTS = ["cold_resist","fire_resist","magic_resist","poison_resist","disease_resist","electric_resist","corruption_resist","holy_resist"];

const wikiUrl = (t) => WIKI + encodeURIComponent(String(t).replace(/ /g, "_"));
const tokens = (s) => (s ? String(s).toUpperCase().replace(/[,/]/g, " ").split(/\s+/).filter(Boolean) : []);
const slotsOf = (it) => tokens(it.slot);
const classesOf = (it) => tokens(it.classes).filter((c) => c !== "ALL" && c !== "NONE");
const hasResist = (it) => RESISTS.some((r) => Number(it[r]) > 0);

/* ---- build filter option lists ---- */
function uniqueSorted(values, order) {
  const set = new Set();
  values.forEach((v) => v && set.add(v));
  const arr = [...set];
  if (order) arr.sort((a, b) => (order.indexOf(a) + 1 || 999) - (order.indexOf(b) + 1 || 999) || a.localeCompare(b));
  else arr.sort();
  return arr;
}
const allSlots = uniqueSorted(ITEMS.flatMap(slotsOf), SLOT_ORDER);
const allClasses = uniqueSorted(ITEMS.flatMap(classesOf));

function fillSelect(el, opts) {
  opts.forEach((o) => {
    const opt = document.createElement("option");
    opt.value = o; opt.textContent = o; el.appendChild(opt);
  });
}
fillSelect(document.getElementById("slot"), allSlots);
fillSelect(document.getElementById("cls"), allClasses);
fillSelect(document.getElementById("bis-cls"), allClasses);

/* ---- table ---- */
const ratioOf = (it) => (it.dmg && it.delay ? +(it.dmg / it.delay).toFixed(3) : null);
const COLS = [
  { k: "name", label: "Name" },
  { k: "slot", label: "Slot" },
  { k: "dmg", label: "DMG", num: true },
  { k: "delay", label: "DLY", num: true },
  { k: "ratio", label: "Ratio", num: true, calc: ratioOf },
  ...STAT_COLS.filter((k) => k !== "dmg" && k !== "delay").map((k) => ({ k, label: k.toUpperCase(), num: true })),
  { k: "weight", label: "Wt", num: true },
  { k: "classes", label: "Classes", cls: true },
];
let sortKey = "name", sortAsc = true;

function buildHead() {
  const head = document.getElementById("head");
  head.innerHTML = "";
  COLS.forEach((c) => {
    const th = document.createElement("th");
    th.textContent = c.label;
    th.onclick = () => { if (sortKey === c.k) sortAsc = !sortAsc; else { sortKey = c.k; sortAsc = c.k === "name"; } render(); };
    if (sortKey === c.k) { th.classList.add("sorted"); if (sortAsc) th.classList.add("asc"); }
    head.appendChild(th);
  });
}

function currentFilters() {
  const mins = {};
  document.querySelectorAll("[data-min]").forEach((i) => { if (i.value !== "") mins[i.dataset.min] = Number(i.value); });
  return {
    q: document.getElementById("q").value.trim().toLowerCase(),
    slot: document.getElementById("slot").value,
    cls: document.getElementById("cls").value,
    magic: document.getElementById("f-magic").checked,
    nodrop: document.getElementById("f-nodrop").checked,
    unique: document.getElementById("f-unique").checked,
    resist: document.getElementById("f-resist").checked,
    mins,
  };
}

function matches(it, f) {
  if (f.q && !String(it.name || "").toLowerCase().includes(f.q)) return false;
  if (f.slot && !slotsOf(it).includes(f.slot)) return false;
  if (f.cls) {
    const cl = classesOf(it);
    if (cl.length && !cl.includes(f.cls)) return false; // empty/ALL = usable by all
  }
  if (f.magic && !it.magic) return false;
  if (f.nodrop && !it.nodrop) return false;
  if (f.unique && !it.unique) return false;
  if (f.resist && !hasResist(it)) return false;
  for (const [k, v] of Object.entries(f.mins)) if (!(Number(it[k]) >= v)) return false;
  return true;
}

function colValue(it, k) {
  const col = COLS.find((c) => c.k === k);
  return col && col.calc ? col.calc(it) : it[k];
}
function sortRows(rows) {
  const dir = sortAsc ? 1 : -1;
  return rows.sort((a, b) => {
    let x = colValue(a, sortKey), y = colValue(b, sortKey);
    if (sortKey === "name" || sortKey === "slot" || sortKey === "classes") {
      return String(x || "").localeCompare(String(y || "")) * dir;
    }
    x = x == null ? -Infinity : Number(x); y = y == null ? -Infinity : Number(y);
    return (x - y) * dir;
  });
}

function render() {
  const f = currentFilters();
  let rows = ITEMS.filter((it) => matches(it, f));
  rows = sortRows(rows);
  document.getElementById("count").textContent = `${rows.length.toLocaleString()} items`;
  buildHead();
  const body = document.getElementById("rows");
  body.innerHTML = "";
  const frag = document.createDocumentFragment();
  rows.slice(0, 1000).forEach((it) => {
    const tr = document.createElement("tr");
    COLS.forEach((c) => {
      const td = document.createElement("td");
      if (c.k === "name") {
        const a = document.createElement("a");
        a.href = wikiUrl(it.title); a.target = "_blank"; a.rel = "noopener";
        a.textContent = it.name || it.title;
        td.appendChild(a);
        ["magic","nodrop","unique"].forEach((fl) => {
          if (it[fl]) { const s = document.createElement("span"); s.className = "flagchip"; s.textContent = fl === "nodrop" ? "ND" : fl[0].toUpperCase(); td.appendChild(s); }
        });
      } else if (c.num) {
        td.className = "num";
        const v = c.calc ? c.calc(it) : it[c.k];
        td.textContent = v == null ? "" : v;
      } else if (c.cls) {
        td.className = "cls";
        td.textContent = it.classes || "";
      } else {
        td.textContent = it[c.k] == null ? "" : it[c.k];
      }
      tr.appendChild(td);
    });
    frag.appendChild(tr);
  });
  body.appendChild(frag);
  if (rows.length > 1000) document.getElementById("count").textContent += " (showing first 1000)";
}

/* ---- Best in Slot ---- */
function renderBis() {
  const cls = document.getElementById("bis-cls").value;
  const stat = document.getElementById("bis-stat").value;
  const grid = document.getElementById("bis-grid");
  grid.innerHTML = "";
  const slots = allSlots.length ? allSlots : SLOT_ORDER;
  slots.forEach((slot) => {
    const candidates = ITEMS.filter((it) => {
      if (!slotsOf(it).includes(slot)) return false;
      const cl = classesOf(it);
      if (cls && cl.length && !cl.includes(cls)) return false;
      return Number(it[stat]) > 0;
    }).sort((a, b) => Number(b[stat]) - Number(a[stat]));
    const card = document.createElement("div");
    card.className = "slotcard" + (candidates.length ? "" : " empty");
    const best = candidates[0];
    card.innerHTML = `<h3>${slot}</h3>` + (best
      ? `<div class="item"><a href="${wikiUrl(best.title)}" target="_blank" rel="noopener">${best.name || best.title}</a></div>
         <div class="val">${stat.toUpperCase()}: ${best[stat]}</div>`
      : `<div class="item">— none —</div>`);
    grid.appendChild(card);
  });
}

/* ---- wiring ---- */
document.querySelectorAll(".tab").forEach((t) => t.onclick = () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
  document.querySelectorAll(".view").forEach((x) => x.classList.remove("active"));
  t.classList.add("active");
  document.getElementById(t.dataset.tab).classList.add("active");
  if (t.dataset.tab === "bis") renderBis();
});
["q","slot","cls","f-magic","f-nodrop","f-unique","f-resist"].forEach((id) => {
  const el = document.getElementById(id);
  el.addEventListener("input", render);
});
document.querySelectorAll("[data-min]").forEach((i) => i.addEventListener("input", render));
document.getElementById("reset").onclick = () => {
  document.querySelectorAll(".filters input").forEach((i) => { if (i.type === "checkbox") i.checked = false; else i.value = ""; });
  document.getElementById("slot").value = ""; document.getElementById("cls").value = "";
  render();
};
document.getElementById("bis-cls").addEventListener("change", renderBis);
document.getElementById("bis-stat").addEventListener("change", renderBis);

document.getElementById("src").textContent = META.source || "";
document.getElementById("meta").textContent =
  `${(META.item_count ?? ITEMS.length).toLocaleString()} items` +
  (META.mob_count ? ` · ${META.mob_count.toLocaleString()} monsters` : "") +
  (META.drop_links ? ` · ${META.drop_links.toLocaleString()} drop links` : "") +
  (META.generated ? ` · extracted ${META.generated}` : "") +
  " · data from the Monsters & Memories wiki (unofficial fan tool)";

window.MNM_showItem = (title) => {
  const it = ITEMS.find((x) => x.title === title);
  document.querySelector('.tab[data-tab="browse"]')?.click();
  document.getElementById("q").value = it?.name || title;
  render();
};

(function () {
  const hash = location.hash || "";
  if (hash.startsWith("#item=")) {
    window.MNM_showItem(decodeURIComponent(hash.slice(6)));
  } else if (hash.startsWith("#mob=") && window.MNM_showMob) {
    window.MNM_showMob(decodeURIComponent(hash.slice(5)));
  }
})();

if (!ITEMS.length) {
  document.getElementById("count").textContent = "No data — run the crawl and build step (see README).";
}
render();
