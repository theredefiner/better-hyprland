#!/usr/bin/env python3
"""
main.py - entry point / renderer for the Start menu

Needs (Arch):  sudo pacman -S python-pyqt6 layer-shell-qt

Background mode (instant open, recommended):
    python3 /path/to/main.py --hidden   start in the background, nothing is shown
                                        (detaches by itself; use it from Hyprland exec-once)
    python3 /path/to/main.py toggle      show the menu if hidden, close it (animated) if shown
    python3 /path/to/main.py open        show if hidden, do nothing if already shown
    python3 /path/to/main.py close       close if shown, do nothing if hidden
    python3 /path/to/main.py quit        stop the background instance
In background mode the menu is only hidden when it closes, never quit, so the next
toggle is instant. Log file: ~/.cache/better-hyprland/start-menu.log

One-shot mode (no --hidden running): toggle / open start a normal menu that quits when it closes.
    python3 main.py          same as "open"
    python3 main.py --plain  (normal window, only for quick UI checks)

Scaling (768p -> 4K): the whole menu is scaled relative to a 1366x768 screen, so it looks the
same on every monitor. The factor comes from the focused monitor (hyprctl, after Hyprland's own
monitor scale), times MENU_SIZE (overall size of the menu). Override everything with
--scale 1.5  or the environment variable SM_SCALE=1.5.

Only one menu can exist at a time: every launch first asks the running menu (over a
local socket) instead of opening a second layer.

Close: click outside the menu, or Esc (Esc only works if the compositor gives
the layer keyboard focus, which the default layer-shell-qt setup does not).
"""
import json
import os
import subprocess
import sys

PLAIN = "--plain" in sys.argv
HIDDEN = "--hidden" in sys.argv

SOCKET_NAME = "start-system-bh-menu"
COMMANDS = ("toggle", "open", "close", "quit")
LOG_FILE = os.path.expanduser("~/.cache/better-hyprland/start-menu.log")


