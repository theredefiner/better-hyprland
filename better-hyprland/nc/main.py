#!/usr/bin/env python3
"""Better Hyprland - notification center host (layer-shell panel).

Loads the pills (notifications.py, sliders.py, media.py, quick-settings.py) that exist next
to this file, stacks them in one transparent layer-shell surface anchored top-right, and
slides it in/out. Missing pill files are skipped, so you can add them one by one.

Usage:
    main.py [toggle|show|hide|quit] [--hidden] [--demo]

    The first launch becomes the long-running panel process. Later launches just send
    their command to it over a unix socket (no Qt import, so a keybind toggles instantly).
      --hidden   start without showing (use this for autostart)
      --demo     fill the notification list with sample cards

Pill contract: each pill file defines `create_pill(services: dict) -> QWidget`.

Hyprland (hyprland.lua), blur + keybind:
    hl.layer_rule({
        match = { namespace = "^better-hyprland-nc.*$" },  -- also matches the Wi-Fi popup
        blur = true,
        ignore_alpha = 0.1,   -- pills are 0.2 alpha, the gaps between them are 0
        no_anim = true,       -- the panel animates itself
    })
    hl.bind(mainMod .. " + N", hl.dsp.exec_cmd("python ~/.config/better-hyprland/nc/main.py toggle"))
    hl.on("hyprland.start", function()
        hl.exec_cmd("python ~/.config/better-hyprland/nc/main.py --hidden")
    end)

Needs: python-pyqt6 (the distro package, NOT the pip wheel), qt6-wayland, layer-shell-qt.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import importlib.util
import logging
import os
import signal
import socket
import sys
from pathlib import Path

APP_ID = "better-hyprland-nc"
LAYER_SCOPE = "better-hyprland-nc"  # namespace shown by `hyprctl layers`, matched by the layer rule
BASE_DIR = Path(__file__).resolve().parent
SOCKET_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", f"{APP_ID}.sock")
COMMANDS = ("toggle", "show", "hide", "quit")

# (file, module name). quick-settings.py has a hyphen, so files are loaded by path.
PILL_FILES = (
    ("notifications.py", "notifications"),
    ("sliders.py", "sliders"),
    ("media.py", "media"),
    ("quick-settings.py", "quick_settings"),
)

log = logging.getLogger(APP_ID)


# ------------------------------------------------------- stage 1: talk to a running panel


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="main.py", description="Better Hyprland notification center")
    parser.add_argument("command", nargs="?", default="toggle", choices=COMMANDS)
    parser.add_argument("--hidden", action="store_true", help="start without showing the panel")
    parser.add_argument("--demo", action="store_true", help="add sample notifications")
    return parser.parse_args(argv)


def _send_to_running_instance(command: str) -> bool:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(0.5)
    try:
        client.connect(SOCKET_PATH)
        client.sendall(command.encode() + b"\n")
        return True
    except OSError:
        return False
    finally:
        client.close()


if __name__ == "__main__":
    _ARGS = _parse_args(sys.argv[1:])
    # "ping" is ignored by the server; it only checks that a panel is already running.
    if _send_to_running_instance("ping" if _ARGS.hidden else _ARGS.command):
        sys.exit(0)
    if _ARGS.command in ("hide", "quit"):  # nothing running, nothing to do
        sys.exit(0)

# ----------------------------------------------------------- stage 2: the panel process

sys.path.insert(0, str(BASE_DIR))

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import (  # noqa: E402
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtNetwork import QLocalServer  # noqa: E402
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from common import Theme, make_font  # noqa: E402


class LayerShell:
    """Best-effort bridge to LayerShellQt (the C++ library has no Python bindings).

    `LayerShellQt::Window::get(QWindow*)` is called through ctypes; the object it returns is a
    QObject with Q_PROPERTYs, so scope/layer/anchors are set through Qt's property system.
    Needs layer-shell-qt built against the same Qt6 that PyQt6 uses (the distro packages).
    """

    ANCHOR_TOP = 1
    ANCHOR_BOTTOM = 2
    ANCHOR_LEFT = 4
    ANCHOR_RIGHT = 8
    ANCHOR_ALL = 15
    LAYER_TOP = 2
    KEYBOARD_ON_DEMAND = 2
    _GET_SYMBOL = "_ZN12LayerShellQt6Window3getEP7QWindow"
    _keep_alive: list[QObject] = []

    @classmethod
    def load(cls) -> ctypes.CDLL | None:
        import PyQt6

        if (Path(PyQt6.__file__).parent / "Qt6").is_dir():
            log.warning("PyQt6 pip wheel detected (bundled Qt): layer-shell would mix two Qt copies. "
                        "Install the distro package: sudo pacman -S python-pyqt6")
            return None
        for name in (ctypes.util.find_library("LayerShellQtInterface"), "libLayerShellQtInterface.so.6"):
            if not name:
                continue
            try:
                return ctypes.CDLL(name)
            except OSError:
                continue
        log.warning("layer-shell-qt not found (sudo pacman -S layer-shell-qt); using a normal window")
        return None

    @classmethod
    def configure(cls, lib: ctypes.CDLL, qwindow, *, scope: str, anchors: int, layer: int, keyboard: int) -> bool:
        """Turn `qwindow` into a layer surface. Must run before the window is first shown."""
        try:
            get = lib[cls._GET_SYMBOL]
        except AttributeError:
            log.warning("LayerShellQt::Window::get not found in the library")
            return False
        get.argtypes = [ctypes.c_void_p]
        get.restype = ctypes.c_void_p
        address = get(sip.unwrapinstance(qwindow))
        if not address:
            log.warning("LayerShellQt::Window::get returned null (not a Wayland window?)")
            return False
        window = sip.wrapinstance(address, QObject)
        cls._keep_alive.append(window)
        for name, value in (
            ("scope", scope),
            ("layer", layer),
            ("anchors", anchors),
            ("keyboardInteractivity", keyboard),
        ):
            if not window.setProperty(name, value):
                log.debug("layer-shell property %r is not available in this version", name)
        log.debug("layer-shell configured: scope=%r anchors=%d layer=%d", window.property("scope"), anchors, layer)
        return True


class PanelWindow(QWidget):
    """One transparent surface holding the pill column; the column slides inside it."""

    def __init__(self, pills: list[QWidget], *, layer_shell: bool) -> None:
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if not layer_shell:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setWindowTitle("Better Hyprland Notification Center")
        self.setObjectName("NotificationCenter")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.auto_hide = False  # True = close when focus moves to another window (also fires on mouse-over of other windows)
        self._layer_shell = layer_shell
        self._open = False
        self._was_active = False

        self._column = QWidget(self)
        layout = QVBoxLayout(self._column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Theme.PILL_SPACING)
        for pill in pills:
            layout.addWidget(pill)
        layout.addStretch(1)  # keeps the pills at the top when the column is taller than them
        self._column.setFixedWidth(Theme.COLUMN_WIDTH)
        layout.activate()
        column_height = max(layout.sizeHint().height(), Theme.PANEL_MIN_HEIGHT)
        self._column.setFixedSize(Theme.COLUMN_WIDTH, column_height)

        # The surface covers the whole screen (all four anchors) and is fully transparent, so a
        # click on the empty part can close the panel. The column sits at the top-right inside it.
        screen = QApplication.primaryScreen()
        self.resize(screen.size() if screen is not None else QSize(1366, 768))
        self._park()

        self._anim = QPropertyAnimation(self._column, b"pos", self)
        self._anim.finished.connect(self._on_anim_finished)

    # -- public
    def toggle(self) -> None:
        self.dismiss() if self._open else self.reveal()

    def reveal(self) -> None:
        if self._open:
            return
        self._open = True
        self._was_active = False
        if not self.isVisible():
            self._column.move(self._hidden_x(), Theme.PANEL_MARGIN_TOP)
            if not self._layer_shell:
                self._place_without_layer_shell()
            self.show()
            self._column.move(self._hidden_x(), Theme.PANEL_MARGIN_TOP)  # show() may have parked it open
        self._slide_to(self._rest_x(), Theme.ANIM_SLIDE_IN, QEasingCurve.Type.OutCubic)

    def dismiss(self) -> None:
        if not self._open:
            return
        self._open = False
        self._slide_to(self._hidden_x(), Theme.ANIM_SLIDE_OUT, QEasingCurve.Type.InCubic)

    # -- internals
    def _slide_to(self, x: int, duration: int, curve: QEasingCurve.Type) -> None:
        self._anim.stop()
        self._anim.setDuration(duration)
        self._anim.setEasingCurve(curve)
        self._anim.setStartValue(self._column.pos())
        self._anim.setEndValue(QPoint(x, Theme.PANEL_MARGIN_TOP))
        self._anim.start()

    def _rest_x(self) -> int:
        """Column x when the panel is open (top-right corner of the surface)."""
        return self.width() - Theme.COLUMN_WIDTH - Theme.PANEL_MARGIN_RIGHT

    def _hidden_x(self) -> int:
        """Column x when it is parked just past the right edge."""
        return self.width()

    def _park(self) -> None:
        self._column.move(self._rest_x() if self._open else self._hidden_x(), Theme.PANEL_MARGIN_TOP)

    def _on_anim_finished(self) -> None:
        if self._open:
            self._park()  # the compositor may have sized the surface differently while sliding
        else:
            self.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        anim = getattr(self, "_anim", None)
        if anim is None or anim.state() != QAbstractAnimation.State.Running:
            self._park()

    def mousePressEvent(self, event) -> None:
        # A click on the empty (transparent) part of the surface = a click on the desktop: close.
        if self._open and not self._column.geometry().contains(event.position().toPoint()):
            self.dismiss()
        else:
            super().mousePressEvent(event)

    def _place_without_layer_shell(self) -> None:
        screen = self.screen()
        if screen is not None:  # only honoured by compositors that allow client-side positioning
            self.setGeometry(screen.availableGeometry())

    def event(self, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.WindowActivate:
            self._was_active = True
        elif kind == QEvent.Type.WindowDeactivate and self._was_active and self._open and self.auto_hide:
            self._was_active = False
            self.dismiss()
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
        else:
            super().keyPressEvent(event)


class CommandServer(QObject):
    """Receives one-line commands from later `main.py <command>` invocations."""

    command = pyqtSignal(str)

    def __init__(self, path: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        QLocalServer.removeServer(path)  # clear a stale socket from a crashed run
        if not self._server.listen(path):
            log.error("cannot listen on %s: %s", path, self._server.errorString())
        self._server.newConnection.connect(self._on_connection)

    def _on_connection(self) -> None:
        while (sock := self._server.nextPendingConnection()) is not None:
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(lambda s=sock: (self._read(s), s.deleteLater()))
            self._read(sock)

    def _read(self, sock) -> None:
        while sock.canReadLine():
            text = bytes(sock.readLine()).decode(errors="replace").strip()
            if text:
                self.command.emit(text)


def load_pills(services: dict) -> list[QWidget]:
    """Import every pill file that exists; one broken pill must not take the panel down."""
    pills: list[QWidget] = []
    for filename, module_name in PILL_FILES:
        path = BASE_DIR / filename
        if not path.is_file():
            log.debug("skipping %s (not written yet)", filename)
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"nc_{module_name}", path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module  # dataclasses needs the module registered
            spec.loader.exec_module(module)
            pills.append(module.create_pill(services))
        except Exception:
            log.exception("failed to load pill %s", filename)
    return pills


def main(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("BH_DEBUG") else logging.WARNING,
        format="%(name)s: %(levelname)s: %(message)s",
    )
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Ctrl+C works even inside the Qt loop
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland")

    layer_lib = LayerShell.load()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_ID)
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)  # hiding the panel must not end the process
    app.setFont(make_font(Theme.BODY_PT))

    on_wayland = app.platformName() == "wayland"
    if not on_wayland:
        log.warning("Qt platform is %r, not wayland; layer-shell disabled", app.platformName())
    use_layer = layer_lib is not None and on_wayland

    services: dict = {}
    pills = load_pills(services)
    if not pills:
        log.error("no pills could be loaded from %s", BASE_DIR)
        return 1

    window = PanelWindow(pills, layer_shell=use_layer)
    if use_layer:
        window.winId()  # creates the QWindow + platform window without mapping it
        configured = LayerShell.configure(
            layer_lib,
            window.windowHandle(),
            scope=LAYER_SCOPE,
            anchors=LayerShell.ANCHOR_ALL,  # full screen, transparent; see PanelWindow
            layer=LayerShell.LAYER_TOP,
            keyboard=LayerShell.KEYBOARD_ON_DEMAND,
        )
        if not configured:
            log.warning("layer-shell setup failed; the panel will be a normal window")

    if args.demo and services.get("notifications") is not None:
        services["notifications"].add_demo_data()

    def handle(command: str) -> None:
        if command == "toggle":
            window.toggle()
        elif command == "show":
            window.reveal()
        elif command == "hide":
            window.dismiss()
        elif command == "quit":
            app.quit()
        elif command != "ping":
            log.warning("unknown command %r", command)

    server = CommandServer(SOCKET_PATH)
    server.command.connect(handle)

    if not args.hidden:
        window.reveal()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(_ARGS))
