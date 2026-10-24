"""Media Player pill (third pill): any MPRIS player (Spotify, Brave/Chromium, Firefox, mpv, VLC...).

Backend: `playerctl` (sudo pacman -S playerctl). One short-lived process per second while the
panel is visible - no background work when it is hidden. If several players are open, the one
that is Playing wins; otherwise the one used last stays selected.

Layout (from the mockup): thumbnail on the left; on the right "Now playing", track title,
seek slider, then elapsed time, previous / play-pause / next, and total time.

main.py loads this file and calls `create_pill(services)`.
"""
from __future__ import annotations

import logging
import shutil
import time
from collections import OrderedDict
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QPointF, QProcess, QRectF, Qt, QTimer, QUrl, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import QAbstractButton, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from common import ElidedLabel, HoverTracker, Pill, Theme, draw_icon, make_label, mix, run_async

log = logging.getLogger(__name__)

SEP = "\x1f"  # field separator in playerctl's output (never appears in titles)
FORMAT = SEP.join(
    ["{{status}}", "{{title}}", "{{artist}}", "{{mpris:artUrl}}", "{{mpris:length}}", "{{position}}", "{{playerName}}"]
)


# ------------------------------------------------------------------------ pure helpers


@dataclass
class Track:
    player: str
    status: str  # "Playing" | "Paused" | "Stopped"
    title: str
    artist: str
    art_url: str
    length_us: int  # 0 = unknown (live streams)
    position_us: int  # -1 = unknown


def _to_int(text: str, default: int) -> int:
    try:
        return int(float(text))
    except ValueError:
        return default


def parse_players(text: str) -> list[Track]:
    """One Track per output line of `playerctl -a metadata --format FORMAT`."""
    tracks = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(SEP)]
        if len(parts) < 7:
            continue
        status, title, artist, art_url, length, position, player = parts[:7]
        tracks.append(
            Track(
                player=player,
                status=status,
                title=title,
                artist=artist,
                art_url=art_url,
                length_us=max(0, _to_int(length, 0)),
                position_us=_to_int(position, -1),
            )
        )
    return tracks


def pick_player(tracks: list[Track], preferred: str = "") -> Track | None:
    """Playing wins, then the previously selected player, then any Paused one."""
    usable = [t for t in tracks if t.title or t.status in ("Playing", "Paused")]
    for track in usable:
        if track.status == "Playing":
            return track
    for track in usable:
        if track.player == preferred:
            return track
    for track in usable:
        if track.status == "Paused":
            return track
    return usable[0] if usable else None


