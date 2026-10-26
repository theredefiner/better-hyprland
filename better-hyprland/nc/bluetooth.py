#!/usr/bin/env python3
"""Bluetooth popup for Better Hyprland (opened from the arrow on the Bluetooth tile in Quick Settings).

    python bluetooth.py [--align-bottom Y] [--right PX]

    - Scans for devices (`bluetoothctl scan on`) and lists them: icon, name, check mark when connected.
    - Click a paired device to connect, click a connected one to disconnect.
    - Click a new device to pair: if the device shows a code, a confirm row asks "Yes / No"
      (the answer is sent to bluetoothctl's pairing agent). Then it is trusted and connected.
    - Click outside the popup, press Esc, or press the X to close it.

Same shell as wlan.py (full-screen transparent layer surface, popup placed left of the notification
column); only the device list and the commands differ. Needs wlan.py, main.py and common.py next to it.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

APP_ID = "better-hyprland-nc-bluetooth"
LAYER_SCOPE = "better-hyprland-nc-bluetooth"  # starts with better-hyprland-nc: the blur rule matches it
SOCKET_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", f"{APP_ID}.sock")

log = logging.getLogger(APP_ID)


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
    if _close_running_instance():  # arrow clicked twice = open, then close
        sys.exit(0)

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
from PyQt6.QtGui import QPainter  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from common import (  # noqa: E402
    CloseButton,
    ElidedLabel,
    MaterialIcon,
    Pill,
    TextButton,
    Theme,
    c_locale_env,
    make_font,
    make_label,
    run_async,
)
from main import CommandServer, LayerShell  # noqa: E402
from wlan import (  # noqa: E402
    _SCROLL_QSS,
    DEFAULT_BOTTOM,
    DEFAULT_RIGHT,
    PANEL_H,
    PANEL_W,
    ROW_H,
    RowHead,
    _parse_args,
    strip_ansi,
)

REFRESH_MS = 4000
SCAN_SECONDS = 10
PAIR_TIMEOUT_MS = 45000
CONNECT_SECONDS = 15
CONFIRM_H = 64


# ------------------------------------------------------------------------ pure helpers

_MAC = r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}"
_DEVICE_LINE = re.compile(rf"^\s*Device\s+({_MAC})\s+(.*?)\s*$")


@dataclass
class Device:
    mac: str
    name: str
    paired: bool = False
    connected: bool = False


def parse_devices(text: str) -> dict[str, str]:
    """`bluetoothctl devices [Paired|Connected]` -> {MAC: name} (devices without a real name are skipped)."""
    found = {}
    for line in strip_ansi(text).splitlines():
        match = _DEVICE_LINE.match(line)
        if not match:
            continue
        mac, name = match.groups()
        if name and name.replace("-", ":").upper() != mac.upper():  # unnamed devices are listed by address
            found[mac.upper()] = name
    return found


def merge_devices(all_text: str, paired_text: str, connected_text: str) -> list[Device]:
    paired = set(parse_devices(paired_text))
    connected = set(parse_devices(connected_text))
    names = parse_devices(all_text)
    for mac, name in {**parse_devices(paired_text), **parse_devices(connected_text)}.items():
        names.setdefault(mac, name)
    devices = [Device(mac, name, mac in paired or mac in connected, mac in connected) for mac, name in names.items()]
    return sorted(devices, key=lambda d: (not d.connected, not d.paired, d.name.lower()))


def icon_for(name: str) -> tuple[str, str]:
    """(Material Symbols name, plain fallback) guessed from the device name."""
    lower = name.lower()
    table = (
        (("headphone", "headset", "buds", "airpods", "earbud", "earphone", "wh-", "wf-"), ("headphones", "♫")),
        (("speaker", "soundbar", "boombox", "jbl", "echo"), ("speaker", "♪")),
        (("keyboard", "kbd"), ("keyboard", "⌨")),
        (("mouse", "trackpad", "mx master"), ("mouse", "◐")),
        (("phone", "galaxy", "pixel", "redmi", "xiaomi", "oneplus", "poco"), ("smartphone", "▯")),
        (("watch", "band"), ("watch", "◔")),
        (("tv", "bravia"), ("tv", "▭")),
        (("controller", "gamepad", "dualsense", "xbox"), ("sports_esports", "◉")),
    )
    for keys, icon in table:
        if any(key in lower for key in keys):
            return icon
    return "bluetooth", "B"


_CONFIRM = re.compile(r"Confirm passkey\s+(\d+)", re.IGNORECASE)
_PIN = re.compile(r"(Request PIN code|Request passkey|Enter PIN code|Enter passkey)", re.IGNORECASE)
_FAILED_PAIR = re.compile(r"Failed to pair:?\s*([^\n\r]*)", re.IGNORECASE)
_FAILED_CONNECT = re.compile(r"Failed to connect:?\s*([^\n\r]*)", re.IGNORECASE)


def scan_pair_output(text: str) -> dict:
    """Facts found so far in a pairing session's output (re-run on the whole buffer each time)."""
    clean = strip_ansi(text)
    confirm = _CONFIRM.search(clean)
    failed_pair = _FAILED_PAIR.search(clean)
    failed_connect = _FAILED_CONNECT.search(clean)
    return {
        "code": confirm.group(1) if confirm else "",
        "needs_pin": bool(_PIN.search(clean)),
        "authorize": "Authorize service" in clean,
        "paired": "Pairing successful" in clean or "AlreadyExists" in clean,
        "connected": "Connection successful" in clean,
        "failed_pair": failed_pair.group(1).strip() if failed_pair else None,
        "failed_connect": failed_connect.group(1).strip() if failed_connect else None,
    }


