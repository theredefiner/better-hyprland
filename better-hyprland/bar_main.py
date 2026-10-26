#!/usr/bin/env python3
"""
Better Hyprland - taskbar            (~/.config/better-hyprland/bar/main.py)

Three pills, one layer-shell surface per monitor:
  pill 1 (left)   : Start button
  pill 2 (middle) : workspaces | RAM / CPU / battery / swap | clock
  pill 3 (right)  : hidden tray chevron | network | notifications

Run:   python ~/.config/better-hyprland/bar/main.py
"""
import ctypes
import glob
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

from PyQt6 import sip
from PyQt6.QtCore import (QEasingCurve, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt,
                          QThread, QTime, QTimer, QVariantAnimation, pyqtSignal)
from PyQt6.QtGui import (QColor, QFont, QFontDatabase, QFontMetrics, QIcon, QImage, QPainter,
                         QPainterPath, QPen, QPixmap, QRegion)
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------
BASE_H = 768            # development resolution (1366x768); everything scales from this
BASE_PILL_H = 40        # pill height in px at BASE_H
POPUP_ROOM = 250        # transparent space above the pills reserved for hover popups (px at BASE_H)
EDGE_MARGIN = 8         # gap between pills and the screen edges, px at 768p (scales up)
WS_MIN, WS_MAX = 7, 10  # workspace circles shown (grows if you use higher ones)

PILL_RGB = (0x69, 0x36, 0x52)
PILL_OPACITY = 0.4      # spec: 0.3 - 0.4

SM_CMD = "python ~/.config/better-hyprland/sm/main.py toggle"
NC_CMD = "python ~/.config/better-hyprland/nc/main.py toggle"

# layer-shell namespace, match it in hyprland.lua (blur etc.)
SCOPE = "sys-bar"
USE_SCOPE = True        # set False if the bar crashes on launch (see notes)

# Arch logo from "Font Awesome 7 Brands". None = auto-detect the codepoint with fontTools
# (pacman -S python-fonttools). Or set it by hand, e.g. 0xF000, from the FA icon page.
ARCH_CODEPOINT = None

WHITE = QColor(255, 255, 255)
RED = QColor(255, 77, 77)
WS_DIM = QColor(255, 255, 255, 128)   # workspace outlines + empty dots at 50%


def pill_color():
    return QColor(*PILL_RGB, int(255 * PILL_OPACITY))


def ui_scale(screen):
    """Scale from the screen's SHORT side in logical px (so portrait/ultrawide behave too).
    768 -> 1.0, 1080 -> 1.4, 1440 -> 1.9, 2160 -> 2.8 (cap)."""
    g = screen.geometry()
    return min(max(min(g.width(), g.height()) / BASE_H, 0.85), 2.8)


def sh(cmd):
    subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def hypr_dispatch(groups):
    """Run the first group of `hyprctl dispatch` calls that succeeds; log failures to stderr."""
    def work():
        for group in groups:
            ok = True
            for args in group:
                try:
                    r = subprocess.run(["hyprctl", "dispatch", *args], capture_output=True,
                                       text=True, timeout=3)
                    out = r.stdout.strip()
                    ok = r.returncode == 0 and out.lower().startswith("ok")
                except Exception as e:
                    out, ok = str(e), False
                if not ok:
                    print(f"[bar] hyprctl dispatch {' '.join(args)} -> {out!r}", file=sys.stderr)
                    break
            if ok:
                return
    threading.Thread(target=work, daemon=True).start()


# ----------------------------------------------------------------------------
# FONTS / ICONS
# ----------------------------------------------------------------------------
def find_arch_codepoint(family):
    if ARCH_CODEPOINT:
        return ARCH_CODEPOINT
    try:
        from fontTools.ttLib import TTFont
        out = subprocess.check_output(["fc-match", "-f", "%{family}|%{file}", family],
                                      timeout=3, text=True)
        fam, path = out.split("|", 1)
        if "awesome" not in fam.lower():
            raise RuntimeError(f"{family} not installed (fc-match gave {fam})")
        cmap = TTFont(path, fontNumber=0).getBestCmap()
        names = {cp: n.lower() for cp, n in cmap.items()}
        for cp, n in sorted(names.items()):
            if re.fullmatch(r"(font-)?arch([-_]?linux)?", n):
                return cp
        for cp, n in sorted(names.items()):
            if "arch" in n and "linux" in n:
                return cp
        raise RuntimeError("no glyph named like arch-linux in " + path)
    except Exception as e:
        print(f"[bar] Arch glyph auto-detect failed: {e}\n"
              f"[bar] set ARCH_CODEPOINT at the top of main.py", file=sys.stderr)
        return None


class Fonts:
    def __init__(self):
        fams = QFontDatabase.families()

        def pick(*patterns):
            out = []
            for pat in patterns:
                rx = re.compile(pat, re.I)
                for f in sorted((f for f in fams if rx.match(f)), reverse=True):
                    if f not in out:
                        out.append(f)
            return out

        # "Font Awesome.*" -> every installed version, newest first
        self.fa = pick(r"Font Awesome \d+ Brands", r"Font Awesome.*Brands") or ["Font Awesome 7 Brands"]
        self.arch_cp = find_arch_codepoint(self.fa[0])
        self.mat = pick(r"Material Symbols Rounded", r"Material Symbols Outlined",
                        r"Material Icons Round") or ["Material Symbols Rounded"]
        # there is no standalone family called "Google Sans Flex 9pt"; match any Google Sans*
        self.text = ["Google Sans Flex 9pt"] + pick(r"Google Sans Flex", r"Google Sans") + ["Noto Sans"]


FONTS = None


def make_font(families, px, bold=False):
    f = QFont()
    f.setFamilies(list(families))
    f.setPixelSize(max(1, int(px)))
    f.setBold(bold)
    return f


def draw_glyph(p, rect, text, families, px, color):
    p.save()
    p.setFont(make_font(families, px))
    p.setPen(color)
    p.drawText(QRectF(rect), Qt.AlignmentFlag.AlignCenter, text)
    p.restore()


def tinted_pixmap(icon, px, color):
    pm = icon.pixmap(QSize(px, px))
    q = QPainter(pm)
    q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    q.fillRect(pm.rect(), color)
    q.end()
    return pm


class IconResolver:
    """window class -> Papirus icon, using .desktop files (StartupWMClass / Icon)."""

    def __init__(self):
        if QIcon.themeName() not in ("Papirus", "Papirus-Dark", "Papirus-Light"):
            for t in ("Papirus-Dark", "Papirus"):
                if any(os.path.isdir(f"{d}/icons/{t}") for d in
                       ("/usr/share", os.path.expanduser("~/.local/share"))):
                    QIcon.setThemeName(t)
                    break
        self.map, self.cache = {}, {}
        dirs = ["/usr/share/applications", os.path.expanduser("~/.local/share/applications"),
                "/var/lib/flatpak/exports/share/applications",
                os.path.expanduser("~/.local/share/flatpak/exports/share/applications")]
        for d in dirs:
            for f in glob.glob(d + "/*.desktop"):
                icon = wm = None
                try:
                    with open(f, encoding="utf-8", errors="ignore") as fh:
                        for line in fh:
                            if line.startswith("Icon=") and icon is None:
                                icon = line[5:].strip()
                            elif line.startswith("StartupWMClass=") and wm is None:
                                wm = line[15:].strip()
                except OSError:
                    continue
                if icon:
                    self.map.setdefault(os.path.basename(f)[:-8].lower(), icon)
                    if wm:
                        self.map[wm.lower()] = icon

    def icon(self, wmclass):
        key = (wmclass or "").lower()
        if key in self.cache:
            return self.cache[key]
        name = self.map.get(key, key)
        ic = QIcon(name) if name.startswith("/") else QIcon.fromTheme(name)
        if ic.isNull():
            ic = QIcon.fromTheme(key)
        if ic.isNull():
            ic = QIcon.fromTheme("application-x-executable")
        self.cache[key] = ic
        return ic


# ----------------------------------------------------------------------------
# LAYER SHELL  (layer-shell-qt through ctypes)
# ----------------------------------------------------------------------------
class _QBAView(ctypes.Structure):  # QByteArrayView {qsizetype size; const char *data;}
    _fields_ = [("size", ctypes.c_ssize_t), ("data", ctypes.c_char_p)]


