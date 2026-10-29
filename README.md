# Astra WeChat Lab v0.2.5

本版清理重复实现与测试，保留现有群指令、管理后台、原生桥接、数据格式和固定 `ZhBot.exe` 入口。安装包及升级说明见 [v0.2.5 交付文档](docs/DELIVERY_v0.2.5.md)，具体清理见 [变更记录](CHANGELOG.md)。

已有真实群记录覆盖文本、真实 @、棋盘 PNG、静态原生表情、双成员身份和 Wordle 接力；新群已完成主人登记、本机确认、重启和实际收发。用户在新群测试后反馈“目前来看没有什么问题”。原生回执、数据库证据与手机确认分别记录于 [兼容与验收结果](docs/COMPATIBILITY.md)，不能把 accepted 回执当成手机收件确认。

本机已验证微信最小化下的单成员闭环。动画表情手机效果、入库后跨重启随机发送、托盘、锁屏、实际远控断开及微信掉登录恢复仍有待验收。按项目约定，后续迭代仅在用户报告机器人功能问题时处理微信版本问题；运行时已有的账号与构建核验继续保留。

旧游戏数据库、运行环境及验收记录保留；`wechat_reader` 作为独立诊断工具保留，生产入口使用 helper 原生桥接。旧版事实见 [v0.1.0 验收记录](docs/V0_1_0_ACCEPTANCE.md)。

## 安装

在机器人专用 Windows 用户的已登录桌面中运行。使用 Python 3.12 x64、Git 和已正常登录的机器人微信。本机现有 `.venv`、`.python` 可继续使用；仅在新机器且尚无环境时执行 `py -3.12 -m venv .venv`。

新安装可直接执行 `powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1`，会创建缺失的虚拟环境、安装锁定依赖、获取固定 helper，并仅在配置不存在时复制空白示例；不会绑定或启动微信桥接。也可在项目根目录的 PowerShell 手动执行：

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

CLI 的 `bind --group` **替换整个群白名单**，需逐个传入所有要保留的群；运行中的进程要正常重启后才应用配置。日常新增群推荐使用下面的 EXE 群聊接入，添加会保留已有群。

`data_dir`、`helper_root` 的相对路径均从配置文件所在目录解析，运行时打印绝对数据路径。示例放入 `runtime/config.bot.toml` 后，默认数据在 `runtime/`。示例 `stickers = false`；原生表情真机验收前保持关闭，帮助中不展示关闭功能。机器人数据库绑定一个账号；换账号需使用独立数据目录。

## 在现有机器人电脑接入新群

`v0.2.3` 发布后的部署检查补充了“群聊接入”窗口。此流程使用当前已绑定机器人账号；新群不需要改源码或另建机器人进程。

1. 将机器人账号加入准备启用的群；使用登记方式时，配置的主人账号也需在群里
2. 打开 `ZhBot.exe`，等待 `READY`，点击“群聊接入”→“生成登记码”
3. 主人从目标群通过成员选择器真实 @机器人，再发送窗口显示的 `登记群聊 十二位登记码`，5 分钟内有效
4. 点击“刷新状态”，核对候选原生群 ID 和发送者，点击“确认接入并重启”；后台追加白名单、备份配置，再正常重启机器人
5. 等待 `READY`，重新打开“群聊接入”，检查目标群已列入“当前进程已生效的群”；在该群真实 @发送 `随机zxj` 和 `猜词`，确认手机收到文字与棋盘

已知原生群 ID 时，也可在该窗口直接填写并点击“添加并重启”。移除群会保留历史和媒体，重启后不处理该群新业务，尚未开始发送的旧回复按授权检查过期；已经提交的发送不撤回。当前至少保留一个允许群，停止所有群业务可使用“正常停止”。正在等待用户上传的短期表情会话在重启后需要重新发起，已接收的上传意图仍持久保存。

登记只开放“配置主人 + 真实 @ + 原生群/成员/消息 ID + 有效一次性码”的窄入口，不读取或保存其他未授权群的普通聊天。收到登记后只保存候选元数据，不回复消息、不自动启用群；本机确认后才写白名单。多窗口修改使用当前名单校验，过期页面须刷新。群名缺少可靠原生字段，界面使用原生群 ID。

在同一机器人账号下，多群共享一个进程和数据库；Wordle 对局/战绩、表情池按群隔离，zxj 每日结果按成员全局共享。代码和隔离数据测试已覆盖新群登记、确认、重启后的路由及移除后的待发检查；目标群的实际收发与后台条件仍以 [验收记录](docs/COMPATIBILITY.md) 为准。

