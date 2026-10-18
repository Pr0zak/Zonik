"""Why a download job failed, as one server-side class (pure: no DB, no I/O).

Every consumer that needs to explain a failed download (the jobs list, the final
WebSocket payload, the failure buckets and the incident grouping) asks this module
instead of matching result strings itself, so a row's label and its triage bucket
can never disagree.

Classes (``failure_class``), checked in this order:

- ``None``       the job did not fail.
- ``orphan``     failed with no result, or a result that is not a JSON object
                 (a job ended mid-flight with no reason recorded).
- ``cancelled``  ``result.error == "Cancelled by user"``.
- ``infra``      Zonik's own infrastructure failure (``is_infra_error``): restart,
                 Soulseek not connected / client not available, backend
                 unreachable, internal error. Says nothing about the track.
- ``not_found``  ``No results for …`` / ``No other sources for …``.
- ``no_better``  ``No source better than …`` (an upgrade search).
- ``rejected``   a file arrived but the importer refused it (``Not imported: …``,
                 legacy ``Import rejected …``) as the LAST error.
- ``peer``       everything else: a file was found and every peer failed.

Buckets (``BUCKET_OF_CLASS``) fold cancelled/infra/orphan into one ``infra`` bucket
("not the track's fault"). ``INFRA_PATTERNS`` is shared with the SQL filter in
``backend/api/jobs.py`` so the SQL bucket and the Python class agree.
"""
from __future__ import annotations

import json

# Substrings of Zonik's own failure messages. The SQL filter matches each as
# ``result LIKE '%<pattern>%'`` (plus ``result IS NULL`` for orphans).
INFRA_PATTERNS: list[str] = [
    "Cancelled by user",
    "Interrupted by restart",
    "Soulseek server not connected",
    "Soulseek download backend unreachable",
    "Internal error:",
    "Soulseek native client not available",
]

# Human labels per class (short; the page builds full sentences itself).
CLASS_LABELS: dict[str, str] = {
    "not_found": "Not found on Soulseek",
    "no_better": "No better-quality source",
    "rejected": "Not imported (duplicate, not better, wrong song)",
    "peer": "Peer or transfer problem",
    "cancelled": "Cancelled",
    "infra": "Soulseek or Zonik problem",
    "orphan": "Stopped with no reason recorded",
}

# Class -> failure bucket (the keys of jobs.FAILURE_REASONS / ?reason=).
BUCKET_OF_CLASS: dict[str, str] = {
    "not_found": "not_found",
    "no_better": "no_better",
    "rejected": "rejected",
    "peer": "peer",
    "cancelled": "infra",
    "infra": "infra",
    "orphan": "infra",
}

# The five buckets in display order.
BUCKETS: tuple[str, ...] = ("not_found", "no_better", "rejected", "peer", "infra")

NOT_FOUND_PREFIXES = ("No results for", "No other sources for")
NO_BETTER_PREFIX = "No source better than"
REJECTED_PREFIX = "Not imported:"
REJECTED_LEGACY = "Import rejected"


def _infra(text: str | None) -> bool:
    # Imported at call time: auto_download pulls in the DB layer, and this module
    # must stay importable without it. One rule, never re-implemented here.
    from backend.services.auto_download import is_infra_error
    return is_infra_error(text)


def _loads(text: str | None):
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _last_track_error(tracks_json: str | None) -> str:
    tracks = _loads(tracks_json)
    if isinstance(tracks, list) and tracks and isinstance(tracks[0], dict):
        err = tracks[0].get("error")
        if isinstance(err, str):
            return err
    return ""


def failure_class(status: str | None, result_json: str | None, tracks_json: str | None) -> str | None:
    """Classify one job row (see the module docstring for the rules and order)."""
    if status != "failed":
        return None
    result = _loads(result_json)
    if not isinstance(result, dict):
        return "orphan"
    error = result.get("error")
    error = error if isinstance(error, str) else ""
    message = result.get("message")
    message = message if isinstance(message, str) else ""
    if error == "Cancelled by user":
        return "cancelled"
    if _infra(error or message):
        return "infra"
    msg = message.strip()
    if msg.startswith(NOT_FOUND_PREFIXES):
        return "not_found"
    if msg.startswith(NO_BETTER_PREFIX):
        return "no_better"
    # Only the LAST error counts: a "Not imported" from an earlier peer that sits in
    # source_errors does not make a later timeout a rejection.
    track_err = _last_track_error(tracks_json).strip()
    if (track_err.startswith(REJECTED_PREFIX) or REJECTED_LEGACY in track_err
            or msg.startswith(REJECTED_PREFIX)):
        return "rejected"
    return "peer"


def failure_bucket(status: str | None, result_json: str | None, tracks_json: str | None) -> str | None:
    """The failure bucket of a row (``None`` when it did not fail)."""
    cls = failure_class(status, result_json, tracks_json)
    return BUCKET_OF_CLASS.get(cls) if cls else None


def incident_kind(text: str | None) -> str:
    """Kind of a not-the-track's-fault failure, from its error text (or the raw
    result JSON): restart | outage | cancel | internal | unreachable | orphan.

    Empty text, or text that names none of Zonik's own failures, is ``orphan``:
    such rows are the ones ``failure_class`` calls orphans (no usable result)."""
    t = (text or "").strip()
    if not t:
        return "orphan"
    if "Interrupted by restart" in t:
        return "restart"
    if "Soulseek server not connected" in t or "native client not available" in t:
        return "outage"
    if "Cancelled by user" in t:
        return "cancel"
    if "Internal error:" in t:
        return "internal"
    if "backend unreachable" in t:
        return "unreachable"
    return "orphan"
