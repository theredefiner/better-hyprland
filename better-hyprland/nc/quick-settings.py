"""Quick Settings pill (fourth pill): six toggle tiles in a 3x2 grid.

    Wi-Fi         nmcli radio wifi            (arrow / right-click opens wlan.py)
    Bluetooth     bluetoothctl power          (arrow / right-click opens bluetooth.py)
    Night Light   hyprsunset                  (runs while on)
    Dark Mode     gsettings color-scheme + GTK 3/4 settings.ini
    Airplane      all radios off: nmcli radio all + bluetooth power
    Power Plan    powerprofilesctl            (click cycles the available plans)

Off tiles are grey, on tiles use the purple gradient. Every tool that is missing on your system
just disables its own tile (hover it to see what to install). State is re-read every 2 s while
the panel is visible, so changes made elsewhere show up. Nothing runs while it is hidden.

main.py loads this file and calls `create_pill(services)`.
"""
from __future__ import annotations

import re
import shutil
import sys
import time
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QProcess,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QBrush, QColor, QCursor, QLinearGradient, QPainter, QPainterPath
from PyQt6.QtWidgets import QGridLayout, QSizePolicy, QToolTip, QVBoxLayout, QWidget

from common import ElidedLabel, HoverTracker, Pill, Theme, draw_icon, make_label, run_async

BASE_DIR = Path(__file__).resolve().parent

# --- settings you may want to change -------------------------------------------------------
NIGHT_LIGHT_KELVIN = 4000  # colour temperature while Night Light is on
DARK_GTK_THEME: str | None = None  # e.g. "Adwaita-dark"; None leaves the GTK theme name alone
LIGHT_GTK_THEME: str | None = None  # e.g. "Adwaita"
POPUP_SCRIPTS = {"wifi": "wlan.py", "bluetooth": "bluetooth.py"}  # opened from the tile arrows
POLL_MS = 2000
# --------------------------------------------------------------------------------------------

POWER_ORDER = ("power-saver", "balanced", "performance")
POWER_LABELS = {"power-saver": "Battery Saver", "balanced": "Balanced", "performance": "Performance"}
POWER_ICONS = {
    "power-saver": ("energy_savings_leaf", "🍃"),
    "balanced": ("speed", "⚖"),
    "performance": ("bolt", "⚡"),
}

MISSING_TOOL_HINT = {
    "wifi": "nmcli not found (install networkmanager)",
    "bluetooth": "bluetoothctl not found (install bluez-utils)",
    "nightlight": "hyprsunset not found (install hyprsunset)",
    "dark": "gsettings not found (install glib2 and dconf)",
    "airplane": "needs nmcli or bluetoothctl",
    "power": "powerprofilesctl not found (install power-profiles-daemon)",
}


# ------------------------------------------------------------------------ pure helpers


def parse_enabled(text: str) -> bool:
    """`nmcli radio wifi` -> "enabled" / "disabled"."""
    return text.strip().lower() == "enabled"


def parse_bluetooth_powered(text: str) -> bool:
    """`bluetoothctl show` -> contains "Powered: yes"."""
    return re.search(r"^\s*Powered:\s*yes\b", text, re.MULTILINE | re.IGNORECASE) is not None


def parse_color_scheme_dark(text: str) -> bool:
    """`gsettings get ... color-scheme` -> 'prefer-dark'."""
    return "dark" in text.lower()


def parse_power_profiles(text: str) -> list[str]:
    """Profile names from `powerprofilesctl list` ("* balanced:" marks the active one)."""
    return re.findall(r"^[* ] ([a-z][a-z-]*):\s*$", text, re.MULTILINE)


def next_profile(current: str, available: list[str]) -> str | None:
    order = [name for name in POWER_ORDER if name in available] or list(available)
    if not order:
        return None
    if current not in order:
        return order[0]
    return order[(order.index(current) + 1) % len(order)]


