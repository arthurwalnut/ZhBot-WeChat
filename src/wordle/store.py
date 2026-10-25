"""SQLite persistence. Game rules belong in game.py."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3


class WordleStore:
    def __init__(self, db_path):
        self.path = Path(db_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    creator_id TEXT NOT NULL,
                    length INTEGER NOT NULL CHECK (length BETWEEN 3 AND 10),
                    answer TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('active','won','lost','ended')),
                    winner_id TEXT,
                    created_at_utc TEXT NOT NULL,
                    ended_at_utc TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_game_per_group
                    ON games(group_id) WHERE status = 'active';
                CREATE TABLE IF NOT EXISTS guesses (
                    game_id INTEGER NOT NULL REFERENCES games(id),
                    turn_number INTEGER NOT NULL CHECK (turn_number BETWEEN 1 AND 6),
                    user_id TEXT NOT NULL,
                    word TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    PRIMARY KEY (game_id, turn_number),
                    UNIQUE (game_id, word)
                );
            """)

    @contextmanager
    def transaction(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        # Serializes the read/validate/write sequence across separate CLI processes.
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def load(self, connection, group_id, game_id=None, *, active_only=False):
        if game_id is not None:
            row = connection.execute(
                "SELECT * FROM games WHERE id = ? AND group_id = ?",
                (game_id, group_id),
            ).fetchone()
        elif active_only:
            row = connection.execute(
                "SELECT * FROM games WHERE group_id = ? AND status = 'active'",
                (group_id,),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT * FROM games WHERE group_id = ? ORDER BY id DESC LIMIT 1",
                (group_id,),
            ).fetchone()
        if row is None:
            return None
        game = dict(row)
        game["guesses"] = [dict(item) for item in connection.execute(
            "SELECT * FROM guesses WHERE game_id = ? ORDER BY turn_number", (game["id"],)
        )]
        return game

    def create(self, connection, group_id, user_id, answer, timestamp):
        cursor = connection.execute(
            "INSERT INTO games (group_id, creator_id, length, answer, status, created_at_utc) "
            "VALUES (?, ?, ?, ?, 'active', ?)",
            (group_id, user_id, len(answer), answer, timestamp),
        )
        return cursor.lastrowid

    def add_guess(self, connection, game_id, turn, user_id, word, timestamp):
        connection.execute(
            "INSERT INTO guesses VALUES (?, ?, ?, ?, ?)",
            (game_id, turn, user_id, word, timestamp),
        )

    def finish(self, connection, game_id, status, timestamp, winner_id=None):
        connection.execute(
            "UPDATE games SET status = ?, winner_id = ?, ended_at_utc = ? WHERE id = ?",
            (status, winner_id, timestamp, game_id),
        )

    def wins(self, connection, user_id):
        return connection.execute(
            "SELECT COUNT(*) FROM games WHERE status = 'won' AND winner_id = ?", (user_id,)
        ).fetchone()[0]
