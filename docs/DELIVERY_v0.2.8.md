# ZhBot v0.2.8：Windows 部署与迁移

本版整理路径和环境依赖，保留固定 `ZhBot.exe`、群指令、Wordle 词库、数据库内容及原生桥接版本。发布包包含应用源码、入口、安装脚本、wheel、配置示例、许可与文档；真实 `runtime/`、Python 环境和 helper 工作树不进入公开发布包。

## Windows 条件与证据

| 目标 | 已核对内容 | 尚未完成 |
| --- | --- | --- |
| 本机 Windows 桌面 x64 | NT build 26100、交互 Session 1、.NET Release 533320；迁移/安装/启动前检查与离线整合测试 | 本次未重新加载桥接或发送群消息；沿用既有验收记录 |
| Windows Server 2022 Desktop Experience x64 | 官方 .NET 4.8 预装说明；桌面类型、系统版本、框架与会话预检分支 | 没有该系统真机，登录、桥接收发、PNG、原生表情、托盘及 RDP 条件均待实际验收 |
| Windows Server 2025 Desktop Experience x64 | 官方 .NET 4.8.1 预装说明；同上预检分支 | 同上 |
| Server Core / Nano、Session 0 服务 | 代码拒绝此部署方式 | 不作为可部署目标 |

安装使用 PowerShell 5.1+、Python 3.12 x64、Git、.NET Framework 4.8 或后续 4.x，不依赖 PowerShell 7 或 winget。Microsoft 说明 Server 的 Desktop Experience 提供标准桌面，而 Core 不安装标准图形界面；服务运行会话与用户桌面分离。依据：[Server 安装选项](https://learn.microsoft.com/en-us/windows-server/get-started/install-options-server-core-desktop-experience)、[.NET 系统要求](https://learn.microsoft.com/en-us/dotnet/framework/get-started/system-requirements)、[服务交互限制](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services)。

未取得微信对 Server 2022/2025 的官方支持声明，也没有这两个系统的真机访问，因此不能确认整套机器人已在它们上运行通过。依赖匹配和测试中构造的系统信息不等于真机兼容认证。旧 Windows、ARM64、无桌面环境也不据此扩展为支持目标。

## 原有目录更新

正常停止机器人并退出托盘管理器后，在项目根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe launcher\control.py check
```

检查通过后打开 `ZhBot.exe`。如果项目位置和数据目录没有改变，无需执行 `relocate`。安装脚本保留已有配置与数据；固定入口读取更新后的项目代码。

## 迁移到另一目录或电脑

1. 在原电脑托盘菜单选择「退出程序」，等待正常退出，确认后台 `STOPPED`。CLI 可使用 `.\.venv\Scripts\python.exe launcher\control.py shutdown`；随后关闭管理器。复制完成后原电脑保持停止，目标机器使用同一机器人账号
2. 复制完整应用和**完整数据目录**，包括 `bot.sqlite3`、媒体发送副本、`media/stickers/originals/`、失败原件、配置、备份和验收记录。默认是整个 `runtime/`；自定义 `data_dir` 时另行复制该整个目录。不要只复制 EXE 或运行中的 SQLite 主文件
3. 在目标系统安装 Python 3.12 x64、Git 和上述桌面依赖。把项目放在目标用户可写的本地短路径，例如 `C:\Bots\ZhBot`。此路径仅为示例；中文和空格路径已做本机迁移测试。目标用户需要有读写整个项目、数据和 helper 目录的权限
4. 从目标项目根目录执行下方命令。复制的虚拟环境应重建，即便新旧电脑的项目绝对路径相同；Python 官方也要求在移动后重建 [venv](https://docs.python.org/3.12/library/venv.html)。安装脚本先检查目标机解释器、检查项目环境和管理器未被占用，再把旧环境移至 `.venv.backup-*` 保留

```powershell
$TargetPython = Read-Host '目标机 Python 3.12 x64 的 python.exe 完整路径'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -PythonPath $TargetPython -RecreateEnvironment
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m wechat_bot relocate --config runtime/config.bot.toml --data-dir runtime --helper-root external/helper
```

自定义数据目录时，将 `--data-dir` 改为**目标机实际副本**路径；CLI 相对参数从当前工作目录解析，所以以上命令在项目根目录执行。配置内的 `data_dir`、`helper_root` 相对 TOML 所在目录解析；同盘写为相对路径，跨盘路径保留明确绝对路径。

`relocate` 核对数据库账号、SQLite 完整性、所有表情及已有原件的文件/大小/摘要，取得目标目录单实例锁后才更新配置。旧 `status.json`、`launcher-start.json`、`stop.request` 移入 `backups/relocate-*`，旧微信 PID 清空；输出 `REBIND_REQUIRED`。数据库不改写，群、主人、历史和待发状态保留。校验失败时补全正确副本再执行；配置写入失败时旧状态归档仍保留，可修复目录权限/空间后重试。

5. 在目标 Windows 用户的交互桌面打开微信，扫码及手机确认后登录**同一机器人账号**，重新选择真实 PID；旧进程编号不能迁移使用

```powershell
Get-Process Weixin | Select-Object Id, Path, SessionId, StartTime
[int]$RobotPid = Read-Host '目标机器上机器人微信的 PID'
.\.venv\Scripts\python.exe -m wechat_bot doctor --config runtime/config.bot.toml --pid $RobotPid
$RobotAccount = Read-Host 'doctor 输出且已确认的同一机器人 account_id'
.\.venv\Scripts\python.exe -m wechat_bot bind --config runtime/config.bot.toml --pid $RobotPid --account $RobotAccount
.\.venv\Scripts\python.exe launcher\control.py check
```

这里省略 `--group`、`--owner`，保留迁移前群白名单与主人。`doctor`/普通 `bind` 核对进程和账号，不加载桥接；`ZhBot.exe` 的正常启动才连接微信。原有构建校验继续执行，按项目约定不主动处理微信自动更新。

6. 打开 `ZhBot.exe`，等待 `READY`，在允许群真实 @ 测试文字、棋盘 PNG 与原生表情。Server 还需单独核对托盘、锁屏和 RDP 断开/重连，未经测试的后台条件保持待验收
7. 如原先使用登录计划任务，在目标机器对应用户下重新执行 `scripts/register_task.ps1`。Windows 任务保存解析后的绝对路径与用户，项目换路径后也需重建任务。它在已登录用户会话运行，不作为 Session 0 服务；实际微信登录仍需完成

下载需代理时，可仅给当前 PowerShell 设置 `HTTP_PROXY` / `HTTPS_PROXY`，例如本机代理 `http://127.0.0.1:7897`；其他机器填写自己的代理地址，不将本机端口写成项目默认依赖。安装失败时旧环境备份和数据保留；网络恢复后重试。旧环境备份的删除由拥有者在验收后决定。

## 路径处理与文件职责

| 文件 | 职责 |
| --- | --- |
| `launcher/Launcher.cs` / `ZhBot.exe` | 从 EXE 所在目录定位控制脚本与 Python；入口二进制沿用原版 |
| `launcher/environment.py` | 隔离 Python 检查当前解释器、editable 源码路径及安装目录标记，拒绝误用另一目录的代码 |
| `scripts/windows_environment.ps1` / `src/wechat_bot/platform_check.py` | 脚本和 Python 的 Windows 桌面、框架、架构、会话预检；不加载桥接 |
| `scripts/install.ps1` | 验证基础 Python、备份并重建迁移环境、安装锁定依赖和固定 helper |
| `config.py` / `relocation.py` | 相对配置写入及复制数据审计、旧进程状态归档、重新绑定要求 |
| `stickers.py` | 媒体相对键和历史绝对路径映射；发送副本与原件校验 |
| `admin.py` / `runtime.py` | 管理预览与待发项使用新目录资源；业务重试沿用持久结果 |
| `wordle/render.py` / `wechat_reader/ocr.py` | 从 `WINDIR` / `SystemRoot` 定位系统字体和诊断 PowerShell；字体缺失使用 Pillow 默认字体 |

调用关系：EXE → 本项目 `.venv` / `launcher/control.py` → 环境检查 → 现有 `wechat_bot run` → 固定 helper。原生发送接口需要的绝对文件路径在发送时从当前数据目录生成；Windows 进程镜像路径与计划任务路径也保留运行时绝对形式。源码已扫描，不再含开发机盘符、用户名或固定 `C:\Windows`。

旧表情数据行不批量改写：完整 `media/stickers/<摘要>.gif` 或原件后缀必须匹配，文件从当前数据目录读取并校验。新记录保存相对键。迁移不重新抽取随机结果、不重扣次数、不重新计战绩；重启后的 `sending` 仍转为 `uncertain`，不盲目重发。棋盘按数据库快照在当前目录重新生成。

固定 helper 仍是 `3e65e4bdaff438dc616f32d412175842fa138763`，保留 `.git`、许可与生命周期组件，见 [第三方声明](../THIRD_PARTY_NOTICES.md)。它的原生请求报告路径使用 260 个 WCHAR 的边界，本版加载前检查完整报告路径；启用 Windows 长路径不能移除此原生限制。上游表情路径另有 1023 UTF-8 字节限制，目标项目和数据目录宜使用短本地路径。OCR 仅为可选诊断，Server 的 WinRT OCR/语言资源没有在本轮真机验证。

## 本轮验证与数据

本机机器人在本轮开始时已停止，本版保留该状态，没有加载桥接或重新进行群收发。升级前一致性备份位于 `runtime/backups/bot-before-v028.sqlite3`。

40 项自动化测试通过（215.43 秒），包括旧媒体/原件在新目录解析、待发项与不确定发送、中文空格路径、配置迁移、旧进程归档、安装环境检查及原功能回归。最后安装脚本修改后的 2 项相关测试复测通过（18.86 秒）。Server 预检使用构造信息覆盖分支，不计为 Server 真机验收。

实际运行库的隔离副本迁至中文/空格新目录，28 条表情发送文件、26 份已有原件校验通过；复制数据库与备份字节一致，旧 PID 清空、状态文件归档。当前配置路径已规范化，账号、主人、群及数据保持原值。后续安装与构建检查见 [兼容记录](COMPATIBILITY.md)。

独立中文/空格目录通过 Windows PowerShell 5.1 首次完整安装，从其他工作目录执行成功，完成虚拟环境、锁定依赖、固定 helper 获取、DLL/许可核验及模板配置生成。上游默认分支已不包含固定 SHA，首次获取增加显式 fetch 该 SHA 后通过；不改变锁定版本。固定 `ZhBot.exe --check` 返回 `CHECKED` / 0.2.8，wheel/sdist 构建通过。本机安装测试没有加载桥接，也不计为 Server 真机验收。