def friendly_error(reason: str | None) -> str:
    if not reason:
        return "Couldn't connect"
    lower = reason.lower()
    if "authentication" in lower or "canceled" in lower or "rejected" in lower:
        return "Pairing was cancelled"
    if "timeout" in lower or "timed out" in lower:
        return "Timed out. Is the device in pairing mode?"
    if "not available" in lower or "page-timeout" in lower:
        return "Device not reachable"
    return "Couldn't connect"


# ------------------------------------------------------------------------ backend


class PairSession(QObject):
    """One interactive `bluetoothctl` with a pairing agent: pair -> trust -> connect."""

    confirm_requested = pyqtSignal(str)  # passkey
    status = pyqtSignal(str)
    finished = pyqtSignal(bool, str)  # ok, message

    def __init__(self, mac: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mac = mac
        self._buffer = ""
        self._asked = False
        self._sent_connect = False
        self._authorized = False
        self._done = False
        self._proc = QProcess(self)
        self._proc.setProcessEnvironment(c_locale_env())
        self._proc.readyReadStandardOutput.connect(self._on_output)
        self._proc.errorOccurred.connect(self._on_error)
        self._proc.start("bluetoothctl", [])
        self._send("agent KeyboardDisplay", "default-agent", f"pair {mac}")
        self.status.emit("Pairing…")
        QTimer.singleShot(PAIR_TIMEOUT_MS, lambda: self._finish(False, "Timed out. Is the device in pairing mode?"))

    def _send(self, *lines: str) -> None:
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.write(("\n".join(lines) + "\n").encode())

    def answer(self, yes: bool) -> None:
        self._send("yes" if yes else "no")
        if not yes:
            self.status.emit("Cancelling…")

    def cancel(self) -> None:
        self._finish(False, "Pairing was cancelled")

    def _on_error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._finish(False, "bluetoothctl could not start")

    def _on_output(self) -> None:
        self._buffer += bytes(self._proc.readAllStandardOutput()).decode(errors="replace")
        facts = scan_pair_output(self._buffer)
        if facts["authorize"] and not self._authorized:
            self._authorized = True
            self._send("yes")
        if facts["needs_pin"]:
            self._finish(False, "This device needs a PIN, which isn't supported")
        elif facts["code"] and not self._asked:
            self._asked = True
            self.confirm_requested.emit(facts["code"])
        elif facts["failed_pair"] is not None and "AlreadyExists" not in facts["failed_pair"]:
            self._finish(False, friendly_error(facts["failed_pair"]))
        elif facts["paired"] and not self._sent_connect:
            self._sent_connect = True
            self.status.emit("Connecting…")
            self._send(f"trust {self._mac}", f"connect {self._mac}")
        elif facts["connected"]:
            self._finish(True, "")
        elif self._sent_connect and facts["failed_connect"] is not None:
            self._finish(False, friendly_error(facts["failed_connect"]))

    def _finish(self, ok: bool, message: str) -> None:
        if self._done:
            return
        self._done = True
        self._send("quit")
        QTimer.singleShot(800, self._kill)
        self.finished.emit(ok, message)

    def _kill(self) -> None:
        try:
            if self._proc.state() != QProcess.ProcessState.NotRunning:
                self._proc.kill()
        except RuntimeError:
            pass


class BluetoothBackend(QObject):
    devices_ready = pyqtSignal(list)
    action_finished = pyqtSignal(str, bool, str)  # mac, ok, message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._scan: QProcess | None = None

    def check(self, callback) -> None:
        """callback("ok" | "off" | "none" | "missing")."""
        if not shutil.which("bluetoothctl"):
            callback("missing")
            return

        def got(code: int, out: str) -> None:
            text = strip_ansi(out)
            if code != 0 or "Controller" not in text:
                callback("none")
            elif re.search(r"Powered:\s*no", text):
                callback("off")
            else:
                callback("ok")

        run_async(self, "bluetoothctl", ["show"], got)

    def scan(self) -> None:
        if self._scan is not None:
            return
        proc = QProcess(self)
        proc.setProcessEnvironment(c_locale_env())

        def done(*_args) -> None:
            self._scan = None
            proc.deleteLater()

        proc.finished.connect(done)
        proc.errorOccurred.connect(done)
        self._scan = proc
        proc.start("bluetoothctl", ["--timeout", str(SCAN_SECONDS), "scan", "on"])

    def stop_scan(self) -> None:
        if self._scan is not None:
            self._scan.kill()

    def fetch(self, callback=None) -> None:
        texts: dict[str, str] = {}

        def got(key: str):
            def handler(code: int, out: str) -> None:
                texts[key] = out if code == 0 else ""
                if len(texts) == 3:
                    devices = merge_devices(texts["all"], texts["paired"], texts["connected"])
                    self.devices_ready.emit(devices)
                    if callback is not None:
                        callback(devices)

            return handler

        run_async(self, "bluetoothctl", ["devices"], got("all"))
        run_async(self, "bluetoothctl", ["devices", "Paired"], got("paired"))
        run_async(self, "bluetoothctl", ["devices", "Connected"], got("connected"))

    def connect_device(self, mac: str) -> None:
        def got(_code: int, out: str) -> None:
            facts = scan_pair_output(out)
            ok = facts["connected"]
            self.action_finished.emit(mac, ok, "" if ok else friendly_error(facts["failed_connect"]))

        proc = run_async(self, "bluetoothctl", ["--timeout", str(CONNECT_SECONDS), "connect", mac], got)
        proc.closeWriteChannel()

    def disconnect_device(self, mac: str) -> None:
        run_async(self, "bluetoothctl", ["disconnect", mac], lambda _c, out: self.action_finished.emit(mac, "successful" in out.lower(), "Couldn't disconnect"))


# ------------------------------------------------------------------------ widgets


class ConfirmBox(QWidget):
    """"Pair with <device>? Code 123456   [Yes] [No]" row."""

    answered = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)
        self._text = make_label("", Theme.SMALL_PT)
        self._text.setWordWrap(True)
        layout.addWidget(self._text)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        yes = TextButton("Yes")
        no = TextButton("No")
        yes.clicked.connect(lambda: self.answered.emit(True))
        no.clicked.connect(lambda: self.answered.emit(False))
        buttons.addWidget(yes)
        buttons.addWidget(no)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def set_request(self, name: str, code: str) -> None:
        self._text.setText(f"Are you sure you want to connect with {name}?\nConfirmation code: {code}")

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Theme.PILL_FILL)
        painter.drawRoundedRect(QRectF(self.rect()), 12, 12)


