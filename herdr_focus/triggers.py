"""When the cover opens: the watcher (idle, app switch), tab revisits, and the manual action."""

import ctypes
import ctypes.util
import fcntl
import json
import os
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

from .config import config, herdr_pane_gaps
from .herdr import PLUGIN_ID, SESSION, SOCKET, STATE_DIR, call, log, pid_alive

# Each terminal app, and the AppleScript that names the tty of its selected tab.
TERMINALS = {
    "Ghostty.app": 'tell application "Ghostty" to get tty of focused terminal of selected tab of front window',
    "iTerm.app": 'tell application "iTerm2" to get tty of current session of current window',
}
ENTRY = Path(__file__).resolve().parent.parent / "focus.py"

_libproc = ctypes.CDLL(ctypes.util.find_library("proc"))
_libc = ctypes.CDLL(None)
_libc.devname.restype = ctypes.c_char_p
_libobjc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
_libobjc.objc_getClass.restype = _libobjc.sel_registerName.restype = ctypes.c_void_p
_libobjc.objc_getClass.argtypes = _libobjc.sel_registerName.argtypes = [ctypes.c_char_p]
ctypes.CDLL("/System/Library/Frameworks/Foundation.framework/Foundation")  # NSAppleScript
_idle = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics").CGEventSourceSecondsSinceLastEventType
_idle.restype = ctypes.c_double


def show(reason: str = "manual") -> None:
    t0 = time.time()
    if pid_alive(STATE_DIR / "cover.pid"):
        log(f"cover already open, skipped ({reason})")
        return
    pane = call("session.snapshot", {})["snapshot"].get("focused_pane_id")
    if not pane:
        return
    # Snapshot before the overlay opens: the overlay is a real split, so it
    # halves the focused pane and the app inside rewraps its screen.
    layout = call("pane.layout", {"pane_id": pane})["layout"]
    layout["pane_gaps"] = herdr_pane_gaps()
    for p in layout["panes"]:
        try:
            p["text"] = call("pane.read", {"pane_id": p["pane_id"], "source": "visible", "format": "ansi"})["read"]["text"]
        except Exception as e:
            p["text"] = f"(could not read pane: {e})"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = STATE_DIR / "snapshot.json"
    snapshot.write_text(json.dumps(layout))
    call(
        "plugin.pane.open",
        {
            "plugin_id": PLUGIN_ID,
            "entrypoint": "cover",
            "focus": True,  # overlays always cover the active pane; no target_pane_id
            "env": {"FOCUS_SNAPSHOT": str(snapshot), "FOCUS_T0": str(t0)},
        },
    )
    log(f"cover opened ({reason}) over {pane} in {time.time() - t0:.2f}s")


# --- is the user looking at this session? ------------------------------------


def hid_idle_seconds() -> float:
    """Seconds since the last keyboard or mouse event anywhere (kCGAnyInputEventType)."""
    return _idle(1, 0xFFFFFFFF)  # kCGEventSourceStateHIDSystemState


def client_session(argv: list[str]) -> str | None:
    """The session a `herdr` client command line attaches to (herdup's _herdup_winch rules)."""
    if not argv or Path(argv[0]).name != "herdr" or argv[-1] == "server":
        return None
    if len(argv) == 4 and argv[1:3] == ["session", "attach"]:
        return argv[3]
    if len(argv) == 3 and argv[1] == "--session":
        return argv[2]
    if len(argv) == 1:
        return "default"  # bare `herdr` attaches to default
    return None


def _tty(pid: int) -> str | None:
    """A process's controlling terminal, e.g. /dev/ttys059 (PROC_PIDTBSDINFO's e_tdev)."""
    info = ctypes.create_string_buffer(136)
    if _libproc.proc_pidinfo(pid, 3, 0, info, 136) != 136:
        return None
    name = _libc.devname(struct.unpack_from("I", info, 108)[0], 0o020000)  # S_IFCHR
    return f"/dev/{name.decode()}" if name else None


def _argv(pid: int) -> list[str]:
    """A process's arguments via sysctl KERN_PROCARGS2: argc, exec path, padding, then argv."""
    mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2
    size = ctypes.c_size_t(65536)
    buf = ctypes.create_string_buffer(size.value)
    if _libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0):
        return []
    argc = struct.unpack_from("i", buf)[0]
    parts = [p for p in buf.raw[4 : size.value].split(b"\0")[1:] if p]
    return [p.decode(errors="replace") for p in parts[:argc]]


