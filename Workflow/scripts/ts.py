"""Tailscale script filter.

Emits Alfred script-filter JSON listing Tailnet devices plus two command
rows (Open admin console, Toggle Tailscale) that surface once the user
starts typing. Each item declares an ``action`` variable that the
downstream Conditional utility routes to the matching Alfred object
(Copy to Clipboard, Open URL, Terminal Command, or the Python dispatcher).
"""

from __future__ import annotations

import json
import sys
from typing import Any

from ts_common import (
    Device,
    classify_error,
    format_last_seen,
    get_devices,
    get_status,
    sort_devices,
)

ADMIN_URL = "https://login.tailscale.com/admin/machines"

ACTION_COPY = "COPY"
ACTION_OPEN_URL = "OPEN_URL"
ACTION_SSH = "SSH"
ACTION_TOGGLE = "TOGGLE"
ACTION_SET_EXIT_NODE = "SET_EXIT_NODE"

ICON_ONLINE = "icons/connected.png"
ICON_OFFLINE = "icons/lastseen.png"

SUBTITLE_SEPARATOR = "  ·  "

EXIT_NODE_PREFIX = "exit"
ACTIVE_MARKER = "✓ "

Item = dict[str, Any]


# --- Matching -------------------------------------------------------------


def matches(query: str, *fields: str) -> bool:
    """Case-insensitive AND-of-tokens substring match."""
    if not query:
        return True
    haystack = " ".join(f.lower() for f in fields if f)
    return all(token in haystack for token in query.lower().split())


# --- Device rendering -----------------------------------------------------


def _device_subtitle(device: Device) -> str:
    parts: list[str] = []
    if device.ipv4:
        parts.append(device.ipv4)
    if device.os:
        parts.append(device.os)
    if device.is_self:
        parts.append("this device")
    parts.append(
        "connected"
        if device.online
        else f"last seen {format_last_seen(device.last_seen)}"
    )
    return SUBTITLE_SEPARATOR.join(parts)


def _device_modifiers(device: Device) -> dict[str, Item]:
    mods: dict[str, Item] = {}
    if device.ipv4:
        mods["cmd"] = {
            "arg": device.ipv4,
            "variables": {"action": ACTION_COPY},
            "subtitle": f"Copy IPv4  ({device.ipv4})",
            "valid": True,
        }
    if device.ipv6:
        mods["alt"] = {
            "arg": device.ipv6,
            "variables": {"action": ACTION_COPY},
            "subtitle": f"Copy IPv6  ({device.ipv6})",
            "valid": True,
        }
    if device.dns and device.ssh:
        mods["shift"] = {
            "arg": device.dns,
            "variables": {"action": ACTION_SSH},
            "subtitle": f"SSH to {device.dns}",
            "valid": True,
        }
    return mods


def _device_item(device: Device) -> Item:
    primary = device.dns or device.ipv4
    return {
        # "uid": device.key or device.name,
        "title": device.name or device.dns or "(unnamed)",
        "subtitle": _device_subtitle(device),
        "arg": primary,
        "variables": {"action": ACTION_COPY},
        "match": " ".join(
            filter(None, [device.name, device.dns, device.ipv4, device.ipv6])
        ),
        "icon": {"path": ICON_ONLINE if device.online else ICON_OFFLINE},
        "mods": _device_modifiers(device),
        "text": {"copy": primary},
    }


# --- Command rows ---------------------------------------------------------


def _command_items(*, self_online: bool) -> list[Item]:
    state = "connected" if self_online else "disconnected"
    next_state = "disconnect" if self_online else "connect"
    return [
        {
            "uid": "cmd-admin",
            "title": "Open admin console",
            "subtitle": ADMIN_URL,
            "arg": ADMIN_URL,
            "variables": {"action": ACTION_OPEN_URL},
            "autocomplete": "admin",
            "match": "admin",
            "icon": {"path": ICON_ONLINE},
        },
        {
            "uid": "cmd-toggle",
            "title": "Toggle Tailscale",
            "subtitle": f"Currently {state} — press ↵ to {next_state}",
            "arg": "",
            "variables": {"action": ACTION_TOGGLE},
            "autocomplete": "toggle",
            "match": "toggle on off connect disconnect up down",
            "icon": {"path": ICON_ONLINE if self_online else ICON_OFFLINE},
        },
        {
            "uid": "cmd-exit",
            "title": "Exit node",
            "subtitle": "Pick a peer to route traffic through",
            "valid": False,
            "autocomplete": f"{EXIT_NODE_PREFIX} ",
            "match": "exit node route vpn",
            "icon": {"path": ICON_ONLINE},
        },
    ]


# --- Exit node sublist ----------------------------------------------------


def _is_exit_node_query(query: str) -> bool:
    parts = query.split(maxsplit=1)
    return bool(parts) and parts[0].lower() == EXIT_NODE_PREFIX


