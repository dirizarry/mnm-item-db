"""Decrypt XOR-obfuscated global-metadata.dat (disunity-style recovery)."""

from __future__ import annotations

import struct
from collections import Counter
from pathlib import Path

from client_re.paths import ensure_dumps, il2cpp_metadata

METADATA_MAGIC = 0xFAB11BAF
KNOWN_STRINGS = (
    b"System",
    b"mscorlib",
    b"UnityEngine",
    b"Void",
    b"Object",
    b"String",
    b"Int32",
    b".ctor",
)


def _decrypt_partial(data: bytes, key: bytes) -> bytes:
    key_len = len(key)
    out = bytearray(data)
    for i in range(7, len(data)):
        out[i] = data[i] ^ key[i % key_len]
    return bytes(out)


def _decrypt_full(data: bytes, key: bytes) -> bytes:
    key_len = len(key)
    return bytes(data[i] ^ key[i % key_len] for i in range(len(data)))


def _quick_validate_v35_header(data: bytes) -> bool:
    if len(data) < 32:
        return False
    magic, version = struct.unpack_from("<II", data, 0)
    if magic != METADATA_MAGIC or not (24 <= version <= 106):
        return False
    string_offset, string_size = struct.unpack_from("<II", data, 24)
    if string_offset == 0 or string_offset + string_size > len(data):
        return False
    return True


def _quick_validate_v39_header(data: bytes) -> bool:
    if len(data) < 380:
        return False
    magic, version = struct.unpack_from("<II", data, 0)
    if magic != METADATA_MAGIC or not (38 <= version <= 41):
        return False
    ok = 0
    for pos in range(8, 8 + 31 * 12, 12):
        offset, size, count = struct.unpack_from("<III", data, pos)
        if 0 < offset < len(data) and 0 < size < len(data) and count < 50_000_000:
            ok += 1
    return ok >= 20


def _validate_strings(data: bytes, string_offset: int, string_size: int) -> bool:
    end = min(string_offset + string_size, len(data), string_offset + 50 * 1024)
    if end <= string_offset:
        return False
    chunk = data[string_offset:end]
    found = sum(1 for s in KNOWN_STRINGS if s in chunk)
    return found >= 4


def _validate_decrypted(data: bytes) -> bool:
    if _quick_validate_v39_header(data):
        off, size, _ = struct.unpack_from("<III", data, 8 + 2 * 12)  # strings section
        return _validate_strings(data, off, size)
    if not _quick_validate_v35_header(data):
        return False
    _, _, string_offset, string_size = struct.unpack_from("<IIII", data, 16)
    return _validate_strings(data, string_offset, string_size)


def _kasiski_key_length(data: bytes, max_len: int = 32) -> int:
    # 3-gram repeats in ciphertext (skip tiny prefixes)
    distances: list[int] = []
    grams: dict[bytes, int] = {}
    start = 0 if struct.unpack_from("<I", data, 0)[0] != METADATA_MAGIC else 7
    for i in range(start, min(len(data) - 3, 65536)):
        g = data[i : i + 3]
        if g in grams:
            d = i - grams[g]
            if 2 <= d <= max_len * 8:
                distances.append(d)
        grams[g] = i
    if not distances:
        return 0
    from math import gcd
    from functools import reduce

    g = reduce(gcd, distances[:50], distances[0])
    for prefer in (8, 16, 4, 12, 32, 24):
        if g % prefer == 0 and 4 <= prefer <= max_len:
            return prefer
    return g if 4 <= g <= max_len else 8


def _freq_key_byte(data: bytes, key_len: int, pos: int, start: int) -> int:
    counts = Counter(data[i] for i in range(start + pos, min(len(data), 65536), key_len))
    if not counts:
        return 0
    return counts.most_common(1)[0][0]


def _try_key_length_full(data: bytes, key_len: int) -> tuple[bytes, bytes] | None:
    magic_bytes = struct.pack("<I", METADATA_MAGIC)
    key = bytearray(key_len)
    known = [False] * key_len
    for i in range(4):
        pos = i % key_len
        key[pos] = data[i] ^ magic_bytes[i]
        known[pos] = True
    pos7 = 7 % key_len
    key[pos7] = data[7] ^ 0x00
    known[pos7] = True

    test = _decrypt_full(data[:32], bytes(key))
    version = struct.unpack_from("<I", test, 4)[0]
    if version < 20 or version > 106:
        return None

    for pos in range(key_len):
        if not known[pos]:
            key[pos] = _freq_key_byte(data, key_len, pos, 0)

    decrypted = _decrypt_full(data, bytes(key))
    if _validate_decrypted(decrypted):
        return bytes(key), decrypted

    unknown = [i for i in range(key_len) if not known[i]]
    if len(unknown) > 3:
        return None
    order = list(range(256))
    if len(unknown) == 1:
        p = unknown[0]
        for b in order:
            key[p] = b
            dec = _decrypt_full(data, bytes(key))
            if _validate_decrypted(dec):
                return bytes(key), dec
    elif len(unknown) == 2:
        p0, p1 = unknown
        for b0 in order:
            key[p0] = b0
            for b1 in order:
                key[p1] = b1
                dec = _decrypt_full(data, bytes(key))
                if _validate_decrypted(dec):
                    return bytes(key), dec
    elif len(unknown) == 3:
        p0, p1, p2 = unknown
        for b0 in order[:64]:
            key[p0] = b0
            for b1 in order[:64]:
                key[p1] = b1
                for b2 in order[:64]:
                    key[p2] = b2
                    dec = _decrypt_full(data, bytes(key))
                    if _validate_decrypted(dec):
                        return bytes(key), dec
    return None


