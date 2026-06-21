#!/usr/bin/env python3
"""Client reverse-engineering pipeline for Monsters & Memories.

Phases implemented here (ledger parser is separate: ``mnm_ledger_db.py``):

  --fingerprint   Build ID from client game.db + DLL hashes
  --catalog       Index Addressable bundles (UnityPy + MnM header strip)
  --assets        Rank large MonoBehaviour blobs (data table candidates)
  --il2cpp        Metadata symbols + optional Il2CppDumper run
  --crosswalk     Ledger item_hid vs bundle plaintext scan + wiki names
  --all           Run all of the above

Usage:
    pip install -r requirements-client.txt
    python mnm_client_db.py --all
    python mnm_client_db.py --catalog --install "C:\\...\\mnm"

Set ``MNM_INSTALL`` to override the default install path.
Set ``MNM_IL2CPP_DUMPER`` to Il2CppDumper.exe for ``--il2cpp``.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from client_re.catalog_bundles import write_catalog
from client_re.crosswalk import write_crosswalk
from client_re.find_assets import write_candidates
from client_re.item_assets import write_item_assets
from client_re.il2cpp import write_il2cpp_report
from client_re.paths import DATA_CLIENT, ensure_out, install_root
from client_re.version import write_fingerprint
from client_re.watch_patch import archive_fingerprint, check_patch, load_previous

ROOT = Path(__file__).parent
STATUS_PATH = ROOT / "CLIENT-RE.md"


def _write_status(summary: dict) -> None:
    lines = [
        "# Client RE status",
        "",
        f"Last run: {summary.get('generated', '—')}",
        "",
        "## Outputs",
        "",
    ]
    for key, path in summary.get("outputs", {}).items():
        lines.append(f"- **{key}**: `{path}`")
    lines.extend(["", "## Summary", ""])
    for line in summary.get("lines", []):
        lines.append(f"- {line}")
    lines.extend([
        "",
        "## Next steps (manual)",
        "",
        "1. Install [Il2CppDumper](https://github.com/Perfare/Il2CppDumper); set `MNM_IL2CPP_DUMPER`.",
        "2. Import `client_re/dumps/il2cpp/script.json` into Ghidra with `GameAssembly.dll`.",
        "3. Trace `ChatLibrary` / `ChatMessageEntry` for Option F combat memory harvest.",
        "4. Run `python mnm_client_db.py --resolve-signatures` then `--verify-signatures`.",
        "",
    ])
    STATUS_PATH.write_text("\n".join(lines), encoding="utf-8")


def run_fingerprint(install: Path | None) -> tuple[Path, dict]:
    out = ensure_out() / "build-fingerprint.json"
    prev = load_previous()
    if prev:
        archive_fingerprint(prev)
    return out, write_fingerprint(out, install)


def run_catalog(install: Path | None) -> tuple[Path, dict]:
    out = ensure_out() / "bundle-index.json"
    return out, write_catalog(out, install)


def run_assets(install: Path | None) -> tuple[Path, dict]:
    out = ensure_out() / "asset-candidates.json"
    return out, write_candidates(out, install)


def run_il2cpp(install: Path | None) -> tuple[Path, dict]:
    out = ensure_out() / "il2cpp-report.json"
    return out, write_il2cpp_report(out, install)


def run_dump_metadata() -> tuple[Path, dict]:
    from client_re.dump_metadata import dump_metadata

    out = ensure_out() / "metadata-dump.json"
    doc = dump_metadata()
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return out, doc


def run_decrypt_metadata(install: Path | None) -> tuple[Path, dict]:
    from client_re.decrypt_metadata import decrypt_metadata_file

    out = ensure_out() / "metadata-decrypt.json"
    doc = decrypt_metadata_file(allow_partial=True)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return out, doc


def run_crosswalk(install: Path | None) -> tuple[Path, dict]:
    out = ensure_out() / "ids-crosswalk.json"
    return out, write_crosswalk(out, install)


def run_item_assets(install: Path | None, export_icons: bool) -> tuple[Path, dict]:
    out = ensure_out() / "item-assets.json"
    return out, write_item_assets(out, install, export_icons)


def main() -> int:
    ap = argparse.ArgumentParser(description="M&M client RE pipeline")
    ap.add_argument("--install", type=Path, help="Path to mnm install (contains mnm.exe)")
    ap.add_argument("--fingerprint", action="store_true")
    ap.add_argument("--catalog", action="store_true")
    ap.add_argument("--assets", action="store_true")
    ap.add_argument("--il2cpp", action="store_true")
    ap.add_argument("--dump-metadata", action="store_true", help="Scan running mnm.exe for decrypted metadata")
    ap.add_argument("--decrypt-metadata", action="store_true", help="Attempt static XOR decrypt of global-metadata.dat")
    ap.add_argument("--crosswalk", action="store_true")
    ap.add_argument("--item-assets", action="store_true", help="Catalog client icon sprites + equipment models")
    ap.add_argument("--export-icons", action="store_true", help="With --item-assets, dump icon PNGs to data/client/icons/")
    ap.add_argument("--patch", action="store_true", help="Compare install to last fingerprint before running")
    ap.add_argument("--verify-signatures", action="store_true", help="Verify combat memory signature cache")
    ap.add_argument("--resolve-signatures", action="store_true", help="Scan GameAssembly.dll and cache signatures")
    ap.add_argument("--mnmlib-types", action="store_true", help="Regenerate client_re/mnmlib/types.json from metadata")
    ap.add_argument("--discover-combat-struct", action="store_true", help="Discover ChatMessageEntry queue from live memory")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if args.all:
        args.patch = args.fingerprint = args.catalog = args.assets = args.il2cpp = args.crosswalk = args.item_assets = True

    if not any((
        args.patch, args.fingerprint, args.catalog, args.assets, args.il2cpp,
        args.dump_metadata, args.decrypt_metadata, args.crosswalk, args.item_assets,
        args.verify_signatures, args.resolve_signatures, args.mnmlib_types,
        args.combat_memory_status, args.discover_combat_struct,
    )):
        ap.print_help()
        return 1

    install = install_root(args.install)
    outputs: dict[str, str] = {}
    lines: list[str] = []

    if args.patch or args.all:
        patch = check_patch(install)
        patch_path = ensure_out() / "patch-report.json"
        patch_path.write_text(json.dumps(patch, indent=2), encoding="utf-8")
        outputs["patch"] = str(patch_path.relative_to(ROOT))
        if patch.get("patched"):
            for ch in patch["changes"]:
                lines.append(f"PATCH: {ch}")
            print("Launcher patch detected:")
            for ch in patch["changes"]:
                print(f"  - {ch}")
            # stale decrypted metadata must not be reused
            stale = ROOT / "client_re" / "dumps" / "il2cpp" / "global-metadata.decrypted.dat"
            if stale.is_file():
                stale.unlink()
                print("  Cleared stale decrypted metadata cache")
            sig = archive_signature_cache(load_previous() or {})
            if sig:
                print(f"  Archived stale signature cache -> {sig}")
        else:
            print("No fingerprint changes since last run.")
        print(f"Wrote {patch_path}")

    if args.fingerprint:
        path, doc = run_fingerprint(install)
        outputs["fingerprint"] = str(path.relative_to(ROOT))
        lines.append(
            f"Fingerprint: {doc['manifest_entries']} manifest entries, "
            f"Unity {doc.get('unity_version', '?')}"
        )
        print(f"Wrote {path}")

    if args.catalog:
        path, doc = run_catalog(install)
        outputs["catalog"] = str(path.relative_to(ROOT))
        top = doc["scanned_files"][0] if doc["scanned_files"] else {}
        data_bundles = [
            f for f in doc["scanned_files"]
            if f.get("category") not in ("zone", "bundle_other")
        ]
        if data_bundles:
            top = max(data_bundles, key=lambda f: f.get("mono_behaviour_count", 0))
        lines.append(
            f"Catalog: {len(doc['scanned_files'])} Unity files, "
            f"lead data bundle = {top.get('name', '?')} "
            f"({top.get('mono_behaviour_count', 0)} MonoBehaviours)"
        )
        print(f"Wrote {path}")

    if args.assets:
        path, doc = run_assets(install)
        outputs["assets"] = str(path.relative_to(ROOT))
        top = doc["top_overall"][0] if doc.get("top_overall") else {}
        lines.append(
            f"Asset candidates: largest MonoBehaviour {top.get('size', 0):,} bytes "
            f"in {top.get('file', '?')}"
        )
        print(f"Wrote {path}")

    if args.il2cpp:
        path, doc = run_il2cpp(install)
        outputs["il2cpp"] = str(path.relative_to(ROOT))
        sym = doc["symbols"]
        dumper = doc["dumper"]
        ok = dumper.get("ran") and not dumper.get("error") and (ROOT / "client_re" / "dumps" / "il2cpp" / "dump.cs").is_file()
        lines.append(
            f"IL2CPP: {len(sym['priority_hits'])} priority symbols; "
            f"dump.cs {'written' if ok else 'not produced (encrypted on-disk metadata)'}"
        )
        if dumper.get("error"):
            print(f"  il2cpp note: {dumper['error']}")
        if dumper.get("stdout"):
            tail = dumper["stdout"].strip().splitlines()[-1]
            if tail:
                print(f"  il2cpp: {tail}")
        print(f"Wrote {path}")

    if args.dump_metadata:
        path, doc = run_dump_metadata()
        outputs["metadata_dump"] = str(path.relative_to(ROOT))
        if doc.get("ran"):
            lines.append(f"Metadata dump: {doc.get('source', '?')} at {doc.get('address', '?')}")
            if doc.get("decrypt", {}).get("partial"):
                lines.append("Metadata decrypt: partial (magic only; Il2CppDumper still blocked)")
        else:
            lines.append(f"Metadata dump failed: {doc.get('error', '?')}")
            print(f"  metadata: {doc.get('error')}")
        print(f"Wrote {path}")

    if args.decrypt_metadata:
        path, doc = run_decrypt_metadata(install)
        outputs["metadata_decrypt"] = str(path.relative_to(ROOT))
        if doc.get("success"):
            lines.append(f"Metadata decrypt: full success (v{doc.get('version', '?')})")
        elif doc.get("partial"):
            lines.append("Metadata decrypt: partial XOR — magic restored, header still invalid")
        else:
            lines.append(f"Metadata decrypt failed: {doc.get('error', '?')}")
        print(f"Wrote {path}")
        if doc.get("output"):
            print(f"  output: {doc['output']}")

    if args.crosswalk:
        path, doc = run_crosswalk(install)
        outputs["crosswalk"] = str(path.relative_to(ROOT))
        lines.append(
            f"Crosswalk: {doc['ledger_items']} ledger items, "
            f"{doc['plaintext_hid_hits']} plaintext bundle hits, "
            f"{doc['wiki_name_matches']} wiki name matches"
        )
        print(f"Wrote {path}")

    if args.item_assets:
        path, doc = run_item_assets(install, args.export_icons)
        outputs["item_assets"] = str(path.relative_to(ROOT))
        c = doc["counts"]
        lines.append(
            f"Item assets: {c['icon_sprites']} icons, {c['item_models']} models, "
            f"{c['icons_matched_to_wiki']} icons fuzzy-matched to wiki"
            + (" (PNGs exported)" if args.export_icons else "")
        )
        print(f"Wrote {path}")

    if args.mnmlib_types:
        from client_re.mnmlib.types import generate_types_catalog

        doc = generate_types_catalog()
        out = ROOT / "client_re" / "mnmlib" / "types.json"
        outputs["mnmlib_types"] = str(out.relative_to(ROOT))
        lines.append(
            f"mnmlib: {doc['metadata']['combat_type_count']} combat types, "
            f"{len(doc['metadata']['priority_hits'])} priority hits"
        )
        print(f"Wrote {out}")

    if args.resolve_signatures:
        from client_re.signatures import resolve_signatures

        doc = resolve_signatures(install)
        outputs["signatures"] = doc.get("cache_path", "data/client/signatures-*.json")
        hits = sum(1 for e in doc.get("resolved") or [] if e.get("ok"))
        lines.append(f"Signatures resolved: {hits} patterns OK")
        print(f"Wrote signature cache ({hits} hits)")

    if args.verify_signatures:
        from client_re.signatures import verify_signatures

        doc = verify_signatures(install)
        path = ensure_out() / "signature-verify.json"
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        outputs["signature_verify"] = str(path.relative_to(ROOT))
        state = "ready" if doc.get("ready") else "stale"
        lines.append(f"Signature verify: {state} — {', '.join(doc.get('reasons') or ['ok'])}")
        print(f"Signatures {state}")
        if doc.get("reasons"):
            for r in doc["reasons"]:
                print(f"  - {r}")
        print(f"Wrote {path}")

    if args.discover_combat_struct:
        from client_re.discover_combat_struct import discover_and_apply

        doc = discover_and_apply()
        path = ensure_out() / "combat-struct-discovery.json"
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        outputs["combat_struct_discovery"] = str(path.relative_to(ROOT))
        if doc.get("success"):
            lines.append(
                f"Structured RE: enabled text_off={doc.get('text_offset')} "
                f"list={doc.get('list_ptr')} score={doc.get('score')}"
            )
        else:
            lines.append(f"Structured RE failed: {doc.get('error', '?')}")
        print(json.dumps(doc, indent=2))
        print(f"Wrote {path}")

    if args.combat_memory_status:
        from client_re.combat_memory import memory_capture_status

        doc = memory_capture_status(install)
        path = ensure_out() / "combat-memory-status.json"
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        outputs["combat_memory_status"] = str(path.relative_to(ROOT))
        lines.append(
            f"Combat memory: mode={doc.get('recommended_mode')}, "
            f"running={doc.get('process_running')}, ready={doc.get('signatures_ready')}"
        )
        print(json.dumps(doc, indent=2))
        print(f"Wrote {path}")

    summary = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "install_root": str(install),
        "outputs": outputs,
        "lines": lines,
    }
    (ensure_out() / "client-re-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    _write_status(summary)
    print(f"Updated {STATUS_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
