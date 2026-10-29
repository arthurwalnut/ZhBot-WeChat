from datetime import UTC, datetime, timedelta, timezone
import sqlite3

import pytest

from zxj.service import draw, history


def test_daily_draw_independence_midnight_and_persistence(tmp_path):
    db_path = tmp_path / "zxj.sqlite3"
    before_midnight = datetime(2026, 10, 25, 15, 59, 59, tzinfo=UTC)

    first = draw("alice", db_path, before_midnight)
    # The same instant expressed in a different timezone uses the same Beijing day.
    repeated = draw("alice", db_path, before_midnight.astimezone(timezone(timedelta(hours=-7))))
    bob = draw("bob", db_path, before_midnight)
    assert first["is_first"] is True
    assert repeated == {**first, "is_first": False}
    assert first["business_date"] == "2026-10-25"
    assert len(first["result"]) == 3
    assert bob["is_first"] is True

    tomorrow = draw("alice", db_path, before_midnight + timedelta(seconds=1))
    assert tomorrow["is_first"] is True
    assert tomorrow["business_date"] == "2026-10-26"
    # A new day may randomly draw the same text: date uniqueness is the rule.
    with sqlite3.connect(db_path) as reopened:
        assert reopened.execute("SELECT COUNT(*) FROM draws").fetchone()[0] == 3

    records = history("alice", db_path)
    assert [row["business_date"] for row in records] == ["2026-10-26", "2026-10-25"]
    assert records[1]["result"] == first["result"]
    assert history("alice", db_path, limit=1) == records[:1]
    assert len(history("bob", db_path)) == 1


def test_admin_characters_are_live_and_daily_results_stay_saved(tmp_path):
    from wechat_bot.dictionaries import initialize, characters, save_characters
    from zxj.service import initialize_schema

    path = tmp_path / 'bot.sqlite3'
    before = datetime(2026, 10, 30, 1, tzinfo=UTC)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute('BEGIN IMMEDIATE')
        initialize_schema(connection)
        initialize(connection)
        save_characters(connection, {'z': ['中'], 'x': ['心'], 'j': ['家']})
        first = draw('alice', now=before, connection=connection, characters=characters(connection))
        assert first['result'] == '中心家'
        save_characters(connection, {'z': ['早'], 'x': ['新'], 'j': ['今']})
        # Same-day saved result survives dictionary edits, other members use them.
        assert draw('alice', now=before, connection=connection, characters=characters(connection))['result'] == '中心家'
        assert draw('bob', now=before, connection=connection, characters=characters(connection))['result'] == '早新今'
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute('BEGIN IMMEDIATE')
        initialize(connection)  # Reopening must not replace owner edits with seeds.
        original = characters(connection)
        for invalid in ({'z': [], 'x': ['心'], 'j': ['家']},
                        {'z': ['早', '早'], 'x': ['心'], 'j': ['家']},
                        {'z': ['A'], 'x': ['心'], 'j': ['家']}):
            with pytest.raises(ValueError):
                save_characters(connection, invalid)
            assert characters(connection) == original
        save_characters(connection, {'z': ['中'], 'x': ['心'], 'j': ['家']})
        connection.rollback()
        assert characters(connection) == original
