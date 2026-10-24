"""
start_main_menu.py - Start menu UI

Screens (one layer window, slide-fade between them):
  home   : header, search, Pinned apps (6x2, user chosen), Continue with (2x2), user pill
  editor : editor_apps_pinned.PinnedEditor (opened with the pencil icon)
  search : search.SearchScreen (opened with the search bar)
  all    : apps_all_menu.AllAppsScreen (opened with "See all")

Data files (created automatically) in ~/.config/better-hyprland/sm/ :
  pinned.json  - ids of pinned apps
  recent.json  - apps launched from this menu (for "Continue with")
"""
import configparser
import getpass
import glob
import json
import os
import shlex
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import unquote, urlparse

from PyQt6.QtCore import (
    Qt, QAbstractAnimation, QEasingCurve, QMimeDatabase, QParallelAnimationGroup, QPoint,
    QPropertyAnimation, QRectF, QSize, QTimer, QVariantAnimation, pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QMovie, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel,
    QSizePolicy, QVBoxLayout, QWidget,
)

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
DRY_RUN = False  # True = power / log out buttons only print the command (safe for testing)

CONFIG_DIR = os.path.expanduser("~/.config/better-hyprland")
SM_DIR = os.path.join(CONFIG_DIR, "sm")
PINNED_FILE = os.path.join(SM_DIR, "pinned.json")
RECENT_FILE = os.path.join(SM_DIR, "recent.json")
XBEL_FILE = os.path.expanduser("~/.local/share/recently-used.xbel")

ICON_THEME = "Papirus"          # package: papirus-icon-theme
FONT_TEXT = "Google Sans Flex 9pt"
FONT_ICON = "Material Symbols Outlined"

MENU_WIDTH = 640
MENU_RADIUS = 30
LEFT_MARGIN = 12         # gap from the left screen edge
BOTTOM_MARGIN = 60       # gap above your bottom bar
GIF_SIZE = 60
PINNED_COLS, PINNED_ROWS = 6, 2
RECENT_COLS, RECENT_ROWS = 2, 2
MAX_PINNED = PINNED_COLS * PINNED_ROWS
RECENT_MAX_AGE = 12 * 3600       # "Continue with" shows up to 12 hours
TILE_H = 96
RECENT_H = 54

BASE = (105, 54, 82)                      # #693652
CARD_BG = QColor(*BASE, 51)               # 0.2
FILL_HEADER = QColor(*BASE, 102)          # 0.4
FILL_HALF = QColor(*BASE, 128)            # 0.5  search bar, app circles
FILL_LIST = QColor(*BASE, 178)            # 0.7  editor list panel
FILL_STRONG = QColor(*BASE, 235)          # power buttons, See all
WHITE = QColor(255, 255, 255)
WHITE_DIM = QColor(255, 255, 255, 190)
HOVER = QColor(255, 255, 255, 28)
AVATAR = QColor("cyan")
RED = QColor(255, 99, 99)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def mkfont(px, bold=False, icon=False):
    f = QFont(FONT_ICON if icon else FONT_TEXT)
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def draw_text(p, rect, txt, px, bold=False, color=WHITE,
              align=Qt.AlignmentFlag.AlignCenter, icon=False):
    font = mkfont(px, bold, icon)
    p.setFont(font)
    p.setPen(color)
    if not icon:
        txt = QFontMetrics(font).elidedText(txt, Qt.TextElideMode.ElideRight, int(rect.width()))
    p.drawText(rect, int(align), txt)


def wrap2(text, font, width):
    """Greedy word-wrap into at most 2 lines (last line elided)."""
    fm = QFontMetrics(font)
    words = text.split()
    lines, cur = [], ""
    for i, w in enumerate(words):
        trial = f"{cur} {w}".strip()
        if cur and fm.horizontalAdvance(trial) > width:
            lines.append(cur)
            cur = " ".join(words[i:])
            break
        cur = trial
    lines.append(cur)
    return [fm.elidedText(l, Qt.TextElideMode.ElideRight, int(width)) for l in lines[:2]]


def clear_layout(layout):
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()


def run_cmd(cmd):
    if DRY_RUN:
        print("[dry-run]", " ".join(cmd))
        return
    subprocess.Popen(cmd, start_new_session=True)


def open_py(path):
    path = os.path.expanduser(path)
    if os.path.exists(path):
        _spawn(["python3", path])
    else:
        print(f"[todo] not created yet: {path}")


def ordinal(n):
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def greeting_for(now):
    """Returns (text, gif filename) from the system time ranges in the spec."""
    t = now.hour * 60 + now.minute
    if 4 * 60 + 1 <= t <= 8 * 60:
        return "Early bird rised!", "sunrise.gif"
    if 8 * 60 + 1 <= t <= 17 * 60:
        return "It's Daytime!", "day.gif"
    if 17 * 60 + 1 <= t <= 19 * 60:
        return "Evening vibes!", "sunset.gif"
    return "Nightly tunes!!", "night.gif"


