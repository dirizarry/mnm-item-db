/* Central persistence — characters, gear library, guilds, shared bank (v2). */
(function () {
  const K = {
    CHARS: "mnm_v2_characters",
    GEAR: "mnm_v2_gear",
    GUILDS: "mnm_v2_guilds",
    BANK: "mnm_v2_bank",
    SERVERS: "mnm_v2_servers",
    SESSION: "mnm_v2_session",
    FLAG: "mnm_v2_migrated",
  };

  const INTENTS = ["owned", "desired", "template"];
  const INTENT_LABEL = { owned: "Owned", desired: "Desired", template: "Template" };

  const RACE_NAMES = {
    HUM: "Human", DWF: "Dwarf", GNM: "Gnome", GOB: "Goblin", HFL: "Halfling",
    HIE: "High Elf", OGR: "Ogre", TRL: "Troll", ELF: "Wood Elf",
    DDF: "Deep Dwarf", DEF: "Deep Elf", DGN: "Deep Gnome",
  };
  const CLASS_NAMES = {
    ARC: "Archer", BRD: "Bard", BST: "Beastmaster", CLR: "Cleric", DRU: "Druid",
    ELE: "Elementalist", ENC: "Enchanter", FTR: "Fighter", INQ: "Inquisitor",
    MNK: "Monk", NEC: "Necromancer", PAL: "Paladin", RNG: "Ranger", ROG: "Rogue",
    SHD: "Shadowknight", SHM: "Shaman", SPB: "Spellblade", WIZ: "Wizard",
  };

  const read = (k, fb) => { try { return JSON.parse(localStorage.getItem(k) || JSON.stringify(fb ?? {})); } catch { return fb ?? {}; } };
  const write = (k, v) => localStorage.setItem(k, JSON.stringify(v));
  const uid = (p) => p + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);

  function inferIntent(gear) {
    const slots = Object.keys(gear.slots || {}).filter((s) => gear.slots[s]);
    if (!slots.length) return "desired";
    const acq = gear.acquired || {};
    const got = slots.filter((s) => acq[s]).length;
    return got >= slots.length * 0.7 ? "owned" : "desired";
  }

  function migrate() {
    if (localStorage.getItem(K.FLAG)) return;

    const chars = read(K.CHARS, {});
    const gear = read(K.GEAR, {});
    const guilds = read(K.GUILDS, {});
    const servers = read(K.SERVERS, ["Default"]);
    const defaultServer = servers[0] || "Default";

    // legacy mnm_builds → name-keyed chars/gear (if v1 migration didn't run)
    const oldBuilds = read("mnm_builds", {});
    const v1Chars = read("mnm_chars", {});
    const v1Gear = read("mnm_gear", {});

    for (const [name, b] of Object.entries(oldBuilds)) {
      if (!v1Chars[name]) v1Chars[name] = { name, race: b.race, cls: b.cls, base: b.base, traits: b.traits };
      if (!v1Gear[name]) v1Gear[name] = { name, cls: b.cls, slots: b.slots || {}, acquired: b.acquired || {} };
    }

    const charIdByName = {};
    const pairedGearNames = new Set();
    for (const [name, c] of Object.entries(v1Chars)) {
      const id = uid("c_");
      charIdByName[name] = id;
      let gearId = null;
      if (v1Gear[name]) {
        pairedGearNames.add(name);
        gearId = uid("g_");
        const g = v1Gear[name];
        gear[gearId] = {
          id: gearId,
          name: g.name || name,
          cls: g.cls || c.cls || "",
          server: defaultServer,
          intent: inferIntent(g),
          tags: [],
          linkedCharacterIds: [id],
          slots: g.slots || {},
          acquired: g.acquired || {},
        };
      }
      chars[id] = {
        id,
        name: c.name || name,
        server: defaultServer,
        level: c.level || null,
        race: c.race || "",
        cls: c.cls || "",
        guildId: null,
        base: c.base || {},
        traits: c.traits || { major_combat: "", minor_combat: "", major_noncombat: "", minor_noncombat: "" },
        gearSetIds: gearId ? [gearId] : [],
        activeGearSetId: gearId,
        targetGearSetId: gearId,
      };
    }

    // orphan gear sets (not paired by name)
    for (const [name, g] of Object.entries(v1Gear)) {
      if (pairedGearNames.has(name)) continue;
      const id = uid("g_");
      gear[id] = {
        id,
        name: g.name || name,
        cls: g.cls || "",
        server: defaultServer,
        intent: inferIntent(g),
        tags: [],
        linkedCharacterIds: [],
        slots: g.slots || {},
        acquired: g.acquired || {},
      };
    }

    // legacy single roster → one guild
    const roster = read("mnm_roster", {});
    if (roster.members?.length && !Object.keys(guilds).length) {
      const gid = uid("guild_");
      guilds[gid] = {
        id: gid,
        name: roster.name || "Imported Roster",
        server: defaultServer,
        members: roster.members.map((m) => ({
          id: uid("gm_"),
          characterId: null,
          targetGearSetId: null,
          imported: m.gear ? {
            charName: m.charName,
            race: m.race,
            cls: m.cls,
            gearName: m.gearName,
            gear: m.gear,
          } : null,
        })),
      };
    }

    write(K.CHARS, chars);
    write(K.GEAR, gear);
    write(K.GUILDS, guilds);
    write(K.SERVERS, servers.length ? servers : ["Default"]);
    write(K.BANK, read(K.BANK, {}));
    localStorage.setItem(K.FLAG, "1");
  }

  /* ---------- session ---------- */
  function getSession() { return read(K.SESSION, { characterId: null, gearSetId: null }); }
  function setSession(partial) { write(K.SESSION, Object.assign(getSession(), partial)); }

  /* ---------- servers ---------- */
  function listServers() { return read(K.SERVERS, ["Default"]); }
  function addServer(name) {
    const n = String(name || "").trim();
    if (!n) return;
    const s = listServers();
    if (!s.includes(n)) { s.push(n); write(K.SERVERS, s.sort()); }
  }

  /* ---------- characters ---------- */
  function listCharacters() { return Object.values(read(K.CHARS, {})); }
  function getCharacter(id) { return read(K.CHARS, {})[id] || null; }
  function saveCharacter(c) {
    if (!c.id) c.id = uid("c_");
    const all = read(K.CHARS, {});
    all[c.id] = c;
    write(K.CHARS, all);
    return c;
  }
  function deleteCharacter(id) {
    const all = read(K.CHARS, {});
    const c = all[id];
    if (!c) return;
    delete all[id];
    write(K.CHARS, all);
    // unlink from gear
    const gear = read(K.GEAR, {});
    Object.values(gear).forEach((g) => {
      g.linkedCharacterIds = (g.linkedCharacterIds || []).filter((x) => x !== id);
    });
    write(K.GEAR, gear);
  }

  /* ---------- gear sets ---------- */
  function listGearSets(filter) {
    let list = Object.values(read(K.GEAR, {}));
    if (filter?.intent) list = list.filter((g) => g.intent === filter.intent);
    if (filter?.cls) list = list.filter((g) => !g.cls || g.cls === filter.cls);
    if (filter?.server) list = list.filter((g) => !g.server || g.server === filter.server);
    if (filter?.characterId) list = list.filter((g) => (g.linkedCharacterIds || []).includes(filter.characterId));
    return list.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  }
  function getGearSet(id) { return read(K.GEAR, {})[id] || null; }
  function saveGearSet(g) {
    if (!g.id) g.id = uid("g_");
    if (!g.intent) g.intent = "desired";
    const all = read(K.GEAR, {});
    all[g.id] = g;
    write(K.GEAR, all);
    return g;
  }
  function deleteGearSet(id) {
    const all = read(K.GEAR, {});
    delete all[id];
    write(K.GEAR, all);
    listCharacters().forEach((c) => {
      let dirty = false;
      if (c.gearSetIds?.includes(id)) { c.gearSetIds = c.gearSetIds.filter((x) => x !== id); dirty = true; }
      if (c.activeGearSetId === id) { c.activeGearSetId = c.gearSetIds[0] || null; dirty = true; }
      if (c.targetGearSetId === id) { c.targetGearSetId = c.gearSetIds.find((g) => getGearSet(g)?.intent === "desired") || null; dirty = true; }
      if (dirty) saveCharacter(c);
    });
  }
  function linkGearToCharacter(gearId, charId) {
    const g = getGearSet(gearId);
    const c = getCharacter(charId);
    if (!g || !c) return;
    g.linkedCharacterIds = [...new Set([...(g.linkedCharacterIds || []), charId])];
    c.gearSetIds = [...new Set([...(c.gearSetIds || []), gearId])];
    if (!c.activeGearSetId) c.activeGearSetId = gearId;
    if (!c.targetGearSetId && g.intent === "desired") c.targetGearSetId = gearId;
    saveGearSet(g);
    saveCharacter(c);
  }
  function cloneGearSet(id, opts) {
    const src = getGearSet(id);
    if (!src) return null;
    const g = JSON.parse(JSON.stringify(src));
    g.id = uid("g_");
    g.name = opts?.name || (src.name + " (copy)");
    g.intent = opts?.intent || src.intent;
    g.linkedCharacterIds = opts?.characterId ? [opts.characterId] : [];
    saveGearSet(g);
    if (opts?.characterId) linkGearToCharacter(g.id, opts.characterId);
    return g;
  }

  function gearProgress(g) {
    const slots = Object.keys(g.slots || {}).filter((s) => g.slots[s]);
    if (!slots.length) return { total: 0, done: 0, pct: 0 };
    const done = slots.filter((s) => g.acquired?.[s]).length;
    return { total: slots.length, done, pct: Math.round((done / slots.length) * 100) };
  }

  /* ---------- shared bank (per server, no nodrop) ---------- */
  function getBank(server) {
    const all = read(K.BANK, {});
    return all[server] || {};
  }
  function bankHas(server, itemKey) {
    return !!getBank(server)[itemKey];
  }
  function canBank(item) {
    return item && !item.nodrop;
  }
  function bankAdd(server, itemKey, item) {
    if (item && !canBank(item)) return false;
    const all = read(K.BANK, {});
    all[server] = all[server] || {};
    all[server][itemKey] = true;
    write(K.BANK, all);
    return true;
  }
  function bankRemove(server, itemKey) {
    const all = read(K.BANK, {});
    if (all[server]) { delete all[server][itemKey]; write(K.BANK, all); }
  }
  function applyBankToGear(gear, server, lookup) {
    if (!gear || !server) return gear;
    const bank = getBank(server);
    const acquired = Object.assign({}, gear.acquired || {});
    Object.entries(gear.slots || {}).forEach(([slotId, title]) => {
      const it = lookup?.(title);
      if (it && canBank(it) && (bank[it.name || title] || bank[title])) acquired[slotId] = true;
    });
    return Object.assign({}, gear, { acquired });
  }

  /* ---------- guilds ---------- */
  function listGuilds() { return Object.values(read(K.GUILDS, {})); }
  function getGuild(id) { return read(K.GUILDS, {})[id] || null; }
  function saveGuild(g) {
    if (!g.id) g.id = uid("guild_");
    const all = read(K.GUILDS, {});
    all[g.id] = g;
    write(K.GUILDS, all);
    return g;
  }
  function deleteGuild(id) {
    const all = read(K.GUILDS, {});
    delete all[id];
    write(K.GUILDS, all);
    listCharacters().forEach((c) => { if (c.guildId === id) { c.guildId = null; saveCharacter(c); } });
  }
  function assignCharacterToGuild(charId, guildId) {
    const c = getCharacter(charId);
    if (!c) return;
    // remove from old guild roster entries
    if (c.guildId && c.guildId !== guildId) {
      const old = getGuild(c.guildId);
      if (old) {
        old.members = (old.members || []).filter((m) => m.characterId !== charId);
        saveGuild(old);
      }
    }
    c.guildId = guildId || null;
    saveCharacter(c);
    if (guildId) {
      const g = getGuild(guildId);
      if (g) {
        g.members = g.members || [];
        if (!g.members.some((m) => m.characterId === charId)) {
          g.members.push({
            id: uid("gm_"),
            characterId: charId,
            targetGearSetId: c.targetGearSetId || c.activeGearSetId,
          });
        }
        saveGuild(g);
      }
    }
  }

  migrate();

  window.MNM_store = {
    K, INTENTS, INTENT_LABEL, RACE_NAMES, CLASS_NAMES,
    uid, inferIntent, gearProgress,
    getSession, setSession,
    listServers, addServer,
    listCharacters, getCharacter, saveCharacter, deleteCharacter,
    listGearSets, getGearSet, saveGearSet, deleteGearSet, linkGearToCharacter, cloneGearSet,
    getBank, bankHas, canBank, bankAdd, bankRemove, applyBankToGear,
    listGuilds, getGuild, saveGuild, deleteGuild, assignCharacterToGuild,
  };
})();