class LayerShell:
    """
    Talks to libLayerShellQtInterface directly. If you already have a working
    layer-shell helper in your start menu, replace apply() with that code.
    The surface gets the namespace SCOPE ("sys-bar"); check with `hyprctl layers`.
    """
    TOP, BOTTOM, LEFT, RIGHT = 1, 2, 4, 8
    LAYER_TOP = 2

    def __init__(self):
        self.lib = None
        for name in ("libLayerShellQtInterface.so.6", "libLayerShellQtInterface.so"):
            try:
                self.lib = ctypes.CDLL(name)
                break
            except OSError:
                pass
        if not self.lib:
            sys.exit("layer-shell-qt not found (pacman -S layer-shell-qt)")
        L = self.lib
        self._use = L["_ZN12LayerShellQt5Shell13useLayerShellEv"]
        self._get = L["_ZN12LayerShellQt6Window3getEP7QWindow"]
        self._get.restype, self._get.argtypes = ctypes.c_void_p, [ctypes.c_void_p]
        self._fn = {}
        for key, sym in {
            "layer": "_ZN12LayerShellQt6Window8setLayerENS0_5LayerE",
            "anchors": "_ZN12LayerShellQt6Window10setAnchorsE6QFlagsINS0_6AnchorEE",
            "zone": "_ZN12LayerShellQt6Window16setExclusiveZoneEi",
            "kbd": "_ZN12LayerShellQt6Window24setKeyboardInteractivityENS0_21KeyboardInteractivityE",
        }.items():
            f = L[sym]
            f.argtypes = [ctypes.c_void_p, ctypes.c_int]
            f.restype = None
            self._fn[key] = f
        f = L["_ZN12LayerShellQt6Window14setDesiredSizeERK5QSize"]
        f.argtypes, f.restype = [ctypes.c_void_p, ctypes.c_void_p], None
        self._fn["size"] = f
        # scope (= Hyprland layer namespace) needs a QString, built through Qt6Core
        self._keep, self._mkq = [], None
        if USE_SCOPE:
            try:
                core = ctypes.CDLL("libQt6Core.so.6")
                try:
                    f = core["_ZN7QString16fromUtf8_helperEPKcl"]
                    f.argtypes, f.restype = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long], None
                    self._mkq = ("helper", f)
                except AttributeError:
                    f = core["_ZN7QString8fromUtf8E14QByteArrayView"]
                    f.argtypes, f.restype = [ctypes.c_void_p, _QBAView], None
                    self._mkq = ("view", f)
                f = L["_ZN12LayerShellQt6Window8setScopeERK7QString"]
                f.argtypes, f.restype = [ctypes.c_void_p, ctypes.c_void_p], None
                self._fn["scope"] = f
            except (AttributeError, OSError) as e:
                print(f"[bar] cannot set namespace, staying on 'window': {e}", file=sys.stderr)
                self._mkq = None

    def _qstring(self, text):
        data = text.encode()
        buf = ctypes.create_string_buffer(24)  # QString = 3 pointers in Qt6
        kind, f = self._mkq
        if kind == "helper":
            f(buf, data, len(data))
        else:
            f(buf, _QBAView(len(data), data))
        self._keep += [buf, data]
        return buf

    def use(self):
        self._use()  # must run before any window is created

    def apply(self, qwindow, height, zone):
        win = self._get(sip.unwrapinstance(qwindow))
        self._fn["layer"](win, self.LAYER_TOP)
        self._fn["anchors"](win, self.BOTTOM | self.LEFT | self.RIGHT)
        self._fn["zone"](win, zone)
        self._fn["kbd"](win, 0)  # no keyboard focus
        if self._mkq and "scope" in self._fn:
            self._fn["scope"](win, ctypes.addressof(self._qstring(SCOPE)))
        size = (ctypes.c_int * 2)(0, height)  # width 0 = stretch (left+right anchored)
        self._fn["size"](win, ctypes.cast(size, ctypes.c_void_p))


# ----------------------------------------------------------------------------
# DATA SOURCES
# ----------------------------------------------------------------------------
def hyprctl(*args):
    try:
        return json.loads(subprocess.check_output(["hyprctl", "-j", *args], timeout=2))
    except Exception:
        return None


class HyprWatcher(QThread):
    """Follows Hyprland's event socket and emits a snapshot of workspaces/windows/monitors."""
    changed = pyqtSignal(object)
    IGNORE = {b"activewindow", b"activewindowv2", b"windowtitle", b"windowtitlev2"}

    def __init__(self):
        super().__init__()
        self.order, self.n = {}, 0

    def snapshot(self):
        clients = hyprctl("clients") or []
        mons = hyprctl("monitors") or []
        wss = hyprctl("workspaces") or []
        for c in sorted(clients, key=lambda c: c.get("pid", 0)):
            if c["address"] not in self.order:  # remember who opened first
                self.n += 1
                self.order[c["address"]] = self.n
        live = {c["address"] for c in clients}
        self.order = {a: o for a, o in self.order.items() if a in live}
        by_ws = {}
        for c in clients:
            wid = c.get("workspace", {}).get("id", -1)
            if wid > 0 and c.get("mapped", True):
                by_ws.setdefault(wid, []).append(c)
        for lst in by_ws.values():
            lst.sort(key=lambda c: self.order.get(c["address"], 1 << 30))
        self.changed.emit({
            "by_ws": by_ws,
            "active": {m["name"]: m.get("activeWorkspace", {}).get("id", 0) for m in mons},
            "mons": {m["name"]: dict(x=m["x"], y=m["y"], w=m["width"] / (m.get("scale") or 1),
                                     h=m["height"] / (m.get("scale") or 1)) for m in mons},
        })

    def run(self):
        self.snapshot()
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        rt = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        path = f"{rt}/hypr/{sig}/.socket2.sock"
        while not self.isInterruptionRequested():
            if not sig or not os.path.exists(path):
                time.sleep(1)
                self.snapshot()
                continue
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(path)
                s.settimeout(1.0)
                while not self.isInterruptionRequested():
                    try:
                        data = s.recv(8192)
                    except socket.timeout:
                        continue
                    if not data:
                        break
                    names = {l.split(b">>")[0] for l in data.splitlines()}
                    if names - self.IGNORE:
                        self.snapshot()
            except OSError:
                time.sleep(1)


class SlowPoller(QThread):
    """Network / notification state (touches the network & subprocesses, so off the UI thread)."""
    result = pyqtSignal(str, bool, bool)

    @staticmethod
    def net_kind():
        wifi = eth = False
        for n in os.listdir("/sys/class/net"):
            if n == "lo" or n.startswith(("veth", "docker", "br-", "virbr", "tun", "tap")):
                continue
            try:
                if open(f"/sys/class/net/{n}/operstate").read().strip() != "up":
                    continue
            except OSError:
                continue
            if os.path.isdir(f"/sys/class/net/{n}/wireless"):
                wifi = True
            else:
                eth = True
        return "ethernet" if eth else "wifi" if wifi else "none"

    @staticmethod
    def notif_active():
        for cmd in (["swaync-client", "-c"], ["dunstctl", "count", "waiting"]):
            if shutil.which(cmd[0]):
                try:
                    return int(subprocess.check_output(cmd, timeout=1).split()[0]) > 0
                except Exception:
                    pass
        return False

    def run(self):
        while not self.isInterruptionRequested():
            kind = self.net_kind()
            online = False
            if kind != "none":
                try:
                    socket.create_connection(("1.1.1.1", 53), 1.2).close()
                    online = True
                except OSError:
                    pass
            self.result.emit(kind, online, self.notif_active())
            self.msleep(5000)


class Stats(QObject):
    updated = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.cpu = 0.0
        self.ram_used = self.ram_total = self.swap_used = self.swap_total = 0.0
        bats = glob.glob("/sys/class/power_supply/BAT*")
        self.bat_dir = bats[0] if bats else None
        self.has_bat = bool(bats)
        self.bat, self.charging = 100, False
        self.net, self.online, self.notif = "none", False, False
        self._prev = None
        self.poll()
        t = QTimer(self)
        t.timeout.connect(self.poll)
        t.start(2000)
        self.slow = SlowPoller()
        self.slow.result.connect(self._slow)
        self.slow.start()

    @property
    def ram_pct(self):
        return 100 * self.ram_used / self.ram_total if self.ram_total else 0

    @property
    def swap_pct(self):
        return 100 * self.swap_used / self.swap_total if self.swap_total else 0

    def _slow(self, net, online, notif):
        self.net, self.online, self.notif = net, online, notif
        self.updated.emit()

    def poll(self):
        mi = {}
        with open("/proc/meminfo") as f:
            for l in f:
                k, v = l.split(":")
                mi[k] = int(v.split()[0])
        g = 1048576.0
        self.ram_total = mi["MemTotal"] / g
        self.ram_used = (mi["MemTotal"] - mi["MemAvailable"]) / g
        self.swap_total = mi["SwapTotal"] / g
        self.swap_used = (mi["SwapTotal"] - mi["SwapFree"]) / g
        with open("/proc/stat") as f:
            v = list(map(int, f.readline().split()[1:9]))
        idle, total = v[3] + v[4], sum(v)
        if self._prev and total > self._prev[0]:
            self.cpu = 100 * (1 - (idle - self._prev[1]) / (total - self._prev[0]))
        self._prev = (total, idle)
        if self.bat_dir:
            try:
                self.bat = int(open(self.bat_dir + "/capacity").read())
                self.charging = open(self.bat_dir + "/status").read().strip() == "Charging"
            except (OSError, ValueError):
                pass
        self.updated.emit()


