/* Acquire tab — solo sourcing checklist + recursive crafting-material rollup. */

(function () {

  const AQ = window.MNM_acquire;

  const { wikiUrl, lookup, key, SRC_LABEL, expand } = AQ;



  let els = {};

  function build() { return window.MNM_planner ? window.MNM_planner.getBuild() : null; }



  function render() {

    const b = build();

    if (!b) { els.list.innerHTML = "<p class='aq-empty'>Open the Build Planner and equip items first.</p>"; els.mats.innerHTML = ""; els.zones.innerHTML = ""; els.summary.textContent = ""; return; }



    const slots = window.MNM_planner.slotList();

    const hideDone = els.hideDone.checked;

    const equipped = slots.filter(([id]) => b.slots[id]).map(([id, label]) => ({ id, label, it: lookup(b.slots[id]) })).filter((x) => x.it);



    const acq = equipped.filter((e) => b.acquired[e.id]).length;

    els.title.textContent = (b.name ? b.name + " — " : "") + "Acquisition Checklist";

    els.summary.innerHTML =

      `<span class="aq-prog">${acq}/${equipped.length} acquired</span>` +

      (b.race || b.cls ? ` · ${window.MNM_planner.raceName(b.race) || ""} ${window.MNM_planner.className(b.cls) || ""}` : "");



    els.list.innerHTML = "";

    if (!equipped.length) els.list.innerHTML = "<p class='aq-empty'>No items equipped in the planner yet.</p>";

    equipped.forEach(({ id, label, it }) => {

      const done = !!b.acquired[id];

      if (hideDone && done) return;

      const types = it.source_types || ["unknown"];

      const card = document.createElement("div");

      card.className = "aq-card" + (done ? " done" : "");

      const badges = types.map((t) => `<span class="aq-badge t-${t}">${SRC_LABEL[t] || t}</span>`).join("");

      let detail = "";

      if (it.drops_mobs || it.drops_zones) {

        const zones = (it.drops_zones || []).map((z) => `<a href="${wikiUrl(z)}" target="_blank" rel="noopener">${z}</a>`).join(", ");

        const mobs = (it.drops_mobs || []).map((m) => `<a href="${wikiUrl(m)}" target="_blank" rel="noopener">${m}</a>`).join(", ");

        detail += `<div class="aq-line"><b>Drops:</b> ${mobs || "?"}${zones ? ` <span class="aq-zone">in ${zones}</span>` : ""}</div>`;

      }

      if (it.crafted) {

        const ts = (it.tradeskills || []).join(", ");

        const comps = (it.components || []).map((c) => `${c.qty}× <a href="${wikiUrl(c.name)}" target="_blank" rel="noopener">${c.name}</a>`).join(", ");

        detail += `<div class="aq-line"><b>Craft${ts ? " (" + ts + ")" : ""}:</b> ${comps || "recipe unknown"}</div>`;

      }

      if (it.quests) detail += `<div class="aq-line"><b>Quest:</b> ${it.quests.map((q) => `<a href="${wikiUrl(q)}" target="_blank" rel="noopener">${q}</a>`).join(", ")}</div>`;

      if (it.vendor_value) detail += `<div class="aq-line"><b>Vendor value:</b> ${it.vendor_value}</div>`;

      if (!detail) detail = `<div class="aq-line muted">No source data on the wiki yet.</div>`;

      card.innerHTML =

        `<label class="aq-check"><input type="checkbox" ${done ? "checked" : ""} data-acq="${id}">` +

        `<span class="aq-slot">${label}</span></label>` +

        `<div class="aq-body"><a class="aq-item" href="${wikiUrl(it.title)}" target="_blank" rel="noopener">${it.name || it.title}</a> ${badges}${detail}</div>`;

      els.list.appendChild(card);

    });

    els.list.querySelectorAll("[data-acq]").forEach((cb) =>

      cb.addEventListener("change", () => { b.acquired[cb.dataset.acq] = cb.checked; render(); }));



    const raw = {}, tools = {};

    equipped.forEach(({ it, id }) => {

      if (b.acquired[id]) return;

      if (it.crafted && Array.isArray(it.components))

        it.components.forEach((c) => expand(c.name, c.qty || 1, raw, tools, new Set([key(it)]), 0));

    });

    const mats = Object.entries(raw).sort((a, b2) => b2[1] - a[1]);

    let matsHtml = mats.length

      ? `<table class="aq-mat-tbl"><tr><th>Qty</th><th>Material</th><th>How</th></tr>` +

        mats.map(([name, qty]) => {

          const mi = lookup(name);

          const how = mi ? (mi.source_types || ["unknown"]).map((t) => SRC_LABEL[t] || t).join(", ") : "Gathered/raw";

          return `<tr><td class="num">${qty}</td><td><a href="${wikiUrl(name)}" target="_blank" rel="noopener">${name}</a></td><td class="muted">${how}</td></tr>`;

        }).join("") + `</table>`

      : "<p class='aq-empty'>No crafted gear in this build (or all acquired).</p>";

    const toolList = Object.keys(tools).sort();

    if (toolList.length) matsHtml += `<div class="aq-tools"><b>Tools (reusable):</b> ${toolList.map((t) => `<a href="${wikiUrl(t)}" target="_blank" rel="noopener">${t}</a>`).join(", ")}</div>`;

    els.mats.innerHTML = matsHtml;



    const zoneMap = {};

    equipped.forEach(({ it, id }) => {

      if (b.acquired[id]) return;

      (it.drops_zones && it.drops_zones.length ? it.drops_zones : (it.drops_mobs ? ["(zone unknown)"] : [])).forEach((z) => {

        (zoneMap[z] = zoneMap[z] || []).push({ item: it, mobs: it.drops_mobs || [] });

      });

    });

    const zones = Object.entries(zoneMap).sort((a, b2) => b2[1].length - a[1].length);

    els.zones.innerHTML = zones.length

      ? zones.map(([z, list]) =>

          `<div class="aq-zone-card"><div class="aq-zone-name">${z === "(zone unknown)" ? z : `<a href="${wikiUrl(z)}" target="_blank" rel="noopener">${z}</a>`} <span class="muted">(${list.length})</span></div>` +

          list.map((x) => `<div class="aq-zone-item">${x.item.name || x.item.title}${x.mobs.length ? ` <span class="muted">— ${x.mobs.join(", ")}</span>` : ""}</div>`).join("") +

          `</div>`).join("")

      : "<p class='aq-empty'>No dropped gear in this build (or all acquired).</p>";

  }



  function init() {

    els = {

      title: document.getElementById("aq-title"),

      summary: document.getElementById("aq-summary"),

      list: document.getElementById("aq-list"),

      mats: document.getElementById("aq-mats"),

      zones: document.getElementById("aq-zones"),

      hideDone: document.getElementById("aq-hide-done"),

    };

    els.hideDone.addEventListener("change", render);

    document.querySelector('.tab[data-tab="acquire"]').addEventListener("click", render);

  }



  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);

  else init();

})();