def fmt_time(microseconds: float) -> str:
    total = max(0, int(microseconds // 1_000_000))
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def status_line(track: Track) -> str:
    base = {"Playing": "Now playing", "Paused": "Paused"}.get(track.status, "Stopped")
    return f"{base} · {track.artist}" if track.artist else base


# ------------------------------------------------------------------------ backend


class MediaController(QObject):
    updated = pyqtSignal(object)  # Track | None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.available = shutil.which("playerctl") is not None
        self._player = ""  # exact instance name, e.g. "brave.instance4242"
        self._busy = False
        self._busy_since = 0.0

    def poll(self) -> None:
        if not self.available:
            return
        now = time.monotonic()
        if self._busy and now - self._busy_since < 3.0:  # a poll is in flight (3 s watchdog)
            return
        self._busy = True
        self._busy_since = now
        run_async(self, "playerctl", ["-l"], self._on_player_list)

    def _on_player_list(self, code: int, out: str) -> None:
        """Ask every player by its exact instance name. Chromium-based browsers (Chromium, Brave...)
        can share the short name "chromium", so a short name could reach the wrong browser."""
        names = [line.strip() for line in out.splitlines() if line.strip()] if code == 0 else []
        names = list(dict.fromkeys(names))
        if not names:
            self._on_poll([])
            return
        results: dict[str, Track | None] = {}

        def ask(name: str) -> None:
            def got(exit_code: int, text: str) -> None:
                parsed = parse_players(text) if exit_code == 0 else []
                if parsed:
                    parsed[0].player = name
                results[name] = parsed[0] if parsed else None
                if len(results) == len(names):
                    self._on_poll([results[n] for n in names if results[n] is not None])

            run_async(self, "playerctl", ["-p", name, "metadata", "--format", FORMAT], got)

        for name in names:
            ask(name)

    def _on_poll(self, tracks: list[Track]) -> None:
        self._busy = False
        track = pick_player(tracks, self._player)
        self._player = track.player if track else ""
        if track is not None and track.position_us < 0 and track.status != "Stopped":
            # older playerctl without the {{position}} variable: ask for it separately
            def got_position(pos_code: int, pos_out: str) -> None:
                try:
                    track.position_us = int(float(pos_out) * 1_000_000) if pos_code == 0 else -1
                except ValueError:
                    track.position_us = -1
                self.updated.emit(track)

            run_async(self, "playerctl", ["-p", track.player, "position"], got_position)
        else:
            self.updated.emit(track)

    def _run(self, selector: list[str], args: tuple[str, ...], done) -> None:
        """Run `playerctl [selector] args`; done(ok, stderr_text) fires on the GUI thread."""
        holder: list[QProcess] = []

        def finished(code: int, _out: str) -> None:
            error = bytes(holder[0].readAllStandardError()).decode(errors="replace").strip() if holder else ""
            done(code == 0, error)

        holder.append(run_async(self, "playerctl", [*selector, *args], finished))

    def _command(self, *args: str) -> None:
        """Control exactly the selected player instance; a failure is logged with playerctl's message."""
        if not self._player:
            return
        name = self._player

        def done(ok: bool, error: str) -> None:
            if not ok:
                log.warning("playerctl %s failed for player %r: %s", " ".join(args), name, error or "no error text")
            QTimer.singleShot(120, self.poll)

        self._run(["-p", name], args, done)

    def play_pause(self) -> None:
        self._command("play-pause")

    def next(self) -> None:
        self._command("next")

    def previous(self) -> None:
        self._command("previous")

    def seek(self, seconds: float) -> None:
        self._command("position", f"{max(0.0, seconds):.2f}")


class ArtLoader(QObject):
    """Cover art from file:// or http(s) URLs, cached; network fetches never block the UI."""

    loaded = pyqtSignal(str, QPixmap)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._net = QNetworkAccessManager(self)
        self._net.setRedirectPolicy(QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._pending: set[str] = set()

    def get(self, url: str) -> QPixmap | None:
        """Cached pixmap now, or None (and `loaded` fires when it arrives)."""
        if not url:
            return None
        cached = self._cache.get(url)
        if cached is not None:
            self._cache.move_to_end(url)
            return cached
        if url.startswith("file://"):
            pixmap = QPixmap(QUrl(url).toLocalFile())
            if not pixmap.isNull():
                self._store(url, pixmap)
                return pixmap
        elif url.startswith(("http://", "https://")) and url not in self._pending:
            self._pending.add(url)
            reply = self._net.get(QNetworkRequest(QUrl(url)))
            reply.finished.connect(lambda r=reply, u=url: self._on_reply(u, r))
        return None

    def _on_reply(self, url: str, reply: QNetworkReply) -> None:
        self._pending.discard(url)
        pixmap = QPixmap()
        if reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap.loadFromData(bytes(reply.readAll()))
        reply.deleteLater()
        if not pixmap.isNull():
            self._store(url, pixmap)
            self.loaded.emit(url, pixmap)

    def _store(self, url: str, pixmap: QPixmap) -> None:
        self._cache[url] = pixmap.scaled(
            192, 192, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
        )
        while len(self._cache) > 8:
            self._cache.popitem(last=False)


# ------------------------------------------------------------------------ widgets


class Thumbnail(QWidget):
    SIZE = 84
    RADIUS = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._pixmap: QPixmap | None = None
        self._alpha = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(Theme.ANIM)
        self._anim.valueChanged.connect(self._on_alpha)

    def _on_alpha(self, value) -> None:
        self._alpha = float(value)
        self.update()

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        if pixmap is None or pixmap.isNull():
            self._pixmap = None
            self._anim.stop()
            self._alpha = 1.0
        else:
            size = self.SIZE
            scaled = pixmap.scaled(
                size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
            )
            self._pixmap = scaled.copy((scaled.width() - size) // 2, (scaled.height() - size) // 2, size, size)
            self._anim.stop()
            if self.isVisible():  # fade the new cover in
                self._anim.setStartValue(0.0)
                self._anim.setEndValue(1.0)
                self._anim.start()
            else:
                self._alpha = 1.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), self.RADIUS, self.RADIUS)
        painter.setClipPath(clip)
        painter.fillRect(self.rect(), QColor(255, 255, 255, 40))
        if self._pixmap is not None:
            painter.setOpacity(self._alpha)
            painter.drawPixmap(0, 0, self._pixmap)
        else:
            draw_icon(painter, QRectF(self.rect()), "music_note", "♪", 32, Theme.TEXT_FAINT)


class SeekSlider(QWidget):
    """Thin seek line with a knob. Emits `seek_released` only on mouse release (no command spam)."""

    seek_released = pyqtSignal(float)  # fraction 0..1
    fraction_changed = pyqtSignal(float)  # while dragging, for the elapsed label

    KNOB = 5.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(14)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fraction = 0.0
        self._dragging = False

    @property
    def dragging(self) -> bool:
        return self._dragging

    def set_fraction(self, fraction: float) -> None:
        fraction = max(0.0, min(1.0, fraction))
        if not self._dragging and abs(fraction - self._fraction) > 1e-4:
            self._fraction = fraction
            self.update()

    def _fraction_at(self, x: float) -> float:
        span = max(1.0, self.width() - 2 * self.KNOB)
        return max(0.0, min(1.0, (x - self.KNOB) / span))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._dragging = True
            self._fraction = self._fraction_at(event.position().x())
            self.fraction_changed.emit(self._fraction)
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._fraction = self._fraction_at(event.position().x())
            self.fraction_changed.emit(self._fraction)
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.seek_released.emit(self._fraction)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, centre = float(self.width()), self.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 70))
        painter.drawRoundedRect(QRectF(0, centre - 1.5, width, 3), 1.5, 1.5)
        if self.isEnabled():
            x = self.KNOB + (width - 2 * self.KNOB) * self._fraction
            painter.setBrush(QColor(255, 255, 255, 235))
            painter.drawRoundedRect(QRectF(0, centre - 1.5, x, 3), 1.5, 1.5)
            painter.drawEllipse(QPointF(x, centre), self.KNOB, self.KNOB)


