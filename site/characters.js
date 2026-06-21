/* Characters hub — alt list, guild assign, screenshot import hook. */
(function () {
  const ST = window.MNM_store;
  const PL = () => window.MNM_planner;

  let els = {};
  let importPreview = null;

  function esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  }

  function openPlanner(charId, gearId) {
    ST.setSession({ characterId: charId, gearSetId: gearId || null });
    PL()?.loadContext?.(charId, gearId);
    document.querySelector('.tab[data-tab="planner"]')?.click();
  }

  function render() {
    const server = els.serverFilter.value;
    const guildF = els.guildFilter.value;
    const chars = ST.listCharacters()
      .filter((c) => !server || c.server === server)
      .filter((c) => !guildF || c.guildId === guildF)
      .sort((a, b) => (a.name || "").localeCompare(b.name || ""));

    els.list.innerHTML = "";
    if (!chars.length) {
      els.list.innerHTML = "<p class='ch-empty'>No characters yet. Create one below or import from a screenshot.</p>";
      return;
    }

    chars.forEach((c) => {
      const gearSets = (c.gearSetIds || []).map((id) => ST.getGearSet(id)).filter(Boolean);
      const owned = gearSets.filter((g) => g.intent === "owned");
      const desired = gearSets.filter((g) => g.intent === "desired");
      const target = c.targetGearSetId ? ST.getGearSet(c.targetGearSetId) : null;
      const prog = target ? ST.gearProgress(target) : { done: 0, total: 0, pct: 0 };
      const guild = c.guildId ? ST.getGuild(c.guildId) : null;

      const card = document.createElement("div");
      card.className = "ch-card";
      card.innerHTML =
        `<div class="ch-card-head"><strong>${esc(c.name)}</strong>` +
        `<span class="ch-badge">Lv ${c.level ?? "?"}</span>` +
        `<span class="muted">${esc(ST.RACE_NAMES[c.race] || "")} ${esc(ST.CLASS_NAMES[c.cls] || "")}</span></div>` +
        `<div class="ch-meta muted">${esc(c.server || "Default")}` +
        (guild ? ` · ${esc(guild.name)}` : "") +
        ` · ${gearSets.length} gear set${gearSets.length !== 1 ? "s" : ""}</div>` +
        `<div class="ch-sets">` +
        (owned.length ? `<span class="intent owned">${owned.length} owned</span>` : "") +
        (desired.length ? `<span class="intent desired">${desired.length} desired</span>` : "") +
        (target ? `<span class="ch-prog">${prog.done}/${prog.total} on target</span>` : "") +
        `</div>` +
        `<div class="ch-actions">` +
        `<button type="button" data-open="${c.id}">Open planner</button>` +
        `<button type="button" data-gear="${c.id}">+ Gear set</button>` +
        `<button type="button" data-guild="${c.id}">Guild</button>` +
        `<button type="button" data-del="${c.id}" class="danger">Delete</button>` +
        `</div>`;
      els.list.appendChild(card);
    });

    els.list.querySelectorAll("[data-open]").forEach((b) =>
      b.onclick = () => {
        const c = ST.getCharacter(b.dataset.open);
        openPlanner(c.id, c.activeGearSetId);
      });
    els.list.querySelectorAll("[data-gear]").forEach((b) =>
      b.onclick = () => {
        const c = ST.getCharacter(b.dataset.gear);
        const name = prompt("New gear set name:", "BiS target");
        if (!name) return;
        const intent = prompt("Intent: owned, desired, or template?", "desired") || "desired";
        const g = ST.saveGearSet({
          name,
          cls: c.cls,
          server: c.server,
          intent: ST.INTENTS.includes(intent) ? intent : "desired",
          linkedCharacterIds: [c.id],
          slots: {},
          acquired: {},
        });
        ST.linkGearToCharacter(g.id, c.id);
        if (intent === "desired") { c.targetGearSetId = g.id; ST.saveCharacter(c); }
        openPlanner(c.id, g.id);
      });
    els.list.querySelectorAll("[data-guild]").forEach((b) =>
      b.onclick = () => assignGuild(b.dataset.guild));
    els.list.querySelectorAll("[data-del]").forEach((b) =>
      b.onclick = () => {
        if (confirm("Delete this character?")) { ST.deleteCharacter(b.dataset.del); render(); refreshFilters(); }
      });
  }

  function assignGuild(charId) {
    const guilds = ST.listGuilds();
    const c = ST.getCharacter(charId);
    const names = guilds.map((g) => `${g.name} (${g.server})`).join("\n");
    const pick = prompt(`Assign ${c.name} to guild (blank = none):\n${names || "(no guilds — create one in Guild tab)"}`);
    if (pick === null) return;
    if (!pick.trim()) { ST.assignCharacterToGuild(charId, null); render(); return; }
    const g = guilds.find((x) => x.name.toLowerCase() === pick.trim().toLowerCase());
    if (!g) return alert("Guild not found. Create it in the Guild tab first.");
    if (g.server !== c.server && !confirm(`Character is on ${c.server} but guild is on ${g.server}. Assign anyway?`)) return;
    ST.assignCharacterToGuild(charId, g.id);
    render();
  }

  function refreshFilters() {
    const servers = ST.listServers();
    els.serverFilter.innerHTML = `<option value="">All servers</option>` +
      servers.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
    const guilds = ST.listGuilds();
    els.guildFilter.innerHTML = `<option value="">All guilds</option>` +
      guilds.map((g) => `<option value="${g.id}">${esc(g.name)}</option>`).join("");
  }

  function createCharacter() {
    const name = els.newName.value.trim();
    if (!name) return alert("Character name required.");
    const server = els.newServer.value.trim() || "Default";
    ST.addServer(server);
    const c = ST.saveCharacter({
      name,
      server,
      level: els.newLevel.value ? Number(els.newLevel.value) : null,
      race: els.newRace.value,
      cls: els.newClass.value,
      guildId: null,
      base: {},
      traits: { major_combat: "", minor_combat: "", major_noncombat: "", minor_noncombat: "" },
      gearSetIds: [],
      activeGearSetId: null,
      targetGearSetId: null,
    });
    els.newName.value = "";
    refreshFilters();
    render();
    openPlanner(c.id, null);
  }

  function onImportFile(ev) {
    const file = ev.target.files?.[0];
    if (!file) return;
    importPreview = URL.createObjectURL(file);
    els.importImg.src = importPreview;
    els.importImg.classList.remove("hidden");
    els.importPanel.classList.remove("hidden");
    els.importHint.textContent = "Confirm values below (full OCR coming soon — enter manually from screenshot).";
    ev.target.value = "";
  }

  function applyImport() {
    const name = els.impName.value.trim();
    if (!name) return alert("Name required.");
    const server = els.impServer.value.trim() || "Default";
    ST.addServer(server);
    const c = ST.saveCharacter({
      name,
      server,
      level: els.impLevel.value ? Number(els.impLevel.value) : null,
      race: els.impRace.value,
      cls: els.impClass.value,
      guildId: null,
      base: {},
      traits: { major_combat: "", minor_combat: "", major_noncombat: "", minor_noncombat: "" },
      gearSetIds: [],
      activeGearSetId: null,
      targetGearSetId: null,
    });
    els.importPanel.classList.add("hidden");
    refreshFilters();
    render();
    openPlanner(c.id, null);
    PL()?.applyBaseline?.();
  }

  function fillRaceClassSelects() {
    [els.newRace, els.newClass, els.impRace, els.impClass].forEach((sel, i) => {
      const isRace = i % 2 === 0;
      const entries = Object.entries(isRace ? ST.RACE_NAMES : ST.CLASS_NAMES).sort((a, b) => a[1].localeCompare(b[1]));
      sel.innerHTML = `<option value="">—</option>` + entries.map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
    });
    els.newServer.innerHTML = els.impServer.innerHTML = ST.listServers()
      .map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  }

  function init() {
    els = {
      list: document.getElementById("ch-list"),
      serverFilter: document.getElementById("ch-filter-server"),
      guildFilter: document.getElementById("ch-filter-guild"),
      newName: document.getElementById("ch-new-name"),
      newLevel: document.getElementById("ch-new-level"),
      newServer: document.getElementById("ch-new-server"),
      newRace: document.getElementById("ch-new-race"),
      newClass: document.getElementById("ch-new-class"),
      importImg: document.getElementById("ch-import-img"),
      importPanel: document.getElementById("ch-import-panel"),
      importHint: document.getElementById("ch-import-hint"),
      impName: document.getElementById("ch-imp-name"),
      impLevel: document.getElementById("ch-imp-level"),
      impServer: document.getElementById("ch-imp-server"),
      impRace: document.getElementById("ch-imp-race"),
      impClass: document.getElementById("ch-imp-class"),
    };
    fillRaceClassSelects();
    document.getElementById("ch-create").onclick = createCharacter;
    document.getElementById("ch-import-file").onchange = onImportFile;
    document.getElementById("ch-import-apply").onclick = applyImport;
    document.getElementById("ch-import-cancel").onclick = () => els.importPanel.classList.add("hidden");
    els.serverFilter.onchange = els.guildFilter.onchange = render;
    document.querySelector('.tab[data-tab="characters"]').addEventListener("click", () => { refreshFilters(); render(); });
    refreshFilters();
    render();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
