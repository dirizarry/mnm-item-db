"""Tk dialogs for combat OCR stream management and in-game filter selection."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from mnm_combat_channels import OCR_PRESETS, WINDOW_ROLES, build_filter_menu
from mnm_combat_streams import (
    channels_for_preset,
    channels_for_role,
    filter_paths_from_channels,
    import_window_channels,
    iter_filter_leaves,
    new_stream_id,
    normalize_stream,
)
from mnm_region_selector import pick_screen_region, region_to_str


class FilterPickerDialog(tk.Toplevel):
    """Checkbox tree mirroring in-game Combat > filter flyouts."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        selected_paths: set[str] | None = None,
        selected_channels: set[str] | None = None,
        on_apply: Callable[[set[str], list[str]], None] | None = None,
        title: str = "Combat filters",
    ):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.grab_set()
        self.geometry("520x520")
        self.minsize(420, 360)
        self._on_apply = on_apply
        self._menu = build_filter_menu()
        self._leaf_paths: dict[str, list[str]] = {}
        self._path_vars: dict[str, tk.BooleanVar] = {}

        if selected_paths:
            initial = set(selected_paths)
        elif selected_channels:
            initial = filter_paths_from_channels(selected_channels, self._menu)
        else:
            initial = set()

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(
            top,
            text="Match the toggles from Right-click chat window → Combat >",
            wraplength=480,
        ).pack(anchor="w")

        preset_row = ttk.Frame(top)
        preset_row.pack(fill="x", pady=(6, 0))
        ttk.Label(preset_row, text="Preset:").pack(side="left")
        self._preset_var = tk.StringVar(value="meter")
        preset_cb = ttk.Combobox(
            preset_row,
            textvariable=self._preset_var,
            values=list(OCR_PRESETS.keys()),
            state="readonly",
            width=14,
        )
        preset_cb.pack(side="left", padx=4)
        ttk.Button(preset_row, text="Apply preset", command=self._apply_preset).pack(
            side="left", padx=4
        )

        tree_frm = ttk.Frame(self, padding=(8, 4))
        tree_frm.pack(fill="both", expand=True)
        self._tree = ttk.Treeview(tree_frm, show="tree", selectmode="none")
        scroll = ttk.Scrollbar(tree_frm, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self._build_tree(initial)

        self._tree.bind("<Button-1>", self._on_tree_click, add="+")

        summary = ttk.Frame(self, padding=8)
        summary.pack(fill="x")
        self._summary_var = tk.StringVar()
        ttk.Label(summary, textvariable=self._summary_var).pack(anchor="w")
        self._update_summary()

        btns = ttk.Frame(self, padding=8)
        btns.pack(fill="x")
        ttk.Button(btns, text="Select all", command=self._select_all).pack(side="left", padx=4)
        ttk.Button(btns, text="Clear", command=self._clear_all).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="OK", command=self._ok).pack(side="right", padx=4)

    def _build_tree(self, initial: set[str]) -> None:
        groups: dict[str, str] = {}
        for path_id, label, chs in iter_filter_leaves(self._menu):
            self._leaf_paths[path_id] = chs
            parts = path_id.split(":")
            group_key = parts[0]
            group_label = {
                "death": "Death",
                "pet": "Pet",
                "los": "Line of Sight",
                "melee": "Melee",
                "ability": "Ability",
                "spell": "Spell",
            }.get(group_key, group_key.title())
            if group_key not in groups:
                groups[group_key] = self._tree.insert("", "end", text=group_label, open=True)
            parent = groups[group_key]
            if len(parts) > 2:
                mid_key = f"{group_key}:{parts[1]}"
                if mid_key not in groups:
                    mid_label = parts[1].replace("_", " ")
                    groups[mid_key] = self._tree.insert(parent, "end", text=mid_label, open=False)
                parent = groups[mid_key]
            checked = path_id in initial
            var = tk.BooleanVar(value=checked)
            self._path_vars[path_id] = var
            display = f"{'☑' if checked else '☐'}  {label.split(' → ')[-1]}"
            self._tree.insert(parent, "end", iid=path_id, text=display)

    def _on_tree_click(self, event) -> str | None:
        row = self._tree.identify_row(event.y)
        if not row or row not in self._path_vars:
            return None
        var = self._path_vars[row]
        var.set(not var.get())
        self._tree.item(
            row,
            text=f"{'☑' if var.get() else '☐'}  {self._tree.item(row, 'text').split('  ', 1)[-1]}",
        )
        self._update_summary()
        return "break"

    def _selected_paths(self) -> set[str]:
        return {pid for pid, var in self._path_vars.items() if var.get()}

    def _selected_channels(self) -> list[str]:
        from mnm_combat_streams import channels_from_filter_paths

        return channels_from_filter_paths(self._selected_paths(), self._menu)

    def _update_summary(self) -> None:
        chs = self._selected_channels()
        self._summary_var.set(
            f"{len(self._selected_paths())} toggles → {len(chs)} channel categories"
        )

    def _select_all(self) -> None:
        for pid, var in self._path_vars.items():
            var.set(True)
            self._tree.item(pid, text=f"☑  {self._tree.item(pid, 'text').split('  ', 1)[-1]}")
        self._update_summary()

    def _clear_all(self) -> None:
        for pid, var in self._path_vars.items():
            var.set(False)
            self._tree.item(pid, text=f"☐  {self._tree.item(pid, 'text').split('  ', 1)[-1]}")
        self._update_summary()

    def _apply_preset(self) -> None:
        key = self._preset_var.get()
        chs = set(channels_for_preset(key))
        paths = filter_paths_from_channels(chs, self._menu)
        self._clear_all()
        for pid in paths:
            if pid in self._path_vars:
                self._path_vars[pid].set(True)
                self._tree.item(pid, text=f"☑  {self._tree.item(pid, 'text').split('  ', 1)[-1]}")
        self._update_summary()

    def _ok(self) -> None:
        paths = self._selected_paths()
        chs = self._selected_channels()
        if self._on_apply:
            self._on_apply(paths, chs)
        self.destroy()

    @classmethod
    def pick(
        cls,
        master: tk.Misc,
        *,
        selected_paths: set[str] | None = None,
        selected_channels: set[str] | None = None,
    ) -> tuple[set[str], list[str]] | None:
        result: dict = {}

        def on_apply(paths, chs):
            result["paths"] = paths
            result["channels"] = chs

        dlg = cls(
            master,
            selected_paths=selected_paths,
            selected_channels=selected_channels,
            on_apply=on_apply,
        )
        master.wait_window(dlg)
        if "paths" in result:
            return result["paths"], result["channels"]
        return None


