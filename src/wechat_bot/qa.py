"""Owner-authored exact-match replies, shared by this account's allowed groups."""
import json
import secrets
import sqlite3
import time


MAX_REPLIES = 20
MAX_REPLY_BYTES = 700  # One existing outbox text segment, leaving room for @ labels.


def initialize(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS simple_qa (
        id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL UNIQUE,
        replies_json TEXT NOT NULL, updated_at REAL NOT NULL)""")


def _item(row):
    replies = json.loads(row['replies_json'])
    return {'id': row['id'], 'question': row['question'], 'replies': replies,
            'reply_count': len(replies), 'updated_at': row['updated_at']}


def list_page(connection, *, search='', page=1):
    if not isinstance(search, str) or len(search) > 128:
        raise ValueError('问答搜索内容最多 128 个字符')
    if type(page) is not int or not 1 <= page <= 1_000_000:
        raise ValueError('页码需要为正整数')
    search = search.strip()
    total = connection.execute('SELECT COUNT(*) FROM simple_qa WHERE instr(question,?)>0', (search,)).fetchone()[0]
    pages = max(1, (total + 29) // 30)
    page = min(page, pages)
    rows = connection.execute('''SELECT * FROM simple_qa WHERE instr(question,?)>0
        ORDER BY id DESC LIMIT 30 OFFSET ?''', (search, (page - 1) * 30))
    return {'items': [_item(row) for row in rows], 'page': page, 'pages': pages, 'total': total}


def _identifier(value):
    if type(value) is not int or value <= 0:
        raise ValueError('请选择已有问答')
    return value


def save(connection, *, question, replies, identifier=None):
    # Lazy import keeps the database schema independent of command routing.
    from .router import ADMIN, COMMAND
    from .groups import _code

    if not isinstance(question, str):
        raise ValueError('问题需要为文本')
    question = question.strip()
    if not 1 <= len(question) <= 128 or any(ord(ch) < 32 or ord(ch) == 127 for ch in question):
        raise ValueError('问题需要 1～128 个字符，不能包含换行或控制字符')
    if COMMAND.fullmatch(question) or question in ADMIN or _code(question):
        raise ValueError('简单问答不能覆盖内置指令')
    if not isinstance(replies, list) or not 1 <= len(replies) <= MAX_REPLIES:
        raise ValueError('请添加 1～20 条候选回复')
    for value in replies:
        if (not isinstance(value, str) or not value.strip() or '\0' in value
                or len(value.encode('utf-8')) > MAX_REPLY_BYTES):
            raise ValueError('每条回复需非空、不含空字符，且最多 700 个 UTF-8 字节')
    if len(set(replies)) != len(replies):
        raise ValueError('候选回复不能重复')
    encoded, updated = json.dumps(replies, ensure_ascii=False), time.time()
    try:
        if identifier is None:
            identifier = connection.execute('''INSERT INTO simple_qa(question,replies_json,updated_at)
                VALUES (?,?,?)''', (question, encoded, updated)).lastrowid
        else:
            _identifier(identifier)
            result = connection.execute('''UPDATE simple_qa SET question=?,replies_json=?,updated_at=? WHERE id=?''',
                                        (question, encoded, updated, identifier))
            if result.rowcount != 1:
                raise ValueError('该问答已不存在，请刷新列表')
    except sqlite3.IntegrityError:
        raise ValueError('这个问题已经存在，请编辑原问答') from None
    return _item(connection.execute('SELECT * FROM simple_qa WHERE id=?', (identifier,)).fetchone())


def delete(connection, identifier):
    result = connection.execute('DELETE FROM simple_qa WHERE id=?', (_identifier(identifier),))
    if result.rowcount != 1:
        raise ValueError('该问答已不存在，请刷新列表')
    return {'deleted': True, 'id': identifier}


def choose(connection, question):
    """Called inside the inbox/outbox transaction; sending retries use saved text."""
    row = connection.execute('SELECT replies_json FROM simple_qa WHERE question=?', (question,)).fetchone()
    return secrets.choice(json.loads(row[0])) if row else None