class SniHost:
    """
    System-tray host for the StatusNotifierItem protocol (what Telegram, AB Download Manager,
    Discord, Steam, nm-applet ... use), over Gio/GDBus (pacman -S python-gobject).

    * If nobody owns org.kde.StatusNotifierWatcher it becomes the watcher itself (apps then
      register with it and every app that insists on a registered host is satisfied).
    * If another watcher already runs, it just registers as a host there and follows it.

    Runs in its own threads and never touches Qt: on_change(list_of_item_dicts) is called
    from a worker thread whenever the set of items or one of their icons changes.
    """
    ITEM = "org.kde.StatusNotifierItem"
    WATCHER = "org.kde.StatusNotifierWatcher"
    WPATH = "/StatusNotifierWatcher"
    DBUS = "org.freedesktop.DBus"
    XML = """<node><interface name="org.kde.StatusNotifierWatcher">
      <method name="RegisterStatusNotifierItem"><arg type="s" name="service" direction="in"/></method>
      <method name="RegisterStatusNotifierHost"><arg type="s" name="service" direction="in"/></method>
      <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
      <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
      <property name="ProtocolVersion" type="i" access="read"/>
      <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
      <signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal>
      <signal name="StatusNotifierHostRegistered"/>
      <signal name="StatusNotifierHostUnregistered"/>
    </interface></node>"""
    MENU = "com.canonical.dbusmenu"
    REFRESH = {"NewIcon", "NewAttentionIcon", "NewOverlayIcon", "NewStatus", "NewTitle",
               "NewIconThemePath", "NewToolTip"}

    def __init__(self, on_change):
        self.on_change = on_change
        self.error = None
        self.items = {}          # key -> item dict (insertion order = registration order)
        self.registered = []     # keys, as served to other hosts by our own watcher
        self.subs = {}           # key -> [signal subscription ids]
        self.owner = False
        self.conn = None
        self.q = queue.Queue()
        self.ready = threading.Event()
        threading.Thread(target=self._loop_thread, daemon=True).start()
        threading.Thread(target=self._worker, daemon=True).start()

    # ---- helpers --------------------------------------------------------------------
    @staticmethod
    def split(service, sender=None):
        """'name', 'name/path', '/path' (+ sender) -> (bus name, object path)."""
        if service.startswith("/"):
            return sender, service
        i = service.find("/")
        return (service, "/StatusNotifierItem") if i < 0 else (service[:i], service[i:])

    def _call(self, name, path, iface, method, args=None, sig=None, timeout=1500):
        G, GL = self.Gio, self.GLib
        return self.conn.call_sync(name, path, iface, method, args,
                                   GL.VariantType(sig) if sig else None,
                                   G.DBusCallFlags.NONE, timeout, None)

    # ---- GLib thread: watcher object, name tracking, item signals -------------------
    def _loop_thread(self):
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
        except Exception as e:
            self.error = "python-gobject missing"
            print(f"[bar] tray disabled: {e} (pacman -S python-gobject)", file=sys.stderr)
            return
        self.Gio, self.GLib = Gio, GLib
        try:
            ctx = GLib.MainContext.new()
            ctx.push_thread_default()  # GDBus delivers our callbacks in this thread
            self.loop = GLib.MainLoop.new(ctx, False)
            self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.conn.signal_subscribe(self.DBUS, self.DBUS, "NameOwnerChanged",
                                       "/org/freedesktop/DBus", None, Gio.DBusSignalFlags.NONE,
                                       self._on_owner_changed)
            # Export the watcher object BEFORE claiming the name: running apps re-register within
            # milliseconds of the name appearing, and an unanswered call is never retried.
            info = Gio.DBusNodeInfo.new_for_xml(self.XML)
            reg_id = self.conn.register_object(self.WPATH, info.interfaces[0], self._on_call,
                                               self._on_get, None)
            # DO_NOT_QUEUE (4): become the watcher only if nobody else is one
            r = self._call(self.DBUS, "/org/freedesktop/DBus", self.DBUS, "RequestName",
                           GLib.Variant("(su)", (self.WATCHER, 4)), "(u)").unpack()[0]
            self.owner = r in (1, 3)
            host = f"org.kde.StatusNotifierHost-{os.getpid()}"
            self._call(self.DBUS, "/org/freedesktop/DBus", self.DBUS, "RequestName",
                       GLib.Variant("(su)", (host, 0)), "(u)")
            if self.owner:
                self.conn.emit_signal(None, self.WPATH, self.WATCHER,
                                      "StatusNotifierHostRegistered", None)
                # apps that were already running and don't re-register: pick up the ones
                # that own a StatusNotifierItem name
                names = self._call(self.DBUS, "/org/freedesktop/DBus", self.DBUS, "ListNames",
                                   None, "(as)").unpack()[0]
                for n in names:
                    if n.startswith("org.kde.StatusNotifierItem-"):
                        self._register(n, None)
            else:
                self.conn.unregister_object(reg_id)
                self._follow_existing_watcher(host)
        except Exception as e:
            self.error = "tray host failed"
            print(f"[bar] tray host failed: {e}", file=sys.stderr)
            return
        self.ready.set()
        self.loop.run()

    def _follow_existing_watcher(self, host):
        G, GL = self.Gio, self.GLib
        try:
            self._call(self.WATCHER, self.WPATH, self.WATCHER, "RegisterStatusNotifierHost",
                       GL.Variant("(s)", (host,)))
        except Exception as e:
            print(f"[bar] RegisterStatusNotifierHost: {e}", file=sys.stderr)
        for sig, op in (("StatusNotifierItemRegistered", "add"),
                        ("StatusNotifierItemUnregistered", "del")):
            self.conn.signal_subscribe(
                self.WATCHER, self.WATCHER, sig, self.WPATH, None, G.DBusSignalFlags.NONE,
                lambda c, s, p, i, sg, params, op=op: self._watcher_signal(op, params.unpack()[0]))
        try:
            ret = self._call(self.WATCHER, self.WPATH, "org.freedesktop.DBus.Properties", "Get",
                             GL.Variant("(ss)", (self.WATCHER, "RegisteredStatusNotifierItems")),
                             "(v)")
            for svc in ret.unpack()[0]:
                self._watcher_signal("add", svc)
        except Exception as e:
            print(f"[bar] reading existing tray items: {e}", file=sys.stderr)

    def _watcher_signal(self, op, svc):
        name, path = self.split(svc)
        if not name:
            return
        if op == "add":
            self._watch_item(name, path)
            self.q.put(("add", name, path))
        else:
            self.q.put(("del", name + path))

    def _on_call(self, conn, sender, opath, iface, method, params, inv):
        GL = self.GLib
        if method == "RegisterStatusNotifierItem":
            self._register(params.unpack()[0], sender)
        inv.return_value(GL.Variant("()", ()))

    def _on_get(self, conn, sender, opath, iface, prop):
        GL = self.GLib
        if prop == "RegisteredStatusNotifierItems":
            return GL.Variant("as", list(self.registered))
        if prop == "IsStatusNotifierHostRegistered":
            return GL.Variant("b", True)
        if prop == "ProtocolVersion":
            return GL.Variant("i", 0)
        return None

    def _register(self, service, sender):
        name, path = self.split(service, sender)
        key = (name or "") + path
        if not name or key in self.registered:
            return
        self.registered.append(key)
        self.conn.emit_signal(None, self.WPATH, self.WATCHER, "StatusNotifierItemRegistered",
                              self.GLib.Variant("(s)", (key,)))
        self._watch_item(name, path)
        self.q.put(("add", name, path))

    def _watch_item(self, name, path):
        G = self.Gio
        key = name + path
        if key in self.subs:
            return
        self.subs[key] = [self.conn.signal_subscribe(
            name, self.ITEM, None, path, None, G.DBusSignalFlags.NONE,
            lambda c, s, p, i, sg, params, key=key:
                self.q.put(("refresh", key)) if sg in self.REFRESH else None)]

    def _on_owner_changed(self, conn, sender, opath, iface, sig, params):
        name, old, new = params.unpack()
        if new:
            return
        for key in [k for k in list(self.registered) + list(self.items) if
                    k.startswith(name + "/")]:
            if key in self.registered:
                self.registered.remove(key)
                if self.owner:
                    conn.emit_signal(None, self.WPATH, self.WATCHER,
                                     "StatusNotifierItemUnregistered",
                                     self.GLib.Variant("(s)", (key,)))
            self.q.put(("del", key))

    # ---- worker thread: reads item properties (blocking calls, never in the GLib thread) ----
    def _worker(self):
        self.ready.wait()
        while True:
            op = self.q.get()
            try:
                changed = self._handle(op)
            except Exception as e:
                print(f"[bar] tray: {e}", file=sys.stderr)
                continue
            if changed:
                self.on_change(self.snapshot())

    def _handle(self, op):
        if op[0] == "del":
            key = op[1]
            for sid in self.subs.pop(key, []):
                self.conn.signal_unsubscribe(sid)
            return self.items.pop(key, None) is not None
        if op[0] == "add":
            key = op[1] + op[2]
            if key in self.items:
                return False
        else:
            key = op[1]
            if key not in self.items:
                return False
        name, path = (op[1], op[2]) if op[0] == "add" else (self.items[key]["name"],
                                                           self.items[key]["path"])
        props = None
        for attempt in range(4):  # the app may export its object a moment after registering
            try:
                props = self._call(name, path, "org.freedesktop.DBus.Properties", "GetAll",
                                   self.GLib.Variant("(s)", (self.ITEM,)), "(a{sv})").unpack()[0]
                break
            except Exception as e:
                err = e
                time.sleep(0.4)
        if props is None:
            print(f"[bar] tray item {key}: {err}", file=sys.stderr)
            return False
        self.items[key] = self._parse(key, name, path, props)
        return True

    @staticmethod
    def _best(pixmaps):
        best = None
        for w, h, data in pixmaps or []:
            if w > 0 and h > 0 and len(data) >= w * h * 4 and (best is None or w * h > best[0] * best[1]):
                best = (w, h, bytes(data[:w * h * 4]))
        return best

    def _parse(self, key, name, path, p):
        item = dict(
            key=key, name=name, path=path,
            id=p.get("Id", ""), title=p.get("Title", "") or p.get("Id", ""),
            status=p.get("Status", "Active"),
            icon_name=p.get("IconName", ""), att_name=p.get("AttentionIconName", ""),
            theme_path=p.get("IconThemePath", ""),
            pixmap=self._best(p.get("IconPixmap")), att_pixmap=self._best(p.get("AttentionIconPixmap")),
            menu=p.get("Menu", ""), is_menu=bool(p.get("ItemIsMenu", False)),
        )
        item["sig"] = hash((item["icon_name"], item["att_name"], item["theme_path"], item["status"],
                            item["pixmap"] and item["pixmap"][2], item["att_pixmap"] and item["att_pixmap"][2]))
        return item

    def snapshot(self):
        return [dict(i) for i in self.items.values() if i["status"] != "Passive"]

    # ---- dbusmenu (the right-click menu of an item) ----
    @classmethod
    def _menu_node(cls, node):
        nid, p, kids = node
        label = re.sub(r"_(.)?", lambda m: "_" if m.group(1) == "_" else (m.group(1) or ""),
                       p.get("label", ""))
        children = [cls._menu_node(k) for k in kids]
        return dict(id=nid, label=label, enabled=bool(p.get("enabled", True)),
                    visible=bool(p.get("visible", True)), sep=p.get("type", "") == "separator",
                    toggle=p.get("toggle-type", ""), state=int(p.get("toggle-state", -1)),
                    icon=p.get("icon-name", ""), children=children,
                    sub=p.get("children-display", "") == "submenu" or bool(children))

    def get_menu(self, name, path, done):
        """Fetch the menu tree in a short-lived thread, then done(tree or None)."""
        def work():
            tree = None
            try:
                GL = self.GLib
                try:
                    self._call(name, path, self.MENU, "AboutToShow", GL.Variant("(i)", (0,)), "(b)")
                except Exception:
                    pass
                ret = self._call(name, path, self.MENU, "GetLayout",
                                 GL.Variant("(iias)", (0, -1, [])), "(u(ia{sv}av))", 3000)
                tree = self._menu_node(ret.unpack()[1])
            except Exception as e:
                print(f"[bar] tray menu of {name}: {e}", file=sys.stderr)
            done(tree)
        if self.conn:
            threading.Thread(target=work, daemon=True).start()
        else:
            done(None)

    def menu_click(self, name, path, mid):
        def work():
            GL = self.GLib
            try:
                self._call(name, path, self.MENU, "Event", GL.Variant(
                    "(isvu)", (int(mid), "clicked", GL.Variant("i", 0), int(time.time()) & 0xFFFFFFFF)))
            except Exception as e:
                print(f"[bar] tray menu click on {name}: {e}", file=sys.stderr)
        if self.conn:
            threading.Thread(target=work, daemon=True).start()

    # ---- clicks (called from the UI thread; runs in its own short-lived thread) ----
    def act(self, name, path, method, x=0, y=0):
        def work():
            try:
                self._call(name, path, self.ITEM, method, self.GLib.Variant("(ii)", (int(x), int(y))))
            except Exception as e:
                print(f"[bar] tray {method} on {name}: {e}", file=sys.stderr)
                if method == "Activate":  # items without Activate (menu-only) get their menu
                    try:
                        self._call(name, path, self.ITEM, "ContextMenu",
                                   self.GLib.Variant("(ii)", (int(x), int(y))))
                    except Exception:
                        pass
        if self.conn:
            threading.Thread(target=work, daemon=True).start()


