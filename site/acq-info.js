/* Acquisition level labels for picker / acquire views. */
(function () {
  const ITEMS = window.MNM_ITEMS || [];
  const byTitle = new Map(ITEMS.map((it) => [it.title, it]));
  const byName = new Map();
  ITEMS.forEach((it) => { if (it.name && !byName.has(it.name)) byName.set(it.name, it); });
  const lookup = (n) => byTitle.get(n) || byName.get(n) || null;

  function acqInfo(it) {
    if (!it) return { kind: "unknown", level: null, label: "—", sortKey: 99999 };

    if (it.acq_level != null && it.acq_label) {
      return { kind: it.acq_kind || "unknown", level: it.acq_level, label: it.acq_label, sortKey: it.acq_level };
    }

    const types = it.source_types || [];
    if (types.includes("dropped")) {
      const mob = (it.drops_mobs || [])[0] || "?";
      const zone = (it.drops_zones || [])[0] || "";
      const label = zone ? `? · ${mob} · ${zone}` : `? · ${mob}`;
      return { kind: "dropped", level: null, label, sortKey: 99998 };
    }
    if (types.includes("crafted") || it.crafted) {
      const skill = (it.tradeskills || [])[0] || "Craft";
      return { kind: "crafted", level: it.trivial || null, label: it.trivial ? `${it.trivial} · ${skill}` : `? · ${skill}`, sortKey: it.trivial || 99997 };
    }
    if (types.includes("quest")) {
      const q = (it.quests || [])[0] || "Quest";
      return { kind: "quest", level: null, label: `? · ${q}`, sortKey: 99996 };
    }
    if (types.includes("vendor")) return { kind: "vendor", level: null, label: "Vendor", sortKey: 99995 };
    if (types.includes("starter")) return { kind: "starter", level: null, label: "Starter", sortKey: 0 };
    return { kind: "unknown", level: null, label: "?", sortKey: 99999 };
  }

  /** Compare item acq level vs character level for row tinting. */
  function acqTier(charLevel, acqLevel) {
    if (charLevel == null || charLevel === "" || acqLevel == null) return "";
    const cl = Number(charLevel);
    const al = Number(acqLevel);
    if (al <= cl) return "acq-ok";
    if (al <= cl + 5) return "acq-warn";
    return "acq-hard";
  }

  window.MNM_acq = { lookup, acqInfo, acqTier };
})();
