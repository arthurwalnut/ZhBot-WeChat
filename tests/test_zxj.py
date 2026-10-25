from datetime import UTC, datetime, timedelta, timezone
import sqlite3

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
