"""
search.py - app search screen

Opened from the search bar in the start menu (slide-fade from the start UI).
  - the text cursor is put in the search box automatically
  - results slide up with a cubic-bezier(0.16, 1, 0.3, 1) curve
  - Up / Down moves the highlight, Enter launches, Esc clears then goes back
Empty box = all apps A-Z; typing filters + ranks them.
"""
from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLineEdit, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from start_main_menu import (
    icon_pixmap,
    BASE, FILL_HALF, HOVER, EmptyNote, IconButton, Pressable,
    all_apps, clear_layout, draw_text, launch_app, load_icon, make_icon_label, mkfont,
)

BACK_FILL = QColor(*BASE, 51)        # back button: #693652 @ 0.2 (same as apps_all_menu)
ICON_BG = QColor(*BASE, 77)          # app icon circles: #693652 @ 0.3 (same as apps_all_menu)
SELECTED = QColor(255, 255, 255, 42)
STAGGER_MS = 28          # delay between rows sliding in
MAX_STAGGER = 10         # rows after this all start together


def slide_curve():
    """cubic-bezier(0.16, 1, 0.3, 1)"""
    c = QEasingCurve(QEasingCurve.Type.BezierSpline)
    c.addCubicBezierSegment(QPointF(0.16, 1.0), QPointF(0.3, 1.0), QPointF(1.0, 1.0))
    return c


def match_score(app, q):
    """Lower = better. None = no match."""
    n = app["name"].lower()
    if n == q:
        return 0
    if n.startswith(q):
        return 1
    if any(w.startswith(q) for w in n.replace("-", " ").split()):
        return 2
    if q in n:
        return 3
    if q in app["id"].lower():
        return 4
    it = iter(n)
    if all(ch in it for ch in q.replace(" ", "")):   # letters in order, e.g. "ffx" -> Firefox
        return 5
    return None


def ranked_apps(q):
    if not q:
        return list(all_apps())
    scored = []
    for app in all_apps():
        s = match_score(app, q)
        if s is not None:
            scored.append((s, app["name"].lower(), app))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in scored]


class SearchEdit(QLineEdit):
    move_up = pyqtSignal()
    move_down = pyqtSignal()
    escape = pyqtSignal()

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Down:
            self.move_down.emit()
        elif k == Qt.Key.Key_Up:
            self.move_up.emit()
        elif k == Qt.Key.Key_Escape:
            self.escape.emit()
        else:
            super().keyPressEvent(e)


class SearchPill(QWidget):
    """Pill-shaped text input: #693652 @ 0.5, search icon, no placeholder text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 16, 0)
        lay.setSpacing(8)
        lay.addWidget(make_icon_label("search", 24))
        self.edit = SearchEdit()
        self.edit.setFont(mkfont(15))
        self.edit.setFrame(False)
        self.edit.setStyleSheet(
            "QLineEdit { color: white; background: transparent; border: none;"
            " selection-background-color: rgba(255,255,255,70); }"
        )
        lay.addWidget(self.edit, 1)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(FILL_HALF)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)


class Panel(QWidget):
    """Rounded results panel (#693652 @ 0.5, same as the All Apps screen)."""

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 24, 24)
        p.fillPath(path, FILL_HALF)


