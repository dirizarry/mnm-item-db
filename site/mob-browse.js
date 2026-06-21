/* Monsters browse — linked to items via MNM_DROPS */
(function () {
  const WIKI = "https://monstersandmemories.miraheze.org/wiki/";
  const MOBS = window.MNM_MOBS || [];
  const DROPS = window.MNM_DROPS || { byItem: {}, byMob: {} };
  const ITEMS = window.MNM_ITEMS || [];
  const wikiUrl = (t) => WIKI + encodeURIComponent(String(t).replace(/ /g, "_"));

  const byTitle = new Map(MOBS.map((m) => [m.title, m]));
  const itemByTitle = new Map(ITEMS.map((it) => [it.title, it]));

  const mobZones = (m) => (m.zones?.length ? m.zones : m.zone ? [m.zone] : []);
  const zones = [...new Set(MOBS.flatMap(mobZones).filter(Boolean))].sort();

  let sortKey = "level_min";
  let sortDir = 1;

  function levelLabel(m) {
    if (m.level_label) return m.level_label;
    if (m.level_min == null) return "—";
    if (m.level_min === m.level_max) return String(m.level_min);
    return `${m.level_min}–${m.level_max}`;
  }

  function lootCount(m) {
    const rel = DROPS.byMob[m.title] || [];
    if (rel.length) return rel.length;
    return (m.unique_loot?.length || 0) + (m.known_loot?.length || 0) + (m.common_loot?.length || 0);
  }

  const isNamedMob = (m) => (m.categories || []).includes("Named Mobs");

  function candidates() {
    const q = (document.getElementById("mob-q")?.value || "").toLowerCase();
    const zone = document.getElementById("mob-zone")?.value || "";
    const minLv = Number(document.getElementById("mob-min-lv")?.value);
    const maxLv = Number(document.getElementById("mob-max-lv")?.value);
    const namedOnly = document.getElementById("mob-named-only")?.checked;
    let list = MOBS.filter((m) => {
      if (namedOnly && !isNamedMob(m)) return false;
      if (q && !(m.name || m.title || "").toLowerCase().includes(q)) return false;
      if (zone && !mobZones(m).includes(zone)) return false;
      if (!Number.isNaN(minLv) && document.getElementById("mob-min-lv")?.value !== "" &&
          (m.level_max ?? m.level_min ?? 999) < minLv) return false;
      if (!Number.isNaN(maxLv) && document.getElementById("mob-max-lv")?.value !== "" &&
          (m.level_min ?? 0) > maxLv) return false;
      return true;
    });
    list.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "name") cmp = (a.name || "").localeCompare(b.name || "");
      else if (sortKey === "zone") cmp = mobZones(a).join(", ").localeCompare(mobZones(b).join(", "));
      else if (sortKey === "level_min") cmp = (a.level_min ?? 9999) - (b.level_min ?? 9999);
      else if (sortKey === "loot") cmp = lootCount(a) - lootCount(b);
      return cmp * sortDir;
    });
    return list;
  }

  function renderList() {
    const list = candidates();
    document.getElementById("mob-count").textContent = `${list.length} monsters`;
    const tbody = document.getElementById("mob-rows");
    const zoneDisplay = (m) => {
      const zs = mobZones(m);
      if (!zs.length) return "—";
      return zs.map((z) =>
        `<a href="${wikiUrl(z)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${z}</a>`
      ).join(", ");
    };
    tbody.innerHTML = list.slice(0, 800).map((m) =>
      `<tr data-mob="${m.title.replace(/"/g, "&quot;")}">` +
      `<td><a href="${wikiUrl(m.title)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${m.name || m.title}</a></td>` +
      `<td class="num">${levelLabel(m)}</td>` +
      `<td>${zoneDisplay(m)}</td>` +
      `<td>${m.race || "—"}</td>` +
      `<td class="num">${lootCount(m) || ""}</td>` +
      `</tr>`).join("");
    tbody.querySelectorAll("tr[data-mob]").forEach((tr) =>
      tr.onclick = () => showDetail(tr.dataset.mob));
  }

  function showDetail(title) {
    const m = byTitle.get(title);
    const panel = document.getElementById("mob-detail");
    if (!m) { panel.innerHTML = ""; panel.classList.add("hidden"); return; }
    panel.classList.remove("hidden");
    const rel = DROPS.byMob[title] || [];
    const TR = window.MNM_trust;
    const lootHtml = rel.length
      ? rel.map((d) => {
          const it = itemByTitle.get(d.item);
          const nm = it?.name || d.item;
          const trust = TR?.trustBadge(d) || "";
          const personal = TR?.personalBadge(d.item, title) || "";
          return `<li><span class="loot-kind ${d.kind || "drop"}">${d.kind || "drop"}</span> ` +
            `<a href="#" class="mob-item-link" data-item="${d.item.replace(/"/g, "&quot;")}">${nm}</a>` +
            `${trust}${personal}</li>`;
        }).join("")
      : [...(m.unique_loot || []).map((x) => `<li><span class="loot-kind unique">unique</span> ${x}</li>`),
         ...(m.known_loot || []).map((x) => `<li><span class="loot-kind known">known</span> ${x}</li>`),
         ...(m.common_loot || []).map((x) => `<li><span class="loot-kind common">common</span> ${x}</li>`)].join("") ||
        "<li class='muted'>No loot listed on wiki.</li>";

    panel.innerHTML =
      `<div class="mob-detail-head"><strong>${m.name || m.title}</strong>` +
      `<a href="${wikiUrl(m.title)}" target="_blank" rel="noopener">Wiki</a></div>` +
      `<div class="mob-detail-meta muted">${levelLabel(m)} · ${mobZones(m).join(", ") || "?"} · ${m.race || "?"}${m.class ? " · " + m.class : ""}</div>` +
      (m.location ? `<div class="mob-detail-loc">${m.location}</div>` : "") +
      (m.damage_per_hit ? `<div>Dmg/hit: ${m.damage_per_hit}</div>` : "") +
      (m.special ? `<div>Special: ${m.special}</div>` : "") +
      (TR?.personalForMob(title)?.length
        ? `<div class="personal-panel"><h4>Your kills & drops</h4>` +
          TR.personalForMob(title).slice(0, 12).map((r) =>
            `<div>${r.item} ×${r.count}${r.zone ? ` · ${r.zone}` : ""}</div>`
          ).join("") + `</div>`
        : "") +
      `<h4>Loot</h4><ul class="mob-loot">${lootHtml}</ul>`;
    panel.querySelectorAll(".mob-item-link").forEach((a) =>
      a.onclick = (e) => {
        e.preventDefault();
        window.MNM_showItem?.(a.dataset.item);
      });
  }

  function toggleSort(k) {
    if (sortKey === k) sortDir *= -1;
    else { sortKey = k; sortDir = k === "name" || k === "zone" ? 1 : -1; }
    renderList();
  }

  function init() {
    const zsel = document.getElementById("mob-zone");
    zsel.innerHTML = `<option value="">Any zone</option>` +
      zones.map((z) => `<option value="${z.replace(/"/g, "&quot;")}">${z}</option>`).join("");
    ["mob-q", "mob-zone", "mob-min-lv", "mob-max-lv", "mob-named-only"].forEach((id) =>
      document.getElementById(id)?.addEventListener("input", renderList));
    document.querySelectorAll(".mob-th").forEach((th) =>
      th.onclick = () => toggleSort(th.dataset.sort));
    document.querySelector('.tab[data-tab="monsters"]')?.addEventListener("click", renderList);
    renderList();
  }

  window.MNM_showMob = (title) => {
    document.querySelector('.tab[data-tab="monsters"]')?.click();
    showDetail(title);
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
