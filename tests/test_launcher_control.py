"""Tray shutdown on isolated state; never starts or stops a real bot."""
from contextlib import contextmanager
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def launcher(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'launcher' / 'control.py'
    spec = importlib.util.spec_from_file_location('isolated_launcher_control', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = SimpleNamespace(data_dir=tmp_path)
    monkeypatch.setattr(module, 'load_config', lambda _: config)
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    return module, config


def test_shutdown_waits_for_confirmed_exit_under_start_lock(tmp_path, monkeypatch):
    module, config = launcher(tmp_path, monkeypatch)
    held = []

    @contextmanager
    def lock(actual):
        assert actual is config
        held.append(True)
        try:
            yield
        finally:
            held.pop()

    states = iter([True, True, False])
    observed = []

    def status(actual):
        assert actual is config and held
        alive = next(states)
        if observed:
            assert (tmp_path / 'stop.request').is_file()
        observed.append(alive)
        return {'state': 'READY' if alive else 'STOPPED', 'process_alive': alive}

    monkeypatch.setattr(module, 'start_lock', lock)
    monkeypatch.setattr(module, 'status', status)
    result = module.control('shutdown')
    assert result['state'] == 'STOPPED' and result['process_alive'] is False
    assert observed == [True, True, False] and not held


def test_shutdown_keeps_unknown_or_slow_process_for_manual_review(tmp_path, monkeypatch):
    module, _ = launcher(tmp_path, monkeypatch)

    @contextmanager
    def lock(_):
        yield

    monkeypatch.setattr(module, 'start_lock', lock)
    monkeypatch.setattr(module, 'status', lambda _: {'process_alive': None})
    with pytest.raises(ValueError, match='无法核验后台进程'):
        module.control('shutdown')
    assert not (tmp_path / 'stop.request').exists()
    clock = iter([10, 81])
    monkeypatch.setattr(module.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(module, 'status', lambda _: {'process_alive': True})
    with pytest.raises(ValueError, match='后台仍在正常停止'):
        module.control('shutdown')
    assert (tmp_path / 'stop.request').is_file()
