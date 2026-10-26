#!/usr/bin/env python3
"""Wi-Fi popup for Better Hyprland (opened from the arrow on the Wi-Fi tile in Quick Settings).

    python wlan.py [--align-bottom Y] [--right PX]

What it does
    - Lists nearby networks (signal icon, name, lock) and rescans every few seconds.
    - Click a network to connect. Saved and open networks connect straight away; a new secured
      network opens an "Enter Password" row (Enter or the check mark connects).
    - Click anywhere outside the popup, press Esc, or press the X to close it.

Backends (picked automatically, in this order)
    iwd              `iwctl station <iface> ...`      (what your pseudocode used)
    NetworkManager   `nmcli dev wifi ...`             (fallback when iwd is not managing the card)

It is a full-screen transparent layer surface (like the main panel) with the popup placed to the
left of the notification column, so a click on the empty desktop closes it.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import signal
import socket
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
APP_ID = "better-hyprland-nc-wlan"
LAYER_SCOPE = "better-hyprland-nc-wlan"  # starts with better-hyprland-nc, so the blur rule matches it
SOCKET_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", f"{APP_ID}.sock")

PANEL_W, PANEL_H = 308, 382  # px at 1366x768 (mockup 431x537 on a 1920x1080 canvas)
ROW_H = 42
PW_H = 34
DEFAULT_RIGHT = 12 + 344 + 12  # screen margin + notification column + gap
DEFAULT_BOTTOM = 678  # where the Quick Settings pill ends when it is not told otherwise
REFRESH_MS = 6000
CONNECT_TIMEOUT_MS = 25000

log = logging.getLogger(APP_ID)


# ------------------------------------------------------- stage 1: a second launch closes the first


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="wlan.py", description="Better Hyprland Wi-Fi popup")
    parser.add_argument("--align-bottom", type=int, default=DEFAULT_BOTTOM, help="y of the popup's bottom edge")
    parser.add_argument("--right", type=int, default=DEFAULT_RIGHT, help="gap between the popup and the screen's right edge")
    return parser.parse_args(argv)


def _close_running_instance() -> bool:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(0.3)
    try:
        client.connect(SOCKET_PATH)
        client.sendall(b"quit\n")
        return True
    except OSError:
        return False
    finally:
        client.close()


if __name__ == "__main__":
    _ARGS = _parse_args(sys.argv[1:])
    if _close_running_instance():  # arrow clicked twice = open, then close
        sys.exit(0)

# ----------------------------------------------------------- stage 2: the popup process

sys.path.insert(0, str(BASE_DIR))

from PyQt6.QtCore import (  # noqa: E402
    QEasingCurve,
    QObject,
    QPoint,
    QProcess,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from common import CloseButton, ElidedLabel, HoverTracker, MaterialIcon, Pill, Theme, make_font, make_label, run_async  # noqa: E402
from main import CommandServer, LayerShell  # noqa: E402  (reuses the layer-shell bridge + socket server)


# ------------------------------------------------------------------------ pure helpers

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def bars_from_percent(percent: int) -> int:
    return 1 if percent <= 25 else 2 if percent <= 50 else 3 if percent <= 75 else 4


def signal_icon(bars: int) -> tuple[str, str]:
    """(Material Symbols name, plain-glyph fallback)."""
    if bars <= 1:
        return "wifi_1_bar", "📶"
    if bars == 2:
        return "wifi_2_bar", "📶"
    return "wifi", "📶"


@dataclass
class Network:
    ssid: str
    security: str  # "open" | "psk" | "8021x" | "wep" | NetworkManager's text (e.g. "WPA2")
    strength: int  # 0..100
    connected: bool = False
    known: bool = False

    @property
    def secured(self) -> bool:
        return self.security != "open"

    @property
    def bars(self) -> int:
        return bars_from_percent(self.strength)


def sort_networks(networks: list[Network]) -> list[Network]:
    return sorted(networks, key=lambda n: (not n.connected, -n.strength, n.ssid.lower()))


def find_wifi_interface(base: str = "/sys/class/net") -> str:
    """First network interface that is a Wi-Fi card ("" if there is none)."""
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return ""
    for name in names:
        if os.path.exists(os.path.join(base, name, "wireless")) or os.path.exists(os.path.join(base, name, "phy80211")):
            return name
    return ""


_IWD_ROW = re.compile(r"^\s*(>)?\s*(.+?)\s{2,}(open|psk|8021x|wep)\s+(\S.*?)\s*$", re.IGNORECASE)
_IWD_KNOWN_ROW = re.compile(r"^\s*(.+?)\s{2,}(open|psk|8021x|wep)\b", re.IGNORECASE)


def parse_iwd_networks(text: str) -> list[Network]:
    """`iwctl station <iface> get-networks` -> networks (">" marks the connected one, stars = signal)."""
    networks = []
    for raw in text.splitlines():
        # iwctl draws unlit signal stars in dim grey (ESC[1;90m); count only the lit ones
        lit = re.split(r"\x1b\[[0-9;]*90m", raw, maxsplit=1)[0]
        match = _IWD_ROW.match(strip_ansi(lit)) or _IWD_ROW.match(strip_ansi(raw))
        if not match:
            continue
        marker, ssid, security, signal_text = match.groups()
        stars = signal_text.count("*")
        networks.append(
            Network(ssid.strip(), security.lower(), min(4, stars) * 25 if stars else 50, connected=bool(marker))
        )
    return networks


def parse_iwd_known(text: str) -> set[str]:
    """`iwctl known-networks list` -> saved network names."""
    names = set()
    for line in strip_ansi(text).splitlines():
        match = _IWD_KNOWN_ROW.match(line)
        if match:
            names.add(match.group(1).strip())
    return names


def split_nmcli(line: str) -> list[str]:
    """Split a `nmcli -t` line on ':' (a literal ':' or '\\' inside a field is escaped with '\\')."""
    parts: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(line):
        char = line[i]
        if char == "\\" and i + 1 < len(line):
            current.append(line[i + 1])
            i += 2
        elif char == ":":
            parts.append("".join(current))
            current = []
            i += 1
        else:
            current.append(char)
            i += 1
    parts.append("".join(current))
    return parts


def parse_nm_networks(text: str) -> list[Network]:
    """`nmcli -t -f IN-USE,SSID,SECURITY,SIGNAL dev wifi list` -> one Network per SSID (strongest AP)."""
    best: dict[str, Network] = {}
    for line in text.splitlines():
        parts = split_nmcli(line)
        if len(parts) < 4:
            continue
        in_use, ssid, security, signal_text = parts[:4]
        if not ssid:  # hidden network
            continue
        try:
            percent = int(signal_text)
        except ValueError:
            percent = 0
        network = Network(
            ssid, "open" if security.strip() in ("", "--") else security.strip(), percent, connected=in_use.strip() == "*"
        )
        old = best.get(ssid)
        if old is None or network.connected or (not old.connected and network.strength > old.strength):
            best[ssid] = network
    return list(best.values())


def parse_nm_known(text: str) -> set[str]:
    """`nmcli -t -f NAME,TYPE connection show` -> names of saved Wi-Fi profiles."""
    names = set()
    for line in text.splitlines():
        parts = split_nmcli(line)
        if len(parts) >= 2 and parts[1] in ("802-11-wireless", "wifi"):
            names.add(parts[0])
    return names


# ------------------------------------------------------------------------ backends


class WifiBackend(QObject):
    """Shared flow; subclasses supply the commands and parsers. All calls are asynchronous."""

    networks_ready = pyqtSignal(list)  # sorted list[Network]
    connect_finished = pyqtSignal(str, bool)  # ssid, connected

    program = ""

    def __init__(self, iface: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.iface = iface

    # -- hooks
    def list_args(self) -> list[str]:
        raise NotImplementedError

    def known_args(self) -> list[str]:
        raise NotImplementedError

    def scan_args(self) -> list[str]:
        raise NotImplementedError

    def parse_list(self, text: str) -> list[Network]:
        raise NotImplementedError

    def parse_known(self, text: str) -> set[str]:
        raise NotImplementedError

    def _connect_command(self, ssid: str, password: str | None, known: bool, done: Callable[[], None]) -> None:
        raise NotImplementedError

    # -- shared
    def scan(self) -> None:
        run_async(self, self.program, self.scan_args())

    def fetch(self, callback: Callable[[list[Network]], None] | None = None) -> None:
        """Read the network list and the saved networks, then emit `networks_ready`."""
        state: dict = {}

        def finish() -> None:
            if "list" not in state or "known" not in state:
                return
            networks = state["list"]
            for network in networks:
                network.known = network.connected or network.ssid in state["known"]
            networks = sort_networks(networks)
            self.networks_ready.emit(networks)
            if callback is not None:
                callback(networks)

        def got_list(code: int, out: str) -> None:
            state["list"] = self.parse_list(out) if code == 0 else []
            finish()

        def got_known(code: int, out: str) -> None:
            state["known"] = self.parse_known(out) if code == 0 else set()
            finish()

        run_async(self, self.program, self.list_args(), got_list)
        run_async(self, self.program, self.known_args(), got_known)

    def connect_to(self, ssid: str, password: str | None, known: bool) -> None:
        def after_command() -> None:
            # Exit codes differ between versions, so the network list decides if it worked.
            def check(networks: list[Network]) -> None:
                ok = any(n.ssid == ssid and n.connected for n in networks)
                self.connect_finished.emit(ssid, ok)

            QTimer.singleShot(600, lambda: self.fetch(check))

        self._connect_command(ssid, password, known, after_command)

    def _run_connect(self, args: list[str], callback: Callable[[int, str], None]) -> None:
        """Run a connect command with stdin closed (no prompts) and a hard timeout."""
        proc = run_async(self, self.program, args, callback)
        proc.closeWriteChannel()

        def kill() -> None:
            try:
                if proc.state() != QProcess.ProcessState.NotRunning:
                    proc.kill()
            except RuntimeError:  # already finished and deleted
                pass

        QTimer.singleShot(CONNECT_TIMEOUT_MS, kill)


class IwdBackend(WifiBackend):
    program = "iwctl"

    def list_args(self) -> list[str]:
        return ["station", self.iface, "get-networks"]

    def known_args(self) -> list[str]:
        return ["known-networks", "list"]

    def scan_args(self) -> list[str]:
        return ["station", self.iface, "scan"]

    def parse_list(self, text: str) -> list[Network]:
        return parse_iwd_networks(text)

    def parse_known(self, text: str) -> set[str]:
        return parse_iwd_known(text)

    def _connect_command(self, ssid: str, password: str | None, known: bool, done: Callable[[], None]) -> None:
        def connect() -> None:
            options = [f"--passphrase={password}"] if password else []
            self._run_connect([*options, "station", self.iface, "connect", ssid], lambda *_: done())

        if password and known:  # the saved passphrase did not work: forget it, then use the new one
            run_async(self, self.program, ["known-networks", ssid, "forget"], lambda *_: connect())
        else:
            connect()


class NmBackend(WifiBackend):
    program = "nmcli"

    def list_args(self) -> list[str]:
        return ["-t", "-f", "IN-USE,SSID,SECURITY,SIGNAL", "dev", "wifi", "list", "ifname", self.iface]

    def known_args(self) -> list[str]:
        return ["-t", "-f", "NAME,TYPE", "connection", "show"]

    def scan_args(self) -> list[str]:
        return ["dev", "wifi", "rescan", "ifname", self.iface]

    def parse_list(self, text: str) -> list[Network]:
        return parse_nm_networks(text)

    def parse_known(self, text: str) -> set[str]:
        return parse_nm_known(text)

    def _connect_command(self, ssid: str, password: str | None, known: bool, done: Callable[[], None]) -> None:
        up = ["-w", "20", "connection", "up", "id", ssid, "ifname", self.iface]
        if known and not password:
            self._run_connect(up, lambda *_: done())
        elif known:  # replace the saved password, then connect
            run_async(
                self,
                self.program,
                ["connection", "modify", "id", ssid, "wifi-sec.psk", password],
                lambda *_: self._run_connect(up, lambda *_: done()),
            )
        else:
            args = ["-w", "20", "dev", "wifi", "connect", ssid, *(["password", password] if password else []), "ifname", self.iface]

            def after(code: int, _out: str) -> None:
                if code != 0 and password:  # drop the half-made profile a wrong password leaves behind
                    run_async(self, self.program, ["connection", "delete", "id", ssid], lambda *_: done())
                else:
                    done()

            self._run_connect(args, after)


def detect_backend(owner, iface: str, done: Callable[[str], None]) -> None:
    """done("iwd" | "nm" | ""): iwd if it manages this card, else NetworkManager if it is running."""

    def try_nm() -> None:
        if not shutil.which("nmcli"):
            done("")
            return
        run_async(
            owner,
            "nmcli",
            ["-t", "-f", "RUNNING", "general"],
            lambda code, out: done("nm" if code == 0 and "running" in out.lower() else ""),
        )

    if shutil.which("iwctl"):

        def got(code: int, out: str) -> None:
            if code == 0 and "state" in strip_ansi(out).lower():
                done("iwd")
            else:
                try_nm()

        run_async(owner, "iwctl", ["station", iface, "show"], got)
    else:
        try_nm()


# ------------------------------------------------------------------------ widgets

_SCROLL_QSS = """
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 4px; margin: 0; }
QScrollBar::handle:vertical { background: rgba(255, 255, 255, 90); border-radius: 2px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""

_PASSWORD_QSS = """
QLineEdit { background: transparent; border: none; color: #1B0B2E;
            selection-background-color: #CC6EDD; selection-color: white; }
"""

DARK_ICON = QColor("#1B0B2E")


class RowHead(QWidget):
    """The clickable top line of a network row, with a soft hover highlight."""

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(ROW_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = HoverTracker(self)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, int(26 * self._hover.value)))
        painter.drawRoundedRect(QRectF(self.rect()), 12, 12)


