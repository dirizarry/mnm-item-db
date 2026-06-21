/* Guild tab — multi-guild rosters + aggregated acquisition. */
(function () {
  const AQ = window.MNM_acquire;
  const ST = window.MNM_store;
  const PL = () => window.MNM_planner;

  let activeGuildId = null;
  let els = {};

  function esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  }

  function activeGuild() {
    return activeGuildId ? ST.getGuild(activeGuildId) : null;
  }

  function memberGear(m) {
    if (m.imported?.gear) return m.imported.gear;
    const c = m.characterId ? ST.getCharacter(m.characterId) : null;
    if (!c) return null;
    const gid = m.targetGearSetId || c.targetGearSetId || c.activeGearSetId;
    const g = gid ? ST.getGearSet(gid) : null;
    if (!g) return null;
    const lookup = (t) => AQ.lookup(t);
    return ST.applyBankToGear(g, c.server, lookup);
  }

  function memberInfo(m) {
    if (m.imported) {
      return {
        charName: m.imported.charName,
        race: m.imported.race,
        cls: m.imported.cls,
        gearName: m.imported.gearName || m.imported.gear?.name,
      };
    }
    const c = ST.getCharacter(m.characterId);
    if (!c) return { charName: "?", race: "", cls: "" };
    const g = ST.getGearSet(m.targetGearSetId || c.targetGearSetId || c.activeGearSetId);
    return { charName: c.name, race: c.race, cls: c.cls, gearName: g?.name };
  }

  function refreshGuildSelect() {
    const guilds = ST.listGuilds().sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    if (!activeGuildId && guilds.length) activeGuildId = guilds[0].id;
    els.guildSelect.innerHTML = guilds.length
      ? guilds.map((g) => `<option value="${g.id}"${g.id === activeGuildId ? " selected" : ""}>${esc(g.name)} (${esc(g.server)})</option>`).join("")
      : `<option value="">— no guilds —</option>`;
    const g = activeGuild();
    if (g) {
      els.guildName.value = g.name;
      els.guildServer.value = g.server || "Default";
    }
  }

  function saveGuild() {
    let g = activeGuild() || { members: [] };
    g.name = els.guildName.value.trim() || "Guild";
    g.server = els.guildServer.value.trim() || "Default";
    ST.addServer(g.server);
    g = ST.saveGuild(Object.assign(g, { id: activeGuildId || undefined }));
    activeGuildId = g.id;
    refreshGuildSelect();
    flash(els.save, "Saved");
    render();
  }

  function newGuild() {
    const name = prompt("Guild name:") || "New Guild";
    const server = prompt("Server:", "Default") || "Default";
    ST.addServer(server);
    const g = ST.saveGuild({ name, server, members: [] });
    activeGuildId = g.id;
    refreshGuildSelect();
    render();
  }

  function addLocalMember() {
    const g = activeGuild();
    if (!g) return alert("Create or select a guild first.");
    const chars = ST.listCharacters().filter((c) => c.server === g.server);
    if (!chars.length) return alert(`No characters on server ${g.server}.`);
    const names = chars.map((c) => c.name).join(", ");
    const pick = prompt(`Character on ${g.server}:\n${names}`);
    const c = chars.find((x) => x.name.toLowerCase() === (pick || "").trim().toLowerCase());
    if (!c) return;
    ST.assignCharacterToGuild(c.id, g.id);
    refreshGuildSelect();
    render();
  }

  function addFromShare() {
    const g = activeGuild();
    if (!g) return;
    const raw = prompt("Paste gear share link or JSON:");
    if (!raw) return;
    try {
      const m = raw.match(/gear=([^&\s]+)/);
      const gear = m ? JSON.parse(decodeURIComponent(escape(atob(m[1])))) : JSON.parse(raw);
      const charName = prompt("Member name:") || gear.name || "Member";
      g.members = g.members || [];
      g.members.push({
        id: ST.uid("gm_"),
        imported: { charName, cls: gear.cls, race: "", gearName: gear.name, gear },
      });
      ST.saveGuild(g);
      render();
    } catch { alert("Invalid gear set."); }
  }

  function exportGuild() {
    const g = activeGuild();
    if (!g) return;
    const blob = new Blob([JSON.stringify(g, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = (g.name || "guild").replace(/\s+/g, "-").toLowerCase() + ".json";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function importGuild() {
    const raw = prompt("Paste guild JSON:");
    if (!raw) return;
    try {
      const data = JSON.parse(raw);
      const g = ST.saveGuild(Object.assign(data, { id: undefined }));
      activeGuildId = g.id;
      refreshGuildSelect();
      render();
    } catch { alert("Invalid guild JSON."); }
  }

  function aggregate() {
    const g = activeGuild();
    const pl = PL();
    const slots = pl?.slotList?.() || [];
    const members = g?.members || [];
    const byItem = new Map();
    const byZone = new Map();
    const byMob = new Map();
    const raw = {}, tools = {};

    members.forEach((m) => {
      const info = memberInfo(m);
      const gear = memberGear(m);
      if (!gear) return;
      const needed = AQ.neededItems(gear, slots);
      needed.forEach(({ id, label, it }) => {
        const ik = AQ.key(it);
        const entry = byItem.get(ik) || { it, needs: [] };
        entry.needs.push({ member: info.charName, slot: label });
        byItem.set(ik, entry);
        if (it.crafted && Array.isArray(it.components))
          it.components.forEach((c) => AQ.expand(c.name, c.qty || 1, raw, tools, new Set([ik]), 0));
        const zones = it.drops_zones?.length ? it.drops_zones : (it.drops_mobs?.length ? ["(zone unknown)"] : []);
        zones.forEach((z) => {
          if (!byZone.has(z)) byZone.set(z, []);
          byZone.get(z).push({ member: info.charName, it, mobs: it.drops_mobs || [] });
        });
        (it.drops_mobs || []).forEach((mob) => {
          const me = byMob.get(mob) || { zone: (it.drops_zones || [])[0] || "", needs: [] };
          me.needs.push({ member: info.charName, it });
          byMob.set(mob, me);
        });
      });
    });

    return {
      members,
      items: [...byItem.values()].sort((a, b) => b.needs.length - a.needs.length),
      zones: [...byZone.entries()].sort((a, b) => b[1].length - a[1].length),
      mobs: [...byMob.entries()]
        .map(([mob, data]) => ({ mob, zone: data.zone, needs: data.needs, members: new Set(data.needs.map((n) => n.member)).size }))
        .filter((x) => x.members > 1 || x.needs.length > 1)
        .sort((a, b) => b.members - a.members),
      mats: Object.entries(raw).sort((a, b) => b[1] - a[1]),
      tools: Object.keys(tools).sort(),
    };
  }

  function renderRoster() {
    const g = activeGuild();
    els.roster.innerHTML = "";
    if (!g?.members?.length) {
      els.roster.innerHTML = "<p class='gd-empty'>Add local characters (same server) or paste share links.</p>";
      return;
    }
    const slots = PL()?.slotList?.() || [];
    g.members.forEach((m) => {
      const info = memberInfo(m);
      const gear = memberGear(m);
      const needed = gear ? AQ.neededItems(gear, slots) : [];
      const total = Object.keys(gear?.slots || {}).filter((id) => gear.slots[id]).length;
      const done = total - needed.length;
      const card = document.createElement("div");
      card.className = "gd-member";
      card.innerHTML =
        `<div class="gd-member-head"><strong>${esc(info.charName)}</strong>` +
        `<span class="muted">${esc(PL()?.className?.(info.cls) || info.cls || "")}</span>` +
        `<span class="gd-prog">${done}/${total}</span></div>` +
        `<div class="gd-member-gear muted">Target: <b>${esc(info.gearName || "?")}</b></div>` +
        `<div class="gd-member-actions">` +
        (m.characterId ? `<button type="button" data-open="${m.characterId}">Open</button>` : "") +
        `<button type="button" data-remove="${m.id}" class="danger">Remove</button></div>`;
      els.roster.appendChild(card);
    });
    els.roster.querySelectorAll("[data-open]").forEach((b) =>
      b.onclick = () => {
        const c = ST.getCharacter(b.dataset.open);
        PL()?.loadContext?.(c.id, c.targetGearSetId || c.activeGearSetId);
        document.querySelector('.tab[data-tab="planner"]')?.click();
      });
    els.roster.querySelectorAll("[data-remove]").forEach((b) =>
      b.onclick = () => {
        const g2 = activeGuild();
        g2.members = g2.members.filter((x) => x.id !== b.dataset.remove);
        ST.saveGuild(g2);
        render();
      });
  }

  function renderAggregate() {
    const { members, items, zones, mobs, mats, tools } = aggregate();
    const g = activeGuild();
    els.summary.innerHTML = g
      ? `<span class="aq-prog">${g.name}</span> · ${esc(g.server)} · ${members.length} members · ${items.length} unique items needed`
      : "Create or select a guild.";

    els.needs.innerHTML = items.length
      ? `<table class="aq-mat-tbl gd-tbl"><tr><th>#</th><th>Item</th><th>Source</th><th>Who</th></tr>` +
        items.map(({ it, needs }) => {
          const types = (it.source_types || ["unknown"]).map((t) => `<span class="aq-badge t-${t}">${AQ.SRC_LABEL[t] || t}</span>`).join("");
          const who = needs.map((n) => `<span class="gd-tag">${esc(n.member)}</span>`).join(" ");
          return `<tr><td class="num">${needs.length > 1 ? `<span class="gd-hot">${needs.length}×</span>` : needs.length}</td>` +
            `<td><a href="${AQ.wikiUrl(it.title)}" target="_blank" rel="noopener">${esc(it.name || it.title)}</a></td><td>${types}</td><td>${who}</td></tr>`;
        }).join("") + `</table>`
      : "<p class='gd-empty'>No unacquired gear across roster.</p>";

    els.contested.innerHTML = mobs.length
      ? mobs.map(({ mob, zone, needs, members: mc }) =>
          `<div class="aq-zone-card gd-contested"><div class="aq-zone-name"><a href="${AQ.wikiUrl(mob)}" target="_blank" rel="noopener">${esc(mob)}</a>` +
          (zone ? ` <span class="muted">in ${esc(zone)}</span>` : "") +
          ` <span class="gd-hot">${mc} members</span></div>` +
          needs.map((n) => `<div class="aq-zone-item">${esc(n.member)} — ${esc(n.it.name || n.it.title)}</div>`).join("") +
          `</div>`).join("")
      : "<p class='gd-empty'>No contested mob drops yet.</p>";

    let matsHtml = mats.length
      ? `<table class="aq-mat-tbl"><tr><th>Qty</th><th>Material</th></tr>` +
        mats.map(([name, qty]) => `<tr><td class="num">${qty}</td><td><a href="${AQ.wikiUrl(name)}" target="_blank" rel="noopener">${esc(name)}</a></td></tr>`).join("") + `</table>`
      : "<p class='gd-empty'>No crafted gear remaining.</p>";
    if (tools.length) matsHtml += `<div class="aq-tools"><b>Tools:</b> ${tools.map((t) => esc(t)).join(", ")}</div>`;
    els.mats.innerHTML = matsHtml;

    els.zones.innerHTML = zones.length
      ? zones.map(([z, list]) => {
          const mc = new Set(list.map((x) => x.member)).size;
          const heat = mc >= 4 ? "gd-heat-4" : mc >= 3 ? "gd-heat-3" : mc >= 2 ? "gd-heat-2" : "";
          return `<div class="aq-zone-card ${heat}"><div class="aq-zone-name">${z === "(zone unknown)" ? z : esc(z)}` +
            ` <span class="gd-hot">${list.length} items</span> · ${mc} members</div>` +
            list.map((x) => `<div class="aq-zone-item">${esc(x.member)} — ${esc(x.it.name || x.it.title)}</div>`).join("") +
            `</div>`;
        }).join("")
      : "<p class='gd-empty'>No dropped gear remaining.</p>";
  }

  function render() { renderRoster(); renderAggregate(); }

  function flash(btn, msg) { const o = btn.textContent; btn.textContent = msg; setTimeout(() => (btn.textContent = o), 1200); }

  function init() {
    els = {
      guildSelect: document.getElementById("gd-select"),
      guildName: document.getElementById("gd-name"),
      guildServer: document.getElementById("gd-server"),
      save: document.getElementById("gd-save"),
      roster: document.getElementById("gd-roster"),
      summary: document.getElementById("gd-summary"),
      needs: document.getElementById("gd-needs"),
      contested: document.getElementById("gd-contested"),
      mats: document.getElementById("gd-mats"),
      zones: document.getElementById("gd-zones"),
    };
    els.guildServer.innerHTML = ST.listServers().map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
    refreshGuildSelect();
    els.guildSelect.onchange = () => { activeGuildId = els.guildSelect.value || null; refreshGuildSelect(); render(); };
    document.getElementById("gd-new").onclick = newGuild;
    document.getElementById("gd-add-local").onclick = addLocalMember;
    document.getElementById("gd-add-share").onclick = addFromShare;
    document.getElementById("gd-export").onclick = exportGuild;
    document.getElementById("gd-import").onclick = importGuild;
    els.save.onclick = saveGuild;
    document.querySelector('.tab[data-tab="guild"]').addEventListener("click", () => { refreshGuildSelect(); render(); });
    render();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
