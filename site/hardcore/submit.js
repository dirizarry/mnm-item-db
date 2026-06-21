/* Parse character-select screenshot text (mirrors mnm_hardcore_parse.py). */
(function () {
  const CHAR_LINE_RE = /([A-Za-z][A-Za-z'-]{1,23})\s*\(\s*(\d{1,2})\s+(.+?)\s*\)/i;
  const ZONE_RE = /Current\s+Zone\s*:\s*(.+)/i;
  const HARDCORE_RE = /(?<![A-Za-z])Hardcore(?![A-Za-z])/;

  function parseCharSelectText(text) {
    const lines = String(text || "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    const blob = lines.join("\n");
    let name = "";
    let level = null;
    let raceClass = "";
    let zone = "";
    let server = "betapvp";

    for (const line of lines) {
      const cm = line.match(CHAR_LINE_RE);
      if (cm && !name) {
        name = cm[1];
        level = parseInt(cm[2], 10);
        raceClass = cm[3].trim();
      }
      const zm = line.match(ZONE_RE);
      if (zm) zone = zm[1].trim();
    }
    if (/beta\s*server\s*pvp/i.test(blob) || /\bbetapvp\b/i.test(blob)) server = "betapvp";
    else if (/\bharadrel\b/i.test(blob)) server = "haradrel";

    const hardcore = HARDCORE_RE.test(blob);
    return {
      character: name || null,
      level,
      race_class: raceClass || null,
      zone: zone || null,
      server,
      hardcore_detected: hardcore,
      parse_ok: Boolean(name && level && hardcore),
    };
  }

  function sha256Hex(buffer) {
    return crypto.subtle.digest("SHA-256", buffer).then((hash) =>
      [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("")
    );
  }

  function submitId() {
    const key = "mnm_hardcore_submit_id";
    let id = localStorage.getItem(key);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(key, id);
    }
    return id;
  }

  function installId() {
    const key = "mnm_hardcore_install_id";
    let id = localStorage.getItem(key);
    if (!id) {
      id = crypto.randomUUID().replace(/-/g, "").slice(0, 16);
      localStorage.setItem(key, id);
    }
    return id;
  }

  function profileToken(server, character, anchor) {
    const raw = `${server}|${character}|${anchor}`.toLowerCase();
    return crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw)).then((hash) =>
      [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 20)
    );
  }

  const els = {
    file: document.getElementById("hc-file"),
    preview: document.getElementById("hc-preview"),
    ocrStatus: document.getElementById("hc-ocr-status"),
    form: document.getElementById("hc-form"),
    character: document.getElementById("hc-character"),
    server: document.getElementById("hc-server"),
    level: document.getElementById("hc-level"),
    raceClass: document.getElementById("hc-race-class"),
    zone: document.getElementById("hc-zone"),
    hardcore: document.getElementById("hc-hardcore"),
    copy: document.getElementById("hc-copy"),
    submit: document.getElementById("hc-submit"),
    submitStatus: document.getElementById("hc-submit-status"),
  };

  let ocrText = "";
  let imageSha = null;
  const cfg = window.MNM_HARDCORE_SUBMIT || {};

  function fillForm(parsed) {
    if (parsed.character) els.character.value = parsed.character;
    if (parsed.level) els.level.value = parsed.level;
    if (parsed.race_class) els.raceClass.value = parsed.race_class;
    if (parsed.zone) els.zone.value = parsed.zone;
    if (parsed.server) els.server.value = parsed.server;
    els.hardcore.checked = parsed.hardcore_detected;
    els.submit.disabled = !parsed.hardcore_detected;
  }

  async function runOcr(file) {
    els.ocrStatus.textContent = "Reading screenshot…";
    const url = URL.createObjectURL(file);
    els.preview.src = url;
    els.preview.classList.remove("hidden");
    try {
      const buf = await file.arrayBuffer();
      imageSha = await sha256Hex(buf);
      const result = await Tesseract.recognize(url, "eng", { logger: () => {} });
      ocrText = result.data.text || "";
      const parsed = parseCharSelectText(ocrText);
      fillForm(parsed);
      els.ocrStatus.textContent = parsed.parse_ok
        ? "Parsed character select — confirm fields and submit."
        : "Could not fully parse — enter fields manually. Hardcore tag must be visible.";
      if (!parsed.hardcore_detected) {
        els.ocrStatus.textContent += " No Hardcore tag detected in OCR text.";
      }
    } catch (e) {
      els.ocrStatus.textContent = "OCR failed — enter fields manually from your screenshot.";
      console.error(e);
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  async function buildPayload() {
    const now = new Date().toISOString();
    const sid = submitId();
    const server = els.server.value;
    const character = els.character.value.trim();
    const token = await profileToken(server, character, now);
    return {
      schema: "mnm-hardcore-submit/v1",
      submit_id: sid,
      batch_id: sid,
      install_id: installId(),
      generated_at: now,
      profile: {
        server,
        character,
        level: parseInt(els.level.value, 10),
        zone: els.zone.value.trim() || null,
        race_class: els.raceClass.value.trim() || null,
        status: "magnificent",
        source: "screenshot",
        kills: 0,
        committed_at: now,
        last_seen: now,
        profile_token: token,
      },
      proof: {
        hardcore_detected: els.hardcore.checked,
        parse_ok: Boolean(character && els.level.value && els.hardcore.checked),
        ocr_text: ocrText.slice(0, 4000),
        image_sha256: imageSha,
      },
    };
  }

  els.file.onchange = () => {
    const file = els.file.files?.[0];
    if (file) runOcr(file);
  };

  document.querySelector(".hc-upload-label .hc-btn").onclick = () => els.file.click();

  els.copy.onclick = async () => {
    const payload = await buildPayload();
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    els.submitStatus.textContent = "Copied submission JSON to clipboard.";
  };

  els.form.onsubmit = async (e) => {
    e.preventDefault();
    if (!els.hardcore.checked) {
      els.submitStatus.textContent = "Screenshot must show the Hardcore tag.";
      return;
    }
    const payload = await buildPayload();
    const url = cfg.endpoint;
    if (!url) {
      await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
      els.submitStatus.textContent =
        "No submit endpoint configured — JSON copied. Save to data/crowd-inbox/ or set MNM_UPLOAD_URL.";
      return;
    }
    els.submit.disabled = true;
    els.submitStatus.textContent = "Submitting…";
    try {
      const headers = { "Content-Type": "application/json", "X-MNM-Schema": payload.schema };
      if (cfg.token) headers.Authorization = `Bearer ${cfg.token}`;
      const res = await fetch(url, { method: "POST", headers, body: JSON.stringify(payload) });
      els.submitStatus.textContent = res.ok
        ? "Submitted — thank you! Your standing joins the board on the next deploy."
        : `Submit failed (${res.status}). Try Copy submission JSON instead.`;
    } catch (err) {
      els.submitStatus.textContent = "Submit failed — try Copy submission JSON.";
      console.error(err);
    } finally {
      els.submit.disabled = false;
    }
  };

  window.MNM_parseCharSelectText = parseCharSelectText;
})();
