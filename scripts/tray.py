"""System-tray front-end for codex-auto-confirm.

The tray runs on the main thread (pystray requires it on Windows) and the
watchdog loop runs on a worker thread.  Call :func:`run_tray` from ``main()``
when the user asked for ``--tray`` (this is the default under PyInstaller).
"""
from __future__ import annotations

from collections.abc import Callable

from PIL import Image, ImageDraw


def _make_icon(color: tuple[int, int, int]) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, size - 6, size - 6), fill=color + (255,), outline=(255, 255, 255, 255), width=2)
    # Check mark when ON.
    if color[1] > color[0] + 50:  # green-ish
        d.line((18, 34, 28, 44), fill=(255, 255, 255, 255), width=5)
        d.line((28, 44, 48, 22), fill=(255, 255, 255, 255), width=5)
    return img


def run_tray(
    *,
    is_on: Callable[[], bool],
    toggle: Callable[[], None],
    is_autostart: Callable[[], bool],
    set_autostart: Callable[[bool], None],
    shutdown: Callable[[], None],
) -> None:
    """Block until the user picks Exit from the tray menu."""
    import pystray
    from pystray import Menu
    from pystray import MenuItem as Item

    icon_ref: dict[str, pystray.Icon] = {}

    def refresh_icon(icon: pystray.Icon) -> None:
        icon.icon = _make_icon((34, 197, 94) if is_on() else (120, 120, 120))
        icon.title = f"codex-auto-confirm: {'ON' if is_on() else 'OFF'}"

    def on_toggle(icon, item):
        toggle()
        refresh_icon(icon)
        icon.update_menu()

    def on_autostart(icon, item):
        set_autostart(not is_autostart())
        icon.update_menu()

    def on_exit(icon, item):
        shutdown()
        icon.stop()

    def on_open_logs(icon, item):
        import os
        import subprocess
        log_dir = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")),
            "codex-auto-confirm",
        )
        os.makedirs(log_dir, exist_ok=True)
        try:
            os.startfile(log_dir)  # type: ignore[attr-defined]
        except Exception:
            subprocess.Popen(["explorer", log_dir])

    menu = Menu(
        Item(
            lambda item: f"Auto-confirm: {'ON' if is_on() else 'OFF'}",
            on_toggle,
            checked=lambda item: is_on(),
        ),
        Item(
            "Run at Windows startup",
            on_autostart,
            checked=lambda item: is_autostart(),
        ),
        Menu.SEPARATOR,
        Item("Open log folder", on_open_logs),
        Item("Exit", on_exit),
    )

    icon = pystray.Icon(
        "codex-auto-confirm",
        _make_icon((34, 197, 94)),
        "codex-auto-confirm",
        menu,
    )
    icon_ref["icon"] = icon
    refresh_icon(icon)
    icon.run()
