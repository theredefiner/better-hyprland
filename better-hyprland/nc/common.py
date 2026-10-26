"""Shared UI building blocks for the Better Hyprland notification center.

Every pill (notifications, sliders, media, quick-settings) imports from here so the
look and the motion stay identical across files.

Target: 1366x768 @ 60 Hz, 100 % scale. One frame is ~16.7 ms, so all animations
below run 140-240 ms with an ease-out curve, and each widget only repaints itself.
"""
from __future__ import annotations

import functools
from collections.abc import Callable

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QProcess,
    QProcessEnvironment,
    QRectF,
    QSize,
    Qt,
    QPropertyAnimation,
    QVariantAnimation,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette, QPen
from PyQt6.QtWidgets import QAbstractButton, QLabel, QSizePolicy, QWidget


class Theme:
    """Single source of truth for sizes, colours and timings (px @ 1366x768)."""

    # Geometry
    COLUMN_WIDTH = 344
    PANEL_MARGIN_TOP = 12
    PANEL_MARGIN_RIGHT = 12
    PILL_SPACING = 8
    PILL_RADIUS = 18
    PILL_PADDING = 14

    # Colours. The pill is chocolate magenta @ 0.4 alpha; the frosted blur is done by Hyprland.
    PILL_FILL = QColor(105, 54, 82, 65)
    PILL_BORDER = QColor(140, 75, 110, 70)
    TEXT = QColor(255, 255, 255, 240)
    TEXT_DIM = QColor(255, 255, 255, 185)
    TEXT_FAINT = QColor(255, 255, 255, 140)
    ACCENT = QColor("#693652")  # DND "on" colour, chocolate magenta
    TOGGLE_OFF = QColor(255, 255, 255, 70)
    GRADIENT_START = QColor("#3D1C2F")  # sliders + "on" toggles, 45 degrees (from the pseudocode)
    GRADIENT_END = QColor("#693652")
    SLIDER_TRACK = QColor(255, 255, 255, 56)

    # The panel surface is at least this tall so popovers (per-app volume) have room to open
    # even while the lower pills are not written yet.
    PANEL_MIN_HEIGHT = 452

    # Font sizes (pt; Qt maps 1 pt = 1.33 px at 96 dpi)
    TITLE_PT = 10.0
    BODY_PT = 9.0
    SMALL_PT = 8.0
    EMPTY_PT = 11.0

    # Motion (ms)
    ANIM_FAST = 140
    ANIM = 200
    ANIM_SLIDE_IN = 240
    ANIM_SLIDE_OUT = 180


FONT_FAMILIES = ["Google Sans Flex 9pt", "Google Sans", "Inter", "Noto Sans"]


def make_font(point_size: float, bold: bool = False) -> QFont:
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSizeF(point_size)
    font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def make_label(
    text: str,
    point_size: float,
    *,
    bold: bool = False,
    color: QColor | None = None,
    align: Qt.AlignmentFlag | None = None,
) -> QLabel:
    label = QLabel(text)
    label.setFont(make_font(point_size, bold))
    palette = label.palette()
    palette.setColor(QPalette.ColorRole.WindowText, color or Theme.TEXT)
    label.setPalette(palette)
    if align is not None:
        label.setAlignment(align)
    return label


def mix(a: QColor, b: QColor, t: float) -> QColor:
    """Linear blend of two colours (alpha included), t in 0..1."""
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def _pen(color: QColor, width: float = 1.0) -> QPen:
    pen = QPen()
    pen.setColor(color)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


class HoverTracker(QObject):
    """Animates a 0..1 `value` while the pointer is over `widget`, repainting it per frame."""

    def __init__(self, widget: QWidget, duration: int = Theme.ANIM_FAST) -> None:
        super().__init__(widget)
        self.value = 0.0
        self._widget = widget
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(duration)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_value)
        widget.installEventFilter(self)

    def _on_value(self, value) -> None:
        self.value = float(value)
        self._widget.update()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._widget:
            kind = event.type()
            if kind == QEvent.Type.Enter:
                self._go(1.0)
            elif kind == QEvent.Type.Leave:
                self._go(0.0)
        return False

    def _go(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self.value)
        self._anim.setEndValue(target)
        self._anim.start()