class SearchRow(Pressable):
    """One result: icon circle + app name. Slides up + fades in when it appears."""
    PRESS_SCALE = 0.97
    CIRCLE = ICON_BG            # icon circle colour (#693652 @ 0.3)

    def __init__(self, app, delay_ms, parent=None):
        super().__init__(parent)
        self.app = app
        self.selected = False
        self.icon = load_icon(app["icon"])
        self._in = 0.0
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._in_anim = QVariantAnimation(self)
        self._in_anim.setStartValue(0.0)
        self._in_anim.setEndValue(1.0)
        self._in_anim.setDuration(520)
        self._in_anim.setEasingCurve(slide_curve())
        self._in_anim.valueChanged.connect(self._set_in)

        self._delay = QTimer(self)               # child of the row: dies with it
        self._delay.setSingleShot(True)
        self._delay.timeout.connect(self._in_anim.start)
        self._delay.start(max(0, int(delay_ms)))

    def _set_in(self, v):
        self._in = float(v)
        self.update()

    def draw(self, p):
        p.setOpacity(self._in)
        p.translate(0, (1.0 - self._in) * 24)       # slide up
        if self.selected or self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(SELECTED if self.selected else HOVER)
            p.drawRoundedRect(QRectF(self.rect()), 14, 14)
        circle = QRectF(6, 6, 40, 40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.CIRCLE)
        p.drawEllipse(circle)
        if not self.icon.isNull():
            pm = icon_pixmap(self.icon, 28, self)
            p.drawPixmap(int(circle.center().x() - 14), int(circle.center().y() - 14), pm)
        else:
            draw_text(p, circle, (self.app["name"][:1] or "?").upper(), 18, bold=True)
        draw_text(p, QRectF(58, 0, self.width() - 70, self.height()), self.app["name"], 14,
                  align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)


class SearchScreen(QWidget):
    back = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.selected = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        back = IconButton("chevron_left", 40, fill=BACK_FILL)
        back.clicked.connect(self.back.emit)
        self.pill = SearchPill()
        head.addWidget(back)
        head.addWidget(self.pill, 1)
        root.addLayout(head)

        self.panel = Panel()
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(14, 12, 14, 12)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("search_list_content")
        self.list_layout = QVBoxLayout(self.content)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        self.scroll.setWidget(self.content)
        # setWidget() re-enables auto-fill (opaque box) -> make transparent AFTER it
        self.scroll.viewport().setAutoFillBackground(False)
        self.content.setAutoFillBackground(False)
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget#search_list_content { background: transparent; }"
        )
        self.scroll.viewport().setStyleSheet("background: transparent;")
        pl.addWidget(self.scroll)
        root.addWidget(self.panel, 1)

        edit = self.pill.edit
        edit.textChanged.connect(self._on_text)
        edit.returnPressed.connect(self._launch_selected)
        edit.move_down.connect(lambda: self._move(+1))
        edit.move_up.connect(lambda: self._move(-1))
        edit.escape.connect(self._on_escape)

    # ---- called by the start menu every time the screen is opened -----------
    def reload(self):
        edit = self.pill.edit
        edit.blockSignals(True)
        edit.clear()
        edit.blockSignals(False)
        self._refresh("", base_delay=240)                 # wait for the slide-fade to finish
        QTimer.singleShot(260, edit.setFocus)             # put the type cursor in the box

    # ---- results ---------------------------------------------------------------
    def _on_text(self, text):
        self._refresh(text.strip().lower())

    def _refresh(self, q, base_delay=0):
        apps = ranked_apps(q)
        clear_layout(self.list_layout)
        self.rows = []
        self.selected = -1
        if not apps:
            note = EmptyNote("No apps found", bold=True, alpha=128)
            note.setMinimumHeight(140)
            self.list_layout.addWidget(note)
        else:
            for i, app in enumerate(apps):
                row = SearchRow(app, base_delay + min(i, MAX_STAGGER) * STAGGER_MS)
                row.clicked.connect(lambda a=app: self._launch(a))
                self.list_layout.addWidget(row)
                self.rows.append(row)
        self.list_layout.addStretch()
        self.scroll.verticalScrollBar().setValue(0)
        if self.rows:
            self._select(0)

    def _select(self, i):
        if 0 <= self.selected < len(self.rows):
            old = self.rows[self.selected]
            old.selected = False
            old.update()
        self.selected = i
        row = self.rows[i]
        row.selected = True
        row.update()
        self.scroll.ensureWidgetVisible(row, 0, 24)

    def _move(self, d):
        if self.rows:
            self._select((self.selected + d) % len(self.rows))

    # ---- actions ---------------------------------------------------------------
    def _launch(self, app):
        launch_app(app)
        self.window().close_menu()

    def _launch_selected(self):
        if 0 <= self.selected < len(self.rows):
            self._launch(self.rows[self.selected].app)

    def _on_escape(self):
        if self.pill.edit.text():
            self.pill.edit.clear()
        else:
            self.back.emit()
