"""Beijing-day draws and their small SQLite store."""

from contextlib import closing
from datetime import UTC, datetime
from importlib.resources import files
import json
from pathlib import Path
import random
import sqlite3
from zoneinfo import ZoneInfo


def _characters() -> dict[str, list[str]]:
    groups = json.loads(files("zxj").joinpath("characters.json").read_text(encoding="utf-8"))
    for initial in ("z", "x", "j"):
        group = groups.get(initial)
        if not isinstance(group, list) or not group or any(
            not isinstance(char, str) or len(char) != 1 for char in group
        ):
            raise ValueError(f"characters.json 的 {initial} 组必须是非空单字列表")
    return groups


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS draws (
                user_id TEXT NOT NULL,
                business_date TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                PRIMARY KEY (user_id, business_date)
            )"""
        )
    except Exception:
        connection.close()
        raise
    return connection


def _validate_user(user_id: str) -> None:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("用户 ID 不能为空")


def draw(user_id: str, db_path: str | Path, now: datetime | None = None) -> dict:
    """Return the saved daily draw, with ``is_first`` for this request.

    ``now`` is an aware datetime for controlled tests; the CLI always uses the
    real clock. Persisted UTC time and the Beijing business date are distinct.
    """
    _validate_user(user_id)
    instant = datetime.now(UTC) if now is None else now
    if not isinstance(instant, datetime) or instant.utcoffset() is None:
        raise ValueError("now 必须是带时区的 datetime")
    business_date = instant.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()

    with closing(_connect(db_path)) as connection, connection:
        # Serialize lookup and insertion so concurrent requests return one saved draw.
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM draws WHERE user_id = ? AND business_date = ?",
            (user_id, business_date),
        ).fetchone()
        if existing is not None:
            return {**dict(existing), "is_first": False}

        groups = _characters()
        record = {
            "user_id": user_id,
            "business_date": business_date,
            "result": "".join(random.choice(groups[initial]) for initial in ("z", "x", "j")),
            "created_at_utc": instant.astimezone(UTC).isoformat(timespec="seconds"),
        }
        connection.execute(
            """INSERT INTO draws (user_id, business_date, result, created_at_utc)
               VALUES (:user_id, :business_date, :result, :created_at_utc)""",
            record,
        )
        return {**record, "is_first": True}


def history(user_id: str, db_path: str | Path, limit: int | None = None) -> list[dict]:
    """Return newest-first saved draws; omit ``limit`` to query all dates."""
    _validate_user(user_id)
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit 必须是正整数")
    query = "SELECT * FROM draws WHERE user_id = ? ORDER BY business_date DESC"
    params: tuple = (user_id,)
    if limit is not None:
        query += " LIMIT ?"
        params += (limit,)
    with closing(_connect(db_path)) as connection:
        return [dict(row) for row in connection.execute(query, params)]