class StreamEditorDialog(tk.Toplevel):
    """Edit one OCR stream: label, window id, region, filters."""

    def __init__(
        self,
        master: tk.Misc,
        stream: dict,
        *,
        window_ids: list[str],
        locallow,
        on_save: Callable[[dict], None],
    ):
        super().__init__(master)
        self.title("OCR stream")
        self.transient(master)
        self.grab_set()
        self._locallow = locallow
        self._on_save = on_save
        self._stream = dict(stream)
        self._filter_paths = set(stream.get("filter_paths") or [])
        self._channels = list(stream.get("channels") or [])

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Label:").grid(row=0, column=0, sticky="w", pady=4)
        self._label_var = tk.StringVar(value=stream.get("label") or "Combat")
        ttk.Entry(frm, textvariable=self._label_var, width=36).grid(
            row=0, column=1, columnspan=2, sticky="we"
        )

        ttk.Label(frm, text="In-game window id:").grid(row=1, column=0, sticky="w", pady=4)
        self._window_var = tk.StringVar(value=stream.get("window_id") or "combat")
        ids = window_ids or ["combat", "chat0", "chat1", "combat2", "combat3"]
        ttk.Combobox(frm, textvariable=self._window_var, values=ids, width=18).grid(
            row=1,
            column=1,
            sticky="w",
            pady=4,
        )

        ttk.Label(frm, text="Role preset:").grid(row=2, column=0, sticky="w", pady=4)
        self._role_var = tk.StringVar(value=stream.get("role") or "meter")
        ttk.Combobox(
            frm,
            textvariable=self._role_var,
            values=list(WINDOW_ROLES.keys()),
            state="readonly",
            width=18,
        ).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Button(frm, text="Use role channels", command=self._use_role).grid(
            row=2, column=2, padx=4
        )

        ttk.Label(frm, text="Region:").grid(row=3, column=0, sticky="w", pady=4)
        region = stream.get("region") or {}
        self._region_var = tk.StringVar(value=region_to_str(region) if region.get("width") else "")
        ttk.Entry(frm, textvariable=self._region_var, width=36).grid(
            row=3, column=1, sticky="we", pady=4
        )
        ttk.Button(frm, text="Pick…", command=self._pick_region).grid(row=3, column=2, padx=4)

        filt_row = ttk.Frame(frm)
        filt_row.grid(row=4, column=0, columnspan=3, sticky="we", pady=(8, 4))
        self._filt_summary = tk.StringVar(value=self._filter_summary())
        ttk.Label(filt_row, textvariable=self._filt_summary, wraplength=420).pack(anchor="w")
        filt_btns = ttk.Frame(frm)
        filt_btns.grid(row=5, column=0, columnspan=3, sticky="w")
        ttk.Button(filt_btns, text="Combat filters…", command=self._edit_filters).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(filt_btns, text="Import from game", command=self._import_game).pack(
            side="left", padx=4
        )

        btns = ttk.Frame(frm, padding=(0, 8))
        btns.grid(row=6, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save", command=self._save).pack(side="right", padx=4)

        frm.columnconfigure(1, weight=1)

    def _filter_summary(self) -> str:
        n = len(self._channels)
        if n:
            return f"{n} channel categories selected (matches in-game Combat > toggles)"
        return "No filters — all parsed lines accepted (use Import from game or Combat filters…)"

    def _use_role(self) -> None:
        self._channels = channels_for_role(self._role_var.get())
        self._filter_paths = filter_paths_from_channels(set(self._channels))
        self._filt_summary.set(self._filter_summary())

    def _edit_filters(self) -> None:
        def on_apply(paths, chs):
            self._filter_paths = paths
            self._channels = chs
            self._filt_summary.set(self._filter_summary())

        FilterPickerDialog(
            self,
            selected_paths=self._filter_paths,
            selected_channels=set(self._channels),
            on_apply=on_apply,
        )

    def _import_game(self) -> None:
        wid = self._window_var.get().strip() or "combat"
        chs = import_window_channels(self._locallow, wid)
        if not chs:
            messagebox.showwarning(
                "Import from game",
                f"No channels routed to window '{wid}' in chats.json.\n"
                "Configure routing in-game first, or pick filters manually.",
                parent=self,
            )
            return
        self._channels = chs
        self._filter_paths = filter_paths_from_channels(set(chs))
        self._filt_summary.set(self._filter_summary())

    def _pick_region(self) -> None:
        self.grab_release()
        master = self.master
        if hasattr(master, "withdraw"):
            master.withdraw()
        try:
            region = pick_screen_region(parent=master)
        finally:
            if hasattr(master, "deiconify"):
                master.deiconify()
            self.grab_set()
        if not region:
            return
        try:
            from mnm_game_window import attach_window_lock

            region = attach_window_lock(region)
        except ImportError:
            pass
        self._stream["region"] = region
        self._region_var.set(region_to_str(region))

    def _parse_region(self) -> dict | None:
        if self._stream.get("region") and self._stream["region"].get("width"):
            return self._stream["region"]
        raw = self._region_var.get().strip()
        if not raw:
            return None
        parts = raw.replace(",", " ").split()
        if len(parts) < 4:
            return None
        try:
            left, top, width, height = (int(float(x)) for x in parts[:4])
        except ValueError:
            return None
        return {"left": left, "top": top, "width": width, "height": height, "source": "manual"}

    def _save(self) -> None:
        region = self._parse_region()
        if not region:
            messagebox.showerror(
                "Region required", "Pick a screen region for this stream.", parent=self
            )
            return
        out = {
            "id": self._stream.get("id") or new_stream_id(),
            "label": self._label_var.get().strip() or "Combat",
            "window_id": self._window_var.get().strip() or "combat",
            "role": self._role_var.get() or None,
            "region": region,
            "channels": list(self._channels),
            "filter_paths": sorted(self._filter_paths),
        }
        norm = normalize_stream(out)
        if not norm:
            messagebox.showerror(
                "Invalid stream", "Could not save stream configuration.", parent=self
            )
            return
        self._on_save(norm)
        self.destroy()


class StreamManagerDialog(tk.Toplevel):
    """Manage combat_streams[] — add, edit, remove OCR regions."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        streams: list[dict],
        locallow,
        on_save: Callable[[list[dict]], None],
    ):
        super().__init__(master)
        self.title("Combat OCR streams")
        self.transient(master)
        self.grab_set()
        self.geometry("640x360")
        self._locallow = locallow
        self._on_save = on_save
        self._streams = [dict(s) for s in streams]

        ttk.Label(
            self,
            text="One OCR region per in-game chat window. Filters should match Combat > toggles for that window.",
            wraplength=600,
            padding=(10, 8),
        ).pack(anchor="w")

        cols = ("label", "window", "region", "filters")
        self._tree = ttk.Treeview(self, columns=cols, show="headings", height=10)
        for col, w in zip(cols, (140, 80, 200, 80), strict=False):
            self._tree.heading(col, text=col.title())
            self._tree.column(col, width=w, anchor="w")
        self._tree.pack(fill="both", expand=True, padx=10, pady=4)
        self._refresh_list()

        btns = ttk.Frame(self, padding=10)
        btns.pack(fill="x")
        ttk.Button(btns, text="Add…", command=self._add).pack(side="left", padx=4)
        ttk.Button(btns, text="Edit…", command=self._edit).pack(side="left", padx=4)
        ttk.Button(btns, text="Remove", command=self._remove).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save", command=self._save_all).pack(side="right", padx=4)

        self._window_ids = self._load_window_ids()

    def _load_window_ids(self) -> list[str]:
        from mnm_chat_windows import load_layout

        layout = load_layout(self._locallow)
        ids = list(layout.get("identifiers") or [])
        for default in ("combat", "combat2", "combat3", "chat0", "chat1"):
            if default not in ids:
                ids.append(default)
        return ids

    def _refresh_list(self) -> None:
        self._tree.delete(*self._tree.get_children())
        for s in self._streams:
            r = s.get("region") or {}
            reg = region_to_str(r) if r.get("width") else "(none)"
            n = len(s.get("channels") or [])
            filt = str(n) if n else "all"
            self._tree.insert(
                "",
                "end",
                iid=s.get("id") or new_stream_id(),
                values=(s.get("label"), s.get("window_id"), reg, filt),
            )

    def _selected_index(self) -> int | None:
        sel = self._tree.selection()
        if not sel:
            return None
        sid = sel[0]
        for i, s in enumerate(self._streams):
            if s.get("id") == sid:
                return i
        return None

    def _add(self) -> None:
        blank = {
            "id": new_stream_id(),
            "label": f"Stream {len(self._streams) + 1}",
            "window_id": "combat",
            "role": "meter",
            "region": {},
            "channels": [],
            "filter_paths": [],
        }
        self._open_editor(blank, is_new=True)

    def _edit(self) -> None:
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("Select stream", "Choose a stream to edit.", parent=self)
            return
        self._open_editor(self._streams[idx], is_new=False)

    def _open_editor(self, stream: dict, *, is_new: bool) -> None:
        def on_save(updated: dict) -> None:
            if is_new:
                self._streams.append(updated)
            else:
                for i, s in enumerate(self._streams):
                    if s.get("id") == stream.get("id"):
                        self._streams[i] = updated
                        break
            self._refresh_list()

        StreamEditorDialog(
            self,
            stream,
            window_ids=self._window_ids,
            locallow=self._locallow,
            on_save=on_save,
        )

    def _remove(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        if messagebox.askyesno("Remove stream", "Remove this OCR stream?", parent=self):
            self._streams.pop(idx)
            self._refresh_list()

    def _save_all(self) -> None:
        valid = []
        for raw in self._streams:
            norm = normalize_stream(raw)
            if norm:
                valid.append(norm)
        self._on_save(valid)
        self.destroy()

    @classmethod
    def manage(cls, master: tk.Misc, *, streams: list[dict], locallow) -> list[dict] | None:
        result: dict = {}

        def on_save(updated):
            result["streams"] = updated

        dlg = cls(master, streams=streams, locallow=locallow, on_save=on_save)
        master.wait_window(dlg)
        return result.get("streams")
