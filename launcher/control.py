"""Stable EXE's local control bridge; bot code stays in the updatable project.

No WeChat calls happen here. The regular bot runtime owns identity checks,
the single-instance lock, native loading and graceful shutdown.
"""

from __future__ import annotations

from datetime import datetime
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wechat_bot import __version__
from wechat_bot.__main__ import _process_alive, read_status
from wechat_bot.config import load_config


def startup(config):
    target = config.data_dir / "launcher-start.json"
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def status(config):
    record = read_status(config)
    pending = startup(config)
    if pending and record.get("updated_at", 0) < pending["started_at"]:
        alive = _process_alive(pending["launcher_pid"])
        if alive is not False:
            return {"state": "STARTING" if alive else "STALE", "version": __version__,
                    "process_alive": alive, "launcher_pid": pending["launcher_pid"],
                    "reason": "后台启动进程尚未发布本次连接状态。", "data_dir": str(config.data_dir),
                    "stderr_log": pending["stderr_log"]}
        record = {"state": "STOPPED", "process_alive": False,
                  "reason": "本次启动进程已退出，未发布连接状态；请检查启动日志。",
                  "data_dir": str(config.data_dir)}
    # The launcher needs operational state, not account/group identifiers.
    result = {key: record[key] for key in (
        "state", "recorded_state", "process_alive", "pid", "error", "reason",
        "status_age_seconds", "counts", "data_dir",
    ) if key in record}
    result["version"] = __version__
    result["config_path"] = str(config.source_path)
    if pending:
        result["stderr_log"] = pending["stderr_log"]
    return result


@contextmanager
def start_lock(config):
    """Serialize GUI double-clicks until the launched PID is durably recorded."""
    import msvcrt

    config.data_dir.mkdir(parents=True, exist_ok=True)
    with (config.data_dir / "launcher.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        # LK_LOCK retries for up to 10 seconds. This critical section contains
        # file/process operations only, never DLL initialization or network I/O.
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def control(action):
    config_path = ROOT / "runtime" / "config.bot.toml"
    config = load_config(config_path)
    if action == "admin":
        from wechat_bot.admin import AdminService
        payload = sys.stdin.read(1_048_577)
        if len(payload) > 1_048_576:
            raise ValueError("管理请求超过大小限制")
        return AdminService(config).execute(json.loads(payload.lstrip('\ufeff')))
    if action == "status":
        return status(config)
    if action == "stop":
        config.data_dir.mkdir(parents=True, exist_ok=True)
        (config.data_dir / "stop.request").write_text(str(time.time()), encoding="ascii")
        return {"state": "STOP_REQUESTED", "version": __version__,
                "reason": "已请求正常停止；等待发送与原生桥接清理。"}
    if action not in ("start", "check"):
        raise ValueError("Unknown launcher action")
    config.require_binding()
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise ValueError("项目 .venv Python 不存在，请先按 README 安装。")
    missing = [name for name in ("PIL", "pefile", "cryptography")
               if importlib.util.find_spec(name) is None]
    if missing:
        raise ValueError("缺少运行依赖：" + ", ".join(missing))
    if not (config.helper_root / "native" / "compatibility.json").is_file():
        raise ValueError("未找到固定的 helper 源码，请运行 scripts/fetch_helper.ps1。")
    if action == "check":
        return {"state": "CHECKED", "version": __version__, "reason": "入口、Python、配置和依赖存在；未加载微信桥接。"}
    with start_lock(config):
        return start(config, python, config_path)


def start(config, python, config_path):
    record = status(config)
    if record.get("process_alive") is True:
        return dict(record, launcher_note="已有机器人或启动进程；未重复启动。")
    if record.get("process_alive", False) is None:
        raise ValueError("无法核验已记录的机器人进程，请先检查权限和运行状态。")
    log_dir = config.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    stdout_path = log_dir / f"launcher-{stamp}.stdout.log"
    stderr_path = log_dir / f"launcher-{stamp}.stderr.log"
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    # Source updates apply on the next launch, even if editable metadata is older.
    environment["PYTHONPATH"] = str(ROOT / "src") + (
        os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
    # Files are inherited directly by the bot. Closing this control process or
    # the EXE does not close a pipe that the running bot still needs to write.
    started_at = time.time()
    with stdout_path.open("ab", buffering=0) as stdout, stderr_path.open("ab", buffering=0) as stderr:
        process = subprocess.Popen(
            [str(python), "-u", "-m", "wechat_bot", "run", "--config", str(config_path)],
            cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    marker = {"launcher_pid": process.pid, "started_at": started_at,
              "stdout_log": str(stdout_path), "stderr_log": str(stderr_path)}
    target = config.data_dir / "launcher-start.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(marker), encoding="utf-8")
    temporary.replace(target)
    return {"state": "STARTING", "version": __version__, "launcher_pid": process.pid,
            "reason": "已启动后台进程，正在等待实际连接状态。", "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path)}


def main():
    try:
        if len(sys.argv) != 2:
            raise ValueError("Expected start, stop, status, check or admin")
        print(json.dumps(control(sys.argv[1]), ensure_ascii=False), flush=True)
        return 0
    except Exception as error:
        print(json.dumps({"ok": False, "state": "ERROR", "error": str(error), "version": __version__}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
