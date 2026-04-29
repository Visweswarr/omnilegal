"""Project-local Python startup fixes for Windows tooling.

Python 3.12's ``platform.machine()`` can call WMI on Windows. On some local
Windows installs WMI calls hang, which makes tooling such as ``pip check`` block
while evaluating dependency markers. The processor architecture environment
variable is enough for those markers and avoids a live WMI query.
"""
from __future__ import annotations

import os
import platform
import sys


if any("pytest" in arg.lower() for arg in sys.argv):
    os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")


if sys.platform == "win32":
    _machine = os.getenv("PROCESSOR_ARCHITECTURE") or os.getenv("PROCESSOR_ARCHITEW6432") or "AMD64"
    _release = f"{sys.getwindowsversion().major}.{sys.getwindowsversion().minor}"
    platform.machine = lambda: _machine  # type: ignore[assignment]
    platform.release = lambda: _release  # type: ignore[assignment]
    platform.version = lambda: _release  # type: ignore[assignment]


try:
    from engineio.payload import Payload

    Payload.max_decode_packets = int(os.getenv("ENGINEIO_MAX_DECODE_PACKETS", "128"))
except Exception:
    pass