class DeviceRow(QWidget):
    selected = pyqtSignal(str)  # mac
    answered = pyqtSignal(str, bool)  # mac, yes/no

    def __init__(self, device: Device, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.device = device
        self._confirm_open = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._head = RowHead()
        head = QHBoxLayout(self._head)
        head.setContentsMargins(10, 0, 10, 0)
        head.setSpacing(10)
        self._icon = MaterialIcon("bluetooth", "B", 22, color=Theme.TEXT)
        self._name = ElidedLabel(device.name, Theme.BODY_PT)
        self._status = ElidedLabel("", Theme.SMALL_PT, color=Theme.TEXT_DIM)
        self._status.hide()
        names = QVBoxLayout()
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(0)
        names.addStretch(1)
        names.addWidget(self._name)
        names.addWidget(self._status)
        names.addStretch(1)
        self._trailing = MaterialIcon("check", "✓", 18, color=Theme.TEXT_DIM)
        head.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addLayout(names, 1)
        head.addWidget(self._trailing, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._head)

        self._box = ConfirmBox()
        self._box.setMaximumHeight(0)
        self._box.hide()
        layout.addWidget(self._box)
        self._anim = QPropertyAnimation(self._box, b"maximumHeight", self)
        self._anim.setDuration(Theme.ANIM)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_anim_done)

        self._head.clicked.connect(lambda: self.selected.emit(self.device.mac))
        self._box.answered.connect(lambda yes: self.answered.emit(self.device.mac, yes))
        self.update_device(device)

    @property
    def confirm_open(self) -> bool:
        return self._confirm_open

    def update_device(self, device: Device) -> None:
        self.device = device
        self._icon.set_icon(*icon_for(device.name))
        self._name.setFont(make_font(Theme.BODY_PT, bold=device.connected))
        self._name.update()
        self._trailing.setVisible(device.connected)

    def set_status(self, text: str) -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text))

    def show_confirm(self, code: str) -> None:
        self._box.set_request(self.device.name, code)
        self._set_confirm(True)

    def hide_confirm(self) -> None:
        self._set_confirm(False)

    def _set_confirm(self, show: bool) -> None:
        if show == self._confirm_open:
            return
        self._confirm_open = show
        self._anim.stop()
        if show:
            self._box.show()
        self._anim.setStartValue(self._box.maximumHeight())
        self._anim.setEndValue(CONFIRM_H if show else 0)
        self._anim.start()

    def _on_anim_done(self) -> None:
        if not self._confirm_open:
            self._box.hide()


