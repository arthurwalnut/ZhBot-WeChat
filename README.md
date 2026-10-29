# Astra WeChat Lab v0.1.0

三个独立 Python 包。`zxj`、`wordle` 已实现并通过核心测试；`wechat_reader` 已在微信 4.1.15.13 实测**私聊可见区域文本读取**，包括连续相同文本。群聊按用户安排留待后续验证，仍未完成；整个 v0.1.0 尚未达到任务书的完整验收条件。

原始实施依据保留在 `ASTRA_WECHAT_V0_1_0_PLAN.md`，未修改原文。没有微信回复、游戏微信触发、大模型、表情包或私人助手入口。

## 安装与入口

在 PowerShell 中进入本项目根目录。现有 `.venv` 可直接使用，无需激活或更改执行策略。

本机初始没有 `py` 注册的 3.12，实际使用已有 `uv` 建立项目内 Python：

```powershell
$env:UV_PYTHON_INSTALL_DIR = Join-Path (Get-Location) '.python'
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.cache\uv'
uv python install 3.12
uv venv --python 3.12 --seed .venv
.\.venv\Scripts\python.exe -m pip install -c requirements-lock.txt -e ".[dev,reader]"
```

已安装 Python 3.12 的其他电脑也可先 `py -3.12 -m venv .venv`。仅玩游戏可安装 `-e .`，不加载 Windows 自动化依赖。`.python` 是本项目虚拟环境使用的解释器，请和 `.venv` 一并保留。

```powershell
.\.venv\Scripts\python.exe -m zxj --help
.\.venv\Scripts\python.exe -m wordle --help
.\.venv\Scripts\python.exe -m wechat_reader --help
```

## 随机 zxj

```powershell
.\.venv\Scripts\python.exe -m zxj draw --user alice
.\.venv\Scripts\python.exe -m zxj draw --user bob
.\.venv\Scripts\python.exe -m zxj history --user alice
.\.venv\Scripts\python.exe -m zxj history --user alice --limit 10
```

每人按北京时间每日一次，同日返回数据库原结果；重启后历史保留。每天可随机得到相同字符串。服务支持可控时间用于测试，CLI 使用真实时间。

## Wordle

```powershell
.\.venv\Scripts\python.exe -m wordle start --group demo --user alice --length 5
.\.venv\Scripts\python.exe -m wordle guess --group demo --user bob alley
.\.venv\Scripts\python.exe -m wordle guess --group demo --user carol apple
.\.venv\Scripts\python.exe -m wordle board --group demo
.\.venv\Scripts\python.exe -m wordle stats --user bob
.\.venv\Scripts\python.exe -m wordle end --group demo --user alice
# 历史棋盘：把 1 换成该群的实际对局编号
.\.venv\Scripts\python.exe -m wordle board --group demo --game 1
```

每群同时一局，玩家共用六次有效猜测。非法、词库未收录和重复猜测不扣次数；首次猜中者获一次胜场。`end` 由开局者操作；已结束的局不重复结算。答案池 609 词，允许猜测 626 词，**当前只有长度 5 可用**；添加本地答案词后才开放对应的 3–10 长度。

上述猜测是操作示例，随机答案不固定；若猜中后再执行 `end`，会明确提示已结束。活跃局的 CLI 和 PNG 不显示答案；SQLite 保存答案供判色和重建棋盘，是本地游戏存储。

## 微信当前状态与运行条件

| 实际版本 / 日期 | 后端 | 群聊 | 私聊 | 已观察条件与限制 |
| --- | --- | --- | --- | --- |
| 4.1.15.13 / 2026-10-29 | Windows UIA / pywinauto 0.6.9，`uia-visible` | 未实测，未完成；本轮推迟 | 可见区域文本与连续同文增量已实测 | 窗口保持未最小化、目标会话打开；视口变化会中断观察；发送者显示名、原生消息/发送者 ID、原生发送时间缺失 |

本次实际读取了 `mmui::RecyclerListView`（`chat_message_list`）的直接 `ListItem` 子项；文本来自 `mmui::ChatTextItemView.name`。`mmui::ChatTitleBarChatSingleView` 提供了私聊类型的界面证据。该消息列表未暴露 ScrollPattern，因此实现仅读取与列表视口相交的消息行，不判断是否已处于历史底部。

```powershell
.\.venv\Scripts\python.exe -m wechat_reader doctor
# 先手工恢复微信，打开允许读取的目标私聊，再明确选择窗口和会话
.\.venv\Scripts\python.exe -m wechat_reader select --config runtime/config.private.toml --expected-type private
.\.venv\Scripts\python.exe -m wechat_reader watch --config runtime/config.private.toml
# 本机 2026-10-29 已保存的选择；窗口/进程重建后需重新 select
.\.venv\Scripts\python.exe -m wechat_reader watch --config runtime/config.private-20261029.toml
```

`doctor` 默认把不含消息正文的诊断写入 `runtime/doctor.json`，包括实际版本、依赖、候选窗口。检测失败时 `--reported-version 版本号` 单独保存人工记录，不替代实际检测。`select` 必须明确选择窗口，即使只有一个也不自动默认选择；随后读取并确认实际会话标题，自动填入已观察到的控件规则。`expected_type` 仅保存用户预期，实际事件的 `detected_chat_type` 由界面结构独立探测；当前识别私聊为 `private`，其他结构为 `null`。

