"""Versioned imports preserve owner choices and in-progress game snapshots."""
from importlib.resources import files
import json
import re
import sqlite3

import pytest

from wechat_bot import dictionaries
from wordle.game import WordleService
from wordle.store import WordleStore


WORD_SPACE = 'word_space:6b2ce3432d5753d2b77724e0255ca6d4d019d34d'
WORD_LISTS = 'word_lists:89401c32360e839f36cbe37716e14c5456ce8034'


def vocabularies():
    package = files('wordle')
    defaults = json.loads(package.joinpath('words.json').read_text(encoding='utf-8'))
    old = json.loads(package.joinpath('word_space_upgrade.json').read_text(encoding='utf-8'))
    upgrade = json.loads(package.joinpath('word_lists_upgrade.json').read_text(encoding='utf-8'))
    return defaults, old, upgrade


@pytest.mark.parametrize('previous_version', ['0.2.6', '0.2.7'])
def test_upgrade_preserves_owner_edits_old_games_and_runs_once(tmp_path, previous_version):
    defaults, old, upgrade = vocabularies()
    current = set(defaults['answers']) | set(defaults['allowed_guesses'])
    prior_026, prior_027 = set(old['prior_seed_words']), set(upgrade['prior_seed_words'])
    prior = prior_026 if previous_version == '0.2.6' else prior_027
    novel = sorted(current - prior_027)
    assert len(novel) > 2
    deleted = {'apple'}
    if previous_version == '0.2.7':
        # A word introduced in v0.2.7 and later removed must stay removed too.
        deleted.add(sorted(prior_027 - prior_026)[0])
    custom = 'zzzzzzzzzz'
    assert custom not in current
    path = tmp_path / 'old.sqlite3'
    snapshot = json.dumps(['alley', 'apple'])
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE dictionary_state (name TEXT PRIMARY KEY)')
        connection.execute("INSERT INTO dictionary_state VALUES ('wordle')")
        if previous_version == '0.2.7':
            connection.execute('INSERT INTO dictionary_state VALUES (?)', (WORD_SPACE,))
        connection.execute('CREATE TABLE wordle_words (word TEXT PRIMARY KEY,is_answer INTEGER NOT NULL)')
        connection.executemany('INSERT INTO wordle_words VALUES (?,0)',
                               [(word,) for word in sorted(prior - deleted)])
        connection.execute('INSERT INTO wordle_words VALUES (?,1)', (custom,))
        # An owner-added, guess-only word overlaps this new upstream dataset.
        connection.execute('INSERT INTO wordle_words VALUES (?,0)', (novel[0],))
        previous_words = dict(connection.execute('SELECT word,is_answer FROM wordle_words'))
        WordleStore.initialize_schema(connection)
        connection.execute('''INSERT INTO games
            (group_id,creator_id,length,answer,status,created_at_utc,max_guesses,allowed_words_json)
            VALUES ('old-group','alice',5,'apple','active','2026-10-30T00:00:00+00:00',6,?)''', (snapshot,))
        previous_game = connection.execute('SELECT * FROM games').fetchone()

        dictionaries.initialize(connection)
        answers, allowed = dictionaries.words(connection)
        assert allowed == (current - deleted) | {custom}
        assert custom in answers and novel[0] not in answers and novel[1] in answers
        after_words = dict(connection.execute('SELECT word,is_answer FROM wordle_words'))
        assert all(after_words[word] == value for word, value in previous_words.items())
        assert len(after_words) == len(allowed)
        assert connection.execute('SELECT * FROM games').fetchone() == previous_game
        assert connection.execute('SELECT COUNT(*) FROM dictionary_state WHERE name IN (?,?)',
                                  (WORD_SPACE, WORD_LISTS)).fetchone()[0] == 2
        dictionaries.change_words(connection, remove=[novel[1]])
        dictionaries.initialize(connection)
        assert novel[1] not in dictionaries.words(connection)[1]

    # A new connection and normal game initialization still use the old inline
    # snapshot, including an answer which the owner removed from the live pool.
    game = WordleService(path)
    assert game.guess('old-group', 'bob', 'alley')['status'] == 'active'
    assert game.guess('old-group', 'alice', 'apple')['status'] == 'won'
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT allowed_words_json FROM games').fetchone()[0] == snapshot
        connection.execute('BEGIN')
        dictionaries.initialize(connection)
        assert not ({*deleted, novel[1]} & dictionaries.words(connection)[1])
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []


def test_fresh_database_contains_unique_merged_vocabulary(tmp_path):
    defaults, _, upgrade = vocabularies()
    expected = set(defaults['answers']) | set(defaults['allowed_guesses'])
    assert len(defaults['answers']) == len(set(defaults['answers']))
    assert len(defaults['allowed_guesses']) == len(set(defaults['allowed_guesses']))
    assert set(upgrade['prior_seed_words']) <= expected
    assert set(upgrade['prior_seed_answers']) <= set(defaults['answers'])
    assert all(re.fullmatch(r'[a-z]{3,10}', word) for word in expected)
    assert {len(word) for word in defaults['answers']} == set(range(3, 11))
    with sqlite3.connect(tmp_path / 'new.sqlite3') as connection:
        connection.execute('BEGIN')
        dictionaries.initialize(connection)
        answers, allowed = dictionaries.words(connection)
        assert set(answers) == set(defaults['answers']) and allowed == expected
        assert connection.execute('SELECT COUNT(*) FROM wordle_words').fetchone()[0] == len(expected)
        before = connection.execute('SELECT COUNT(*) FROM dictionary_state').fetchone()[0]
        dictionaries.initialize(connection)
        assert connection.execute('SELECT COUNT(*) FROM dictionary_state').fetchone()[0] == before
        assert connection.execute('SELECT COUNT(*) FROM wordle_words').fetchone()[0] == len(expected)