def session_ttys() -> set[str]:
    """Terminals (ttys) showing a client of this session. Several clients: any of them counts. ~3 ms."""
    n = _libproc.proc_listallpids(None, 0)
    pids = (ctypes.c_int * (n + 64))()
    n = _libproc.proc_listallpids(pids, ctypes.sizeof(pids))
    comm = ctypes.create_string_buffer(64)
    ttys = set()
    for pid in pids[:n]:
        # PROC_PIDT_SHORTBSDINFO: the 16-char command name at offset 16, one cheap call per process.
        if _libproc.proc_pidinfo(pid, 13, 0, comm, 64) == 64 and comm.raw[16:32].split(b"\0")[0] == b"herdr":
            if client_session(_argv(pid)) == SESSION and (tty := _tty(pid)):
                ttys.add(tty)
    return ttys


def _objc(obj, sel: bytes, *args, argtypes=()):
    """obj.sel(args...) through objc_msgSend; objects come back as raw pointers."""
    send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(("objc_msgSend", _libobjc))
    return send(obj, _libobjc.sel_registerName(sel), *args)


_scripts: dict = {}


def selected_tty(app: str) -> str | None:
    """The tty of the tab the user sees in a terminal app. One window, many tabs: only this one is visible.
    NSAppleScript in-process, compiled once: ~3 ms, where an `osascript` process costs ~200 ms."""
    if app not in _scripts:
        source = _objc(_libobjc.objc_getClass(b"NSString"), b"stringWithUTF8String:", TERMINALS[app].encode(), argtypes=(ctypes.c_char_p,))
        script = _objc(_libobjc.objc_getClass(b"NSAppleScript"), b"alloc")
        _scripts[app] = _objc(script, b"initWithSource:", source, argtypes=(ctypes.c_void_p,))
    result = _objc(_scripts[app], b"executeAndReturnError:", None, argtypes=(ctypes.c_void_p,))
    text = result and _objc(result, b"stringValue")
    return ctypes.string_at(_objc(text, b"UTF8String")).decode() if text else None


def frontmost() -> tuple[str | None, str]:
    """(terminal app if one is in front, the front app's name for the log)."""
    # shortcut: LaunchServices' "front" can lag or stick (see herdup); fine for minute-scale breaks.
    asn = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True).stdout.strip()
    out = subprocess.run(["lsappinfo", "info", "-only", "bundlepath", asn], capture_output=True, text=True).stdout
    name = re.search(r"/([^/]+)\.app", out)
    return next((app for app in TERMINALS if f"/{app}" in out), None), name.group(1) if name else "?"


# --- the three triggers ----------------------------------------------------------


def daemon() -> None:
    (STATE_DIR / "daemon.pid").write_text(str(os.getpid()))
    log(f"watcher started for session {SESSION}")
    idle_fired = False
    hidden_since = None
    last_seen = None
    while True:
        cfg = config()  # cheap: re-read only when config.toml changes
        if not os.path.exists(SOCKET):
            log("socket gone, watcher exiting")
            return
        try:
            front, name = frontmost()
            visible = front is not None and selected_tty(front) in session_ttys()
            if cfg["debug"] and (name, visible) != last_seen:
                log(f"debug front={name} visible={visible}")
                last_seen = (name, visible)
            if not visible and hidden_since is None:
                hidden_since = time.time()
                log(f"hidden (front: {name})")
            elif visible and hidden_since is not None:
                away = time.time() - hidden_since
                hidden_since = None
                log(f"visible again after {int(away)}s")
                if 0 < cfg["app_away_seconds"] <= away:
                    show(f"back after {int(away)}s in another app")

            if cfg["idle_seconds"] > 0:
                idle = hid_idle_seconds()
                if idle >= cfg["idle_seconds"] and not idle_fired:
                    idle_fired = True
                    if visible:
                        show(f"idle {int(idle)}s")
                elif idle < cfg["idle_seconds"]:
                    idle_fired = False
        except Exception as e:
            log(f"watcher tick failed: {e}")
        time.sleep(cfg["poll_seconds"])


def startup() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if pid_alive(STATE_DIR / "daemon.pid"):
        return
    with open(STATE_DIR / "focus.log", "a") as out:
        subprocess.Popen(
            [sys.executable, str(ENTRY), "daemon"],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=out,
            start_new_session=True,
        )


def tab_focused() -> None:
    now = time.time()
    tab = call("session.snapshot", {})["snapshot"].get("focused_tab_id")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_DIR / "tabs.json", "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        state = json.loads(f.read() or '{"current": null, "left": {}}')
        if tab == state["current"]:
            return
        if state["current"]:
            state["left"][state["current"]] = now
        left_at = state["left"].get(tab)
        state["current"] = tab
        f.seek(0)
        f.truncate()
        f.write(json.dumps(state))
    if left_at and 0 < config()["tab_away_seconds"] <= now - left_at:
        show(f"tab unseen {int(now - left_at)}s")