def set_ini_key(text: str, section: str, key: str, value: str) -> str:
    """Set key=value inside [section] of an ini text, leaving every other line untouched."""
    lines = text.splitlines()
    header = f"[{section}]"
    start = next((i for i, line in enumerate(lines) if line.strip() == header), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [header, f"{key}={value}"]
        return "\n".join(lines) + "\n"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].strip().startswith("["):
            end = i
            break
    for i in range(start + 1, end):
        if "=" in lines[i] and lines[i].split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            return "\n".join(lines) + "\n"
    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1  # keep blank separator lines below the section
    lines.insert(insert_at, f"{key}={value}")
    return "\n".join(lines) + "\n"


def write_gtk_dark_flag(dark: bool) -> None:
    """GTK 3 apps that ignore `color-scheme` honour gtk-application-prefer-dark-theme."""
    for folder in ("gtk-3.0", "gtk-4.0"):
        path = Path.home() / ".config" / folder / "settings.ini"
        try:
            current = path.read_text() if path.exists() else ""
            updated = set_ini_key(current, "Settings", "gtk-application-prefer-dark-theme", "1" if dark else "0")
            if updated != current:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(updated)
        except OSError:
            pass


# ------------------------------------------------------------------------ backend


class QuickSettingsController(QObject):
    state_changed = pyqtSignal(str, object)  # key, bool (power: the profile name)
    action_finished = pyqtSignal(str)  # key; lets the UI stop ignoring polls for that tile

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        have = shutil.which
        self.available = {
            "wifi": have("nmcli") is not None,
            "bluetooth": have("bluetoothctl") is not None,
            "nightlight": have("hyprsunset") is not None and have("pgrep") is not None,
            "dark": have("gsettings") is not None,
            "power": have("powerprofilesctl") is not None,
        }
        self.available["airplane"] = self.available["wifi"] or self.available["bluetooth"]
        self.profiles: list[str] = []
        self.profile = ""
        # None = not read yet; radios that are not available count as off.
        self._radio: dict[str, bool | None] = {
            "wifi": None if self.available["wifi"] else False,
            "bluetooth": None if self.available["bluetooth"] else False,
        }

    # -- reads
    def refresh(self) -> None:
        if self.available["wifi"]:
            run_async(self, "nmcli", ["radio", "wifi"], self._on_wifi)
        if self.available["bluetooth"]:
            run_async(self, "bluetoothctl", ["show"], self._on_bluetooth)
        if self.available["nightlight"]:
            run_async(self, "pgrep", ["-x", "hyprsunset"], lambda code, _o: self.state_changed.emit("nightlight", code == 0))
        if self.available["dark"]:
            run_async(
                self,
                "gsettings",
                ["get", "org.gnome.desktop.interface", "color-scheme"],
                lambda code, out: self.state_changed.emit("dark", parse_color_scheme_dark(out)) if code == 0 else None,
            )
        if self.available["power"]:
            self._refresh_power()

    def _on_wifi(self, code: int, out: str) -> None:
        self._set_radio("wifi", code == 0 and parse_enabled(out))

    def _on_bluetooth(self, code: int, out: str) -> None:
        self._set_radio("bluetooth", code == 0 and parse_bluetooth_powered(out))

    def _set_radio(self, key: str, on: bool) -> None:
        self._radio[key] = on
        self.state_changed.emit(key, on)
        if all(value is not None for value in self._radio.values()):
            self.state_changed.emit("airplane", not self._radio["wifi"] and not self._radio["bluetooth"])

    def _refresh_power(self) -> None:
        def got_profile(code: int, out: str) -> None:
            if code == 0 and out.strip():
                self.profile = out.strip()
                self.state_changed.emit("power", self.profile)

        def got_list(code: int, out: str) -> None:
            if code == 0:
                self.profiles = parse_power_profiles(out)
                run_async(self, "powerprofilesctl", ["get"], got_profile)

        if self.profiles:
            run_async(self, "powerprofilesctl", ["get"], got_profile)
        else:
            run_async(self, "powerprofilesctl", ["list"], got_list)

    # -- writes
    def apply(self, key: str, on: bool) -> None:
        {
            "wifi": self._apply_wifi,
            "bluetooth": self._apply_bluetooth,
            "nightlight": self._apply_nightlight,
            "dark": self._apply_dark,
            "airplane": self._apply_airplane,
        }[key](on)

    def _finish(self, key: str) -> None:
        self.action_finished.emit(key)
        self.refresh()

    def _apply_wifi(self, on: bool) -> None:
        run_async(self, "nmcli", ["radio", "wifi", "on" if on else "off"], lambda *_: self._finish("wifi"))

    def _apply_bluetooth(self, on: bool) -> None:
        self._bluetooth_power(on, lambda: self._finish("bluetooth"))

    def _bluetooth_power(self, on: bool, done) -> None:
        def after(code: int, _out: str) -> None:
            if on and code != 0:  # usually an rfkill soft-block: unblock, then retry once
                run_async(
                    self,
                    "rfkill",
                    ["unblock", "bluetooth"],
                    lambda *_: run_async(self, "bluetoothctl", ["power", "on"], lambda *_: done()),
                )
            else:
                done()

        run_async(self, "bluetoothctl", ["power", "on" if on else "off"], after)

    def _apply_nightlight(self, on: bool) -> None:
        if on:
            QProcess.startDetached("hyprsunset", ["-t", str(NIGHT_LIGHT_KELVIN)])
            self.action_finished.emit("nightlight")
            QTimer.singleShot(500, self.refresh)  # give the process a moment to start
        else:
            run_async(self, "pkill", ["-x", "hyprsunset"], lambda *_: self._finish("nightlight"))

    def _apply_dark(self, on: bool) -> None:
        write_gtk_dark_flag(on)
        scheme = "prefer-dark" if on else "default"
        theme = DARK_GTK_THEME if on else LIGHT_GTK_THEME
        if theme:
            run_async(self, "gsettings", ["set", "org.gnome.desktop.interface", "gtk-theme", theme])
        run_async(
            self,
            "gsettings",
            ["set", "org.gnome.desktop.interface", "color-scheme", scheme],
            lambda *_: self._finish("dark"),
        )

    def _apply_airplane(self, on: bool) -> None:
        radios_on = not on
        jobs = []
        if self.available["wifi"]:
            jobs.append(
                lambda done: run_async(self, "nmcli", ["radio", "all", "on" if radios_on else "off"], lambda *_: done())
            )
        if self.available["bluetooth"]:
            jobs.append(lambda done: self._bluetooth_power(radios_on, done))
        remaining = len(jobs)

        def done() -> None:
            nonlocal remaining
            remaining -= 1
            if remaining == 0:
                self.action_finished.emit("wifi")
                self.action_finished.emit("bluetooth")
                self._finish("airplane")

        for job in jobs:
            job(done)

    def cycle_power(self) -> str | None:
        """Switch to the next power plan; returns its name (None if nothing to switch to)."""
        target = next_profile(self.profile, self.profiles)
        if target is None:
            return None
        self.profile = target
        run_async(self, "powerprofilesctl", ["set", target], lambda *_: self._finish("power"))
        return target


