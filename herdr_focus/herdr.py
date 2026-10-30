"""The Herdr side: socket calls, which session we serve, where state and logs live."""

import json
import os
import socket
import time
from pathlib import Path

SOCKET = os.environ.get("HERDR_SOCKET_PATH", "")
# One watcher and one state per session. Same rule as herdup's _herdup_sock:
# sessions/<name>/herdr.sock, and `default` lives at the config root.
SESSION = Path(SOCKET).parent.name if Path(SOCKET).parent.parent.name == "sessions" else "default"
STATE_DIR = Path(os.environ.get("HERDR_PLUGIN_STATE_DIR") or "/tmp/herdr-focus") / SESSION
CONFIG_DIR = Path(os.environ.get("HERDR_PLUGIN_CONFIG_DIR") or STATE_DIR)
PLUGIN_ID = os.environ.get("HERDR_PLUGIN_ID", "herdr-focus")


def log(msg: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_DIR / "focus.log", "a") as f:
        f.write(f"{time.strftime('%F %T')} {msg}\n")


def call(method: str, params: dict) -> dict:
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(SOCKET)
        s.sendall((json.dumps({"id": "focus", "method": method, "params": params}) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(1 << 16)
            if not chunk:
                break
            buf += chunk
    reply = json.loads(buf)
    if "error" in reply:
        raise RuntimeError(f"{method}: {reply['error']}")
    return reply["result"]


def pid_alive(path: Path) -> bool:
    try:
        os.kill(int(path.read_text()), 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False