class Pill(QWidget):
    """Frosted-glass pill background (white @ 0.2). Subclass it and add a layout."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(Theme.COLUMN_WIDTH)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(_pen(Theme.PILL_BORDER, 1.0))
        painter.setBrush(Theme.PILL_FILL)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(rect, Theme.PILL_RADIUS, Theme.PILL_RADIUS)


class ToggleSwitch(QAbstractButton):
    """Small animated on/off switch (used for Do Not Disturb)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(38, 22)
        self._progress = 0.0
        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(Theme.ANIM_FAST)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._on_toggled)

    @pyqtProperty(float)
    def progress(self) -> float:
        return self._progress

    @progress.setter
    def progress(self, value: float) -> None:
        self._progress = value
        self.update()

    def _on_toggled(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def sizeHint(self) -> QSize:
        return QSize(38, 22)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(mix(Theme.TOGGLE_OFF, Theme.ACCENT, self._progress))
        painter.drawRoundedRect(QRectF(0, 0, width, height), height / 2, height / 2)
        knob = height - 6
        x = 3 + (width - knob - 6) * self._progress
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(QRectF(x, 3, knob, knob))


class CloseButton(QAbstractButton):
    """Round ✕ button drawn with vector lines (no icon-font dependency)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = HoverTracker(self)

    def sizeHint(self) -> QSize:
        return QSize(22, 22)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = self._hover.value
        if hover > 0.01:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, int(50 * hover)))
            painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
        painter.setPen(_pen(mix(Theme.TEXT_DIM, Theme.TEXT, hover), 1.6))
        center = QRectF(self.rect()).center()
        r = 4.0
        painter.drawLine(QPointF(center.x() - r, center.y() - r), QPointF(center.x() + r, center.y() + r))
        painter.drawLine(QPointF(center.x() - r, center.y() + r), QPointF(center.x() + r, center.y() - r))


class TextButton(QAbstractButton):
    """Rounded-rectangle text button (e.g. "Clear All")."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setFont(make_font(Theme.SMALL_PT))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = HoverTracker(self)
        self.setFixedSize(self.fontMetrics().horizontalAdvance(text) + 22, 22)

    def sizeHint(self) -> QSize:
        return self.size()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        alpha = 38 + 34 * self._hover.value + (30 if self.isDown() else 0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, int(alpha)))
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(Theme.TEXT)
        painter.setFont(self.font())
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())


class ElidedLabel(QWidget):
    """Single-line label that elides with "…" instead of widening its layout."""

    def __init__(
        self,
        text: str = "",
        point_size: float = Theme.BODY_PT,
        *,
        bold: bool = False,
        color: QColor | None = None,
        center: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._color = color or Theme.TEXT
        self._center = center
        self.setFont(make_font(point_size, bold))
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.fontMetrics().height())

    def setText(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self.update()

    def text(self) -> str:
        return self._text

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.height())

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self._color)
        metrics = self.fontMetrics()
        text = metrics.elidedText(self._text, Qt.TextElideMode.ElideRight, self.width())
        x = (self.width() - metrics.horizontalAdvance(text)) / 2 if self._center else 0.0
        baseline = metrics.ascent() + (self.height() - metrics.height()) / 2
        painter.drawText(QPointF(x, baseline), text)


# ------------------------------------------------------------------ icons + commands

MATERIAL_FAMILY = "Material Symbols Outlined"


@functools.lru_cache(maxsize=1)
def has_material_symbols() -> bool:
    return MATERIAL_FAMILY in QFontDatabase.families()


def draw_icon(painter: QPainter, rect: QRectF, name: str, fallback: str, size: int, color: QColor) -> None:
    """Draw a Material Symbols ligature centred in `rect` (plain `fallback` glyph if the font is missing)."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setPen(color)
    if has_material_symbols():
        font = QFont(MATERIAL_FAMILY)
        font.setPixelSize(size)
        text = name
    else:
        font = QFont()
        font.setPixelSize(int(size * 0.85))
        text = fallback
    painter.setFont(font)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()


class MaterialIcon(QWidget):
    """Material Symbols icon by ligature name (e.g. "volume_up"); a plain glyph if the font is missing."""

    clicked = pyqtSignal()

    def __init__(
        self,
        name: str,
        fallback: str = "",
        size: int = 20,
        *,
        color: QColor | None = None,
        clickable: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._fallback = fallback
        self._size = size
        self._color = color or Theme.TEXT_DIM
        self._clickable = clickable
        self.setFixedSize(size + 4, size + 4)
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_icon(self, name: str, fallback: str = "") -> None:
        if name != self._name or fallback != self._fallback:
            self._name = name
            self._fallback = fallback
            self.update()

    def mousePressEvent(self, event) -> None:
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        color = self._color if self.isEnabled() else mix(self._color, QColor(0, 0, 0, 0), 0.6)
        draw_icon(painter, QRectF(self.rect()), self._name, self._fallback, self._size, color)


def c_locale_env() -> QProcessEnvironment:
    """System environment with LC_ALL=C so command output is the same on every locale."""
    env = QProcessEnvironment.systemEnvironment()
    env.insert("LC_ALL", "C")
    return env


def run_async(
    owner: QObject,
    program: str,
    args: list[str],
    callback: Callable[[int, str], None] | None = None,
) -> QProcess:
    """Run a command without blocking the UI.

    `callback(exit_code, stdout)` runs on the GUI thread; exit_code -1 = program could not start.
    """
    proc = QProcess(owner)
    proc.setProcessEnvironment(c_locale_env())

    def finished(code, _status) -> None:
        out = bytes(proc.readAllStandardOutput()).decode(errors="replace")
        proc.deleteLater()
        if callback is not None:
            callback(code, out)

    def errored(error) -> None:
        if error == QProcess.ProcessError.FailedToStart:  # `finished` is not emitted in this case
            proc.deleteLater()
            if callback is not None:
                callback(-1, "")

    proc.finished.connect(finished)
    proc.errorOccurred.connect(errored)
    proc.start(program, args)
    return proc
