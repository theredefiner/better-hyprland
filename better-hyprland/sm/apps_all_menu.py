"""
apps_all_menu.py - "All Apps" screen

Opened from "See all" in the start menu (slide-fade from the start UI).
Every installed app A-Z (# first), apps slide up with cubic-bezier(0.16, 1, 0.3, 1).
Click an app to launch it (the menu closes).
"""
from PyQt6.QtCore import QAbstractAnimation, QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from search import MAX_STAGGER, STAGGER_MS, SearchRow
from start_main_menu import (
    BASE, FILL_HALF, IconButton, Pressable, all_apps, clear_layout, draw_text,
    launch_app, mkfont,
)

BACK_FILL = QColor(*BASE, 51)        # back button: #693652 @ 0.2
ICON_BG = QColor(*BASE, 77)          # app icon circles: #693652 @ 0.3
WHITE = QColor(255, 255, 255)


class TitlePill(QWidget):
    """Centered pill: icon + "All Apps"."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(240, 40)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(FILL_HALF)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        draw_text(p, QRectF(r.left() + 44, r.top(), 28, r.height()), "dashboard_customize", 22, icon=True)
        draw_text(p, QRectF(r.left() + 80, r.top(), r.width() - 92, r.height()), "All Apps", 15, bold=True,
                  align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)


class Panel(QWidget):
    """Rounded list panel (#693652 @ 0.5)."""

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 24, 24)
        p.fillPath(path, FILL_HALF)


class AllAppRow(SearchRow):
    """Same slide-up row as the search results, with the 0.3 icon circle."""
    CIRCLE = ICON_BG

    def __init__(self, app, delay_ms, parent=None):
        super().__init__(app, delay_ms, parent)
        self.selected = False        # no keyboard highlight on this screen


class ScrollHint(Pressable):
    """Chevron at the bottom of the list ("more below")."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = True
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def draw(self, p):
        if self.active:
            draw_text(p, QRectF(self.rect()), "expand_more", 28, icon=True, color=WHITE)


class AllAppsScreen(QWidget):
    back = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        back = IconButton("chevron_left", 40, fill=BACK_FILL)
        back.clicked.connect(self.back.emit)
        spacer = QWidget()
        spacer.setFixedSize(40, 40)
        head.addWidget(back)
        head.addStretch()
        head.addWidget(TitlePill())
        head.addStretch()
        head.addWidget(spacer)
        root.addLayout(head)

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
        self.content.setObjectName("all_apps_content")
        self.list_layout = QVBoxLayout(self.content)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        self.scroll.setWidget(self.content)
        # setWidget() re-enables auto-fill (opaque box) -> make transparent AFTER it
        self.scroll.viewport().setAutoFillBackground(False)
        self.content.setAutoFillBackground(False)
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget#all_apps_content { background: transparent; }"
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

    # ---- called by the start menu every time the screen opens ---------------
    def reload(self):
        clear_layout(self.list_layout)
        groups = {}
        for app in all_apps():
            ch = app["name"][:1].upper()
            groups.setdefault(ch if ch.isalpha() else "#", []).append(app)

        n = 0
        for key in sorted(groups, key=lambda k: (k != "#", k)):
            lab = QLabel(key)
            lab.setFont(mkfont(12, bold=True))
            lab.setStyleSheet("color: rgba(255,255,255,200); background: transparent;")
            lab.setContentsMargins(8, 8, 0, 2)
            self.list_layout.addWidget(lab)
            for app in groups[key]:
                # wait for the slide-fade (240ms), then rows slide up one after another
                row = AllAppRow(app, 240 + min(n, MAX_STAGGER) * STAGGER_MS)
                row.clicked.connect(lambda a=app: self._launch(a))
                self.list_layout.addWidget(row)
                n += 1
        self.list_layout.addStretch()
        self.scroll.verticalScrollBar().setValue(0)
        QTimer.singleShot(0, self._update_hint)

    def _launch(self, app):
        launch_app(app)
        self.window().close_menu()

    # ---- scroll hint -----------------------------------------------------------
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
