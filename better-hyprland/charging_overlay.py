#!/usr/bin/env python3
"""
Charging overlay  (python3 + PyQt6)

Shows a fullscreen overlay for 5 seconds when the charger is plugged in:
  - green lightning bolt (reveal curve, 3 s)
  - "Charging • NN%" text (slide curve, 3 s, 60% opacity)
  - a sound

Run it:
    python3 charging_overlay.py            # watch the battery in the background
    python3 charging_overlay.py --test     # show the overlay once, right now
    python3 charging_overlay.py --test --no-sound

Needs:  sudo pacman -S python-pyqt6 ttf-font-awesome mpv
(inside a VS Code virtualenv instead:  pip install PyQt6)
"""

import glob
import shutil
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QUrl, QTimer, QVariantAnimation
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QLinearGradient,
    QPainter,
    QRadialGradient,
)
from PyQt6.QtMultimedia import QSoundEffect
from PyQt6.QtWidgets import QApplication, QWidget

# =====================================================================
#  SETTINGS  (change things here)
# =====================================================================
STAY_TIME_MS = 4000          # total time the overlay stays on screen
FADE_IN_MS = 300           # background fade-in
FADE_OUT_MS = 800            # background fade-out at the end of STAY_TIME_MS

ANIM_TIME_MS = 1500          # icon + text animation time (3 seconds)
REVEAL_CURVE = (0.16, 1.0, 0.3, 1.0)     # curve("anm1")
SLIDE_CURVE = (0.22, 1.0, 0.36, 1.0)    # curve("slide")

BOLT_SCALEY_START = 0.02   # phase-1-start: pinched flat
BOLT_BURST_AT = 0.80       # phase-2-progress: when the burst peaks (0-1 of 3 s)
BOLT_BURST_PEAK = 1.00     # how tall it bursts (1.0 = no overshoot)
BOLT_SCALEY_END = 1.00     # phase-3-end: original shape

ICON_COLOR = "#83EC83"
ICON_GLYPH = "\uf0e7"        # fa-solid fa-bolt
ICON_SIZE_PX = 150
ICON_FONT_CANDIDATES = [
    "Font Awesome 7 Free",
    "Font Awesome 7 Pro",
    "Font Awesome 6 Free",
]

TEXT_FONT_FAMILY = "Google Sans Flex"
TEXT_FONT_SIZE_PT = 15
                             # fullscreen overlay, so change this number to taste
TEXT_OPACITY = 0.50          # font-opacity: 60%
SLIDE_DISTANCE_PX = 50    # how far the text slides up into place

# Background: No Color, Frosted Glass Blur
BG_COLORS = [(0, 0, 0), (0, 0, 0), (0, 0, 0)]
BG_ALPHA = 8             

# Sound: looked for next to this script first, then in ~/.config/better-hyprland
SOUND_CANDIDATES = [
    Path(__file__).resolve().with_name("sound.mp3"),
    Path.home() / ".config" / "better-hyprland" / "sound.mp3",
]

POLL_INTERVAL_MS = 100      # how often the battery is checked
SHOW_IF_ALREADY_CHARGING = False   # popup at startup if charger already plugged?
# =====================================================================


def bezier(x1, y1, x2, y2):
    """cubic-bezier(x1, y1, x2, y2) as a QEasingCurve."""
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1.0, 1.0))
    return curve


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def pick_font(candidates, fallback):
    families = set(QFontDatabase.families())
    for name in candidates:
        if name in families:
            return name
    return fallback


def read_battery():
    """Returns (status, percent) or (None, None) if there is no battery."""
    batteries = sorted(glob.glob("/sys/class/power_supply/BAT*"))
    if not batteries:
        return None, None
    base = Path(batteries[0])
    try:
        status = (base / "status").read_text().strip()
        percent = int((base / "capacity").read_text().strip())
        return status, percent
    except (OSError, ValueError):
        return None, None

_cached_sound = None

def play_sound():
    global _cached_sound
    if _cached_sound is None:
        sound = next((p for p in SOUND_CANDIDATES if p.exists()), None)
        if sound is None:
            print("[charging-overlay] no sound.mp3 found, skipping sound")
            return
        _cached_sound = QSoundEffect()
        _cached_sound.setSource(QUrl.fromLocalFile(str(sound)))
        _cached_sound.setVolume(0.8)
    
    _cached_sound.play()


