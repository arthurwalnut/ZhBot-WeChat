"""Bound receive loop, durable outbox and conservative recovery."""
from contextlib import contextmanager
from dataclasses import asdict, replace
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import threading
import time

from wordle.render import render_board
from .gateway import Event, GatewayError, Outgoing
from .router import Router
from .store import BotStore
from .stickers import StickerError, StickerService
from .sticker_media import MEDIA_PUBLIC_REASONS

log = logging.getLogger("wechat_bot")

# Only fixed, reviewed messages may enter a group reply. Other errors can carry
# local paths, CDN URLs, XML or credentials, even when wrapped by a known class.
_PUBLIC_MEDIA_REASONS = frozenset({
    "表情事件账号或原生类型不符", "表情缺少可获取原件",
    "表情元数据缺少受支持的原件地址、MD5或格式",
    "WXGF 尚未启用转换；不改变原动画播放时长",
    "原生 GIF 超过上游 1 MiB/1024 像素发送限制",
    "该原生表情原件格式尚未支持",
    "表情 GIF 必须非空且不超过 1 MiB", "原生表情资源必须是完整 GIF",
    "表情超出 1024 像素、300 帧或累计像素限制", "表情 GIF 无法完整解码",
    "表情原件格式尚未支持", "表情转换说明无效",
    "表情保存目录发生重定向", "同摘要的现有表情文件内容不一致",
    "表情包连接已结束", "表情包下载地址无效", "表情包下载地址不受支持",
    "表情包响应超过大小限制", "表情包下载已取消或超时",
    "表情包下载失败或超过支持范围", "表情包内容校验失败或连接已结束",
    "表情原件缺失、格式不符或超过 20 MiB", "已保存表情原件的路径或摘要不一致",
}) | MEDIA_PUBLIC_REASONS


@contextmanager
def single_instance(directory):
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / "bot.lock").open("a+b")
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("此 data_dir 已有机器人实例") from None
    try:
        yield
    finally:
        handle.close()