class BluetoothPanel(Pill):
    close_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(PANEL_W, PANEL_H)
        self._backend = BluetoothBackend(self)
        self._rows: dict[str, DeviceRow] = {}
        self._busy = ""  # MAC of the device being paired/connected
        self._session: PairSession | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(Theme.PILL_PADDING, 12, Theme.PILL_PADDING, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(make_label("Bluetooth", Theme.TITLE_PT, bold=True))
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

        self._backend.devices_ready.connect(self._on_devices)
        self._backend.action_finished.connect(self._on_action_finished)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        QTimer.singleShot(0, self._start)

    # -- startup
    def _show_message(self, text: str) -> None:
        self._message.setText(text)
        self._stack.setCurrentIndex(0)

    def _start(self) -> None:
        self._show_message("Looking for devices…")
        self._backend.check(self._on_checked)

    def _on_checked(self, state: str) -> None:
        if state == "ok":
            self._hint.setText("Scanning…")
            self._refresh()
            self._timer.start()
            return
        self._hint.setText("")
        self._show_message(
            {
                "missing": "bluetoothctl isn't installed (package: bluez-utils)",
                "none": "You haven't a Bluetooth adapter or driver on this PC",
                "off": "Bluetooth is turned off.\nTurn it on from the tile first.",
            }[state]
        )

    def _refresh(self) -> None:
        self._backend.scan()  # no-op while a scan is still running
        if not self._busy:
            self._backend.fetch()

    def shutdown(self) -> None:
        self._timer.stop()
        self._backend.stop_scan()
        if self._session is not None:
            self._session.cancel()

    # -- list
    def _on_devices(self, devices: list) -> None:
        self._hint.setText("")
        seen = set()
        for device in devices:
            seen.add(device.mac)
            row = self._rows.get(device.mac)
            if row is None:
                row = DeviceRow(device)
                row.selected.connect(self._on_selected)
                row.answered.connect(self._on_answered)
                self._rows[device.mac] = row
                self._list.insertWidget(self._list.count() - 1, row)
            else:
                row.update_device(device)
        if not self._busy:
            for mac in [m for m in self._rows if m not in seen]:
                row = self._rows.pop(mac)
                row.hide()
                row.deleteLater()
            for index, device in enumerate(d for d in devices if d.mac in self._rows):
                row = self._rows[device.mac]
                if self._list.indexOf(row) != index:
                    self._list.removeWidget(row)
                    self._list.insertWidget(index, row)
        if self._rows:
            self._stack.setCurrentIndex(1)
        else:
            self._show_message("No devices found yet…")

    # -- actions
    def _on_selected(self, mac: str) -> None:
        row = self._rows.get(mac)
        if row is None or self._busy:
            return
        device = row.device
        self._busy = mac
        row.set_status("")
        if device.connected:
            row.set_status("Disconnecting…")
            self._backend.disconnect_device(mac)
        elif device.paired:
            row.set_status("Connecting…")
            self._backend.connect_device(mac)
        else:
            self._session = PairSession(mac, self)
            self._session.status.connect(row.set_status)
            self._session.confirm_requested.connect(lambda code, r=row: self._ask(r, code))
            self._session.finished.connect(lambda ok, msg, m=mac: self._on_pair_finished(m, ok, msg))

    def _ask(self, row: DeviceRow, code: str) -> None:
        row.set_status("Waiting for your answer…")
        row.show_confirm(code)

    def _on_answered(self, mac: str, yes: bool) -> None:
        row = self._rows.get(mac)
        if row is not None:
            row.hide_confirm()
        if self._session is not None:
            self._session.answer(yes)

    def _on_pair_finished(self, mac: str, ok: bool, message: str) -> None:
        self._session = None
        row = self._rows.get(mac)
        self._busy = ""
        if row is not None:
            row.hide_confirm()
            row.set_status("" if ok else message)
        self._backend.fetch()

    def _on_action_finished(self, mac: str, ok: bool, message: str) -> None:
        self._busy = ""
        row = self._rows.get(mac)
        if row is not None:
            row.set_status("" if ok else message)
        self._backend.fetch()


class BluetoothWindow(QWidget):
    """Full-screen transparent surface holding the popup; a click outside the popup closes it."""

    def __init__(self, *, layer_shell: bool, right: int, bottom: int) -> None:
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if not layer_shell:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setWindowTitle("Better Hyprland Bluetooth")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._layer = layer_shell
        self._right = right
        self._bottom = bottom
        self._closing = False
        self._t = 0.0

        self.panel = BluetoothPanel(self)
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
        self.panel.move(target.x() + int(16 * (1.0 - self._t)), target.y())

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
            self.panel.shutdown()
            self._animate_to(0.0)

    def _on_anim_finished(self) -> None:
        if self._closing:
            QApplication.quit()

    def mousePressEvent(self, event) -> None:
        if self._layer and not self.panel.geometry().contains(event.position().toPoint()):
            self.close_animated()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close_animated()
        else:
            super().keyPressEvent(event)


def run(args) -> int:
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

    window = BluetoothWindow(layer_shell=use_layer, right=args.right, bottom=args.align_bottom)
    if use_layer:
        window.winId()
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
    sys.exit(run(_parse_args(sys.argv[1:])))