class TrayBackend(QObject):
    """Hidden-icons tray. SniHost does the D-Bus work in its own threads; this class lives in
    the Qt thread, keeps the item list and turns items into pixmaps."""
    changed = pyqtSignal()
    menuReady = pyqtSignal(str, object)   # (item key, menu tree or None)
    _got = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.items, self._cache = [], {}
        self._got.connect(self._set)          # emitted from the worker thread -> queued
        self.host = SniHost(self._got.emit)

    @property
    def error(self):
        return self.host.error

    def _set(self, items):
        self.items, self._cache = items, {}
        self.changed.emit()

    def visible(self):
        return []

    def hidden(self):
        return self.items

    def act(self, item, method, pos):
        self.host.act(item["name"], item["path"], method, pos.x(), pos.y())

    @staticmethod
    def has_menu(item):
        m = item.get("menu") or ""
        return bool(m) and m != "/" and "NO_DBUSMENU" not in m

    def request_menu(self, item):
        key = item["key"]
        self.host.get_menu(item["name"], item["menu"], lambda tree: self.menuReady.emit(key, tree))

    def menu_click(self, item, mid):
        self.host.menu_click(item["name"], item["menu"], mid)

    @staticmethod
    def _icon_from_name(name, theme_path):
        if not name:
            return None
        if os.path.isabs(name):
            ic = QIcon(name)
            return None if ic.isNull() else ic
        if theme_path and os.path.isdir(theme_path):  # apps ship icons in their own folder
            for ext in (".png", ".svg", ".xpm"):
                f = os.path.join(theme_path, name + ext)
                if os.path.isfile(f):
                    return QIcon(f)
            found = [f for f in glob.glob(os.path.join(theme_path, "**", name + ".*"), recursive=True)
                     if f.lower().endswith((".png", ".svg", ".xpm"))]
            if found:
                found.sort(key=lambda f: (not f.endswith(".svg"), -os.path.getsize(f)))
                return QIcon(found[0])
        ic = QIcon.fromTheme(name)
        return None if ic.isNull() else ic

    def pixmap(self, item, px, dpr=1.0):
        key = (item["key"], item["sig"], px, dpr)
        if key in self._cache:
            return self._cache[key]
        size = max(1, int(px * dpr))
        attention = item["status"] == "NeedsAttention"
        name = (item["att_name"] if attention and item["att_name"] else item["icon_name"])
        raw = (item["att_pixmap"] if attention and item["att_pixmap"] else item["pixmap"])
        pm = None
        ic = self._icon_from_name(name, item["theme_path"])
        if ic:
            try:
                pm = ic.pixmap(QSize(px, px), dpr)
            except TypeError:
                pm = ic.pixmap(QSize(size, size))
        elif raw:  # IconPixmap: ARGB32, network byte order, not premultiplied
            w, h, data = raw
            buf = bytearray(w * h * 4)
            buf[0::4], buf[1::4], buf[2::4], buf[3::4] = data[1::4], data[2::4], data[3::4], data[0::4]
            img = QImage(bytes(buf), w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
            img = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(dpr)
        else:
            pm = QIcon.fromTheme("application-x-executable").pixmap(QSize(px, px))
        self._cache[key] = pm
        return pm


# ----------------------------------------------------------------------------
# BASE WIDGETS
# ----------------------------------------------------------------------------
class Hoverable(QWidget):
    hoverChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def enterEvent(self, e):
        self.hoverChanged.emit(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.hoverChanged.emit(False)
        super().leaveEvent(e)


class PressButton(Hoverable):
    """Custom-painted button with the zoom-out-and-in click animation (touch works too:
    Qt turns unhandled touch events into mouse events)."""
    clicked = pyqtSignal()

    def __init__(self, w, h, paint_fn, parent=None):
        super().__init__(parent)
        self.setFixedSize(int(w), int(h))
        self.paint_fn = paint_fn
        self._k, self._down = 1.0, False
        self.anim = QVariantAnimation(self)
        self.anim.valueChanged.connect(self._setk)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _setk(self, v):
        self._k = float(v)
        self.update()

    def _go(self, to, ms, curve):
        self.anim.stop()
        self.anim.setStartValue(self._k)
        self.anim.setEndValue(to)
        self.anim.setDuration(ms)
        self.anim.setEasingCurve(curve)
        self.anim.start()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._down = True
            self._go(0.78, 90, QEasingCurve.Type.OutCubic)

    def mouseReleaseEvent(self, e):
        if self._down:
            self._down = False
            self._go(1.0, 280, QEasingCurve.Type.OutBack)
            if self.rect().contains(e.position().toPoint()):
                self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                         | QPainter.RenderHint.SmoothPixmapTransform)
        c = QPointF(self.width() / 2, self.height() / 2)
        p.translate(c)
        p.scale(self._k, self._k)
        p.translate(-c)
        self.paint_fn(p, QRectF(self.rect()), self)


class Pill(QWidget):
    def __init__(self, parent, ph):
        super().__init__(parent)
        self.ph = ph
        self.setFixedHeight(ph)



class Popup(Hoverable):
    """Hover popup that grows upward out of a pill (expand + slide)."""
    stateChanged = pyqtSignal()

    def __init__(self, bar, w, h):
        super().__init__(bar)
        self.bar, self.reveal, self.target = bar, 0.0, False
        self.radius = bar.ph * 0.5  # same radius as the pills so joins are seamless
        self.resize(int(w), int(h))
        self.body = QWidget(self)
        self.body.resize(int(w), int(h))
        self.anim = QVariantAnimation(self)
        self.anim.valueChanged.connect(self._set)
        self.anim.finished.connect(self._done)
        self.hide()

    def visible_rect(self):
        g = self.geometry()
        off = int(g.height() * (1 - self.reveal))
        return QRect(g.x(), g.y() + off, g.width(), g.height() - off)

    def shape_rect(self):
        """Visible part of the popup, continued down to the bottom of the pills (the
        expanded area runs all the way down, also where it sticks out beside a pill)."""
        vr = self.visible_rect()
        bottom = self.bar.height() - self.bar.edge
        return QRect(vr.x(), vr.y(), vr.width(), bottom - vr.y())

    def set_size(self, w, h):
        w, h = int(w), int(h)
        if (w, h) == (self.width(), self.height()):
            return
        self.resize(w, h)
        self.body.resize(w, h)
        if self.isVisible():
            self._set(self.reveal)

    def place(self, x, bottom):
        x = max(0, min(int(x), self.bar.width() - self.width()))
        self.move(x, int(bottom) - self.height())
        if self.isVisible():  # moved/resized while open: the input region must follow it
            self.bar.update_mask()
            self.bar.update()

    def _run(self, to, ms, curve):
        self.anim.stop()
        self.anim.setStartValue(self.reveal)
        self.anim.setEndValue(to)
        self.anim.setDuration(ms)
        self.anim.setEasingCurve(curve)
        self.anim.start()

    def open(self):
        if self.target and self.isVisible():
            return
        self.target = True
        self._set(self.reveal)
        self.show()
        self.raise_()
        self._run(1.0, 240, QEasingCurve.Type.OutCubic)
        self.stateChanged.emit()

    def close_anim(self):
        if not self.target:
            return
        self.target = False
        self._run(0.0, 170, QEasingCurve.Type.InCubic)
        self.stateChanged.emit()

    def _set(self, v):
        self.reveal = float(v)
        off = int(self.height() * (1 - self.reveal))
        if off >= self.height():
            self.body.hide()
        else:  # content stays put and is uncovered as the pill grows (no sliding)
            self.body.setMask(QRegion(0, off, self.width(), self.height() - off))
            self.body.show()
        self.bar.update_mask()
        self.bar.update()

    def _done(self):
        if not self.target:
            self.hide()
            self.bar.update_mask()
            self.bar.update()



class HoverLink(QObject):
    """Opens a popup while the mouse is over any bound trigger or the popup itself."""

    def __init__(self, popup, on_open, delay=140):
        super().__init__(popup)
        self.popup, self.on_open = popup, on_open
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(delay)
        self.timer.timeout.connect(popup.close_anim)
        popup.hoverChanged.connect(lambda h: self.timer.stop() if h else self.timer.start())

    def bind(self, widget, key=None):
        widget.hoverChanged.connect(lambda h, k=key: self._on(h, k))

    def _on(self, hovered, key):
        if hovered:
            self.timer.stop()
            self.on_open(key)
        else:
            self.timer.start()


# ----------------------------------------------------------------------------
# BAR PARTS
# ----------------------------------------------------------------------------
class ResourceBox(PressButton):
    """RAM% | CPU% | battery | swap%  - one painted widget so width never jitters."""

    def __init__(self, bar, parent):
        ph = bar.ph
        st = bar.ctx.stats
        iw = ph * 0.52
        fm = QFontMetrics(bar.label_font())
        lw = fm.horizontalAdvance("100%")
        gap = ph * 0.22
        seq = ["ram", "cpu"] + (["bat"] if st.has_bat else []) + ["swap"]
        x, cells = 0.0, []
        for k in seq:
            cells.append((k, x))
            x += iw + (0 if k == "bat" else ph * 0.04 + lw) + gap
        super().__init__(x - gap, ph, self._paint, parent)
        self.bar, self.iw, self.lw, self.cells, self.gap_il = bar, iw, lw, cells, ph * 0.04

    def _paint(self, p, rect, btn):
        st, ph = self.bar.ctx.stats, self.bar.ph
        p.setFont(self.bar.label_font())
        for k, x in self.cells:
            col, txt = WHITE, None
            if k == "ram":
                glyph, txt = "memory_alt", f"{st.ram_pct:.0f}%"
            elif k == "cpu":
                glyph, txt = "memory", f"{st.cpu:.0f}%"
            elif k == "swap":
                glyph, txt = "swap_horizontal_circle", f"{st.swap_pct:.0f}%"
            else:
                if st.charging:
                    glyph = "battery_android_bolt"
                else:
                    glyph = f"battery_android_{min(6, st.bat * 7 // 100)}"  # 7 phases: 0..6
                    if st.bat <= 15:
                        col = RED
            draw_glyph(p, QRectF(x, 0, self.iw, ph), glyph, FONTS.mat, self.iw, col)
            if txt:
                p.setFont(self.bar.label_font())
                p.setPen(WHITE)
                p.drawText(QRectF(x + self.iw + self.gap_il, 0, self.lw, ph),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, txt)


class WsPreview(QWidget):
    """Mini map of the windows on a workspace (the light box in the hover mockup)."""

    def __init__(self, parent, bar):
        super().__init__(parent)
        self.bar, self.clients = bar, []
        self.mon = dict(x=0, y=0, w=1920, h=1080)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        r = self.bar.ph * 0.25
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(240, 228, 233, 225))
        p.drawRoundedRect(QRectF(self.rect()), r, r)
        m = self.mon
        sx, sy = self.width() / m["w"], self.height() / m["h"]
        for c in self.clients:
            (x, y), (w, h) = c["at"], c["size"]
            rc = QRectF((x - m["x"]) * sx, (y - m["y"]) * sy, w * sx, h * sy)
            p.setBrush(QColor(105, 54, 82, 70))
            p.setPen(QPen(QColor(105, 54, 82, 170), max(1.0, self.bar.s)))
            p.drawRoundedRect(rc, r * 0.4, r * 0.4)
            sz = int(min(min(rc.width(), rc.height()) * 0.55, self.bar.ph * 0.9))
            if sz > 8:
                pm = self.bar.ctx.icons.icon(c.get("class")).pixmap(QSize(sz, sz))
                p.drawPixmap(int(rc.center().x() - sz / 2), int(rc.center().y() - sz / 2), pm)


