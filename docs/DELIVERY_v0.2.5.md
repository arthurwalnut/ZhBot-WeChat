# ZhBot v0.2.5 交付说明

本版为现有群机器人及本机管理后台的代码整理版本。群指令、每日额度、Wordle 次数规则、表情转换与查重、群白名单和数据格式沿用现有版本；没有数据库迁移或新增运行依赖。原 `ZhBot.exe` 入口继续使用。

## 发布文件

| 文件 | 用途 |
| --- | --- |
| `ZhBot-v0.2.5-windows.zip` | Windows 安装包：EXE、生产源码、诊断读取器、配置示例、安装/启停脚本、文档、依赖锁定清单及 Python wheel |
| `astra_wechat_lab-0.2.5-py3-none-any.whl` | Python 发行包，不含 EXE 或 helper |
| `astra_wechat_lab-0.2.5.tar.gz` | Python 源码发行包，保留维护所需测试 |
| `ZhBot-v0.2.5-SHA256SUMS.txt` | 上述三个文件的 SHA-256 |

Windows ZIP 不含用户配置、数据库、媒体、聊天记录、验收私密记录、虚拟环境或测试。它需要首次安装依赖并获取固定 helper，属于联网安装包，单独的 EXE 不是独立运行环境。

## 安装与日常使用

使用 Windows 11 x64、Python 3.12 x64、Git，以及机器人专用 Windows 用户的已登录桌面。解压后保留完整目录结构，在该目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

Python 未注册到 `py` 时传入 `-PythonPath 'C:\实际路径\python.exe'`。需要本机代理时，可在这次 PowerShell 会话中先设置：

```powershell
$env:HTTP_PROXY = 'http://127.0.0.1:7897'
$env:HTTPS_PROXY = 'http://127.0.0.1:7897'
```