# ---- icons ---------------------------------------------------------------
def setup_icon_theme():
    """Use Papirus if installed (sudo pacman -S papirus-icon-theme)."""
    # Flatpak app icons live outside the normal icon folders
    paths = QIcon.themeSearchPaths()
    for base in _flatpak_share_dirs():
        d = os.path.join(base, "icons")
        if os.path.isdir(d) and d not in paths:
            paths.append(d)
    QIcon.setThemeSearchPaths(paths)
    dirs = ["/usr/share/icons", os.path.expanduser("~/.local/share/icons"), os.path.expanduser("~/.icons")]
    if any(os.path.isdir(os.path.join(d, ICON_THEME)) for d in dirs):
        QIcon.setThemeName(ICON_THEME)
    else:
        print(f"[info] {ICON_THEME} icon theme not found, using the system theme")


def load_icon(name, fallback="application-x-executable"):
    icon = QIcon()
    if name:
        if os.path.isabs(name) and os.path.exists(name):
            icon = QIcon(name)
        else:
            icon = QIcon.fromTheme(name)
    if icon.isNull() and fallback:
        icon = QIcon.fromTheme(fallback)
    return icon


def icon_pixmap(icon, side, widget):
    """Icon rendered at its REAL on-screen resolution (side x UI scale), so it stays crisp at
    any scale. A plain icon.pixmap(QSize) is 1x and gets resampled -> jagged edges at 0.9x etc."""
    return icon.pixmap(QSize(side, side), widget.devicePixelRatioF())


# ---- installed apps ------------------------------------------------------
_APPS = None
_APP_MAP = {}


def _flatpak_share_dirs():
    """Where Flatpak exports its .desktop files and icons (system + user installs)."""
    return ["/var/lib/flatpak/exports/share",
            os.path.expanduser("~/.local/share/flatpak/exports/share")]


def app_dirs():
    """Every folder that can hold .desktop files: XDG dirs + Flatpak + Snap (user dir last = overrides)."""
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    data_dirs = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    bases = data_dirs + ["/usr/share"] + _flatpak_share_dirs() + [data_home]
    out = []
    for b in bases:
        d = os.path.join(b, "applications")
        if b and d not in out and os.path.isdir(d):
            out.append(d)
    if os.path.isdir("/var/lib/snapd/desktop/applications") and "/var/lib/snapd/desktop/applications" not in out:
        out.append("/var/lib/snapd/desktop/applications")
    return out


def all_apps(force=False):
    """All launchable apps as dicts: id, name, icon, exec (sorted by name)."""
    global _APPS, _APP_MAP
    if _APPS is not None and not force:
        return _APPS
    dirs = app_dirs()
    found = {}
    for d in dirs:
        for path in glob.glob(os.path.join(d, "*.desktop")):
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            cp.optionxform = str
            try:
                cp.read(path, encoding="utf-8")
            except Exception:
                continue
            if "Desktop Entry" not in cp:
                continue
            e = cp["Desktop Entry"]
            if e.get("Type") != "Application":
                continue
            if e.get("NoDisplay", "false").lower() == "true" or e.get("Hidden", "false").lower() == "true":
                continue
            name = e.get("Name")
            if name:
                app_id = os.path.basename(path)
                found[app_id] = {"id": app_id, "name": name, "icon": e.get("Icon", ""),
                                 "exec": e.get("Exec", "")}
    _APPS = sorted(found.values(), key=lambda a: a["name"].lower())
    _APP_MAP = found
    return _APPS


def app_by_id(app_id):
    all_apps()
    return _APP_MAP.get(app_id)


