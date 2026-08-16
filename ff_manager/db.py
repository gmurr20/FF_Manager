"""Database module for notification state management and deduplication."""

import hashlib
import logging
from typing import List, Optional

import requests

from ff_manager.models import ActionResult

logger = logging.getLogger(__name__)

# Statuses that represent a "problem" worth fingerprinting
_PROBLEM_STATUSES = {"FAILED", "ERROR", "NO_REPLACEMENT"}


def get_connection(database_url: str):
    """
    Create and return a psycopg2 connection.

    Returns None if psycopg2 is not installed or connection fails.
    """
    try:
        import psycopg2
    except ImportError:
        logger.warning(
            "psycopg2 is not installed. Notification deduplication is disabled. "
            "Install with: pip install psycopg2-binary"
        )
        return None

    try:
        conn = psycopg2.connect(database_url)
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        return None


def init_db(conn) -> None:
    """Create the notification_state table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_state (
                user_id     VARCHAR(255) PRIMARY KEY,
                fingerprint VARCHAR(64)  NOT NULL
            )
        """)
    conn.commit()


def get_nfl_week() -> str:
    """
    Fetch the current NFL week from Sleeper's public state endpoint.

    Returns a string like "2026_REG_2" (season_type_week).
    Falls back to "unknown" on failure so fingerprinting still works.
    """
    try:
        resp = requests.get("https://api.sleeper.app/v1/state/nfl", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        season = data.get("season", "unknown")
        season_type = data.get("season_type", "unknown")
        week = data.get("week", "unknown")
        return f"{season}_{season_type}_{week}"
    except Exception as e:
        logger.warning(f"Failed to fetch NFL week from Sleeper API: {e}")
        return "unknown"


def compute_fingerprint(results: List[ActionResult], nfl_week: str) -> str:
    """
    Compute a SHA-256 fingerprint of the problem results and NFL week.

    Only results that represent actionable problems (swaps, errors, failures)
    are included. If no problems exist, returns an empty string.
    """
    problem_tuples = []
    for r in results:
        is_problem = (
            (r.swap is not None)
            or r.error
            or r.status.upper() in _PROBLEM_STATUSES
        )
        if is_problem:
            # Include the key identifying fields that make this problem unique
            problem_tuples.append((
                r.platform,
                r.league_id,
                r.status,
                r.message,
                r.error or "",
            ))

    if not problem_tuples:
        return ""

    # Sort for determinism regardless of processing order
    problem_tuples.sort()

    # Include NFL week so same issue in a new week gets a fresh alert
    content = f"{nfl_week}|" + "|".join(str(t) for t in problem_tuples)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def get_last_fingerprint(conn, user_id: str) -> Optional[str]:
    """Return the saved fingerprint for a user, or None if not found."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT fingerprint FROM notification_state WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def save_fingerprint(conn, user_id: str, fingerprint: str) -> None:
    """Upsert the fingerprint for a user after sending an email."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO notification_state (user_id, fingerprint)
            VALUES (%s, %s)
            ON CONFLICT (user_id)
            DO UPDATE SET fingerprint = EXCLUDED.fingerprint
            """,
            (user_id, fingerprint),
        )
    conn.commit()


def clear_fingerprint(conn, user_id: str) -> None:
    """Delete the saved fingerprint when problems are resolved."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM notification_state WHERE user_id = %s",
            (user_id,),
        )
    conn.commit()
