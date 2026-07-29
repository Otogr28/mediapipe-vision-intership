"""Runtime switches an operator flips on the RUNNING exhibit.

The exhibit is an appliance: it boots itself, updates itself from git and has
no keyboard in front of it, so anything an operator wants to ask of it *while
visitors are there* has to arrive over the wire. This module is the one place
those overrides live — a small thread-safe box written by the HTTP server
(``POST /control/idle``, driven from ``deploy/hall-app/hallidle``) and read by
the UI layer once per frame.

It is its own module because of who its two users are. ``output.py`` is the
sink layer and deliberately does not import the UI layer at module level (see
``WebSink._attract_root``, which imports ``ui.attract`` lazily for exactly
that reason), so the flag cannot live under ``ui/``. And it is written from an
HTTP worker thread while the render loop reads it, so it is not a plain
module global either.

**Forcing idle does not pause the pipeline.** Capture, detection and presence
all keep running; only ``UIManager.phase`` is pinned to ``attract``. So
releasing the force hands back a live exhibit on the very next frame — no
detector rebuild (which on the Jetson is a multi-second TensorRT engine load)
and no camera reopen. That is what makes this safe to do with somebody
standing in front of the screen, and why it is a flag here rather than an
``HALL_*`` variable that would need a restart to change.
"""

import threading

_lock = threading.Lock()
_forced_idle = False


def set_forced_idle(on):
    """Pin the exhibit to the idle slideshow (True), or release it (False).

    Returns the value now in force, so a caller can report back what it did
    without a second read.
    """
    global _forced_idle
    with _lock:
        _forced_idle = bool(on)
        return _forced_idle


def forced_idle():
    """Is an operator currently holding the exhibit in the slideshow?"""
    with _lock:
        return _forced_idle


def reset():
    """Drop every override. For tests — the flags are process-wide, and a
    test that forced idle must not leave the next one running against it."""
    set_forced_idle(False)
