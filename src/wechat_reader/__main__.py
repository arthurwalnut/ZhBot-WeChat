"""Local diagnostic/selection/observation CLI. No input injection."""

import argparse
from dataclasses import asdict
import json
import multiprocessing
from pathlib import Path
import sys
import time
import tomllib

from .reader import SnapshotDiffer
from .backend import query_worker


def query(action, argument=None):
    # Some UIA providers hang. Bound each read without killing the WeChat process.
    parent, child = multiprocessing.Pipe(duplex=False)
    process = multiprocessing.Process(target=query_worker, args=(child, action, argument), daemon=True)
    process.start()
    child.close()
    try:
        if not parent.poll(12):
            raise RuntimeError("UIA 查询超过 12 秒，已停止本次读取；微信未被关闭。")
        try:
            ok, result = parent.recv()
        except EOFError as exc:
            raise RuntimeError("UIA 查询子进程提前退出，未获得读取结果。") from exc
        if not ok:
            raise RuntimeError(result)
        return result
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        parent.close()


def save_json(path, value):
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"诊断文件：{path}")


def selection(args):
    report = query("doctor")
    windows = report["windows"]
    if not windows:
        raise ValueError("没有可选择的微信窗口。请登录并手工打开微信，再运行 doctor/select。")
    for index, window in enumerate(windows, 1):
        print(f"{index}. HWND={window['hwnd']} PID={window['pid']} "
              f"版本={window['version']} 标题={window['window_title']!r} 最小化={window['minimized']}")
    if args.hwnd is not None:
        selected = [window for window in windows if window["hwnd"] == args.hwnd]
        if len(selected) != 1:
            raise ValueError("--hwnd 未唯一匹配当前微信窗口。")
        window = selected[0]
    else:
        index = int(input("请选择拟读取账号的窗口编号（即使只有一个也需选择）："))
        if not 1 <= index <= len(windows):
            raise ValueError("窗口编号超出范围。")
        window = windows[index - 1]
    account = args.account_alias or input("本地账号别名（不是微信 ID）：").strip()
    chat = args.chat_alias or input("本地会话别名（群聊/私聊分别配置）：").strip()
    title = args.chat_title or input("手工打开目标会话后，填写界面显示的完整会话标题：").strip()
    if not all((account, chat, title)):
        raise ValueError("别名与会话标题不能为空。")
    path = args.config.resolve()
    if path.exists() and input(f"替换已有配置 {path}？输入 yes：").strip() != "yes":
        raise ValueError("已保留原配置。")
    lines = ["# 会话选择是本地定位信息；原生微信身份尚未识别。",
             "# 尚无已实测的消息规则。按真实 UIA 树填写下方 selectors 后才可 watch。",
             "[binding]"]
    for key in ("hwnd", "pid", "process_started", "process_path", "class_name", "version"):
        if window[key] is not None:
            lines.append(f"{key} = {json.dumps(window[key], ensure_ascii=False)}")
    lines.extend(["", "[chat]", f"account_alias = {json.dumps(account, ensure_ascii=False)}",
                  f"alias = {json.dumps(chat, ensure_ascii=False)}",
                  f"title = {json.dumps(title, ensure_ascii=False)}",
                  f"expected_type = {json.dumps(args.expected_type)}",
                  "# expected_type 是用户提供的预期；实际探测类型仍为 null。"])
    for section in ("title", "messages", "row", "text"):
        lines.extend(["", f"[selectors.{section}]", "# 可填写 control_type / class_name / automation_id / name；必须来自真实控件。"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已保存窗口选择：{path}")
    print("消息定位规则尚未完成；select 成功不代表真实接入成功。")


def watch(args):
    config = tomllib.loads(args.config.read_text(encoding="utf-8"))
    for name in ("title", "messages", "row", "text"):
        if not config.get("selectors", {}).get(name):
            raise ValueError(f"{name} 控件规则尚未配置；微信真实读取未完成。请先检查真实会话 UIA。")
    if args.interval < 0.5:
        raise ValueError("--interval 至少为 0.5 秒。")
    differ = SnapshotDiffer(config["chat"]["account_alias"], config["chat"]["alias"])
    print("只读观察：初始快照不作为新消息。字段缺失为 null；无法识别所有账号切换或同名会话。")
    print("当前版本的群聊/私聊真实接收尚未验证；首次运行需要人工核对来源与正文。")
    if args.jsonl:
        args.jsonl = args.jsonl.resolve()
        args.jsonl.parent.mkdir(parents=True, exist_ok=True)
        print(f"用户选择保存 JSONL：{args.jsonl}")
    while True:
        snapshot = query("snapshot", config)
        result = differ.update(snapshot)
        if result.status != "unchanged":
            print(f"观察状态：{result.status}" + (f"；{result.reason}" if result.reason else ""), flush=True)
        for event in result.events:
            line = json.dumps(asdict(event), ensure_ascii=False)
            print(line, flush=True)
            if args.jsonl:
                with args.jsonl.open("a", encoding="utf-8") as output:
                    output.write(line + "\n")
        if args.once:
            break
        time.sleep(args.interval)


def main():
    parser = argparse.ArgumentParser(description="微信只读 UIA 探测与观察；真实接收尚待验证")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="真实系统、依赖、微信版本与窗口诊断")
    doctor.add_argument("--hwnd", type=int, help="探测 doctor 返回的指定窗口 UIA 树")
    doctor.add_argument("--include-text", action="store_true", help="明确选择将该窗口 UIA 文字写入本地诊断（可能含聊天内容）")
    doctor.add_argument("--reported-version", help="检测失败时记录人工版本；不替代 detected version")
    doctor.add_argument("--output", type=Path, default=Path("runtime/doctor.json"))
    select = commands.add_parser("select", help="明确选择窗口；保存本地别名和待校准规则")
    select.add_argument("--config", type=Path, default=Path("runtime/config.local.toml"))
    select.add_argument("--hwnd", type=int)
    select.add_argument("--account-alias")
    select.add_argument("--chat-alias")
    select.add_argument("--chat-title")
    select.add_argument("--expected-type", choices=("unknown", "private", "group"), default="unknown")
    watch_parser = commands.add_parser("watch", help="绑定所选窗口并观察；规则缺失时明确停止")
    watch_parser.add_argument("--config", type=Path, default=Path("runtime/config.local.toml"))
    watch_parser.add_argument("--interval", type=float, default=1)
    watch_parser.add_argument("--jsonl", type=Path, help="主动启用原始观察记录保存；默认只打印终端")
    watch_parser.add_argument("--once", action="store_true", help="只建立一次基线，用于验证绑定")
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            if args.include_text and args.hwnd is None:
                raise ValueError("--include-text 需要同时指定 --hwnd。")
            report = query("doctor")
            if args.reported_version:
                report["user_reported_version"] = args.reported_version
            if args.hwnd is not None:
                found = [w for w in report["windows"] if w["hwnd"] == args.hwnd]
                if len(found) != 1:
                    raise ValueError("当前窗口列表未唯一匹配 --hwnd。")
                report["probe"] = query("probe", (found[0], args.include_text))
            save_json(args.output, report)
            print(json.dumps({key: value for key, value in report.items() if key != "probe"}, ensure_ascii=False, indent=2))
            if report["errors"]:
                return 1
        elif args.command == "select":
            selection(args)
        else:
            watch(args)
    except KeyboardInterrupt:
        print("\n观察已停止。")
        return 0
    except (ValueError, RuntimeError, OSError, EOFError, KeyError, TypeError) as exc:
        print(f"未完成：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
