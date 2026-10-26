"""Notifications pill (first pill of the Better Hyprland notification center).

Contents:
    Notification       plain data record for one notification
    NotificationStore  QObject that owns the list + Do Not Disturb state (the D-Bus
                       listener / toast code will feed it with `store.add(...)`)
    NotificationCard   one compact row: avatar, app name, age, summary, body, ✕
    NotificationsPill  the pill: title, Clear All, DND switch, card list / empty state

main.py loads this file and calls `create_pill(services)`.
"""
from __future__ import annotations

import functools
import html
import os
import re
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field

from PyQt6.QtCore import (
    QEasingCurve,
    QFileSystemWatcher,
    QObject,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

import notify_store
from common import (
    CloseButton,
    ElidedLabel,
    HoverTracker,
    Pill,
    TextButton,
    Theme,
    ToggleSwitch,
    make_label,
)


# --------------------------------------------------------------------------- data


@dataclass
class Notification:
    id: int  # 0 or less = let the store assign one
    app_name: str
    summary: str
    body: str = ""
    app_icon: str = ""  # icon-theme name or absolute path / file:// URL
    image_path: str = ""  # sender avatar, preferred over app_icon when set
    timestamp: float = field(default_factory=time.time)
    actions: list[tuple[str, str]] = field(default_factory=list)  # (key, label) for the toast
    urgency: int = 1


def format_age(timestamp: float, now: float | None = None) -> str:
    delta = max(0.0, (time.time() if now is None else now) - timestamp)
    if delta < 60:
        return "now"
    if delta < 3600:
        return f"{int(delta // 60)}m"
    if delta < 86400:
        return f"{int(delta // 3600)}h"
    return f"{int(delta // 86400)}d"


def _plain(text: str) -> str:
    """Notification bodies may contain tiny HTML; show them as one plain line."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", text)).split())


class NotificationStore(QObject):
    """Source of truth for the panel. All mutation happens on the GUI thread."""

    added = pyqtSignal(object)  # Notification
    removed = pyqtSignal(int)  # notification id
    cleared = pyqtSignal()
    dnd_changed = pyqtSignal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: dict[int, Notification] = {}  # oldest -> newest
        self._next_id = 1
        self._dnd = False
        self._synced = False
        self._watcher: QFileSystemWatcher | None = None
        self._reload_timer: QTimer | None = None

    # -- shared history file (written by notification-catcher.py)
    def enable_sync(self) -> None:
        """Mirror notify_store's file: load it now and follow every change made by the catcher."""
        self._synced = True
        folder = notify_store.state_dir()
        folder.mkdir(parents=True, exist_ok=True)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.addPath(str(folder))  # the directory: the file is replaced atomically on each write
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(40)
        self._reload_timer.timeout.connect(self._reload)
        self._watcher.directoryChanged.connect(lambda *_: self._reload_timer.start())
        self._reload()

    def _reload(self) -> None:
        if not self._synced:
            return
        data = notify_store.read()
        fresh = {
            int(i["id"]): Notification(
                int(i["id"]), i.get("app_name", ""), i.get("summary", ""), i.get("body", ""),
                i.get("app_icon", ""), i.get("image_path", ""), float(i.get("timestamp") or time.time()),
                urgency=int(i.get("urgency", 1)),
            )
            for i in data["items"]
        }
        for notification_id in [i for i in self._items if i not in fresh]:
            del self._items[notification_id]
            self.removed.emit(notification_id)
        for notification_id, notification in fresh.items():  # oldest -> newest
            old = self._items.get(notification_id)
            if old is not None and old.timestamp == notification.timestamp:
                continue
            if old is not None:  # replaced by the app: show the new one on top
                del self._items[notification_id]
                self.removed.emit(notification_id)
            self._items[notification_id] = notification
            self.added.emit(notification)
        dnd = bool(data.get("dnd"))
        if dnd != self._dnd:
            self._dnd = dnd
            self.dnd_changed.emit(dnd)

    # -- read
    def items(self) -> list[Notification]:
        """Newest first."""
        return list(reversed(self._items.values()))

    @property
    def dnd(self) -> bool:
        return self._dnd

    # -- write
    def add(self, notification: Notification) -> Notification:
        if notification.id <= 0:
            notification.id = self._next_id
        self._next_id = max(self._next_id, notification.id) + 1
        if notification.id in self._items:  # "replaces_id": drop the old one, show the new on top
            del self._items[notification.id]
            self.removed.emit(notification.id)
        self._items[notification.id] = notification
        self.added.emit(notification)
        return notification

    def dismiss(self, notification_id: int) -> None:
        if self._synced:
            notify_store.dismiss(notification_id)
        if self._items.pop(notification_id, None) is not None:
            self.removed.emit(notification_id)

    def clear(self) -> None:
        if self._synced:
            notify_store.clear()
        if self._items:
            self._items.clear()
            self.cleared.emit()

    def set_dnd(self, enabled: bool) -> None:
        if self._synced:
            notify_store.set_dnd(enabled)
        if enabled != self._dnd:
            self._dnd = enabled
            self.dnd_changed.emit(enabled)

    def add_demo_data(self) -> None:
        """Preview helper for `main.py --demo`: three cards arriving one after another."""
        self._synced = False  # demo cards are not in the history file; do not let a reload wipe them
        now = time.time()
        samples = [
            Notification(0, "Telegram Desktop", "Riyad ⚡", "kire,,, koi gelu", app_icon="telegram", timestamp=now),
            Notification(
                0, "Brave", "Download complete", "arch-linux-2026.10.01-x86_64.iso", app_icon="brave-browser",
                timestamp=now - 12 * 60,
            ),
            Notification(
                0, "System Update", "Updates available", "14 packages can be upgraded", app_icon="system-software-update",
                timestamp=now - 2 * 3600,
            ),
        ]
        for index, sample in enumerate(samples):
            QTimer.singleShot(350 * (index + 1), lambda s=sample: self.add(s))


# -------------------------------------------------------------------------- cards


@functools.lru_cache(maxsize=64)
def _load_pixmap(source: str, size: int) -> QPixmap | None:
    """Square, smooth-scaled pixmap from a file path or an icon-theme name."""
    if not source:
        return None
    if source.startswith("file://"):
        source = source[7:]
    if os.path.isabs(source):
        pixmap = QPixmap(source)
    else:
        icon = QIcon.fromTheme(source)
        pixmap = icon.pixmap(size * 2, size * 2) if not icon.isNull() else QPixmap()
    if pixmap.isNull():
        return None
    side = min(pixmap.width(), pixmap.height())
    square = pixmap.copy(QRect((pixmap.width() - side) // 2, (pixmap.height() - side) // 2, side, side))
    return square.scaled(
        size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
    )


class Avatar(QWidget):
    """Circular sender image / app icon, falling back to a coloured initial."""

    def __init__(self, notification: Notification, size: int = 34, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._pixmap = _load_pixmap(notification.image_path, size) or _load_pixmap(notification.app_icon, size)
        name = notification.app_name or "?"
        self._letter = name[:1].upper()
        self._fallback = QColor.fromHsl(zlib.crc32(name.encode()) % 360, 110, 120)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        circle = QPainterPath()
        circle.addEllipse(QRectF(self.rect()))
        painter.setClipPath(circle)
        if self._pixmap is not None:
            painter.drawPixmap(0, 0, self._pixmap)
            return
        painter.fillPath(circle, self._fallback)
        painter.setPen(QColor(255, 255, 255))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(int(self.height() * 0.45))
        painter.setFont(font)
        painter.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, self._letter)


class NotificationCard(QWidget):
    HEIGHT = 58

    dismiss_requested = pyqtSignal(int)

    def __init__(self, notification: Notification, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.notification_id = notification.id
        self._timestamp = notification.timestamp
        self._on_done: Callable[[], None] | None = None
        self._anim = QPropertyAnimation(self, b"maximumHeight", self)  # one reusable animation
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._anim_finished)
        self._hover = HoverTracker(self)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMaximumHeight(self.HEIGHT)

        root = QHBoxLayout(self)
        # Lets maximumHeight animate down to 0 instead of being held up by the content's min size.
        root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        root.setContentsMargins(10, 6, 6, 6)
        root.setSpacing(10)

        root.addWidget(Avatar(notification), 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)
        top_row.addWidget(ElidedLabel(notification.app_name, Theme.SMALL_PT, color=Theme.TEXT_FAINT), 1)
        self._age = make_label(format_age(self._timestamp), Theme.SMALL_PT, color=Theme.TEXT_FAINT)
        top_row.addWidget(self._age, 0)

        text_col.addStretch(1)
        text_col.addLayout(top_row)
        text_col.addWidget(ElidedLabel(_plain(notification.summary), Theme.BODY_PT, bold=True))
        body = _plain(notification.body)
        if body:
            text_col.addWidget(ElidedLabel(body, Theme.SMALL_PT, color=Theme.TEXT_DIM))
        text_col.addStretch(1)
        root.addLayout(text_col, 1)

        close = CloseButton()
        close.clicked.connect(lambda *_: self.dismiss_requested.emit(self.notification_id))
        root.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

    def refresh_age(self) -> None:
        self._age.setText(format_age(self._timestamp))

    def animate_height(self, end: int, duration: int, on_done: Callable[[], None] | None = None) -> None:
        self._on_done = None  # an interrupted animation must not fire its old callback
        self._anim.stop()
        self._on_done = on_done
        self._anim.setDuration(duration)
        self._anim.setStartValue(self.maximumHeight())
        self._anim.setEndValue(end)
        self._anim.start()

    def _anim_finished(self) -> None:
        done, self._on_done = self._on_done, None
        if done is not None:
            done()

    def collapse(self, on_done: Callable[[], None]) -> None:
        self.setEnabled(False)
        self.animate_height(0, Theme.ANIM, on_done)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, int(28 + 18 * self._hover.value)))
        painter.drawRoundedRect(QRectF(self.rect()), 14, 14)


# --------------------------------------------------------------------------- pill

_SCROLL_QSS = """
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 4px; margin: 0; }
QScrollBar::handle:vertical { background: rgba(255, 255, 255, 90); border-radius: 2px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""


class NotificationsPill(Pill):
    HEIGHT = 178

    def __init__(self, store: NotificationStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self._store = store
        self._cards: dict[int, NotificationCard] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(Theme.PILL_PADDING, 12, Theme.PILL_PADDING, 12)
        root.setSpacing(8)

        # Header: title + Clear All on the left, Do Not Disturb on the right.
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(make_label("Notifications", Theme.TITLE_PT, bold=True))
        self._clear_button = TextButton("Clear All")
        header.addWidget(self._clear_button)
        header.addStretch(1)
        header.addWidget(make_label("Do Not Disturb", Theme.BODY_PT))
        self._dnd_switch = ToggleSwitch()
        header.addWidget(self._dnd_switch)
        root.addLayout(header)

        # Body: either the "No Notifications" label or the scrolling card list.
        body = QWidget()
        self._stack = QStackedLayout(body)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._empty = make_label(
            "No Notifications", Theme.EMPTY_PT, color=Theme.TEXT_DIM, align=Qt.AlignmentFlag.AlignCenter
        )
        self._stack.addWidget(self._empty)

        self._scroll = QScrollArea()
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.setStyleSheet(_SCROLL_QSS)
        host = QWidget()
        host.setAutoFillBackground(False)
        self._list = QVBoxLayout(host)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(6)
        self._list.addStretch(1)
        self._scroll.setWidget(host)
        self._stack.addWidget(self._scroll)
        root.addWidget(body, 1)

        # Wiring
        self._dnd_switch.setChecked(store.dnd)
        self._dnd_switch.toggled.connect(store.set_dnd)
        store.dnd_changed.connect(self._dnd_switch.setChecked)
        self._clear_button.clicked.connect(store.clear)
        store.added.connect(self._on_added)
        store.removed.connect(self._on_removed)
        store.cleared.connect(self._on_cleared)

        for notification in reversed(store.items()):  # oldest first, each inserted on top
            self._add_card(notification, animate=False)
        self._sync_header()
        self._sync_body()

        # One shared timer keeps every "5m" / "2h" label fresh, only while the pill is visible.
        self._age_timer = QTimer(self)
        self._age_timer.setInterval(30_000)
        self._age_timer.timeout.connect(self._refresh_ages)

    # -- store events
    def _on_added(self, notification: Notification) -> None:
        self._add_card(notification, animate=self.isVisible())
        self._sync_header()
        self._sync_body()

    def _on_removed(self, notification_id: int) -> None:
        card = self._cards.pop(notification_id, None)
        if card is None:
            return
        self._sync_header()
        card.collapse(lambda c=card: self._finish_removal(c))

    def _on_cleared(self) -> None:
        cards = list(self._cards.values())
        self._cards.clear()
        self._sync_header()
        for card in cards:
            card.collapse(lambda c=card: self._finish_removal(c))
        if not cards:
            self._sync_body()

    # -- helpers
    def _add_card(self, notification: Notification, *, animate: bool) -> None:
        card = NotificationCard(notification)
        card.dismiss_requested.connect(self._store.dismiss)
        self._cards[notification.id] = card
        self._list.insertWidget(0, card)
        if animate:
            card.setMaximumHeight(0)
            card.animate_height(NotificationCard.HEIGHT, Theme.ANIM)

    def _finish_removal(self, card: NotificationCard) -> None:
        card.hide()
        card.deleteLater()
        self._sync_body()

    def _sync_header(self) -> None:
        self._clear_button.setVisible(bool(self._cards))

    def _sync_body(self) -> None:
        self._stack.setCurrentIndex(1 if self._cards else 0)

    def _refresh_ages(self) -> None:
        for card in self._cards.values():
            card.refresh_age()

    # -- visibility
    def showEvent(self, event) -> None:
        self._refresh_ages()
        self._age_timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._age_timer.stop()
        super().hideEvent(event)


def create_pill(services: dict) -> QWidget:
    """Entry point used by main.py. Shares the store through `services["notifications"]`."""
    store = services.get("notifications")
    if store is None:
        store = NotificationStore()
        store.enable_sync()  # history comes from notification-catcher.py
        services["notifications"] = store
    return NotificationsPill(store)
