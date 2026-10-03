"""INZO desktop skill group: background-first desktop integration points.

No GUI code lives in this project. Skills that need a display, global
hotkeys, screen capture, or app launching expose stdlib ``Protocol``
boundaries plus honest headless fallbacks; the real OS-specific adapters
(e.g. pystream, pystray, OS clipboard APIs) are plugged in OUTSIDE this
codebase. ``file_organizer`` and ``clipboard_history`` are fully local.
"""
