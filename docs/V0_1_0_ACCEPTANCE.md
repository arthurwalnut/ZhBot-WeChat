# Astra WeChat Lab v0.1.0

**v0.1.0 已在本机按用户接受的可见区域读取与 OCR 限制完成本轮验收。** 三个 Python 包独立运行：`zxj`、`wordle` 已通过核心测试；`wechat_reader` 在微信 4.1.15.13 读出真实私聊与群聊正文，并在可见快照中保留两位成员的相同正文及受限 OCR 标签。视口变化会产生 `gap`，群聊本轮证据包含重新建立基线后的 `snapshot`，不承诺连续完整的 `new` 事件或漏读补收。

实施依据为 `ASTRA_WECHAT_V0_1_0_PLAN.md`。2026-10-29 按用户授权调整为机器人号在专用服务器或旧电脑登录，移除同机双账号共存验收；读取仍需可用的 Windows 桌面和明确的目标窗口绑定。没有微信回复、游戏微信触发、大模型、表情包或私人助手入口。

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
| 4.1.15.13 / 2026-10-29 | 私聊 `uia-visible`；群聊 `uia-visible+windows-ocr` | UIA 正文、两位成员同文快照与受限 OCR 标签已实测；滚动、遮挡停止、重启重新选择通过 | 可见区域文本与连续同文增量已实测 | 窗口保持未最小化、目标会话打开；群聊截图区域无遮挡，深色主题、150% 显示缩放；视口变化会中断增量观察 |

正文直接来自 `mmui::RecyclerListView`（`chat_message_list`）中 `ListItem` 的 `mmui::ChatTextItemView.name`；私聊与群聊类型分别由 `mmui::ChatTitleBarChatSingleView`、`mmui::ChatTitleBarChatRoomView` 识别。该消息列表未暴露 ScrollPattern，因此实现仅读取与列表视口相交的消息行，不判断是否已处于历史底部。

群消息的发送者标签未通过本次 UIA、Legacy 接口或原始子节点检查获得。群聊读取在 UIA 正文之外，用系统 Windows OCR 识别行上方的显示标签，保留原始识别字符串并设置 `sender_display_name_source="windows-ocr"`。两位测试成员的标签可作本轮受限区分，其中带特殊符号的标签存在识别错误；同一成员的标签在不同快照中出现 `.` 与 `•` 两种原始输出，识别结果不稳定。用户已明确接受“接受本轮两位成员的受限区分，保留OCR限制”；这项验收只覆盖本轮两位成员，标签有误字、同名及改名歧义，不提供稳定身份映射。

```powershell
.\.venv\Scripts\python.exe -m wechat_reader doctor
# 先手工恢复微信，打开允许读取的目标私聊，再明确选择窗口和会话
.\.venv\Scripts\python.exe -m wechat_reader select --config runtime/config.private.toml --expected-type private
.\.venv\Scripts\python.exe -m wechat_reader watch --config runtime/config.private.toml
# 手工打开目标群后选择；按需显示初始/间断时的可见快照
.\.venv\Scripts\python.exe -m wechat_reader select --config runtime/config.group.toml --expected-type group
.\.venv\Scripts\python.exe -m wechat_reader watch --config runtime/config.group.toml --show-snapshots
# 本机 2026-10-29 微信完整重启后重新选择的群配置
.\.venv\Scripts\python.exe -m wechat_reader watch --config runtime/config.zhbot.local.toml --show-snapshots
```

`doctor` 默认把不含消息正文的诊断写入 `runtime/doctor.json`，包括实际版本、依赖、候选窗口。检测失败时 `--reported-version 版本号` 单独保存人工记录，不替代实际检测。`select` 必须明确选择窗口，即使只有一个也不自动默认选择；随后读取并确认实际会话标题，自动填入已观察到的控件规则。`expected_type` 仅保存用户预期，实际事件的 `detected_chat_type` 由界面结构独立探测：`private`、`group`，无法唯一判断时为 `null`。

日常运行时，手工滚到目标会话的最新消息，保持微信未最小化，并避免移动、缩放窗口或滚动消息区域。开始观察后，由用户或测试伙伴发送消息；初始快照只建立基线。`watch` 不调用切换聊天、焦点、滚动、剪贴板或发送接口。微信更新可正常进行，本项目不修改客户端或更新设置；未来版本兼容性尚未验证，更新后重新运行 `doctor/select`，按实际界面验证。

