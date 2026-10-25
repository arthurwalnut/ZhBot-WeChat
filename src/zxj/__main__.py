"""Command-line entry point for local zxj draws."""

import argparse
from pathlib import Path
import sqlite3

from .service import draw, history


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="随机 zxj：每位本地用户北京时间每天抽取一次")
    parser.add_argument("--data-dir", default="runtime", help="数据目录（默认 runtime）")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("draw", "抽取今日组合；重复请求返回原结果"), ("history", "查询历史")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--user", required=True, help="本地模拟用户 ID，例如 alice")
        command.add_argument("--data-dir", default=argparse.SUPPRESS, help="数据目录（默认 runtime）")
        if name == "history":
            command.add_argument("--limit", type=int, help="最多显示多少条（默认全部）")
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir).expanduser().resolve()
    print(f"数据目录：{data_dir}")
    db_path = data_dir / "zxj.sqlite3"
    try:
        if args.command == "draw":
            record = draw(args.user, db_path)
            state = "今日首次抽取" if record["is_first"] else "今日已抽取，返回原结果"
            print(f"{record['business_date']}  {args.user}  {record['result']}  （{state}）")
        else:
            records = history(args.user, db_path, args.limit)
            if not records:
                print(f"{args.user} 暂无抽取记录")
            for record in records:
                print(f"{record['business_date']}  {record['result']}")
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"错误：{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