class Runtime:
    def __init__(self, config, gateway=None):
        self.config = config
        self.store = BotStore(config.data_dir,config.account_id)
        self.stickers = StickerService(config.data_dir)
        with self.store.transaction() as c:
            self.stickers.initialize(c)
        self.router = Router(config,self.store,self.stickers)
        if gateway is None:
            from .adapters.helper_native import HelperNative
            gateway = HelperNative(config.helper_root,config.data_dir,config.account_id,
                                   config.wechat_pid,config.group_allowlist,owner_id=config.owner_id)
        self.gateway = gateway
        self.shutdown = threading.Event()
        self.delivery_lock = threading.RLock()
        self.state = "STOPPED"
        self.error = ""
        self.receive_error = False
        self.last_receive = None

    def receive(self, event):
        try:
            if not self.router.in_scope(event):
                return
            with self.store.transaction() as c:
                if c.execute("SELECT 1 FROM inbox WHERE account_id=? AND chat_id=? AND native_message_id=?",
                             (event.account_id,event.chat_id,event.native_message_id)).fetchone():
                    return
                payload = asdict(event)
                identity = dict(account_id=event.account_id,chat_id=event.chat_id,sender_id=event.sender_id,received_at=event.received_at)
                if self.config.stickers and event.chat_type == 'group' and self.stickers.waiting(c,**identity) and not self.router.accepts(event):
                    if event.message_type == 'sticker':
                        payload['sticker_intent'] = self.stickers.claim(c,**identity,native_message_id=event.native_message_id,message_type='sticker')
                    else:
                        payload['wrong_sticker_type'] = True
                        payload['media_ref'] = None
                        payload['text'] = ''
                elif not self.router.accepts(event):
                    return
                c.execute("""INSERT INTO inbox (namespace,account_id,chat_id,native_message_id,received_at,payload)
                    VALUES ('helper.native_text',?,?,?,?,?)""",(event.account_id,event.chat_id,event.native_message_id,event.received_at,json.dumps(payload,ensure_ascii=False)))
            self.last_receive = time.time()
        except Exception:
            self.receive_error = True
            self.state = "DEGRADED"
            self.error = "接收持久化失败，存在消息缺口；停止业务，请检查磁盘/数据库后重启"
            log.error(self.error)  # No message content, XML or credentials.

    def process_one(self):
        with self.store.transaction() as c:
            row = c.execute("SELECT * FROM inbox WHERE state='pending' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return False
        data = json.loads(row['payload'])
        prepared = None
        media_error = None
        resource = None
        if data.get('sticker_intent'):
            try:
                event = Event(**{k:v for k,v in data.items() if k in Event.__dataclass_fields__})
                if not self.router.in_scope(event) or not self.config.stickers:
                    raise ValueError('上传账号/群已不在当前授权范围')
                event = replace(event,connection_id=self.gateway.connection_id)
                resource = self.gateway.fetch_sticker(event)
                log.info("sticker_resource inbox=%s source=%s", row['id'],
                         json.dumps(resource.get('diagnostic', {}), ensure_ascii=False))
                prepared = self.stickers.prepare(resource['data'],source_format=resource['source_format'],
                    note=resource.get('note',''),source_data=resource.get('source_data'),
                    legacy_digest=resource.get('legacy_digest'))
            except Exception as error:
                diagnostic = getattr(error, 'media_diagnostic', (resource or {}).get('diagnostic', {}))
                source = getattr(error, 'source_data', (resource or {}).get('source_data'))
                if source is not None:
                    try:
                        archived = self.stickers.archive_failed_source(source)
                        diagnostic = {**diagnostic, 'archived': archived.name}
                    except (OSError, ValueError):
                        diagnostic = {**diagnostic, 'archive_failed': True}
                log.info("sticker_resource_failed inbox=%s type=%s source=%s", row['id'],
                         type(error).__name__, json.dumps(diagnostic, ensure_ascii=False))
                reason = str(error) if isinstance(error,(GatewayError,StickerError)) else ''
                media_error = "表情资源取得或持久保存失败：" + (
                    reason if reason in _PUBLIC_MEDIA_REASONS else type(error).__name__)
        with self.delivery_lock:
            return self.router.process_one(Event,prepared=prepared,media_error=media_error)

    def send_one(self, *, now=None):
        # Deletion and native submission share this lock. Receive persists separately.
        with self.delivery_lock:
            return self._send_one(now=now)

    def _send_one(self, *, now=None):
        now = time.time() if now is None else now
        with self.store.transaction() as c:
            row = c.execute("""SELECT o.* FROM outbox o WHERE o.state='pending' AND o.next_attempt<=?
                AND NOT EXISTS (SELECT 1 FROM outbox older WHERE older.inbox_id=o.inbox_id
                    AND older.ordinal<o.ordinal AND older.state IN ('pending','sending')) ORDER BY o.id LIMIT 1""",(now,)).fetchone()
            if row is None:
                return False
            cfg = self.config
            valid_target = (row['account_id'] == cfg.account_id and
                ((row['chat_type']=='group' and row['chat_id'] in cfg.group_allowlist) or
                 (row['chat_type']=='private' and row['chat_id']==cfg.owner_id)))
            if not valid_target or now-row['created_at'] > cfg.reply_expiry_seconds:
                c.execute("UPDATE outbox SET state='expired',detail='expiry or binding changed' WHERE id=?",(row['id'],))
                return True
            payload = json.loads(row['payload'])
            c.execute("UPDATE outbox SET state='sending',attempts=attempts+1 WHERE id=?",(row['id'],))
        # Rendering/native calls do not hold the business write transaction.
        try:
            path = payload.get('path')
            if payload.get('board'):
                path = str(render_board(payload['board'],self.config.data_dir / 'media/wordle' / f"reply-{row['id']}.png"))
        except Exception as error:
            from .gateway import SendResult
            result = SendResult('failed',type(error).__name__,True)
        else:
            outgoing = Outgoing(account_id=row['account_id'],chat_id=row['chat_id'],chat_type=row['chat_type'],
                kind=payload['kind'],text=payload.get('text',''),mentioned_ids=tuple(payload.get('mentioned_ids',())),
                path=path,connection_id=self.gateway.connection_id)
            try:
                result = self.gateway.send(outgoing)
            except Exception as error:
                from .gateway import SendResult
                result = SendResult('uncertain',type(error).__name__,False)
        state = result.status
        if state == 'failed' and result.retryable and row['attempts']+1 < self.config.max_send_attempts:
            state = 'pending'
        with self.store.transaction() as c:
            c.execute("UPDATE outbox SET state=?,detail=?,next_attempt=? WHERE id=?",
                      (state,result.detail,now+2**(row['attempts']+1),row['id']))
        log.info("outbox=%s state=%s",row['id'],state)
        return True

    def write_status(self):
        record = dict(state=self.state,pid=os.getpid(),updated_at=time.time(),error=self.error,
                      last_receive=self.last_receive,counts=self.store.counts(),connection=self.gateway.health())
        target = self.config.data_dir / 'status.json'
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(target)

    def _sender(self):
        while not self.shutdown.wait(0.2):
            if self.state == 'READY':
                try:
                    self.send_one()
                except Exception:
                    self.receive_error = True
                    self.error = "发送队列持久化失败，请重启核查 uncertain 项"

    def run(self):
        cfg = self.config
        with single_instance(cfg.data_dir):
            logs = cfg.data_dir / 'logs'
            logs.mkdir(exist_ok=True)
            handler = RotatingFileHandler(logs/'bot.log',maxBytes=1_000_000,backupCount=3,encoding='utf-8')
            log.addHandler(handler)
            log.setLevel(logging.INFO)
            self.store.recover()
            stop_file = cfg.data_dir / 'stop.request'
            stop_file.unlink(missing_ok=True)
            sender = threading.Thread(target=self._sender,name='bot-outbox',daemon=True)
            sender.start()
            attempts = 0
            ready_since = None
            try:
                while not self.shutdown.is_set() and not stop_file.exists():
                    if self.state != 'READY' and not self.receive_error:
                        try:
                            self.gateway.start(self.receive)
                            self.state,self.error = 'READY',''
                            ready_since = time.monotonic()
                        except Exception as error:
                            ready_since = None
                            self.state = getattr(error,'state','RECONNECTING')
                            self.error = str(error)
                            attempts += 1
                            self.write_status()
                            if self.state not in ('LOGIN_REQUIRED','RECONNECTING') or attempts >= 5:
                                if self.state not in ('VERSION_UNSUPPORTED','LOGIN_REQUIRED'):
                                    self.state = 'DEGRADED'
                                break
                            self.shutdown.wait(min(2**attempts,15))
                            continue
                    health = self.gateway.health()
                    if not health.get('connected',False) and not self.receive_error:
                        ready_since = None
                        if health.get('error') and not health.get('recoverable',False):
                            self.receive_error = True
                            self.state,self.error = 'DEGRADED','原生接收中断，可能存在缺口；请检查后重启'
                            self.gateway.stop()
                            continue
                        self.state = 'RECONNECTING'
                        attempts += 1
                        self.gateway.stop()
                        if attempts >= 5:
                            self.state,self.error = 'DEGRADED','连接连续中断，请核查微信登录状态'
                            break
                        self.shutdown.wait(min(2**attempts,15))
                        continue
                    # A brief successful start must not reset a flapping loop.
                    # A later, separate outage gets a fresh budget after stability.
                    if not self.receive_error and ready_since is not None and time.monotonic()-ready_since >= 30:
                        attempts = 0
                    if self.receive_error:
                        self.state = 'DEGRADED'
                    else:
                        self.process_one()
                    self.write_status()
                    self.shutdown.wait(0.25)
            except KeyboardInterrupt:
                pass
            except Exception as error:
                self.state,self.error = 'DEGRADED','业务运行失败：' + type(error).__name__
            finally:
                self.shutdown.set()
                sender.join(timeout=60)
                if sender.is_alive():
                    self.state = 'DEGRADED'
                    self.error = '发送调用尚未退出，桥接保留；退出守护负责后续清理'
                else:
                    try:
                        self.gateway.stop()
                        if self.state not in ('VERSION_UNSUPPORTED','LOGIN_REQUIRED','DEGRADED'):
                            self.state = 'STOPPED'
                    except Exception as error:
                        self.state,self.error = 'DEGRADED',str(error)
                self.write_status()
                log.removeHandler(handler)
                handler.close()
