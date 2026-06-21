"""Screen capture + OCR for the in-game combat chat window (Option C).

Backends (auto-selected):
  1. Windows.Media.Ocr via winrt — returns **per-line** text + Y positions
  2. pytesseract + Tesseract — line clustering from word boxes

Capture uses ``mss`` (fast) with PIL ImageGrab fallback.

For accurate damage totals over time, use ``ocr_region_lines`` / ``ocr_image_lines``
rather than the legacy blob ``ocr_image`` string.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
from dataclasses import dataclass

Region = dict  # {left, top, width, height}

_COMBAT_HEADER = re.compile(r"^COMBAT\s*", re.I)
_JSON_OCR_JUNK = re.compile(
    r'^[\s"]*(kind|raw|actor|target|verb|ability|amount|source|pet|damage|direction|"\s*:)',
    re.I,
)
_JSON_LITERAL_JUNK = frozenset({
    "null,",
    "null",
    '"source"',
    '"pet": null,',
    '"damage _ type" :',
    ". null,",
})

# OCR often splits mid-sentence across rows (e.g. "... 1 point of" / "damage.").
_INCOMPLETE_SUFFIXES = (
    " point of",
    " points of",
    " point of damage",
    " points of damage",
    " for 1 point of",
    " for 2 points of",
    " for 3 points of",
    " for 4 points of",
    " for 5 points of",
    " for 1 point of",
    " hits a",
    " strike hits a",
    " hits a fire",
    " hits a large",
    " hits a snake",
    " for 1",
    " for 2",
    " for 3",
    " for 4",
    " for 5",
    " for 10",
    " point",
    " points",
    "for 1 point",
    "for 2 points",
    "for 3 points",
    "for 1 point of",
    "for 1 point",
)


def merge_wrapped_ocr_lines(lines: list[str]) -> list[str]:
    """Join OCR rows that were split mid-message."""
    if not lines:
        return []
    merged: list[str] = []
    buf = ""
    for raw in lines:
        part = raw.strip()
        if not part:
            continue
        low = part.lower()
        if low in ("damage.", "damage"):
            if buf:
                part = part
            else:
                continue
        if buf:
            buf = f"{buf} {part}"
        else:
            buf = part
        if _ocr_line_complete(buf):
            merged.append(buf.strip())
            buf = ""
    if buf.strip() and len(buf.strip()) > 4:
        merged.append(buf.strip())
    return merged


def _ocr_line_complete(text: str) -> bool:
    t = text.strip()
    if re.search(r"[.!]$", t):
        return True
    low = t.lower()
    return not any(low.endswith(suffix) for suffix in _INCOMPLETE_SUFFIXES)


@dataclass(frozen=True)
class OcrTextLine:
    """One visual row in the combat window."""

    text: str
    y: int  # top edge in prepared-image coordinates
    height: int


def _has_winrt() -> bool:
    return importlib.util.find_spec("winrt.windows.media.ocr") is not None


def _has_tesseract() -> bool:
    if importlib.util.find_spec("pytesseract") is None:
        return False
    import pytesseract
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def available_backends() -> list[str]:
    out = []
    if _has_winrt():
        out.append("windows")
    if _has_tesseract():
        out.append("tesseract")
    return out


def capture_region(region: Region, *, window_lock: bool | None = None) -> "object":
    """Return a PIL Image of the combat capture rectangle.

    When ``window_lock`` is true (default on Windows), capture uses ``PrintWindow``
    on the game client so overlays on screen do not pollute OCR.
    """
    from PIL import Image

    lock = window_lock
    if lock is None:
        lock = bool(region.get("window_lock", True))

    if sys.platform == "win32" and lock:
        from mnm_game_window import capture_window_region

        return capture_window_region(region)

    left = int(region["left"])
    top = int(region["top"])
    w = int(region["width"])
    h = int(region["height"])
    right = left + w
    bottom = top + h

    if importlib.util.find_spec("mss"):
        import mss
        with mss.mss() as sct:
            shot = sct.grab({"left": left, "top": top, "width": w, "height": h})
            return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    from PIL import ImageGrab
    return ImageGrab.grab(bbox=(left, top, right, bottom))


def _prepare_for_ocr(im: "object", scale: float = 2.0) -> "object":
    """Upscale + grayscale to help OCR on small chat fonts."""
    from PIL import ImageOps, ImageFilter

    if scale and scale > 1.0:
        w, h = im.size
        im = im.resize((int(w * scale), int(h * scale)), resample=3)  # BICUBIC
    im = ImageOps.grayscale(im)
    im = ImageOps.autocontrast(im)
    im = im.filter(ImageFilter.SHARPEN)
    return im.convert("RGB")


def _clean_combat_line(text: str) -> str:
    """Strip window title row and glued ``COMBAT`` prefix from OCR."""
    text = " ".join(text.split()).strip()
    if not text:
        return ""
    if _JSON_OCR_JUNK.match(text) or text.startswith('":'):
        return ""
    if text.lower() in _JSON_LITERAL_JUNK:
        return ""
    if _COMBAT_HEADER.match(text) and len(text) <= 8:
        return ""
    text = _COMBAT_HEADER.sub("", text).strip()
    if text.lower() in ("damage.", "damage", "aamage."):
        return ""
    return text


def _filter_combat_lines(lines: list[OcrTextLine]) -> list[OcrTextLine]:
    out: list[OcrTextLine] = []
    for line in lines:
        cleaned = _clean_combat_line(line.text)
        if len(cleaned) >= 4:
            out.append(OcrTextLine(cleaned, line.y, line.height))
    return out


def ocr_image_lines(im: "object", backend: str | None = None) -> list[str]:
    """OCR a capture and return ordered chat lines (top → bottom)."""
    raw = [ln.text for ln in ocr_image_frame(im, backend=backend)]
    return merge_wrapped_ocr_lines(raw)


def ocr_image_frame(im: "object", backend: str | None = None) -> list[OcrTextLine]:
    """OCR a capture and return lines with vertical positions."""
    backends = available_backends()
    if not backends:
        raise RuntimeError(
            "No OCR backend available. On Windows: pip install -r requirements-combat.txt\n"
            "Or install Tesseract: https://github.com/UB-Mannheim/tesseract/wiki"
        )
    use = backend if backend in backends else backends[0]
    prepared = _prepare_for_ocr(im)

    if use == "windows":
        lines = _ocr_windows_frame(prepared)
    else:
        lines = _ocr_tesseract_frame(prepared)

    lines.sort(key=lambda ln: ln.y)
    return _filter_combat_lines(lines)


def ocr_image(im: "object", backend: str | None = None) -> str:
    """Legacy blob OCR — prefer ``ocr_image_lines`` for live capture."""
    return "\n".join(ocr_image_lines(im, backend=backend))


def _ocr_tesseract_frame(im: "object") -> list[OcrTextLine]:
    import pytesseract

    data = pytesseract.image_to_data(im, config="--psm 6", output_type=pytesseract.Output.DICT)
    n = len(data["text"])
    rows: dict[tuple[int, int], list[tuple[str, int, int, int]]] = {}

    for i in range(n):
        word = (data["text"][i] or "").strip()
        if not word:
            continue
        key = (data["block_num"][i], data["line_num"][i])
        rows.setdefault(key, []).append(
            (word, data["left"][i], data["top"][i], data["height"][i]),
        )

    lines: list[OcrTextLine] = []
    for words in rows.values():
        words.sort(key=lambda w: w[1])
        text = " ".join(w[0] for w in words)
        y = min(w[2] for w in words)
        height = max(w[2] + w[3] for w in words) - y
        lines.append(OcrTextLine(text, y, height))
    return lines


def _pil_to_software_bitmap(im: "object") -> "object":
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    import winrt.windows.storage.streams as streams

    im = im.convert("RGBA")
    data_writer = streams.DataWriter()
    data_writer.write_bytes(im.tobytes())
    bitmap = SoftwareBitmap(BitmapPixelFormat.RGBA8, im.width, im.height)
    bitmap.copy_from_buffer(data_writer.detach_buffer())
    return bitmap


async def _ocr_windows_frame_async(im: "object") -> list[OcrTextLine]:
    from winrt.windows.media.ocr import OcrEngine

    engine = OcrEngine.try_create_from_user_profile_languages()
    if not engine:
        raise RuntimeError("Windows OCR engine not available for your language profile")
    bitmap = _pil_to_software_bitmap(im)
    result = await engine.recognize_async(bitmap)
    if not result:
        return []

    lines: list[OcrTextLine] = []
    try:
        ocr_lines = list(result.lines)
    except ModuleNotFoundError:
        # winrt-Windows.Foundation.Collections needed to iterate OcrLine list
        return _lines_from_windows_text(result.text or "", im.size[1])

    for ocr_line in ocr_lines:
        text = (ocr_line.text or "").strip()
        if not text:
            continue
        y_vals: list[int] = []
        h_vals: list[int] = []
        for word in ocr_line.words:
            rect = word.bounding_rect
            y_vals.append(int(rect.y))
            h_vals.append(int(rect.y + rect.height))
        if y_vals:
            y = min(y_vals)
            height = max(h_vals) - y
        else:
            y, height = 0, 0
        lines.append(OcrTextLine(text, y, height))
    return lines


def _lines_from_windows_text(text: str, image_height: int) -> list[OcrTextLine]:
    """Fallback when OcrResult.lines cannot be iterated (missing winrt collection pkg)."""
    parts = [p.strip() for p in re.split(r"[\r\n]+", text) if p.strip()]
    if not parts:
        return []
    if len(parts) == 1 and len(parts[0]) > 80:
        # Single blob — split on sentence boundaries for combat starters.
        from mnm_combat_text import split_combat_messages
        parts = split_combat_messages(parts[0])
    row_h = max(image_height // max(len(parts), 1), 12)
    return [
        OcrTextLine(part, i * row_h, row_h)
        for i, part in enumerate(parts)
    ]


def _ocr_windows_frame(im: "object") -> list[OcrTextLine]:
    if sys.platform != "win32":
        raise RuntimeError("windows OCR backend requires Windows")
    return asyncio.run(_ocr_windows_frame_async(im))


def _ocr_windows(im: "object") -> str:
    return "\n".join(ln.text for ln in _ocr_windows_frame(im))


def _ocr_tesseract(im: "object") -> str:
    return "\n".join(ln.text for ln in _ocr_tesseract_frame(im))


def diff_chat_lines(prev: list[str], curr: list[str]) -> list[str]:
    """Return lines that are new since the previous frame (scroll-aware).

    Handles upward chat scroll (new row at bottom, top row drops off) by matching
    the prefix of the current frame to the suffix of the previous frame. When the
    window does not scroll, only bottom row(s) that changed are returned.
    """
    from mnm_combat_text import normalize_line

    prev_norm = [normalize_line(l) for l in prev if l.strip()]
    curr_raw = [l.strip() for l in curr if l.strip()]
    curr_norm = [normalize_line(l) for l in curr_raw]

    if not prev_norm:
        return curr_raw

    # Scrolled: bottom of previous frame aligns with top of current frame.
    scroll_overlap = 0
    for i in range(1, min(len(prev_norm), len(curr_norm)) + 1):
        if prev_norm[-i:] == curr_norm[:i]:
            scroll_overlap = i
    if scroll_overlap > 0:
        return curr_raw[scroll_overlap:]

    # More rows than before (chat grew without losing top row yet).
    if len(curr_norm) > len(prev_norm):
        return curr_raw[len(prev_norm):]

    # Same row count — bottom row(s) updated in place.
    if len(curr_norm) == len(prev_norm):
        new: list[str] = []
        for i in range(len(curr_norm) - 1, -1, -1):
            if curr_norm[i] != prev_norm[i]:
                new.append(curr_raw[i])
            else:
                break
        return list(reversed(new))

    # Fewer rows — emit non-overlapping tail after suffix match.
    k = 0
    while k < len(curr_norm) and k < len(prev_norm):
        if curr_norm[-(k + 1)] != prev_norm[-(k + 1)]:
            break
        k += 1
    if k == 0:
        return curr_raw
    return curr_raw[: len(curr_raw) - k]


def ocr_region_lines(
    region: Region,
    backend: str | None = None,
    *,
    window_lock: bool | None = None,
) -> list[str]:
    im = capture_region(region, window_lock=window_lock)
    return ocr_image_lines(im, backend=backend)


def ocr_region(
    region: Region,
    backend: str | None = None,
    *,
    window_lock: bool | None = None,
) -> str:
    im = capture_region(region, window_lock=window_lock)
    return ocr_image(im, backend=backend)
