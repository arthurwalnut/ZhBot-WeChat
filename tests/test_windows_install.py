"""Moved environments and project-relative scripts on isolated Windows folders."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from wechat_bot.platform_check import validate_desktop


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows installation flow')


def test_copied_environment_is_detected_and_backup_survives_install_failure(tmp_path):
    original = tmp_path / '原项目 original'
    moved = tmp_path / '目标项目 moved'
    original.mkdir()
    base = str(Path(sys.base_prefix) / 'python.exe')
    subprocess.run([base, '-m', 'venv', '--without-pip', str(original / '.venv')], check=True)
    source = original / 'src/wechat_bot'
    source.mkdir(parents=True)
    (source / '__init__.py').write_text('')
    pth = original / '.venv/Lib/site-packages/zhbot-test-source.pth'
    pth.write_text(str(original / 'src') + '\n', encoding='utf-8')
    (original / '.venv/zhbot-install-root.txt').write_text(str(original), encoding='utf-8')
    (original / 'runtime').mkdir()
    (original / 'runtime/keep.txt').write_text('user data', encoding='utf-8')
    for relative in ['launcher/environment.py', 'scripts/install.ps1', 'scripts/windows_environment.ps1']:
        destination = original / relative
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    # Failure after environment creation must keep the backup and user data.
    (original / 'pyproject.toml').write_text('[build-system]\nrequires=[]\nbuild-backend="missing_test_backend"\n')
    (original / 'requirements-lock.txt').write_text('')
    shutil.copytree(original, moved)
    def probe(folder):
        return subprocess.run([str(folder / '.venv/Scripts/python.exe'), '-I',
                               str(folder / 'launcher/environment.py'), str(folder)],
                              capture_output=True, text=True, cwd=tmp_path)
    assert json.loads(probe(original).stdout)['ok']
    stale = probe(moved)
    assert stale.returncode == 1 and not json.loads(stale.stdout)['ok']
    environment = dict(os.environ, PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
    command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
               str(moved / 'scripts/install.ps1'), '-PythonPath', base]
    # Refuse to move an environment still used by a live interpreter. This is
    # an isolated stdin-waiting process, never a real bot or WeChat process.
    active = subprocess.Popen([str(moved / '.venv/Scripts/python.exe'), '-I', '-c',
                               'import sys; sys.stdin.read()'], stdin=subprocess.PIPE,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        blocked = subprocess.run(command, env=environment, cwd=tmp_path, capture_output=True, timeout=30)
        assert blocked.returncode != 0
        assert b'environment is in use' in blocked.stderr
        assert not list(moved.glob('.venv.backup-*'))
    finally:
        active.stdin.close()
        active.wait(timeout=10)
    install = subprocess.run(command,
                             env=environment, cwd=tmp_path, capture_output=True, timeout=90)
    assert install.returncode != 0
    backups = list(moved.glob('.venv.backup-*'))
    assert len(backups) == 1, install.stdout + install.stderr
    assert (backups[0] / 'Lib/site-packages/zhbot-test-source.pth').read_text(encoding='utf-8') == pth.read_text(encoding='utf-8')
    assert (moved / 'runtime/keep.txt').read_text() == 'user data'
    assert json.loads(probe(original).stdout)['ok']
    new_prefix = subprocess.check_output([str(moved / '.venv/Scripts/python.exe'), '-I', '-c',
                                         'import sys; print(sys.prefix)'], text=True).strip()
    assert Path(new_prefix).resolve() == (moved / '.venv').resolve()


def test_config_resolution_and_server_desktop_requirements(tmp_path):
    project = tmp_path / '中文 项目'
    (project / 'runtime').mkdir(parents=True)
    config = project / 'runtime/config.bot.toml'
    config.write_text('')
    # Resolve a relative -ConfigPath against the project, not the caller's cwd.
    script = tmp_path / 'resolve.ps1'
    def quoted(path):
        return "'" + str(path).replace("'", "''") + "'"
    script.write_text('. ' + quoted(ROOT / 'scripts/windows_environment.ps1') + '\n' +
                      '[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n' +
                      'Resolve-ProjectConfig -ProjectRoot ' + quoted(project) +
                      " -ConfigPath 'runtime/config.bot.toml'\n", encoding='utf-8-sig')
    result = subprocess.check_output(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
                                     cwd=tmp_path, encoding='utf-8').strip()
    assert Path(result) == config
    # These branch checks are not actual Windows Server acceptance.
    for build, framework in [(20348, 528449), (26100, 533325)]:
        details = dict(major=10, build=build, installation='Server', framework_release=framework, session_id=2)
        validate_desktop(details)
        with pytest.raises(ValueError, match='Desktop Experience'):
            validate_desktop(dict(details, installation='Server Core'))
        with pytest.raises(ValueError, match='Session 0'):
            validate_desktop(dict(details, session_id=0))
