# Astra WeChat Lab v0.2.0

本版已增加 `wechat_bot` 原生接入、统一事务、待发回复及群功能代码。**真实群验收仍在进行，当前不能标记“群游戏可用”或“完整功能交付”。**

2026-10-29 本机记录：Windows 11、微信 4.1.15.13 的核心 DLL 指纹匹配固定上游；已实际接收指定群与主人私聊的新消息，并取得原生群 ID、成员 ID、消息编号及 `at_members`。最短收发检查的群文本、PNG 已获手机端确认；真实 @ 在补齐上游要求的显示标签和原生提及列表后复测，用户确认真正提及成功。完整机器人已通过 `start.ps1` 隐藏启动至 `READY`，原生正常停止与卸载已实测。代码接口、模拟测试、最短收发链路与完整群验收分别记录在 [兼容与验收结果](docs/COMPATIBILITY.md)。

单成员真实群检查已收到两次 zxj 文本回复和一次 Wordle 开局棋盘，用户确认回复正确。正常重启机器人后，当天抽取记录及原活跃局保留；无空格猜测在原局增加一猜，更新棋盘已获用户确认。指定成员原生表情入库和随机原生发送也获手机确认。本轮微信最小化下的单成员文本、PNG 和静态原生表情闭环通过；完整结算、双成员接力、动画与表情入库后重启重发、其他后台条件仍待验收。

实施依据：[v0.2.0 规划](ASTRA_WECHAT_V0_2_0_GROUP_READY_PLAN.md)。旧版 README 与验收事实完整保存在 [v0.1.0 验收记录](docs/V0_1_0_ACCEPTANCE.md)。旧游戏数据库、运行环境与验收文件保留；`wechat_reader` 继续用于独立诊断。生产入口只使用 helper 原生桥接，不订阅 OCR 快照。

## 安装

在机器人专用 Windows 用户的已登录桌面中运行。使用 Python 3.12 x64、Git 和已正常登录的机器人微信。本机现有 `.venv`、`.python` 可继续使用；仅在新机器且尚无环境时执行 `py -3.12 -m venv .venv`。

