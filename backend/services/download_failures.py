"""Why a download job failed, as one server-side class (pure: no DB, no I/O).

Every consumer that needs to explain a failed download (the jobs list, the final
WebSocket payload, the failure buckets and the incident grouping) asks this module
instead of matching result strings itself, so a row's label and its triage bucket
can never disagree.

Classes (``failure_class``), checked in this order:

- ``None``       the job did not fail.
- ``orphan``     failed with no result, or a result that is not a JSON object
                 (a job ended mid-flight with no reason recorded). A result that
                 holds nothing but the incident-dismissed flag is still an orphan.
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
from datetime import datetime, timedelta
from typing import Iterable

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

# Merged into member rows' result by POST /api/jobs/incidents/{id}/dismiss. It never
# changes a row's class: a NULL result that only gained this flag stays an orphan.
DISMISSED_KEY = "incident_dismissed"


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
    if not isinstance(result, dict) or not (set(result) - {DISMISSED_KEY}):
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


def failure_text(result_json: str | None) -> str:
    """The text incident_kind reads for a row: ``result.error or result.message``,
    the raw text for a result that is not a JSON object, "" for none."""
    result = _loads(result_json)
    if isinstance(result, dict):
        error = result.get("error")
        message = result.get("message")
        error = error if isinstance(error, str) else ""
        message = message if isinstance(message, str) else ""
        return error or message
    if result is None and result_json and isinstance(result_json, str):
        return result_json  # unparseable text (an old reaper's plain string)
    return ""


def is_dismissed(result_json: str | None) -> bool:
    result = _loads(result_json)
    return isinstance(result, dict) and result.get(DISMISSED_KEY) is True


def _as_dt(ts) -> datetime | None:
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=None) if ts.tzinfo else ts
    if isinstance(ts, str) and ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def _bucket_start(ts: datetime, minutes: int) -> datetime:
    midnight = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    mins = ts.hour * 60 + ts.minute
    return midnight + timedelta(minutes=(mins // minutes) * minutes)


def group_incidents(rows: Iterable[tuple], bucket_minutes: int = 15) -> list[dict]:
    """Group not-the-track's-fault failures into incidents (DC-17).

    ``rows`` are ``(id, card, finished_at|started_at, error_text, dismissed)``.
    Rows group by ``(incident_kind(error_text), bucket_minutes bucket of the time)``;
    adjacent buckets of the same kind merge (a 4-minute outage across a bucket
    boundary is one incident, two reaper batches 40 minutes apart are two). The id
    is ``"<kind>:<first bucket start ISO>"``, derived from the rows, so it is stable
    across reloads while those rows exist. An incident is ``dismissed`` when every
    member is. Newest first."""
    step = timedelta(minutes=bucket_minutes)
    groups: dict[tuple[str, datetime], list[tuple]] = {}
    for jid, card, ts, text, dismissed in rows:
        ts = _as_dt(ts)
        if ts is None:
            continue
        kind = incident_kind(text)
        groups.setdefault((kind, _bucket_start(ts, bucket_minutes)), []).append(
            (jid, card, ts, bool(dismissed)))

    buckets_by_kind: dict[str, list[datetime]] = {}
    for kind, start in sorted(groups):
        buckets_by_kind.setdefault(kind, []).append(start)

    def build(kind: str, run: list[datetime]) -> dict:
        members = sorted((m for b in run for m in groups[(kind, b)]), key=lambda m: (m[2], str(m[0])))
        by_card: dict[str, int] = {}
        for _, card, _, _ in members:
            c = card or "dl"
            by_card[c] = by_card.get(c, 0) + 1
        return {
            "id": f"{kind}:{run[0].isoformat()}",
            "kind": kind,
            "count": len(members),
            "start": members[0][2].isoformat(),
            "end": members[-1][2].isoformat(),
            "job_ids": [m[0] for m in members],
            "by_card": by_card,
            "dismissed": all(m[3] for m in members),
        }

    out: list[dict] = []
    for kind, starts in buckets_by_kind.items():
        run: list[datetime] = []
        for b in starts:
            if run and b - run[-1] > step:
                out.append(build(kind, run))
                run = []
            run.append(b)
        if run:
            out.append(build(kind, run))
    out.sort(key=lambda i: (i["end"], i["id"]), reverse=True)
    return out
