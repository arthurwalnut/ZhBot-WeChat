# Astra WeChat Lab v0.1.0

三个独立 Python 包。`zxj`、`wordle` 已实现并通过核心测试；`wechat_reader` 已完成本机诊断与观察代码，**消息定位规则和真实群聊/私聊接收未完成**。整个 v0.1.0 尚未达到任务书的完整验收条件。

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

## 微信当前状态与后续人工检查

| 实际版本 / 日期 | 后端 | 群聊 | 私聊 | 已观察条件与限制 |
| --- | --- | --- | --- | --- |
| 4.1.15.13 / 2026-10-25 | Windows UIA / pywinauto 0.6.9 | 未实测，未完成 | 未实测，未完成 | 实际文件版本、窗口、进程启动时间和 UIA 结构已读取；窗口最小化，聊天页为空；未采集消息正文 |

检测到 UIA `mmui::MainWindow`、`MainView`、`ChatPage` 和会话列表。它们仅证明窗口/界面可探测。当前未配置消息定位规则，`watch` 会明确停止。微信更新继续正常使用；本项目不修改客户端或更新设置。未来版本需重新探测。

```powershell
.\.venv\Scripts\python.exe -m wechat_reader doctor
.\.venv\Scripts\python.exe -m wechat_reader select --config runtime/config.local.toml
.\.venv\Scripts\python.exe -m wechat_reader watch --config runtime/config.local.toml
```

`doctor` 默认把不含正文的诊断写入 `runtime/doctor.json`，包括实际版本、依赖、候选窗口。检测失败时 `--reported-version 版本号` 单独保存人工记录，不替代实际检测。`select` 必须明确选择窗口，即使只有一个也不自动默认选择；它保存本地别名、用户提供的预期类型和会话标题，**这些都不是原生微信 ID 或已识别的账号身份**。

后续继续适配的具体步骤：

1. 手工恢复拟用于测试的微信，登录目标账号，打开允许读取的私聊；再运行 `doctor` 取得当前 HWND。
2. 运行以下诊断，用实际数字替换占位值。该命令明确把所选窗口的 UIA 文字保存到本地，可能包含聊天内容；文件留在被 Git 忽略的 `runtime/`。

   ```powershell
   .\.venv\Scripts\python.exe -m wechat_reader doctor --hwnd <实际HWND> --include-text --output runtime/private-uia.json
   ```

3. 依据真实树完成 `config.local.toml` 的 `selectors.title/messages/row/text`；属性只支持 `control_type/class_name/automation_id/name`。标题与消息容器须唯一；行是列表的直接子项，正文在行内。当前没有经实测可直接复制的消息选择器。若真实控件结构不符合此读法，继续修改 `profiles.py/backend.py`，不能用猜测值蒙混通过。
4. 建立基线后，由用户或测试伙伴手工发私聊文本和连续两条相同文本，核对来源、正文及新增事件。再为群聊单独保存配置，重复检查。切换私人窗口时检查绑定仍指向选定窗口；切换会话、关闭或重建窗口时观察是否暂停。

观察过程不调用切换聊天、焦点、滚动、剪贴板和发送接口。每次读取核对 HWND、PID、进程启动时间、路径、窗口类和版本；绑定变化停止，重新 `select`。消息列表需要暴露 UIA ScrollPattern 且位于底部；不满足会停止，需要后续真实控件核查。每次 UIA 调用限时 12 秒，仅结束本项目的查询子进程。

初始快照仅建立基线。有序差分保留同文的出现次数；无法对齐时报告 `gap` 并重建基线，不补报历史。UIA runtime ID 只作为当次行定位线索。账号切换、同名会话及部分历史滚动尚无可靠识别证据；使用时需停留在已选择的会话最新位置，切换账号后停止并重新选择。**多账号共存、遮挡读取、同时群私聊、重复同文增量都尚未人工验证。**

实际会话类型、发送者显示名、原生账号/群/消息 ID、原生发送时间均保留 `null`，不从本地别名、昵称或观察时间推算。默认只在终端输出；只有传入 `watch --jsonl runtime/observations.jsonl` 才保存观察记录。Ctrl+C 退出。

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
- `runtime/config.local.toml`、`runtime/doctor*.json`：本机定位与诊断；群/私聊可使用分别命名的配置。
- `runtime/stage-b-check/zxj.sqlite3` 与 `runtime/wordle.sqlite3` 中的 `validation-wordle`：本轮实际运行记录，已保留。Wordle 验证局已由开局者结束。

这些数据、Python 环境与缓存均不进入 Git。输出重定向到工具管道若出现编码问题，可在当前 PowerShell 设置 `$env:PYTHONIOENCODING='utf-8'`，不改变系统设置。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

保留三个自动化场景：zxj 日期/独立用户/持久化；Wordle 重复字母判色；Wordle 多人状态/重启/六次失败。测试用临时数据库与固定时间/答案，不修改运行记录。

人工 PNG 检查已完成：六行、字母、颜色与边界无裁切。人工微信检查按用户选择推迟，未完成。原任务书要求的全版完成条件尚未满足。