新电脑部署需要完整项目、Python 3.12 x64、虚拟环境、Git、固定 helper 源码及其 `.git`/许可、机器人登录和真实绑定，单独复制 EXE 不构成完整安装。仅把旧 `runtime` 复制到另一目录也不构成数据迁移：配置和旧表情元数据含绝对路径，需单独迁移核对。锁屏、托盘、远控断开及掉登录恢复目前没有完整真机验收，不据此宣称任意电脑无人值守可用。

## 启动、状态与停止

本机日常测试：先打开微信并登录已绑定机器人账号，再双击项目根目录的 **`ZhBot.exe`**。入口读取旁边项目中的最新代码、`.venv` 与 `runtime/config.bot.toml`；更新项目后继续使用同一个入口。它是项目启动器，需要这些目录随项目保留。窗口提供运行状态及正常停止操作，关闭启动器窗口后机器人继续后台运行。

当前版本增加本机管理后台，仍使用上述 `ZhBot.exe` 入口。窗口包含运行概览、zxj 记录、Wordle 战绩和表情库，可按已配置群与已观察成员筛选。运行状态每 4 秒刷新；业务记录通过“刷新数据”更新。管理界面直接调用本机 Python 和 SQLite，无网络监听端口；拥有该 Windows 用户和项目目录访问权限的人可以操作。

| 管理页面 | 操作与生效规则 |
| --- | --- |
| zxj 记录 | 查看成员历史；“编辑 z / x / j 字库”保存三组单字，空格或换行分隔；每组至少一个字，不接受组内重复。保存后用于后续新抽取，已有每日结果保留。字的拼音归组由拥有者维护 |
| Wordle 战绩 | 查看已猜中对局的成员、单词、时间和猜测次数；“管理 Wordle 词库”可按长度/文本搜索，添加 3～10 字母单词或删除选中词。新增词同时进入答案和可猜词库，删除同时移出两者；进行中对局继续使用开局词库快照 |
| 表情库 | 查看上传者、来源、时间、格式及预览；“从本机添加”选择目标群和图片/GIF，归属配置主人（未配置主人时归属机器人账号），标记为本机导入；“删除选中表情”移出该群随机池并取消尚未开始发送的待发项 |

**表情池按群共用**：同群 A 上传的表情和 B 上传的表情，A、B 都可以抽到；群之间隔离。成员筛选只影响管理页面显示，不改变随机抽取范围。本机导入与微信上传共用资源校验、转换和摘要查重。默认预览发送 GIF，也可切换原件；Windows 内置预览不支持的原件格式会显示提示。删除保留原件和发送文件，已开始的原生发送可能完成。

zxj 每日结果按成员保存，旧记录没有抽取发生群字段；选择群时展示该群已观察成员的全局历史。成员名称来自接收事件，缺少名称时显示真实 ID。管理页面只展示已猜中的 Wordle 答案，未结束对局不列出答案。

字库和词库保存在 `runtime/bot.sqlite3` 的 `zxj_characters`、`wordle_words` 表中，随数据库保留；源码 JSON 仅作首次初始化种子。词库编辑后无需重启机器人。此次升级已先备份数据库至 `runtime/backups/bot-before-admin-20261030-013927.sqlite3`。本机管理修改不向微信群发送消息。

启动时仍核验真实账号和微信构建，按已绑定账号寻找重启后的新 PID。扫码或手机确认需本人完成。已运行时显示当前状态；构建不支持或账号不匹配时显示失败原因。源码位于 `launcher/`，重新构建命令为 `powershell -ExecutionPolicy Bypass -File .\scripts\build_launcher.ps1`。

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

机器人新生成的文字回复统一省略中文句号，日期中的英文点号保留。表情添加成功只回复 `表情编号x：添加成功`，其中 x 为实际编号；重复上传仍提示已有资源。

| 群输入（前置真实 @机器人） | 已实现的处理 |
| --- | --- |
| `帮助` | 显示已启用功能 |
| `随机zxj` | 按原生成员 ID、北京时间每日保存一次；回复 `今天（26.10.30）` 后换行，再显示 `你的zxj是“随机组合”`；同日返回原结果 |
| `我的zxj` / `我的zxj 2` | 每页 10 条历史，日期使用 `YY.MM.DD`，显示结果、总数及页码 |
| `猜词` / `猜词 3` … `猜词 10` | 默认 5 字母，每群一局；已有活跃局展示原棋盘 |
| `我猜是 apple` / `我猜是apple` | 空格可省略；多人共用该局次数；无效、未收录或重复词不扣次数；回复该次棋盘 PNG |
| `猜词棋盘` | 查询当前/最近一局棋盘，不消耗猜测次数 |
| `猜词战绩` | 查询当前群中本人猜中次数 |
| `结束猜词` | 开局者或配置主人结束该群当前局 |
| `添加表情包` | 开启该群、该成员 30 秒的原生表情上传等待，需先启用表情功能 |
| `取消添加` | 取消本人的等待 |
| `随机表情包` | 从本群持久库选取资源，通过原生表情接口发送 |
| `我的表情包` / `我的表情包 2` | 分页查询本人在本群的条目编号 |
| `删除表情包 12` | 添加者或配置主人删除条目，同时取消对应尚未开始发送的待发项 |