日常运行时，手工滚到目标会话的最新消息，保持微信未最小化，并避免移动、缩放窗口或滚动消息区域。开始观察后，由用户或测试伙伴发送消息；初始快照只建立基线。`watch` 不调用切换聊天、焦点、滚动、剪贴板或发送接口。微信更新可正常进行，本项目不修改客户端或更新设置；更新后重新运行 `doctor/select`，按实际界面验证。

有序差分保留同文的出现次数。共同消息行的坐标变化、旧行移出视口、快照缺失或无法完整对齐时，返回 `gap`，清除旧基线；下一次成功快照仅重新建立基线，**期间的消息可能漏读，不补收历史**。新消息使窗口自动滚动或列表视口填满时，同样可能触发此限制；当前实现不能提供连续完整消息流。

空视口随后首次出现内容时，无法区分初始加载与新消息，这批内容仅用于重新建立基线，可能不输出首条到达的消息。无法匹配正文的可见行以 `message_type="unknown"`、`text=null` 记录，不解释为已识别的文本消息。

每次读取前后核对窗口/进程绑定和会话；绑定或标题变化时停止，不转向另一个会话。每次 UIA 查询限时 12 秒，超时仅结束本项目的查询子进程。已实测切换到文件传输助手后因标题不符退出；窗口最小化时读取也明确退出。账号切换、同名会话、多账号共存、其他窗口遮挡、同时观察群私聊尚未实测；账号切换后需停止并重新选择。

发送者显示名、原生发送者 ID、原生消息 ID、原生发送时间均为 `null`；`observed_at` 是程序观察时间。本地账号/会话别名、HWND、UIA runtime ID 和本地 `event_id` 均不作为原生微信身份。默认只在终端输出；只有传入 `watch --jsonl runtime/observations.jsonl` 才保存观察记录。Ctrl+C 退出。

如果后续客户端的控件变化，可用以下命令保存所选窗口的实际 UIA 文字。用 `doctor` 返回的当前句柄替换占位值；文件可能包含聊天内容，保存在被 Git 忽略的 `runtime/`。

```powershell
.\.venv\Scripts\python.exe -m wechat_reader doctor --hwnd <实际HWND> --include-text --output runtime/private-uia.json
```

定位属性集中在 `profiles.py`；`title/messages` 须唯一，`row` 匹配列表直接子项，`text` 匹配行自身或行内正文。本轮群聊验证按用户安排推迟，尚无群聊兼容结论。

## 文件职责和数据位置

| 调用路径 | 职责 |
| --- | --- |
| `zxj/__main__.py → service.py → zxj.sqlite3` | 参数/输出；北京时间与抽取事务、历史；`characters.json` 维护三组单字 |
| `wordle/__main__.py → game.py → store.py → wordle.sqlite3` | 参数/输出；校验、判色、状态；SQL 事务及胜场统计；`words.json` 维护离线词库 |
| `wordle/__main__.py → render.py → PNG` | 只读取棋盘状态绘图，不改变游戏或战绩 |
| `wechat_reader/__main__.py → backend.py/profiles.py → reader.py` | 命令/配置；真实 UIA 与定位规则；快照差分和观察字段；不调用小游戏 |

两个游戏都支持 `--data-dir 路径`，放在子命令前后均可。默认相对**运行时当前目录**的 `runtime/`，启动会显示解析后的绝对路径；从本项目根运行时：

- `runtime/zxj.sqlite3`：每日抽取与历史。
- `runtime/wordle.sqlite3`：对局、参与玩家、UTC 时间、猜测和胜场来源。
- `runtime/boards/wordle-<对局>-<次数>-<状态>.png`：每次有效操作/重绘的棋盘，不自动弹窗。
- `runtime/config.private-20261029.toml`：本次私聊选择与实际控件规则；仅供本机使用，绑定失效后重新选择。
- `runtime/config*.toml`、`runtime/doctor*.json`：本机定位与诊断；群/私聊可使用分别命名的配置。
- `runtime/stage-b-check/zxj.sqlite3` 与 `runtime/wordle.sqlite3` 中的 `validation-wordle`：本轮实际运行记录，已保留。Wordle 验证局已由开局者结束。

这些数据、Python 环境与缓存均不进入 Git。输出重定向到工具管道若出现编码问题，可在当前 PowerShell 设置 `$env:PYTHONIOENCODING='utf-8'`，不改变系统设置。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

2026-10-29：`4 passed`。保留原三个核心场景：zxj 日期/独立用户/持久化；Wordle 重复字母判色；Wordle 多人状态/重启/六次失败。针对本次视口变化问题补一个最小接收回归：同文追加、坐标变化、旧行丢失与恢复时重新建立基线。自动化使用临时数据库与人工快照，不修改运行记录。

人工检查记录：

- 2026-10-29 私聊：初始快照读到 `接受测试A-1029`；实时 `watch` 收到 `重复测试b-1029` 一条、`重复测试C_1029` 两条，后两条具有不同本地事件 ID。最终重启先建立基线、未重放历史，随后读到 `最终验证D-1029` 和一条 `unknown` 行；`--once` 基线检查通过。切换会话及最小化停止已观察。群聊本轮推迟，未完成。
- 2026-10-25 PNG：已打开正常对局图片，六行、字母、颜色与边界无裁切。

2026-10-25 的安装验证记录：`pip check` 未发现依赖冲突，三个入口帮助可运行，wheel 构建成功且包含 JSON 资源。本轮未新增依赖；第三方来源与许可见 `THIRD_PARTY_NOTICES.md`。私聊受限读取已实测，原任务书要求的全版完成条件仍未满足。
