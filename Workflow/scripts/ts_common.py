"""Shared helpers for talking to the Tailscale CLI."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

TAILSCALE_PATHS: tuple[Path, ...] = (
    Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale"),
    Path("/usr/local/bin/tailscale"),
    Path("/opt/homebrew/bin/tailscale"),
)

MULLVAD_TAG = "tag:mullvad-exit-node"


class TailscaleError(Exception):
    """Raised when the Tailscale CLI returns a non-zero exit status."""


@dataclass(frozen=True)
class Location:
    country: str = ""
    country_code: str = ""
    city: str = ""


@dataclass(frozen=True)
class Device:
    key: str
    name: str
    dns: str
    ipv4: str
    ipv6: str
    os: str
    online: bool
    is_self: bool
    last_seen: str
    ssh: bool
    exit_node_option: bool = False
    exit_node: bool = False
    tags: tuple[str, ...] = ()
    location: Location | None = None

    @property
    def is_mullvad(self) -> bool:
        return MULLVAD_TAG in self.tags


# --- CLI execution --------------------------------------------------------


def _tailscale_binary() -> Path:
    for path in TAILSCALE_PATHS:
        if path.exists():
            return path
    return TAILSCALE_PATHS[0]  # fallback so the error surfaces clearly


def run_command(*args: str) -> str:
    """Run the Tailscale CLI with the given arguments and return stdout."""
    cmd = [str(_tailscale_binary()), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        raise TailscaleError(message or f"tailscale {' '.join(args)} failed")
    return proc.stdout.strip()


def get_status(peers: bool = True) -> dict[str, Any]:
    raw = run_command("status", "--json", f"--peers={str(peers).lower()}")
    return json.loads(raw)


# --- Device parsing -------------------------------------------------------


def _location_from_raw(raw: dict[str, Any] | None) -> Location | None:
    if not raw:
        return None
    return Location(
        country=raw.get("Country", ""),
        country_code=raw.get("CountryCode", ""),
        city=raw.get("City", ""),
    )


def _device_from_node(node: dict[str, Any], *, is_self: bool) -> Device:
    ips: list[str] = node.get("TailscaleIPs") or []
    dns = (node.get("DNSName") or "").rstrip(".")
    raw_os = node.get("OS") or ""
    return Device(
        key=node.get("ID", ""),
        name=dns.split(".")[0] if dns else node.get("HostName", ""),
        dns=dns,
        ipv4=ips[0] if len(ips) > 0 else "",
        ipv6=ips[1] if len(ips) > 1 else "",
        os="Linux" if raw_os == "linux" else raw_os,
        online=bool(node.get("Online")),
        is_self=is_self,
        last_seen=node.get("LastSeen", ""),
        ssh=bool(node.get("sshHostKeys")),
        exit_node_option=bool(node.get("ExitNodeOption")),
        exit_node=bool(node.get("ExitNode")),
        tags=tuple(node.get("Tags") or ()),
        location=_location_from_raw(node.get("Location")),
    )


def get_devices(status: dict[str, Any]) -> list[Device]:
    devices: list[Device] = []
    if self_node := status.get("Self"):
        devices.append(_device_from_node(self_node, is_self=True))
    for peer in (status.get("Peer") or {}).values():
        devices.append(_device_from_node(peer, is_self=False))
    return devices


def sort_devices(devices: Iterable[Device]) -> list[Device]:
    """Self first, then connected devices, then alphabetically."""
    return sorted(devices, key=lambda d: (not d.is_self, not d.online, d.name.lower()))


# --- Formatting -----------------------------------------------------------

_FRACTIONAL_SECONDS_RE = re.compile(r"(\d+)(.*)")


def format_last_seen(iso_timestamp: str) -> str:
    """Render a Tailscale RFC3339 timestamp as a short local date/time."""
    if not iso_timestamp:
        return "unknown"
    try:
        dt = datetime.fromisoformat(_normalize_iso(iso_timestamp)).astimezone()
    except ValueError:
        return iso_timestamp
    return dt.strftime("%b %-d, %-I:%M %p")


def _normalize_iso(iso_timestamp: str) -> str:
    """Trim sub-microsecond fractional seconds so ``datetime`` can parse it."""
    normalized = iso_timestamp.replace("Z", "+00:00")
    if "." not in normalized:
        return normalized
    head, tail = normalized.split(".", 1)
    match = _FRACTIONAL_SECONDS_RE.match(tail)
    if not match:
        return normalized
    fractional = match.group(1)[:6].ljust(6, "0")
    return f"{head}.{fractional}{match.group(2)}"


# --- Error rendering ------------------------------------------------------


def classify_error(err: Exception) -> tuple[str, str]:
    """Turn a raw exception into a (title, subtitle) suitable for Alfred."""
    message = str(err).lower()
    if "no such file" in message or "not found" in message:
        return (
            "Can't find the Tailscale CLI",
            "Install Tailscale from tailscale.com/download/mac.",
        )
    if "is tailscale running" in message or "connection refused" in message:
        return ("Can't connect to Tailscale", "Make sure Tailscale is running.")
    if "not logged in" in message or "logged out" in message:
        return ("Not logged in", "Log in to Tailscale and try again.")
    return ("Something went wrong", str(err))
