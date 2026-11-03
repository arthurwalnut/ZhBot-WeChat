"""Detect moved/copy-only virtual environments without importing old bot code.

Invoke with ``python -I launcher/environment.py <project-root>`` so PYTHONPATH
and the caller's working directory cannot mask stale editable-install paths.
"""
import importlib.util
import json
from pathlib import Path
import struct
import sys


def inspect_environment(root):
    root = Path(root).resolve()
    problems = []
    if sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8:
        problems.append('Python 3.12 x64 required')
    if Path(sys.prefix).resolve() != root / '.venv':
        problems.append('Virtual environment belongs to a different location')
    spec = importlib.util.find_spec('wechat_bot')
    if spec is None or not spec.origin or Path(spec.origin).resolve() != root / 'src/wechat_bot/__init__.py':
        problems.append('Editable package source does not match this project')
    marker = root / '.venv/zhbot-install-root.txt'
    if marker.exists() and Path(marker.read_text(encoding='utf-8').strip()).resolve() != root:
        problems.append('Virtual environment was copied from another project location')
    return {'ok': not problems, 'problems': problems, 'python': sys.executable,
            'base_python': str(Path(sys.base_prefix) / 'python.exe')}


if __name__ == '__main__':
    result = inspect_environment(sys.argv[1])
    print(json.dumps(result))
    raise SystemExit(0 if result['ok'] else 1)