Wordle 开放 3～10 字母，使用项目维护的词库；保留原 5 字母词库并扩充其余长度。新局次数按 `min(9, 5 + floor((wordLength - 3) / 2))` 保存：

| 字母数 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 共用猜测次数 | 5 | 5 | 6 | 6 | 7 | 7 | 8 | 8 |

升级前的对局保留原来的 6 次上限；每局上限及待发棋盘快照持久保存。首次猜中者获得一场胜利；重投同一原生消息不重复结算。每个待发 PNG 保存独立棋盘快照；稍后的猜测不改写此前回复内容。棋盘下方用绿色方块说明字母和位置正确，黄色方块说明字母存在但位置不同。

表情等待按账号、群和成员隔离；普通图片/文字不会入库。只有取得原件、校验并持久保存成功才回复添加成功。同一成员或不同成员重复上传，按同群的发送文件及原件 SHA-256 去重，返回已有条目并保留原添加者；这属于字节去重，不提供视觉相似度识别。

接收表情消息中的静态 PNG/JPEG/WebP/BMP 与 GIF 原件，按实际内容解码识别格式。原件完整另存，最多 20 MiB、单边 8192 像素、累计解码 128 Mi 像素。符合发送限制的 GIF 保留原编码；其他资源生成最多 256 色的 GIF 副本（有透明像素时 255 色加透明索引）。大 GIF 不再仅因超过 1 MiB/1024 像素而被直接拒绝，而是等比缩小发送副本；转换后逐项核对帧数、每帧时长及循环设置，不删帧、不将有限或单次播放改成无限循环。

原生发送副本仍需符合固定桥接的 1 MiB、1024 像素，以及上游 Python 的 300 帧、累计 64 Mi 像素检查。GIF 色彩与半透明效果可能变化，转换说明保存在数据库 `note` 中，成功消息只显示编号及结果。本项目没有 PNG→JPG 路径。动态 PNG/WebP、WXGF 仍未支持，超过 300 帧的资源明确拒绝，避免丢弃动画内容。普通图片消息和文件消息继续不进入原生表情添加流程。

已下载且通过来源校验、但后续转换失败的原件保存在 `media/stickers/unprocessed/` 供本机诊断，不登记为成功表情、不进入随机池。轮转日志记录资源格式、体积、尺寸和摘要，不写 CDN 参数或原始 XML。下载失败或未通过完整性校验的内容不会作为原件保存。

旧条目及发送文件保留，重新上传可补存原件并识别旧版 32 色转换的重复项；已有条目不会自动换成新发送副本。要替换旧副本，由添加者或主人先删除对应条目，再重新上传原表情。旧版静态原生发送已有手机确认；新版 256 色副本、动画及入库后重启重发的实测情况见兼容表。删除先移出随机池，保留物理文件以避免删除仍被待发回复引用的资源；当前没有自动磁盘回收任务。

## 事务、重试与恢复

`inbox` 去重键为 `(helper.native_text, account_id, chat_id, native_message_id)`。游戏写入、处理结果、事件完成标记与有序 outbox 共用同一个 SQLite 连接和事务。PNG 渲染、媒体下载和原生发送在事务外执行。普通无关群聊不写入业务 inbox；本项目轮转业务日志记录事件状态与错误，账号配置和资源凭据留在被 Git 忽略的本地目录。

outbox 状态为 `pending / sending / accepted / failed / uncertain / expired`。明确尚未提交且可重试的失败，最多执行配置中的 3 次发送尝试，使用已保存的结果。原生调用已发生但结果不明，或重启时仍为 `sending`，转为 `uncertain` 并停止自动重发。`accepted` 只表示上游确认层级，不表示对端已读。文本和图片有各自待发项。

未处理的普通命令默认超过 120 秒失效，待发回复默认超过 300 秒不补发；已提交业务状态保留，可重新查询当天 zxj、棋盘或战绩。账号和当前白名单在发送前再次检查，新连接使用新连接标识。重启取消尚未收到表情的上传等待；已经收到并保存上传意图的事件保留，不按普通命令的 120 秒期限清除；恢复时重新核对账号和群后取得该事件资源。若原件地址已失效则返回失败，不登记成功条目。

