// Minimal ledger ingest endpoint (Cloudflare Worker).
//
// Routes:
//   GET  /api/ledger/v1/health   -> { ok, schema }
//   POST /api/ledger/v1/ingest   -> validate + rate-limit + store payload to R2
//
// Phase A: no accounts. Anonymous installs are identified only by the opaque
// install_id the client generates. Aggregation/trust runs offline over the stored
// payloads via mnm_crowd_aggregate.py (Phase B promotes this to a live pipeline).

const ACCEPTED_SCHEMAS = new Set(["mnm-ledger-upload/v1", "mnm-ledger-upload/v2", "mnm-hardcore-submit/v1"]);

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type,Authorization,X-MNM-Schema",
};

function json(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }

    if (url.pathname === "/api/ledger/v1/health" && request.method === "GET") {
      return json(200, { ok: true, schema: [...ACCEPTED_SCHEMAS] });
    }

    if (url.pathname !== "/api/ledger/v1/ingest" || request.method !== "POST") {
      return json(404, { error: "not_found" });
    }

    // Optional shared-secret auth.
    const allowAnon = (env.ALLOW_ANONYMOUS ?? "1") === "1";
    if (env.INGEST_TOKEN) {
      const auth = request.headers.get("Authorization") || "";
      if (auth !== `Bearer ${env.INGEST_TOKEN}`) {
        return json(401, { error: "unauthorized" });
      }
    } else if (!allowAnon) {
      return json(503, { error: "ingest_disabled" });
    }

    // Size guard (before reading the whole body where possible).
    const maxBytes = parseInt(env.MAX_BYTES || "2000000", 10);
    const declared = parseInt(request.headers.get("Content-Length") || "0", 10);
    if (declared && declared > maxBytes) {
      return json(413, { error: "payload_too_large", max_bytes: maxBytes });
    }

    let payload;
    try {
      const text = await request.text();
      if (text.length > maxBytes) return json(413, { error: "payload_too_large", max_bytes: maxBytes });
      payload = JSON.parse(text);
    } catch {
      return json(400, { error: "invalid_json" });
    }

    const schema = payload.schema || request.headers.get("X-MNM-Schema");
    if (!ACCEPTED_SCHEMAS.has(schema)) {
      return json(422, { error: "unsupported_schema", accepted: [...ACCEPTED_SCHEMAS] });
    }
    const installId = String(payload.install_id || "").slice(0, 64) || "anon";
    const batchId = String(payload.batch_id || crypto.randomUUID()).slice(0, 64);

    // Per-install hourly rate limit (best-effort; KV is eventually consistent).
    if (env.RATE) {
      const limit = parseInt(env.RATE_PER_HOUR || "30", 10);
      const hour = new Date().toISOString().slice(0, 13); // YYYY-MM-DDTHH
      const key = `rate:${installId}:${hour}`;
      const count = parseInt((await env.RATE.get(key)) || "0", 10);
      if (count >= limit) {
        return json(429, { error: "rate_limited", retry_after_seconds: 3600 });
      }
      await env.RATE.put(key, String(count + 1), { expirationTtl: 3700 });
    }

    // Store the raw payload for offline aggregation.
    const day = new Date().toISOString().slice(0, 10);
    const objectKey = `payloads/${day}/${installId}/${batchId}.json`;
    if (env.PAYLOADS) {
      await env.PAYLOADS.put(objectKey, JSON.stringify(payload), {
        httpMetadata: { contentType: "application/json" },
        customMetadata: { schema, installId, batchId },
      });
    }

    return json(202, { accepted: true, batch_id: batchId, stored: objectKey, schema });
  },
};
