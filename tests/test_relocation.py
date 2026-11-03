"""Copy configuration/data to another local root without touching live WeChat."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from wechat_bot.config import Config, load_config, write_config
from wechat_bot.relocation import relocate
from wechat_bot.runtime import single_instance
from wechat_bot.stickers import StickerService


def test_config_paths_follow_copied_project_and_not_working_directory(tmp_path, monkeypatch):
    original = tmp_path / 'original project'
    config_path = original / 'runtime/config.bot.toml'
    cfg = Config(data_dir=config_path.parent, helper_root=original / 'external/helper',
                 account_id='robot', owner_id='owner', group_allowlist=('one@chatroom',), wechat_pid=123)
    write_config(config_path, cfg)
    text = config_path.read_text(encoding='utf-8')
    assert 'data_dir = "."' in text and 'helper_root = "../external/helper"' in text
    copied = tmp_path / '新机器 copy'
    shutil.copytree(original, copied)
    monkeypatch.chdir(tmp_path)
    loaded = load_config(copied / 'runtime/config.bot.toml')
    assert loaded.data_dir == copied / 'runtime'
    assert loaded.helper_root == copied / 'external/helper'
    assert loaded.account_id == cfg.account_id and loaded.group_allowlist == cfg.group_allowlist


def test_relocate_archives_foreign_process_state_and_keeps_database(tmp_path):
    data = tmp_path / 'new root/运行数据'
    data.mkdir(parents=True)
    helper = tmp_path / 'new root/helper'
    (helper / 'native').mkdir(parents=True)
    (helper / 'native/compatibility.json').write_text('{}')
    old = Config(account_id='robot', owner_id='owner', group_allowlist=('one@chatroom',),
                 wechat_pid=123, data_dir=tmp_path / 'old/runtime', helper_root=tmp_path / 'old/helper')
    config_path = data / 'config.bot.toml'
    write_config(config_path, old)
    with sqlite3.connect(data / 'bot.sqlite3') as c:
        c.execute('CREATE TABLE settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        c.execute("INSERT INTO settings VALUES ('account_id','robot')")
        StickerService(data).initialize(c)
    before = (data / 'bot.sqlite3').read_bytes()
    for name in ('status.json', 'launcher-start.json', 'stop.request'):
        (data / name).write_text(json.dumps({'pid':123,'state':'READY'}))
    with single_instance(data):
        with pytest.raises(RuntimeError):
            relocate(config_path, old, data, helper)
    assert (data / 'status.json').exists()
    result = relocate(config_path, old, data, helper)
    assert result['state'] == 'REBIND_REQUIRED'
    assert (data / 'bot.sqlite3').read_bytes() == before
    loaded = load_config(config_path)
    assert loaded.wechat_pid is None and loaded.data_dir == data and loaded.helper_root == helper
    assert loaded.account_id == 'robot' and loaded.group_allowlist == old.group_allowlist
    for name in ('status.json', 'launcher-start.json', 'stop.request'):
        assert not (data / name).exists()
        assert (Path(result['archived_state']) / name).is_file()
    previous = config_path.read_bytes()
    with pytest.raises(ValueError, match='账号'):
        relocate(config_path, replace(old, account_id='another'), data, helper)
    assert config_path.read_bytes() == previous