安装脚本创建缺失的 `.venv`，按 `requirements-lock.txt` 安装机器人和可选诊断读取器依赖，检查依赖一致性，获取并校验固定 helper，仅在配置不存在时复制空白示例。开发测试依赖不安装。安装不加载微信桥接；首次机器人账号、主人、群绑定按 [README](../README.md#绑定机器人测试群与主人) 操作，扫码与手机确认由账号本人完成。

完成绑定后：打开微信并登录机器人账号，双击 `ZhBot.exe`，等待 `READY`。关闭管理窗口后后台继续运行；停止时点击“正常停止”，或执行：

```powershell
.\scripts\start.ps1
.\.venv\Scripts\python.exe -m wechat_bot status --config runtime/config.bot.toml
.\scripts\stop.ps1
```

`start.ps1` 是 EXE 之外的启动方式，不需要在 EXE 启动后重复执行。`READY` 是接收连接状态，发送是否到达手机仍以手机观察为准。

在同一机器人上增加群：把机器人和主人加入目标群，打开 EXE“群聊接入”，生成登记码；主人在目标群通过微信成员选择器真实 @机器人发送 `登记群聊 十二位登记码`，5 分钟内本机刷新、核对候选并确认接入，正常重启至 READY。已有群会保留。群名没有可靠原生字段，窗口显示实际群 ID。

## 已有安装升级

先正常停止机器人，再更新同一项目目录中的代码和文档；保留 `.venv/`、`.python/`、`external/helper/`、`runtime/` 和现有配置。Git 安装执行 `git pull --ff-only`；ZIP 安装将包内文件覆盖到原目录，不更换运行数据位置。更新 Python 安装元数据：

```powershell
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

再打开同一个 `ZhBot.exe`。本版 EXE 界面代码没有变化，继续使用已有二进制。没有必要重装 helper 或重新登记已启用群。

升级前使用 SQLite backup API 保存一致备份，或正常停止后备份整个 `runtime`。本机本轮备份为 `runtime/backups/bot-before-v025-cleanup.sqlite3`。配置、媒体文件和数据库需一起保留；旧媒体元数据存在绝对路径，跨机器或跨目录迁移需要另外核对路径。

## 群内操作

普通群指令需通过微信成员选择器真实 @机器人。

| 功能 | 指令及行为 |
| --- | --- |
| zxj | `随机zxj`、`我的zxj`；每天每人一个结果，跨群共用当天额度；日期为 `YY.MM.DD` |
| Wordle | `猜词`、`猜词 3` 至 `猜词 10`、`我猜是apple`、`猜词棋盘`、`猜词战绩`；同群共享对局，次数为 `min(9, 5 + floor((长度 - 3) / 2))`，重启续局 |
| 表情 | `添加表情包` 后 30 秒内从微信表情面板发送原生表情；`随机表情包` 从本群公共池抽取；同一群的相同原件或发送副本不重复入库 |
| 帮助 | `帮助`；全部命令、权限和查询/删除语法以 [README 群指令](../README.md#群指令) 为准 |

EXE 可按群和成员查看 zxj 历史、猜中单词和上传表情，编辑 z/x/j 字库及 3～10 字母词库，本机添加/删除表情。新词库用于新局，当前局保留开局快照；删除表情移出本群池并保留文件。每个群的 Wordle 和表情池互相隔离，同群成员共享表情池。

静态 PNG/JPEG/WebP/BMP 生成最多 256 色 GIF，GIF 保留原件并在需要时缩放发送副本。原件门槛为 20 MiB、边长 8192、累计 128 Mi 像素；发送受固定上游 1 MiB、1024 边长、300 帧等限制。大 GIF 可能明显缩小；APNG、动画 WebP、WXGF 暂不支持。

## 文件职责与调用关系

```text
ZhBot.exe → launcher/control.py → wechat_bot.__main__ → Runtime
helper_native → 原生事件 → inbox → Router → zxj / Wordle / stickers
                                      └→ 同一事务保存业务结果与 outbox → 原生发送
ZhBot.exe → control.py admin → AdminService → dictionaries / StickerService / SQLite
```

| 文件 | 职责 |
| --- | --- |
| `launcher/` | 本机管理窗口、后台进程启停；同一入口读取更新后的 Python 代码 |
| `src/wechat_bot/config.py`、`groups.py` | 账号/主人/群配置，登记、白名单修改和生效核对 |
| `src/wechat_bot/runtime.py`、`store.py`、`router.py` | 持久收件、统一事务、命令、去重、有限重试和恢复 |
| `src/wechat_bot/adapters/helper_native.py` | 原生身份/@字段转换、文本/PNG/表情收发、固定构建校验和生命周期 |
| `src/wechat_bot/admin.py`、`dictionaries.py` | 本机记录查询、字库和词库维护 |
| `src/wechat_bot/stickers.py`、`sticker_media.py` | 原件保留、GIF 副本、摘要查重、群公共池 |
| `src/zxj/`、`src/wordle/` | 游戏规则、持久化、棋盘和独立 CLI |
| `src/wechat_reader/` | 保留的 UIA/OCR 诊断入口 |
| `scripts/install.ps1`、`package_release.py` | 安装与按明确文件范围构建发布包 |
| `tests/` | 合成事件/临时数据库回归，仅存在 Git 和源码发行包 |

默认运行数据位于 `runtime/`：`config.bot.toml` 是私密绑定配置；`bot.sqlite3` 保存游戏、词库、表情元数据、inbox/outbox；`media/stickers/` 保存发送 GIF，`originals/` 保存原件，`unprocessed/` 保存处理失败但已核验来源的原件；`media/wordle/` 保存棋盘；`logs/`、`backups/` 和本机验收记录继续保留。

## 上游与验收边界

helper 固定于 `Prometheus-first/helper` 提交 `3e65e4bdaff438dc616f32d412175842fa138763`，许可为 `LicenseRef-helper-noncommercial-1.0`，仅按其原协议允许的非商业范围使用。安装保留完整源码、`.git`、LICENSE、THIRD_PARTY_NOTICES、run_selftest、watchdog 和清理组件；不启动其默认插件。DLL 来自该固定提交，摘要保存在 `external/helper.lock.json`；尚未独立复现 DLL 构建。Python 依赖来源和许可见 [第三方声明](../THIRD_PARTY_NOTICES.md)。

现有记录已经覆盖两个实际群、真实成员身份、真实 @、文本/PNG/静态原生表情以及 Wordle 接力。新群登记、追加白名单和正常重启已实际完成；用户反馈“目前来看没有什么问题”。本轮没有因版本迭代另行探测或处理微信升级，保留原有启动核验。

本轮自动化、构建和运行复核结果见下节；模拟事件和安装检查不作为真机群消息验收。动画手机效果、跨重启表情发送以及锁屏/托盘/远控断开等条件未全部验证，具体历史证据见 [COMPATIBILITY](COMPATIBILITY.md)。

## v0.2.5 发布核对

- 全部保留测试：24 passed in 7.92s；覆盖身份/@、事务回滚、去重/重试/不确定恢复、多人游戏、媒体/查重、管理和群接入；`pip check` 无冲突
- C# 入口源码实际编译通过；根目录固定 EXE 二进制保持不变，无桥接 `--check` 返回 CHECKED，版本 0.2.5
- 新建目录解压后，Windows PowerShell 5.1 安装成功；Python 依赖安装、固定 helper 源码获取与 DLL 摘要核验、机器人及旧诊断 CLI 检查通过。配置保持空绑定，没有创建机器人数据库或启动桥接
- 真实后台通过正常停止/启动加载清理后的代码，重新达到 READY，两个群配置生效；核对时 77 条 inbox done / 81 条 outbox accepted，无待发项、无错误日志
- SQLite `quick_check=ok`，外键检查无错误；旧字库、表情、zxj、猜测及收发记录保留。备份后的活跃局因用户后续真实猜测在重启前结算为 won，没有将这次正常业务变化当作数据丢失
- 发布 ZIP 的文件清单检查排除了 runtime、私人配置、测试、虚拟环境及本机 Python；源文件与最终工作区逐一比对，SHA-256 清单随包提供

本轮没有要求重复发送原有功能测试消息。清理后的自动化通过和后台 READY 不扩大既往手机验收范围。

开发者可从 Git 工作区重建：先构建 wheel/sdist（本机使用 `uv build --python .venv\Scripts\python.exe --offline`），再运行 `.\.venv\Scripts\python.exe scripts/package_release.py`。打包仅选取 Git 已跟踪的明确生产/文档路径；新增文件需先暂存。EXE 源码有改动时，先执行 `scripts/build_launcher.ps1`，关闭旧管理窗口后替换入口。
