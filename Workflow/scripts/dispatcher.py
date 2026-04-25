"""Dispatcher for non-routable actions from the `ts` script filter.

With Copy to Clipboard, Open URL, and Terminal Command handled by native
Alfred objects, only ``TOGGLE`` still reaches this script. It reads the
chosen action from the ``action`` workflow variable (exported as an env
var by Alfred) and prints a one-line message for the downstream
Post Notification object.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Callable

from ts_common import classify_error, get_status, run_command

UP_SETTLE_SECONDS = 2


def _tailscale_is_online() -> bool:
    try:
        status = get_status(peers=False)
    except Exception:
        return False
    return bool(status.get("Self", {}).get("Online"))


def _connect() -> str:
    run_command("up")
    time.sleep(UP_SETTLE_SECONDS)
    try:
        status = get_status(peers=False)
    except Exception:
        return "Connected"
    suffix = status.get("MagicDNSSuffix") or status.get("CurrentTailnet", {}).get(
        "Name", ""
    )
    return f"Connected on {suffix}" if suffix else "Connected"


def _disconnect() -> str:
    run_command("down")
    return "Disconnected"


def _toggle(_: str) -> str:
    return _disconnect() if _tailscale_is_online() else _connect()


def _set_exit_node(target: str) -> str:
    target = target.strip()
    if target:
        run_command("set", f"--exit-node={target}")
        return f"Routing through {target}"
    run_command("set", "--exit-node=")
    return "Exit node disabled"


ACTIONS: dict[str, Callable[[str], str]] = {
    "TOGGLE": _toggle,
    "SET_EXIT_NODE": _set_exit_node,
}


def main() -> None:
    action = os.environ.get("action", "").strip()
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    handler = ACTIONS.get(action)
    if handler is None:
        print(f"Unknown action: {action or '(empty)'}", end="")
        return
    try:
        message = handler(target)
    except Exception as err:
        title, subtitle = classify_error(err)
        message = f"{title}: {subtitle}"
    print(message, end="")


if __name__ == "__main__":
    main()