def detach_to_background():
    """--hidden: start a detached copy of ourselves (own session, output -> log file), then exit."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    log = open(LOG_FILE, "a")
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__)] + sys.argv[1:],
        env=dict(os.environ, SM_DETACHED="1"),
        stdin=subprocess.DEVNULL, stdout=log, stderr=log,
        start_new_session=True,
    )
    sys.exit(0)


if HIDDEN and os.environ.get("SM_DETACHED") != "1" and "--no-detach" not in sys.argv:
    detach_to_background()

# ---- scaling ---------------------------------------------------------------
BASE_W, BASE_H = 1366, 768            # the design size: scale 1.0 = your laptop
MIN_SCALE, MAX_SCALE = 0.7, 4.0

# Overall size of the start menu relative to the design size. 1.0 = as designed,
# 0.9 = 10% smaller everywhere (fonts, icons, margins, the box). Tune this to match the side panel.
# (only applies to the automatic scale; --scale / SM_SCALE are used exactly as given)
MENU_SIZE = 0.90
_menu_size_used = 1.0


def arg_value(name):
    """--name value  or  --name=value"""
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def detect_scale():
    """UI scale factor for the focused monitor (1.0 at 1366x768, ~2.8 at 4K without Hyprland scaling)."""
    manual = arg_value("--scale") or os.environ.get("SM_SCALE")
    try:
        if manual:
            return max(MIN_SCALE, min(MAX_SCALE, float(manual)))
    except ValueError:
        print(f"[warn] bad scale '{manual}', detecting automatically")
    try:
        out = subprocess.run(["hyprctl", "-j", "monitors"], capture_output=True, text=True, timeout=2).stdout
        mons = json.loads(out)
        mon = next((m for m in mons if m.get("focused")), mons[0])
        w, h = mon["width"], mon["height"]
        if mon.get("transform", 0) % 2 == 1:          # rotated 90/270: width and height swap
            w, h = h, w
        hypr_scale = mon.get("scale") or 1.0           # logical size = pixels / Hyprland's monitor scale
        factor = min((w / hypr_scale) / BASE_W, (h / hypr_scale) / BASE_H) * MENU_SIZE
        global _menu_size_used
        _menu_size_used = MENU_SIZE
        return round(max(MIN_SCALE, min(MAX_SCALE, factor)), 2)
    except Exception as ex:                            # hyprctl missing / not Hyprland
        print("[warn] could not detect the monitor size, using scale 1.0:", ex)
        return 1.0


def _wants_menu():
    """Only launches that may build a menu need the scale (not close / quit)."""
    return HIDDEN or not any(a in ("close", "quit") for a in sys.argv[1:])


SCALE = detect_scale() if _wants_menu() else 1.0
if abs(SCALE - 1.0) >= 0.02:
    # Qt reads this once while QApplication is created; it is removed again right after
    # so the apps we launch (Dolphin, ...) are NOT scaled.
    os.environ["QT_SCALE_FACTOR"] = f"{SCALE:g}"
    print(f"[info] UI scale {SCALE:g}")

if not PLAIN:
    # Must be set BEFORE QApplication is created. Makes Qt use the layer-shell
    # plugin (from the layer-shell-qt package) instead of a normal xdg window.
    os.environ["QT_QPA_PLATFORM"] = "wayland"
    os.environ["QT_WAYLAND_SHELL_INTEGRATION"] = "layer-shell"

from PyQt6.QtGui import QFont
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

import start_main_menu as smm
from start_main_menu import StartMainMenu

# The gaps to the screen edge / the bar are in menu pixels, so shrinking the menu would shrink
# them too. Compensate so the menu keeps the same distance from the left edge and from the bar.
smm.LEFT_MARGIN = round(smm.LEFT_MARGIN / _menu_size_used)
smm.BOTTOM_MARGIN = round(smm.BOTTOM_MARGIN / _menu_size_used)


def get_command():
    """toggle / open / close / quit from the command line (default: open)."""
    for arg in sys.argv[1:]:
        if arg in COMMANDS:
            return arg
    return "open"


def send_to_running(message):
    """Send a message to an already-running menu. Returns True if one was running."""
    sock = QLocalSocket()
    sock.connectToServer(SOCKET_NAME)
    if not sock.waitForConnected(150):
        return False                              # nothing listening (or stale socket)
    sock.write(message.encode())
    sock.flush()
    sock.waitForBytesWritten(150)
    sock.disconnectFromServer()
    return True


def start_listener(on_message):
    """Listen for later launches; every message (toggle/open/close/quit/ping) goes to on_message(text)."""
    QLocalServer.removeServer(SOCKET_NAME)        # clears a stale socket after a crash
    server = QLocalServer()

    def on_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def on_data():
            on_message(bytes(conn.readAll()).decode(errors="ignore").strip())
            conn.disconnectFromServer()

        conn.readyRead.connect(on_data)
        if conn.bytesAvailable():
            on_data()

    server.newConnection.connect(on_connection)
    server.listen(SOCKET_NAME)
    return server


# --------------------------------------------------------------------------
# Background (resident) mode helpers
# --------------------------------------------------------------------------
class _QuitHook:
    """
    Stands in for `QApplication` inside start_main_menu.py (module global only).
    The menu ends its closing animation with QApplication.quit(); in background mode
    that call is redirected to `on_quit` (hide the menu) instead of exiting the process.
    Everything else is forwarded to the real QApplication.
    """

    def __init__(self, real, on_quit):
        self._real = real
        self._on_quit = on_quit

    def __getattr__(self, name):
        return getattr(self._real, name)

    def quit(self):
        self._on_quit()


def pause_idle(menu):
    """Hidden menu: stop the clock timer and the greeting GIF so it costs nothing."""
    clock = getattr(menu, "clock", None)
    if clock is not None:
        clock.stop()
    movie = getattr(getattr(menu, "gif", None), "movie", None)
    if movie is not None:
        movie.setPaused(True)


def resume_idle(menu):
    clock = getattr(menu, "clock", None)
    if clock is not None:
        clock.start(1000)
    movie = getattr(getattr(menu, "gif", None), "movie", None)
    if movie is not None:
        movie.setPaused(False)
    menu.refresh_time()


def reset_menu(menu):
    """After a close animation: hide the window and put the UI back to its fresh 'home' state."""
    menu.hide()
    menu.card.setGraphicsEffect(None)
    for screen in menu.screens.values():              # editor / search / all apps
        screen.setGraphicsEffect(None)
        screen.move(0, 0)
        screen.hide()
    menu.home_view.setGraphicsEffect(None)
    menu.home_view.move(0, 0)
    menu.home_view.show()
    menu.card.move(menu.rest_pos)
    menu.active_screen = None
    menu._busy = False
    menu._closing = False
    pause_idle(menu)
    smm.all_apps(force=True)                          # pick up apps installed while hidden


def main():
    app = QApplication([sys.argv[0]])
    os.environ.pop("QT_SCALE_FACTOR", None)           # Qt has read it; don't leak it to launched apps
    app.setApplicationName("start-menu")
    app.setFont(QFont("Google Sans Flex 9pt", 9))

    cmd = get_command()
    if HIDDEN:
        if send_to_running("ping"):                   # already running in the background
            sys.exit(0)
    else:
        if send_to_running(cmd):                      # toggle/open/close/quit go to the running menu
            sys.exit(0)
        if cmd in ("close", "quit"):
            sys.exit(0)                               # nothing running, nothing to do

    if HIDDEN:
        app.setQuitOnLastWindowClosed(False)          # hiding the menu must not end the process

    menu = None

    def on_message(msg):
        if menu is None:
            return
        shown = menu.isVisible()
        closing = getattr(menu, "_closing", False)
        if msg == "quit":
            QApplication.quit()
        elif msg in ("toggle", "close") and shown and not closing:
            menu.close_menu()                         # slide-down animation
        elif msg in ("toggle", "open") and not shown:
            resume_idle(menu)
            menu.open_menu()                          # slide-up animation
        # anything else (ping, toggle while closing, open while shown) is ignored

    server = start_listener(on_message)               # keep a reference so it stays alive

    menu = StartMainMenu(overlay=not PLAIN)
    if not PLAIN:
        from layer_namespace import set_layer_namespace
        set_layer_namespace(menu, "start-system-bh.menu")   # before the first show()

    if HIDDEN:
        def finish_close():
            if getattr(menu, "_closing", False):      # ignores the menu's 1s safety-net call
                reset_menu(menu)

        smm.QApplication = _QuitHook(QApplication, finish_close)
        pause_idle(menu)                              # built, but not shown until "toggle"/"open"
    else:
        menu.open_menu()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