# ---- pinned apps (stored as ids in pinned.json; none by default) ---------
def load_pinned():
    try:
        with open(PINNED_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return [x for x in data if isinstance(x, str)]
    except Exception:
        return []


def save_pinned(ids):
    try:
        os.makedirs(SM_DIR, exist_ok=True)
        with open(PINNED_FILE, "w", encoding="utf-8") as f:
            json.dump(ids, f, indent=2)
    except Exception as ex:
        print("[warn] could not save pinned apps:", ex)


# ---- recent apps / files -------------------------------------------------
def _load_launches():
    try:
        with open(RECENT_FILE, encoding="utf-8") as f:
            return [e for e in json.load(f) if isinstance(e, dict)]
    except Exception:
        return []


def record_launch(app):
    entries = [e for e in _load_launches() if e.get("id") != app["id"]]
    entries.insert(0, {"id": app["id"], "name": app["name"], "icon": app.get("icon", ""),
                       "exec": app.get("exec", ""), "ts": time.time()})
    try:
        os.makedirs(SM_DIR, exist_ok=True)
        with open(RECENT_FILE, "w", encoding="utf-8") as f:
            json.dump(entries[:50], f, indent=2)
    except Exception as ex:
        print("[warn] could not save recent apps:", ex)


def _parse_iso(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


_MIME = None


def _file_icon_name(path):
    global _MIME
    if _MIME is None:
        _MIME = QMimeDatabase()
    mt = _MIME.mimeTypeForFile(path)
    return mt.iconName() or mt.genericIconName() or "text-x-generic"


def _recent_files(now):
    out = []
    try:
        root = ET.parse(XBEL_FILE).getroot()
    except Exception:
        return out
    for bm in root.iter("bookmark"):
        href = bm.get("href", "")
        if not href.startswith("file://"):
            continue
        ts = _parse_iso(bm.get("visited") or bm.get("modified") or "")
        if ts is None or now - ts > RECENT_MAX_AGE:
            continue
        path = unquote(urlparse(href).path)
        if not os.path.exists(path):
            continue
        out.append({"kind": "file", "id": path, "name": os.path.basename(path),
                    "icon": _file_icon_name(path), "exec": "", "ts": ts})
    return out


def get_recents(limit=RECENT_COLS * RECENT_ROWS):
    """Apps launched from this menu + recently used files, newest first, up to 12 hours old."""
    now = time.time()
    items = []
    for e in _load_launches():
        ts = e.get("ts", 0)
        if now - ts <= RECENT_MAX_AGE and e.get("id"):
            items.append({"kind": "app", "id": e["id"], "name": e.get("name", e["id"]),
                          "icon": e.get("icon", ""), "exec": e.get("exec", ""), "ts": ts})
    items += _recent_files(now)
    items.sort(key=lambda i: i["ts"], reverse=True)
    seen, out = set(), []
    for it in items:
        key = (it["kind"], it["id"])
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out[:limit]


def ago(ts):
    m = max(0, int(time.time() - ts)) // 60
    if m < 1:
        return "Just now"
    if m < 60:
        return f"{m} min{'s' if m != 1 else ''} ago"
    h = m // 60
    return f"{h} hour{'s' if h != 1 else ''} ago"


# ---- launching -----------------------------------------------------------
LOG_FILE = os.path.expanduser("~/.cache/better-hyprland/start-menu.log")
# set by main.py for the menu itself - must NOT leak into the apps we start
# (a Qt app such as Dolphin would try to become a layer-shell surface and fail to open)
_MENU_ONLY_ENV = ("QT_WAYLAND_SHELL_INTEGRATION", "QT_QPA_PLATFORM", "SM_DETACHED")
_FLATPAK_MARKERS = {"@@", "@@u", "@@f"}      # file-forwarding markers in flatpak Exec lines


def child_env():
    """Environment for launched apps = ours without the menu-only variables."""
    env = dict(os.environ)
    for key in _MENU_ONLY_ENV:
        env.pop(key, None)
    return env


def _spawn(cmd):
    """Start a program detached with a clean environment; its output goes to the log file."""
    log = None
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        log = open(LOG_FILE, "a")
        log.write(f"\n[launch] {datetime.now():%Y-%m-%d %H:%M:%S} {shlex.join(cmd)}\n")
        log.flush()
    except OSError:
        log = None
    try:
        subprocess.Popen(cmd, start_new_session=True, env=child_env(),
                         stdin=subprocess.DEVNULL,
                         stdout=log or subprocess.DEVNULL, stderr=log or subprocess.DEVNULL)
        return True
    except OSError as ex:
        print(f"[warn] could not start {cmd[0]}: {ex}")
        return False
    finally:
        if log:
            log.close()


def launch_app(app):
    try:
        parts = [p for p in shlex.split(app.get("exec", ""))
                 if p not in _FLATPAK_MARKERS and not (p.startswith("%") and len(p) == 2)]
    except ValueError:
        parts = []
    if parts and _spawn(parts):
        record_launch(app)


def open_file(path):
    _spawn(["xdg-open", path])


# ---- users ---------------------------------------------------------------
def other_users():
    me = getpass.getuser()
    users = []
    try:
        with open("/etc/passwd", encoding="utf-8") as f:
            for line in f:
                p = line.strip().split(":")
                if len(p) < 7:
                    continue
                try:
                    uid = int(p[2])
                except ValueError:
                    continue
                if 1000 <= uid < 60000 and p[0] != me and not p[6].endswith(("nologin", "false")):
                    users.append(p[0])
    except OSError:
        pass
    return users


def switch_user(name):
    if shutil.which("dm-tool"):          # LightDM only
        run_cmd(["dm-tool", "switch-to-user", name])
    else:
        print(f"[todo] switch to user '{name}' (depends on your display manager)")


def log_out():
    run_cmd(["hyprctl", "dispatch", "hl.dsp.exit()"])      # Hyprland 0.55+ (Lua) syntax


# --------------------------------------------------------------------------
# Pressable base: zoom-out-and-in click animation for every clickable item
# --------------------------------------------------------------------------
class Pressable(QWidget):
    clicked = pyqtSignal()
    PRESS_SCALE = 0.90

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scale = 1.0
        self._down = False
        self._hover = False
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._set_scale)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _set_scale(self, v):
        self._scale = float(v)
        self.update()

    def _animate_to(self, target, ms, curve):
        self._anim.stop()
        self._anim.setStartValue(self._scale)
        self._anim.setEndValue(target)
        self._anim.setDuration(ms)
        self._anim.setEasingCurve(curve)
        self._anim.start()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._down = True
            self._animate_to(self.PRESS_SCALE, 90, QEasingCurve.Type.OutCubic)   # zoom out

    def mouseReleaseEvent(self, e):
        if not self._down:
            return
        self._down = False
        self._animate_to(1.0, 240, QEasingCurve.Type.OutBack)                   # zoom back in
        if self.rect().contains(e.position().toPoint()):
            QTimer.singleShot(130, self.clicked.emit)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        c = QRectF(self.rect()).center()
        p.translate(c)
        p.scale(self._scale, self._scale)
        p.translate(-c)
        self.draw(p)

    def draw(self, p):
        raise NotImplementedError

    def text(self, p, rect, txt, px, **kw):
        draw_text(p, rect, txt, px, **kw)


class IconButton(Pressable):
    def __init__(self, glyph, size=34, filled=True, fill=FILL_STRONG, parent=None):
        super().__init__(parent)
        self.glyph, self.filled, self.fill = glyph, filled, fill
        self.setFixedSize(size, size)

    def draw(self, p):
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.filled:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.fill)
            p.drawEllipse(r)
        elif self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(HOVER)
            p.drawEllipse(r)
        self.text(p, r, self.glyph, int(r.width() * 0.6), icon=True)


