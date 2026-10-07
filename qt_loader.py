"""Import PySide6 robustly on Windows.

Qt links against the unversioned ICU that ships in System32. A conda-style distribution such as
Anaconda puts its own versioned icuuc.dll (ICU 73 exports ucnv_open_73, not ucnv_open) on the DLL
search path, so "import PySide6.QtCore" fails with:

    ImportError: DLL load failed while importing QtCore: The specified procedure could not be found.

Binding the Windows ICU first and retrying repairs that case and does nothing on a healthy one.
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path


def bind_system_icu() -> bool:
    """Map the Windows system ICU so icuuc.dll lookups reuse it instead of a shadowing copy."""
    if sys.platform != "win32":
        return False
    system_root = os.environ.get("SystemRoot") or r"C:\Windows"
    candidate = Path(system_root) / "System32" / "icuuc.dll"
    if not candidate.is_file():
        return False
    try:
        ctypes.WinDLL(str(candidate))
    except OSError:
        return False
    return True


def preload_qt() -> None:
    """Import PySide6.QtCore, retrying once with the Windows system ICU bound."""
    try:
        import PySide6.QtCore  # noqa: F401
        return
    except ImportError as exc:
        if sys.platform != "win32" or "QtCore" not in str(exc):
            raise
        if not bind_system_icu():
            raise
    import PySide6.QtCore  # noqa: F401
