"""
VibeRide - SQLite persistence layer (Developer 3).

Privacy-first design:
  * No GPS trails, no ride history, no advertising profile is ever stored.
  * A ride only adds its aggregate distance to the rider's crew totals.
  * Hazard reports are anonymous (no user column) and their coordinates are
    rounded to ~11 m. They expire automatically after HAZARD_TTL_DAYS.

Tables: feed_posts, hazard_reports, crew_members.

All functions are synchronous (stdlib sqlite3). The FastAPI layer calls them
through ``asyncio.to_thread`` so the event loop is never blocked.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

logger = logging.getLogger("viberide.database")

DB_PATH = Path(
    os.environ.get("VIBERIDE_DB_PATH", Path(__file__).resolve().parent.parent / "viberide.db")
)

HAZARD_TTL_DAYS = 30
DUPLICATE_RIDE_WINDOW_SEC = 60
MAX_FEED_LIMIT = 50
MAX_HAZARD_LIMIT = 500

_CREW_CODE_RE = re.compile(r"^[A-Z0-9_-]{2,32}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS crew_members (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    crew_code           TEXT    NOT NULL,
    user_name           TEXT    NOT NULL COLLATE NOCASE,
    total_km            REAL    NOT NULL DEFAULT 0,
    weekly_km           REAL    NOT NULL DEFAULT 0,
    week_key            TEXT    NOT NULL,
    ride_count          INTEGER NOT NULL DEFAULT 0,
    current_badge_title TEXT,
    current_badge_lore  TEXT,
    last_ride_signature TEXT,
    last_ride_epoch     REAL    NOT NULL DEFAULT 0,
    updated_at          TEXT    NOT NULL,
    UNIQUE (crew_code, user_name)
);

CREATE INDEX IF NOT EXISTS idx_crew_code ON crew_members (crew_code);

CREATE TABLE IF NOT EXISTS feed_posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name    TEXT NOT NULL,
    caption      TEXT NOT NULL DEFAULT '',
    image_base64 TEXT,
    badge_title  TEXT,
    stats_json   TEXT NOT NULL DEFAULT '{}',
    crew_code    TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feed_created ON feed_posts (created_at DESC);

CREATE TABLE IF NOT EXISTS hazard_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    hazard_type TEXT NOT NULL,
    surface     TEXT,
    shade_level TEXT,
    audio_alert TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hazard_geo ON hazard_reports (lat, lon);
"""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def current_week_key(now: Optional[datetime] = None) -> str:
    """ISO year + week number, e.g. '2026-W44'."""
    return (now or _now()).strftime("%G-W%V")


def normalize_crew_code(value: Optional[str]) -> Optional[str]:
    """Upper-case and validate a crew code. Returns None for empty input."""
    if value is None:
        return None
    code = value.strip().upper()
    if not code:
        return None
    if not _CREW_CODE_RE.match(code):
        raise ValueError("crew_code must be 2-32 chars: letters, digits, '-' or '_'.")
    return code


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Open a short-lived connection with an explicit transaction."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
def init_db() -> None:
    """Create tables and drop expired hazard reports. Safe to call repeatedly."""
    # executescript issues its own COMMIT, so it runs on a plain connection
    # instead of the transactional get_connection() helper.
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    purged = purge_expired_hazards()
    logger.info("Database ready at %s (purged %d expired hazards)", DB_PATH, purged)


def purge_expired_hazards() -> int:
    cutoff = _iso(_now() - timedelta(days=HAZARD_TTL_DAYS))
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM hazard_reports WHERE created_at < ?", (cutoff,))
        return cur.rowcount


