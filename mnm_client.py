#!/usr/bin/env python3
"""MnM Item DB — desktop control panel (Phase A client).

A one-window app that wraps the existing pipeline so non-technical players can:
  - auto-discover their Monsters & Memories logs
  - mine kills/loot/coin/XP analytics
  - run a live session monitor while they play
  - open the local stats dashboard in a browser
  - (opt-in) submit aggregated, privacy-gated data to the shared DB
  - check for updates
  - combat chat OCR (damage/healing from the in-game combat window)

Run from source:
    python mnm_client.py

Build a standalone exe:
    python build_client.py        (see CLIENT.md)
"""

from __future__ import annotations

import contextlib
import queue
import shutil
import threading
import tkinter as tk
import webbrowser
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import mnm_paths
from mnm_local import default_locallow
from mnm_version import __version__
from wiki_review_server import handler_class


class _Console:
    """Thread-safe sink that streams worker output into the Tk log widget."""

    def __init__(self, sink: queue.Queue[str]):
        self.sink = sink

    def write(self, text: str) -> int:
        if text:
            self.sink.put(text)
        return len(text)

    def flush(self) -> None:  # pragma: no cover - file-like protocol
        pass


class ClientApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = mnm_paths.load_settings()
        mnm_paths.apply_settings_to_env(self.settings)
        self._prepare_workspace()

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.busy = False
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self._combat_stop = threading.Event()
        self._combat_thread: threading.Thread | None = None
        self._combat_stats_job: str | None = None
        self._httpd: ThreadingHTTPServer | None = None

        root.title(f"MnM Item DB — Control Panel  v{__version__}")
        root.geometry("780x620")
        root.minsize(640, 520)
        self._build_ui()
        self._refresh_status()
        self.root.after(120, self._drain_log)
        if self.settings.get("auto_check_updates"):
            self.root.after(
                800, partial(self._run_async, self._do_update_check, "update check", quiet=True)
            )
        self.root.after(400, self._check_combat_deps)

    def _check_combat_deps(self) -> None:
        try:
            from mnm_combat_ocr import available_backends

            backends = available_backends()
        except ImportError:
            backends = []
        if backends:
            self._append(f"Combat OCR ready ({', '.join(backends)}).\n")
        else:
            self._append(
                "Combat OCR: install optional deps — pip install -r requirements-combat.txt\n"
            )

    # --- workspace -------------------------------------------------------------
    def _prepare_workspace(self) -> None:
        """When frozen, seed a writable workspace and point pipeline modules at it."""
        if not mnm_paths.is_frozen():
            return
        ws = mnm_paths.workspace_dir()
        for sub in ("site", "data"):
            src = mnm_paths.resource_path(sub)
            dst = ws / sub
            if src.is_dir() and not dst.exists():
                shutil.copytree(src, dst, dirs_exist_ok=True)
        self._retarget_modules(ws)

    @staticmethod
    def _retarget_modules(ws: Path) -> None:
        """Centralized override so untouched pipeline modules write to the workspace."""
        data = ws / "data"
        site_stats = ws / "site" / "stats"
        try:
            import mnm_ledger_db

            mnm_ledger_db.OUT = data
            import build_ledger_site

            build_ledger_site.DATA = data
            build_ledger_site.SITE_STATS = site_stats
            import build_site

            build_site.DATA = data
            build_site.SITE = ws / "site"
            import mnm_ledger_upload

            mnm_ledger_upload.DATA = data
            import build_relations

            build_relations.DATA = data
            for attr in (
                "ITEMS_PATH",
                "MOBS_PATH",
                "LEDGER_DROPS_PATH",
                "CROWD_DROPS_PATH",
                "GAME_DB",
            ):
                if hasattr(build_relations, attr):
                    setattr(build_relations, attr, data / Path(getattr(build_relations, attr)).name)
        except Exception:  # pragma: no cover - best-effort retarget
            pass

    # --- UI --------------------------------------------------------------------
    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        self.status_var = tk.StringVar(value="Starting…")
        ttk.Label(top, textvariable=self.status_var, justify="left").pack(anchor="w")

        btns = ttk.Frame(self.root, padding=(10, 0))
        btns.pack(fill="x")
        self.buttons: dict[str, ttk.Button] = {}

        def add(key: str, label: str, cmd) -> None:
            b = ttk.Button(btns, text=label, command=cmd)
            b.pack(side="left", padx=4, pady=6)
            self.buttons[key] = b

        add("sync", "Sync now", lambda: self._run_async(self._do_sync, "sync"))
        add("mine", "Mine logs only", lambda: self._run_async(self._do_mine, "mining"))
        self.watch_btn = ttk.Button(btns, text="Start live watch", command=self._toggle_watch)
        self.watch_btn.pack(side="left", padx=4, pady=6)
        add("dashboard", "Open dashboard", self._open_dashboard)
        add("wiki_review", "Wiki review", self._open_wiki_review)
        add(
            "relations",
            "Rebuild DB",
            lambda: self._run_async(self._do_relations, "rebuilding relations"),
        )
        add("upload", "Submit data", lambda: self._run_async(self._do_upload, "uploading"))

        combat_row = ttk.LabelFrame(
            self.root, text="Combat capture (memory / OCR)", padding=(10, 6)
        )
        combat_row.pack(fill="x", padx=10, pady=(4, 0))
        combat_btns = ttk.Frame(combat_row)
        combat_btns.pack(fill="x")
        self.combat_btn = ttk.Button(
            combat_btns, text="Start combat capture", command=self._toggle_combat_capture
        )
        self.combat_btn.pack(side="left", padx=4, pady=2)
        ttk.Button(
            combat_btns,
            text="Test OCR once",
            command=lambda: self._run_async(self._do_combat_test, "combat test"),
        ).pack(side="left", padx=4)
        ttk.Button(combat_btns, text="Combat setup…", command=self._show_combat_setup).pack(
            side="left", padx=4
        )
        ttk.Button(combat_btns, text="Pick on screen…", command=self._pick_combat_region).pack(
            side="left", padx=4
        )
        ttk.Button(combat_btns, text="OCR streams…", command=self._manage_combat_streams).pack(
            side="left", padx=4
        )
        ttk.Button(combat_btns, text="Clear session", command=self._clear_combat_session).pack(
            side="left", padx=4
        )

        stats_frm = ttk.Frame(combat_row)
        stats_frm.pack(fill="x", pady=(6, 0))
        self.combat_stat_vars = {
            "status": tk.StringVar(value="Idle"),
            "dmg_out": tk.StringVar(value="0"),
            "dmg_in": tk.StringVar(value="0"),
            "heal_out": tk.StringVar(value="0"),
            "heal_in": tk.StringVar(value="0"),
            "events": tk.StringVar(value="0"),
            "pvp": tk.StringVar(value="0"),
        }
        for key, label in (
            ("status", "Status:"),
            ("dmg_out", "Damage out:"),
            ("dmg_in", "Damage in:"),
            ("heal_out", "Heal out:"),
            ("heal_in", "Heal in:"),
            ("events", "Events:"),
            ("pvp", "PvP hits:"),
        ):
            cell = ttk.Frame(stats_frm)
            cell.pack(side="left", padx=(0, 14))
            ttk.Label(cell, text=label, font=("", 9)).pack(anchor="w")
            ttk.Label(cell, textvariable=self.combat_stat_vars[key], font=("", 10, "bold")).pack(
                anchor="w"
            )

        btns2 = ttk.Frame(self.root, padding=(10, 0))
        btns2.pack(fill="x")
        ttk.Button(btns2, text="Settings…", command=self._open_settings).pack(side="left", padx=4)
        ttk.Button(
            btns2,
            text="Check for updates",
            command=lambda: self._run_async(self._do_update_check, "update check"),
        ).pack(side="left", padx=4)

        ttk.Separator(self.root).pack(fill="x", pady=8)
        logframe = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        logframe.pack(fill="both", expand=True)
        self.log = tk.Text(
            logframe,
            height=18,
            wrap="word",
            state="disabled",
            background="#101418",
            foreground="#d4dae0",
            insertbackground="#d4dae0",
        )
        scroll = ttk.Scrollbar(logframe, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._append("Ready. Mine your logs or start a live watch.\n")

    # --- helpers ---------------------------------------------------------------
    def _locallow(self) -> Path:
        if self.settings.get("locallow"):
            return Path(self.settings["locallow"])
        return default_locallow()

    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain_log(self) -> None:
        try:
            while True:
                self._append(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(120, self._drain_log)

    def _set_busy(self, busy: bool, what: str = "") -> None:
        self.busy = busy
        for b in self.buttons.values():
            b.configure(state="disabled" if busy else "normal")
        if busy:
            self.status_var.set(f"Working: {what}…")
        else:
            self._refresh_status()

    def _refresh_status(self) -> None:
        ll = self._locallow()
        found = ll.is_dir()
        servers = []
        if found:
            for p in ll.iterdir():
                if p.is_dir() and any((c / "Ledger").is_dir() for c in p.iterdir() if c.is_dir()):
                    servers.append(p.name)
            servers.sort()
        share = "ON" if self.settings.get("share_characters") else "off"
        upload = self.settings.get("upload_url") or "(not set)"
        cr = self.settings.get("combat_region") or self._combat_region()
        streams = self.settings.get("combat_streams") or []
        if streams:
            cr_txt = f"{len(streams)} stream(s) configured — OCR streams…"
        elif cr and cr.get("width"):
            cr_txt = f"{cr['left']},{cr['top']} {cr['width']}×{cr['height']}"
        else:
            cr_txt = "(not set — use OCR streams… or Pick on screen…)"
        if not streams and cr and cr.get("window_lock"):
            cr_txt += " [game window]"
        elif not streams and cr and self.settings.get("combat_window_lock"):
            cr_txt += " [screen — re-pick region to lock]"
        lines = [
            f"Logs: {ll}" + ("" if found else "  [NOT FOUND — set in Settings]"),
            f"Servers detected: {', '.join(servers) if servers else '(none yet)'}",
            f"Submit endpoint: {upload}    Share character names: {share}",
            f"Combat OCR: {cr_txt}",
            f"Workspace: {mnm_paths.workspace_dir()}",
        ]
        self.status_var.set("\n".join(lines))

    def _run_async(self, fn, what: str, quiet: bool = False) -> None:
        if self.busy:
            return
        self._set_busy(True, what)

        def worker():
            console = _Console(self.log_queue)
            try:
                with contextlib.redirect_stdout(console), contextlib.redirect_stderr(console):
                    fn()
            except Exception as exc:  # surface errors into the log
                self.log_queue.put(f"\n[ERROR] {exc}\n")
            finally:
                self.root.after(0, lambda: self._set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    # --- actions ---------------------------------------------------------------
    def _do_sync(self) -> None:
        locallow = self._locallow()
        if not locallow.is_dir():
            print(f"Logs folder not found: {locallow}\nSet it in Settings.")
            return
        print(f"Full sync from {locallow} …")
        from sync_manifest import print_report, run_sync

        report = run_sync(
            locallow=locallow,
            data_dir=mnm_paths.data_dir(),
            site_dir=mnm_paths.site_dir(),
            incremental=True,
            upload=bool(self.settings.get("upload_url")),
            client_re=False,
        )
        print_report(report)
        print("Done. Open dashboard or item browser to view updated data.")

    def _do_mine(self) -> None:
        locallow = self._locallow()
        if not locallow.is_dir():
            print(f"Logs folder not found: {locallow}\nSet it in Settings.")
            return
        print(f"Mining logs from {locallow} …")
        from mnm_ledger_db import run as extract_run

        stats = extract_run(locallow, ledger=True, journal=True)
        print(f"  {stats['files']:,} files, {stats['events']:,} events, {stats['kills']:,} kills")
        from build_ledger_site import main as build_stats

        build_stats()
        print("Done. Click 'Open dashboard' to view your stats.")

    def _do_relations(self) -> None:
        print("Rebuilding item/mob/drop relations (game.db) …")
        from build_relations import main as rel_main

        rel_main()
        print("Done.")

    def _do_upload(self) -> None:
        if not self.settings.get("upload_url"):
            print(
                "No submit endpoint configured. Set 'Submit endpoint URL' in Settings to contribute."
            )
            print("A privacy-gated payload was still written locally for inspection.")
        from mnm_ledger_upload import build_payload, upload_payload, write_payload

        payload = build_payload(share_characters=bool(self.settings.get("share_characters")))
        out = write_payload(payload)
        print(f"Built payload: {out} ({out.stat().st_size // 1024} KB, schema {payload['schema']})")
        url = self.settings.get("upload_url")
        if url:
            res = upload_payload(payload, url, self.settings.get("upload_token") or None)
            print(f"Upload -> HTTP {res['status_code']}")

    def _do_update_check(self) -> None:
        from mnm_updater import check_for_update

        info = check_for_update(self.settings.get("update_url", ""))
        if info.error:
            print(f"Update check: {info.error}")
            return
        if info.update_available:
            print(f"Update available: {info.current} -> {info.latest}")
            self.root.after(0, lambda: self._prompt_update(info))
        else:
            print(f"You are up to date (v{info.current}).")

    def _prompt_update(self, info) -> None:
        if (
            messagebox.askyesno(
                "Update available",
                f"v{info.latest} is available (you have v{info.current}).\n\n"
                f"{info.notes}\n\nOpen the download page?",
            )
            and info.url
        ):
            webbrowser.open(info.url)

    def _toggle_watch(self) -> None:
        if self._watch_thread and self._watch_thread.is_alive():
            self._watch_stop.set()
            self.watch_btn.configure(text="Start live watch")
            self._append("Live watch stopping…\n")
            return
        locallow = self._locallow()
        if not locallow.is_dir():
            messagebox.showerror("Logs not found", f"Set your logs folder in Settings.\n{locallow}")
            return
        self._watch_stop.clear()
        self.watch_btn.configure(text="Stop live watch")
        self._append("Live watch started — play the game; stats update live.\n")

        def loop():
            from mnm_ledger_watch import run as watch_run

            console = _Console(self.log_queue)
            while not self._watch_stop.is_set():
                try:
                    with contextlib.redirect_stdout(console), contextlib.redirect_stderr(console):
                        watch_run(
                            locallow,
                            interval=2.0,
                            gap_minutes=15.0,
                            backlog=False,
                            once=True,
                            rebuild=False,
                        )
                except Exception as exc:
                    self.log_queue.put(f"[watch error] {exc}\n")
                self._watch_stop.wait(2.0)
            self.log_queue.put("Live watch stopped.\n")

        self._watch_thread = threading.Thread(target=loop, daemon=True)
        self._watch_thread.start()

    def _combat_region(self) -> dict | None:
        if self.settings.get("combat_region"):
            r = self.settings["combat_region"]
            if isinstance(r, dict) and r.get("width") and r.get("height"):
                return r
        from mnm_chat_windows import load_layout

        layout = load_layout(self._locallow())
        return layout.get("combat_region_estimate")

    def _resolve_combat_streams(self) -> list[dict]:
        from mnm_combat_streams import resolve_capture_streams

        return resolve_capture_streams(self.settings, self._locallow())

    def _manage_combat_streams(self) -> None:
        from mnm_combat_filter_dialog import StreamManagerDialog

        existing = list(self.settings.get("combat_streams") or [])
        updated = StreamManagerDialog.manage(
            self.root,
            streams=existing,
            locallow=self._locallow(),
        )
        if updated is None:
            return
        self.settings["combat_streams"] = updated
        if len(updated) == 1:
            self.settings["combat_region"] = updated[0]["region"]
        mnm_paths.save_settings(self.settings)
        mnm_paths.apply_settings_to_env(self.settings)
        self._refresh_status()
        self._append(f"Combat OCR streams saved ({len(updated)}).\n")

    def _show_combat_setup(self) -> None:
        from mnm_chat_windows import load_layout, setup_recommendations
        from mnm_combat_channels import OCR_PRESETS
        from mnm_combat_ocr import available_backends
        from mnm_combat_streams import stream_summary

        layout = load_layout(self._locallow())
        tips = setup_recommendations(layout)
        est = layout.get("combat_region_estimate") or self.settings.get("combat_region")
        backends = (
            ", ".join(available_backends()) or "none — pip install -r requirements-combat.txt"
        )
        streams = self._resolve_combat_streams()
        stream_txt = stream_summary(streams) if streams else "(none — use OCR streams…)"
        preset_lines = []
        for key in ("meter", "pvp", "buffs", "casts"):
            p = OCR_PRESETS[key]
            preset_lines.append(f"  [{key}] {p['label']}")
            for step in p["steps"][:2]:
                preset_lines.append(f"      • {step}")
        msg = (
            f"Character: {layout.get('server')}/{layout.get('character')}\n"
            f"Combat channels: {layout.get('combat_channel_count')}\n"
            f"OCR backends: {backends}\n"
            f"Region: {est}\n"
            f"OCR streams: {stream_txt}\n\n"
            "Use OCR streams… to bind each chat window region to the same Combat > filters\n"
            "you enable in-game (or Import from game to read chats.json routing).\n\n"
            "Filter catalog: data/combat-filter-ui.json (from in-game Combat > flyouts)\n\n"
            "OCR presets (in-game filter toggles):\n"
            + "\n".join(preset_lines)
            + "\n\nUse OCR streams… for multi-window capture, or Pick on screen… for a single region.\n\n"
            + "\n".join(f"• {t}" for t in tips[:6])
        )
        messagebox.showinfo("Combat OCR setup", msg)

    def _pick_combat_region(
        self,
        cr_var: tk.StringVar | None = None,
        settings_dlg: tk.Toplevel | None = None,
    ) -> None:
        """Hide the panel, drag-select a screen rectangle, save as combat_region."""
        from mnm_region_selector import pick_screen_region, region_to_str

        if settings_dlg is not None:
            settings_dlg.grab_release()
        self.root.withdraw()
        self.root.update_idletasks()
        try:
            region = pick_screen_region(parent=self.root)
        finally:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            if settings_dlg is not None:
                settings_dlg.grab_set()

        if not region:
            return

        try:
            from mnm_game_window import attach_window_lock, game_window_status

            region = attach_window_lock(region)
            lock_note = (
                f" (locked to game window — {game_window_status()})"
                if region.get("window_lock")
                else " (screen pixels — game window not found)"
            )
        except ImportError:
            lock_note = ""

        self.settings["combat_region"] = region
        mnm_paths.save_settings(self.settings)
        mnm_paths.apply_settings_to_env(self.settings)
        if cr_var is not None:
            cr_var.set(region_to_str(region))
        self._refresh_status()
        self._append(f"Combat OCR region set: {region_to_str(region)}{lock_note}\n")

    def _clear_combat_session(self) -> None:
        if self._combat_thread and self._combat_thread.is_alive():
            messagebox.showwarning(
                "Combat OCR running",
                "Stop combat OCR before clearing session data.",
            )
            return
        if not messagebox.askyesno(
            "Clear combat session",
            "Reset combat-events.json, combat-live.json, and capture state?\n"
            "Damage/heal counters and parsed events will be deleted.",
        ):
            return
        from mnm_combat_watch import clear_combat_session

        clear_combat_session()
        for key in ("dmg_out", "dmg_in", "heal_out", "heal_in", "events"):
            self.combat_stat_vars[key].set("0")
        self.combat_stat_vars["status"].set("Idle")
        self._append("Combat OCR session cleared.\n")

    def _do_combat_test(self) -> None:
        streams = self._resolve_combat_streams()
        if not streams:
            print("No OCR streams — open OCR streams… or Pick on screen…")
            return
        stream = streams[0]
        region = stream["region"]
        from mnm_combat_ocr import available_backends, ocr_region_lines
        from mnm_combat_streams import allowed_channel_set, event_allowed
        from mnm_combat_text import parse_lines

        if not available_backends():
            print("OCR not available. pip install -r requirements-combat.txt")
            return
        backend = self.settings.get("combat_ocr_backend") or None
        window_lock = bool(self.settings.get("combat_window_lock", True))
        print(f"OCR test on stream '{stream.get('label')}' region {region} …")
        lines = ocr_region_lines(region, backend=backend, window_lock=window_lock)
        print(f"--- {len(lines)} OCR lines (top → bottom) ---")
        for i, line in enumerate(lines, 1):
            print(f"  {i:2}. {line}")
        events = parse_lines("\n".join(lines), stream_id=stream.get("id"))
        allowed = allowed_channel_set(stream)
        if allowed:
            events = [e for e in events if event_allowed(e, allowed)]
            print(f"--- parsed {len(events)} events after filter ({len(allowed)} channels) ---")
        else:
            print(f"--- parsed {len(events)} events (no channel filter) ---")
        for ev in events[:12]:
            print(
                f"  [{ev['kind']}] {ev.get('actor')} -> {ev.get('target')} {ev.get('amount') or ''}"
            )

    def _poll_combat_stats(self) -> None:
        """Refresh combat stat labels from data/combat-live.json while OCR runs."""
        from mnm_combat_watch import LIVE_PATH

        if self._combat_thread and self._combat_thread.is_alive():
            self.combat_stat_vars["status"].set("Capturing…")
            if LIVE_PATH.is_file():
                try:
                    import json

                    live = json.loads(LIVE_PATH.read_text(encoding="utf-8"))
                    self.combat_stat_vars["dmg_out"].set(str(live.get("damage_out", 0)))
                    self.combat_stat_vars["dmg_in"].set(str(live.get("damage_in", 0)))
                    self.combat_stat_vars["heal_out"].set(str(live.get("heal_out", 0)))
                    self.combat_stat_vars["heal_in"].set(str(live.get("heal_in", 0)))
                    self.combat_stat_vars["events"].set(str(live.get("event_count", 0)))
                    self.combat_stat_vars["pvp"].set(str(live.get("pvp_incoming_count", 0)))
                except (json.JSONDecodeError, OSError):
                    pass
            self._combat_stats_job = self.root.after(1000, self._poll_combat_stats)
        else:
            self.combat_stat_vars["status"].set("Idle")
            self._combat_stats_job = None

    def _start_combat_stats_poll(self) -> None:
        if self._combat_stats_job:
            self.root.after_cancel(self._combat_stats_job)
        self._poll_combat_stats()

    def _on_pvp_alert(self, event: dict, title: str, msg: str) -> None:
        """UI-thread handler: log + play alert sound."""
        from mnm_combat_pvp import play_alert_sound

        self.combat_stat_vars["status"].set("PvP!")
        self._append(f"\n*** {title}: {msg}\n")
        play_alert_sound(self.settings)
        self.root.bell()

    def _toggle_combat_capture(self) -> None:
        if self._combat_thread and self._combat_thread.is_alive():
            self._combat_stop.set()
            self.combat_btn.configure(text="Start combat capture")
            self.combat_stat_vars["status"].set("Stopping…")
            self._append("Combat capture stopping…\n")
            return

        from mnm_combat_watch import resolve_capture_backend

        capture_mode = self.settings.get("combat_capture") or "auto"
        backend_name = resolve_capture_backend(capture_mode)
        use_memory = backend_name == "memory"

        streams = self._resolve_combat_streams() if not use_memory else []
        if not use_memory and not streams:
            messagebox.showerror(
                "Combat region",
                "No OCR streams configured. Use OCR streams… to add a chat window region\n"
                "and match in-game Combat > filters, or Pick on screen… for a single region.\n\n"
                "Tip: start the game and use Settings → combat capture = auto for memory mode.",
            )
            return
        if not use_memory:
            try:
                from mnm_combat_ocr import available_backends

                if not available_backends():
                    messagebox.showerror(
                        "OCR not available",
                        "Install combat OCR deps:\n  pip install -r requirements-combat.txt",
                    )
                    return
            except ImportError as exc:
                messagebox.showerror("OCR not available", str(exc))
                return

        self._combat_stop.clear()
        self.combat_btn.configure(text="Stop combat capture")
        interval = float(self.settings.get("combat_ocr_interval") or 1.5)
        backend = self.settings.get("combat_ocr_backend") or None
        window_lock = bool(self.settings.get("combat_window_lock", True))
        lock_txt = "game window" if window_lock else "screen"
        self._start_combat_stats_poll()
        if use_memory:
            self._append(
                f"Combat memory capture started (Option F) — polling mnm.exe every "
                f"{min(interval, 1.0)}s\n"
            )
        elif len(streams) == 1:
            s = streams[0]
            region = s["region"]
            self._append(
                f"Combat OCR started — {lock_txt} '{s.get('label')}' "
                f"{region['left']},{region['top']} {region['width']}x{region['height']} "
                f"every {interval}s\n"
            )
        else:
            self._append(
                f"Combat OCR started — {lock_txt} {len(streams)} streams every {interval}s\n"
            )

        def loop():
            from mnm_combat_pvp import PvpAlerter
            from mnm_combat_streams import allowed_channel_set
            from mnm_combat_watch import run_memory_watch, run_multi_watch, run_watch

            console = _Console(self.log_queue)

            def on_pvp(ev, title, msg):
                self.root.after(0, lambda: self._on_pvp_alert(ev, title, msg))

            pvp_alerter = PvpAlerter(self.settings, on_alert=on_pvp)

            def on_ev(ev):
                if "error" in ev:
                    sid = ev.get("stream_id") or ""
                    prefix = f"[{sid}] " if sid else ""
                    console.write(f"{prefix}[combat ocr] {ev['error']}\n")
                elif ev.get("pvp_aggressive"):
                    console.write(
                        f"[PVP] {ev.get('actor')} -> {ev.get('target')} {ev.get('raw')}\n"
                    )
                else:
                    amt = ev.get("amount") or ""
                    sid = ev.get("stream_id") or ""
                    tag = f"[{sid}] " if sid else ""
                    console.write(
                        f"{tag}[{ev.get('kind')}] {ev.get('actor')} -> {ev.get('target')} {amt}\n"
                    )

            try:
                with contextlib.redirect_stdout(console), contextlib.redirect_stderr(console):
                    if use_memory:
                        run_memory_watch(
                            interval=min(interval, 1.0),
                            stop_event=self._combat_stop,
                            pvp_alerter=pvp_alerter,
                            on_event=on_ev,
                        )
                    elif len(streams) == 1:
                        s = streams[0]
                        run_watch(
                            s["region"],
                            interval=interval,
                            backend=backend,
                            window_lock=window_lock,
                            stream_id=s.get("id"),
                            allowed_channels=allowed_channel_set(s),
                            stop_event=self._combat_stop,
                            pvp_alerter=pvp_alerter,
                            on_event=on_ev,
                        )
                    else:
                        run_multi_watch(
                            streams,
                            interval=interval,
                            backend=backend,
                            window_lock=window_lock,
                            stop_event=self._combat_stop,
                            pvp_alerter=pvp_alerter,
                            on_event=on_ev,
                        )
            except Exception as exc:
                self.log_queue.put(f"[combat error] {exc}\n")
            self.log_queue.put("Combat capture stopped.\n")

        self._combat_thread = threading.Thread(target=loop, daemon=True)
        self._combat_thread.start()

    def _open_dashboard(self) -> None:
        ws = mnm_paths.workspace_dir()
        stats_index = ws / "site" / "stats" / "index.html"
        if not stats_index.exists():
            messagebox.showinfo("No dashboard yet", "Mine your logs first to build the dashboard.")
            return
        try:
            from build_combat_site import main as build_combat_site

            build_combat_site()
            self._append("Combat stats bundle refreshed for dashboard.\n")
        except Exception as exc:
            self._append(f"Combat stats bundle skipped: {exc}\n")
        port = self._ensure_http_server()
        if port is None:
            return
        webbrowser.open(f"http://127.0.0.1:{port}/site/stats/index.html")

    def _open_wiki_review(self) -> None:
        port = self._ensure_http_server()
        if port is None:
            return
        review = mnm_paths.workspace_dir() / "site" / "wiki-review" / "index.html"
        if not review.is_file():
            messagebox.showinfo(
                "No wiki fixes",
                "Run gen_wiki_loot_fixes.py first to generate fixes and the review UI.",
            )
            return
        webbrowser.open(f"http://127.0.0.1:{port}/site/wiki-review/index.html")

    def _ensure_http_server(self) -> int | None:
        ws = mnm_paths.workspace_dir()
        if self._httpd is None:
            self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_class(ws))
            threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
            self._append(f"Serving site at http://127.0.0.1:{self._httpd.server_address[1]}/\n")
        return self._httpd.server_address[1]

    # --- settings dialog -------------------------------------------------------
    def _open_settings(self) -> None:
        dlg = tk.Toplevel(self.root)
        dlg.title("Settings")
        dlg.transient(self.root)
        dlg.grab_set()
        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)

        vars_: dict[str, tk.Variable] = {}

        def row(r: int, label: str, key: str, browse: bool = False) -> None:
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=str(self.settings.get(key, "") or ""))
            vars_[key] = var
            ent = ttk.Entry(frm, textvariable=var, width=52)
            ent.grid(row=r, column=1, sticky="we", pady=4)
            if browse:
                ttk.Button(
                    frm,
                    text="Browse…",
                    command=lambda: var.set(filedialog.askdirectory() or var.get()),
                ).grid(row=r, column=2, padx=4)

        row(0, "Logs folder (LocalLow):", "locallow", browse=True)
        row(1, "Submit endpoint URL:", "upload_url")
        row(2, "Submit token (optional):", "upload_token")
        row(3, "Update manifest URL:", "update_url")
        cr = self.settings.get("combat_region") or {}
        ttk.Label(frm, text="Combat region (L,T,W,H):").grid(row=4, column=0, sticky="w", pady=4)
        cr_var = tk.StringVar(
            value=f"{cr.get('left', '')},{cr.get('top', '')},{cr.get('width', '')},{cr.get('height', '')}"
        )
        vars_["combat_region_str"] = cr_var
        ttk.Entry(frm, textvariable=cr_var, width=52).grid(row=4, column=1, sticky="we", pady=4)
        ttk.Button(
            frm, text="Estimate…", command=lambda: cr_var.set(self._estimate_region_str())
        ).grid(row=4, column=2, padx=4)
        ttk.Button(frm, text="Pick…", command=lambda: self._pick_combat_region(cr_var, dlg)).grid(
            row=4, column=3, padx=4
        )
        row(5, "Combat OCR interval (sec):", "combat_ocr_interval")
        cap_modes = ("auto", "memory", "ocr")
        cap_default = str(self.settings.get("combat_capture") or "auto")
        ttk.Label(frm, text="Combat capture mode:").grid(row=6, column=0, sticky="w", pady=4)
        cap_var = tk.StringVar(value=cap_default if cap_default in cap_modes else "auto")
        vars_["combat_capture"] = cap_var
        cap_combo = ttk.Combobox(
            frm, textvariable=cap_var, values=cap_modes, width=12, state="readonly"
        )
        cap_combo.grid(row=6, column=1, sticky="w", pady=4)

        win_lock_var = tk.BooleanVar(value=bool(self.settings.get("combat_window_lock", True)))
        vars_["combat_window_lock"] = win_lock_var
        ttk.Checkbutton(
            frm,
            text="Lock combat OCR to game window (ignores overlays on screen)",
            variable=win_lock_var,
        ).grid(row=7, column=0, columnspan=4, sticky="w", pady=4)

        pvp_var = tk.BooleanVar(value=bool(self.settings.get("pvp_alert_enabled", True)))
        vars_["pvp_alert_enabled"] = pvp_var
        ttk.Checkbutton(
            frm,
            text="Sound alert when a player hits you or your pet (PvP)",
            variable=pvp_var,
        ).grid(row=8, column=0, columnspan=4, sticky="w", pady=2)
        ttk.Label(frm, text="PvP alert sound (.wav):").grid(row=9, column=0, sticky="w", pady=4)
        pvp_snd_var = tk.StringVar(value=str(self.settings.get("pvp_alert_sound_path") or ""))
        vars_["pvp_alert_sound_path"] = pvp_snd_var
        ttk.Entry(frm, textvariable=pvp_snd_var, width=52).grid(
            row=9, column=1, sticky="we", pady=4
        )
        ttk.Button(
            frm,
            text="Browse…",
            command=lambda: pvp_snd_var.set(
                filedialog.askopenfilename(
                    filetypes=[("WAV files", "*.wav"), ("All files", "*.*")],
                )
                or pvp_snd_var.get()
            ),
        ).grid(row=9, column=2, padx=4)
        row(10, "PvP alert cooldown (sec):", "pvp_alert_cooldown")

        share_var = tk.BooleanVar(value=bool(self.settings.get("share_characters")))
        vars_["share_characters"] = share_var
        ttk.Checkbutton(
            frm, text="Share character names when submitting (off = anonymous)", variable=share_var
        ).grid(row=11, column=0, columnspan=3, sticky="w", pady=6)
        auto_var = tk.BooleanVar(value=bool(self.settings.get("auto_check_updates")))
        vars_["auto_check_updates"] = auto_var
        ttk.Checkbutton(frm, text="Check for updates on startup", variable=auto_var).grid(
            row=12, column=0, columnspan=3, sticky="w"
        )

        if not self.settings.get("locallow"):
            vars_["locallow"].set(str(default_locallow()))

        frm.columnconfigure(1, weight=1)

        def save():
            for key, var in vars_.items():
                if key == "combat_region_str":
                    continue
                if key == "combat_window_lock":
                    self.settings[key] = bool(var.get())
                    continue
                if key == "pvp_alert_enabled":
                    self.settings[key] = bool(var.get())
                    continue
                self.settings[key] = var.get()
            raw = vars_["combat_region_str"].get().strip()
            if raw:
                parts = [p.strip() for p in raw.split(",")]
                if len(parts) == 4 and all(p.lstrip("-").isdigit() for p in parts):
                    region = {
                        "left": int(parts[0]),
                        "top": int(parts[1]),
                        "width": int(parts[2]),
                        "height": int(parts[3]),
                        "source": "settings",
                    }
                    if vars_["combat_window_lock"].get():
                        try:
                            from mnm_game_window import attach_window_lock

                            region = attach_window_lock(region)
                        except ImportError:
                            region["window_lock"] = False
                    else:
                        region["window_lock"] = False
                    self.settings["combat_region"] = region
            mnm_paths.save_settings(self.settings)
            mnm_paths.apply_settings_to_env(self.settings)
            self._refresh_status()
            dlg.destroy()

        bar = ttk.Frame(frm)
        bar.grid(row=12, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(bar, text="Cancel", command=dlg.destroy).pack(side="right", padx=4)
        ttk.Button(bar, text="Save", command=save).pack(side="right")

    def _estimate_region_str(self) -> str:
        from mnm_chat_windows import load_layout

        est = load_layout(self._locallow()).get("combat_region_estimate")
        if not est:
            return ""
        return f"{est['left']},{est['top']},{est['width']},{est['height']}"

    def on_close(self) -> None:
        self._watch_stop.set()
        self._combat_stop.set()
        if self._combat_stats_job:
            self.root.after_cancel(self._combat_stats_job)
        if self._httpd:
            self._httpd.shutdown()
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    with contextlib.suppress(tk.TclError):
        ttk.Style().theme_use("clam")
    app = ClientApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