def _exit_node_subquery(query: str) -> str:
    parts = query.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


def _none_exit_node_item(*, active: bool) -> Item:
    title = f"{ACTIVE_MARKER}None" if active else "None"
    subtitle = (
        "In use — no exit node configured"
        if active
        else "Disable exit node"
    )
    return {
        "uid": "exit-none",
        "title": title,
        "subtitle": subtitle,
        "arg": "",
        "variables": {"action": ACTION_SET_EXIT_NODE},
        "valid": not active,
        "match": "none disable off clear",
        "icon": {"path": ICON_OFFLINE},
    }


def _exit_node_item(device: Device) -> Item:
    target = device.ipv4 or device.name
    parts: list[str] = []
    if device.ipv4:
        parts.append(device.ipv4)
    if device.os:
        parts.append(device.os)
    if device.exit_node:
        parts.append("in use — press ↵ to disable")
    elif not device.online:
        parts.append(f"last seen {format_last_seen(device.last_seen)}")
    else:
        parts.append("press ↵ to route traffic here")
    title = f"{ACTIVE_MARKER}{device.name}" if device.exit_node else device.name
    arg = "" if device.exit_node else target
    return {
        "title": title or "(unnamed)",
        "subtitle": SUBTITLE_SEPARATOR.join(parts),
        "arg": arg,
        "variables": {"action": ACTION_SET_EXIT_NODE},
        "match": " ".join(filter(None, [device.name, device.dns, device.ipv4])),
        "icon": {"path": ICON_ONLINE if device.online else ICON_OFFLINE},
        "valid": True,
    }


def _exit_node_items(
    devices: list[Device], subquery: str, *, any_active: bool
) -> list[Item]:
    candidates = [
        d for d in devices
        if d.exit_node_option and not d.is_self and not d.is_mullvad
    ]
    candidates.sort(key=lambda d: (not d.exit_node, not d.online, d.name.lower()))
    items: list[Item] = []
    if matches(subquery, "none disable off clear"):
        items.append(_none_exit_node_item(active=not any_active))
    for d in candidates:
        if matches(subquery, d.name, d.dns, d.ipv4, d.ipv6):
            items.append(_exit_node_item(d))
    return items


def _no_exit_nodes_item() -> Item:
    return {
        "title": "No exit nodes available",
        "subtitle": "No peers in your tailnet advertise as an exit node",
        "valid": False,
        "icon": {"path": ICON_OFFLINE},
    }


def _offline_toggle_fallback() -> Item:
    """Shown when Tailscale is unreachable but the user is asking to connect."""
    return {
        "uid": "cmd-toggle",
        "title": "Toggle Tailscale",
        "subtitle": "Currently disconnected — press ↵ to connect",
        "arg": "",
        "variables": {"action": ACTION_TOGGLE},
        "autocomplete": "toggle",
        "icon": {"path": ICON_OFFLINE},
    }


def _no_results_item(query: str) -> Item:
    return {
        "title": "No matches",
        "subtitle": f"Nothing in the tailnet matches “{query}”",
        "valid": False,
        "icon": {"path": ICON_OFFLINE},
    }


def _error_item(title: str, subtitle: str) -> Item:
    return {
        "title": title,
        "subtitle": subtitle,
        "valid": False,
        "icon": {"path": ICON_OFFLINE},
    }


# --- Entry point ----------------------------------------------------------


def _emit(items: list[Item]) -> None:
    print(json.dumps({"items": items}))


def main(argv: list[str]) -> None:
    query = " ".join(argv[1:]).strip()

    try:
        status = get_status()
    except Exception as err:
        if query and matches(query, "toggle on connect up"):
            _emit([_offline_toggle_fallback()])
            return
        title, subtitle = classify_error(err)
        _emit([_error_item(title, subtitle)])
        return

    all_devices = get_devices(status)
    any_active_exit_node = any(d.exit_node for d in all_devices)
    devices = sort_devices(d for d in all_devices if not d.is_mullvad)

    if _is_exit_node_query(query):
        items = _exit_node_items(
            devices,
            _exit_node_subquery(query),
            any_active=any_active_exit_node,
        )
        if not items:
            items.append(_no_exit_nodes_item())
        _emit(items)
        return

    items: list[Item] = [
        _device_item(d)
        for d in devices
        if matches(query, d.name, d.dns, d.ipv4, d.ipv6)
    ]

    if query:
        self_online = bool(status.get("Self", {}).get("Online"))
        items.extend(
            cmd
            for cmd in _command_items(self_online=self_online)
            if matches(query, cmd["title"], cmd.get("match", ""))
        )

    if not items:
        items.append(_no_results_item(query))

    _emit(items)


if __name__ == "__main__":
    main(sys.argv)
