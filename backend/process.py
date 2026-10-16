"""Which process is this: the web app or the arq worker?

Some work is only appropriate in the worker (loading the ~1 GB CLAP model to
embed recommendation previews, for example). Inferring the process from the
Soulseek client is unreliable: the web process has no client when Soulseek is
unconfigured, failed to log in, or is between a stop and a restart, which is
exactly when a user is likely to press "refresh". The worker marks itself at
startup instead.
"""
from __future__ import annotations

IS_WORKER = False


def mark_worker() -> None:
    """Called from the arq worker's on_startup hook."""
    global IS_WORKER
    IS_WORKER = True
