"""
editor_apps_pinned.py - "Pinned apps" editor screen

Opened from the pencil icon in start_main_menu.py (slide-fade from the start UI).
Lists every installed app A-Z with an animated circle-tick; tapping a row pins /
unpins it. Changes are saved straight to ~/.config/better-hyprland/sm/pinned.json
and the start menu re-reads them when you press Back.
"""
from PyQt6.QtCore import QAbstractAnimation, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from start_main_menu import (
    icon_pixmap,
    BASE, FILL_HALF, HOVER, MAX_PINNED, WHITE, WHITE_DIM,
    IconButton, Pressable, all_apps, app_by_id, clear_layout, draw_text,
    load_icon, load_pinned, mkfont, save_pinned,
)

BACK_FILL = QColor(*BASE, 51)             # back button: #693652 @ 0.2 (same as apps_all_menu)
ICON_BG = QColor(*BASE, 77)               # app icon circles: #693652 @ 0.3 (same as apps_all_menu)
TICK_COLOR = QColor(105, 54, 82)          # #693652


class TitlePill(QWidget):
    """The pill at the top: pencil icon + "Pinned apps" (shows a short hint when needed)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(240, 40)
        self.override = None

    def flash(self, text):
        self.override = text
        self.update()
        QTimer.singleShot(1800, self._clear)

    def _clear(self):
        self.override = None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(FILL_HALF)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if self.override:
            draw_text(p, r, self.override, 14, bold=True)
            return
        draw_text(p, QRectF(r.left() + 40, r.top(), 28, r.height()), "edit", 22, icon=True)
        draw_text(p, QRectF(r.left() + 76, r.top(), r.width() - 90, r.height()), "Pinned apps", 15,
                  bold=True, align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)


class Panel(QWidget):
    """The rounded list panel (#693652 @ 0.5, same as the All Apps screen)."""

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 24, 24)
        p.fillPath(path, FILL_HALF)


class AppRow(Pressable):
    """App icon + name + animated circle-tick (filled = pinned, outline = not pinned)."""
    PRESS_SCALE = 0.97

    def __init__(self, app, pinned, parent=None):
        super().__init__(parent)
        self.app = app
        self.pinned = pinned
        self.icon = load_icon(app["icon"])
        self._tick = 1.0 if pinned else 0.0
        self._tick_anim = QVariantAnimation(self)
        self._tick_anim.valueChanged.connect(self._set_tick)
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _set_tick(self, v):
        self._tick = float(v)
        self.update()

    def set_pinned(self, value):
        self.pinned = value
        self._tick_anim.stop()
        self._tick_anim.setStartValue(self._tick)
        self._tick_anim.setEndValue(1.0 if value else 0.0)
        self._tick_anim.setDuration(240)
        self._tick_anim.setEasingCurve(QEasingCurve.Type.OutBack if value else QEasingCurve.Type.OutCubic)
        self._tick_anim.start()

    def draw(self, p):
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(HOVER)
            p.drawRoundedRect(QRectF(self.rect()), 14, 14)
        circle = QRectF(6, 6, 40, 40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ICON_BG)
        p.drawEllipse(circle)
        if not self.icon.isNull():
            pm = icon_pixmap(self.icon, 28, self)
            p.drawPixmap(int(circle.center().x() - 14), int(circle.center().y() - 14), pm)
        else:
            draw_text(p, circle, (self.app["name"][:1] or "?").upper(), 18, bold=True)
        draw_text(p, QRectF(58, 0, self.width() - 110, self.height()), self.app["name"], 14,
                  align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        # tick circle on the right
        c = QRectF(self.width() - 38, (self.height() - 26) / 2, 26, 26)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(TICK_COLOR, 2.2))
        p.drawEllipse(c.adjusted(1, 1, -1, -1))
        t = max(0.0, self._tick)
        if t > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(TICK_COLOR)
            inner = c.adjusted(1, 1, -1, -1)
            cx, cy = inner.center().x(), inner.center().y()
            hw = inner.width() / 2 * t
            p.drawEllipse(QRectF(cx - hw, cy - hw, hw * 2, hw * 2))
            draw_text(p, c, "check", max(1, int(18 * t)), icon=True)


