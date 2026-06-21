/* Gear library — owned vs desired vs template sets. */
(function () {
  const ST = window.MNM_store;
  const PL = () => window.MNM_planner;

  let els = {};
  let intentFilter = "";

  function esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  }

  function render() {
    const cls = els.clsFilter.value;
    const server = els.serverFilter.value;
    let list = ST.listGearSets({ cls: cls || undefined, server: server || undefined });
    if (intentFilter) list = list.filter((g) => g.intent === intentFilter);

    els.grid.innerHTML = "";
    if (!list.length) {
      els.grid.innerHTML = "<p class='gl-empty'>No gear sets match. Create one from a character or the planner.</p>";
      return;
    }

    list.forEach((g) => {
      const prog = ST.gearProgress(g);
      const linked = (g.linkedCharacterIds || []).map((id) => ST.getCharacter(id)?.name).filter(Boolean);
      const card = document.createElement("div");
      card.className = "gl-card intent-" + (g.intent || "desired");
      card.innerHTML =
        `<div class="gl-head"><strong>${esc(g.name)}</strong>` +
        `<span class="intent-badge ${g.intent}">${ST.INTENT_LABEL[g.intent] || g.intent}</span></div>` +
        `<div class="gl-meta muted">${esc(ST.CLASS_NAMES[g.cls] || g.cls || "Any class")} · ${esc(g.server || "Default")}</div>` +
        `<div class="gl-prog">${g.intent === "owned" ? "Equipped" : "Progress"}: ${prog.done}/${prog.total} (${prog.pct}%)</div>` +
        (linked.length ? `<div class="gl-linked muted">Linked: ${linked.map(esc).join(", ")}</div>` : "") +
        `<div class="gl-actions">` +
        `<button type="button" data-open="${g.id}">Open</button>` +
        `<button type="button" data-clone="${g.id}">Clone</button>` +
        `<button type="button" data-intent="${g.id}">Set intent</button>` +
        `<button type="button" data-share="${g.id}">Share</button>` +
        `<button type="button" data-del="${g.id}" class="danger">Delete</button>` +
        `</div>`;
      els.grid.appendChild(card);
    });

    els.grid.querySelectorAll("[data-open]").forEach((b) => {
      b.onclick = () => {
        const g = ST.getGearSet(b.dataset.open);
        const charId = (g.linkedCharacterIds || [])[0] || ST.getSession().characterId;
        ST.setSession({ characterId: charId, gearSetId: g.id });
        PL()?.loadContext?.(charId, g.id);
        document.querySelector('.tab[data-tab="planner"]')?.click();
      };
    });
    els.grid.querySelectorAll("[data-clone]").forEach((b) => {
      b.onclick = () => {
        const intent = prompt("Clone as: owned, desired, or template?", "desired") || "desired";
        ST.cloneGearSet(b.dataset.clone, { intent: ST.INTENTS.includes(intent) ? intent : "desired" });
        render();
      };
    });
    els.grid.querySelectorAll("[data-intent]").forEach((b) => {
      b.onclick = () => {
        const g = ST.getGearSet(b.dataset.intent);
        const intent = prompt("Set intent: owned, desired, or template", g.intent || "desired");
        if (!intent || !ST.INTENTS.includes(intent)) return;
        g.intent = intent;
        ST.saveGearSet(g);
        render();
      };
    });
    els.grid.querySelectorAll("[data-share]").forEach((b) => {
      b.onclick = () => {
        const g = ST.getGearSet(b.dataset.share);
        const payload = { name: g.name, cls: g.cls, intent: g.intent, slots: g.slots, acquired: g.acquired };
        const enc = btoa(unescape(encodeURIComponent(JSON.stringify(payload))));
        const url = location.origin + location.pathname + "#gear=" + enc;
        navigator.clipboard?.writeText(url).catch(() => {});
        prompt("Share link:", url);
      };
    });
    els.grid.querySelectorAll("[data-del]").forEach((b) => {
      b.onclick = () => {
        if (confirm("Delete this gear set?")) { ST.deleteGearSet(b.dataset.del); render(); }
      };
    });
  }

  function setIntentFilter(intent) {
    intentFilter = intent;
    document.querySelectorAll(".gl-intent-tab").forEach((t) =>
      t.classList.toggle("active", t.dataset.intent === intent));
    render();
  }

  function init() {
    els = {
      grid: document.getElementById("gl-grid"),
      clsFilter: document.getElementById("gl-filter-cls"),
      serverFilter: document.getElementById("gl-filter-server"),
    };
    els.clsFilter.innerHTML = `<option value="">Any class</option>` +
      Object.entries(ST.CLASS_NAMES).sort((a, b) => a[1].localeCompare(b[1]))
        .map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
    els.serverFilter.innerHTML = `<option value="">Any server</option>` +
      ST.listServers().map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
    els.clsFilter.onchange = els.serverFilter.onchange = render;
    document.querySelectorAll(".gl-intent-tab").forEach((t) =>
      t.onclick = () => setIntentFilter(t.dataset.intent));
    document.querySelector('.tab[data-tab="gear-library"]').addEventListener("click", render);
    setIntentFilter("");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
