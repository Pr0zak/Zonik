"""Listening layers for the Music Map — what you play, in what order, and how
that changes over time. Everything here reads play_history (one row per
completed scrobble, with the client in `source`) plus the per-track play and
skip counters.

Times are stored as naive UTC; anything bucketed by day, week or month is
converted to the server's local time first, matching the listening clock.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.genres import genre_family

# Two plays further apart than this belong to different listening sessions, so
# the second isn't counted as "what came after" the first.
SESSION_GAP = timedelta(minutes=30)


def _utc(v) -> datetime | None:
    """play_history.played_at comes back as a string or a naive datetime (UTC)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        try:
            dt = datetime.fromisoformat(str(v))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _local(v) -> datetime | None:
    dt = _utc(v)
    return dt.astimezone() if dt else None


def _iso(v) -> str | None:
    dt = _utc(v)
    return dt.isoformat() if dt else None


def _week_start(d: datetime) -> datetime:
    d = d.replace(hour=0, minute=0, second=0, microsecond=0)
    return d - timedelta(days=d.weekday())


async def _plays(db: AsyncSession, since: datetime | None = None) -> list[tuple]:
    """(track_id, played_at, source, genre) in time order."""
    sql = (
        "SELECT ph.track_id, ph.played_at, ph.source, t.genre "
        "FROM play_history ph JOIN tracks t ON t.id = ph.track_id "
        "WHERE ph.played_at IS NOT NULL"
    )
    params = {}
    if since is not None:
        sql += " AND ph.played_at >= :since"
        params["since"] = since.astimezone(timezone.utc).replace(tzinfo=None).isoformat(" ")
    sql += " ORDER BY ph.played_at"
    return (await db.execute(text(sql), params)).all()


# --- B: taste river ---