class PasswordBox(QWidget):
    """White "Enter Password" field with a check mark, as in the mockup."""

    submitted = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 8, 0)
        layout.setSpacing(6)
        self._edit = QLineEdit()
        self._edit.setPlaceholderText("Enter Password")
        self._edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit.setFrame(False)
        self._edit.setFont(make_font(Theme.BODY_PT))
        self._edit.setStyleSheet(_PASSWORD_QSS)
        self._ok = MaterialIcon("check", "✓", 20, color=DARK_ICON, clickable=True)
        layout.addWidget(self._edit, 1)
        layout.addWidget(self._ok)
        self._edit.returnPressed.connect(self._submit)
        self._ok.clicked.connect(self._submit)

    def _submit(self) -> None:
        if self._edit.text():
            self.submitted.emit(self._edit.text())

    def focus_field(self) -> None:
        self._edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def clear(self) -> None:
        self._edit.clear()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 238))
        painter.drawRoundedRect(QRectF(self.rect()), 12, 12)


class NetworkRow(QWidget):
    selected = pyqtSignal(str)  # ssid: the row was clicked
    password_submitted = pyqtSignal(str, str)  # ssid, password

    def __init__(self, network: Network, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.network = network
        self._pw_open = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._head = RowHead()
        head = QHBoxLayout(self._head)
        head.setContentsMargins(10, 0, 10, 0)
        head.setSpacing(10)
        self._signal = MaterialIcon("wifi", "📶", 22, color=Theme.TEXT)
        self._name = ElidedLabel(network.ssid, Theme.BODY_PT)
        self._status = ElidedLabel("", Theme.SMALL_PT, color=Theme.TEXT_DIM)
        self._status.hide()
        names = QVBoxLayout()
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(0)
        names.addStretch(1)
        names.addWidget(self._name)
        names.addWidget(self._status)
        names.addStretch(1)
        self._trailing = MaterialIcon("lock", "🔒", 18, color=Theme.TEXT_DIM)
        head.addWidget(self._signal, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addLayout(names, 1)
        head.addWidget(self._trailing, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._head)

        self._pw = PasswordBox()
        self._pw.setMaximumHeight(0)
        self._pw.hide()
        layout.addWidget(self._pw)
        self._pw_anim = QPropertyAnimation(self._pw, b"maximumHeight", self)
        self._pw_anim.setDuration(Theme.ANIM)
        self._pw_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._pw_anim.finished.connect(self._on_pw_anim_done)

        self._head.clicked.connect(lambda: self.selected.emit(self.network.ssid))
        self._pw.submitted.connect(lambda text: self.password_submitted.emit(self.network.ssid, text))
        self.update_network(network)

    @property
    def password_open(self) -> bool:
        return self._pw_open

    def update_network(self, network: Network) -> None:
        self.network = network
        self._signal.set_icon(*signal_icon(network.bars))
        self._name.setFont(make_font(Theme.BODY_PT, bold=network.connected))
        self._name.update()
        if network.connected:
            self._trailing.set_icon("check", "✓")
            self._trailing.show()
        elif network.secured:
            self._trailing.set_icon("lock", "🔒")
            self._trailing.show()
        else:
            self._trailing.hide()

    def set_status(self, text: str) -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text))

    def set_busy(self, busy: bool) -> None:
        self._pw.setEnabled(not busy)

    def clear_password(self) -> None:
        self._pw.clear()

    def open_password(self, show: bool) -> None:
        if show == self._pw_open:
            if show:
                self._pw.focus_field()
            return
        self._pw_open = show
        self._pw_anim.stop()
        if show:
            self._pw.show()
        self._pw_anim.setStartValue(self._pw.maximumHeight())
        self._pw_anim.setEndValue(PW_H if show else 0)
        self._pw_anim.start()
        if show:
            self._pw.focus_field()

    def _on_pw_anim_done(self) -> None:
        if not self._pw_open:
            self._pw.hide()


