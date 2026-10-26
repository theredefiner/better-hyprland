"""org.freedesktop.Notifications server for Better Hyprland (no Qt: GLib/Gio only).

Needs PyGObject (Arch: `sudo pacman -S python-gobject`). The callbacks run inside the GLib main
loop; Qt's own event loop on Linux is a GLib loop too, so inside a PyQt6 app they just work.

    server = NotificationServer(on_notify=..., on_close=..., on_name_lost=...)
    server.start()
    server.closed(id, reason)       # emit NotificationClosed
    server.action(id, "key")        # emit ActionInvoked
"""
from __future__ import annotations

import logging
from collections.abc import Callable

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

log = logging.getLogger("better-hyprland.dbus")

BUS_NAME = "org.freedesktop.Notifications"
OBJECT_PATH = "/org/freedesktop/Notifications"
INTERFACE = "org.freedesktop.Notifications"

CAPABILITIES = ["actions", "body", "body-markup", "icon-static", "persistence"]

# Why a notification was closed (NotificationClosed's reason)
REASON_EXPIRED = 1
REASON_DISMISSED = 2
REASON_CLOSED_BY_CALL = 3

_XML = f"""
<node>
  <interface name="{INTERFACE}">
    <method name="GetCapabilities"><arg direction="out" name="capabilities" type="as"/></method>
    <method name="Notify">
      <arg direction="in" name="app_name" type="s"/>
      <arg direction="in" name="replaces_id" type="u"/>
      <arg direction="in" name="app_icon" type="s"/>
      <arg direction="in" name="summary" type="s"/>
      <arg direction="in" name="body" type="s"/>
      <arg direction="in" name="actions" type="as"/>
      <arg direction="in" name="hints" type="a{{sv}}"/>
      <arg direction="in" name="expire_timeout" type="i"/>
      <arg direction="out" name="id" type="u"/>
    </method>
    <method name="CloseNotification"><arg direction="in" name="id" type="u"/></method>
    <method name="GetServerInformation">
      <arg direction="out" name="name" type="s"/>
      <arg direction="out" name="vendor" type="s"/>
      <arg direction="out" name="version" type="s"/>
      <arg direction="out" name="spec_version" type="s"/>
    </method>
    <signal name="NotificationClosed"><arg name="id" type="u"/><arg name="reason" type="u"/></signal>
    <signal name="ActionInvoked"><arg name="id" type="u"/><arg name="action_key" type="s"/></signal>
  </interface>
</node>
"""


def split_actions(flat: list[str]) -> list[tuple[str, str]]:
    """["key1", "Label 1", "key2", "Label 2"] -> [("key1", "Label 1"), ...]"""
    return [(flat[i], flat[i + 1]) for i in range(0, len(flat) - 1, 2)]


def parse_image_data(value) -> dict | None:
    """The `image-data` hint: (width, height, rowstride, has_alpha, bits_per_sample, channels, bytes)."""
    try:
        width, height, rowstride, has_alpha, bits, channels, data = value
        if bits != 8 or width <= 0 or height <= 0 or len(data) < rowstride * (height - 1) + width * channels:
            return None
        return {
            "width": int(width),
            "height": int(height),
            "rowstride": int(rowstride),
            "has_alpha": bool(has_alpha),
            "channels": int(channels),
            "data": bytes(data),
        }
    except (TypeError, ValueError):
        return None


class NotificationServer:
    def __init__(
        self,
        on_notify: Callable[[dict], int],
        on_close: Callable[[int], None],
        on_name_lost: Callable[[], None] | None = None,
    ) -> None:
        self._on_notify = on_notify
        self._on_close = on_close
        self._on_name_lost = on_name_lost
        self._connection: Gio.DBusConnection | None = None
        self._owner_id = 0
        self._node = Gio.DBusNodeInfo.new_for_xml(_XML)

    # -- lifecycle
    def start(self) -> None:
        self._owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT | Gio.BusNameOwnerFlags.REPLACE,
            self._bus_acquired,
            self._name_acquired,
            self._name_lost,
        )

    def stop(self) -> None:
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = 0

    def _bus_acquired(self, connection, _name) -> None:
        self._connection = connection
        connection.register_object(OBJECT_PATH, self._node.interfaces[0], self._method_call, None, None)

    def _name_acquired(self, _connection, name) -> None:
        log.debug("owning %s", name)

    def _name_lost(self, _connection, name) -> None:
        log.warning("could not own %s (another notification daemon is running?)", name)
        if self._on_name_lost is not None:
            self._on_name_lost()

    # -- incoming calls
    def _method_call(self, _connection, _sender, _path, _interface, method, parameters, invocation) -> None:
        try:
            if method == "GetCapabilities":
                invocation.return_value(GLib.Variant("(as)", (CAPABILITIES,)))
            elif method == "GetServerInformation":
                invocation.return_value(GLib.Variant("(ssss)", ("Better Hyprland", "theredefiner", "1.0", "1.2")))
            elif method == "CloseNotification":
                (notification_id,) = parameters.unpack()
                self._on_close(int(notification_id))
                invocation.return_value(None)
            elif method == "Notify":
                app_name, replaces_id, app_icon, summary, body, actions, hints, timeout = parameters.unpack()
                notification_id = self._on_notify(
                    {
                        "app_name": app_name,
                        "id": int(replaces_id),
                        "app_icon": app_icon,
                        "summary": summary,
                        "body": body,
                        "actions": split_actions(list(actions)),
                        "hints": dict(hints),
                        "timeout": int(timeout),
                    }
                )
                invocation.return_value(GLib.Variant("(u)", (int(notification_id),)))
            else:
                invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
        except Exception as error:  # a bad client must never take the daemon down
            log.exception("error in %s", method)
            invocation.return_dbus_error("org.freedesktop.DBus.Error.Failed", str(error))

    # -- outgoing signals
    def closed(self, notification_id: int, reason: int) -> None:
        self._emit("NotificationClosed", GLib.Variant("(uu)", (int(notification_id), int(reason))))

    def action(self, notification_id: int, key: str) -> None:
        self._emit("ActionInvoked", GLib.Variant("(us)", (int(notification_id), key)))

    def _emit(self, name: str, parameters) -> None:
        if self._connection is not None:
            self._connection.emit_signal(None, OBJECT_PATH, INTERFACE, name, parameters)