async def taste_river(db: AsyncSession, weeks: int = 52) -> dict:
    """Plays per genre family per local week, oldest week first."""
    now = datetime.now().astimezone()
    first = _week_start(now) - timedelta(weeks=weeks - 1)
    # Start at the first recorded play rather than drawing empty weeks before tracking began.
    earliest = _local((await db.execute(text(
        "SELECT MIN(played_at) FROM play_history WHERE played_at IS NOT NULL"
    ))).scalar())
    if earliest and _week_start(earliest) > first:
        first = _week_start(earliest)
        weeks = max(1, (_week_start(now) - first).days // 7 + 1)
    rows = await _plays(db, first)
    starts = [first + timedelta(weeks=k) for k in range(weeks)]
    counts: dict[str, list[int]] = defaultdict(lambda: [0] * weeks)
    for _tid, at, _src, genre in rows:
        d = _local(at)
        if d is None:
            continue
        k = (_week_start(d) - first).days // 7
        if 0 <= k < weeks:
            counts[genre_family(genre)][k] += 1
    # Biggest families first so they sit at the bottom of the stack.
    families = sorted(counts, key=lambda f: (f == "Unknown", -sum(counts[f])))
    return {
        "weeks": [s.date().isoformat() for s in starts],
        "families": families,
        "counts": [counts[f] for f in families],
        "total": len(rows),
    }


# --- G: genre flow ---

async def genre_flow(db: AsyncSession, days: int = 90) -> dict:
    """How often a play in one family is followed by a play in another, within
    one session. Replays of the same track are left out."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await _plays(db, since)
    pairs: Counter = Counter()
    prev = None
    sessions = 1 if rows else 0
    for tid, at, _src, genre in rows:
        t = _utc(at)
        fam = genre_family(genre)
        if prev is not None:
            ptid, pt, pfam = prev
            if t - pt > SESSION_GAP:
                sessions += 1
            elif tid != ptid:
                pairs[(pfam, fam)] += 1
        prev = (tid, t, fam)
    out_tot: Counter = Counter()
    in_tot: Counter = Counter()
    for (a, b), n in pairs.items():
        out_tot[a] += n
        in_tot[b] += n
    families = sorted(set(out_tot) | set(in_tot), key=lambda f: (f == "Unknown", -(out_tot[f] + in_tot[f])))
    idx = {f: i for i, f in enumerate(families)}
    matrix = [[0] * len(families) for _ in families]
    for (a, b), n in pairs.items():
        matrix[idx[a]][idx[b]] = n
    return {
        "days": days, "families": families, "matrix": matrix,
        "transitions": sum(pairs.values()), "sessions": sessions, "plays": len(rows),
        "gap_minutes": int(SESSION_GAP.total_seconds() // 60),
    }


# --- I: rotation board ---

async def rotation(db: AsyncSession, days: int = 30, limit: int = 60) -> dict:
    """Tracks ranked by plays in the last `days`, against the `days` before,
    with a weekly sparkline and a flag for the ones changing fastest."""
    now = datetime.now(timezone.utc)
    cur_from, prev_from = now - timedelta(days=days), now - timedelta(days=days * 2)
    spark_weeks = 8
    spark_from = now - timedelta(weeks=spark_weeks)
    rows = await _plays(db, min(prev_from, spark_from))

    cur: Counter = Counter()
    prev: Counter = Counter()
    spark: dict[str, list[int]] = defaultdict(lambda: [0] * spark_weeks)
    for tid, at, _src, _genre in rows:
        t = _utc(at)
        if t >= cur_from:
            cur[tid] += 1
        elif t >= prev_from:
            prev[tid] += 1
        if t >= spark_from:
            k = min(spark_weeks - 1, int((t - spark_from).total_seconds() // (7 * 86400)))
            spark[tid][k] += 1

    ids = set(cur) | {t for t, n in prev.items() if n >= 3}
    if not ids:
        return {"days": days, "tracks": [], "dropped": []}
    first_played = {
        r[0]: _utc(r[1]) for r in (await db.execute(text(
            "SELECT track_id, MIN(played_at) FROM play_history GROUP BY track_id"
        ))).all()
    }
    meta = {}
    id_list = list(ids)
    for k in range(0, len(id_list), 500):
        chunk = id_list[k:k + 500]
        marks = ",".join(f":i{n}" for n in range(len(chunk)))
        for r in (await db.execute(text(
            "SELECT t.id, t.title, ar.name, t.album_id, t.genre, COALESCE(t.play_count, 0), "
            "       COALESCE(t.skip_count, 0), t.last_played_at "
            f"FROM tracks t LEFT JOIN artists ar ON ar.id = t.artist_id WHERE t.id IN ({marks})"
        ), {f"i{n}": v for n, v in enumerate(chunk)})).all():
            meta[r[0]] = r

    def row(tid: str) -> dict | None:
        m = meta.get(tid)
        if not m:
            return None
        c, p, skips = cur[tid], prev[tid], m[6]
        flag = None
        # Thresholds are low on purpose: most tracks here get one to three plays a month.
        if c >= 3 and skips >= 2 and skips / (skips + c) >= 0.25:
            flag = "wearing_out"
        elif c >= 3 and p == 0 and (first_played.get(tid) or now) >= cur_from:
            flag = "new"
        elif c == 0 and p >= 3:
            flag = "dropped"
        elif c - p >= 3:
            flag = "rising"
        elif p - c >= 3:
            flag = "falling"
        return {
            "track_id": tid, "title": m[1], "artist": m[2], "album_id": m[3],
            "family": genre_family(m[4]), "plays": c, "prev": p, "delta": c - p,
            "total_plays": m[5], "skips": skips, "last_played": _iso(m[7]),
            "spark": spark[tid], "flag": flag,
        }

    tracks = [r for r in (row(t) for t in cur) if r]
    tracks.sort(key=lambda r: (-r["plays"], -r["delta"], r["title"] or ""))
    dropped = [r for r in (row(t) for t in ids if cur[t] == 0) if r]
    dropped.sort(key=lambda r: -r["prev"])

    # The same board by artist: listening here is spread thin across tracks, so
    # artist-level movement is often the clearer signal.
    artist_of = {}
    for tid in cur.keys() | prev.keys():
        m = meta.get(tid)
        if m and m[2]:
            artist_of[tid] = m[2]
    missing = [t for t in (cur.keys() | prev.keys()) if t not in meta]
    for k in range(0, len(missing), 500):
        chunk = missing[k:k + 500]
        marks = ",".join(f":i{n}" for n in range(len(chunk)))
        for r in (await db.execute(text(
            f"SELECT t.id, ar.name FROM tracks t JOIN artists ar ON ar.id = t.artist_id WHERE t.id IN ({marks})"
        ), {f"i{n}": v for n, v in enumerate(chunk)})).all():
            artist_of[r[0]] = r[1]
    agg: dict[str, dict] = {}
    for src, key in ((cur, "plays"), (prev, "prev")):
        for tid, n in src.items():
            name = artist_of.get(tid)
            if not name:
                continue
            a = agg.setdefault(name, {"artist": name, "plays": 0, "prev": 0, "tracks": set(), "spark": [0] * spark_weeks})
            a[key] += n
            if key == "plays":
                a["tracks"].add(tid)
    for tid, sp in spark.items():
        a = agg.get(artist_of.get(tid))
        if a:
            a["spark"] = [x + y for x, y in zip(a["spark"], sp)]
    artists = []
    for a in agg.values():
        a["delta"] = a["plays"] - a["prev"]
        a["tracks"] = len(a["tracks"])
        artists.append(a)
    artists.sort(key=lambda a: (-a["plays"], -a["delta"]))

    return {
        "days": days, "tracks": tracks[:limit], "dropped": dropped[:20],
        "artists": [a for a in artists if a["plays"]][:limit],
        "spark_weeks": spark_weeks,
    }


# --- H: one track's listening ---

async def track_listening(db: AsyncSession, track_id: str) -> dict | None:
    t = (await db.execute(text(
        "SELECT t.id, t.title, ar.name, al.title, t.album_id, t.genre, t.year, "
        "       COALESCE(t.play_count, 0), COALESCE(t.skip_count, 0), t.last_played_at, t.last_skipped_at, "
        "       a.bpm, a.key, a.scale "
        "FROM tracks t LEFT JOIN artists ar ON ar.id = t.artist_id "
        "LEFT JOIN albums al ON al.id = t.album_id "
        "LEFT JOIN track_analysis a ON a.track_id = t.id WHERE t.id = :id"
    ), {"id": track_id})).first()
    if not t:
        return None

    mine = (await db.execute(text(
        "SELECT played_at, source FROM play_history WHERE track_id = :id AND played_at IS NOT NULL ORDER BY played_at"
    ), {"id": track_id})).all()

    now = datetime.now().astimezone()
    months = []
    y, m = now.year, now.month
    for _ in range(12):
        months.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()
    by_month = Counter()
    sources = Counter()
    for at, src in mine:
        d = _local(at)
        if d:
            by_month[(d.year, d.month)] += 1
        sources[src or "unknown"] += 1

    # What you played next, within the same session, across every play of this track.
    after: Counter = Counter()
    if mine:
        rows = (await db.execute(text(
            "SELECT ph.track_id, ph.played_at FROM play_history ph "
            "WHERE ph.played_at IS NOT NULL AND ph.played_at >= :first ORDER BY ph.played_at"
        ), {"first": str(mine[0][0])})).all()
        for k in range(len(rows) - 1):
            if rows[k][0] != track_id:
                continue
            nxt, at = rows[k + 1]
            if nxt != track_id and _utc(at) - _utc(rows[k][1]) <= SESSION_GAP:
                after[nxt] += 1
    after_rows = []
    if after:
        top = after.most_common(5)
        marks = ",".join(f":i{n}" for n in range(len(top)))
        names = {r[0]: r for r in (await db.execute(text(
            "SELECT t.id, t.title, ar.name, t.album_id FROM tracks t LEFT JOIN artists ar ON ar.id = t.artist_id "
            f"WHERE t.id IN ({marks})"
        ), {f"i{n}": tid for n, (tid, _) in enumerate(top)})).all()}
        for tid, n in top:
            r = names.get(tid)
            if r:
                after_rows.append({"track_id": tid, "title": r[1], "artist": r[2], "album_id": r[3], "count": n})

    return {
        "track_id": t[0], "title": t[1], "artist": t[2], "album": t[3], "album_id": t[4],
        "family": genre_family(t[5]), "genre": t[5], "year": t[6],
        "play_count": t[7], "skip_count": t[8],
        "last_played": _iso(t[9]), "last_skipped": _iso(t[10]),
        "first_played": _iso(mine[0][0]) if mine else None,
        "bpm": t[11], "key": t[12], "scale": t[13],
        "months": [f"{yy}-{mm:02d}" for yy, mm in months],
        "monthly": [by_month[k] for k in months],
        "sources": dict(sources.most_common()),
        "after": after_rows,
    }


# --- D: listening trail ---

async def trail(db: AsyncSession, hours: int = 0) -> dict:
    """Plays in time order since local midnight (hours=0) or over the last
    `hours`, plus what's playing now and the saved play queue."""
    if hours <= 0:
        since = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = await _plays(db, since)
    plays = [{"track_id": r[0], "played_at": _iso(r[1]), "source": r[2]} for r in rows]

    from backend.subsonic.annotation import _now_playing
    cutoff = datetime.utcnow() - timedelta(minutes=10)
    now_playing = [
        {"track_id": info.get("track_id"), "client": info.get("playerId") or "",
         "started_at": _iso(info.get("started_at"))}
        for info in list(_now_playing.values())
        if info.get("track_id") and info.get("started_at") and info["started_at"] >= cutoff
    ]
    now_playing.sort(key=lambda r: r["started_at"] or "", reverse=True)

    queue = None
    q = (await db.execute(text(
        "SELECT current_track_id, track_ids, updated_at FROM play_queue ORDER BY updated_at DESC LIMIT 1"
    ))).first()
    if q and q[1]:
        try:
            ids = [i for i in json.loads(q[1]) if isinstance(i, str)]
        except (ValueError, TypeError):
            ids = []
        cur = q[0]
        upcoming = ids[ids.index(cur) + 1:] if cur in ids else ids
        queue = {"current": cur, "next": upcoming[:20], "updated_at": _iso(q[2])}

    return {"since": since.isoformat(), "plays": plays, "now_playing": now_playing, "queue": queue}