class MenuView(QWidget):
    """Draws a tray item's menu (dbusmenu rows) inside the hidden-icons popup."""
    picked = pyqtSignal(object)

    def mousePressEvent(self, e):
        e.accept()  # we are the target of the click (the release picks the row)

    def __init__(self, bar, parent):
        super().__init__(parent)
        ph = bar.ph
        self.bar, self.rows, self.hover, self.scroll = bar, [], -1, 0
        self.font = make_font(FONTS.text, ph * 0.31)
        self.rh, self.sh = int(ph * 0.68), int(ph * 0.26)
        self.padx, self.top = int(ph * 0.2), int(ph * 0.14)
        self.setMouseTracking(True)
        self.hide()

    def set_rows(self, rows):
        self.rows = [r for r in rows if r.get("visible", True)]
        self.hover, self.scroll = -1, 0
        self.update()

    def _h(self, r):
        return self.sh if r["sep"] else self.rh

    def need_size(self):
        fm = QFontMetrics(self.font)
        tw = max([fm.horizontalAdvance(r["label"]) for r in self.rows if not r["sep"]] + [0])
        return (2 * self.padx + 2 * self.rh + tw,
                sum(self._h(r) for r in self.rows) + self.top + self.padx)

    def _row_at(self, y):
        yy = self.top - self.scroll
        for i, r in enumerate(self.rows):
            if yy <= y < yy + self._h(r):
                return i
            yy += self._h(r)
        return -1

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                         | QPainter.RenderHint.SmoothPixmapTransform)
        fm = QFontMetrics(self.font)
        rh, y = self.rh, self.top - self.scroll
        for i, r in enumerate(self.rows):
            h = self._h(r)
            rect = QRectF(self.padx / 2, y, self.width() - self.padx, h)
            y += h
            if rect.bottom() < 0 or rect.top() > self.height():
                continue
            if r["sep"]:
                p.setPen(QPen(QColor(255, 255, 255, 70), 1))
                p.drawLine(QPointF(rect.left() + rh * 0.3, rect.center().y()),
                           QPointF(rect.right() - rh * 0.3, rect.center().y()))
                continue
            col = QColor(255, 255, 255, 255 if r["enabled"] else 105)
            if i == self.hover and r["enabled"]:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 48))
                p.drawRoundedRect(rect, self.bar.ph * 0.22, self.bar.ph * 0.22)
            left = QRectF(rect.left(), rect.top(), rh, h)
            if r.get("back"):
                draw_glyph(p, left, "chevron_left", FONTS.mat, rh * 0.62, col)
            elif r["toggle"] and r["state"] == 1:
                draw_glyph(p, left, "check" if r["toggle"] == "checkmark" else "radio_button_checked",
                           FONTS.mat, rh * 0.55, col)
            elif r["toggle"] == "radio":
                draw_glyph(p, left, "radio_button_unchecked", FONTS.mat, rh * 0.55, col)
            elif r["icon"]:
                ic = QIcon.fromTheme(r["icon"])
                if not ic.isNull():
                    sz = int(rh * 0.55)
                    p.drawPixmap(int(left.center().x() - sz / 2), int(left.center().y() - sz / 2),
                                 ic.pixmap(QSize(sz, sz)))
            tw = int(rect.width() - 2 * rh)
            p.setFont(self.font)
            p.setPen(col)
            p.drawText(QRectF(rect.left() + rh, rect.top(), tw, h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(r["label"], Qt.TextElideMode.ElideRight, tw))
            if r.get("sub"):
                draw_glyph(p, QRectF(rect.right() - rh, rect.top(), rh, h), "chevron_right",
                           FONTS.mat, rh * 0.62, col)

    def mouseMoveEvent(self, e):
        i = self._row_at(int(e.position().y()))
        if i != self.hover:
            self.hover = i
            self.update()

    def leaveEvent(self, e):
        self.hover = -1
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        i = self._row_at(int(e.position().y()))
        if 0 <= i < len(self.rows) and self.rows[i]["enabled"] and not self.rows[i]["sep"]:
            self.picked.emit(self.rows[i])

    def wheelEvent(self, e):
        total = sum(self._h(r) for r in self.rows) + self.top + self.padx
        mx = max(0, total - self.height())
        self.scroll = max(0, min(mx, self.scroll - int(e.angleDelta().y() / 120 * self.rh)))
        self.hover = self._row_at(int(e.position().y()))
        self.update()


class TrayButton(PressButton):
    """One tray icon in the hidden-icons popup: left = activate, middle = secondary action,
    right = context menu."""

    def __init__(self, bar, item, size, parent):
        super().__init__(size, size, self._paint, parent)
        self.bar, self.item = bar, item
        self.setToolTip(item.get("title") or item.get("id") or "")
        self.clicked.connect(self._left)

    def _paint(self, p, rect, btn):
        px = int(rect.height() * 0.62)
        pm = self.bar.ctx.tray.pixmap(self.item, px, self.devicePixelRatioF())
        c = rect.center()
        p.drawPixmap(int(c.x() - px / 2), int(c.y() - px / 2), pm)

    def _pos(self):
        return self.mapToGlobal(self.rect().center())

    def _left(self):
        if self.item.get("is_menu"):  # menu-only item: left click opens the menu too
            self.bar.tray_context(self.item, self._pos())
        else:
            self.bar.ctx.tray.act(self.item, "Activate", self._pos())

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            super().mousePressEvent(e)
        else:
            e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(e)
        elif self.rect().contains(e.position().toPoint()):
            if e.button() == Qt.MouseButton.RightButton:
                self.bar.tray_context(self.item, self._pos())
            else:
                self.bar.ctx.tray.act(self.item, "SecondaryActivate", self._pos())


def _label(parent, text, px, alpha=255, bold=True):
    lb = QLabel(text, parent)
    lb.setFont(make_font(FONTS.text, px, bold))
    lb.setStyleSheet(f"color: rgba(255,255,255,{alpha}); background: transparent;")
    lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return lb


# ----------------------------------------------------------------------------
# THE BAR  (one per monitor)
# ----------------------------------------------------------------------------
class Bar(QWidget):
    def __init__(self, screen, ctx):
        super().__init__()
        self.ctx, self.scr, self.state = ctx, screen, None
        self.s = ui_scale(screen)
        self.ph = round(BASE_PILL_H * self.s)
        self.room = round(POPUP_ROOM * self.s)
        self.edge = round(EDGE_MARGIN * self.s)
        self._mask_want = self._mask_applied = QRegion()
        self._mask_timer = QTimer(self)
        self._mask_timer.setSingleShot(True)
        self._mask_timer.setInterval(120)
        self._mask_timer.timeout.connect(self._shrink_mask)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setScreen(screen)
        self.resize(screen.geometry().width(), self.ph + self.edge + self.room)
        self._build()
        self.create()
        self.windowHandle().setScreen(screen)
        ctx.ls.apply(self.windowHandle(), self.height(), self.ph + self.edge)
        self.show()
        self.relayout()
        ctx.stats.updated.connect(self.on_stats)
        ctx.tray.changed.connect(self.on_tray)
        ctx.tray.menuReady.connect(self.on_menu)
        self.tick = QTimer(self)
        self.tick.timeout.connect(self.on_tick)
        self.tick.start(1000)
        self.on_tick()
        if ctx.last_state:
            self.apply_state(ctx.last_state)

    # ---- helpers
    def label_font(self):
        return make_font(FONTS.text, self.ph * 0.37, bold=True)

    def goto_ws(self, wid):
        hypr_dispatch([
            [["focusmonitor", self.scr.name()], ["workspace", str(wid)]],  # classic dispatchers
            [[f"hl.dsp.focus({{ workspace = {wid} }})"]],                  # Lua-era form (unverified)
        ])

    # ---- build
    def _build(self):
        ph = self.ph
        ctx = self.ctx

        # pill 1: start
        self.pill_start = Pill(self, ph)
        self.pill_start.setFixedWidth(2 * ph)
        self.btn_start = PressButton(2 * ph, ph, self._paint_start, self.pill_start)
        self.btn_start.clicked.connect(lambda: sh(SM_CMD))

        # pill 2: workspaces | resources | clock
        self.pill_mid = Pill(self, ph)
        lay = QHBoxLayout(self.pill_mid)
        lay.setContentsMargins(int(ph * 0.3), 0, int(ph * 0.45), 0)
        lay.setSpacing(int(ph * 0.55))
        self.ws_box = QWidget(self.pill_mid)
        self.ws_lay = QHBoxLayout(self.ws_box)
        self.ws_lay.setContentsMargins(0, 0, 0, 0)
        self.ws_lay.setSpacing(int(ph * 0.1))
        self.ws_btns = []
        self.res = ResourceBox(self, self.pill_mid)
        self.clock = _label(self.pill_mid, "", ph * 0.37)
        self.clock.setFixedWidth(QFontMetrics(self.label_font()).horizontalAdvance("12:59 AM") + 4)
        lay.addWidget(self.ws_box)
        lay.addWidget(self.res)
        lay.addWidget(self.clock)

        # pill 3: tray chevron | network | notifications
        self.pill_right = Pill(self, ph)
        rl = QHBoxLayout(self.pill_right)
        rl.setContentsMargins(int(ph * 0.25), 0, int(ph * 0.25), 0)
        rl.setSpacing(int(ph * 0.05))
        bw = int(ph * 0.85)
        self.btn_chev = PressButton(bw, ph, self._paint_chev, self.pill_right)
        self.btn_net = PressButton(bw, ph, self._paint_net, self.pill_right)
        self.btn_bell = PressButton(bw, ph, self._paint_bell, self.pill_right)
        self.btn_net.clicked.connect(lambda: sh(NC_CMD))   # per your spec
        self.btn_bell.clicked.connect(lambda: sh(NC_CMD))
        for b in (self.btn_chev, self.btn_net, self.btn_bell):
            rl.addWidget(b)

        # popups (created after the pills so they stack above them)
        self.start_pop = Popup(self, 2 * ph, ph * 0.55)
        _label(self.start_pop.body, "Start", ph * 0.34, 215, False).setGeometry(
            0, 0, self.start_pop.width(), int(ph * 0.5))
        HoverLink(self.start_pop, self._open_start).bind(self.btn_start)

        pw, phh = int(ph * 4.7), int(ph * 2.7)
        self.ws_pop = Popup(self, pw, phh)
        self.ws_title = _label(self.ws_pop.body, "", ph * 0.34, 215, False)
        self.ws_title.setGeometry(0, int(ph * 0.04), pw, int(ph * 0.5))
        pad = int(ph * 0.24)
        self.ws_prev = WsPreview(self.ws_pop.body, self)
        self.ws_prev.setGeometry(pad, int(ph * 0.55), pw - 2 * pad, phh - int(ph * 0.55) - pad)
        self.ws_link = HoverLink(self.ws_pop, self._open_ws)

        has_bat = ctx.stats.has_bat
        self.res_pop = Popup(self, int(ph * 6.1), int(ph * (2.85 if has_bat else 2.2)))
        vl = QVBoxLayout(self.res_pop.body)
        vl.setContentsMargins(0, int(ph * 0.2), 0, int(ph * 0.1))
        self.res_lbls = [_label(self.res_pop.body, "", ph * 0.37) for _ in range(4 if has_bat else 3)]
        for lb in self.res_lbls:
            vl.addWidget(lb)
        HoverLink(self.res_pop, self._open_res).bind(self.res)

        self.tray_pop = Popup(self, int(ph * 2.8), int(ph * 0.95))
        self.tray_lbl = _label(self.tray_pop.body, "", ph * 0.3, 200, False)
        self.tray_lbl.setGeometry(0, int(ph * 0.1), self.tray_pop.width(), int(ph * 0.6))
        HoverLink(self.tray_pop, self._open_tray).bind(self.btn_chev)
        self.tray_pop.stateChanged.connect(self.btn_chev.update)
        self.tray_btns, self._tray_cx = [], 0
        self.tray_menu = MenuView(self, self.tray_pop.body)
        self.tray_menu.picked.connect(self._menu_pick)
        self.menu_stack, self._menu_item, self._menu_wait, self._menu_pos = [], None, None, QPoint()
        self.tray_pop.anim.finished.connect(self._tray_closed)

        self.rebuild_ws(WS_MIN)

    def rebuild_ws(self, n):
        for b in self.ws_btns:
            self.ws_lay.removeWidget(b)
            b.setParent(None)
            b.deleteLater()
        self.ws_btns = []
        for i in range(1, n + 1):
            b = PressButton(self.ph * 0.9, self.ph, self._paint_ws, self.ws_box)
            b.ws = i
            b.clicked.connect(lambda i=i: self.goto_ws(i))
            self.ws_link.bind(b, i)
            self.ws_lay.addWidget(b)
            self.ws_btns.append(b)
        self.pill_mid.layout().activate()
        self.pill_mid.setFixedWidth(self.pill_mid.sizeHint().width())
        self.pill_right.setFixedWidth(self.pill_right.sizeHint().width())
        if self.isVisible():
            self.relayout()

    # ---- layout / input region
    def resizeEvent(self, e):
        if hasattr(self, "pill_right"):
            self.relayout()
        super().resizeEvent(e)

    def relayout(self):
        W, H, ph = self.width(), self.height(), self.ph
        y = H - ph - self.edge
        self.pill_start.move(self.edge, y)
        self.pill_mid.move((W - self.pill_mid.width()) // 2, y)
        self.pill_right.move(W - self.pill_right.width() - self.edge, y)
        self.update_mask()

    def paintEvent(self, e):
        """Pills and open popups are filled as one shape, so a popup is the pill growing
        upward (seamless, and no double opacity where they overlap)."""
        ph = self.ph
        path = QPainterPath()
        for w in (self.pill_start, self.pill_mid, self.pill_right):
            sub = QPainterPath()
            sub.addRoundedRect(QRectF(w.geometry()), ph / 2, ph / 2)
            path = path.united(sub)
        for pop in (self.start_pop, self.ws_pop, self.res_pop, self.tray_pop):
            if not pop.isVisible():
                continue
            vr, r = QRectF(pop.visible_rect()), pop.radius
            sub = QPainterPath()
            sub.addRoundedRect(QRectF(pop.shape_rect()), r, r)
            # square join, reaching into the pill. It must start BELOW the popup's own rounded
            # top corners (vr.top + r), otherwise on a short popup (e.g. Start) its square
            # corners fill them in and the outline looks cut / jagged.
            top = max(vr.top() + r, vr.bottom() - r)
            if top < vr.bottom():
                join = QPainterPath()
                join.addRect(QRectF(vr.left(), top, vr.width(), vr.bottom() - top + ph * 0.5))
                # union explicitly: adding the rect into the same path made the overlap an
                # even-odd "hole" (transparent band under the popup content)
                sub = sub.united(join)
            path = path.united(sub)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(pill_color())
        p.drawPath(path)

    def update_mask(self):
        """Only pills and visible popups take input; the rest of the surface is click-through."""
        r = QRegion()
        for w in (self.pill_start, self.pill_mid, self.pill_right):
            r = r.united(QRegion(w.geometry()))
        for pop in (self.start_pop, self.ws_pop, self.res_pop, self.tray_pop):
            if pop.isVisible():
                r = r.united(QRegion(pop.shape_rect()))
        # Qt only repaints/flushes pixels INSIDE the window mask. If the mask shrinks together
        # with a closing popup, the pixels it just left are never cleared -> jagged leftovers
        # and a "stuck" expanded part. So the mask only grows while things animate and is
        # shrunk to the real shape once everything has been quiet for a moment.
        self._mask_want = r
        self._mask_applied = self._mask_applied.united(r)
        self.setMask(self._mask_applied)
        self._mask_timer.start()

    def _shrink_mask(self):
        self._mask_applied = QRegion(self._mask_want)
        self.setMask(self._mask_applied)

    # ---- painters
    def _paint_start(self, p, rect, btn):
        px = int(self.ph * 0.5)
        if FONTS.arch_cp:
            draw_glyph(p, rect, chr(FONTS.arch_cp), FONTS.fa, px, WHITE)
        else:  # codepoint unknown (see stderr): plain "A" placeholder
            draw_glyph(p, rect, "A", FONTS.text, px, WHITE)

    def _paint_ws(self, p, rect, btn):
        st = self.state or {}
        clients = st.get("by_ws", {}).get(btn.ws, [])
        active = st.get("active", {}).get(self.scr.name()) == btn.ws
        d = self.ph * 0.6
        c = rect.center()
        circle = QRectF(c.x() - d / 2, c.y() - d / 2, d, d)
        if active:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 75))
            p.drawEllipse(circle)
        if clients:
            draw_glyph(p, rect, "radio_button_unchecked", FONTS.mat, d * 1.15, WS_DIM)
            sz = int(d * 0.58)  # icon of the app that was opened first
            pm = self.ctx.icons.icon(clients[0].get("class")).pixmap(QSize(sz, sz))
            p.drawPixmap(int(c.x() - sz / 2), int(c.y() - sz / 2), pm)
        else:
            draw_glyph(p, rect, "radio_button_checked", FONTS.mat, d * 1.15, WS_DIM)

    def _paint_chev(self, p, rect, btn):
        if self.tray_pop.target:
            p.translate(rect.center())
            p.rotate(180)
            p.translate(-rect.center())
        draw_glyph(p, rect, "keyboard_arrow_up", FONTS.mat, self.ph * 0.55, WHITE)

    def _paint_net(self, p, rect, btn):
        st = self.ctx.stats
        if st.net == "ethernet":
            g = "settings_ethernet"
        elif st.net == "wifi" and st.online:
            g = "network_wifi"
        else:
            g = "signal_wifi_bad"
        draw_glyph(p, rect, g, FONTS.mat, self.ph * 0.5, WHITE)

    def _paint_bell(self, p, rect, btn):
        g = "notifications_active" if self.ctx.stats.notif else "notifications"
        draw_glyph(p, rect, g, FONTS.mat, self.ph * 0.5, WHITE)

    # ---- hover callbacks
    def _top(self, w):
        return self.height() - self.ph - self.edge

    def _open_start(self, _):
        self.start_pop.place(self.pill_start.x(), self._top(0))
        self.start_pop.open()

    def _open_ws(self, wid):
        self._fill_ws(wid)
        self.ws_pop.place(self.pill_mid.x(), self._top(0))
        self.ws_pop.open()

    def _fill_ws(self, wid):
        self.ws_title.setText(f"Workspace {wid}")
        st = self.state or {}
        self.ws_prev.clients = st.get("by_ws", {}).get(wid, [])
        self.ws_prev.mon = st.get("mons", {}).get(self.scr.name(), self.ws_prev.mon)
        self.ws_prev.update()

    def _open_res(self, _):
        self._fill_res()
        x = self.res.mapTo(self, QPoint(0, 0)).x() - self.ph * 0.25
        self.res_pop.place(x, self._top(0))
        self.res_pop.open()

    def _fill_res(self):
        st = self.ctx.stats
        lines = [f"RAM : {st.ram_used:.1f}/{st.ram_total:.1f} GB",
                 f"CPU: {st.cpu:.0f}% occupied"]
        if st.has_bat:
            lines.append(f"Battery: {st.bat}%" + (" (charging)" if st.charging else ""))
        lines.append(f"Swap: {st.swap_used:.1f}/{st.swap_total:.1f} GB")
        for lb, t in zip(self.res_lbls, lines):
            lb.setText(t)

    def _open_tray(self, _):
        self._tray_cx = self.btn_chev.mapTo(self, QPoint(0, 0)).x() + self.btn_chev.width() / 2
        self._fill_tray()
        self.tray_pop.open()

    def _fill_tray(self):
        """(Re)build the hidden-icons popup: one button per tray item, or a text if none."""
        ph, pop = self.ph, self.tray_pop
        items = self.ctx.tray.hidden()
        self.tray_menu.hide()
        self.menu_stack = []
        for b in self.tray_btns:
            b.setParent(None)
            b.deleteLater()
        self.tray_btns = []
        if not items:
            msg = "Tray unavailable (" + self.ctx.tray.error + ")" if self.ctx.tray.error \
                else "No hidden icons"
            w, h = int(ph * (2.8 if not self.ctx.tray.error else 6.4)), int(ph * 0.95)
            pop.set_size(w, h)
            self.tray_lbl.setText(msg)
            self.tray_lbl.setGeometry(0, int(ph * 0.1), w, int(ph * 0.6))
            self.tray_lbl.show()
        else:
            cell, pad = int(ph * 0.8), int(ph * 0.2)
            cols = min(len(items), 6)
            rows = -(-len(items) // cols)
            w = max(cols * cell + 2 * pad, int(ph * 1.6))
            h = rows * cell + int(ph * 0.45)
            pop.set_size(w, h)
            self.tray_lbl.hide()
            x0 = (w - cols * cell) // 2
            for i, it in enumerate(items):
                b = TrayButton(self, it, cell, pop.body)
                b.move(x0 + (i % cols) * cell, pad + (i // cols) * cell)
                b.show()
                self.tray_btns.append(b)
        pop.place(self._tray_cx - pop.width() / 2, self._top(0))

    # ---- updates
    def apply_state(self, st):
        self.state = st
        top = max([WS_MIN] + list(st["by_ws"]) + list(st["active"].values()))
        n = min(top, WS_MAX)
        if n != len(self.ws_btns):
            self.rebuild_ws(n)
        for b in self.ws_btns:
            b.update()
        if self.ws_pop.target:
            self._fill_ws(int(self.ws_title.text().split()[-1]))

    def on_stats(self):
        self.res.update()
        self.btn_net.update()
        self.btn_bell.update()
        if self.res_pop.target:
            self._fill_res()

    def on_tray(self):
        if self.tray_pop.target and not self.menu_stack:  # open: show the new icons right away
            self._fill_tray()

    # ---- tray item menus (right click)
    def tray_context(self, item, pos):
        tr = self.ctx.tray
        self._menu_pos = pos
        if tr.has_menu(item):
            self._menu_wait = item["key"]
            tr.request_menu(item)
        else:  # no dbusmenu: ask the app to show its own menu
            tr.act(item, "ContextMenu", pos)

    def on_menu(self, key, tree):
        if key != self._menu_wait:
            return
        self._menu_wait = None
        item = next((i for i in self.ctx.tray.hidden() if i["key"] == key), None)
        if item is None or not self.tray_pop.target:
            return
        if not tree or not tree["children"]:
            self.ctx.tray.act(item, "ContextMenu", self._menu_pos)
            return
        self._menu_item = item
        self.menu_stack = [tree["children"]]
        self._show_menu()

    def _show_menu(self):
        ph, pop, view = self.ph, self.tray_pop, self.tray_menu
        back = [dict(id=-1, label="Back", back=True, sep=False, enabled=True, visible=True,
                     children=[], sub=False, toggle="", state=-1, icon="")]
        view.set_rows((back if len(self.menu_stack) > 1 else []) + self.menu_stack[-1])
        w, h = view.need_size()
        # never smaller than the icon grid it grew out of, so the mouse stays inside the popup
        w = max(w, pop.width(), int(ph * 2.4))
        h = min(max(h, pop.height()), self.room - int(ph * 0.15))
        for b in self.tray_btns:
            b.hide()
        self.tray_lbl.hide()
        pop.set_size(w, h)
        view.setGeometry(0, 0, w, h)
        view.show()
        view.raise_()
        pop.place(self._tray_cx - w / 2, self._top(0))

    def _menu_pick(self, row):
        if row.get("back"):
            self.menu_stack.pop()
            self._show_menu()
        elif row.get("sub") and row.get("children"):
            self.menu_stack.append(row["children"])
            self._show_menu()
        else:
            self.ctx.tray.menu_click(self._menu_item, row["id"])
            self.tray_pop.close_anim()

    def _tray_closed(self):
        if not self.tray_pop.target:
            self.tray_menu.hide()
            self.menu_stack, self._menu_wait = [], None

    def on_tick(self):
        self.clock.setText(QTime.currentTime().toString("h:mm AP"))


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
class Ctx:
    pass


def main():
    global FONTS
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setDesktopFileName("better-hyprland-bar")
    FONTS = Fonts()

    ctx = Ctx()
    ctx.ls = LayerShell()
    ctx.ls.use()
    ctx.icons = IconResolver()
    ctx.stats = Stats()
    ctx.tray = TrayBackend()

    ctx.last_state = None
    bars, watched = {}, set()

    def add(screen):
        if screen not in bars:
            bars[screen] = Bar(screen, ctx)
        if screen not in watched:  # resolution / scale change at runtime -> rebuild at new size
            watched.add(screen)
            screen.geometryChanged.connect(
                lambda _g, s=screen: QTimer.singleShot(300, lambda: rebuild(s)))

    def remove(screen):
        b = bars.pop(screen, None)
        if b:
            b.hide()
            b.deleteLater()

    def rebuild(screen):
        if screen in app.screens() and screen in bars:
            remove(screen)
            add(screen)

    def on_state(st):
        ctx.last_state = st
        for b in list(bars.values()):
            b.apply_state(st)

    hypr = HyprWatcher()
    hypr.changed.connect(on_state)
    for sc in app.screens():
        add(sc)
    app.screenAdded.connect(add)
    app.screenRemoved.connect(remove)
    hypr.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
