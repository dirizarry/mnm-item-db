/* Contribute — item source drafts with reverse search (wiki push via copy/preview). */
(function () {
  const ITEMS = window.MNM_ITEMS || [];
  const WIKI = "https://monstersandmemories.miraheze.org/wiki/";
  const wikiUrl = (t) => WIKI + encodeURIComponent(String(t).replace(/ /g, "_"));

  let mode = "drop";
  let els = {};

  function esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  }

  function reverseSearchItem(name) {
    const q = name.toLowerCase();
    if (!q) return { zones: [], mobs: [], items: [] };
    const hit = ITEMS.find((it) => (it.name || it.title || "").toLowerCase() === q)
      || ITEMS.find((it) => (it.name || it.title || "").toLowerCase().includes(q));
    return {
      item: hit,
      zones: hit?.drops_zones || [],
      mobs: hit?.drops_mobs || [],
    };
  }

  function reverseSearchZone(zone) {
    const q = zone.toLowerCase();
    const mobs = new Set();
    const items = [];
    ITEMS.forEach((it) => {
      if ((it.drops_zones || []).some((z) => z.toLowerCase().includes(q))) {
        items.push(it.name || it.title);
        (it.drops_mobs || []).forEach((m) => mobs.add(m));
      }
    });
    return { mobs: [...mobs].sort(), items: items.slice(0, 40) };
  }

  function reverseSearchMob(mob) {
    const q = mob.toLowerCase();
    const items = [];
    const zones = new Set();
    ITEMS.forEach((it) => {
      if ((it.drops_mobs || []).some((m) => m.toLowerCase().includes(q))) {
        items.push(it.name || it.title);
        (it.drops_zones || []).forEach((z) => zones.add(z));
      }
    });
    return { zones: [...zones].sort(), items: items.slice(0, 40) };
  }

  function updateReverse() {
    const item = els.itemName.value.trim();
    const zone = els.zone.value.trim();
    const mob = els.mob.value.trim();
    let html = "";
    if (item) {
      const r = reverseSearchItem(item);
      html += `<div class="ct-reverse"><b>Item lookup:</b> ` +
        (r.item ? `known — ${(r.zones || []).join(", ") || "no zone"} / ${(r.mobs || []).join(", ") || "no mob"}` : "not in DB yet") +
        `</div>`;
    }
    if (zone) {
      const r = reverseSearchZone(zone);
      html += `<div class="ct-reverse"><b>Zone "${esc(zone)}":</b> mobs: ${r.mobs.slice(0, 12).join(", ") || "—"} · sample items: ${r.items.slice(0, 8).join(", ") || "—"}</div>`;
    }
    if (mob) {
      const r = reverseSearchMob(mob);
      html += `<div class="ct-reverse"><b>Mob "${esc(mob)}":</b> zones: ${r.zones.join(", ") || "—"} · items: ${r.items.slice(0, 8).join(", ") || "—"}</div>`;
    }
    els.reverse.innerHTML = html || "<p class='muted ct-reverse'>Enter item, zone, or mob to reverse-search existing DB.</p>";
  }

  function buildWikitext() {
    const item = els.itemName.value.trim();
    if (!item) return "";
    if (mode === "drop") {
      const zone = els.zone.value.trim();
      const mob = els.mob.value.trim();
      let drops = "";
      if (zone) drops += `[[${zone}]]\n`;
      if (mob) drops += `*[[${mob}]]\n`;
      return `<!-- Draft for [[${item}]] Itempage -->\n|dropsfrom=${drops}\n`;
    }
    if (mode === "craft") {
      const skill = els.skill.value.trim();
      const trivial = els.trivial.value.trim();
      const comps = els.components.value.trim();
      return `<!-- Draft craft notes for [[${item}]] -->\n|playercrafted=yes\n|notes=${skill ? `[[${skill}]]` : ""}${trivial ? ` Trivial: ${trivial}.` : ""}\n${comps}\n`;
    }
    if (mode === "quest") {
      const quest = els.quest.value.trim();
      const qlevel = els.questLevel.value.trim();
      return `<!-- Draft for [[${item}]] -->\n|relatedquests=[[${quest}]]${qlevel ? `\n<!-- Quest level ${qlevel} on quest page -->` : ""}\n`;
    }
    return "";
  }

  function renderDraft() {
    els.draft.textContent = buildWikitext() || "(fill in fields above)";
    updateReverse();
  }

  function setMode(m) {
    mode = m;
    document.querySelectorAll(".ct-mode").forEach((b) => b.classList.toggle("active", b.dataset.mode === m));
    els.dropFields.classList.toggle("hidden", m !== "drop");
    els.craftFields.classList.toggle("hidden", m !== "craft");
    els.questFields.classList.toggle("hidden", m !== "quest");
    renderDraft();
  }

  function onFile(ev) {
    const f = ev.target.files?.[0];
    if (!f) return;
    els.preview.src = URL.createObjectURL(f);
    els.preview.classList.remove("hidden");
    els.fileHint.textContent = "Screenshot attached — enter values manually (OCR pipeline hooks here).";
    ev.target.value = "";
  }

  function init() {
    els = {
      itemName: document.getElementById("ct-item"),
      zone: document.getElementById("ct-zone"),
      mob: document.getElementById("ct-mob"),
      skill: document.getElementById("ct-skill"),
      trivial: document.getElementById("ct-trivial"),
      components: document.getElementById("ct-components"),
      quest: document.getElementById("ct-quest"),
      questLevel: document.getElementById("ct-quest-level"),
      reverse: document.getElementById("ct-reverse"),
      draft: document.getElementById("ct-draft"),
      dropFields: document.getElementById("ct-drop-fields"),
      craftFields: document.getElementById("ct-craft-fields"),
      questFields: document.getElementById("ct-quest-fields"),
      preview: document.getElementById("ct-preview"),
      fileHint: document.getElementById("ct-file-hint"),
    };
    document.querySelectorAll(".ct-mode").forEach((b) => b.onclick = () => setMode(b.dataset.mode));
    ["itemName", "zone", "mob", "skill", "trivial", "components", "quest", "questLevel"].forEach((k) =>
      els[k]?.addEventListener("input", renderDraft));
    document.getElementById("ct-copy").onclick = () => {
      const t = buildWikitext();
      navigator.clipboard?.writeText(t).then(() => alert("Wikitext copied — paste into wiki or push_wiki.py workflow."));
    };
    document.getElementById("ct-wiki").onclick = () => {
      const item = els.itemName.value.trim();
      if (item) window.open(wikiUrl(item), "_blank");
    };
    document.getElementById("ct-upload").onchange = onFile;
    setMode("drop");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
