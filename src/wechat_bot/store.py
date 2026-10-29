"""One database and transaction for inbox, game effects and ordered replies."""
from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import time

from zxj.service import initialize_schema
from wordle.store import WordleStore


class BotStore:
    def __init__(self, data_dir, account_id):
        self.directory = Path(data_dir)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "bot.sqlite3"
        with self.transaction() as c:
            c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            previous = self.setting(c, "account_id")
            if previous and previous != account_id:
                raise ValueError("该数据库已绑定其他账号，请使用独立 data_dir")
            self.set_setting(c, "account_id", account_id)
            initialize_schema(c)
            WordleStore.initialize_schema(c)
            c.execute("""CREATE TABLE IF NOT EXISTS inbox (
                id INTEGER PRIMARY KEY, namespace TEXT NOT NULL, account_id TEXT NOT NULL,
                chat_id TEXT NOT NULL, native_message_id TEXT NOT NULL, received_at REAL NOT NULL,
                payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', result TEXT,
                UNIQUE(namespace,account_id,chat_id,native_message_id))""")
            c.execute("""CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY, inbox_id INTEGER NOT NULL REFERENCES inbox(id),
                ordinal INTEGER NOT NULL, account_id TEXT NOT NULL, chat_id TEXT NOT NULL,
                chat_type TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt REAL NOT NULL DEFAULT 0, detail TEXT NOT NULL DEFAULT '',
                UNIQUE(inbox_id,ordinal))""")

    @contextmanager
    def transaction(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def setting(c, key, default=""):
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    @staticmethod
    def set_setting(c, key, value):
        c.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key,str(value)))

    def receive(self, event, extra=None):
        payload = asdict(event)
        if extra:
            payload.update(extra)
        with self.transaction() as c:
            cursor = c.execute("""INSERT OR IGNORE INTO inbox
                (namespace,account_id,chat_id,native_message_id,received_at,payload)
                VALUES ('helper.native_text',?,?,?,?,?)""", (event.account_id,event.chat_id,
                    event.native_message_id,event.received_at,json.dumps(payload,ensure_ascii=False)))
            return bool(cursor.rowcount)

    def recover(self):
        with self.transaction() as c:
            c.execute("UPDATE outbox SET state='uncertain',detail='process stopped while sending' WHERE state='sending'")

    @staticmethod
    def replies(c, row, replies):
        parts = []
        for payload in replies:
            if payload['kind'] != 'text':
                parts.append(payload)
                continue
            encoded = payload['text'].encode('utf-8')
            first = True
            while encoded:
                end = min(700,len(encoded))
                while end < len(encoded) and encoded[end] & 0xc0 == 0x80:
                    end -= 1
                parts.append(dict(payload,text=encoded[:end].decode('utf-8'),mentioned_ids=payload.get('mentioned_ids',[]) if first else []))
                encoded,first = encoded[end:],False
        for ordinal, payload in enumerate(parts):
            c.execute("""INSERT INTO outbox
                (inbox_id,ordinal,account_id,chat_id,chat_type,payload,created_at)
                VALUES (?,?,?,?,?,?,?)""", (row["id"],ordinal,row["account_id"],row["chat_id"],
                    json.loads(row["payload"])["chat_type"],json.dumps(payload,ensure_ascii=False),time.time()))

    def counts(self):
        with self.transaction() as c:
            return {table: dict(c.execute(f"SELECT state,COUNT(*) FROM {table} GROUP BY state")) for table in ("inbox","outbox")}
