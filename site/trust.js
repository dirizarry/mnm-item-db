/* Shared provenance / trust UI helpers for item browser + mob browse */
(function () {
  const STATUS = {
    confirmed: { label: "Confirmed", cls: "trust-confirmed" },
    crowd_candidate: { label: "Wiki gap", cls: "trust-gap" },
    wiki_corroborated: { label: "Wiki match", cls: "trust-wiki" },
    wiki_unconfirmed: { label: "Unverified", cls: "trust-unverified" },
    unknown: { label: "Unknown", cls: "trust-unknown" },
  };

  function statusMeta(status) {
    return STATUS[status] || STATUS.unknown;
  }

  function confLabel(conf) {
    if (conf == null) return "";
    const pct = Math.round(Number(conf) * 100);
    return `${pct}%`;
  }

  function trustBadge(drop) {
    if (!drop) return "";
    const meta = statusMeta(drop.status);
    const conf = drop.conf != null ? ` · ${confLabel(drop.conf)}` : "";
    const you = drop.you ? ' <span class="trust-you">You</span>' : "";
    const gap = drop.conflict ? ' <span class="trust-conflict">!</span>' : "";
    return `<span class="trust-badge ${meta.cls}" title="${meta.label}${conf}">${meta.label}${conf}</span>${you}${gap}`;
  }

  function personalForItem(title) {
    const p = window.MNM_PERSONAL;
    if (!p?.byItem) return null;
    return p.byItem[title] || null;
  }

  function personalForMob(title) {
    const p = window.MNM_PERSONAL;
    if (!p?.byMob) return null;
    return p.byMob[title] || null;
  }

  function personalBadge(itemTitle, mobTitle) {
    const rows = personalForItem(itemTitle) || [];
    const hit = rows.find((r) => r.mob === mobTitle);
    if (!hit) return "";
    const rate = window.MNM_PERSONAL?.rates?.[mobTitle]?.items?.[itemTitle];
    const rateTxt = rate?.drop_rate != null ? ` · ${(rate.drop_rate * 100).toFixed(1)}%` : "";
    return `<span class="trust-you" title="You looted this ${hit.count} time(s)${rateTxt}">You ×${hit.count}${rateTxt}</span>`;
  }

  function itemDbLink(title) {
    const enc = encodeURIComponent(title);
    return `../index.html#item=${enc}`;
  }

  function mobDbLink(title) {
    const enc = encodeURIComponent(title);
    return `../index.html#mob=${enc}`;
  }

  window.MNM_trust = {
    statusMeta,
    confLabel,
    trustBadge,
    personalForItem,
    personalForMob,
    personalBadge,
    itemDbLink,
    mobDbLink,
  };
})();
