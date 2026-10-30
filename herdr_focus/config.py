"""config.toml: plugin-wide settings at the top level, each effect's under [effects.<name>]."""

import os
import tomllib
from pathlib import Path

from .effects import EFFECTS
from .herdr import CONFIG_DIR, log

# Keep in step with config.example.toml (a test checks it).
DEFAULTS = {
    "idle_seconds": 600,
    "app_away_seconds": 600,
    "tab_away_seconds": 600,
    "poll_seconds": 2,
    "refresh_seconds": 15,
    "resize_timeout_seconds": 3,
    "effect": "contrast",
    "debug": False,
}

_cache: tuple = (None, None)


def config() -> dict:
    """Defaults overlaid with config.toml. Re-read only when the file changes, so warnings log once.
    The chosen effect's settings are under cfg["effect_settings"]."""
    global _cache
    path = CONFIG_DIR / "config.toml"
    mtime = path.stat().st_mtime if path.exists() else None
    if _cache[0] != mtime or _cache[1] is None:
        _cache = (mtime, load(path))
    return _cache[1]


def load(path: Path) -> dict:
    cfg = dict(DEFAULTS)
    try:
        user = tomllib.loads(path.read_text())
    except FileNotFoundError:
        user = {}
    except tomllib.TOMLDecodeError as e:
        log(f"config.toml ignored, using defaults: {e}")
        user = {}

    for key, value in user.items():
        if key == "effects":
            continue
        if key not in DEFAULTS:
            log(f"config.toml: unknown key {key!r} ignored")
        elif type(value) is not type(DEFAULTS[key]) and not (
            isinstance(value, (int, float)) and isinstance(DEFAULTS[key], (int, float)) and not isinstance(value, bool)
        ):
            log(f"config.toml: {key} must be a {type(DEFAULTS[key]).__name__}; using {DEFAULTS[key]!r}")
        else:
            cfg[key] = value

    if cfg["effect"] not in EFFECTS:
        log(f"config.toml: unknown effect {cfg['effect']!r} (known: {', '.join(EFFECTS)}); using contrast")
        cfg["effect"] = "contrast"
    effect = EFFECTS[cfg["effect"]]
    settings = dict(effect.DEFAULTS)
    for key, value in user.get("effects", {}).get(cfg["effect"], {}).items():
        if key not in effect.DEFAULTS:
            log(f"config.toml: [effects.{cfg['effect']}] unknown key {key!r} ignored")
            continue
        try:
            settings[key] = effect.validate(key, value)
        except ValueError as e:
            log(f"config.toml: [effects.{cfg['effect']}] {key}: {e}; using {effect.DEFAULTS[key]!r}")
    cfg["effect_settings"] = settings
    return cfg


def herdr_pane_gaps() -> bool:
    """Herdr's own ui.pane_gaps (default true): it decides where pane borders are drawn."""
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    try:
        return bool(tomllib.loads((base / "herdr" / "config.toml").read_text()).get("ui", {}).get("pane_gaps", True))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return True