# ------------------------------------------------------------------------ widgets


class TileButton(QWidget):
    """Pill-shaped toggle: grey when off, gradient when on. With `arrow`, the right part is a second button."""

    HEIGHT = 54
    ARROW_START = 0.58  # fraction of the width where the arrow zone begins

    activated = pyqtSignal()
    arrow_activated = pyqtSignal()

    def __init__(self, icon: str, fallback: str, *, arrow: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon = icon
        self._fallback = fallback
        self._arrow = arrow
        self._on = False
        self._progress = 0.0
        self._zone = "icon"
        self._pressed_zone: str | None = None
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = HoverTracker(self)
        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(Theme.ANIM)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    @pyqtProperty(float)
    def progress(self) -> float:
        return self._progress

    @progress.setter
    def progress(self, value: float) -> None:
        self._progress = value
        self.update()

    @property
    def is_on(self) -> bool:
        return self._on

    def set_on(self, on: bool, animate: bool = True) -> None:
        if on == self._on:
            return
        self._on = on
        self._anim.stop()
        if animate and self.isVisible():
            self._anim.setStartValue(self._progress)
            self._anim.setEndValue(1.0 if on else 0.0)
            self._anim.start()
        else:
            self._progress = 1.0 if on else 0.0
            self.update()

    def set_icon(self, icon: str, fallback: str) -> None:
        if (icon, fallback) != (self._icon, self._fallback):
            self._icon, self._fallback = icon, fallback
            self.update()

    def _zone_at(self, x: float) -> str:
        return "arrow" if self._arrow and x >= self.width() * self.ARROW_START else "icon"

    # -- input
    def mouseMoveEvent(self, event) -> None:
        zone = self._zone_at(event.position().x())
        if zone != self._zone:
            self._zone = zone
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed_zone = self._zone_at(event.position().x())
            self.update()
        elif event.button() == Qt.MouseButton.RightButton and self._arrow:
            self.arrow_activated.emit()  # right-click = open the popup, like the pseudocode

    def mouseReleaseEvent(self, event) -> None:
        pressed, self._pressed_zone = self._pressed_zone, None
        self.update()
        if event.button() != Qt.MouseButton.LeftButton or pressed is None or not self.rect().contains(event.position().toPoint()):
            return
        if pressed == self._zone_at(event.position().x()):
            (self.arrow_activated if pressed == "arrow" else self.activated).emit()

    # -- painting
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.4)
        width, height = float(self.width()), float(self.height())
        full = QRectF(0, 0, width, height)
        shape = QPainterPath()
        shape.addRoundedRect(full, height / 2, height / 2)
        painter.setClipPath(shape)

        painter.fillRect(full, Theme.TOGGLE_OFF)
        if self._progress > 0.0:
            painter.setOpacity(self._progress * (1.0 if self.isEnabled() else 0.4))
            gradient = QLinearGradient(0, height, width, 0)  # 45 degrees, bottom-left to top-right
            gradient.setColorAt(0.0, Theme.GRADIENT_START)
            gradient.setColorAt(1.0, Theme.GRADIENT_END)
            painter.fillRect(full, QBrush(gradient))
            painter.setOpacity(1.0 if self.isEnabled() else 0.4)

        split = width * self.ARROW_START if self._arrow else width
        icon_zone = QRectF(0, 0, split, height)
        arrow_zone = QRectF(split, 0, width - split, height)

        hover = self._hover.value if self.isEnabled() else 0.0
        zone_rect = arrow_zone if self._zone == "arrow" else icon_zone
        alpha = 40 * hover + (36 if self._pressed_zone == self._zone and self._pressed_zone is not None else 0)
        if alpha > 1:
            painter.fillRect(zone_rect, QColor(255, 255, 255, int(alpha)))

        draw_icon(painter, icon_zone, self._icon, self._fallback, 22, QColor(255, 255, 255, 240))
        if self._arrow:
            painter.setPen(QColor(255, 255, 255, 50))
            painter.drawLine(int(split), int(height * 0.28), int(split), int(height * 0.72))
            draw_icon(painter, arrow_zone, "arrow_forward", "→", 18, QColor(255, 255, 255, 215))