class ScrollHint(Pressable):
    """Small chevron at the bottom of the list: "there is more below"."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = True
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def draw(self, p):
        if self.active:
            draw_text(p, QRectF(self.rect()), "expand_more", 28, icon=True, color=WHITE)


class PinnedEditor(QWidget):
    back = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pinned = []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # header: back button | "Pinned apps" pill | spacer (keeps the pill centered)
        head = QHBoxLayout()
        back = IconButton("chevron_left", 40, fill=BACK_FILL)
        back.clicked.connect(self.back.emit)
        self.title = TitlePill()
        spacer = QWidget()
        spacer.setFixedSize(40, 40)
        head.addWidget(back)
        head.addStretch()
        head.addWidget(self.title)
        head.addStretch()
        head.addWidget(spacer)
        root.addLayout(head)

        # list panel
        self.panel = Panel()
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(14, 12, 14, 4)
        pl.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("pinned_list_content")
        self.list_layout = QVBoxLayout(self.content)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        self.scroll.setWidget(self.content)
        # setWidget() turns auto-fill back ON for the inner widget (opaque grey box),
        # so make everything transparent AFTER it.
        self.scroll.viewport().setAutoFillBackground(False)
        self.content.setAutoFillBackground(False)
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget#pinned_list_content { background: transparent; }"
        )
        self.scroll.viewport().setStyleSheet("background: transparent;")
        pl.addWidget(self.scroll, 1)

        self.hint = ScrollHint()
        self.hint.clicked.connect(self._scroll_down)
        pl.addWidget(self.hint)
        root.addWidget(self.panel, 1)

        bar = self.scroll.verticalScrollBar()
        bar.valueChanged.connect(self._update_hint)
        bar.rangeChanged.connect(self._update_hint)

    # ---- data -----------------------------------------------------------
    def reload(self):
        """Rebuild the A-Z list from the installed apps and the saved pinned ids."""
        self.pinned = [i for i in load_pinned() if app_by_id(i)]
        clear_layout(self.list_layout)

        groups = {}
        for app in all_apps():
            ch = app["name"][:1].upper()
            groups.setdefault(ch if ch.isalpha() else "#", []).append(app)

        self.rows = {}
        for key in sorted(groups, key=lambda k: (k != "#", k)):
            lab = QLabel(key)
            lab.setFont(mkfont(12, bold=True))
            lab.setStyleSheet("color: rgba(255,255,255,200); background: transparent;")
            lab.setContentsMargins(8, 8, 0, 2)
            self.list_layout.addWidget(lab)
            for app in groups[key]:
                row = AppRow(app, app["id"] in self.pinned)
                row.clicked.connect(lambda r=row: self._toggle(r))
                self.list_layout.addWidget(row)
                self.rows[app["id"]] = row
        self.list_layout.addStretch()
        self.scroll.verticalScrollBar().setValue(0)
        QTimer.singleShot(0, self._update_hint)

    def _toggle(self, row):
        app_id = row.app["id"]
        if app_id in self.pinned:
            self.pinned.remove(app_id)
            row.set_pinned(False)
        else:
            if len(self.pinned) >= MAX_PINNED:
                self.title.flash(f"Max {MAX_PINNED} pinned apps")
                return
            self.pinned.append(app_id)
            row.set_pinned(True)
        save_pinned(self.pinned)

    # ---- scrolling hint ---------------------------------------------------
    def _update_hint(self, *_):
        bar = self.scroll.verticalScrollBar()
        self.hint.active = bar.value() < bar.maximum() - 4
        self.hint.update()

    def _scroll_down(self):
        bar = self.scroll.verticalScrollBar()
        anim = QPropertyAnimation(bar, b"value", self)
        anim.setDuration(260)
        anim.setStartValue(bar.value())
        anim.setEndValue(min(bar.maximum(), bar.value() + int(self.scroll.height() * 0.8)))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