连接中断按有限退避处理；稳定连接 30 秒后重新计一轮故障预算，连续失败最多尝试 5 次。原 PID 失效时，代码只读检查受支持构建的候选进程，必须唯一匹配已绑定账号才重新连接；不自动接受其他账号。原生接收报告间断或持久化失败进入 `DEGRADED`，保留已有数据并停止继续处理，需要检查错误后重启。断线期间未被桥接捕获的消息没有历史补拉。微信退出、注销、睡眠与掉登录期间不提供收发；恢复及远程桌面断开的实测结果见兼容表。

运行时核心指纹不匹配会进入 `VERSION_UNSUPPORTED`，停止加载/发送并保留数据库。仅在用户明确报告功能问题后排查版本；需要新适配时再核对上游固定提交和摘要并做真实文本/图片验证。本项目不降级微信、不修改更新策略、不删除构建校验。

## 文件职责与数据

调用关系：`ZhBot.exe → launcher/control.py → .venv Python → wechat_bot.__main__ → Runtime → helper_native 接收 → Router → zxj / Wordle / stickers → SQLite outbox → 渲染与原生发送`。命令行与 EXE 调用相同运行入口。helper 的默认应用入口与插件管理器不启动；防撤回、朋友圈、图库和自动加好友插件不进入运行链。

本机管理调用：`ZhBot.exe → launcher/control.py admin（UTF-8 JSON 标准输入）→ AdminService → dictionaries / StickerService / SQLite`。管理与机器人共用事务数据库；Wordle 开局词库另存于 `games.allowed_words_json`，本机表情来源另存于 `stickers.origin`。

| 文件 | 职责 |
| --- | --- |
| `ZhBot.exe`、`launcher/`、`scripts/build_launcher.ps1` | 固定 Windows 入口、启动/状态/停止控制及本机构建；调用项目现有 Python 环境 |
| `src/wechat_bot/admin.py`、`dictionaries.py` | 本机管理查询、字库和词库编辑、表情导入删除；数据库初始化种子及输入校验 |
| `src/wechat_bot/groups.py` | 有限时主人登记、候选确认、保留旧群的白名单增删、配置备份与运行生效状态 |
| `src/wechat_bot/__main__.py`、`config.py` | 本机命令、绑定、配置校验与状态读取 |
| `src/wechat_bot/adapters/helper_native.py`、`gateway.py` | 固定依赖/客户端指纹检查、账号连接、实际消息转换、文本/真实 @/PNG/原生表情接口 |
| `src/wechat_bot/runtime.py` | 单实例、接收持久化、业务循环、发送队列、重连和正常退出 |
| `src/wechat_bot/router.py`、`store.py` | 群白名单、权限、命令与统一数据库事务 |
| `src/wechat_bot/stickers.py`、`sticker_media.py` | 成员等待、PNG 转换、原件/副本校验和原子落盘、持久库、随机选择及删除 |
| `src/zxj/service.py`、`src/wordle/game.py`、`src/wordle/store.py` | 原规则与持久化；支持外部事务，原 CLI 独立运行 |
| `src/wordle/render.py` | 从保存的棋盘快照绘图，不改变业务状态 |
| `external/helper/` | 固定上游及必要 DLL、`run_selftest.py`、watchdog 和清理组件 |
| `tests/` | 保留业务事务、成员权限、媒体、群接入及管理整合检查；旧 CLI 与读取诊断的有效回归继续保留 |

默认配置位于 `runtime/config.bot.toml` 时：

| 位置 | 内容 |
| --- | --- |
| `runtime/bot.sqlite3` | 账号绑定、inbox、zxj/Wordle、outbox、表情元数据与暂停设置 |
| `runtime/media/wordle/` | 每个待发项对应的棋盘 PNG |
| `runtime/media/stickers/` | 持久表情资源；不作为临时缓存清空 |
| `runtime/media/stickers/originals/` | 新上传资源的原件；旧条目未保存的原件不会凭空补回 |
| `runtime/media/stickers/unprocessed/` | 下载和来源校验成功但后续转换失败的原件，仅本机诊断，不在随机池 |
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

## 验证与验收

```powershell
.\.venv\Scripts\python.exe -m pip install -c requirements-lock.txt -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pip check
```

测试使用临时数据库和模拟事件，不修改实际运行库。发布包不含测试和开发依赖；从 Git 仓库执行上述检查。历次真实兼容、原生回执、手机确认及未测条件见 [COMPATIBILITY.md](docs/COMPATIBILITY.md)，本版构建和检查结果见 [交付文档](docs/DELIVERY_v0.2.5.md)。
