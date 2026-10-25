import pytest

from wordle.game import GameError, WordleService, score_guess


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
