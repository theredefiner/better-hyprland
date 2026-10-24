"""Sliders pill (second pill): brightness + volume, with a per-app volume list.

Backends (all run without blocking the UI):
    brightness  read from /sys/class/backlight, written with `brightnessctl`
    volume      `pactl` (PipeWire-pulse or PulseAudio); `pactl subscribe` pushes live changes,
                so the slider follows the volume keys with no polling

The per-app list is a popover that opens under this pill (over the pills below it).
main.py loads this file and calls `create_pill(services)`.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPointF,
    QProcess,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from common import HoverTracker, MaterialIcon, Pill, Theme, c_locale_env, make_label, mix, run_async

USER_QUIET_SECONDS = 0.35  # ignore external updates this long after the user touched a slider


# ------------------------------------------------------------------------ pure helpers


def parse_percent(text: str) -> int | None:
    match = re.search(r"(\d+)%", text)
    return int(match.group(1)) if match else None


def parse_streams(text: str) -> list[dict]:
    """`pactl --format=json list sink-inputs` -> the apps that are actually playing."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    streams = []
    for item in data if isinstance(data, list) else []:
        if item.get("corked"):  # paused streams are not "playing"
            continue
        props = item.get("properties") or {}
        percent = 0
        for channel in (item.get("volume") or {}).values():
            found = parse_percent(str(channel.get("value_percent", "")))
            if found is not None:
                percent = found
                break
        streams.append(
            {
                "index": int(item["index"]),
                "name": props.get("application.name")
                or props.get("application.process.binary")
                or props.get("media.name")
                or "Unknown",
                "icon": props.get("application.icon_name") or props.get("application.process.binary") or "",
                "volume": min(100, percent),
                "muted": bool(item.get("mute", False)),
            }
        )
    return streams


def volume_icon(percent: int, muted: bool) -> tuple[str, str]:
    """(Material Symbols name, plain-glyph fallback)."""
    if muted or percent <= 0:
        return "volume_off", "🔇"
    if percent < 34:
        return "volume_mute", "🔈"
    if percent < 67:
        return "volume_down", "🔉"
    return "volume_up", "🔊"


def _pen(color: QColor, width: float) -> QPen:
    pen = QPen()
    pen.setColor(color)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


