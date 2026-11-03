"""Rebind copied data to explicitly selected local paths, without starting WeChat."""
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import sqlite3

from .config import write_config
from .runtime import single_instance
from .stickers import StickerService


def relocate(config_path, config, data_dir, helper_root):
    data_dir, helper_root = Path(data_dir).resolve(), Path(helper_root).resolve()
    database = data_dir / 'bot.sqlite3'
    if not database.is_file():
        raise ValueError('目标数据目录缺少 bot.sqlite3；请先正常停止原机器人并复制完整数据目录')
    if not (helper_root / 'native/compatibility.json').is_file():
        raise ValueError('目标 helper 目录不完整；请先运行安装脚本')
    with single_instance(data_dir):
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
            connection.row_factory = sqlite3.Row
            account = connection.execute("SELECT value FROM settings WHERE key='account_id'").fetchone()
            if not account or account[0] != config.account_id:
                raise ValueError('配置账号与复制数据库绑定的账号不一致')
            if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('复制数据库完整性检查失败；请重新取得已停止机器人的完整副本')
            media = StickerService(data_dir).audit_paths(connection)
        # Local process IDs and launcher paths are not transferable. Keep their
        # old records for diagnosis, but never use them to identify a new process.
        names = ('status.json', 'launcher-start.json', 'stop.request')
        pending = [data_dir / name for name in names if (data_dir / name).exists()]
        archive = data_dir / 'backups' / ('relocate-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        if pending:
            archive.mkdir(parents=True)
            for path in pending:
                path.replace(archive / path.name)
        write_config(config_path, replace(config, data_dir=data_dir, helper_root=helper_root, wechat_pid=None))
    return {'state': 'REBIND_REQUIRED', 'data_dir': str(data_dir), 'helper_root': str(helper_root),
            'archived_state': str(archive) if pending else None, 'media': media,
            'next': '在目标 Windows 用户会话登录同一机器人账号，再用 doctor/bind 核对并绑定实际 PID；群、主人和历史保留'}