class SearchBar(Pressable):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def draw(self, p):
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(FILL_HALF)                       # #693652 @ 0.5, no border
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        self.text(p, QRectF(r.left() + 8, r.top(), 28, r.height()), "search", 24, icon=True)
        self.text(p, QRectF(r.left() + 44, r.top(), r.width() - 56, r.height()),
                  "Type here to search apps", 13, color=WHITE_DIM,
                  align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)


class SeeAllButton(Pressable):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(96, 30)

    def draw(self, p):
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(FILL_STRONG)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        self.text(p, QRectF(r.left() + 12, r.top(), 56, r.height()), "See all", 12, bold=True,
                  align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.text(p, QRectF(r.right() - 30, r.top(), 24, r.height()), "chevron_right", 20, icon=True)


class AppTile(Pressable):
    """Pinned app: icon on a #693652 @0.5 circle, name in up to 2 lines."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.icon = load_icon(app["icon"])
        self.setFixedHeight(TILE_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def draw(self, p):
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(HOVER)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(4, 0, -4, 0), 14, 14)
        d = 50
        circle = QRectF((self.width() - d) / 2, 4, d, d)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(FILL_HALF)
        p.drawEllipse(circle)
        if not self.icon.isNull():
            pm = icon_pixmap(self.icon, 32, self)
            p.drawPixmap(int(circle.center().x() - 16), int(circle.center().y() - 16), pm)
        else:
            self.text(p, circle, (self.app["name"][:1] or "?").upper(), 22, bold=True)
        font = mkfont(11)
        for i, line in enumerate(wrap2(self.app["name"], font, self.width() - 8)):
            self.text(p, QRectF(4, 58 + i * 15, self.width() - 8, 15), line, 11, color=WHITE_DIM)


class RecentItem(Pressable):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item
        self.icon = load_icon(item["icon"], "text-x-generic" if item["kind"] == "file" else "application-x-executable")
        self.setFixedHeight(RECENT_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def draw(self, p):
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(HOVER)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(2, 0, -2, 0), 14, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(FILL_HALF)
        circle = QRectF(10, 4, 46, 46)
        p.drawEllipse(circle)
        if not self.icon.isNull():
            pm = icon_pixmap(self.icon, 28, self)
            p.drawPixmap(int(circle.center().x() - 14), int(circle.center().y() - 14), pm)
        left = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        self.text(p, QRectF(68, 6, self.width() - 76, 24), self.item["name"], 14, align=left)
        self.text(p, QRectF(68, 28, self.width() - 76, 18), ago(self.item["ts"]), 11,
                  color=WHITE_DIM, align=left)


class EmptyNote(QWidget):
    """Centered placeholder text (no apps pinned / no recents)."""

    def __init__(self, text, bold=False, alpha=170, parent=None):
        super().__init__(parent)
        self.txt, self.bold, self.alpha = text, bold, alpha

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        draw_text(p, QRectF(self.rect()), self.txt, 14, bold=self.bold,
                  color=QColor(255, 255, 255, self.alpha))


class UserPill(Pressable):
    def __init__(self, username, parent=None):
        super().__init__(parent)
        self.username = username
        self.open = False
        self.setFixedSize(210, 44)

    def draw(self, p):
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(FILL_HEADER)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        av = QRectF(r.left() + 6, r.top() + 5, 32, 32)
        p.setBrush(AVATAR)
        p.drawEllipse(av)
        self.text(p, av, (self.username[:1] or "?").upper(), 17, bold=True, color=QColor(20, 20, 20))
        left = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        self.text(p, QRectF(av.right() + 10, r.top(), 110, r.height()), self.username, 14, bold=True, align=left)
        self.text(p, QRectF(r.right() - 34, r.top(), 28, r.height()),
                  "expand_less" if self.open else "expand_more", 24, icon=True)


class PopupRow(Pressable):
    """Row in the user popup: a user, or the red Log Out."""
    PRESS_SCALE = 0.96

    def __init__(self, label, glyph=None, letter=None, color=WHITE, parent=None):
        super().__init__(parent)
        self.label, self.glyph, self.letter, self.color = label, glyph, letter, color
        self.setFixedHeight(38)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def draw(self, p):
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(HOVER)
            p.drawRoundedRect(QRectF(self.rect()), 12, 12)
        left = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        icon_rect = QRectF(8, 5, 28, 28)
        if self.letter:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(AVATAR)
            p.drawEllipse(icon_rect)
            self.text(p, icon_rect, self.letter.upper(), 14, bold=True, color=QColor(20, 20, 20))
        elif self.glyph:
            self.text(p, icon_rect, self.glyph, 22, icon=True, color=self.color)
        self.text(p, QRectF(46, 0, self.width() - 54, self.height()), self.label, 14,
                  bold=self.glyph is not None, color=self.color, align=left)


class UserPopup(QWidget):
    """Opens above the user pill: other users (or a note) and a red Log Out."""
    switch_requested = pyqtSignal(str)
    logout_requested = pyqtSignal()
    WIDTH = 220

    def __init__(self, users, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(2)
        if users:
            for u in users:
                row = PopupRow(u, letter=u[:1])
                row.clicked.connect(lambda name=u: self.switch_requested.emit(name))
                lay.addWidget(row)
        else:
            note = EmptyNote("No another users found", bold=False, alpha=170)
            note.setFixedHeight(38)
            lay.addWidget(note)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(255,255,255,45); border: none;")
        lay.addWidget(line)
        out = PopupRow("Log Out", glyph="logout", color=RED)
        out.clicked.connect(self.logout_requested.emit)
        lay.addWidget(out)
        self.resize(self.WIDTH, self.sizeHint().height())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 20, 20)
        p.fillPath(path, FILL_LIST)

    def mousePressEvent(self, e):
        e.accept()      # don't let clicks on the panel close it


# --------------------------------------------------------------------------
# Small non-clickable pieces
# --------------------------------------------------------------------------
def make_label(px, bold=False, alpha=255, rich=False):
    lab = QLabel()
    lab.setFont(mkfont(px, bold))
    lab.setStyleSheet(f"color: rgba(255,255,255,{alpha}); background: transparent;")
    if rich:
        lab.setTextFormat(Qt.TextFormat.RichText)
    return lab


def make_icon_label(glyph, px):
    lab = QLabel(glyph)
    lab.setFont(mkfont(px, icon=True))
    lab.setStyleSheet("color: white; background: transparent;")
    return lab


class GifBox(QLabel):
    """
    Renders the custom greeting GIF; shows a grey placeholder if the file is missing.

    Every frame is scaled ONCE, smoothly, to the real on-screen size (box size x the UI scale),
    so it stays crisp at any scale (0.9, 1.0, 2.8 ...). Scaling twice (QMovie.setScaledSize and
    then Qt's own scaling) is what made it look jagged on small / odd sizes.
    """

    def __init__(self, size):
        super().__init__()
        self.size_px = size
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.movie = None
        self._frames = {}
        self.set_placeholder()

    def set_placeholder(self):
        self.setStyleSheet("background: rgba(220,220,220,220); border-radius: 6px;")

    def set_gif(self, path):
        path = os.path.expanduser(path)
        if self.movie:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None
        self._frames = {}
        if not os.path.exists(path):
            self.clear()
            self.set_placeholder()
            return
        self.setStyleSheet("background: transparent;")
        self.movie = QMovie(path)
        self.movie.setCacheMode(QMovie.CacheMode.CacheAll)      # decode each frame only once
        self.movie.frameChanged.connect(self._show_frame)
        self.movie.start()

    def _show_frame(self, n):
        dpr = self.devicePixelRatioF()                          # includes the UI scale factor
        key = (n, round(dpr, 3))
        pm = self._frames.get(key)
        if pm is None:
            side = max(1, round(self.size_px * dpr))            # real pixels on screen
            img = self.movie.currentImage().scaled(
                side, side, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(dpr)                         # drawn 1:1, no second resampling
            self._frames[key] = pm
        self.setPixmap(pm)


class Card(QWidget):
    """The rounded #693652 @ 0.2 body. Blur comes from the Hyprland layer rule."""

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), MENU_RADIUS, MENU_RADIUS)
        p.fillPath(path, CARD_BG)


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------
class StartMainMenu(QWidget):
    SLIDE_DISTANCE = 90      # opening animation
    SWAP_DISTANCE = 44       # home <-> editor slide-fade

    def __init__(self, overlay=True):
        """
        overlay=True : window = transparent full-screen layer surface, card sits
                       bottom-left inside it, click outside closes.
        overlay=False: window = just the card (plain window, for quick UI checks).
        """
        super().__init__()
        self.overlay = overlay
        self.username = getpass.getuser()
        self.screens = {}
        self.active_screen = None
        self.popup = None
        self._busy = False
        self._closing = False
        self._last_minute = -1
        setup_icon_theme()

        self.setWindowTitle("start-menu")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)

        self.card = Card(self)
        self.home_view = QWidget(self.card)

        root = QVBoxLayout(self.home_view)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(0)
        root.addLayout(self._build_header())
        root.addSpacing(12)
        root.addLayout(self._build_search_row())
        root.addSpacing(12)
        root.addLayout(self._build_section("keep", "Pinned", on_edit=self.show_editor))
        root.addWidget(self._build_pinned_box())
        root.addSpacing(6)
        root.addLayout(self._build_section("schedule", "Continue with"))
        root.addWidget(self._build_recent_box())
        root.addSpacing(8)
        root.addLayout(self._build_footer())

        h = self.home_view.sizeHint().height()
        if self.overlay:
            screen = QApplication.primaryScreen().geometry()
            self.setFixedSize(screen.width(), screen.height())
            self.rest_pos = QPoint(LEFT_MARGIN, screen.height() - h - BOTTOM_MARGIN)
        else:
            self.setFixedSize(MENU_WIDTH, h)
            self.rest_pos = QPoint(0, 0)
        self.card.setGeometry(self.rest_pos.x(), self.rest_pos.y(), MENU_WIDTH, h)
        self.home_view.setGeometry(0, 0, MENU_WIDTH, h)

        self.refresh_pinned()
        self.refresh_recent()

        self.clock = QTimer(self)
        self.clock.timeout.connect(self.refresh_time)
        self.clock.start(1000)
        self.refresh_time()

    # ---- builders --------------------------------------------------------
    def _build_header(self):
        row = QHBoxLayout()
        row.setSpacing(12)

        self.gif = GifBox(GIF_SIZE)
        row.addWidget(self.gif, 0, Qt.AlignmentFlag.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(0)
        self.greet = make_label(18, bold=True)
        self.hey = make_label(13, alpha=220)
        self.hey.setText(f"Hey {self.username}")
        col.addStretch()
        col.addWidget(self.greet)
        col.addWidget(self.hey)
        col.addStretch()
        row.addLayout(col)
        row.addStretch()

        buttons = [
            ("settings", lambda: open_py("~/.config/better-hyprland/app_settings.py")),
            ("refresh", lambda: run_cmd(["systemctl", "reboot"])),
            ("bedtime", lambda: run_cmd(["systemctl", "suspend"])),
            ("power_settings_new", lambda: run_cmd(["systemctl", "poweroff"])),
        ]
        for glyph, cb in buttons:
            b = IconButton(glyph, 34)
            b.clicked.connect(cb)
            row.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(10)

        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        self.time_label = make_label(19, bold=True)
        self.date_label = make_label(12, alpha=220, rich=True)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        tcol.addStretch()
        tcol.addWidget(self.time_label)
        tcol.addWidget(self.date_label)
        tcol.addStretch()
        row.addLayout(tcol)
        return row

    def _build_search_row(self):
        row = QHBoxLayout()
        row.setSpacing(12)
        search = SearchBar()
        search.clicked.connect(self.show_search)
        see_all = SeeAllButton()
        see_all.clicked.connect(self.show_all_apps)
        row.addWidget(search, 1)
        row.addWidget(see_all, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _build_section(self, glyph, title, on_edit=None):
        row = QHBoxLayout()
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(8)
        row.addWidget(make_icon_label(glyph, 24))
        lab = make_label(14, bold=True)
        lab.setText(title)
        row.addWidget(lab)
        row.addStretch()
        if on_edit:
            b = IconButton("edit", 28, filled=False)
            b.clicked.connect(on_edit)
            row.addWidget(b)
        return row

    def _build_pinned_box(self):
        self.pinned_box = QWidget()
        self.pinned_box.setFixedHeight(PINNED_ROWS * TILE_H)
        self.pinned_grid = QGridLayout(self.pinned_box)
        self.pinned_grid.setContentsMargins(0, 6, 0, 0)
        self.pinned_grid.setSpacing(0)
        for c in range(PINNED_COLS):
            self.pinned_grid.setColumnStretch(c, 1)
        return self.pinned_box

    def _build_recent_box(self):
        self.recent_box = QWidget()
        self.recent_box.setFixedHeight(RECENT_ROWS * RECENT_H + 4)
        self.recent_grid = QGridLayout(self.recent_box)
        self.recent_grid.setContentsMargins(0, 6, 0, 0)
        self.recent_grid.setSpacing(4)
        for c in range(RECENT_COLS):
            self.recent_grid.setColumnStretch(c, 1)
        return self.recent_box

    def _build_footer(self):
        row = QHBoxLayout()
        self.pill = UserPill(self.username)
        self.pill.clicked.connect(self.toggle_user_popup)
        row.addStretch()
        row.addWidget(self.pill)
        row.addStretch()
        return row

    # ---- content refresh ------------------------------------------------
    def refresh_pinned(self):
        clear_layout(self.pinned_grid)
        apps = [a for a in (app_by_id(i) for i in load_pinned()[:MAX_PINNED]) if a]
        if not apps:
            self.pinned_grid.addWidget(EmptyNote("Click Edit to add pinned apps"),
                                       0, 0, PINNED_ROWS, PINNED_COLS)
            return
        for i, app in enumerate(apps):
            tile = AppTile(app)
            tile.clicked.connect(lambda a=app: self.launch(a))
            self.pinned_grid.addWidget(tile, i // PINNED_COLS, i % PINNED_COLS)

    def refresh_recent(self):
        clear_layout(self.recent_grid)
        items = get_recents()
        if not items:
            self.recent_grid.addWidget(
                EmptyNote("There is no recent apps available", bold=True, alpha=128),
                0, 0, RECENT_ROWS, RECENT_COLS)
            return
        for i, it in enumerate(items):
            w = RecentItem(it)
            w.clicked.connect(lambda it=it: self.open_recent(it))
            self.recent_grid.addWidget(w, i // RECENT_COLS, i % RECENT_COLS)

    def launch(self, app):
        launch_app(app)
        self.close_menu()

    def open_recent(self, it):
        if it["kind"] == "file":
            open_file(it["id"])
        else:
            launch_app(it)
        self.close_menu()

    def refresh_time(self):
        now = datetime.now()
        self.time_label.setText(now.strftime("%I:%M %p"))
        self.date_label.setText(
            f"{now.strftime('%a')}, {now.day}<sup>{ordinal(now.day)}</sup> {now.strftime('%B')}"
        )
        text, gif = greeting_for(now)
        if self.greet.text() != text:
            self.greet.setText(text)
            self.gif.set_gif(os.path.join(SM_DIR, gif))
        if now.minute != self._last_minute:       # keep "xx mins ago" fresh
            self._last_minute = now.minute
            self.refresh_recent()

    # ---- user popup -------------------------------------------------------
    def toggle_user_popup(self):
        if self.popup is not None:
            self.hide_user_popup()
            return
        self.popup = UserPopup(other_users(), self.card)
        self.popup.switch_requested.connect(switch_user)
        self.popup.logout_requested.connect(log_out)
        pos = self.pill.mapTo(self.card, QPoint(0, 0))
        x = pos.x() + (self.pill.width() - self.popup.width()) // 2
        y = pos.y() - self.popup.height() - 8
        self.popup.move(x, y + 10)
        self.popup.show()
        self.popup.raise_()
        self.pill.open = True
        self.pill.update()

        eff = QGraphicsOpacityEffect(self.popup)
        self.popup.setGraphicsEffect(eff)
        slide = QPropertyAnimation(self.popup, b"pos", self.popup)
        slide.setDuration(170)
        slide.setStartValue(QPoint(x, y + 10))
        slide.setEndValue(QPoint(x, y))
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade = QPropertyAnimation(eff, b"opacity", self.popup)
        fade.setDuration(170)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        group = QParallelAnimationGroup(self.popup)
        group.addAnimation(slide)
        group.addAnimation(fade)
        popup = self.popup
        group.finished.connect(lambda: popup.setGraphicsEffect(None))
        group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def hide_user_popup(self):
        if self.popup is not None:
            self.popup.hide()
            self.popup.deleteLater()
            self.popup = None
        self.pill.open = False
        self.pill.update()

    # ---- screens ---------------------------------------------------------
    def _get_screen(self, name):
        if name not in self.screens:
            if name == "editor":
                from editor_apps_pinned import PinnedEditor as Screen   # lazy: avoids circular import
            elif name == "all_apps":
                from apps_all_menu import AllAppsScreen as Screen
            else:
                from search import SearchScreen as Screen
            w = Screen(self.card)
            w.back.connect(self.show_home)
            w.setGeometry(0, 0, self.card.width(), self.card.height())
            w.hide()
            self.screens[name] = w
        return self.screens[name]

    def _show_screen(self, name):
        if self._busy:
            return
        self.hide_user_popup()
        w = self._get_screen(name)
        w.reload()
        self.active_screen = w
        self._slide(self.home_view, w, +1)

    def show_editor(self):
        self._show_screen("editor")

    def show_search(self):
        self._show_screen("search")

    def show_all_apps(self):
        self._show_screen("all_apps")

    def show_home(self):
        if self._busy or self.active_screen is None:
            return
        self.refresh_pinned()
        self._slide(self.active_screen, self.home_view, -1)
        self.active_screen = None

    def _slide(self, out_w, in_w, d):
        """slide-fade: out_w drifts away while in_w drifts in from the side."""
        self._busy = True
        dist = self.SWAP_DISTANCE
        eff_out, eff_in = QGraphicsOpacityEffect(out_w), QGraphicsOpacityEffect(in_w)
        out_w.setGraphicsEffect(eff_out)
        in_w.setGraphicsEffect(eff_in)
        eff_in.setOpacity(0.0)
        in_w.move(d * dist, 0)
        in_w.show()
        in_w.raise_()

        group = QParallelAnimationGroup(self)
        specs = [
            (out_w, b"pos", QPoint(0, 0), QPoint(-d * dist, 0)),
            (eff_out, b"opacity", 1.0, 0.0),
            (in_w, b"pos", QPoint(d * dist, 0), QPoint(0, 0)),
            (eff_in, b"opacity", 0.0, 1.0),
        ]
        for target, prop, a, b in specs:
            an = QPropertyAnimation(target, prop, group)
            an.setDuration(240)
            an.setStartValue(a)
            an.setEndValue(b)
            an.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(an)

        def done():
            out_w.hide()
            out_w.move(0, 0)
            out_w.setGraphicsEffect(None)
            in_w.setGraphicsEffect(None)
            self._busy = False

        group.finished.connect(done)
        group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    # ---- opening animation -------------------------------------------------
    def open_menu(self):
        """Opening animation: slide bottom -> up while revealing (fade)."""
        self.refresh_pinned()
        self.refresh_recent()
        start = QPoint(self.rest_pos.x(), self.rest_pos.y() + self.SLIDE_DISTANCE)
        self.card.move(start)
        eff = QGraphicsOpacityEffect(self.card)
        eff.setOpacity(0.0)
        self.card.setGraphicsEffect(eff)
        self.show()

        slide = QPropertyAnimation(self.card, b"pos", self)
        slide.setDuration(320)
        slide.setStartValue(start)
        slide.setEndValue(self.rest_pos)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)

        reveal = QPropertyAnimation(eff, b"opacity", self)
        reveal.setDuration(260)
        reveal.setStartValue(0.0)
        reveal.setEndValue(1.0)
        reveal.setEasingCurve(QEasingCurve.Type.OutQuad)

        self._open_anim = QParallelAnimationGroup(self)
        self._open_anim.addAnimation(slide)
        self._open_anim.addAnimation(reveal)
        self._open_anim.finished.connect(lambda: self.card.setGraphicsEffect(None))
        self._open_anim.start()

    # ---- closing animation -------------------------------------------------
    def close_menu(self):
        """
        Closing animation in two steps:
          1. the elements (everything inside the box) fade out and drift down a little
          2. then the box itself slides down while fading out (mirror of open_menu)
        """
        if self._closing:
            return
        self._closing = True
        self.hide_user_popup()
        QTimer.singleShot(1000, QApplication.quit)     # safety net: never get stuck open

        opening = getattr(self, "_open_anim", None)
        still_opening = (opening is not None
                         and opening.state() == QAbstractAnimation.State.Running)
        if opening is not None:
            opening.stop()                             # still opening: take over from where it is

        # the screen that is showing right now (home, or editor / search / all apps)
        content = self.active_screen if self.active_screen is not None else self.home_view
        if still_opening or self._busy:                # mid-animation: skip step 1, just close the box
            self._close_box(None)
            return

        eff = QGraphicsOpacityEffect(content)
        eff.setOpacity(1.0)
        content.setGraphicsEffect(eff)

        fade = QPropertyAnimation(eff, b"opacity", self)
        fade.setDuration(150)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.Type.InQuad)

        drift = QPropertyAnimation(content, b"pos", self)
        drift.setDuration(150)
        drift.setStartValue(QPoint(0, 0))
        drift.setEndValue(QPoint(0, 10))
        drift.setEasingCurve(QEasingCurve.Type.InQuad)

        self._elements_anim = QParallelAnimationGroup(self)
        self._elements_anim.addAnimation(fade)
        self._elements_anim.addAnimation(drift)
        self._elements_anim.finished.connect(lambda: self._close_box(content))
        self._elements_anim.start()

    def _close_box(self, content):
        """Step 2 of the closing animation: the box slides down + fades out, then quit."""
        if content is not None:
            content.hide()                             # already invisible (opacity 0)
            content.setGraphicsEffect(None)
        old = self.card.graphicsEffect()
        start_opacity = old.opacity() if old is not None else 1.0
        start = self.card.pos()
        end = QPoint(self.rest_pos.x(), self.rest_pos.y() + self.SLIDE_DISTANCE)

        eff = QGraphicsOpacityEffect(self.card)
        eff.setOpacity(start_opacity)
        self.card.setGraphicsEffect(eff)

        slide = QPropertyAnimation(self.card, b"pos", self)
        slide.setDuration(260)
        slide.setStartValue(start)
        slide.setEndValue(end)
        slide.setEasingCurve(QEasingCurve.Type.InCubic)

        fade = QPropertyAnimation(eff, b"opacity", self)
        fade.setDuration(220)
        fade.setStartValue(start_opacity)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.Type.InQuad)

        self._close_anim = QParallelAnimationGroup(self)
        self._close_anim.addAnimation(slide)
        self._close_anim.addAnimation(fade)
        self._close_anim.finished.connect(QApplication.quit)
        self._close_anim.start()

    # ---- input -------------------------------------------------------------
    def mousePressEvent(self, e):
        # only reaches here when nothing inside accepted the click
        if self.popup is not None:
            self.hide_user_popup()
            return
        if self.overlay and not self.card.geometry().contains(e.position().toPoint()):
            self.close_menu()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            if self.popup is not None:
                self.hide_user_popup()
            else:
                self.close_menu()
        else:
            super().keyPressEvent(e)
