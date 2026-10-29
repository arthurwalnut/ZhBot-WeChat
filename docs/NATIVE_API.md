# helper 原生适配边界

核查日期：2026-10-29。固定源码提交 `3e65e4bdaff438dc616f32d412175842fa138763`，来源 https://github.com/Prometheus-first/helper 。本文件记录源码调用事实；真实群和后台条件结果另见 `COMPATIBILITY.md`。

## 实际调用链

`wechat_bot.adapters.helper_native.HelperNative` 是本项目类型。它包装上游 `wxbot_framework.backend.NativeTextBackend(root, config, data_root=...)`，传入明确 `wechat_pid`、`wechat_account`。未导入或启动上游 `main.py`、网页台、插件管理器、防撤回、朋友圈、图库、自动加好友业务。

| 本项目方法 | 已核对的上游调用 |
| --- | --- |
| `inspect_bound(helper_root, pid)` | `run_selftest.modules(pid)` → `compatible_core(path, compatibility.json)` → `text_service.inspect_profile(pid)`；只读指定进程，不注入 |
| `start(emit)` | `NativeTextBackend.start(emit)` → `NativeTextService.start()` → `NativeFileHelperService.start()`；原生注册消息回调 |
| `send(Outgoing(kind='text'))` | `send_text(chat_id,text)`；真实 @ 用 `send_at_text(room,text,at_list)` |
| `send(Outgoing(kind='image'))` | `send_image(chat_id,path)` → `WxSendImage` |
| `send(Outgoing(kind='sticker'))` | `send_emoticon(chat_id,path)` → `WxSendEmoticon`，原生类型 47 |
| `fetch_sticker(event)` | 只加载 `plugins/anti_recall/stickers.py` 资源函数：`Sticker`、`download_sticker`、`_gif_payload`；发送副本由本项目 `convert_sticker` 生成，旧 `gif_bytes` 仅计算兼容去重摘要；不实例化防撤回插件 |
| `stop()` | 上游正常 stop，等接收/媒体任务结束，复用 `WxRemoveSelfTest`、`BridgeGuard`、`bridge_watchdog.py` |

上游 `run_selftest.py` 实际承担生产远程调用、构建检查及卸载，必须保留。`text_bridge.cpp` 复用 `selftest_bridge.cpp`；两个桥接 DLL 和 MinHook 源码/许可也保留。没有按文件名删除这些组件。

## 构建与身份

本项目先检查 helper Git HEAD、已跟踪文件无修改以及两个 DLL 的 SHA-256，再导入上游代码；锁定值见 `external/helper.lock.json`。上游读取真实核心 DLL，按大小和 SHA-256 匹配 `native/compatibility.json`，原生层继续校验映像布局。没有修改版本校验或使用未知构建地址。

接收为上游 SDK `Message`：`data.self_wxid` 为当前进程账号；`chat_id` 和 `sender_id` 来自 `TextRouter.convert`；群正文解析原生 `成员ID:\n正文`，作者缺失时跳过。`data.native_message_id` 来自 `ReceivedMediaMessageV6.native_message_id`（64 位编号转十进制字符串），不使用本地 `sequence` 冒充消息编号。

`data.at_members` 来自原生 `mention_source/msgsource` 中的 `atuserlist`。昵称只用于显示。`received_at` 是本项目收到回调的 UTC Unix 时间；该接收结构没有提供平台发送时间，`sent_at=None`。类型 49 引用/合并转发及系统消息不进入命令路由。缺失真实账号、作者、群、消息编号的事件不执行业务。

首次绑定始终需要明确 PID；已有账号不会因窗口顺序改变而自动改绑。生产启动在原 PID 已退出或不再有登录账号时，可只读枚举候选进程，逐个先校验精确核心构建再读取账号，只选唯一匹配持久绑定 `account_id` 的进程；枚举阶段不加载 DLL。原 PID仍存在但账号不同、权限不足、未知构建时直接拒绝，不改绑其他账号。适配器每次 start 和上游加载前均重新核对账号。该恢复路径已完成源码与离线选择检查，实际微信重启恢复仍需真机检查；无法唯一匹配时需重新 `bind --pid`。

`binding_mode=True` 仅输出事件，适配器发送方法也直接拒绝。生产接收限制为群白名单与主人私聊；生产发送还检查持久回复中的账号、目标与当前 connection_id。

## 媒体及回执限制

