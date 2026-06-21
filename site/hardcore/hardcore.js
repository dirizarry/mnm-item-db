/* Magnificent Hall — community leaderboard */
(function () {
  const RAW = window.MNM_HARDCORE;
  const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;");

  const state = {
    server: "betapvp",
    view: "crowd",
    selected: null,
  };

  function statusLabel(status, source) {
    if (status === "magnificent") {
      if (source === "screenshot" || source === "community") return "Hardcore · community";
      return "Hardcore";
    }
    if (status === "candidate") return "Seeking";
    return status || "—";
  }

  function statusClass(status) {
    if (status === "magnificent") return "magnificent";
    if (status === "candidate") return "candidate";
    return "";
  }

  function daysSince(iso) {
    if (!iso) return "—";
    const d = new Date(String(iso).slice(0, 19));
    if (Number.isNaN(d.getTime())) return "—";
    const days = Math.floor((Date.now() - d.getTime()) / 86400000);
    return days <= 0 ? "<1" : String(days);
  }

  function localKeys() {
    const set = new Set();
    for (const p of RAW?.local || []) {
      set.add(`${p.server}|${p.character}`.toLowerCase());
    }
    return set;
  }

  function mergeRows() {
    const local = RAW?.local || [];
    const crowd = RAW?.crowd || [];
    const yours = localKeys();
    const byKey = new Map();

    for (const row of crowd) {
      if (state.server && row.server !== state.server) continue;
      const key = `${row.server}|${row.character}`.toLowerCase();
      byKey.set(key, { ...row, isYou: yours.has(key), source: "crowd" });
    }

    for (const row of local) {
      if (state.server && row.server !== state.server) continue;
      const key = `${row.server}|${row.character}`.toLowerCase();
      const existing = byKey.get(key);
      if (!existing || row.level > existing.level) {
        byKey.set(key, { ...row, isYou: true, source: "local" });
      } else if (existing) {
        existing.isYou = true;
      }
    }

    let rows = [...byKey.values()];
    if (state.view === "crowd") {
      rows = rows.filter((r) => r.source === "crowd" || (RAW?.crowd || []).length === 0);
      if ((RAW?.crowd || []).length === 0) rows = [...byKey.values()];
    } else if (state.view === "local") {
      rows = rows.filter((r) => r.isYou);
    }

    rows.sort((a, b) => {
      if (b.level !== a.level) return b.level - a.level;
      if (b.kills !== a.kills) return b.kills - a.kills;
      return String(a.committed_at || "").localeCompare(String(b.committed_at || ""));
    });
    return rows;
  }

  function renderStats(rows) {
    const el = document.getElementById("hc-stats");
    const hardcore = rows.filter((r) => r.status === "magnificent").length;
    const maxLvl = rows.reduce((m, r) => Math.max(m, r.level || 0), 0);
    const totalKills = rows.reduce((s, r) => s + (r.kills || 0), 0);
    const cards = [
      { val: rows.length, lbl: "Listed" },
      { val: hardcore, lbl: "Hardcore" },
      { val: maxLvl || "—", lbl: "Top level" },
      { val: totalKills.toLocaleString(), lbl: "Total kills" },
    ];
    el.innerHTML = cards
      .map((c) => `<div class="hc-card"><div class="val">${esc(c.val)}</div><div class="lbl">${esc(c.lbl)}</div></div>`)
      .join("");
  }

  function renderPodium(rows) {
    const el = document.getElementById("hc-podium");
    const top = rows.filter((r) => r.status === "magnificent" || r.status === "candidate").slice(0, 3);
    if (top.length < 2) {
      el.classList.add("hidden");
      return;
    }
    el.classList.remove("hidden");
    const order = top.length >= 3 ? [top[1], top[0], top[2]] : top;
    const ranks = top.length >= 3 ? [2, 1, 3] : [1, 2];
    el.innerHTML = order
      .map((p, i) => {
        const rank = ranks[i];
        return `<div class="hc-podium-card rank-${rank}">
          <div class="hc-podium-rank">#${rank}</div>
          <div class="hc-podium-name">${esc(p.character)}${p.isYou ? '<span class="hc-badge you">You</span>' : ""}</div>
          <div class="hc-podium-level">${esc(p.level)}</div>
          <div class="hc-podium-zone">${esc(p.zone || "—")}</div>
          <span class="hc-badge ${statusClass(p.status)}">${esc(statusLabel(p.status, p.source))}</span>
        </div>`;
      })
      .join("");
  }

  function renderTable(rows) {
    const tbody = document.querySelector("#hc-table tbody");
    tbody.innerHTML = rows
      .map((p, i) => {
        const rank = i + 1;
        const sel = state.selected === `${p.server}|${p.character}` ? " selected" : "";
        return `<tr class="${p.isYou ? "is-you" : ""}${sel}" data-key="${esc(p.server)}|${esc(p.character)}">
          <td>${rank}</td>
          <td>${esc(p.character)}${p.isYou ? '<span class="hc-badge you">You</span>' : ""}</td>
          <td class="level-cell">${esc(p.level)}</td>
          <td>${esc(p.zone || "—")}</td>
          <td>${esc((p.kills || 0).toLocaleString())}</td>
          <td>${esc(daysSince(p.committed_at))}</td>
          <td><span class="hc-badge ${statusClass(p.status)}">${esc(statusLabel(p.status, p.source))}</span></td>
        </tr>`;
      })
      .join("");

    tbody.querySelectorAll("tr").forEach((tr) => {
      tr.onclick = () => {
        state.selected = tr.dataset.key;
        renderTable(rows);
        updateFlexBtn(rows);
      };
    });
  }

  function flexLine(p) {
    const tag = p.status === "magnificent" ? "Hardcore" : "Seeking Hardcore";
    return `⚔️ ${p.character} · Lvl ${p.level} · ${p.zone || "?"} · ${p.server} · ${tag}`;
  }

  function updateFlexBtn(rows) {
    const btn = document.getElementById("btn-flex");
    let pick = rows.find((r) => `${r.server}|${r.character}` === state.selected);
    if (!pick) pick = rows.find((r) => r.isYou) || rows[0];
    btn.disabled = !pick;
    btn.onclick = async () => {
      if (!pick) return;
      await navigator.clipboard.writeText(flexLine(pick));
      const prev = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = prev; }, 1500);
    };
  }

  function renderMilestones() {
    const panel = document.getElementById("hc-milestones");
    const ticker = document.getElementById("hc-ticker");
    const local = RAW?.local || [];
    const ups = [];
    for (const p of local) {
      if (p.levelups > 0) {
        ups.push(`${p.character} — ${p.levelups} level-up${p.levelups === 1 ? "" : "s"} · now Lvl ${p.level}`);
      } else if (p.level > 1) {
        ups.push(`${p.character} reached Lvl ${p.level} in ${p.zone || "?"}`);
      }
    }
    if (!ups.length) {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");
    ticker.innerHTML = ups.map((t) => `<li>${esc(t)}</li>`).join("");
  }

  function populateServers() {
    const sel = document.getElementById("filter-server");
    const servers = new Set(["betapvp"]);
    for (const p of [...(RAW?.local || []), ...(RAW?.crowd || [])]) {
      if (p.server) servers.add(p.server);
    }
    for (const s of RAW?.meta?.servers || []) servers.add(s);
    sel.innerHTML = [...servers].sort().map((s) =>
      `<option value="${esc(s)}"${s === state.server ? " selected" : ""}>${esc(s)}</option>`
    ).join("");
    sel.onchange = () => {
      state.server = sel.value;
      render();
    };
  }

  function render() {
    const rows = mergeRows();
    const summary = document.getElementById("filter-summary");
    summary.textContent = `${rows.length} on ${state.server || "all servers"}`;
    renderStats(rows);
    renderPodium(rows);
    renderTable(rows);
    updateFlexBtn(rows);
    renderMilestones();
  }

  function init() {
    if (!RAW?.meta) {
      document.getElementById("hc-empty").classList.remove("hidden");
      return;
    }
    document.getElementById("hc-root").classList.remove("hidden");
    document.getElementById("hc-meta").textContent =
      `Generated ${RAW.meta.generated || "?"} · ${RAW.meta.hardcore_n || 0} local · ${RAW.meta.crowd_n || 0} community`;

    populateServers();
    document.getElementById("filter-view").onchange = (e) => {
      state.view = e.target.value;
      render();
    };
    render();
  }

  init();
})();