群聊 OCR 需要消息区域未被其他窗口遮挡。后台窗口截图在本次探测中得到黑图，当前实现只截取屏幕上所选消息区域；已实测浏览器遮挡消息区域后明确退出，提示移开遮挡窗口。适配基于本次深色主题和 150% 显示缩放，其他主题/显示缩放组合尚未验收。私聊沿用 UIA 读取，不调用 OCR。OCR 在本机内存中处理，不上传图片，正常生产路径不保存截图。

UIA 正文读取和截图并非同时发生，两者之间滚动可能导致正文与 OCR 标签错配。代码已增加截图前后的消息行签名、视口与会话检查：检测到变化时丢弃本次内容，报告 `gap` 后重新建立基线。这条处理路径的最小回归已通过。

有序差分保留同文的出现次数。共同消息行的坐标变化、旧行移出视口、快照缺失或无法完整对齐时，返回 `gap`，清除旧基线；下一次成功快照仅重新建立基线，**期间的消息可能漏读，不补收历史**。新消息使窗口自动滚动或列表视口填满时，同样可能触发此限制；当前实现不能提供连续完整消息流。

空视口随后首次出现内容时，无法区分初始加载与新消息，这批内容仅用于重新建立基线，可能不输出首条到达的消息。无法匹配正文的可见行以 `message_type="unknown"`、`text=null` 记录，不解释为已识别的文本消息。

`--show-snapshots` 在 `baseline/gap` 时额外输出当前可见行，明确标记 `observation_kind="snapshot"`；只有有序追加事件标记为 `"new"`。快照可能重复显示历史行并生成新的本地事件 ID，滚动快照不表示新消息，也不表示补齐漏读。

本轮群聊运行中，手工上滚再回到底部各触发一次 `gap → baseline`，只显示 `snapshot`，没有产生 `new` 事件。新群消息与视口滚动检查也实际触发截图前后行/视口变化：本次内容被丢弃，随后在基线快照中读到新正文。这次检查同样没有产生 `new` 事件。

每次读取前后核对窗口/进程绑定和会话；绑定或标题变化时停止，不转向另一个会话。每次查询限时 12 秒，超时仅结束本项目的查询子进程。已实测切换到文件传输助手后因标题不符退出；窗口最小化时读取也明确退出。账号切换、同名会话、同时观察群私聊尚未实测；账号切换后需停止并重新选择。同机双账号共存已从验收中移除，不执行相关测试。

已实测微信完整退出时，正在运行的观察进程报“窗口已关闭，请重新 select”并退出；重启后沿用旧配置也明确失败。`doctor` 读到新的窗口句柄、进程和启动时间，版本仍为 4.1.15.13；已重新 `select` 保存 `runtime/config.zhbot.local.toml`，新观察进程成功建立 `baseline`。后续客户端退出、重启或绑定变化时，都需重新选择当前目标窗口。

私聊发送者显示名仍为 `null`；群聊单行未取得标签时也为空，OCR 执行失败则停止读取并报告原因。原生发送者 ID、原生消息 ID、原生发送时间均为 `null`；`observed_at` 是程序观察时间。本地账号/会话别名、OCR 标签、HWND、UIA runtime ID 和本地 `event_id` 均不作为原生微信身份。默认只在终端输出；只有传入 `watch --jsonl runtime/observations.jsonl` 才保存观察记录，其中也会保留已启用的 `snapshot/new` 区分。Ctrl+C 退出。

如果后续客户端的控件变化，可用以下命令保存所选窗口的实际 UIA 文字。用 `doctor` 返回的当前句柄替换占位值；文件可能包含聊天内容，保存在被 Git 忽略的 `runtime/`。

```powershell
.\.venv\Scripts\python.exe -m wechat_reader doctor --hwnd <实际HWND> --include-text --output runtime/private-uia.json
```

定位属性集中在 `profiles.py`；`title/messages` 须唯一，`row` 匹配列表直接子项，`text` 匹配行自身或行内正文。群聊 OCR 标签截取在 `ocr.py`，保持与游戏业务分离。

## 文件职责和数据位置

| 调用路径 | 职责 |
| --- | --- |
| `zxj/__main__.py → service.py → zxj.sqlite3` | 参数/输出；北京时间与抽取事务、历史；`characters.json` 维护三组单字 |
| `wordle/__main__.py → game.py → store.py → wordle.sqlite3` | 参数/输出；校验、判色、状态；SQL 事务及胜场统计；`words.json` 维护离线词库 |
| `wordle/__main__.py → render.py → PNG` | 只读取棋盘状态绘图，不改变游戏或战绩 |
| `wechat_reader/__main__.py → backend.py/profiles.py → reader.py` | 命令/配置；真实 UIA 与定位规则；快照差分和观察字段；不调用小游戏 |
| `wechat_reader/backend.py → ocr.py → windows_ocr.ps1` | 群聊所选区域截图；标签裁剪和原始识别结果；调用本机 Windows OCR，图像只在内存中传递 |