在项目根目录的 PowerShell 执行：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe -m pip install -c requirements-lock.txt -e ".[bot,dev,reader]"
.\scripts\fetch_helper.ps1
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m wechat_bot --help
```

`requirements-lock.txt` 固定本次检查的 Python 依赖。`fetch_helper.ps1` 从 `external/helper.lock.json` 获取固定提交、核对 DLL 摘要，并保留上游源码、许可和生命周期组件。已有目录的提交或受版本控制文件不同会停止，不覆盖现有修改。日常启动不重新安装依赖、不拉取最新分支。

接入源为 [Prometheus-first/helper](https://github.com/Prometheus-first/helper/tree/3e65e4bdaff438dc616f32d412175842fa138763)，固定提交 `3e65e4bdaff438dc616f32d412175842fa138763`。许可为 `LicenseRef-helper-noncommercial-1.0`；其 [完整许可](https://github.com/Prometheus-first/helper/blob/3e65e4bdaff438dc616f32d412175842fa138763/LICENSE)允许个人学习、研究、测试、娱乐及非商业自用，分发须保留原许可和第三方声明。本项目没有将该组件改标为 MIT 或 Apache。组件来源及两份桥接 DLL 的摘要见 [第三方声明](THIRD_PARTY_NOTICES.md)和 [锁定清单](external/helper.lock.json)。DLL 来自该提交内的二进制文件，尚未独立验证可复现构建。

## 绑定机器人、测试群与主人

首次绑定需要真实进程、账号和群 ID。显示昵称、群名及旧 OCR 配置不能用作权限键。先完成微信扫码及手机确认，再进行以下操作。

```powershell
New-Item -ItemType Directory -Force -Path runtime | Out-Null
if (-not (Test-Path -LiteralPath 'runtime/config.bot.toml')) {
    Copy-Item -LiteralPath config.bot.example.toml -Destination runtime/config.bot.toml
}
Get-Process Weixin | Select-Object Id, Path, SessionId, StartTime
[int]$RobotPid = Read-Host '明确选择机器人微信进程 PID'
.\.venv\Scripts\python.exe -m wechat_bot doctor --config runtime/config.bot.toml --pid $RobotPid
```

`doctor` 只读取指定进程的已加载核心模块、版本指纹和账号资料，不加载桥接。它要求实际 DLL 大小和 SHA-256 同时匹配上游支持项；版本字符串本身不足以通过校验。核对输出账号确属机器人后，填写实际 ID 并观察新消息：

```powershell
$RobotAccount = Read-Host 'doctor 输出且已确认的机器人 account_id'
.\.venv\Scripts\python.exe -m wechat_bot bind --config runtime/config.bot.toml --pid $RobotPid --account $RobotAccount --observe --seconds 120
```

此命令加载明确绑定的原生桥接，发送通道禁用。出现 `OBSERVING` 后，由另一账号在指定测试群发送一条新消息，并真实 @机器人；若需要主人私聊管理，再由主人向机器人发送一条新私聊。终端只显示原生账号、群、发送者、消息编号、类型与提及对象，不输出聊天正文。观察结束正常停止桥接；这一步不自动保存群或主人配置。

从对应新事件取得 `chat_id`（群 ID 以 `@chatroom` 结尾）及主人 `sender_id`，明确保存：

```powershell
$TestGroup = Read-Host '指定测试群的原生 chat_id'
$OwnerAccount = Read-Host '主人原生 sender_id；仅本机管理可留空'
if ($OwnerAccount) {
    .\.venv\Scripts\python.exe -m wechat_bot bind --config runtime/config.bot.toml --pid $RobotPid --account $RobotAccount --group $TestGroup --owner $OwnerAccount
} else {
    .\.venv\Scripts\python.exe -m wechat_bot bind --config runtime/config.bot.toml --pid $RobotPid --account $RobotAccount --group $TestGroup
}
```

省略 `--owner` 保留当前配置；新配置默认空主人。已有主人配置需要清空时编辑本地 TOML 的 `owner_id = ""`。多个允许群可重复传 `--group`。保存前核对实际账号，已有配置先备份到配置目录下的 `backups/`。

`data_dir`、`helper_root` 的相对路径均从配置文件所在目录解析，运行时打印绝对数据路径。示例放入 `runtime/config.bot.toml` 后，默认数据在 `runtime/`。示例 `stickers = false`；原生表情真机验收前保持关闭，帮助中不展示关闭功能。机器人数据库绑定一个账号；换账号需使用独立数据目录。

## 启动、状态与停止

前台运行，Ctrl+C 请求正常停止：

```powershell
.\.venv\Scripts\python.exe -m wechat_bot run --config runtime/config.bot.toml
```

在同一已登录用户会话中后台启动：

```powershell
.\scripts\start.ps1
.\.venv\Scripts\python.exe -m wechat_bot status --config runtime/config.bot.toml
.\.venv\Scripts\python.exe -m wechat_bot pause --config runtime/config.bot.toml
.\.venv\Scripts\python.exe -m wechat_bot resume --config runtime/config.bot.toml
.\scripts\stop.ps1
.\.venv\Scripts\python.exe -m wechat_bot status --config runtime/config.bot.toml
```

三个管理脚本都接受 `-ConfigPath`；`start.ps1` 通过脚本位置定位项目虚拟环境，隐藏启动 Python 并打印进程、实际状态及启动日志。`stop.ps1` 等价于 `python -m wechat_bot stop --config ...`，提交停止请求后由运行循环调用上游清理。查看后续 `status` 确认结果；无需杀微信进程。

`status` 显示账号连接、接收线程、适配器开放的能力、最近收件时间、inbox/outbox 各状态数量及错误。`READY` 表示本次桥接接收线程处于连接状态；每次发送是否到达仍以实际接收结果为准。状态文件超过 15 秒未更新或进程无法核验时显示 `STALE`；进程已退出时显示 `STOPPED`，并保留 `recorded_state` 供查看退出原因。没有新聊天本身不作为故障。

暂停状态保存在数据库，停止新群业务处理；已生成的待发回复仍按队列处理。需要停止全部收发时使用 `stop`。配置主人可私聊发送 `机器人状态`、`暂停群功能`、`恢复群功能`；空主人配置只开放本机管理。普通私聊不进入游戏。

按需安装或移除当前用户登录启动任务：

```powershell
.\scripts\register_task.ps1
.\scripts\register_task.ps1 -Remove
```

任务在当前用户交互登录后启动，不设置 Windows 自动登录、不修改锁屏或睡眠策略。微信需要扫码或手机确认时由本人完成。当前没有 Windows Session 0 服务或 Linux 无桌面部署验收。

## 群指令

以下是当前路由实现的命令，真实群效果以兼容表为准。默认要求通过微信成员选择器产生的真实 @，随后输入命令；手打相同昵称不提供权限。命令须为独立文本，引用、转发、XML 内嵌文字不进入游戏。明确真实 @机器人但未匹配的文本收到简短帮助；普通无关群聊仍忽略。每位成员默认 1 秒冷却。

| 群输入（前置真实 @机器人） | 已实现的处理 |
| --- | --- |
| `帮助` | 显示已启用功能 |
| `随机zxj` | 按原生成员 ID、北京时间每日保存一次；同日返回原结果，可用来复查当天结果 |
| `我的zxj` / `我的zxj 2` | 每页 10 条历史，显示日期、结果、总数及页码 |
| `猜词` / `猜词 5` | 每群一局；已有活跃局展示原棋盘 |
| `我猜是 apple` / `我猜是apple` | 空格可省略；多人共用六次有效猜测；无效、未收录或重复词不扣次数；回复该次棋盘 PNG |
| `猜词棋盘` | 查询当前/最近一局棋盘，不消耗猜测次数 |
| `猜词战绩` | 查询当前群中本人猜中次数 |
| `结束猜词` | 开局者或配置主人结束该群当前局 |
| `添加表情包` | 开启该群、该成员 60 秒的原生表情上传等待，需先启用表情功能 |
| `取消添加` | 取消本人的等待 |
| `随机表情包` | 从本群持久库选取资源，通过原生表情接口发送 |
| `我的表情包` / `我的表情包 2` | 分页查询本人在本群的条目编号 |
| `删除表情包 12` | 添加者或配置主人删除条目，同时取消对应尚未开始发送的待发项 |

Wordle 复用原规则、词库及绘图，当前本地答案池仅开放长度 5。首次猜中者获得一场胜利；重投同一原生消息不重复结算。每个待发 PNG 保存独立棋盘快照；稍后的猜测不改写此前回复内容。

表情等待按账号、群和成员隔离；普通图片/文字不会入库。只有取得原件、校验并持久保存成功才回复添加成功，同群按资源摘要去重。代码支持完整 GIF 原件及明确说明的 PNG→GIF 转换；WXGF 和未支持的商店/加密资源返回失败。发送资源限制为不超过 1 MiB、1024 像素、300 帧及累计 64 Mi 像素，属于当前实现限制。单帧 PNG 原件转换后的原生发送已获手机确认；动画效果和入库后重启重发仍待验收。删除先移出随机池，保留物理文件以避免删除仍被待发回复引用的资源；当前没有自动磁盘回收任务。

## 事务、重试与恢复

`inbox` 去重键为 `(helper.native_text, account_id, chat_id, native_message_id)`。游戏写入、处理结果、事件完成标记与有序 outbox 共用同一个 SQLite 连接和事务。PNG 渲染、媒体下载和原生发送在事务外执行。普通无关群聊不写入业务 inbox；本项目轮转业务日志记录事件状态与错误，账号配置和资源凭据留在被 Git 忽略的本地目录。

outbox 状态为 `pending / sending / accepted / failed / uncertain / expired`。明确尚未提交且可重试的失败，最多执行配置中的 3 次发送尝试，使用已保存的结果。原生调用已发生但结果不明，或重启时仍为 `sending`，转为 `uncertain` 并停止自动重发。`accepted` 只表示上游确认层级，不表示对端已读。文本和图片有各自待发项。

未处理的普通命令默认超过 120 秒失效，待发回复默认超过 300 秒不补发；已提交业务状态保留，可重新查询当天 zxj、棋盘或战绩。账号和当前白名单在发送前再次检查，新连接使用新连接标识。重启取消尚未收到表情的上传等待；已经收到并保存上传意图的事件保留，不按普通命令的 120 秒期限清除；恢复时重新核对账号和群后取得该事件资源。若原件地址已失效则返回失败，不登记成功条目。

连接中断按有限退避处理；稳定连接 30 秒后重新计一轮故障预算，连续失败最多尝试 5 次。原 PID 失效时，代码只读检查受支持构建的候选进程，必须唯一匹配已绑定账号才重新连接；不自动接受其他账号。原生接收报告间断或持久化失败进入 `DEGRADED`，保留已有数据并停止继续处理，需要检查错误后重启。断线期间未被桥接捕获的消息没有历史补拉。微信退出、注销、睡眠与掉登录期间不提供收发；恢复及远程桌面断开的实测结果见兼容表。

微信更新后重新执行 `doctor`。核心指纹不匹配进入 `VERSION_UNSUPPORTED`，停止加载/发送并保留数据库。取得新的上游适配后更新固定提交及摘要，再做真实文本/图片验证。本项目不降级微信、不修改更新策略、不删除构建校验。

## 文件职责与数据

调用关系：`wechat_bot.__main__ → Runtime → helper_native 接收 → Router → zxj / Wordle / stickers → SQLite outbox → 渲染与原生发送`。helper 的默认应用入口与插件管理器不启动；防撤回、朋友圈、图库和自动加好友插件不进入运行链。

| 文件 | 职责 |
| --- | --- |
| `src/wechat_bot/__main__.py`、`config.py` | 本机命令、绑定、配置校验与状态读取 |
| `src/wechat_bot/adapters/helper_native.py`、`gateway.py` | 固定依赖/客户端指纹检查、账号连接、实际消息转换、文本/真实 @/PNG/原生表情接口 |
| `src/wechat_bot/runtime.py` | 单实例、接收持久化、业务循环、发送队列、重连和正常退出 |
| `src/wechat_bot/router.py`、`store.py` | 群白名单、权限、命令与统一数据库事务 |
| `src/wechat_bot/stickers.py` | 成员等待、资源校验和原子落盘、持久库、随机选择及删除 |
| `src/zxj/service.py`、`src/wordle/game.py`、`src/wordle/store.py` | 原规则与持久化；支持外部事务，原 CLI 独立运行 |
| `src/wordle/render.py` | 从保存的棋盘快照绘图，不改变业务状态 |
| `external/helper/` | 固定上游及必要 DLL、`run_selftest.py`、watchdog 和清理组件 |
| `tests/test_bot.py`、`tests/test_stickers.py` | 四个整合场景；其余测试保留旧游戏和读取回归 |

默认配置位于 `runtime/config.bot.toml` 时：

| 位置 | 内容 |
| --- | --- |
| `runtime/bot.sqlite3` | 账号绑定、inbox、zxj/Wordle、outbox、表情元数据与暂停设置 |
| `runtime/media/wordle/` | 每个待发项对应的棋盘 PNG |
| `runtime/media/stickers/` | 持久表情资源；不作为临时缓存清空 |
| `runtime/status.json`、`bot.lock`、`stop.request` | 状态、单实例锁和停止请求 |
| `runtime/logs/` | 轮转业务日志和各次启动输出 |
| `runtime/backups/` | 覆盖配置前保留的备份；数据库备份应使用 SQLite backup API 或正常停止后复制 |
| `runtime/acceptance-v0.2.0.md` | 本轮验收记录（包含真实身份的信息仅留本地） |
| `runtime/zxj.sqlite3`、`wordle.sqlite3`、`boards/` | 原本地 CLI 数据与历史验收；不自动迁移为真实微信身份 |

`.venv/`、`.python/`、旧配置和验收记录保留。备份机器人时同时保存数据库、配置和 `media/stickers/`；不要仅保留条目而删除原件。未涉及大模型部署、长期群聊记忆或私人自动执行助手。

本地游戏与旧诊断入口继续可用：

```powershell
.\.venv\Scripts\python.exe -m zxj draw --user alice
.\.venv\Scripts\python.exe -m zxj history --user alice
.\.venv\Scripts\python.exe -m wordle --help
.\.venv\Scripts\python.exe -m wechat_reader --help
```

旧游戏 `--data-dir` 相对运行时当前目录解析；机器人配置中的 `data_dir` 相对配置目录解析。详细旧 CLI 和 OCR 限制见 v0.1.0 验收记录。

## 验证记录与剩余验收

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp runtime/test-v020 -p no:cacheprovider
.\.venv\Scripts\python.exe -m pip check
```

