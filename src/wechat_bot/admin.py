"""Local owner administration. No network listener and no message submission."""
from datetime import datetime
import hashlib
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from . import dictionaries
from .store import BotStore
from .stickers import MAX_SOURCE_BYTES, StickerService
from .sticker_media import convert_sticker


def _date(value):
    if isinstance(value, (int, float)):
        instant = datetime.fromtimestamp(value, ZoneInfo('Asia/Shanghai'))
    else:
        instant = datetime.fromisoformat(value).astimezone(ZoneInfo('Asia/Shanghai'))
    return instant.strftime('%Y-%m-%d %H:%M:%S')


class AdminService:
    def __init__(self, config):
        config.require_binding()
        self.config = config
        self.store = BotStore(config.data_dir, config.account_id)
        self.stickers = StickerService(config.data_dir)
        with self.store.transaction() as connection:
            self.stickers.initialize(connection)

    def _group(self, value, *, required=False):
        if not value and not required:
            return None
        if value not in self.config.group_allowlist:
            raise ValueError('请选择当前白名单中的群')
        return value

    @staticmethod
    def _user(value):
        if not isinstance(value, str) or len(value) > 128 or any(ord(ch) < 32 for ch in value):
            raise ValueError('成员 ID 无效')
        return value

    def _members(self, connection):
        # Read only observed identity metadata, never message bodies or media URLs.
        members = {}
        for row in connection.execute("""SELECT chat_id,
                json_extract(payload,'$.sender_id') AS member_id,
                json_extract(payload,'$.sender_display_name') AS name
                FROM inbox WHERE account_id=? ORDER BY received_at,id""", (self.config.account_id,)):
            if row['chat_id'] not in self.config.group_allowlist or not row['member_id']:
                continue
            item = members.setdefault(row['member_id'], {'id': row['member_id'], 'name': row['member_id'], 'groups': []})
            if row['name']:
                item['name'] = row['name']
            if row['chat_id'] not in item['groups']:
                item['groups'].append(row['chat_id'])
        for row in connection.execute('SELECT sender_id,chat_id FROM stickers WHERE account_id=?', (self.config.account_id,)):
            if row['chat_id'] in self.config.group_allowlist:
                item = members.setdefault(row['sender_id'], {'id': row['sender_id'], 'name': row['sender_id'], 'groups': []})
                if row['chat_id'] not in item['groups']:
                    item['groups'].append(row['chat_id'])
        for row in connection.execute('SELECT DISTINCT user_id FROM draws'):
            members.setdefault(row['user_id'], {'id': row['user_id'], 'name': row['user_id'], 'groups': []})
        for row in connection.execute("SELECT DISTINCT winner_id,group_id FROM games WHERE status='won'"):
            if row['group_id'] in self.config.group_allowlist:
                item = members.setdefault(row['winner_id'], {'id': row['winner_id'], 'name': row['winner_id'], 'groups': []})
                if row['group_id'] not in item['groups']:
                    item['groups'].append(row['group_id'])
        return members

    @staticmethod
    def _page(request, items, size=30):
        page = request.get('page', 1)
        if type(page) is not int or not 1 <= page <= 1_000_000:
            raise ValueError('页码需要为正整数')
        total = len(items)
        pages = max(1, math.ceil(total / size))
        page = min(page, pages)
        return {'items': items[(page - 1) * size:page * size], 'page': page, 'pages': pages, 'total': total}

    def _preview(self, path):
        target = Path(path).resolve()
        return str(target) if target.is_relative_to(self.stickers.directory) and target.is_file() else ''

    def execute(self, request):
        if not isinstance(request, dict):
            raise ValueError('管理请求需要为 JSON 对象')
        action = request.get('action')
        if action == 'sticker_add':
            return {'ok': True, **self._import_sticker(request)}
        with self.store.transaction() as connection:
            result = self._execute(connection, action, request)
        return {'ok': True, **result}

    def _execute(self, connection, action, request):
        if action == 'zxj_dictionary':
            return {'characters': dictionaries.characters(connection)}
        if action == 'zxj_save':
            groups = request.get('characters')
            if isinstance(groups, dict):
                groups = {key: list(''.join(value.split())) if isinstance(value, str) else value for key, value in groups.items()}
            dictionaries.save_characters(connection, groups)
            return {'saved': True}
        if action == 'wordle_edit':
            dictionaries.change_words(connection, add=request.get('add', []), remove=request.get('remove', []))
            return {'saved': True}
        if action == 'wordle_dictionary':
            length, search = request.get('length', 0), request.get('search', '')
            if type(length) is not int or length not in (0, *range(3, 11)):
                raise ValueError('单词长度需要为 3～10 或全部')
            if not isinstance(search, str) or len(search) > 100:
                raise ValueError('搜索内容无效')
            answers, allowed = dictionaries.words(connection)
            answer_set = set(answers)
            items = [{'word': word, 'length': len(word), 'kind': '答案词' if word in answer_set else '仅可猜'}
                     for word in sorted(allowed) if (not length or len(word) == length) and search.lower().strip() in word]
            return self._page(request, items, 100)
        if action == 'sticker_delete':
            group = self._group(request.get('group_id'), required=True)
            actor = self.config.owner_id or self.config.account_id
            self.stickers.delete_with_pending(connection, account_id=self.config.account_id, chat_id=group,
                sender_id=actor, sticker_id=request.get('id'), owner_id=actor)
            return {'deleted': True}
        members = self._members(connection)
        if action == 'overview':
            groups = set(self.config.group_allowlist)
            wins = sum(row[0] for row in connection.execute("SELECT COUNT(*),group_id FROM games WHERE status='won' GROUP BY group_id") if row[1] in groups)
            stickers = sum(row[0] for row in connection.execute('SELECT COUNT(*),chat_id FROM stickers WHERE deleted=0 GROUP BY chat_id') if row[1] in groups)
            return {'account_id': self.config.account_id, 'owner_id': self.config.owner_id,
                    'groups': [{'id': group, 'name': group} for group in self.config.group_allowlist],
                    'members': sorted(members.values(), key=lambda item: (item['name'], item['id'])),
                    'counts': {'draws': connection.execute('SELECT COUNT(*) FROM draws').fetchone()[0], 'wins': wins, 'stickers': stickers},
                    'paused': BotStore.setting(connection, 'paused') == '1'}
        group = self._group(request.get('group_id', ''))
        user = self._user(request.get('user_id', ''))
        name = lambda member: members.get(member, {}).get('name', member)
        if action == 'zxj_history':
            items = [{'date': row['business_date'].replace('-', '.'), 'member': name(row['user_id']),
                      'member_id': row['user_id'], 'result': row['result']}
                     for row in connection.execute('SELECT user_id,business_date,result FROM draws ORDER BY business_date DESC,user_id')
                     if (not user or row['user_id'] == user)
                     and (not group or group in members.get(row['user_id'], {}).get('groups', []))]
            return self._page(request, items)
        if action == 'wordle_wins':
            # Unfinished answers are never selected or returned to this screen.
            items = [{'game_id': row['id'], 'group_id': row['group_id'], 'member': name(row['winner_id']),
                      'member_id': row['winner_id'], 'word': row['answer'], 'length': row['length'],
                      'guesses': row['turns'], 'date': _date(row['ended_at_utc'])}
                     for row in connection.execute("""SELECT g.id,g.group_id,g.winner_id,g.answer,g.length,g.ended_at_utc,
                        (SELECT COUNT(*) FROM guesses WHERE game_id=g.id) AS turns
                        FROM games g WHERE g.status='won' ORDER BY g.id DESC""")
                     if row['group_id'] in self.config.group_allowlist and (not group or row['group_id'] == group)
                     and (not user or row['winner_id'] == user)]
            return self._page(request, items)
        if action == 'stickers':
            items = [{'id': row['id'], 'group_id': row['chat_id'], 'member': name(row['sender_id']),
                      'member_id': row['sender_id'], 'date': _date(row['created_at']),
                      'source_format': row['source_format'], 'width': row['width'], 'height': row['height'],
                      'frames': row['frames'], 'bytes': row['bytes'],
                      'origin': '本机导入' if row['origin'] == 'local' else '微信上传',
                      'preview_path': self._preview(row['path']),
                      'original_path': self._preview(row['source_path']) if row['source_path'] else ''}
                     for row in connection.execute('SELECT * FROM stickers WHERE account_id=? AND deleted=0 ORDER BY id DESC', (self.config.account_id,))
                     if row['chat_id'] in self.config.group_allowlist and (not group or row['chat_id'] == group)
                     and (not user or row['sender_id'] == user)]
            return self._page(request, items)
        raise ValueError('未知管理操作')

    def _import_sticker(self, request):
        group = self._group(request.get('group_id'), required=True)
        value = request.get('path')
        if not isinstance(value, str) or not value or len(value) > 32767:
            raise ValueError('请选择本机图片或 GIF 文件')
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_SOURCE_BYTES:
            raise ValueError('文件必须非空且不超过 20 MiB')
        with path.open('rb') as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            raise ValueError('文件超过 20 MiB')
        result = convert_sticker(data)
        legacy = None
        if result['source_format'] == 'PNG':
            with self.store.transaction() as connection:
                has_legacy = connection.execute("SELECT 1 FROM stickers WHERE source_format='PNG' AND source_digest IS NULL AND deleted=0 LIMIT 1").fetchone()
            if has_legacy:
                try:
                    # Pure resource encoding only; no native loading or plugin startup.
                    from .adapters.helper_native import _load, _sticker_helpers
                    root, _, _ = _load(self.config.helper_root)
                    legacy = hashlib.sha256(_sticker_helpers(root).gif_bytes(data, lambda: True)).hexdigest()
                except (ValueError, RuntimeError, OSError):
                    pass
        prepared = self.stickers.prepare(result['data'], source_format=result['source_format'],
            source_data=data, note=result['note'], legacy_digest=legacy)
        actor = self.config.owner_id or self.config.account_id
        with self.store.transaction() as connection:
            item = self.stickers.add_local(connection, account_id=self.config.account_id,
                chat_id=group, sender_id=actor, prepared=prepared)
        return {'id': item['id'], 'duplicate': item['is_duplicate']}
