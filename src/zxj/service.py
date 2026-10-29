"""Beijing-day draws and their small SQLite store."""

from contextlib import closing, contextmanager
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


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Create tables without committing the caller's transaction."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS draws (
            user_id TEXT NOT NULL,
            business_date TEXT NOT NULL,
            result TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            PRIMARY KEY (user_id, business_date)
        )"""
    )


@contextmanager
def _transaction(db_path, connection):
    if connection is not None:
        if not connection.in_transaction or connection.row_factory is not sqlite3.Row:
            raise ValueError("外部连接需要已开启事务及 sqlite3.Row row_factory")
        # The inbox/business/outbox owner controls this transaction's lifecycle.
        yield connection
        return
    if db_path is None:
        raise ValueError("需要 db_path 或外部 connection")
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as owned, owned:
        owned.row_factory = sqlite3.Row
        initialize_schema(owned)
        owned.execute("BEGIN IMMEDIATE")
        yield owned


def _validate_user(user_id: str) -> None:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("用户 ID 不能为空")


def draw(user_id: str, db_path: str | Path | None = None, now: datetime | None = None,
         *, connection: sqlite3.Connection | None = None, characters: dict | None = None) -> dict:
    """Return the saved daily draw, with ``is_first`` for this request.

    ``now`` is an aware datetime for controlled tests; the CLI always uses the
    real clock. Persisted UTC time and the Beijing business date are distinct.
    An external connection must have an active transaction, sqlite3.Row, and
    initialized tables. Its caller owns commit, rollback and close.
    """
    _validate_user(user_id)
    instant = datetime.now(UTC) if now is None else now
    if not isinstance(instant, datetime) or instant.utcoffset() is None:
        raise ValueError("now 必须是带时区的 datetime")
    business_date = instant.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()

    with _transaction(db_path, connection) as connection:
        existing = connection.execute(
            "SELECT * FROM draws WHERE user_id = ? AND business_date = ?",
            (user_id, business_date),
        ).fetchone()
        if existing is not None:
            return {**dict(existing), "is_first": False}

        groups = _characters() if characters is None else characters
        if not isinstance(groups, dict) or any(not isinstance(groups.get(initial), (tuple, list))
                or not groups[initial] or any(not isinstance(char, str) or len(char) != 1
                for char in groups[initial]) for initial in ("z", "x", "j")):
            raise ValueError("字库需要非空的 z、x、j 单字列表")
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


def history(user_id: str, db_path: str | Path | None = None, limit: int | None = None,
            *, offset: int = 0, connection: sqlite3.Connection | None = None) -> list[dict]:
    """Return newest-first saved draws; omit ``limit`` to query all dates."""
    _validate_user(user_id)
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit 必须是正整数")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset 必须是非负整数")
    query = "SELECT * FROM draws WHERE user_id = ? ORDER BY business_date DESC"
    params: tuple = (user_id,)
    if limit is not None or offset:
        query += " LIMIT ? OFFSET ?"
        params += (limit if limit is not None else -1, offset)
    with _transaction(db_path, connection) as connection:
        return [dict(row) for row in connection.execute(query, params)]


def history_count(user_id: str, db_path: str | Path | None = None,
                  *, connection: sqlite3.Connection | None = None) -> int:
    _validate_user(user_id)
    with _transaction(db_path, connection) as connection:
        return connection.execute("SELECT COUNT(*) FROM draws WHERE user_id = ?", (user_id,)).fetchone()[0]


def history_page(user_id: str, db_path: str | Path | None = None, *, page: int = 1,
                 page_size: int = 10, connection: sqlite3.Connection | None = None) -> dict:
    """Read a history page and its count from the same transaction snapshot."""
    _validate_user(user_id)
    if type(page) is not int or page < 1 or type(page_size) is not int or page_size < 1:
        raise ValueError("page 和 page_size 必须是正整数")
    with _transaction(db_path, connection) as connection:
        total = history_count(user_id, connection=connection)
        return {
            "items": history(user_id, limit=page_size, offset=(page - 1) * page_size,
                             connection=connection),
            "total": total, "page": page, "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }
