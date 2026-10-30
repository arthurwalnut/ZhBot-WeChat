"""The requested word-list import is additive and runs once per database."""
from importlib.resources import files
import json
import sqlite3

from wechat_bot import dictionaries


def test_word_space_import_preserves_owner_edits_and_is_not_repeated(tmp_path):
    defaults = json.loads(files('wordle').joinpath('words.json').read_text())
    upgrade = json.loads(files('wordle').joinpath('word_space_upgrade.json').read_text())
    prior = set(upgrade['prior_seed_words'])
    novel_answers = sorted(set(defaults['answers']) - prior)
    with sqlite3.connect(tmp_path / 'old.sqlite3') as connection:
        connection.execute('CREATE TABLE dictionary_state (name TEXT PRIMARY KEY)')
        connection.execute("INSERT INTO dictionary_state VALUES ('wordle')")
        connection.execute('CREATE TABLE wordle_words (word TEXT PRIMARY KEY,is_answer INTEGER NOT NULL)')
        # The owner deleted apple, added a custom word, and made one future
        # upstream answer guess-only. None of those choices may be overwritten.
        connection.executemany('INSERT INTO wordle_words VALUES (?,0)',
                               [(word,) for word in sorted(prior - {'apple'})])
        connection.execute("INSERT INTO wordle_words VALUES ('zzzzz',1)")
        connection.execute('INSERT INTO wordle_words VALUES (?,0)', (novel_answers[0],))
        dictionaries.initialize(connection)
        answers, allowed = dictionaries.words(connection)
        assert 'apple' not in allowed and 'zzzzz' in answers
        assert novel_answers[0] in allowed and novel_answers[0] not in answers
        assert novel_answers[1] in answers
        assert set(defaults['allowed_guesses']) - prior <= allowed
        dictionaries.change_words(connection, remove=[novel_answers[1]])
        dictionaries.initialize(connection)
        assert novel_answers[1] not in dictionaries.words(connection)[1]
        assert connection.execute("SELECT COUNT(*) FROM dictionary_state WHERE name LIKE 'word_space:%'").fetchone()[0] == 1