class ChargingOverlay(QWidget):
    def __init__(self, with_sound=True):
        super().__init__()
        self.with_sound = with_sound
        self.message = "Charging"
        self._icon_p = 0.0   # icon animation progress (reveal curve)
        self._text_p = 0.0   # text animation progress (slide curve)
        self._fade = 0.0     # whole-overlay fade
        self._anims = []
        self.anm1 = bezier(*REVEAL_CURVE)

        self.setWindowTitle("charging-overlay")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        icon_family = pick_font(ICON_FONT_CANDIDATES, "Sans")
        self.icon_font = QFont(icon_family)
        self.icon_font.setPixelSize(ICON_SIZE_PX)
        self.icon_font.setWeight(QFont.Weight.Black)   # "solid" style

        text_family = pick_font([TEXT_FONT_FAMILY], "Sans")
        self.text_font = QFont(text_family)
        self.text_font.setPointSize(TEXT_FONT_SIZE_PT)
        self.text_font.setWeight(QFont.Weight.Medium)

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._start_fade_out)

        self.finished_callback = None

        # --- Pre-render optimization for Low End PCs ---
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.show()
        self.hide()
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, False)

    # ---------- animation helpers ----------
    def _animate(self, setter, start, end, duration, curve=None):
        anim = QVariantAnimation(self)
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.setDuration(int(duration))
        if curve is not None:
            anim.setEasingCurve(curve)
        anim.valueChanged.connect(lambda v: (setter(v), self.update()))
        anim.start()
        self._anims.append(anim)
        return anim

    def _stop_animations(self):
        for anim in self._anims:
            anim.stop()
        self._anims.clear()
        self.hide_timer.stop()

    def _set_icon(self, v):
        self._icon_p = v

    def _set_text(self, v):
        self._text_p = v

    def _set_fade(self, v):
        self._fade = v

    # ---------- public ----------
    def play(self, percent=None):
        self._stop_animations()
        self.message = f"Charging  \u2022  {percent}%" if percent is not None else "Charging"
        self._icon_p = self._text_p = self._fade = 0.0

        screen = QApplication.primaryScreen().geometry()
        self.resize(screen.width(), screen.height())
        self.show()
        self._animate(self._set_fade, 0.0, 1.0, FADE_IN_MS)
        self._animate(self._set_icon, 0.0, 1.0, ANIM_TIME_MS),
        self._animate(self._set_text, 0.0, 1.0, ANIM_TIME_MS, bezier(*SLIDE_CURVE))
        if self.with_sound:
            play_sound()
        self.hide_timer.start(max(0, STAY_TIME_MS - FADE_OUT_MS))

    def _start_fade_out(self):
        anim = self._animate(self._set_fade, self._fade, 0.0, FADE_OUT_MS)
        anim.finished.connect(self._done)

    def _done(self):
        self.hide()
        if self.finished_callback:
            self.finished_callback()

    # ---------- drawing ----------
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        # background (dark blue -> dark purple)
        grad = QLinearGradient(0, 0, w, h)
        alpha = int(BG_ALPHA * clamp(self._fade))
        for i, (r, g, b) in enumerate(BG_COLORS):
            grad.setColorAt(i / (len(BG_COLORS) - 1), QColor(r, g, b, alpha))
        painter.fillRect(self.rect(), grad)

        icon_y = cy - 40

        # soft glow behind the icon
        glow_alpha = int(70 * clamp(self._fade) * clamp(self._icon_p))
        if glow_alpha > 0:
            glow_color = QColor(ICON_COLOR)
            glow = QRadialGradient(QPointF(cx, icon_y), ICON_SIZE_PX * 1.6)
            glow_color.setAlpha(glow_alpha)
            glow.setColorAt(0.0, glow_color)
            glow_color.setAlpha(0)
            glow.setColorAt(1.0, glow_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(QPointF(cx, icon_y), ICON_SIZE_PX * 1.6, ICON_SIZE_PX * 1.6)

        # lightning bolt: reveals with opacity + scale
        painter.save()
        painter.setOpacity(clamp(self._fade))
        t = clamp(self._icon_p)    # linear 0..1 over the 3 seconds
        if t < BOLT_BURST_AT:      # phase 1 to 2: burst open
           k = self.anm1.valueForProgress(t / BOLT_BURST_AT)
           scale_y = BOLT_SCALEY_START + (BOLT_BURST_PEAK - BOLT_SCALEY_START) * k
        else:                      # phase 2 to 3: settle
           k = self.anm1.valueForProgress((t - BOLT_BURST_AT) / (1.0 - BOLT_BURST_AT))
           scale_y = BOLT_BURST_PEAK + (BOLT_SCALEY_END - BOLT_BURST_PEAK) * k
        painter.translate(cx, icon_y)
        painter.scale(1.0, max(scale_y, 0.01))
        painter.setFont(self.icon_font)
        painter.setPen(QColor(ICON_COLOR))
        half = ICON_SIZE_PX
        painter.drawText(
            QRectF(-half, -half, half * 2, half * 2),
            Qt.AlignmentFlag.AlignCenter,
            ICON_GLYPH,
        )
        painter.restore()

        # text: slides up into place, 60% opacity
        painter.save()
        painter.setOpacity(clamp(self._fade) * TEXT_OPACITY * clamp(self._text_p))
        painter.setFont(self.text_font)
        painter.setPen(QColor("#ffffff"))
        offset = (1.0 - self._text_p) * SLIDE_DISTANCE_PX
        painter.drawText(
            QRectF(0, icon_y + ICON_SIZE_PX * 0.7 + offset, w, 100),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            self.message,
        )
        painter.restore()


class BatteryWatcher:
    """Calls overlay.play() the moment the battery status becomes 'Charging'."""

    def __init__(self, overlay):
        self.overlay = overlay
        status, _ = read_battery()
        if status is None:
            print("[charging-overlay] no battery found in /sys/class/power_supply")
        self.last_status = None if SHOW_IF_ALREADY_CHARGING else status
        self.timer = QTimer()
        self.timer.timeout.connect(self.check)
        self.timer.start(POLL_INTERVAL_MS)
        if SHOW_IF_ALREADY_CHARGING:
            self.check()

    def check(self):
        status, percent = read_battery()
        if status is None:
            return
        if status == "Charging" and self.last_status != "Charging":
            self.overlay.play(percent)
        self.last_status = status


def main():
    args = set(sys.argv[1:])
    app = QApplication(sys.argv)
    app.setApplicationName("charging-overlay")
    app.setDesktopFileName("charging-overlay")   # Wayland app_id / window class
    app.setQuitOnLastWindowClosed(False)

    overlay = ChargingOverlay(with_sound="--no-sound" not in args)

    if "--test" in args:
        _status, percent = read_battery()
        overlay.finished_callback = app.quit
        QTimer.singleShot(300, lambda: overlay.play(percent if percent is not None else 80))
    else:
        watcher = BatteryWatcher(overlay)   # noqa: F841 (keep a reference)
        print("[charging-overlay] running. Plug in the charger to see it.")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()