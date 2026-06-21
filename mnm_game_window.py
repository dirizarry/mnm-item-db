"""Find the Monsters & Memories game window and capture its client area.

Uses ``PrintWindow`` so OCR reads the game framebuffer even when other apps
cover the game on screen (e.g. an editor over the combat chat).
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

if sys.platform != "win32":
    raise ImportError("mnm_game_window requires Windows")

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PW_RENDERFULLCONTENT = 2

GAME_TITLE_PATTERNS = (
    "monsters and memories",
    "monsters & memories",
)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _is_game_title(title: str) -> bool:
    low = title.lower()
    return any(pat in low for pat in GAME_TITLE_PATTERNS)


def find_game_hwnd() -> int | None:
    """Return HWND of the visible game window, or None."""
    matches: list[tuple[int, int, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _window_title(hwnd)
        if not title or not _is_game_title(title):
            return True
        rect = RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        area = max(0, rect.right) * max(0, rect.bottom)
        if area > 0:
            matches.append((hwnd, area, title))
        return True

    user32.EnumWindows(_enum, 0)
    if not matches:
        return None
    matches.sort(key=lambda m: m[1], reverse=True)
    return matches[0][0]


def client_origin_screen(hwnd: int) -> tuple[int, int]:
    """Screen coordinates of the client area's top-left corner."""
    point = POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y


def client_size(hwnd: int) -> tuple[int, int]:
    rect = RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    return max(0, rect.right), max(0, rect.bottom)


def capture_hwnd_client(hwnd: int) -> object:
    """Capture the full client area of ``hwnd`` as a PIL RGB image."""
    from PIL import Image

    w, h = client_size(hwnd)
    if w <= 0 or h <= 0:
        raise RuntimeError("Game window has no client area")

    hwnd_dc = user32.GetWindowDC(hwnd)
    if not hwnd_dc:
        raise RuntimeError("GetWindowDC failed")
    mfc_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    gdi32.SelectObject(mfc_dc, bitmap)

    ok = user32.PrintWindow(hwnd, mfc_dc, PW_RENDERFULLCONTENT)
    if not ok:
        ok = user32.PrintWindow(hwnd, mfc_dc, 0)
    if not ok:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mfc_dc)
        user32.ReleaseDC(hwnd, hwnd_dc)
        raise RuntimeError("PrintWindow failed — try running the game as admin or borderless")

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0  # BI_RGB

    buf_size = w * h * 4
    buffer = ctypes.create_string_buffer(buf_size)
    lines = gdi32.GetDIBits(
        mfc_dc,
        bitmap,
        0,
        h,
        buffer,
        ctypes.byref(bmi),
        0,
    )

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mfc_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)

    if not lines:
        raise RuntimeError("GetDIBits failed")

    im = Image.frombuffer("RGBA", (w, h), buffer, "raw", "BGRA", 0, 1)
    return im.convert("RGB")


def attach_window_lock(region: dict) -> dict:
    """Add ``window_lock`` + ``relative`` crop inside the game client area."""
    hwnd = find_game_hwnd()
    if not hwnd:
        region["window_lock"] = False
        return region

    ox, oy = client_origin_screen(hwnd)
    region["window_lock"] = True
    region["relative"] = {
        "left": int(region["left"]) - ox,
        "top": int(region["top"]) - oy,
        "width": int(region["width"]),
        "height": int(region["height"]),
    }
    region["window_title"] = _window_title(hwnd)
    return region


def _crop_region(region: dict, im: object) -> object:
    rel = region.get("relative")
    if rel:
        left, top = int(rel["left"]), int(rel["top"])
        w, h = int(rel["width"]), int(rel["height"])
    else:
        hwnd = find_game_hwnd()
        if not hwnd:
            raise RuntimeError("Game window not found")
        ox, oy = client_origin_screen(hwnd)
        left = int(region["left"]) - ox
        top = int(region["top"]) - oy
        w, h = int(region["width"]), int(region["height"])

    iw, ih = im.size
    left = max(0, min(left, iw - 1))
    top = max(0, min(top, ih - 1))
    w = max(1, min(w, iw - left))
    h = max(1, min(h, ih - top))
    return im.crop((left, top, left + w, top + h))


def capture_window_region(region: dict) -> object:
    """Capture combat chat region from the game window (not screen pixels)."""
    hwnd = find_game_hwnd()
    if not hwnd:
        raise RuntimeError(
            "Monsters and Memories window not found. Start the game before combat OCR."
        )
    full = capture_hwnd_client(hwnd)
    return _crop_region(region, full)


def game_window_status() -> str:
    hwnd = find_game_hwnd()
    if not hwnd:
        return "game window: not found"
    w, h = client_size(hwnd)
    return f"game window: {_window_title(hwnd)} ({w}x{h})"
