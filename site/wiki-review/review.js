/* Wiki loot fix review — side-by-side before/after + local push API */
(function () {
  const DATA = window.MNM_WIKI_REVIEW || { meta: {}, fixes: [] };
  const STORAGE_REVIEWED = "mnm-wiki-review-done";
  const STORAGE_PUSHED = "mnm-wiki-review-pushed";
  const STORAGE_REJECTED = "mnm-wiki-review-rejected";
  const fixes = DATA.fixes || [];
  const meta = DATA.meta || {};

  let activeId = null;
  let reviewed = new Set(JSON.parse(localStorage.getItem(STORAGE_REVIEWED) || "[]"));
  let pushed = new Set(JSON.parse(localStorage.getItem(STORAGE_PUSHED) || "[]"));
  let rejected = new Set(JSON.parse(localStorage.getItem(STORAGE_REJECTED) || "[]"));
  let api = { available: false, credentials: false };

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function saveReviewed() {
    localStorage.setItem(STORAGE_REVIEWED, JSON.stringify([...reviewed]));
  }

  function savePushed() {
    localStorage.setItem(STORAGE_PUSHED, JSON.stringify([...pushed]));
  }

  function saveRejected() {
    localStorage.setItem(STORAGE_REJECTED, JSON.stringify([...rejected]));
  }

  function mergeServerState(data) {
    if (Array.isArray(data.pushed)) {
      data.pushed.forEach((id) => pushed.add(id));
      savePushed();
    }
    if (Array.isArray(data.rejected)) {
      data.rejected.forEach((id) => rejected.add(id));
      saveRejected();
    }
  }

  async function rejectIds(ids) {
    const pages = ids
      .map((id) => fixes.find((f) => f.id === id))
      .filter(Boolean)
      .map((f) => f.page);
    const msg =
      ids.length === 1
        ? `Reject fix for “${pages[0]}”? It will not appear in future review queues.`
        : `Reject ${ids.length} fixes? They will not appear in future review queues.`;
    if (!window.confirm(msg)) return;

    ids.forEach((id) => {
      rejected.add(id);
      reviewed.delete(id);
    });
    saveRejected();
    saveReviewed();

    if (api.available) {
      setBusy(true);
      try {
        await apiPost("/api/wiki-review/reject", { ids });
      } catch (err) {
        log([`Reject saved locally; API: ${err.message || err}`], "err");
      } finally {
        setBusy(false);
      }
    }
    renderList();
    if (activeId && ids.includes(activeId)) {
      const list = filtered();
      if (list.length) select(list[0].id);
      else document.getElementById("wr-detail").classList.add("hidden");
    }
  }

  function log(lines, kind) {
    const el = document.getElementById("wr-log");
    el.classList.remove("hidden");
    const cls = kind === "err" ? "wr-log-err" : kind === "ok" ? "wr-log-ok" : "";
    el.innerHTML = `<pre class="${cls}">${esc(lines.join("\n"))}</pre>`;
    el.scrollTop = el.scrollHeight;
  }

  async function apiPost(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok && !data.results) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    return data;
  }

  function formatResults(results) {
    const lines = [];
    for (const r of results) {
      if (r.ok) {
        lines.push(`OK  ${r.page || r.id}${r.url ? "  " + r.url : ""}`);
        if (r.diff && r.diff.length) {
          lines.push(...r.diff.slice(0, 80));
          if (r.diff.length > 80) lines.push("... (diff truncated)");
        }
      } else {
        lines.push(`FAIL  ${r.page || r.id}: ${r.error || "unknown error"}`);
      }
    }
    return lines;
  }

  async function dryRunIds(ids) {
    setBusy(true);
    try {
      const data = await apiPost("/api/wiki-review/dry-run", { ids });
      log(formatResults(data.results || []), data.ok ? "ok" : "err");
    } catch (err) {
      log([String(err.message || err)], "err");
    } finally {
      setBusy(false);
    }
  }

  async function pushIds(ids) {
    if (!api.credentials) {
      log(["Wiki credentials not configured. Add ~/.mnm-wiki/wiki-credentials.env"], "err");
      return;
    }
    const pages = ids
      .map((id) => fixes.find((f) => f.id === id))
      .filter(Boolean)
      .map((f) => f.page);
    const msg =
      ids.length === 1
        ? `Publish wiki edit for “${pages[0]}”?`
        : `Publish ${ids.length} reviewed wiki edits?`;
    if (!window.confirm(msg)) return;

    setBusy(true);
    try {
      const data = await apiPost("/api/wiki-review/push", { ids });
      const lines = formatResults(data.results || []);
      for (const r of data.results || []) {
        if (r.ok && r.id) {
          pushed.add(r.id);
          reviewed.add(r.id);
        }
      }
      savePushed();
      saveReviewed();
      renderList();
      if (activeId) select(activeId);
      log(lines, data.ok ? "ok" : "err");
    } catch (err) {
      log([String(err.message || err)], "err");
    } finally {
      setBusy(false);
    }
  }

  function setBusy(on) {
    document.querySelectorAll(".wr-btn[data-action]").forEach((btn) => {
      btn.disabled = on;
    });
  }

  function lineDiff(before, after) {
    const a = (before || "").split("\n");
    const b = (after || "").split("\n");
    const aTrim = new Set(a.map((l) => l.trim()).filter(Boolean));
    const bTrim = new Set(b.map((l) => l.trim()).filter(Boolean));
    return {
      before: a.map((line) => ({
        text: line,
        kind: line.trim() && !bTrim.has(line.trim()) ? "del" : "same",
      })),
      after: b.map((line) => ({
        text: line,
        kind: line.trim() && !aTrim.has(line.trim()) ? "add" : "same",
      })),
    };
  }

  function renderPanel(el, lines) {
    el.innerHTML = lines
      .map((ln) => {
        const cls = ln.kind === "same" ? "" : ` class="wr-line ${ln.kind}"`;
        return `<span${cls}>${esc(ln.text)}\n</span>`;
      })
      .join("");
  }

  function syncScroll(a, b) {
    let lock = false;
    const sync = (src, dst) => {
      src.addEventListener("scroll", () => {
        if (lock) return;
        lock = true;
        dst.scrollTop = src.scrollTop;
        dst.scrollLeft = src.scrollLeft;
        lock = false;
      });
    };
    sync(a, b);
    sync(b, a);
  }

  function filtered() {
    const f = document.getElementById("wr-filter").value;
    return fixes.filter((fx) => {
      if (f === "mob") return fx.kind === "mob";
      if (f === "item") return fx.kind === "item";
      if (f === "done") return reviewed.has(fx.id);
      if (f === "pending") return !reviewed.has(fx.id) && !rejected.has(fx.id) && !pushed.has(fx.id);
      if (f === "pushed") return pushed.has(fx.id);
      if (f === "rejected") return rejected.has(fx.id);
      return true;
    });
  }

  function statusLabel(fx) {
    if (fx.new_page) return "new page";
    if (rejected.has(fx.id)) return "rejected";
    if (pushed.has(fx.id)) return "pushed";
    if (reviewed.has(fx.id)) return "reviewed";
    return "";
  }

  function renderQueueMeta() {
    const el = document.getElementById("wr-queue-meta");
    if (!el) return;
    const parts = [`${fixes.length} in queue`];
    if (meta.candidate_edges) parts.push(`${meta.candidate_edges} drop edges scanned`);
    if (meta.skipped_unchanged) parts.push(`${meta.skipped_unchanged} already on wiki`);
    if (meta.skipped_no_wiki) parts.push(`${meta.skipped_no_wiki} need --create-missing`);
    if (meta.stubbed_pages) parts.push(`${meta.stubbed_pages} new page stubs`);
    el.textContent = parts.join(" · ");
  }

  function renderList() {
    const list = filtered();
    const reviewedPending = fixes.filter(
      (f) => reviewed.has(f.id) && !pushed.has(f.id) && !rejected.has(f.id)
    );
    document.getElementById("wr-count").textContent =
      `${list.length} shown · ${reviewed.size} reviewed · ${pushed.size} pushed · ${rejected.size} rejected`;
    const batchBtn = document.getElementById("wr-push-reviewed");
    if (batchBtn) {
      batchBtn.textContent = `Push reviewed (${reviewedPending.length})`;
      batchBtn.disabled =
        !api.available || !api.credentials || reviewedPending.length === 0;
    }

    const ul = document.getElementById("wr-list");
    if (!list.length) {
      ul.innerHTML = "<li class='muted' style='padding:12px'>No matches.</li>";
      return;
    }
    ul.innerHTML = list
      .map((fx) => {
        const st = statusLabel(fx);
        const cls = [
          fx.id === activeId ? "active" : "",
          reviewed.has(fx.id) ? "done" : "",
          pushed.has(fx.id) ? "pushed" : "",
          rejected.has(fx.id) ? "rejected" : "",
        ]
          .filter(Boolean)
          .join(" ");
        return (
          `<li><button type="button" data-id="${esc(fx.id)}" class="${cls}">` +
          `<span class="kind">${fx.kind}</span>${esc(fx.page)}` +
          (st ? `<span class="wr-st">${st}</span>` : "") +
          `</button></li>`
        );
      })
      .join("");
    ul.querySelectorAll("button[data-id]").forEach((btn) => {
      btn.onclick = () => select(btn.dataset.id);
    });
    if (!activeId || !list.find((f) => f.id === activeId)) {
      select(list[0].id);
    }
  }

  function updateApiStatus() {
    const el = document.getElementById("wr-api-status");
    if (!el) return;
    if (!api.available) {
      el.textContent =
        "Push API offline — open via desktop client or: python wiki_review_server.py";
      el.className = "wr-api-status wr-api-off";
      return;
    }
    if (!api.credentials) {
      el.textContent =
        "Push API ready · credentials missing (~/.mnm-wiki/wiki-credentials.env)";
      el.className = "wr-api-status wr-api-warn";
      return;
    }
    el.textContent = "Push API ready · credentials configured";
    el.className = "wr-api-status wr-api-ok";
  }

  function setActionButtons() {
    const canApi = api.available;
    const canPush = canApi && api.credentials;
    document.getElementById("wr-dry-run").disabled = !canApi;
    document.getElementById("wr-push-one").disabled = !canPush;
  }

  function select(id) {
    activeId = id;
    const fx = fixes.find((f) => f.id === id);
    if (!fx) return;
    renderList();
    const bits = [`${fx.kind} page`, fx.file];
    if (fx.new_page) bits.push("new wiki page");
    if (pushed.has(id)) bits.push("pushed");
    else if (rejected.has(id)) bits.push("rejected");
    else if (reviewed.has(id)) bits.push("reviewed");
    document.getElementById("wr-title").textContent = fx.page;
    document.getElementById("wr-meta").textContent = bits.join(" · ");
    document.getElementById("wr-wiki").href = fx.wiki_url;
    document.getElementById("wr-adds").innerHTML = (fx.adds || []).length
      ? "<strong>Adds:</strong> " + fx.adds.map((a) => `<span>${esc(a)}</span>`).join("")
      : "";

    const diff = lineDiff(fx.before, fx.after);
    const beforeEl = document.getElementById("wr-before");
    const afterEl = document.getElementById("wr-after");
    renderPanel(beforeEl, diff.before);
    renderPanel(afterEl, diff.after);
    syncScroll(beforeEl, afterEl);

    document.getElementById("wr-dry-run").onclick = () => dryRunIds([id]);
    document.getElementById("wr-push-one").onclick = () => pushIds([id]);
    document.getElementById("wr-mark").onclick = () => {
      reviewed.add(id);
      saveReviewed();
      renderList();
      select(id);
    };
    document.getElementById("wr-reject").onclick = () => rejectIds([id]);
  }

  async function loadApiStatus() {
    try {
      const res = await fetch("/api/wiki-review/status");
      if (!res.ok) throw new Error("status failed");
      const data = await res.json();
      api = { available: true, credentials: !!data.credentials };
      mergeServerState(data);
    } catch {
      api = { available: false, credentials: false };
    }
    updateApiStatus();
    setActionButtons();
    renderList();
  }

  function init() {
    if (!fixes.length) {
      document.getElementById("wr-empty").classList.remove("hidden");
      return;
    }
    document.getElementById("wr-root").classList.remove("hidden");
    renderQueueMeta();
    document.getElementById("wr-filter").onchange = renderList;
    document.getElementById("wr-push-reviewed").onclick = () => {
      const ids = fixes
        .filter((f) => reviewed.has(f.id) && !pushed.has(f.id) && !rejected.has(f.id))
        .map((f) => f.id);
      pushIds(ids);
    };
    loadApiStatus();
  }

  init();
})();
