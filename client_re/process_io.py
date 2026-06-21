"""Read-only Win32 process memory helpers (shared by metadata dump and combat harvest)."""

from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes
from typing import Iterator

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
MEM_PRIVATE = 0x20000
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE_READWRITE = 0x40
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

PROCESS_NAME = "mnm.exe"


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_uint64),
        ("AllocationBase", ctypes.c_uint64),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_uint64),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.c_uint64),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", wintypes.WCHAR * 256),
        ("szExePath", wintypes.WCHAR * 260),
    ]


def find_process(name: str = PROCESS_NAME) -> int | None:
    import psutil

    for proc in psutil.process_iter(["pid", "name"]):
        if (proc.info.get("name") or "").lower() == name.lower():
            return int(proc.info["pid"])
    return None


def open_process(pid: int, *, write: bool = False):
    access = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
    if write:
        access |= 0x0020  # PROCESS_VM_WRITE — not used by combat harvest
    handle = kernel32.OpenProcess(access, False, pid)
    if not handle:
        raise OSError(f"OpenProcess failed for pid {pid}: {ctypes.get_last_error()}")
    return handle


def close_process(handle) -> None:
    if handle:
        kernel32.CloseHandle(handle)


def _readable(protect: int) -> bool:
    return not (protect & PAGE_GUARD or protect == PAGE_NOACCESS)


def read_memory(handle, address: int, size: int) -> bytes | None:
    buf = (ctypes.c_char * size)()
    read = ctypes.c_size_t(0)
    if not kernel32.ReadProcessMemory(
        handle, ctypes.c_uint64(address), buf, size, ctypes.byref(read)
    ):
        return None
    return bytes(buf[: read.value])


def iter_regions(handle) -> Iterator[tuple[int, int, int, int]]:
    mbi = MEMORY_BASIC_INFORMATION()
    addr = 0
    while addr < 0x7FFFFFFFFFFF:
        if not kernel32.VirtualQueryEx(
            handle, ctypes.c_uint64(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)
        ):
            break
        base = mbi.BaseAddress or 0
        size = int(mbi.RegionSize)
        if mbi.State == MEM_COMMIT and _readable(mbi.Protect) and size >= 4096:
            yield base, size, mbi.Protect, mbi.Type
        addr = base + size


def iter_region_data(
    handle,
    max_region: int = 80_000_000,
    *,
    heap_only: bool = False,
    max_bytes: int | None = None,
) -> Iterator[tuple[int, bytes]]:
    """Read committed regions. When ``heap_only``, skip image/mapped mappings."""
    heap_protect = {PAGE_READWRITE, PAGE_WRITECOPY, PAGE_EXECUTE_READWRITE}
    scanned = 0
    for base, size, protect, typ in iter_regions(handle):
        if size > max_region:
            continue
        if heap_only:
            if typ != MEM_PRIVATE:
                continue
            if protect not in heap_protect:
                continue
            if size > 16_000_000:
                continue
        if max_bytes is not None and scanned + size > max_bytes:
            break
        data = read_memory(handle, base, size)
        if data:
            scanned += len(data)
            yield base, data


def list_modules(pid: int) -> list[dict]:
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap in (-1, 0xFFFFFFFF):
        raise OSError(f"CreateToolhelp32Snapshot failed: {ctypes.get_last_error()}")
    try:
        me = MODULEENTRY32W()
        me.dwSize = ctypes.sizeof(MODULEENTRY32W)
        out: list[dict] = []
        if kernel32.Module32FirstW(snap, ctypes.byref(me)):
            while True:
                out.append({
                    "name": me.szModule,
                    "path": me.szExePath,
                    "base": me.modBaseAddr,
                    "size": me.modBaseSize,
                })
                if not kernel32.Module32NextW(snap, ctypes.byref(me)):
                    break
        return out
    finally:
        kernel32.CloseHandle(snap)


def find_module(pid: int, name: str) -> dict | None:
    target = name.lower()
    for mod in list_modules(pid):
        if mod["name"].lower() == target:
            return mod
    return None


def read_ptr(handle, address: int) -> int | None:
    raw = read_memory(handle, address, 8)
    if not raw or len(raw) < 8:
        return None
    return struct.unpack_from("<Q", raw, 0)[0]


def read_i32(handle, address: int) -> int | None:
    raw = read_memory(handle, address, 4)
    if not raw or len(raw) < 4:
        return None
    return struct.unpack_from("<i", raw, 0)[0]


def read_utf8_string(handle, address: int, max_len: int = 4096) -> str | None:
    """Read IL2CPP/System.String (UTF-16) or null-terminated UTF-8 at address."""
    if not address:
        return None
    header = read_memory(handle, address, 0x20)
    if not header:
        return None
    # IL2CPP string: length at +0x10, chars at +0x14 (32-bit) or +0x10 (64-bit layout varies)
    for len_off, data_off in ((0x10, 0x14), (0x10, 0x18)):
        if len(header) < data_off + 4:
            continue
        slen = struct.unpack_from("<i", header, len_off)[0]
        if 0 < slen <= max_len:
            raw = read_memory(handle, address + data_off, slen * 2)
            if raw and len(raw) >= slen * 2:
                try:
                    return raw[: slen * 2].decode("utf-16-le")
                except UnicodeDecodeError:
                    pass
    # Fallback: scan for null-terminated UTF-8
    chunk = read_memory(handle, address, min(max_len, 512))
    if chunk:
        end = chunk.find(b"\x00")
        if end > 0:
            try:
                return chunk[:end].decode("utf-8")
            except UnicodeDecodeError:
                pass
    return None
