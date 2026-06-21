"""Fullscreen drag-to-select screen region picker for combat OCR calibration."""

from __future__ import annotations

import contextlib
import sys
import tkinter as tk

MIN_WIDTH = 48
MIN_HEIGHT = 32


def _virtual_screen() -> tuple[int, int, int, int]:
    """Return (left, top, width, height) covering all monitors when possible."""
    if sys.platform == "win32":
        import ctypes

        user32 = ctypes.windll.user32
        return (
            user32.GetSystemMetrics(76),  # SM_XVIRTUALSCREEN
            user32.GetSystemMetrics(77),  # SM_YVIRTUALSCREEN
            user32.GetSystemMetrics(78),  # SM_CXVIRTUALSCREEN
            user32.GetSystemMetrics(79),  # SM_CYVIRTUALSCREEN
        )
    tmp = tk.Tk()
    tmp.withdraw()
    tmp.update_idletasks()
    w, h = tmp.winfo_screenwidth(), tmp.winfo_screenheight()
    tmp.destroy()
    return 0, 0, w, h


def pick_screen_region(
    parent: tk.Misc | None = None,
    *,
    hint: str = "Drag around your combat chat window. Release to confirm. Esc to cancel.",
) -> dict | None:
    """Open a dim fullscreen overlay; user drags a rectangle in screen pixels.

    Returns ``{left, top, width, height, source: 'picker'}`` or ``None`` if cancelled.
    Blocks until the user finishes.
    """
    owns_root = False
    if parent is None:
        root = tk.Tk()
        root.withdraw()
        parent = root
        owns_root = True

    result: dict | None = None
    vx, vy, vw, vh = _virtual_screen()

    overlay = tk.Toplevel(parent)
    overlay.title("Select OCR region")
    overlay.geometry(f"{vw}x{vh}+{vx}+{vy}")
    overlay.configure(bg="#101010")
    overlay.attributes("-topmost", True)
    with contextlib.suppress(tk.TclError):
        overlay.attributes("-alpha", 0.35)

    canvas = tk.Canvas(
        overlay,
        highlightthickness=0,
        bg="#101010",
        cursor="crosshair",
    )
    canvas.pack(fill="both", expand=True)

    banner = tk.Label(
        overlay,
        text=hint,
        bg="#1a2332",
        fg="#e8ecf0",
        font=("Segoe UI", 11),
        padx=12,
        pady=6,
    )
    banner.place(relx=0.5, y=12, anchor="n")

    size_label = tk.Label(
        overlay,
        text="",
        bg="#1a2332",
        fg="#8bc4ff",
        font=("Segoe UI", 10),
        padx=8,
        pady=4,
    )
    size_label.place(relx=0.5, y=44, anchor="n")

    start: tuple[int, int] | None = None
    rect_id: int | None = None

    def _draw_selection(x0: int, y0: int, x1: int, y1: int) -> None:
        nonlocal rect_id
        lx0, ly0 = x0 - vx, y0 - vy
        lx1, ly1 = x1 - vx, y1 - vy
        left, top = min(lx0, lx1), min(ly0, ly1)
        right, bottom = max(lx0, lx1), max(ly0, ly1)
        if rect_id is not None:
            canvas.delete(rect_id)
        rect_id = canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline="#60a5fa",
            width=3,
        )
        w, h = right - left, bottom - top
        size_label.configure(text=f"{w} × {h} px")

    def on_press(event: tk.Event) -> None:
        nonlocal start
        start = (event.x_root, event.y_root)
        size_label.configure(text="")

    def on_drag(event: tk.Event) -> None:
        if start is None:
            return
        _draw_selection(start[0], start[1], event.x_root, event.y_root)

    def on_release(event: tk.Event) -> None:
        nonlocal result, start
        if start is None:
            return
        x0, y0 = start
        x1, y1 = event.x_root, event.y_root
        left = min(x0, x1)
        top = min(y0, y1)
        width = abs(x1 - x0)
        height = abs(y1 - y0)
        start = None
        if width < MIN_WIDTH or height < MIN_HEIGHT:
            size_label.configure(
                text=f"Too small — drag a larger area (min {MIN_WIDTH}×{MIN_HEIGHT})"
            )
            return
        result = {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "source": "picker",
        }
        overlay.destroy()

    def on_cancel(_event: tk.Event | None = None) -> None:
        nonlocal result, start
        result = None
        start = None
        overlay.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    overlay.bind("<Escape>", on_cancel)
    overlay.protocol("WM_DELETE_WINDOW", on_cancel)

    overlay.grab_set()
    overlay.focus_force()
    parent.wait_window(overlay)

    if owns_root:
        parent.destroy()

    return result


def region_to_str(region: dict) -> str:
    return f"{region['left']},{region['top']},{region['width']},{region['height']}"
