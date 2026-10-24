#!/usr/bin/env python3
"""Notification catcher for Better Hyprland: the replacement for swaync's daemon + popups.

    python notification-catcher.py            (start it once, with Hyprland)

It does two jobs:
  1. Owns `org.freedesktop.Notifications` on the session bus, so apps (Telegram, Brave, notify-send...)
     send their notifications here. Every notification is saved to the shared history file
     (notify_store.py) which the notification panel (notifications.py) shows.
  2. Shows each new notification as a toast at the bottom-right corner (your mockup): app name, age,
     close button, avatar, title, text and the app's action buttons (Reply, Mark as Unread...).

Do Not Disturb (switch in the panel) hides the toasts; notifications are still saved.
Only one notification daemon can own the bus name: stop swaync first (`pkill swaync`).

Needs: python-pyqt6, qt6-wayland, layer-shell-qt, python-gobject. Debug: BH_DEBUG=1.
"""
from __future__ import annotations

import hashlib
import logging
import os
import signal
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

APP_ID = "better-hyprland-nc-toast"
LAYER_SCOPE = "better-hyprland-nc-toast"  # starts with better-hyprland-nc, so the blur rule matches it

TOAST_W = 370  # mockup 520 px on the 1920x1080 canvas
MARGIN_RIGHT = 12
MARGIN_BOTTOM = 12
TOAST_GAP = 8
MAX_TOASTS = 3
MAX_ACTIONS = 3
DEFAULT_TIMEOUT_MS = 6000
HOVER_TIMEOUT_MS = 3000
WINDOW_H = MAX_TOASTS * 140 + (MAX_TOASTS - 1) * TOAST_GAP + MARGIN_BOTTOM

log = logging.getLogger(APP_ID)

try:
    from PyQt6.QtCore import (
        QAbstractEventDispatcher,
        QEasingCurve,
        QFileSystemWatcher,
        QRect,
        QRectF,
        Qt,
        QTimer,
        QVariantAnimation,
        pyqtSignal,
    )
    from PyQt6.QtGui import QColor, QImage, QPainter, QRegion
    from PyQt6.QtWidgets import (
        QAbstractButton,
        QApplication,
        QGraphicsOpacityEffect,
        QHBoxLayout,
        QLabel,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
    )
except ImportError as error:  # pragma: no cover
    sys.exit(f"PyQt6 is missing ({error}). Install it with: sudo pacman -S python-pyqt6 qt6-wayland")

try:
    from notify_dbus import REASON_CLOSED_BY_CALL, REASON_DISMISSED, REASON_EXPIRED, NotificationServer
except ImportError as error:  # pragma: no cover
    sys.exit(f"PyGObject is missing ({error}). Install it with: sudo pacman -S python-gobject")

import notify_store  # noqa: E402
from common import CloseButton, ElidedLabel, HoverTracker, Pill, Theme, make_font, make_label  # noqa: E402
from main import LayerShell  # noqa: E402  (the layer-shell bridge)
from notifications import Avatar, Notification, _plain  # noqa: E402


# ------------------------------------------------------------------------ helpers


def image_from_data(info: dict) -> QImage | None:
    """The `image-data` hint -> QImage (raw RGB / RGBA bytes with a row stride)."""
    fmt = QImage.Format.Format_RGBA8888 if info["has_alpha"] else QImage.Format.Format_RGB888
    image = QImage(info["data"], info["width"], info["height"], info["rowstride"], fmt)
    return image.copy() if not image.isNull() else None  # copy: the bytes object will not outlive this call


def save_hint_image(hints: dict) -> str:
    """Write an `image-data` hint to the cache as a PNG and return its path ("" if there is none)."""
    from notify_dbus import parse_image_data

    for key in ("image-data", "image_data", "icon_data"):
        if key in hints:
            info = parse_image_data(hints[key])
            if info is None:
                continue
            image = image_from_data(info)
            if image is None:
                continue
            folder = notify_store.image_dir()
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / (hashlib.sha1(info["data"]).hexdigest()[:20] + ".png")
            if not path.exists():
                image.save(str(path), "PNG")
            return str(path)
    return ""


