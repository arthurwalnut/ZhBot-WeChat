"""Word validation, scoring and persistent game transitions."""

from collections import Counter
from datetime import datetime, timezone
from importlib.resources import files
import json
import re
import secrets

from .store import WordleStore


class GameError(ValueError):
    """A rejected action leaves the saved game unchanged."""


def score_guess(answer, guess):
    """Score green positions first, then consume the remaining letter counts."""
    answer, guess = answer.lower(), guess.lower()
    if len(answer) != len(guess) or not re.fullmatch(r"[a-z]+", answer + guess):
        raise ValueError("answer and guess must be equal-length English words")
    colors = ["gray"] * len(answer)
    remaining = Counter()
    for index, letter in enumerate(answer):
        if guess[index] == letter:
            colors[index] = "green"
        else:
            remaining[letter] += 1
    for index, letter in enumerate(guess):
        if colors[index] != "green" and remaining[letter]:
            colors[index] = "yellow"
            remaining[letter] -= 1
    return colors


def _identifier(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise GameError(f"{name} 需要 1–128 个字符。")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise GameError(f"{name} 不能含控制字符。")
    return value.strip()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_words():
    data = json.loads(files("wordle").joinpath("words.json").read_text(encoding="utf-8"))
    answers = tuple(data["answers"])
    allowed = frozenset(data["allowed_guesses"]) | frozenset(answers)
    if not answers or any(not re.fullmatch(r"[a-z]{3,10}", word) for word in allowed):
        raise ValueError("words.json 需要 3–10 位的小写英文单词。")
    if len(answers) != len(set(answers)):
        raise ValueError("words.json 答案池存在重复单词。")
    return answers, allowed


def supported_lengths():
    answers, _ = _load_words()
    return sorted({len(word) for word in answers})


class WordleService:
    def __init__(self, db_path, *, answer_picker=None, initialize=True):
        self.store = WordleStore(db_path, initialize=initialize)
        self.answers, self.allowed = _load_words()
        # Tests may choose a fixed answer; the normal CLI exposes no answer override.
        self.answer_picker = answer_picker or secrets.choice

    @staticmethod
    def _board(game):
        board = {
            "game_id": game["id"], "group_id": game["group_id"],
            "creator_id": game["creator_id"], "length": game["length"],
            "status": game["status"], "winner_id": game["winner_id"],
            "created_at_utc": game["created_at_utc"], "ended_at_utc": game["ended_at_utc"],
            "max_guesses": 6,
            "guesses": [
                {"turn_number": item["turn_number"], "user_id": item["user_id"],
                 "word": item["word"], "created_at_utc": item["created_at_utc"],
                 "colors": score_guess(game["answer"], item["word"])}
                for item in game["guesses"]
            ],
        }
        if game["status"] != "active":
            board["answer"] = game["answer"]
        return board

    def start(self, group_id, user_id, length=5, *, connection=None):
        group_id, user_id = _identifier(group_id, "group"), _identifier(user_id, "user")
        candidates = tuple(word for word in self.answers if len(word) == length)
        if not candidates:
            raise GameError(f"本地答案词库支持的长度：{', '.join(map(str, supported_lengths()))}。")
        with self.store.transaction(connection) as connection:
            existing = self.store.load(connection, group_id, active_only=True)
            if existing:
                raise GameError(f"该群已有进行中的对局 #{existing['id']}；请继续猜测或由开局者结束。")
            answer = self.answer_picker(candidates)
            if answer not in candidates:
                raise ValueError("answer_picker returned a word outside the answer pool")
            game_id = self.store.create(connection, group_id, user_id, answer, _now())
            return self._board(self.store.load(connection, group_id, game_id))

    def guess(self, group_id, user_id, word, *, connection=None):
        group_id, user_id = _identifier(group_id, "group"), _identifier(user_id, "user")
        with self.store.transaction(connection) as connection:
            game = self.store.load(connection, group_id)
            if game is None:
                raise GameError("该群尚无对局；请先 start。")
            if game["status"] != "active":
                raise GameError(f"对局 #{game['id']} 已结束（{game['status']}）；请 start 新局。")
            if not re.fullmatch(r"[a-zA-Z]+", word):
                raise GameError("猜测只接受英文字母，不消耗机会。")
            word = word.lower()
            if len(word) != game["length"]:
                raise GameError(f"本局需要 {game['length']} 个字母，不消耗机会。")
            if word not in self.allowed:
                raise GameError("本地词库未收录该词，不消耗机会。")
            if any(item["word"] == word for item in game["guesses"]):
                raise GameError("该词已猜过，不消耗机会。")
            turn, timestamp = len(game["guesses"]) + 1, _now()
            self.store.add_guess(connection, game["id"], turn, user_id, word, timestamp)
            if word == game["answer"]:
                self.store.finish(connection, game["id"], "won", timestamp, user_id)
            elif turn == 6:
                self.store.finish(connection, game["id"], "lost", timestamp)
            return self._board(self.store.load(connection, group_id, game["id"]))

    def current(self, group_id, game_id=None, *, connection=None):
        group_id = _identifier(group_id, "group")
        with self.store.transaction(connection) as connection:
            game = self.store.load(connection, group_id, game_id)
            if game is None:
                raise GameError("找不到该群的指定对局。")
            return self._board(game)

    def stats(self, user_id, group_id=None, *, connection=None):
        user_id = _identifier(user_id, "user")
        if group_id is not None:
            group_id = _identifier(group_id, "group")
        with self.store.transaction(connection) as connection:
            result = {"user_id": user_id, "wins": self.store.wins(connection, user_id, group_id)}
            if group_id is not None:
                result["group_id"] = group_id
            return result

    def end(self, group_id, user_id, *, owner_id=None, connection=None):
        group_id, user_id = _identifier(group_id, "group"), _identifier(user_id, "user")
        if owner_id is not None:
            owner_id = _identifier(owner_id, "owner")
        with self.store.transaction(connection) as connection:
            game = self.store.load(connection, group_id)
            if game is None:
                raise GameError("该群尚无对局。")
            if user_id != game["creator_id"] and user_id != owner_id:
                raise GameError("只有本局开局者或配置主人可以 end。")
            if game["status"] != "active":
                raise GameError(f"对局 #{game['id']} 已结束（{game['status']}）。")
            self.store.finish(connection, game["id"], "ended", _now())
            return self._board(self.store.load(connection, group_id, game["id"]))
