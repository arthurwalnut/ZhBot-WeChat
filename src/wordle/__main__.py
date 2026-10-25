"""Five local CLI actions; each completed board is rendered to a PNG."""

import argparse
from pathlib import Path
import sqlite3
import sys

from .game import GameError, WordleService, supported_lengths
from .render import render_board


def build_parser():
    lengths = ", ".join(map(str, supported_lengths()))
    parser = argparse.ArgumentParser(description=f"本地多人 Wordle；本地词库支持长度：{lengths}；共用 6 次机会。")
    parser.add_argument("--data-dir", default="runtime", help="数据库和图片目录（默认 runtime）")
    commands = parser.add_subparsers(dest="command", required=True)
    for action in ("start", "guess", "board", "stats", "end"):
        command = commands.add_parser(action)
        # Accept --data-dir before or after the subcommand.
        command.add_argument("--data-dir", default=argparse.SUPPRESS, help="数据库和图片目录")
        if action != "stats":
            command.add_argument("--group", required=True, help="本地模拟群 ID")
        if action != "board":
            command.add_argument("--user", required=True, help="本地模拟用户 ID")
        if action == "start":
            command.add_argument("--length", type=int, default=5, help=f"默认 5；本地词库支持：{lengths}")
        elif action == "guess":
            command.add_argument("word", help="英文猜测词，大小写等价")
        elif action == "board":
            command.add_argument("--game", type=int, help="查询该群的历史对局 ID；默认最新一局")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    data_dir = Path(args.data_dir).expanduser().resolve()
    print(f"数据目录: {data_dir}")
    print(f"数据库: {data_dir / 'wordle.sqlite3'}")
    try:
        service = WordleService(data_dir / "wordle.sqlite3")
        if args.command == "stats":
            stats = service.stats(args.user)
            print(f"用户 {stats['user_id']} 猜中次数: {stats['wins']}")
            return 0
        if args.command == "start":
            board = service.start(args.group, args.user, args.length)
        elif args.command == "guess":
            board = service.guess(args.group, args.user, args.word)
        elif args.command == "board":
            board = service.current(args.group, args.game)
        else:
            board = service.end(args.group, args.user)
        print(f"对局 #{board['game_id']} | 群 {board['group_id']} | {board['status']} | {len(board['guesses'])}/6")
        labels = {"green": "绿", "yellow": "黄", "gray": "灰"}
        for guess in board["guesses"]:
            colors = " ".join(labels[color] for color in guess["colors"])
            print(f"{guess['turn_number']}. {guess['user_id']}: {guess['word'].upper()}  {colors}")
        if "answer" in board:
            print(f"答案: {board['answer'].upper()}")
        if board["winner_id"]:
            print(f"猜中者: {board['winner_id']}")
        image_path = data_dir / "boards" / (
            f"wordle-{board['game_id']}-{len(board['guesses'])}-{board['status']}.png"
        )
        try:
            print(f"棋盘图片: {render_board(board, image_path)}")
        except OSError as exc:
            print(f"对局已保存，图片生成失败：{exc}。可用 board 重新生成。", file=sys.stderr)
            return 1
        return 0
    except (GameError, sqlite3.Error, OSError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