class QuickTile(QWidget):
    """TileButton with its label underneath."""

    activated = pyqtSignal()
    arrow_activated = pyqtSignal()

    def __init__(self, label: str, icon: str, fallback: str, *, arrow: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.button = TileButton(icon, fallback, arrow=arrow)
        self._label = ElidedLabel(label, Theme.BODY_PT, center=True)
        layout.addWidget(self.button)
        layout.addWidget(self._label)
        self.button.activated.connect(self.activated)
        self.button.arrow_activated.connect(self.arrow_activated)

    def set_label(self, text: str) -> None:
        self._label.setText(text)

    def set_available(self, available: bool, hint: str) -> None:
        self.button.setEnabled(available)
        self.setToolTip("" if available else hint)


# ------------------------------------------------------------------------ the pill

# key, label, Material icon, fallback glyph, has popup arrow
TILES = (
    ("wifi", "Wi-Fi", "wifi", "📶", True),
    ("bluetooth", "Bluetooth", "bluetooth", "ᛒ", True),
    ("nightlight", "Night Light", "light_mode", "☀", False),
    ("dark", "Dark Mode", "dark_mode", "🌙", False),
    ("airplane", "Airplane Mode", "flight", "✈", False),
    ("power", "Power Plan", "speed", "⚡", False),
)


class QuickSettingsPill(Pill):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctl = QuickSettingsController(self)
        self._quiet: dict[str, float] = {}  # key -> ignore polled state until this time
        self._tiles: dict[str, QuickTile] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(Theme.PILL_PADDING, 12, Theme.PILL_PADDING, 12)
        root.setSpacing(10)
        root.addWidget(make_label("Quick Settings", Theme.TITLE_PT, bold=True))

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(10)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        for position, (key, label, icon, fallback, arrow) in enumerate(TILES):
            tile = QuickTile(label, icon, fallback, arrow=arrow)
            tile.set_available(self._ctl.available[key], MISSING_TOOL_HINT[key])
            tile.activated.connect(lambda k=key: self._on_activated(k))
            tile.arrow_activated.connect(lambda k=key: self._open_popup(k))
            grid.addWidget(tile, position // 3, position % 3)
            self._tiles[key] = tile
        root.addLayout(grid)
        root.activate()
        self.setFixedHeight(root.sizeHint().height())

        self._ctl.state_changed.connect(self._on_state)
        self._ctl.action_finished.connect(lambda key: self._quiet.pop(key, None))

        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._ctl.refresh)
        QTimer.singleShot(0, self._ctl.refresh)  # right tile states before the first slide-in

    # -- state from the system
    def _on_state(self, key: str, value) -> None:
        if time.monotonic() < self._quiet.get(key, 0.0):
            return
        tile = self._tiles[key]
        if key == "power":
            profile = str(value)
            tile.button.set_icon(*POWER_ICONS.get(profile, ("speed", "⚡")))
            tile.set_label(POWER_LABELS.get(profile, profile))
            tile.button.set_on(True)
        else:
            tile.button.set_on(bool(value))

    # -- clicks
    def _on_activated(self, key: str) -> None:
        tile = self._tiles[key]
        if not self._ctl.available[key]:
            return
        if key == "power":
            target = self._ctl.cycle_power()
            if target is not None:
                tile.button.set_icon(*POWER_ICONS.get(target, ("speed", "⚡")))
                tile.set_label(POWER_LABELS.get(target, target))
                tile.button.set_on(True)
            return
        new_state = not tile.button.is_on
        held_until = time.monotonic() + 1.5  # show the new state at once; polls may lag behind
        self._quiet[key] = held_until
        tile.button.set_on(new_state)
        if key == "airplane":
            for radio in ("wifi", "bluetooth"):
                self._quiet[radio] = held_until
                self._tiles[radio].button.set_on(not new_state)
        self._ctl.apply(key, new_state)

    def _open_popup(self, key: str) -> None:
        script = BASE_DIR / POPUP_SCRIPTS[key]
        if script.is_file():
            bottom = self.mapTo(self.window(), QPoint(0, self.height())).y()
            QProcess.startDetached(sys.executable, [str(script), "--align-bottom", str(bottom)])
        else:
            QToolTip.showText(QCursor.pos(), f"{script.name} is not installed yet", self)

    # -- visibility
    def showEvent(self, event) -> None:
        self._ctl.refresh()
        self._poll.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._poll.stop()
        super().hideEvent(event)


def create_pill(services: dict) -> QWidget:
    """Entry point used by main.py."""
    return QuickSettingsPill()
