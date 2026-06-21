# Client RE status

Last run: 2026-06-21T00:42:03.624595+00:00

## Outputs

- **fingerprint**: `data\client\build-fingerprint.json`
- **mnmlib_types**: `client_re\mnmlib\types.json`
- **signatures**: `data\client\signatures-d57400cb5e626ad0.json`

## Summary

- Fingerprint: 235 manifest entries, Unity 6000.0.59f2
- mnmlib: 390 combat types, 18 priority hits
- Signatures resolved: 4 patterns OK

## Next steps (manual)

1. Install [Il2CppDumper](https://github.com/Perfare/Il2CppDumper); set `MNM_IL2CPP_DUMPER`.
2. Import `client_re/dumps/il2cpp/script.json` into Ghidra with `GameAssembly.dll`.
3. Trace `ChatLibrary` / `ChatMessageEntry` for Option F combat memory harvest.
4. Run `python mnm_client_db.py --resolve-signatures` then `--verify-signatures`.