2026-10-29 整合检查：`9 passed in 0.74s`，包括原 5 个有效测试与 4 个整合场景；`pip check` 通过。新增场景覆盖身份/@/权限、统一事务与发送不确定恢复、多人游戏与独立棋盘快照、表情等待隔离/持久资源。测试使用临时数据库与模拟原生事件，未修改旧运行数据。`--basetemp` 只用于指定测试目录，该目录会被 pytest 重新创建，不要指向实际运行数据目录。

最短真实链路已取得群与主人私聊的新事件、原生身份和提及字段；群文本/PNG 发送已获手机确认。首次真实 @ 发送缺少 SDK 要求的显示标签，手机端检查失败；补齐标签并保留原生提及列表后再次发送，用户确认真正提及成功。`start.ps1` 隐藏启动完整机器人至 `READY`，正常停止及桥接卸载均已实际执行。

真实群业务的两次 `随机zxj` 和一次开局均已获用户确认；当天抽取记录只有一条。最初 `我猜是apple` 因当时路由要求空格而未匹配，没有扣除次数；已增加无空格支持，缺词或多余参数会回复明确格式提示。正常 stop/start 后，新发送的无空格猜测已在原局增加第 1 步，更新棋盘原生发送 accepted。

指定成员随后完成表情等待、原生上传和随机发送：本地保存 PNG 原件转换的单帧 GIF（17132 字节），添加成功回复带转换说明，随机回复通过原生 sticker 通道且 accepted。当前共 7 条 inbox done、7 条 outbox accepted；用户对更新棋盘及表情添加、随机发送反馈“都跑起来了”。单帧资源不能作为动画效果验收。

本轮应用重启前，窗口工具确认微信处于最小化，之后未恢复窗口；随后手机发送的指令已得到文本、更新棋盘 PNG 和静态原生表情回复，用户确认运行成功。本轮最小化单成员闭环记为 PASS，托盘、锁屏、目标群未展开和遮挡继续单独验收。

第二名测试成员暂不可用。剩余真机验收：A Wordle 完整结算与真实战绩、双成员身份与接力、动画表情及入库后重启随机发送；B 未展开会话、遮挡、托盘、锁屏和实际远程断开逐项核心收发；C 微信退出/掉登录与同账号恢复（游戏和当天结果已随本次应用重启保留）。具体 PASS/FAIL/NOT_TESTED 以 [COMPATIBILITY.md](docs/COMPATIBILITY.md) 为准。
