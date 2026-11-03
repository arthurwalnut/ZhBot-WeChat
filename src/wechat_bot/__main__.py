"""Local administration and the single production bot entry point."""

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import time

from .config import Config, PROJECT_ROOT, load_config, write_config


def _print(value):
    # pythonw.exe has no console streams; runtime health remains in status.json.
    if sys.stdout is None:
        return
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str), flush=True)


def _process_alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None if ctypes.get_last_error() == 5 else False
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return None


def read_status(config):
    target = config.data_dir / "status.json"
    if not target.exists():
        return {"state": "STOPPED", "reason": "尚无运行状态记录", "data_dir": str(config.data_dir)}
    record = json.loads(target.read_text(encoding="utf-8"))
    alive = _process_alive(record.get("pid"))
    age = max(0, time.time() - record.get("updated_at", 0))
    record["process_alive"] = alive
    record["status_age_seconds"] = round(age, 1)
    record["data_dir"] = str(config.data_dir)
    record["recorded_state"] = record.get("state")
    if alive is False:
        record["state"] = "STOPPED"
    elif alive is None or age > 15:
        record["state"] = "STALE"
        record["reason"] = "状态文件陈旧或无法核验进程；不能据此确认连接"
    return record


def _parser():
    parser = argparse.ArgumentParser(description="Astra 群聊机器人：绑定、运行与本机管理")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "bind", "run", "status", "pause", "resume", "stop", "relocate"):
        item = sub.add_parser(name)
        item.add_argument("--config", type=Path, default=PROJECT_ROOT / "runtime" / "config.bot.toml")
        if name == "relocate":
            item.add_argument("--data-dir", type=Path, required=True, help="已复制到目标机器的数据目录")
            item.add_argument("--helper-root", type=Path, required=True, help="目标机器的固定 helper 目录")
        if name in ("doctor", "bind"):
            item.add_argument("--pid", type=int, help="明确指定机器人微信 PID")
        if name == "bind":
            item.add_argument("--account", help="必须与指定进程检测到的原生机器人 ID 一致")
            item.add_argument("--owner", help="主人原生微信 ID")
            item.add_argument("--group", action="append", help="允许的原生群 ID；可重复")
            item.add_argument("--observe", action="store_true", help="只接收实时身份元数据；加载桥接但不发送、不保存聊天")
            item.add_argument("--seconds", type=int, default=60)
    return parser


def _bind(args, config):
    from .adapters.helper_native import inspect_bound
    pid = args.pid or config.wechat_pid
    if not pid:
        raise ValueError("bind 需要 --pid 明确指定机器人微信进程")
    identity = inspect_bound(config.helper_root, pid)
    _print(identity)
    if not args.account:
        _print({"state": "BIND_REQUIRED", "next": "核对检测出的机器人账号，再带 --account、--group 执行 bind；--owner 可选。需要发现 ID 时使用 --account 与 --observe"})
        return
    if args.account != identity["account_id"]:
        raise ValueError("指定 --account 与该 PID 实际账号不一致，未加载桥接、未保存绑定")
    bound = replace(config, wechat_pid=pid, account_id=args.account,
                    owner_id=args.owner if args.owner is not None else config.owner_id,
                    group_allowlist=tuple(args.group) if args.group is not None else config.group_allowlist)
    if args.observe:
        if not 1 <= args.seconds <= 300:
            raise ValueError("--seconds 需要在 1–300 之间")
        from .adapters.helper_native import HelperNative
        gateway = HelperNative(bound.helper_root, bound.data_dir, bound.account_id, pid,
                               bound.group_allowlist, owner_id=bound.owner_id, binding_mode=True)

        def on_event(event):
            _print({"account_id": event.account_id, "chat_id": event.chat_id, "chat_type": event.chat_type,
                    "sender_id": event.sender_id, "native_message_id": event.native_message_id,
                    "message_type": event.message_type, "mentioned_ids": event.mentioned_ids,
                    "is_self": event.is_self})

        from .runtime import single_instance
        with single_instance(bound.data_dir):
            try:
                gateway.start(on_event)
                _print({"state": "OBSERVING", "seconds": args.seconds, "next": "请从指定测试群发送新消息，并由主人私聊机器人发送一条新消息"})
                deadline = time.monotonic() + args.seconds
                while time.monotonic() < deadline:
                    health = gateway.health()
                    if not health.get("connected"):
                        from .gateway import GatewayError
                        raise GatewayError("DEGRADED", "绑定观察连接已断开：" + str(health.get("error") or health.get("state")))
                    time.sleep(0.2)
            finally:
                gateway.stop()
        return
    bound.require_binding()
    # Validate explicit identities before replacing a user's working configuration.
    from .config import _identity
    _identity(bound.account_id, "account_id")
    _identity(bound.owner_id, "owner_id", allow_empty=True)
    if len(bound.group_allowlist) != len(set(bound.group_allowlist)):
        raise ValueError("群白名单不能重复")
    for group in bound.group_allowlist:
        _identity(group, "group_allowlist")
        if not group.endswith("@chatroom"):
            raise ValueError("群 ID 需要以 @chatroom 结尾")
    write_config(args.config, bound)
    _print({"state": "BOUND", "config": str(args.config.resolve()), "account_id": bound.account_id,
            "group_allowlist": bound.group_allowlist, "data_dir": str(bound.data_dir)})


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.config.exists():
            config = load_config(args.config)
        elif args.command in ("doctor", "bind"):
            config = Config(data_dir=args.config.resolve().parent, source_path=args.config.resolve())
        else:
            raise ValueError(f"配置不存在：{args.config.resolve()}；请复制 config.bot.example.toml 后绑定")
        if args.command == "doctor":
            from .adapters.helper_native import inspect_bound
            pid = args.pid or config.wechat_pid
            if not pid:
                raise ValueError("doctor 需要 --pid 指定微信进程；可用 Get-Process Weixin 查看候选")
            _print(inspect_bound(config.helper_root, pid))
        elif args.command == "bind":
            _bind(args, config)
        elif args.command == "relocate":
            from .relocation import relocate
            _print(relocate(args.config, config, args.data_dir, args.helper_root))
        elif args.command == "status":
            _print(read_status(config))
        elif args.command == "run":
            config.require_binding()
            from .platform_check import check_windows_desktop
            check_windows_desktop()
            from .runtime import Runtime
            _print({"config": str(args.config.resolve()), "data_dir": str(config.data_dir), "state": "STARTING"})
            runtime = Runtime(config)
            runtime.run()
            if runtime.state != "STOPPED":
                _print({"state": runtime.state, "error": runtime.error})
                return 1
        elif args.command in ("pause", "resume"):
            if not config.account_id:
                raise ValueError("配置中缺少机器人账号")
            from .store import BotStore
            store = BotStore(config.data_dir, config.account_id)
            with store.transaction() as connection:
                store.set_setting(connection, "paused", "1" if args.command == "pause" else "0")
            _print({"paused": args.command == "pause", "data_dir": str(config.data_dir)})
        elif args.command == "stop":
            config.data_dir.mkdir(parents=True, exist_ok=True)
            (config.data_dir / "stop.request").write_text(str(time.time()), encoding="ascii")
            _print({"state": "STOP_REQUESTED", "next": "使用 status 查看正常清理后的结果；未强制结束微信"})
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        _print({"state": getattr(error, "state", getattr(error, "code", "ERROR")), "error": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
