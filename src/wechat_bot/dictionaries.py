"""Owner-edited dictionaries in the bot database, using caller transactions.

Packaged JSON seeds new databases. The versioned word-space expansion adds only
new seed words once, retaining prior seed deletions and existing word attributes.
"""
from importlib.resources import files
import json
import re
import unicodedata


def _transaction(connection):
    if not connection.in_transaction:
        raise ValueError("词库修改需要已开启的事务")


def _characters(groups):
    if not isinstance(groups, dict) or set(groups) != {"z", "x", "j"}:
        raise ValueError("字库需要完整的 z、x、j 三组")
    result = {}
    for initial in ("z", "x", "j"):
        values = groups[initial]
        if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 2000:
            raise ValueError(f"{initial} 组需要 1～2000 个汉字")
        if any(not isinstance(char, str) or len(char) != 1 or not unicodedata.name(char, "").startswith(
                ("CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH")) for char in values):
            raise ValueError(f"{initial} 组只接受单个汉字")
        if len(set(values)) != len(values):
            raise ValueError(f"{initial} 组含重复汉字")
        result[initial] = list(values)
    return result


def initialize(connection):
    _transaction(connection)
    connection.execute("CREATE TABLE IF NOT EXISTS dictionary_state (name TEXT PRIMARY KEY)")
    connection.execute("""CREATE TABLE IF NOT EXISTS zxj_characters (
        initial TEXT NOT NULL CHECK(initial IN ('z','x','j')), position INTEGER NOT NULL,
        character TEXT NOT NULL, PRIMARY KEY(initial,character), UNIQUE(initial,position))""")
    connection.execute("""CREATE TABLE IF NOT EXISTS wordle_words (
        word TEXT PRIMARY KEY, is_answer INTEGER NOT NULL CHECK(is_answer IN (0,1)))""")
    if not connection.execute("SELECT 1 FROM dictionary_state WHERE name='zxj'").fetchone():
        defaults = json.loads(files("zxj").joinpath("characters.json").read_text(encoding="utf-8"))
        save_characters(connection, defaults)
        connection.execute("INSERT INTO dictionary_state VALUES ('zxj')")
    if not connection.execute("SELECT 1 FROM dictionary_state WHERE name='wordle'").fetchone():
        defaults = json.loads(files("wordle").joinpath("words.json").read_text(encoding="utf-8"))
        answers = set(defaults["answers"])
        connection.executemany("INSERT INTO wordle_words VALUES (?,?)", [
            (word, int(word in answers)) for word in sorted(answers | set(defaults["allowed_guesses"]))])
        connection.execute("INSERT INTO dictionary_state VALUES ('wordle')")
    # Import this requested expansion once. Old seed words are excluded so an
    # owner's old-seed deletions and existing answer choices survive the upgrade.
    revision = 'word_space:6b2ce3432d5753d2b77724e0255ca6d4d019d34d'
    if not connection.execute("SELECT 1 FROM dictionary_state WHERE name=?", (revision,)).fetchone():
        defaults = json.loads(files("wordle").joinpath("words.json").read_text(encoding="utf-8"))
        upgrade = json.loads(files("wordle").joinpath("word_space_upgrade.json").read_text(encoding="utf-8"))
        answers = set(defaults['answers'])
        additions = (answers | set(defaults['allowed_guesses'])) - set(upgrade['prior_seed_words'])
        connection.executemany("INSERT OR IGNORE INTO wordle_words VALUES (?,?)",
                               [(word, int(word in answers)) for word in sorted(additions)])
        connection.execute("INSERT INTO dictionary_state VALUES (?)", (revision,))


def characters(connection):
    groups = {initial: [] for initial in ("z", "x", "j")}
    for initial, _, char in connection.execute(
            "SELECT initial,position,character FROM zxj_characters ORDER BY initial,position"):
        groups[initial].append(char)
    return _characters(groups)


def save_characters(connection, groups):
    _transaction(connection)
    groups = _characters(groups)  # Validate every group before changing any row.
    connection.execute("DELETE FROM zxj_characters")
    connection.executemany("INSERT INTO zxj_characters VALUES (?,?,?)", [
        (initial, position, char) for initial, values in groups.items()
        for position, char in enumerate(values)])
    return groups


def words(connection):
    rows = list(connection.execute("SELECT word,is_answer FROM wordle_words ORDER BY word"))
    return tuple(word for word, answer in rows if answer), frozenset(word for word, _ in rows)


def _word_list(values):
    if not isinstance(values, (list, tuple)) or len(values) > 10000:
        raise ValueError("每次最多修改 10000 个单词")
    result = set()
    for value in values:
        if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z]{3,10}", value.strip()):
            raise ValueError("单词需要 3～10 个英文字母")
        result.add(value.strip().lower())
    return result


def change_words(connection, *, add=(), remove=()):
    _transaction(connection)
    added, removed = _word_list(add), _word_list(remove)
    if added & removed:
        raise ValueError("同一个单词不能同时添加和删除")
    current_answers, current_allowed = words(connection)
    if not ((set(current_answers) - removed) | added):
        raise ValueError("答案词库至少需要保留一个单词")
    connection.executemany("DELETE FROM wordle_words WHERE word=?", [(word,) for word in sorted(removed)])
    connection.executemany("INSERT INTO wordle_words VALUES (?,1) ON CONFLICT(word) DO UPDATE SET is_answer=1",
                           [(word,) for word in sorted(added)])
    return {"added": len(added - set(current_answers)), "removed": len(removed & current_allowed)}
