"""
layer_namespace.py - sets the Wayland layer-shell namespace ("scope") of a Qt window.

layer-shell-qt has no Python binding, so this talks to it directly:
  LayerShellQt::Window::get(QWindow*)  -> returns the per-window LayerShellQt::Window (a QObject)
  its Q_PROPERTY "scope"               -> the namespace Hyprland sees (hyprctl layers)

The scope is read when the layer surface is created, so call this AFTER the widget
is built and BEFORE it is shown for the first time.

Hyprland (hyprland.lua):
    hl.layer_rule({ match = { namespace = "^start-system-bh\\..*$" }, blur = true })
"""
import ctypes

from PyQt6 import sip
from PyQt6.QtCore import QObject

# C++ symbol of LayerShellQt::Window::get(QWindow *)
_GET_SYMBOL = "_ZN12LayerShellQt6Window3getEP7QWindow"
_LIB_NAMES = ("libLayerShellQtInterface.so.6", "libLayerShellQtInterface.so")


def set_layer_namespace(widget, namespace):
    """Give `widget`'s layer surface the namespace `namespace`. Returns True on success."""
    try:
        lib = None
        for name in _LIB_NAMES:
            try:
                lib = ctypes.CDLL(name)
                break
            except OSError:
                continue
        if lib is None:
            print("[warn] libLayerShellQtInterface not found (install layer-shell-qt)")
            return False

        get = getattr(lib, _GET_SYMBOL)
        get.restype = ctypes.c_void_p
        get.argtypes = [ctypes.c_void_p]

        widget.winId()                      # creates the QWindow (not mapped yet)
        qwindow = widget.windowHandle()
        if qwindow is None:
            print("[warn] no QWindow for the widget, namespace not set")
            return False

        ptr = get(sip.unwrapinstance(qwindow))
        if not ptr:
            print("[warn] LayerShellQt::Window::get returned null, namespace not set")
            return False

        shell_window = sip.wrapinstance(ptr, QObject)
        shell_window.setProperty("scope", namespace)
        return shell_window.property("scope") == namespace
    except Exception as ex:                 # never block the menu from opening
        print("[warn] could not set layer namespace:", ex)
        return False
