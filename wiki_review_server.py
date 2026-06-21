#!/usr/bin/env python3
"""Local HTTP server for wiki review UI with push/dry-run API.

Serves the repo (or workspace) root and exposes:
  GET  /api/wiki-review/status
  POST /api/wiki-review/dry-run   { "ids": ["mob-foo", ...] }
  POST /api/wiki-review/push      { "ids": ["..."], "summary": "...", "dry_run": false }

Run standalone:
  python wiki_review_server.py
  python wiki_review_server.py --port 8080

The desktop client (mnm_client.py) uses the same handler for Wiki review.
"""

from __future__ import annotations

import argparse
import json
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from build_wiki_review import parse_fix_file
from wiki_review_state import add_pushed, add_rejected, load_state

ROOT = Path(__file__).parent
FIX_ID_RE = re.compile(r"^[\w\-]+$")
DEFAULT_LOOT_SUMMARY = "Add missing loot drops (mnm-item-db)"


def credentials_configured() -> bool:
    from push_wiki import load_credentials, wiki_password, wiki_user

    load_credentials()
    return bool(wiki_user() and wiki_password())


def resolve_fix_path(workspace: Path, fix_id: str) -> Path:
    if not FIX_ID_RE.fullmatch(fix_id):
        raise ValueError(f"invalid fix id: {fix_id}")
    fixes_root = (workspace / "data" / "wiki-fixes").resolve()
    for sub in ("loot", "zones"):
        path = (workspace / "data" / "wiki-fixes" / sub / f"{fix_id}.wiki").resolve()
        if path.is_file():
            if fixes_root not in path.parents:
                raise ValueError("fix path outside wiki-fixes")
            return path
    raise FileNotFoundError(f"fix not found: {fix_id}")


def load_fix(workspace: Path, fix_id: str) -> dict[str, Any]:
    path = resolve_fix_path(workspace, fix_id)
    meta, _body = parse_fix_file(path)
    if not meta or not meta.get("page"):
        raise ValueError(f"fix metadata missing: {fix_id}")
    return {
        "id": fix_id,
        "page": meta["page"],
        "kind": meta.get("kind") or ("mob" if fix_id.startswith("mob-") else "item"),
        "path": path,
    }


def run_dry_run(workspace: Path, fix_id: str) -> dict[str, Any]:
    from push_wiki import dry_run_fix

    fix = load_fix(workspace, fix_id)
    return dry_run_fix(fix["page"], fix["path"])


def run_push(
    workspace: Path,
    fix_id: str,
    *,
    summary: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    from push_wiki import dry_run_fix, push_fix

    fix = load_fix(workspace, fix_id)
    if dry_run:
        out = dry_run_fix(fix["page"], fix["path"])
        out["id"] = fix_id
        return out
    text_summary = summary or DEFAULT_LOOT_SUMMARY
    out = push_fix(fix["page"], fix["path"], text_summary)
    out["id"] = fix_id
    return out


def run_batch(
    workspace: Path,
    ids: list[str],
    *,
    summary: str | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    pushed_ok: list[str] = []
    for fix_id in ids:
        try:
            out = run_push(workspace, fix_id, summary=summary, dry_run=dry_run)
            results.append(out)
            if out.get("ok") and not dry_run:
                pushed_ok.append(fix_id)
        except Exception as exc:
            results.append({"id": fix_id, "ok": False, "error": str(exc)})
    if pushed_ok:
        add_pushed(pushed_ok)
    return results


class WikiReviewHTTPHandler(SimpleHTTPRequestHandler):
    workspace: Path

    def __init__(self, *args, directory: str | None = None, workspace: Path | None = None, **kwargs):
        self.workspace = workspace or Path(directory or ".")
        super().__init__(*args, directory=str(self.workspace), **kwargs)

    def log_message(self, format: str, *args) -> None:
        if str(args[0]).startswith("GET /api/") or str(args[0]).startswith("POST /api/"):
            return
        super().log_message(format, *args)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc
        return data if isinstance(data, dict) else {}

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _api_path(self) -> str:
        return urlparse(self.path).path.rstrip("/") or "/"

    def do_GET(self) -> None:
        if self._api_path().startswith("/api/wiki-review"):
            self._handle_api_get()
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self._api_path().startswith("/api/wiki-review"):
            self._handle_api_post()
            return
        self.send_error(404)

    def _handle_api_get(self) -> None:
        path = self._api_path()
        if path == "/api/wiki-review/status":
            loot_dir = self.workspace / "data" / "wiki-fixes" / "loot"
            fix_count = len(list(loot_dir.glob("*.wiki"))) if loot_dir.is_dir() else 0
            state = load_state()
            self._json(
                200,
                {
                    "ok": True,
                    "api": True,
                    "credentials": credentials_configured(),
                    "fix_count": fix_count,
                    "rejected": state["rejected"],
                    "pushed": state["pushed"],
                },
            )
            return
        self._json(404, {"ok": False, "error": "not found"})

    def _handle_api_post(self) -> None:
        path = self._api_path()
        try:
            data = self._read_json()
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return

        ids = data.get("ids")
        if not ids:
            single = data.get("id")
            ids = [single] if single else []
        if not isinstance(ids, list) or not ids:
            self._json(400, {"ok": False, "error": "ids required"})
            return
        ids = [str(i) for i in ids]

        summary = data.get("summary")
        dry_run = bool(data.get("dry_run"))

        if path == "/api/wiki-review/dry-run":
            results = run_batch(self.workspace, ids, dry_run=True)
            ok = all(r.get("ok") for r in results)
            self._json(200, {"ok": ok, "results": results})
            return

        if path == "/api/wiki-review/reject":
            state = add_rejected(ids)
            for fix_id in ids:
                try:
                    fix_path = resolve_fix_path(self.workspace, fix_id)
                    fix_path.unlink(missing_ok=True)
                except (ValueError, FileNotFoundError):
                    pass
            self._json(200, {"ok": True, "rejected": state["rejected"]})
            return

        if path == "/api/wiki-review/push":
            if not dry_run and not credentials_configured():
                self._json(
                    400,
                    {
                        "ok": False,
                        "error": "Wiki credentials not configured (~/.mnm-wiki/wiki-credentials.env)",
                    },
                )
                return
            results = run_batch(self.workspace, ids, summary=summary, dry_run=dry_run)
            ok = all(r.get("ok") for r in results)
            self._json(200, {"ok": ok, "results": results})
            return

        self._json(404, {"ok": False, "error": "not found"})


def handler_class(workspace: Path) -> type[WikiReviewHTTPHandler]:
    ws = workspace.resolve()

    class _Handler(WikiReviewHTTPHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ws), workspace=ws, **kwargs)

    return _Handler


def serve(workspace: Path, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    handler = handler_class(workspace)
    httpd = ThreadingHTTPServer((host, port), handler)
    return httpd


def main() -> int:
    ap = argparse.ArgumentParser(description="Wiki review UI + push API server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--root", type=Path, default=ROOT, help="Workspace/repo root to serve")
    args = ap.parse_args()

    ws = args.root.resolve()
    httpd = serve(ws, host=args.host, port=args.port)
    host, port = httpd.server_address
    print(f"Serving {ws}")
    print(f"Wiki review: http://{host}:{port}/site/wiki-review/")
    print(f"Push API:    http://{host}:{port}/api/wiki-review/status")
    if not credentials_configured():
        print("Note: no wiki credentials found — push disabled until ~/.mnm-wiki/wiki-credentials.env is set")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
