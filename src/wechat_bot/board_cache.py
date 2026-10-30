"""Rebuildable PNG cache; never removes original media or old reply PNGs."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
import time

from wordle.render import render_board

MAX_AGE = 7 * 24 * 3600
MAX_BYTES = 128 * 1024 * 1024


def board_key(board):
    encoded = json.dumps(board, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return sha256(('board-v1:' + encoded).encode('utf-8')).hexdigest()


def directory(data_dir):
    return Path(data_dir).resolve() / 'media' / 'wordle' / 'cache'


def render_cached(board, data_dir):
    folder = directory(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    if folder.resolve() != folder:
        raise OSError('Wordle cache directory was redirected')
    destination = folder / (board_key(board) + '.png')
    if destination.is_symlink():
        raise OSError('Wordle cache file was redirected')
    if not destination.exists():
        with tempfile.NamedTemporaryFile(prefix='.render-', suffix='.tmp', dir=folder, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            render_board(board, temporary)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    # Frequently queried boards remain hot; identical replies share one file.
    os.utime(destination, None)
    return destination


def prune(data_dir, protected, *, now=None, max_bytes=MAX_BYTES):
    """Caller holds delivery_lock across reference collection and pruning.

    Only the new cache's SHA-named PNGs are eligible. Pending, sending, uncertain
    and failed reply snapshots are protected, so their bytes may exceed the cap.
    Database history remains authoritative for reconstructing other PNGs.
    """
    folder = directory(data_dir)
    if not folder.exists():
        return 0
    if folder.resolve() != folder:
        raise OSError('Wordle cache directory was redirected')
    now = time.time() if now is None else now
    candidates = []
    for path in folder.iterdir():
        if re.fullmatch(r'[0-9a-f]{64}\.png', path.name) and path.is_file() and not path.is_symlink():
            stat = path.stat()
            candidates.append((stat.st_mtime, stat.st_size, path))
    total, removed = sum(size for _, size, _ in candidates), 0
    for modified, size, path in sorted(candidates):
        if path.stem in protected:
            continue
        if modified < now - MAX_AGE or total > max_bytes:
            # The exact path is inside this dedicated cache, never a recursive
            # operation; unknown names, originals and old reply-*.png are kept.
            path.unlink()
            total -= size
            removed += 1
    return removed
