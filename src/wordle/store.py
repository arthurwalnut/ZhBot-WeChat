"""SQLite persistence. Game rules belong in game.py."""

from contextlib import closing, contextmanager
from importlib.resources import files
import json
from pathlib import Path
import re
import sqlite3


class WordleStore:
    def __init__(self, db_path, *, initialize=True):
        self.path = Path(db_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if initialize:
            with self.transaction() as connection:
                self.initialize_schema(connection)

    @staticmethod
    def initialize_schema(connection):
        """Create tables without executescript's implicit transaction commit."""
        statements = (
            """
                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    creator_id TEXT NOT NULL,
                    length INTEGER NOT NULL CHECK (length BETWEEN 3 AND 10),
                    max_guesses INTEGER NOT NULL DEFAULT 6 CHECK (max_guesses BETWEEN 1 AND 9),
                    allowed_words_json TEXT,
                    answer TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('active','won','lost','ended')),
                    winner_id TEXT,
                    created_at_utc TEXT NOT NULL,
                    ended_at_utc TEXT
                )""",
            """
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_game_per_group
                    ON games(group_id) WHERE status = 'active'""",
            """
                CREATE TABLE IF NOT EXISTS guesses (
                    game_id INTEGER NOT NULL REFERENCES games(id),
                    turn_number INTEGER NOT NULL CHECK (turn_number BETWEEN 1 AND 9),
                    user_id TEXT NOT NULL,
                    word TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    PRIMARY KEY (game_id, turn_number),
                    UNIQUE (game_id, word)
                )""",
        )
        for statement in statements:
            connection.execute(statement)
        # The caller owns this transaction. Legacy games keep their original
        # six-turn rule; pending outbox board snapshots are not rewritten.
        columns = {row[1] for row in connection.execute("PRAGMA table_info(games)")}
        if "max_guesses" not in columns:
            connection.execute("ALTER TABLE games ADD COLUMN max_guesses INTEGER NOT NULL "
                               "DEFAULT 6 CHECK (max_guesses BETWEEN 1 AND 9)")
        if "allowed_words_json" not in columns:
            connection.execute("ALTER TABLE games ADD COLUMN allowed_words_json TEXT")
        legacy = connection.execute("SELECT id,length,answer FROM games "
                                    "WHERE status='active' AND allowed_words_json IS NULL").fetchall()
        if legacy:
            defaults = json.loads(files("wordle").joinpath("words.json").read_text(encoding="utf-8"))
            allowed = set(defaults["answers"]) | set(defaults["allowed_guesses"])
            for identifier, length, answer in legacy:
                snapshot = sorted({word for word in allowed if len(word) == length} | {answer})
                connection.execute("UPDATE games SET allowed_words_json=? WHERE id=?",
                                   (json.dumps(snapshot), identifier))
        old_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='guesses'"
        ).fetchone()[0]
        if re.search(r"turn_number\s+BETWEEN\s+1\s+AND\s+6", old_sql, re.IGNORECASE):
            connection.execute("""CREATE TABLE guesses_expanded (
                game_id INTEGER NOT NULL REFERENCES games(id),
                turn_number INTEGER NOT NULL CHECK (turn_number BETWEEN 1 AND 9),
                user_id TEXT NOT NULL, word TEXT NOT NULL, created_at_utc TEXT NOT NULL,
                PRIMARY KEY (game_id, turn_number), UNIQUE (game_id, word))""")
            connection.execute("INSERT INTO guesses_expanded SELECT * FROM guesses")
            connection.execute("DROP TABLE guesses")
            connection.execute("ALTER TABLE guesses_expanded RENAME TO guesses")

    @contextmanager
    def transaction(self, connection=None):
        if connection is not None:
            if not connection.in_transaction or connection.row_factory is not sqlite3.Row:
                raise ValueError("外部连接需要已开启事务及 sqlite3.Row row_factory")
            yield connection
            return
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            # Serialize the read/validate/write sequence across CLI processes.
            connection.execute("BEGIN IMMEDIATE")
            yield connection

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

    def create(self, connection, group_id, user_id, answer, timestamp, max_guesses, allowed_words):
        cursor = connection.execute(
            "INSERT INTO games (group_id, creator_id, length, answer, status, created_at_utc, max_guesses, allowed_words_json) "
            "VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
            (group_id, user_id, len(answer), answer, timestamp, max_guesses, json.dumps(sorted(allowed_words))),
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

    def wins(self, connection, user_id, group_id=None):
        query = "SELECT COUNT(*) FROM games WHERE status = 'won' AND winner_id = ?"
        params = (user_id,)
        if group_id is not None:
            query += " AND group_id = ?"
            params += (group_id,)
        return connection.execute(query, params).fetchone()[0]