# --------------------------------------------------------------------------- #
# Crew members / leaderboard
# --------------------------------------------------------------------------- #
def record_ride(
    *,
    user_name: str,
    crew_code: str,
    distance_km: float,
    route_title: str,
    badge_title: Optional[str],
    badge_lore: Optional[str],
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Add one finished ride to a rider's crew totals.

    Only aggregate distance is stored; the route itself is discarded. A second
    identical submission within DUPLICATE_RIDE_WINDOW_SEC (e.g. a client retry
    after a timeout) is ignored so kilometres are never double counted.
    """
    moment = now or _now()
    week = current_week_key(moment)
    epoch = moment.timestamp()
    signature = f"{route_title}|{round(distance_km, 3)}"

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM crew_members WHERE crew_code = ? AND user_name = ?",
            (crew_code, user_name),
        ).fetchone()

        if row is None:
            conn.execute(
                """INSERT INTO crew_members
                   (crew_code, user_name, total_km, weekly_km, week_key, ride_count,
                    current_badge_title, current_badge_lore,
                    last_ride_signature, last_ride_epoch, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
                (crew_code, user_name, distance_km, distance_km, week,
                 badge_title, badge_lore, signature, epoch, _iso(moment)),
            )
            duplicate = False
        else:
            duplicate = (
                row["last_ride_signature"] == signature
                and epoch - row["last_ride_epoch"] < DUPLICATE_RIDE_WINDOW_SEC
            )
            if not duplicate:
                weekly_base = row["weekly_km"] if row["week_key"] == week else 0.0
                conn.execute(
                    """UPDATE crew_members SET
                         total_km = total_km + ?,
                         weekly_km = ?,
                         week_key = ?,
                         ride_count = ride_count + 1,
                         current_badge_title = COALESCE(?, current_badge_title),
                         current_badge_lore = COALESCE(?, current_badge_lore),
                         last_ride_signature = ?,
                         last_ride_epoch = ?,
                         updated_at = ?
                       WHERE id = ?""",
                    (distance_km, weekly_base + distance_km, week, badge_title, badge_lore,
                     signature, epoch, _iso(moment), row["id"]),
                )
        updated = conn.execute(
            "SELECT total_km, weekly_km, ride_count FROM crew_members "
            "WHERE crew_code = ? AND user_name = ?",
            (crew_code, user_name),
        ).fetchone()
        return {
            "total_km": round(updated["total_km"], 2),
            "weekly_km": round(updated["weekly_km"], 2),
            "ride_count": updated["ride_count"],
            "duplicate": duplicate,
        }


def get_leaderboard(crew_code: str, scope: str = "weekly", limit: int = 50) -> list[dict[str, Any]]:
    """Crew ranking sorted by kilometres. scope: 'weekly' or 'all_time'."""
    if scope not in {"weekly", "all_time"}:
        raise ValueError("scope must be 'weekly' or 'all_time'.")
    limit = max(1, min(limit, 100))
    week = current_week_key()

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT user_name, total_km, weekly_km, week_key, ride_count, "
            "current_badge_title, current_badge_lore "
            "FROM crew_members WHERE crew_code = ?",
            (crew_code,),
        ).fetchall()

    entries = []
    for r in rows:
        weekly = r["weekly_km"] if r["week_key"] == week else 0.0
        km = weekly if scope == "weekly" else r["total_km"]
        if scope == "weekly" and km <= 0:
            continue
        entries.append(
            {
                "user_name": r["user_name"],
                "total_km": round(km, 2),
                "ride_count": r["ride_count"],
                "badge_title": r["current_badge_title"],
                "badge_lore": r["current_badge_lore"],
            }
        )
    entries.sort(key=lambda e: (-e["total_km"], e["user_name"].lower()))
    for i, entry in enumerate(entries[:limit], start=1):
        entry["rank"] = i
    return entries[:limit]


# --------------------------------------------------------------------------- #
# Feed
# --------------------------------------------------------------------------- #
def add_feed_post(
    *,
    user_name: str,
    caption: str,
    image_base64: Optional[str],
    badge_title: Optional[str],
    stats: dict[str, Any],
    crew_code: Optional[str],
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO feed_posts
               (user_name, caption, image_base64, badge_title, stats_json, crew_code, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_name, caption, image_base64, badge_title,
             json.dumps(stats, separators=(",", ":")), crew_code, _iso(_now())),
        )
        return int(cur.lastrowid)


def list_feed(crew_code: Optional[str] = None, limit: int = 20, before_id: Optional[int] = None) -> list[dict[str, Any]]:
    """
    Newest first. Without ``crew_code`` only public posts are returned; with a
    crew code the crew's private posts are included as well.
    """
    limit = max(1, min(limit, MAX_FEED_LIMIT))
    clauses = ["(crew_code IS NULL OR crew_code = '' OR crew_code = ?)"]
    params: list[Any] = [crew_code or "\x00"]
    if before_id is not None:
        clauses.append("id < ?")
        params.append(before_id)
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT id, user_name, caption, image_base64, badge_title, stats_json, created_at "
            f"FROM feed_posts WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()

    posts = []
    for r in rows:
        try:
            stats = json.loads(r["stats_json"])
        except (TypeError, ValueError):
            stats = {}
        posts.append(
            {
                "id": r["id"],
                "user_name": r["user_name"],
                "caption": r["caption"],
                "image_base64": r["image_base64"],
                "badge_title": r["badge_title"],
                "stats": stats,
                "created_at": r["created_at"],
            }
        )
    return posts


# --------------------------------------------------------------------------- #
# Hazards (anonymous open data)
# --------------------------------------------------------------------------- #
def add_hazard_report(
    *,
    lat: float,
    lon: float,
    hazard_type: str,
    surface: Optional[str],
    shade_level: Optional[str],
    audio_alert: Optional[str],
) -> int:
    """Store an anonymous hazard. Coordinates are rounded to 4 decimals (~11 m)."""
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO hazard_reports
               (lat, lon, hazard_type, surface, shade_level, audio_alert, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (round(lat, 4), round(lon, 4), hazard_type, surface, shade_level,
             audio_alert, _iso(_now())),
        )
        return int(cur.lastrowid)


def list_hazards(
    *,
    min_lat: Optional[float] = None,
    max_lat: Optional[float] = None,
    min_lon: Optional[float] = None,
    max_lon: Optional[float] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Recent, non-expired hazards, optionally inside a bounding box."""
    limit = max(1, min(limit, MAX_HAZARD_LIMIT))
    cutoff = _iso(_now() - timedelta(days=HAZARD_TTL_DAYS))
    clauses = ["created_at >= ?"]
    params: list[Any] = [cutoff]
    for column, op, value in (
        ("lat", ">=", min_lat), ("lat", "<=", max_lat),
        ("lon", ">=", min_lon), ("lon", "<=", max_lon),
    ):
        if value is not None:
            clauses.append(f"{column} {op} ?")
            params.append(value)
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT id, lat, lon, hazard_type, surface, shade_level, audio_alert, created_at "
            f"FROM hazard_reports WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]
