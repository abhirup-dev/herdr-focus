"""Cover effects. Each module is one look, chosen with `effect = "<name>"` in config.toml.

An effect module provides:
  DEFAULTS                 its settings, configurable under [effects.<name>]
  validate(key, value)     return the value to use, or raise ValueError with the reason
  render(frame) -> str     the escape sequences for one frame (geometry.Frame)

To add one: write effects/<name>.py, register it below, document it in
config.example.toml.
"""

from . import contrast

EFFECTS = {"contrast": contrast}
