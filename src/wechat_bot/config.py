"""Validated local configuration; paths are relative to the TOML file."""

from dataclasses import dataclass, field
from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    account_id: str = ""
    owner_id: str = ""
    group_allowlist: tuple[str, ...] = ()
    data_dir: Path = field(default_factory=lambda: (PROJECT_ROOT / "runtime").resolve())
    helper_root: Path = field(default_factory=lambda: PROJECT_ROOT / "external" / "helper")
    wechat_pid: int | None = None
    require_native_mention: bool = True
    zxj: bool = True
    wordle: bool = True
    stickers: bool = False
    max_command_age_seconds: int = 120
    reply_expiry_seconds: int = 300
    max_send_attempts: int = 3
    per_user_cooldown_seconds: float = 1
    source_path: Path | None = None

    def require_binding(self):
        if not self.account_id or not self.group_allowlist:
            raise ValueError("运行前需要真实 account_id 和非空 group_allowlist；先执行 bind")
        if self.account_id == self.owner_id:
            raise ValueError("机器人 account_id 与主人 owner_id 必须不同")
        if self.wechat_pid is None:
            raise ValueError("首次连接需要明确绑定的 wechat_pid；请执行 bind --pid")


def _identity(value, name, *, allow_empty=False):
    if not isinstance(value, str) or (not value and not allow_empty):
        raise ValueError(f"{name} 必须是真实非空 ID")
    if value != value.strip() or len(value) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{name} 含无效字符或超过 128 字符")
    return value


def _boolean(section, key, default):
    result = section.get(key, default)
    if type(result) is not bool:
        raise ValueError(f"{key} 必须是布尔值")
    return result


def _number(section, key, default, maximum, *, zero=False, integral=True):
    value = section.get(key, default)
    types = (int,) if integral else (int, float)
    if type(value) not in types or not (0 if zero else 1) <= value <= maximum:
        raise ValueError(f"{key} 必须在 {0 if zero else 1}–{maximum} 范围内")
    return value


def load_config(path: str | Path) -> Config:
    source = Path(path).expanduser().resolve()
    with source.open("rb") as stream:
        data = tomllib.load(stream)
    bot, features, runtime = (data.get(name, {}) for name in ("bot", "features", "runtime"))
    if not all(isinstance(section, dict) for section in (bot, features, runtime)):
        raise ValueError("bot、features、runtime 必须是 TOML 表")
    if bot.get("backend", "helper_native") != "helper_native":
        raise ValueError("仅支持 helper_native 生产接入")
    groups = bot.get("group_allowlist", [])
    if not isinstance(groups, list):
        raise ValueError("group_allowlist 必须是原生群 ID 数组")
    groups = tuple(_identity(item, "group_allowlist") for item in groups)
    if len(groups) != len(set(groups)) or any(not group.endswith("@chatroom") for group in groups):
        raise ValueError("group_allowlist 需要互不重复且以 @chatroom 结尾的原生群 ID")
    pid = bot.get("wechat_pid")
    if pid is not None and (type(pid) is not int or pid < 1):
        raise ValueError("wechat_pid 必须是明确选择的正整数进程 ID")

    def local_path(value, name):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} 必须是本地路径")
        result = Path(value).expanduser()
        return (result if result.is_absolute() else source.parent / result).resolve()

    return Config(
        account_id=_identity(bot.get("account_id", ""), "account_id", allow_empty=True),
        owner_id=_identity(bot.get("owner_id", ""), "owner_id", allow_empty=True),
        group_allowlist=groups,
        data_dir=local_path(bot.get("data_dir", "."), "data_dir"),
        helper_root=local_path(bot.get("helper_root", str(PROJECT_ROOT / "external" / "helper")), "helper_root"),
        wechat_pid=pid,
        require_native_mention=_boolean(bot, "require_native_mention", True),
        zxj=_boolean(features, "zxj", True), wordle=_boolean(features, "wordle", True),
        stickers=_boolean(features, "stickers", False),
        max_command_age_seconds=_number(runtime, "max_command_age_seconds", 120, 3600),
        reply_expiry_seconds=_number(runtime, "reply_expiry_seconds", 300, 3600),
        max_send_attempts=_number(runtime, "max_send_attempts", 3, 3),
        per_user_cooldown_seconds=_number(runtime, "per_user_cooldown_seconds", 1, 60, zero=True, integral=False),
        source_path=source,
    )


def write_config(path: str | Path, config: Config):
    """Write known settings atomically; existing configuration is backed up first."""
    import json
    from datetime import datetime
    import shutil

    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[bot]", 'backend = "helper_native"']
    for key in ("account_id", "owner_id"):
        lines.append(f"{key} = {json.dumps(getattr(config, key), ensure_ascii=False)}")
    lines.append(f"group_allowlist = {json.dumps(list(config.group_allowlist), ensure_ascii=False)}")
    for key in ("data_dir", "helper_root"):
        lines.append(f"{key} = {json.dumps(str(getattr(config, key)), ensure_ascii=False)}")
    if config.wechat_pid is not None:
        lines.append(f"wechat_pid = {config.wechat_pid}")
    lines.append(f"require_native_mention = {str(config.require_native_mention).lower()}")
    lines.extend(["", "[features]"])
    lines.extend(f"{key} = {str(getattr(config, key)).lower()}" for key in ("zxj", "wordle", "stickers"))
    lines.extend(["", "[runtime]"])
    for key in ("max_command_age_seconds", "reply_expiry_seconds", "max_send_attempts", "per_user_cooldown_seconds"):
        lines.append(f"{key} = {getattr(config, key)}")
    if target.exists():
        backup_dir = target.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(target, backup_dir / f"{target.name}.{stamp}.bak")
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(target)