def _try_key_length_partial(data: bytes, key_len: int) -> tuple[bytes, bytes] | None:
    key = bytearray(key_len)
    known = [False] * key_len
    key[7 % key_len] = data[7] ^ 0x00
    known[7 % key_len] = True
    for idx, val in ((9, 0x01), (10, 0x00), (11, 0x00), (15, 0x00)):
        key[idx % key_len] = data[idx] ^ val
        known[idx % key_len] = True
    for pos in range(key_len):
        if not known[pos]:
            key[pos] = _freq_key_byte(data, key_len, pos, 7)
    decrypted = _decrypt_partial(data, bytes(key))
    if _validate_decrypted(decrypted):
        return bytes(key), decrypted
    return None


def decrypt_metadata_bytes(data: bytes) -> tuple[bytes, dict]:
    """Return (decrypted_bytes, report). Raises ValueError on failure."""
    magic = struct.unpack_from("<I", data, 0)[0]
    full_enc = magic != METADATA_MAGIC
    detected = _kasiski_key_length(data)
    lengths = []
    for n in (detected, 8, 16, 4, 32, 12, 24):
        if n and 4 <= n <= 32 and n not in lengths:
            lengths.append(n)

    attempts: list[dict] = []
    for key_len in lengths:
        if full_enc:
            result = _try_key_length_full(data, key_len)
            mode = "full"
        else:
            result = _try_key_length_partial(data, key_len)
            mode = "partial"
        if result:
            key, decrypted = result
            version = struct.unpack_from("<i", decrypted, 4)[0]
            return decrypted, {
                "mode": mode,
                "key_len": key_len,
                "key_hex": key.hex(),
                "version": version,
                "attempts": attempts,
            }
        attempts.append({"key_len": key_len, "mode": mode, "ok": False})

    raise ValueError(f"Could not recover XOR key (full_encryption={full_enc}, tried {lengths})")


def analyze_encryption(data: bytes) -> dict:
    """Summarize on-disk metadata protection (for reports when decrypt fails)."""
    import math
    from collections import Counter

    def entropy(chunk: bytes) -> float:
        if not chunk:
            return 0.0
        counts = Counter(chunk)
        n = len(chunk)
        return -sum((c / n) * math.log2(c / n) for c in counts.values())

    magic_le = struct.unpack_from("<I", data, 0)[0]
    plaintext_hits = {
        name: data.count(name.encode("ascii"))
        for name in ("ItemRecord", "ClientItemRecord", "LootTable", "System.", "mscorlib", "Assembly-CSharp")
    }
    return {
        "on_disk_magic_hex": f"{magic_le:08x}",
        "standard_il2cpp_magic": magic_le == METADATA_MAGIC,
        "header_entropy_256": round(entropy(data[:256]), 3),
        "body_entropy_64k": round(entropy(data[65536 : 65536 + 65536]), 3) if len(data) > 131072 else None,
        "plaintext_symbol_hits": plaintext_hits,
        "note": (
            "M&M keeps type/name strings readable in the file body but the v38/v39 header "
            "is obfuscated. Simple 8-byte XOR (including magic-derived keys) does not yield "
            "valid section offsets. Runtime memory mirrors the same encrypted header."
        ),
    }


def decrypt_metadata_file(
    src: Path | None = None,
    dst: Path | None = None,
    *,
    allow_partial: bool = False,
) -> dict:
    src = src or il2cpp_metadata()
    data = src.read_bytes()
    dst = dst or (ensure_dumps() / "il2cpp" / "global-metadata.decrypted.dat")
    dst.parent.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "source": str(src),
        "output": str(dst),
        "source_size": len(data),
        "analysis": analyze_encryption(data),
        "success": False,
        "partial": False,
    }
    try:
        decrypted, info = decrypt_metadata_bytes(data)
        dst.write_bytes(decrypted)
        report.update(
            {
                "success": True,
                "output_size": len(decrypted),
                "magic_ok": decrypted[:4] == struct.pack("<I", METADATA_MAGIC),
                **info,
            }
        )
        return report
    except ValueError as exc:
        report["error"] = str(exc)

    if allow_partial:
        for ver in (39, 38, 40):
            plain_hdr = struct.pack("<Ii", METADATA_MAGIC, ver)
            key = bytes(a ^ b for a, b in zip(data[:8], plain_hdr))
            out = bytearray(data)
            for i in range(len(out)):
                out[i] ^= key[i % 8]
            if struct.unpack_from("<I", out, 0)[0] != METADATA_MAGIC:
                continue
            dst.write_bytes(out)
            report.update(
                {
                    "partial": True,
                    "output_size": len(out),
                    "magic_ok": True,
                    "mode": "full_xor_magic_derived",
                    "key_hex": key.hex(),
                    "version": ver,
                    "warning": "Header section offsets remain invalid; Il2CppDumper will not parse this.",
                }
            )
            return report

    return report


if __name__ == "__main__":
    import json
    import sys

    try:
        print(json.dumps(decrypt_metadata_file(), indent=2))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