上游 `chat_allowlist=[]` 的含义是允许所有自动媒体下载。本项目传入不可匹配的媒体哨兵会话以关闭图片、文件、语音的自动保存，实际业务白名单在本项目内执行。类型 3 只输出 `metadata_only`，可拒绝把普通图片入表情库。它不是 PNG 原件下载成功的证据。Wordle PNG 发送调用真实图片接口；手机端确认仍需真机验收。

`health.capabilities` 仅列本适配器暴露且对应构建有接口的文本、真实 @、图片元数据、图片发送、原生表情资源取得/发送，不列联系人、自动加好友或朋友圈等未开放业务。此列表是接口能力，不替代真实验收结果。

类型 47 使用单条消息的原件地址/MD5，经上游 CDN 主机白名单、禁止重定向、大小、超时和 MD5 校验后获取。只在上传等待已匹配后下载，不导出账号收藏。原始 XML不保留；被接受上传事件的受控资源参数暂存于 inbox，普通日志不写 CDN 凭据。

当前支持完整 GIF 与静态 PNG/JPEG/WebP/BMP 表情原件。可直接发送的 GIF 保留编码，允许按上游结构解析去掉微信附加尾标；较大的 GIF 和其他格式生成最多 256 色、等比缩小的发送副本，校验帧数、各帧时长和循环设置不变。原件可到 20 MiB、8192 像素、累计 128 Mi 像素；发送副本保持 1 MiB/1024 像素/300 帧/64 Mi 像素校验。前两项在固定 C++ 桥接内亦有硬检查，未修改上游或桥接限制。

数据库 `note` 保留转换说明，添加成功回复只显示编号和结果。APNG/动画 WebP 与 WXGF 明确拒绝，未将动画拍平成单帧。原件与副本分别保存并校验摘要，兼容旧 32 色条目的去重；旧编码器仅用于兼容摘要，其较低解码限制不会拒绝新支持的资源。下载完成并校验成功后的转换失败可留存原件和不含凭据的格式诊断；不会建立可随机发送的条目。

WXGF 返回明确未支持，本版不安装 FFmpeg，也不把改变时长的转换当作原动画重放。此前 4.1.15.13 上的静态 PNG→32 色 GIF 原生发送已有手机确认；新版 256 色转换、动画 GIF 以及实际更新至 4.1.15.56 后的收发分别验收。

一次文本发送上限为 1023 个 UTF-8 字节；长回复在 outbox 拆成独立项，适配器不自动将部分发送成功掩盖成一个布尔值。上游 `success=True` 经过 `completion_success`、目标/内容、任务清理和 @名单检查，映射为 `accepted`；只代表该层原生调用确认，不是对方送达或已读。调用开始后返回 false、异常、超时全部为 `uncertain`，禁止盲目重发。只有调用前的失败可以判定未提交。

2026-10-29 首次真实 @ 检查中，主代理获得 `accepted`，用户反馈手机端没有实际提及。复查发现本项目直接调用 backend，遗漏上游 `ServiceFacade.send_at_text` 添加的可见标签；上游 `tests/test_mentions.py` 要求文本携带 `@昵称\u2005\n正文`，同时传独立的原生成员 ID。适配器已按这一格式补齐，先只读群成员缓存中的 `nickname`，缺失时以 wxid 显示，真实通知对象仍取 `at_list`；完整标签及正文一起校验 1023 字节限制。修正后已发送独立复测消息，用户明确确认真正提及成功；该结论来自手机端反馈。

原生 `text_completion_invoke` 写入的 `at_members` 是请求参数的副本；`mention_factory` 虽设置 `applied=true`，该字段未被发送完成检查读取。因此名单相同和 `accepted` 不是手机端确实产生提及的独立证据。

上游同一个 `_calls` 锁会串行化原生发送和接收轮询。它的原生队列溢出会抛出错误并停止接收；本项目据此报告 `DEGRADED`。没有根据线程仍存在或短时没有新消息推定完整收发。锁屏、最小化和远控断开的效果不由源码接口推定。

## 依赖来源

helper 为 `LicenseRef-helper-noncommercial-1.0` 个人非商业许可，原始 `LICENSE` 与 `THIRD_PARTY_NOTICES.md` 保留。DLL 来自固定提交的受版本控制二进制；上游说明由其 native 源码及 MinHook 1.3.4 构建，本轮没有独立复现二进制构建。

最小 Python 原生路径需要 `pefile`；单条表情资源工具导入需要 `cryptography` 与现有 `Pillow`。未启动模型/语音/Web 服务，无需安装这些功能的依赖。