两个游戏都支持 `--data-dir 路径`，放在子命令前后均可。默认相对**运行时当前目录**的 `runtime/`，启动会显示解析后的绝对路径；从本项目根运行时：

- `runtime/zxj.sqlite3`：每日抽取与历史。
- `runtime/wordle.sqlite3`：对局、参与玩家、UTC 时间、猜测和胜场来源。
- `runtime/boards/wordle-<对局>-<次数>-<状态>.png`：每次有效操作/重绘的棋盘，不自动弹窗。
- `runtime/config.zhbot.local.toml`：本次客户端完整重启后重新选择的群配置；仅供本机使用，绑定失效后重新选择。
- `runtime/config.private-20261029.toml`：保留的历史私聊配置；客户端重启后应重新 `select`。
- `runtime/config*.toml`、`runtime/doctor*.json`：本机定位与诊断；群/私聊可使用分别命名的配置。
- `runtime/group-visible-probe.png`：本轮保留的临时群聊探测画面，含聊天内容，不进入 Git；正常生产 OCR 路径不保存截图。
- `runtime/stage-b-check/zxj.sqlite3` 与 `runtime/wordle.sqlite3` 中的 `validation-wordle`：本轮实际运行记录，已保留。Wordle 验证局已由开局者结束。
- `dist/astra_wechat_lab-0.1.0-py3-none-any.whl`：保留的本轮构建产物，包含三个包与所需资源。

这些数据、Python 环境与缓存均不进入 Git。输出重定向到工具管道若出现编码问题，可在当前 PowerShell 设置 `$env:PYTHONIOENCODING='utf-8'`，不改变系统设置。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

2026-10-29 最终自动化检查：`5 passed in 0.18s`。保留原三个核心场景：zxj 日期/独立用户/持久化；Wordle 重复字母判色；Wordle 多人状态/重启/六次失败。另有两个最小接收回归：视口变化后的间断与重建基线，以及截图期间行移动/替换时丢弃内容。自动化使用临时数据库与人工快照，不修改运行记录。

人工检查记录：

- 2026-10-29 私聊：初始快照读到 `接受测试A-1029`；实时 `watch` 收到 `重复测试b-1029` 一条、`重复测试C_1029` 两条，后两条具有不同本地事件 ID。观察进程重启先建立基线、未重放历史，随后读到 `最终验证D-1029` 和一条 `unknown` 行；`--once` 基线检查通过。切换会话及最小化停止已观察。
- 2026-10-29 群聊：UIA 准确读出 `成员A-1029`、`成员B-1029` 两条不同正文；两位成员的不同 OCR 原始标签作受限区分已获用户接受，保留特殊符号识别错误。浏览器遮挡消息区域后明确停止。手工上滚和回到底部触发两次 `gap → baseline`，无 `new` 事件，仅输出可见快照。
- 2026-10-29 客户端完整重启：原观察进程及旧配置均因窗口关闭明确失败；`doctor` 确认新窗口/进程/启动时间，微信仍为 4.1.15.13；已重新选择目标群，保存本地配置并成功建立 `baseline`。
- 2026-10-29 最终群聊检查：`滚动验证S-1029` 到达期间触发截图前后行/视口变化，丢弃本次内容后，在 `baseline` 的 `snapshot` 中读到正文。随后两位成员各发 `同文验证H-1029`，可见快照同时保留两条相同正文和不同的 OCR 原始标签，下一次基线仍保留两条。这些检查出现 `gap → baseline`，共 0 条 `new` 事件；验收范围是可见快照的正文保留与本轮两成员受限区分。
- 2026-10-25 PNG：已打开正常对局图片，六行、字母、颜色与边界无裁切。

2026-10-25 的安装验证记录：`pip check` 未发现依赖冲突，三个入口帮助可运行。2026-10-29 最终 `uv build` 和 wheel 内容检查通过，包含最新截图一致性校验、`ocr.py`、`windows_ocr.ps1` 和游戏 JSON；构建中间目录已清理，运行数据保留。本轮增加对已安装 Windows OCR 的调用，未新增 Python 运行依赖；本机可用语言为 `en-US`、`zh-Hans-CN`、`de-DE`，当前标签识别使用 `en-US`。第三方来源与许可见 `THIRD_PARTY_NOTICES.md`。本轮验收已完成，无延期项；适用范围限于上述实际版本、界面条件与用户接受的 OCR 限制。