class WlanPanel(Pill):
    close_requested = pyqtSignal()

    def __init__(self, iface: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(PANEL_W, PANEL_H)
        self._iface = iface
        self._backend: WifiBackend | None = None
        self._rows: dict[str, NetworkRow] = {}
        self._connecting = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(Theme.PILL_PADDING, 12, Theme.PILL_PADDING, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(make_label("Wi-Fi", Theme.TITLE_PT, bold=True))
        self._hint = make_label("", Theme.SMALL_PT, color=Theme.TEXT_DIM)
        header.addWidget(self._hint)
        header.addStretch(1)
        close = CloseButton()
        close.clicked.connect(self.close_requested)
        header.addWidget(close)
        root.addLayout(header)

        body = QWidget()
        self._stack = QStackedLayout(body)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._message = make_label("", Theme.BODY_PT, color=Theme.TEXT_DIM, align=Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)
        self._stack.addWidget(self._message)
        self._scroll = QScrollArea()
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.setStyleSheet(_SCROLL_QSS)
        host = QWidget()
        self._list = QVBoxLayout(host)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(4)
        self._list.addStretch(1)
        self._scroll.setWidget(host)
        self._stack.addWidget(self._scroll)
        root.addWidget(body, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        QTimer.singleShot(0, self._start)

    # -- startup
    def _start(self) -> None:
        if not self._iface:
            self._show_message("No Wi-Fi adapter found")
            return
        self._show_message("Looking for networks…")
        self._hint.setText("Scanning…")
        detect_backend(self, self._iface, self._on_backend)

    def _on_backend(self, name: str) -> None:
        if name == "iwd":
            self._backend = IwdBackend(self._iface, self)
        elif name == "nm":
            self._backend = NmBackend(self._iface, self)
        else:
            self._hint.setText("")
            self._show_message("Neither iwd nor NetworkManager is managing Wi-Fi")
            return
        self._backend.networks_ready.connect(self._on_networks)
        self._backend.connect_finished.connect(self._on_connect_finished)
        self._refresh()
        self._timer.start()

    def _refresh(self) -> None:
        if self._backend is None or self._connecting:
            return
        self._backend.fetch()  # what is cached shows at once
        self._backend.scan()
        QTimer.singleShot(2000, self._backend.fetch)  # the fresh scan results

    def _show_message(self, text: str) -> None:
        self._message.setText(text)
        self._stack.setCurrentIndex(0)

    # -- network list
    def _frozen(self) -> bool:
        return bool(self._connecting) or any(row.password_open for row in self._rows.values())

    def _on_networks(self, networks: list) -> None:
        self._hint.setText("")
        seen = set()
        for network in networks:
            seen.add(network.ssid)
            row = self._rows.get(network.ssid)
            if row is None:
                row = NetworkRow(network)
                row.selected.connect(self._on_selected)
                row.password_submitted.connect(self._on_password)
                self._rows[network.ssid] = row
                self._list.insertWidget(self._list.count() - 1, row)  # above the trailing stretch
            else:
                row.update_network(network)
        for ssid in [s for s in self._rows if s not in seen and s != self._connecting]:
            row = self._rows.pop(ssid)
            row.hide()
            row.deleteLater()
        if not self._frozen():  # do not shuffle rows while someone is typing a password
            for index, network in enumerate(n for n in networks if n.ssid in self._rows):
                row = self._rows[network.ssid]
                if self._list.indexOf(row) != index:
                    self._list.removeWidget(row)
                    self._list.insertWidget(index, row)
        if self._rows:
            self._stack.setCurrentIndex(1)
        else:
            self._show_message("No networks found")

    # -- connecting
    def _on_selected(self, ssid: str) -> None:
        row = self._rows.get(ssid)
        if row is None or self._connecting:
            return
        network = row.network
        if network.connected:
            return
        if network.security == "8021x" and not network.known:
            row.set_status("Enterprise networks aren't supported here")
            return
        if not network.secured or network.known:
            self._connect(ssid, None)
            return
        opening = not row.password_open  # new secured network: ask for the password
        for other in self._rows.values():
            if other is not row:
                other.open_password(False)
        row.set_status("")
        row.open_password(opening)

    def _on_password(self, ssid: str, password: str) -> None:
        if not self._connecting:
            self._connect(ssid, password)

    def _connect(self, ssid: str, password: str | None) -> None:
        row = self._rows.get(ssid)
        if row is None or self._backend is None:
            return
        self._connecting = ssid
        row.set_status("Connecting…")
        row.set_busy(True)
        self._backend.connect_to(ssid, password, row.network.known)

    def _on_connect_finished(self, ssid: str, ok: bool) -> None:
        self._connecting = ""
        row = self._rows.get(ssid)
        if row is None:
            return
        row.set_busy(False)
        if ok:
            row.set_status("")
            row.clear_password()
            row.open_password(False)
        elif row.network.secured:
            row.set_status("Couldn't connect. Wrong password?")
            row.open_password(True)  # let the user type it again
        else:
            row.set_status("Couldn't connect")


class WlanWindow(QWidget):
    """Full-screen transparent surface holding the popup; a click outside the popup closes it."""

    def __init__(self, iface: str, *, layer_shell: bool, right: int, bottom: int) -> None:
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if not layer_shell:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setWindowTitle("Better Hyprland Wi-Fi")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._layer = layer_shell
        self._right = right
        self._bottom = bottom
        self._closing = False
        self._t = 0.0

        self.panel = WlanPanel(iface, self)
        self.panel.close_requested.connect(self.close_animated)
        self._effect = QGraphicsOpacityEffect(self.panel)
        self._effect.setOpacity(0.0)
        self.panel.setGraphicsEffect(self._effect)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(Theme.ANIM)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_t)
        self._anim.finished.connect(self._on_anim_finished)

        if layer_shell:
            screen = QApplication.primaryScreen()
            self.resize(screen.size() if screen is not None else self.size().expandedTo(self.panel.size()))
        else:
            self.resize(PANEL_W, PANEL_H)
        self._on_t(0.0)

    def _target(self) -> QPoint:
        if not self._layer:
            return QPoint(0, 0)
        x = self.width() - self._right - PANEL_W
        y = max(12, min(self._bottom - PANEL_H, self.height() - PANEL_H - 12))
        return QPoint(x, y)

    def _on_t(self, t) -> None:
        self._t = float(t)
        self._effect.setOpacity(self._t)
        target = self._target()
        self.panel.move(target.x() + int(16 * (1.0 - self._t)), target.y())  # drifts in from the right

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_anim"):
            self._on_t(self._t)

    def _animate_to(self, end: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(end)
        self._anim.start()

    def open_animated(self) -> None:
        self.show()
        self._animate_to(1.0)

    def close_animated(self) -> None:
        if not self._closing:
            self._closing = True
            self._animate_to(0.0)

    def _on_anim_finished(self) -> None:
        if self._closing:
            QApplication.quit()

    def mousePressEvent(self, event) -> None:
        if self._layer and not self.panel.geometry().contains(event.position().toPoint()):
            self.close_animated()  # a click on the empty desktop
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close_animated()
        else:
            super().keyPressEvent(event)


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("BH_DEBUG") else logging.WARNING,
        format="%(name)s: %(levelname)s: %(message)s",
    )
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland")

    layer_lib = LayerShell.load()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_ID)
    app.setDesktopFileName(APP_ID)
    app.setFont(make_font(Theme.BODY_PT))
    use_layer = layer_lib is not None and app.platformName() == "wayland"

    window = WlanWindow(find_wifi_interface(), layer_shell=use_layer, right=args.right, bottom=args.align_bottom)
    if use_layer:
        window.winId()  # create the platform window without mapping it
        if not LayerShell.configure(
            layer_lib,
            window.windowHandle(),
            scope=LAYER_SCOPE,
            anchors=LayerShell.ANCHOR_ALL,
            layer=LayerShell.LAYER_TOP,
            keyboard=LayerShell.KEYBOARD_ON_DEMAND,
        ):
            log.warning("layer-shell setup failed; the popup will be a normal window")

    server = CommandServer(SOCKET_PATH)
    server.command.connect(lambda command: window.close_animated() if command == "quit" else None)
    window.open_animated()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run(_ARGS))
