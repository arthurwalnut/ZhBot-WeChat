"""Exact commands, native identity and group-scoped permissions."""
from datetime import UTC, datetime
import json
import re
import time

from zxj.service import draw, history_page
from wordle.game import WordleService, GameError
from .gateway import Event
from .store import BotStore
from .stickers import WAIT_SECONDS
from . import dictionaries

ADMIN = {"机器人状态", "暂停群功能", "恢复群功能"}
COMMAND = re.compile(r"(?:帮助|今日zxj|我的zxj(?: [1-9][0-9]{0,5})?|猜词(?: [0-9]{1,2})?|我猜是[^\r\n]{0,128}|猜词棋盘|猜词战绩|结束猜词|添加表情包|取消添加|随机表情包|我的表情包(?: [1-9][0-9]{0,5})?|删除表情包 [1-9][0-9]*)\Z")
GUESS = re.compile(r"我猜是[ \t\u3000]*([A-Za-z]+)\Z")


def command_text(event):
    # Only remove visible labels after native mention metadata has been checked.
    return re.sub(r"^(?:@[^@\r\n\u2005]+\u2005\s*)+", "", event.text).strip()


class Router:
    def __init__(self, config, store, stickers=None):
        self.config, self.store, self.stickers = config, store, stickers
        self.game = WordleService(store.path, initialize=False, dictionary_provider=dictionaries.words)

    def in_scope(self, event):
        cfg = self.config
        return (event.account_id == cfg.account_id and not event.is_self and
                bool(event.native_message_id and event.sender_id) and
                (event.chat_type != 'group' or event.sender_id != event.chat_id) and
                ((event.chat_type == "group" and event.chat_id in cfg.group_allowlist) or
                 (event.chat_type == "private" and event.sender_id == cfg.owner_id and event.chat_id == cfg.owner_id)))

    def accepts(self, event):
        if not self.in_scope(event):
            return False
        if event.message_type != "text":
            return False  # Explicit sticker upload intents are handled by runtime.
        if event.chat_type == "private":
            return event.text.strip() in ADMIN
        if self.config.require_native_mention and self.config.account_id not in event.mentioned_ids:
            return False
        # Unknown text explicitly addressed to this bot gets a short help reply.
        # When mention gating is disabled, ordinary unaddressed chat is still ignored.
        return bool(COMMAND.fullmatch(command_text(event))) or self.config.account_id in event.mentioned_ids

    def handle(self, c, event):
        cfg = self.config
        if not self.in_scope(event):
            return []
        text = command_text(event) if event.chat_type == "group" else event.text.strip()
        def reply(value):
            return [{"kind":"text", "text":value, "mentioned_ids":[event.sender_id] if event.chat_type == "group" else []}]
        if event.chat_type == "private":
            if text == "暂停群功能":
                BotStore.set_setting(c,"paused","1")
                return reply("群功能已暂停。")
            if text == "恢复群功能":
                BotStore.set_setting(c,"paused","0")
                return reply("群功能已恢复。")
            if text == "机器人状态":
                return reply("群功能：" + ("暂停" if BotStore.setting(c,"paused") == "1" else "启用"))
            return []
        if BotStore.setting(c,"paused") == "1":
            return []
        key = "cooldown:" + event.sender_id
        previous = float(BotStore.setting(c,key,"0"))
        if event.received_at - previous < cfg.per_user_cooldown_seconds:
            return []
        BotStore.set_setting(c,key,event.received_at)
        if not COMMAND.fullmatch(text):
            return reply("未识别指令。请发送「帮助」查看用法；例如「我猜是apple」。")
        try:
            if text == "帮助":
                commands = ["帮助"]
                if cfg.zxj:
                    commands += ["今日zxj", "我的zxj [页码]"]
                if cfg.wordle:
                    commands += ["猜词 [3~10]（默认 5）", "我猜是 apple（空格可省略）", "猜词棋盘", "猜词战绩", "结束猜词"]
                if cfg.stickers and self.stickers:
                    commands += ["添加表情包", "取消添加", "随机表情包", "我的表情包 [页码]", "删除表情包 编号"]
                return reply("请真实 @机器人 后输入：\n" + "\n".join(commands))
            if text == "今日zxj" and cfg.zxj:
                result = draw(event.sender_id, connection=c, now=datetime.fromtimestamp(event.received_at,UTC),
                              characters=dictionaries.characters(c))
                date = datetime.strptime(result['business_date'], '%Y-%m-%d').strftime('%y.%m.%d')
                return reply(f"今天（{date}）\n你的zxj是“{result['result']}”")
            if text.startswith("我的zxj") and cfg.zxj:
                page = int(text.split()[1]) if " " in text else 1
                result = history_page(event.sender_id, page=page, connection=c)
                lines = [f"{datetime.strptime(v['business_date'], '%Y-%m-%d'):%y.%m.%d}：{v['result']}" for v in result['items']]
                return reply("\n".join(lines + [f"第 {page}/{result['total_pages']} 页，共 {result['total']} 条。", f"下一页：我的zxj {page+1}"] ))
            board = None
            if text.split()[0] == "猜词" and cfg.wordle:
                length = int(text.split()[1]) if " " in text else 5
                if not 3 <= length <= 10:
                    return reply("单词长度需要在 3~10 之间，例如：猜词 7。")
                # An existing active game is shown without changing its answer.
                current = self.game.store.load(c,event.chat_id,active_only=True)
                board = self.game._board(current) if current else self.game.start(event.chat_id,event.sender_id,length,connection=c)
            elif text.startswith("我猜是") and cfg.wordle:
                match = GUESS.fullmatch(text)
                if not match:
                    return reply("格式：我猜是 apple（空格可省略）。猜测只接受英文字母，不消耗机会。")
                board = self.game.guess(event.chat_id,event.sender_id,match[1],connection=c)
            elif text == "猜词棋盘" and cfg.wordle:
                board = self.game.current(event.chat_id,connection=c)
            elif text == "猜词战绩" and cfg.wordle:
                stats = self.game.stats(event.sender_id,event.chat_id,connection=c)
                return reply(f"本群猜中：{stats['wins']} 次。")
            elif text == "结束猜词" and cfg.wordle:
                board = self.game.end(event.chat_id,event.sender_id,owner_id=cfg.owner_id,connection=c)
            if board:
                responses = [{"kind":"image", "board":board}]
                if board['status'] != 'active':
                    responses += reply(f"本局 {board['status']}；答案：{board['answer']}。")
                return responses
            if "表情包" in text or text == "取消添加":
                if not cfg.stickers or not self.stickers:
                    return reply("原生表情收集与重发尚未启用。")
                return self.sticker_command(c,event,text,reply)
        except (GameError, ValueError) as error:
            return reply(str(error))
        return reply("该功能尚未启用。")

    def sticker_command(self, c, event, text, reply):
        key = dict(account_id=event.account_id,chat_id=event.chat_id,sender_id=event.sender_id)
        if text == '添加表情包':
            self.stickers.begin_wait(c,**key,received_at=event.received_at)
            return reply(f'请在 {WAIT_SECONDS} 秒内发送一条原生表情。')
        if text == '取消添加':
            self.stickers.cancel_wait(c,**key)
            return reply('已取消等待。')
        if text == '随机表情包':
            item = self.stickers.random(c,account_id=event.account_id,chat_id=event.chat_id)
            return [{"kind":"sticker","path":item['path'],"sticker_id":item['id']}] if item else reply('本群表情库为空。')
        if text.startswith('我的表情包'):
            page = int(text.split()[1]) if ' ' in text else 1
            result = self.stickers.list(c,**key,page=page)
            return reply('编号：'+', '.join(str(v['id']) for v in result['items'])+f"；第 {page}/{result['pages']} 页，共 {result['total']} 条。")
        if text.startswith('删除表情包 '):
            self.stickers.delete_with_pending(c,**key,sticker_id=int(text.split()[1]),owner_id=self.config.owner_id)
            return reply('已删除该条目并取消尚未开始发送的待发项。')
        return []

    def process_one(self, *, now=None, prepared=None, media_error=None):
        now = time.time() if now is None else now
        with self.store.transaction() as c:
            row = c.execute("SELECT * FROM inbox WHERE state='pending' ORDER BY id LIMIT 1").fetchone()
            if row is None:
                return False
            data = json.loads(row['payload'])
            event = Event(**{k:v for k,v in data.items() if k in Event.__dataclass_fields__})
            if not data.get('sticker_intent') and now - event.received_at > self.config.max_command_age_seconds:
                data['media_ref'] = None
                c.execute("UPDATE inbox SET state='expired',payload=? WHERE id=?",(json.dumps(data,ensure_ascii=False),row['id']))
                return True
            if data.get('sticker_intent'):
                if not self.in_scope(event) or BotStore.setting(c,'paused') == '1' or not self.config.stickers:
                    replies = []
                elif prepared:
                    try:
                        item = self.stickers.add(c,data['sticker_intent'],prepared)
                        text = f"表情编号{item['id']}：" + ('已有同一资源' if item['is_duplicate'] else '添加成功')
                    except (ValueError, OSError) as error:
                        text = '表情保存校验失败：' + type(error).__name__
                    replies = [{'kind':'text','text':text,'mentioned_ids':[event.sender_id]}]
                else:
                    replies = [{'kind':'text','text':media_error or '资源未就绪，请重新添加。','mentioned_ids':[event.sender_id]}]
            elif data.get('wrong_sticker_type'):
                replies = [{'kind':'text','text':'请发送原生表情；图片或文字不能加入表情库。','mentioned_ids':[event.sender_id]}]
            else:
                replies = self.handle(c,event)
            self.store.replies(c,row,replies)
            data['media_ref'] = None
            c.execute("UPDATE inbox SET state='done',result=?,payload=? WHERE id=?",(json.dumps({"replies":len(replies)}),json.dumps(data,ensure_ascii=False),row['id']))
        return True
