/* Shared acquisition helpers — used by Acquire (solo) and Guild (aggregated) tabs. */
(function () {
  const WIKI = "https://monstersandmemories.miraheze.org/wiki/";
  const ITEMS = window.MNM_ITEMS || [];
  const wikiUrl = (t) => WIKI + encodeURIComponent(String(t).replace(/ /g, "_"));

  const byTitle = new Map(ITEMS.map((it) => [it.title, it]));
  const byName = new Map();
  ITEMS.forEach((it) => { if (it.name && !byName.has(it.name)) byName.set(it.name, it); });
  const lookup = (n) => byTitle.get(n) || byName.get(n) || null;
  const key = (it) => (typeof it === "string" ? it : (it.name || it.title));

  const SRC_LABEL = {
    dropped: "Dropped", crafted: "Crafted", quest: "Quest",
    starter: "Starter", vendor: "Vendor", unknown: "Unknown",
  };
  const TOOL_RE = /\b(mold|pliers|hammer|chisel|needle|loom|pick|sickle|tongs|snips|toolkit|tool kit)\b/i;
  const isTool = (n) => TOOL_RE.test(n);

  const rawOnly = new Set();
  ITEMS.forEach((a) => {
    if (!a.crafted || !Array.isArray(a.components)) return;
    a.components.forEach((c) => {
      const b = lookup(c.name);
      if (b && b.crafted && Array.isArray(b.components) &&
          b.components.some((cc) => key(lookup(cc.name) || { name: cc.name }) === key(a))) {
        const la = a.components.length, lb = b.components.length;
        rawOnly.add(la <= lb ? key(a) : key(b));
      }
    });
  });

  function expand(name, qty, raw, tools, path, depth) {
    if (isTool(name)) { tools[name] = Math.max(tools[name] || 0, 1); return; }
    const it = lookup(name);
    const canCraft = it && it.crafted && Array.isArray(it.components) && it.components.length
      && !rawOnly.has(name) && !path.has(name) && depth < 8;
    if (canCraft) {
      path.add(name);
      it.components.forEach((c) => expand(c.name, qty * (c.qty || 1), raw, tools, path, depth + 1));
      path.delete(name);
    } else {
      raw[name] = (raw[name] || 0) + qty;
    }
  }

  /** Collect unacquired equipped items from a gear set. slots = [[id, label, slotCode], ...] */
  function neededItems(gear, slots) {
    const out = [];
    if (!gear || !gear.slots) return out;
    slots.forEach(([id, label]) => {
      const title = gear.slots[id];
      if (!title || gear.acquired?.[id]) return;
      const it = lookup(title);
      if (it) out.push({ id, label, title, it });
    });
    return out;
  }

  window.MNM_acquire = {
    WIKI, wikiUrl, lookup, key, SRC_LABEL, isTool, rawOnly, expand, neededItems,
  };
})();