def timeout_for(timeout: int, urgency: int) -> int:
    """Milliseconds until the toast closes itself; 0 = stays until closed."""
    if urgency >= 2 or timeout == 0:
        return 0
    return timeout if timeout > 0 else DEFAULT_TIMEOUT_MS


# ------------------------------------------------------------------------ toast widgets

DARK_TEXT = QColor("#1B0B2E")


class ActionButton(QAbstractButton):
    """White pill with dark text: "Reply", "Mark as Unread"."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setFont(make_font(Theme.SMALL_PT))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._hover = HoverTracker(self)

    def sizeHint(self):
        size = super().sizeHint()
        size.setHeight(22)
        return size

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        alpha = 215 + 30 * self._hover.value - (25 if self.isDown() else 0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, int(alpha)))
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(rect, 11, 11)
        painter.setPen(DARK_TEXT)
        painter.setFont(self.font())
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, int(rect.width()) - 12)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


class ToastCard(Pill):
    closed = pyqtSignal(int, int)  # id, reason
    action = pyqtSignal(int, str)  # id, action key
    changed = pyqtSignal()  # size/geometry changed (the window refreshes its input mask)

    def __init__(self, notification: Notification, actions: list[tuple[str, str]], timeout_ms: int) -> None:
        super().__init__()
        self.notification_id = notification.id
        self._timeout = timeout_ms
        self._has_default = any(key == "default" for key, _ in actions)
        self._t = 0.0
        self._closing = False
        self._on_gone = None
        self.setFixedWidth(TOAST_W)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 12, 12)
        root.setSpacing(6)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        top.addWidget(ElidedLabel(notification.app_name, Theme.BODY_PT, color=Theme.TEXT_DIM), 1)
        top.addWidget(make_label("now", Theme.SMALL_PT, color=Theme.TEXT_DIM), 0)
        close = CloseButton()
        close.clicked.connect(lambda *_: self.closed.emit(self.notification_id, REASON_DISMISSED))
        top.addWidget(close, 0)
        root.addLayout(top)

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(12)
        middle.addWidget(Avatar(notification, 60), 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        text.addWidget(ElidedLabel(_plain(notification.summary), Theme.TITLE_PT, bold=True))
        body = _plain(notification.body)
        if body:
            label = QLabel(body)
            label.setFont(make_font(Theme.BODY_PT))
            label.setWordWrap(True)
            label.setMaximumHeight(label.fontMetrics().lineSpacing() * 2 + 2)  # two lines at most
            label.setStyleSheet(f"color: {Theme.TEXT.name()}; background: transparent;")
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            text.addWidget(label)
        text.addStretch(1)
        middle.addLayout(text, 1)
        root.addLayout(middle)

        shown = [(key, label) for key, label in actions if key != "default" and label][:MAX_ACTIONS]
        if shown:
            row = QHBoxLayout()
            row.setContentsMargins(72, 0, 0, 0)  # lines up with the text column (avatar 60 + gap 12)
            row.setSpacing(8)
            for key, label in shown:
                button = ActionButton(label)
                button.clicked.connect(lambda _=False, k=key: self._invoke(k))
                row.addWidget(button, 1)
            root.addLayout(row)

        self._full = root.sizeHint().height()
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self.setMaximumHeight(0)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(Theme.ANIM)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_t)
        self._anim.finished.connect(self._anim_finished)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self.closed.emit(self.notification_id, REASON_EXPIRED))

    # -- animation
    def _on_t(self, t) -> None:
        self._t = float(t)
        self._effect.setOpacity(self._t)
        self.setMaximumHeight(int(round(self._full * self._t)) if self._t < 1.0 else 16777215)
        self.changed.emit()

    def appear(self) -> None:
        self._go(1.0)
        if self._timeout > 0:
            self._timer.start(self._timeout)

    def disappear(self, on_gone) -> None:
        self._closing = True
        self._timer.stop()
        self._on_gone = on_gone
        self._go(0.0)

    def _go(self, end: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(end)
        self._anim.start()

    def _anim_finished(self) -> None:
        if self._closing and self._on_gone is not None:
            callback, self._on_gone = self._on_gone, None
            callback()

    # -- interaction
    def _invoke(self, key: str) -> None:
        self.action.emit(self.notification_id, key)
        self.closed.emit(self.notification_id, REASON_DISMISSED)

    def enterEvent(self, event) -> None:
        self._timer.stop()  # reading it: do not close under the pointer
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._timeout > 0 and not self._closing:
            self._timer.start(min(self._timeout, HOVER_TIMEOUT_MS))
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._has_default and self.rect().contains(event.position().toPoint()):
            self._invoke("default")  # clicking the toast itself opens the app
        else:
            super().mouseReleaseEvent(event)


class ToastWindow(QWidget):
    """Small layer surface in the bottom-right corner holding the stack of toast cards."""

    closed = pyqtSignal(int, int)
    action = pyqtSignal(int, str)

    def __init__(self, *, layer_shell: bool) -> None:
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if not layer_shell:
            flags |= Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocusHint
        super().__init__(None, flags)
        self.setWindowTitle("Better Hyprland Notification Toasts")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._layer = layer_shell
        self._cards: dict[int, ToastCard] = {}  # oldest -> newest

        self.setFixedSize(TOAST_W + MARGIN_RIGHT, WINDOW_H)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, MARGIN_RIGHT, MARGIN_BOTTOM)
        self._layout.setSpacing(TOAST_GAP)
        self._layout.addStretch(1)  # cards sit at the bottom; older ones are pushed up

    def show_toast(self, notification: Notification, actions: list[tuple[str, str]], timeout_ms: int) -> None:
        if notification.id in self._cards:  # "replaces_id": swap the old card out at once
            self._drop(notification.id)
        while len(self._cards) >= MAX_TOASTS:
            self.closed.emit(next(iter(self._cards)), REASON_EXPIRED)
            self._drop(next(iter(self._cards)))
        card = ToastCard(notification, actions, timeout_ms)
        card.closed.connect(self.close_toast)
        card.action.connect(self.action)
        card.changed.connect(self._update_mask)
        self._cards[notification.id] = card
        self._layout.addWidget(card)
        if not self.isVisible():
            self._place()
            self.show()
        card.appear()

    def has_toast(self, notification_id: int) -> bool:
        return notification_id in self._cards

    def close_toast(self, notification_id: int, reason: int) -> None:
        card = self._cards.pop(notification_id, None)
        if card is None:
            return
        self.closed.emit(notification_id, reason)
        card.disappear(lambda c=card: self._finish(c))

    def remove_silently(self, notification_id: int) -> None:
        card = self._cards.pop(notification_id, None)
        if card is not None:
            card.disappear(lambda c=card: self._finish(c))

    def _drop(self, notification_id: int) -> None:
        card = self._cards.pop(notification_id, None)
        if card is not None:
            self._finish(card)

    def _finish(self, card: ToastCard) -> None:
        card.hide()
        self._layout.removeWidget(card)
        card.deleteLater()
        self._update_mask()
        if not self._cards:
            self.hide()

    def _place(self) -> None:
        if self._layer:
            return  # the compositor anchors us to the corner
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.right() - self.width() + 1, area.bottom() - self.height() + 1)

    def _update_mask(self) -> None:
        """Only the cards take clicks; the empty part of this surface lets them through."""
        self._layout.activate()
        region = QRegion()
        for card in self._cards.values():
            geometry = card.geometry()
            if geometry.height() > 0:
                region = region.united(QRegion(QRect(geometry)))
        if region.isEmpty():
            region = QRegion(QRect(0, 0, 1, 1))
        self.setMask(region)


# ------------------------------------------------------------------------ the daemon


class Catcher:
    def __init__(self, toasts: ToastWindow, app: QApplication) -> None:
        self.toasts = toasts
        self.app = app
        self.server = NotificationServer(self._on_notify, self._on_close_request, self._on_name_lost)
        self._known: set[int] = {int(i["id"]) for i in notify_store.read()["items"]}

        toasts.closed.connect(self.server.closed)
        toasts.action.connect(self.server.action)

        # The panel can dismiss notifications; tell the apps and drop the matching toast.
        self._watcher = QFileSystemWatcher(self.app)
        folder = notify_store.state_dir()
        folder.mkdir(parents=True, exist_ok=True)
        self._watcher.addPath(str(folder))
        self._debounce = QTimer(self.app)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(60)
        self._debounce.timeout.connect(self._history_changed)
        self._watcher.directoryChanged.connect(lambda *_: self._debounce.start())

    def start(self) -> None:
        self.server.start()

    # -- D-Bus callbacks
    def _on_notify(self, params: dict) -> int:
        hints = params["hints"]
        urgency = int(hints.get("urgency", 1))
        image_path = str(hints.get("image-path") or hints.get("image_path") or "")
        try:
            image_path = save_hint_image(hints) or image_path
        except Exception:
            log.exception("could not read the notification image")
        app_name = params["app_name"] or str(hints.get("desktop-entry") or "") or "Notification"
        item = {
            "id": params["id"],
            "app_name": app_name,
            "summary": params["summary"],
            "body": params["body"],
            "app_icon": params["app_icon"],
            "image_path": image_path,
            "timestamp": time.time(),
            "urgency": urgency,
        }
        notification_id, dnd = notify_store.add(item)
        self._known.add(notification_id)
        if not dnd or urgency >= 2:
            notification = Notification(
                notification_id, app_name, params["summary"], params["body"], params["app_icon"], image_path,
                item["timestamp"], params["actions"], urgency,
            )
            self.toasts.show_toast(notification, params["actions"], timeout_for(params["timeout"], urgency))
        log.debug("notification %d from %s: %s", notification_id, app_name, params["summary"])
        return notification_id

    def _on_close_request(self, notification_id: int) -> None:
        """An app asked to retract its notification."""
        if self.toasts.has_toast(notification_id):
            self.toasts.remove_silently(notification_id)
        notify_store.dismiss(notification_id)
        self._known.discard(notification_id)
        self.server.closed(notification_id, REASON_CLOSED_BY_CALL)

    def _on_name_lost(self) -> None:
        print(
            "Another notification daemon (swaync, dunst, mako...) already owns org.freedesktop.Notifications.\n"
            "Stop it first, for example:  pkill swaync   -- then start this again.",
            file=sys.stderr,
        )
        self.app.exit(1)

    # -- history changes made by the panel
    def _history_changed(self) -> None:
        current = {int(i["id"]) for i in notify_store.read()["items"]}
        for gone in self._known - current:
            self.toasts.remove_silently(gone)
            self.server.closed(gone, REASON_DISMISSED)
        self._known = current


def run() -> int:
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
    app.setQuitOnLastWindowClosed(False)  # the toast window hides when empty; the daemon keeps running
    app.setFont(make_font(Theme.BODY_PT))
    use_layer = layer_lib is not None and app.platformName() == "wayland"

    toasts = ToastWindow(layer_shell=use_layer)
    if use_layer:
        toasts.winId()  # create the platform window without mapping it
        if not LayerShell.configure(
            layer_lib,
            toasts.windowHandle(),
            scope=LAYER_SCOPE,
            anchors=LayerShell.ANCHOR_BOTTOM | LayerShell.ANCHOR_RIGHT,
            layer=LayerShell.LAYER_TOP,
            keyboard=0,  # toasts never take the keyboard
        ):
            log.warning("layer-shell setup failed; toasts will be a normal window")

    catcher = Catcher(toasts, app)

    # Gio callbacks need the GLib main loop. Qt's event loop is one on a normal Linux build;
    # if it is not, pump GLib from a timer so D-Bus calls are still answered.
    dispatcher = QAbstractEventDispatcher.instance()
    kind = dispatcher.metaObject().className() if dispatcher is not None else ""
    log.debug("event dispatcher: %s", kind)
    if "glib" not in kind.lower():
        from gi.repository import GLib

        pump = QTimer(app)
        pump.setInterval(30)
        pump.timeout.connect(lambda: [None for _ in iter(lambda: GLib.MainContext.default().iteration(False), False)])
        pump.start()

    catcher.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