class ControlButton(QAbstractButton):
    """Round transport button; `filled` is the white play/pause disc."""

    def __init__(
        self, icon: str, fallback: str, size: int = 30, *, filled: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._icon = icon
        self._fallback = fallback
        self._size = size
        self._filled = filled
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = HoverTracker(self)

    def set_icon(self, icon: str, fallback: str) -> None:
        if (icon, fallback) != (self._icon, self._fallback):
            self._icon, self._fallback = icon, fallback
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.35)
        hover = self._hover.value
        disc = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        if self._filled:
            painter.setBrush(mix(QColor(255, 255, 255, 222), QColor(255, 255, 255, 255), hover))
            painter.drawEllipse(disc)
            color = QColor("#1B0B2E")
        else:
            alpha = 46 * hover + (30 if self.isDown() else 0)
            if alpha > 1:
                painter.setBrush(QColor(255, 255, 255, int(alpha)))
                painter.drawEllipse(disc)
            color = Theme.TEXT
        draw_icon(painter, QRectF(self.rect()), self._icon, self._fallback, int(self._size * 0.62), color)


# ------------------------------------------------------------------------ the pill


class MediaPill(Pill):
    HEIGHT = 148
    POLL_MS = 1000
    TICK_MS = 250

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self._media = MediaController(self)
        self._art = ArtLoader(self)
        self._art_url = ""
        self._has_track = False
        self._playing = False
        self._length_us = 0
        self._pos_us = 0.0
        self._stamp = time.monotonic()
        self._seek_quiet_until = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(Theme.PILL_PADDING, 12, Theme.PILL_PADDING, 12)
        root.setSpacing(8)
        root.addWidget(make_label("Media Player", Theme.TITLE_PT, bold=True))

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        self._thumb = Thumbnail()
        body.addWidget(self._thumb, 0, Qt.AlignmentFlag.AlignVCenter)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        self._status = ElidedLabel("Nothing playing", Theme.SMALL_PT, color=Theme.TEXT_DIM)
        self._title = ElidedLabel("No media", Theme.BODY_PT, bold=True)
        self._seek = SeekSlider()
        self._elapsed = make_label("0:00", Theme.SMALL_PT, color=Theme.TEXT_DIM)
        self._elapsed.setFixedWidth(40)
        self._total = make_label("--:--", Theme.SMALL_PT, color=Theme.TEXT_DIM, align=Qt.AlignmentFlag.AlignRight)
        self._total.setFixedWidth(40)
        self._prev = ControlButton("skip_previous", "⏮", 30)
        self._play = ControlButton("play_arrow", "▶", 36, filled=True)
        self._next = ControlButton("skip_next", "⏭", 30)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        controls.addWidget(self._elapsed, 0, Qt.AlignmentFlag.AlignVCenter)
        controls.addStretch(1)
        for button in (self._prev, self._play, self._next):
            controls.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        controls.addStretch(1)
        controls.addWidget(self._total, 0, Qt.AlignmentFlag.AlignVCenter)

        column.addStretch(1)
        column.addWidget(self._status)
        column.addWidget(self._title)
        column.addWidget(self._seek)
        column.addLayout(controls)
        column.addStretch(1)
        body.addLayout(column, 1)
        root.addLayout(body, 1)

        self._prev.clicked.connect(self._media.previous)
        self._play.clicked.connect(self._media.play_pause)
        self._next.clicked.connect(self._media.next)
        self._seek.seek_released.connect(self._on_seek)
        self._seek.fraction_changed.connect(self._on_drag)
        self._media.updated.connect(self._on_update)
        self._art.loaded.connect(self._on_art)

        # Poll once a second and tick the progress bar four times a second, only while visible.
        self._poll = QTimer(self)
        self._poll.setInterval(self.POLL_MS)
        self._poll.timeout.connect(self._media.poll)
        self._tick = QTimer(self)
        self._tick.setInterval(self.TICK_MS)
        self._tick.timeout.connect(self._refresh_progress)

        self._show_empty()
        if not self._media.available:
            self._status.setText("playerctl is not installed")
            self._title.setText("sudo pacman -S playerctl")

    # -- state
    def _show_empty(self) -> None:
        self._has_track = False
        self._playing = False
        self._length_us = 0
        self._pos_us = 0.0
        self._art_url = ""
        self._status.setText("Nothing playing")
        self._title.setText("No media")
        self._thumb.set_pixmap(None)
        self._play.set_icon("play_arrow", "▶")
        for widget in (self._prev, self._play, self._next, self._seek):
            widget.setEnabled(False)
        self._refresh_progress()

    def _on_update(self, track: Track | None) -> None:
        if track is None:
            if self._media.available:
                self._show_empty()
            return
        now = time.monotonic()
        self._has_track = True
        self._playing = track.status == "Playing"
        self._status.setText(status_line(track))
        self._title.setText(track.title or "Unknown title")
        self._play.set_icon(*(("pause", "⏸") if self._playing else ("play_arrow", "▶")))
        for widget in (self._prev, self._play, self._next):
            widget.setEnabled(True)
        if track.art_url != self._art_url:
            self._art_url = track.art_url
            self._thumb.set_pixmap(self._art.get(track.art_url))  # None until a download finishes
        self._length_us = track.length_us
        if now >= self._seek_quiet_until and not self._seek.dragging and track.position_us >= 0:
            self._pos_us = float(track.position_us)
            self._stamp = now
        self._refresh_progress()

    def _on_art(self, url: str, pixmap: QPixmap) -> None:
        if url == self._art_url:
            self._thumb.set_pixmap(pixmap)

    def _position_now(self) -> float:
        position = self._pos_us + ((time.monotonic() - self._stamp) * 1e6 if self._playing else 0.0)
        if self._length_us > 0:
            position = min(position, float(self._length_us))
        return max(0.0, position)

    def _refresh_progress(self) -> None:
        position = self._position_now()
        has_length = self._length_us > 0
        self._seek.setEnabled(self._has_track and has_length)
        self._total.setText(fmt_time(self._length_us) if has_length else "--:--")
        if not self._seek.dragging:
            self._elapsed.setText(fmt_time(position))
            self._seek.set_fraction(position / self._length_us if has_length else 0.0)

    # -- seeking
    def _on_drag(self, fraction: float) -> None:
        self._elapsed.setText(fmt_time(fraction * self._length_us))

    def _on_seek(self, fraction: float) -> None:
        if self._length_us <= 0:
            return
        now = time.monotonic()
        self._pos_us = fraction * self._length_us
        self._stamp = now
        self._seek_quiet_until = now + 0.8  # ignore stale positions from polls already in flight
        self._media.seek(self._pos_us / 1e6)
        self._refresh_progress()

    # -- visibility
    def showEvent(self, event) -> None:
        self._media.poll()
        self._poll.start()
        self._tick.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._poll.stop()
        self._tick.stop()
        super().hideEvent(event)


def create_pill(services: dict) -> QWidget:
    """Entry point used by main.py."""
    return MediaPill()
