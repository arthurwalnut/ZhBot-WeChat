import pytest
import sqlite3

from PIL import Image

from wordle.game import GameError, WordleService, score_guess, supported_lengths
from wordle.render import render_board
from wordle.store import WordleStore


def test_duplicate_letter_scoring():
    assert score_guess("APPLE", "ALLEY") == ["green", "yellow", "gray", "yellow", "gray"]
    assert score_guess("eerie", "refer") == ["yellow", "green", "gray", "yellow", "gray"]
    assert score_guess("apple", "apple") == ["green"] * 5
    assert score_guess("apple", "civic") == ["gray"] * 5


def test_multiplayer_persistence_and_loss(tmp_path):
    db_path = tmp_path / "wordle.sqlite3"
    service = WordleService(db_path, answer_picker=lambda words: "apple")
    first = service.start("demo", "alice")
    assert first["status"] == "active" and "answer" not in first
    with pytest.raises(GameError):
        service.start("demo", "bob")
    for word in ("a!ple", "app", "zzzzz"):
        with pytest.raises(GameError):
            service.guess("demo", "bob", word)
    assert service.current("demo")["guesses"] == []
    service.guess("demo", "bob", "ALLEY")
    with pytest.raises(GameError):
        service.guess("demo", "carol", "alley")
    with pytest.raises(GameError):
        service.end("demo", "bob")
    service = WordleService(db_path, answer_picker=lambda words: "apple")
    resumed = service.current("demo")
    assert len(resumed["guesses"]) == 1 and resumed["guesses"][0]["user_id"] == "bob"
    won = service.guess("demo", "carol", "APPLE")
    assert won["status"] == "won" and won["winner_id"] == "carol"
    assert won["answer"] == "apple" and len(won["guesses"]) == 2
    with pytest.raises(GameError):
        service.guess("demo", "carol", "apple")
    service = WordleService(db_path, answer_picker=lambda words: "apple")
    assert service.stats("carol")["wins"] == 1
    assert service.stats("bob")["wins"] == 0
    assert service.current("demo") == won
    service.start("demo", "alice")
    service.start("independent", "dave")
    for word in ("about", "above", "actor", "acute", "admit", "adopt"):
        lost = service.guess("demo", "bob", word)
    assert lost["status"] == "lost" and len(lost["guesses"]) == 6
    assert lost["winner_id"] is None and service.stats("bob")["wins"] == 0
    assert service.current("demo", first["game_id"]) == won
    assert service.current("independent")["status"] == "active"
    ended = service.end("independent", "dave")
    assert ended["status"] == "ended" and service.stats("dave")["wins"] == 0


def test_legacy_migration_and_variable_length_relay(tmp_path):
    db_path = tmp_path / "legacy.sqlite3"
    # This is the v0.2.1 schema, including its six-turn SQLite constraint.
    with sqlite3.connect(db_path) as connection:
        connection.executescript("""
            CREATE TABLE games (
                id INTEGER PRIMARY KEY, group_id TEXT NOT NULL, creator_id TEXT NOT NULL,
                length INTEGER NOT NULL CHECK (length BETWEEN 3 AND 10), answer TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('active','won','lost','ended')),
                winner_id TEXT, created_at_utc TEXT NOT NULL, ended_at_utc TEXT);
            CREATE TABLE guesses (
                game_id INTEGER NOT NULL REFERENCES games(id),
                turn_number INTEGER NOT NULL CHECK (turn_number BETWEEN 1 AND 6),
                user_id TEXT NOT NULL, word TEXT NOT NULL, created_at_utc TEXT NOT NULL,
                PRIMARY KEY (game_id, turn_number), UNIQUE (game_id, word));
            INSERT INTO games VALUES (1,'legacy','alice',5,'apple','active',NULL,'earlier',NULL);
            INSERT INTO guesses VALUES (1,1,'bob','alley','earlier');
        """)
        connection.execute("BEGIN IMMEDIATE")
        WordleStore.initialize_schema(connection)
        connection.rollback()
        assert 'max_guesses' not in {row[1] for row in connection.execute('PRAGMA table_info(games)')}
        assert 'BETWEEN 1 AND 6' in connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='guesses'"
        ).fetchone()[0]

    service = WordleService(db_path, answer_picker=lambda words: words[0])
    legacy = service.current('legacy')
    assert legacy['max_guesses'] == 6 and legacy['guesses'][0]['word'] == 'alley'
    assert legacy['guesses'][0]['user_id'] == 'bob'
    assert service.guess('legacy', 'carol', 'apple')['winner_id'] == 'carol'
    assert supported_lengths() == list(range(3, 11))

    for length, limit in ((3,5), (4,5), (5,6), (6,6), (7,7), (8,7), (9,8), (10,8)):
        group = f'length-{length}'
        board = service.start(group, 'alice', length)
        assert board['length'] == length and board['max_guesses'] == limit
        candidates = [word for word in service.answers if len(word) == length]
        for turn, word in enumerate(candidates[1:limit+1], 1):
            # Reopen the same database between players, including beyond turn six.
            service = WordleService(db_path, answer_picker=lambda words: words[0])
            board = service.guess(group, 'alice' if turn % 2 else 'bob', word)
            assert len(board['guesses']) == turn
            assert board['status'] == ('lost' if turn == limit else 'active')
        with pytest.raises(GameError):
            service.guess(group, 'carol', candidates[0])
        assert service.stats('bob', group)['wins'] == 0
        path = render_board(board, tmp_path / f'board-{length}.png')
        with Image.open(path) as picture:
            assert picture.format == 'PNG'
            assert picture.height == 102 + limit * 74 - 8 + 85
            assert picture.getpixel((25, picture.height-62)) == (83,141,78)
            assert picture.getpixel((25, picture.height-33)) == (181,159,59)

    with service.store.transaction() as connection:
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    for invalid in (2,11,5.5,True):
        with pytest.raises(GameError):
            service.start('invalid', 'alice', invalid)
    # An already generated board remains renderable without new database fields.
    legacy.pop('max_guesses')
    render_board(legacy, tmp_path / 'legacy-outbox.png')
