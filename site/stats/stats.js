/* Local play stats dashboard — reads window.MNM_LEDGER_STATS from ledger-stats.js */
(function () {
  const RAW = window.MNM_LEDGER_STATS;
  const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;");

  const state = {
    server: "",
    character: "",
    drill: { view: "zones", zone: null, mob: null },
    session: { start: null, end: null, viewStart: null, viewEnd: null, sig: null },
  };

  function filterRow(row) {
    if (state.server && row.server !== state.server) return false;
    if (state.character && row.character !== state.character) return false;
    return true;
  }

  function filteredKills() {
    return (RAW?.kills || []).filter(filterRow);
  }

  function filteredLoot() {
    return (RAW?.loot || []).filter(filterRow);
  }

  function filteredLevelups() {
    return (RAW?.levelups || []).filter((lu) => {
      if (state.server && lu.server !== state.server) return false;
      if (state.character && lu.character !== state.character && lu.observer !== state.character) return false;
      return true;
    });
  }

  function killsByDay(kills) {
    const byDay = new Map();
    for (const k of kills) {
      const day = k.day || (k.at || "").slice(0, 10) || "?";
      byDay.set(day, (byDay.get(day) || 0) + 1);
    }
    return [...byDay.entries()]
      .map(([day, count]) => ({ day, kills: count }))
      .sort((a, b) => a.day.localeCompare(b.day));
  }

  function killsByZone(kills) {
    const byZone = new Map();
    for (const k of kills) {
      const zone = k.zone || "?";
      byZone.set(zone, (byZone.get(zone) || 0) + 1);
    }
    return [...byZone.entries()]
      .map(([zone, count]) => ({ zone, kills: count }))
      .sort((a, b) => b.kills - a.kills);
  }

  function mobsInZone(kills, zone) {
    const counts = new Map();
    const coin = new Map();
    for (const k of kills) {
      if ((k.zone || "?") !== zone) continue;
      const name = k.mob_name || "?";
      counts.set(name, (counts.get(name) || 0) + 1);
      coin.set(name, (coin.get(name) || 0) + (k.copper || 0));
    }
    return [...counts.entries()]
      .map(([name, kills]) => ({
        name,
        kills,
        coin_avg: kills ? Math.round((coin.get(name) || 0) / kills) : 0,
      }))
      .sort((a, b) => b.kills - a.kills);
  }

  function lootForMob(loot, zone, mobName) {
    const mobCf = mobName.toLowerCase();
    const items = new Map();
    let totalQty = 0;
    for (const row of loot) {
      if (row.own === false) continue;
      if ((row.zone || "?") !== zone) continue;
      if ((row.mob_name || "").toLowerCase() !== mobCf) continue;
      const key = row.item_name || "?";
      const prev = items.get(key) || { item_name: key, qty: 0, events: 0 };
      prev.qty += row.qty || 1;
      prev.events += 1;
      items.set(key, prev);
      totalQty += row.qty || 1;
    }
    return [...items.values()].sort((a, b) => b.qty - a.qty).map((it) => ({
      ...it,
      pct: totalQty ? Math.round((100 * it.qty) / totalQty) : null,
    }));
  }

  function topMobs(kills) {
    const counts = new Map();
    const coin = new Map();
    const zones = new Map();
    for (const k of kills) {
      const name = k.mob_name || "?";
      counts.set(name, (counts.get(name) || 0) + 1);
      coin.set(name, (coin.get(name) || 0) + (k.copper || 0));
      const z = k.zone || "?";
      if (!zones.has(name)) zones.set(name, new Set());
      zones.get(name).add(z);
    }
    return [...counts.entries()]
      .map(([name, kill_count]) => ({
        name,
        kill_count,
        coin_avg: kill_count ? Math.round((coin.get(name) || 0) / kill_count) : 0,
        zones: [...(zones.get(name) || [])].sort(),
      }))
      .sort((a, b) => b.kill_count - a.kill_count)
      .slice(0, 35);
  }

  function partyLootRows(loot) {
    return loot
      .filter((r) => r.party_loot || (r.looter && r.owner && r.looter !== r.owner))
      .sort((a, b) => (b.at || "").localeCompare(a.at || ""))
      .slice(0, 80);
  }

  function fillTable(tbody, rows, fn) {
    tbody.innerHTML = rows.length ? rows.map(fn).join("") : "<tr><td colspan='99' class='muted'>No data</td></tr>";
  }

  function fmtCoinShort(cp) {
    cp = Math.round(cp || 0);
    if (!cp) return "—";
    // 100 per tier: 100c = 1s, 100s = 1g, 100g = 1p.
    const pp = Math.floor(cp / 1000000);
    const gp = Math.floor((cp % 1000000) / 10000);
    const sp = Math.floor((cp % 10000) / 100);
    const c = cp % 100;
    return [pp && `${pp}p`, gp && `${gp}g`, sp && `${sp}s`, c && `${c}c`].filter(Boolean).join(" ") || "0c";
  }

  function renderLineChart(container, rows) {
    if (!rows.length) {
      container.innerHTML = "<p class='muted'>No data</p>";
      return;
    }
    const W = 480;
    const H = 160;
    const pad = { l: 36, r: 12, t: 12, b: 28 };
    const innerW = W - pad.l - pad.r;
    const innerH = H - pad.t - pad.b;
    const maxY = Math.max(...rows.map((r) => r.kills), 1);
    const pts = rows.map((r, i) => {
      const x = pad.l + (rows.length === 1 ? innerW / 2 : (i / (rows.length - 1)) * innerW);
      const y = pad.t + innerH - (r.kills / maxY) * innerH;
      return { x, y, ...r };
    });
    const line = pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
    const tickStep = Math.max(1, Math.ceil(rows.length / 6));
    const xLabels = pts
      .filter((_, i) => i % tickStep === 0 || i === pts.length - 1)
      .map((p) => `<text x="${p.x}" y="${H - 6}" text-anchor="middle" class="chart-label">${esc(p.day.slice(5))}</text>`)
      .join("");
    const yTicks = [0, Math.round(maxY / 2), maxY]
      .filter((v, i, a) => a.indexOf(v) === i)
      .map((v) => {
        const y = pad.t + innerH - (v / maxY) * innerH;
        return `<line x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}" class="grid-line"/>
          <text x="${pad.l - 6}" y="${y + 4}" text-anchor="end" class="chart-label">${v}</text>`;
      })
      .join("");
    const dots = pts
      .map(
        (p) =>
          `<circle cx="${p.x}" cy="${p.y}" r="3" class="chart-dot"><title>${esc(p.day)}: ${p.kills} kills</title></circle>`
      )
      .join("");
    container.innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="chart-svg" role="img">${yTicks}<polyline points="${line}" class="chart-line"/>${dots}${xLabels}</svg>`;
  }

  function renderZoneMap(container, kills, zoneMap) {
    const zones = zoneMap?.zones || {};
    const counts = killsByZone(kills);
    const byName = new Map(counts.map((r) => [r.zone, r.kills]));
    const max = Math.max(...counts.map((r) => r.kills), 1);
    const region = zoneMap?.region || "Szuur";
    const boxes = Object.entries(zones)
      .map(([name, box]) => {
        const n = byName.get(name) || 0;
        const intensity = n ? 0.25 + 0.75 * (n / max) : 0.08;
        const title = `${name}: ${n} kills`;
        return `<div class="zone-cell" style="left:${box.x * 100}%;top:${box.y * 100}%;width:${box.w * 100}%;height:${box.h * 100}%;--heat:${intensity}" title="${esc(title)}"><span>${esc(name)}</span><em>${n || ""}</em></div>`;
      })
      .join("");
    const unmapped = counts.filter((r) => !zones[r.zone]);
    const extra =
      unmapped.length > 0
        ? `<div class="zone-unmapped muted">Unmapped: ${unmapped.map((r) => `${esc(r.zone)} (${r.kills})`).join(", ")}</div>`
        : "";
    container.innerHTML = `<div class="zone-map-inner" data-region="${esc(region)}">${boxes}</div>${extra}`;
    container.querySelectorAll(".zone-cell").forEach((cell) => {
      const name = cell.querySelector("span")?.textContent;
      if (!name) return;
      cell.style.cursor = "pointer";
      cell.onclick = () => {
        state.drill = { view: "mobs", zone: name, mob: null };
        render();
        document.querySelector(".drill-panel")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      };
    });
  }

  function renderDrill(kills, loot) {
    const content = document.getElementById("drill-content");
    const crumb = document.getElementById("drill-breadcrumb");
    const { view, zone, mob } = state.drill;

    if (view === "zones") {
      crumb.classList.add("hidden");
      const zones = killsByZone(kills);
      content.innerHTML = zones
        .map(
          (z) =>
            `<button type="button" class="drill-row" data-zone="${esc(z.zone)}">
              <span class="label">${esc(z.zone)}</span>
              <span class="num">${z.kills}</span>
            </button>`
        )
        .join("") || "<p class='muted'>No kills</p>";
      content.querySelectorAll("[data-zone]").forEach((btn) => {
        btn.onclick = () => {
          state.drill = { view: "mobs", zone: btn.dataset.zone, mob: null };
          render();
        };
      });
      return;
    }

    crumb.classList.remove("hidden");
    const parts = [
      `<button type="button" data-crumb="zones">Zones</button>`,
      `<button type="button" data-crumb="mobs">${esc(zone)}</button>`,
    ];
    if (view === "loot") parts.push(`<span>${esc(mob)}</span>`);
    crumb.innerHTML = parts.join(" › ");

    crumb.querySelector('[data-crumb="zones"]').onclick = () => {
      state.drill = { view: "zones", zone: null, mob: null };
      render();
    };
    crumb.querySelector('[data-crumb="mobs"]').onclick = () => {
      state.drill = { view: "mobs", zone, mob: null };
      render();
    };

    if (view === "mobs") {
      const mobs = mobsInZone(kills, zone);
      const killCount = mobs.reduce((s, m) => s + m.kills, 0);
      content.innerHTML =
        mobs
          .map(
            (m) =>
              `<button type="button" class="drill-row" data-mob="${esc(m.name)}">
                <span class="label">${esc(m.name)} <small class="muted">${fmtCoinShort(m.coin_avg)}/kill</small></span>
                <span class="num">${m.kills}</span>
              </button>`
          )
          .join("") || "<p class='muted'>No mobs</p>";
      content.querySelectorAll("[data-mob]").forEach((btn) => {
        btn.onclick = () => {
          state.drill = { view: "loot", zone, mob: btn.dataset.mob };
          render();
        };
      });
      return;
    }

    const mobKills = kills.filter((k) => (k.zone || "?") === zone && k.mob_name === mob).length;
    const items = lootForMob(loot, zone, mob);
    content.innerHTML = `<p class="drill-summary">${mobKills} kills · ${items.length} item types</p>
      <div class="tablewrap"><table><thead><tr><th>Item</th><th>Qty</th><th>Events</th><th>% of loot</th><th>Rate/kill</th></tr></thead><tbody>
      ${items
        .map(
          (it) => {
            const href = `../index.html#item=${encodeURIComponent(it.item_name)}`;
            return `<tr><td><a href="${href}">${esc(it.item_name)}</a></td><td>${it.qty}</td><td>${it.events}</td><td>${it.pct ?? "—"}%</td><td>${mobKills ? (it.events / mobKills).toFixed(3) : "—"}</td></tr>`;
          }
        )
        .join("")}
      </tbody></table></div>`;
  }

  function coinSummary() {
    const rows = (RAW.coin || []).filter((c) => {
      if (state.server && c.server !== state.server) return false;
      if (state.character && c.character !== state.character) return false;
      return true;
    });
    return rows.reduce(
      (a, c) => ({
        group_total: a.group_total + (c.group_total || 0),
        my_split: a.my_split + (c.my_split || 0),
        vendor: a.vendor + (c.vendor || 0),
      }),
      { group_total: 0, my_split: 0, vendor: 0 }
    );
  }

  function renderSummary(meta, kills, loot) {
    const s = meta.stats || {};
    const coin = coinSummary();
    const share = coin.group_total ? Math.round((100 * coin.my_split) / coin.group_total) : 0;
    const cards = [
      ["Kills", kills.length],
      ["Group looted", fmtCoinShort(coin.group_total), true],
      [`My split (${share}%)`, fmtCoinShort(coin.my_split), true],
      ["Loot events", loot.length],
      ["Party loot", partyLootRows(loot).length],
      ["Mobs", topMobs(kills).length],
      ["Level-ups", filteredLevelups().length],
    ];
    document.getElementById("summary-cards").innerHTML = cards
      .map(([lbl, val, isStr]) => `<div class="stat-card"><div class="val">${isStr ? esc(val) : Number(val || 0).toLocaleString()}</div><div class="lbl">${lbl}</div></div>`)
      .join("");

    const chars = (meta.characters || []).join(", ") || "—";
    document.getElementById("stats-meta").textContent =
      `Generated ${meta.generated?.slice(0, 19) || "?"} · install ${meta.install_id || "?"} · ${chars}`;
    const parts = [];
    if (state.server) parts.push(state.server);
    if (state.character) parts.push(state.character);
    document.getElementById("filter-summary").textContent = parts.length
      ? `Showing: ${parts.join(" / ")}`
      : "Showing all characters";
  }

  function populateFilters(meta) {
    const serverSel = document.getElementById("filter-server");
    const charSel = document.getElementById("filter-character");
    const servers = meta.servers || [];
    const chars = meta.characters || [];
    serverSel.innerHTML =
      '<option value="">All servers</option>' + servers.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
    charSel.innerHTML =
      '<option value="">All characters</option>' + chars.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
    serverSel.value = state.server;
    charSel.value = state.character;
    serverSel.onchange = () => {
      state.server = serverSel.value;
      render();
    };
    charSel.onchange = () => {
      state.character = charSel.value;
      render();
    };
  }

  async function loadUploadPayload() {
    try {
      const res = await fetch("upload-payload.json");
      if (!res.ok) return null;
      return res.json();
    } catch {
      return null;
    }
  }

  function renderUpload(meta, payload) {
    const el = document.getElementById("upload-status");
    const up = meta.upload || {};
    if (!payload) {
      el.innerHTML = "Upload bundle not found. Run <code>python mine_local.py</code>.";
      return;
    }
    const kb = (JSON.stringify(payload).length / 1024).toFixed(0);
    el.innerHTML = up.configured
      ? `Endpoint configured: <code>${esc(up.endpoint)}</code> · bundle ~${kb} KB`
      : `No upload endpoint configured (set <code>MNM_UPLOAD_URL</code> in config/ledger.env) · bundle ~${kb} KB ready`;
    document.getElementById("upload-preview").textContent = JSON.stringify(
      {
        schema: payload.schema,
        summary: payload.summary,
        batch_id: payload.batch_id,
        characters: payload.characters ? "(included)" : undefined,
        hardcore_profiles: payload.hardcore_profiles
          ? `${payload.hardcore_profiles.length} Magnificent profile(s)`
          : undefined,
      },
      null,
      2
    );

    const btn = document.getElementById("btn-upload");
    btn.disabled = !up.configured;
    btn.title = up.configured ? "POST upload-payload.json to configured endpoint" : "Configure MNM_UPLOAD_URL first";

    document.getElementById("btn-copy-payload").onclick = async () => {
      const copyBtn = document.getElementById("btn-copy-payload");
      await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
      const prev = copyBtn.textContent;
      copyBtn.textContent = "Copied!";
      setTimeout(() => {
        copyBtn.textContent = prev;
      }, 1500);
    };

    btn.onclick = async () => {
      if (!up.endpoint) return;
      btn.disabled = true;
      btn.textContent = "Uploading…";
      try {
        const headers = { "Content-Type": "application/json", "X-MNM-Schema": payload.schema };
        const res = await fetch(up.endpoint, { method: "POST", headers, body: JSON.stringify(payload) });
        btn.textContent = res.ok ? `Uploaded (${res.status})` : `Failed (${res.status})`;
      } catch (e) {
        btn.textContent = "Upload failed";
        console.error(e);
      } finally {
        setTimeout(() => {
          btn.disabled = false;
          btn.textContent = "Upload to site";
        }, 2500);
      }
    };
  }

  // ---- Session explorer -------------------------------------------------
  const IDLE_MIN = 20;
  const SESSION = { evts: [], domain: [0, 0] };

  const parseTs = (at) => (at ? Date.parse(at) : NaN);
  const pad2 = (n) => String(n).padStart(2, "0");
  function msToInput(ms) {
    const d = new Date(ms);
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
  }
  const inputToMs = (v) => (v ? Date.parse(v) : NaN);
  function clockLabel(ms) {
    const d = new Date(ms);
    return `${pad2(d.getMonth() + 1)}/${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  }

  function filteredCoinEvents() {
    return (RAW?.coin_events || []).filter(filterRow);
  }

  function buildSessionEvents() {
    const out = [];
    for (const k of filteredKills()) {
      const t = parseTs(k.at);
      if (t === t) out.push({ t, kind: "kill", mob: k.mob_name || "?" });
    }
    for (const c of filteredCoinEvents()) {
      const t = parseTs(c.at);
      if (t === t) out.push({ t, kind: "coin", mine: c.mine || 0, bulk: c.bulk || 0 });
    }
    for (const l of filteredLoot()) {
      const t = parseTs(l.at);
      if (t === t) out.push({ t, kind: "loot", qty: l.qty || 1, own: l.own });
    }
    out.sort((a, b) => a.t - b.t);
    return out;
  }

  function detectSessions(evts) {
    const gap = IDLE_MIN * 60000;
    const out = [];
    let cur = null;
    for (const e of evts) {
      if (!cur || e.t - cur.end > gap) {
        cur = { start: e.t, end: e.t, kills: 0 };
        out.push(cur);
      }
      cur.end = e.t;
      if (e.kind === "kill") cur.kills++;
    }
    return out;
  }

  function windowStats(evts, start, end) {
    let kills = 0,
      lootQty = 0,
      group = 0,
      mine = 0;
    const mobs = new Map();
    for (const e of evts) {
      if (e.t < start || e.t > end) continue;
      if (e.kind === "kill") {
        kills++;
        mobs.set(e.mob, (mobs.get(e.mob) || 0) + 1);
      } else if (e.kind === "loot") {
        if (e.own !== false) lootQty += e.qty;
      } else {
        group += e.bulk;
        mine += e.mine;
      }
    }
    const dur = Math.max(0, end - start);
    const hrs = dur / 3600000;
    return {
      kills,
      lootQty,
      group,
      mine,
      dur,
      killsHr: hrs ? Math.round(kills / hrs) : 0,
      coinHr: hrs ? Math.round(mine / hrs) : 0,
      share: group ? Math.round((100 * mine) / group) : 0,
      mobs: [...mobs.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8),
    };
  }

  function renderSessionPresets(sessions) {
    const el = document.getElementById("session-presets");
    const recent = sessions.slice(-8).reverse();
    const btns = recent
      .map((s) => {
        const active =
          Math.abs(s.start - state.session.start) < 1000 && Math.abs(s.end - state.session.end) < 1000;
        const label = `${clockLabel(s.start)} · ${fmtDur((s.end - s.start) / 1000)} · ${s.kills}k`;
        return `<button type="button" class="session-preset${active ? " active" : ""}" data-start="${s.start}" data-end="${s.end}">${esc(label)}</button>`;
      })
      .join("");
    el.innerHTML = `<button type="button" class="session-preset" data-start="all">All time</button>${btns}`;
    el.querySelectorAll(".session-preset").forEach((b) => {
      b.onclick = () => {
        if (b.dataset.start === "all") {
          state.session.start = SESSION.domain[0];
          state.session.end = SESSION.domain[1];
          state.session.viewStart = SESSION.domain[0];
          state.session.viewEnd = SESSION.domain[1];
        } else {
          const s = +b.dataset.start;
          const e = +b.dataset.end;
          const pad = Math.max(600000, (e - s) * 0.25);
          state.session.start = s;
          state.session.end = e;
          state.session.viewStart = Math.max(SESSION.domain[0], s - pad);
          state.session.viewEnd = Math.min(SESSION.domain[1], e + pad);
        }
        renderSession();
      };
    });
  }

  function renderMiniLine(container, rows) {
    if (!rows.length || rows.every((r) => !r.val)) {
      container.innerHTML = "<p class='muted'>No coin in window</p>";
      return;
    }
    const W = 480,
      H = 160,
      pad = { l: 52, r: 12, t: 12, b: 24 },
      iw = W - pad.l - pad.r,
      ih = H - pad.t - pad.b;
    const maxY = Math.max(...rows.map((r) => r.val), 1);
    const pts = rows.map((r, i) => {
      const x = pad.l + (rows.length === 1 ? iw / 2 : (i / (rows.length - 1)) * iw);
      const y = pad.t + ih - (r.val / maxY) * ih;
      return { x, y };
    });
    const line = pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
    const area = `${pad.l},${pad.t + ih} ${line} ${pad.l + iw},${pad.t + ih}`;
    const yTicks = [0, Math.round(maxY / 2), maxY]
      .filter((v, i, a) => a.indexOf(v) === i)
      .map((v) => {
        const y = pad.t + ih - (v / maxY) * ih;
        return `<line x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}" class="grid-line"/><text x="${pad.l - 6}" y="${y + 4}" text-anchor="end" class="chart-label">${esc(fmtCoinShort(v))}</text>`;
      })
      .join("");
    container.innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="chart-svg" role="img">${yTicks}<polyline points="${area}" fill="rgba(212,175,55,.12)" stroke="none"/><polyline points="${line}" class="chart-line"/></svg>`;
  }

  function renderSessionChart(evts, start, end) {
    const c = document.getElementById("session-chart");
    const dur = end - start;
    if (dur <= 0) {
      c.innerHTML = "<p class='muted'>—</p>";
      return;
    }
    const nb = Math.max(4, Math.min(24, Math.round(dur / 600000)));
    const buckets = new Array(nb).fill(0);
    for (const e of evts) {
      if (e.kind !== "coin" || e.t < start || e.t > end) continue;
      let i = Math.floor(((e.t - start) / dur) * nb);
      if (i >= nb) i = nb - 1;
      if (i < 0) i = 0;
      buckets[i] += e.mine;
    }
    const bucketHrs = dur / nb / 3600000;
    renderMiniLine(c, buckets.map((v) => ({ val: bucketHrs ? v / bucketHrs : 0 })));
  }

  function renderSessionStats() {
    const { start, end } = state.session;
    const st = windowStats(SESSION.evts, start, end);
    document.getElementById("session-meta").textContent =
      `${clockLabel(start)} → ${clockLabel(end)} · ${fmtDur(st.dur / 1000)}`;
    const si = document.getElementById("session-start");
    const ei = document.getElementById("session-end");
    if (document.activeElement !== si) si.value = msToInput(start);
    if (document.activeElement !== ei) ei.value = msToInput(end);
    const cards = [
      ["Duration", fmtDur(st.dur / 1000), ""],
      ["Kills", st.kills.toLocaleString(), `${st.killsHr}/hr`],
      ["Loot qty", st.lootQty.toLocaleString(), ""],
      ["My split", fmtCoin(st.mine), `${st.coinHr}cp/hr`],
      ["Group looted", fmtCoin(st.group), `${st.share}% mine`],
    ];
    document.getElementById("session-cards").innerHTML = cards
      .map(
        ([lbl, val, sub]) =>
          `<div class="session-card"><div class="val">${esc(val)}</div><div class="lbl">${esc(lbl)}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ""}</div>`
      )
      .join("");
    document.getElementById("session-mobs").innerHTML =
      st.mobs.map(([n, k]) => `<li><span>${esc(n)}</span><b>${k}</b></li>`).join("") ||
      "<li class='muted'>—</li>";
    renderSessionChart(SESSION.evts, start, end);
  }

  function repositionBrush(svg, geo) {
    const [t0, t1] = geo.view;
    const span = Math.max(1, t1 - t0);
    const xOf = (t) => geo.pad.l + ((t - t0) / span) * geo.innerW;
    const sx = xOf(state.session.start);
    const ex = xOf(state.session.end);
    const w = Math.max(1, ex - sx);
    const set = (id, attrs) => {
      const el = svg.querySelector(id);
      if (el) for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    };
    set("#tl-sel", { x: sx.toFixed(2), width: w.toFixed(2) });
    set("#tl-body", { x: sx.toFixed(2), width: w.toFixed(2) });
    set("#tl-lh", { x: (sx - 1.5).toFixed(2) });
    set("#tl-rh", { x: (ex - 1.5).toFixed(2) });
    set("#tl-lhit", { x: (sx - 6).toFixed(2) });
    set("#tl-rhit", { x: (ex - 6).toFixed(2) });
    svg.querySelectorAll(".tl-bar").forEach((b) => {
      const bt = t0 + ((+b.dataset.i + 0.5) / 120) * span;
      b.classList.toggle("in", bt >= state.session.start && bt <= state.session.end);
    });
  }

  function renderTimeline() {
    const container = document.getElementById("session-timeline");
    const t0 = state.session.viewStart;
    const t1 = state.session.viewEnd;
    const span = Math.max(1, t1 - t0);
    const VBW = 1000,
      VBH = 90,
      pad = { l: 10, r: 10, t: 8, b: 18 },
      innerW = VBW - pad.l - pad.r,
      innerH = VBH - pad.t - pad.b;
    const nb = 120;
    const buckets = new Array(nb).fill(0);
    for (const e of SESSION.evts) {
      if (e.kind !== "kill" || e.t < t0 || e.t > t1) continue;
      let i = Math.floor(((e.t - t0) / span) * nb);
      if (i >= nb) i = nb - 1;
      if (i < 0) i = 0;
      buckets[i] += 1;
    }
    const maxB = Math.max(1, ...buckets);
    const bw = innerW / nb;
    let bars = "";
    for (let i = 0; i < nb; i++) {
      const v = buckets[i];
      if (!v) continue;
      const h = (v / maxB) * innerH;
      const x = pad.l + i * bw;
      bars += `<rect class="tl-bar" data-i="${i}" x="${x.toFixed(2)}" y="${(pad.t + innerH - h).toFixed(2)}" width="${Math.max(0.6, bw - 0.3).toFixed(2)}" height="${h.toFixed(2)}"/>`;
    }
    const xOf = (t) => pad.l + ((t - t0) / span) * innerW;
    let ticks = "";
    for (let k = 0; k <= 4; k++) {
      const t = t0 + (span * k) / 4;
      const anchor = k === 0 ? "start" : k === 4 ? "end" : "middle";
      ticks += `<text class="tl-axis" x="${xOf(t).toFixed(1)}" y="${VBH - 5}" text-anchor="${anchor}">${clockLabel(t)}</text>`;
    }
    const sx = xOf(state.session.start);
    const ex = xOf(state.session.end);
    const w = Math.max(1, ex - sx);
    const svgInner =
      bars +
      ticks +
      `<rect class="tl-sel" id="tl-sel" x="${sx.toFixed(2)}" y="${pad.t}" width="${w.toFixed(2)}" height="${innerH}"/>` +
      `<rect class="tl-body-hit" id="tl-body" x="${sx.toFixed(2)}" y="${pad.t}" width="${w.toFixed(2)}" height="${innerH}"/>` +
      `<rect class="tl-handle" id="tl-lh" x="${(sx - 1.5).toFixed(2)}" y="${pad.t}" width="3" height="${innerH}"/>` +
      `<rect class="tl-handle" id="tl-rh" x="${(ex - 1.5).toFixed(2)}" y="${pad.t}" width="3" height="${innerH}"/>` +
      `<rect class="tl-handle-hit" id="tl-lhit" x="${(sx - 6).toFixed(2)}" y="${pad.t}" width="12" height="${innerH}"/>` +
      `<rect class="tl-handle-hit" id="tl-rhit" x="${(ex - 6).toFixed(2)}" y="${pad.t}" width="12" height="${innerH}"/>`;
    container.innerHTML = `<svg id="tl-svg" viewBox="0 0 ${VBW} ${VBH}" role="img">${svgInner}</svg>`;
    const svg = container.querySelector("#tl-svg");
    const geo = { pad, innerW, VBW, view: [t0, t1] };
    repositionBrush(svg, geo);
    attachTimelineDrag(svg, geo);
  }

  function attachTimelineDrag(svg, geo) {
    const [t0, t1] = geo.view;
    const span = Math.max(1, t1 - t0);
    const minW = 1000;
    const xToTime = (clientX) => {
      const rect = svg.getBoundingClientRect();
      const plotLeft = rect.left + (geo.pad.l / geo.VBW) * rect.width;
      const plotW = (geo.innerW / geo.VBW) * rect.width;
      let f = (clientX - plotLeft) / plotW;
      f = Math.max(0, Math.min(1, f));
      return t0 + f * span;
    };
    let mode = null,
      grabOffset = 0,
      width = 0;
    const onMove = (ev) => {
      if (!mode) return;
      const t = xToTime(ev.clientX);
      let { start, end } = state.session;
      if (mode === "left") start = Math.max(t0, Math.min(t, end - minW));
      else if (mode === "right") end = Math.min(t1, Math.max(t, start + minW));
      else {
        let ns = t - grabOffset;
        ns = Math.max(t0, Math.min(ns, t1 - width));
        start = ns;
        end = ns + width;
      }
      state.session.start = start;
      state.session.end = end;
      repositionBrush(svg, geo);
      renderSessionStats();
      ev.preventDefault();
    };
    const onUp = () => {
      if (!mode) return;
      mode = null;
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      renderSession();
    };
    const begin = (m) => (ev) => {
      mode = m;
      const t = xToTime(ev.clientX);
      grabOffset = t - state.session.start;
      width = state.session.end - state.session.start;
      document.addEventListener("pointermove", onMove);
      document.addEventListener("pointerup", onUp);
      ev.preventDefault();
    };
    svg.querySelector("#tl-lhit").addEventListener("pointerdown", begin("left"));
    svg.querySelector("#tl-rhit").addEventListener("pointerdown", begin("right"));
    svg.querySelector("#tl-body").addEventListener("pointerdown", begin("body"));
  }

  function renderSession() {
    const panel = document.querySelector(".session-panel");
    const evts = buildSessionEvents();
    if (!evts.length) {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");
    const t0 = evts[0].t;
    const t1 = Math.max(evts[evts.length - 1].t, t0 + 1);
    SESSION.evts = evts;
    SESSION.domain = [t0, t1];
    const sig = `${state.server}|${state.character}`;
    if (state.session.sig !== sig || state.session.start == null) {
      const sessions = detectSessions(evts);
      const last = sessions[sessions.length - 1];
      const pad = Math.max(600000, (last.end - last.start) * 0.25);
      state.session = {
        sig,
        start: last.start,
        end: last.end,
        viewStart: Math.max(t0, last.start - pad),
        viewEnd: Math.min(t1, last.end + pad),
      };
    }
    state.session.viewStart = Math.max(t0, Math.min(state.session.viewStart, t1 - 1000));
    state.session.viewEnd = Math.min(t1, Math.max(state.session.viewEnd, state.session.viewStart + 1000));
    state.session.start = Math.max(state.session.viewStart, Math.min(state.session.start, state.session.viewEnd - 1000));
    state.session.end = Math.min(state.session.viewEnd, Math.max(state.session.end, state.session.start + 1000));
    renderSessionPresets(detectSessions(evts));
    renderTimeline();
    renderSessionStats();
  }

  function wireSessionControls() {
    const si = document.getElementById("session-start");
    const ei = document.getElementById("session-end");
    si.addEventListener("change", () => {
      const ms = inputToMs(si.value);
      if (ms === ms) {
        state.session.start = Math.min(ms, state.session.end - 1000);
        if (state.session.start < state.session.viewStart) state.session.viewStart = state.session.start;
        renderSession();
      }
    });
    ei.addEventListener("change", () => {
      const ms = inputToMs(ei.value);
      if (ms === ms) {
        state.session.end = Math.max(ms, state.session.start + 1000);
        if (state.session.end > state.session.viewEnd) state.session.viewEnd = state.session.end;
        renderSession();
      }
    });
    document.getElementById("session-reset").addEventListener("click", () => {
      state.session.start = SESSION.domain[0];
      state.session.end = SESSION.domain[1];
      state.session.viewStart = SESSION.domain[0];
      state.session.viewEnd = SESSION.domain[1];
      renderSession();
    });
  }

  let uploadPayload = null;
  let uploadBase = null;

  function hardcoreProfilesForUpload() {
    const rows = window.MNM_HARDCORE?.local || [];
    return rows
      .filter((r) => r.status === "magnificent" || r.status === "candidate")
      .map((r) => ({
        server: r.server,
        character: r.character,
        level: r.level,
        zone: r.zone,
        kills: r.kills,
        status: r.status,
        committed_at: r.committed_at,
        last_seen: r.last_seen,
        profile_token: r.profile_token,
      }));
  }

  function applyUploadPrivacy(base, shareChars, shareHc) {
    const payload = JSON.parse(JSON.stringify(base));
    delete payload.characters;
    delete payload.servers;
    delete payload.hardcore_profiles;
    if (payload.levelups_by_day) {
      payload.levelups_by_day = payload.levelups_by_day.map((row) => {
        const copy = { ...row };
        delete copy.character;
        return copy;
      });
    }
    if (shareChars) {
      payload.characters = RAW.meta.characters || [];
      payload.servers = RAW.meta.servers || [];
      if (RAW.levelups) {
        payload.levelups_by_day = RAW.levelups.map((lu) => ({
          day: lu.day,
          new_level: lu.new_level,
          old_level: lu.old_level,
          zone: lu.zone,
          character: lu.character,
        }));
      }
      if (shareHc) {
        payload.hardcore_profiles = hardcoreProfilesForUpload();
      }
    }
    return payload;
  }

  function wireUploadPrivacy() {
    const shareChars = document.getElementById("upload-share-characters");
    const shareHc = document.getElementById("upload-share-hardcore");
    if (!shareChars || !shareHc) return;

    const refresh = () => {
      shareHc.disabled = !shareChars.checked;
      if (!shareChars.checked) shareHc.checked = false;
      if (uploadBase) {
        uploadPayload = applyUploadPrivacy(uploadBase, shareChars.checked, shareHc.checked);
        renderUpload(RAW.meta, uploadPayload);
      }
    };
    shareChars.onchange = refresh;
    shareHc.onchange = refresh;
    refresh();
  }

  function render() {
    if (!RAW?.meta) return;
    const meta = RAW.meta;
    const kills = filteredKills();
    const loot = filteredLoot();

    renderSummary(meta, kills, loot);
    renderSession();
    renderLineChart(document.getElementById("chart-kills-day"), killsByDay(kills));
    renderDrill(kills, loot);
    renderZoneMap(document.getElementById("zone-map"), kills, RAW.zone_map || {});

    fillTable(
      document.querySelector("#mobs-table tbody"),
      topMobs(kills),
      (m) =>
        `<tr><td>${esc(m.name)}</td><td>${m.kill_count}</td><td>${fmtCoinShort(m.coin_avg)}</td><td>${esc(m.zones.join(", "))}</td></tr>`
    );

    fillTable(
      document.querySelector("#party-loot-table tbody"),
      partyLootRows(loot),
      (r) =>
        `<tr><td>${esc((r.at || "").slice(0, 16))}</td><td>${esc(r.looter)}</td><td>${esc(r.owner)}</td><td>${esc(r.item_name)}</td><td>${r.qty || 1}</td><td>${esc(r.mob_name)}</td><td>${esc(r.zone)}</td></tr>`
    );

    fillTable(
      document.querySelector("#levelups-table tbody"),
      filteredLevelups().slice().reverse(),
      (lu) =>
        `<tr><td>${esc(lu.at?.slice(0, 16))}</td><td>${esc(lu.character)}</td><td>${lu.old_level} → ${lu.new_level}</td><td>${esc(lu.zone)}</td></tr>`
    );

    if (uploadPayload) renderUpload(meta, uploadPayload);
  }

  function fmtDur(seconds) {
    const s = Math.max(0, Math.round(seconds || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (h) return `${h}h ${m}m`;
    if (m) return `${m}m ${s % 60}s`;
    return `${s}s`;
  }

  function fmtCoin(cp) {
    cp = Math.round(cp || 0);
    // 100 per tier: 100c = 1s, 100s = 1g, 100g = 1p.
    const pp = Math.floor(cp / 1000000);
    const gp = Math.floor((cp % 1000000) / 10000);
    const sp = Math.floor((cp % 10000) / 100);
    const c = cp % 100;
    return [pp && `${pp}p`, gp && `${gp}g`, sp && `${sp}s`, `${c}c`].filter(Boolean).join(" ");
  }

  function renderLive(live) {
    const panel = document.getElementById("live-panel");
    if (!live || !live.session || !live.session.started_at) {
      panel.classList.add("hidden");
      return;
    }
    if (state.character && live.session.character !== state.character) {
      panel.classList.add("hidden");
      return;
    }
    if (state.server && live.session.server !== state.server) {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");
    const s = live.session;
    const t = live.totals || {};
    const r = live.rates_per_hour || {};
    const ageMs = live.observed_at ? Date.now() - new Date(live.observed_at).getTime() : Infinity;
    const stale = ageMs > 15000;
    const dot = document.querySelector("#live-panel .live-dot");
    if (dot) dot.classList.toggle("stale", stale);
    const status = stale
      ? `paused — run \u2018python mnm_ledger_watch.py\u2019 (last update ${(live.observed_at || "").slice(11, 19)})`
      : `live · updated ${(live.observed_at || "").slice(11, 19)}`;
    document.getElementById("live-meta").textContent =
      `${s.character || "?"}@${s.server || "?"} · lvl ${s.level ?? "?"} · ${s.zone || "?"} · active ${fmtDur(s.active_seconds)} · ${status}`;

    const grp = t.coin_group_total || 0;
    const liveShare = grp ? `${Math.round((100 * (t.coin_received || 0)) / grp)}% of group` : "";
    const cards = [
      ["Kills", t.kills, `${r.kills || 0}/hr`],
      ["Loot", t.loot_qty, `${r.loot_qty || 0}/hr`],
      ["My split", fmtCoin(t.coin_received || 0), liveShare],
      ["Group looted", fmtCoin(grp), `${r.coin || 0}cp/hr`],
    ];
    document.getElementById("live-cards").innerHTML = cards
      .map(
        ([lbl, val, sub]) =>
          `<div class="live-card"><div class="val">${typeof val === "number" ? val.toLocaleString() : esc(val)}</div><div class="lbl">${lbl}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ""}</div>`
      )
      .join("");

    document.getElementById("live-mobs").innerHTML =
      (live.top_mobs || []).map((m) => `<li><span>${esc(m.name)}</span><b>${m.kills}</b></li>`).join("") ||
      "<li class='muted'>—</li>";

    document.getElementById("live-recent").innerHTML =
      (live.recent || [])
        .slice(0, 10)
        .map((e) => {
          const tm = (e.at || "").slice(11, 19);
          let txt;
          if (e.kind === "kill") txt = `killed ${esc(e.name)}${e.level ? ` (lv${e.level})` : ""}`;
          else if (e.kind === "loot") txt = `looted ${e.qty || 1}× ${esc(e.name)}`;
          else if (e.kind === "levelup") txt = `<b>reached level ${e.level}</b>`;
          else txt = esc(e.kind);
          return `<li><span class="t">${tm}</span> ${txt}</li>`;
        })
        .join("") || "<li class='muted'>—</li>";
  }

  async function pollLive() {
    let live = null;
    try {
      const res = await fetch("ledger-live.json", { cache: "no-store" });
      if (res.ok) live = await res.json();
    } catch {
      live = window.MNM_LEDGER_LIVE || null;
    }
    if (!live) live = window.MNM_LEDGER_LIVE || null;
    renderLive(live);
  }

  function renderCombat(liveCombat) {
    const panel = document.getElementById("combat-panel");
    const cards = document.getElementById("combat-cards");
    const streamsEl = document.getElementById("combat-streams");
    const combat = window.MNM_COMBAT;
    const live = liveCombat || combat?.live || {};
    const totals = combat?.totals && Object.keys(combat.totals).length ? combat.totals : live;
    const hasData = Boolean(
      combat?.meta?.has_data ||
      live?.event_count ||
      totals?.event_count ||
      (combat?.recent && combat.recent.length)
    );
    if (!panel || !cards || !hasData) {
      panel?.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");
    const rows = [
      ["Damage out", totals.damage_out ?? live.damage_out],
      ["Damage in", totals.damage_in ?? live.damage_in],
      ["Heal out", totals.heal_out ?? live.heal_out],
      ["Heal in", totals.heal_in ?? live.heal_in],
      ["Events", totals.event_count ?? live.event_count ?? combat?.meta?.event_count],
      ["PvP incoming", totals.pvp_incoming_count ?? live.pvp_incoming_count ?? 0],
    ];
    cards.innerHTML = rows
      .map(([label, val]) => `<div class="live-card"><span class="lbl">${label}</span><span class="val">${val ?? 0}</span></div>`)
      .join("");

    if (streamsEl && combat?.by_stream && Object.keys(combat.by_stream).length > 1) {
      const streamRows = Object.entries(combat.by_stream)
        .map(([sid, s]) => `<li><b>${esc(s.label || sid)}</b> — ${s.events} events, ${s.damage_out} dmg out</li>`)
        .join("");
      streamsEl.innerHTML = `<ul class="combat-stream-list">${streamRows}</ul>`;
      streamsEl.classList.remove("hidden");
    } else if (streamsEl) {
      streamsEl.classList.add("hidden");
    }
  }

  async function pollCombat() {
    let live = null;
    try {
      const res = await fetch("../../data/combat-live.json", { cache: "no-store" });
      if (res.ok) live = await res.json();
    } catch {
      live = window.MNM_COMBAT?.live || null;
    }
    if (!live) live = window.MNM_COMBAT?.live || null;
    renderCombat(live);
  }

  function init() {
    if (!RAW || !RAW.meta) {
      document.getElementById("stats-empty").classList.remove("hidden");
      return;
    }
    document.getElementById("stats-root").classList.remove("hidden");
    populateFilters(RAW.meta);
    wireSessionControls();
    loadUploadPayload().then((payload) => {
      uploadBase = payload;
      uploadPayload = payload ? applyUploadPrivacy(payload, false, false) : null;
      wireUploadPrivacy();
      renderUpload(RAW.meta, uploadPayload);
    });
    render();
    renderCombat(window.MNM_COMBAT?.live);
    pollLive();
    pollCombat();
    setInterval(pollLive, 3000);
    setInterval(pollCombat, 3000);
  }

  init();
})();