class Throttle(QObject):
    """Sends the first value at once, then at most one value per `interval_ms` (the latest wins)."""

    def __init__(self, interval_ms: int, send: Callable[[int], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._send = send
        self._pending: int | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._flush)

    def push(self, value: int) -> None:
        if self._timer.isActive():
            self._pending = value
        else:
            self._send(value)
            self._timer.start()

    def _flush(self) -> None:
        if self._pending is not None:
            value, self._pending = self._pending, None
            self._send(value)
            self._timer.start()


# ------------------------------------------------------------------------ the slider


class GradientSlider(QWidget):
    """Pill-shaped slider: translucent track, gradient fill, no handle (as in the mockup)."""

    value_changed = pyqtSignal(int)  # emitted for user input only (mouse / wheel)

    def __init__(self, minimum: int = 0, maximum: int = 100, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._min = minimum
        self._max = maximum
        self._value = minimum
        self._shown = float(minimum)  # what is painted; eases toward _value on external changes
        self._dragging = False
        self.setFixedHeight(14)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(Theme.ANIM_FAST)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    @property
    def dragging(self) -> bool:
        return self._dragging

    def value(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        """Programmatic change (no signal). Eases when visible."""
        value = max(self._min, min(self._max, int(value)))
        if value == self._value:
            return
        self._value = value
        self._anim.stop()
        if self.isVisible() and not self._dragging:
            self._anim.setStartValue(self._shown)
            self._anim.setEndValue(float(value))
            self._anim.start()
        else:
            self._shown = float(value)
            self.update()

    def _on_anim(self, value) -> None:
        self._shown = float(value)
        self.update()

    def _user_value(self, x: float) -> None:
        fraction = max(0.0, min(1.0, x / max(1, self.width())))
        value = round(self._min + fraction * (self._max - self._min))
        self._anim.stop()
        self._shown = float(value)  # follow the pointer 1:1
        self.update()
        if value != self._value:
            self._value = value
            self.value_changed.emit(value)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._user_value(event.position().x())

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._user_value(event.position().x())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def wheelEvent(self, event) -> None:
        step = 5 if event.angleDelta().y() > 0 else -5
        target = max(self._min, min(self._max, self._value + step))
        if target != self._value:
            self._anim.stop()
            self._shown = float(target)
            self._value = target
            self.update()
            self.value_changed.emit(target)
        event.accept()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.4)
        width, height = float(self.width()), float(self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Theme.SLIDER_TRACK)
        painter.drawRoundedRect(QRectF(0, 0, width, height), height / 2, height / 2)

        span = max(1, self._max - self._min)
        fraction = max(0.0, min(1.0, (self._shown - self._min) / span))
        if fraction > 0 or self._min > 0:  # a slider whose minimum is 1 never looks empty
            fill = max(height, width * fraction)
            gradient = QLinearGradient(0, height, fill, 0)  # bottom-left -> top-right
            gradient.setColorAt(0.0, Theme.GRADIENT_START)
            gradient.setColorAt(1.0, Theme.GRADIENT_END)
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(QRectF(0, 0, fill, height), height / 2, height / 2)


class ChevronButton(QAbstractButton):
    """The ⌄ that opens the per-app list; flips to ⌃ while open."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(26, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._turn = 0.0
        self._hover = HoverTracker(self)
        self._anim = QPropertyAnimation(self, b"turn", self)
        self._anim.setDuration(Theme.ANIM)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    @pyqtProperty(float)
    def turn(self) -> float:
        return self._turn

    @turn.setter
    def turn(self, value: float) -> None:
        self._turn = value
        self.update()

    def set_open(self, is_open: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._turn)
        self._anim.setEndValue(1.0 if is_open else 0.0)
        self._anim.start()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(_pen(mix(Theme.TEXT_DIM, Theme.TEXT, self._hover.value), 1.8))
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(180.0 * self._turn)
        painter.drawPolyline(QPolygonF([QPointF(-5, -2), QPointF(0, 3), QPointF(5, -2)]))


# ------------------------------------------------------------------------ backends


def _find_backlight() -> Path | None:
    base = Path("/sys/class/backlight")
    try:
        devices = sorted(p for p in base.iterdir() if (p / "max_brightness").exists())
    except OSError:
        return None
    return devices[0] if devices else None


class BrightnessController(QObject):
    """Reads sysfs (cheap, synchronous) and writes through `brightnessctl` (async)."""

    changed = pyqtSignal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._device = _find_backlight()
        self._max = 0
        if self._device is not None:
            try:
                self._max = int((self._device / "max_brightness").read_text())
            except (OSError, ValueError):
                self._device = None
        self.can_read = self._device is not None and self._max > 0
        self.available = self.can_read and shutil.which("brightnessctl") is not None
        self._last = -1
        self._throttle = Throttle(50, self._send, self)

    def read_percent(self) -> int | None:
        if not self.can_read:
            return None
        try:
            current = int((self._device / "brightness").read_text())
        except (OSError, ValueError):
            return None
        return max(1, min(100, round(current * 100 / self._max)))

    def poll(self) -> None:
        percent = self.read_percent()
        if percent is not None and percent != self._last:
            self._last = percent
            self.changed.emit(percent)

    def set_percent(self, percent: int) -> None:
        self._last = percent
        self._throttle.push(percent)

    def _send(self, percent: int) -> None:
        run_async(self, "brightnessctl", ["-q", "-d", self._device.name, "set", f"{max(1, percent)}%"])


_RELEVANT_EVENT = re.compile(r"on (sink|server)\b")  # also matches "sink-input"


class VolumeController(QObject):
    state_changed = pyqtSignal(int, bool)  # default output: percent, muted
    streams_changed = pyqtSignal(list)  # playing apps, see parse_streams()
    activity = pyqtSignal()  # something changed in the audio server (debounced)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.available = shutil.which("pactl") is not None
        self._sink_throttle = Throttle(40, self._send_sink_volume, self)
        self._stream_throttles: dict[int, Throttle] = {}
        self._watcher: QProcess | None = None
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(60)
        self._debounce.timeout.connect(self.activity)
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.setInterval(3000)
        self._retry.timeout.connect(self.start)

    # -- live updates
    def start(self) -> None:
        """Subscribe to audio-server events (no polling)."""
        if not self.available or self._watcher is not None:
            return
        proc = QProcess(self)
        proc.setProcessEnvironment(c_locale_env())
        proc.readyReadStandardOutput.connect(self._on_watch_output)
        proc.finished.connect(self._on_watch_finished)
        self._watcher = proc
        proc.start("pactl", ["subscribe"])

    def _on_watch_output(self) -> None:
        text = bytes(self._watcher.readAllStandardOutput()).decode(errors="replace")
        if _RELEVANT_EVENT.search(text):
            self._debounce.start()

    def _on_watch_finished(self, *_args) -> None:  # audio server restarted or went away
        if self._watcher is not None:
            self._watcher.deleteLater()
            self._watcher = None
        self._retry.start()

    # -- reads
    def refresh(self) -> None:
        if self.available:
            run_async(self, "pactl", ["get-sink-volume", "@DEFAULT_SINK@"], self._on_volume_text)

    def _on_volume_text(self, code: int, out: str) -> None:
        percent = parse_percent(out)
        if code != 0 or percent is None:
            return

        def got_mute(mute_code: int, mute_out: str) -> None:
            if mute_code == 0:
                self.state_changed.emit(min(100, percent), "yes" in mute_out.lower())

        run_async(self, "pactl", ["get-sink-mute", "@DEFAULT_SINK@"], got_mute)

    def refresh_streams(self) -> None:
        if self.available:
            run_async(
                self,
                "pactl",
                ["--format=json", "list", "sink-inputs"],
                lambda code, out: self.streams_changed.emit(parse_streams(out)) if code == 0 else None,
            )

    # -- writes
    def set_volume(self, percent: int) -> None:
        self._sink_throttle.push(percent)

    def _send_sink_volume(self, percent: int) -> None:
        run_async(self, "pactl", ["set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"])

    def toggle_mute(self) -> None:
        if self.available:
            run_async(self, "pactl", ["set-sink-mute", "@DEFAULT_SINK@", "toggle"])

    def set_stream_volume(self, index: int, percent: int) -> None:
        throttle = self._stream_throttles.get(index)
        if throttle is None:
            throttle = Throttle(
                40,
                lambda value, i=index: run_async(self, "pactl", ["set-sink-input-volume", str(i), f"{value}%"]),
                self,
            )
            self._stream_throttles[index] = throttle
        throttle.push(percent)


# ------------------------------------------------------------------------ per-app popover


class AppIcon(QWidget):
    """App icon from the icon theme, or a coloured initial when the theme has none."""

    def __init__(self, name: str, icon: str, size: int = 24, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._pixmap = None
        if icon:
            themed = QIcon.fromTheme(icon)
            if not themed.isNull():
                self._pixmap = themed.pixmap(size, size)
        self._letter = (name or "?")[:1].upper()
        self._fallback = QColor.fromHsl(sum(map(ord, name or "?")) % 360, 110, 120)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._pixmap is not None and not self._pixmap.isNull():
            painter.drawPixmap(0, 0, self._pixmap)
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._fallback)
        painter.drawEllipse(QRectF(self.rect()))
        painter.setPen(QColor(255, 255, 255))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(int(self.height() * 0.5))
        painter.setFont(font)
        painter.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, self._letter)


class StreamRow(QWidget):
    HEIGHT = 28

    volume_changed = pyqtSignal(int, int)  # stream index, percent

    def __init__(self, stream: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = stream["index"]
        self._quiet_until = 0.0
        self.setFixedHeight(self.HEIGHT)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(AppIcon(stream["name"], stream["icon"]), 0, Qt.AlignmentFlag.AlignVCenter)
        self._slider = GradientSlider(0, 100)
        self._slider.set_value(stream["volume"])
        self._slider.value_changed.connect(self._on_user)
        row.addWidget(self._slider, 1, Qt.AlignmentFlag.AlignVCenter)

    def _on_user(self, percent: int) -> None:
        self._quiet_until = time.monotonic() + USER_QUIET_SECONDS
        self.volume_changed.emit(self.index, percent)

    def update_stream(self, stream: dict) -> None:
        if not self._slider.dragging and time.monotonic() >= self._quiet_until:
            self._slider.set_value(stream["volume"])


_SCROLL_QSS = """
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 4px; margin: 0; }
QScrollBar::handle:vertical { background: rgba(255, 255, 255, 90); border-radius: 2px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""


class AppVolumePopover(Pill):
    """Frosted list of the apps playing audio, floating under the sliders pill."""

    GAP = 6
    PAD_V = 10
    MAX_ROWS = 4
    EMPTY_HEIGHT = 56

    stream_volume_changed = pyqtSignal(int, int)  # stream index, percent

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._rows: dict[int, StreamRow] = {}
        self._open = False
        self._x = 0
        self._y = 0

        root = QVBoxLayout(self)
        root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)  # lets the height animate to 0
        root.setContentsMargins(Theme.PILL_PADDING, self.PAD_V, Theme.PILL_PADDING, self.PAD_V)
        root.setSpacing(0)
        self._empty = make_label(
            "No apps playing audio", Theme.BODY_PT, color=Theme.TEXT_DIM, align=Qt.AlignmentFlag.AlignCenter
        )
        root.addWidget(self._empty)

        self._scroll = QScrollArea()
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.setStyleSheet(_SCROLL_QSS)
        host = QWidget()
        self._list = QVBoxLayout(host)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(self.GAP)
        self._list.addStretch(1)
        self._scroll.setWidget(host)
        root.addWidget(self._scroll)

        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.finished.connect(self._on_anim_finished)
        self._sync_content()
        self.hide()

    @property
    def is_open(self) -> bool:
        return self._open

    def set_streams(self, streams: list[dict]) -> None:
        seen = set()
        for stream in streams:
            seen.add(stream["index"])
            row = self._rows.get(stream["index"])
            if row is None:
                row = StreamRow(stream)
                row.volume_changed.connect(self.stream_volume_changed)
                self._rows[stream["index"]] = row
                self._list.insertWidget(self._list.count() - 1, row)  # above the trailing stretch
            else:
                row.update_stream(stream)
        for index in [i for i in self._rows if i not in seen]:
            row = self._rows.pop(index)
            row.hide()
            row.deleteLater()
        self._sync_content()
        if self._open:  # grow/shrink to fit the new list
            self._anim.stop()
            self.setGeometry(self._x, self._y, Theme.COLUMN_WIDTH, self._content_height())

    def open_at(self, x: int, y: int) -> None:
        self._x, self._y = x, y
        self._open = True
        self._anim.stop()
        self._anim.setDuration(Theme.ANIM)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(QRect(x, y, Theme.COLUMN_WIDTH, 0))
        self._anim.setEndValue(QRect(x, y, Theme.COLUMN_WIDTH, self._content_height()))
        self.setGeometry(QRect(x, y, Theme.COLUMN_WIDTH, 0))
        self.show()
        self.raise_()
        self._anim.start()

    def close_animated(self) -> None:
        if not self._open:
            return
        self._open = False
        self._anim.stop()
        self._anim.setDuration(Theme.ANIM_FAST)
        self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(QRect(self._x, self._y, Theme.COLUMN_WIDTH, 0))
        self._anim.start()

    def hide_now(self) -> None:
        self._open = False
        self._anim.stop()
        self.hide()

    def _on_anim_finished(self) -> None:
        if not self._open:
            self.hide()

    def _sync_content(self) -> None:
        has_rows = bool(self._rows)
        self._empty.setVisible(not has_rows)
        self._scroll.setVisible(has_rows)

    def _content_height(self) -> int:
        count = len(self._rows)
        if count == 0:
            return self.EMPTY_HEIGHT
        rows = min(count, self.MAX_ROWS)
        return rows * StreamRow.HEIGHT + (rows - 1) * self.GAP + 2 * self.PAD_V


# ------------------------------------------------------------------------ the pill


class SlidersPill(Pill):
    HEIGHT = 106

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self._brightness = BrightnessController(self)
        self._volume = VolumeController(self)
        self._popover: AppVolumePopover | None = None
        self._last_streams: list[dict] = []
        self._brightness_quiet_until = 0.0
        self._volume_quiet_until = 0.0
        self._muted = False
        self._percent = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(Theme.PILL_PADDING, 19, Theme.PILL_PADDING, 19)
        root.setSpacing(12)
        center = Qt.AlignmentFlag.AlignVCenter

        # Brightness row: icon + slider
        brightness_row = QHBoxLayout()
        brightness_row.setContentsMargins(0, 0, 0, 0)
        brightness_row.setSpacing(10)
        self._brightness_icon = MaterialIcon("brightness_medium", "☀", 20, color=Theme.TEXT_DIM)
        self._brightness_slider = GradientSlider(1, 100)
        brightness_row.addWidget(self._brightness_icon, 0, center)
        brightness_row.addWidget(self._brightness_slider, 1, center)
        root.addLayout(brightness_row)

        # Volume row: icon (click = mute) + slider + chevron (per-app list)
        volume_row = QHBoxLayout()
        volume_row.setContentsMargins(0, 0, 0, 0)
        volume_row.setSpacing(10)
        self._volume_icon = MaterialIcon("volume_up", "🔊", 20, color=Theme.TEXT_DIM, clickable=True)
        self._volume_slider = GradientSlider(0, 100)
        self._chevron = ChevronButton()
        volume_row.addWidget(self._volume_icon, 0, center)
        volume_row.addWidget(self._volume_slider, 1, center)
        volume_row.addWidget(self._chevron, 0, center)
        root.addLayout(volume_row)

        # Rows whose backend is missing stay visible but disabled
        self._brightness_slider.setEnabled(self._brightness.available)
        self._brightness_icon.setEnabled(self._brightness.available)
        for widget in (self._volume_slider, self._volume_icon, self._chevron):
            widget.setEnabled(self._volume.available)

        self._brightness_slider.value_changed.connect(self._on_brightness_user)
        self._brightness.changed.connect(self._on_brightness_external)
        self._volume_slider.value_changed.connect(self._on_volume_user)
        self._volume_icon.clicked.connect(self._volume.toggle_mute)
        self._chevron.clicked.connect(self._toggle_popover)
        self._volume.state_changed.connect(self._on_volume_state)
        self._volume.streams_changed.connect(self._on_streams)
        self._volume.activity.connect(self._on_audio_activity)

        # Brightness has no change notifications, so poll it (1 s) while the panel is visible.
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._brightness.poll)

        self._volume.start()

    # -- brightness
    def _on_brightness_user(self, percent: int) -> None:
        self._brightness_quiet_until = time.monotonic() + USER_QUIET_SECONDS
        self._brightness.set_percent(percent)

    def _on_brightness_external(self, percent: int) -> None:
        if not self._brightness_slider.dragging and time.monotonic() >= self._brightness_quiet_until:
            self._brightness_slider.set_value(percent)

    # -- volume
    def _on_volume_user(self, percent: int) -> None:
        self._volume_quiet_until = time.monotonic() + USER_QUIET_SECONDS
        self._percent = percent
        self._volume.set_volume(percent)
        self._update_volume_icon()

    def _on_volume_state(self, percent: int, muted: bool) -> None:
        self._muted = muted
        if not self._volume_slider.dragging and time.monotonic() >= self._volume_quiet_until:
            self._percent = percent
            self._volume_slider.set_value(percent)
        self._update_volume_icon()

    def _update_volume_icon(self) -> None:
        self._volume_icon.set_icon(*volume_icon(self._percent, self._muted))

    def _on_audio_activity(self) -> None:
        if self.isVisible():
            self._volume.refresh()
            if self._popover is not None and self._popover.is_open:
                self._volume.refresh_streams()

    # -- per-app popover
    def _toggle_popover(self) -> None:
        if self._popover is None:
            column = self.parentWidget()  # the panel column; the popover slides with it
            if column is None:
                return
            self._popover = AppVolumePopover(column)
            self._popover.stream_volume_changed.connect(self._volume.set_stream_volume)
            self._popover.set_streams(self._last_streams)
        if self._popover.is_open:
            self._popover.close_animated()
            self._chevron.set_open(False)
        else:
            self._volume.refresh_streams()
            self._popover.open_at(self.x(), self.y() + self.height() + Theme.PILL_SPACING)
            self._chevron.set_open(True)

    def _on_streams(self, streams: list) -> None:
        self._last_streams = streams
        if self._popover is not None:
            self._popover.set_streams(streams)

    # -- visibility
    def showEvent(self, event) -> None:
        self._brightness.poll()
        self._volume.refresh()
        self._poll.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._poll.stop()
        if self._popover is not None:
            self._popover.hide_now()
            self._chevron.set_open(False)
        super().hideEvent(event)


def create_pill(services: dict) -> QWidget:
    """Entry point used by main.py."""
    return SlidersPill()
