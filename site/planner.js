/* M&M Build Planner — equipment, stats, traits, save/load. Vanilla JS. */
(function () {
  const WIKI = "https://monstersandmemories.miraheze.org/wiki/";
  const ITEMS = window.MNM_ITEMS || [];
  const TRAITS = window.MNM_TRAITS || {};
  const BASESTATS = window.MNM_BASESTATS || {};
  const wikiUrl = (t) => WIKI + encodeURIComponent(String(t).replace(/ /g, "_"));
  const tok = (s) => (s ? String(s).toUpperCase().replace(/[,/]/g, " ").split(/\s+/).filter(Boolean) : []);
  const itemSlots = (it) => tok(it.slot);
  const itemClasses = (it) => tok(it.classes).filter((c) => c !== "ALL" && c !== "NONE");
  const usableBy = (it, cls) => { const c = itemClasses(it); return !cls || !c.length || c.includes(cls); };

  const byTitle = new Map(ITEMS.map((it) => [it.title, it]));

  const STATS = ["str", "sta", "agi", "dex", "int", "wis", "cha"];
  const RESISTS = [
    ["cold_resist", "Cold"], ["fire_resist", "Fire"], ["magic_resist", "Magic"],
    ["poison_resist", "Poison"], ["disease_resist", "Disease"],
    ["electric_resist", "Electric"], ["corruption_resist", "Corruption"], ["holy_resist", "Holy"],
  ];

  // EQ-style paper-doll: id -> {label, slot code}
  const SLOTS = [
    ["ear1", "Ear", "EAR"], ["head", "Head", "HEAD"], ["face", "Face", "FACE"], ["ear2", "Ear", "EAR"],
    ["neck", "Neck", "NECK"], ["shoulders", "Shoulders", "SHOULDERS"], ["back", "Back", "BACK"],
    ["chest", "Chest", "CHEST"], ["arms", "Arms", "ARMS"], ["wrist1", "Wrist", "WRIST"], ["wrist2", "Wrist", "WRIST"],
    ["hands", "Hands", "HANDS"], ["finger1", "Finger", "FINGER"], ["finger2", "Finger", "FINGER"],
    ["waist", "Waist", "WAIST"], ["legs", "Legs", "LEGS"], ["feet", "Feet", "FEET"],
    ["primary", "Primary", "PRIMARY"], ["secondary", "Secondary", "SECONDARY"],
    ["ranged", "Ranged", "RANGED"], ["ammo", "Ammo", "AMMO"],
  ];

  const TRAIT_SLOTS = [
    ["major_combat", "Major Combat"], ["minor_combat", "Minor Combat"],
    ["major_noncombat", "Major Non-Combat"], ["minor_noncombat", "Minor Non-Combat"],
  ];

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

  const els = {};
  let build = newBuild();
  let pickerSlot = null;
  const ST = () => window.MNM_store;
  const ACQ = () => window.MNM_acq;

  // The working "build" is a live combination of the current CHARACTER
  // (identity: race/class/stats/traits) and the current GEAR SET (slots/acquired).
  // They are persisted to separate stores so a character can own many gear sets
  // and public gear sets can be applied to any compatible character.
  function newBuild() {
    return {
      characterId: null, gearSetId: null,
      charName: "", gearName: "",
      level: null, server: "Default",
      gearIntent: "desired",
      name: "", race: "", cls: "",
      base: Object.fromEntries(STATS.map((s) => [s, 0])),
      slots: {},
      traits: { major_combat: "", minor_combat: "", major_noncombat: "", minor_noncombat: "" },
      acquired: {},
    };
  }
  function charPart() {
    return {
      id: build.characterId, name: build.charName, server: build.server, level: build.level,
      race: build.race, cls: build.cls, base: build.base, traits: build.traits,
      gearSetIds: [], activeGearSetId: build.gearSetId, targetGearSetId: null, guildId: null,
    };
  }
  function gearPart() {
    return {
      id: build.gearSetId, name: build.gearName, cls: build.cls, server: build.server,
      intent: build.gearIntent, slots: build.slots, acquired: build.acquired,
      linkedCharacterIds: build.characterId ? [build.characterId] : [], tags: [],
    };
  }
  function effectiveGear() {
    const g = gearPart();
    return ST()?.applyBankToGear(g, build.server, (t) => byTitle.get(t)) || g;
  }

  /* ---------- option lists ---------- */
  function fillSelect(sel, entries, placeholder) {
    sel.innerHTML = "";
    if (placeholder !== undefined) {
      const o = document.createElement("option"); o.value = ""; o.textContent = placeholder; sel.appendChild(o);
    }
    entries.forEach(([val, label]) => {
      const o = document.createElement("option"); o.value = val; o.textContent = label; sel.appendChild(o);
    });
  }

  /* ---------- traits ---------- */
  function traitReqOk(t) {
    const cls = tok(t.classes).filter((c) => c !== "ALL" && c !== "ANY");
    const race = tok(t.race).filter((r) => r !== "ALL" && r !== "ANY");
    const clsOk = !build.cls || !cls.length || cls.includes(build.cls);
    const raceOk = !build.race || !race.length || race.includes(build.race);
    return clsOk && raceOk;
  }
  function traitOptions(category) {
    return (TRAITS[category] || []).filter(traitReqOk);
  }

  function racialFor(race) {
    return (TRAITS.racial || []).find((t) => tok(t.race).includes(race));
  }

  /* ---------- base stats (race/class) ---------- */
  function baseEntry() {
    if (!build.race || !build.cls) return null;
    return BASESTATS[build.race + "|" + build.cls] || null;
  }
  function applyBaseline() {
    // Set base stats to the race/class starting values when available;
    // clear stale values when the combo has no entry.
    const e = baseEntry();
    if (e && e.current) build.base = Object.assign(Object.fromEntries(STATS.map((s) => [s, 0])), e.current);
    else if (build.race && build.cls) build.base = Object.fromEntries(STATS.map((s) => [s, 0]));
  }

  // valid classes per race, derived from the captured base-stat combos
  const validClassesByRace = {};
  Object.keys(BASESTATS).forEach((k) => {
    const [r, c] = k.split("|");
    (validClassesByRace[r] = validClassesByRace[r] || new Set()).add(c);
  });
  function setClassOptions(race) {
    const valid = race && validClassesByRace[race];
    const entries = Object.entries(CLASS_NAMES)
      .filter(([code]) => !valid || valid.has(code))
      .sort((a, b) => a[1].localeCompare(b[1]));
    const cur = build.cls;
    fillSelect(els.class, entries, "Any class");
    if (cur && (!valid || valid.has(cur))) els.class.value = cur;
    else { build.cls = ""; els.class.value = ""; }
  }
  function pointsInfo() {
    const e = baseEntry();
    if (!e) return null;
    const spent = STATS.reduce((n, s) => n + Math.max(0, Number(build.base[s] || 0) - Number((e.current || {})[s] || 0)), 0);
    return { total: e.points || 0, spent, remaining: (e.points || 0) - spent, current: e.current || {}, max: e.max || {} };
  }

  /* ---------- totals ---------- */
  function computeTotals() {
    const t = {
      ac: 0, hp: 0, mana: 0, weight: 0,
      str: 0, sta: 0, agi: 0, dex: 0, int: 0, wis: 0, cha: 0,
    };
    RESISTS.forEach(([k]) => (t[k] = 0));
    // base
    STATS.forEach((s) => (t[s] += Number(build.base[s] || 0)));
    // items
    Object.values(build.slots).forEach((title) => {
      const it = byTitle.get(title);
      if (!it) return;
      ["ac", "hp", "mana", "weight", ...STATS].forEach((k) => { if (it[k]) t[k] += Number(it[k]); });
      RESISTS.forEach(([k]) => { if (it[k]) t[k] += Number(it[k]); });
    });
    // trait bonuses
    TRAIT_SLOTS.forEach(([cat]) => {
      const name = build.traits[cat];
      if (!name) return;
      const tr = (TRAITS[cat] || []).find((x) => x.name === name);
      if (tr && tr.bonus) for (const [k, v] of Object.entries(tr.bonus)) t[k] = (t[k] || 0) + v;
    });
    const racial = build.race && racialFor(build.race);
    if (racial && racial.bonus) for (const [k, v] of Object.entries(racial.bonus)) t[k] = (t[k] || 0) + v;
    return t;
  }

  /* ---------- render ---------- */
  function renderSlots() {
    const wrap = els.slots; wrap.innerHTML = "";
    const eff = effectiveGear().acquired || {};
    SLOTS.forEach(([id, label, code]) => {
      const title = build.slots[id];
      const it = title ? byTitle.get(title) : null;
      const done = !!eff[id];
      const banked = it && ST()?.canBank(it) && ST()?.bankHas(build.server, it.name || title);
      const div = document.createElement("div");
      div.className = "pl-slot" + (it ? " filled" : "") + (done ? " acquired" : "");
      div.innerHTML =
        `<span class="pl-slot-label">${label}</span>` +
        (it
          ? `<a class="pl-slot-item" href="${wikiUrl(it.title)}" target="_blank" rel="noopener">${it.name || it.title}</a>` +
            (build.gearIntent !== "owned" ? `<label class="pl-slot-acq" title="Acquired"><input type="checkbox" data-acq="${id}" ${done ? "checked" : ""}></label>` : "") +
            (banked ? `<span class="pl-bank-tag">Bank</span>` : "") +
            `<button class="pl-slot-clear" data-clear="${id}">✕</button>`
          : `<span class="pl-slot-empty">+ add</span>`);
      div.dataset.slot = id; div.dataset.code = code;
      div.onclick = (e) => {
        if (e.target.dataset.clear) { delete build.slots[id]; delete build.acquired[id]; renderAll(); return; }
        if (e.target.dataset.acq != null) return;
        if (e.target.classList.contains("pl-slot-item")) return;
        openPicker(id, code, label);
      };
      wrap.appendChild(div);
    });
    wrap.querySelectorAll("[data-acq]").forEach((cb) =>
      cb.addEventListener("change", () => {
        build.acquired[cb.dataset.acq] = cb.checked;
        renderSlots(); renderBank();
      }));
  }

  function renderStats() {
    const totals = computeTotals();
    const pi = pointsInfo();
    const tbl = els.stats;
    let header = "<tr><th>Stat</th><th>Base</th><th>Gear+Traits</th><th>Total</th></tr>";
    if (pi) {
      const cls = pi.remaining < 0 ? "over" : "";
      header = `<tr><td colspan="4" class="pl-points ${cls}">Points remaining: <strong>${pi.remaining}</strong> / ${pi.total}` +
        (pi.remaining < 0 ? " (over budget)" : "") + `</td></tr>` + header;
    } else if (build.race && build.cls) {
      header = `<tr><td colspan="4" class="pl-points over">No starting stats for this combination — enter base values manually.</td></tr>` + header;
    }
    tbl.innerHTML = header;
    STATS.forEach((s) => {
      const base = Number(build.base[s] || 0);
      const total = totals[s];
      const bonus = total - base;
      const maxAttr = pi ? ` max="${pi.max[s] ?? ""}"` : "";
      const minAttr = pi ? ` min="${pi.current[s] ?? 0}"` : ` min="0"`;
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td>${s.toUpperCase()}</td>` +
        `<td><input type="number" data-base="${s}" value="${base}"${minAttr}${maxAttr}></td>` +
        `<td class="num ${bonus ? "pos" : ""}">${bonus ? "+" + bonus : ""}</td>` +
        `<td class="num strong">${total}</td>`;
      tbl.appendChild(tr);
    });
    tbl.querySelectorAll("[data-base]").forEach((inp) =>
      inp.addEventListener("input", () => {
        let v = Number(inp.value || 0);
        const s = inp.dataset.base;
        const e = baseEntry();
        if (e) {
          const lo = Number((e.current || {})[s] || 0);
          const hi = Number((e.max || {})[s] || Infinity);
          if (v < lo) v = lo;
          if (v > hi) v = hi;
        }
        build.base[s] = v;
        renderTotals(); renderStats();
        const again = els.stats.querySelector(`[data-base="${s}"]`);
        if (again) again.focus();
      }));
  }

  function renderTraits() {
    const wrap = els.traits; wrap.innerHTML = "";
    TRAIT_SLOTS.forEach(([cat, label]) => {
      const opts = traitOptions(cat);
      const row = document.createElement("label");
      row.className = "pl-trait";
      const cur = build.traits[cat] || "";
      row.innerHTML = `<span>${label}</span>`;
      const sel = document.createElement("select");
      sel.innerHTML = `<option value="">— none —</option>` +
        opts.map((t) => `<option value="${t.name.replace(/"/g, "&quot;")}"${t.name === cur ? " selected" : ""}>${t.name}</option>`).join("");
      sel.onchange = () => { build.traits[cat] = sel.value; renderTraits(); renderTotals(); };
      row.appendChild(sel);
      const tr = opts.find((t) => t.name === cur);
      if (tr) { const d = document.createElement("div"); d.className = "pl-trait-desc"; d.textContent = tr.desc; row.appendChild(d); }
      wrap.appendChild(row);
    });
    const racial = build.race && racialFor(build.race);
    els.racial.innerHTML = racial
      ? `<div class="pl-racial-box"><span class="pl-racial-tag">Racial (auto)</span> <a href="${wikiUrl(racial.name)}" target="_blank" rel="noopener">${racial.name}</a><div class="pl-trait-desc">${racial.desc}</div></div>`
      : (build.race ? `<div class="pl-racial-box muted">No racial combat ability listed for ${RACE_NAMES[build.race] || build.race}.</div>` : "");
  }

  function renderTotals() {
    const t = computeTotals();
    const tbl = els.totals;
    const row = (k, v) => `<tr><td>${k}</td><td class="num strong">${v}</td></tr>`;
    let html = row("Armor Class", t.ac) + row("HP", t.hp) + row("Mana", t.mana) + row("Weight", (t.weight || 0).toFixed(1));
    STATS.forEach((s) => (html += row(s.toUpperCase(), t[s])));
    const anyRes = RESISTS.some(([k]) => t[k]);
    if (anyRes) { html += `<tr class="sep"><td colspan="2">Resists</td></tr>`; RESISTS.forEach(([k, label]) => { if (t[k]) html += row(label, t[k]); }); }
    tbl.innerHTML = html;

    const filled = Object.keys(build.slots).length;
    els.detail.innerHTML = `<div class="pl-summary">${filled}/${SLOTS.length} slots equipped` +
      (build.race ? ` · ${RACE_NAMES[build.race] || build.race}` : "") +
      (build.cls ? ` ${CLASS_NAMES[build.cls] || build.cls}` : "") + `</div>`;
  }

  function renderHeader() {
    els.charName.value = build.charName || "";
    els.gearName.value = build.gearName || "";
    if (els.level) els.level.value = build.level ?? "";
    if (els.server) els.server.value = build.server || "Default";
    if (els.intent) els.intent.value = build.gearIntent || "desired";
    els.race.value = build.race || "";
    setClassOptions(build.race);
    renderBreadcrumb();
    refreshCharList();
    refreshGearList();
    renderBank();
  }

  function renderBreadcrumb() {
    if (!els.breadcrumb) return;
    const intent = ST()?.INTENT_LABEL[build.gearIntent] || build.gearIntent || "";
    els.breadcrumb.innerHTML =
      `<span class="muted">${build.server || "Default"}</span> › ` +
      `<strong>${build.charName || "No character"}</strong>` +
      (build.level != null ? ` <span class="pl-lv">Lv ${build.level}</span>` : "") +
      ` › <em>${build.gearName || "No gear set"}</em>` +
      (intent ? ` <span class="intent-badge ${build.gearIntent}">${intent}</span>` : "");
  }

  function renderBank() {
    if (!els.bank) return;
    const server = build.server || "Default";
    const bank = ST()?.getBank(server) || {};
    const keys = Object.keys(bank).sort();
    els.bank.innerHTML = keys.length
      ? keys.map((k) => `<span class="bank-item">${k} <button data-bank-rm="${k.replace(/"/g, "&quot;")}">✕</button></span>`).join("")
      : `<span class="muted">No shared-bank items on ${server}. Mark droppable loot below.</span>`;
    els.bank.querySelectorAll("[data-bank-rm]").forEach((b) =>
      b.onclick = () => { ST().bankRemove(server, b.dataset.bankRm); renderBank(); renderSlots(); });
    if (els.bankAdd) {
      els.bankAdd.onclick = () => {
        const name = prompt("Item name in shared bank (droppable only):");
        if (!name) return;
        const it = byTitle.get(name) || [...byTitle.values()].find((x) => x.name === name);
        if (it?.nodrop) return alert("No Drop items cannot go in the shared bank.");
        ST().bankAdd(server, it?.name || name, it);
        renderBank(); renderSlots();
      };
    }
  }

  function renderAll() { renderSlots(); renderStats(); renderTraits(); renderTotals(); }

  /* ---------- item picker (sortable, filterable) ---------- */
  const ratioOf = (it) => (it.dmg && it.delay ? +(it.dmg / it.delay).toFixed(3) : null);
  const PICK_COLS = [
    { k: "name", label: "Name", text: true },
    { k: "acq", label: "Acq", acq: true },
    { k: "ac", label: "AC" },
    { k: "dmg", label: "Dmg" },
    { k: "delay", label: "Dly" },
    { k: "ratio", label: "Ratio", calc: ratioOf },
    { k: "str", label: "STR" }, { k: "sta", label: "STA" }, { k: "agi", label: "AGI" },
    { k: "dex", label: "DEX" }, { k: "int", label: "INT" }, { k: "wis", label: "WIS" }, { k: "cha", label: "CHA" },
    { k: "hp", label: "HP" }, { k: "mana", label: "Mana" }, { k: "weight", label: "Wt" },
  ];
  const RANGE_KEYS = ["ac", "dmg", "delay", "ratio", "str", "sta", "agi", "dex", "int", "wis", "cha", "hp", "mana"];
  const colVal = (it, col) => {
    if (col.acq) return ACQ()?.acqInfo(it)?.label || "—";
    return col.calc ? col.calc(it) : it[col.k];
  };
  const acqSortKey = (it) => ACQ()?.acqInfo(it)?.sortKey ?? 99999;
  const numVal = (it, k) => {
    if (k === "acq") return acqSortKey(it);
    const col = PICK_COLS.find((c) => c.k === k);
    const v = col && col.calc ? col.calc(it) : it[k];
    return v == null ? 0 : Number(v);
  };

  let pickState = { code: "", sort: [{ k: "name", dir: 1 }], q: "", ranges: {} };

  function openPicker(slotId, code, label) {
    pickerSlot = slotId;
    pickState = { code, sort: weaponSlot(code) ? [{ k: "ratio", dir: -1 }] : [{ k: "ac", dir: -1 }], q: "", ranges: {} };
    els.pickerTitle.textContent = `${label} — pick item` + (build.cls ? ` (${CLASS_NAMES[build.cls] || build.cls})` : "");
    els.picker.classList.remove("hidden");
    renderPicker();
  }
  function weaponSlot(code) { return ["PRIMARY", "SECONDARY", "RANGED"].includes(code); }
  function closePicker() { els.picker.classList.add("hidden"); pickerSlot = null; }

  function pickerCandidates() {
    let list = ITEMS.filter((it) => itemSlots(it).includes(pickState.code) && usableBy(it, build.cls));
    if (pickState.q) { const q = pickState.q.toLowerCase(); list = list.filter((it) => String(it.name || "").toLowerCase().includes(q)); }
    for (const [k, r] of Object.entries(pickState.ranges)) {
      if (r.min != null) list = list.filter((it) => numVal(it, k) >= r.min);
      if (r.max != null) list = list.filter((it) => numVal(it, k) <= r.max);
    }
    list.sort((a, b) => {
      for (const s of pickState.sort) {
        const col = PICK_COLS.find((c) => c.k === s.k);
        let cmp;
        if (col && col.text) cmp = String(colVal(a, col) || "").localeCompare(String(colVal(b, col) || ""));
        else cmp = numVal(a, s.k) - numVal(b, s.k);
        if (cmp) return cmp * s.dir;
      }
      return 0;
    });
    return list;
  }

  function toggleSort(k, additive) {
    const existing = pickState.sort.find((s) => s.k === k);
    if (additive) {
      if (existing) existing.dir *= -1;
      else pickState.sort.push({ k, dir: k === "name" ? 1 : -1 });
    } else {
      if (existing && pickState.sort.length === 1) existing.dir *= -1;
      else pickState.sort = [{ k, dir: k === "name" ? 1 : -1 }];
    }
    renderPicker();
  }

  function renderPicker() {
    const list = pickerCandidates();
    const sortChips = pickState.sort.map((s, i) =>
      `<span class="pl-sortchip">${i ? "› " : ""}${(PICK_COLS.find((c) => c.k === s.k) || {}).label} ${s.dir < 0 ? "↓" : "↑"}` +
      `<button data-rmsort="${s.k}">✕</button></span>`).join("");
    const rangeInputs = RANGE_KEYS.map((k) => {
      const col = PICK_COLS.find((c) => c.k === k); const r = pickState.ranges[k] || {};
      return `<label class="pl-range"><span>${col.label}</span>` +
        `<input type="number" data-rmin="${k}" placeholder="min" value="${r.min ?? ""}">` +
        `<input type="number" data-rmax="${k}" placeholder="max" value="${r.max ?? ""}"></label>`;
    }).join("");
    const head = PICK_COLS.map((c) => {
      const s = pickState.sort.find((x) => x.k === c.k);
      const cls = "pl-th" + (s ? " sorted" + (s.dir < 0 ? " desc" : "") : "") + (c.text ? " txt" : "");
      return `<th class="${cls}" data-sort="${c.k}">${c.label}</th>`;
    }).join("");
    const rows = list.slice(0, 500).map((it) => {
      const tier = ACQ()?.acqTier(build.level, ACQ()?.acqInfo(it)?.level) || "";
      const tds = PICK_COLS.map((c) => {
        if (c.text) return `<td class="pl-td-name">${it.name || it.title}</td>`;
        if (c.acq) return `<td class="pl-td-acq ${tier}">${colVal(it, c)}</td>`;
        const v = colVal(it, c);
        return `<td class="num">${v == null || v === 0 ? "" : v}</td>`;
      }).join("");
      return `<tr class="${tier}" data-title="${(it.title || "").replace(/"/g, "&quot;")}">${tds}</tr>`;
    }).join("");

    els.pickerList.innerHTML =
      `<div class="pl-pickbar">
         <input id="pl-pq" type="search" placeholder="search name…" value="${pickState.q.replace(/"/g, "&quot;")}">
         <button id="pl-filters-toggle" class="pl-ftoggle">Filters</button>
         <span class="pl-sortchips">Sort: ${sortChips || "—"}</span>
         <span class="pl-count">${list.length} items${list.length > 500 ? " (top 500)" : ""}</span>
       </div>
       <div id="pl-rangewrap" class="pl-rangewrap hidden">${rangeInputs}</div>
       <div class="pl-picktablewrap"><table class="pl-picktable"><thead><tr>${head}</tr></thead><tbody>${rows || `<tr><td colspan="${PICK_COLS.length}" class="pl-pick-empty">No matching items.</td></tr>`}</tbody></table></div>`;

    const pq = document.getElementById("pl-pq");
    pq.oninput = () => { pickState.q = pq.value; renderPickerKeepFocus(); };
    document.getElementById("pl-filters-toggle").onclick = () => document.getElementById("pl-rangewrap").classList.toggle("hidden");
    els.pickerList.querySelectorAll(".pl-th").forEach((th) =>
      th.onclick = (e) => toggleSort(th.dataset.sort, e.shiftKey));
    els.pickerList.querySelectorAll("[data-rmsort]").forEach((b) =>
      b.onclick = () => { pickState.sort = pickState.sort.filter((s) => s.k !== b.dataset.rmsort); if (!pickState.sort.length) pickState.sort = [{ k: "name", dir: 1 }]; renderPicker(); });
    els.pickerList.querySelectorAll("[data-rmin]").forEach((inp) =>
      inp.oninput = () => { setRange(inp.dataset.rmin, "min", inp.value); });
    els.pickerList.querySelectorAll("[data-rmax]").forEach((inp) =>
      inp.oninput = () => { setRange(inp.dataset.rmax, "max", inp.value); });
    els.pickerList.querySelectorAll("tbody tr[data-title]").forEach((tr) =>
      tr.onclick = () => { build.slots[pickerSlot] = tr.dataset.title; closePicker(); renderAll(); });
  }
  function renderPickerKeepFocus() {
    renderPicker();
    const pq = document.getElementById("pl-pq"); if (pq) { pq.focus(); pq.selectionStart = pq.value.length; }
  }
  function setRange(k, which, val) {
    const r = pickState.ranges[k] || (pickState.ranges[k] = {});
    r[which] = val === "" ? null : Number(val);
    if (r.min == null && r.max == null) delete pickState.ranges[k];
    // keep the range panel open; only re-filter the table
    const open = !document.getElementById("pl-rangewrap").classList.contains("hidden");
    renderPicker();
    if (open) document.getElementById("pl-rangewrap").classList.remove("hidden");
  }

  /* ---------- persistence (v2 store) ---------- */
  function loadContext(charId, gearId) {
    if (charId) {
      const c = ST().getCharacter(charId);
      if (c) {
        build.characterId = c.id;
        build.charName = c.name;
        build.level = c.level;
        build.server = c.server || "Default";
        build.race = c.race || "";
        build.cls = c.cls || "";
        build.base = Object.assign(Object.fromEntries(STATS.map((s) => [s, 0])), c.base || {});
        build.traits = Object.assign({ major_combat: "", minor_combat: "", major_noncombat: "", minor_noncombat: "" }, c.traits || {});
      }
    }
    const gid = gearId || (charId && ST().getCharacter(charId)?.activeGearSetId);
    if (gid) {
      const g = ST().getGearSet(gid);
      if (g) applyGearFromStore(g);
    }
    ST().setSession({ characterId: build.characterId, gearSetId: build.gearSetId });
    renderHeader(); renderAll();
  }

  function applyGearFromStore(g) {
    if (g.cls && build.cls && g.cls !== build.cls &&
      !confirm(`This gear set is for ${CLASS_NAMES[g.cls] || g.cls} but your character is ${CLASS_NAMES[build.cls] || build.cls}. Apply anyway?`)) return;
    build.gearSetId = g.id;
    build.gearName = g.name || build.gearName;
    build.gearIntent = g.intent || "desired";
    build.slots = JSON.parse(JSON.stringify(g.slots || {}));
    build.acquired = JSON.parse(JSON.stringify(g.acquired || {}));
  }

  function refreshCharList() {
    const chars = ST().listCharacters().sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    els.charLoad.innerHTML = `<option value="">Load character…</option>` +
      chars.map((c) => `<option value="${c.id}"${c.id === build.characterId ? " selected" : ""}>${c.name} (${c.server})</option>`).join("");
  }
  function refreshGearList() {
    const linked = build.characterId ? ST().listGearSets({ characterId: build.characterId }) : ST().listGearSets();
    const all = linked.length ? linked : ST().listGearSets();
    els.gearLoad.innerHTML = `<option value="">Load gear set…</option>` +
      all.map((g) => {
        const off = build.cls && g.cls && g.cls !== build.cls ? ` [${CLASS_NAMES[g.cls] || g.cls}]` : "";
        const tag = ST().INTENT_LABEL[g.intent] || g.intent;
        return `<option value="${g.id}"${g.id === build.gearSetId ? " selected" : ""}>${g.name} (${tag})${off}</option>`;
      }).join("");
  }

  function saveChar() {
    build.charName = els.charName.value.trim();
    if (!build.charName) { alert("Name the character first."); els.charName.focus(); return; }
    build.level = els.level?.value ? Number(els.level.value) : null;
    build.server = els.server?.value?.trim() || "Default";
    ST().addServer(build.server);
    const existing = build.characterId ? ST().getCharacter(build.characterId) : null;
    const c = ST().saveCharacter(Object.assign(existing || charPart(), {
      id: build.characterId || undefined,
      name: build.charName,
      server: build.server,
      level: build.level,
      race: build.race,
      cls: build.cls,
      base: build.base,
      traits: build.traits,
      gearSetIds: existing?.gearSetIds || (build.gearSetId ? [build.gearSetId] : []),
      activeGearSetId: build.gearSetId || existing?.activeGearSetId,
      targetGearSetId: existing?.targetGearSetId || (build.gearIntent === "desired" ? build.gearSetId : null),
      guildId: existing?.guildId || null,
    }));
    build.characterId = c.id;
    if (build.gearSetId) ST().linkGearToCharacter(build.gearSetId, c.id);
    ST().setSession({ characterId: c.id });
    refreshCharList(); flash(els.charSave, "Saved");
    renderBreadcrumb();
  }

  function loadChar(id) {
    const c = ST().getCharacter(id); if (!c) return;
    loadContext(c.id, c.activeGearSetId);
  }

  function delChar() {
    if (!build.characterId) return;
    if (confirm("Delete this character?")) {
      ST().deleteCharacter(build.characterId);
      build = newBuild();
      renderHeader(); renderAll();
    }
  }

  function newChar() {
    build.characterId = null;
    build.charName = ""; build.level = null; build.race = ""; build.cls = "";
    build.base = Object.fromEntries(STATS.map((s) => [s, 0]));
    build.traits = { major_combat: "", minor_combat: "", major_noncombat: "", minor_noncombat: "" };
    renderHeader(); renderAll();
  }

  function saveGear() {
    build.gearName = els.gearName.value.trim();
    if (!build.gearName) { alert("Name the gear set first."); els.gearName.focus(); return; }
    build.gearIntent = els.intent?.value || "desired";
    build.server = els.server?.value?.trim() || build.server || "Default";
    const existing = build.gearSetId ? ST().getGearSet(build.gearSetId) : null;
    const g = ST().saveGearSet(Object.assign(existing || gearPart(), {
      id: build.gearSetId || undefined,
      name: build.gearName,
      cls: build.cls,
      server: build.server,
      intent: build.gearIntent,
      slots: build.slots,
      acquired: build.acquired,
      linkedCharacterIds: build.characterId ? [...new Set([...(existing?.linkedCharacterIds || []), build.characterId])] : (existing?.linkedCharacterIds || []),
    }));
    build.gearSetId = g.id;
    if (build.characterId) {
      ST().linkGearToCharacter(g.id, build.characterId);
      const c = ST().getCharacter(build.characterId);
      if (c && build.gearIntent === "desired") { c.targetGearSetId = g.id; ST().saveCharacter(c); }
    }
    ST().setSession({ gearSetId: g.id });
    refreshGearList(); flash(els.gearSave, "Saved");
    renderBreadcrumb();
  }

  function applyGear(g) {
    applyGearFromStore(typeof g === "string" ? ST().getGearSet(g) : g);
    renderHeader(); renderAll();
  }
  function loadGear(id) {
    const g = ST().getGearSet(id);
    if (g) applyGear(g);
  }
  function delGear() {
    if (!build.gearSetId) return;
    if (confirm("Delete this gear set?")) {
      ST().deleteGearSet(build.gearSetId);
      build.gearSetId = null; build.gearName = ""; build.slots = {}; build.acquired = {};
      renderHeader(); renderAll();
    }
  }
  function newGear() {
    build.gearSetId = null; build.gearName = ""; build.slots = {}; build.acquired = {};
    build.gearIntent = "desired";
    renderHeader(); renderAll();
  }

  const enc = (o) => btoa(unescape(encodeURIComponent(JSON.stringify(o))));
  const dec = (s) => JSON.parse(decodeURIComponent(escape(atob(s))));
  function shareGear() {
    const payload = { name: build.gearName, cls: build.cls, intent: build.gearIntent, slots: build.slots, acquired: build.acquired };
    const url = location.origin + location.pathname + "#gear=" + enc(payload);
    navigator.clipboard?.writeText(url).then(() => flash(els.gearShare, "Link copied")).catch(() => prompt("Share URL:", url));
  }
  function exportGear() {
    const blob = new Blob([JSON.stringify(gearPart(), null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = (build.gearName || "gearset") + ".json"; a.click();
    URL.revokeObjectURL(a.href);
  }
  function importGear() {
    const raw = prompt("Paste gear-set JSON or share link:");
    if (!raw) return;
    try {
      const m = raw.match(/gear=([^&\s]+)/);
      const g = m ? dec(m[1]) : JSON.parse(raw);
      g.intent = g.intent || "template";
      const saved = ST().saveGearSet(Object.assign(g, { id: undefined, server: build.server }));
      applyGear(saved);
    } catch { alert("Invalid gear set."); }
  }
  function maybeLoadFromHash() {
    const g = location.hash.match(/gear=([^&]+)/);
    if (g) {
      try {
        const data = dec(g[1]);
        data.intent = data.intent || "template";
        applyGear(ST().saveGearSet(Object.assign(data, { id: undefined })));
        return true;
      } catch {}
    }
    return false;
  }

  function flash(btn, msg) { const o = btn.textContent; btn.textContent = msg; setTimeout(() => (btn.textContent = o), 1200); }

  /* ---------- init ---------- */
  function init() {
    els.charName = document.getElementById("pl-char-name");
    els.gearName = document.getElementById("pl-gear-name");
    els.race = document.getElementById("pl-race");
    els.class = document.getElementById("pl-class");
    els.slots = document.getElementById("pl-slots");
    els.stats = document.getElementById("pl-stats");
    els.traits = document.getElementById("pl-traits");
    els.racial = document.getElementById("pl-racial");
    els.totals = document.getElementById("pl-totals");
    els.detail = document.getElementById("pl-detail");
    els.charLoad = document.getElementById("pl-char-load");
    els.charSave = document.getElementById("pl-char-save");
    els.charDel = document.getElementById("pl-char-del");
    els.gearLoad = document.getElementById("pl-gear-load");
    els.gearSave = document.getElementById("pl-gear-save");
    els.gearDel = document.getElementById("pl-gear-del");
    els.gearShare = document.getElementById("pl-gear-share");
    els.gearExport = document.getElementById("pl-gear-export");
    els.gearImport = document.getElementById("pl-gear-import");
    els.picker = document.getElementById("pl-picker");
    els.pickerTitle = document.getElementById("pl-picker-title");
    els.pickerList = document.getElementById("pl-picker-list");
    els.breadcrumb = document.getElementById("pl-breadcrumb");
    els.level = document.getElementById("pl-level");
    els.server = document.getElementById("pl-server");
    els.intent = document.getElementById("pl-intent");
    els.bank = document.getElementById("pl-bank");
    els.bankAdd = document.getElementById("pl-bank-add");

    if (els.server) {
      els.server.innerHTML = ST().listServers().map((s) => `<option value="${s}">${s}</option>`).join("");
      els.server.onchange = () => { build.server = els.server.value; renderBank(); renderSlots(); };
    }
    if (els.level) els.level.oninput = () => { build.level = els.level.value ? Number(els.level.value) : null; renderBreadcrumb(); };
    if (els.intent) els.intent.onchange = () => { build.gearIntent = els.intent.value; renderBreadcrumb(); };

    fillSelect(els.race, Object.entries(RACE_NAMES).sort((a, b) => a[1].localeCompare(b[1])), "Any race");
    fillSelect(els.class, Object.entries(CLASS_NAMES).sort((a, b) => a[1].localeCompare(b[1])), "Any class");

    els.race.onchange = () => { build.race = els.race.value; setClassOptions(build.race); applyBaseline(); renderTraits(); renderStats(); renderTotals(); refreshGearList(); };
    els.class.onchange = () => { build.cls = els.class.value; applyBaseline(); renderTraits(); renderStats(); renderTotals(); refreshGearList(); };
    els.charName.oninput = () => { build.charName = els.charName.value; };
    els.gearName.oninput = () => { build.gearName = els.gearName.value; };
    els.charLoad.onchange = () => { if (els.charLoad.value) loadChar(els.charLoad.value); };
    els.charSave.onclick = saveChar;
    els.charDel.onclick = delChar;
    document.getElementById("pl-char-new").onclick = newChar;
    els.gearLoad.onchange = () => { if (els.gearLoad.value) loadGear(els.gearLoad.value); };
    els.gearSave.onclick = saveGear;
    els.gearDel.onclick = delGear;
    document.getElementById("pl-gear-new").onclick = newGear;
    els.gearShare.onclick = shareGear;
    els.gearExport.onclick = exportGear;
    els.gearImport.onclick = importGear;
    document.getElementById("pl-picker-close").onclick = closePicker;
    els.picker.onclick = (e) => { if (e.target === els.picker) closePicker(); };
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePicker(); });

    // expose for the Acquire tab
    window.MNM_planner = {
      getBuild: () => {
        const eff = effectiveGear();
        return Object.assign({}, build, eff, {
          name: [build.charName, build.gearName].filter(Boolean).join(" · "),
          slots: build.slots,
          acquired: eff.acquired,
        });
      },
      slotList: () => SLOTS,
      raceName: (r) => RACE_NAMES[r] || r,
      className: (c) => CLASS_NAMES[c] || c,
      charPart, gearPart, loadContext, applyBaseline,
      getCharacter: (id) => ST().getCharacter(id),
      getGearSet: (id) => ST().getGearSet(id),
      listCharacters: () => ST().listCharacters(),
      listGearSets: (f) => ST().listGearSets(f),
    };

    const fromHash = maybeLoadFromHash();
    const sess = ST().getSession();
    if (!fromHash && sess.characterId) loadContext(sess.characterId, sess.gearSetId);
    else { renderHeader(); renderAll(); }

    // lazy-init when planner tab opened (data already ready, just ensure render)
    document.querySelector('.tab[data-tab="planner"]').addEventListener("click", () => { renderAll(); });
    if (fromHash) document.querySelector('.tab[data-tab="planner"]').click();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
